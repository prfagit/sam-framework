import keyring
import os
import logging
from typing import Optional, Dict
from cryptography.fernet import Fernet
import base64
import json

logger = logging.getLogger(__name__)


class SecureStorage:
    """Secure storage for sensitive data using system keyring and encryption.

    Improvements:
    - Prefer existing keyring key if it conflicts with env to preserve access.
    - Do not silently swallow keyring sync failures.
    - Maintain an encrypted canary to detect key mismatches early.
    - Track the current key string for safe reloads.
    """
    
    def __init__(self, service_name: str = "sam-framework"):
        self.service_name = service_name
        self.current_key_str: Optional[str] = None
        self.fernet_key = self._select_and_sync_encryption_key()
        self.fernet = Fernet(self.fernet_key) if self.fernet_key else None
        
        if self.fernet:
            try:
                self._ensure_canary()
            except Exception as e:
                logger.warning(f"Encryption canary check failed: {e}")
        
        logger.info(f"Initialized secure storage for service: {service_name}")
    
    def _select_and_sync_encryption_key(self) -> Optional[bytes]:
        """Determine the encryption key with safe precedence and sync.

        Rules:
        - If keyring has a key, prefer it to preserve access to existing ciphertexts.
        - If env has a key but keyring is empty, write env -> keyring (log on failure).
        - If both exist and differ, prefer keyring, set env to keyring, and warn.
        - If neither exists, generate, persist to keyring, and set env.
        """
        env_key = os.getenv("SAM_FERNET_KEY")
        kr_key = None
        try:
            kr_key = keyring.get_password(self.service_name, "encryption_key")
        except Exception as e:
            logger.warning(f"Keyring read failed: {e}")

        # Both present
        if env_key and kr_key:
            if env_key != kr_key:
                logger.warning("SAM_FERNET_KEY mismatch between environment and keyring; using keyring key to preserve access. Update your .env to match.")
                try:
                    os.environ["SAM_FERNET_KEY"] = kr_key
                except Exception:
                    pass
                self.current_key_str = kr_key
                return kr_key.encode()
            # Equal
            self.current_key_str = env_key
            return env_key.encode()

        # Only env present
        if env_key and not kr_key:
            try:
                keyring.set_password(self.service_name, "encryption_key", env_key)
            except Exception as e:
                logger.error(f"Failed to persist SAM_FERNET_KEY to keyring: {e}")
            self.current_key_str = env_key
            return env_key.encode()

        # Only keyring present
        if kr_key and not env_key:
            try:
                os.environ["SAM_FERNET_KEY"] = kr_key
            except Exception:
                pass
            self.current_key_str = kr_key
            return kr_key.encode()

        # Neither present: generate new
        try:
            new_key = Fernet.generate_key()
            new_key_str = new_key.decode()
            try:
                keyring.set_password(self.service_name, "encryption_key", new_key_str)
            except Exception as e:
                logger.error(f"Failed to write new encryption key to keyring: {e}")
            try:
                os.environ["SAM_FERNET_KEY"] = new_key_str
            except Exception:
                pass
            self.current_key_str = new_key_str
            logger.info("Generated new encryption key")
            return new_key
        except Exception as e:
            logger.error(f"Could not generate encryption key: {e}")
            return None

    def _ensure_canary(self) -> None:
        """Ensure an encrypted canary exists and is decryptable with current key.

        Stores a small value encrypted with the active key as 'encryption_canary'.
        If present but undecryptable, logs a clear mismatch warning.
        """
        if not self.fernet:
            return
        try:
            canary = keyring.get_password(self.service_name, "encryption_canary")
        except Exception as e:
            logger.warning(f"Keyring canary read failed: {e}")
            canary = None

        if canary:
            try:
                # base64 decode then decrypt
                data = base64.b64decode(canary.encode())
                _ = self.fernet.decrypt(data)
            except Exception:
                logger.error("Encryption key mismatch detected: cannot decrypt canary with current SAM_FERNET_KEY. Stored secrets may be inaccessible.")
                return
        else:
            # Create canary
            try:
                blob = self.fernet.encrypt(b"canary_v1")
                keyring.set_password(self.service_name, "encryption_canary", base64.b64encode(blob).decode())
            except Exception as e:
                logger.warning(f"Failed to write encryption canary: {e}")
    
    def store_private_key(self, user_id: str, private_key: str) -> bool:
        """Store encrypted private key in keyring."""
        if not self.fernet:
            logger.error("No encryption available for private key storage")
            return False
        
        try:
            # Encrypt the private key
            encrypted_key = self.fernet.encrypt(private_key.encode())
            encrypted_key_str = base64.b64encode(encrypted_key).decode()
            
            # Store in keyring
            keyring.set_password(self.service_name, f"private_key_{user_id}", encrypted_key_str)
            logger.info(f"Stored encrypted private key for user: {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to store private key for {user_id}: {e}")
            return False
    
    def get_private_key(self, user_id: str) -> Optional[str]:
        """Retrieve and decrypt private key from keyring."""
        if not self.fernet:
            logger.error("No decryption available for private key retrieval")
            return None
        
        try:
            # Get encrypted key from keyring
            encrypted_key_str = keyring.get_password(self.service_name, f"private_key_{user_id}")
            if not encrypted_key_str:
                logger.debug(f"No private key found for user: {user_id}")
                return None
            
            # Decrypt the key
            encrypted_key = base64.b64decode(encrypted_key_str.encode())
            private_key = self.fernet.decrypt(encrypted_key).decode()
            
            logger.debug(f"Retrieved private key for user: {user_id}")
            return private_key
            
        except Exception as e:
            logger.error(f"Failed to retrieve private key for {user_id}: {e}")
            return None
    
    def delete_private_key(self, user_id: str) -> bool:
        """Delete private key from keyring."""
        try:
            keyring.delete_password(self.service_name, f"private_key_{user_id}")
            logger.info(f"Deleted private key for user: {user_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete private key for {user_id}: {e}")
            return False
    
    def store_api_key(self, service: str, api_key: str) -> bool:
        """Store API key in keyring."""
        try:
            keyring.set_password(self.service_name, f"api_key_{service}", api_key)
            logger.info(f"Stored API key for service: {service}")
            return True
        except Exception as e:
            logger.error(f"Failed to store API key for {service}: {e}")
            return False
    
    def get_api_key(self, service: str) -> Optional[str]:
        """Retrieve API key from keyring."""
        try:
            api_key = keyring.get_password(self.service_name, f"api_key_{service}")
            if api_key:
                logger.debug(f"Retrieved API key for service: {service}")
                return api_key
            else:
                logger.debug(f"No API key found for service: {service}")
                return None
        except Exception as e:
            logger.error(f"Failed to retrieve API key for {service}: {e}")
            return None
    
    def store_wallet_config(self, user_id: str, config: Dict) -> bool:
        """Store wallet configuration securely."""
        if not self.fernet:
            logger.error("No encryption available for wallet config storage")
            return False
        
        try:
            # Encrypt the configuration
            config_json = json.dumps(config)
            encrypted_config = self.fernet.encrypt(config_json.encode())
            encrypted_config_str = base64.b64encode(encrypted_config).decode()
            
            # Store in keyring
            keyring.set_password(self.service_name, f"wallet_config_{user_id}", encrypted_config_str)
            logger.info(f"Stored encrypted wallet config for user: {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to store wallet config for {user_id}: {e}")
            return False
    
    def get_wallet_config(self, user_id: str) -> Optional[Dict]:
        """Retrieve and decrypt wallet configuration."""
        if not self.fernet:
            logger.error("No decryption available for wallet config retrieval")
            return None
        
        try:
            # Get encrypted config from keyring
            encrypted_config_str = keyring.get_password(self.service_name, f"wallet_config_{user_id}")
            if not encrypted_config_str:
                logger.debug(f"No wallet config found for user: {user_id}")
                return None
            
            # Decrypt the config
            encrypted_config = base64.b64decode(encrypted_config_str.encode())
            config_json = self.fernet.decrypt(encrypted_config).decode()
            config = json.loads(config_json)
            
            logger.debug(f"Retrieved wallet config for user: {user_id}")
            return config
            
        except Exception as e:
            logger.error(f"Failed to retrieve wallet config for {user_id}: {e}")
            return None
    
    def list_stored_users(self) -> list[str]:
        """List users with stored private keys."""
        # Note: keyring doesn't provide a way to list all keys
        # This would need to be implemented differently for each keyring backend
        # For now, return empty list and log warning
        logger.warning("Listing stored users is not supported by keyring interface")
        return []
    
    def test_keyring_access(self) -> Dict[str, bool]:
        """Test keyring access and return status."""
        results = {
            "keyring_available": False,
            "can_store": False,
            "can_retrieve": False,
            "encryption_available": bool(self.fernet)
        }
        
        try:
            # Test storing a value
            test_key = "test_access"
            test_value = "test_value_123"
            
            keyring.set_password(self.service_name, test_key, test_value)
            results["can_store"] = True
            
            # Test retrieving the value
            retrieved = keyring.get_password(self.service_name, test_key)
            results["can_retrieve"] = (retrieved == test_value)
            
            # Clean up test data
            try:
                keyring.delete_password(self.service_name, test_key)
            except Exception:
                pass  # Ignore cleanup errors
                
            results["keyring_available"] = True
            
        except Exception as e:
            logger.warning(f"Keyring test failed: {e}")
        
        return results


