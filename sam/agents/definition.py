"""Agent definitions for declarative agent configuration."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, validator


class LLMConfig(BaseModel):
    """LLM configuration overrides for an agent definition."""

    provider: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    api_key_env: Optional[str] = Field(
        default=None,
        description="Environment variable containing the API key to use for this agent.",
    )


class ToolConfig(BaseModel):
    """Tool bundle activation entry."""

    name: str
    enabled: bool = True
    config: Dict[str, Any] = Field(default_factory=dict)

    @validator("name")
    def normalize_name(cls, value: str) -> str:  # noqa: D401
        return value.strip().lower()


class AgentMetadata(BaseModel):
    author: Optional[str] = None
    version: Optional[str] = None
    homepage: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


class AgentDefinition(BaseModel):
    """Declarative description of an agent."""

    name: str
    description: str = ""
    system_prompt: str
    llm: Optional[LLMConfig] = None
    tools: List[ToolConfig] = Field(default_factory=list)
    metadata: AgentMetadata = Field(default_factory=AgentMetadata)
    memory: Dict[str, Any] = Field(default_factory=dict)
    middleware: Dict[str, Any] = Field(default_factory=dict)
    variables: Dict[str, Any] = Field(default_factory=dict)

    # Non-serialised attributes
    path: Optional[Path] = Field(default=None, exclude=True)

    @property
    def enabled_tools(self) -> Dict[str, ToolConfig]:
        """Return a mapping of enabled tool bundles by name."""
        return {tool.name: tool for tool in self.tools if tool.enabled}

    @classmethod
    def load(cls, path: Path) -> "AgentDefinition":
        resolved = path.resolve()
        data = tomllib.loads(resolved.read_text(encoding="utf-8"))
        definition = cls(**data)
        definition.path = resolved
        return definition

    @classmethod
    def from_dict(cls, data: Dict[str, Any], *, path: Optional[Path] = None) -> "AgentDefinition":
        definition = cls(**data)
        definition.path = path
        return definition


def default_agents_dir() -> Path:
    """Return default directory for agent definitions."""
    return Path(os.getenv("SAM_AGENTS_DIR", "agents"))
