import pytest
from sam.core.memory import MemoryManager
import tempfile
import os


@pytest.mark.asyncio
async def test_memory_roundtrip():
    """Test saving and loading session messages."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "test.db")
        memory = MemoryManager(db_path)
        await memory.initialize()

        # Test data
        session_id = "test_session"
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]

        # Save and load
        await memory.save_session(session_id, messages)
        loaded_messages = await memory.load_session(session_id)

        assert loaded_messages == messages


@pytest.mark.asyncio
async def test_memory_empty_session():
    """Test loading non-existent session."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "test.db")
        memory = MemoryManager(db_path)
        await memory.initialize()

        loaded_messages = await memory.load_session("non_existent")
        assert loaded_messages == []


@pytest.mark.asyncio
async def test_user_preferences():
    """Test saving and loading user preferences."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "test.db")
        memory = MemoryManager(db_path)
        await memory.initialize()

        # Save preference
        await memory.save_user_preference("user1", "risk_level", "low")

        # Load preference
        value = await memory.get_user_preference("user1", "risk_level")
        assert value == "low"

        # Load non-existent preference
        value = await memory.get_user_preference("user1", "non_existent")
        assert value is None


@pytest.mark.asyncio
async def test_trade_history():
    """Test saving and loading trade history."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "test.db")
        memory = MemoryManager(db_path)
        await memory.initialize()

        # Save trade
        await memory.save_trade_history("user1", "token123", "buy", 0.5)

        # Load trades
        trades = await memory.get_trade_history("user1")
        assert len(trades) == 1
        assert trades[0]["action"] == "buy"
        assert trades[0]["amount"] == 0.5


@pytest.mark.asyncio
async def test_secure_data_storage():
    """Test secure data storage and retrieval."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = os.path.join(temp_dir, "test.db")
        memory = MemoryManager(db_path)
        await memory.initialize()

        # Store secure data
        await memory.store_secure_data("user1", "encrypted_key_123", "wallet_address_123")

        # Retrieve secure data
        data = await memory.get_secure_data("user1")
        assert data is not None
        assert data["encrypted_private_key"] == "encrypted_key_123"
        assert data["wallet_address"] == "wallet_address_123"

        # Non-existent user
        data = await memory.get_secure_data("non_existent")
        assert data is None
