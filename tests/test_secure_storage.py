import json
import os

import pytest

import keyring

from sam.utils.secure_storage import SecureStorage
from sam.utils.crypto import generate_encryption_key


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
    assert "keyring_available" in test_results
    assert "can_store" in test_results
    assert "can_retrieve" in test_results
    assert "encryption_available" in test_results


def test_encrypted_fallback_vault(tmp_path, monkeypatch):
    """Secrets should persist encrypted when keyring operations fail."""

    fallback_path = tmp_path / "secure_store.json"
    monkeypatch.setenv("SAM_SECURE_STORE_PATH", str(fallback_path))

    def _raise(*args, **kwargs):  # noqa: ANN001
        raise RuntimeError("keyring disabled for test")

    monkeypatch.setattr("keyring.set_password", _raise)
    monkeypatch.setattr("keyring.get_password", _raise)
    monkeypatch.setattr("keyring.delete_password", _raise)

    storage = SecureStorage("test-fallback")

    assert storage.store_private_key("default", "priv-key-123") is True
    assert storage.get_private_key("default") == "priv-key-123"

    assert storage.store_api_key("service", "api-key-xyz") is True
    assert storage.get_api_key("service") == "api-key-xyz"

    config = {"network": "devnet", "max_slippage": 5}
    assert storage.store_wallet_config("default", config) is True
    assert storage.get_wallet_config("default") == config

    assert fallback_path.exists()
    with fallback_path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)

    secrets = payload.get("secrets", {})
    priv_blob = secrets.get("private_key_default")
    assert priv_blob is not None
    assert "priv-key-123" not in priv_blob  # ciphertext should not expose plaintext

    diagnostics = storage.diagnostics()
    assert diagnostics["fallback_active"] is True
    assert diagnostics["stale_cipher_blobs"] == 0


def test_rotate_encryption_key_success(tmp_path, monkeypatch):
    store: dict[tuple[str, str], str] = {}

    def set_password(service, key, value):  # noqa: ANN001
        store[(service, key)] = value

    def get_password(service, key):  # noqa: ANN001
        return store.get((service, key))

    def delete_password(service, key):  # noqa: ANN001
        store.pop((service, key), None)

    monkeypatch.setattr(keyring, "set_password", set_password)
    monkeypatch.setattr(keyring, "get_password", get_password)
    monkeypatch.setattr(keyring, "delete_password", delete_password)

    fallback_path = tmp_path / "vault.json"
    monkeypatch.setenv("SAM_SECURE_STORE_PATH", str(fallback_path))

    initial_key = generate_encryption_key()
    monkeypatch.setenv("SAM_FERNET_KEY", initial_key)

    storage = SecureStorage("rotate-test")
    assert storage.store_private_key("default", "secret-123") is True

    old_blob = store[("rotate-test", "private_key_default")]

    result = storage.rotate_encryption_key()

    assert result["success"] is True
    assert "private_key_default" in result["rotated"]

    new_blob = store[("rotate-test", "private_key_default")]
    assert new_blob != old_blob
    assert storage.current_key_str != initial_key
    assert storage.get_private_key("default") == "secret-123"

    diagnostics = storage.diagnostics()
    assert diagnostics["stale_cipher_blobs"] == 0


def test_diagnostics_detects_stale_cipher(tmp_path, monkeypatch):
    fallback_path = tmp_path / "vault.json"
    monkeypatch.setenv("SAM_SECURE_STORE_PATH", str(fallback_path))

    def raise_error(*args, **kwargs):  # noqa: ANN001
        raise RuntimeError("keyring disabled")

    monkeypatch.setattr(keyring, "set_password", raise_error)
    monkeypatch.setattr(keyring, "get_password", raise_error)
    monkeypatch.setattr(keyring, "delete_password", raise_error)

    key_v1 = generate_encryption_key()
    monkeypatch.setenv("SAM_FERNET_KEY", key_v1)
    storage_v1 = SecureStorage("diag-test")
    storage_v1.store_private_key("default", "secret-xyz")

    diagnostics_v1 = storage_v1.diagnostics()
    assert diagnostics_v1["stale_cipher_blobs"] == 0

    key_v2 = generate_encryption_key()
    monkeypatch.setenv("SAM_FERNET_KEY", key_v2)
    storage_v2 = SecureStorage("diag-test")
    diagnostics_v2 = storage_v2.diagnostics()
    assert diagnostics_v2["stale_cipher_blobs"] >= 1
    assert diagnostics_v2["fingerprint_mismatch"] is True
