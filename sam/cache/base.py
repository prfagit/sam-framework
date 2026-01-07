"""Base cache abstractions for multi-backend support."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class CacheStats:
    """Cache statistics."""

    hits: int
    misses: int
    size: int
    max_size: int
    backend_type: str
    connection_info: str


class CacheBackend(ABC):
    """Abstract base class for cache backends."""

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the cache backend."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Close the cache backend."""
        ...

    @abstractmethod
    async def get(self, key: str) -> Optional[Any]:
        """Get a value from the cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found/expired
        """
        ...

    @abstractmethod
    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set a value in the cache.

        Args:
            key: Cache key
            value: Value to cache (must be JSON-serializable for Redis)
            ttl: Time-to-live in seconds (None for no expiration)
        """
        ...

    @abstractmethod
    async def delete(self, key: str) -> bool:
        """Delete a value from the cache.

        Args:
            key: Cache key

        Returns:
            True if key existed and was deleted
        """
        ...

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Check if a key exists in the cache.

        Args:
            key: Cache key

        Returns:
            True if key exists and is not expired
        """
        ...

    @abstractmethod
    async def clear(self, pattern: Optional[str] = None) -> int:
        """Clear cache entries.

        Args:
            pattern: Optional pattern to match keys (e.g., "user:*")
                    If None, clears all entries

        Returns:
            Number of entries cleared
        """
        ...

    @abstractmethod
    async def get_stats(self) -> CacheStats:
        """Get cache statistics."""
        ...

    # Convenience methods for common patterns

    async def get_or_set(
        self,
        key: str,
        factory: Any,  # Callable that returns value
        ttl: Optional[int] = None,
    ) -> Any:
        """Get value from cache, or compute and cache it.

        Args:
            key: Cache key
            factory: Async callable that returns the value if not cached
            ttl: Time-to-live in seconds

        Returns:
            Cached or computed value
        """
        value = await self.get(key)
        if value is not None:
            return value

        # Compute value
        if callable(factory):
            import asyncio

            if asyncio.iscoroutinefunction(factory):
                value = await factory()
            else:
                value = factory()
        else:
            value = factory

        await self.set(key, value, ttl)
        return value

    async def increment(self, key: str, amount: int = 1) -> int:
        """Increment a counter value.

        Args:
            key: Cache key
            amount: Amount to increment by

        Returns:
            New value after increment
        """
        current = await self.get(key) or 0
        new_value = current + amount
        await self.set(key, new_value)
        return new_value
