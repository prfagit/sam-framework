"""Database migration system for SAM Framework."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from ..utils.connection_pool import get_db_connection

logger = logging.getLogger(__name__)


@dataclass
class Migration:
    """Represents a database migration."""

    version: int
    name: str
    description: str
    up: Callable[[Any], Any]  # Async function that takes a connection
    down: Optional[Callable[[Any], Any]] = None  # Optional rollback function


class MigrationManager:
    """Manages database migrations."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.migrations: List[Migration] = []

    def register(self, migration: Migration) -> None:
        """Register a migration."""
        # Check for duplicate versions
        if any(m.version == migration.version for m in self.migrations):
            raise ValueError(f"Migration version {migration.version} already exists")
        self.migrations.append(migration)
        # Sort by version
        self.migrations.sort(key=lambda m: m.version)

    async def initialize(self) -> None:
        """Initialize the migrations table."""
        async with get_db_connection(self.db_path) as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    applied_at TEXT NOT NULL
                )
                """
            )
            await conn.commit()
            logger.debug("Migrations table initialized")

    async def get_applied_migrations(self) -> List[int]:
        """Get list of applied migration versions."""
        async with get_db_connection(self.db_path) as conn:
            cursor = await conn.execute("SELECT version FROM schema_migrations ORDER BY version")
            rows = await cursor.fetchall()
            return [row[0] for row in rows]

    async def record_migration(self, version: int, name: str, description: str) -> None:
        """Record that a migration has been applied."""
        async with get_db_connection(self.db_path) as conn:
            applied_at = datetime.now(timezone.utc).isoformat()
            await conn.execute(
                """
                INSERT INTO schema_migrations (version, name, description, applied_at)
                VALUES (?, ?, ?, ?)
                """,
                (version, name, description, applied_at),
            )
            await conn.commit()
            logger.info(f"Recorded migration {version}: {name}")

    async def migrate(self, target_version: Optional[int] = None) -> int:
        """Run pending migrations.

        Args:
            target_version: Target version to migrate to (None = latest)

        Returns:
            Number of migrations applied
        """
        await self.initialize()

        applied = await self.get_applied_migrations()
        pending = [m for m in self.migrations if m.version not in applied]

        if target_version is not None:
            pending = [m for m in pending if m.version <= target_version]

        if not pending:
            logger.info("No pending migrations")
            return 0

        logger.info(f"Applying {len(pending)} migration(s)")

        applied_count = 0
        for migration in pending:
            try:
                logger.info(f"Applying migration {migration.version}: {migration.name}")
                async with get_db_connection(self.db_path) as conn:
                    # Run migration in a transaction
                    await migration.up(conn)
                    await conn.commit()

                # Record migration
                await self.record_migration(
                    migration.version, migration.name, migration.description
                )
                applied_count += 1
                logger.info(f"Successfully applied migration {migration.version}: {migration.name}")
            except Exception as e:
                logger.error(
                    f"Failed to apply migration {migration.version}: {migration.name} - {e}"
                )
                raise

        return applied_count

    async def rollback(self, target_version: int) -> int:
        """Rollback migrations to a specific version.

        Args:
            target_version: Version to rollback to

        Returns:
            Number of migrations rolled back
        """
        await self.initialize()

        applied = await self.get_applied_migrations()
        to_rollback = [
            m for m in self.migrations if m.version > target_version and m.version in applied
        ]

        if not to_rollback:
            logger.info("No migrations to rollback")
            return 0

        # Sort in reverse order (newest first)
        to_rollback.sort(key=lambda m: m.version, reverse=True)

        logger.info(f"Rolling back {len(to_rollback)} migration(s)")

        rolled_back_count = 0
        for migration in to_rollback:
            if migration.down is None:
                logger.warning(
                    f"Migration {migration.version}: {migration.name} has no rollback function"
                )
                continue

            try:
                logger.info(f"Rolling back migration {migration.version}: {migration.name}")
                async with get_db_connection(self.db_path) as conn:
                    await migration.down(conn)
                    await conn.commit()

                # Remove migration record
                async with get_db_connection(self.db_path) as conn:
                    await conn.execute(
                        "DELETE FROM schema_migrations WHERE version = ?",
                        (migration.version,),
                    )
                    await conn.commit()

                rolled_back_count += 1
                logger.info(
                    f"Successfully rolled back migration {migration.version}: {migration.name}"
                )
            except Exception as e:
                logger.error(
                    f"Failed to rollback migration {migration.version}: {migration.name} - {e}"
                )
                raise

        return rolled_back_count

    async def get_current_version(self) -> int:
        """Get the current schema version (highest applied migration)."""
        applied = await self.get_applied_migrations()
        return max(applied) if applied else 0

    async def get_status(self) -> Dict[str, Any]:
        """Get migration status information."""
        await self.initialize()
        applied = await self.get_applied_migrations()
        pending = [m.version for m in self.migrations if m.version not in applied]

        return {
            "current_version": max(applied) if applied else 0,
            "total_migrations": len(self.migrations),
            "applied_count": len(applied),
            "pending_count": len(pending),
            "applied_versions": applied,
            "pending_versions": pending,
        }


# Global migration manager instance
_migration_manager: Optional[MigrationManager] = None


def get_migration_manager(db_path: str) -> MigrationManager:
    """Get or create the global migration manager.

    Re-uses existing manager for the same db_path to prevent duplicate
    migration registrations.
    """
    global _migration_manager
    if _migration_manager is None or _migration_manager.db_path != db_path:
        _migration_manager = MigrationManager(db_path)
    return _migration_manager


def reset_migration_manager() -> None:
    """Reset the global migration manager (for testing)."""
    global _migration_manager
    _migration_manager = None


__all__ = ["Migration", "MigrationManager", "get_migration_manager"]
