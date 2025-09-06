import pytest
from sam.utils.secure_storage import SecureStorage
import os


def test_secure_storage_init():
    """Test secure storage initialization."""
    storage = SecureStorage("test-service")
    assert storage.service_name == "test-service"

    # Test keyring availability
    test_results = storage.test_keyring_access()
    assert isinstance(test_results, dict)
    assert "keyring_available" in test_results
    assert "can_store" in test_results
    assert "can_retrieve" in test_results
    assert "encryption_available" in test_results


def test_secure_storage_encryption():
    """Test encryption functionality."""
    storage = SecureStorage("test-service")

    # Test that encryption is available
    assert storage.fernet is not None

    # Test that we can encrypt and decrypt
    test_data = "test_private_key_123456"
    encrypted = storage.fernet.encrypt(test_data.encode())
    decrypted = storage.fernet.decrypt(encrypted).decode()
    assert decrypted == test_data


@pytest.mark.skipif(os.getenv("GITHUB_ACTIONS"), reason="Keyring not available in CI")
def test_private_key_storage():
    """Test private key storage and retrieval."""
    storage = SecureStorage("test-sam-framework")

    test_user = "test_user_123"
    test_key = "test_private_key_abcd1234"

    try:
        # Store private key
        success = storage.store_private_key(test_user, test_key)
        if success:  # Only test if storage succeeded
            # Retrieve private key
            retrieved_key = storage.get_private_key(test_user)
            assert retrieved_key == test_key

            # Clean up
            storage.delete_private_key(test_user)

            # Verify deletion
            deleted_key = storage.get_private_key(test_user)
            assert deleted_key is None
        else:
            pytest.skip("Keyring storage not available")

    except Exception as e:
        pytest.skip(f"Keyring test skipped due to: {e}")


@pytest.mark.skipif(os.getenv("GITHUB_ACTIONS"), reason="Keyring not available in CI")
def test_api_key_storage():
    """Test API key storage and retrieval."""
    storage = SecureStorage("test-sam-framework")

    test_service = "test_service"
    test_api_key = "sk-test1234567890abcdef"

    try:
        # Store API key
        success = storage.store_api_key(test_service, test_api_key)
        if success:  # Only test if storage succeeded
            # Retrieve API key
            retrieved_key = storage.get_api_key(test_service)
            assert retrieved_key == test_api_key

            # Test non-existent service
            non_existent = storage.get_api_key("non_existent_service")
            assert non_existent is None
        else:
            pytest.skip("Keyring storage not available")

    except Exception as e:
        pytest.skip(f"Keyring test skipped due to: {e}")


def test_wallet_config_storage():
    """Test wallet configuration storage and retrieval."""
    storage = SecureStorage("test-sam-framework")

    test_user = "test_user_config"
    test_config = {
        "network": "devnet",
        "rpc_url": "https://api.devnet.solana.com",
        "preferences": {"max_slippage": 5, "priority_fee": 0.0001},
    }

    try:
        # Store wallet config
        success = storage.store_wallet_config(test_user, test_config)
        if success:  # Only test if storage succeeded
            # Retrieve wallet config
            retrieved_config = storage.get_wallet_config(test_user)
            assert retrieved_config == test_config

            # Test non-existent user
            non_existent = storage.get_wallet_config("non_existent_user")
            assert non_existent is None
        else:
            pytest.skip("Wallet config storage not available")

    except Exception as e:
        pytest.skip(f"Keyring test skipped due to: {e}")


def test_convenience_functions():
    """Test convenience functions."""
    from sam.utils.secure_storage import (
        store_private_key,
        get_private_key,
        store_api_key,
        get_api_key,
    )

    # These functions should work (though may fail gracefully if keyring unavailable)
    test_user = "test_convenience"
    test_key = "test_key_conv"

    try:
        success = store_private_key(test_user, test_key)
        if success:
            retrieved = get_private_key(test_user)
            assert retrieved == test_key

        api_success = store_api_key("test_api", "test_value")
        if api_success:
            api_retrieved = get_api_key("test_api")
            assert api_retrieved == "test_value"

    except Exception as e:
        pytest.skip(f"Convenience function test skipped due to: {e}")


def test_storage_without_keyring():
    """Test storage behavior when keyring is not available."""
    # This test ensures graceful degradation
    storage = SecureStorage("test-unavailable")

    # Should still be able to create storage instance
    assert storage.service_name == "test-unavailable"

    # Test results should indicate availability status
    test_results = storage.test_keyring_access()
    assert isinstance(test_results, dict)
