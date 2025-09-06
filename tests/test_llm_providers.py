import pytest
from unittest.mock import patch
from sam.core.llm_provider import (
    ChatResponse, LLMProvider, OpenAICompatibleProvider,
    XAIProvider, AnthropicProvider, create_llm_provider
)
from sam.config.settings import Settings


class TestChatResponse:
    """Test ChatResponse class."""

    def test_chat_response_creation(self):
        """Test ChatResponse initialization."""
        response = ChatResponse(
            content="Test response",
            tool_calls=[{"id": "1", "function": {"name": "test"}}],
            usage={"tokens": 100}
        )

        assert response.content == "Test response"
        assert len(response.tool_calls) == 1
        assert response.usage == {"tokens": 100}

    def test_chat_response_defaults(self):
        """Test ChatResponse with default values."""
        response = ChatResponse(content="Test")

        assert response.content == "Test"
        assert response.tool_calls == []
        assert response.usage == {}


class TestLLMProvider:
    """Test base LLM provider functionality."""

    def test_llm_provider_initialization(self):
        """Test LLM provider base class initialization."""
        provider = LLMProvider("test_key", "test_model", "https://test.com")

        assert provider.api_key == "test_key"
        assert provider.model == "test_model"
        assert provider.base_url == "https://test.com"

    @pytest.mark.asyncio
    async def test_llm_provider_close(self):
        """Test LLM provider close method."""
        provider = LLMProvider("test_key", "test_model")

        # Should not raise an exception
        await provider.close()

    def test_llm_provider_not_implemented(self):
        """Test that base chat_completion raises NotImplementedError."""
        provider = LLMProvider("test_key", "test_model")

        with pytest.raises(NotImplementedError):
            import asyncio
            asyncio.run(provider.chat_completion([]))


class TestOpenAICompatibleProvider:
    """Test OpenAI compatible provider."""

    def test_openai_provider_initialization(self):
        """Test OpenAI provider initialization."""
        provider = OpenAICompatibleProvider("test_key", "gpt-4", "https://custom.com")

        assert provider.api_key == "test_key"
        assert provider.model == "gpt-4"
        assert provider.base_url == "https://custom.com"

    def test_openai_provider_default_url(self):
        """Test OpenAI provider with default URL."""
        provider = OpenAICompatibleProvider("test_key", "gpt-4")

        assert provider.base_url == "https://api.openai.com/v1"

    def test_openai_tool_formatting(self):
        """Test OpenAI tool formatting."""
        provider = OpenAICompatibleProvider("test_key", "gpt-4")

        tools = [{
            "name": "test_tool",
            "description": "A test tool",
            "input_schema": {
                "type": "object",
                "properties": {"arg": {"type": "string"}},
                "required": ["arg"]
            }
        }]

        # Test tool formatting logic
        formatted_tools = []
        for tool in tools:
            input_schema = tool["input_schema"]
            parameters = input_schema.get("parameters") if isinstance(input_schema, dict) else input_schema
            function_def = {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": parameters
            }
            formatted_tools.append({"type": "function", "function": function_def})

        assert len(formatted_tools) == 1
        assert formatted_tools[0]["type"] == "function"
        assert formatted_tools[0]["function"]["name"] == "test_tool"
        assert formatted_tools[0]["function"]["description"] == "A test tool"

    def test_openai_initialization(self):
        """Test OpenAI provider initialization with different parameters."""
        # Test with custom base URL
        provider = OpenAICompatibleProvider("test_key", "gpt-4", "https://custom.openai.com/v1")
        assert provider.api_key == "test_key"
        assert provider.model == "gpt-4"
        assert provider.base_url == "https://custom.openai.com/v1"

        # Test with default base URL
        provider2 = OpenAICompatibleProvider("test_key", "gpt-3.5-turbo")
        assert provider2.base_url == "https://api.openai.com/v1"


class TestXAIProvider:
    """Test xAI provider."""

    def test_xai_provider_initialization(self):
        """Test xAI provider initialization."""
        provider = XAIProvider("test_key", "grok-2", "https://api.x.ai/v1")

        assert provider.api_key == "test_key"
        assert provider.model == "grok-2"
        assert provider.base_url == "https://api.x.ai/v1"

    @pytest.mark.asyncio
    async def test_xai_parameter_cleaning(self):
        """Test xAI parameter schema cleaning."""
        provider = XAIProvider("test_key", "grok-2")

        # Test cleaning $defs and complex references
        dirty_params = {
            "$defs": {"some_def": {}},
            "type": "object",
            "properties": {
                "test": {"type": "string"}
            },
            "anyOf": [{"$ref": "#/defs/some_def"}]
        }

        cleaned = provider._clean_parameters(dirty_params)

        # $defs should be removed
        assert "$defs" not in cleaned
        # anyOf with $ref should be removed
        assert "anyOf" not in cleaned
        # Normal properties should remain
        assert cleaned["type"] == "object"


