import pytest
import os
from unittest.mock import patch, MagicMock
from sam.cli import (
    CLIFormatter,
    check_setup_status,
    show_setup_status,
    show_onboarding_guide,
    supports_ansi,
    colorize,
    term_width,
)
from sam.utils.cli_helpers import (
    format_balance_display,
    format_error_for_cli,
    is_first_run,
    _llm_api_configured,
)
from sam.config.settings import Settings


class TestCLIFormatter:
    """Test CLI formatting utilities."""

    def test_colorize_with_ansi(self):
        """Test colorize function with ANSI support."""
        with patch("sam.cli.supports_ansi", return_value=True):
            result = colorize("test", "\033[31m")
            assert result == "\033[31mtest\033[0m"

    def test_colorize_without_ansi(self):
        """Test colorize function without ANSI support."""
        with patch("sam.cli.supports_ansi", return_value=False):
            result = colorize("test", "\033[31m")
            assert result == "test"

    def test_supports_ansi_tty(self):
        """Test ANSI support detection for TTY."""
        with patch("sys.stdout.isatty", return_value=True):
            with patch.dict(os.environ, {}, clear=True):
                assert supports_ansi() is True

    def test_supports_ansi_no_color(self):
        """Test ANSI support with NO_COLOR environment variable."""
        with patch("sys.stdout.isatty", return_value=True):
            with patch.dict(os.environ, {"NO_COLOR": "1"}):
                assert supports_ansi() is False

    def test_term_width_with_shutil(self):
        """Test terminal width detection."""
        with patch("shutil.get_terminal_size", return_value=MagicMock(columns=120)):
            assert term_width() == 120

    def test_term_width_fallback(self):
        """Test terminal width fallback."""
        with patch("shutil.get_terminal_size", side_effect=OSError):
            assert term_width() == 80

    def test_term_width_custom_default(self):
        """Test terminal width with custom default."""
        with patch("shutil.get_terminal_size", side_effect=OSError):
            assert term_width(100) == 100

    def test_cli_formatter_success(self):
        """Test CLI formatter success method."""
        result = CLIFormatter.success("Test message")
        assert "✅ Test message" in result
        assert CLIFormatter.GREEN in result

    def test_cli_formatter_error(self):
        """Test CLI formatter error method."""
        result = CLIFormatter.error("Test error")
        assert "❌ Test error" in result
        assert CLIFormatter.RED in result

    def test_cli_formatter_warning(self):
        """Test CLI formatter warning method."""
        result = CLIFormatter.warning("Test warning")
        assert "⚠️  Test warning" in result
        assert CLIFormatter.YELLOW in result

    def test_cli_formatter_info(self):
        """Test CLI formatter info method."""
        result = CLIFormatter.info("Test info")
        assert "ℹ️  Test info" in result
        assert CLIFormatter.CYAN in result

    def test_cli_formatter_header(self):
        """Test CLI formatter header method."""
        result = CLIFormatter.header("Test header")
        assert CLIFormatter.BOLD in result
        assert CLIFormatter.BLUE in result

    def test_cli_formatter_box(self):
        """Test CLI formatter box method."""
        result = CLIFormatter.box("Title", "Content")
        assert "┌" in result
        assert "└" in result
        assert "Title" in result
        assert "Content" in result


