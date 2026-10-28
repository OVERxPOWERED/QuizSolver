from fastapi import APIRouter, Response
from prometheus_client import generate_latest

from core.metrics import REGISTRY

api_router = APIRouter()


@api_router.get("/metrics")
async def metrics() -> Response:
    """Expose Prometheus metrics for scraping."""
    return Response(
        content=generate_latest(REGISTRY),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@api_router.get("/healthz")
async def healthz() -> dict:
    """Kubernetes liveness probe endpoint."""
    return {"status": "ok"}