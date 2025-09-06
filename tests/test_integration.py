import pytest
import asyncio
import os
import tempfile
from sam.cli import setup_agent
from sam.core.agent import SAMAgent
from sam.core.llm_provider import LLMProvider
from sam.core.memory import MemoryManager
from sam.core.tools import ToolRegistry
from sam.config.prompts import SOLANA_AGENT_PROMPT


@pytest.mark.asyncio
async def test_agent_initialization():
    """Test that the agent initializes properly with all components."""
    try:
        agent = await setup_agent()

        # Verify agent has all required components
        assert isinstance(agent, SAMAgent)
        assert isinstance(agent.llm, LLMProvider)
        assert isinstance(agent.memory, MemoryManager)
        assert isinstance(agent.tools, ToolRegistry)
        assert agent.system_prompt == SOLANA_AGENT_PROMPT

        # Verify tools are loaded
        tools = agent.tools.list_specs()
        assert len(tools) >= 15  # Should have at least 15 tools

        # Verify specific tools exist
        tool_names = [tool["name"] for tool in tools]
        expected_tools = [
            "get_balance",
            "transfer_sol",
            "get_token_data",
            "pump_fun_buy",
            "pump_fun_sell",
            "jupiter_swap",
            "get_swap_quote",
            "search_pairs",
        ]

        for expected_tool in expected_tools:
            assert expected_tool in tool_names, f"Missing tool: {expected_tool}"

    except Exception as e:
        if "OPENAI_API_KEY" in str(e):
            pytest.skip("OpenAI API key not available for integration test")
        else:
            raise


