import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch
from src.api.health import router as health_router
from src.core.database import DatabaseManager
from src.core.browser import BrowserManager
from src.core.ai_solver import AISolver
from src.main import app
from src.api.health import HealthResponse, DependencyStatus


@pytest.fixture
def test_client():
    """Create a test client with the health router included."""
    with TestClient(app) as client:
        yield client


@pytest.fixture
def mock_database_manager():
    """Mock DatabaseManager with configurable health check."""
    with patch("src.api.health.get_database_manager") as mock:
        manager = AsyncMock(spec=DatabaseManager)
        mock.return_value = manager
        yield manager


@pytest.fixture
def mock_browser_manager():
    """Mock BrowserManager with configurable health check."""
    with patch("src.api.health.get_browser_manager") as mock:
        manager = AsyncMock(spec=BrowserManager)
        mock.return_value = manager
        yield manager


@pytest.fixture
def mock_ai_solver():
    """Mock AISolver with configurable health check."""
    with patch("src.api.health.get_ai_solver") as mock:
        solver = AsyncMock(spec=AISolver)
        mock.return_value = solver
        yield solver


class TestHealthEndpoints:
    """Integration tests for health check endpoints."""

    def test_all_healthy_returns_200_with_connected_status(
        self, test_client, mock_database_manager, mock_browser_manager, mock_ai_solver
    ):
        """Test all dependencies healthy returns 200 with all 'connected'."""
        mock_database_manager.health_check.return_value = True
        mock_browser_manager.health_check.return_value = True
        mock_ai_solver.health_check.return_value = True

        response = test_client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["dependencies"]["database"] == "connected"
        assert data["dependencies"]["browser"] == "connected"
        assert data["dependencies"]["ai"] == "connected"
        HealthResponse(**data)  # Validate schema

    def test_database_failure_returns_503_with_disconnected(
        self, test_client, mock_database_manager, mock_browser_manager, mock_ai_solver
    ):
        """Test database failure returns 503 with database 'disconnected'."""
        mock_database_manager.health_check.return_value = False
        mock_browser_manager.health_check.return_value = True
        mock_ai_solver.health_check.return_value = True

        response = test_client.get("/health")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["dependencies"]["database"] == "disconnected"
        assert data["dependencies"]["browser"] == "connected"
        assert data["dependencies"]["ai"] == "connected"
        HealthResponse(**data)

    def test_browser_not_installed_returns_503_with_unavailable(
        self, test_client, mock_database_manager, mock_browser_manager, mock_ai_solver
    ):
        """Test browser not installed returns 503 with browser 'unavailable'."""
        mock_database_manager.health_check.return_value = True
        mock_browser_manager.health_check.side_effect = FileNotFoundError("Browser not installed")
        mock_ai_solver.health_check.return_value = True

        response = test_client.get("/health")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["dependencies"]["database"] == "connected"
        assert data["dependencies"]["browser"] == "unavailable"
        assert data["dependencies"]["ai"] == "connected"
        HealthResponse(**data)

    def test_ai_misconfigured_returns_200_with_degraded(
        self, test_client, mock_database_manager, mock_browser_manager, mock_ai_solver
    ):
        """Test AI misconfigured returns 200 with ai 'degraded' (non-blocking)."""
        mock_database_manager.health_check.return_value = True
        mock_browser_manager.health_check.return_value = True
        mock_ai_solver.health_check.return_value = False

        response = test_client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["dependencies"]["database"] == "connected"
        assert data["dependencies"]["browser"] == "connected"
        assert data["dependencies"]["ai"] == "degraded"
        HealthResponse(**data)

    def test_readiness_endpoint_all_healthy(
        self, test_client, mock_database_manager, mock_browser_manager, mock_ai_solver
    ):
        """Test readiness endpoint returns 200 when all critical deps healthy."""
        mock_database_manager.health_check.return_value = True
        mock_browser_manager.health_check.return_value = True
        mock_ai_solver.health_check.return_value = True

        response = test_client.get("/health/ready")

        assert response.status_code == 200
        data = response.json()
        assert data["ready"] is True
        assert data["dependencies"]["database"] == "connected"
        assert data["dependencies"]["browser"] == "connected"

    def test_readiness_endpoint_database_down(
        self, test_client, mock_database_manager, mock_browser_manager, mock_ai_solver
    ):
        """Test readiness endpoint returns 503 when database down."""
        mock_database_manager.health_check.return_value = False
        mock_browser_manager.health_check.return_value = True
        mock_ai_solver.health_check.return_value = True

        response = test_client.get("/health/ready")

        assert response.status_code == 503
        data = response.json()
        assert data["ready"] is False
        assert data["dependencies"]["database"] == "disconnected"

    def test_liveness_endpoint_always_returns_200(self, test_client):
        """Test liveness endpoint always returns 200."""
        response = test_client.get("/health/live")

        assert response.status_code == 200
        data = response.json()
        assert data["alive"] is True