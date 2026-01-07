"""Storage layer for public agent sharing and marketplace functionality."""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple

from ..config.settings import Settings
from ..utils.connection_pool import get_db_connection


@dataclass
class PublicAgentEntry:
    """Represents a public agent entry in the database."""

    id: int
    public_id: str
    user_id: str
    agent_name: str
    visibility: Literal["private", "unlisted", "public"]
    share_token: Optional[str]
    published_at: Optional[datetime]
    download_count: int
    created_at: datetime
    updated_at: datetime
    # Computed fields (not stored directly)
    rating: Optional[float] = None
    rating_count: int = 0

    @classmethod
    def from_row(cls, row: tuple) -> "PublicAgentEntry":
        """Create entry from database row."""
        return cls(
            id=row[0],
            public_id=row[1],
            user_id=row[2],
            agent_name=row[3],
            visibility=row[4],
            share_token=row[5],
            published_at=datetime.fromisoformat(row[6]) if row[6] else None,
            download_count=row[7],
            created_at=datetime.fromisoformat(row[8]),
            updated_at=datetime.fromisoformat(row[9]),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "public_id": self.public_id,
            "user_id": self.user_id,
            "agent_name": self.agent_name,
            "visibility": self.visibility,
            "share_token": self.share_token,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "download_count": self.download_count,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "rating": self.rating,
            "rating_count": self.rating_count,
        }


@dataclass
class AgentRating:
    """Represents an agent rating."""

    id: int
    public_id: str
    user_id: str
    rating: int
    comment: Optional[str]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: tuple) -> "AgentRating":
        """Create rating from database row."""
        return cls(
            id=row[0],
            public_id=row[1],
            user_id=row[2],
            rating=row[3],
            comment=row[4],
            created_at=datetime.fromisoformat(row[5]),
            updated_at=datetime.fromisoformat(row[6]),
        )


def _generate_public_id() -> str:
    """Generate a unique public ID for an agent."""
    return str(uuid.uuid4())[:8]


def _generate_share_token() -> str:
    """Generate a secure share token for unlisted agents."""
    return secrets.token_urlsafe(32)


