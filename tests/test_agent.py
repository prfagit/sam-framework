import pytest
import tempfile
import os
from unittest.mock import MagicMock, AsyncMock
from sam.core.agent import SAMAgent
from sam.core.tools import ToolRegistry, ToolSpec
from sam.core.memory import MemoryManager
from sam.core.llm_provider import ChatResponse


@pytest.fixture
async def mock_memory():
    """Create a mock memory manager."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "test.db")
        memory = MemoryManager(db_path)
        await memory.initialize()
        yield memory


@pytest.fixture
def mock_llm():
    """Create a mock LLM provider."""
    llm = MagicMock()
    llm.close = AsyncMock()
    return llm


@pytest.fixture
def mock_tools():
    """Create a mock tool registry."""
    registry = ToolRegistry()
    return registry


@pytest.fixture
async def agent(mock_llm, mock_tools, mock_memory):
    """Create a test agent."""
    system_prompt = "You are a test agent."
    agent = SAMAgent(
        llm=mock_llm, tools=mock_tools, memory=mock_memory, system_prompt=system_prompt
    )
    return agent


class TestSAMAgent:
    """Test SAM Agent core functionality."""

    @pytest.mark.asyncio
    async def test_agent_initialization(self, agent, mock_llm, mock_tools, mock_memory):
        """Test agent initialization with all components."""
        assert agent.llm == mock_llm
        assert agent.tools == mock_tools
        assert agent.memory == mock_memory
        assert agent.system_prompt == "You are a test agent."
        assert agent.tool_callback is None
        assert isinstance(agent.session_stats, dict)
        assert "total_tokens" in agent.session_stats

    @pytest.mark.asyncio
    async def test_agent_run_no_tools(self, agent, mock_llm, mock_memory):
        """Test agent run without tool calls."""
        # Setup mocks
        mock_response = ChatResponse(
            content="Hello! I can help you with Solana operations.",
            tool_calls=[],
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )
        mock_llm.chat_completion = AsyncMock(return_value=mock_response)
        mock_memory.load_session = AsyncMock(return_value=[])
        mock_memory.save_session = AsyncMock()

        # Run agent
        session_id = "test_session"
        result = await agent.run("Hello", session_id)

        # Verify result
        assert result == "Hello! I can help you with Solana operations."

        # Verify LLM was called with correct messages
        mock_llm.chat_completion.assert_called_once()
        call_args = mock_llm.chat_completion.call_args[0][0]
        assert len(call_args) == 2  # system prompt + user message
        assert call_args[0]["role"] == "system"
        assert call_args[1]["role"] == "user"
        assert call_args[1]["content"] == "Hello"

        # Verify session was saved
        mock_memory.save_session.assert_called_once_with(session_id, call_args[1:])

        # Verify stats were updated
        assert agent.session_stats["total_tokens"] == 15
        assert agent.session_stats["requests"] == 1

    @pytest.mark.asyncio
    async def test_agent_run_with_tools(self, agent, mock_llm, mock_memory):
        """Test agent run with tool calls."""

        # Create a test tool
        async def test_handler(args):
            return {"result": f"processed {args.get('input', 'nothing')}"}

        tool_spec = ToolSpec(
            name="test_tool",
            description="A test tool",
            input_schema={
                "type": "object",
                "properties": {"input": {"type": "string"}},
                "required": ["input"],
            },
        )

        from sam.core.tools import Tool

        test_tool = Tool(spec=tool_spec, handler=test_handler)
        agent.tools.register(test_tool)

        # Setup mocks
        tool_calls = [
            {
                "id": "call_123",
                "type": "function",
                "function": {"name": "test_tool", "arguments": '{"input": "test_data"}'},
            }
        ]

        mock_response1 = ChatResponse(
            content="Let me process that for you.",
            tool_calls=tool_calls,
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )

        mock_response2 = ChatResponse(
            content="Processing complete!",
            tool_calls=[],
            usage={"prompt_tokens": 15, "completion_tokens": 8, "total_tokens": 23},
        )

        mock_llm.chat_completion = AsyncMock(side_effect=[mock_response1, mock_response2])
        mock_memory.load_session = AsyncMock(return_value=[])
        mock_memory.save_session = AsyncMock()

        # Run agent
        session_id = "test_session"
        result = await agent.run("Process test_data", session_id)

        # Verify result
        assert result == "Processing complete!"

        # Verify LLM was called twice
        assert mock_llm.chat_completion.call_count == 2

        # Verify tool was called
        # (This would need to be verified by checking the messages passed to the second LLM call)

    @pytest.mark.asyncio
    async def test_agent_clear_context(self, agent, mock_memory):
        """Test clearing conversation context."""
        # Setup initial stats
        agent.session_stats = {"total_tokens": 100, "requests": 5, "context_length": 10}

        mock_memory.clear_session = AsyncMock()

        # Clear context
        session_id = "test_session"
        result = await agent.clear_context(session_id)

        # Verify result
        assert "Context cleared" in result

        # Verify memory was called
        mock_memory.clear_session.assert_called_once_with(session_id)

        # Verify stats were reset
        assert agent.session_stats["total_tokens"] == 0
        assert agent.session_stats["requests"] == 0
        assert agent.session_stats["context_length"] == 0

    @pytest.mark.asyncio
    async def test_agent_compact_conversation(self, agent, mock_llm, mock_memory):
        """Test conversation compaction."""
        # Setup conversation history (need more than 6 messages to trigger compaction)
        old_messages = [
            {"role": "user", "content": "First message"},
            {"role": "assistant", "content": "First response"},
            {"role": "user", "content": "Second message"},
            {"role": "assistant", "content": "Second response"},
            {"role": "user", "content": "Third message"},
            {"role": "assistant", "content": "Third response"},
            {"role": "user", "content": "Fourth message"},
            {"role": "assistant", "content": "Fourth response"},
            {"role": "user", "content": "Fifth message"},
            {"role": "assistant", "content": "Fifth response"},
        ]

        mock_memory.load_session = AsyncMock(return_value=old_messages)
        mock_memory.save_session = AsyncMock()

        # Mock LLM summary response
        summary_response = ChatResponse(
            content="User asked questions about Solana operations.",
            tool_calls=[],
            usage={"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60},
        )
        mock_llm.chat_completion = AsyncMock(return_value=summary_response)

        # Compact conversation
        session_id = "test_session"
        result = await agent.compact_conversation(session_id)

        # Verify result contains compaction info
        assert "compacted" in result.lower() or "summarized" in result.lower()

        # Verify memory operations
        mock_memory.load_session.assert_called_once_with(session_id)
        mock_memory.save_session.assert_called_once()

        # Verify LLM was called for summary
        mock_llm.chat_completion.assert_called_once()

    @pytest.mark.asyncio
    async def test_agent_compact_short_conversation(self, agent, mock_memory):
        """Test conversation compaction with short conversation."""
        # Setup short conversation
        short_messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]

        mock_memory.load_session = AsyncMock(return_value=short_messages)
        mock_memory.save_session = AsyncMock()

        # Compact short conversation
        session_id = "test_session"
        result = await agent.compact_conversation(session_id)

        # Should not compact short conversations
        assert "compact" in result.lower()

        # Should not save anything
        mock_memory.save_session.assert_not_called()

    def test_balance_cache_operations(self, agent):
        """Test balance caching operations."""
        # Test initial state
        assert agent.get_cached_balance() is None
        assert agent.is_balance_fresh() is False

        # Cache balance data
        balance_data = {"sol_balance": 1.5, "tokens": []}
        agent.cache_balance_data(balance_data)

        # Verify cache works
        assert agent.is_balance_fresh() is True
        assert agent.get_cached_balance() == balance_data

        # Test cache invalidation
        agent.invalidate_balance_cache()
        assert agent.get_cached_balance() is None
        assert agent.is_balance_fresh() is False

    def test_token_metadata_cache(self, agent):
        """Test token metadata caching."""
        mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

        # Test empty cache
        assert agent.get_cached_token_metadata(mint) is None

        # Cache metadata
        metadata = {"name": "USD Coin", "symbol": "USDC"}
        agent.cache_token_metadata(mint, metadata)

        # Verify cache works
        assert agent.get_cached_token_metadata(mint) == metadata

        # Test different mint
        assert agent.get_cached_token_metadata("different_mint") is None

    def test_session_stats_tracking(self, agent):
        """Test session statistics tracking."""
        # Test initial stats
        assert agent.session_stats["total_tokens"] == 0
        assert agent.session_stats["requests"] == 0
        assert agent.session_stats["context_length"] == 0

        # Update stats
        agent.session_stats["total_tokens"] = 100
        agent.session_stats["requests"] = 5
        agent.session_stats["context_length"] = 10

        # Verify stats are maintained
        assert agent.session_stats["total_tokens"] == 100
        assert agent.session_stats["requests"] == 5
        assert agent.session_stats["context_length"] == 10

    def test_tool_callback_setting(self, agent):
        """Test tool callback functionality."""
        # Test initial state
        assert agent.tool_callback is None

        # Set callback
        def test_callback(tool_name, tool_args):
            pass

        agent.tool_callback = test_callback

        # Verify callback is set
        assert agent.tool_callback == test_callback

    def test_format_messages_for_summary(self, agent):
        """Test message formatting for summary."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
            {"role": "tool", "name": "get_balance", "content": "balance data"},
        ]

        result = agent._format_messages_for_summary(messages)

        # Verify formatting
        assert "User: Hello" in result
        assert "Assistant: Hi there" in result
        assert "[get_balance executed]" in result


if __name__ == "__main__":
    pytest.main([__file__])
