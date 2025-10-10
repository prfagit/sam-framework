"""Configuration management commands."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from dotenv import dotenv_values

from ..config.profile_store import PROFILE_KEYS, get_profile_store
from ..config.settings import API_KEY_ALIASES, PRIVATE_KEY_ALIASES, Settings
from ..utils.cli_helpers import CLIFormatter
from ..utils.env_files import find_env_path, write_env_file
from ..utils.secure_storage import get_secure_storage, sync_stored_api_key


def migrate_env_to_profile() -> int:
    """Migrate legacy .env configuration into the profile store and secure storage."""

    env_path = find_env_path()
    if not os.path.exists(env_path):
        print(CLIFormatter.info("No .env file found; nothing to migrate."))
        return 0

    env_values = dotenv_values(env_path)

    if not env_values:
        print(CLIFormatter.info(".env file is empty; nothing to migrate."))
        return 0

    profile_store = get_profile_store()
    storage = get_secure_storage()

    profile_updates: Dict[str, Any] = {}
    migrated_api = 0
    migrated_private = 0

    brave_present = None

    for key, value in env_values.items():
        if value in (None, ""):
            continue
        # At this point, value is guaranteed to be a non-empty string
        assert value is not None and value != "", (
            "value should be non-None and non-empty after filter"
        )

        if key in API_KEY_ALIASES:
            try:
                storage.store_api_key(API_KEY_ALIASES[key], value)
                migrated_api += 1
                if API_KEY_ALIASES[key] == "brave_api_key":
                    brave_present = True
            except Exception as exc:
                print(CLIFormatter.error(f"Failed to store API key for {key}: {exc}"))
            continue
        if key in PRIVATE_KEY_ALIASES:
            try:
                storage.store_private_key(PRIVATE_KEY_ALIASES[key], value)
                migrated_private += 1
            except Exception as exc:
                print(CLIFormatter.error(f"Failed to store secret for {key}: {exc}"))
            continue
        if key in PROFILE_KEYS:
            profile_updates[key] = value

    if brave_present is None:
        try:
            brave_present = bool(storage.get_api_key("brave_api_key"))
        except Exception:
            brave_present = None
    if brave_present is not None:
        # ProfileStore accepts Dict[str, Any], so bool is fine
        profile_updates["BRAVE_API_KEY_PRESENT"] = brave_present

    if profile_updates:
        profile_store.update(profile_updates)

    # Filter out None and empty values for remaining_env
    remaining_env: Dict[str, str] = {
        key: value
        for key, value in env_values.items()
        if key not in PROFILE_KEYS
        and key not in API_KEY_ALIASES
        and key not in PRIVATE_KEY_ALIASES
        and value not in (None, "")
        and isinstance(value, str)  # Type guard to ensure str
    }

    write_env_file(env_path, remaining_env)

    Settings.refresh_from_env()

    print(CLIFormatter.success("Migration complete!"))
    print(
        CLIFormatter.info(
            f"Stored {migrated_api} API key(s) and {migrated_private} private secret(s) in secure storage."
        )
    )
    if profile_updates:
        print(
            CLIFormatter.info(
                f"Persisted {len(profile_updates)} configuration value(s) to the profile store."
            )
        )

    return 0


def show_profile(include_defaults: bool = True) -> int:
    """Display profile configuration and secret status."""

    profile_store = get_profile_store()
    storage = get_secure_storage()

    data = profile_store.data
    Settings.refresh_from_env()

    print(CLIFormatter.header("Profile Settings"))
    for key in sorted(PROFILE_KEYS):
        if hasattr(Settings, key):
            value = getattr(Settings, key)
        else:
            value = data.get(key)
        if value is None and not include_defaults:
            continue
        print(f"  {key} = {value}")

    print()
    print(CLIFormatter.header("Stored Secrets"))
    for env_key, alias in sorted(API_KEY_ALIASES.items()):
        try:
            present = bool(storage.get_api_key(alias))
        except Exception:
            present = False
        status = "present" if present else "missing"
        print(f"  {env_key}: {status}")

    for env_key, alias in sorted(PRIVATE_KEY_ALIASES.items()):
        try:
            present = bool(storage.get_private_key(alias))
        except Exception:
            present = False
        status = "present" if present else "missing"
        print(f"  {env_key}: {status}")

    return 0


def edit_profile(
    key: str, value: Optional[str], *, clear: bool = False, secret: bool = False
) -> int:
    """Edit a configuration value or secret."""

    key_upper = key.upper()
    profile_store = get_profile_store()
    storage = get_secure_storage()

    if secret or key_upper in API_KEY_ALIASES or key_upper in PRIVATE_KEY_ALIASES:
        target = key_upper
        if target in API_KEY_ALIASES:
            if clear:
                storage.delete_api_key(API_KEY_ALIASES[target])
                if target == "BRAVE_API_KEY":
                    profile_store.update({"BRAVE_API_KEY_PRESENT": False})
                print(CLIFormatter.success(f"Cleared secret for {target}"))
                return 0
            if not value:
                print(CLIFormatter.error("Provide a value to set this secret."))
                return 1
            storage.store_api_key(API_KEY_ALIASES[target], value)
            if target == "BRAVE_API_KEY":
                profile_store.update({"BRAVE_API_KEY_PRESENT": True})
            print(CLIFormatter.success(f"Updated secret for {target}"))
            return 0
        if target in PRIVATE_KEY_ALIASES:
            if clear:
                storage.delete_private_key(PRIVATE_KEY_ALIASES[target])
                print(CLIFormatter.success(f"Cleared private key for {target}"))
                return 0
            if not value:
                print(CLIFormatter.error("Provide a value to set this private key."))
                return 1
            storage.store_private_key(PRIVATE_KEY_ALIASES[target], value)
            print(CLIFormatter.success(f"Updated private key for {target}"))
            return 0
        print(CLIFormatter.error(f"Unknown secret key '{key}'"))
        return 1

    if key_upper not in PROFILE_KEYS:
        print(CLIFormatter.error(f"Unknown profile key '{key}'"))
        return 1

    if clear:
        profile_store.remove(key_upper)
        if key_upper == "EVM_WALLET_ADDRESS":
            profile_store.remove("HYPERLIQUID_ACCOUNT_ADDRESS")
            sync_stored_api_key(
                storage,
                "hyperliquid_account_address",
                None,
                case_insensitive=True,
                delete_when_empty=True,
            )
        Settings.refresh_from_env()
        print(CLIFormatter.success(f"Cleared profile value for {key_upper}"))
        return 0

    if value is None:
        print(CLIFormatter.error("Provide a value or use --clear to remove."))
        return 1

    normalized_value = value.strip()

    if key_upper == "EVM_WALLET_ADDRESS":
        desired = normalized_value or None
        profile_store.update(
            {
                key_upper: desired,
                "HYPERLIQUID_ACCOUNT_ADDRESS": None,
            }
        )
        sync_stored_api_key(
            storage,
            "hyperliquid_account_address",
            desired,
            case_insensitive=True,
            delete_when_empty=True,
        )
    else:
        profile_store.update({key_upper: normalized_value})

    Settings.refresh_from_env()
    print(CLIFormatter.success(f"Updated profile value for {key_upper}"))
    return 0


def repair_fernet_key() -> int:
    """Synchronise SAM_FERNET_KEY between secure storage and .env."""

    storage = get_secure_storage()
    current_key = getattr(storage, "current_key_str", None)
    if not current_key:
        print(CLIFormatter.error("Secure storage does not expose a Fernet key."))
        return 1

    env_path = find_env_path()
    env_values_raw = dotenv_values(env_path)
    # Filter out None values and ensure all values are strings
    env_values: Dict[str, str] = {k: v for k, v in env_values_raw.items() if v is not None}
    env_values["SAM_FERNET_KEY"] = current_key
    write_env_file(env_path, env_values)
    os.environ["SAM_FERNET_KEY"] = current_key
    Settings.refresh_from_env()
    print(CLIFormatter.success("SAM_FERNET_KEY synchronised with keyring."))
    return 0
