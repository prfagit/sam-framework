import pytest
from unittest.mock import patch, AsyncMock
from sam.utils.transaction_validator import (
    TransactionValidator,
    ValidationResult,
    get_transaction_validator,
    validate_pump_buy,
    validate_pump_sell,
    validate_sol_transfer,
)


class TestValidationResult:
    """Test ValidationResult dataclass."""

    def test_validation_result_creation(self):
        """Test ValidationResult initialization."""
        result = ValidationResult(
            is_valid=True,
            warnings=["Warning 1"],
            errors=["Error 1"],
            suggestions=["Suggestion 1"],
            estimated_cost=0.005,
        )

        assert result.is_valid is True
        assert result.warnings == ["Warning 1"]
        assert result.errors == ["Error 1"]
        assert result.suggestions == ["Suggestion 1"]
        assert result.estimated_cost == 0.005

    def test_validation_result_defaults(self):
        """Test ValidationResult with default values."""
        result = ValidationResult(is_valid=False, warnings=[], errors=[], suggestions=[])

        assert result.is_valid is False
        assert result.warnings == []
        assert result.errors == []
        assert result.suggestions == []
        assert result.estimated_cost is None


class TestTransactionValidator:
    """Test TransactionValidator functionality."""

    @pytest.fixture
    async def validator(self):
        """Create a test validator."""
        return TransactionValidator()

    @pytest.mark.asyncio
    async def test_validate_balance_sufficient_success(self, validator):
        """Test successful balance validation."""
        result = await validator.validate_balance_sufficient(
            wallet_balance=1.0, transaction_amount=0.1, operation_type="test"
        )

        assert result.is_valid is True
        assert len(result.errors) == 0
        assert abs(result.estimated_cost - 0.105) < 0.001  # 0.1 + 0.005 fees

    @pytest.mark.asyncio
    async def test_validate_balance_insufficient(self, validator):
        """Test insufficient balance validation."""
        result = await validator.validate_balance_sufficient(
            wallet_balance=0.01, transaction_amount=0.1, operation_type="test"
        )

        assert result.is_valid is False
        assert len(result.errors) > 0
        assert "Insufficient SOL balance" in result.errors[0]

    @pytest.mark.asyncio
    async def test_validate_balance_low_remaining(self, validator):
        """Test low balance warning after transaction."""
        result = await validator.validate_balance_sufficient(
            wallet_balance=0.02, transaction_amount=0.015, operation_type="test"
        )

        assert result.is_valid is True
        assert len(result.warnings) > 0
        assert "Low SOL balance" in result.warnings[0]

    @pytest.mark.asyncio
    async def test_validate_balance_large_transaction(self, validator):
        """Test large transaction warning."""
        with patch("sam.utils.transaction_validator.get_price_service") as mock_get_price:
            mock_price_service = AsyncMock()
            mock_price_service.sol_to_usd.return_value = 2500.0
            mock_get_price.return_value = mock_price_service

            result = await validator.validate_balance_sufficient(
                wallet_balance=15.0, transaction_amount=12.0, operation_type="test"
            )

            assert result.is_valid is True
            assert len(result.warnings) > 0
            assert "Large transaction" in result.warnings[0]

    @pytest.mark.asyncio
    async def test_validate_slippage_valid(self, validator):
        """Test valid slippage validation."""
        result = await validator.validate_slippage_settings(slippage=5, token_type="token")

        assert result.is_valid is True
        assert len(result.errors) == 0

    @pytest.mark.asyncio
    async def test_validate_slippage_invalid_low(self, validator):
        """Test invalid low slippage."""
        result = await validator.validate_slippage_settings(slippage=0, token_type="token")

        assert result.is_valid is False
        assert len(result.errors) > 0
        assert "Invalid slippage" in result.errors[0]

    @pytest.mark.asyncio
    async def test_validate_slippage_invalid_high(self, validator):
        """Test invalid high slippage."""
        result = await validator.validate_slippage_settings(slippage=60, token_type="token")

        assert result.is_valid is False
        assert len(result.errors) > 0
        assert "Invalid slippage" in result.errors[0]

    @pytest.mark.asyncio
    async def test_validate_slippage_high_warning(self, validator):
        """Test high slippage warning."""
        result = await validator.validate_slippage_settings(slippage=15, token_type="token")

        assert result.is_valid is True
        assert len(result.warnings) > 0
        assert "High slippage tolerance" in result.warnings[0]

    @pytest.mark.asyncio
    async def test_validate_slippage_pump_fun_suggestions(self, validator):
        """Test pump.fun specific slippage suggestions."""
        result = await validator.validate_slippage_settings(slippage=2, token_type="pump_fun")

        assert result.is_valid is True
        assert len(result.suggestions) > 0
        assert "Pump.fun tokens often need" in result.suggestions[0]

    @pytest.mark.asyncio
    async def test_validate_token_address_valid(self, validator):
        """Test valid token address validation."""
        valid_address = "So11111111111111111111111111111111111111112"  # SOL mint

        result = await validator.validate_token_address(valid_address)

        assert result.is_valid is True
        assert len(result.errors) == 0

    @pytest.mark.asyncio
    async def test_validate_token_address_invalid_short(self, validator):
        """Test invalid short token address."""
        result = await validator.validate_token_address("short")

        assert result.is_valid is False
        assert len(result.errors) > 0
        assert "Invalid token address format" in result.errors[0]

    @pytest.mark.asyncio
    async def test_validate_token_address_invalid_long(self, validator):
        """Test invalid long token address."""
        long_address = "A" * 50

        result = await validator.validate_token_address(long_address)

        assert result.is_valid is False
        assert len(result.errors) > 0
        assert "Invalid token address format" in result.errors[0]

    @pytest.mark.asyncio
    async def test_validate_token_address_suspicious_pattern(self, validator):
        """Test suspicious token address pattern."""
        suspicious_address = "1" * 35  # Too many 1s

        result = await validator.validate_token_address(suspicious_address)

        assert result.is_valid is True
        assert len(result.warnings) > 0
        assert "Unusual token address pattern" in result.warnings[0]

    @pytest.mark.asyncio
    async def test_validate_pump_fun_buy_success(self, validator):
        """Test successful pump.fun buy validation."""
        with patch("sam.utils.transaction_validator.get_price_service") as mock_get_price:
            mock_price_service = AsyncMock()
            mock_price_service.sol_to_usd.return_value = 100.0
            mock_get_price.return_value = mock_price_service

            result = await validator.validate_pump_fun_buy(
                wallet_balance=2.0,
                amount=0.5,
                slippage=10,
                mint_address="So11111111111111111111111111111111111111112",
            )

            assert result.is_valid is True
            assert len(result.errors) == 0

    @pytest.mark.asyncio
    async def test_validate_pump_fun_buy_insufficient_balance(self, validator):
        """Test pump.fun buy with insufficient balance."""
        result = await validator.validate_pump_fun_buy(
            wallet_balance=0.01,
            amount=0.5,
            slippage=10,
            mint_address="So11111111111111111111111111111111111111112",
        )

        assert result.is_valid is False
        assert len(result.errors) > 0
        assert "Insufficient SOL balance" in result.errors[0]

    @pytest.mark.asyncio
    async def test_validate_pump_fun_buy_invalid_slippage(self, validator):
        """Test pump.fun buy with invalid slippage."""
        result = await validator.validate_pump_fun_buy(
            wallet_balance=2.0,
            amount=0.1,
            slippage=60,
            mint_address="So11111111111111111111111111111111111111112",
        )

        assert result.is_valid is False
        assert len(result.errors) > 0
        assert "Invalid slippage" in result.errors[0]

    @pytest.mark.asyncio
    async def test_validate_pump_fun_buy_invalid_token(self, validator):
        """Test pump.fun buy with invalid token address."""
        result = await validator.validate_pump_fun_buy(
            wallet_balance=2.0, amount=0.1, slippage=10, mint_address="invalid"
        )

        assert result.is_valid is False
        assert len(result.errors) > 0
        assert "Invalid token address format" in result.errors[0]

    @pytest.mark.asyncio
    async def test_validate_pump_fun_buy_small_amount_warning(self, validator):
        """Test pump.fun buy with small amount warning."""
        result = await validator.validate_pump_fun_buy(
            wallet_balance=2.0,
            amount=0.0005,
            slippage=10,
            mint_address="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC mint
        )

        assert result.is_valid is True
        assert len(result.warnings) > 0
        assert "Very small trade amount" in result.warnings[-1]

    @pytest.mark.asyncio
    async def test_validate_pump_fun_sell_success(self, validator):
        """Test successful pump.fun sell validation."""
        result = await validator.validate_pump_fun_sell(
            percentage=50, slippage=10, mint_address="So11111111111111111111111111111111111111112"
        )

        assert result.is_valid is True
        assert len(result.errors) == 0

    @pytest.mark.asyncio
    async def test_validate_pump_fun_sell_invalid_percentage_low(self, validator):
        """Test pump.fun sell with invalid low percentage."""
        result = await validator.validate_pump_fun_sell(
            percentage=0, slippage=10, mint_address="So11111111111111111111111111111111111111112"
        )

        assert result.is_valid is False
        assert len(result.errors) > 0
        assert "Invalid sell percentage" in result.errors[0]

    @pytest.mark.asyncio
    async def test_validate_pump_fun_sell_invalid_percentage_high(self, validator):
        """Test pump.fun sell with invalid high percentage."""
        result = await validator.validate_pump_fun_sell(
            percentage=150, slippage=10, mint_address="So11111111111111111111111111111111111111112"
        )

        assert result.is_valid is False
        assert len(result.errors) > 0
        assert "Invalid sell percentage" in result.errors[0]

    @pytest.mark.asyncio
    async def test_validate_pump_fun_sell_full_position_warning(self, validator):
        """Test pump.fun sell with full position warning."""
        result = await validator.validate_pump_fun_sell(
            percentage=100,
            slippage=10,
            mint_address="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC mint
        )

        assert result.is_valid is True
        assert len(result.warnings) > 0
        assert "Selling entire token position" in result.warnings[-1]

    @pytest.mark.asyncio
    async def test_validate_pump_fun_sell_small_percentage_warning(self, validator):
        """Test pump.fun sell with small percentage warning."""
        result = await validator.validate_pump_fun_sell(
            percentage=5,
            slippage=10,
            mint_address="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC mint
        )

        assert result.is_valid is True
        assert len(result.warnings) > 0
        assert "Selling very small percentage" in result.warnings[-1]

    @pytest.mark.asyncio
    async def test_validate_sol_transfer_success(self, validator):
        """Test successful SOL transfer validation."""
        result = await validator.validate_sol_transfer(
            wallet_balance=2.0, amount=0.5, to_address="11111111111111111111111111111112"
        )

        assert result.is_valid is True
        assert len(result.errors) == 0

    @pytest.mark.asyncio
    async def test_validate_sol_transfer_insufficient_balance(self, validator):
        """Test SOL transfer with insufficient balance."""
        result = await validator.validate_sol_transfer(
            wallet_balance=0.01, amount=0.5, to_address="11111111111111111111111111111112"
        )

        assert result.is_valid is False
        assert len(result.errors) > 0
        assert "Insufficient SOL balance" in result.errors[0]

    @pytest.mark.asyncio
    async def test_validate_sol_transfer_invalid_address(self, validator):
        """Test SOL transfer with invalid destination address."""
        result = await validator.validate_sol_transfer(
            wallet_balance=2.0, amount=0.5, to_address="invalid"
        )

        assert result.is_valid is False
        assert len(result.errors) > 0
        assert "Invalid destination address" in result.errors[0]

    @pytest.mark.asyncio
    async def test_validate_sol_transfer_large_amount_warning(self, validator):
        """Test SOL transfer with large amount warning."""
        with patch("sam.utils.transaction_validator.get_price_service") as mock_get_price:
            mock_price_service = AsyncMock()
            mock_price_service.sol_to_usd.return_value = 250.0
            mock_get_price.return_value = mock_price_service

            result = await validator.validate_sol_transfer(
                wallet_balance=5.0, amount=2.0, to_address="11111111111111111111111111111112"
            )

            assert result.is_valid is True
            assert len(result.warnings) > 0
            assert "Large transfer" in result.warnings[0]

    def test_format_validation_result(self, validator):
        """Test validation result formatting."""
        result = ValidationResult(
            is_valid=False,
            warnings=["Warning 1"],
            errors=["Error 1", "Error 2"],
            suggestions=["Suggestion 1"],
            estimated_cost=0.005,
        )

        formatted = validator.format_validation_result(result)

        assert "❌ **Validation Errors:**" in formatted
        assert "Error 1" in formatted
        assert "Error 2" in formatted
        assert "⚠️  **Warnings:**" in formatted
        assert "Warning 1" in formatted
        assert "💡 **Suggestions:**" in formatted
        assert "Suggestion 1" in formatted
        assert "0.0050 SOL" in formatted

    def test_format_validation_result_success(self, validator):
        """Test validation result formatting for success."""
        result = ValidationResult(is_valid=True, warnings=[], errors=[], suggestions=[])

        formatted = validator.format_validation_result(result)

        assert formatted == ""


