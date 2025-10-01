"""Utilities for working with agent definition files."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from .definition import AgentDefinition, default_agents_dir

AGENT_FILE_SUFFIXES = (".agent.toml", ".toml")


def _iter_definition_paths(directory: Path) -> List[Path]:
    if not directory.exists():
        return []
    paths: List[Path] = []
    seen: set[Path] = set()
    for suffix in AGENT_FILE_SUFFIXES:
        for candidate in sorted(directory.glob(f"*{suffix}")):
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            paths.append(resolved)
    return paths


def list_agent_definitions(directory: Optional[Path] = None) -> List[AgentDefinition]:
    agents_dir = directory or default_agents_dir()
    definitions: List[AgentDefinition] = []
    for path in _iter_definition_paths(agents_dir):
        try:
            definitions.append(AgentDefinition.load(path))
        except Exception:
            continue
    return definitions


def find_agent_definition(name: str, directory: Optional[Path] = None) -> Optional[AgentDefinition]:
    agents_dir = directory or default_agents_dir()

    # Allow explicit path
    candidate_path = Path(name)
    if candidate_path.exists():
        try:
            return AgentDefinition.load(candidate_path)
        except Exception:
            return None

    for suffix in AGENT_FILE_SUFFIXES:
        path = agents_dir / f"{name}{suffix}"
        if path.exists():
            try:
                return AgentDefinition.load(path)
            except Exception:
                return None
    return None


def ensure_agents_dir(directory: Optional[Path] = None) -> Path:
    agents_dir = directory or default_agents_dir()
    agents_dir.mkdir(parents=True, exist_ok=True)
    return agents_dir
