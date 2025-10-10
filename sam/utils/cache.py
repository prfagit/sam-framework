"""Caching layer for tool results and API responses."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# Cache configuration from environment
CACHE_ENABLED = os.getenv("SAM_CACHE_ENABLED", "1") == "1"
CACHE_DEFAULT_TTL = int(os.getenv("SAM_CACHE_DEFAULT_TTL", "300"))  # 5 minutes
CACHE_MAX_SIZE = int(os.getenv("SAM_CACHE_MAX_SIZE", "1000"))
CACHE_KEY_PREFIX = os.getenv("SAM_CACHE_KEY_PREFIX", "sam:")


@dataclass
class CacheEntry:
    """Cache entry with metadata."""

    key: str
    value: Any
    created_at: float
    ttl: int
    hits: int = 0
    size_bytes: int = 0

    def is_expired(self) -> bool:
        """Check if entry is expired."""
        return time.time() > (self.created_at + self.ttl)

    def remaining_ttl(self) -> int:
        """Get remaining TTL in seconds."""
        remaining = int((self.created_at + self.ttl) - time.time())
        return max(0, remaining)


class CacheBackend(ABC):
    """Abstract cache backend interface."""

    @abstractmethod
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        pass

    @abstractmethod
    async def set(self, key: str, value: Any, ttl: int) -> bool:
        """Set value in cache with TTL."""
        pass

    @abstractmethod
    async def delete(self, key: str) -> bool:
        """Delete key from cache."""
        pass

    @abstractmethod
    async def clear(self) -> int:
        """Clear all cache entries."""
        pass

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Check if key exists."""
        pass

    @abstractmethod
    async def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        pass


