import keyring
import os
import logging
from typing import Optional, Dict
from cryptography.fernet import Fernet
import base64
import json

logger = logging.getLogger(__name__)


class SecureStorage:
    """Secure storage for sensitive data using system keyring and encryption."""
    
    def __init__(self, service_name: str = "sam-framework"):
        self.service_name = service_name
        self.fernet_key = self._get_or_create_encryption_key()
        self.fernet = Fernet(self.fernet_key) if self.fernet_key else None
        
        logger.info(f"Initialized secure storage for service: {service_name}")
    
    def _get_or_create_encryption_key(self) -> Optional[bytes]:
        """Get encryption key from environment or keyring."""
        # First try environment variable (for compatibility)
        env_key = os.getenv("SAM_FERNET_KEY")
        if env_key:
            try:
                # SAM_FERNET_KEY should already be a base64-encoded string
                key_bytes = env_key.encode('ascii')
                # Also update the keyring to match the environment for consistency
                try:
                    keyring.set_password(self.service_name, "encryption_key", env_key)
                except Exception as e:
                    logger.warning(f"Could not sync environment key to keyring: {e}")
                return key_bytes
            except (UnicodeDecodeError, AttributeError) as e:
                logger.warning(f"Invalid SAM_FERNET_KEY in environment: {e}")
        
        # Try to get key from keyring
        try:
            stored_key = keyring.get_password(self.service_name, "encryption_key")
            if stored_key:
                return stored_key.encode()
        except Exception as e:
            logger.warning(f"Could not retrieve encryption key from keyring: {e}")
        
        # Generate new key and store in keyring only (not in environment)
        try:
            new_key = Fernet.generate_key()
            keyring.set_password(self.service_name, "encryption_key", new_key.decode())
            logger.info("Generated and stored new encryption key in keyring")
            return new_key
        except Exception as e:
            logger.error(f"Could not store encryption key in keyring: {e}")
            return None
    
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
    if _secure_storage is None:
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