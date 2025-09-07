import pytest
import os
import logging
from unittest.mock import patch, MagicMock
from sam.config.prompts import (
    SOLANA_AGENT_PROMPT,
    RISK_ASSESSMENT_PROMPT,
    TRADING_CONFIRMATION_PROMPT,
)
from sam.config.settings import Settings, setup_logging


class TestPrompts:
    """Test prompt templates and content."""

    def test_solana_agent_prompt_exists(self):
        """Test that SOLANA_AGENT_PROMPT is defined and has content."""
        assert SOLANA_AGENT_PROMPT is not None
        assert isinstance(SOLANA_AGENT_PROMPT, str)
        assert len(SOLANA_AGENT_PROMPT.strip()) > 0

    def test_solana_agent_prompt_content(self):
        """Test SOLANA_AGENT_PROMPT contains expected content."""
        prompt = SOLANA_AGENT_PROMPT.upper()

        # Check for key sections
        assert "SAM" in prompt
        assert "SOLANA" in prompt
        assert "PUMP.FUN" in prompt
        assert "JUPITER" in prompt
        assert "TOOL SELECTION" in prompt
        assert "EXECUTION RULES" in prompt

    def test_risk_assessment_prompt_exists(self):
        """Test that RISK_ASSESSMENT_PROMPT is defined and has content."""
        assert RISK_ASSESSMENT_PROMPT is not None
        assert isinstance(RISK_ASSESSMENT_PROMPT, str)
        assert len(RISK_ASSESSMENT_PROMPT.strip()) > 0

    def test_risk_assessment_prompt_content(self):
        """Test RISK_ASSESSMENT_PROMPT contains expected content."""
        prompt = RISK_ASSESSMENT_PROMPT.upper()

        assert "RISK" in prompt
        assert "LIQUIDITY" in prompt
        assert "VOLATILITY" in prompt
        assert "RECOMMENDATIONS" in prompt

    def test_trading_confirmation_prompt_exists(self):
        """Test that TRADING_CONFIRMATION_PROMPT is defined and has content."""
        assert TRADING_CONFIRMATION_PROMPT is not None
        assert isinstance(TRADING_CONFIRMATION_PROMPT, str)
        assert len(TRADING_CONFIRMATION_PROMPT.strip()) > 0

    def test_trading_confirmation_prompt_content(self):
        """Test TRADING_CONFIRMATION_PROMPT contains expected content."""
        prompt = TRADING_CONFIRMATION_PROMPT.upper()

        assert "CONFIRM" in prompt
        assert "TRADING ACTION" in prompt
        assert "SLIPPAGE" in prompt
        assert "RISK ASSESSMENT" in prompt

    def test_prompts_are_strings(self):
        """Test that all prompts are strings."""
        prompts = [SOLANA_AGENT_PROMPT, RISK_ASSESSMENT_PROMPT, TRADING_CONFIRMATION_PROMPT]

        for prompt in prompts:
            assert isinstance(prompt, str)
            assert len(prompt.strip()) > 10  # Reasonable minimum length

    def test_prompts_contain_placeholders(self):
        """Test that prompts contain expected placeholder patterns."""
        # Risk assessment should have placeholders
        assert "{token_info}" in RISK_ASSESSMENT_PROMPT
        assert "{trading_data}" in RISK_ASSESSMENT_PROMPT
        assert "{market_data}" in RISK_ASSESSMENT_PROMPT

        # Trading confirmation should have placeholders
        assert "{action}" in TRADING_CONFIRMATION_PROMPT
        assert "{token_symbol}" in TRADING_CONFIRMATION_PROMPT
        assert "{amount}" in TRADING_CONFIRMATION_PROMPT
        assert "{price_usd}" in TRADING_CONFIRMATION_PROMPT
        assert "{slippage}" in TRADING_CONFIRMATION_PROMPT
        assert "{estimated_value}" in TRADING_CONFIRMATION_PROMPT
        assert "{risk_level}" in TRADING_CONFIRMATION_PROMPT
        assert "{liquidity_usd}" in TRADING_CONFIRMATION_PROMPT


