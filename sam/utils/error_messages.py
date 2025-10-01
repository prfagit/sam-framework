"""User-friendly error messages with actionable solutions."""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)


class ErrorCategory(Enum):
    WALLET = "wallet"
    NETWORK = "network"
    TRADING = "trading"
    VALIDATION = "validation"
    AUTHENTICATION = "authentication"
    SYSTEM = "system"


class UserFriendlyError:
    def __init__(
        self,
        category: ErrorCategory,
        title: str,
        message: str,
        solutions: Sequence[str],
        original_error: Optional[str] = None,
    ):
        self.category = category
        self.title = title
        self.message = message
        self.solutions: List[str] = list(solutions)
        self.original_error = original_error

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error": True,
            "category": self.category.value,
            "title": self.title,
            "message": self.message,
            "solutions": self.solutions,
            "original_error": self.original_error,
        }

    def format_for_user(self) -> str:
        """Format error for display to user."""
        output = f"❌ **{self.title}**\n\n{self.message}"

        if self.solutions:
            output += "\n\n💡 **How to fix:**"
            for i, solution in enumerate(self.solutions, 1):
                output += f"\n{i}. {solution}"

        return output


class ErrorMessageGenerator:
    """Generate user-friendly error messages from technical errors."""

    @staticmethod
    def from_solana_error(
        error_msg: str, context: Optional[Mapping[str, Any]] = None
    ) -> UserFriendlyError:
        """Convert Solana RPC errors to user-friendly messages."""
        error_lower = error_msg.lower()

        # Insufficient balance errors
        if "insufficient" in error_lower and ("balance" in error_lower or "funds" in error_lower):
            return UserFriendlyError(
                category=ErrorCategory.WALLET,
                title="Insufficient Balance",
                message="Your wallet doesn't have enough SOL to complete this transaction.",
                solutions=[
                    "Check your balance with: `sam run` → 'check balance'",
                    "Add more SOL to your wallet",
                    "Try a smaller amount",
                ],
                original_error=error_msg,
            )

        # Blockhash errors
        if "blockhash" in error_lower or "expired" in error_lower:
            return UserFriendlyError(
                category=ErrorCategory.NETWORK,
                title="Transaction Expired",
                message="The transaction took too long and expired on the blockchain.",
                solutions=[
                    "Try the transaction again - it should work now",
                    "Check network status if this keeps happening",
                ],
                original_error=error_msg,
            )

        # Network/RPC errors
        if any(keyword in error_lower for keyword in ["timeout", "connection", "network", "rpc"]):
            return UserFriendlyError(
                category=ErrorCategory.NETWORK,
                title="Network Connection Error",
                message="Unable to connect to the Solana network.",
                solutions=[
                    "Check your internet connection",
                    "Try again in a few seconds",
                    "The Solana network may be experiencing issues",
                ],
                original_error=error_msg,
            )

        # Token/mint errors
        if "mint" in error_lower or "token" in error_lower:
            return UserFriendlyError(
                category=ErrorCategory.VALIDATION,
                title="Invalid Token",
                message="The token address is invalid or the token doesn't exist.",
                solutions=[
                    "Double-check the token mint address",
                    "Make sure the token exists on Solana",
                    "Try searching for the token first",
                ],
                original_error=error_msg,
            )

        # Slippage/trading errors
        if "slippage" in error_lower:
            return UserFriendlyError(
                category=ErrorCategory.TRADING,
                title="Slippage Too High",
                message="The price moved too much during the trade.",
                solutions=[
                    "Try increasing slippage tolerance to 10-15%",
                    "Wait for less volatile market conditions",
                    "Use a smaller trade amount",
                ],
                original_error=error_msg,
            )

        # Generic fallback
        return UserFriendlyError(
            category=ErrorCategory.SYSTEM,
            title="Transaction Failed",
            message="The blockchain transaction could not be completed.",
            solutions=[
                "Try the transaction again",
                "Check your wallet balance and network connection",
                "Contact support if the problem persists",
            ],
            original_error=error_msg,
        )

    @staticmethod
    def from_pump_fun_error(
        error_msg: str, context: Optional[Mapping[str, Any]] = None
    ) -> UserFriendlyError:
        """Convert Pump.fun API errors to user-friendly messages."""
        error_lower = error_msg.lower()

        # API rate limiting
        if "rate" in error_lower and "limit" in error_lower:
            return UserFriendlyError(
                category=ErrorCategory.NETWORK,
                title="Too Many Requests",
                message="You're making too many trades too quickly.",
                solutions=[
                    "Wait 30 seconds before trying again",
                    "Slow down your trading frequency",
                ],
                original_error=error_msg,
            )

        # Token not found on pump.fun
        if "not found" in error_lower or "404" in error_msg:
            return UserFriendlyError(
                category=ErrorCategory.TRADING,
                title="Token Not Found",
                message="This token is not available on Pump.fun.",
                solutions=[
                    "Check if the token mint address is correct",
                    "Try trading on Jupiter instead for established tokens",
                    "Make sure the token is actually on Pump.fun",
                ],
                original_error=error_msg,
            )

        # Liquidity issues
        if "liquidity" in error_lower:
            return UserFriendlyError(
                category=ErrorCategory.TRADING,
                title="Low Liquidity",
                message="There's not enough liquidity to complete this trade at the current price.",
                solutions=[
                    "Try a smaller trade amount",
                    "Increase slippage tolerance to 10-20%",
                    "Wait for more trading activity",
                ],
                original_error=error_msg,
            )

        # Generic API error
        return UserFriendlyError(
            category=ErrorCategory.TRADING,
            title="Trading Error",
            message="The Pump.fun trading service encountered an error.",
            solutions=[
                "Try the trade again in a few seconds",
                "Check if Pump.fun is experiencing issues",
                "Try a smaller amount if the problem persists",
            ],
            original_error=error_msg,
        )

    @staticmethod
    def from_validation_error(field: str, error_msg: str) -> UserFriendlyError:
        """Convert validation errors to user-friendly messages."""

        if "address" in field.lower():
            return UserFriendlyError(
                category=ErrorCategory.VALIDATION,
                title="Invalid Address",
                message=f"The {field} you provided is not a valid Solana address.",
                solutions=[
                    "Check that the address is 32-44 characters long",
                    "Make sure there are no typos",
                    "Addresses should only contain letters and numbers",
                ],
                original_error=error_msg,
            )

        if "amount" in field.lower():
            return UserFriendlyError(
                category=ErrorCategory.VALIDATION,
                title="Invalid Amount",
                message="The amount you specified is not valid.",
                solutions=[
                    "Use a positive number (e.g., 0.1, 1.5)",
                    "Maximum amount is 1000 SOL for safety",
                    "Minimum amount is 0.001 SOL",
                ],
                original_error=error_msg,
            )

        if "slippage" in field.lower():
            return UserFriendlyError(
                category=ErrorCategory.VALIDATION,
                title="Invalid Slippage",
                message="The slippage tolerance must be between 1% and 50%.",
                solutions=[
                    "Use 1-5% for stable tokens",
                    "Use 5-15% for volatile tokens",
                    "Use up to 50% for very new tokens",
                ],
                original_error=error_msg,
            )

        # Generic validation error
        return UserFriendlyError(
            category=ErrorCategory.VALIDATION,
            title="Invalid Input",
            message=f"The {field} you provided is not valid.",
            solutions=[
                "Check the format of your input",
                "Try using the example format shown",
                "Ask for help if you're unsure",
            ],
            original_error=error_msg,
        )

    @staticmethod
    def wallet_not_configured() -> UserFriendlyError:
        """Error when no wallet is configured."""
        return UserFriendlyError(
            category=ErrorCategory.WALLET,
            title="Wallet Not Configured",
            message="No wallet is set up for trading. You need to configure a wallet first.",
            solutions=[
                "Run: `sam key import` to add your private key",
                "Make sure your private key is stored securely",
                "Restart SAM after adding the key",
            ],
        )

    @staticmethod
    def no_api_key() -> UserFriendlyError:
        """Error when OpenAI API key is missing."""
        return UserFriendlyError(
            category=ErrorCategory.AUTHENTICATION,
            title="API Key Missing",
            message="OpenAI API key is not configured.",
            solutions=[
                "Set OPENAI_API_KEY environment variable",
                "Get your API key from: https://platform.openai.com/api-keys",
                "Add it to your .env file or export it in your shell",
            ],
        )


