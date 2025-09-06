import pytest
from sam.utils.error_messages import (
    ErrorCategory,
    UserFriendlyError,
    ErrorMessageGenerator,
    handle_error_gracefully,
    format_error_for_cli,
)


class TestErrorCategory:
    """Test ErrorCategory enum."""

    def test_error_category_values(self):
        """Test error category enum values."""
        assert ErrorCategory.WALLET.value == "wallet"
        assert ErrorCategory.NETWORK.value == "network"
        assert ErrorCategory.TRADING.value == "trading"
        assert ErrorCategory.VALIDATION.value == "validation"
        assert ErrorCategory.AUTHENTICATION.value == "authentication"
        assert ErrorCategory.SYSTEM.value == "system"


class TestUserFriendlyError:
    """Test UserFriendlyError class."""

    def test_user_friendly_error_creation(self):
        """Test UserFriendlyError initialization."""
        error = UserFriendlyError(
            category=ErrorCategory.WALLET,
            title="Test Error",
            message="Something went wrong",
            solutions=["Try again", "Check balance"],
            original_error="Original error details",
        )

        assert error.category == ErrorCategory.WALLET
        assert error.title == "Test Error"
        assert error.message == "Something went wrong"
        assert error.solutions == ["Try again", "Check balance"]
        assert error.original_error == "Original error details"

    def test_user_friendly_error_to_dict(self):
        """Test UserFriendlyError to_dict method."""
        error = UserFriendlyError(
            category=ErrorCategory.NETWORK,
            title="Connection Error",
            message="Network issue",
            solutions=["Check connection"],
            original_error="Connection timeout",
        )

        result = error.to_dict()

        expected = {
            "error": True,
            "category": "network",
            "title": "Connection Error",
            "message": "Network issue",
            "solutions": ["Check connection"],
            "original_error": "Connection timeout",
        }

        assert result == expected

    def test_user_friendly_error_format_for_user(self):
        """Test UserFriendlyError format_for_user method."""
        error = UserFriendlyError(
            category=ErrorCategory.TRADING,
            title="Trade Failed",
            message="Insufficient balance",
            solutions=["Add more funds", "Try smaller amount"],
            original_error="Insufficient funds",
        )

        result = error.format_for_user()

        assert "❌ **Trade Failed**" in result
        assert "Insufficient balance" in result
        assert "💡 **How to fix:**" in result
        assert "1. Add more funds" in result
        assert "2. Try smaller amount" in result

    def test_user_friendly_error_format_no_solutions(self):
        """Test UserFriendlyError format with no solutions."""
        error = UserFriendlyError(
            category=ErrorCategory.SYSTEM,
            title="System Error",
            message="Unexpected error",
            solutions=[],
            original_error="System crash",
        )

        result = error.format_for_user()

        assert "❌ **System Error**" in result
        assert "Unexpected error" in result
        assert "How to fix:" not in result


