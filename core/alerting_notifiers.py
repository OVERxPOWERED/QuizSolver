import asyncio
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional, Protocol

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.api.alerting_schemas import AlertPayload, NotificationChannel


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    failure_threshold: int = 5
    recovery_timeout: float = 30.0
    expected_exception: tuple = (httpx.RequestError, httpx.HTTPStatusError)

    def __post_init__(self):
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: Optional[float] = None
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        return self._state

    async def call(self, func, *args, **kwargs):
        async with self._lock:
            if self._state == CircuitState.OPEN:
                if time.time() - self._last_failure_time >= self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                else:
                    raise CircuitBreakerOpenError("Circuit breaker is open")

        try:
            result = await func(*args, **kwargs)
            async with self._lock:
                self._on_success()
            return result
        except self.expected_exception as e:
            async with self._lock:
                self._on_failure()
            raise

    def _on_success(self):
        self._failure_count = 0
        self._state = CircuitState.CLOSED

    def _on_failure(self):
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN


class CircuitBreakerOpenError(Exception):
    pass


class NotifierProtocol(Protocol):
    async def send(self, payload: AlertPayload, channel: NotificationChannel) -> bool:
        ...


class BaseNotifier(ABC):
    def __init__(self, channel: NotificationChannel):
        self.channel = channel
        self._client: Optional[httpx.AsyncClient] = None
        self._circuit_breaker = CircuitBreaker()
        self._retry_policy = AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            retry=retry_if_exception_type((httpx.RequestError, httpx.HTTPStatusError)),
            reraise=True,
        )

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            timeout = httpx.Timeout(10.0, connect=5.0)
            limits = httpx.Limits(max_connections=10, max_keepalive_connections=5)
            self._client = httpx.AsyncClient(timeout=timeout, limits=limits)
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    @abstractmethod
    async def _send_request(self, payload: AlertPayload) -> httpx.Response:
        pass

    async def send(self, payload: AlertPayload, channel: NotificationChannel) -> bool:
        self.channel = channel
        try:
            await self._circuit_breaker.call(self._send_with_retry, payload)
            return True
        except (httpx.RequestError, httpx.HTTPStatusError, CircuitBreakerOpenError) as e:
            return False

    async def _send_with_retry(self, payload: AlertPayload):
        async for attempt in self._retry_policy:
            with attempt:
                response = await self._send_request(payload)
                response.raise_for_status()


class PagerDutyNotifier(BaseNotifier):
    SEVERITY_MAP = {
        "critical": "critical",
        "error": "error",
        "warning": "warning",
        "info": "info",
    }

    async def _send_request(self, payload: AlertPayload) -> httpx.Response:
        client = await self._get_client()
        routing_key = self.channel.config.get("routing_key")
        if not routing_key:
            raise ValueError("PagerDuty routing_key not configured in channel")

        pd_payload = {
            "routing_key": routing_key,
            "event_action": "trigger",
            "payload": {
                "summary": payload.summary,
                "severity": self.SEVERITY_MAP.get(payload.severity.value, "error"),
                "source": payload.source,
                "custom_details": payload.custom_details or {},
            },
        }

        if payload.metric_name:
            pd_payload["payload"]["custom_details"]["metric_name"] = payload.metric_name
        if payload.value is not None:
            pd_payload["payload"]["custom_details"]["value"] = payload.value
        if payload.threshold is not None:
            pd_payload["payload"]["custom_details"]["threshold"] = payload.threshold
        if payload.timestamp:
            pd_payload["payload"]["timestamp"] = payload.timestamp.isoformat()

        return await client.post(
            "https://events.pagerduty.com/v2/enqueue",
            json=pd_payload,
            headers={"Content-Type": "application/json"},
        )


class SlackNotifier(BaseNotifier):
    SEVERITY_EMOJI = {
        "critical": ":red_circle:",
        "error": ":large_orange_circle:",
        "warning": ":yellow_circle:",
        "info": ":large_blue_circle:",
    }

    async def _send_request(self, payload: AlertPayload) -> httpx.Response:
        client = await self._get_client()
        webhook_url = self.channel.config.get("webhook_url")
        if not webhook_url:
            raise ValueError("Slack webhook_url not configured in channel")

        severity_emoji = self.SEVERITY_EMOJI.get(payload.severity.value, ":warning:")
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{severity_emoji} Alert: {payload.summary}",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Severity:*\n{payload.severity.value.upper()}"},
                    {"type": "mrkdwn", "text": f"*Source:*\n{payload.source}"},
                ],
            },
        ]

        if payload.metric_name:
            blocks.append(
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Metric:*\n{payload.metric_name}"},
                        {"type": "mrkdwn", "text": f"*Value:*\n{payload.value}"},
                    ],
                }
            )
            if payload.threshold is not None:
                blocks[-1]["fields"].append(
                    {"type": "mrkdwn", "text": f"*Threshold:*\n{payload.threshold}"}
                )

        if payload.timestamp:
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"Timestamp: {payload.timestamp.isoformat()}",
                        }
                    ],
                }
            )

        if payload.custom_details:
            details_text = "\n".join(
                f"*{k}:* {v}" for k, v in payload.custom_details.items()
            )
            blocks.append(
                {"type": "section", "text": {"type": "mrkdwn", "text": details_text}}
            )

        slack_payload = {"blocks": blocks, "text": f"Alert: {payload.summary}"}
        return await client.post(webhook_url, json=slack_payload)


def get_notifier(channel_type: str) -> NotifierProtocol:
    notifiers = {
        "pagerduty": PagerDutyNotifier,
        "slack": SlackNotifier,
    }
    notifier_class = notifiers.get(channel_type.lower())
    if not notifier_class:
        raise ValueError(f"Unknown notifier type: {channel_type}")
    return notifier_class


__all__ = [
    "NotifierProtocol",
    "BaseNotifier",
    "PagerDutyNotifier",
    "SlackNotifier",
    "get_notifier",
    "CircuitBreaker",
    "CircuitBreakerOpenError",
]