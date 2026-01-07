"""Database backup and restore functionality for SAM Framework."""

from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


class BackupManager:
    """Manages database backups with retention policies."""

    def __init__(self, db_path: str, backup_dir: Optional[str] = None):
        self.db_path = db_path
        self.backup_dir = backup_dir or os.path.join(os.path.dirname(db_path) or ".sam", "backups")
        os.makedirs(self.backup_dir, exist_ok=True)

    def create_backup(self, label: Optional[str] = None) -> Tuple[str, str]:
        """
        Create a backup of the database.

        Args:
            label: Optional label for the backup (e.g., "before-migration")

        Returns:
            Tuple of (backup_path, backup_filename)
        """
        if not os.path.exists(self.db_path):
            raise FileNotFoundError(f"Database not found: {self.db_path}")

        # Generate backup filename with timestamp
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        if label:
            # Sanitize label (remove special chars)
            safe_label = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in label)
            filename = f"sam_memory_{timestamp}_{safe_label}.db"
        else:
            filename = f"sam_memory_{timestamp}.db"

        backup_path = os.path.join(self.backup_dir, filename)

        logger.info(f"Creating backup: {backup_path}")

        # Use SQLite backup API for safe backup
        try:
            source_conn = sqlite3.connect(self.db_path)
            backup_conn = sqlite3.connect(backup_path)

            # Use SQLite backup API
            source_conn.backup(backup_conn)

            source_conn.close()
            backup_conn.close()

            # Verify backup
            if not self.verify_backup(backup_path):
                os.remove(backup_path)
                raise RuntimeError("Backup verification failed")

            file_size = os.path.getsize(backup_path)
            logger.info(f"Backup created successfully: {backup_path} ({file_size:,} bytes)")

            return backup_path, filename

        except Exception as e:
            # Clean up on error
            if os.path.exists(backup_path):
                os.remove(backup_path)
            logger.error(f"Backup failed: {e}")
            raise

    def verify_backup(self, backup_path: str) -> bool:
        """
        Verify that a backup file is valid.

        Args:
            backup_path: Path to backup file

        Returns:
            True if backup is valid, False otherwise
        """
        if not os.path.exists(backup_path):
            return False

        try:
            # Try to open and query the backup
            conn = sqlite3.connect(backup_path)
            cursor = conn.cursor()

            # Check if we can read from the database
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cursor.fetchall()

            cursor.close()
            conn.close()

            # Basic validation: should have at least some tables
            if len(tables) == 0:
                logger.warning(f"Backup appears empty: {backup_path}")
                return False

            return True

        except Exception as e:
            logger.error(f"Backup verification failed: {e}")
            return False

    def restore_backup(self, backup_path: str, force: bool = False) -> None:
        """
        Restore database from backup.

        Args:
            backup_path: Path to backup file
            force: If True, restore even if target database exists

        Raises:
            FileNotFoundError: If backup file doesn't exist
            RuntimeError: If restore fails
        """
        if not os.path.exists(backup_path):
            raise FileNotFoundError(f"Backup file not found: {backup_path}")

        # Verify backup before restoring
        if not self.verify_backup(backup_path):
            raise RuntimeError("Backup verification failed. Cannot restore.")

        # Check if target database exists
        if os.path.exists(self.db_path) and not force:
            raise RuntimeError(
                f"Database already exists: {self.db_path}. Use --force to overwrite."
            )

        logger.info(f"Restoring database from backup: {backup_path}")

        # Create backup of current database if it exists
        if os.path.exists(self.db_path):
            try:
                pre_restore_backup, _ = self.create_backup(label="pre-restore")
                logger.info(f"Created pre-restore backup: {pre_restore_backup}")
            except Exception as e:
                logger.warning(f"Failed to create pre-restore backup: {e}")

        try:
            # Use SQLite backup API for safe restore
            backup_conn = sqlite3.connect(backup_path)
            target_conn = sqlite3.connect(self.db_path)

            # Use SQLite backup API
            backup_conn.backup(target_conn)

            backup_conn.close()
            target_conn.close()

            # Verify restored database
            if not self.verify_backup(self.db_path):
                raise RuntimeError("Restored database verification failed")

            file_size = os.path.getsize(self.db_path)
            logger.info(f"Database restored successfully: {self.db_path} ({file_size:,} bytes)")

        except Exception as e:
            logger.error(f"Restore failed: {e}")
            raise

    def list_backups(self) -> List[Tuple[str, datetime, int]]:
        """
        List all backup files with metadata.

        Returns:
            List of tuples: (backup_path, timestamp, size_bytes)
        """
        backups = []

        if not os.path.exists(self.backup_dir):
            return backups

        for filename in os.listdir(self.backup_dir):
            if not filename.endswith(".db"):
                continue

            backup_path = os.path.join(self.backup_dir, filename)

            try:
                # Extract timestamp from filename
                # Format: sam_memory_YYYYMMDD_HHMMSS[_label].db
                parts = filename.replace(".db", "").split("_")
                if len(parts) >= 3:
                    date_str = parts[2]  # YYYYMMDD
                    time_str = parts[3] if len(parts) > 3 else "000000"  # HHMMSS

                    timestamp = datetime.strptime(
                        f"{date_str}_{time_str}", "%Y%m%d_%H%M%S"
                    ).replace(tzinfo=timezone.utc)
                else:
                    # Fallback to file modification time
                    timestamp = datetime.fromtimestamp(
                        os.path.getmtime(backup_path), tz=timezone.utc
                    )

                size = os.path.getsize(backup_path)
                backups.append((backup_path, timestamp, size))

            except Exception as e:
                logger.warning(f"Failed to parse backup metadata for {filename}: {e}")
                continue

        # Sort by timestamp (newest first)
        backups.sort(key=lambda x: x[1], reverse=True)
        return backups

    def cleanup_old_backups(
        self,
        keep_daily: int = 7,
        keep_weekly: int = 4,
        keep_monthly: int = 12,
    ) -> int:
        """
        Clean up old backups according to retention policy.

        Args:
            keep_daily: Number of daily backups to keep (last N days)
            keep_weekly: Number of weekly backups to keep
            keep_monthly: Number of monthly backups to keep

        Returns:
            Number of backups deleted
        """
        backups = self.list_backups()
        if not backups:
            return 0

        now = datetime.now(timezone.utc)
        deleted_count = 0

        # Group backups by type
        daily_backups = []
        weekly_backups = []
        monthly_backups = []
        other_backups = []

        for backup_path, timestamp, size in backups:
            age_days = (now - timestamp).days

            if age_days < 7:
                # Daily backup (last 7 days)
                daily_backups.append((backup_path, timestamp, size))
            elif age_days < 30:
                # Weekly backup (last 4 weeks)
                weekly_backups.append((backup_path, timestamp, size))
            elif age_days < 365:
                # Monthly backup (last 12 months)
                monthly_backups.append((backup_path, timestamp, size))
            else:
                # Older than 1 year
                other_backups.append((backup_path, timestamp, size))

        # Keep only the most recent N of each type
        to_keep = set()

        # Daily backups: keep most recent N
        daily_backups.sort(key=lambda x: x[1], reverse=True)
        for backup in daily_backups[:keep_daily]:
            to_keep.add(backup[0])

        # Weekly backups: keep most recent N (one per week)
        weekly_backups.sort(key=lambda x: x[1], reverse=True)
        for backup in weekly_backups[:keep_weekly]:
            to_keep.add(backup[0])

        # Monthly backups: keep most recent N (one per month)
        monthly_backups.sort(key=lambda x: x[1], reverse=True)
        for backup in monthly_backups[:keep_monthly]:
            to_keep.add(backup[0])

        # Delete backups not in keep list
        for backup_path, timestamp, size in backups:
            if backup_path not in to_keep:
                try:
                    os.remove(backup_path)
                    deleted_count += 1
                    logger.info(f"Deleted old backup: {backup_path}")
                except Exception as e:
                    logger.error(f"Failed to delete backup {backup_path}: {e}")

        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} old backup(s)")

        return deleted_count

    def get_backup_info(self, backup_path: str) -> dict:
        """
        Get information about a backup file.

        Args:
            backup_path: Path to backup file

        Returns:
            Dictionary with backup information
        """
        if not os.path.exists(backup_path):
            raise FileNotFoundError(f"Backup file not found: {backup_path}")

        info = {
            "path": backup_path,
            "filename": os.path.basename(backup_path),
            "size_bytes": os.path.getsize(backup_path),
            "exists": True,
            "valid": False,
            "tables": [],
        }

        # Try to get database info
        try:
            conn = sqlite3.connect(backup_path)
            cursor = conn.cursor()

            # Get table names
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            info["tables"] = [row[0] for row in cursor.fetchall()]

            # Get database size
            cursor.execute(
                "SELECT page_count * page_size FROM pragma_page_count(), pragma_page_size()"
            )
            result = cursor.fetchone()
            if result:
                info["db_size_bytes"] = result[0]

            cursor.close()
            conn.close()

            info["valid"] = True

        except Exception as e:
            logger.warning(f"Failed to read backup info: {e}")
            info["error"] = str(e)

        return info
