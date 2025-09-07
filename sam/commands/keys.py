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
