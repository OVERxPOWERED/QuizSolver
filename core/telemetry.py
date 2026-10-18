```python
import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Union

try:
    import structlog
    STRUCTLOG_AVAILABLE = True
except ImportError:
    STRUCTLOG_AVAILABLE = False

correlation_id_var: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)


def get_correlation_id() -> str:
    """Get or generate a correlation ID for the current context."""
    cid = correlation_id_var.get()
    if cid is None:
        cid = str(uuid.uuid4())
        correlation_id_var.set(cid)
    return cid


def set_correlation_id(cid: str) -> None:
    """Set the correlation ID for the current context."""
    correlation_id_var.set(cid)


def clear_correlation_id() -> None:
    """Clear the correlation ID for the current context."""
    correlation_id_var.set(None)


@dataclass
class TelemetryConfig:
    """Configuration for telemetry service."""
    service_name: str = "unknown-service"
    environment: str = "development"
    log_level: str = "INFO"
    json_output: bool = True


class TelemetryService:
    """Structured telemetry and error event handling service."""

    def __init__(self, config: Optional[TelemetryConfig] = None):
        self.config = config or TelemetryConfig()
        self._logger = self._setup_logger()
        self._metrics_buffer: list = []

    def _setup_logger(self) -> Union["structlog.BoundLogger", logging.Logger]:
        """Configure and return a structured logger."""
        if STRUCTLOG_AVAILABLE:
            return self._setup_structlog()
        else:
            return self._setup_stdlib_logging()

    def _setup_structlog(self) -> "structlog.BoundLogger":
        """Configure structlog with JSON output and correlation ID injection."""
        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.processors.add_log_level,
                structlog.processors.TimeStamper(fmt="iso", utc=True),
                structlog.processors.CallsiteParameterAdder(
                    parameters=[
                        structlog.processors.CallsiteParameter.FILENAME,
                        structlog.processors.CallsiteParameter.LINENO,
                        structlog.processors.CallsiteParameter.FUNC_NAME,
                    ]
                ),
                self._add_correlation_id,
                structlog.processors.JSONRenderer() if self.config.json_output
                else structlog.dev.ConsoleRenderer(),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(
                getattr(logging, self.config.log_level.upper())
            ),
            context_class=dict,
            logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
            cache_logger_on_first_use=True,
        )
        return structlog.get_logger(self.config.service_name)

    def _setup_stdlib_logging(self) -> logging.Logger:
        """Configure stdlib logging with JSON formatting as fallback."""
        logger = logging.getLogger(self.config.service_name)
        logger.setLevel(getattr(logging, self.config.log_level.upper()))
        logger.handlers.clear()

        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.propagate = False
        return logger

    def _add_correlation_id(self, logger, method_name, event_dict):
        """Add correlation ID to log event."""
        cid = correlation_id_var.get()
        if cid:
            event_dict["correlation_id"] = cid
        return event_dict

    def record_event(
        self,
        event_type: str,
        payload: Dict[str, Any],
        level: str = "info"
    ) -> None:
        """Record a structured event with the given type and payload."""
        log_data = {
            "event_type": event_type,
            "payload": payload,
            "service": self.config.service_name,
            "environment": self.config.environment,
        }

        if STRUCTLOG_AVAILABLE:
            getattr(self._logger, level.lower())(event_type, **log_data)
        else:
            log_data["level"] = level.upper()
            log_data["timestamp"] = time.time()
            self._logger.log(getattr(logging, level.upper()), json.dumps(log_data))

    def record_error(
        self,
        error: Exception,
        context: Optional[Dict[str, Any]] = None,
        level: str = "error"
    ) -> None:
        """Record an error with full context and stack trace."""
        error_data = {
            "error_type": type(error).__name__,
            "error_message": str(error),
            "service": self.config.service_name,
            "environment": self.config.environment,
        }

        if context:
            error_data["context"] = context

        if STRUCTLOG_AVAILABLE:
            self._logger.error(
                "error_occurred",
                error_type=type(error).__name__,
                error_message=str(error),
                context=context or {},
                service=self.config.service_name,
                environment=self.config.environment,
                exc_info=True,
            )
        else:
            error_data["level"] = level.upper()
            error_data["timestamp"] = time.time()
            error_data["exc_info"] = self._format_exception(error)
            self._logger.log(getattr(logging, level.upper()), json.dumps(error_data))

    def record_metric(
        self,
        name: str,
        value: Union[int, float],
        tags: Optional[Dict[str, str]] = None,
        metric_type: str = "gauge"
    ) -> None:
        """Record a metric with name, value, and optional tags."""
        metric_data = {
            "metric_name": name,
            "metric_value": value,
            "metric_type": metric_type,
            "tags": tags or {},
            "service": self.config.service_name,
            "environment": self.config.environment,
        }

        if STRUCTLOG_AVAILABLE:
            self._logger.info(
                "metric_recorded",
                metric_name=name,
                metric_value=value,
                metric_type=metric_type,
                tags=tags or {},
                service=self.config.service_name,
                environment=self.config.environment,
            )
        else:
            metric_data["level"] = "INFO"
            metric_data["timestamp"] = time.time()
            self._logger.info(json.dumps(metric_data))

        self._metrics_buffer.append(metric_data)

    def _format_exception(self, error: Exception) -> str:
        """Format exception for stdlib logging."""
        import traceback
        return "".join(traceback.format_exception(type(error), error, error.__traceback__))

    def get_metrics_buffer(self) -> list:
        """Get the current metrics buffer."""
        return self._metrics_buffer.copy()

    def clear_metrics_buffer(self) -> None:
        """Clear the metrics buffer."""
        self._metrics_buffer.clear()


class JsonFormatter(logging.Formatter):
    """JSON formatter for stdlib logging."""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if hasattr(record, "correlation_id"):
            log_data["correlation_id"] = record.correlation_id

        if record.exc_info:
            log_data["exc_info"] = self.formatException(record.exc_info)

        for key