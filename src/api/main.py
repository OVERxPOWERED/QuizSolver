from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse
import time

from src.api.routes import api_router
from src.core.metrics import (
    metrics_registry,
    http_requests_total,
    http_request_duration_seconds,
    initialize_metrics,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_metrics()
    yield


app = FastAPI(
    title="Trading Platform API",
    description="High-frequency trading platform with real-time market data and order execution",
    version="1.0.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start_time = time.perf_counter()
    method = request.method
    path = request.url.path

    try:
        response: Response = await call_next(request)
        status_code = response.status_code
    except Exception as exc:
        status_code = 500
        raise
    finally:
        duration = time.perf_counter() - start_time
        http_requests_total.labels(method=method, endpoint=path, status=str(status_code)).inc()
        http_request_duration_seconds.labels(method=method, endpoint=path).observe(duration)

    return response


app.include_router(api_router)


@app.get("/metrics", response_class=PlainTextResponse, include_in_schema=False)
async def metrics_endpoint():
    return PlainTextResponse(content=metrics_registry.generate_latest(), media_type="text/plain; version=0.0.4; charset=utf-8")