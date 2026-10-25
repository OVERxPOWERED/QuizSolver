"""
Prometheus metrics collectors and instrumentation helpers for quizAuto.
Provides standardized telemetry for quiz sessions, OCR extraction, solver latency, and API endpoints.
"""

from __future__ import annotations

import time
import functools
from typing import Callable, Any, Optional

try:
    from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry, generate_latest
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    CollectorRegistry = None
    generate_latest = None

# Custom registry for application metrics
registry = CollectorRegistry() if PROMETHEUS_AVAILABLE else None

if PROMETHEUS_AVAILABLE:
    QUIZ_SOLVED_TOTAL = Counter(
        "quizauto_questions_solved_total",
        "Total number of quiz questions solved by the engine",
        ["quiz_type", "status"],
        registry=registry,
    )

    SOLVER_DURATION_SECONDS = Histogram(
        "quizauto_solver_duration_seconds",
        "Time taken to analyze and solve questions in seconds",
        ["quiz_type"],
        buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
        registry=registry,
    )

    ACTIVE_SESSIONS = Gauge(
        "quizauto_active_sessions",
        "Number of active automated quiz sessions in progress",
        registry=registry,
    )

    OCR_ACCURACY_RATIO = Gauge(
        "quizauto_ocr_accuracy_ratio",
        "Estimated OCR confidence and accuracy score (0.0 to 1.0)",
        registry=registry,
    )

    API_ERRORS_TOTAL = Counter(
        "quizauto_api_errors_total",
        "Total errors encountered in quiz processing pipelines",
        ["error_type", "component"],
        registry=registry,
    )
else:
    QUIZ_SOLVED_TOTAL = None
    SOLVER_DURATION_SECONDS = None
    ACTIVE_SESSIONS = None
    OCR_ACCURACY_RATIO = None
    API_ERRORS_TOTAL = None


def track_solver_latency(quiz_type: str = "general") -> Callable:
    """Decorator to measure and record question solver execution duration."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            start_time = time.perf_counter()
            status = "success"
            try:
                result = func(*args, **kwargs)
                return result
            except Exception:
                status = "error"
                raise
            finally:
                duration = time.perf_counter() - start_time
                if PROMETHEUS_AVAILABLE and SOLVER_DURATION_SECONDS:
                    SOLVER_DURATION_SECONDS.labels(quiz_type=quiz_type).observe(duration)
                if PROMETHEUS_AVAILABLE and QUIZ_SOLVED_TOTAL:
                    QUIZ_SOLVED_TOTAL.labels(quiz_type=quiz_type, status=status).inc()
        return wrapper
    return decorator


def record_solver_result(quiz_type: str, status: str = "success") -> None:
    """Record a completed or failed quiz solve event."""
    if PROMETHEUS_AVAILABLE and QUIZ_SOLVED_TOTAL:
        QUIZ_SOLVED_TOTAL.labels(quiz_type=quiz_type, status=status).inc()


def record_error(error_type: str, component: str = "solver") -> None:
    """Record an operational error in telemetry."""
    if PROMETHEUS_AVAILABLE and API_ERRORS_TOTAL:
        API_ERRORS_TOTAL.labels(error_type=error_type, component=component).inc()


def set_active_sessions(count: int) -> None:
    """Update current active concurrent sessions gauge."""
    if PROMETHEUS_AVAILABLE and ACTIVE_SESSIONS:
        ACTIVE_SESSIONS.set(max(0, count))


def get_metrics_data() -> bytes:
    """Generate and return raw Prometheus format metrics."""
    if PROMETHEUS_AVAILABLE and registry:
        return generate_latest(registry)
    return b"# Prometheus metrics not available\n"


def get_content_type() -> str:
    """Return the Prometheus exposition content type header."""
    return "text/plain; version=0.0.4; charset=utf-8"
