"""Example SAM plugin that registers simple tools.

Usage (from repo root):

  export SAM_PLUGINS="examples.plugins.simple_plugin.plugin"
  uv run sam tools

This registers two demo tools: `echo` and `time_now`.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field

from sam.core.tools import Tool, ToolSpec


class EchoInput(BaseModel):
    message: str = Field(..., description="Text to echo back")


async def handle_echo(args: Dict[str, Any]) -> Dict[str, Any]:
    return {"echo": args.get("message", "")}


async def handle_time_now(_: Dict[str, Any]) -> Dict[str, Any]:
    return {"now": datetime.now(timezone.utc).isoformat()}


def register(registry, agent: Optional[object] = None) -> None:
    """Register example tools into the SAM ToolRegistry.

    Accepts the registry and optional agent reference (unused here).
    """

    echo_tool = Tool(
        spec=ToolSpec(
            name="echo",
            description="Echo back a provided message",
            input_schema={"parameters": {}},  # Will be auto-filled from input_model
            namespace="examples",
            version="0.1.0",
        ),
        handler=handle_echo,
        input_model=EchoInput,
    )

    time_tool = Tool(
        spec=ToolSpec(
            name="time_now",
            description="Return the current UTC timestamp in ISO format",
            input_schema={"parameters": {"type": "object", "properties": {}}},
            namespace="examples",
            version="0.1.0",
        ),
        handler=handle_time_now,
    )

    registry.register(echo_tool)
    registry.register(time_tool)
