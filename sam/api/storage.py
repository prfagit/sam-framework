"""Persistence helpers for user-scoped agent definitions.

This module provides a unified interface for agent storage that can use
either file-based storage (development) or database storage (production).

Storage backend is controlled by SAM_AGENT_STORAGE setting:
- "database" (default): Uses PostgreSQL/SQLite database storage
- "file": Uses TOML files on disk (legacy, not recommended for production)
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import List, Optional

import tomli_w

from ..agents.definition import AgentDefinition
from ..agents.manager import find_agent_definition, list_agent_definitions
from ..config.settings import Settings
from .db_storage import get_agent_db_storage
from .utils import get_user_agents_dir, sanitize_agent_name

logger = logging.getLogger(__name__)


def _definition_to_dict(definition: AgentDefinition) -> dict:
    return definition.model_dump(exclude={"path"}, exclude_none=True)


def _use_database_storage() -> bool:
    """Check if database storage should be used."""
    return Settings.SAM_AGENT_STORAGE == "database"


# =============================================================================
# File-based storage functions (legacy)
# =============================================================================


def _list_user_definitions_file(user_id: str) -> List[AgentDefinition]:
    """List agents from file storage."""
    directory = get_user_agents_dir(user_id)
    return list_agent_definitions(directory=directory)


def _load_user_definition_file(user_id: str, name: str) -> Optional[AgentDefinition]:
    """Load agent from file storage."""
    directory = get_user_agents_dir(user_id)
    result = find_agent_definition(name, directory=directory)
    if result is None:
        sanitized = sanitize_agent_name(name)
        if sanitized != name:
            result = find_agent_definition(sanitized, directory=directory)
    return result


def _save_user_definition_file(user_id: str, definition: AgentDefinition) -> Path:
    """Save agent to file storage."""
    directory = get_user_agents_dir(user_id)
    filename = f"{sanitize_agent_name(definition.name)}.agent.toml"
    path = directory / filename

    payload = _definition_to_dict(definition)
    toml_text = tomli_w.dumps(payload)
    path.write_text(toml_text, encoding="utf-8")
    definition.path = path
    return path


def _delete_user_definition_file(user_id: str, name: str) -> bool:
    """Delete agent from file storage."""
    directory = get_user_agents_dir(user_id)
    names_to_try = [sanitize_agent_name(name), name]
    for try_name in names_to_try:
        for suffix in (".agent.toml", ".toml"):
            candidate = directory / f"{try_name}{suffix}"
            if candidate.exists():
                candidate.unlink()
                return True
    return False


# =============================================================================
# Database storage functions
# =============================================================================


async def _list_user_definitions_db(user_id: str) -> List[AgentDefinition]:
    """List agents from database storage."""
    storage = get_agent_db_storage()
    records, _ = await storage.list_agents(user_id, include_templates=False)
    return [record.to_definition() for record in records]


async def _load_user_definition_db(user_id: str, name: str) -> Optional[AgentDefinition]:
    """Load agent from database storage."""
    storage = get_agent_db_storage()
    record = await storage.get_agent(user_id, name)
    if record is None:
        # Try sanitized name
        sanitized = sanitize_agent_name(name)
        if sanitized != name:
            record = await storage.get_agent(user_id, sanitized)
    return record.to_definition() if record else None


async def _save_user_definition_db(
    user_id: str, definition: AgentDefinition, update: bool = False
) -> AgentDefinition:
    """Save agent to database storage."""
    storage = get_agent_db_storage()
    if update:
        record = await storage.update_agent(user_id, definition.name, definition)
    else:
        try:
            record = await storage.create_agent(user_id, definition)
        except ValueError:
            # Agent already exists, update instead
            record = await storage.update_agent(user_id, definition.name, definition)
    return record.to_definition()


async def _delete_user_definition_db(user_id: str, name: str) -> bool:
    """Delete agent from database storage."""
    storage = get_agent_db_storage()
    # Try both exact name and sanitized name
    deleted = await storage.delete_agent(user_id, name)
    if not deleted:
        sanitized = sanitize_agent_name(name)
        if sanitized != name:
            deleted = await storage.delete_agent(user_id, sanitized)
    return deleted


async def _agent_exists_db(user_id: str, name: str) -> bool:
    """Check if agent exists in database."""
    storage = get_agent_db_storage()
    return await storage.agent_exists(user_id, name)


async def _count_user_agents_db(user_id: str) -> int:
    """Count user agents in database."""
    storage = get_agent_db_storage()
    return await storage.count_user_agents(user_id)


# =============================================================================
# Public API - Unified interface
# =============================================================================


def list_user_definitions(user_id: str) -> List[AgentDefinition]:
    """List all agent definitions for a user.

    Args:
        user_id: User identifier

    Returns:
        List of agent definitions
    """
    if _use_database_storage():
        return asyncio.get_event_loop().run_until_complete(_list_user_definitions_db(user_id))
    return _list_user_definitions_file(user_id)


async def list_user_definitions_async(user_id: str) -> List[AgentDefinition]:
    """Async version of list_user_definitions."""
    if _use_database_storage():
        return await _list_user_definitions_db(user_id)
    return _list_user_definitions_file(user_id)


def load_user_definition(user_id: str, name: str) -> Optional[AgentDefinition]:
    """Load an agent definition by name.

    Args:
        user_id: User identifier
        name: Agent name

    Returns:
        Agent definition or None if not found
    """
    if _use_database_storage():
        return asyncio.get_event_loop().run_until_complete(_load_user_definition_db(user_id, name))
    return _load_user_definition_file(user_id, name)


async def load_user_definition_async(user_id: str, name: str) -> Optional[AgentDefinition]:
    """Async version of load_user_definition."""
    if _use_database_storage():
        return await _load_user_definition_db(user_id, name)
    return _load_user_definition_file(user_id, name)


def save_user_definition(
    user_id: str, definition: AgentDefinition, update: bool = False
) -> Path | AgentDefinition:
    """Save an agent definition.

    Args:
        user_id: User identifier
        definition: Agent definition to save
        update: If True, update existing; if False, create new

    Returns:
        Path to saved file (file storage) or updated definition (database)
    """
    if _use_database_storage():
        return asyncio.get_event_loop().run_until_complete(
            _save_user_definition_db(user_id, definition, update)
        )
    return _save_user_definition_file(user_id, definition)


async def save_user_definition_async(
    user_id: str, definition: AgentDefinition, update: bool = False
) -> Path | AgentDefinition:
    """Async version of save_user_definition."""
    if _use_database_storage():
        return await _save_user_definition_db(user_id, definition, update)
    return _save_user_definition_file(user_id, definition)


def delete_user_definition(user_id: str, name: str) -> bool:
    """Delete an agent definition.

    Args:
        user_id: User identifier
        name: Agent name

    Returns:
        True if deleted, False if not found
    """
    if _use_database_storage():
        return asyncio.get_event_loop().run_until_complete(
            _delete_user_definition_db(user_id, name)
        )
    return _delete_user_definition_file(user_id, name)


async def delete_user_definition_async(user_id: str, name: str) -> bool:
    """Async version of delete_user_definition."""
    if _use_database_storage():
        return await _delete_user_definition_db(user_id, name)
    return _delete_user_definition_file(user_id, name)


async def agent_exists_async(user_id: str, name: str) -> bool:
    """Check if an agent exists.

    Args:
        user_id: User identifier
        name: Agent name

    Returns:
        True if agent exists
    """
    if _use_database_storage():
        return await _agent_exists_db(user_id, name)
    return _load_user_definition_file(user_id, name) is not None


async def count_user_agents_async(user_id: str) -> int:
    """Count agents for a user.

    Args:
        user_id: User identifier

    Returns:
        Number of agents
    """
    if _use_database_storage():
        return await _count_user_agents_db(user_id)
    return len(_list_user_definitions_file(user_id))


__all__ = [
    # Sync functions
    "delete_user_definition",
    "list_user_definitions",
    "load_user_definition",
    "save_user_definition",
    # Async functions
    "delete_user_definition_async",
    "list_user_definitions_async",
    "load_user_definition_async",
    "save_user_definition_async",
    "agent_exists_async",
    "count_user_agents_async",
]
