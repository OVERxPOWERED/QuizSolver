import pytest
import re
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_metrics_endpoint_returns_prometheus_format(async_client: AsyncClient):
    """Verify /metrics returns text/plain with expected metric names."""
    response = await async_client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    
    content = response.text
    # Check for standard Prometheus metrics
    assert "quiz_runs_total" in content
    assert "quiz_run_duration_seconds" in content
    assert "http_requests_total" in content
    assert "http_request_duration_seconds" in content


@pytest.mark.asyncio
async def test_quiz_run_increments_counter(async_client: AsyncClient, sample_quiz_request: dict):
    """POST /api/v1/quiz/run and verify quiz_runs_total increases."""
    # Get initial metric value
    initial_response = await async_client.get("/metrics")
    initial_value = _extract_metric_value(initial_response.text, "quiz_runs_total")
    
    # Make a quiz run request
    response = await async_client.post("/api/v1/quiz/run", json=sample_quiz_request)
    assert response.status_code == 200
    
    # Get metric value after request
    after_response = await async_client.get("/metrics")
    after_value = _extract_metric_value(after_response.text, "quiz_runs_total")
    
    # Verify counter increased by 1
    assert after_value == initial_value + 1


@pytest.mark.asyncio
async def test_version_negotiation_accept_header(async_client: AsyncClient, sample_quiz_request: dict):
    """Request with Accept: application/vnd.quizauto.v1+json returns API-Version: v1 header."""
    headers = {"Accept": "application/vnd.quizauto.v1+json"}
    response = await async_client.post("/api/v1/quiz/run", json=sample_quiz_request, headers=headers)
    
    assert response.status_code == 200
    assert response.headers.get("API-Version") == "v1"
    assert "Deprecation" in response.headers


@pytest.mark.asyncio
async def test_version_negotiation_url_path(async_client: AsyncClient, sample_quiz_request: dict):
    """Request to /api/v1/quiz/run works, /api/v2/quiz/run returns 404."""
    # v1 should work
    response_v1 = await async_client.post("/api/v1/quiz/run", json=sample_quiz_request)
    assert response_v1.status_code == 200
    
    # v2 should not exist
    response_v2 = await async_client.post("/api/v2/quiz/run", json=sample_quiz_request)
    assert response_v2.status_code == 404


@pytest.mark.asyncio
async def test_deprecation_header_on_old_version(async_client: AsyncClient, sample_quiz_request: dict):
    """v1 requests include Deprecation header."""
    response = await async_client.post("/api/v1/quiz/run", json=sample_quiz_request)
    
    assert response.status_code == 200
    deprecation_header = response.headers.get("Deprecation")
    assert deprecation_header is not None
    assert deprecation_header == "true"
    # Optionally check for Link header with deprecation info
    link_header = response.headers.get("Link")
    assert link_header is not None
    assert 'rel="deprecation"' in link_header


def _extract_metric_value(metrics_text: str, metric_name: str) -> float:
    """Extract the value of a Prometheus metric from the metrics text."""
    # Pattern matches metric_name{...} value or metric_name value
    pattern = rf'^{metric_name}(?:\{{[^}}]*\}})?\s+(\d+(?:\.\d+)?)\s*$'
    for line in metrics_text.split('\n'):
        line = line.strip()
        if line.startswith('#') or not line:
            continue
        match = re.match(pattern, line)
        if match:
            return float(match.group(1))
    return 0.0