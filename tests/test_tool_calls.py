import pytest
import json
from unittest.mock import Mock, AsyncMock
from sam.core.agent import SAMAgent
from sam.core.llm_provider import LLMProvider, ChatResponse
from sam.core.tools import Tool, ToolSpec, ToolRegistry
from sam.core.memory import MemoryManager


@pytest.mark.asyncio
async def test_tool_call_round_trip():
    """Test the complete tool-call round-trip with OpenAI-style responses."""
    # Mock LLM provider that simulates OpenAI tool-call response
    mock_llm = Mock(spec=LLMProvider)

    # Simulate OpenAI response with tool_calls (JSON string arguments)
    tool_calls_response = ChatResponse(
        content="I'll help you get your balance.",
        tool_calls=[
            {
                "id": "call_123",
                "type": "function",
                "function": {
                    "name": "get_balance",
                    "arguments": json.dumps({"address": "test_address_123"}),
                },
            }
        ],
    )

    # Final response after tool execution
    final_response = ChatResponse(content="Your balance is 1.5 SOL", tool_calls=[])

    mock_llm.chat_completion = AsyncMock(side_effect=[tool_calls_response, final_response])

    # Mock tool registry with a test tool
    tool_registry = ToolRegistry()

    async def mock_get_balance(args):
        return {"balance": 1.5, "address": args["address"]}

    test_tool = Tool(
        spec=ToolSpec(
            name="get_balance",
            description="Get SOL balance",
            input_schema={
                "parameters": {"type": "object", "properties": {"address": {"type": "string"}}}
            },
        ),
        handler=mock_get_balance,
    )

    tool_registry.register(test_tool)

    # Mock memory manager
    mock_memory = Mock(spec=MemoryManager)
    mock_memory.load_session = AsyncMock(return_value=[])
    mock_memory.save_session = AsyncMock()

    # Create agent
    agent = SAMAgent(
        llm=mock_llm, tools=tool_registry, memory=mock_memory, system_prompt="Test system prompt"
    )

    # Execute agent run
    result = await agent.run("Check my balance", "test_session")

    # Verify the final result
    assert result == "Your balance is 1.5 SOL"

    # Verify LLM was called twice (initial + after tool execution)
    assert mock_llm.chat_completion.call_count == 2

    # Verify first call included tools
    first_call = mock_llm.chat_completion.call_args_list[0]
    assert "tools" in first_call.kwargs

    # Verify second call included tool results with proper format
    second_call = mock_llm.chat_completion.call_args_list[1]
    messages = second_call[0][0]  # messages argument

    # Find tool result message
    tool_result_msg = None
    for msg in messages:
        if msg.get("role") == "tool":
            tool_result_msg = msg
            break

    assert tool_result_msg is not None
    assert tool_result_msg["tool_call_id"] == "call_123"
    assert tool_result_msg["name"] == "get_balance"

    # Verify content is JSON-encoded
    content = json.loads(tool_result_msg["content"])
    assert content["balance"] == 1.5
    assert content["address"] == "test_address_123"


@pytest.mark.asyncio
async def test_tool_call_argument_parsing():
    """Test that tool arguments are correctly parsed from JSON strings."""
    mock_llm = Mock(spec=LLMProvider)

    # Test with complex JSON arguments
    complex_args = {"mint": "token_address_123", "percentage": 50, "slippage": 2}

    tool_calls_response = ChatResponse(
        content="",
        tool_calls=[
            {
                "id": "call_456",
                "type": "function",
                "function": {"name": "pump_fun_sell", "arguments": json.dumps(complex_args)},
            }
        ],
    )

    final_response = ChatResponse(content="Sell executed", tool_calls=[])
    mock_llm.chat_completion = AsyncMock(side_effect=[tool_calls_response, final_response])

    # Mock tool that expects parsed arguments
    received_args = None

    async def mock_pump_fun_sell(args):
        nonlocal received_args
        received_args = args
        return {"success": True}

    tool_registry = ToolRegistry()
    test_tool = Tool(
        spec=ToolSpec(
            name="pump_fun_sell",
            description="Sell tokens",
            input_schema={
                "parameters": {
                    "type": "object",
                    "properties": {
                        "mint": {"type": "string"},
                        "percentage": {"type": "integer"},
                        "slippage": {"type": "integer"},
                    },
                }
            },
        ),
        handler=mock_pump_fun_sell,
    )
    tool_registry.register(test_tool)

    mock_memory = Mock(spec=MemoryManager)
    mock_memory.load_session = AsyncMock(return_value=[])
    mock_memory.save_session = AsyncMock()

    agent = SAMAgent(mock_llm, tool_registry, mock_memory, "Test")

    await agent.run("Sell tokens", "test_session")

    # Verify tool received correctly parsed arguments
    assert received_args == complex_args


