"""Database abstraction layer for SAM Framework.

Supports SQLite (development) and PostgreSQL (production).
Configure via SAM_DATABASE_URL environment variable.

Examples:
    SQLite (default): sqlite:///.sam/sam_memory.db
    PostgreSQL: postgresql://user:pass@host:5432/sam_db
"""

from .engine import (
    DatabaseEngine,
    get_engine,
    get_connection,
    cleanup_engine,
)
from .base import DatabaseBackend, ConnectionContext

__all__ = [
    "DatabaseEngine",
    "DatabaseBackend",
    "ConnectionContext",
    "get_engine",
    "get_connection",
    "cleanup_engine",
]