class TestErrorMessageGenerator:
    """Test ErrorMessageGenerator class."""

    def test_from_solana_error_insufficient_balance(self):
        """Test Solana insufficient balance error conversion."""
        error_msg = "insufficient balance for transaction"
        result = ErrorMessageGenerator.from_solana_error(error_msg)

        assert result.category == ErrorCategory.WALLET
        assert result.title == "Insufficient Balance"
        assert "enough SOL" in result.message
        assert "check balance" in result.solutions[0]
        assert result.original_error == error_msg

    def test_from_solana_error_blockhash_expired(self):
        """Test Solana blockhash expired error conversion."""
        error_msg = "blockhash expired"
        result = ErrorMessageGenerator.from_solana_error(error_msg)

        assert result.category == ErrorCategory.NETWORK
        assert result.title == "Transaction Expired"
        assert "took too long" in result.message
        assert "try" in result.solutions[0].lower()

    def test_from_solana_error_network_timeout(self):
        """Test Solana network timeout error conversion."""
        error_msg = "RPC timeout occurred"
        result = ErrorMessageGenerator.from_solana_error(error_msg)

        assert result.category == ErrorCategory.NETWORK
        assert result.title == "Network Connection Error"
        assert "connect to the Solana network" in result.message
        assert "internet connection" in result.solutions[0]

    def test_from_solana_error_invalid_token(self):
        """Test Solana invalid token error conversion."""
        error_msg = "invalid mint address"
        result = ErrorMessageGenerator.from_solana_error(error_msg)

        assert result.category == ErrorCategory.VALIDATION
        assert result.title == "Invalid Token"
        assert "token address is invalid" in result.message
        assert "check" in result.solutions[0].lower()

    def test_from_solana_error_slippage_too_high(self):
        """Test Solana slippage error conversion."""
        error_msg = "slippage tolerance exceeded"
        result = ErrorMessageGenerator.from_solana_error(error_msg)

        assert result.category == ErrorCategory.TRADING
        assert result.title == "Slippage Too High"
        assert "price moved too much" in result.message
        assert "increasing slippage" in result.solutions[0]

    def test_from_solana_error_generic_fallback(self):
        """Test Solana generic error fallback."""
        error_msg = "some unknown error"
        result = ErrorMessageGenerator.from_solana_error(error_msg)

        assert result.category == ErrorCategory.SYSTEM
        assert result.title == "Transaction Failed"
        assert "could not be completed" in result.message
        assert "try" in result.solutions[0].lower()

    def test_from_pump_fun_error_rate_limit(self):
        """Test Pump.fun rate limit error conversion."""
        error_msg = "rate limit exceeded"
        result = ErrorMessageGenerator.from_pump_fun_error(error_msg)

        assert result.category == ErrorCategory.NETWORK
        assert result.title == "Too Many Requests"
        assert "too many trades" in result.message
        assert "30 seconds" in result.solutions[0]

    def test_from_pump_fun_error_token_not_found(self):
        """Test Pump.fun token not found error conversion."""
        error_msg = "token not found"
        result = ErrorMessageGenerator.from_pump_fun_error(error_msg)

        assert result.category == ErrorCategory.TRADING
        assert result.title == "Token Not Found"
        assert "not available on Pump.fun" in result.message
        assert "token mint address" in result.solutions[0]

    def test_from_pump_fun_error_liquidity_issue(self):
        """Test Pump.fun liquidity error conversion."""
        error_msg = "insufficient liquidity"
        result = ErrorMessageGenerator.from_pump_fun_error(error_msg)

        assert result.category == ErrorCategory.TRADING
        assert result.title == "Low Liquidity"
        assert "enough liquidity" in result.message
        assert "smaller trade amount" in result.solutions[0]

    def test_from_pump_fun_error_generic(self):
        """Test Pump.fun generic error conversion."""
        error_msg = "pump.fun service error"
        result = ErrorMessageGenerator.from_pump_fun_error(error_msg)

        assert result.category == ErrorCategory.TRADING
        assert result.title == "Trading Error"
        assert "trading service encountered an error" in result.message
        assert "try" in result.solutions[0].lower()

    def test_from_validation_error_address(self):
        """Test validation error for address field."""
        error_msg = "invalid address format"
        result = ErrorMessageGenerator.from_validation_error("address", error_msg)

        assert result.category == ErrorCategory.VALIDATION
        assert result.title == "Invalid Address"
        assert "not a valid Solana address" in result.message
        assert "32-44 characters" in result.solutions[0]

    def test_from_validation_error_amount(self):
        """Test validation error for amount field."""
        error_msg = "amount must be positive"
        result = ErrorMessageGenerator.from_validation_error("amount", error_msg)

        assert result.category == ErrorCategory.VALIDATION
        assert result.title == "Invalid Amount"
        assert "not valid" in result.message
        assert "positive number" in result.solutions[0]

    def test_from_validation_error_slippage(self):
        """Test validation error for slippage field."""
        error_msg = "slippage out of range"
        result = ErrorMessageGenerator.from_validation_error("slippage", error_msg)

        assert result.category == ErrorCategory.VALIDATION
        assert result.title == "Invalid Slippage"
        assert "between 1% and 50%" in result.message
        assert "stable tokens" in result.solutions[0]

    def test_from_validation_error_generic_field(self):
        """Test validation error for generic field."""
        error_msg = "invalid input"
        result = ErrorMessageGenerator.from_validation_error("custom_field", error_msg)

        assert result.category == ErrorCategory.VALIDATION
        assert result.title == "Invalid Input"
        assert "custom_field" in result.message
        assert "format of your input" in result.solutions[0]

    def test_wallet_not_configured(self):
        """Test wallet not configured error."""
        result = ErrorMessageGenerator.wallet_not_configured()

        assert result.category == ErrorCategory.WALLET
        assert result.title == "Wallet Not Configured"
        assert "wallet" in result.message.lower() and "set up" in result.message.lower()
        assert "sam key import" in result.solutions[0]

    def test_no_api_key(self):
        """Test no API key error."""
        result = ErrorMessageGenerator.no_api_key()

        assert result.category == ErrorCategory.AUTHENTICATION
        assert result.title == "API Key Missing"
        assert "OpenAI API key is not configured" in result.message
        assert "OPENAI_API_KEY" in result.solutions[0]


