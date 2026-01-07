"""Base database abstractions for multi-backend support."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, List, Optional, Protocol, Tuple

logger = logging.getLogger(__name__)

# Type for database row results
Row = Tuple[Any, ...]
Rows = List[Row]


class ConnectionContext(Protocol):
    """Protocol for database connection context."""

    async def execute(self, sql: str, parameters: Optional[Tuple[Any, ...]] = None) -> Any:
        """Execute a SQL query."""
        ...

    async def executemany(self, sql: str, parameters: List[Tuple[Any, ...]]) -> Any:
        """Execute a SQL query with multiple parameter sets."""
        ...

    async def fetchone(self) -> Optional[Row]:
        """Fetch one row from the last query."""
        ...

    async def fetchall(self) -> Rows:
        """Fetch all rows from the last query."""
        ...

    async def commit(self) -> None:
        """Commit the current transaction."""
        ...

    async def rollback(self) -> None:
        """Rollback the current transaction."""
        ...


@dataclass
class PoolStats:
    """Database connection pool statistics."""

    pool_size: int
    min_pool_size: int
    max_pool_size: int
    active_connections: int
    idle_connections: int
    total_connections_created: int
    total_queries_executed: int
    backend_type: str
    connection_string: str  # Sanitized (no password)


class DatabaseBackend(ABC):
    """Abstract base class for database backends."""

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the database backend and connection pool."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Close all connections and cleanup resources."""
        ...

    @abstractmethod
    @asynccontextmanager
    async def connection(self) -> AsyncIterator[ConnectionContext]:
        """Get a connection from the pool."""
        ...

    @abstractmethod
    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[ConnectionContext]:
        """Get a connection with automatic transaction management."""
        ...

    @abstractmethod
    async def execute(self, sql: str, parameters: Optional[Tuple[Any, ...]] = None) -> Any:
        """Execute a query and return the cursor/result."""
        ...

    @abstractmethod
    async def fetch_one(
        self, sql: str, parameters: Optional[Tuple[Any, ...]] = None
    ) -> Optional[Row]:
        """Execute a query and fetch one row."""
        ...

    @abstractmethod
    async def fetch_all(self, sql: str, parameters: Optional[Tuple[Any, ...]] = None) -> Rows:
        """Execute a query and fetch all rows."""
        ...

    @abstractmethod
    async def get_stats(self) -> PoolStats:
        """Get connection pool statistics."""
        ...

    @abstractmethod
    def get_placeholder(self, index: int) -> str:
        """Get the placeholder syntax for this backend.

        SQLite uses ?, PostgreSQL uses $1, $2, etc.
        """
        ...

    @abstractmethod
    async def table_exists(self, table_name: str) -> bool:
        """Check if a table exists."""
        ...

    @abstractmethod
    async def run_migrations(self, migrations: List[Any]) -> None:
        """Run database migrations."""
        ...


def sanitize_connection_string(conn_str: str) -> str:
    """Remove password from connection string for logging."""
    import re

    # Match patterns like :password@ and replace password
    return re.sub(r":([^:@]+)@", r":***@", conn_str)
