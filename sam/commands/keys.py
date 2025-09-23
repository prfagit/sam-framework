"""Key management commands for SAM CLI."""

import os
import getpass

from ..config.settings import Settings
from ..utils.secure_storage import get_secure_storage
from ..utils.crypto import encrypt_private_key, generate_encryption_key
from ..utils.env_files import find_env_path, write_env_file


def import_private_key() -> int:
    """Import and securely store a private key using keyring if available."""
    print("🔐 Secure Private Key Import")
    print("This will encrypt and store your private key in the system keyring.")

    try:
        secure_storage = get_secure_storage()
        keyring_test = secure_storage.test_keyring_access()

        if not keyring_test["keyring_available"]:
            print(
                "❌ System keyring is not available. Falling back to environment variable method."
            )
            return import_private_key_legacy()

        print("✅ System keyring is available")

        user_id = input("Enter user ID (or press enter for 'default'): ").strip() or "default"

        existing_key = secure_storage.get_private_key(user_id)
        if existing_key:
            overwrite = (
                input(f"Private key for '{user_id}' already exists. Overwrite? (y/N): ")
                .strip()
                .lower()
            )
            if overwrite != "y":
                print("❌ Import cancelled")
                return 1

        private_key = getpass.getpass("Enter your private key (hidden): ")
        if not private_key.strip():
            print("❌ Private key cannot be empty")
            return 1

        success = secure_storage.store_private_key(user_id, private_key.strip())

        if success:
            print(f"✅ Private key securely stored in system keyring for user: {user_id}")
            test_key = secure_storage.get_private_key(user_id)
            if test_key:
                print("✅ Key retrieval test successful")
            else:
                print("⚠️ Warning: Could not retrieve stored key for verification")
            return 0
        else:
            print("❌ Failed to store private key in keyring")
            return 1

    except Exception as e:
        print(f"❌ Failed to import private key: {e}")
        return 1


def import_private_key_legacy() -> int:
    """Legacy import using environment variables (fallback)."""
    print("🔐 Legacy Private Key Import (Environment Variable)")
    print("This will encrypt and store your private key as an environment variable.")

    if not Settings.SAM_FERNET_KEY:
        print("❌ SAM_FERNET_KEY not set. Generate one securely with:")
        print("sam generate-key")
        return 1

    try:
        private_key = getpass.getpass("Enter your private key (hidden): ")
        if not private_key.strip():
            print("❌ Private key cannot be empty")
            return 1

        encrypted_key = encrypt_private_key(private_key.strip())
        os.environ["SAM_WALLET_PRIVATE_KEY"] = encrypted_key

        print("✅ Private key encrypted and stored for this session")
        print("To make permanent, add this to your .env file:")
        print(f"SAM_WALLET_PRIVATE_KEY={encrypted_key}")
        return 0

    except Exception as e:
        print(f"❌ Failed to import private key: {e}")
        return 1


def generate_key() -> int:
    """Generate a new Fernet encryption key and store it in .env."""
    try:
        key = generate_encryption_key()
        env_path = find_env_path()

        # Update existing or create new .env
        print(f"🔐 Generated new encryption key and updated {env_path}")
        write_env_file(env_path, {"SAM_FERNET_KEY": key})

        os.environ["SAM_FERNET_KEY"] = key
        print("✅ Key generated and configured automatically")
        print("🔒 Key is ready for use. Restart your session to apply changes.")
        return 0

    except Exception as e:
        print(f"❌ Failed to generate key: {e}")
        print("Manual fallback: Add SAM_FERNET_KEY to your .env file")
        return 1


def rotate_key(new_key: str | None = None, *, assume_yes: bool = False) -> int:
    """Rotate SAM_FERNET_KEY and re-encrypt stored secrets."""
    print("🔄 Rotating SAM_FERNET_KEY")

    secure_storage = get_secure_storage()
    if not secure_storage.fernet:
        print("❌ Encryption not initialized; cannot rotate key")
        return 1

    if not assume_yes:
        confirm = input(
            "This will generate a new key and re-encrypt stored secrets. Proceed? (y/N): "
        ).strip().lower()
        if confirm != "y":
            print("❌ Rotation cancelled")
            return 1

    result = secure_storage.rotate_encryption_key(new_key)

    if not result.get("success"):
        failures = ", ".join(result.get("failures", [])) or "unknown error"
        print(f"❌ Rotation failed. Problematic secrets: {failures}")
        return 1

    try:
        env_path = find_env_path()
        write_env_file(env_path, {"SAM_FERNET_KEY": secure_storage.current_key_str or ""})
        print(f"✅ Updated {env_path} with rotated key")
    except Exception as exc:  # pragma: no cover - filesystem edge
        print(f"⚠️  Rotated key generated but failed to update .env automatically: {exc}")

    rotated = len(result.get("rotated", []))
    print(f"🔒 Re-encrypted {rotated} secret{'s' if rotated != 1 else ''}")

    fallback_promoted = result.get("fallback_promoted", [])
    if fallback_promoted:
        print(
            "⚠️  The encrypted fallback vault now holds copies of: "
            + ", ".join(fallback_promoted)
        )
        print("   Restore system keyring access and rerun rotation to migrate them back.")

    stale = result.get("failures", [])
    if stale:
        print("⚠️  Some secrets could not be rotated; check logs for details.")

    fingerprint = result.get("fingerprint")
    if fingerprint:
        print(f"🔏 Active key fingerprint: {fingerprint}")

    print("✅ SAM_FERNET_KEY rotated successfully. Restart agents to apply changes.")
    return 0
