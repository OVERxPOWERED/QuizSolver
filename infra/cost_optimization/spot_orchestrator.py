"""
Spot Instance Orchestrator for Quiz Batch Workloads.

Manages EC2 Spot Fleet requests, handles interruption notices,
and provides graceful workload migration to on-demand instances.
"""

import asyncio
import json
import logging
import os
import signal
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set
from uuid import uuid4

import boto3
import redis.asyncio as redis
from botocore.config import Config
from botocore.exceptions import ClientError, BotoCoreError

from core.quiz_runner import QuizRunner, QuizState, QuizCheckpoint

logger = logging.getLogger(__name__)


class InstanceType(str, Enum):
    """Supported instance types for spot fleet diversification."""
    C6I_XLARGE = "c6i.xlarge"
    C6A_XLARGE = "c6a.xlarge"
    C7G_XLARGE = "c7g.xlarge"


class AllocationStrategy(str, Enum):
    """Spot Fleet allocation strategies."""
    DIVERSIFIED = "diversified"
    LOWEST_PRICE = "lowestPrice"
    CAPACITY_OPTIMIZED = "capacityOptimized"
    CAPACITY_OPTIMIZED_PRIORITIZED = "capacityOptimizedPrioritized"


class FleetState(str, Enum):
    """Spot Fleet request states."""
    SUBMITTED = "submitted"
    ACTIVE = "active"
    MODIFYING = "modifying"
    DELETED = "deleted"
    DELETED_RUNNING = "deleted_running"
    DELETED_TERMINATING = "deleted_terminating"
    ERROR = "error"


@dataclass
class SpotFleetConfig:
    """Configuration for Spot Fleet request."""
    fleet_name: str
    target_capacity: int
    instance_types: List[InstanceType] = field(
        default_factory=lambda: [
            InstanceType.C6I_XLARGE,
            InstanceType.C6A_XLARGE,
            InstanceType.C7G_XLARGE,
        ]
    )
    allocation_strategy: AllocationStrategy = AllocationStrategy.CAPACITY_OPTIMIZED
    spot_price: Optional[str] = None  # None = use on-demand price as max
    availability_zones: List[str] = field(default_factory=list)
    subnet_ids: List[str] = field(default_factory=list)
    security_group_ids: List[str] = field(default_factory=list)
    iam_instance_profile_arn: Optional[str] = None
    key_name: Optional[str] = None
    user_data: Optional[str] = None
    tags: Dict[str, str] = field(default_factory=dict)
    termination_policy: str = "oldestInstance"
    load_balancers: List[str] = field(default_factory=list)
    target_groups: List[str] = field(default_factory=list)
    replace_unhealthy_instances: bool = True
    instance_interruption_behavior: str = "terminate"
    on_demand_percentage: float = 0.0
    on_demand_base_capacity: int = 0


@dataclass
class InterruptionNotice:
    """EC2 Spot Instance Interruption Notice."""
    instance_id: str
    instance_action: str  # terminate, stop, hibernate
    interruption_time: datetime
    notice_id: str


