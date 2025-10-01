import textwrap
from unittest.mock import MagicMock, patch

from sam.commands.config import edit_profile, migrate_env_to_profile


def test_migrate_env_to_profile(tmp_path):
    env_path = tmp_path / ".env"
    env_content = textwrap.dedent(
        """
        LLM_PROVIDER=openai
        OPENAI_MODEL=gpt-profile
        ENABLE_SOLANA_TOOLS=true
        OPENAI_API_KEY=sk-test-123
        SAM_FERNET_KEY=existing-fernet
        """
    ).strip()
    env_path.write_text(env_content, encoding="utf-8")

    profile_store = MagicMock()
    storage = MagicMock()
    storage.store_api_key.return_value = True
    storage.get_api_key.return_value = None

    env_values = {
        "LLM_PROVIDER": "openai",
        "OPENAI_MODEL": "gpt-profile",
        "ENABLE_SOLANA_TOOLS": "true",
        "OPENAI_API_KEY": "sk-test-123",
        "SAM_FERNET_KEY": "existing-fernet",
    }

    with (
        patch("sam.commands.config.get_profile_store", return_value=profile_store),
        patch("sam.commands.config.get_secure_storage", return_value=storage),
        patch("sam.commands.config.find_env_path", return_value=str(env_path)),
        patch("sam.commands.config.dotenv_values", return_value=env_values.copy()),
        patch("sam.commands.config.write_env_file") as mock_write,
    ):
        result = migrate_env_to_profile()

    assert result == 0

    profile_store.update.assert_called_once()
    profile_updates = profile_store.update.call_args[0][0]
    assert profile_updates.get("LLM_PROVIDER") == "openai"
    assert profile_updates.get("OPENAI_MODEL") == "gpt-profile"
    assert profile_updates.get("ENABLE_SOLANA_TOOLS") == "true"
    assert profile_updates.get("BRAVE_API_KEY_PRESENT") is False

    storage.store_api_key.assert_any_call("openai_api_key", "sk-test-123")

    mock_write.assert_called_once()
    remaining_env = mock_write.call_args[0][1]
    assert remaining_env == {"SAM_FERNET_KEY": "existing-fernet"}


@patch("sam.commands.config.Settings.refresh_from_env")
@patch("sam.commands.config.get_secure_storage")
@patch("sam.commands.config.get_profile_store")
def test_edit_profile_updates_evm_wallet(
    mock_get_profile_store,
    mock_get_secure_storage,
    mock_refresh,
):
    profile_store = MagicMock()
    storage = MagicMock()
    storage.get_api_key.return_value = None
    storage.store_api_key.return_value = True

    mock_get_profile_store.return_value = profile_store
    mock_get_secure_storage.return_value = storage

    result = edit_profile("EVM_WALLET_ADDRESS", " 0xNewAddress ")

    assert result == 0

    profile_store.update.assert_called_once_with(
        {
            "EVM_WALLET_ADDRESS": "0xNewAddress",
            "HYPERLIQUID_ACCOUNT_ADDRESS": None,
        }
    )
    storage.store_api_key.assert_called_with("hyperliquid_account_address", "0xNewAddress")
    mock_refresh.assert_called_once()


@patch("sam.commands.config.Settings.refresh_from_env")
@patch("sam.commands.config.get_secure_storage")
@patch("sam.commands.config.get_profile_store")
def test_edit_profile_clears_evm_wallet(
    mock_get_profile_store,
    mock_get_secure_storage,
    mock_refresh,
):
    profile_store = MagicMock()
    storage = MagicMock()
    storage.get_api_key.return_value = "0xOld"
    storage.delete_api_key.return_value = True

    mock_get_profile_store.return_value = profile_store
    mock_get_secure_storage.return_value = storage

    result = edit_profile("EVM_WALLET_ADDRESS", None, clear=True)

    assert result == 0

    profile_store.remove.assert_any_call("EVM_WALLET_ADDRESS")
    profile_store.remove.assert_any_call("HYPERLIQUID_ACCOUNT_ADDRESS")
    storage.delete_api_key.assert_called_with("hyperliquid_account_address")
    mock_refresh.assert_called_once()
