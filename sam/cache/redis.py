"""Redis cache backend for production distributed deployments."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Check if redis is available
try:
    import redis.asyncio as aioredis
    from redis.asyncio import Redis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    aioredis = None  # type: ignore[assignment]
    Redis = None  # type: ignore[assignment]

from .base import CacheBackend, CacheStats  # noqa: E402


class RedisCacheBackend(CacheBackend):
    """Redis-backed cache for distributed deployments.

    Features:
    - Distributed caching across multiple app instances
    - Persistent cache that survives restarts
    - Native TTL support
    - Pub/sub for cache invalidation
    """

    def __init__(
        self,
        redis_url: str,
        prefix: str = "sam:",
        default_ttl: int = 3600,
    ):
        """Initialize Redis cache.

        Args:
            redis_url: Redis connection URL (redis://host:port/db)
            prefix: Key prefix for all cache entries
            default_ttl: Default TTL in seconds when not specified
        """
        if not REDIS_AVAILABLE:
            raise RuntimeError(
                "redis[hiredis] is required for Redis cache. "
                "Install with: pip install redis[hiredis]"
            )

        self._redis_url = redis_url
        self._prefix = prefix
        self._default_ttl = default_ttl
        self._redis: Optional[Redis] = None
        self._hits = 0
        self._misses = 0

    def _make_key(self, key: str) -> str:
        """Add prefix to key."""
        return f"{self._prefix}{key}"

    async def initialize(self) -> None:
        """Connect to Redis."""
        logger.info(f"Connecting to Redis: {self._sanitize_url(self._redis_url)}")

        self._redis = aioredis.from_url(
            self._redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=5,
            socket_keepalive=True,
            health_check_interval=30,
        )

        # Test connection
        await self._redis.ping()
        logger.info("Redis connection established")

    async def close(self) -> None:
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()
            self._redis = None
            logger.info("Redis connection closed")

    def _sanitize_url(self, url: str) -> str:
        """Remove password from URL for logging."""
        import re

        return re.sub(r":([^:@]+)@", r":***@", url)

    def _serialize(self, value: Any) -> str:
        """Serialize value for storage."""
        return json.dumps(value)

    def _deserialize(self, data: str) -> Any:
        """Deserialize value from storage."""
        try:
            return json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return data

    async def get(self, key: str) -> Optional[Any]:
        """Get a value from Redis."""
        if not self._redis:
            raise RuntimeError("Redis not initialized")

        data = await self._redis.get(self._make_key(key))
        if data is None:
            self._misses += 1
            return None

        self._hits += 1
        return self._deserialize(data)

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set a value in Redis."""
        if not self._redis:
            raise RuntimeError("Redis not initialized")

        ttl = ttl or self._default_ttl
        await self._redis.set(
            self._make_key(key),
            self._serialize(value),
            ex=ttl,
        )

    async def delete(self, key: str) -> bool:
        """Delete a value from Redis."""
        if not self._redis:
            raise RuntimeError("Redis not initialized")

        result = await self._redis.delete(self._make_key(key))
        return result > 0

    async def exists(self, key: str) -> bool:
        """Check if a key exists in Redis."""
        if not self._redis:
            raise RuntimeError("Redis not initialized")

        return await self._redis.exists(self._make_key(key)) > 0

    async def clear(self, pattern: Optional[str] = None) -> int:
        """Clear cache entries matching pattern."""
        if not self._redis:
            raise RuntimeError("Redis not initialized")

        if pattern is None:
            pattern = "*"

        full_pattern = self._make_key(pattern)
        count = 0

        # Use SCAN for safe iteration
        async for key in self._redis.scan_iter(match=full_pattern, count=100):
            await self._redis.delete(key)
            count += 1

        return count

    async def get_stats(self) -> CacheStats:
        """Get cache statistics."""
        if not self._redis:
            return CacheStats(
                hits=self._hits,
                misses=self._misses,
                size=0,
                max_size=-1,  # Redis doesn't have fixed size
                backend_type="redis",
                connection_info=self._sanitize_url(self._redis_url),
            )

        # Get Redis info
        info = await self._redis.info("keyspace")
        db_info = info.get("db0", {})
        size = db_info.get("keys", 0) if isinstance(db_info, dict) else 0

        return CacheStats(
            hits=self._hits,
            misses=self._misses,
            size=size,
            max_size=-1,
            backend_type="redis",
            connection_info=self._sanitize_url(self._redis_url),
        )

    async def increment(self, key: str, amount: int = 1) -> int:
        """Atomic increment using Redis INCRBY."""
        if not self._redis:
            raise RuntimeError("Redis not initialized")

        return await self._redis.incrby(self._make_key(key), amount)

    # Redis-specific features

    async def set_hash(self, key: str, mapping: dict, ttl: Optional[int] = None) -> None:
        """Set a hash (dictionary) in Redis."""
        if not self._redis:
            raise RuntimeError("Redis not initialized")

        full_key = self._make_key(key)
        await self._redis.hset(full_key, mapping=mapping)
        if ttl:
            await self._redis.expire(full_key, ttl)

    async def get_hash(self, key: str) -> Optional[dict]:
        """Get a hash from Redis."""
        if not self._redis:
            raise RuntimeError("Redis not initialized")

        result = await self._redis.hgetall(self._make_key(key))
        return result if result else None

    async def publish(self, channel: str, message: Any) -> int:
        """Publish a message to a channel."""
        if not self._redis:
            raise RuntimeError("Redis not initialized")

        return await self._redis.publish(
            f"{self._prefix}channel:{channel}",
            self._serialize(message),
        )

    async def expire(self, key: str, ttl: int) -> bool:
        """Set/update TTL on a key."""
        if not self._redis:
            raise RuntimeError("Redis not initialized")

        return await self._redis.expire(self._make_key(key), ttl)