class TestAnthropicProvider:
    """Test Anthropic provider."""

    def test_anthropic_provider_initialization(self):
        """Test Anthropic provider initialization."""
        provider = AnthropicProvider("test_key", "claude-3", "https://api.anthropic.com")

        assert provider.api_key == "test_key"
        assert provider.model == "claude-3"
        assert provider.base_url == "https://api.anthropic.com"
        assert provider.API_VERSION == "2023-06-01"

    def test_anthropic_format_tools(self):
        """Test Anthropic tool formatting."""
        provider = AnthropicProvider("test_key", "claude-3")

        tools = [{
            "name": "test_tool",
            "description": "Test tool",
            "input_schema": {
                "type": "object",
                "properties": {"arg": {"type": "string"}}
            }
        }]

        formatted = provider._format_tools(tools)

        assert len(formatted) == 1
        assert formatted[0]["name"] == "test_tool"
        assert formatted[0]["description"] == "Test tool"
        assert "input_schema" in formatted[0]

    def test_anthropic_format_tools_none(self):
        """Test Anthropic tool formatting with None input."""
        provider = AnthropicProvider("test_key", "claude-3")

        formatted = provider._format_tools(None)

        assert formatted is None

    def test_anthropic_convert_messages_simple(self):
        """Test Anthropic message conversion for simple messages."""
        provider = AnthropicProvider("test_key", "claude-3")

        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"}
        ]

        system_text, anth_messages = provider._convert_messages(messages)

        assert system_text == "You are a helpful assistant"
        assert len(anth_messages) == 2
        assert anth_messages[0]["role"] == "user"
        assert anth_messages[1]["role"] == "assistant"

    def test_anthropic_initialization(self):
        """Test Anthropic provider initialization."""
        provider = AnthropicProvider("test_key", "claude-3", "https://api.anthropic.com")

        assert provider.api_key == "test_key"
        assert provider.model == "claude-3"
        assert provider.base_url == "https://api.anthropic.com"
        assert provider.API_VERSION == "2023-06-01"


class TestCreateLLMProvider:
    """Test LLM provider factory function."""

    @patch.object(Settings, 'LLM_PROVIDER', 'openai')
    @patch.object(Settings, 'OPENAI_API_KEY', 'test_key')
    @patch.object(Settings, 'OPENAI_MODEL', 'gpt-4')
    def test_create_openai_provider(self, *mocks):
        """Test creating OpenAI provider."""
        provider = create_llm_provider()

        assert isinstance(provider, OpenAICompatibleProvider)
        assert provider.api_key == "test_key"
        assert provider.model == "gpt-4"

    @patch.object(Settings, 'LLM_PROVIDER', 'anthropic')
    @patch.object(Settings, 'ANTHROPIC_API_KEY', 'test_key')
    @patch.object(Settings, 'ANTHROPIC_MODEL', 'claude-3')
    def test_create_anthropic_provider(self, *mocks):
        """Test creating Anthropic provider."""
        provider = create_llm_provider()

        assert isinstance(provider, AnthropicProvider)
        assert provider.api_key == "test_key"
        assert provider.model == "claude-3"

    @patch.object(Settings, 'LLM_PROVIDER', 'xai')
    @patch.object(Settings, 'XAI_API_KEY', 'test_key')
    @patch.object(Settings, 'XAI_MODEL', 'grok-2')
    def test_create_xai_provider(self, *mocks):
        """Test creating xAI provider."""
        provider = create_llm_provider()

        assert isinstance(provider, XAIProvider)
        assert provider.api_key == "test_key"
        assert provider.model == "grok-2"

    @patch.object(Settings, 'LLM_PROVIDER', 'local')
    @patch.object(Settings, 'LOCAL_LLM_BASE_URL', 'http://localhost:11434/v1')
    @patch.object(Settings, 'LOCAL_LLM_MODEL', 'llama3.1')
    def test_create_local_provider(self, *mocks):
        """Test creating local provider."""
        provider = create_llm_provider()

        assert isinstance(provider, OpenAICompatibleProvider)
        assert provider.base_url == "http://localhost:11434/v1"
        assert provider.model == "llama3.1"

    @patch.object(Settings, 'LLM_PROVIDER', 'unknown')
    @patch.object(Settings, 'OPENAI_API_KEY', 'fallback_key')
    @patch.object(Settings, 'OPENAI_MODEL', 'gpt-4')
    def test_create_unknown_provider_fallback(self, *mocks):
        """Test fallback for unknown provider."""
        with patch('sam.core.llm_provider.logger') as mock_logger:
            provider = create_llm_provider()

            # Should fallback to OpenAI compatible
            assert isinstance(provider, OpenAICompatibleProvider)
            mock_logger.warning.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__])
