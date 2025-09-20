import pytest
import os
from unittest.mock import patch, MagicMock
from sam.commands.onboard import run_onboarding


class TestOnboarding:
    """Test onboarding command functionality."""

    @pytest.mark.asyncio
    @patch("builtins.input")
    @patch("getpass.getpass")
    @patch("sam.commands.onboard.generate_encryption_key")
    @patch("sam.commands.onboard.get_secure_storage")
    @patch("sam.commands.onboard.find_env_path")
    @patch("sam.commands.onboard.write_env_file")
    @patch("sam.commands.onboard.show_sam_intro")
    @patch("os.path.exists")
    @patch("os.makedirs")
    async def test_onboarding_openai_provider(
        self,
        mock_makedirs,
        mock_exists,
        mock_show_intro,
        mock_write_env,
        mock_find_env_path,
        mock_get_storage,
        mock_generate_key,
        mock_getpass,
        mock_input,
    ):
        """Test onboarding flow with OpenAI provider."""
        # Mock user inputs
        mock_input.side_effect = [
            "1",  # OpenAI provider
            "gpt-4o-mini",  # Model
            "",  # No custom base URL
            "1",  # Mainnet RPC
            "I AGREE",  # Accept terms
        ]
        mock_getpass.side_effect = [
            "sk-test123456789",  # OpenAI key
            "test_private_key",  # Solana private key
            "",  # No Brave API key (getpass call)
        ]

        # Mock dependencies
        mock_generate_key.return_value = "test_fernet_key"
        mock_find_env_path.return_value = "/tmp/.env"
        mock_exists.return_value = False

        mock_storage = MagicMock()
        mock_storage.store_private_key.return_value = True
        mock_storage.get_private_key.return_value = "test_private_key"
        mock_get_storage.return_value = mock_storage

        mock_show_intro.return_value = None

        with patch.dict(os.environ, {}, clear=True):
            result = await run_onboarding()

            assert result == 0
            mock_write_env.assert_called_once()
            mock_storage.store_private_key.assert_called_once_with("default", "test_private_key")

            # Check that environment was updated
            call_args = mock_write_env.call_args[0]
            config_data = call_args[1]
            assert config_data["LLM_PROVIDER"] == "openai"
            assert config_data["OPENAI_API_KEY"] == "sk-test123456789"
            assert config_data["OPENAI_MODEL"] == "gpt-4o-mini"
            assert config_data["SAM_SOLANA_RPC_URL"] == "https://api.mainnet-beta.solana.com"

    @pytest.mark.asyncio
    @patch("builtins.input")
    @patch("getpass.getpass")
    @patch("sam.commands.onboard.generate_encryption_key")
    @patch("sam.commands.onboard.get_secure_storage")
    @patch("sam.commands.onboard.find_env_path")
    @patch("sam.commands.onboard.write_env_file")
    @patch("sam.commands.onboard.show_sam_intro")
    @patch("os.path.exists")
    @patch("os.makedirs")
    async def test_onboarding_anthropic_provider(
        self,
        mock_makedirs,
        mock_exists,
        mock_show_intro,
        mock_write_env,
        mock_find_env_path,
        mock_get_storage,
        mock_generate_key,
        mock_getpass,
        mock_input,
    ):
        """Test onboarding flow with Anthropic provider."""
        # Mock user inputs
        mock_input.side_effect = [
            "2",  # Anthropic provider
            "claude-3-5-sonnet-latest",  # Model
            "",  # No custom base URL
            "1",  # Mainnet RPC
            "I AGREE",  # Accept terms
        ]
        mock_getpass.side_effect = [
            "sk-ant-test123",  # Anthropic key
            "test_private_key",  # Solana private key
            "",  # No Brave API key (getpass call)
        ]

        # Mock dependencies
        mock_generate_key.return_value = "test_fernet_key"
        mock_find_env_path.return_value = "/tmp/.env"
        mock_exists.return_value = False

        mock_storage = MagicMock()
        mock_storage.store_private_key.return_value = True
        mock_storage.get_private_key.return_value = "test_private_key"
        mock_get_storage.return_value = mock_storage

        mock_show_intro.return_value = None

        with patch.dict(os.environ, {}, clear=True):
            result = await run_onboarding()

            assert result == 0
            call_args = mock_write_env.call_args[0]
            config_data = call_args[1]
            assert config_data["LLM_PROVIDER"] == "anthropic"
            assert config_data["ANTHROPIC_API_KEY"] == "sk-ant-test123"
            assert config_data["ANTHROPIC_MODEL"] == "claude-3-5-sonnet-latest"

    @pytest.mark.asyncio
    @patch("builtins.input")
    @patch("getpass.getpass")
    @patch("sam.commands.onboard.generate_encryption_key")
    @patch("sam.commands.onboard.get_secure_storage")
    @patch("sam.commands.onboard.find_env_path")
    @patch("sam.commands.onboard.write_env_file")
    @patch("sam.commands.onboard.show_sam_intro")
    @patch("os.path.exists")
    @patch("os.makedirs")
    async def test_onboarding_xai_provider(
        self,
        mock_makedirs,
        mock_exists,
        mock_show_intro,
        mock_write_env,
        mock_find_env_path,
        mock_get_storage,
        mock_generate_key,
        mock_getpass,
        mock_input,
    ):
        """Test onboarding flow with xAI provider."""
        # Mock user inputs
        mock_input.side_effect = [
            "3",  # xAI provider
            "grok-2-latest",  # Model
            "https://api.x.ai/v1",  # Base URL
            "1",  # Mainnet RPC
            "I AGREE",  # Accept terms
        ]
        mock_getpass.side_effect = [
            "xai-test123",  # xAI key
            "test_private_key",  # Solana private key
            "",  # No Brave API key (getpass call)
        ]

        # Mock dependencies
        mock_generate_key.return_value = "test_fernet_key"
        mock_find_env_path.return_value = "/tmp/.env"
        mock_exists.return_value = False

        mock_storage = MagicMock()
        mock_storage.store_private_key.return_value = True
        mock_storage.get_private_key.return_value = "test_private_key"
        mock_get_storage.return_value = mock_storage

        mock_show_intro.return_value = None

        with patch.dict(os.environ, {}, clear=True):
            result = await run_onboarding()

            assert result == 0
            call_args = mock_write_env.call_args[0]
            config_data = call_args[1]
            assert config_data["LLM_PROVIDER"] == "xai"
            assert config_data["XAI_API_KEY"] == "xai-test123"
            assert config_data["XAI_MODEL"] == "grok-2-latest"
            assert config_data["XAI_BASE_URL"] == "https://api.x.ai/v1"

    @pytest.mark.asyncio
    @patch("builtins.input")
    @patch("getpass.getpass")
    @patch("sam.commands.onboard.generate_encryption_key")
    @patch("sam.commands.onboard.get_secure_storage")
    @patch("sam.commands.onboard.find_env_path")
    @patch("sam.commands.onboard.write_env_file")
    @patch("sam.commands.onboard.show_sam_intro")
    @patch("os.path.exists")
    @patch("os.makedirs")
    async def test_onboarding_local_provider(
        self,
        mock_makedirs,
        mock_exists,
        mock_show_intro,
        mock_write_env,
        mock_find_env_path,
        mock_get_storage,
        mock_generate_key,
        mock_getpass,
        mock_input,
    ):
        """Test onboarding flow with local provider."""
        # Mock user inputs
        mock_input.side_effect = [
            "4",  # Local provider
            "http://localhost:11434/v1",  # Base URL
            "llama3.1",  # Model
            "1",  # Mainnet RPC
            "I AGREE",  # Accept terms
        ]
        mock_getpass.side_effect = [
            "optional_key",  # API key (getpass call for local provider)
            "test_private_key",  # Solana private key
            "",  # No Brave API key (getpass call)
        ]

        # Mock dependencies
        mock_generate_key.return_value = "test_fernet_key"
        mock_find_env_path.return_value = "/tmp/.env"
        mock_exists.return_value = False

        mock_storage = MagicMock()
        mock_storage.store_private_key.return_value = True
        mock_storage.get_private_key.return_value = "test_private_key"
        mock_get_storage.return_value = mock_storage

        mock_show_intro.return_value = None

        with patch.dict(os.environ, {}, clear=True):
            result = await run_onboarding()

            assert result == 0
            call_args = mock_write_env.call_args[0]
            config_data = call_args[1]
            assert config_data["LLM_PROVIDER"] == "local"
            assert config_data["LOCAL_LLM_BASE_URL"] == "http://localhost:11434/v1"
            assert config_data["LOCAL_LLM_MODEL"] == "llama3.1"
            assert config_data["LOCAL_LLM_API_KEY"] == "optional_key"

    @pytest.mark.asyncio
    @patch("builtins.input")
    @patch("getpass.getpass")
    @patch("sam.commands.onboard.generate_encryption_key")
    @patch("sam.commands.onboard.get_secure_storage")
    @patch("sam.commands.onboard.find_env_path")
    @patch("sam.commands.onboard.write_env_file")
    @patch("sam.commands.onboard.show_sam_intro")
    @patch("os.path.exists")
    @patch("os.makedirs")
    async def test_onboarding_devnet_rpc(
        self,
        mock_makedirs,
        mock_exists,
        mock_show_intro,
        mock_write_env,
        mock_find_env_path,
        mock_get_storage,
        mock_generate_key,
        mock_getpass,
        mock_input,
    ):
        """Test onboarding with devnet RPC selection."""
        # Mock user inputs
        mock_input.side_effect = [
            "1",  # OpenAI provider
            "gpt-4o-mini",  # Model
            "",  # No custom base URL
            "2",  # Devnet RPC
            "I AGREE",  # Accept terms
        ]
        mock_getpass.side_effect = [
            "sk-test123456789",  # OpenAI key
            "test_private_key",  # Solana private key
            "",  # No Brave API key (getpass call)
        ]

        # Mock dependencies
        mock_generate_key.return_value = "test_fernet_key"
        mock_find_env_path.return_value = "/tmp/.env"
        mock_exists.return_value = False

        mock_storage = MagicMock()
        mock_storage.store_private_key.return_value = True
        mock_storage.get_private_key.return_value = "test_private_key"
        mock_get_storage.return_value = mock_storage

        mock_show_intro.return_value = None

        with patch.dict(os.environ, {}, clear=True):
            result = await run_onboarding()

            assert result == 0
            call_args = mock_write_env.call_args[0]
            config_data = call_args[1]
            assert config_data["SAM_SOLANA_RPC_URL"] == "https://api.devnet.solana.com"

    @pytest.mark.asyncio
    @patch("builtins.input")
    @patch("getpass.getpass")
    @patch("sam.commands.onboard.generate_encryption_key")
    @patch("sam.commands.onboard.get_secure_storage")
    @patch("sam.commands.onboard.find_env_path")
    @patch("sam.commands.onboard.write_env_file")
    @patch("sam.commands.onboard.show_sam_intro")
    @patch("os.path.exists")
    @patch("os.makedirs")
    async def test_onboarding_custom_rpc(
        self,
        mock_makedirs,
        mock_exists,
        mock_show_intro,
        mock_write_env,
        mock_find_env_path,
        mock_get_storage,
        mock_generate_key,
        mock_getpass,
        mock_input,
    ):
        """Test onboarding with custom RPC URL."""
        # Mock user inputs
        mock_input.side_effect = [
            "1",  # OpenAI provider
            "gpt-4o-mini",  # Model
            "",  # No custom base URL
            "3",  # Custom RPC
            "https://my-custom.rpc.com",  # Custom RPC URL
            "I AGREE",  # Accept terms
        ]
        mock_getpass.side_effect = [
            "sk-test123456789",  # OpenAI key
            "test_private_key",  # Solana private key
            "",  # No Brave API key (getpass call)
        ]

        # Mock dependencies
        mock_generate_key.return_value = "test_fernet_key"
        mock_find_env_path.return_value = "/tmp/.env"
        mock_exists.return_value = False

        mock_storage = MagicMock()
        mock_storage.store_private_key.return_value = True
        mock_storage.get_private_key.return_value = "test_private_key"
        mock_get_storage.return_value = mock_storage

        mock_show_intro.return_value = None

        with patch.dict(os.environ, {}, clear=True):
            result = await run_onboarding()

            assert result == 0
            call_args = mock_write_env.call_args[0]
            config_data = call_args[1]
            assert config_data["SAM_SOLANA_RPC_URL"] == "https://my-custom.rpc.com"

    @pytest.mark.asyncio
    @patch("builtins.input")
    @patch("sam.commands.onboard.show_sam_intro")
    async def test_onboarding_terms_rejection(self, mock_show_intro, mock_input):
        """Test onboarding when user rejects terms."""
        mock_input.return_value = "no"  # Reject terms
        mock_show_intro.return_value = None

        result = await run_onboarding()

        assert result == 1

    @pytest.mark.asyncio
    @patch("builtins.input")
    @patch("getpass.getpass")
    @patch("sam.commands.onboard.generate_encryption_key")
    @patch("sam.commands.onboard.get_secure_storage")
    @patch("sam.commands.onboard.find_env_path")
    @patch("sam.commands.onboard.write_env_file")
    @patch("sam.commands.onboard.show_sam_intro")
    @patch("os.path.exists")
    @patch("os.makedirs")
    async def test_onboarding_private_key_storage_failure(
        self,
        mock_makedirs,
        mock_exists,
        mock_show_intro,
        mock_write_env,
        mock_find_env_path,
        mock_get_storage,
        mock_generate_key,
        mock_getpass,
        mock_input,
    ):
        """Test onboarding when private key storage fails."""
        # Mock user inputs
        mock_input.side_effect = [
            "1",  # OpenAI provider
            "gpt-4o-mini",  # Model
            "",  # No custom base URL
            "1",  # Mainnet RPC
            "I AGREE",  # Accept terms
        ]
        mock_getpass.side_effect = [
            "sk-test123456789",  # OpenAI key
            "test_private_key",  # Solana private key
            "",  # No Brave API key (getpass call)
        ]

        # Mock dependencies
        mock_generate_key.return_value = "test_fernet_key"
        mock_find_env_path.return_value = "/tmp/.env"
        mock_exists.return_value = False

        mock_storage = MagicMock()
        mock_storage.store_private_key.return_value = False  # Storage fails
        mock_get_storage.return_value = mock_storage

        mock_show_intro.return_value = None

        with patch.dict(os.environ, {}, clear=True):
            result = await run_onboarding()

            assert result == 1  # Should fail due to storage error

    @pytest.mark.asyncio
    @patch("builtins.input")
    @patch("getpass.getpass")
    @patch("sam.commands.onboard.generate_encryption_key")
    @patch("sam.commands.onboard.get_secure_storage")
    @patch("sam.commands.onboard.find_env_path")
    @patch("sam.commands.onboard.write_env_file")
    @patch("sam.commands.onboard.show_sam_intro")
    @patch("os.path.exists")
    @patch("os.makedirs")
    async def test_onboarding_private_key_verification_failure(
        self,
        mock_makedirs,
        mock_exists,
        mock_show_intro,
        mock_write_env,
        mock_find_env_path,
        mock_get_storage,
        mock_generate_key,
        mock_getpass,
        mock_input,
    ):
        """Test onboarding when private key verification fails."""
        # Mock user inputs
        mock_input.side_effect = [
            "1",  # OpenAI provider
            "gpt-4o-mini",  # Model
            "",  # No custom base URL
            "1",  # Mainnet RPC
            "I AGREE",  # Accept terms
        ]
        mock_getpass.side_effect = [
            "sk-test123456789",  # OpenAI key
            "test_private_key",  # Solana private key
            "",  # No Brave API key (getpass call)
        ]

        # Mock dependencies
        mock_generate_key.return_value = "test_fernet_key"
        mock_find_env_path.return_value = "/tmp/.env"
        mock_exists.return_value = False

        mock_storage = MagicMock()
        mock_storage.store_private_key.return_value = True
        mock_storage.get_private_key.return_value = None  # Verification fails
        mock_get_storage.return_value = mock_storage

        mock_show_intro.return_value = None

        with patch.dict(os.environ, {}, clear=True):
            result = await run_onboarding()

            assert result == 1  # Should fail due to verification error

    @pytest.mark.asyncio
    @patch("builtins.input")
    @patch("sam.commands.onboard.show_sam_intro")
    async def test_onboarding_keyboard_interrupt(self, mock_show_intro, mock_input):
        """Test onboarding with keyboard interrupt."""
        mock_input.side_effect = KeyboardInterrupt()
        mock_show_intro.return_value = None

        result = await run_onboarding()

        assert result == 1

    @pytest.mark.asyncio
    @patch("builtins.input")
    @patch("getpass.getpass")
    @patch("sam.commands.onboard.generate_encryption_key")
    @patch("sam.commands.onboard.get_secure_storage")
    @patch("sam.commands.onboard.find_env_path")
    @patch("sam.commands.onboard.write_env_file")
    @patch("sam.commands.onboard.show_sam_intro")
    @patch("os.path.exists")
    @patch("os.makedirs")
    async def test_onboarding_with_brave_api_key(
        self,
        mock_makedirs,
        mock_exists,
        mock_show_intro,
        mock_write_env,
        mock_find_env_path,
        mock_get_storage,
        mock_generate_key,
        mock_getpass,
        mock_input,
    ):
        """Test onboarding with Brave search API key."""
        # Mock user inputs
        mock_input.side_effect = [
            "1",  # OpenAI provider
            "gpt-4o-mini",  # Model
            "",  # No custom base URL
            "1",  # Mainnet RPC
            "I AGREE",  # Accept terms
        ]
        mock_getpass.side_effect = [
            "sk-test123456789",  # OpenAI key
            "test_private_key",  # Solana private key
            "brave-api-key-123",  # Brave API key (getpass call)
        ]

        # Mock dependencies
        mock_generate_key.return_value = "test_fernet_key"
        mock_find_env_path.return_value = "/tmp/.env"
        mock_exists.return_value = False

        mock_storage = MagicMock()
        mock_storage.store_private_key.return_value = True
        mock_storage.get_private_key.return_value = "test_private_key"
        mock_get_storage.return_value = mock_storage

        mock_show_intro.return_value = None

        with patch.dict(os.environ, {}, clear=True):
            result = await run_onboarding()

            assert result == 0
            call_args = mock_write_env.call_args[0]
            config_data = call_args[1]
            assert config_data["BRAVE_API_KEY"] == "brave-api-key-123"


if __name__ == "__main__":
    pytest.main([__file__])