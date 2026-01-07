"""Cache engine factory and global instance management."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from .base import CacheBackend
from .memory import MemoryCacheBackend

logger = logging.getLogger(__name__)


class CacheEngine:
    """Central cache engine that manages backend lifecycle."""

    def __init__(self, redis_url: Optional[str] = None):
        """Initialize cache engine.

        Args:
            redis_url: Redis connection URL. If not provided,
                      uses SAM_REDIS_URL env var or defaults to in-memory.
        """
        self._redis_url = redis_url or os.getenv("SAM_REDIS_URL")
        self._backend: Optional[CacheBackend] = None
        self._initialized = False
        self._lock = asyncio.Lock()

    @property
    def backend_type(self) -> str:
        """Get the type of cache backend."""
        if self._redis_url:
            return "redis"
        return "memory"

    async def initialize(self) -> None:
        """Initialize the cache backend."""
        if self._initialized:
            return

        async with self._lock:
            if self._initialized:
                return

            if self._redis_url:
                # Use Redis for production
                from .redis import RedisCacheBackend

                self._backend = RedisCacheBackend(
                    redis_url=self._redis_url,
                    prefix=os.getenv("SAM_CACHE_PREFIX", "sam:"),
                    default_ttl=int(os.getenv("SAM_CACHE_DEFAULT_TTL", "3600")),
                )
            else:
                # Use in-memory for development
                max_size = int(os.getenv("SAM_CACHE_MAX_SIZE", "10000"))
                self._backend = MemoryCacheBackend(max_size=max_size)

            await self._backend.initialize()
            self._initialized = True

            logger.info(f"Cache engine initialized: {self.backend_type}")

    async def close(self) -> None:
        """Close the cache backend."""
        if self._backend:
            await self._backend.close()
            self._backend = None
            self._initialized = False

    @property
    def backend(self) -> CacheBackend:
        """Get the cache backend (must be initialized first)."""
        if not self._backend:
            raise RuntimeError("Cache engine not initialized. Call initialize() first.")
        return self._backend

    # Delegate common methods

    async def get(self, key: str):
        """Get a value from cache."""
        if not self._initialized:
            await self.initialize()
        return await self.backend.get(key)

    async def set(self, key: str, value, ttl: Optional[int] = None):
        """Set a value in cache."""
        if not self._initialized:
            await self.initialize()
        return await self.backend.set(key, value, ttl)

    async def delete(self, key: str):
        """Delete a value from cache."""
        if not self._initialized:
            await self.initialize()
        return await self.backend.delete(key)

    async def get_or_set(self, key: str, factory, ttl: Optional[int] = None):
        """Get value from cache or compute and cache it."""
        if not self._initialized:
            await self.initialize()
        return await self.backend.get_or_set(key, factory, ttl)


# Global cache instance
_cache: Optional[CacheEngine] = None
_cache_lock: Optional[asyncio.Lock] = None


def _get_cache_lock() -> asyncio.Lock:
    """Get or create the cache initialization lock."""
    global _cache_lock
    if _cache_lock is None:
        _cache_lock = asyncio.Lock()
    return _cache_lock


async def get_cache(redis_url: Optional[str] = None) -> CacheEngine:
    """Get the global cache engine instance.

    Args:
        redis_url: Optional Redis URL (only used on first call)

    Returns:
        Initialized CacheEngine instance
    """
    global _cache

    if _cache is not None and _cache._initialized:
        return _cache

    lock = _get_cache_lock()
    async with lock:
        if _cache is not None and _cache._initialized:
            return _cache

        _cache = CacheEngine(redis_url)
        await _cache.initialize()
        return _cache


async def cleanup_cache() -> None:
    """Cleanup the global cache engine."""
    global _cache, _cache_lock

    if _cache:
        await _cache.close()
        _cache = None
    _cache_lock = None
