"""Agent definitions for declarative agent configuration."""

from __future__ import annotations

import os
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, validator


# Visibility options for agent sharing
AgentVisibility = Literal["private", "unlisted", "public"]


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
    """Metadata for an agent definition including sharing settings."""

    # Basic metadata
    author: Optional[str] = None
    version: Optional[str] = None
    homepage: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    license: Optional[str] = Field(
        default=None,
        description="License for the agent (e.g., 'MIT', 'Apache-2.0', 'proprietary')",
    )

    # Sharing and visibility settings
    visibility: AgentVisibility = Field(
        default="private",
        description="Agent visibility: 'private' (owner only), 'unlisted' (link access), 'public' (marketplace)",
    )
    public_id: Optional[str] = Field(
        default=None,
        description="Unique public identifier for marketplace discovery",
    )
    share_token: Optional[str] = Field(
        default=None,
        description="Secret token for unlisted sharing via link",
    )
    published_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp when agent was published to marketplace",
    )

    # Public statistics (populated from database, not stored in TOML)
    download_count: int = Field(
        default=0,
        description="Number of times this agent has been cloned",
    )
    rating: Optional[float] = Field(
        default=None,
        description="Average rating (1-5 stars)",
    )
    rating_count: int = Field(
        default=0,
        description="Number of ratings received",
    )


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