def handle_error_gracefully(
    error: Exception, context: Optional[Mapping[str, Any]] = None
) -> Dict[str, Any]:
    """Convert any error to a user-friendly response."""
    error_msg = str(error)

    try:
        # Try to categorize the error and provide helpful message
        if "insufficient" in error_msg.lower():
            friendly_error = ErrorMessageGenerator.from_solana_error(error_msg, context)
        elif "pump" in error_msg.lower():
            friendly_error = ErrorMessageGenerator.from_pump_fun_error(error_msg, context)
        elif "validation" in error_msg.lower():
            # Extract field name if possible
            field_value = context.get("field", "input") if context else "input"
            friendly_error = ErrorMessageGenerator.from_validation_error(
                str(field_value), error_msg
            )
        elif "api" in error_msg.lower() and "key" in error_msg.lower():
            friendly_error = ErrorMessageGenerator.no_api_key()
        elif "wallet" in error_msg.lower() and "configured" in error_msg.lower():
            friendly_error = ErrorMessageGenerator.wallet_not_configured()
        else:
            # Default to Solana error handling
            friendly_error = ErrorMessageGenerator.from_solana_error(error_msg, context)

        # Log the technical error for debugging
        logger.error(f"Error handled gracefully: {error_msg}", exc_info=True)

        return friendly_error.to_dict()

    except Exception as handle_error:
        # Fallback if our error handling fails
        logger.error(f"Error handling failed: {handle_error}", exc_info=True)
        return {
            "error": True,
            "category": "system",
            "title": "Unexpected Error",
            "message": "Something went wrong. Please try again.",
            "solutions": [
                "Try the command again",
                "Restart SAM if the problem persists",
                "Check the logs for more details",
            ],
            "original_error": error_msg,
        }


def format_error_for_cli(error_dict: Mapping[str, Any]) -> str:
    """Format error dictionary for CLI display."""
    if not error_dict.get("error"):
        return str(error_dict)

    title = error_dict.get("title", "Error")
    message = error_dict.get("message", "Something went wrong")
    raw_solutions = error_dict.get("solutions", [])
    if isinstance(raw_solutions, Sequence) and not isinstance(raw_solutions, (str, bytes)):
        solutions = [str(item) for item in raw_solutions]
    elif raw_solutions:
        solutions = [str(raw_solutions)]
    else:
        solutions = []

    output = f"❌ **{title}**\n\n{message}"

    if solutions:
        output += "\n\n💡 **How to fix:**"
        for i, solution in enumerate(solutions, 1):
            output += f"\n{i}. {solution}"

    return output
