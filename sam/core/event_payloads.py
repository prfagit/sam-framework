"""Typed payload schemas for SAM event bus notifications.

These TypedDict definitions can be imported by API adapters to ensure
consistency when streaming events to downstream clients.
"""

from __future__ import annotations

from typing import Any, Dict, Literal, TypedDict


AgentStatusState = Literal["start", "thinking", "tool_call", "fallback", "tool_done", "finish"]


class AgentStatusPayload(TypedDict, total=False):
    session_id: str
    user_id: str
    state: AgentStatusState
    message: str
    iteration: int
    name: str


class LLMUsagePayload(TypedDict, total=False):
    session_id: str
    user_id: str
    usage: Dict[str, Any]
    context_length: int


class ToolCalledPayload(TypedDict, total=False):
    session_id: str
    user_id: str
    name: str
    args: Dict[str, Any]
    tool_call_id: str


class ToolResultPayload(TypedDict, total=False):
    session_id: str
    user_id: str
    name: str
    args: Dict[str, Any]
    result: Any
    tool_call_id: str


class ToolFailedPayload(ToolResultPayload, total=False):
    error: Any


class AgentDeltaPayload(TypedDict, total=False):
    session_id: str
    user_id: str
    content: str


class AgentMessagePayload(TypedDict, total=False):
    session_id: str
    user_id: str
    content: str
    usage: Dict[str, Any]


__all__ = [
    "AgentStatusPayload",
    "AgentStatusState",
    "LLMUsagePayload",
    "ToolCalledPayload",
    "ToolResultPayload",
    "ToolFailedPayload",
    "AgentDeltaPayload",
    "AgentMessagePayload",
]
