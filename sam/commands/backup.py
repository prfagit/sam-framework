"""CLI commands for database backup and restore."""

from __future__ import annotations

import logging
import os

from ..config.settings import Settings
from ..core.backup import BackupManager

logger = logging.getLogger(__name__)


async def create_backup(label: str | None = None) -> int:
    """
    Create a database backup.

    Args:
        label: Optional label for the backup

    Returns:
        Exit code (0 for success, 1 for error)
    """
    try:
        manager = BackupManager(Settings.SAM_DB_PATH)
        backup_path, filename = manager.create_backup(label=label)

        print(f"✓ Backup created: {filename}")
        print(f"  Path: {backup_path}")

        # Show backup info
        info = manager.get_backup_info(backup_path)
        size_mb = info["size_bytes"] / (1024 * 1024)
        print(f"  Size: {size_mb:.2f} MB")
        print(f"  Tables: {len(info.get('tables', []))}")

        return 0

    except FileNotFoundError as e:
        print(f"✗ Error: {e}")
        return 1
    except Exception as e:
        logger.exception("Backup creation failed")
        print(f"✗ Backup failed: {e}")
        return 1


async def restore_backup(backup_path: str, force: bool = False) -> int:
    """
    Restore database from backup.

    Args:
        backup_path: Path to backup file (can be relative to backup directory)
        force: If True, restore even if target database exists

    Returns:
        Exit code (0 for success, 1 for error)
    """
    try:
        manager = BackupManager(Settings.SAM_DB_PATH)

        # If backup_path is not absolute, check if it's in backup directory
        if not os.path.isabs(backup_path):
            backup_dir_backup = os.path.join(manager.backup_dir, backup_path)
            if os.path.exists(backup_dir_backup):
                backup_path = backup_dir_backup

        if not os.path.exists(backup_path):
            print(f"✗ Error: Backup file not found: {backup_path}")
            return 1

        # Verify backup before restoring
        if not manager.verify_backup(backup_path):
            print(f"✗ Error: Backup verification failed: {backup_path}")
            return 1

        # Confirm restore
        if not force:
            print(f"Warning: This will overwrite the current database: {Settings.SAM_DB_PATH}")
            response = input("Continue? (yes/no): ").strip().lower()
            if response not in ("yes", "y"):
                print("Restore cancelled.")
                return 0

        manager.restore_backup(backup_path, force=force)
        print(f"✓ Database restored from: {os.path.basename(backup_path)}")
        return 0

    except FileNotFoundError as e:
        print(f"✗ Error: {e}")
        return 1
    except Exception as e:
        logger.exception("Restore failed")
        print(f"✗ Restore failed: {e}")
        return 1


async def list_backups() -> int:
    """
    List all available backups.

    Returns:
        Exit code (0 for success, 1 for error)
    """
    try:
        manager = BackupManager(Settings.SAM_DB_PATH)
        backups = manager.list_backups()

        if not backups:
            print("No backups found.")
            return 0

        print(f"\nFound {len(backups)} backup(s):\n")
        print(f"{'Filename':<50} {'Date':<20} {'Size':<15} {'Status'}")
        print("-" * 100)

        for backup_path, timestamp, size in backups:
            filename = os.path.basename(backup_path)
            date_str = timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")
            size_mb = size / (1024 * 1024)
            size_str = f"{size_mb:.2f} MB"

            # Verify backup
            is_valid = manager.verify_backup(backup_path)
            status = "✓ Valid" if is_valid else "✗ Invalid"

            print(f"{filename:<50} {date_str:<20} {size_str:<15} {status}")

        return 0

    except Exception as e:
        logger.exception("List backups failed")
        print(f"✗ Failed to list backups: {e}")
        return 1


async def cleanup_backups(
    keep_daily: int = 7,
    keep_weekly: int = 4,
    keep_monthly: int = 12,
) -> int:
    """
    Clean up old backups according to retention policy.

    Args:
        keep_daily: Number of daily backups to keep
        keep_weekly: Number of weekly backups to keep
        keep_monthly: Number of monthly backups to keep

    Returns:
        Exit code (0 for success, 1 for error)
    """
    try:
        manager = BackupManager(Settings.SAM_DB_PATH)
        deleted_count = manager.cleanup_old_backups(
            keep_daily=keep_daily,
            keep_weekly=keep_weekly,
            keep_monthly=keep_monthly,
        )

        if deleted_count == 0:
            print("No old backups to clean up.")
        else:
            print(f"✓ Cleaned up {deleted_count} old backup(s)")

        return 0

    except Exception as e:
        logger.exception("Cleanup backups failed")
        print(f"✗ Cleanup failed: {e}")
        return 1


async def show_backup_info(backup_path: str) -> int:
    """
    Show detailed information about a backup.

    Args:
        backup_path: Path to backup file

    Returns:
        Exit code (0 for success, 1 for error)
    """
    try:
        manager = BackupManager(Settings.SAM_DB_PATH)

        # If backup_path is not absolute, check if it's in backup directory
        if not os.path.isabs(backup_path):
            backup_dir_backup = os.path.join(manager.backup_dir, backup_path)
            if os.path.exists(backup_dir_backup):
                backup_path = backup_dir_backup

        info = manager.get_backup_info(backup_path)

        print("\nBackup Information:")
        print(f"  Filename: {info['filename']}")
        print(f"  Path: {info['path']}")
        print(f"  Size: {info['size_bytes']:,} bytes ({info['size_bytes'] / (1024 * 1024):.2f} MB)")
        print(f"  Valid: {'Yes' if info['valid'] else 'No'}")
        print(f"  Tables: {len(info.get('tables', []))}")

        if info.get("tables"):
            print("\n  Tables:")
            for table in info["tables"]:
                print(f"    - {table}")

        if "error" in info:
            print(f"\n  Error: {info['error']}")

        return 0

    except FileNotFoundError as e:
        print(f"✗ Error: {e}")
        return 1
    except Exception as e:
        logger.exception("Show backup info failed")
        print(f"✗ Failed to show backup info: {e}")
        return 1
