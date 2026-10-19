import time
import asyncio
import shutil
import platform
import sys
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from core.database import DatabaseManager
from core.browser import BrowserManager
from core.ai_solver import AISolver
from core.cache import CacheManager
from config import get_settings


router = APIRouter(prefix="/health", tags=["health"])


class DependencyHealth(BaseModel):
    name: str
    status: str = Field(..., pattern="^(healthy|unhealthy|degraded)$")
    latency_ms: float
    details: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class HealthResponse(BaseModel):
    status: str = Field(..., pattern="^(healthy|unhealthy|degraded)$")
    timestamp: float
    total_latency_ms: float
    dependencies: Dict[str, DependencyHealth]


class DetailedHealthResponse(HealthResponse):
    system_info: Dict[str, Any]
    configuration: Dict[str, Any]


async def run_with_timeout(coro, timeout_seconds: float = 5.0) -> Any:
    """Run a coroutine with a timeout guard."""
    try:
        return await asyncio.wait_for(coro, timeout=timeout_seconds)
    except asyncio.TimeoutError:
        raise Exception(f"Health check timed out after {timeout_seconds} seconds")


async def check_database(db: DatabaseManager) -> DependencyHealth:
    start = time.perf_counter()
    try:
        async with db.get_session() as session:
            await session.execute("SELECT 1")
        latency = (time.perf_counter() - start) * 1000
        return DependencyHealth(
            name="database",
            status="healthy",
            latency_ms=round(latency, 2),
            details={"query": "SELECT 1"}
        )
    except Exception as e:
        latency = (time.perf_counter() - start) * 1000
        return DependencyHealth(
            name="database",
            status="unhealthy",
            latency_ms=round(latency, 2),
            error=str(e)
        )


async def check_cache(cache: CacheManager) -> DependencyHealth:
    start = time.perf_counter()
    try:
        # Test cache connectivity and get stats
        await cache.ping()
        stats = await cache.get_stats()
        latency = (time.perf_counter() - start) * 1000
        hit_rate = stats.get("hit_rate", 0)
        status = "healthy"
        if hit_rate < 0.5:  # arbitrary threshold for degraded
            status = "degraded"
        return DependencyHealth(
            name="cache",
            status=status,
            latency_ms=round(latency, 2),
            details={
                "hit_rate": hit_rate,
                "miss_rate": stats.get("miss_rate", 0),
                "keys": stats.get("keys", 0),
                "memory_usage": stats.get("memory_usage", "unknown")
            }
        )
    except Exception as e:
        latency = (time.perf_counter() - start) * 1000
        return DependencyHealth(
            name="cache",
            status="unhealthy",
            latency_ms=round(latency, 2),
            error=str(e)
        )


async def check_browser(browser: BrowserManager) -> DependencyHealth:
    start = time.perf_counter()
    try:
        is_ready = await browser.verify_installation()
        pool_status = await browser.get_pool_status()
        latency = (time.perf_counter() - start) * 1000
        if is_ready and pool_status.get("available", 0) > 0:
            return DependencyHealth(
                name="browser",
                status="healthy",
                latency_ms=round(latency, 2),
                details={
                    "playwright": "installed",
                    "browsers": "available",
                    "pool": pool_status
                }
            )
        elif is_ready:
            return DependencyHealth(
                name="browser",
                status="degraded",
                latency_ms=round(latency, 2),
                details={
                    "playwright": "installed",
                    "browsers": "available",
                    "pool": pool_status
                },
                error="No available browser instances in pool"
            )
        else:
            return DependencyHealth(
                name="browser",
                status="degraded",
                latency_ms=round(latency, 2),
                details={"playwright": "installed", "browsers": "missing"},
                error="Browser binaries not found, run 'playwright install'"
            )
    except Exception as e:
        latency = (time.perf_counter() - start) * 1000
        return DependencyHealth(
            name="browser",
            status="unhealthy",
            latency_ms=round(latency, 2),
            error=str(e)
        )


async def check_ai_s