```python
#!/usr/bin/env python3
"""
Production Deployment Verification Script

Automated health checks, smoke tests, and rollback validation for production deployments.
"""

import os
import sys
import json
import time
import subprocess
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum

import httpx
import pytest

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.config import get_settings
from core.database import get_db_session, check_database_connection
from core.cache import get_redis_client, check_redis_connection
from utils.health import HealthChecker
from services.quiz_service import QuizService


class CheckStatus(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"
    WARNING = "WARNING"


@dataclass
class CheckResult:
    name: str
    status: CheckStatus
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class DeploymentReport:
    environment: str
    version: str
    started_at: str
    completed_at: Optional[str] = None
    pre_deployment: List[CheckResult] = field(default_factory=list)
    post_deployment: List[CheckResult] = field(default_factory=list)
    performance: List[CheckResult] = field(default_factory=list)
    rollback: List[CheckResult] = field(default_factory=list)
    overall_status: CheckStatus = CheckStatus.PASS

    def to_markdown(self) -> str:
        lines = [
            f"# Deployment Verification Report",
            f"",
            f"**Environment:** {self.environment}",
            f"**Version:** {self.version}",
            f"**Started:** {self.started_at}",
            f"**Completed:** {self.completed_at or 'In Progress'}",
            f"**Overall Status:** {self.overall_status.value}",
            f"",
        ]

        for section_name, checks in [
            ("Pre-Deployment Checks", self.pre_deployment),
            ("Post-Deployment Smoke Tests", self.post_deployment),
            ("Performance Baseline", self.performance),
            ("Rollback Validation", self.rollback),
        ]:
            if not checks:
                continue
            lines.append(f"## {section_name}")
            lines.append("")
            lines.append("| Check | Status | Duration | Message |")
            lines.append("|-------|--------|----------|---------|")
            for check in checks:
                status_emoji = {
                    CheckStatus.PASS: "✅",
                    CheckStatus.FAIL: "❌",
                    CheckStatus.SKIP: "⏭️",
                    CheckStatus.WARNING: "⚠️",
                }.get(check.status, "❓")
                lines.append(
                    f"| {check.name} | {status_emoji} {check.status.value} | "
                    f"{check.duration_ms:.1f}ms | {check.message} |"
                )
            lines.append("")

        return "\n".join(lines)


class DeploymentVerifier:
    """Production deployment verification with automated health checks."""

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        environment: str = "production",
        version: Optional[str] = None,
        timeout: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.environment = environment
        self.version = version or self._get_git_version()
        self.timeout = timeout
        self.settings = get_settings()
        self.report = DeploymentReport(
            environment=environment,
            version=self.version,
            started_at=datetime.utcnow().isoformat(),
        )
        self._client: Optional[httpx.AsyncClient] = None
        self._health_checker = HealthChecker()

    def _get_git_version(self) -> str:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                cwd=PROJECT_ROOT,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return "unknown"

    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=self.timeout, follow_redirects=True)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            await self._client.aclose()

    def _record_check(
        self, section: str, name: str, status: CheckStatus, message: str, details: Dict = None, duration_ms: float = 0.0
    ) -> CheckResult:
        result = CheckResult(
            name=name,
            status=status,
            message=message,
            details=details or {},
            duration_ms=duration_ms,
        )
        getattr(self.report, section).append(result)
        return result

    async def pre_deployment_checks(self) -> List[CheckResult]:
        """Validate configuration, database migrations, and cache connectivity before deployment."""
        checks = []

        # Check 1: Configuration validation
        start = time.perf_counter()
        try:
            settings = get_settings()
            required_settings = [
                "DATABASE_URL",
                "REDIS_URL",
                "SECRET_KEY",
                "ENVIRONMENT",
            ]
            missing = [s for s in required_settings if not getattr(settings, s, None)]
            if missing:
                self._record_check(
                    "pre_deployment",
                    "Configuration Validation",
                    CheckStatus.FAIL,
                    f"Missing required settings: {', '.join(missing)}",
                    duration_ms=(time.perf_counter() - start) * 1000,
                )
            else:
                self._record_check(
                    "pre_deployment",
                    "Configuration Validation",
                    CheckStatus.PASS,
                    "All required configuration settings present",
                    {"settings_checked": required_settings},
                    duration_ms=(time.perf_counter() - start) * 1000,
                )
        except Exception as e:
            self._record_check(
                "pre_deployment",
                "Configuration Validation",
                CheckStatus.FAIL,
                f"Configuration error: {str(e)}",
                duration_ms=(time.perf_counter() - start) * 1000,
            )

        # Check 2: .env file exists (for non-container environments)
        start = time.perf_counter()
        env_path = PROJECT_ROOT / ".env"
        if env_path.exists() or self.settings.ENVIRONMENT == "production":
            self._record_check(
                "pre_deployment",
                "Environment File",
                CheckStatus.PASS,
                ".env file present or running in containerized environment",
                duration_ms=(time.perf_counter() - start) * 1000,
            )
        else:
            self._record_check(
                "pre_deployment",
                "Environment File",
                CheckStatus.WARNING,
                ".env file