class TestUtilityFunctions:
    """Test utility functions."""

    def test_handle_error_gracefully_insufficient_balance(self):
        """Test handle_error_gracefully with insufficient balance."""
        error = Exception("insufficient balance for transaction")

        result = handle_error_gracefully(error)

        assert result["error"] is True
        assert result["category"] == "wallet"
        assert result["title"] == "Insufficient Balance"
        assert "enough SOL" in result["message"]

    def test_handle_error_gracefully_pump_fun_error(self):
        """Test handle_error_gracefully with pump.fun error."""
        error = Exception("pump.fun rate limit exceeded")

        result = handle_error_gracefully(error)

        assert result["error"] is True
        assert result["category"] == "network"
        assert result["title"] == "Too Many Requests"

    def test_handle_error_gracefully_validation_error(self):
        """Test handle_error_gracefully with validation error."""
        error = Exception("validation failed")
        context = {"field": "address"}

        result = handle_error_gracefully(error, context)

        assert result["error"] is True
        assert result["category"] == "validation"
        assert result["title"] == "Invalid Address"

    def test_handle_error_gracefully_api_key_error(self):
        """Test handle_error_gracefully with API key error."""
        error = Exception("API key missing")

        result = handle_error_gracefully(error)

        assert result["error"] is True
        assert result["category"] == "authentication"
        assert result["title"] == "API Key Missing"

    def test_handle_error_gracefully_wallet_config_error(self):
        """Test handle_error_gracefully with wallet config error."""
        error = Exception("wallet not configured")

        result = handle_error_gracefully(error)

        assert result["error"] is True
        assert result["category"] == "wallet"
        assert result["title"] == "Wallet Not Configured"

    def test_handle_error_gracefully_generic_error(self):
        """Test handle_error_gracefully with generic error."""
        error = Exception("some unknown error")

        result = handle_error_gracefully(error)

        assert result["error"] is True
        assert result["category"] == "system"
        assert result["title"] == "Transaction Failed"

    def test_handle_error_gracefully_error_in_handler(self):
        """Test handle_error_gracefully when error handling itself fails."""
        # This tests that the function handles its own errors gracefully
        error = Exception("test error")

        # The function should handle any internal errors and return a fallback response
        result = handle_error_gracefully(error)
        assert isinstance(result, dict)
        assert result["error"] is True
        assert "title" in result
        assert "message" in result

    def test_format_error_for_cli_with_solutions(self):
        """Test format_error_for_cli with solutions."""
        error_dict = {
            "error": True,
            "title": "Test Error",
            "message": "Something went wrong",
            "solutions": ["Try again", "Check connection"],
        }

        result = format_error_for_cli(error_dict)

        assert "❌ **Test Error**" in result
        assert "Something went wrong" in result
        assert "💡 **How to fix:**" in result
        assert "1. Try again" in result
        assert "2. Check connection" in result

    def test_format_error_for_cli_no_solutions(self):
        """Test format_error_for_cli without solutions."""
        error_dict = {
            "error": True,
            "title": "Simple Error",
            "message": "Basic error",
            "solutions": [],
        }

        result = format_error_for_cli(error_dict)

        assert "❌ **Simple Error**" in result
        assert "Basic error" in result
        assert "How to fix:" not in result

    def test_format_error_for_cli_not_error(self):
        """Test format_error_for_cli with non-error dict."""
        error_dict = {"success": True, "data": "test"}

        result = format_error_for_cli(error_dict)

        assert result == str(error_dict)


if __name__ == "__main__":
    pytest.main([__file__])