class TestGlobalTransactionValidator:
    """Test global transaction validator functions."""

    @pytest.mark.asyncio
    async def test_get_transaction_validator_singleton(self):
        """Test global transaction validator singleton."""
        # Reset global state
        import sam.utils.transaction_validator

        sam.utils.transaction_validator._global_validator = None

        validator1 = await get_transaction_validator()
        validator2 = await get_transaction_validator()

        assert validator1 is validator2
        assert isinstance(validator1, TransactionValidator)

    @pytest.mark.asyncio
    async def test_validate_pump_buy_convenience_function(self):
        """Test validate_pump_buy convenience function."""
        with patch(
            "sam.utils.transaction_validator.get_transaction_validator"
        ) as mock_get_validator:
            mock_validator = AsyncMock()
            mock_validator.validate_pump_fun_buy.return_value = ValidationResult(
                is_valid=True, warnings=[], errors=[], suggestions=[]
            )
            mock_get_validator.return_value = mock_validator

            result = await validate_pump_buy(1.0, 0.5, 10, "mint123")

            assert result.is_valid is True
            mock_validator.validate_pump_fun_buy.assert_called_once_with(1.0, 0.5, 10, "mint123")

    @pytest.mark.asyncio
    async def test_validate_pump_sell_convenience_function(self):
        """Test validate_pump_sell convenience function."""
        with patch(
            "sam.utils.transaction_validator.get_transaction_validator"
        ) as mock_get_validator:
            mock_validator = AsyncMock()
            mock_validator.validate_pump_fun_sell.return_value = ValidationResult(
                is_valid=True, warnings=[], errors=[], suggestions=[]
            )
            mock_get_validator.return_value = mock_validator

            result = await validate_pump_sell(50, 10, "mint123")

            assert result.is_valid is True
            mock_validator.validate_pump_fun_sell.assert_called_once_with(50, 10, "mint123")

    @pytest.mark.asyncio
    async def test_validate_sol_transfer_convenience_function(self):
        """Test validate_sol_transfer convenience function."""
        with patch(
            "sam.utils.transaction_validator.get_transaction_validator"
        ) as mock_get_validator:
            mock_validator = AsyncMock()
            mock_validator.validate_sol_transfer.return_value = ValidationResult(
                is_valid=True, warnings=[], errors=[], suggestions=[]
            )
            mock_get_validator.return_value = mock_validator

            result = await validate_sol_transfer(1.0, 0.5, "address123")

            assert result.is_valid is True
            mock_validator.validate_sol_transfer.assert_called_once_with(1.0, 0.5, "address123")


if __name__ == "__main__":
    pytest.main([__file__])
