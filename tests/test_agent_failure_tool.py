import pytest
from unittest.mock import AsyncMock, MagicMock

from sam.core.agent import SAMAgent
from sam.core.tools import ToolRegistry, ToolSpec, Tool
from sam.core.memory import MemoryManager
from sam.core.llm_provider import ChatResponse


@pytest.mark.asyncio
async def test_agent_handles_failed_tool_and_completes(tmp_path):
    # Memory
    db_path = tmp_path / "mem.db"
    mem = MemoryManager(str(db_path))
    await mem.initialize()

    # LLM mock that requests a tool then returns final reply
    llm = MagicMock()
    llm.close = AsyncMock()

    tool_calls = [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "fail_tool", "arguments": "{}"},
        }
    ]

    resp1 = ChatResponse(content="Trying a tool...", tool_calls=tool_calls, usage={})
    resp2 = ChatResponse(content="All good after failure", tool_calls=[], usage={})
    llm.chat_completion = AsyncMock(side_effect=[resp1, resp2])

    # Registry with a failing tool that returns success=False shape
    async def fail_handler(args):
        return {"success": False, "error": "simulated failure"}

    reg = ToolRegistry()
    reg.register(
        Tool(
            spec=ToolSpec(
                name="fail_tool",
                description="Always fails",
                input_schema={"type": "object", "properties": {}, "required": []},
            ),
            handler=fail_handler,
        )
    )

    agent = SAMAgent(llm=llm, tools=reg, memory=mem, system_prompt="test")

    out = await agent.run("do something", "s1")
    assert "All good" in out

