"""Pytest configuration and fixtures for SAM Framework tests."""

import os
import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True, scope="session")
def mock_environment_variables():
    """Mock environment variables to prevent interactive prompts during tests."""
    env_vars = {
        # LLM Configuration - use mock values to prevent prompts
        "LLM_PROVIDER": "openai",
        "OPENAI_API_KEY": "sk-test-key-for-testing-only",
        "OPENAI_BASE_URL": "https://api.openai.com/v1",
        "OPENAI_MODEL": "gpt-4o-mini",

        # Anthropic (mock)
        "ANTHROPIC_API_KEY": "sk-ant-test-key-for-testing-only",

        # xAI (mock)
        "XAI_API_KEY": "xai-test-key-for-testing-only",

        # Local LLM (mock)
        "LOCAL_LLM_BASE_URL": "http://localhost:11434/v1",
        "LOCAL_LLM_MODEL": "llama3.1",

        # Solana Configuration
        "SAM_SOLANA_RPC_URL": "https://api.mainnet-beta.solana.com",
        "SAM_WALLET_PRIVATE_KEY": "test-private-key-for-testing",

        # Database Configuration
        "SAM_DB_PATH": ":memory:",  # Use in-memory database for tests

        # Security
        "SAM_FERNET_KEY": "test-fernet-key-for-testing-only",

        # Disable rate limiting for tests
        "RATE_LIMITING_ENABLED": "false",

        # Enable all tools by default for tests
        "ENABLE_SOLANA_TOOLS": "true",
        "ENABLE_PUMP_FUN_TOOLS": "true",
        "ENABLE_DEXSCREENER_TOOLS": "true",
        "ENABLE_JUPITER_TOOLS": "true",
        "ENABLE_SEARCH_TOOLS": "true",

        # Transaction limits
        "MAX_TRANSACTION_SOL": "1000",
        "DEFAULT_SLIPPAGE": "1",

        # Logging - disable noisy logs during tests
        "LOG_LEVEL": "ERROR",

        # Disable first-run experience for tests
        "SAM_LEGAL_ACCEPTED": "true",
    }

    with patch.dict(os.environ, env_vars, clear=False):
        yield


@pytest.fixture(autouse=True, scope="function")
def mock_interactive_functions():
    """Mock interactive functions to prevent user input prompts."""
    with patch("builtins.input", return_value="1"), \
         patch("getpass.getpass", return_value="test-password"), \
         patch("sam.utils.cli_helpers.is_first_run", return_value=False):
        yield


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    import asyncio
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# Disable logging to reduce noise during tests
import logging
logging.getLogger().setLevel(logging.ERROR)

# Mock dotenv loading to prevent .env file issues
import sys
from unittest.mock import MagicMock, patch

# Mock any potential import-time side effects
sys.modules['dotenv'] = MagicMock()
sys.modules['dotenv'].load_dotenv = MagicMock(return_value=None)

# Mock keyring to prevent OS keyring access during tests
sys.modules['keyring'] = MagicMock()
sys.modules['keyring'].get_password = MagicMock(return_value=None)
sys.modules['keyring'].set_password = MagicMock(return_value=None)
