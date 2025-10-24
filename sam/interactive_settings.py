"""Interactive settings management for SAM framework."""

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Protocol, Sequence, Tuple, Union, cast

from .config.profile_store import get_profile_store
from .config.settings import API_KEY_ALIASES, PRIVATE_KEY_ALIASES, Settings
from .utils.wallets import (
    WalletError,
    derive_evm_address,
    derive_solana_address,
    generate_evm_wallet,
    generate_solana_wallet,
    normalize_evm_private_key,
)
from .utils.secure_storage import get_secure_storage, sync_stored_api_key


class InquirerInterface(Protocol):
    """Subset of the inquirer API used by the interactive settings flow."""

    def list_input(
        self,
        message: str,
        choices: Sequence[Union[str, Tuple[str, Any]]],
        default: Optional[Any] = None,
    ) -> Any: ...

    def confirm(self, message: str, default: bool = ...) -> bool: ...

    def password(self, message: str) -> str: ...

    def text(self, message: str, default: str = ...) -> str: ...


_INQUIRER_MODULE: Optional[Any] = None
try:
    _INQUIRER_MODULE = importlib.import_module("inquirer")
    INQUIRER_AVAILABLE = True
except ImportError:  # pragma: no cover - import availability depends on optional dependency
    INQUIRER_AVAILABLE = False

inquirer: Optional[InquirerInterface] = cast(Optional[InquirerInterface], _INQUIRER_MODULE)


class SettingType(Enum):
    """Types of settings that can be configured."""

    BOOLEAN = "boolean"
    CHOICE = "choice"
    TEXT = "text"
    PASSWORD = "password"
    INTEGER = "integer"
    FLOAT = "float"


@dataclass
class SettingDefinition:
    """Definition of a configurable setting."""

    key: str
    display_name: str
    description: str
    setting_type: SettingType
    current_value: Any = None
    default_value: Any = None
    choices: Optional[List[str]] = None
    validation: Optional[Callable[[Any], bool]] = None
    sensitive: bool = False
    env_var: str = field(init=False)

    def __post_init__(self) -> None:
        self.env_var = self.key
        if self.current_value is None and self.default_value is not None:
            self.current_value = self.default_value


SettingChoice = Tuple[str, Union[SettingDefinition, str]]


