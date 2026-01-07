"""Caching layer for SAM Framework.

Supports in-memory caching (development) and Redis (production).
Configure via SAM_REDIS_URL environment variable.

Examples:
    In-memory (default): None or empty
    Redis: redis://localhost:6379/0
    Redis with auth: redis://:password@host:6379/0
"""

from .base import CacheBackend, CacheStats
from .engine import (
    CacheEngine,
    get_cache,
    cleanup_cache,
)

__all__ = [
    "CacheBackend",
    "CacheStats",
    "CacheEngine",
    "get_cache",
    "cleanup_cache",
]
