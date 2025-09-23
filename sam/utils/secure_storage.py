import base64
import hashlib
import json
import logging
import os
import threading
from pathlib import Path
from typing import Dict, Optional, Any

import keyring
from cryptography.fernet import Fernet
from importlib.metadata import entry_points

logger = logging.getLogger(__name__)


class EncryptedFileVault:
    """Encrypted fallback persistence for secrets when keyring is unavailable."""

    def __init__(self, path: Optional[str] = None) -> None:
        default_path = Path(os.getenv("SAM_SECURE_STORE_PATH", ".sam/secure_store.json"))
        self.path = Path(path).expanduser() if path else default_path.expanduser()
        self._lock = threading.Lock()
        self._data: Dict[str, str] = {}
        self._index: Dict[str, Dict[str, str]] = {}
        self._meta: Dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
            if not isinstance(payload, dict):
                return
            secrets = payload.get("secrets")
            if isinstance(secrets, dict):
                self._data = {str(k): str(v) for k, v in secrets.items()}
            index = payload.get("index")
            if isinstance(index, dict):
                self._index = {
                    str(k): {"source": str(v.get("source", "fallback")), "kind": str(v.get("kind", "fernet_b64"))}
                    for k, v in index.items()
                    if isinstance(v, dict)
                }
            else:
                # Backfill index with available secrets assuming fallback origin
                self._index = {
                    key: {"source": "fallback", "kind": "fernet_b64"}
                    for key in self._data.keys()
                }
            meta = payload.get("meta")
            if isinstance(meta, dict):
                self._meta = {str(k): str(v) for k, v in meta.items() if isinstance(v, (str, int, float))}
        except Exception as exc:
            logger.warning("Failed to load secure store fallback %s: %s", self.path, exc)

    def _dump(self) -> None:
        payload = {
            "version": 2,
            "secrets": self._data,
            "index": self._index,
            "meta": self._meta,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".tmp")
        try:
            with tmp_path.open("w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, sort_keys=True)
            os.replace(tmp_path, self.path)
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
        except Exception as exc:
            logger.error("Failed to persist secure store fallback %s: %s", self.path, exc)
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except Exception:
                pass
            raise

    def store_cipher(self, key: str, value: str, *, source: str, kind: str) -> bool:
        with self._lock:
            self._data[key] = value
            self._index[key] = {"source": source, "kind": kind}
            try:
                self._dump()
                logger.info("Stored secret '%s' via encrypted fallback vault", key)
                return True
            except Exception:
                self._data.pop(key, None)
                self._index.pop(key, None)
                return False

    def record_key(self, key: str, *, source: str, kind: str) -> None:
        with self._lock:
            entry = self._index.get(key, {}).copy()
            entry["source"] = source
            entry["kind"] = kind
            self._index[key] = entry
            try:
                self._dump()
            except Exception as exc:
                logger.debug("Failed to persist index update for %s: %s", key, exc)

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            return self._data.get(key)

    def delete(self, key: str) -> bool:
        with self._lock:
            removed = key in self._data or key in self._index
            self._data.pop(key, None)
            self._index.pop(key, None)
            if not removed:
                return False
            try:
                self._dump()
                return True
            except Exception as exc:
                logger.error("Failed to update fallback vault while deleting %s: %s", key, exc)
                return False

    def list_index(self) -> Dict[str, Dict[str, str]]:
        with self._lock:
            return {k: v.copy() for k, v in self._index.items()}

    def iter_secrets(self):
        with self._lock:
            for key, value in self._data.items():
                yield key, value

    def has_fallback_entries(self) -> bool:
        with self._lock:
            return bool(self._data)

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self._meta[key] = value
            try:
                self._dump()
            except Exception as exc:
                logger.debug("Failed to persist vault metadata %s: %s", key, exc)

    def get_meta(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._lock:
            return self._meta.get(key, default)

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
        self.fernet = self._create_fernet(self.fernet_key)
        self._fallback_store = EncryptedFileVault()

        if self.fernet_key and not self._fallback_store.get_meta("key_fingerprint"):
            fingerprint = hashlib.sha256(self.fernet_key).hexdigest()[:16]
            self._fallback_store.set_meta("key_fingerprint", fingerprint)

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
                logger.warning(
                    "SAM_FERNET_KEY mismatch between environment and keyring; using keyring key to preserve access. Update your .env to match."
                )
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
        return self._generate_and_store_new_key()

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
                logger.error(
                    "Encryption key mismatch detected: cannot decrypt canary with current SAM_FERNET_KEY. Stored secrets may be inaccessible."
                )
                return
        else:
            # Create canary
            try:
                blob = self.fernet.encrypt(b"canary_v1")
                keyring.set_password(
                    self.service_name, "encryption_canary", base64.b64encode(blob).decode()
                )
            except Exception as e:
                logger.warning(f"Failed to write encryption canary: {e}")

    def _store_in_fallback(self, key: str, value: str) -> bool:
        try:
            stored = self._fallback_store.store_cipher(
                key, value, source="fallback", kind="fernet_b64"
            )
            if stored:
                logger.warning(
                    "Stored secret '%s' in encrypted fallback vault; system keyring unavailable",
                    key,
                )
            return stored
        except Exception as exc:
            logger.error("Failed to write fallback secret %s: %s", key, exc)
            return False

    def _generate_and_store_new_key(self) -> Optional[bytes]:
        try:
            new_key = Fernet.generate_key()
            new_key_str = new_key.decode()
            try:
                keyring.set_password(self.service_name, "encryption_key", new_key_str)
            except Exception as exc:
                logger.error(f"Failed to write new encryption key to keyring: {exc}")
            try:
                os.environ["SAM_FERNET_KEY"] = new_key_str
            except Exception:
                pass
            self.current_key_str = new_key_str
            logger.info("Generated new encryption key")
            return new_key
        except Exception as exc:
            logger.error(f"Could not generate encryption key: {exc}")
            return None

    def _create_fernet(self, key: Optional[bytes]) -> Optional[Fernet]:
        if not key:
            return None
        try:
            return Fernet(key)
        except ValueError:
            logger.error("Invalid SAM_FERNET_KEY detected; generating new key")
            regenerated = self._generate_and_store_new_key()
            if regenerated is None:
                return None
            self.fernet_key = regenerated
            try:
                return Fernet(regenerated)
            except ValueError as exc:
                logger.error(f"Regenerated SAM_FERNET_KEY is invalid: {exc}")
                return None

    def _encrypt_text(self, value: str) -> Optional[str]:
        if not self.fernet:
            return None
        try:
            blob = self.fernet.encrypt(value.encode())
            return base64.b64encode(blob).decode()
        except Exception as exc:
            logger.error("Failed to encrypt value for fallback storage: %s", exc)
            return None

    def _decrypt_text(self, value: str) -> Optional[str]:
        if not self.fernet:
            return None
        try:
            blob = base64.b64decode(value.encode())
            return self.fernet.decrypt(blob).decode()
        except Exception as exc:
            logger.error("Failed to decrypt fallback secret: %s", exc)
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
            self._fallback_store.record_key(
                f"private_key_{user_id}", source="keyring", kind="fernet_b64"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to store private key for {user_id}: {e}")
            return self._store_in_fallback(f"private_key_{user_id}", encrypted_key_str)

    def get_private_key(self, user_id: str) -> Optional[str]:
        """Retrieve and decrypt private key from keyring."""
        if not self.fernet:
            logger.error("No decryption available for private key retrieval")
            return None

        encrypted_key_str: Optional[str] = None

        try:
            encrypted_key_str = keyring.get_password(
                self.service_name, f"private_key_{user_id}"
            )
        except Exception as e:
            logger.error(f"Failed to retrieve private key via keyring for {user_id}: {e}")

            if not encrypted_key_str:
                encrypted_key_str = self._fallback_store.get(f"private_key_{user_id}")
                if not encrypted_key_str:
                    logger.debug(f"No private key found for user: {user_id}")
                    return None
                self._fallback_store.record_key(
                    f"private_key_{user_id}", source="fallback", kind="fernet_b64"
                )
                logger.warning(
                    "Using encrypted fallback vault for private key '%s'; restore system keyring to migrate secrets",
                    user_id,
                )

        try:
            encrypted_key = base64.b64decode(encrypted_key_str.encode())
            private_key = self.fernet.decrypt(encrypted_key).decode()
            logger.debug(f"Retrieved private key for user: {user_id}")
            return private_key
        except Exception as exc:
            logger.error(f"Failed to decrypt private key for {user_id}: {exc}")
            return None

    def delete_private_key(self, user_id: str) -> bool:
        """Delete private key from keyring."""
        try:
            keyring.delete_password(self.service_name, f"private_key_{user_id}")
            logger.info(f"Deleted private key for user: {user_id}")
            self._fallback_store.delete(f"private_key_{user_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete private key for {user_id}: {e}")
            if self._fallback_store.delete(f"private_key_{user_id}"):
                logger.info(f"Deleted fallback private key for user: {user_id}")
                return True
            return False

    def store_api_key(self, service: str, api_key: str) -> bool:
        """Store API key in keyring."""
        try:
            keyring.set_password(self.service_name, f"api_key_{service}", api_key)
            logger.info(f"Stored API key for service: {service}")
            self._fallback_store.record_key(
                f"api_key_{service}", source="keyring", kind="plaintext"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to store API key for {service}: {e}")
            encrypted_value = self._encrypt_text(api_key)
            if encrypted_value is None:
                return False
            return self._store_in_fallback(f"api_key_{service}", encrypted_value)

    def get_api_key(self, service: str) -> Optional[str]:
        """Retrieve API key from keyring."""
        try:
            api_key = keyring.get_password(self.service_name, f"api_key_{service}")
            if api_key:
                logger.debug(f"Retrieved API key for service: {service}")
                return api_key
        except Exception as e:
            logger.error(f"Failed to retrieve API key for {service}: {e}")
        fallback_val = self._fallback_store.get(f"api_key_{service}")
        if fallback_val:
            decrypted = self._decrypt_text(fallback_val)
            if decrypted:
                self._fallback_store.record_key(
                    f"api_key_{service}", source="fallback", kind="fernet_b64"
                )
                logger.warning(
                    "Using encrypted fallback vault for API key '%s'; restore system keyring to migrate secrets",
                    service,
                )
                logger.debug(f"Retrieved API key for service: {service} via fallback store")
                return decrypted
        logger.debug(f"No API key found for service: {service}")
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
            keyring.set_password(
                self.service_name, f"wallet_config_{user_id}", encrypted_config_str
            )
            logger.info(f"Stored encrypted wallet config for user: {user_id}")
            self._fallback_store.record_key(
                f"wallet_config_{user_id}", source="keyring", kind="fernet_b64"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to store wallet config for {user_id}: {e}")
            return self._store_in_fallback(
                f"wallet_config_{user_id}", encrypted_config_str
            )

    def get_wallet_config(self, user_id: str) -> Optional[Dict]:
        """Retrieve and decrypt wallet configuration."""
        if not self.fernet:
            logger.error("No decryption available for wallet config retrieval")
            return None

        try:
            # Get encrypted config from keyring
            encrypted_config_str = keyring.get_password(
                self.service_name, f"wallet_config_{user_id}"
            )
            if not encrypted_config_str:
                encrypted_config_str = self._fallback_store.get(f"wallet_config_{user_id}")
                if not encrypted_config_str:
                    logger.debug(f"No wallet config found for user: {user_id}")
                    return None
                self._fallback_store.record_key(
                    f"wallet_config_{user_id}", source="fallback", kind="fernet_b64"
                )
                logger.warning(
                    "Using encrypted fallback vault for wallet config '%s'; restore system keyring to migrate secrets",
                    user_id,
                )

            # Decrypt the config
            encrypted_config = base64.b64decode(encrypted_config_str.encode())
            config_json = self.fernet.decrypt(encrypted_config).decode()
            config = json.loads(config_json)

            logger.debug(f"Retrieved wallet config for user: {user_id}")
            return config

        except Exception as e:
            logger.error(f"Failed to retrieve wallet config for {user_id}: {e}")
            try:
                encrypted_config_str = self._fallback_store.get(f"wallet_config_{user_id}")
                if not encrypted_config_str:
                    return None
                encrypted_config = base64.b64decode(encrypted_config_str.encode())
                config_json = self.fernet.decrypt(encrypted_config).decode()
                return json.loads(config_json)
            except Exception:
                return None

    def list_stored_users(self) -> list[str]:
        """List users with stored private keys."""
        # Note: keyring doesn't provide a way to list all keys
        # This would need to be implemented differently for each keyring backend
        # For now, return empty list and log warning
        logger.warning("Listing stored users is not supported by keyring interface")
        return []

    def rotate_encryption_key(self, new_key: Optional[str] = None) -> Dict[str, Any]:
        """Rotate the Fernet encryption key and re-encrypt tracked secrets."""
        if not self.fernet:
            logger.error("Cannot rotate encryption key: Fernet not initialized")
            return {"success": False, "error": "fernet_unavailable"}

        if new_key:
            new_key_str = new_key.strip()
            try:
                new_key_bytes = new_key_str.encode()
                new_fernet = Fernet(new_key_bytes)
            except (ValueError, TypeError) as exc:
                logger.error(f"Provided SAM_FERNET_KEY is invalid: {exc}")
                return {"success": False, "error": "invalid_key"}
        else:
            new_key_bytes = Fernet.generate_key()
            new_key_str = new_key_bytes.decode()
            new_fernet = Fernet(new_key_bytes)

        index = self._fallback_store.list_index()
        rotated: list[str] = []
        failures: list[str] = []
        fallback_promoted: list[str] = []

        for key_name, meta in index.items():
            kind = meta.get("kind", "fernet_b64")
            if kind != "fernet_b64":
                continue

            source = meta.get("source", "keyring")
            ciphertext: Optional[str] = None
            keyring_failed = False

            if source in {"keyring", "both"}:
                try:
                    ciphertext = keyring.get_password(self.service_name, key_name)
                except Exception as exc:
                    logger.warning(
                        f"Keyring read failed for {key_name} during rotation: {exc}"
                    )
                    keyring_failed = True

            if not ciphertext:
                fallback_cipher = self._fallback_store.get(key_name)
                if fallback_cipher:
                    ciphertext = fallback_cipher
                    source = "fallback"

            if not ciphertext:
                continue

            try:
                plaintext = self.fernet.decrypt(base64.b64decode(ciphertext.encode()))
            except Exception as exc:
                logger.error(f"Failed to decrypt {key_name} during rotation: {exc}")
                failures.append(key_name)
                continue

            new_blob = base64.b64encode(new_fernet.encrypt(plaintext)).decode()

            write_failure = False

            if meta.get("source", "keyring") in {"keyring", "both"} and not keyring_failed:
                try:
                    keyring.set_password(self.service_name, key_name, new_blob)
                except Exception as exc:
                    logger.error(f"Failed to update keyring secret {key_name}: {exc}")
                    write_failure = True
                    keyring_failed = True

            if keyring_failed or self._fallback_store.get(key_name) is not None:
                if not self._fallback_store.store_cipher(
                    key_name, new_blob, source="fallback", kind="fernet_b64"
                ):
                    write_failure = True
                else:
                    fallback_promoted.append(key_name)

            if write_failure:
                failures.append(key_name)
                continue

            rotated.append(key_name)

        try:
            keyring.set_password(self.service_name, "encryption_key", new_key_str)
        except Exception as exc:
            logger.error(f"Failed to write rotated SAM_FERNET_KEY to keyring: {exc}")
            return {"success": False, "error": "keyring_write_failed", "failures": failures}

        try:
            os.environ["SAM_FERNET_KEY"] = new_key_str
        except Exception:
            pass

        self.current_key_str = new_key_str
        self.fernet_key = new_key_bytes
        self.fernet = new_fernet

        fingerprint = hashlib.sha256(new_key_bytes).hexdigest()[:16]
        self._fallback_store.set_meta("key_fingerprint", fingerprint)

        try:
            self._ensure_canary()
        except Exception as exc:
            logger.warning(f"Failed to refresh encryption canary after rotation: {exc}")

        return {
            "success": not failures,
            "failures": failures,
            "rotated": rotated,
            "fallback_promoted": fallback_promoted,
            "fingerprint": fingerprint,
        }

    def test_keyring_access(self) -> Dict[str, bool]:
        """Test keyring access and return status."""
        results = {
            "keyring_available": False,
            "can_store": False,
            "can_retrieve": False,
            "encryption_available": bool(self.fernet),
        }

        try:
            # Test storing a value
            test_key = "test_access"
            test_value = "test_value_123"

            keyring.set_password(self.service_name, test_key, test_value)
            results["can_store"] = True

            # Test retrieving the value
            retrieved = keyring.get_password(self.service_name, test_key)
            results["can_retrieve"] = retrieved == test_value

            # Clean up test data
            try:
                keyring.delete_password(self.service_name, test_key)
            except Exception:
                pass  # Ignore cleanup errors

            results["keyring_available"] = True

        except Exception as e:
            logger.warning(f"Keyring test failed: {e}")

        return results

    def diagnostics(self) -> Dict[str, Any]:
        """Return diagnostic information for health checks."""
        index = self._fallback_store.list_index()
        fallback_keys = [k for k, meta in index.items() if meta.get("source") == "fallback"]
        tracked = len(index)
        stale_keys: list[str] = []

        if self.fernet:
            for key, cipher in self._fallback_store.iter_secrets():
                meta = index.get(key, {})
                if meta.get("kind", "fernet_b64") != "fernet_b64":
                    continue
                try:
                    payload = base64.b64decode(cipher.encode())
                    self.fernet.decrypt(payload)
                except Exception:
                    stale_keys.append(key)

        fingerprint = self._fallback_store.get_meta("key_fingerprint")
        current_fp = (
            hashlib.sha256(self.fernet_key).hexdigest()[:16]
            if self.fernet_key is not None
            else None
        )
        mismatch = bool(fingerprint and current_fp and fingerprint != current_fp)
        if mismatch:
            stale_keys = list({*stale_keys, *fallback_keys})

        return {
            "fallback_active": self._fallback_store.has_fallback_entries(),
            "fallback_path": str(self._fallback_store.path),
            "tracked_keys": tracked,
            "fallback_keys": fallback_keys,
            "stale_keys": stale_keys,
            "stale_cipher_blobs": len(stale_keys),
            "fingerprint_mismatch": mismatch,
        }


# Global secure storage instance
_secure_storage: Optional[SecureStorage] = None


def get_secure_storage() -> SecureStorage:
    """Get the global secure storage instance."""
    global _secure_storage
    # If env key changed since last use, recreate to avoid stale Fernet
    env_key = os.getenv("SAM_FERNET_KEY")
    if _secure_storage is None:
        # Try plugin backend first
        try:
            eps = entry_points(group="sam.secure_storage")  # type: ignore[arg-type]
            for ep in eps:
                # We only support a single secure storage plugin; pick the first
                try:
                    factory = ep.load()
                    inst = factory()  # expected to return SecureStorage-like object
                    _secure_storage = inst if inst is not None else SecureStorage()
                    logger.info(f"Loaded secure storage via plugin: {ep.name}")
                    break
                except Exception as e:
                    logger.warning(f"Failed loading secure storage plugin {ep.name}: {e}")
            if _secure_storage is None:
                _secure_storage = SecureStorage()
        except Exception:
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
