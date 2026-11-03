"""
Prometheus metrics exposition for quiz automation services.

Provides counters, histograms, and gauges for monitoring quiz runs,
AI solver latency, browser operations, cache hit rates, and active sessions.
"""

from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from fastapi import Response
from typing import Optional

from core.config import get_settings
from core.logging import get_logger

logger = get_logger(__name__)

# Initialize settings
settings = get_settings()

# =============================================================================
# Metric Definitions
# =============================================================================

# Counter for total quiz runs with status and quiz_type labels
quiz_runs_total = Counter(
    "quiz_runs_total",
    "Total number of quiz runs executed",
    ["status", "quiz_type"],
)

# Histogram for AI solver latency with buckets for percentile calculation
ai_solver_latency_seconds = Histogram(
    "ai_solver_latency_seconds",
    "Latency of AI solver operations in seconds",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
)

# Histogram for browser operation durations
browser_operation_duration_seconds = Histogram(
    "browser_operation_duration_seconds",
    "Duration of browser operations in seconds",
    ["operation_type"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)

# Gauge for cache hit ratio (0.0 to 1.0)
cache_hit_ratio = Gauge(
    "cache_hit_ratio",
    "Cache hit ratio (hits / total requests)",
)

# Gauge for active quiz sessions
active_quiz_sessions = Gauge(
    "active_quiz_sessions",
    "Number of currently active quiz sessions",
)


# =============================================================================
# Metric Recording Functions
# =============================================================================

def record_quiz_run(status: str, quiz_type: str) -> None:
    """
    Record a quiz run completion.

    Args:
        status: "success" or "failed"
        quiz_type: Type of quiz (e.g., "multiple_choice", "coding", "essay")
    """
    quiz_runs_total.labels(status=status, quiz_type=quiz_type).inc()
    logger.debug("Recorded quiz run", extra={"status": status, "quiz_type": quiz_type})


def record_ai_solver_latency(duration_seconds: float) -> None:
    """
    Record AI solver latency.

    Args:
        duration_seconds: Time taken for AI solver operation in seconds
    """
    ai_solver_latency_seconds.observe(duration_seconds)
    logger.debug("Recorded AI solver latency", extra={"duration_seconds": duration_seconds})


def record_browser_operation(operation_type: str, duration_seconds: float) -> None:
    """
    Record browser operation duration.

    Args:
        operation_type: Type of operation (e.g., "page_navigation", "element_click", "form_fill", "screenshot")
        duration_seconds: Time taken for the operation in seconds
    """
    browser_operation_duration_seconds.labels(operation_type=operation_type).observe(duration_seconds)
    logger.debug(
        "Recorded browser operation",
        extra={"operation_type": operation_type, "duration_seconds": duration_seconds}
    )


def record_cache_hit(hit: bool) -> None:
    """
    Update cache hit ratio gauge.

    Args:
        hit: True if cache hit, False if cache miss
    """
    # This is a simplified implementation. In production, you'd track
    # hits and misses separately and compute the ratio.
    # For now, we'll use a simple moving average approach.
    current = cache_hit_ratio._value.get()  # type: ignore[attr-defined]
    # Simple exponential moving update
    new_value = 0.9 * current + 0.1 * (1.0 if hit else 0.0)
    cache_hit_ratio.set(new_value)
    logger.debug("Updated cache hit ratio", extra={"hit": hit, "ratio": new_value})


def record_active_sessions(count: int) -> None:
    """
    Set the number of active quiz sessions.

    Args:
        count: Current number of active sessions
    """
    active_quiz_sessions.set(count)
    logger.debug("Updated active quiz sessions", extra={"count": count})


def increment_active_sessions() -> None:
    """Increment active quiz sessions counter."""
    active_quiz_sessions.inc()
    logger.debug("Incremented active quiz sessions")


def decrement_active_sessions() -> None:
    """Decrement active quiz sessions counter."""
    active_quiz_sessions.dec()
    logger.debug("Decremented active quiz sessions")


# =============================================================================
# Metrics Exposition
# =============================================================================

def get_metrics() -> bytes:
    """
    Generate Prometheus metrics in text format.

    Returns:
        Metrics data as bytes in Prometheus exposition format
    """
    return generate_latest()


async def metrics_endpoint() -> Response:
    """
    FastAPI endpoint for Prometheus metrics exposition.

    Returns:
        Response with Prometheus metrics in text format
    """
    return Response(content=get_metrics(), media_type=CONTENT_TYPE_LATEST)


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    # Metrics
    "quiz_runs_total",
    "ai_solver_latency_seconds",
    "browser_operation_duration_seconds",
    "cache_hit_ratio",
    "active_quiz_sessions",
    # Recording functions
    "record_quiz_run",
    "record_ai_solver_latency",
    "record_browser_operation",
    "record_cache_hit",
    "record_active_sessions",
    "increment_active_sessions",
    "decrement_active_sessions",
    # Exposition
    "get_metrics",
    "metrics_endpoint",
]