class TestSettings:
    """Test Settings class functionality."""

    def test_settings_class_attributes_exist(self):
        """Test that Settings class has expected attributes."""
        # LLM Configuration
        assert hasattr(Settings, "LLM_PROVIDER")
        assert hasattr(Settings, "OPENAI_API_KEY")
        assert hasattr(Settings, "OPENAI_BASE_URL")
        assert hasattr(Settings, "OPENAI_MODEL")
        assert hasattr(Settings, "ANTHROPIC_API_KEY")
        assert hasattr(Settings, "ANTHROPIC_BASE_URL")
        assert hasattr(Settings, "ANTHROPIC_MODEL")
        assert hasattr(Settings, "XAI_API_KEY")
        assert hasattr(Settings, "XAI_BASE_URL")
        assert hasattr(Settings, "XAI_MODEL")
        assert hasattr(Settings, "LOCAL_LLM_BASE_URL")
        assert hasattr(Settings, "LOCAL_LLM_API_KEY")
        assert hasattr(Settings, "LOCAL_LLM_MODEL")

        # Solana Configuration
        assert hasattr(Settings, "SAM_SOLANA_RPC_URL")
        assert hasattr(Settings, "SAM_WALLET_PRIVATE_KEY")

        # Database Configuration
        assert hasattr(Settings, "SAM_DB_PATH")

        # Other Configuration
        assert hasattr(Settings, "RATE_LIMITING_ENABLED")
        assert hasattr(Settings, "SAM_FERNET_KEY")
        assert hasattr(Settings, "MAX_TRANSACTION_SOL")
        assert hasattr(Settings, "DEFAULT_SLIPPAGE")
        assert hasattr(Settings, "LOG_LEVEL")

    def test_settings_default_values(self):
        """Test Settings default values."""
        # Clear any existing environment variables
        with patch.dict(os.environ, {}, clear=True):
            # Refresh settings to use defaults
            Settings.refresh_from_env()

            assert Settings.LLM_PROVIDER == "openai"
            assert Settings.OPENAI_MODEL == "gpt-4o-mini"
            assert Settings.ANTHROPIC_MODEL == "claude-3-5-sonnet-latest"
            assert Settings.XAI_MODEL == "grok-2-latest"
            assert Settings.LOCAL_LLM_MODEL == "llama3.1"
            assert Settings.SAM_SOLANA_RPC_URL == "https://api.mainnet-beta.solana.com"
            assert Settings.SAM_DB_PATH == ".sam/sam_memory.db"
            assert Settings.RATE_LIMITING_ENABLED is False
            assert Settings.MAX_TRANSACTION_SOL == 1000.0
        assert Settings.DEFAULT_SLIPPAGE == 1
        assert Settings.LOG_LEVEL == "INFO"

    def test_tool_toggles_default_on(self):
        """Tool toggles should default to enabled (true)."""
        with patch.dict(os.environ, {}, clear=True):
            Settings.refresh_from_env()
            assert Settings.ENABLE_SOLANA_TOOLS is True
            assert Settings.ENABLE_PUMP_FUN_TOOLS is True
            assert Settings.ENABLE_DEXSCREENER_TOOLS is True
            assert Settings.ENABLE_JUPITER_TOOLS is True
            assert Settings.ENABLE_SEARCH_TOOLS is True

    @patch.dict(
        os.environ,
        {
            "LLM_PROVIDER": "anthropic",
            "ANTHROPIC_API_KEY": "test_key",
            "SAM_SOLANA_RPC_URL": "https://test.rpc.com",
            "RATE_LIMITING_ENABLED": "true",
            "MAX_TRANSACTION_SOL": "500",
            "DEFAULT_SLIPPAGE": "5",
        },
    )
    def test_settings_environment_variables(self):
        """Test Settings loading from environment variables."""
        Settings.refresh_from_env()

        assert Settings.LLM_PROVIDER == "anthropic"
        assert Settings.ANTHROPIC_API_KEY == "test_key"
        assert Settings.SAM_SOLANA_RPC_URL == "https://test.rpc.com"
        assert Settings.RATE_LIMITING_ENABLED is True
        assert Settings.MAX_TRANSACTION_SOL == 500.0
        assert Settings.DEFAULT_SLIPPAGE == 5

    def test_tool_toggles_env_overrides(self):
        """Tool toggles should respect environment variable overrides."""
        with patch.dict(
            os.environ,
            {
                "ENABLE_SOLANA_TOOLS": "false",
                "ENABLE_PUMP_FUN_TOOLS": "TRUE",
                "ENABLE_DEXSCREENER_TOOLS": "False",
                "ENABLE_JUPITER_TOOLS": "false",
                "ENABLE_SEARCH_TOOLS": "true",
            },
            clear=False,
        ):
            Settings.refresh_from_env()
            assert Settings.ENABLE_SOLANA_TOOLS is False
            assert Settings.ENABLE_PUMP_FUN_TOOLS is True
            assert Settings.ENABLE_DEXSCREENER_TOOLS is False
            assert Settings.ENABLE_JUPITER_TOOLS is False
            assert Settings.ENABLE_SEARCH_TOOLS is True

    def test_settings_refresh_from_env(self):
        """Test refresh_from_env method."""
        with patch.dict(os.environ, {"LLM_PROVIDER": "xai"}, clear=False):
            Settings.refresh_from_env()
            assert Settings.LLM_PROVIDER == "xai"

    def test_settings_validate_openai_success(self):
        """Test validation with valid OpenAI configuration."""
        with patch.object(Settings, "LLM_PROVIDER", "openai"):
            with patch.object(Settings, "OPENAI_API_KEY", "test_key"):
                with patch.object(Settings, "SAM_FERNET_KEY", "fernet_key"):
                    assert Settings.validate() is True

    def test_settings_validate_openai_missing_key(self):
        """Test validation with missing OpenAI API key."""
        with patch.object(Settings, "LLM_PROVIDER", "openai"):
            with patch.object(Settings, "OPENAI_API_KEY", ""):
                with patch.object(Settings, "SAM_FERNET_KEY", "fernet_key"):
                    assert Settings.validate() is False

    def test_settings_validate_anthropic_success(self):
        """Test validation with valid Anthropic configuration."""
        with patch.object(Settings, "LLM_PROVIDER", "anthropic"):
            with patch.object(Settings, "ANTHROPIC_API_KEY", "test_key"):
                with patch.object(Settings, "SAM_FERNET_KEY", "fernet_key"):
                    assert Settings.validate() is True

    def test_settings_validate_xai_success(self):
        """Test validation with valid xAI configuration."""
        with patch.object(Settings, "LLM_PROVIDER", "xai"):
            with patch.object(Settings, "XAI_API_KEY", "test_key"):
                with patch.object(Settings, "SAM_FERNET_KEY", "fernet_key"):
                    assert Settings.validate() is True

    def test_settings_validate_openai_compat_success(self):
        """Test validation with valid OpenAI-compatible configuration."""
        with patch.object(Settings, "LLM_PROVIDER", "openai_compat"):
            with patch.object(Settings, "OPENAI_BASE_URL", "http://localhost:8000"):
                with patch.object(Settings, "SAM_FERNET_KEY", "fernet_key"):
                    assert Settings.validate() is True

    def test_settings_validate_openai_compat_missing_url(self):
        """Test validation with missing OpenAI-compatible base URL."""
        with patch.object(Settings, "LLM_PROVIDER", "openai_compat"):
            with patch.object(Settings, "OPENAI_BASE_URL", None):
                with patch.object(Settings, "SAM_FERNET_KEY", "fernet_key"):
                    assert Settings.validate() is False

    def test_settings_validate_missing_fernet_key(self):
        """Test validation with missing Fernet key."""
        with patch.object(Settings, "LLM_PROVIDER", "openai"):
            with patch.object(Settings, "OPENAI_API_KEY", "test_key"):
                with patch.object(Settings, "SAM_FERNET_KEY", None):
                    assert Settings.validate() is False

    @patch("sam.config.settings.logger")
    def test_settings_log_config(self, mock_logger):
        """Test log_config method."""
        with patch.object(Settings, "LLM_PROVIDER", "openai"):
            with patch.object(Settings, "OPENAI_MODEL", "gpt-4"):
                with patch.object(Settings, "SAM_SOLANA_RPC_URL", "https://test.rpc.com"):
                    Settings.log_config()

                    # Check that logger.info was called multiple times
                    assert mock_logger.info.call_count > 5


