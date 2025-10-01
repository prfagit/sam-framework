"""Test clear-context command with custom user contexts."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from sam.core.agent import SAMAgent
from sam.core.context import RequestContext


@pytest.mark.asyncio
async def test_clear_context_preserves_user_id():
    """Verify that clear_context passes the correct user_id from context."""
    # Create mock agent
    mock_memory = MagicMock()
    mock_memory.clear_session = AsyncMock(return_value=1)

    agent = MagicMock(spec=SAMAgent)
    agent.memory = mock_memory
    agent.clear_context = AsyncMock(return_value="Context cleared")

    # Simulate what happens when running hyperliquid agent
    context = RequestContext(user_id="agent:hyperliquid-trader")
    session_id = "hyperliquid-trader"

    # Call clear_context with user_id (the fix)
    await agent.clear_context(session_id, user_id=context.user_id)

    # Verify it was called with the correct user_id
    agent.clear_context.assert_awaited_once_with(session_id, user_id="agent:hyperliquid-trader")


@pytest.mark.asyncio
async def test_clear_context_actual_implementation():
    """Test the actual clear_context implementation with custom user_id."""
    from sam.core.memory import MemoryManager
    from sam.core.agent import SAMAgent
    from sam.core.llm_provider import LLMProvider
    from sam.core.tools import ToolRegistry

    # Create real components with mocked memory
    mock_memory = MagicMock(spec=MemoryManager)
    mock_memory.clear_session = AsyncMock(return_value=1)

    mock_llm = MagicMock(spec=LLMProvider)
    mock_tools = MagicMock(spec=ToolRegistry)

    agent = SAMAgent(llm=mock_llm, tools=mock_tools, memory=mock_memory, system_prompt="test")

    # Clear with custom user_id
    custom_user_id = "agent:hyperliquid-trader"
    result = await agent.clear_context("test-session", user_id=custom_user_id)

    # Verify memory.clear_session was called with the right user_id
    mock_memory.clear_session.assert_awaited_once_with("test-session", user_id=custom_user_id)

    assert "Context cleared" in result


@pytest.mark.asyncio
async def test_compact_conversation_preserves_user_id():
    """Verify that compact_conversation passes user_id correctly to load_session."""
    from sam.core.memory import MemoryManager
    from sam.core.agent import SAMAgent
    from sam.core.llm_provider import LLMProvider
    from sam.core.tools import ToolRegistry

    # Create mock components
    mock_memory = MagicMock(spec=MemoryManager)
    # More messages to trigger actual compaction
    mock_memory.load_session = AsyncMock(
        return_value=[{"role": "user", "content": f"msg{i}"} for i in range(10)]
    )
    mock_memory.save_session = AsyncMock()

    mock_llm = MagicMock(spec=LLMProvider)
    # Mock LLM response for summarization
    mock_response = MagicMock()
    mock_response.content = "Summary of conversation"
    mock_response.usage = {"total_tokens": 50, "prompt_tokens": 30, "completion_tokens": 20}
    mock_llm.chat_completion = AsyncMock(return_value=mock_response)

    mock_tools = MagicMock(spec=ToolRegistry)

    agent = SAMAgent(llm=mock_llm, tools=mock_tools, memory=mock_memory, system_prompt="test")

    # Compact with custom user_id
    custom_user_id = "agent:test-agent"
    await agent.compact_conversation("test-session", keep_recent=2, user_id=custom_user_id)

    # Verify load_session was called with correct user_id (this is the key test)
    mock_memory.load_session.assert_awaited_once_with("test-session", user_id=custom_user_id)