class SpotOrchestrator:
    """
    Orchestrates EC2 Spot Fleet for quiz batch workloads.
    
    Handles fleet creation, interruption monitoring, graceful draining,
    and migration to on-demand instances.
    """
    
    def __init__(
        self,
        config: SpotFleetConfig,
        redis_url: str = "redis://localhost:6379/0",
        artifact_bucket: str = "quiz-artifacts",
        region: str = "us-east-1",
        quiz_runner: Optional[QuizRunner] = None,
    ):
        """
        Initialize Spot Orchestrator.
        
        Args:
            config: Spot Fleet configuration
            redis_url: Redis connection URL for quiz queue
            artifact_bucket: S3 bucket for quiz artifacts
            region: AWS region
            quiz_runner: QuizRunner instance for checkpoint/resume
        """
        self.config = config
        self.redis_url = redis_url
        self.artifact_bucket = artifact_bucket
        self.region = region
        self.quiz_runner = quiz_runner
        
        # AWS clients with retry configuration
        retry_config = Config(
            retries={
                "max_attempts": 5,
                "mode": "adaptive",
            },
            region_name=region,
        )
        self.ec2 = boto3.client("ec2", config=retry_config)
        self.ec2_resource = boto3.resource("ec2", config=retry_config)
        self.s3 = boto3.client("s3", config=retry_config)
        self.autoscaling = boto3.client("autoscaling", config=retry_config)
        
        # Redis connection pool
        self._redis_pool: Optional[redis.ConnectionPool] = None
        self._redis_client: Optional[redis.Redis] = None
        
        # Fleet state
        self.fleet_id: Optional[str] = None
        self.fleet_state: FleetState = FleetState.SUBMITTED
        self.active_instances: Set[str] = set()
        self.interruption_handlers: List[Callable[[InterruptionNotice], None]] = []
        
        # Monitoring tasks
        self._monitor_task: Optional[asyncio.Task] = None
        self._interruption_monitor_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
        
        # Metrics
        self.metrics = {
            "interruptions_handled": 0,
            "workloads_migrated": 0,
            "checkpoints_created": 0,
            "on_demand_launched": 0,
        }
    
    async def initialize(self) -> None:
        """Initialize async resources."""
        self._redis_pool = redis.ConnectionPool.from_url(
            self.redis_url,
            max_connections=20,
            decode_responses=True,
        )
        self._redis_client = redis.Redis(connection_pool=self._redis_pool)
        
        # Setup S3 Intelligent-Tiering lifecycle policy
        await self._setup_s3_lifecycle_policy()
        
        logger.info("SpotOrchestrator initialized")
    
    async def _setup_s3_lifecycle_policy(self) -> None:
        """Configure S3 Intelligent-Tiering lifecycle policy for artifact bucket."""
        try:
            lifecycle_config = {
                "Rules": [
                    {
                        "ID": "QuizArtifactsIntelligentTiering",
                        "Status": "Enabled",
                        "Filter": {"Prefix": "quiz-artifacts/"},
                        "Transitions": [
                            {
                                "Days": 30,
                                "StorageClass": "INTELLIGENT_TIERING",
                            },
                            {
                                "Days": 90,
                                "StorageClass": "GLACIER_IR",
                            },
                            {
                                "Days": 365,
                                "StorageClass": "DEEP_ARCHIVE",
                            },
                        ],
                        "NoncurrentVersionTransitions": [
                            {
                                "NoncurrentDays": 30,
                                "StorageClass": "INTELLIGENT_TIERING",
                            },
                            {
                                "NoncurrentDays": 90,
                                "StorageClass": "GLACIER_IR",
                            },
                        ],
                        "AbortIncompleteMultipartUpload": {
                            "DaysAfterInitiation": 7
                        },
                    }
                ]
            }
            
            self.s3.put_bucket_lifecycle_configuration(
                Bucket=self.artifact_bucket,
                LifecycleConfiguration=lifecycle_config,
            )
            logger.info(f"S3 Intelligent-Tiering lifecycle policy applied to {self.artifact_bucket}")
        except ClientError as e:
            logger.warning(f"Failed to set S3 lifecycle policy: {e}")
    
    def create_fleet(self) -> str:
        """
        Create Spot Fleet request with diversified allocation strategy.
        
        Returns:
            Fleet request ID
            
        Raises:
            ClientError: If fleet creation fails
        """
        launch_specs = self._build_launch_specifications()
        
        spot_fleet_request_config = {
            "IamFleetRole": self._get_or_create_fleet_role(),
            "AllocationStrategy": self.config.allocation_strategy.value,
            "TargetCapacity": self.config.target_capacity,
            "SpotPrice": self.config.spot_price or "",
            "TerminateInstancesWithExpiration": True,
            "Type": "maintain",
            "ReplaceUnhealthyInstances": self.config.replace_unhealthy_instances,
            "InstanceInterruptionBehavior": self.config.instance_interruption_behavior,
            "LaunchSpecifications": launch_specs,
            "TagSpecifications": [
                {
                    "ResourceType": "spot-fleet-request",
                    "Tags": [
                        {"Key": k, "Value": v}
                        for k, v in self.config.tags.items()
                    ] + [
                        {"Key": "Name", "Value": self.config.fleet_name},
                        {"Key": "ManagedBy", "Value": "SpotOrchestrator"},
                    ],
                }
            ],
        }
        
        # Add on-demand configuration if specified
        if self.config.on_demand_percentage > 0 or self.config.on_demand_base_capacity > 0:
            spot_fleet_request_config["OnDemandOptions"] = {
                "AllocationStrategy": "lowestPrice",
                "TargetCapacity": self.config.on_demand_base_capacity,
                "MinTargetCapacity": self.config.on_demand_base_capacity,
            }
            spot_fleet_request_config["SpotOptions"] = {
                "AllocationStrategy": self.config.allocation_strategy.value,
                "InstanceInterruptionBehavior": self.config.instance_interruption_behavior,
            }
        
        try:
            response = self.ec2.request_spot_fleet(
                SpotFleetRequestConfig=spot_fleet_request_config
            )
            self.fleet_id = response["SpotFleetRequestId"]
            self.fleet_state = FleetState.SUBMITTED
            logger.info(f"Created Spot Fleet: {self.fleet_id}")
            return self.fleet_id
        except ClientError as e:
            logger.error(f"Failed to create Spot Fleet: {e}")
            raise
    
    def _build_launch_specifications(self) -> List[Dict[str, Any]]:
        """Build launch specifications for each instance type and AZ combination."""
        specs = []
        
        # Get available AZs if not specified
        azs = self.config.availability_zones or self._get_available_azs()
        subnets = self.config.subnet_ids or self._get_subnets_for_azs(azs)
        
        for instance_type in self.config.instance_types:
            for az, subnet_id in zip(azs, subnets):
                spec = {
                    "ImageId": self._get_latest_ami(instance_type),
                    "InstanceType": instance_type.value,
                    "SubnetId": subnet_id,
                    "Placement": {"AvailabilityZone": az},
                    "WeightedCapacity": self._get_instance_weight(instance_type),
                }
                
                if self.config.security_group_ids:
                    spec["SecurityGroups"] = [
                        {"GroupId": sg} for sg in self.config.security_group_ids
                    ]
                
                if self.config.iam_instance_profile_arn:
                    spec["IamInstanceProfile"] = {
                        "Arn": self.config.iam_instance_profile_arn
                    }
                
                if self.config.key_name:
                    spec["KeyName"] = self.config.key_name
                
                if self.config.user_data:
                    spec["UserData"] = self.config.user_data
                
                # Add tags
                spec["TagSpecifications"] = [
                    {
                        "ResourceType": "instance",
                        "Tags": [
                            {"Key": k, "Value": v}
                            for k, v in self.config.tags.items()
                        ] + [
                            {"Key": "FleetName", "Value": self.config.fleet_name},
                            {"Key": "InstanceType", "Value": instance_type.value},
                        ],
                    }
                ]
                
                specs.append(spec)
        
        return specs
    
    def _get_available_azs(self) -> List[str]:
        """Get available availability zones in the region."""
        try:
            response = self.ec2.describe_availability_zones(
                Filters=[{"Name": "state", "Values": ["available"]}]
            )
            return [az["ZoneName"] for az in response["AvailabilityZones"][:3]]
        except ClientError as e:
            logger.error(f"Failed to get AZs: {e}")
            return [f"{self.region}a", f"{self.region}b", f"{self.region}c"]
    
    def _get_subnets_for_azs(self, azs: List[str]) -> List[str]:
        """Get subnet IDs for the given AZs."""
        try:
            response = self.ec2.describe_subnets(
                Filters=[
                    {"Name": "availability-zone", "Values": azs},
                    {"Name": "default-for-az", "Values": ["true"]},
                ]
            )
            subnet_map = {s["AvailabilityZone"]: s["SubnetId"] for s in response["Subnets"]}
            return [subnet_map.get(az, "") for az in azs]
        except ClientError as e:
            logger.error(f"Failed to get subnets: {e}")
            return [""] * len(azs)
    
    def _get_latest_ami(self, instance_type: InstanceType) -> str:
        """Get latest Amazon Linux 2023 AMI for the instance architecture."""
        arch = "arm64" if instance_type == InstanceType.C7G_XLARGE else "x86_64"
        
        try:
            response = self.ec2.describe_images(
                Owners=["amazon"],
                Filters=[
                    {"Name": "name", "Values": [f"al2023-ami-*-{arch}"]},
                    {"Name": "state", "Values": ["available"]},
                    {"Name": "architecture", "Values": [arch]},
                    {"Name": "root-device-type", "Values": ["ebs"]},
                    {"Name": "virtualization-type", "Values": ["hvm"]},
                ],
            )
            images = sorted(
                response["Images"],
                key=lambda x: x["CreationDate"],
                reverse=True,
            )
            return images[0]["ImageId"] if images else ""
        except ClientError as e:
            logger.error(f"Failed to get AMI: {e}")
            # Fallback AMIs
            fallback = {
                "x86_64": "ami-0c02fb55956c7d316",  # Amazon Linux 2023 x86_64
                "arm64": "ami-0a3c3a20c09d6f377",   # Amazon Linux 2023 arm64
            }
            return fallback.get(arch, "")
    
    def _get_instance_weight(self, instance_type: InstanceType) -> int:
        """Get weighted capacity for instance type (based on vCPU)."""
        weights = {
            InstanceType.C6I_XLARGE: 4,   # 4 vCPU
            InstanceType.C6A_XLARGE: 4,   # 4 vCPU
            InstanceType.C7G_XLARGE: 4,   # 4 vCPU
        }
        return weights.get(instance_type, 1)
    
    def _get_or_create_fleet_role(self) -> str:
        """Get or create IAM role for Spot Fleet."""
        role_name = "AWSServiceRoleForEC2SpotFleet"
        try:
            iam = boto3.client("iam", config=Config(region_name=self.region))
            response = iam.get_role(RoleName=role_name)
            return response["Role"]["Arn"]
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchEntity":
                # Create service-linked role
                try:
                    response = iam.create_service_linked_role(
                        AWSServiceName="spotfleet.amazonaws.com",
                        Description="Service-linked role for EC2 Spot Fleet",
                    )
                    return response["Role"]["Arn"]
                except ClientError as create_error:
                    logger.error(f"Failed to create fleet role: {create_error}")
                    raise
            raise
    
    async def start_monitoring(self) -> None:
        """Start fleet monitoring and interruption handling."""
        if self._monitor_task is None or self._monitor_task.done():
            self._monitor_task = asyncio.create_task(self._monitor_fleet())
        
        if self._interruption_monitor_task is None or self._interruption_monitor_task.done():
            self._interruption_monitor_task = asyncio.create_task(
                self._monitor_interruptions()
            )
        
        logger.info("Started fleet monitoring")
    
    async def _monitor_fleet(self) -> None:
        """Monitor fleet state and instance health."""