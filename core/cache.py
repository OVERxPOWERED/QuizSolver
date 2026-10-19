```python
"""
Async query caching layer with TTL and invalidation for quiz service optimization.
Uses aiocache with Redis backend (fallback to in-memory).
"""

import logging
import re
from functools import wraps
from typing import Any, Callable, Optional, TypeVar, Union
from urllib.parse import urlparse

from aiocache import Cache, RedisCache, SimpleMemoryCache
from aiocache.serializers import JsonSerializer, PickleSerializer

from config import settings
from utils.logger import log

logger = logging.getLogger(__name__)

T = TypeVar("T")
CacheValue = Union[str, int, float, bool, dict, list, None]


class CacheManager:
    """
    Async cache manager with Redis backend and in-memory fallback.
    Provides TTL-based caching, pattern invalidation, and key builders.
    """

    def __init__(
        self,
        redis_url: Optional[str] = None,
        default_ttl: int = 300,
        key_prefix: str = "quiz:",
        enable_fallback: bool = True,
    ):
        """
        Initialize cache manager.

        Args:
            redis_url: Redis connection URL. If None, uses settings.REDIS_URL
            default_ttl: Default TTL in seconds
            key_prefix: Prefix for all cache keys
            enable_fallback: Whether to fall back to in-memory cache on Redis failure
        """
        self._default_ttl = default_ttl
        self._key_prefix = key_prefix
        self._enable_fallback = enable_fallback
        self._cache: Optional[Cache] = None
        self._redis_url = redis_url or settings.REDIS_URL
        self._is_redis = False
        self._fallback_cache: Optional[SimpleMemoryCache] = None

    async def initialize(self) -> None:
        """Initialize cache backend (Redis with in-memory fallback)."""
        if self._cache is not None:
            return

        # Try Redis first
        try:
            redis_config = self._parse_redis_url(self._redis_url)
            self._cache = RedisCache(
                endpoint=redis_config["host"],
                port=redis_config["port"],
                password=redis_config["password"] or None,
                db=redis_config["db"],
                ssl=redis_config["ssl"],
                serializer=JsonSerializer(),
                namespace=self._key_prefix,
                pool_min_size=5,
                pool_max_size=20,
                timeout=5,
            )
            # Test connection
            await self._cache.ping()
            self._is_redis = True
            log.info("cache_initialized", backend="redis", url=self._redis_url)
        except Exception as e:
            log.warning("redis_connection_failed", error=str(e), fallback=self._enable_fallback)
            if self._enable_fallback:
                await self._init_fallback()
            else:
                raise

    async def _init_fallback(self) -> None:
        """Initialize in-memory fallback cache."""
        self._fallback_cache = SimpleMemoryCache(
            serializer=PickleSerializer(),
            namespace=self._key_prefix,
        )
        self._cache = self._fallback_cache
        self._is_redis = False
        log.info("cache_initialized", backend="memory")

    def _parse_redis_url(self, url: str) -> dict:
        """
        Parse Redis URL into connection parameters.

        Handles formats:
        - redis://host:port
        - redis://:password@host:port
        - redis://:password@host:port/db
        - rediss://host:port (SSL)
        - redis://user:password@host:port/db?ssl=true
        """
        parsed = urlparse(url)

        # Default values
        config = {
            "host": parsed.hostname or "localhost",
            "port": parsed.port or 6379,
            "password": parsed.password,
            "db": 0,
            "ssl": parsed.scheme == "rediss",
        }

        # Extract database number from path
        if parsed.path and len(parsed.path) > 1:
            try:
                config["db"] = int(parsed.path.lstrip("/"))
            except ValueError:
                pass

        # Handle query parameters for SSL
        if parsed.query:
            query_params = dict(q.split("=") for q in parsed.query.split("&") if "=" in q)
            if query_params.get("ssl", "").lower() in ("true", "1", "yes"):
                config["ssl"] = True

        return config

    def _make_key(self, key: str) -> str:
        """Apply prefix to cache key."""
        return f"{self._key_prefix}{key}"

    async def get(self, key: str, default: Any = None) -> Any:
        """
        Get value from cache.

        Args:
            key: Cache key (without prefix)
            default: Default value if key not found

        Returns:
            Cached value or default
        """
        if self._cache is None:
            await self.initialize()

        full_key = self._make_key(key)
        try:
            value = await self._cache.get(full_key, default=default)
            log.debug("cache_get", key=full_key, hit=value is not default)
            return value
        except Exception as e:
            log.error("cache_get_error", key=full_key, error=str(e))
            if self._is_redis and self._enable_fallback and self._fallback_cache:
                return await self._fallback_cache.get(full_key, default=default)
            return default

    async def set(
        self,
        key: str,
        value: CacheValue,
        ttl: Optional[int] = None,
    ) -> bool:
        """
        Set value in cache with TTL.

        Args:
            key: Cache key (without prefix)
            value: Value to cache
            ttl: Time to live in seconds (None uses default)

        Returns:
            True if successful
        """
        if self._cache is None:
            await self.initialize()

        full_key = self._make_key(key)
        effective_ttl = ttl if ttl is not None else self._default_ttl

        try:
            await self._cache.set(full_key, value, ttl=effective_ttl)
            log.debug("cache_set", key=full_key, ttl=effective_ttl)
            return True
        except Exception as e:
            log.error("cache_set_error", key=full_key, error=str(e))
            if self._is_redis and self._enable_fallback and self._fallback_cache:
                return await self._fallback_cache.set(full_key, value, ttl=effective_ttl)
            return False

    async def delete(self, key: str) -> bool:
        """
        Delete a single key from cache.

        Args:
            key: Cache key (without prefix)

        Returns:
            True if key was deleted
        """
        if self._cache is None:
            await self.initialize()

        full_key = self._make_key(key)
        try:
            result = await self._cache.delete(full_key