"""Database engine factory and global instance management."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from .base import DatabaseBackend, ConnectionContext
from .sqlite import SQLiteBackend

logger = logging.getLogger(__name__)


def parse_database_url(url: str) -> dict:
    """Parse a database URL into components.

    Supports:
        - sqlite:///path/to/db.sqlite
        - sqlite:///:memory:
        - postgresql://user:pass@host:port/database
        - postgres://user:pass@host:port/database

    Args:
        url: Database URL string

    Returns:
        Dictionary with backend type and connection parameters
    """
    if url.startswith("sqlite"):
        # Handle sqlite:///path or sqlite:///:memory:
        match = re.match(r"sqlite:///(.+)", url)
        if match:
            return {
                "backend": "sqlite",
                "path": match.group(1),
            }
        raise ValueError(f"Invalid SQLite URL: {url}")

    if url.startswith(("postgresql://", "postgres://")):
        return {
            "backend": "postgresql",
            "url": url,
        }

    raise ValueError(
        f"Unsupported database URL: {url}. Supported: sqlite:///path, postgresql://..."
    )


class DatabaseEngine:
    """Central database engine that manages backend lifecycle."""

    def __init__(self, database_url: Optional[str] = None):
        """Initialize database engine.

        Args:
            database_url: Database connection URL. If not provided,
                         uses SAM_DATABASE_URL env var or defaults to SQLite.
        """
        self._database_url = database_url or os.getenv(
            "SAM_DATABASE_URL",
            f"sqlite:///{os.getenv('SAM_DB_PATH', '.sam/sam_memory.db')}",
        )
        self._backend: Optional[DatabaseBackend] = None
        self._initialized = False
        self._lock = asyncio.Lock()

    @property
    def backend_type(self) -> str:
        """Get the type of database backend."""
        parsed = parse_database_url(self._database_url)
        return parsed["backend"]

    async def initialize(self) -> None:
        """Initialize the database backend."""
        if self._initialized:
            return

        async with self._lock:
            if self._initialized:
                return

            parsed = parse_database_url(self._database_url)

            if parsed["backend"] == "sqlite":
                # Get pool sizes from env
                min_size = int(os.getenv("SAM_DB_POOL_MIN_SIZE", "1"))
                max_size = int(os.getenv("SAM_DB_POOL_MAX_SIZE", "10"))

                self._backend = SQLiteBackend(
                    db_path=parsed["path"],
                    min_pool_size=min_size,
                    max_pool_size=max_size,
                )

            elif parsed["backend"] == "postgresql":
                # Import here to avoid requiring asyncpg for SQLite-only users
                from .postgres import PostgreSQLBackend

                min_size = int(os.getenv("SAM_DB_POOL_MIN_SIZE", "5"))
                max_size = int(os.getenv("SAM_DB_POOL_MAX_SIZE", "50"))

                self._backend = PostgreSQLBackend(
                    connection_string=parsed["url"],
                    min_pool_size=min_size,
                    max_pool_size=max_size,
                )

            else:
                raise ValueError(f"Unknown backend: {parsed['backend']}")

            await self._backend.initialize()
            self._initialized = True

            logger.info(
                f"Database engine initialized: {parsed['backend']} "
                f"({self._database_url.split('@')[-1] if '@' in self._database_url else self._database_url})"
            )

    async def close(self) -> None:
        """Close the database backend."""
        if self._backend:
            await self._backend.close()
            self._backend = None
            self._initialized = False

    @property
    def backend(self) -> DatabaseBackend:
        """Get the database backend (must be initialized first)."""
        if not self._backend:
            raise RuntimeError("Database engine not initialized. Call initialize() first.")
        return self._backend

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[ConnectionContext]:
        """Get a database connection."""
        if not self._initialized:
            await self.initialize()
        async with self.backend.connection() as conn:
            yield conn

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[ConnectionContext]:
        """Get a database connection with transaction management."""
        if not self._initialized:
            await self.initialize()
        async with self.backend.transaction() as conn:
            yield conn

    def get_placeholder(self, index: int) -> str:
        """Get the SQL placeholder for this backend."""
        if not self._backend:
            # Default to SQLite style for compatibility
            return "?"
        return self._backend.get_placeholder(index)


# Global engine instance
_engine: Optional[DatabaseEngine] = None
_engine_lock: Optional[asyncio.Lock] = None


def _get_engine_lock() -> asyncio.Lock:
    """Get or create the engine initialization lock."""
    global _engine_lock
    if _engine_lock is None:
        _engine_lock = asyncio.Lock()
    return _engine_lock


async def get_engine(database_url: Optional[str] = None) -> DatabaseEngine:
    """Get the global database engine instance.

    Args:
        database_url: Optional database URL (only used on first call)

    Returns:
        Initialized DatabaseEngine instance
    """
    global _engine

    if _engine is not None and _engine._initialized:
        return _engine

    lock = _get_engine_lock()
    async with lock:
        if _engine is not None and _engine._initialized:
            return _engine

        _engine = DatabaseEngine(database_url)
        await _engine.initialize()
        return _engine


@asynccontextmanager
async def get_connection(database_url: Optional[str] = None) -> AsyncIterator[ConnectionContext]:
    """Get a database connection from the global engine.

    This is the primary way to get database connections:

        async with get_connection() as conn:
            await conn.execute("SELECT * FROM users")
            rows = await conn.fetchall()

    Args:
        database_url: Optional database URL (only used on first call)

    Yields:
        Database connection context
    """
    engine = await get_engine(database_url)
    async with engine.connection() as conn:
        yield conn


async def cleanup_engine() -> None:
    """Cleanup the global database engine."""
    global _engine, _engine_lock

    if _engine:
        await _engine.close()
        _engine = None
    _engine_lock = None
