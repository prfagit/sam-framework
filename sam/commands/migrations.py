"""CLI commands for database migrations."""

from __future__ import annotations

import logging
import sys
from typing import Optional

from ..config.settings import Settings
from ..core.migration_definitions import register_all_migrations
from ..core.migrations import get_migration_manager

logger = logging.getLogger(__name__)


async def migrate_database(target_version: Optional[int] = None) -> int:
    """Run database migrations.

    Args:
        target_version: Target version to migrate to (None = latest)

    Returns:
        Exit code (0 = success, 1 = error)
    """
    try:
        db_path = Settings.SAM_DB_PATH
        await register_all_migrations(db_path)
        manager = get_migration_manager(db_path)
        await manager.initialize()

        status = await manager.get_status()
        print(f"Current version: {status['current_version']}")
        print(f"Total migrations: {status['total_migrations']}")
        print(f"Applied: {status['applied_count']}")
        print(f"Pending: {status['pending_count']}")

        if status["pending_count"] == 0:
            print("✅ Database is up to date")
            return 0

        print(f"\nApplying {status['pending_count']} migration(s)...")
        applied = await manager.migrate(target_version=target_version)

        if applied > 0:
            print(f"✅ Successfully applied {applied} migration(s)")
        else:
            print("ℹ️  No migrations were applied")

        return 0
    except Exception as exc:
        print(f"❌ Migration failed: {exc}", file=sys.stderr)
        logger.exception("Migration failed")
        return 1


async def show_migration_status() -> int:
    """Show migration status.

    Returns:
        Exit code (0 = success, 1 = error)
    """
    try:
        db_path = Settings.SAM_DB_PATH
        await register_all_migrations(db_path)
        manager = get_migration_manager(db_path)
        await manager.initialize()

        status = await manager.get_status()

        print("📊 Migration Status")
        print("=" * 50)
        print(f"Current version: {status['current_version']}")
        print(f"Total migrations: {status['total_migrations']}")
        print(f"Applied: {status['applied_count']}")
        print(f"Pending: {status['pending_count']}")

        if status["applied_versions"]:
            print(f"\n✅ Applied migrations: {', '.join(map(str, status['applied_versions']))}")

        if status["pending_versions"]:
            print(f"⏳ Pending migrations: {', '.join(map(str, status['pending_versions']))}")
        else:
            print("✅ No pending migrations")

        return 0
    except Exception as exc:
        print(f"❌ Failed to get migration status: {exc}", file=sys.stderr)
        logger.exception("Failed to get migration status")
        return 1


async def rollback_migration(target_version: int) -> int:
    """Rollback migrations to a specific version.

    Args:
        target_version: Version to rollback to

    Returns:
        Exit code (0 = success, 1 = error)
    """
    try:
        db_path = Settings.SAM_DB_PATH
        await register_all_migrations(db_path)
        manager = get_migration_manager(db_path)
        await manager.initialize()

        current_version = await manager.get_current_version()
        if current_version <= target_version:
            print(
                f"ℹ️  Current version ({current_version}) is already at or below target ({target_version})"
            )
            return 0

        print(f"⚠️  Rolling back from version {current_version} to {target_version}")
        confirm = input("Are you sure? This may cause data loss. Type 'yes' to continue: ")
        if confirm.lower() != "yes":
            print("❌ Rollback cancelled")
            return 1

        rolled_back = await manager.rollback(target_version)

        if rolled_back > 0:
            print(f"✅ Successfully rolled back {rolled_back} migration(s)")
        else:
            print("ℹ️  No migrations were rolled back")

        return 0
    except Exception as exc:
        print(f"❌ Rollback failed: {exc}", file=sys.stderr)
        logger.exception("Rollback failed")
        return 1


__all__ = ["migrate_database", "show_migration_status", "rollback_migration"]
