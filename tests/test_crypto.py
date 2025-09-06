import pytest
import os
from sam.utils.crypto import (
    encrypt_private_key,
    decrypt_private_key,
    generate_encryption_key,
    is_valid_encryption_key,
)


def test_encryption_roundtrip():
    """Test encrypting and decrypting a private key."""
    # Set up encryption key for testing
    test_key = generate_encryption_key()
    os.environ["SAM_FERNET_KEY"] = test_key

    try:
        # Test data
        original_key = "test_private_key_123456789"

        # Encrypt and decrypt
        encrypted = encrypt_private_key(original_key)
        decrypted = decrypt_private_key(encrypted)

        assert decrypted == original_key
        assert encrypted != original_key  # Should be different
    finally:
        # Clean up
        if "SAM_FERNET_KEY" in os.environ:
            del os.environ["SAM_FERNET_KEY"]


def test_encryption_key_validation():
    """Test encryption key validation."""
    # Valid key
    valid_key = generate_encryption_key()
    assert is_valid_encryption_key(valid_key)

    # Invalid keys
    assert not is_valid_encryption_key("invalid_key")
    assert not is_valid_encryption_key("")
    assert not is_valid_encryption_key("too_short")


def test_empty_private_key():
    """Test handling of empty private key."""
    test_key = generate_encryption_key()
    os.environ["SAM_FERNET_KEY"] = test_key

    try:
        with pytest.raises(ValueError):
            encrypt_private_key("")

        with pytest.raises(ValueError):
            decrypt_private_key("")
    finally:
        if "SAM_FERNET_KEY" in os.environ:
            del os.environ["SAM_FERNET_KEY"]


def test_missing_encryption_key():
    """Test behavior when encryption key is missing."""
    # Ensure no key is set
    if "SAM_FERNET_KEY" in os.environ:
        del os.environ["SAM_FERNET_KEY"]

    with pytest.raises(RuntimeError):
        encrypt_private_key("test_key")

    with pytest.raises(RuntimeError):
        decrypt_private_key("encrypted_data")
