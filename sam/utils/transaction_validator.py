"""Pre-transaction validation to prevent errors and provide warnings."""

import logging
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from .price_service import get_price_service

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of transaction validation."""
    is_valid: bool
    warnings: List[str]
    errors: List[str]
    suggestions: List[str]
    estimated_cost: Optional[float] = None  # In SOL


class TransactionValidator:
    """Validates transactions before execution to prevent common errors."""
    
    def __init__(self):
        self.min_sol_for_fees = 0.01  # Minimum SOL to keep for fees
        self.large_trade_threshold = 10.0  # SOL amount that triggers warning
        self.high_slippage_threshold = 10  # Slippage % that triggers warning
    
    async def validate_balance_sufficient(
        self, 
        wallet_balance: float, 
        transaction_amount: float,
        operation_type: str = "transaction"
    ) -> ValidationResult:
        """Check if wallet has sufficient balance for transaction + fees."""
        warnings = []
        errors = []
        suggestions = []
        
        # Estimate transaction fees (rough estimate)
        estimated_fees = 0.005  # Conservative estimate for Solana transactions
        total_needed = transaction_amount + estimated_fees
        
        # Check if insufficient balance
        if wallet_balance < total_needed:
            errors.append(f"Insufficient SOL balance")
            errors.append(f"Need: {total_needed:.4f} SOL (transaction + fees)")
            errors.append(f"Have: {wallet_balance:.4f} SOL")
            suggestions.append("Add more SOL to your wallet")
            suggestions.append("Try a smaller amount")
            return ValidationResult(
                is_valid=False,
                warnings=warnings,
                errors=errors,
                suggestions=suggestions,
                estimated_cost=total_needed
            )
        
        # Warning for low balance after transaction
        remaining_after = wallet_balance - total_needed
        if remaining_after < self.min_sol_for_fees:
            warnings.append(f"Low SOL balance after {operation_type}")
            warnings.append(f"Will have ~{remaining_after:.4f} SOL left for fees")
            suggestions.append("Consider keeping more SOL for future transactions")
        
        # Warning for large transactions
        if transaction_amount > self.large_trade_threshold:
            try:
                price_service = await get_price_service()
                usd_value = await price_service.sol_to_usd(transaction_amount)
                warnings.append(f"Large transaction: {transaction_amount:.4f} SOL (~${usd_value:.2f})")
                suggestions.append("Double-check the amount before proceeding")
            except Exception:
                warnings.append(f"Large transaction: {transaction_amount:.4f} SOL")
        
        return ValidationResult(
            is_valid=True,
            warnings=warnings,
            errors=errors,
            suggestions=suggestions,
            estimated_cost=total_needed
        )
    
    async def validate_slippage_settings(
        self, 
        slippage: int, 
        token_type: str = "token"
    ) -> ValidationResult:
        """Validate slippage settings and provide warnings."""
        warnings = []
        errors = []
        suggestions = []
        
        # Error for invalid slippage
        if slippage < 1 or slippage > 50:
            errors.append(f"Invalid slippage: {slippage}%")
            errors.append("Slippage must be between 1% and 50%")
            suggestions.append("Use 1-5% for stable tokens")
            suggestions.append("Use 5-15% for volatile tokens")
            return ValidationResult(
                is_valid=False,
                warnings=warnings,
                errors=errors,
                suggestions=suggestions
            )
        
        # Warnings for high slippage
        if slippage > self.high_slippage_threshold:
            warnings.append(f"High slippage tolerance: {slippage}%")
            if slippage > 20:
                warnings.append("Very high slippage - you may lose significant value")
                suggestions.append("Consider lowering slippage or waiting for better market conditions")
            else:
                suggestions.append("High slippage is normal for new/volatile tokens")
        
        # Suggestions based on token type
        if token_type == "pump_fun":
            if slippage < 3:
                suggestions.append("Pump.fun tokens often need 5-15% slippage")
        elif token_type == "established" and slippage > 5:
            suggestions.append("Established tokens usually work with 1-3% slippage")
        
        return ValidationResult(
            is_valid=True,
            warnings=warnings,
            errors=errors,
            suggestions=suggestions
        )
    
    async def validate_token_address(self, mint_address: str) -> ValidationResult:
        """Basic validation of token mint address."""
        warnings = []
        errors = []
        suggestions = []
        
        # Basic format check
        if not mint_address or len(mint_address) < 32 or len(mint_address) > 44:
            errors.append("Invalid token address format")
            errors.append("Solana addresses should be 32-44 characters")
            suggestions.append("Double-check the token mint address")
            suggestions.append("Make sure you copied the full address")
            return ValidationResult(
                is_valid=False,
                warnings=warnings,
                errors=errors,
                suggestions=suggestions
            )
        
        # Check for common patterns that might indicate issues
        if mint_address.count('1') > 20 or mint_address.count('0') > 10:
            warnings.append("Unusual token address pattern")
            suggestions.append("Verify this is the correct token address")
        
        return ValidationResult(
            is_valid=True,
            warnings=warnings,
            errors=errors,
            suggestions=suggestions
        )
    
    async def validate_pump_fun_buy(
        self, 
        wallet_balance: float, 
        amount: float, 
        slippage: int,
        mint_address: str
    ) -> ValidationResult:
        """Comprehensive validation for pump.fun buy operations."""
        all_warnings = []
        all_errors = []
        all_suggestions = []
        
        # Validate balance
        balance_result = await self.validate_balance_sufficient(
            wallet_balance, amount, "pump.fun buy"
        )
        all_warnings.extend(balance_result.warnings)
        all_errors.extend(balance_result.errors)
        all_suggestions.extend(balance_result.suggestions)
        
        if not balance_result.is_valid:
            return ValidationResult(
                is_valid=False,
                warnings=all_warnings,
                errors=all_errors,
                suggestions=all_suggestions,
                estimated_cost=balance_result.estimated_cost
            )
        
        # Validate slippage
        slippage_result = await self.validate_slippage_settings(slippage, "pump_fun")
        all_warnings.extend(slippage_result.warnings)
        all_errors.extend(slippage_result.errors)
        all_suggestions.extend(slippage_result.suggestions)
        
        if not slippage_result.is_valid:
            return ValidationResult(
                is_valid=False,
                warnings=all_warnings,
                errors=all_errors,
                suggestions=all_suggestions,
                estimated_cost=balance_result.estimated_cost
            )
        
        # Validate token address
        token_result = await self.validate_token_address(mint_address)
        all_warnings.extend(token_result.warnings)
        all_errors.extend(token_result.errors)
        all_suggestions.extend(token_result.suggestions)
        
        if not token_result.is_valid:
            return ValidationResult(
                is_valid=False,
                warnings=all_warnings,
                errors=all_errors,
                suggestions=all_suggestions,
                estimated_cost=balance_result.estimated_cost
            )
        
        # Additional pump.fun specific checks
        if amount < 0.001:
            all_warnings.append("Very small trade amount")
            all_suggestions.append("Minimum effective trade is usually 0.001-0.01 SOL")
        
        # Success with warnings
        return ValidationResult(
            is_valid=True,
            warnings=all_warnings,
            errors=all_errors,
            suggestions=all_suggestions,
            estimated_cost=balance_result.estimated_cost
        )
    
    async def validate_pump_fun_sell(
        self,
        percentage: int,
        slippage: int,
        mint_address: str
    ) -> ValidationResult:
        """Comprehensive validation for pump.fun sell operations."""
        all_warnings = []
        all_errors = []
        all_suggestions = []
        
        # Validate percentage
        if percentage < 1 or percentage > 100:
            all_errors.append(f"Invalid sell percentage: {percentage}%")
            all_errors.append("Percentage must be between 1% and 100%")
            all_suggestions.append("Use 25%, 50%, 75%, or 100% for common amounts")
            return ValidationResult(
                is_valid=False,
                warnings=all_warnings,
                errors=all_errors,
                suggestions=all_suggestions
            )
        
        # Validate slippage
        slippage_result = await self.validate_slippage_settings(slippage, "pump_fun")
        all_warnings.extend(slippage_result.warnings)
        all_errors.extend(slippage_result.errors)
        all_suggestions.extend(slippage_result.suggestions)
        
        if not slippage_result.is_valid:
            return ValidationResult(
                is_valid=False,
                warnings=all_warnings,
                errors=all_errors,
                suggestions=all_suggestions
            )
        
        # Validate token address
        token_result = await self.validate_token_address(mint_address)
        all_warnings.extend(token_result.warnings)
        all_errors.extend(token_result.errors)
        all_suggestions.extend(token_result.suggestions)
        
        if not token_result.is_valid:
            return ValidationResult(
                is_valid=False,
                warnings=all_warnings,
                errors=all_errors,
                suggestions=all_suggestions
            )
        
        # Selling-specific warnings
        if percentage == 100:
            all_warnings.append("Selling entire token position")
            all_suggestions.append("Consider keeping a small amount for future potential gains")
        elif percentage < 10:
            all_warnings.append("Selling very small percentage")
            all_suggestions.append("Small sells may not be worth the transaction fees")
        
        return ValidationResult(
            is_valid=True,
            warnings=all_warnings,
            errors=all_errors,
            suggestions=all_suggestions
        )
    
    async def validate_sol_transfer(
        self,
        wallet_balance: float,
        amount: float,
        to_address: str
    ) -> ValidationResult:
        """Validate SOL transfer operations."""
        all_warnings = []
        all_errors = []
        all_suggestions = []
        
        # Validate balance
        balance_result = await self.validate_balance_sufficient(
            wallet_balance, amount, "SOL transfer"
        )
        all_warnings.extend(balance_result.warnings)
        all_errors.extend(balance_result.errors)
        all_suggestions.extend(balance_result.suggestions)
        
        if not balance_result.is_valid:
            return ValidationResult(
                is_valid=False,
                warnings=all_warnings,
                errors=all_errors,
                suggestions=all_suggestions,
                estimated_cost=balance_result.estimated_cost
            )
        
        # Validate destination address
        if not to_address or len(to_address) < 32 or len(to_address) > 44:
            all_errors.append("Invalid destination address")
            all_suggestions.append("Check that the address is correct")
            all_suggestions.append("Solana addresses are 32-44 characters long")
            return ValidationResult(
                is_valid=False,
                warnings=all_warnings,
                errors=all_errors,
                suggestions=all_suggestions,
                estimated_cost=balance_result.estimated_cost
            )
        
        # Warning for large transfers
        if amount > 1.0:
            try:
                price_service = await get_price_service()
                usd_value = await price_service.sol_to_usd(amount)
                all_warnings.append(f"Large transfer: {amount:.4f} SOL (~${usd_value:.2f})")
                all_suggestions.append("Double-check the recipient address")
                all_suggestions.append("Consider doing a small test transfer first")
            except Exception:
                all_warnings.append(f"Large transfer: {amount:.4f} SOL")
        
        return ValidationResult(
            is_valid=True,
            warnings=all_warnings,
            errors=all_errors,
            suggestions=all_suggestions,
            estimated_cost=balance_result.estimated_cost
        )
    
    def format_validation_result(self, result: ValidationResult) -> str:
        """Format validation result for CLI display."""
        output = []
        
        # Errors (blocking)
        if result.errors:
            output.append("❌ **Validation Errors:**")
            for error in result.errors:
                output.append(f"   • {error}")
        
        # Warnings (proceed with caution)
        if result.warnings:
            output.append("⚠️  **Warnings:**")
            for warning in result.warnings:
                output.append(f"   • {warning}")
        
        # Suggestions
        if result.suggestions:
            output.append("💡 **Suggestions:**")
            for suggestion in result.suggestions:
                output.append(f"   • {suggestion}")
        
        # Estimated cost
        if result.estimated_cost:
            output.append(f"💰 **Estimated Cost:** {result.estimated_cost:.4f} SOL")
        
        return "\n".join(output) if output else ""


# Global validator instance
_global_validator: Optional[TransactionValidator] = None


async def get_transaction_validator() -> TransactionValidator:
    """Get global transaction validator instance."""
    global _global_validator
    if _global_validator is None:
        _global_validator = TransactionValidator()
    return _global_validator


# Convenience functions
async def validate_pump_buy(wallet_balance: float, amount: float, slippage: int, mint: str) -> ValidationResult:
    """Validate pump.fun buy transaction."""
    validator = await get_transaction_validator()
    return await validator.validate_pump_fun_buy(wallet_balance, amount, slippage, mint)


async def validate_pump_sell(percentage: int, slippage: int, mint: str) -> ValidationResult:
    """Validate pump.fun sell transaction.""" 
    validator = await get_transaction_validator()
    return await validator.validate_pump_fun_sell(percentage, slippage, mint)


async def validate_sol_transfer(wallet_balance: float, amount: float, to_address: str) -> ValidationResult:
    """Validate SOL transfer transaction."""
    validator = await get_transaction_validator() 
    return await validator.validate_sol_transfer(wallet_balance, amount, to_address)