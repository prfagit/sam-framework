from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, cast

from ..utils.connection_pool import get_db_connection, execute_with_logging
from ..utils.sanitize import sanitize_messages, sanitize_session_name
from .migration_definitions import register_all_migrations
from .migrations import get_migration_manager

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
        # Register and run migrations
        await register_all_migrations(self.db_path)
        manager = get_migration_manager(self.db_path)
        await manager.initialize()
        applied = await manager.migrate()
        if applied > 0:
            logger.info(f"Applied {applied} migration(s)")

        # Run legacy initialization for backward compatibility
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
                            agent_name TEXT,
                            session_name TEXT,
                            messages TEXT NOT NULL,
                            created_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL
                        )
                        """
                    )

                    # Ensure user_id and agent_name columns exist for pre-existing tables
                    cursor = await conn.execute("PRAGMA table_info(sessions)")
                    columns = [row[1] for row in await cursor.fetchall()]
                    if "user_id" not in columns:
                        await conn.execute(
                            "ALTER TABLE sessions ADD COLUMN user_id TEXT NOT NULL DEFAULT 'default'"
                        )
                    if "agent_name" not in columns:
                        await conn.execute("ALTER TABLE sessions ADD COLUMN agent_name TEXT")

                    await conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_sessions_updated_at ON sessions(updated_at)"
                    )
                    await conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, updated_at)"
                    )
                    await conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_sessions_agent_name ON sessions(agent_name)"
                    )
                    await conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_sessions_user_agent ON sessions(user_id, agent_name, updated_at)"
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
                    await conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_trades_user_timestamp ON trades(user_id, timestamp)"
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

                    # Create refresh_tokens table for JWT refresh token management
                    await conn.execute("""
                        CREATE TABLE IF NOT EXISTS refresh_tokens (
                            token_id TEXT PRIMARY KEY,
                            user_id TEXT NOT NULL,
                            token_hash TEXT NOT NULL,
                            expires_at TEXT NOT NULL,
                            created_at TEXT NOT NULL,
                            revoked INTEGER NOT NULL DEFAULT 0
                        )
                    """)
                    await conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user ON refresh_tokens(user_id, expires_at)"
                    )
                    await conn.execute(
                        "CREATE INDEX IF NOT EXISTS idx_refresh_tokens_hash ON refresh_tokens(token_hash)"
                    )

                    await conn.commit()
                    return  # Success, exit retry loop

            except Exception as e:
                logger.warning(f"Database initialization attempt {attempt + 1} failed: {e}")
                if attempt == max_retries - 1:
                    logger.error(f"Failed to initialize database after {max_retries} attempts: {e}")
                    raise
                await asyncio.sleep(retry_delay * (2**attempt))

    async def save_session(
        self,
        session_id: str,
        messages: List[Message],
        user_id: Optional[str] = None,
        agent_name: Optional[str] = None,
        session_name: Optional[str] = None,
    ) -> None:
        """Save session messages to database with optimized query logging."""
        uid = self._normalize_user_id(user_id)

        # Sanitize input before storage
        sanitized_messages = sanitize_messages(messages)
        sanitized_session_name = sanitize_session_name(session_name) if session_name else None

        async with get_db_connection(self.db_path) as conn:
            now = datetime.utcnow().isoformat()

            messages_json = json.dumps(sanitized_messages)

            # Use UPSERT to reduce round-trips with SQL logging support
            await execute_with_logging(
                conn,
                """
                INSERT INTO sessions (session_id, user_id, agent_name, session_name, messages, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                  messages = excluded.messages,
                  updated_at = excluded.updated_at,
                  user_id = excluded.user_id,
                  agent_name = COALESCE(excluded.agent_name, sessions.agent_name),
                  session_name = COALESCE(excluded.session_name, sessions.session_name)
                """,
                (session_id, uid, agent_name, sanitized_session_name, messages_json, now, now),
            )

            await conn.commit()
            logger.debug(
                f"Saved session {session_id} for user {uid} with {len(messages)} messages (agent: {agent_name})"
            )

    async def load_session(
        self, session_id: str, user_id: Optional[str] = None
    ) -> Tuple[List[Message], Optional[str], Optional[str]]:
        """Load session messages from database with optimized query logging."""
        uid = self._normalize_user_id(user_id)
        async with get_db_connection(self.db_path) as conn:
            cursor = await execute_with_logging(
                conn,
                "SELECT messages, agent_name, session_name FROM sessions WHERE session_id = ? AND user_id = ?",
                (session_id, uid),
            )
            result = await cursor.fetchone()

            if result:
                messages = cast(List[Message], json.loads(result[0]))
                agent_name = result[1]
                session_name = result[2]
            else:
                messages = []
                agent_name = None
                session_name = None

        logger.debug(f"Loaded session {session_id} for user {uid} with {len(messages)} messages")
        return messages, agent_name, session_name

    async def save_sessions_batch(
        self, sessions: List[Tuple[str, List[Message], Optional[str]]]
    ) -> None:
        """Save multiple sessions in a single transaction for better performance.

        Args:
            sessions: List of (session_id, messages, user_id) tuples

        Example:
            await memory.save_sessions_batch([
                ("session1", messages1, "user1"),
                ("session2", messages2, "user2"),
            ])
        """
        if not sessions:
            return

        async with get_db_connection(self.db_path) as conn:
            now = datetime.utcnow().isoformat()

            # Prepare all data for batch insert
            batch_data = [
                (
                    session_id,
                    self._normalize_user_id(user_id),
                    json.dumps(messages),
                    now,
                    now,
                )
                for session_id, messages, user_id in sessions
            ]

            # Execute batch UPSERT
            await conn.executemany(
                """
                INSERT INTO sessions (session_id, user_id, messages, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                  messages = excluded.messages,
                  updated_at = excluded.updated_at,
                  user_id = excluded.user_id
                """,
                batch_data,
            )

            await conn.commit()
            logger.debug(f"Batch saved {len(sessions)} sessions")

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
                    SELECT session_id, user_id, agent_name, session_name, created_at, updated_at, messages
                    FROM sessions
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
            else:
                cursor = await conn.execute(
                    """
                    SELECT session_id, user_id, agent_name, session_name, created_at, updated_at, messages
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
            # Column order: session_id(0), user_id(1), agent_name(2), session_name(3),
            #               created_at(4), updated_at(5), messages(6)
            try:
                msgs = json.loads(row[6]) if row[6] else []
            except Exception:
                msgs = []

            # Get last message for preview (first non-system message from end)
            last_message = None
            if isinstance(msgs, list) and len(msgs) > 0:
                # Find last user or assistant message
                for msg in reversed(msgs):
                    if isinstance(msg, dict) and msg.get("role") in ("user", "assistant"):
                        content = msg.get("content", "")
                        # Truncate long messages for preview
                        if len(content) > 100:
                            last_message = content[:100] + "..."
                        else:
                            last_message = content
                        break

            sessions.append(
                {
                    "session_id": row[0],
                    "user_id": row[1],
                    "agent_name": row[2],
                    "session_name": row[3],
                    "created_at": row[4],
                    "updated_at": row[5],
                    "message_count": len(msgs) if isinstance(msgs, list) else 0,
                    "last_message": last_message,
                }
            )

        logger.debug(
            f"Listed {len(sessions)} sessions (limit={limit})"
            + (f" for user {uid}" if uid is not None else "")
        )
        return sessions

    async def update_session_name(
        self,
        session_id: str,
        session_name: Optional[str],
        user_id: Optional[str] = None,
    ) -> bool:
        """Update the name of a session.

        Args:
            session_id: The session ID
            session_name: New name for the session (None to clear)
            user_id: Optional user ID for filtering

        Returns:
            True if session was updated, False if not found
        """
        uid = self._normalize_user_id(user_id) if user_id is not None else None
        async with get_db_connection(self.db_path) as conn:
            if uid is None:
                cursor = await execute_with_logging(
                    conn,
                    "UPDATE sessions SET session_name = ?, updated_at = ? WHERE session_id = ?",
                    (session_name, datetime.now(timezone.utc).isoformat(), session_id),
                )
            else:
                cursor = await execute_with_logging(
                    conn,
                    "UPDATE sessions SET session_name = ?, updated_at = ? WHERE session_id = ? AND user_id = ?",
                    (session_name, datetime.now(timezone.utc).isoformat(), session_id, uid),
                )
            await conn.commit()
            return cursor.rowcount > 0

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
        agent_name: Optional[str] = None,
        session_name: Optional[str] = None,
    ) -> bool:
        """Create a new empty session if it doesn't exist.

        Returns True if created, False if already existed.
        """
        uid = self._normalize_user_id(user_id)

        # Sanitize input before storage
        sanitized_messages = sanitize_messages(initial_messages or [])
        sanitized_session_name = sanitize_session_name(session_name) if session_name else None

        async with get_db_connection(self.db_path) as conn:
            now = datetime.utcnow().isoformat()
            msgs_json = json.dumps(sanitized_messages)
            try:
                await conn.execute(
                    """
                    INSERT OR IGNORE INTO sessions (session_id, user_id, agent_name, session_name, messages, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (session_id, uid, agent_name, sanitized_session_name, msgs_json, now, now),
                )
                await conn.commit()
            except Exception as e:
                logger.warning(f"Failed to create session {session_id}: {e}")
                return False

        logger.info(f"Created session {session_id} for user {uid} (agent: {agent_name})")
        return True
