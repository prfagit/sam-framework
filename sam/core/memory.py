from pydantic import BaseModel
import json
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
import logging
import os
from ..utils.connection_pool import get_db_connection

logger = logging.getLogger(__name__)


class SessionMemory(BaseModel):
    session_id: str
    messages: List[Dict]
    created_at: datetime
    updated_at: datetime


class UserPreference(BaseModel):
    user_id: str
    key: str
    value: str
    created_at: datetime


class TradeHistory(BaseModel):
    user_id: str
    token_address: str
    action: str  # buy/sell
    amount: float
    timestamp: datetime


class SecureData(BaseModel):
    user_id: str
    encrypted_private_key: str
    wallet_address: str
    created_at: datetime


class MemoryManager:
    def __init__(self, db_path: str):
        self.db_path = db_path

        # Ensure directory exists (handle case where db_path has no directory)
        dirpath = os.path.dirname(db_path) or "."
        os.makedirs(dirpath, exist_ok=True)

        logger.info(f"Initialized memory manager with database: {db_path}")

    # Connection pooling is now handled by the connection_pool utility

    async def initialize(self):
        """Initialize database tables. Must be called after creating the manager."""
        await self._init_database()
        logger.info(f"Database tables initialized: {self.db_path}")

    async def _init_database(self):
        """Initialize database tables using connection pool."""
        max_retries = 3
        retry_delay = 0.5
        
        for attempt in range(max_retries):
            try:
                async with get_db_connection(self.db_path) as conn:
                    # Create sessions table
                    await conn.execute("""
                    CREATE TABLE IF NOT EXISTS sessions (
                        session_id TEXT PRIMARY KEY,
                        messages TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """)

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
                await asyncio.sleep(retry_delay * (2 ** attempt))

    async def save_session(self, session_id: str, messages: List[Dict]):
        """Save session messages to database."""
        async with get_db_connection(self.db_path) as conn:
            now = datetime.utcnow().isoformat()

            # Check if session exists
            cursor = await conn.execute(
                "SELECT created_at FROM sessions WHERE session_id = ?", (session_id,)
            )
            existing = await cursor.fetchone()

            messages_json = json.dumps(messages)

            if existing:
                # Update existing session
                await conn.execute(
                    """
                    UPDATE sessions 
                    SET messages = ?, updated_at = ? 
                    WHERE session_id = ?
                """,
                    (messages_json, now, session_id),
                )
            else:
                # Create new session
                await conn.execute(
                    """
                    INSERT INTO sessions (session_id, messages, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                """,
                    (session_id, messages_json, now, now),
                )

            await conn.commit()
            logger.debug(f"Saved session {session_id} with {len(messages)} messages")

    async def load_session(self, session_id: str) -> List[Dict]:
        """Load session messages from database."""
        async with get_db_connection(self.db_path) as conn:
            cursor = await conn.execute(
                "SELECT messages FROM sessions WHERE session_id = ?", (session_id,)
            )
            result = await cursor.fetchone()

            if result:
                messages = json.loads(result[0])
            else:
                messages = []

        logger.debug(f"Loaded session {session_id} with {len(messages)} messages")
        return messages

    async def save_user_preference(self, user_id: str, key: str, value: str):
        """Save user preference."""
        async with get_db_connection(self.db_path) as conn:
            now = datetime.utcnow().isoformat()

            # Use REPLACE to handle both insert and update
            await conn.execute(
                """
                REPLACE INTO preferences (user_id, key, value, created_at)
                VALUES (?, ?, ?, ?)
            """,
                (user_id, key, value, now),
            )

            await conn.commit()

        logger.debug(f"Saved preference {key} for user {user_id}")

    async def get_user_preference(self, user_id: str, key: str) -> Optional[str]:
        """Get user preference."""
        async with get_db_connection(self.db_path) as conn:
            cursor = await conn.execute(
                "SELECT value FROM preferences WHERE user_id = ? AND key = ?", (user_id, key)
            )
            result = await cursor.fetchone()

            value = result[0] if result else None

        logger.debug(
            f"Retrieved preference {key} for user {user_id}: {'found' if value else 'not found'}"
        )
        return value

    async def save_trade_history(
        self, user_id: str, token_address: str, action: str, amount: float
    ):
        """Save trade to history."""
        async with get_db_connection(self.db_path) as conn:
            now = datetime.utcnow().isoformat()

            await conn.execute(
                """
                INSERT INTO trades (user_id, token_address, action, amount, timestamp)
                VALUES (?, ?, ?, ?, ?)
            """,
                (user_id, token_address, action, amount, now),
            )

            await conn.commit()

        logger.info(f"Saved trade: {action} {amount} of {token_address} for user {user_id}")

    async def get_trade_history(self, user_id: str, limit: int = 10) -> List[Dict]:
        """Get recent trades for user."""
        async with get_db_connection(self.db_path) as conn:
            cursor = await conn.execute(
                """
                SELECT token_address, action, amount, timestamp
                FROM trades 
                WHERE user_id = ? 
                ORDER BY timestamp DESC 
                LIMIT ?
            """,
                (user_id, limit),
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

        logger.debug(f"Retrieved {len(trades)} trades for user {user_id}")
        return trades

    async def store_secure_data(
        self, user_id: str, encrypted_private_key: str, wallet_address: str
    ):
        """Store encrypted private key and wallet address."""
        async with get_db_connection(self.db_path) as conn:
            now = datetime.utcnow().isoformat()

            # Use REPLACE to handle both insert and update
            await conn.execute(
                """
                REPLACE INTO secure_data (user_id, encrypted_private_key, wallet_address, created_at)
                VALUES (?, ?, ?, ?)
            """,
                (user_id, encrypted_private_key, wallet_address, now),
            )

            await conn.commit()

        logger.info(f"Stored secure data for user {user_id}")

    async def get_secure_data(self, user_id: str) -> Optional[Dict[str, str]]:
        """Get encrypted private key and wallet address for user."""
        async with get_db_connection(self.db_path) as conn:
            cursor = await conn.execute(
                """
                SELECT encrypted_private_key, wallet_address 
                FROM secure_data 
                WHERE user_id = ?
            """,
                (user_id,),
            )
            result = await cursor.fetchone()

            if result:
                data = {"encrypted_private_key": result[0], "wallet_address": result[1]}
            else:
                data = None

        logger.debug(
            f"Retrieved secure data for user {user_id}: {'found' if data else 'not found'}"
        )
        return data

    async def cleanup_old_sessions(self, days_old: int = 30):
        """Clean up sessions older than specified days."""
        async with get_db_connection(self.db_path) as conn:
            # Use timedelta for proper date arithmetic
            cutoff_date = datetime.utcnow() - timedelta(days=days_old)
            cutoff_str = cutoff_date.isoformat()

            cursor = await conn.execute("DELETE FROM sessions WHERE updated_at < ?", (cutoff_str,))

            deleted_count = cursor.rowcount
            await conn.commit()

        logger.info(f"Cleaned up {deleted_count} old sessions (older than {days_old} days)")
        return deleted_count

    async def cleanup_old_trades(self, days_old: int = 90):
        """Clean up old trade history."""
        async with get_db_connection(self.db_path) as conn:
            cutoff_date = datetime.utcnow() - timedelta(days=days_old)
            cutoff_str = cutoff_date.isoformat()

            cursor = await conn.execute("DELETE FROM trades WHERE timestamp < ?", (cutoff_str,))

            deleted_count = cursor.rowcount
            await conn.commit()

        logger.info(f"Cleaned up {deleted_count} old trades (older than {days_old} days)")
        return deleted_count

    async def vacuum_database(self):
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
            stats = {}

            # Count sessions
            cursor = await conn.execute("SELECT COUNT(*) FROM sessions")
            result = await cursor.fetchone()
            stats["sessions"] = result[0] if result else 0

            # Count preferences
            cursor = await conn.execute("SELECT COUNT(*) FROM preferences")
            result = await cursor.fetchone()
            stats["preferences"] = result[0] if result else 0

            # Count trades
            cursor = await conn.execute("SELECT COUNT(*) FROM trades")
            result = await cursor.fetchone()
            stats["trades"] = result[0] if result else 0

            # Count secure data entries
            cursor = await conn.execute("SELECT COUNT(*) FROM secure_data")
            result = await cursor.fetchone()
            stats["secure_data"] = result[0] if result else 0

        logger.debug(f"Database stats: {stats}")
        return stats

    async def clear_session(self, session_id: str) -> int:
        """Clear session messages from database."""
        async with get_db_connection(self.db_path) as conn:
            cursor = await conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            deleted_count = cursor.rowcount
            await conn.commit()

        logger.info(f"Cleared session {session_id}")
        return deleted_count
