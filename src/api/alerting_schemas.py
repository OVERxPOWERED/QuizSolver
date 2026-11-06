from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class ConditionOperator(str, Enum):
    GT = "gt"
    LT = "lt"
    EQ = "eq"
    GTE = "gte"
    LTE = "lte"
    NE = "ne"


class NotificationChannelType(str, Enum):
    PAGERDUTY = "pagerduty"
    SLACK = "slack"
    WEBHOOK = "webhook"
    EMAIL = "email"


class PagerDutyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str = Field(..., min_length=1, description="PagerDuty API key")
    service_key: str = Field(..., min_length=1, description="PagerDuty service integration key")
    severity: Optional[str] = Field(default="critical", description="PagerDuty severity level")
    component: Optional[str] = Field(default=None, description="Component name")
    group: Optional[str] = Field(default=None, description="Group name")
    class_: Optional[str] = Field(default=None, alias="class", description="Class name")


class SlackConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    webhook_url: str = Field(..., min_length=1, description="Slack incoming webhook URL")
    channel: Optional[str] = Field(default=None, description="Slack channel override")
    username: Optional[str] = Field(default="AlertManager", description="Bot username")
    icon_emoji: Optional[str] = Field(default=":warning:", description="Icon emoji")
    mention_users: Optional[List[str]] = Field(default_factory=list, description="User IDs to mention")


class WebhookConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(..., min_length=1, description="Webhook endpoint URL")
    method: Literal["POST", "PUT", "PATCH"] = Field(default="POST", description="HTTP method")
    headers: Dict[str, str] = Field(default_factory=dict, description="Custom headers")
    timeout_seconds: int = Field(default=10, ge=1, le=60, description="Request timeout")
    retry_count: int = Field(default=3, ge=0, le=5, description="Number of retries")


class EmailConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    smtp_host: str = Field(..., min_length=1, description="SMTP server host")
    smtp_port: int = Field(default=587, ge=1, le=65535, description="SMTP server port")
    username: str = Field(..., min_length=1, description="SMTP username")
    password: str = Field(..., min_length=1, description="SMTP password")
    from_address: str = Field(..., min_length=1, description="Sender email address")
    to_addresses: List[str] = Field(..., min_length=1, description="Recipient email addresses")
    use_tls: bool = Field(default=True, description="Use TLS encryption")


NotificationChannelConfig = Union[PagerDutyConfig, SlackConfig, WebhookConfig, EmailConfig]


