"""Pytest configuration and fixtures for SAM Framework tests."""

import logging
import os
import sys
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture(autouse=True, scope="session")
def mock_environment_variables():
    """Mock environment variables to prevent interactive prompts during tests."""
    env_vars = {
        # Enable test mode to allow test/mock API keys
        "SAM_TEST_MODE": "1",
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
    with (
        patch("builtins.input", return_value="1"),
        patch("getpass.getpass", return_value="test-password"),
        patch("sam.utils.cli_helpers.is_first_run", return_value=False),
    ):
        yield


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    import asyncio

    loop = asyncio.get_event_loop_policy().new_event_loop()
    try:
        yield loop
    finally:
        # Proactively cancel any pending tasks to avoid hangs
        try:
            # Collect tasks bound to this loop from within the loop context
            async def _gather_pending():
                cur = asyncio.current_task()
                return [t for t in asyncio.all_tasks() if t is not cur and not t.done()]

            pending = loop.run_until_complete(_gather_pending())
            for t in pending:
                t.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        except Exception:
            pass
        loop.close()


@pytest.fixture(autouse=True, scope="session")
async def cleanup_background_services():
    """Ensure background tasks started by globals are shut down at session end.

    Some modules start background asyncio tasks (metrics collector, rate limiter)
    that can keep the event loop alive after tests finish. This fixture cleans them up.
    """
    yield
    try:
        # Cleanup metrics collector if started
        from sam.utils.monitoring import cleanup_metrics_collector

        await cleanup_metrics_collector()
    except Exception:
        pass
    try:
        # Cleanup global rate limiter if created
        from sam.utils.rate_limiter import cleanup_rate_limiter

        await cleanup_rate_limiter()
    except Exception:
        pass
    try:
        # Cleanup global price service (clears cache, resets singleton)
        from sam.utils.price_service import cleanup_price_service

        await cleanup_price_service()
    except Exception:
        pass
    try:
        # Cleanup shared HTTP client to ensure aiohttp session is closed
        from sam.utils.http_client import cleanup_http_client

        await cleanup_http_client()
    except Exception:
        pass


# Disable logging to reduce noise during tests
logging.getLogger().setLevel(logging.ERROR)

# Mock any potential import-time side effects
sys.modules["dotenv"] = MagicMock()
sys.modules["dotenv"].load_dotenv = MagicMock(return_value=None)

# Mock keyring to prevent OS keyring access during tests
sys.modules["keyring"] = MagicMock()
sys.modules["keyring"].get_password = MagicMock(return_value=None)
sys.modules["keyring"].set_password = MagicMock(return_value=None)