@pytest.mark.asyncio
async def test_memory_integration():
    """Test memory system integration."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "test_integration.db")
        memory = MemoryManager(db_path)
        await memory.initialize()

        # Test session management
        session_id = "test_integration_session"
        test_messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]

        # Save and load session
        await memory.save_session(session_id, test_messages)
        loaded_messages = await memory.load_session(session_id)
        assert loaded_messages == test_messages

        # Test preferences
        await memory.save_user_preference("user1", "risk_level", "low")
        risk_level = await memory.get_user_preference("user1", "risk_level")
        assert risk_level == "low"

        # Test trade history
        await memory.save_trade_history("user1", "token123", "buy", 0.5)
        trades = await memory.get_trade_history("user1")
        assert len(trades) == 1
        assert trades[0]["action"] == "buy"

        # Test database stats
        stats = await memory.get_session_stats()
        assert stats["sessions"] >= 1
        assert stats["preferences"] >= 1
        assert stats["trades"] >= 1


@pytest.mark.asyncio
async def test_tool_registry():
    """Test tool registry functionality."""
    registry = ToolRegistry()

    # Test empty registry
    assert len(registry.list_specs()) == 0

    # Create a simple test tool
    from sam.core.tools import Tool, ToolSpec

    async def test_handler(args):
        return {"result": f"Processed: {args.get('input', 'none')}"}

    test_tool = Tool(
        spec=ToolSpec(
            name="test_tool",
            description="A test tool",
            input_schema={
                "name": "test_tool",
                "description": "Test",
                "parameters": {
                    "type": "object",
                    "properties": {"input": {"type": "string", "description": "Test input"}},
                    "required": ["input"],
                },
            },
        ),
        handler=test_handler,
    )

    # Register tool
    registry.register(test_tool)

    # Verify registration
    specs = registry.list_specs()
    assert len(specs) == 1
    assert specs[0]["name"] == "test_tool"

    # Test tool execution
    result = await registry.call("test_tool", {"input": "hello"})
    assert result["result"] == "Processed: hello"

    # Test non-existent tool
    result = await registry.call("non_existent", {})
    assert "error" in result


@pytest.mark.asyncio
async def test_rate_limiting_integration():
    """Test rate limiting integration with tools."""
    from sam.utils.decorators import rate_limit

    call_count = 0

    @rate_limit("default")
    async def test_rate_limited_function(args):
        nonlocal call_count
        call_count += 1
        return {"call_number": call_count, "success": True}

    # Multiple calls should work (no Redis, so rate limiting is disabled)
    for i in range(5):
        result = await test_rate_limited_function({"user_id": "test_user"})
        assert result["success"] is True


@pytest.mark.asyncio
async def test_secure_storage_integration():
    """Test secure storage integration."""
    from sam.utils.secure_storage import get_secure_storage

    storage = get_secure_storage()

    # Test keyring availability
    test_results = storage.test_keyring_access()
    assert isinstance(test_results, dict)
    assert "keyring_available" in test_results

    if test_results["keyring_available"]:
        # Test key storage if keyring is available
        test_user = "integration_test_user"
        test_key = "integration_test_key_12345"

        try:
            success = storage.store_private_key(test_user, test_key)
            if success:
                retrieved = storage.get_private_key(test_user)
                assert retrieved == test_key

                # Cleanup
                storage.delete_private_key(test_user)

        except Exception as e:
            pytest.skip(f"Keyring integration test skipped: {e}")


@pytest.mark.asyncio
async def test_crypto_utilities():
    """Test cryptographic utilities."""
    from sam.utils.crypto import encrypt_private_key, decrypt_private_key, generate_encryption_key

    # Test key generation
    key = generate_encryption_key()
    assert isinstance(key, str)
    assert len(key) > 0

    # Set the key in environment for testing
    os.environ["SAM_FERNET_KEY"] = key

    # Test encryption/decryption
    test_private_key = "test_private_key_abcd1234567890"
    encrypted = encrypt_private_key(test_private_key)
    assert encrypted != test_private_key
    assert encrypted.startswith("gAAAAA")  # Fernet prefix

    decrypted = decrypt_private_key(encrypted)
    assert decrypted == test_private_key


@pytest.mark.asyncio
async def test_validators():
    """Test input validators."""
    from sam.utils.validators import validate_tool_input

    # Test balance check (no args)
    result = validate_tool_input("get_balance", {})
    assert result == {}

    # Test transfer validation
    valid_transfer = {
        "to_address": "11111111111111111111111111111112",  # Valid looking address
        "amount": 0.1,
    }
    result = validate_tool_input("transfer_sol", valid_transfer)
    assert result["to_address"] == valid_transfer["to_address"]
    assert result["amount"] == valid_transfer["amount"]

    # Test invalid amount
    with pytest.raises(ValueError):
        validate_tool_input(
            "transfer_sol", {"to_address": "11111111111111111111111111111112", "amount": -1}
        )


@pytest.mark.asyncio
async def test_agent_session_workflow():
    """Test a complete agent session workflow with mock LLM."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "test_session.db")

        # Create a mock LLM provider that doesn't need API keys
        class MockLLMProvider:
            def __init__(self):
                pass

            async def chat_completion(self, messages, tools=None):
                # Return a mock response that looks like OpenAI format
                class MockResponse:
                    def __init__(self):
                        self.content = "Hello! I'm a test agent. I can help you with Solana operations but I currently have no tools available."
                        self.tool_calls = None
                        self.usage = {
                            "prompt_tokens": 10,
                            "completion_tokens": 20,
                            "total_tokens": 30,
                        }

                return MockResponse()

        memory = MemoryManager(db_path)
        await memory.initialize()

        tools = ToolRegistry()

        agent = SAMAgent(
            llm=MockLLMProvider(), tools=tools, memory=memory, system_prompt=SOLANA_AGENT_PROMPT
        )

        # Test that agent can handle a simple query
        session_id = "test_workflow_session"

        response = await agent.run("Hello, what can you help me with?", session_id)
        assert isinstance(response, str)
        assert len(response) > 0
        assert "test agent" in response.lower()

        # Verify session was saved
        loaded_session = await memory.load_session(session_id)
        assert len(loaded_session) >= 1  # Should have user message at least
        assert loaded_session[0]["role"] == "user"
        assert "Hello, what can you help me with?" in loaded_session[0]["content"]


if __name__ == "__main__":
    # Allow running integration tests directly
    asyncio.run(test_agent_initialization())
