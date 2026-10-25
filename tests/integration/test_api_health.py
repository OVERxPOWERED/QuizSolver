import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch
from src.api.health import HealthResponse
from src.main import app


@pytest.fixture
def test_client():
    with TestClient(app) as client:
        yield client


@pytest.fixture
def mock_database_manager():
    with patch("src.api.health.get_database_manager") as mock:
        manager = AsyncMock()
        mock.return_value = manager
        yield manager


@pytest.fixture
def mock_browser_manager():
    with patch("src.api.health.get_browser_manager") as mock:
        manager = AsyncMock()
        mock.return_value = manager
        yield manager


@pytest.fixture
def mock_ai_solver():
    with patch("src.api.health.get_ai_solver") as mock:
        solver = AsyncMock()
        mock.return_value = solver
        yield solver


class TestHealthEndpoints:
    def test_all_healthy_returns_200_with_connected_status(
        self, test_client, mock_database_manager, mock_browser_manager, mock_ai_solver
    ):
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
        HealthResponse(**data)

    def test_database_failure_returns_503_with_disconnected(
        self, test_client, mock_database_manager, mock_browser_manager, mock_ai_solver
    ):
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

    def test_browser_failure_returns_503_with_disconnected(
        self, test_client, mock_database_manager, mock_browser_manager, mock_ai_solver
    ):
        mock_database_manager.health_check.return_value = True
        mock_browser_manager.health_check.return_value = False
        mock_ai_solver.health_check.return_value = True

        response = test_client.get("/health")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["dependencies"]["database"] == "connected"
        assert data["dependencies"]["browser"] == "disconnected"
        assert data["dependencies"]["ai"] == "connected"
        HealthResponse(**data)

    def test_ai_failure_returns_503_with_disconnected(
        self, test_client, mock_database_manager, mock_browser_manager, mock_ai_solver
    ):
        mock_database_manager.health_check.return_value = True
        mock_browser_manager.health_check.return_value = True
        mock_ai_solver.health_check.return_value = False

        response = test_client.get("/health")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["dependencies"]["database"] == "connected"
        assert data["dependencies"]["browser"] == "connected"
        assert data["dependencies"]["ai"] == "disconnected"
        HealthResponse(**data)
