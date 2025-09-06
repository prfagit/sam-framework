import pytest
from sam.utils.validators import (
    SolanaAddress,
    TradeAmount,
    SlippageTolerance,
    SessionId,
    SellPercentage,
    validate_tool_input,
)
from pydantic import ValidationError


def test_solana_address_validation():
    """Test Solana address validation."""
    # Valid addresses (mock)
    valid_address = SolanaAddress(address="11111111111111111111111111111112")
    assert len(valid_address.address) >= 32

    # Invalid addresses
    with pytest.raises(ValidationError):
        SolanaAddress(address="too_short")

    with pytest.raises(ValidationError):
        SolanaAddress(address="contains_invalid_chars!")

    with pytest.raises(ValidationError):
        SolanaAddress(address="")


def test_trade_amount_validation():
    """Test trade amount validation."""
    # Valid amounts
    valid_amount = TradeAmount(amount=0.5)
    assert valid_amount.amount == 0.5

    valid_amount = TradeAmount(amount=100.0)
    assert valid_amount.amount == 100.0

    # Invalid amounts
    with pytest.raises(ValidationError):
        TradeAmount(amount=0)  # Must be positive

    with pytest.raises(ValidationError):
        TradeAmount(amount=-1)  # Must be positive

    with pytest.raises(ValidationError):
        TradeAmount(amount=1001)  # Exceeds safety limit


def test_slippage_validation():
    """Test slippage tolerance validation."""
    # Valid slippage
    valid_slippage = SlippageTolerance(slippage=5)
    assert valid_slippage.slippage == 5

    valid_slippage = SlippageTolerance(slippage=0)
    assert valid_slippage.slippage == 0

    # Invalid slippage
    with pytest.raises(ValidationError):
        SlippageTolerance(slippage=-1)  # Too low

    with pytest.raises(ValidationError):
        SlippageTolerance(slippage=51)  # Too high


def test_session_id_validation():
    """Test session ID validation."""
    # Valid session IDs
    valid_session = SessionId(session_id="test_session_123")
    assert valid_session.session_id == "test_session_123"

    valid_session = SessionId(session_id="user-123")
    assert valid_session.session_id == "user-123"

    # Invalid session IDs
    with pytest.raises(ValidationError):
        SessionId(session_id="")  # Empty

    with pytest.raises(ValidationError):
        SessionId(session_id="contains spaces")  # Contains spaces

    with pytest.raises(ValidationError):
        SessionId(session_id="contains@special")  # Invalid characters


def test_tool_input_validation():
    """Test tool input validation."""
    # Valid transfer_sol input
    validated = validate_tool_input(
        "transfer_sol", {"to_address": "11111111111111111111111111111112", "amount": 0.5}
    )
    assert validated["to_address"] == "11111111111111111111111111111112"
    assert validated["amount"] == 0.5

    # Valid pump_fun_buy input
    validated = validate_tool_input(
        "pump_fun_buy",
        {
            "public_key": "11111111111111111111111111111112",
            "mint": "22222222222222222222222222222223",
            "amount": 1.0,
            "slippage": 2,
        },
    )
    assert validated["public_key"] == "11111111111111111111111111111112"
    assert validated["mint"] == "22222222222222222222222222222223"
    assert validated["amount"] == 1.0
    assert validated["slippage"] == 2

    # get_balance (no args needed)
    validated = validate_tool_input("get_balance", {})
    assert validated == {}

    # Unknown tool (should return args as-is with warning)
    validated = validate_tool_input("unknown_tool", {"test": "value"})
    assert validated == {"test": "value"}


def test_sell_percentage_validation():
    """Test sell percentage validation for pump_fun_sell."""
    # Valid percentages
    valid_percentages = [1, 25, 50, 75, 100]
    for pct in valid_percentages:
        validated = SellPercentage(percentage=pct)
        assert validated.percentage == pct

    # Invalid percentages - below range
    with pytest.raises(ValidationError):
        SellPercentage(percentage=0)

    with pytest.raises(ValidationError):
        SellPercentage(percentage=-1)

    # Invalid percentages - above range
    with pytest.raises(ValidationError):
        SellPercentage(percentage=101)

    with pytest.raises(ValidationError):
        SellPercentage(percentage=150)


def test_pump_fun_sell_validation():
    """Test pump_fun_sell tool validation with percentage."""
    # Valid pump_fun_sell with percentage
    result = validate_tool_input(
        "pump_fun_sell",
        {
            "mint": "11111111111111111111111111111112",
            "percentage": 75,
            "slippage": 2,
            "public_key": "11111111111111111111111111111113",
        },
    )
    assert result["mint"] == "11111111111111111111111111111112"
    assert result["percentage"] == 75
    assert result["slippage"] == 2
    assert result["public_key"] == "11111111111111111111111111111113"

    # Test with default percentage
    result = validate_tool_input(
        "pump_fun_sell",
        {
            "mint": "11111111111111111111111111111112",
            "public_key": "11111111111111111111111111111113",
        },
    )
    assert result["percentage"] == 100  # Default value

    # Test with edge case percentages
    result = validate_tool_input(
        "pump_fun_sell",
        {
            "mint": "11111111111111111111111111111112",
            "percentage": 1,  # Minimum
            "public_key": "11111111111111111111111111111113",
        },
    )
    assert result["percentage"] == 1

    result = validate_tool_input(
        "pump_fun_sell",
        {
            "mint": "11111111111111111111111111111112",
            "percentage": 100,  # Maximum
            "public_key": "11111111111111111111111111111113",
        },
    )
    assert result["percentage"] == 100


@pytest.mark.asyncio
async def test_memory_path_edge_case():
    """Test that memory path handling works with bare filenames."""
    from sam.core.memory import MemoryManager
    from sam.utils.connection_pool import cleanup_database_pool
    import tempfile
    import os

    # Clean up any existing connection pools
    await cleanup_database_pool()

    with tempfile.TemporaryDirectory() as temp_dir:
        # Test with bare filename (no directory)
        original_cwd = os.getcwd()
        os.chdir(temp_dir)

        try:
            # This should not raise an exception
            memory = MemoryManager("test.db")
            assert memory.db_path == "test.db"

            # Initialize should work without errors
            await memory.initialize()

            # Database file should exist
            assert os.path.exists("test.db")

            # Clean up after test
            await cleanup_database_pool()
        finally:
            os.chdir(original_cwd)


def test_address_validation_edge_cases():
    """Test Solana address validation edge cases."""
    # Test minimum length
    min_valid = "1" * 32
    validated = SolanaAddress(address=min_valid)
    assert validated.address == min_valid

    # Test maximum length
    max_valid = "1" * 44
    validated = SolanaAddress(address=max_valid)
    assert validated.address == max_valid

    # Test too short
    with pytest.raises(ValidationError):
        SolanaAddress(address="1" * 31)

    # Test too long
    with pytest.raises(ValidationError):
        SolanaAddress(address="1" * 45)

    # Test invalid base58 characters
    with pytest.raises(ValidationError):
        SolanaAddress(address="0" * 32)  # '0' is not valid base58

    with pytest.raises(ValidationError):
        SolanaAddress(address="O" * 32)  # 'O' is not valid base58

    with pytest.raises(ValidationError):
        SolanaAddress(address="I" * 32)  # 'I' is not valid base58