class InMemoryCache(CacheBackend):
    """In-memory LRU cache with TTL support."""

    def __init__(self, max_size: int = CACHE_MAX_SIZE):
        self.max_size = max_size
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = asyncio.Lock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        logger.info(f"Initialized in-memory cache (max_size: {max_size})")

    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache with LRU update."""
        async with self._lock:
            if key not in self._cache:
                self._misses += 1
                logger.debug(f"Cache MISS: {key}")
                return None

            entry = self._cache[key]

            # Check expiration
            if entry.is_expired():
                del self._cache[key]
                self._misses += 1
                logger.debug(f"Cache EXPIRED: {key}")
                return None

            # Update LRU order and hit count
            self._cache.move_to_end(key)
            entry.hits += 1
            self._hits += 1

            logger.debug(f"Cache HIT: {key} (hits: {entry.hits}, TTL: {entry.remaining_ttl()}s)")
            return entry.value

    async def set(self, key: str, value: Any, ttl: int) -> bool:
        """Set value in cache with LRU eviction."""
        async with self._lock:
            # Evict if at capacity and key is new
            if len(self._cache) >= self.max_size and key not in self._cache:
                # Evict least recently used
                oldest_key, _ = self._cache.popitem(last=False)
                self._evictions += 1
                logger.debug(f"Cache EVICT (LRU): {oldest_key}")

            # Estimate size
            try:
                size_bytes = len(json.dumps(value, default=str).encode())
            except Exception:
                size_bytes = 0

            # Create or update entry
            entry = CacheEntry(
                key=key, value=value, created_at=time.time(), ttl=ttl, size_bytes=size_bytes
            )

            self._cache[key] = entry
            self._cache.move_to_end(key)

            logger.debug(f"Cache SET: {key} (TTL: {ttl}s, size: {size_bytes} bytes)")
            return True

    async def delete(self, key: str) -> bool:
        """Delete key from cache."""
        async with self._lock:
            if key in self._cache:
                del self._cache[key]
                logger.debug(f"Cache DELETE: {key}")
                return True
            return False

    async def clear(self) -> int:
        """Clear all cache entries."""
        async with self._lock:
            count = len(self._cache)
            self._cache.clear()
            logger.info(f"Cache CLEAR: removed {count} entries")
            return count

    async def exists(self, key: str) -> bool:
        """Check if key exists and is not expired."""
        async with self._lock:
            if key not in self._cache:
                return False

            entry = self._cache[key]
            if entry.is_expired():
                del self._cache[key]
                return False

            return True

    async def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        async with self._lock:
            total_requests = self._hits + self._misses
            hit_rate = (self._hits / total_requests * 100) if total_requests > 0 else 0.0

            # Clean up expired entries
            expired_keys = [k for k, v in self._cache.items() if v.is_expired()]
            for key in expired_keys:
                del self._cache[key]

            total_size = sum(entry.size_bytes for entry in self._cache.values())
            avg_ttl = (
                sum(entry.remaining_ttl() for entry in self._cache.values()) / len(self._cache)
                if self._cache
                else 0
            )

            return {
                "backend": "in-memory",
                "enabled": CACHE_ENABLED,
                "size": len(self._cache),
                "max_size": self.max_size,
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
                "hit_rate": hit_rate,
                "total_size_bytes": total_size,
                "avg_ttl_seconds": avg_ttl,
                "usage_pct": (len(self._cache) / self.max_size * 100) if self.max_size > 0 else 0,
            }

    async def cleanup_expired(self) -> int:
        """Remove expired entries and return count."""
        async with self._lock:
            expired_keys = [k for k, v in self._cache.items() if v.is_expired()]
            for key in expired_keys:
                del self._cache[key]

            if expired_keys:
                logger.debug(f"Cache cleanup: removed {len(expired_keys)} expired entries")

            return len(expired_keys)


class ToolResultCache:
    """High-level cache for tool results with automatic key generation."""

    def __init__(self, backend: Optional[CacheBackend] = None):
        self.backend = backend or InMemoryCache()
        self.enabled = CACHE_ENABLED
        self._cleanup_task: Optional[asyncio.Task[None]] = None

        if self.enabled:
            logger.info("Tool result cache enabled")
            self._start_cleanup_task()
        else:
            logger.info("Tool result cache disabled")

    def _start_cleanup_task(self) -> None:
        """Start background cleanup task."""
        try:
            asyncio.get_running_loop()
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
        except RuntimeError:
            # No event loop yet
            pass

    async def _periodic_cleanup(self) -> None:
        """Periodically clean up expired entries."""
        while self.enabled:
            try:
                await asyncio.sleep(60)  # Every minute

                if isinstance(self.backend, InMemoryCache):
                    await self.backend.cleanup_expired()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cache cleanup: {e}")

    def generate_key(self, tool_name: str, args: Dict[str, Any]) -> str:
        """Generate cache key from tool name and arguments."""
        # Sort args for consistent hashing
        args_str = json.dumps(args, sort_keys=True, default=str)
        args_hash = hashlib.sha256(args_str.encode()).hexdigest()[:16]

        return f"{CACHE_KEY_PREFIX}tool:{tool_name}:{args_hash}"

    async def get_tool_result(self, tool_name: str, args: Dict[str, Any]) -> Optional[Any]:
        """Get cached tool result."""
        if not self.enabled:
            return None

        key = self.generate_key(tool_name, args)
        return await self.backend.get(key)

    async def set_tool_result(
        self, tool_name: str, args: Dict[str, Any], result: Any, ttl: Optional[int] = None
    ) -> bool:
        """Cache tool result."""
        if not self.enabled:
            return False

        key = self.generate_key(tool_name, args)
        ttl = ttl or CACHE_DEFAULT_TTL

        return await self.backend.set(key, result, ttl)

    async def invalidate_tool(self, tool_name: str) -> int:
        """Invalidate all cached results for a tool."""
        if not self.enabled:
            return 0

        # For in-memory cache, we need to find and delete matching keys
        if isinstance(self.backend, InMemoryCache):
            async with self.backend._lock:
                prefix = f"{CACHE_KEY_PREFIX}tool:{tool_name}:"
                matching_keys = [k for k in self.backend._cache.keys() if k.startswith(prefix)]

                for key in matching_keys:
                    del self.backend._cache[key]

                logger.info(
                    f"Invalidated {len(matching_keys)} cached results for tool '{tool_name}'"
                )
                return len(matching_keys)

        return 0

    async def clear(self) -> int:
        """Clear all cached tool results."""
        if not self.enabled:
            return 0

        return await self.backend.clear()

    async def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        if not self.enabled:
            return {"enabled": False}

        return await self.backend.get_stats()

    async def shutdown(self) -> None:
        """Shutdown cache and cleanup."""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        logger.info("Tool result cache shutdown completed")


# Global cache instance
_global_cache: Optional[ToolResultCache] = None
_cache_lock: Optional[asyncio.Lock] = None


def _get_cache_lock() -> asyncio.Lock:
    """Get or create the cache initialization lock."""
    global _cache_lock
    if _cache_lock is None:
        _cache_lock = asyncio.Lock()
    return _cache_lock


async def get_tool_cache() -> ToolResultCache:
    """Get or create the global tool result cache."""
    global _global_cache

    # Fast path
    if _global_cache is not None:
        return _global_cache

    # Acquire lock for initialization
    lock = _get_cache_lock()
    async with lock:
        if _global_cache is None:
            _global_cache = ToolResultCache()
        return _global_cache


async def cleanup_tool_cache() -> None:
    """Cleanup global tool cache."""
    global _global_cache, _cache_lock

    if _global_cache is None:
        return

    lock = _get_cache_lock()
    async with lock:
        if _global_cache:
            await _global_cache.shutdown()
            _global_cache = None
        _cache_lock = None

