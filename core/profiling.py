```python
"""
Performance profiling utilities with async context managers for hot path measurement,
database query timing, and cache hit/miss tracking.
"""

import time
import functools
import statistics
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, TypeVar, AsyncGenerator
from collections import defaultdict

from utils.logger import get_logger

logger = get_logger(__name__)

try:
    from core.telemetry import get_metrics_collector
except ImportError:
    get_metrics_collector = None


T = TypeVar("T")


@dataclass
class ProfileResult:
    """Result of a profiling operation."""
    name: str
    duration_ns: int
    success: bool
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        return self.duration_ns / 1_000_000

    @property
    def duration_us(self) -> float:
        return self.duration_ns / 1_000


@dataclass
class PercentileStats:
    """Percentile statistics for a set of measurements."""
    count: int
    p50: float
    p95: float
    p99: float
    min: float
    max: float
    mean: float
    unit: str = "ms"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "count": self.count,
            "p50": round(self.p50, 3),
            "p95": round(self.p95, 3),
            "p99": round(self.p99, 3),
            "min": round(self.min, 3),
            "max": round(self.max, 3),
            "mean": round(self.mean, 3),
            "unit": self.unit,
        }


class ProfilingMiddleware:
    """
    Middleware for profiling hot paths with async context managers.
    
    Provides nanosecond-precision timing for database queries, cache operations,
    API endpoints, and arbitrary async functions.
    """

    def __init__(self, service_name: str = "api"):
        self.service_name = service_name
        self._db_query_times: Dict[str, List[int]] = defaultdict(list)
        self._cache_op_times: Dict[str, List[int]] = defaultdict(list)
        self._api_endpoint_times: Dict[str, List[int]] = defaultdict(list)
        self._function_times: Dict[str, List[int]] = defaultdict(list)
        self._metrics_collector = get_metrics_collector() if get_metrics_collector else None

    @asynccontextmanager
    async def profile_db_query(self, query_name: str) -> AsyncGenerator[None, None]:
        """
        Profile a database query execution.
        
        Args:
            query_name: Identifier for the query (e.g., "user_lookup", "order_insert")
            
        Yields:
            None - use as async context manager
            
        Example:
            async with profiler.profile_db_query("user_lookup"):
                await db.execute("SELECT * FROM users WHERE id = ?", user_id)
        """
        start_ns = time.perf_counter_ns()
        success = False
        error: Optional[Exception] = None
        
        try:
            yield
            success = True
        except Exception as e:
            error = e
            success = False
            raise
        finally:
            duration_ns = time.perf_counter_ns() - start_ns
            self._db_query_times[query_name].append(duration_ns)
            
            result = ProfileResult(
                name=f"db.{query_name}",
                duration_ns=duration_ns,
                success=success,
                metadata={"error": str(error)} if error else {}
            )
            
            self._record_metric(result)
            logger.debug(
                "db_query_profiled",
                query=query_name,
                duration_ms=result.duration_ms,
                success=success,
            )

    @asynccontextmanager
    async def profile_cache_operation(self, op_name: str) -> AsyncGenerator[None, None]:
        """
        Profile a cache operation (get, set, delete, etc.).
        
        Args:
            op_name: Operation identifier (e.g., "get", "set", "delete", "mget")
            
        Yields:
            None - use as async context manager
            
        Example:
            async with profiler.profile_cache_operation("get"):
                value = await cache.get(key)
        """
        start_ns = time.perf_counter_ns()
        success = False
        hit = False
        error: Optional[Exception] = None
        
        try:
            yield
            success = True
        except Exception as e:
            error = e
            success = False
            raise
        finally:
            duration_ns = time.perf_counter_ns() - start_ns
            self._cache_op_times[op_name].append(duration_ns)
            
            result = ProfileResult(
                name=f"cache.{op_name}",
                duration_ns=duration_ns,
                success=success,
                metadata={"hit": hit, "error": str(error)} if error else {"hit": hit}
            )
            
            self._record_metric(result)
            logger.debug(
                "cache_operation_profiled",
                operation=op_name,
                duration_ms=result.duration_ms,
                success=success,
                hit=hit,
            )

    @asynccontextmanager
    async def profile_api_endpoint(self, endpoint_name: str) -> AsyncGenerator[None, None]:
        """
        Profile an API endpoint execution.
        
        Args:
            endpoint_name: Endpoint identifier (e.g., "GET /api/users", "POST /api/orders")
            
        Yields:
            None - use as async context manager
            
        Example:
            async with profiler.profile_api_endpoint("GET /api/users"):
                return await handle_request(request)
        """
        start_ns = time.perf_counter_ns()
        success = False
        status_code: Optional[int] = None
        error: Optional[Exception] = None
        
        try:
            yield
            success = True
        except Exception as e:
            error = e
            success = False
            raise
        finally:
            duration_ns = time.perf_counter_ns() - start_ns
            self._api_endpoint_times[endpoint_name].append(duration_ns)
            
            result = ProfileResult(
                name=f"api.{endpoint_name}",
                duration_ns=duration_ns,
                success=success,
                metadata={
                    "status_code": status_code,
                    "error": str(error)
                } if error else {"status_code": status_code}
            )
            
            self._record_metric(result)
            logger.info(
                "api_endpoint_profiled",
                endpoint=endpoint_name,
                duration_ms=result.duration_ms,
                success=success,
                status_code=status_code,
            )

    def profile_async(self, name: Optional[str] = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """
        Decorator for automatic async function profiling.
        
        Args:
            name: Optional custom name for the profile. Defaults to function qualified name