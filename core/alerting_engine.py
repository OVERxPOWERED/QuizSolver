import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from src.api.alerting_schemas import AlertPayload, AlertRule, AlertSeverity
from core.prometheus_metrics import get_metric_value

logger = logging.getLogger(__name__)


class AlertingEngine:
    """Core alerting engine that evaluates Prometheus metrics against alert rules."""

    def __init__(self, rules: List[AlertRule], evaluation_interval: int = 30):
        self.rules = {rule.name: rule for rule in rules}
        self.evaluation_interval = evaluation_interval
        self.firing_alerts: Dict[str, AlertPayload] = {}
        self.last_fired: Dict[str, datetime] = {}
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start the evaluation loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self.evaluate_loop())
        logger.info("Alerting engine started")

    async def stop(self) -> None:
        """Stop the evaluation loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Alerting engine stopped")

    async def evaluate_loop(self) -> None:
        """Background task that periodically evaluates all alert rules."""
        while self._running:
            try:
                for rule in self.rules.values():
                    await self._evaluate_rule(rule)
            except Exception as e:
                logger.error(f"Error in evaluation loop: {e}", exc_info=True)
            await asyncio.sleep(self.evaluation_interval)

    async def _evaluate_rule(self, rule: AlertRule) -> None:
        """Evaluate a single alert rule against Prometheus metrics."""
        try:
            metric_value = await get_metric_value(rule.metric_query)
            if metric_value is None:
                logger.warning(f"No data returned for query: {rule.metric_query}")
                return

            condition_met = self._check_condition(metric_value, rule.condition)
            is_firing = rule.name in self.firing_alerts

            if condition_met and not is_firing:
                if self._check_cooldown(rule.name, rule.cooldown_seconds):
                    await self._fire_alert(rule, metric_value)
            elif not condition_met and is_firing:
                await self._resolve_alert(rule.name)

        except Exception as e:
            logger.error(f"Error evaluating rule {rule.name}: {e}", exc_info=True)

    def _check_condition(self, value: float, condition: str) -> bool:
        """
        Parse and evaluate a condition string against a metric value.
        Supported formats: '> 100', '>= 50', '< 10', '<= 5', '== 0', '!= 0'
        """
        match = re.match(r'^\s*(>=|<=|>|<|==|!=)\s*([\d.]+)\s*$', condition)
        if not match:
            logger.error(f"Invalid condition format: {condition}")
            return False

        operator, threshold_str = match.groups()
        threshold = float(threshold_str)

        if operator == '>':
            return value > threshold
        elif operator == '>=':
            return value >= threshold
        elif operator == '<':
            return value < threshold
        elif operator == '<=':
            return value <= threshold
        elif operator == '==':
            return value == threshold
        elif operator == '!=':
            return value != threshold
        else:
            logger.error(f"Unsupported operator: {operator}")
            return False

    def _check_cooldown(self, rule_name: str, cooldown_seconds: int) -> bool:
        """Check if enough time has passed since the last alert firing."""
        last_fired = self.last_fired.get(rule_name)
        if last_fired is None:
            return True
        elapsed = (datetime.utcnow() - last_fired).total_seconds()
        return elapsed >= cooldown_seconds

    async def _fire_alert(self, rule: AlertRule, metric_value: float) -> None:
        """Fire a new alert and store it in firing_alerts."""
        payload = AlertPayload(
            rule_name=rule.name,
            severity=rule.severity,
            message=rule.description.format(value=metric_value),
            metric_value=metric_value,
            timestamp=datetime.utcnow(),
            status="firing"
        )
        self.firing_alerts[rule.name] = payload
        self.last_fired[rule.name] = datetime.utcnow()
        logger.warning(f"ALERT FIRED: {rule.name} - {payload.message}")
        # In a real implementation, this would emit to an event bus or notification service
        await self._emit_alert(payload)

    async def _resolve_alert(self, rule_name: str) -> None:
        """Resolve a firing alert."""
        payload = self.firing_alerts.pop(rule_name, None)
        if payload:
            resolved_payload = AlertPayload(
                rule_name=payload.rule_name,
                severity=payload.severity,
                message=f"RESOLVED: {payload.message}",
                metric_value=payload.metric_value,
                timestamp=datetime.utcnow(),
                status="resolved"
            )
            logger.info(f"ALERT RESOLVED: {rule_name}")
            await self._emit_alert(resolved_payload)

    async def _emit_alert(self, payload: AlertPayload) -> None:
        """
        Emit alert payload to notification channels.
        This is a placeholder for integration with PagerDuty, Slack, etc.
        """
        # Implementation would go here - e.g., publish to message queue, call webhook, etc.
        pass

    def get_firing_alerts(self) -> List[AlertPayload]:
        """Return list of currently firing alerts."""
        return list(self.firing_alerts.values())