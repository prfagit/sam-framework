"""Database storage layer for agent definitions.

This module provides ACID-compliant storage for agent definitions,
replacing the file-based storage for production deployments.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..agents.definition import (
    AgentDefinition,
    AgentMetadata,
    LLMConfig,
    ToolConfig,
)
from ..config.settings import Settings
from ..utils.connection_pool import get_db_connection


@dataclass
class AgentRecord:
    """Database record for an agent."""

    id: int
    user_id: str
    name: str
    description: Optional[str]
    system_prompt: str
    llm_config: Optional[Dict[str, Any]]
    tools_config: Optional[List[Dict[str, Any]]]
    metadata: Optional[Dict[str, Any]]
    variables: Optional[Dict[str, Any]]
    memory_config: Optional[Dict[str, Any]]
    middleware_config: Optional[Dict[str, Any]]
    is_template: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: tuple) -> "AgentRecord":
        """Create record from database row."""
        return cls(
            id=row[0],
            user_id=row[1],
            name=row[2],
            description=row[3],
            system_prompt=row[4],
            llm_config=json.loads(row[5]) if row[5] else None,
            tools_config=json.loads(row[6]) if row[6] else None,
            metadata=json.loads(row[7]) if row[7] else None,
            variables=json.loads(row[8]) if row[8] else None,
            memory_config=json.loads(row[9]) if row[9] else None,
            middleware_config=json.loads(row[10]) if row[10] else None,
            is_template=bool(row[11]),
            created_at=datetime.fromisoformat(row[12]),
            updated_at=datetime.fromisoformat(row[13]),
        )

    def to_definition(self) -> AgentDefinition:
        """Convert database record to AgentDefinition."""
        # Build LLM config
        llm = None
        if self.llm_config:
            llm = LLMConfig(**self.llm_config)

        # Build tools config
        tools = []
        if self.tools_config:
            for tool_data in self.tools_config:
                tools.append(ToolConfig(**tool_data))

        # Build metadata
        metadata = None
        if self.metadata:
            metadata = AgentMetadata(**self.metadata)

        return AgentDefinition(
            name=self.name,
            description=self.description or "",
            system_prompt=self.system_prompt,
            llm=llm,
            tools=tools,
            metadata=metadata,
            variables=self.variables or {},
            memory=self.memory_config or {},
            middleware=self.middleware_config or {},
        )


@dataclass
class AgentVersionRecord:
    """Database record for an agent version."""

    id: int
    agent_id: int
    version_number: int
    name: str
    description: Optional[str]
    system_prompt: str
    llm_config: Optional[Dict[str, Any]]
    tools_config: Optional[List[Dict[str, Any]]]
    metadata: Optional[Dict[str, Any]]
    variables: Optional[Dict[str, Any]]
    memory_config: Optional[Dict[str, Any]]
    middleware_config: Optional[Dict[str, Any]]
    change_summary: Optional[str]
    created_at: datetime
    created_by: str

    @classmethod
    def from_row(cls, row: tuple) -> "AgentVersionRecord":
        """Create record from database row."""
        return cls(
            id=row[0],
            agent_id=row[1],
            version_number=row[2],
            name=row[3],
            description=row[4],
            system_prompt=row[5],
            llm_config=json.loads(row[6]) if row[6] else None,
            tools_config=json.loads(row[7]) if row[7] else None,
            metadata=json.loads(row[8]) if row[8] else None,
            variables=json.loads(row[9]) if row[9] else None,
            memory_config=json.loads(row[10]) if row[10] else None,
            middleware_config=json.loads(row[11]) if row[11] else None,
            change_summary=row[12],
            created_at=datetime.fromisoformat(row[13]),
            created_by=row[14],
        )


class AgentDatabaseStorage:
    """Database storage operations for agent definitions."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or Settings.SAM_DB_PATH

    async def create_agent(
        self,
        user_id: str,
        definition: AgentDefinition,
        is_template: bool = False,
    ) -> AgentRecord:
        """
        Create a new agent in the database.

        Args:
            user_id: Owner's user ID
            definition: Agent definition to store
            is_template: Whether this is a template agent

        Returns:
            Created AgentRecord

        Raises:
            ValueError: If agent with same name already exists for user
        """
        now = datetime.now(timezone.utc).isoformat()

        # Serialize complex fields to JSON
        llm_json = json.dumps(definition.llm.model_dump()) if definition.llm else None
        tools_json = (
            json.dumps([t.model_dump() for t in definition.tools]) if definition.tools else None
        )
        metadata_json = (
            json.dumps(definition.metadata.model_dump()) if definition.metadata else None
        )
        variables_json = json.dumps(definition.variables) if definition.variables else None
        memory_json = json.dumps(definition.memory) if definition.memory else None
        middleware_json = json.dumps(definition.middleware) if definition.middleware else None

        async with get_db_connection(self.db_path) as conn:
            # Check if agent already exists
            cursor = await conn.execute(
                "SELECT id FROM agents WHERE user_id = ? AND name = ?",
                (user_id, definition.name),
            )
            existing = await cursor.fetchone()
            if existing:
                raise ValueError(f"Agent '{definition.name}' already exists for user")

            # Insert new agent
            cursor = await conn.execute(
                """
                INSERT INTO agents (
                    user_id, name, description, system_prompt,
                    llm_config, tools_config, metadata, variables,
                    memory_config, middleware_config, is_template,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    definition.name,
                    definition.description,
                    definition.system_prompt,
                    llm_json,
                    tools_json,
                    metadata_json,
                    variables_json,
                    memory_json,
                    middleware_json,
                    1 if is_template else 0,
                    now,
                    now,
                ),
            )
            await conn.commit()
            agent_id = cursor.lastrowid

            # Create initial version
            await self._create_version(
                conn,
                agent_id,
                definition,
                user_id,
                "Initial version",
            )
            await conn.commit()

        return await self.get_agent(user_id, definition.name)  # type: ignore

    async def update_agent(
        self,
        user_id: str,
        name: str,
        definition: AgentDefinition,
        change_summary: Optional[str] = None,
    ) -> AgentRecord:
        """
        Update an existing agent.

        Args:
            user_id: Owner's user ID
            name: Current agent name
            definition: Updated agent definition
            change_summary: Description of changes

        Returns:
            Updated AgentRecord

        Raises:
            ValueError: If agent not found
        """
        now = datetime.now(timezone.utc).isoformat()

        # Serialize complex fields
        llm_json = json.dumps(definition.llm.model_dump()) if definition.llm else None
        tools_json = (
            json.dumps([t.model_dump() for t in definition.tools]) if definition.tools else None
        )
        metadata_json = (
            json.dumps(definition.metadata.model_dump()) if definition.metadata else None
        )
        variables_json = json.dumps(definition.variables) if definition.variables else None
        memory_json = json.dumps(definition.memory) if definition.memory else None
        middleware_json = json.dumps(definition.middleware) if definition.middleware else None

        async with get_db_connection(self.db_path) as conn:
            # Get existing agent
            cursor = await conn.execute(
                "SELECT id FROM agents WHERE user_id = ? AND name = ?",
                (user_id, name),
            )
            row = await cursor.fetchone()
            if not row:
                raise ValueError(f"Agent '{name}' not found for user")

            agent_id = row[0]

            # Update agent
            await conn.execute(
                """
                UPDATE agents SET
                    name = ?, description = ?, system_prompt = ?,
                    llm_config = ?, tools_config = ?, metadata = ?,
                    variables = ?, memory_config = ?, middleware_config = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    definition.name,
                    definition.description,
                    definition.system_prompt,
                    llm_json,
                    tools_json,
                    metadata_json,
                    variables_json,
                    memory_json,
                    middleware_json,
                    now,
                    agent_id,
                ),
            )

            # Create version record
            await self._create_version(
                conn,
                agent_id,
                definition,
                user_id,
                change_summary or "Updated agent",
            )
            await conn.commit()

        return await self.get_agent(user_id, definition.name)  # type: ignore

    async def delete_agent(self, user_id: str, name: str) -> bool:
        """
        Delete an agent.

        Args:
            user_id: Owner's user ID
            name: Agent name

        Returns:
            True if deleted, False if not found
        """
        async with get_db_connection(self.db_path) as conn:
            cursor = await conn.execute(
                "DELETE FROM agents WHERE user_id = ? AND name = ?",
                (user_id, name),
            )
            await conn.commit()
            return cursor.rowcount > 0

    async def get_agent(self, user_id: str, name: str) -> Optional[AgentRecord]:
        """
        Get an agent by user and name.

        Args:
            user_id: Owner's user ID
            name: Agent name

        Returns:
            AgentRecord if found, None otherwise
        """
        async with get_db_connection(self.db_path) as conn:
            cursor = await conn.execute(
                """
                SELECT id, user_id, name, description, system_prompt,
                       llm_config, tools_config, metadata, variables,
                       memory_config, middleware_config, is_template,
                       created_at, updated_at
                FROM agents
                WHERE user_id = ? AND name = ?
                """,
                (user_id, name),
            )
            row = await cursor.fetchone()
            if not row:
                return None
            return AgentRecord.from_row(row)

    async def get_agent_by_id(self, agent_id: int) -> Optional[AgentRecord]:
        """Get an agent by its database ID."""
        async with get_db_connection(self.db_path) as conn:
            cursor = await conn.execute(
                """
                SELECT id, user_id, name, description, system_prompt,
                       llm_config, tools_config, metadata, variables,
                       memory_config, middleware_config, is_template,
                       created_at, updated_at
                FROM agents
                WHERE id = ?
                """,
                (agent_id,),
            )
            row = await cursor.fetchone()
            if not row:
                return None
            return AgentRecord.from_row(row)

    async def list_agents(
        self,
        user_id: str,
        include_templates: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[AgentRecord], int]:
        """
        List agents for a user.

        Args:
            user_id: Owner's user ID
            include_templates: Whether to include template agents
            limit: Maximum results
            offset: Pagination offset

        Returns:
            Tuple of (list of agents, total count)
        """
        async with get_db_connection(self.db_path) as conn:
            # Build query
            if include_templates:
                where_clause = "(user_id = ? OR is_template = 1)"
                params: tuple = (user_id,)
            else:
                where_clause = "user_id = ?"
                params = (user_id,)

            # Get count
            cursor = await conn.execute(
                f"SELECT COUNT(*) FROM agents WHERE {where_clause}",
                params,
            )
            count_row = await cursor.fetchone()
            total = count_row[0] if count_row else 0

            # Get records
            cursor = await conn.execute(
                f"""
                SELECT id, user_id, name, description, system_prompt,
                       llm_config, tools_config, metadata, variables,
                       memory_config, middleware_config, is_template,
                       created_at, updated_at
                FROM agents
                WHERE {where_clause}
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                params + (limit, offset),
            )
            rows = await cursor.fetchall()
            agents = [AgentRecord.from_row(row) for row in rows]

            return agents, total

    async def agent_exists(self, user_id: str, name: str) -> bool:
        """Check if an agent exists."""
        async with get_db_connection(self.db_path) as conn:
            cursor = await conn.execute(
                "SELECT 1 FROM agents WHERE user_id = ? AND name = ?",
                (user_id, name),
            )
            return await cursor.fetchone() is not None

    async def count_user_agents(self, user_id: str) -> int:
        """Count agents for a user (excluding templates)."""
        async with get_db_connection(self.db_path) as conn:
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM agents WHERE user_id = ? AND is_template = 0",
                (user_id,),
            )
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def get_agent_versions(
        self,
        user_id: str,
        name: str,
        limit: int = 20,
        offset: int = 0,
    ) -> Tuple[List[AgentVersionRecord], int]:
        """
        Get version history for an agent.

        Args:
            user_id: Owner's user ID
            name: Agent name
            limit: Maximum results
            offset: Pagination offset

        Returns:
            Tuple of (list of versions, total count)
        """
        async with get_db_connection(self.db_path) as conn:
            # Get agent ID
            cursor = await conn.execute(
                "SELECT id FROM agents WHERE user_id = ? AND name = ?",
                (user_id, name),
            )
            row = await cursor.fetchone()
            if not row:
                return [], 0

            agent_id = row[0]

            # Get count
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM agent_versions WHERE agent_id = ?",
                (agent_id,),
            )
            count_row = await cursor.fetchone()
            total = count_row[0] if count_row else 0

            # Get versions
            cursor = await conn.execute(
                """
                SELECT id, agent_id, version_number, name, description,
                       system_prompt, llm_config, tools_config, metadata,
                       variables, memory_config, middleware_config,
                       change_summary, created_at, created_by
                FROM agent_versions
                WHERE agent_id = ?
                ORDER BY version_number DESC
                LIMIT ? OFFSET ?
                """,
                (agent_id, limit, offset),
            )
            rows = await cursor.fetchall()
            versions = [AgentVersionRecord.from_row(row) for row in rows]

            return versions, total

    async def restore_version(
        self,
        user_id: str,
        name: str,
        version_number: int,
    ) -> AgentRecord:
        """
        Restore an agent to a previous version.

        Args:
            user_id: Owner's user ID
            name: Agent name
            version_number: Version to restore

        Returns:
            Updated AgentRecord

        Raises:
            ValueError: If agent or version not found
        """
        async with get_db_connection(self.db_path) as conn:
            # Get agent ID
            cursor = await conn.execute(
                "SELECT id FROM agents WHERE user_id = ? AND name = ?",
                (user_id, name),
            )
            row = await cursor.fetchone()
            if not row:
                raise ValueError(f"Agent '{name}' not found")

            agent_id = row[0]

            # Get version
            cursor = await conn.execute(
                """
                SELECT name, description, system_prompt, llm_config,
                       tools_config, metadata, variables, memory_config,
                       middleware_config
                FROM agent_versions
                WHERE agent_id = ? AND version_number = ?
                """,
                (agent_id, version_number),
            )
            version_row = await cursor.fetchone()
            if not version_row:
                raise ValueError(f"Version {version_number} not found")

            now = datetime.now(timezone.utc).isoformat()

            # Update agent with version data
            await conn.execute(
                """
                UPDATE agents SET
                    name = ?, description = ?, system_prompt = ?,
                    llm_config = ?, tools_config = ?, metadata = ?,
                    variables = ?, memory_config = ?, middleware_config = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                version_row + (now, agent_id),
            )

            # Create new version record for the restore
            await self._create_version_from_row(
                conn,
                agent_id,
                version_row,
                user_id,
                f"Restored from version {version_number}",
            )
            await conn.commit()

        return await self.get_agent(user_id, version_row[0])  # type: ignore

    async def _create_version(
        self,
        conn,
        agent_id: int,
        definition: AgentDefinition,
        created_by: str,
        change_summary: str,
    ) -> None:
        """Create a version record for an agent."""
        now = datetime.now(timezone.utc).isoformat()

        # Get next version number
        cursor = await conn.execute(
            "SELECT COALESCE(MAX(version_number), 0) + 1 FROM agent_versions WHERE agent_id = ?",
            (agent_id,),
        )
        row = await cursor.fetchone()
        version_number = row[0] if row else 1

        # Serialize fields
        llm_json = json.dumps(definition.llm.model_dump()) if definition.llm else None
        tools_json = (
            json.dumps([t.model_dump() for t in definition.tools]) if definition.tools else None
        )
        metadata_json = (
            json.dumps(definition.metadata.model_dump()) if definition.metadata else None
        )
        variables_json = json.dumps(definition.variables) if definition.variables else None
        memory_json = json.dumps(definition.memory) if definition.memory else None
        middleware_json = json.dumps(definition.middleware) if definition.middleware else None

        await conn.execute(
            """
            INSERT INTO agent_versions (
                agent_id, version_number, name, description, system_prompt,
                llm_config, tools_config, metadata, variables,
                memory_config, middleware_config, change_summary,
                created_at, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                agent_id,
                version_number,
                definition.name,
                definition.description,
                definition.system_prompt,
                llm_json,
                tools_json,
                metadata_json,
                variables_json,
                memory_json,
                middleware_json,
                change_summary,
                now,
                created_by,
            ),
        )

    async def _create_version_from_row(
        self,
        conn,
        agent_id: int,
        row: tuple,
        created_by: str,
        change_summary: str,
    ) -> None:
        """Create a version record from a raw database row."""
        now = datetime.now(timezone.utc).isoformat()

        # Get next version number
        cursor = await conn.execute(
            "SELECT COALESCE(MAX(version_number), 0) + 1 FROM agent_versions WHERE agent_id = ?",
            (agent_id,),
        )
        version_row = await cursor.fetchone()
        version_number = version_row[0] if version_row else 1

        await conn.execute(
            """
            INSERT INTO agent_versions (
                agent_id, version_number, name, description, system_prompt,
                llm_config, tools_config, metadata, variables,
                memory_config, middleware_config, change_summary,
                created_at, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (agent_id, version_number) + row + (change_summary, now, created_by),
        )


# Global instance
_agent_db_storage: Optional[AgentDatabaseStorage] = None


def get_agent_db_storage(db_path: Optional[str] = None) -> AgentDatabaseStorage:
    """Get or create the global agent database storage instance."""
    global _agent_db_storage
    if _agent_db_storage is None:
        _agent_db_storage = AgentDatabaseStorage(db_path)
    return _agent_db_storage


__all__ = [
    "AgentRecord",
    "AgentVersionRecord",
    "AgentDatabaseStorage",
    "get_agent_db_storage",
]
