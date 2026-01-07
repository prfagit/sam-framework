"""In-memory cache backend for development and testing."""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .base import CacheBackend, CacheStats

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Single cache entry with optional expiration."""

    value: Any
    expires_at: Optional[float] = None  # Unix timestamp

    def is_expired(self) -> bool:
        """Check if entry has expired."""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at


class MemoryCacheBackend(CacheBackend):
    """Thread-safe in-memory cache with TTL support.

    Suitable for single-process deployments and development.
    For multi-process/distributed deployments, use Redis.
    """

    def __init__(self, max_size: int = 10000):
        """Initialize memory cache.

        Args:
            max_size: Maximum number of entries (LRU eviction when exceeded)
        """
        self._max_size = max_size
        self._cache: Dict[str, CacheEntry] = {}
        self._access_order: list[str] = []  # For LRU tracking
        self._lock = asyncio.Lock()
        self._hits = 0
        self._misses = 0
        self._cleanup_task: Optional[asyncio.Task] = None

    async def initialize(self) -> None:
        """Start background cleanup task."""
        logger.info(f"Initializing in-memory cache (max_size: {self._max_size})")
        self._start_cleanup_task()

    async def close(self) -> None:
        """Stop cleanup task."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        self._cache.clear()
        self._access_order.clear()
        logger.info("In-memory cache closed")

    def _start_cleanup_task(self) -> None:
        """Start periodic cleanup of expired entries."""
        try:
            asyncio.get_running_loop()
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
        except RuntimeError:
            pass

    async def _periodic_cleanup(self) -> None:
        """Periodically remove expired entries."""
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute
                await self._cleanup_expired()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cache cleanup: {e}")

    async def _cleanup_expired(self) -> int:
        """Remove all expired entries."""
        async with self._lock:
            expired_keys = [key for key, entry in self._cache.items() if entry.is_expired()]
            for key in expired_keys:
                del self._cache[key]
                if key in self._access_order:
                    self._access_order.remove(key)

            if expired_keys:
                logger.debug(f"Cleaned up {len(expired_keys)} expired cache entries")

            return len(expired_keys)

    def _evict_lru(self) -> None:
        """Evict least recently used entries if over max size."""
        while len(self._cache) >= self._max_size and self._access_order:
            lru_key = self._access_order.pop(0)
            if lru_key in self._cache:
                del self._cache[lru_key]

    def _touch(self, key: str) -> None:
        """Update access order for LRU tracking."""
        if key in self._access_order:
            self._access_order.remove(key)
        self._access_order.append(key)

    async def get(self, key: str) -> Optional[Any]:
        """Get a value from the cache."""
        async with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._misses += 1
                return None

            if entry.is_expired():
                del self._cache[key]
                if key in self._access_order:
                    self._access_order.remove(key)
                self._misses += 1
                return None

            self._hits += 1
            self._touch(key)
            return entry.value

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set a value in the cache."""
        async with self._lock:
            # Evict if necessary
            if key not in self._cache:
                self._evict_lru()

            expires_at = time.time() + ttl if ttl else None
            self._cache[key] = CacheEntry(value=value, expires_at=expires_at)
            self._touch(key)

    async def delete(self, key: str) -> bool:
        """Delete a value from the cache."""
        async with self._lock:
            if key in self._cache:
                del self._cache[key]
                if key in self._access_order:
                    self._access_order.remove(key)
                return True
            return False

    async def exists(self, key: str) -> bool:
        """Check if a key exists and is not expired."""
        async with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return False
            if entry.is_expired():
                del self._cache[key]
                return False
            return True

    async def clear(self, pattern: Optional[str] = None) -> int:
        """Clear cache entries matching pattern."""
        async with self._lock:
            if pattern is None:
                count = len(self._cache)
                self._cache.clear()
                self._access_order.clear()
                return count

            # Match pattern (supports * and ? wildcards)
            keys_to_delete = [key for key in self._cache.keys() if fnmatch.fnmatch(key, pattern)]
            for key in keys_to_delete:
                del self._cache[key]
                if key in self._access_order:
                    self._access_order.remove(key)

            return len(keys_to_delete)

    async def get_stats(self) -> CacheStats:
        """Get cache statistics."""
        return CacheStats(
            hits=self._hits,
            misses=self._misses,
            size=len(self._cache),
            max_size=self._max_size,
            backend_type="memory",
            connection_info="in-process",
        )

    async def increment(self, key: str, amount: int = 1) -> int:
        """Atomic increment operation."""
        async with self._lock:
            entry = self._cache.get(key)
            if entry is None or entry.is_expired():
                new_value = amount
                self._cache[key] = CacheEntry(value=new_value)
            else:
                new_value = (entry.value or 0) + amount
                entry.value = new_value

            self._touch(key)
            return new_value
