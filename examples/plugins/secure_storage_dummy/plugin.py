"""Dummy secure storage plugin (for demo/testing only).

This plugin replaces the OS keyring + Fernet with an in-memory store.
It is NOT secure and should only be used for tests or demos.

Usage (env):
  export SAM_PLUGINS="examples.plugins.secure_storage_dummy.plugin"
  uv run sam
"""

from __future__ import annotations

from typing import Optional, Dict, Any
import logging

from sam.utils.secure_storage import BaseSecretStore, configure_secure_storage

logger = logging.getLogger(__name__)


class DummySecureStorage(BaseSecretStore):
    def __init__(self):
        self.current_key_str: Optional[str] = None
        self._keys: Dict[str, str] = {}
        self._api: Dict[str, str] = {}
        self._wallet_cfg: Dict[str, Dict] = {}
        logger.warning("Using DummySecureStorage (not secure)")

    def store_private_key(self, user_id: str, private_key: str) -> bool:
        self._keys[user_id] = private_key
        return True

    def get_private_key(self, user_id: str) -> Optional[str]:
        return self._keys.get(user_id)

    def delete_private_key(self, user_id: str) -> bool:
        return self._keys.pop(user_id, None) is not None

    def store_api_key(self, service: str, api_key: str) -> bool:
        self._api[service] = api_key
        return True

    def get_api_key(self, service: str) -> Optional[str]:
        return self._api.get(service)

    def delete_api_key(self, service: str) -> bool:
        return self._api.pop(service, None) is not None

    def store_wallet_config(self, user_id: str, config: Dict[str, Any]) -> bool:
        self._wallet_cfg[user_id] = dict(config)
        return True

    def get_wallet_config(self, user_id: str) -> Optional[Dict[str, Any]]:
        return self._wallet_cfg.get(user_id)

    def test_keyring_access(self) -> Dict[str, bool]:
        return {
            "keyring_available": True,
            "can_store": True,
            "can_retrieve": True,
            "encryption_available": True,
        }

    def rotate_encryption_key(self, new_key: Optional[str] = None) -> Dict[str, Any]:
        if new_key:
            self.current_key_str = new_key
        else:
            self.current_key_str = "dummy"
        return {"success": True, "rotated": list(self._keys.keys()), "fingerprint": "dummy"}


def register(registry=None, agent=None):
    # This plugin uses a different entry point group (sam.secure_storage) loaded by get_secure_storage
    # The 'register' function exists to support SAM_PLUGINS env discovery as well.
    configure_secure_storage(DummySecureStorage())
    return None


def create_storage():
    return DummySecureStorage()