class TestSetupLogging:
    """Test setup_logging function."""

    def test_setup_logging_default_level(self):
        """Test setup_logging with default log level."""
        # Test that setup_logging doesn't crash with default settings
        try:
            setup_logging()
        except Exception as e:
            pytest.fail(f"setup_logging() raised an exception: {e}")

    @patch("logging.basicConfig")
    @patch("logging.getLogger")
    def test_setup_logging_custom_level(self, mock_get_logger, mock_basic_config):
        """Test setup_logging with custom log level."""
        setup_logging("DEBUG")

        call_args = mock_basic_config.call_args
        assert call_args[1]["level"] == logging.DEBUG

    @patch("logging.basicConfig")
    @patch("logging.getLogger")
    def test_setup_logging_no_logging(self, mock_get_logger, mock_basic_config):
        """Test setup_logging with NO logging level."""
        mock_logger = MagicMock()
        mock_get_logger.return_value = mock_logger

        setup_logging("NO")

        call_args = mock_basic_config.call_args
        # Should set level higher than CRITICAL to disable logging
        assert call_args[1]["level"] > logging.CRITICAL

    @patch("logging.basicConfig")
    @patch("logging.getLogger")
    def test_setup_logging_invalid_level(self, mock_get_logger, mock_basic_config):
        """Test setup_logging with invalid log level."""
        setup_logging("INVALID")

        call_args = mock_basic_config.call_args
        # Should default to INFO for invalid levels
        assert call_args[1]["level"] == logging.INFO

    @patch("logging.basicConfig")
    @patch("logging.getLogger")
    def test_setup_logging_reduces_third_party_noise(self, mock_get_logger, mock_basic_config):
        """Test that setup_logging reduces noise from third-party libraries."""
        mock_aiohttp_logger = MagicMock()
        mock_solana_logger = MagicMock()
        mock_urllib3_logger = MagicMock()

        def get_logger_side_effect(name):
            if name == "aiohttp":
                return mock_aiohttp_logger
            elif name == "solana":
                return mock_solana_logger
            elif name == "urllib3":
                return mock_urllib3_logger
            else:
                return MagicMock()

        mock_get_logger.side_effect = get_logger_side_effect

        setup_logging("DEBUG")

        # Check that third-party loggers had their levels set
        mock_aiohttp_logger.setLevel.assert_called()
        mock_solana_logger.setLevel.assert_called()
        mock_urllib3_logger.setLevel.assert_called()


if __name__ == "__main__":
    pytest.main([__file__])