# Global secure storage instance
_secure_storage: Optional[SecureStorage] = None


def get_secure_storage() -> SecureStorage:
    """Get the global secure storage instance."""
    global _secure_storage
    # If env key changed since last use, recreate to avoid stale Fernet
    env_key = os.getenv("SAM_FERNET_KEY")
    if _secure_storage is None:
        _secure_storage = SecureStorage()
    else:
        try:
            if getattr(_secure_storage, "current_key_str", None) != env_key and env_key is not None:
                logger.info("SAM_FERNET_KEY changed in environment; reinitializing secure storage")
                _secure_storage = SecureStorage()
        except Exception:
            # Best-effort safeguard
            _secure_storage = SecureStorage()
    return _secure_storage


def store_private_key(user_id: str, private_key: str) -> bool:
    """Convenience function to store private key."""
    return get_secure_storage().store_private_key(user_id, private_key)


def get_private_key(user_id: str) -> Optional[str]:
    """Convenience function to get private key."""
    return get_secure_storage().get_private_key(user_id)


def store_api_key(service: str, api_key: str) -> bool:
    """Convenience function to store API key."""
    return get_secure_storage().store_api_key(service, api_key)


def get_api_key(service: str) -> Optional[str]:
    """Convenience function to get API key."""
    return get_secure_storage().get_api_key(service)
