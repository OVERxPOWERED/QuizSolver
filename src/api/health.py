import time
from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from core.database import DatabaseManager
from core.browser import BrowserManager
from core.ai_solver import AISolver
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


async def check_browser(browser: BrowserManager) -> DependencyHealth:
    start = time.perf_counter()
    try:
        is_ready = await browser.verify_installation()
        latency = (time.perf_counter() - start) * 1000
        if is_ready:
            return DependencyHealth(
                name="browser",
                status="healthy",
                latency_ms=round(latency, 2),
                details={"playwright": "installed", "browsers": "available"}
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


async def check_ai(ai: AISolver) -> DependencyHealth:
    start = time.perf_counter()
    try:
        config_valid = ai.validate_configuration()
        latency = (time.perf_counter() - start) * 1000
        if config_valid:
            return DependencyHealth(
                name="ai",
                status="healthy",
                latency_ms=round(latency, 2),
                details={"provider": ai.provider, "model": ai.model}
            )
        else:
            return DependencyHealth(
                name="ai",
                status="degraded",
                latency_ms=round(latency, 2),
                details={"provider": ai.provider, "model": ai.model},
                error="API key not configured or invalid"
            )
    except Exception as e:
        latency = (time.perf_counter() - start) * 1000
        return DependencyHealth(
            name="ai",
            status="unhealthy",
            latency_ms=round(latency, 2),
            error=str(e)
        )


def get_database() -> DatabaseManager:
    from core.database import get_database_manager
    return get_database_manager()


def get_browser() -> BrowserManager:
    from core.browser import get_browser_manager
    return get_browser_manager()


def get_ai() -> AISolver:
    from core.ai_solver import get_ai_solver
    return get_ai_solver()


@router.get("", response_model=HealthResponse)
async def health_check(
    db: DatabaseManager = Depends(get_database),
    browser: BrowserManager = Depends(get_browser),
    ai: AISolver = Depends(get_ai)
) -> HealthResponse:
    start = time.perf_counter()
    
    db_health, browser_health, ai_health = await asyncio.gather(
        check_database(db),
        check_browser(browser),
        check_ai(ai)
    )
    
    dependencies = {
        "database": db_health,
        "browser": browser_health,
        "ai": ai_health
    }
    
    statuses = [d.status for d in dependencies.values()]
    if all(s == "healthy" for s in statuses):
        overall_status = "healthy"
    elif any(s == "unhealthy" for s in statuses):
        overall_status = "unhealthy"
    else:
        overall_status = "degraded"
    
    total_latency = (time.perf_counter() - start) * 1000
    
    return HealthResponse(
        status=overall_status,
        timestamp=time.time(),
        total_latency_ms=round(total_latency, 2),
        dependencies=dependencies
    )


@router.get("/detailed", response_model=DetailedHealthResponse)
async def detailed_health_check(
    db: DatabaseManager = Depends(get_database),
    browser: BrowserManager = Depends(get_browser),
    ai: AISolver = Depends(get_ai)
) -> DetailedHealthResponse:
    start = time.perf_counter()
    
    db_health, browser_health, ai_health = await asyncio.gather(
        check_database(db),
        check_browser(browser),
        check_ai(ai)
    )
    
    dependencies = {
        "database": db_health,
        "browser": browser_health,
        "ai": ai_health
    }
    
    statuses = [d.status for d in dependencies.values()]
    if all(s == "healthy" for s in statuses):
        overall_status = "healthy"
    elif any(s == "unhealthy" for s in statuses):
        overall_status = "unhealthy"
    else:
        overall_status = "degraded"
    
    total_latency = (time.perf_counter() - start) * 1000
    
    settings = get_settings()
    
    system_info = {
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "platform": sys.platform,
    }
    
    configuration = {
        "database_url": settings.database_url.split("@")[-1] if "@" in settings.database_url else "configured",
        "browser_headless": settings.browser_headless,
        "ai_provider": settings.ai_provider,
        "ai_model": settings.ai_model,
        "log_level": settings.log_level,
    }
    
    return DetailedHealthResponse(
        status=overall_status,
        timestamp=time.time(),
        total_latency_ms=round(total_latency, 2),
        dependencies=dependencies,
        system_info=system_info,
        configuration=configuration
    )


import asyncio
import sys