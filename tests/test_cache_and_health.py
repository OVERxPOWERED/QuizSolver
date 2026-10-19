```python
import pytest
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
import json

# Import the modules under test
from src.cache.manager import CacheManager, CacheConfig, CacheEntry
from src.health.endpoints import HealthEndpoints, HealthResponse, ComponentHealth, HealthStatus
from src.health.checks import DatabaseHealthCheck, CacheHealthCheck, BrowserHealthCheck


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def cache_config() -> CacheConfig:
    """Default cache configuration for testing."""
    return CacheConfig(
        default_ttl=300,
        max_ttl=3600,
        key_prefix="test:",
        enable_compression=False,
        serialization="json"
    )


@pytest.fixture
def mock_redis():
    """Mock Redis client with async methods."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.setex = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=1)
    redis.exists = AsyncMock(return_value=0)
    redis.keys = AsyncMock(return_value=[])
    redis.scan = AsyncMock(return_value=(0, []))
    redis.expire = AsyncMock(return_value=True)
    redis.ttl = AsyncMock(return_value=-2)
    redis.ping = AsyncMock(return_value=True)
    redis.close = AsyncMock()
    redis.aclose = AsyncMock()
    return redis


@pytest.fixture
def mock_redis_unavailable():
    """Mock Redis that simulates connection failures."""
    redis = AsyncMock()
    redis.get = AsyncMock(side_effect=ConnectionError("Redis unavailable"))
    redis.set = AsyncMock(side_effect=ConnectionError("Redis unavailable"))
    redis.setex = AsyncMock(side_effect=ConnectionError("Redis unavailable"))
    redis.delete = AsyncMock(side_effect=ConnectionError("Redis unavailable"))
    redis.exists = AsyncMock(side_effect=ConnectionError("Redis unavailable"))
    redis.keys = AsyncMock(side_effect=ConnectionError("Redis unavailable"))
    redis.scan = AsyncMock(side_effect=ConnectionError("Redis unavailable"))
    redis.expire = AsyncMock(side_effect=ConnectionError("Redis unavailable"))
    redis.ttl = AsyncMock(side_effect=ConnectionError("Redis unavailable"))
    redis.ping = AsyncMock(side_effect=ConnectionError("Redis unavailable"))
    redis.close = AsyncMock()
    redis.aclose = AsyncMock()
    return redis


@pytest.fixture
def mock_db_pool():
    """Mock database connection pool."""
    pool = AsyncMock()
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value=1)
    conn.execute = AsyncMock(return_value="OK")
    conn.close = AsyncMock()
    pool.acquire = AsyncMock(return_value=conn)
    pool.release = AsyncMock()
    pool.close = AsyncMock()
    return pool


@pytest.fixture
def mock_db_pool_unhealthy():
    """Mock database pool that simulates failures."""
    pool = AsyncMock()
    pool.acquire = AsyncMock(side_effect=Exception("Database connection failed"))
    return pool


@pytest.fixture
def mock_browser():
    """Mock browser instance."""
    browser = AsyncMock()
    browser.is_connected = True
    browser.new_page = AsyncMock()
    page = AsyncMock()
    page.goto = AsyncMock()
    page.title = AsyncMock(return_value="Test Page")
    page.close = AsyncMock()
    browser.new_page.return_value = page
    browser.close = AsyncMock()
    return browser


@pytest.fixture
def mock_browser_unhealthy():
    """Mock browser that simulates failures."""
    browser = AsyncMock()
    browser.is_connected = False
    browser.new_page = AsyncMock(side_effect=Exception("Browser not available"))
    return browser


@pytest.fixture
async def cache_manager(mock_redis, cache_config):
    """Create CacheManager with mocked Redis."""
    with patch('src.cache.manager.redis.from_url', return_value=mock_redis):
        manager = CacheManager(config=cache_config)
        manager._redis = mock_redis
        yield manager
        await manager.close()


@pytest.fixture
async def cache_manager_no_redis(cache_config):
    """Create CacheManager without Redis (fallback mode)."""
    with patch('src.cache.manager.redis.from_url', side_effect=ConnectionError("No Redis")):
        manager = CacheManager(config=cache_config)
        yield manager
        await manager.close()


@pytest.fixture
def health_endpoints(mock_db_pool, mock_redis, mock_browser):
    """Create HealthEndpoints with mocked dependencies."""
    endpoints = HealthEndpoints(
        db_pool=mock_db_pool,
        cache_manager=AsyncMock(),
        browser=mock_browser
    )
    return endpoints


# ============================================================================
# CACHE MANAGER TESTS
# ============================================================================

class TestCacheManager:
    """Test suite for CacheManager class."""

    @pytest.mark.asyncio
    async def test_set_and_get_basic(self, cache_manager, mock_redis):
        """Test basic set and get operations."""
        key = "test_key"
        value = {"data": "test_value", "number": 42}
        
        await cache_manager.set(key, value)
        mock_redis.setex.assert_called_once()
        
        # Mock the return value for get
        mock_redis.get.return_value = json.dumps(value).encode()
        result = await cache_manager.get(key)
        
        assert result == value
        mock_redis.get.assert_called_once_with(f"test:{key}")

    @pytest.mark.asyncio
    async def test_set_with_custom_ttl(self, cache_manager, mock_redis):
        """Test set with custom TTL."""
        key = "custom_ttl_key"
        value = "custom_value"
        custom_ttl = 600
        
        await cache_manager.set(key, value, ttl=custom_ttl)
        
        # Verify setex was called with custom TTL
        call_args = mock_redis.setex.call_args
        assert call_args[0][1] == custom_ttl  # TTL argument

    @pytest.mark.asyncio
    async def test_ttl_expiration(self, cache_manager, mock_redis):
        """Test TTL expiration behavior."""
        key = "expiring_key"
        value = "expiring_value"
        
        # First call returns value, second returns None (expired)
        mock_redis.get.side_effect = [
            json.dumps(value).encode(),
            None
        ]
        
        await cache_manager.set(key, value, ttl=1)
        result1 = await cache_manager.get(key)
        assert result1 == value
        
        # Simulate expiration
        result2 = await cache_manager.get(key)
        assert result2 is None

    @pytest.mark.asyncio
    async def test_ttl_max_limit(self, cache_manager, mock_redis, cache_config):
        """Test that TTL cannot exceed max_ttl."""
        key = "max_ttl_key"
        value = "value"
        excessive_ttl = 10000  # Greater than max_ttl of 3600
        
        await cache_manager.set