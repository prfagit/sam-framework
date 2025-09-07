import pytest
import json
from unittest.mock import Mock, AsyncMock

from sam.core.agent import SAMAgent
from sam.core.llm_provider import LLMProvider, ChatResponse
from sam.core.tools import Tool, ToolSpec, ToolRegistry
from sam.core.events import EventBus
from sam.core.memory import MemoryManager


@pytest.mark.asyncio
async def test_agent_publishes_tool_and_usage_events():
    # Mock LLM provider to request a tool call then produce final response
    mock_llm = Mock(spec=LLMProvider)
    tool_calls_response = ChatResponse(
        content="",
        tool_calls=[
            {
                "id": "evt_call_1",
                "type": "function",
                "function": {
                    "name": "echo_tool",
                    "arguments": json.dumps({"msg": "hi"}),
                },
            }
        ],
        usage={"total_tokens": 42, "prompt_tokens": 10, "completion_tokens": 32},
    )
    final_response = ChatResponse(content="done", tool_calls=[])
    mock_llm.chat_completion = AsyncMock(side_effect=[tool_calls_response, final_response])

    # Minimal tool registry with one tool
    registry = ToolRegistry()

    async def handle_echo(args):
        return {"ok": True, "echo": args.get("msg")}

    registry.register(
        Tool(
            spec=ToolSpec(
                name="echo_tool",
                description="Echo",
                input_schema={
                    "parameters": {"type": "object", "properties": {"msg": {"type": "string"}}}
                },
            ),
            handler=handle_echo,
        )
    )

    # Mock memory manager
    mem = Mock(spec=MemoryManager)
    mem.load_session = AsyncMock(return_value=[])
    mem.save_session = AsyncMock()

    # Capture events
    bus = EventBus()
    events = []

    async def collector(event, payload):
        events.append((event, payload))

    bus.subscribe("tool.called", collector)
    bus.subscribe("tool.succeeded", collector)
    bus.subscribe("llm.usage", collector)

    agent = SAMAgent(mock_llm, registry, mem, system_prompt="Test", event_bus=bus)
    result = await agent.run("do it", session_id="s1")
    assert result == "done"

    # Ensure our three event types fired
    names = [e for e, _ in events]
    assert "llm.usage" in names
    assert "tool.called" in names
    assert "tool.succeeded" in names

    # Validate tool.called payload
    called_payload = next(p for e, p in events if e == "tool.called")
    assert called_payload["name"] == "echo_tool"
    assert called_payload["tool_call_id"] == "evt_call_1"