@pytest.mark.asyncio
async def test_tool_call_malformed_json():
    """Test handling of malformed JSON in tool arguments."""
    mock_llm = Mock(spec=LLMProvider)

    # Malformed JSON arguments
    tool_calls_response = ChatResponse(
        content="",
        tool_calls=[
            {
                "id": "call_789",
                "type": "function",
                "function": {
                    "name": "get_balance",
                    "arguments": "{invalid_json: true",  # Malformed JSON
                },
            }
        ],
    )

    final_response = ChatResponse(content="Error handled", tool_calls=[])
    mock_llm.chat_completion = AsyncMock(side_effect=[tool_calls_response, final_response])

    async def mock_get_balance(args):
        # Should receive empty dict due to JSON parse error
        return {"args_received": args}

    tool_registry = ToolRegistry()
    test_tool = Tool(
        spec=ToolSpec(
            name="get_balance",
            description="Get balance",
            input_schema={"parameters": {"type": "object", "properties": {}}},
        ),
        handler=mock_get_balance,
    )
    tool_registry.register(test_tool)

    mock_memory = Mock(spec=MemoryManager)
    mock_memory.load_session = AsyncMock(return_value=[])
    mock_memory.save_session = AsyncMock()

    agent = SAMAgent(mock_llm, tool_registry, mock_memory, "Test")

    # Should not raise exception, should handle gracefully
    result = await agent.run("Test malformed JSON", "test_session")

    assert result == "Error handled"  # Agent completed despite JSON error


@pytest.mark.asyncio
async def test_multiple_tool_calls():
    """Test handling of multiple tool calls in a single response."""
    mock_llm = Mock(spec=LLMProvider)

    # Response with multiple tool calls
    tool_calls_response = ChatResponse(
        content="I'll check two balances for you.",
        tool_calls=[
            {
                "id": "call_001",
                "type": "function",
                "function": {
                    "name": "get_wallet_info",
                    "arguments": json.dumps({"address": "address1"}),
                },
            },
            {
                "id": "call_002",
                "type": "function",
                "function": {
                    "name": "get_wallet_info",
                    "arguments": json.dumps({"address": "address2"}),
                },
            },
        ],
    )

    final_response = ChatResponse(
        content="Address1 has 1.0 SOL, Address2 has 2.0 SOL", tool_calls=[]
    )

    mock_llm.chat_completion = AsyncMock(side_effect=[tool_calls_response, final_response])

    call_count = 0

    async def mock_get_wallet_info(args):
        nonlocal call_count
        call_count += 1
        if args["address"] == "address1":
            return {"balance": 1.0}
        else:
            return {"balance": 2.0}

    tool_registry = ToolRegistry()
    test_tool = Tool(
        spec=ToolSpec(
            name="get_wallet_info",
            description="Get wallet info",
            input_schema={
                "parameters": {"type": "object", "properties": {"address": {"type": "string"}}}
            },
        ),
        handler=mock_get_wallet_info,
    )
    tool_registry.register(test_tool)

    mock_memory = Mock(spec=MemoryManager)
    mock_memory.load_session = AsyncMock(return_value=[])
    mock_memory.save_session = AsyncMock()

    agent = SAMAgent(mock_llm, tool_registry, mock_memory, "Test")

    result = await agent.run("Check both balances", "test_session")

    # Verify both tools were called
    assert call_count == 2
    assert result == "Address1 has 1.0 SOL, Address2 has 2.0 SOL"

    # Verify both tool results were added to messages
    second_call = mock_llm.chat_completion.call_args_list[1]
    messages = second_call[0][0]

    tool_messages = [msg for msg in messages if msg.get("role") == "tool"]
    assert len(tool_messages) == 2

    # Verify tool_call_ids are correct
    tool_call_ids = [msg["tool_call_id"] for msg in tool_messages]
    assert "call_001" in tool_call_ids
    assert "call_002" in tool_call_ids
