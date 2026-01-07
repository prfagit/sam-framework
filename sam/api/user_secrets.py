"""User secrets storage.

Stores user-specific API keys and secrets encrypted in the database.
Each user can only access their own secrets.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from cryptography.fernet import Fernet

from ..config.settings import Settings
from ..db import get_engine

logger = logging.getLogger(__name__)


def _get_fernet() -> Optional[Fernet]:
    """Get Fernet instance for encryption."""
    key = Settings.SAM_FERNET_KEY
    if not key:
        logger.warning("SAM_FERNET_KEY not set, secrets will not be encrypted")
        return None
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as e:
        logger.error(f"Failed to initialize Fernet: {e}")
        return None


class UserSecretsStore:
    """Store and retrieve user-specific secrets."""

    def __init__(self) -> None:
        self._fernet = _get_fernet()

    def _encrypt(self, value: str) -> str:
        """Encrypt a value."""
        if not self._fernet:
            return value
        return self._fernet.encrypt(value.encode()).decode()

    def _decrypt(self, value: str) -> str:
        """Decrypt a value."""
        if not self._fernet:
            return value
        try:
            return self._fernet.decrypt(value.encode()).decode()
        except Exception:
            return value

    async def _ensure_table(self) -> None:
        """Ensure the user_secrets table exists."""
        db = await get_engine()
        async with db.connection() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_secrets (
                    user_id TEXT NOT NULL,
                    integration TEXT NOT NULL,
                    field TEXT NOT NULL,
                    encrypted_value TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, integration, field)
                )
            """)
            await conn.commit()

    async def set_secret(self, user_id: str, integration: str, field: str, value: str) -> bool:
        """Set a secret value."""
        try:
            await self._ensure_table()
            encrypted = self._encrypt(value)

            db = await get_engine()
            async with db.connection() as conn:
                await conn.execute(
                    """
                    INSERT INTO user_secrets (user_id, integration, field, encrypted_value, updated_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT (user_id, integration, field)
                    DO UPDATE SET encrypted_value = ?, updated_at = CURRENT_TIMESTAMP
                    """,
                    (user_id, integration, field, encrypted, encrypted),
                )
                await conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to set secret: {e}")
            return False

    async def get_secret(self, user_id: str, integration: str, field: str) -> Optional[str]:
        """Get a secret value (decrypted)."""
        try:
            await self._ensure_table()
            db = await get_engine()
            async with db.connection() as conn:
                cursor = await conn.execute(
                    """
                    SELECT encrypted_value FROM user_secrets
                    WHERE user_id = ? AND integration = ? AND field = ?
                    """,
                    (user_id, integration, field),
                )
                row = await cursor.fetchone()
                if row:
                    return self._decrypt(row[0])
            return None
        except Exception as e:
            logger.error(f"Failed to get secret: {e}")
            return None

    async def delete_secret(self, user_id: str, integration: str, field: str) -> bool:
        """Delete a secret."""
        try:
            await self._ensure_table()
            db = await get_engine()
            async with db.connection() as conn:
                await conn.execute(
                    """
                    DELETE FROM user_secrets
                    WHERE user_id = ? AND integration = ? AND field = ?
                    """,
                    (user_id, integration, field),
                )
                await conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to delete secret: {e}")
            return False

    async def delete_integration(self, user_id: str, integration: str) -> bool:
        """Delete all secrets for an integration."""
        try:
            await self._ensure_table()
            db = await get_engine()
            async with db.connection() as conn:
                await conn.execute(
                    """
                    DELETE FROM user_secrets
                    WHERE user_id = ? AND integration = ?
                    """,
                    (user_id, integration),
                )
                await conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to delete integration secrets: {e}")
            return False

    async def get_configured_integrations(self, user_id: str) -> List[str]:
        """Get list of integrations that have at least one secret set."""
        try:
            await self._ensure_table()
            db = await get_engine()
            async with db.connection() as conn:
                cursor = await conn.execute(
                    """
                    SELECT DISTINCT integration FROM user_secrets
                    WHERE user_id = ?
                    """,
                    (user_id,),
                )
                rows = await cursor.fetchall()
                return [row[0] for row in rows]
        except Exception as e:
            logger.error(f"Failed to get configured integrations: {e}")
            return []

    async def get_all_statuses(self, user_id: str) -> List[Dict[str, Any]]:
        """Get status of all secrets for a user."""
        try:
            await self._ensure_table()
            db = await get_engine()
            async with db.connection() as conn:
                cursor = await conn.execute(
                    """
                    SELECT integration, field FROM user_secrets
                    WHERE user_id = ?
                    """,
                    (user_id,),
                )
                rows = await cursor.fetchall()
                return [{"integration": row[0], "field": row[1], "is_set": True} for row in rows]
        except Exception as e:
            logger.error(f"Failed to get secret statuses: {e}")
            return []

    async def get_integration_secrets(self, user_id: str, integration: str) -> Dict[str, str]:
        """Get all secrets for an integration (for use by tools)."""
        try:
            await self._ensure_table()
            db = await get_engine()
            async with db.connection() as conn:
                cursor = await conn.execute(
                    """
                    SELECT field, encrypted_value FROM user_secrets
                    WHERE user_id = ? AND integration = ?
                    """,
                    (user_id, integration),
                )
                rows = await cursor.fetchall()
                return {row[0]: self._decrypt(row[1]) for row in rows}
        except Exception as e:
            logger.error(f"Failed to get integration secrets: {e}")
            return {}
