from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, cast

from ..utils.connection_pool import get_db_connection

logger = logging.getLogger(__name__)


Message = Dict[str, Any]


class MemoryManager:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

        # Ensure directory exists (handle case where db_path has no directory)
        dirpath = os.path.dirname(db_path) or "."
        os.makedirs(dirpath, exist_ok=True)

        logger.info(f"Initialized memory manager with database: {db_path}")

    # Connection pooling is now handled by the connection_pool utility

    @staticmethod
    def _normalize_user_id(user_id: Optional[str]) -> str:
        if isinstance(user_id, str) and user_id.strip():
            return user_id.strip()
        return "default"

    async def initialize(self) -> None:
        """Initialize database tables. Must be called after creating the manager."""
        await self._init_database()
        logger.info(f"Database tables initialized: {self.db_path}")

    async def _init_database(self) -> None:
        """Initialize database tables using connection pool."""
        max_retries = 3
        retry_delay = 0.5

        for attempt in range(max_retries):
            try:
                async with get_db_connection(self.db_path) as conn:
                    # Create sessions table
                    await conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS sessions (
                            session_id TEXT PRIMARY KEY,
                            user_id TEXT NOT NULL DEFAULT 'default',
                            messages TEXT NOT NULL,
                            created_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL
                        )
                        """
                    )

                    # Ensure user_id column exists for pre-existing tables before creating indexes
                    cursor = await conn.execute("PRAGMA table_info(sessions)")
                    columns = [row[1] for row in await cursor.fetchall()]
                    if "user_id" not in columns:
                        await conn.execute(
                            "ALTER TABLE sessions ADD COLUMN user_id TEXT NOT NULL DEFAULT 'default'"
                        )

                    await conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_sessions_updated_at ON sessions(updated_at)"
                    )
                    await conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, updated_at)"
                    )

                    # Create preferences table
                    await conn.execute("""
                        CREATE TABLE IF NOT EXISTS preferences (
                            user_id TEXT NOT NULL,
                            key TEXT NOT NULL,
                            value TEXT NOT NULL,
                            created_at TEXT NOT NULL,
                            PRIMARY KEY (user_id, key)
                        )
                    """)

                    # Create trades table
                    await conn.execute("""
                        CREATE TABLE IF NOT EXISTS trades (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            user_id TEXT NOT NULL,
                            token_address TEXT NOT NULL,
                            action TEXT NOT NULL,
                            amount REAL NOT NULL,
                            timestamp TEXT NOT NULL
                        )
                    """)
                    await conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp)"
                    )

                    # Create secure_data table
                    await conn.execute("""
                        CREATE TABLE IF NOT EXISTS secure_data (
                            user_id TEXT PRIMARY KEY,
                            encrypted_private_key TEXT NOT NULL,
                            wallet_address TEXT NOT NULL,
                            created_at TEXT NOT NULL
                        )
                    """)

                    await conn.commit()
                    return  # Success, exit retry loop

            except Exception as e:
                logger.warning(f"Database initialization attempt {attempt + 1} failed: {e}")
                if attempt == max_retries - 1:
                    logger.error(f"Failed to initialize database after {max_retries} attempts: {e}")
                    raise
                await asyncio.sleep(retry_delay * (2**attempt))

    async def save_session(
        self, session_id: str, messages: List[Message], user_id: Optional[str] = None
    ) -> None:
        """Save session messages to database."""
        uid = self._normalize_user_id(user_id)
        async with get_db_connection(self.db_path) as conn:
            now = datetime.utcnow().isoformat()

            messages_json = json.dumps(messages)

            # Use UPSERT to reduce round-trips
            await conn.execute(
                """
                INSERT INTO sessions (session_id, user_id, messages, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                  messages = excluded.messages,
                  updated_at = excluded.updated_at,
                  user_id = excluded.user_id
                """,
                (session_id, uid, messages_json, now, now),
            )

            await conn.commit()
            logger.debug(f"Saved session {session_id} for user {uid} with {len(messages)} messages")

    async def load_session(self, session_id: str, user_id: Optional[str] = None) -> List[Message]:
        """Load session messages from database."""
        uid = self._normalize_user_id(user_id)
        async with get_db_connection(self.db_path) as conn:
            cursor = await conn.execute(
                "SELECT messages FROM sessions WHERE session_id = ? AND user_id = ?",
                (session_id, uid),
            )
            result = await cursor.fetchone()

            if result:
                messages = cast(List[Message], json.loads(result[0]))
            else:
                messages = []

        logger.debug(f"Loaded session {session_id} for user {uid} with {len(messages)} messages")
        return messages

    async def save_user_preference(self, user_id: str, key: str, value: str) -> None:
        """Save user preference."""
        uid = self._normalize_user_id(user_id)
        async with get_db_connection(self.db_path) as conn:
            now = datetime.utcnow().isoformat()

            # Use REPLACE to handle both insert and update
            await conn.execute(
                """
                REPLACE INTO preferences (user_id, key, value, created_at)
                VALUES (?, ?, ?, ?)
            """,
                (uid, key, value, now),
            )

            await conn.commit()

        logger.debug(f"Saved preference {key} for user {uid}")

    async def get_user_preference(self, user_id: str, key: str) -> Optional[str]:
        """Get user preference."""
        uid = self._normalize_user_id(user_id)
        async with get_db_connection(self.db_path) as conn:
            cursor = await conn.execute(
                "SELECT value FROM preferences WHERE user_id = ? AND key = ?",
                (uid, key),
            )
            result = await cursor.fetchone()

            value = result[0] if result else None

        logger.debug(
            f"Retrieved preference {key} for user {uid}: {'found' if value else 'not found'}"
        )
        return value

    async def save_trade_history(
        self, user_id: str, token_address: str, action: str, amount: float
    ) -> None:
        """Save trade to history."""
        uid = self._normalize_user_id(user_id)
        async with get_db_connection(self.db_path) as conn:
            now = datetime.utcnow().isoformat()

            await conn.execute(
                """
                INSERT INTO trades (user_id, token_address, action, amount, timestamp)
                VALUES (?, ?, ?, ?, ?)
            """,
                (uid, token_address, action, amount, now),
            )

            await conn.commit()

        logger.info(f"Saved trade: {action} {amount} of {token_address} for user {uid}")

    async def get_trade_history(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent trades for user."""
        uid = self._normalize_user_id(user_id)
        async with get_db_connection(self.db_path) as conn:
            cursor = await conn.execute(
                """
                SELECT token_address, action, amount, timestamp
                FROM trades 
                WHERE user_id = ? 
                ORDER BY timestamp DESC 
                LIMIT ?
                """,
                (uid, limit),
            )

            results = await cursor.fetchall()

            trades = []
            for row in results:
                trades.append(
                    {
                        "token_address": row[0],
                        "action": row[1],
                        "amount": row[2],
                        "timestamp": row[3],
                    }
                )

        logger.debug(f"Retrieved {len(trades)} trades for user {uid}")
        return trades

    async def store_secure_data(
        self, user_id: str, encrypted_private_key: str, wallet_address: str
    ) -> None:
        """Store encrypted private key and wallet address."""
        uid = self._normalize_user_id(user_id)
        async with get_db_connection(self.db_path) as conn:
            now = datetime.utcnow().isoformat()

            # Use REPLACE to handle both insert and update
            await conn.execute(
                """
                REPLACE INTO secure_data (user_id, encrypted_private_key, wallet_address, created_at)
                VALUES (?, ?, ?, ?)
            """,
                (uid, encrypted_private_key, wallet_address, now),
            )

            await conn.commit()

        logger.info(f"Stored secure data for user {uid}")

    async def get_secure_data(self, user_id: str) -> Optional[Dict[str, str]]:
        """Get encrypted private key and wallet address for user."""
        uid = self._normalize_user_id(user_id)
        async with get_db_connection(self.db_path) as conn:
            cursor = await conn.execute(
                """
                SELECT encrypted_private_key, wallet_address 
                FROM secure_data 
                WHERE user_id = ?
                """,
                (uid,),
            )
            result = await cursor.fetchone()

            if result:
                data = {"encrypted_private_key": result[0], "wallet_address": result[1]}
            else:
                data = None

        logger.debug(f"Retrieved secure data for user {uid}: {'found' if data else 'not found'}")
        return data

    async def cleanup_old_sessions(self, days_old: int = 30, user_id: Optional[str] = None) -> int:
        """Clean up sessions older than specified days."""
        uid = self._normalize_user_id(user_id) if user_id is not None else None
        async with get_db_connection(self.db_path) as conn:
            # Use timedelta for proper date arithmetic
            cutoff_date = datetime.utcnow() - timedelta(days=days_old)
            cutoff_str = cutoff_date.isoformat()

            if uid is None:
                cursor = await conn.execute(
                    "DELETE FROM sessions WHERE updated_at < ?", (cutoff_str,)
                )
            else:
                cursor = await conn.execute(
                    "DELETE FROM sessions WHERE updated_at < ? AND user_id = ?",
                    (cutoff_str, uid),
                )

            deleted_count = cursor.rowcount or 0
            await conn.commit()

        logger.info(
            f"Cleaned up {deleted_count} old sessions (older than {days_old} days)"
            + (" for user " + uid if uid is not None else "")
        )
        return deleted_count

    async def cleanup_old_trades(self, days_old: int = 90, user_id: Optional[str] = None) -> int:
        """Clean up old trade history."""
        uid = self._normalize_user_id(user_id) if user_id is not None else None
        async with get_db_connection(self.db_path) as conn:
            cutoff_date = datetime.utcnow() - timedelta(days=days_old)
            cutoff_str = cutoff_date.isoformat()

            if uid is None:
                cursor = await conn.execute("DELETE FROM trades WHERE timestamp < ?", (cutoff_str,))
            else:
                cursor = await conn.execute(
                    "DELETE FROM trades WHERE timestamp < ? AND user_id = ?",
                    (cutoff_str, uid),
                )

            deleted_count = cursor.rowcount or 0
            await conn.commit()

        logger.info(
            f"Cleaned up {deleted_count} old trades (older than {days_old} days)"
            + (" for user " + uid if uid is not None else "")
        )
        return deleted_count

    async def vacuum_database(self) -> bool:
        """Vacuum the database to reclaim space after cleanup."""
        try:
            async with get_db_connection(self.db_path) as conn:
                await conn.execute("VACUUM")
                logger.info("Database vacuum completed successfully")
                return True
        except Exception as e:
            logger.error(f"Database vacuum failed: {e}")
            return False

    async def get_database_size(self) -> Dict[str, Any]:
        """Get database size information."""
        try:
            import os

            if os.path.exists(self.db_path):
                size_bytes = os.path.getsize(self.db_path)
                size_mb = size_bytes / (1024 * 1024)

                # Get row counts
                stats = await self.get_session_stats()

                return {
                    "size_bytes": size_bytes,
                    "size_mb": round(size_mb, 2),
                    "path": self.db_path,
                    "tables": stats,
                }
            else:
                return {"error": "Database file not found"}

        except Exception as e:
            logger.error(f"Failed to get database size: {e}")
            return {"error": str(e)}

    async def get_session_stats(self) -> Dict[str, int]:
        """Get database statistics."""
        async with get_db_connection(self.db_path) as conn:
            stats: Dict[str, int] = {}

            # Count sessions
            cursor = await conn.execute("SELECT COUNT(*) FROM sessions")
            result = await cursor.fetchone()
            stats["sessions"] = int(result[0]) if result else 0

            # Count preferences
            cursor = await conn.execute("SELECT COUNT(*) FROM preferences")
            result = await cursor.fetchone()
            stats["preferences"] = int(result[0]) if result else 0

            # Count trades
            cursor = await conn.execute("SELECT COUNT(*) FROM trades")
            result = await cursor.fetchone()
            stats["trades"] = int(result[0]) if result else 0

            # Count secure data entries
            cursor = await conn.execute("SELECT COUNT(*) FROM secure_data")
            result = await cursor.fetchone()
            stats["secure_data"] = int(result[0]) if result else 0

        logger.debug(f"Database stats: {stats}")
        return stats

    async def clear_session(self, session_id: str, user_id: Optional[str] = None) -> int:
        """Clear session messages from database."""
        uid = self._normalize_user_id(user_id)
        async with get_db_connection(self.db_path) as conn:
            cursor = await conn.execute(
                "DELETE FROM sessions WHERE session_id = ? AND user_id = ?",
                (session_id, uid),
            )
            deleted_count = cursor.rowcount or 0
            await conn.commit()

        logger.info(f"Cleared session {session_id} for user {uid}")
        return deleted_count

    async def list_sessions(
        self, limit: int = 20, user_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List recent conversation sessions with metadata.

        Returns newest-first up to `limit` sessions with:
        - session_id, created_at, updated_at, message_count
        """
        uid = self._normalize_user_id(user_id) if user_id is not None else None
        async with get_db_connection(self.db_path) as conn:
            if uid is None:
                cursor = await conn.execute(
                    """
                    SELECT session_id, user_id, created_at, updated_at, messages
                    FROM sessions
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
            else:
                cursor = await conn.execute(
                    """
                    SELECT session_id, user_id, created_at, updated_at, messages
                    FROM sessions
                    WHERE user_id = ?
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (uid, limit),
                )
            rows = await cursor.fetchall()

        sessions: List[Dict[str, Any]] = []
        for row in rows or []:
            try:
                msgs = json.loads(row[4]) if row[4] else []
            except Exception:
                msgs = []
            sessions.append(
                {
                    "session_id": row[0],
                    "user_id": row[1],
                    "created_at": row[2],
                    "updated_at": row[3],
                    "message_count": len(msgs) if isinstance(msgs, list) else 0,
                }
            )

        logger.debug(
            f"Listed {len(sessions)} sessions (limit={limit})"
            + (f" for user {uid}" if uid is not None else "")
        )
        return sessions

    async def clear_all_sessions(self, user_id: Optional[str] = None) -> int:
        """Delete conversation sessions.

        When user_id is provided, only that user's sessions are removed.
        """
        uid = self._normalize_user_id(user_id) if user_id is not None else None
        async with get_db_connection(self.db_path) as conn:
            if uid is None:
                cursor = await conn.execute("DELETE FROM sessions")
            else:
                cursor = await conn.execute("DELETE FROM sessions WHERE user_id = ?", (uid,))
            count = cursor.rowcount or 0
            await conn.commit()
        logger.info(
            "Cleared sessions"
            + (f" for user {uid}" if uid is not None else "")
            + f" (deleted {count} rows)"
        )
        return count

    async def get_latest_session(self, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get the most recently updated session, or None if no sessions exist."""
        uid = self._normalize_user_id(user_id) if user_id is not None else None
        async with get_db_connection(self.db_path) as conn:
            if uid is None:
                cursor = await conn.execute(
                    """
                    SELECT session_id, user_id, created_at, updated_at, messages
                    FROM sessions
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """
                )
            else:
                cursor = await conn.execute(
                    """
                    SELECT session_id, user_id, created_at, updated_at, messages
                    FROM sessions
                    WHERE user_id = ?
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (uid,),
                )
            row = await cursor.fetchone()

        if not row:
            return None
        try:
            msgs = cast(List[Message], json.loads(row[4]) if row[4] else [])
        except Exception:
            msgs = []
        return {
            "session_id": row[0],
            "user_id": row[1],
            "created_at": row[2],
            "updated_at": row[3],
            "message_count": len(msgs) if isinstance(msgs, list) else 0,
        }

    async def create_session(
        self,
        session_id: str,
        initial_messages: Optional[List[Message]] = None,
        user_id: Optional[str] = None,
    ) -> bool:
        """Create a new empty session if it doesn't exist.

        Returns True if created, False if already existed.
        """
        uid = self._normalize_user_id(user_id)
        async with get_db_connection(self.db_path) as conn:
            now = datetime.utcnow().isoformat()
            msgs_json = json.dumps(initial_messages or [])
            try:
                await conn.execute(
                    """
                    INSERT OR IGNORE INTO sessions (session_id, user_id, messages, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (session_id, uid, msgs_json, now, now),
                )
                await conn.commit()
            except Exception as e:
                logger.warning(f"Failed to create session {session_id}: {e}")
                return False

        logger.info(f"Created session {session_id} for user {uid}")
        return True