class TestSetupStatus:
    """Test setup status checking functionality."""

    def test_llm_api_configured_openai(self):
        """Test LLM API configuration check for OpenAI."""
        with patch.object(Settings, "LLM_PROVIDER", "openai"):
            with patch.object(Settings, "OPENAI_API_KEY", "test_key"):
                assert _llm_api_configured() is True

    def test_llm_api_configured_anthropic(self):
        """Test LLM API configuration check for Anthropic."""
        with patch.object(Settings, "LLM_PROVIDER", "anthropic"):
            with patch.object(Settings, "ANTHROPIC_API_KEY", "test_key"):
                assert _llm_api_configured() is True

    def test_llm_api_configured_xai(self):
        """Test LLM API configuration check for xAI."""
        with patch.object(Settings, "LLM_PROVIDER", "xai"):
            with patch.object(Settings, "XAI_API_KEY", "test_key"):
                assert _llm_api_configured() is True

    def test_llm_api_configured_local(self):
        """Test LLM API configuration check for local provider."""
        with patch.object(Settings, "LLM_PROVIDER", "local"):
            with patch.object(Settings, "LOCAL_LLM_BASE_URL", "http://localhost:11434/v1"):
                assert _llm_api_configured() is True

    def test_llm_api_configured_openai_compat(self):
        """Test LLM API configuration check for OpenAI compatible."""
        with patch.object(Settings, "LLM_PROVIDER", "openai_compat"):
            with patch.object(Settings, "OPENAI_BASE_URL", "http://localhost:8080/v1"):
                assert _llm_api_configured() is True

    def test_llm_api_not_configured(self):
        """Test LLM API configuration check when not configured."""
        with patch.object(Settings, "LLM_PROVIDER", "openai"):
            with patch.object(Settings, "OPENAI_API_KEY", ""):
                assert _llm_api_configured() is False

    @patch("sam.utils.cli_helpers._llm_api_configured")
    def test_check_setup_status_complete(self, mock_llm_configured):
        """Test setup status check with all components configured."""
        mock_llm_configured.return_value = True

        with patch.object(Settings, "SAM_DB_PATH", "/tmp/test.db"):
            with patch.object(
                Settings, "SAM_SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com"
            ):
                with patch("os.path.exists", return_value=True):
                    with patch("sam.utils.cli_helpers.get_secure_storage") as mock_get_storage:
                        mock_storage = MagicMock()
                        mock_storage.get_private_key.return_value = "test_key"
                        mock_get_storage.return_value = mock_storage

                        status = check_setup_status()

                        assert status["openai_api_key"] is True
                        assert status["wallet_configured"] is True
                        assert status["database_path"] == "/tmp/test.db"
                        assert status["rpc_url"] == "https://api.mainnet-beta.solana.com"
                        assert len(status["issues"]) == 0

    @patch("sam.utils.cli_helpers._llm_api_configured")
    def test_check_setup_status_incomplete(self, mock_llm_configured):
        """Test setup status check with missing components."""
        mock_llm_configured.return_value = False

        with patch.object(Settings, "SAM_DB_PATH", "/tmp/test.db"):
            with patch.object(
                Settings, "SAM_SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com"
            ):
                with patch.object(Settings, "SAM_WALLET_PRIVATE_KEY", None):
                    with patch("os.path.exists", return_value=False):
                        with patch("sam.utils.cli_helpers.get_secure_storage") as mock_get_storage:
                            mock_storage = MagicMock()
                            mock_storage.get_private_key.return_value = None
                            mock_get_storage.return_value = mock_storage

                            status = check_setup_status()

                            assert status["openai_api_key"] is False
                            assert status["wallet_configured"] is False
                            assert len(status["issues"]) >= 2  # Should have multiple issues

    def test_is_first_run(self):
        """Test first run detection."""
        with patch.object(Settings, "SAM_DB_PATH", "/tmp/nonexistent.db"):
            with patch("os.path.exists", return_value=False):
                assert is_first_run() is True

        with patch.object(Settings, "SAM_DB_PATH", "/tmp/existing.db"):
            with patch("os.path.exists", return_value=True):
                assert is_first_run() is False


