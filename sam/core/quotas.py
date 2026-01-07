"""Per-user resource quota management for SAM Framework."""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional, Tuple
from dataclasses import dataclass

from ..utils.connection_pool import get_db_connection
from ..config.settings import Settings

logger = logging.getLogger(__name__)


@dataclass
class UserQuota:
    """User quota configuration and usage."""

    user_id: str
    max_sessions: int
    max_messages_per_session: int
    max_tokens_per_day: int
    max_agents: int
    tokens_used_today: int
    tokens_reset_at: datetime
    created_at: datetime

    def is_token_quota_exceeded(self) -> bool:
        """Check if daily token quota is exceeded."""
        # Reset if past reset time
        now = datetime.now(timezone.utc)
        if now >= self.tokens_reset_at:
            return False  # Will be reset on next check
        return self.tokens_used_today >= self.max_tokens_per_day

    def get_tokens_remaining(self) -> int:
        """Get remaining tokens for today."""
        now = datetime.now(timezone.utc)
        if now >= self.tokens_reset_at:
            return self.max_tokens_per_day
        return max(0, self.max_tokens_per_day - self.tokens_used_today)


class QuotaManager:
    """Manages per-user resource quotas."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    async def get_or_create_quota(
        self, user_id: str, defaults: Optional[Dict[str, int]] = None
    ) -> UserQuota:
        """Get user quota, creating with defaults if not exists."""
        defaults = defaults or {}

        # Get default values from settings or use hardcoded defaults
        max_sessions = defaults.get("max_sessions", Settings.SAM_QUOTA_MAX_SESSIONS)
        max_messages = defaults.get(
            "max_messages_per_session", Settings.SAM_QUOTA_MAX_MESSAGES_PER_SESSION
        )
        max_tokens = defaults.get("max_tokens_per_day", Settings.SAM_QUOTA_MAX_TOKENS_PER_DAY)
        max_agents = defaults.get("max_agents", Settings.SAM_QUOTA_MAX_AGENTS)

        async with get_db_connection(self.db_path) as conn:
            # Check if quota exists
            cursor = await conn.execute("SELECT * FROM user_quotas WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()

            if row:
                # Parse existing quota
                tokens_reset_at = (
                    datetime.fromisoformat(row[6])
                    if row[6]
                    else datetime.now(timezone.utc) + timedelta(days=1)
                )
                created_at = (
                    datetime.fromisoformat(row[7]) if row[7] else datetime.now(timezone.utc)
                )

                # Reset token usage if past reset time
                now = datetime.now(timezone.utc)
                tokens_used = row[5] if now < tokens_reset_at else 0
                if now >= tokens_reset_at:
                    # Reset tokens and update reset time
                    new_reset_at = now + timedelta(days=1)
                    await conn.execute(
                        """
                        UPDATE user_quotas 
                        SET tokens_used_today = 0, tokens_reset_at = ?
                        WHERE user_id = ?
                        """,
                        (new_reset_at.isoformat(), user_id),
                    )
                    await conn.commit()
                    tokens_reset_at = new_reset_at
                    tokens_used = 0

                return UserQuota(
                    user_id=row[0],
                    max_sessions=row[1],
                    max_messages_per_session=row[2],
                    max_tokens_per_day=row[3],
                    max_agents=row[4],
                    tokens_used_today=tokens_used,
                    tokens_reset_at=tokens_reset_at,
                    created_at=created_at,
                )
            else:
                # Create new quota with defaults
                now = datetime.now(timezone.utc)
                tokens_reset_at = now + timedelta(days=1)

                await conn.execute(
                    """
                    INSERT INTO user_quotas (
                        user_id, max_sessions, max_messages_per_session,
                        max_tokens_per_day, max_agents, tokens_used_today,
                        tokens_reset_at, created_at
                    ) VALUES (?, ?, ?, ?, ?, 0, ?, ?)
                    """,
                    (
                        user_id,
                        max_sessions,
                        max_messages,
                        max_tokens,
                        max_agents,
                        tokens_reset_at.isoformat(),
                        now.isoformat(),
                    ),
                )
                await conn.commit()

                return UserQuota(
                    user_id=user_id,
                    max_sessions=max_sessions,
                    max_messages_per_session=max_messages,
                    max_tokens_per_day=max_tokens,
                    max_agents=max_agents,
                    tokens_used_today=0,
                    tokens_reset_at=tokens_reset_at,
                    created_at=now,
                )

    async def check_session_quota(self, user_id: str) -> Tuple[bool, Optional[str]]:
        """Check if user can create a new session."""
        quota = await self.get_or_create_quota(user_id)

        # Count existing sessions
        from .memory_provider import create_memory_manager

        memory = create_memory_manager(self.db_path)
        await memory.initialize()
        sessions = await memory.list_sessions(limit=1000, user_id=user_id)

        if len(sessions) >= quota.max_sessions:
            return (
                False,
                f"Session limit reached ({quota.max_sessions} max). Please delete old sessions.",
            )

        return True, None

    async def check_agent_quota(self, user_id: str) -> Tuple[bool, Optional[str]]:
        """Check if user can create a new agent."""
        quota = await self.get_or_create_quota(user_id)

        # Count existing agents
        from ..api.storage import list_user_definitions

        try:
            agents = list_user_definitions(user_id)
            agent_count = len(agents)
        except Exception:
            # Fallback: count files directly
            import os

            agent_dir = os.path.join(Settings.SAM_API_AGENT_ROOT, user_id, "agents")
            if os.path.exists(agent_dir):
                agent_count = len([f for f in os.listdir(agent_dir) if f.endswith(".agent.toml")])
            else:
                agent_count = 0

        if agent_count >= quota.max_agents:
            return False, f"Agent limit reached ({quota.max_agents} max). Please delete old agents."

        return True, None

    async def check_token_quota(self, user_id: str, tokens: int) -> Tuple[bool, Optional[str]]:
        """Check if user can use tokens, and reserve them."""
        quota = await self.get_or_create_quota(user_id)

        # Reset if past reset time
        now = datetime.now(timezone.utc)
        if now >= quota.tokens_reset_at:
            # Reset tokens
            new_reset_at = now + timedelta(days=1)
            async with get_db_connection(self.db_path) as conn:
                await conn.execute(
                    """
                    UPDATE user_quotas 
                    SET tokens_used_today = 0, tokens_reset_at = ?
                    WHERE user_id = ?
                    """,
                    (new_reset_at.isoformat(), user_id),
                )
                await conn.commit()
            quota.tokens_used_today = 0
            quota.tokens_reset_at = new_reset_at

        if quota.tokens_used_today + tokens > quota.max_tokens_per_day:
            remaining = quota.max_tokens_per_day - quota.tokens_used_today
            return (
                False,
                f"Token quota exceeded. {remaining} tokens remaining today. Quota resets in {int((quota.tokens_reset_at - now).total_seconds() / 3600)} hours.",
            )

        # Reserve tokens
        async with get_db_connection(self.db_path) as conn:
            await conn.execute(
                """
                UPDATE user_quotas 
                SET tokens_used_today = tokens_used_today + ?
                WHERE user_id = ?
                """,
                (tokens, user_id),
            )
            await conn.commit()

        return True, None

    async def get_quota_status(self, user_id: str) -> Dict[str, Any]:
        """Get current quota status for a user."""
        quota = await self.get_or_create_quota(user_id)

        # Count actual usage
        from .memory_provider import create_memory_manager

        memory = create_memory_manager(self.db_path)
        await memory.initialize()
        sessions = await memory.list_sessions(limit=1000, user_id=user_id)

        # Count agents
        from ..api.storage import list_user_definitions

        try:
            agents = list_user_definitions(user_id)
            agent_count = len(agents)
        except Exception:
            # Fallback: count files directly
            import os

            agent_dir = os.path.join(Settings.SAM_API_AGENT_ROOT, user_id, "agents")
            if os.path.exists(agent_dir):
                agent_count = len([f for f in os.listdir(agent_dir) if f.endswith(".agent.toml")])
            else:
                agent_count = 0

        # Count messages in sessions (approximate)
        total_messages = 0
        for session in sessions[:10]:  # Sample first 10 sessions
            try:
                messages, _, _ = await memory.load_session(session["session_id"], user_id=user_id)
                total_messages += len(messages)
            except Exception:
                pass

        return {
            "user_id": user_id,
            "sessions": {
                "used": len(sessions),
                "limit": quota.max_sessions,
                "remaining": max(0, quota.max_sessions - len(sessions)),
            },
            "agents": {
                "used": agent_count,
                "limit": quota.max_agents,
                "remaining": max(0, quota.max_agents - agent_count),
            },
            "tokens": {
                "used_today": quota.tokens_used_today,
                "limit": quota.max_tokens_per_day,
                "remaining": quota.get_tokens_remaining(),
                "resets_at": quota.tokens_reset_at.isoformat(),
            },
            "messages_per_session": {
                "limit": quota.max_messages_per_session,
            },
        }

    async def update_quota(self, user_id: str, **updates: Dict[str, int]) -> UserQuota:
        """Update user quota limits (admin function)."""
        allowed_updates = {
            "max_sessions",
            "max_messages_per_session",
            "max_tokens_per_day",
            "max_agents",
        }

        updates = {k: v for k, v in updates.items() if k in allowed_updates}
        if not updates:
            raise ValueError("No valid quota fields to update")

        # Ensure quota exists before updating
        await self.get_or_create_quota(user_id)

        # Build update query
        set_clauses = []
        values = []
        for key, value in updates.items():
            set_clauses.append(f"{key} = ?")
            values.append(value)

        values.append(user_id)

        async with get_db_connection(self.db_path) as conn:
            await conn.execute(
                f"""
                UPDATE user_quotas 
                SET {", ".join(set_clauses)}
                WHERE user_id = ?
                """,
                tuple(values),
            )
            await conn.commit()

        # Return updated quota
        return await self.get_or_create_quota(user_id)


# Global quota manager instance
_quota_manager: Optional[QuotaManager] = None


def get_quota_manager(db_path: Optional[str] = None) -> QuotaManager:
    """Get or create global quota manager."""
    global _quota_manager
    if _quota_manager is None:
        _quota_manager = QuotaManager(db_path or Settings.SAM_DB_PATH)
    return _quota_manager
