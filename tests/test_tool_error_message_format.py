"""Test that tool errors maintain correct message format for LLM APIs."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from sam.core.agent import SAMAgent
from sam.core.tools import ToolRegistry, Tool, ToolSpec
from sam.core.memory import MemoryManager
from sam.core.llm_provider import LLMProvider, ChatResponse


@pytest.mark.asyncio
async def test_tool_error_message_format_openai():
    """Verify that tool errors maintain OpenAI's required message format.

    OpenAI requires: assistant (with tool_calls) -> tool messages (one per tool_call_id)
    System messages must come AFTER all tool messages, not between them.
    """

    # Create mock tool that returns validation error
    async def failing_tool(args):
        return {
            "success": False,
            "error": "Validation failed: [{'type': 'missing', 'loc': ('coin',), 'msg': 'Field required'}]",
        }

    tool_registry = ToolRegistry()
    tool_registry.register(
        Tool(
            spec=ToolSpec(
                name="test_tool",
                description="Test tool that fails",
                input_schema={"type": "object", "properties": {}},
            ),
            handler=failing_tool,
        )
    )

    # Mock memory
    mock_memory = MagicMock(spec=MemoryManager)
    mock_memory.load_session = AsyncMock(return_value=[])
    mock_memory.save_session = AsyncMock()

    # Mock LLM
    mock_llm = MagicMock(spec=LLMProvider)

    # First call: LLM decides to call the tool
    tool_call_response = ChatResponse(
        content=None,
        tool_calls=[
            {
                "id": "call_123",
                "type": "function",
                "function": {
                    "name": "test_tool",
                    "arguments": "{}",
                },
            }
        ],
        usage={"total_tokens": 100, "prompt_tokens": 80, "completion_tokens": 20},
    )

    # Second call: LLM responds to the error
    final_response = ChatResponse(
        content="I encountered an error with the tool.",
        tool_calls=[],
        usage={"total_tokens": 120, "prompt_tokens": 100, "completion_tokens": 20},
    )

    # Track the messages passed to LLM to verify format
    messages_history = []

    async def mock_chat_completion(messages, **kwargs):
        messages_history.append(messages.copy())
        if len(messages_history) == 1:
            return tool_call_response
        return final_response

    mock_llm.chat_completion = AsyncMock(side_effect=mock_chat_completion)

    # Create agent
    agent = SAMAgent(
        llm=mock_llm,
        tools=tool_registry,
        memory=mock_memory,
        system_prompt="Test agent",
    )

    # Run agent
    result = await agent.run("test input", "test-session")

    # Verify we got a response
    assert "error" in result.lower()

    # Verify message format in second LLM call
    assert len(messages_history) == 2
    second_call_messages = messages_history[1]

    # Find the assistant message with tool_calls
    assistant_idx = None
    for i, msg in enumerate(second_call_messages):
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            assistant_idx = i
            break

    assert assistant_idx is not None, "Should have assistant message with tool_calls"

    # Verify the NEXT message is a tool message (not system)
    next_msg = second_call_messages[assistant_idx + 1]
    assert next_msg["role"] == "tool", (
        f"Message after assistant should be 'tool', got '{next_msg['role']}'"
    )
    assert next_msg["tool_call_id"] == "call_123", "Tool message should have correct tool_call_id"

    # Verify system messages come AFTER tool messages
    tool_message_found = False
    system_after_tool = False
    for i in range(assistant_idx + 1, len(second_call_messages)):
        msg = second_call_messages[i]
        if msg["role"] == "tool":
            tool_message_found = True
        elif msg["role"] == "system" and tool_message_found:
            system_after_tool = True
            break

    assert tool_message_found, "Should have tool message"
    # System message is optional, but if present should be after tool message
    if any(msg["role"] == "system" for msg in second_call_messages[assistant_idx:]):
        assert system_after_tool, "System messages should come AFTER tool messages"


@pytest.mark.asyncio
async def test_validation_error_includes_success_false():
    """Verify that validation errors include success: False field."""
    from pydantic import BaseModel, Field

    class TestInput(BaseModel):
        required_field: str = Field(..., description="A required field")

    async def tool_handler(args):
        return {"result": "ok"}

    tool_registry = ToolRegistry()
    tool_registry.register(
        Tool(
            spec=ToolSpec(
                name="test_validation",
                description="Test validation",
                input_schema={
                    "type": "object",
                    "properties": {"required_field": {"type": "string"}},
                },
            ),
            handler=tool_handler,
            input_model=TestInput,
        )
    )

    # Call tool with missing required field
    result = await tool_registry.call("test_validation", {})

    # Verify error structure
    assert result.get("success") is False, "Validation error should have success: False"
    assert "error" in result, "Should have error field"
    assert "Validation failed" in result["error"], "Should mention validation failure"
    assert "error_detail" in result, "Should have error_detail field"
    assert result["error_detail"]["code"] == "validation_error"
