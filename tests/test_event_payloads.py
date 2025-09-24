import pytest
from typing import cast

from sam.core.event_payloads import (
    AgentDeltaPayload,
    AgentMessagePayload,
    AgentStatusPayload,
    AgentStatusState,
    LLMUsagePayload,
    ToolCalledPayload,
    ToolFailedPayload,
    ToolResultPayload,
)


def test_agent_status_payload_typing():
    payload: AgentStatusPayload = {
        "session_id": "sess-123",
        "user_id": "user-456",
        "state": cast(AgentStatusState, "thinking"),
        "message": "Thinking",
        "iteration": 2,
    }
    assert payload["state"] == "thinking"
    assert payload["iteration"] == 2


def test_llm_usage_payload():
    payload: LLMUsagePayload = {
        "session_id": "sess-123",
        "user_id": "user-456",
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        "context_length": 7,
    }
    assert payload["usage"]["prompt_tokens"] == 10


def test_tool_payloads():
    result_payload: ToolResultPayload = {
        "session_id": "sess-123",
        "user_id": "user-456",
        "name": "search_web",
        "args": {"query": "solana news"},
        "result": {"status": "ok"},
        "tool_call_id": "call-1",
    }
    failed_payload: ToolFailedPayload = {
        **result_payload,
        "error": {"message": "timeout"},
    }
    assert failed_payload["error"]["message"] == "timeout"


def test_agent_output_payloads():
    delta_payload: AgentDeltaPayload = {
        "session_id": "sess-123",
        "user_id": "user-456",
        "content": "partial text",
    }
    message_payload: AgentMessagePayload = {
        "session_id": "sess-123",
        "user_id": "user-456",
        "content": "final text",
        "usage": {"total_tokens": 42},
    }
    assert "partial" in delta_payload["content"]
    assert message_payload["usage"]["total_tokens"] == 42
