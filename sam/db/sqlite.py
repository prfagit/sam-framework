"""SQLite database backend for development and small deployments."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, List, Optional, Tuple

import aiosqlite

from .base import DatabaseBackend, PoolStats, Row, Rows

logger = logging.getLogger(__name__)


class SQLiteConnection:
    """Wrapper around aiosqlite connection to match our interface."""

    def __init__(self, conn: aiosqlite.Connection):
        self._conn = conn
        self._cursor: Optional[aiosqlite.Cursor] = None
        self.rowcount: int = 0

    async def execute(
        self, sql: str, parameters: Optional[Tuple[Any, ...]] = None
    ) -> "SQLiteConnection":
        """Execute a SQL query, returning self for cursor-like interface."""
        self._cursor = await self._conn.execute(sql, parameters or ())
        self.rowcount = self._cursor.rowcount if self._cursor else 0
        return self

    async def executemany(self, sql: str, parameters: List[Tuple[Any, ...]]) -> Any:
        """Execute a SQL query with multiple parameter sets."""
        await self._conn.executemany(sql, parameters)

    async def fetchone(self) -> Optional[Row]:
        """Fetch one row from the last query."""
        if self._cursor:
            return await self._cursor.fetchone()
        return None

    async def fetchall(self) -> Rows:
        """Fetch all rows from the last query."""
        if self._cursor:
            return await self._cursor.fetchall()
        return []

    async def commit(self) -> None:
        """Commit the current transaction."""
        await self._conn.commit()

    async def rollback(self) -> None:
        """Rollback the current transaction."""
        await self._conn.rollback()


class SQLiteBackend(DatabaseBackend):
    """SQLite backend for development and small-scale deployments."""

    def __init__(
        self,
        db_path: str,
        min_pool_size: int = 1,
        max_pool_size: int = 10,
        max_lifetime: int = 3600,
    ):
        self._db_path = db_path
        self._min_pool_size = min_pool_size
        self._max_pool_size = max_pool_size
        self._max_lifetime = max_lifetime
        self._pool: asyncio.Queue[dict] = asyncio.Queue(maxsize=max_pool_size)
        self._lock = asyncio.Lock()
        self._closed = False
        self._total_connections = 0
        self._total_queries = 0

        # Ensure directory exists
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

    async def initialize(self) -> None:
        """Initialize the connection pool with minimum connections."""
        logger.info(
            f"Initializing SQLite backend: {self._db_path} "
            f"(min: {self._min_pool_size}, max: {self._max_pool_size})"
        )

        # Pre-create minimum connections
        for _ in range(self._min_pool_size):
            conn_info = await self._create_connection()
            await self._pool.put(conn_info)

        logger.info("SQLite backend initialized")

    async def _create_connection(self) -> dict:
        """Create a new database connection."""
        conn = await aiosqlite.connect(
            self._db_path,
            timeout=30.0,
            check_same_thread=False,
        )

        # Optimize SQLite for performance
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA synchronous=NORMAL")
        await conn.execute("PRAGMA cache_size=10000")
        await conn.execute("PRAGMA temp_store=memory")
        await conn.execute("PRAGMA busy_timeout=5000")
        await conn.execute("PRAGMA wal_autocheckpoint=1000")
        await conn.commit()

        self._total_connections += 1

        return {
            "connection": conn,
            "created_at": time.time(),
            "last_used": time.time(),
            "usage_count": 0,
        }

    async def close(self) -> None:
        """Close all connections."""
        self._closed = True

        while not self._pool.empty():
            try:
                conn_info = self._pool.get_nowait()
                await conn_info["connection"].close()
            except asyncio.QueueEmpty:
                break
            except Exception as e:
                logger.error(f"Error closing connection: {e}")

        logger.info("SQLite backend closed")

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[SQLiteConnection]:
        """Get a connection from the pool."""
        if self._closed:
            raise RuntimeError("Database backend is closed")

        conn_info = None
        try:
            # Try to get from pool
            try:
                conn_info = self._pool.get_nowait()
            except asyncio.QueueEmpty:
                # Create new if pool is empty
                async with self._lock:
                    conn_info = await self._create_connection()

            conn_info["last_used"] = time.time()
            conn_info["usage_count"] += 1

            yield SQLiteConnection(conn_info["connection"])

        finally:
            if conn_info and not self._closed:
                try:
                    self._pool.put_nowait(conn_info)
                except asyncio.QueueFull:
                    await conn_info["connection"].close()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[SQLiteConnection]:
        """Get a connection with automatic transaction management."""
        async with self.connection() as conn:
            try:
                yield conn
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise

    async def execute(self, sql: str, parameters: Optional[Tuple[Any, ...]] = None) -> Any:
        """Execute a query."""
        self._total_queries += 1
        async with self.connection() as conn:
            return await conn.execute(sql, parameters)

    async def fetch_one(
        self, sql: str, parameters: Optional[Tuple[Any, ...]] = None
    ) -> Optional[Row]:
        """Execute a query and fetch one row."""
        self._total_queries += 1
        async with self.connection() as conn:
            await conn.execute(sql, parameters)
            return await conn.fetchone()

    async def fetch_all(self, sql: str, parameters: Optional[Tuple[Any, ...]] = None) -> Rows:
        """Execute a query and fetch all rows."""
        self._total_queries += 1
        async with self.connection() as conn:
            await conn.execute(sql, parameters)
            return await conn.fetchall()

    async def get_stats(self) -> PoolStats:
        """Get connection pool statistics."""
        return PoolStats(
            pool_size=self._pool.qsize(),
            min_pool_size=self._min_pool_size,
            max_pool_size=self._max_pool_size,
            active_connections=self._max_pool_size - self._pool.qsize(),
            idle_connections=self._pool.qsize(),
            total_connections_created=self._total_connections,
            total_queries_executed=self._total_queries,
            backend_type="sqlite",
            connection_string=f"sqlite:///{self._db_path}",
        )

    def get_placeholder(self, index: int) -> str:
        """SQLite uses ? for all placeholders."""
        return "?"

    async def table_exists(self, table_name: str) -> bool:
        """Check if a table exists in SQLite."""
        row = await self.fetch_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        )
        return row is not None

    async def run_migrations(self, migrations: List[Any]) -> None:
        """Run database migrations for SQLite."""
        # Create migrations table if not exists
        await self.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # Get current version
        row = await self.fetch_one("SELECT COALESCE(MAX(version), 0) FROM schema_migrations")
        current_version = row[0] if row else 0

        # Run pending migrations
        for migration in migrations:
            if migration.version > current_version:
                logger.info(f"Running migration {migration.version}: {migration.name}")
                async with self.transaction() as conn:
                    await migration.up(conn)
                    await conn.execute(
                        "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
                        (migration.version, migration.name),
                    )
                logger.info(f"Migration {migration.version} completed")
