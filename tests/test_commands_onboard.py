import pytest
import os
from unittest.mock import patch, MagicMock
from sam.commands.onboard import run_onboarding


class TestOnboarding:
    """Test onboarding command functionality."""

    @pytest.mark.asyncio
    @patch("builtins.input")
    @patch("sam.commands.onboard.derive_solana_address")
    @patch("getpass.getpass")
    @patch("sam.commands.onboard.generate_encryption_key")
    @patch("sam.commands.onboard.get_profile_store")
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
        mock_get_profile_store,
        mock_generate_key,
        mock_getpass,
        mock_derive_solana_address,
        mock_input,
    ):
        """Test onboarding flow with OpenAI provider."""
        # Mock user inputs
        mock_input.side_effect = [
            "1",  # OpenAI provider
            "gpt-4o-mini",  # Model
            "",  # No custom base URL
            "1",  # Mainnet RPC
            "",  # Import existing Solana key
            "",  # Skip Hyperliquid setup
            "I AGREE",  # Accept terms
        ]
        mock_getpass.side_effect = [
            "sk-test123456789",  # OpenAI key
            "test_private_key",  # Solana private key
            "",  # No Brave API key (getpass call)
        ]
        mock_derive_solana_address.return_value = "So11111111111111111111111111111111111111112"

        # Mock dependencies
        mock_generate_key.return_value = "test_fernet_key"
        mock_find_env_path.return_value = "/tmp/.env"
        mock_exists.return_value = False

        mock_storage = MagicMock()
        mock_storage.store_private_key.return_value = True
        mock_storage.store_api_key.return_value = True
        mock_storage.get_private_key.return_value = "test_private_key"
        mock_get_storage.return_value = mock_storage

        mock_profile_store = MagicMock()
        mock_get_profile_store.return_value = mock_profile_store

        mock_show_intro.return_value = None

        with patch.dict(os.environ, {}, clear=True):
            result = await run_onboarding()

            assert result == 0
            mock_write_env.assert_called_once()
            mock_storage.store_private_key.assert_any_call("default", "test_private_key")
            mock_storage.store_api_key.assert_any_call("openai_api_key", "sk-test123456789")

            profile_updates = mock_profile_store.update.call_args[0][0]
            assert profile_updates["LLM_PROVIDER"] == "openai"
            assert profile_updates["OPENAI_MODEL"] == "gpt-4o-mini"
            assert profile_updates["SAM_SOLANA_RPC_URL"] == "https://api.mainnet-beta.solana.com"
            assert (
                profile_updates["SAM_SOLANA_ADDRESS"]
                == "So11111111111111111111111111111111111111112"
            )
            assert profile_updates["ENABLE_HYPERLIQUID_TOOLS"] is False

            env_call = mock_write_env.call_args[0][1]
            assert env_call["SAM_FERNET_KEY"] == "test_fernet_key"
            assert env_call["SAM_DB_PATH"] == ".sam/sam_memory.db"

    @pytest.mark.asyncio
    @patch("builtins.input")
    @patch("sam.commands.onboard.derive_solana_address")
    @patch("getpass.getpass")
    @patch("sam.commands.onboard.generate_encryption_key")
    @patch("sam.commands.onboard.get_profile_store")
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
        mock_get_profile_store,
        mock_generate_key,
        mock_getpass,
        mock_derive_solana_address,
        mock_input,
    ):
        """Test onboarding flow with Anthropic provider."""
        # Mock user inputs
        mock_input.side_effect = [
            "2",  # Anthropic provider
            "claude-3-5-sonnet-latest",  # Model
            "",  # No custom base URL
            "1",  # Mainnet RPC
            "",  # Import Solana key
            "",  # Skip Hyperliquid
            "I AGREE",  # Accept terms
        ]
        mock_getpass.side_effect = [
            "sk-ant-test123",  # Anthropic key
            "test_private_key",  # Solana private key
            "",  # No Brave API key (getpass call)
        ]
        mock_derive_solana_address.return_value = "So11111111111111111111111111111111111111112"

        # Mock dependencies
        mock_generate_key.return_value = "test_fernet_key"
        mock_find_env_path.return_value = "/tmp/.env"
        mock_exists.return_value = False

        mock_storage = MagicMock()
        mock_storage.store_private_key.return_value = True
        mock_storage.store_api_key.return_value = True
        mock_storage.get_private_key.return_value = "test_private_key"
        mock_get_storage.return_value = mock_storage

        mock_profile_store = MagicMock()
        mock_get_profile_store.return_value = mock_profile_store

        mock_show_intro.return_value = None

        with patch.dict(os.environ, {}, clear=True):
            result = await run_onboarding()

            assert result == 0
            profile_updates = mock_profile_store.update.call_args[0][0]
            assert profile_updates["LLM_PROVIDER"] == "anthropic"
            assert profile_updates["ANTHROPIC_MODEL"] == "claude-3-5-sonnet-latest"
            assert (
                profile_updates["SAM_SOLANA_ADDRESS"]
                == "So11111111111111111111111111111111111111112"
            )
            assert profile_updates["ENABLE_HYPERLIQUID_TOOLS"] is False

            mock_storage.store_api_key.assert_any_call("anthropic_api_key", "sk-ant-test123")

    @pytest.mark.asyncio
    @patch("builtins.input")
    @patch("sam.commands.onboard.derive_solana_address")
    @patch("getpass.getpass")
    @patch("sam.commands.onboard.generate_encryption_key")
    @patch("sam.commands.onboard.get_profile_store")
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
        mock_get_profile_store,
        mock_generate_key,
        mock_getpass,
        mock_derive_solana_address,
        mock_input,
    ):
        """Test onboarding flow with xAI provider."""
        # Mock user inputs
        mock_input.side_effect = [
            "3",  # xAI provider
            "grok-2-latest",  # Model
            "https://api.x.ai/v1",  # Base URL
            "1",  # Mainnet RPC
            "",  # Import Solana key
            "",  # Skip Hyperliquid
            "I AGREE",  # Accept terms
        ]
        mock_getpass.side_effect = [
            "xai-test123",  # xAI key
            "test_private_key",  # Solana private key
            "",  # No Brave API key (getpass call)
        ]
        mock_derive_solana_address.return_value = "So11111111111111111111111111111111111111112"

        # Mock dependencies
        mock_generate_key.return_value = "test_fernet_key"
        mock_find_env_path.return_value = "/tmp/.env"
        mock_exists.return_value = False

        mock_storage = MagicMock()
        mock_storage.store_private_key.return_value = True
        mock_storage.store_api_key.return_value = True
        mock_storage.get_private_key.return_value = "test_private_key"
        mock_get_storage.return_value = mock_storage

        mock_profile_store = MagicMock()
        mock_get_profile_store.return_value = mock_profile_store

        mock_show_intro.return_value = None

        with patch.dict(os.environ, {}, clear=True):
            result = await run_onboarding()

            assert result == 0
            profile_updates = mock_profile_store.update.call_args[0][0]
            assert profile_updates["LLM_PROVIDER"] == "xai"
            assert profile_updates["XAI_MODEL"] == "grok-2-latest"
            assert profile_updates["XAI_BASE_URL"] == "https://api.x.ai/v1"
            assert (
                profile_updates["SAM_SOLANA_ADDRESS"]
                == "So11111111111111111111111111111111111111112"
            )
            assert profile_updates["ENABLE_HYPERLIQUID_TOOLS"] is False

            mock_storage.store_api_key.assert_any_call("xai_api_key", "xai-test123")

    @pytest.mark.asyncio
    @patch("builtins.input")
    @patch("sam.commands.onboard.derive_solana_address")
    @patch("getpass.getpass")
    @patch("sam.commands.onboard.generate_encryption_key")
    @patch("sam.commands.onboard.get_profile_store")
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
        mock_get_profile_store,
        mock_generate_key,
        mock_getpass,
        mock_derive_solana_address,
        mock_input,
    ):
        """Test onboarding flow with local provider."""
        # Mock user inputs
        mock_input.side_effect = [
            "4",  # Local provider
            "http://localhost:11434/v1",  # Base URL
            "llama3.1",  # Model
            "1",  # Mainnet RPC
            "",  # Import Solana key
            "",  # Skip Hyperliquid
            "I AGREE",  # Accept terms
        ]
        mock_getpass.side_effect = [
            "optional_key",  # API key (getpass call for local provider)
            "test_private_key",  # Solana private key
            "",  # No Brave API key (getpass call)
        ]
        mock_derive_solana_address.return_value = "So11111111111111111111111111111111111111112"

        # Mock dependencies
        mock_generate_key.return_value = "test_fernet_key"
        mock_find_env_path.return_value = "/tmp/.env"
        mock_exists.return_value = False

        mock_storage = MagicMock()
        mock_storage.store_private_key.return_value = True
        mock_storage.store_api_key.return_value = True
        mock_storage.get_private_key.return_value = "test_private_key"
        mock_get_storage.return_value = mock_storage

        mock_profile_store = MagicMock()
        mock_get_profile_store.return_value = mock_profile_store

        mock_show_intro.return_value = None

        with patch.dict(os.environ, {}, clear=True):
            result = await run_onboarding()

            assert result == 0
            profile_updates = mock_profile_store.update.call_args[0][0]
            assert profile_updates["LLM_PROVIDER"] == "local"
            assert profile_updates["LOCAL_LLM_BASE_URL"] == "http://localhost:11434/v1"
            assert profile_updates["LOCAL_LLM_MODEL"] == "llama3.1"
            assert (
                profile_updates["SAM_SOLANA_ADDRESS"]
                == "So11111111111111111111111111111111111111112"
            )
            assert profile_updates["ENABLE_HYPERLIQUID_TOOLS"] is False

            mock_storage.store_api_key.assert_any_call("local_llm_api_key", "optional_key")

    @pytest.mark.asyncio
    @patch("builtins.input")
    @patch("sam.commands.onboard.derive_solana_address")
    @patch("getpass.getpass")
    @patch("sam.commands.onboard.generate_encryption_key")
    @patch("sam.commands.onboard.get_profile_store")
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
        mock_get_profile_store,
        mock_generate_key,
        mock_getpass,
        mock_derive_solana_address,
        mock_input,
    ):
        """Test onboarding with devnet RPC selection."""
        # Mock user inputs
        mock_input.side_effect = [
            "1",  # OpenAI provider
            "gpt-4o-mini",  # Model
            "",  # No custom base URL
            "2",  # Devnet RPC
            "",  # Import Solana key
            "",  # Skip Hyperliquid
            "I AGREE",  # Accept terms
        ]
        mock_getpass.side_effect = [
            "sk-test123456789",  # OpenAI key
            "test_private_key",  # Solana private key
            "",  # No Brave API key (getpass call)
        ]
        mock_derive_solana_address.return_value = "So11111111111111111111111111111111111111112"

        # Mock dependencies
        mock_generate_key.return_value = "test_fernet_key"
        mock_find_env_path.return_value = "/tmp/.env"
        mock_exists.return_value = False

        mock_storage = MagicMock()
        mock_storage.store_private_key.return_value = True
        mock_storage.store_api_key.return_value = True
        mock_storage.get_private_key.return_value = "test_private_key"
        mock_get_storage.return_value = mock_storage

        mock_profile_store = MagicMock()
        mock_get_profile_store.return_value = mock_profile_store

        mock_show_intro.return_value = None

        with patch.dict(os.environ, {}, clear=True):
            result = await run_onboarding()

            assert result == 0
            profile_updates = mock_profile_store.update.call_args[0][0]
            assert profile_updates["SAM_SOLANA_RPC_URL"] == "https://api.devnet.solana.com"
            assert (
                profile_updates["SAM_SOLANA_ADDRESS"]
                == "So11111111111111111111111111111111111111112"
            )
            assert profile_updates["ENABLE_HYPERLIQUID_TOOLS"] is False

            mock_storage.store_api_key.assert_any_call("openai_api_key", "sk-test123456789")

    @pytest.mark.asyncio
    @patch("builtins.input")
    @patch("sam.commands.onboard.derive_solana_address")
    @patch("getpass.getpass")
    @patch("sam.commands.onboard.generate_encryption_key")
    @patch("sam.commands.onboard.get_profile_store")
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
        mock_get_profile_store,
        mock_generate_key,
        mock_getpass,
        mock_derive_solana_address,
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
            "",  # Import Solana key
            "",  # Skip Hyperliquid
            "I AGREE",  # Accept terms
        ]
        mock_getpass.side_effect = [
            "sk-test123456789",  # OpenAI key
            "test_private_key",  # Solana private key
            "",  # No Brave API key (getpass call)
        ]
        mock_derive_solana_address.return_value = "So11111111111111111111111111111111111111112"

        # Mock dependencies
        mock_generate_key.return_value = "test_fernet_key"
        mock_find_env_path.return_value = "/tmp/.env"
        mock_exists.return_value = False

        mock_storage = MagicMock()
        mock_storage.store_private_key.return_value = True
        mock_storage.store_api_key.return_value = True
        mock_storage.get_private_key.return_value = "test_private_key"
        mock_get_storage.return_value = mock_storage

        mock_profile_store = MagicMock()
        mock_get_profile_store.return_value = mock_profile_store

        mock_show_intro.return_value = None

        with patch.dict(os.environ, {}, clear=True):
            result = await run_onboarding()

            assert result == 0
            profile_updates = mock_profile_store.update.call_args[0][0]
            assert profile_updates["SAM_SOLANA_RPC_URL"] == "https://my-custom.rpc.com"
            assert (
                profile_updates["SAM_SOLANA_ADDRESS"]
                == "So11111111111111111111111111111111111111112"
            )
            assert profile_updates["ENABLE_HYPERLIQUID_TOOLS"] is False

            mock_storage.store_api_key.assert_any_call("openai_api_key", "sk-test123456789")

    @pytest.mark.asyncio
    @patch("builtins.input")
    @patch("sam.commands.onboard.derive_solana_address")
    @patch("getpass.getpass")
    @patch("sam.commands.onboard.show_sam_intro")
    async def test_onboarding_terms_rejection(
        self,
        mock_show_intro,
        mock_getpass,
        mock_derive_solana_address,
        mock_input,
    ):
        """Test onboarding when user rejects terms."""
        mock_input.side_effect = [
            "1",  # Provider
            "gpt-4o-mini",  # Model prompt
            "",  # Base URL
            "1",  # RPC
            "",  # Import Solana key
            "",  # Skip Hyperliquid
            "no",  # Reject terms
        ]
        mock_getpass.side_effect = [
            "fake-openai-key",
            "fake-solana-key",
            "",  # Brave optional
        ]
        mock_derive_solana_address.return_value = "So11111111111111111111111111111111111111112"
        mock_show_intro.return_value = None

        result = await run_onboarding()

        assert result == 1

    @pytest.mark.asyncio
    @patch("builtins.input")
    @patch("sam.commands.onboard.derive_solana_address")
    @patch("getpass.getpass")
    @patch("sam.commands.onboard.generate_encryption_key")
    @patch("sam.commands.onboard.get_profile_store")
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
        mock_get_profile_store,
        mock_generate_key,
        mock_getpass,
        mock_derive_solana_address,
        mock_input,
    ):
        """Test onboarding when private key storage fails."""
        # Mock user inputs
        mock_input.side_effect = [
            "1",  # OpenAI provider
            "gpt-4o-mini",  # Model
            "",  # No custom base URL
            "1",  # Mainnet RPC
            "",  # Import Solana key
            "",  # Skip Hyperliquid
            "I AGREE",  # Accept terms
        ]
        mock_getpass.side_effect = [
            "sk-test123456789",  # OpenAI key
            "test_private_key",  # Solana private key
            "",  # No Brave API key (getpass call)
        ]
        mock_derive_solana_address.return_value = "So11111111111111111111111111111111111111112"

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
    @patch("sam.commands.onboard.derive_solana_address")
    @patch("getpass.getpass")
    @patch("sam.commands.onboard.generate_encryption_key")
    @patch("sam.commands.onboard.get_profile_store")
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
        mock_get_profile_store,
        mock_generate_key,
        mock_getpass,
        mock_derive_solana_address,
        mock_input,
    ):
        """Test onboarding when private key verification fails."""
        # Mock user inputs
        mock_input.side_effect = [
            "1",  # OpenAI provider
            "gpt-4o-mini",  # Model
            "",  # No custom base URL
            "1",  # Mainnet RPC
            "",  # Import Solana key
            "",  # Skip Hyperliquid
            "I AGREE",  # Accept terms
        ]
        mock_getpass.side_effect = [
            "sk-test123456789",  # OpenAI key
            "test_private_key",  # Solana private key
            "",  # No Brave API key (getpass call)
        ]
        mock_derive_solana_address.return_value = "So11111111111111111111111111111111111111112"

        # Mock dependencies
        mock_generate_key.return_value = "test_fernet_key"
        mock_find_env_path.return_value = "/tmp/.env"
        mock_exists.return_value = False

        mock_storage = MagicMock()
        mock_storage.store_private_key.return_value = True
        mock_storage.get_private_key.return_value = None  # Verification fails
        mock_get_storage.return_value = mock_storage

        mock_profile_store = MagicMock()
        mock_get_profile_store.return_value = mock_profile_store

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
    @patch("sam.commands.onboard.derive_solana_address")
    @patch("getpass.getpass")
    @patch("sam.commands.onboard.generate_encryption_key")
    @patch("sam.commands.onboard.get_profile_store")
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
        mock_get_profile_store,
        mock_generate_key,
        mock_getpass,
        mock_derive_solana_address,
        mock_input,
    ):
        """Test onboarding with Brave search API key."""
        # Mock user inputs
        mock_input.side_effect = [
            "1",  # OpenAI provider
            "gpt-4o-mini",  # Model
            "",  # No custom base URL
            "1",  # Mainnet RPC
            "",  # Import Solana key
            "",  # Skip Hyperliquid
            "I AGREE",  # Accept terms
        ]
        mock_getpass.side_effect = [
            "sk-test123456789",  # OpenAI key
            "test_private_key",  # Solana private key
            "brave-api-key-123",  # Brave API key (getpass call)
        ]
        mock_derive_solana_address.return_value = "So11111111111111111111111111111111111111112"

        # Mock dependencies
        mock_generate_key.return_value = "test_fernet_key"
        mock_find_env_path.return_value = "/tmp/.env"
        mock_exists.return_value = False

        mock_storage = MagicMock()
        mock_storage.store_private_key.return_value = True
        mock_storage.store_api_key.return_value = True
        mock_storage.get_private_key.return_value = "test_private_key"
        mock_get_storage.return_value = mock_storage

        mock_profile_store = MagicMock()
        mock_get_profile_store.return_value = mock_profile_store

        mock_show_intro.return_value = None

        with patch.dict(os.environ, {}, clear=True):
            result = await run_onboarding()

            assert result == 0
            profile_updates = mock_profile_store.update.call_args[0][0]
            assert (
                profile_updates["SAM_SOLANA_ADDRESS"]
                == "So11111111111111111111111111111111111111112"
            )
            assert profile_updates["ENABLE_HYPERLIQUID_TOOLS"] is False

            mock_storage.store_api_key.assert_any_call("openai_api_key", "sk-test123456789")
            mock_storage.store_api_key.assert_any_call("brave_api_key", "brave-api-key-123")

    @pytest.mark.asyncio
    @patch("builtins.input")
    @patch("sam.commands.onboard.generate_evm_wallet")
    @patch("sam.commands.onboard.derive_evm_address")
    @patch("sam.commands.onboard.generate_solana_wallet")
    @patch("sam.commands.onboard.derive_solana_address")
    @patch("getpass.getpass")
    @patch("sam.commands.onboard.generate_encryption_key")
    @patch("sam.commands.onboard.get_profile_store")
    @patch("sam.commands.onboard.get_secure_storage")
    @patch("sam.commands.onboard.find_env_path")
    @patch("sam.commands.onboard.write_env_file")
    @patch("sam.commands.onboard.show_sam_intro")
    @patch("os.path.exists")
    @patch("os.makedirs")
    async def test_onboarding_with_generated_wallets(
        self,
        mock_makedirs,
        mock_exists,
        mock_show_intro,
        mock_write_env,
        mock_find_env_path,
        mock_get_storage,
        mock_get_profile_store,
        mock_generate_key,
        mock_getpass,
        mock_derive_solana_address,
        mock_generate_solana_wallet,
        mock_derive_evm_address,
        mock_generate_evm_wallet,
        mock_input,
    ):
        """Test onboarding when generating both Solana and Hyperliquid wallets."""

        mock_input.side_effect = [
            "1",  # OpenAI provider
            "gpt-4o-mini",  # Model
            "",  # Base URL
            "1",  # RPC
            "generate",  # Generate Solana wallet
            "y",  # Enable Hyperliquid
            "generate",  # Generate Hyperliquid wallet
            "I AGREE",  # Accept terms
        ]
        mock_getpass.side_effect = [
            "sk-test123456789",  # OpenAI key
            "",  # Brave optional
        ]

        mock_generate_solana_wallet.return_value = (
            "SOL_GENERATED_PRIVATE",
            "SoGenerated1111111111111111111111111111111",
        )
        mock_derive_solana_address.return_value = "SoGenerated1111111111111111111111111111111"
        mock_generate_evm_wallet.return_value = (
            "0xgeneratedprivate",
            "0xGeneratedAddress",
        )
        mock_derive_evm_address.side_effect = lambda key: {
            "0xgeneratedprivate": "0xGeneratedAddress",
        }.get(key, "0xGeneratedAddress")

        mock_generate_key.return_value = "test_fernet_key"
        mock_find_env_path.return_value = "/tmp/.env"
        mock_exists.return_value = False

        mock_storage = MagicMock()
        mock_storage.store_private_key.return_value = True
        mock_storage.store_api_key.return_value = True
        mock_storage.get_private_key.return_value = "SOL_GENERATED_PRIVATE"
        mock_get_storage.return_value = mock_storage

        mock_profile_store = MagicMock()
        mock_get_profile_store.return_value = mock_profile_store

        mock_show_intro.return_value = None

        with patch.dict(os.environ, {}, clear=True):
            result = await run_onboarding()

            assert result == 0

            # Ensure generated keys were stored
            mock_storage.store_private_key.assert_any_call("default", "SOL_GENERATED_PRIVATE")
            mock_storage.store_private_key.assert_any_call(
                "hyperliquid_private_key", "0xgeneratedprivate"
            )
            mock_storage.store_api_key.assert_any_call(
                "hyperliquid_account_address", "0xGeneratedAddress"
            )
            profile_updates = mock_profile_store.update.call_args[0][0]
            assert profile_updates["ENABLE_HYPERLIQUID_TOOLS"] is True
            assert (
                profile_updates["SAM_SOLANA_ADDRESS"]
                == "SoGenerated1111111111111111111111111111111"
            )
            assert profile_updates["EVM_WALLET_ADDRESS"] == "0xGeneratedAddress"
            assert "HYPERLIQUID_ACCOUNT_ADDRESS" not in profile_updates


if __name__ == "__main__":
    pytest.main([__file__])
