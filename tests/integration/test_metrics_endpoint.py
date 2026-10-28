import pytest
import re
from httpx import AsyncClient


class TestMetricsEndpoint:
    """Integration tests for /metrics and /healthz endpoints."""

    @pytest.mark.asyncio
    async def test_metrics_endpoint_returns_200(self, client: AsyncClient):
        """GET /metrics returns 200 with correct content-type."""
        response = await client.get("/metrics")
        
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/plain; version=0.0.4; charset=utf-8"

    @pytest.mark.asyncio
    async def test_metrics_contains_expected_metrics(self, client: AsyncClient):
        """Response text includes expected metric names."""
        response = await client.get("/metrics")
        text = response.text
        
        expected_metrics = [
            "quiz_operations_total",
            "ai_solver_duration_seconds",
            "browser_automation_total",
            "cache_hits_total",
            "http_requests_total",
        ]
        
        for metric in expected_metrics:
            assert metric in text, f"Expected metric '{metric}' not found in response"

    @pytest.mark.asyncio
    async def test_metrics_format_is_prometheus_text(self, client: AsyncClient):
        """Validates Prometheus exposition format (HELP/TYPE lines)."""
        response = await client.get("/metrics")
        text = response.text
        
        # Check for HELP lines
        help_lines = re.findall(r'^# HELP (\S+) (.+)$', text, re.MULTILINE)
        assert len(help_lines) > 0, "No HELP lines found in metrics output"
        
        # Check for TYPE lines
        type_lines = re.findall(r'^# TYPE (\S+) (\S+)$', text, re.MULTILINE)
        assert len(type_lines) > 0, "No TYPE lines found in metrics output"
        
        # Verify each metric has both HELP and TYPE
        help_metrics = {name for name, _ in help_lines}
        type_metrics = {name for name, _ in type_lines}
        
        # Core metrics should have both
        core_metrics = {
            "quiz_operations_total",
            "ai_solver_duration_seconds",
            "browser_automation_total",
            "cache_hits_total",
            "http_requests_total",
        }
        
        for metric in core_metrics:
            assert metric in help_metrics, f"Metric '{metric}' missing HELP line"
            assert metric in type_metrics, f"Metric '{metric}' missing TYPE line"
        
        # Validate TYPE values are valid Prometheus types
        valid_types = {"counter", "gauge", "histogram", "summary", "untyped"}
        for _, metric_type in type_lines:
            assert metric_type in valid_types, f"Invalid metric type: {metric_type}"

    @pytest.mark.asyncio
    async def test_healthz_endpoint(self, client: AsyncClient):
        """GET /healthz returns 200 with {'status': 'ok'}."""
        response = await client.get("/healthz")
        
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/json"
        
        data = response.json()
        assert data == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_metrics_increment_on_request(self, client: AsyncClient):
        """Make request to quiz endpoint, verify http_requests_total increments."""
        # Get initial metrics
        initial_response = await client.get("/metrics")
        initial_text = initial_response.text
        
        # Extract initial http_requests_total value
        initial_count = self._extract_metric_value(initial_text, "http_requests_total")
        
        # Make a request to a quiz endpoint (assuming /api/quiz exists)
        # Use a simple GET that should be handled even if it returns 404
        await client.get("/api/quiz")
        
        # Get metrics again
        final_response = await client.get("/metrics")
        final_text = final_response.text
        
        # Extract final http_requests_total value
        final_count = self._extract_metric_value(final_text, "http_requests_total")
        
        # Verify increment (at least 1 for our request, possibly more for /metrics calls)
        assert final_count > initial_count, (
            f"http_requests_total did not increment: {initial_count} -> {final_count}"
        )

    def _extract_metric_value(self, text: str, metric_name: str) -> float:
        """Extract the value of a metric from Prometheus text format."""
        # Match metric lines (not HELP/TYPE comments)
        pattern = rf'^{re.escape(metric_name)}(?:\{{[^}}]*\}})?\s+(\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)$'
        matches = re.findall(pattern, text, re.MULTILINE)
        
        if not matches:
            # Try with labels pattern
            pattern = rf'^{re.escape(metric_name)}\{{[^}}]*\}}\s+(\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)$'
            matches = re.findall(pattern, text, re.MULTILINE)
        
        if not matches:
            return 0.0
        
        # Sum all instances (in case of multiple label combinations)
        return sum(float(m) for m in matches)
```
```markdown
# ROADMAP_PROGRESS.md

# Roadmap Progress Tracking

## Checkpoint History

| Date | Phase | Task | Status | Notes |
|------|-------|------|--------|-------|
| 2025-01-15 | Foundation | Project scaffolding & CI/CD | ✅ Complete | FastAPI + pytest + ruff + mypy configured |
| 2025-01-20 | Core Features | Quiz generation API | ✅ Complete | CRUD endpoints with validation |
| 2025-01-25 | Core Features | AI solver integration | ✅ Complete | OpenAI + Anthropic providers with fallback |
| 2025-02-01 | Core Features | Browser automation | ✅ Complete | Playwright-based extraction with caching |
| 2025-02-10 | Monitoring & Observability | Prometheus metrics export | 🔄 In Progress | `/metrics` and `/healthz` endpoints implemented; integration tests added |
| 2025-02-15 | Monitoring & Observability | Grafana dashboards | ⏳ Planned | Dashboard JSON definitions for quiz ops, AI latency, browser automation |
| 2025-02-20 | Monitoring & Observability | Alerting rules | ⏳ Planned | PrometheusRule for error rates, latency p99, cache hit ratio |
| 2025-02-25 | Production Hardening | Load testing & chaos | ⏳ Planned | k6 scripts, LitmusChaos experiments |
| 2025-03-01 | Production Hardening | Documentation & runbooks | ⏳ Planned | API docs, operational runbooks, incident response |

## Current Focus: Monitoring & Observability

**Objective**: Integrate Prometheus metrics export and Grafana dashboards for real-time service health visualization.

**Progress This Period**:
- ✅ Implemented `/metrics` endpoint with Prometheus client library
- ✅ Implemented `/healthz` endpoint for Kubernetes liveness/readiness probes
- ✅ Added core metrics: `quiz_operations_total`, `ai_solver_duration_seconds`, `browser_automation_total`, `cache_hits_total`, `http_requests_total`
- ✅ Created integration tests validating Prometheus exposition format, metric presence, and counter increments
- 🔄 Next: Grafana dashboard provisioning and alerting rules

**Metrics Coverage**:
| Metric | Type | Description |
|--------|------|-------------|
| `quiz_operations_total` | Counter | Total quiz CRUD operations by type and status |
| `ai_solver_duration_seconds` | Histogram | AI solver latency by provider and model |
| `browser_automation_total` | Counter | Browser automation runs by outcome |
| `cache_hits_total` | Counter | Cache hits/misses by namespace |
| `http_requests_total` | Counter | HTTP requests by method, path, status |

**Blockers**: None