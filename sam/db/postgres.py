"""PostgreSQL database backend for production use."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Check if asyncpg is available
try:
    import asyncpg
    from asyncpg.pool import Pool

    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False
    asyncpg = None  # type: ignore[assignment]
    Pool = None  # type: ignore[assignment]

from .base import DatabaseBackend, PoolStats, Row, Rows, sanitize_connection_string  # noqa: E402


def _translate_sql(sql: str) -> str:
    """Translate SQLite-style SQL to PostgreSQL.

    - Converts ? placeholders to $1, $2, etc.
    - Handles REPLACE INTO → INSERT ... ON CONFLICT
    - Skips PRAGMA statements
    """
    # Skip PRAGMA statements (SQLite-specific)
    if sql.strip().upper().startswith("PRAGMA"):
        return ""

    # Convert ? placeholders to $1, $2, etc.
    result = []
    param_count = 0
    i = 0
    while i < len(sql):
        if sql[i] == "?":
            param_count += 1
            result.append(f"${param_count}")
        else:
            result.append(sql[i])
        i += 1

    translated = "".join(result)

    # Convert REPLACE INTO to INSERT ... ON CONFLICT (basic conversion)
    if translated.strip().upper().startswith("REPLACE INTO"):
        # This is a simplified conversion - complex cases may need manual handling
        translated = translated.replace("REPLACE INTO", "INSERT INTO", 1)
        # Add ON CONFLICT DO UPDATE (caller should handle properly)

    return translated


class PostgreSQLConnection:
    """Wrapper around asyncpg connection to match SQLite interface.

    Automatically translates SQLite-style SQL to PostgreSQL:
    - ? placeholders → $1, $2, etc.
    - Skips PRAGMA statements
    """

    def __init__(self, conn: "asyncpg.Connection"):
        self._conn = conn
        self._last_result: Optional[List[asyncpg.Record]] = None
        self._cursor_result: Optional[List[asyncpg.Record]] = None
        self.rowcount: int = 0

    async def execute(
        self, sql: str, parameters: Optional[Tuple[Any, ...]] = None
    ) -> "PostgreSQLConnection":
        """Execute a SQL query, returning self for cursor-like interface."""
        translated_sql = _translate_sql(sql)

        # Skip empty SQL (e.g., PRAGMA statements)
        if not translated_sql.strip():
            self._cursor_result = []
            self.rowcount = 0
            return self

        try:
            if parameters:
                result = await self._conn.fetch(translated_sql, *parameters)
            else:
                result = await self._conn.fetch(translated_sql)

            self._cursor_result = result
            self.rowcount = len(result) if result else 0

        except Exception as e:
            # Handle non-SELECT queries (INSERT, UPDATE, DELETE)
            if "cannot be executed in a read-only" in str(e) or "fetch" in str(e).lower():
                if parameters:
                    status = await self._conn.execute(translated_sql, *parameters)
                else:
                    status = await self._conn.execute(translated_sql)
                # Parse affected rows from status like "UPDATE 5"
                try:
                    self.rowcount = int(status.split()[-1]) if status else 0
                except (ValueError, IndexError):
                    self.rowcount = 0
                self._cursor_result = []
            else:
                raise

        return self

    async def executemany(self, sql: str, parameters: List[Tuple[Any, ...]]) -> Any:
        """Execute a SQL query with multiple parameter sets."""
        translated_sql = _translate_sql(sql)
        if not translated_sql.strip():
            return
        await self._conn.executemany(translated_sql, parameters)

    async def fetchone(self) -> Optional[Row]:
        """Fetch one row from the last query."""
        if self._cursor_result and len(self._cursor_result) > 0:
            row = self._cursor_result[0]
            return tuple(row) if row else None
        return None

    async def fetchall(self) -> Rows:
        """Fetch all rows from the last query."""
        if self._cursor_result:
            return [tuple(r) for r in self._cursor_result]
        return []

    async def fetch(self, sql: str, parameters: Optional[Tuple[Any, ...]] = None) -> List[Any]:
        """Fetch all rows directly."""
        translated_sql = _translate_sql(sql)
        if not translated_sql.strip():
            return []

        if parameters:
            self._last_result = await self._conn.fetch(translated_sql, *parameters)
        else:
            self._last_result = await self._conn.fetch(translated_sql)
        return [tuple(r) for r in self._last_result]

    async def fetchrow(
        self, sql: str, parameters: Optional[Tuple[Any, ...]] = None
    ) -> Optional[Row]:
        """Fetch one row directly."""
        translated_sql = _translate_sql(sql)
        if not translated_sql.strip():
            return None

        if parameters:
            row = await self._conn.fetchrow(translated_sql, *parameters)
        else:
            row = await self._conn.fetchrow(translated_sql)
        return tuple(row) if row else None

    async def commit(self) -> None:
        """Commit - PostgreSQL auto-commits, this is for interface compatibility."""
        pass

    async def rollback(self) -> None:
        """Rollback the current transaction."""
        # For non-transaction connections, this is a no-op
        pass


class PostgreSQLBackend(DatabaseBackend):
    """PostgreSQL backend using asyncpg for high-performance async access."""

    def __init__(
        self,
        connection_string: str,
        min_pool_size: int = 5,
        max_pool_size: int = 50,
    ):
        if not ASYNCPG_AVAILABLE:
            raise RuntimeError(
                "asyncpg is required for PostgreSQL support. Install it with: pip install asyncpg"
            )

        self._connection_string = connection_string
        self._min_pool_size = min_pool_size
        self._max_pool_size = max_pool_size
        self._pool: Optional[Pool] = None
        self._total_queries = 0
        self._total_connections = 0

    async def initialize(self) -> None:
        """Initialize the connection pool."""
        if self._pool is not None:
            return

        logger.info(
            f"Initializing PostgreSQL pool: {sanitize_connection_string(self._connection_string)} "
            f"(min: {self._min_pool_size}, max: {self._max_pool_size})"
        )

        self._pool = await asyncpg.create_pool(
            self._connection_string,
            min_size=self._min_pool_size,
            max_size=self._max_pool_size,
            command_timeout=60,
            max_inactive_connection_lifetime=300,
        )

        logger.info("PostgreSQL pool initialized successfully")

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            logger.info("PostgreSQL pool closed")

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[PostgreSQLConnection]:
        """Get a connection from the pool."""
        if not self._pool:
            await self.initialize()

        assert self._pool is not None
        async with self._pool.acquire() as conn:
            self._total_connections += 1
            yield PostgreSQLConnection(conn)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[PostgreSQLConnection]:
        """Get a connection with automatic transaction management."""
        if not self._pool:
            await self.initialize()

        assert self._pool is not None
        async with self._pool.acquire() as conn:
            self._total_connections += 1
            async with conn.transaction():
                yield PostgreSQLConnection(conn)

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
            return await conn.fetchrow(sql, parameters)

    async def fetch_all(self, sql: str, parameters: Optional[Tuple[Any, ...]] = None) -> Rows:
        """Execute a query and fetch all rows."""
        self._total_queries += 1
        async with self.connection() as conn:
            return await conn.fetch(sql, parameters)

    async def get_stats(self) -> PoolStats:
        """Get connection pool statistics."""
        if not self._pool:
            return PoolStats(
                pool_size=0,
                min_pool_size=self._min_pool_size,
                max_pool_size=self._max_pool_size,
                active_connections=0,
                idle_connections=0,
                total_connections_created=self._total_connections,
                total_queries_executed=self._total_queries,
                backend_type="postgresql",
                connection_string=sanitize_connection_string(self._connection_string),
            )

        return PoolStats(
            pool_size=self._pool.get_size(),
            min_pool_size=self._pool.get_min_size(),
            max_pool_size=self._pool.get_max_size(),
            active_connections=self._pool.get_size() - self._pool.get_idle_size(),
            idle_connections=self._pool.get_idle_size(),
            total_connections_created=self._total_connections,
            total_queries_executed=self._total_queries,
            backend_type="postgresql",
            connection_string=sanitize_connection_string(self._connection_string),
        )

    def get_placeholder(self, index: int) -> str:
        """PostgreSQL uses $1, $2, etc."""
        return f"${index}"

    async def table_exists(self, table_name: str) -> bool:
        """Check if a table exists in PostgreSQL."""
        row = await self.fetch_one(
            """
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = $1
            )
            """,
            (table_name,),
        )
        return bool(row and row[0])

    async def run_migrations(self, migrations: List[Any]) -> None:
        """Run database migrations for PostgreSQL."""
        # Create migrations table if not exists
        await self.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
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
                        "INSERT INTO schema_migrations (version, name) VALUES ($1, $2)",
                        (migration.version, migration.name),
                    )
                logger.info(f"Migration {migration.version} completed")
