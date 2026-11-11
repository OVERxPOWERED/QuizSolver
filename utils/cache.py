```python
"""
Async query caching layer with TTL and invalidation for quiz service optimization.
Uses aiocache with Redis backend (fallback to in-memory).
Enhanced with cache warming, TTL optimization, LRU eviction, and batch operations.
"""

import asyncio
import logging
import re
import time
from collections import OrderedDict
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, TypeVar, Union
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
    Provides TTL-based caching, pattern invalidation, key builders,
    cache warming, TTL optimization, LRU eviction, and batch operations.
    """

    def __init__(
        self,
        redis_url: Optional[str] = None,
        default_ttl: int = 300,
        key_prefix: str = "quiz:",
        enable_fallback: bool = True,
        max_size: Optional[int] = None,
    ):
        """
        Initialize cache manager.

        Args:
            redis_url: Redis connection URL. If None, uses settings.REDIS_URL
            default_ttl: Default TTL in seconds
            key_prefix: Prefix for all cache keys
            enable_fallback: Whether to fall back to in-memory cache on Redis failure
            max_size: Maximum cache size for LRU eviction (uses config.CACHE_MAX_SIZE if None)
        """
        self._default_ttl = default_ttl
        self._key_prefix = key_prefix
        self._enable_fallback = enable_fallback
        self._max_size = max_size or getattr(settings, "CACHE_MAX_SIZE", 10000)
        self._cache: Optional[Cache] = None
        self._redis_url = redis_url or settings.REDIS_URL
        self._is_redis = False
        self._fallback_cache: Optional[SimpleMemoryCache] = None

        # TTL policies: pattern -> ttl
        self._ttl_policies: Dict[str, int] = {}
        self._ttl_policies_lock = asyncio.Lock()

        # Hit/miss tracking
        self._hits = 0
        self._misses = 0
        self._stats_lock = asyncio.Lock()

        # LRU tracking for in-memory fallback
        self._lru_cache: OrderedDict[str, float] = OrderedDict()
        self._lru_lock = asyncio.Lock()

        # Batch operation locks
        self._batch_lock = asyncio.Lock()

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

        # Handle query parameters (e.g., ?ssl=true)
        if parsed.query:
            query_params = dict(q.split("=") for q in parsed.query.split("&") if "=" in q)
            if query_params.get("ssl", "").lower() == "true":
                config["ssl"] = True

        return config

    def _build_key(self, key: str) -> str:
        """Build full cache key with prefix."""
        return f"{self._key_prefix}{key}"

    def _match_ttl_policy(self, key: str) -> Optional[int]:
        """Match key against TTL policies and return TTL if matched."""
        for pattern, ttl in self._ttl_policies.items():
            if re.match(pattern, key):
                return ttl
        return None

    async def get(self, key: str, default: Any = None) -> Any:
        """
        Get value from cache with hit/miss tracking.

        Args:
            key: Cache key
            default: Default value if key not found

        Returns:
            Cached value or default
        """
        if self._cache is None:
            await self.initialize()

        full_key = self._build_key(key)
        try:
            value = await self._cache.get(full_key, default=default)
            async with self._stats_lock:
                if value is not default:
                    self._hits += 1
                    await self._update_lru(full_key)
                else:
                    self._misses += 1
            return value
        except Exception as e:
            log.error("cache_get_error", key=key, error=str(e))
            async with self._stats_lock:
                self._misses += 1
            return