class TestFormatters:
    """Test data formatting functions."""

    def test_format_balance_display_success(self):
        """Test balance data formatting for successful response."""
        balance_data = {
            "address": "11111111111111111111111111111112",
            "sol_balance": 1.2345,
            "formatted_sol": "1.2345 SOL",
            "total_portfolio_usd": 150.75,
            "tokens": [
                {"mint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "uiAmount": 100.0},
                {"mint": "So11111111111111111111111111111111111111112", "uiAmount": 0.5},
            ],
            "token_count": 2,
        }

        result = format_balance_display(balance_data)

        assert "11111111...11111112" in result  # Shortened address
        assert "1.2345 SOL" in result
        assert "$150.75" in result
        assert "Tokens (2):" in result

    def test_format_balance_display_error(self):
        """Test balance data formatting for error response."""
        balance_data = {"error": True, "title": "Connection Error"}

        result = format_balance_display(balance_data)

        assert "❌" in result
        assert "Connection Error" in result

    def test_format_error_for_cli(self):
        """Test error formatting for CLI display."""
        error_data = {
            "error": True,
            "title": "Test Error",
            "message": "Something went wrong",
            "solutions": ["Try again", "Check your connection"],
            "category": "network",
        }

        result = format_error_for_cli(error_data)

        assert "🌐" in result and "Test Error" in result  # Network category icon
        assert "Something went wrong" in result
        assert "How to fix:" in result
        assert "1. Try again" in result
        assert "2. Check your connection" in result

    def test_format_error_for_cli_wallet_category(self):
        """Test error formatting with wallet category."""
        error_data = {
            "error": True,
            "title": "Wallet Error",
            "message": "Invalid key",
            "category": "wallet",
        }

        result = format_error_for_cli(error_data)

        assert "👛" in result and "Wallet Error" in result  # Wallet category icon

    def test_format_error_for_cli_no_solutions(self):
        """Test error formatting without solutions."""
        error_data = {"error": True, "title": "Simple Error", "message": "Basic error"}

        result = format_error_for_cli(error_data)

        assert "Simple Error" in result
        assert "How to fix:" not in result


class TestOnboarding:
    """Test onboarding and setup guide functions."""

    @patch("builtins.print")
    def test_show_setup_status(self, mock_print):
        """Test setup status display."""
        with patch("sam.cli.check_setup_status") as mock_check:
            mock_check.return_value = {
                "openai_api_key": True,
                "wallet_configured": True,
                "issues": [],
                "recommendations": [],
            }

            show_setup_status()

            # Verify print was called multiple times
            assert mock_print.call_count > 0

    @patch("builtins.print")
    def test_show_onboarding_guide(self, mock_print):
        """Test onboarding guide display."""
        show_onboarding_guide()

        # Verify print was called multiple times
        assert mock_print.call_count > 0


class TestAdditionalCLIHelpers:
    """Test additional CLI helper functions."""

    @patch("builtins.print")
    def test_show_welcome_banner(self, mock_print):
        """Test welcome banner display."""
        from sam.utils.cli_helpers import show_welcome_banner

        show_welcome_banner()

        # Should print the banner
        assert mock_print.call_count > 0
        banner_text = str(mock_print.call_args_list[0])
        assert "🤖 SAM" in banner_text
        assert "Solana Agent Middleware" in banner_text

    @patch("builtins.print")
    def test_show_quick_help(self, mock_print):
        """Test quick help display."""
        from sam.utils.cli_helpers import show_quick_help

        show_quick_help()

        # Should print help information
        assert mock_print.call_count > 0

    @patch("builtins.print")
    @patch("sam.utils.cli_helpers.show_welcome_banner")
    @patch("sam.utils.cli_helpers.show_onboarding_guide")
    def test_show_first_run_experience(self, mock_onboarding, mock_banner, mock_print):
        """Test first run experience display."""
        from sam.utils.cli_helpers import show_first_run_experience

        show_first_run_experience()

        # Should call banner and onboarding
        mock_banner.assert_called_once()
        mock_onboarding.assert_called_once()

        # Should print additional messages
        assert mock_print.call_count >= 2

    @patch("builtins.print")
    @patch("sam.utils.cli_helpers.check_setup_status")
    def test_show_startup_summary_with_issues(self, mock_check_status, mock_print):
        """Test startup summary with issues."""
        from sam.utils.cli_helpers import show_startup_summary

        mock_check_status.return_value = {
            "issues": ["Missing API key"],
            "recommendations": ["Set OPENAI_API_KEY"],
        }

        show_startup_summary()

        # Should print warning and issues
        assert mock_print.call_count > 0

    @patch("builtins.print")
    @patch("sam.utils.cli_helpers.check_setup_status")
    def test_show_startup_summary_no_issues(self, mock_check_status, mock_print):
        """Test startup summary without issues."""
        from sam.utils.cli_helpers import show_startup_summary

        mock_check_status.return_value = {"issues": [], "recommendations": []}

        show_startup_summary()

        # Should print success message
        assert mock_print.call_count > 0
        success_text = str(mock_print.call_args_list[0])
        assert "ready" in success_text.lower() or "🚀" in success_text


if __name__ == "__main__":
    pytest.main([__file__])