class InteractiveSettingsManager:
    """Manages interactive configuration settings."""

    def __init__(self) -> None:
        self.profile_store = get_profile_store()
        self.settings_definitions = self._create_settings_definitions()
        self.modified_settings: Dict[str, Any] = {}
        self.modified_secrets: Dict[str, Optional[str]] = {}
        self._prompt: Optional[InquirerInterface] = inquirer
        self._hydrate_values()
        self._hydrate_wallet_settings()

    def _set_setting_value(self, key: str, value: Any) -> None:
        for setting in self.settings_definitions:
            if setting.key == key:
                setting.current_value = value
                break

    def _get_setting_value(self, key: str) -> Any:
        for setting in self.settings_definitions:
            if setting.key == key:
                return setting.current_value
        return None

    def _hydrate_values(self) -> None:
        profile_data = self.profile_store.data.copy()
        try:
            storage = get_secure_storage()
        except Exception:
            storage = None

        Settings.refresh_from_env()

        for setting in self.settings_definitions:
            key = setting.key

            if setting.sensitive and key in API_KEY_ALIASES:
                alias = API_KEY_ALIASES[key]
                value = None
                if storage:
                    try:
                        value = storage.get_api_key(alias)
                    except Exception:
                        value = None
                setting.current_value = bool(value)
                continue

            if setting.sensitive and key in PRIVATE_KEY_ALIASES:
                alias = PRIVATE_KEY_ALIASES[key]
                value = None
                if storage:
                    try:
                        value = storage.get_private_key(alias)
                    except Exception:
                        value = None
                setting.current_value = bool(value)
                continue

            if key in profile_data:
                setting.current_value = profile_data[key]
            elif hasattr(Settings, key):
                setting.current_value = getattr(Settings, key)

    def _hydrate_wallet_settings(self) -> None:
        try:
            storage = get_secure_storage()
        except Exception:
            storage = None

        if not storage:
            self._set_setting_value("BRAVE_API_KEY", Settings.BRAVE_API_KEY_PRESENT)
            return

        try:
            sol_key = storage.get_private_key("default")
        except Exception:
            sol_key = None
        if sol_key:
            self._set_setting_value("SAM_WALLET_PRIVATE_KEY", True)
            try:
                sol_address = derive_solana_address(sol_key)
                self._set_setting_value("SAM_SOLANA_ADDRESS", sol_address)
            except WalletError:
                pass

        try:
            evm_key = storage.get_private_key("hyperliquid_private_key")
        except Exception:
            evm_key = None
        if evm_key:
            try:
                normalized = normalize_evm_private_key(evm_key)
            except WalletError:
                normalized = evm_key
            self._set_setting_value("HYPERLIQUID_PRIVATE_KEY", True)
            try:
                evm_address = derive_evm_address(normalized)
                self._set_setting_value("EVM_WALLET_ADDRESS", evm_address)
            except WalletError:
                pass

        try:
            account_address = storage.get_api_key("hyperliquid_account_address")
        except Exception:
            account_address = None
        if account_address and not self._get_setting_value("EVM_WALLET_ADDRESS"):
            self._set_setting_value("EVM_WALLET_ADDRESS", account_address)

        try:
            brave_key = storage.get_api_key("brave_api_key")
        except Exception:
            brave_key = None
        self._set_setting_value("BRAVE_API_KEY", bool(brave_key) or Settings.BRAVE_API_KEY_PRESENT)

    def _require_inquirer(self) -> InquirerInterface:
        """Return the loaded inquirer module or raise if unavailable."""

        if self._prompt is None:
            raise RuntimeError("Interactive settings requires the optional 'inquirer' dependency.")
        return self._prompt

    def _create_settings_definitions(self) -> List[SettingDefinition]:
        """Create all configurable settings definitions."""
        return [
            # LLM Provider Settings
            SettingDefinition(
                key="LLM_PROVIDER",
                display_name="LLM Provider",
                description="Choose your AI language model provider",
                setting_type=SettingType.CHOICE,
                choices=["openai", "anthropic", "xai", "openai_compat", "local"],
                default_value="openai",
            ),
            # OpenAI Settings
            SettingDefinition(
                key="OPENAI_API_KEY",
                display_name="OpenAI API Key",
                description="Your OpenAI API key (required for OpenAI provider)",
                setting_type=SettingType.PASSWORD,
                sensitive=True,
            ),
            SettingDefinition(
                key="OPENAI_MODEL",
                display_name="OpenAI Model",
                description="OpenAI model to use",
                setting_type=SettingType.CHOICE,
                choices=["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
                default_value="gpt-4o-mini",
            ),
            SettingDefinition(
                key="OPENAI_BASE_URL",
                display_name="OpenAI Base URL",
                description="Custom OpenAI-compatible API base URL (optional)",
                setting_type=SettingType.TEXT,
            ),
            # Anthropic Settings
            SettingDefinition(
                key="ANTHROPIC_API_KEY",
                display_name="Anthropic API Key",
                description="Your Anthropic API key (required for Anthropic provider)",
                setting_type=SettingType.PASSWORD,
                sensitive=True,
            ),
            SettingDefinition(
                key="ANTHROPIC_MODEL",
                display_name="Anthropic Model",
                description="Anthropic Claude model to use",
                setting_type=SettingType.CHOICE,
                choices=[
                    "claude-3-5-sonnet-latest",
                    "claude-3-opus-latest",
                    "claude-3-haiku-latest",
                ],
                default_value="claude-3-5-sonnet-latest",
            ),
            # xAI Settings
            SettingDefinition(
                key="XAI_API_KEY",
                display_name="xAI API Key",
                description="Your xAI (Grok) API key",
                setting_type=SettingType.PASSWORD,
                sensitive=True,
            ),
            SettingDefinition(
                key="XAI_MODEL",
                display_name="xAI Model",
                description="xAI Grok model to use",
                setting_type=SettingType.CHOICE,
                choices=["grok-2-latest", "grok-beta"],
                default_value="grok-2-latest",
            ),
            # Local LLM Settings
            SettingDefinition(
                key="LOCAL_LLM_BASE_URL",
                display_name="Local LLM Base URL",
                description="Base URL for local LLM server (e.g., Ollama)",
                setting_type=SettingType.TEXT,
                default_value="http://localhost:11434/v1",
            ),
            SettingDefinition(
                key="LOCAL_LLM_MODEL",
                display_name="Local LLM Model",
                description="Model name for local LLM",
                setting_type=SettingType.TEXT,
                default_value="llama3.1",
            ),
            # Solana Settings
            SettingDefinition(
                key="SAM_SOLANA_RPC_URL",
                display_name="Solana RPC URL",
                description="Solana RPC endpoint URL",
                setting_type=SettingType.TEXT,
                default_value="https://api.mainnet-beta.solana.com",
            ),
            SettingDefinition(
                key="SAM_WALLET_PRIVATE_KEY",
                display_name="Wallet Private Key",
                description="Your Solana wallet private key (base58 format)",
                setting_type=SettingType.PASSWORD,
                sensitive=True,
            ),
            SettingDefinition(
                key="SAM_SOLANA_ADDRESS",
                display_name="Solana Address",
                description="Derived Solana wallet address (read-only)",
                setting_type=SettingType.TEXT,
            ),
            SettingDefinition(
                key="HYPERLIQUID_PRIVATE_KEY",
                display_name="EVM Private Key",
                description="Your EVM private key (0x-prefixed hex)",
                setting_type=SettingType.PASSWORD,
                sensitive=True,
            ),
            SettingDefinition(
                key="EVM_WALLET_ADDRESS",
                display_name="EVM Wallet Address",
                description="Derived EVM wallet address used for Hyperliquid",
                setting_type=SettingType.TEXT,
            ),
            # Aster Futures Settings
            SettingDefinition(
                key="ASTER_API_KEY",
                display_name="Aster API Key",
                description="REST API key from your Aster account",
                setting_type=SettingType.PASSWORD,
                sensitive=True,
            ),
            SettingDefinition(
                key="ASTER_API_SECRET",
                display_name="Aster API Secret",
                description="REST API secret from your Aster account",
                setting_type=SettingType.PASSWORD,
                sensitive=True,
            ),
            SettingDefinition(
                key="ASTER_BASE_URL",
                display_name="Aster Base URL",
                description="Base endpoint for Aster futures API",
                setting_type=SettingType.TEXT,
                default_value="https://fapi.asterdex.com",
            ),
            SettingDefinition(
                key="ASTER_DEFAULT_RECV_WINDOW",
                display_name="Aster recvWindow (ms)",
                description="Default recvWindow value for signed Aster requests",
                setting_type=SettingType.INTEGER,
                default_value=5000,
            ),
            SettingDefinition(
                key="PAYAI_FACILITATOR_URL",
                display_name="PayAI Facilitator URL",
                description="Base URL for the PayAI x402 facilitator (default is the public facilitator).",
                setting_type=SettingType.TEXT,
                default_value="https://facilitator.payai.network",
            ),
            # Tool Toggle Settings
            SettingDefinition(
                key="ENABLE_SOLANA_TOOLS",
                display_name="Enable Solana Tools",
                description="Enable balance checking, transfers, and token data tools",
                setting_type=SettingType.BOOLEAN,
                default_value=True,
            ),
            SettingDefinition(
                key="ENABLE_PUMP_FUN_TOOLS",
                display_name="Enable Pump.fun Tools",
                description="Enable pump.fun trading and token info tools",
                setting_type=SettingType.BOOLEAN,
                default_value=True,
            ),
            SettingDefinition(
                key="ENABLE_DEXSCREENER_TOOLS",
                display_name="Enable DexScreener Tools",
                description="Enable market data and trading pair tools",
                setting_type=SettingType.BOOLEAN,
                default_value=True,
            ),
            SettingDefinition(
                key="ENABLE_JUPITER_TOOLS",
                display_name="Enable Jupiter Tools",
                description="Enable Jupiter swap and quote tools",
                setting_type=SettingType.BOOLEAN,
                default_value=True,
            ),
            SettingDefinition(
                key="ENABLE_SEARCH_TOOLS",
                display_name="Enable Search Tools",
                description="Enable web search and news search tools",
                setting_type=SettingType.BOOLEAN,
                default_value=True,
            ),
            SettingDefinition(
                key="ENABLE_POLYMARKET_TOOLS",
                display_name="Enable Polymarket Tools",
                description="Enable Polymarket market discovery and strategy tools",
                setting_type=SettingType.BOOLEAN,
                default_value=True,
            ),
            SettingDefinition(
                key="ENABLE_ASTER_FUTURES_TOOLS",
                display_name="Enable Aster Futures Tools",
                description="Enable Aster futures trading and account tools",
                setting_type=SettingType.BOOLEAN,
                default_value=False,
            ),
            SettingDefinition(
                key="ENABLE_HYPERLIQUID_TOOLS",
                display_name="Enable Hyperliquid Tools",
                description="Enable Hyperliquid trading and account tools",
                setting_type=SettingType.BOOLEAN,
                default_value=False,
            ),
            SettingDefinition(
                key="ENABLE_PAYAI_FACILITATOR_TOOLS",
                display_name="Enable PayAI Facilitator Tools",
                description="Enable x402 verification, settlement, and discovery tools for PayAI.",
                setting_type=SettingType.BOOLEAN,
                default_value=True,
            ),
            # Safety & Limits Settings
            SettingDefinition(
                key="MAX_TRANSACTION_SOL",
                display_name="Max Transaction Amount (SOL)",
                description="Maximum SOL amount per transaction (safety limit)",
                setting_type=SettingType.FLOAT,
                default_value=1000.0,
                validation=lambda x: 0.001 <= float(x) <= 100000,
            ),
            SettingDefinition(
                key="DEFAULT_SLIPPAGE",
                display_name="Default Slippage (%)",
                description="Default slippage tolerance percentage for trades",
                setting_type=SettingType.INTEGER,
                default_value=1,
                validation=lambda x: 1 <= int(x) <= 50,
            ),
            SettingDefinition(
                key="RATE_LIMITING_ENABLED",
                display_name="Enable Rate Limiting",
                description="Enable API rate limiting protection",
                setting_type=SettingType.BOOLEAN,
                default_value=False,
            ),
            # Other Settings
            SettingDefinition(
                key="BRAVE_API_KEY",
                display_name="Brave Search API Key",
                description="API key for Brave web search functionality (optional)",
                setting_type=SettingType.PASSWORD,
                sensitive=True,
            ),
            SettingDefinition(
                key="SAM_FERNET_KEY",
                display_name="Encryption Key",
                description="Fernet key for secure data encryption (auto-generated)",
                setting_type=SettingType.PASSWORD,
                sensitive=True,
            ),
            SettingDefinition(
                key="LOG_LEVEL",
                display_name="Log Level",
                description="Application logging verbosity level",
                setting_type=SettingType.CHOICE,
                choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "NO"],
                default_value="INFO",
            ),
        ]

    def _format_current_value_display(self, setting: SettingDefinition) -> str:
        """Format current value for display."""
        if setting.sensitive:
            return "✅ Stored securely" if setting.current_value else "❌ Not set"
        elif setting.setting_type == SettingType.BOOLEAN:
            return "✅ Enabled" if setting.current_value else "❌ Disabled"
        elif setting.current_value == "":
            return "❌ Not set"
        elif setting.current_value is None:
            return "❌ Not set"
        else:
            return str(setting.current_value)

    def _get_setting_categories(self) -> Dict[str, List[SettingDefinition]]:
        """Group settings by category for better organization."""
        categories: Dict[str, List[SettingDefinition]] = {
            "🤖 LLM Provider": [],
            "🔑 API Keys": [],
            "💰 Wallets": [],
            "⚡ Tool Toggles": [],
            "🔐 Security & Limits": [],
            "🌐 Network & Storage": [],
            "📊 System & Logging": [],
        }

        for setting in self.settings_definitions:
            if setting.key == "LLM_PROVIDER":
                categories["🤖 LLM Provider"].append(setting)
            elif setting.key in [
                "SAM_WALLET_PRIVATE_KEY",
                "SAM_SOLANA_ADDRESS",
                "HYPERLIQUID_PRIVATE_KEY",
                "EVM_WALLET_ADDRESS",
            ]:
                categories["💰 Wallets"].append(setting)
            elif setting.key.endswith("_API_KEY") or setting.key.endswith("_API_SECRET"):
                categories["🔑 API Keys"].append(setting)
            elif setting.key.startswith("ENABLE_"):
                categories["⚡ Tool Toggles"].append(setting)
            elif setting.key in [
                "MAX_TRANSACTION_SOL",
                "DEFAULT_SLIPPAGE",
                "SAM_FERNET_KEY",
                "RATE_LIMITING_ENABLED",
                "ASTER_DEFAULT_RECV_WINDOW",
            ]:
                categories["🔐 Security & Limits"].append(setting)
            elif setting.key in [
                "SAM_SOLANA_RPC_URL",
                "SAM_DB_PATH",
                "OPENAI_BASE_URL",
                "LOCAL_LLM_BASE_URL",
                "ASTER_BASE_URL",
                "PAYAI_FACILITATOR_URL",
            ]:
                categories["🌐 Network & Storage"].append(setting)
            else:
                categories["📊 System & Logging"].append(setting)

        # Remove empty categories
        return {k: v for k, v in categories.items() if v}

    def show_interactive_settings(self) -> bool:
        """Show interactive settings menu. Returns True if settings were modified."""
        if not INQUIRER_AVAILABLE:
            print("❌ Interactive settings requires 'inquirer' package.")
            print("   Install with: uv add inquirer")
            return False

        prompt = self._require_inquirer()
        print("\n" + "=" * 60)
        print("🛠️  SAM Framework Interactive Settings")
        print("=" * 60)

        categories = self._get_setting_categories()

        while True:
            # Main category selection
            category_choices: List[str] = list(categories.keys()) + [
                "💾 Save & Exit",
                "❌ Exit without saving",
            ]

            try:
                selected_category = prompt.list_input(
                    "Select category to configure:", choices=category_choices
                )
            except KeyboardInterrupt:
                print("\n❌ Cancelled.")
                return False

            if selected_category == "💾 Save & Exit":
                return self._save_settings()
            elif selected_category == "❌ Exit without saving":
                if self.modified_settings:
                    confirm = prompt.confirm(
                        "You have unsaved changes. Are you sure you want to exit?", default=False
                    )
                    if not confirm:
                        continue
                return False
            else:
                self._show_category_settings(selected_category, categories[selected_category])

    def _show_category_settings(
        self, category_name: str, settings: Sequence[SettingDefinition]
    ) -> None:
        """Show settings for a specific category."""
        prompt = self._require_inquirer()

        while True:
            print(f"\n📁 {category_name}")
            print("-" * 50)

            # Create choices with current values
            choices: List[SettingChoice] = []
            for setting in settings:
                current_display = self._format_current_value_display(setting)
                choice_text = f"{setting.display_name}: {current_display}"
                choices.append((choice_text, setting))

            choices.append(("⬅️  Back to categories", "back"))

            try:
                selected = prompt.list_input("Select setting to modify:", choices=choices)
            except KeyboardInterrupt:
                return

            if isinstance(selected, str) and selected == "back":
                return
            elif isinstance(selected, SettingDefinition):
                self._modify_setting(selected)

    def _modify_setting(self, setting: SettingDefinition) -> None:
        """Modify a specific setting."""
        prompt = self._require_inquirer()
        print(f"\n🔧 Configuring: {setting.display_name}")
        print(f"📝 {setting.description}")

        current_display = self._format_current_value_display(setting)
        print(f"🔍 Current value: {current_display}")

        # Wallet-specific handling
        if setting.key in {"SAM_SOLANA_ADDRESS", "EVM_WALLET_ADDRESS"}:
            print("ℹ️  This value is derived from the corresponding private key.")
            print("   Use the wallet private key option to import or generate a new wallet.")
            return

        if setting.key in {"SAM_WALLET_PRIVATE_KEY", "HYPERLIQUID_PRIVATE_KEY"}:
            actions = ["Import existing key", "Generate new wallet", "Cancel"]
            try:
                action = prompt.list_input(
                    "Select wallet action:",
                    choices=actions,
                    default="Import existing key",
                )
            except KeyboardInterrupt:
                return

            if action == "Cancel":
                return

            private_key: Optional[str] = None
            address: Optional[str] = None

            if action == "Import existing key":
                provided_key = prompt.password("Enter private key (input hidden):").strip()
                if not provided_key:
                    print("❌ Private key is required.")
                    return
                try:
                    if setting.key == "SAM_WALLET_PRIVATE_KEY":
                        address = derive_solana_address(provided_key)
                    else:
                        normalized = normalize_evm_private_key(provided_key)
                        address = derive_evm_address(normalized)
                        provided_key = normalized
                except WalletError as exc:
                    print(f"❌ {exc}")
                    return
                private_key = provided_key
            elif action == "Generate new wallet":
                if setting.key == "SAM_WALLET_PRIVATE_KEY":
                    private_key, address = generate_solana_wallet()
                else:
                    private_key, address = generate_evm_wallet()
                print("✅ Generated new wallet.")
                print(f"   Private key: {private_key}")
                print(f"   Address: {address}")
                print("   Save the private key securely before proceeding!\n")

            if not private_key or not address:
                print("❌ Failed to update wallet.")
                return

            # Stash secret for secure storage persistence
            self.modified_secrets[setting.key] = private_key
            self._set_setting_value(setting.key, True)

            if setting.key == "SAM_WALLET_PRIVATE_KEY":
                self.modified_settings["SAM_SOLANA_ADDRESS"] = address
                self._set_setting_value("SAM_SOLANA_ADDRESS", address)
            else:
                self.modified_settings["EVM_WALLET_ADDRESS"] = address
                self._set_setting_value("EVM_WALLET_ADDRESS", address)
                self.modified_settings["ENABLE_HYPERLIQUID_TOOLS"] = True
                self._set_setting_value("ENABLE_HYPERLIQUID_TOOLS", True)

            print("✅ Wallet updated!")
            return

        try:
            new_value: Any
            if setting.setting_type == SettingType.BOOLEAN:
                default_value = (
                    bool(setting.current_value) if setting.current_value is not None else False
                )
                new_value = prompt.confirm(f"Enable {setting.display_name}?", default=default_value)
            elif setting.setting_type == SettingType.CHOICE:
                choices = setting.choices or []
                if not choices:
                    print("❌ No choices configured for this setting.")
                    return

                default_choice: Optional[str] = None
                if isinstance(setting.current_value, str) and setting.current_value in choices:
                    default_choice = setting.current_value
                else:
                    default_choice = choices[0]

                new_value = prompt.list_input(
                    f"Select {setting.display_name}:",
                    choices=choices,
                    default=default_choice,
                )
            elif setting.setting_type == SettingType.PASSWORD:
                if setting.key == "SAM_FERNET_KEY":
                    print("ℹ️  Manage the encryption key via `sam key rotate`.")
                    return

                password_value = prompt.password(
                    f"Enter {setting.display_name} (leave blank to keep current):"
                )
                stripped_value = password_value.strip()
                if not stripped_value:
                    return

                if setting.sensitive and setting.key in API_KEY_ALIASES:
                    self.modified_secrets[setting.key] = stripped_value
                    setting.current_value = True
                    print(f"✅ {setting.display_name} updated!")
                    return

                if setting.sensitive and setting.key in PRIVATE_KEY_ALIASES:
                    self.modified_secrets[setting.key] = stripped_value
                    setting.current_value = True
                    print(f"✅ {setting.display_name} updated!")
                    return

                new_value = password_value
            else:  # TEXT, INTEGER, FLOAT
                prompt_text = f"Enter {setting.display_name}"
                if setting.current_value:
                    prompt_text += f" (current: {setting.current_value})"
                prompt_text += ":"

                text_response = prompt.text(
                    prompt_text,
                    default=str(setting.current_value) if setting.current_value is not None else "",
                )
                new_value = text_response

                # Type conversion and validation
                if setting.setting_type == SettingType.INTEGER:
                    try:
                        new_value = int(text_response)
                    except ValueError:
                        print("❌ Invalid integer value!")
                        return
                elif setting.setting_type == SettingType.FLOAT:
                    try:
                        new_value = float(text_response)
                    except ValueError:
                        print("❌ Invalid number value!")
                        return

            # Apply validation if provided
            if setting.validation is not None:
                try:
                    if not setting.validation(new_value):
                        print("❌ Validation failed!")
                        return
                except Exception as e:
                    print(f"❌ Validation error: {e}")
                    return

            if setting.sensitive and setting.key in API_KEY_ALIASES:
                if isinstance(new_value, str):
                    self.modified_secrets[setting.key] = new_value.strip()
                else:
                    self.modified_secrets[setting.key] = str(new_value)
                setting.current_value = True
                print(f"✅ {setting.display_name} updated!")
                return

            if setting.sensitive and setting.key in PRIVATE_KEY_ALIASES:
                if isinstance(new_value, str):
                    self.modified_secrets[setting.key] = new_value.strip()
                else:
                    self.modified_secrets[setting.key] = str(new_value)
                setting.current_value = True
                print(f"✅ {setting.display_name} updated!")
                return

            # Store the modification
            self.modified_settings[setting.key] = new_value
            setting.current_value = new_value
            print(f"✅ {setting.display_name} updated!")

        except KeyboardInterrupt:
            return

    def _save_settings(self) -> bool:
        """Persist modified settings via profile store and secure storage."""

        if not self.modified_settings and not self.modified_secrets:
            print("ℹ️  No changes to save.")
            return False

        try:
            storage: Optional[Any] = None
            evm_wallet_value: Optional[str] = None

            if "EVM_WALLET_ADDRESS" in self.modified_settings:
                raw_evm = self.modified_settings["EVM_WALLET_ADDRESS"]
                if raw_evm is None:
                    trimmed_evm = None
                else:
                    trimmed_evm = str(raw_evm).strip()
                    if not trimmed_evm:
                        trimmed_evm = None
                if trimmed_evm:
                    self.modified_settings["EVM_WALLET_ADDRESS"] = trimmed_evm
                    evm_wallet_value = trimmed_evm
                else:
                    self.modified_settings["EVM_WALLET_ADDRESS"] = None
                    evm_wallet_value = None
                if "HYPERLIQUID_ACCOUNT_ADDRESS" not in self.modified_settings:
                    self.modified_settings["HYPERLIQUID_ACCOUNT_ADDRESS"] = None

            needs_storage = (
                bool(self.modified_secrets) or "EVM_WALLET_ADDRESS" in self.modified_settings
            )
            if needs_storage:
                storage = get_secure_storage()

            if self.modified_settings:
                self.profile_store.update(self.modified_settings)
                for key, value in self.modified_settings.items():
                    if value is None:
                        os.environ.pop(key, None)
                        continue
                    if isinstance(value, bool):
                        os.environ[key] = "true" if value else "false"
                    else:
                        os.environ[key] = str(value)

            if "EVM_WALLET_ADDRESS" in self.modified_settings and storage is not None:
                sync_stored_api_key(
                    storage,
                    "hyperliquid_account_address",
                    evm_wallet_value,
                    case_insensitive=True,
                    delete_when_empty=True,
                )

            if self.modified_secrets:
                assert storage is not None
                brave_status: Optional[bool] = None
                for key, value in self.modified_secrets.items():
                    if key in API_KEY_ALIASES:
                        alias = API_KEY_ALIASES[key]
                        if value:
                            storage.store_api_key(alias, value)
                        else:
                            storage.delete_api_key(alias)
                        if key == "BRAVE_API_KEY":
                            brave_status = bool(value)
                    elif key in PRIVATE_KEY_ALIASES:
                        alias = PRIVATE_KEY_ALIASES[key]
                        if value:
                            storage.store_private_key(alias, value)
                        else:
                            storage.delete_private_key(alias)
                    else:
                        if value:
                            os.environ[key] = value
                if brave_status is not None:
                    self.profile_store.update({"BRAVE_API_KEY_PRESENT": brave_status})

            Settings.refresh_from_env()

            print("✅ Settings saved successfully!")
            print("ℹ️  Restart SAM for changes to take effect.")

            self.modified_settings.clear()
            self.modified_secrets.clear()
            return True

        except Exception as e:
            print(f"❌ Error saving settings: {e}")
            return False


def run_interactive_settings() -> bool:
    """Entry point for interactive settings."""
    manager = InteractiveSettingsManager()
    return manager.show_interactive_settings()


if __name__ == "__main__":
    run_interactive_settings()