class PublicAgentStorage:
    """Storage operations for public agents and ratings."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or Settings.SAM_DB_PATH

    async def publish_agent(
        self,
        user_id: str,
        agent_name: str,
        visibility: Literal["private", "unlisted", "public"] = "public",
    ) -> PublicAgentEntry:
        """
        Publish an agent to the marketplace or generate share link.

        Args:
            user_id: Owner's user ID
            agent_name: Name of the agent
            visibility: 'private', 'unlisted', or 'public'

        Returns:
            PublicAgentEntry with public_id and share_token if applicable
        """
        now = datetime.now(timezone.utc).isoformat()
        public_id = _generate_public_id()
        share_token = _generate_share_token() if visibility in ("unlisted", "public") else None
        published_at = now if visibility == "public" else None

        async with get_db_connection(self.db_path) as conn:
            # Check if already exists
            cursor = await conn.execute(
                "SELECT id, public_id FROM public_agents WHERE user_id = ? AND agent_name = ?",
                (user_id, agent_name),
            )
            existing = await cursor.fetchone()

            if existing:
                # Update existing entry
                await conn.execute(
                    """
                    UPDATE public_agents
                    SET visibility = ?, share_token = COALESCE(share_token, ?),
                        published_at = COALESCE(published_at, ?), updated_at = ?
                    WHERE id = ?
                    """,
                    (visibility, share_token, published_at, now, existing[0]),
                )
                public_id = existing[1]
            else:
                # Create new entry
                await conn.execute(
                    """
                    INSERT INTO public_agents
                    (public_id, user_id, agent_name, visibility, share_token, published_at,
                     download_count, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
                    """,
                    (
                        public_id,
                        user_id,
                        agent_name,
                        visibility,
                        share_token,
                        published_at,
                        now,
                        now,
                    ),
                )

            await conn.commit()

        # Return the entry
        return await self.get_by_public_id(public_id)  # type: ignore

    async def unpublish_agent(self, user_id: str, agent_name: str) -> bool:
        """
        Unpublish an agent (set to private).

        Returns:
            True if agent was unpublished, False if not found
        """
        now = datetime.now(timezone.utc).isoformat()

        async with get_db_connection(self.db_path) as conn:
            cursor = await conn.execute(
                """
                UPDATE public_agents
                SET visibility = 'private', published_at = NULL, updated_at = ?
                WHERE user_id = ? AND agent_name = ?
                """,
                (now, user_id, agent_name),
            )
            await conn.commit()
            return cursor.rowcount > 0

    async def delete_public_entry(self, user_id: str, agent_name: str) -> bool:
        """
        Delete the public entry for an agent entirely.

        Returns:
            True if deleted, False if not found
        """
        async with get_db_connection(self.db_path) as conn:
            # First get the public_id to delete ratings
            cursor = await conn.execute(
                "SELECT public_id FROM public_agents WHERE user_id = ? AND agent_name = ?",
                (user_id, agent_name),
            )
            row = await cursor.fetchone()
            if row:
                public_id = row[0]
                # Delete ratings
                await conn.execute(
                    "DELETE FROM agent_ratings WHERE public_id = ?",
                    (public_id,),
                )

            # Delete public agent entry
            cursor = await conn.execute(
                "DELETE FROM public_agents WHERE user_id = ? AND agent_name = ?",
                (user_id, agent_name),
            )
            await conn.commit()
            return cursor.rowcount > 0

    async def generate_share_token(self, user_id: str, agent_name: str) -> Optional[str]:
        """
        Generate a new share token for an agent.

        Returns:
            The new share token, or None if agent not found
        """
        now = datetime.now(timezone.utc).isoformat()
        new_token = _generate_share_token()

        async with get_db_connection(self.db_path) as conn:
            cursor = await conn.execute(
                """
                UPDATE public_agents
                SET share_token = ?, updated_at = ?
                WHERE user_id = ? AND agent_name = ?
                """,
                (new_token, now, user_id, agent_name),
            )
            await conn.commit()
            return new_token if cursor.rowcount > 0 else None

    async def get_by_public_id(self, public_id: str) -> Optional[PublicAgentEntry]:
        """Get a public agent entry by its public ID."""
        async with get_db_connection(self.db_path) as conn:
            cursor = await conn.execute(
                """
                SELECT id, public_id, user_id, agent_name, visibility, share_token,
                       published_at, download_count, created_at, updated_at
                FROM public_agents
                WHERE public_id = ?
                """,
                (public_id,),
            )
            row = await cursor.fetchone()
            if not row:
                return None

            entry = PublicAgentEntry.from_row(row)

            # Get rating info
            rating_info = await self._get_rating_info(conn, public_id)
            entry.rating = rating_info[0]
            entry.rating_count = rating_info[1]

            return entry

    async def get_by_share_token(self, share_token: str) -> Optional[PublicAgentEntry]:
        """Get a public agent entry by its share token."""
        async with get_db_connection(self.db_path) as conn:
            cursor = await conn.execute(
                """
                SELECT id, public_id, user_id, agent_name, visibility, share_token,
                       published_at, download_count, created_at, updated_at
                FROM public_agents
                WHERE share_token = ?
                """,
                (share_token,),
            )
            row = await cursor.fetchone()
            if not row:
                return None

            entry = PublicAgentEntry.from_row(row)

            # Get rating info
            rating_info = await self._get_rating_info(conn, entry.public_id)
            entry.rating = rating_info[0]
            entry.rating_count = rating_info[1]

            return entry

    async def get_for_agent(self, user_id: str, agent_name: str) -> Optional[PublicAgentEntry]:
        """Get public agent entry for a specific user's agent."""
        async with get_db_connection(self.db_path) as conn:
            cursor = await conn.execute(
                """
                SELECT id, public_id, user_id, agent_name, visibility, share_token,
                       published_at, download_count, created_at, updated_at
                FROM public_agents
                WHERE user_id = ? AND agent_name = ?
                """,
                (user_id, agent_name),
            )
            row = await cursor.fetchone()
            if not row:
                return None

            entry = PublicAgentEntry.from_row(row)

            # Get rating info
            rating_info = await self._get_rating_info(conn, entry.public_id)
            entry.rating = rating_info[0]
            entry.rating_count = rating_info[1]

            return entry

    async def list_public_agents(
        self,
        limit: int = 20,
        offset: int = 0,
        search: Optional[str] = None,
        tags: Optional[List[str]] = None,
        sort: Literal["popular", "recent", "rating"] = "popular",
        exclude_user_id: Optional[str] = None,
    ) -> Tuple[List[PublicAgentEntry], int]:
        """
        List public agents for the marketplace.

        Args:
            limit: Maximum number of results
            offset: Pagination offset
            search: Search query for agent name
            tags: Filter by tags (not implemented yet - requires agent definition lookup)
            sort: Sort order - 'popular', 'recent', or 'rating'
            exclude_user_id: Exclude agents from this user

        Returns:
            Tuple of (list of entries, total count)
        """
        # Build query
        where_clauses = ["visibility = 'public'"]
        params: List[Any] = []

        if search:
            where_clauses.append("agent_name LIKE ?")
            params.append(f"%{search}%")

        if exclude_user_id:
            where_clauses.append("user_id != ?")
            params.append(exclude_user_id)

        where_sql = " AND ".join(where_clauses)

        # Determine sort
        if sort == "recent":
            order_sql = "published_at DESC"
        elif sort == "rating":
            # Will need subquery for rating
            order_sql = "download_count DESC"  # Fallback for now
        else:  # popular
            order_sql = "download_count DESC"

        async with get_db_connection(self.db_path) as conn:
            # Get total count
            count_cursor = await conn.execute(
                f"SELECT COUNT(*) FROM public_agents WHERE {where_sql}",
                params,
            )
            count_row = await count_cursor.fetchone()
            total_count = count_row[0] if count_row else 0

            # Get entries
            cursor = await conn.execute(
                f"""
                SELECT id, public_id, user_id, agent_name, visibility, share_token,
                       published_at, download_count, created_at, updated_at
                FROM public_agents
                WHERE {where_sql}
                ORDER BY {order_sql}
                LIMIT ? OFFSET ?
                """,
                params + [limit, offset],
            )
            rows = await cursor.fetchall()

            entries = []
            for row in rows:
                entry = PublicAgentEntry.from_row(row)
                # Get rating info
                rating_info = await self._get_rating_info(conn, entry.public_id)
                entry.rating = rating_info[0]
                entry.rating_count = rating_info[1]
                entries.append(entry)

            return entries, total_count

    async def increment_download_count(self, public_id: str) -> bool:
        """Increment the download count for an agent."""
        async with get_db_connection(self.db_path) as conn:
            cursor = await conn.execute(
                """
                UPDATE public_agents
                SET download_count = download_count + 1,
                    updated_at = ?
                WHERE public_id = ?
                """,
                (datetime.now(timezone.utc).isoformat(), public_id),
            )
            await conn.commit()
            return cursor.rowcount > 0

    async def add_rating(
        self,
        public_id: str,
        user_id: str,
        rating: int,
        comment: Optional[str] = None,
    ) -> AgentRating:
        """
        Add or update a rating for an agent.

        Args:
            public_id: Public ID of the agent
            user_id: User giving the rating
            rating: Rating value (1-5)
            comment: Optional comment

        Returns:
            The created or updated rating
        """
        if not 1 <= rating <= 5:
            raise ValueError("Rating must be between 1 and 5")

        now = datetime.now(timezone.utc).isoformat()

        async with get_db_connection(self.db_path) as conn:
            # Upsert rating
            await conn.execute(
                """
                INSERT INTO agent_ratings (public_id, user_id, rating, comment, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(public_id, user_id) DO UPDATE SET
                    rating = excluded.rating,
                    comment = excluded.comment,
                    updated_at = excluded.updated_at
                """,
                (public_id, user_id, rating, comment, now, now),
            )
            await conn.commit()

            # Get the rating
            cursor = await conn.execute(
                """
                SELECT id, public_id, user_id, rating, comment, created_at, updated_at
                FROM agent_ratings
                WHERE public_id = ? AND user_id = ?
                """,
                (public_id, user_id),
            )
            row = await cursor.fetchone()
            return AgentRating.from_row(row)  # type: ignore

    async def get_user_rating(self, public_id: str, user_id: str) -> Optional[AgentRating]:
        """Get a specific user's rating for an agent."""
        async with get_db_connection(self.db_path) as conn:
            cursor = await conn.execute(
                """
                SELECT id, public_id, user_id, rating, comment, created_at, updated_at
                FROM agent_ratings
                WHERE public_id = ? AND user_id = ?
                """,
                (public_id, user_id),
            )
            row = await cursor.fetchone()
            return AgentRating.from_row(row) if row else None

    async def get_agent_ratings(
        self,
        public_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> Tuple[List[AgentRating], int]:
        """Get all ratings for an agent."""
        async with get_db_connection(self.db_path) as conn:
            # Get count
            count_cursor = await conn.execute(
                "SELECT COUNT(*) FROM agent_ratings WHERE public_id = ?",
                (public_id,),
            )
            count_row = await count_cursor.fetchone()
            total_count = count_row[0] if count_row else 0

            # Get ratings
            cursor = await conn.execute(
                """
                SELECT id, public_id, user_id, rating, comment, created_at, updated_at
                FROM agent_ratings
                WHERE public_id = ?
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (public_id, limit, offset),
            )
            rows = await cursor.fetchall()
            ratings = [AgentRating.from_row(row) for row in rows]

            return ratings, total_count

    async def _get_rating_info(self, conn: Any, public_id: str) -> Tuple[Optional[float], int]:
        """Get average rating and count for an agent."""
        cursor = await conn.execute(
            """
            SELECT AVG(rating), COUNT(*)
            FROM agent_ratings
            WHERE public_id = ?
            """,
            (public_id,),
        )
        row = await cursor.fetchone()
        if row and row[1] > 0:
            return (round(row[0], 2), row[1])
        return (None, 0)

    async def get_marketplace_stats(self) -> "MarketplaceStats":
        """Get overall marketplace statistics."""
        async with get_db_connection(self.db_path) as conn:
            # Total public agents
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM public_agents WHERE visibility = 'public'"
            )
            row = await cursor.fetchone()
            total_public = row[0] if row else 0

            # Average rating across all rated agents
            cursor = await conn.execute(
                """
                SELECT AVG(rating), COUNT(DISTINCT public_id)
                FROM agent_ratings
                """
            )
            row = await cursor.fetchone()
            avg_rating = round(row[0], 2) if row and row[0] else None
            rated_agents = row[1] if row else 0

            # Total downloads
            cursor = await conn.execute(
                "SELECT COALESCE(SUM(download_count), 0) FROM public_agents"
            )
            row = await cursor.fetchone()
            total_downloads = row[0] if row else 0

            return MarketplaceStats(
                total_public_agents=total_public,
                average_rating=avg_rating,
                rated_agents=rated_agents,
                total_downloads=total_downloads,
            )


@dataclass
class MarketplaceStats:
    """Marketplace statistics."""

    total_public_agents: int
    average_rating: Optional[float]
    rated_agents: int
    total_downloads: int


# Global instance
_public_storage: Optional[PublicAgentStorage] = None


def get_public_storage(db_path: Optional[str] = None) -> PublicAgentStorage:
    """Get or create the global public storage instance."""
    global _public_storage
    if _public_storage is None:
        _public_storage = PublicAgentStorage(db_path)
    return _public_storage


__all__ = [
    "PublicAgentEntry",
    "AgentRating",
    "PublicAgentStorage",
    "get_public_storage",
]
