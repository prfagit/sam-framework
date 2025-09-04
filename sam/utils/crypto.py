from cryptography.fernet import Fernet
import os
import logging

logger = logging.getLogger(__name__)


def get_fernet() -> Fernet:
    """Get Fernet encryption instance from environment key."""
    key = os.environ.get("SAM_FERNET_KEY")
    if not key:
        raise RuntimeError(
            "SAM_FERNET_KEY not set. Generate one with: "
            "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    
    # Handle both raw bytes and string formats
    if isinstance(key, str):
        key = key.encode()
    
    try:
        return Fernet(key)
    except ValueError as e:
        raise RuntimeError(f"Invalid SAM_FERNET_KEY format: {e}")


def encrypt_private_key(private_key: str) -> str:
    """Encrypt a private key string."""
    if not private_key:
        raise ValueError("Private key cannot be empty")
    
    try:
        fernet = get_fernet()
        encrypted = fernet.encrypt(private_key.encode())
        logger.debug("Private key encrypted successfully")
        return encrypted.decode()
    except Exception as e:
        logger.error(f"Failed to encrypt private key: {e}")
        raise


def decrypt_private_key(encrypted_private_key: str) -> str:
    """Decrypt an encrypted private key."""
    if not encrypted_private_key:
        raise ValueError("Encrypted private key cannot be empty")
    
    try:
        fernet = get_fernet()
        decrypted = fernet.decrypt(encrypted_private_key.encode())
        logger.debug("Private key decrypted successfully")
        return decrypted.decode()
    except Exception as e:
        logger.error(f"Failed to decrypt private key: {e}")
        raise


def generate_encryption_key() -> str:
    """Generate a new Fernet encryption key."""
    return Fernet.generate_key().decode()


def is_valid_encryption_key(key: str) -> bool:
    """Check if a string is a valid Fernet encryption key."""
    try:
        Fernet(key.encode() if isinstance(key, str) else key)
        return True
    except (ValueError, TypeError):
        return False