class NotificationChannel(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    type: NotificationChannelType = Field(..., description="Channel type discriminator")
    name: str = Field(..., min_length=1, max_length=100, description="Human-readable channel name")
    config: NotificationChannelConfig = Field(..., description="Channel-specific configuration")
    enabled: bool = Field(default=True, description="Whether channel is active")
    severity_filter: List[AlertSeverity] = Field(
        default_factory=lambda: [AlertSeverity.WARNING, AlertSeverity.CRITICAL],
        description="Severities this channel should receive"
    )

    @field_validator("config", mode="before")
    @classmethod
    def validate_config_matches_type(cls, v: Any, info: Any) -> Any:
        if isinstance(v, dict) and "type" in info.data:
            channel_type = info.data["type"]
            if channel_type == NotificationChannelType.PAGERDUTY:
                return PagerDutyConfig(**v)
            elif channel_type == NotificationChannelType.SLACK:
                return SlackConfig(**v)
            elif channel_type == NotificationChannelType.WEBHOOK:
                return WebhookConfig(**v)
            elif channel_type == NotificationChannelType.EMAIL:
                return EmailConfig(**v)
        return v


class AlertRule(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    name: str = Field(..., min_length=1, max_length=200, description="Unique rule identifier")
    description: Optional[str] = Field(default=None, max_length=500, description="Human-readable description")
    metric_name: str = Field(..., min_length=1, max_length=200, description="Metric to evaluate")
    condition: ConditionOperator = Field(..., description="Comparison operator")
    threshold: float = Field(..., description="Threshold value for condition")
    duration_seconds: int = Field(
        default=60, ge=10, le=86400, description="Duration condition must persist before firing"
    )
    severity: AlertSeverity = Field(default=AlertSeverity.WARNING, description="Alert severity level")
    channels: List[NotificationChannel] = Field(
        default_factory=list, min_length=1, description="Notification channels for this rule"
    )
    cooldown_seconds: int = Field(
        default=300, ge=0, le=86400, description="Minimum time between alert firings"
    )
    labels: Dict[str, str] = Field(default_factory=dict, description="Additional labels for alert")
    enabled: bool = Field(default=True, description="Whether rule is active")
    evaluation_interval_seconds: int = Field(
        default=30, ge=10, le=3600, description="How often to evaluate the rule"
    )

    @model_validator(mode="after")
    def validate_channels_for_severity(self) -> "AlertRule":
        for channel in self.channels:
            if self.severity not in channel.severity_filter:
                raise ValueError(
                    f"Channel '{channel.name}' does not accept severity '{self.severity.value}'"
                )
        return self


class AlertPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    rule_name: str = Field(..., min_length=1, description="Name of the rule that fired")
    metric_name: str = Field(..., min_length=1, description="Metric that triggered the alert")
    metric_value: float = Field(..., description="Current metric value")
    threshold: float = Field(..., description="Threshold that was breached")
    condition: ConditionOperator = Field(..., description="Condition operator used")
    severity: AlertSeverity = Field(..., description="Alert severity")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="When the alert fired")
    labels: Dict[str, str] = Field(default_factory=dict, description="Alert labels")
    annotations: Dict[str, str] = Field(default_factory=dict, description="Additional annotations")
    runbook_url: Optional[str] = Field(default=None, description="Link to runbook/playbook")
    fingerprint: str = Field(..., min_length=1, description="Unique fingerprint for deduplication")

    @field_validator("fingerprint", mode="before")
    @classmethod
    def generate_fingerprint(cls, v: Any, info: Any) -> str:
        if v:
            return v
        data = info.data
        return f"{data.get('rule_name', '')}:{data.get('metric_name', '')}:{data.get('labels', {})}"


class AlertRuleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=500)
    metric_name: str = Field(..., min_length=1, max_length=200)
    condition: ConditionOperator
    threshold: float
    duration_seconds: int = Field(default=60, ge=10, le=86400)
    severity: AlertSeverity = Field(default=AlertSeverity.WARNING)
    channels: List[NotificationChannel] = Field(..., min_length=1)
    cooldown_seconds: int = Field(default=300, ge=0, le=86400)
    labels: Dict[str, str] = Field(default_factory=dict)
    enabled: bool = Field(default=True)
    evaluation_interval_seconds: int = Field(default=30, ge=10, le=3600)


class AlertRuleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    description: Optional[str] = Field(default=None, max_length=500)
    metric_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    condition: Optional[ConditionOperator] = None
    threshold: Optional[float] = None
    duration_seconds: Optional[int] = Field(default=None, ge=10, le=86400)
    severity: Optional[AlertSeverity] = None
    channels: Optional[List[NotificationChannel]] = None
    cooldown_seconds: Optional[int] = Field(default=None, ge=0, le=86400)
    labels: Optional[Dict[str, str]] = None
    enabled: Optional[bool] = None
    evaluation_interval_seconds: Optional[int] = Field(default=None, ge=10, le=3600)


class AlertSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    total_rules: int = Field(..., ge=0)
    enabled_rules: int = Field(..., ge=0)
    firing_alerts: int = Field(..., ge=0)
    alerts_by_severity: Dict[AlertSeverity, int] = Field(default_factory=dict)
    last_evaluation: Optional[datetime] = None


__all__ = [
    "AlertSeverity",
    "ConditionOperator",
    "NotificationChannelType",
    "PagerDutyConfig",
    "SlackConfig",
    "WebhookConfig",
    "EmailConfig",
    "NotificationChannel",
    "AlertRule",
    "AlertRuleCreate",
    "AlertRuleUpdate",
    "AlertPayload",
    "AlertSummary",
]