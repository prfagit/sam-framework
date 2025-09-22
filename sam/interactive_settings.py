"""Interactive settings management for SAM framework."""

import os
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum

try:
    import inquirer

    INQUIRER_AVAILABLE = True
except ImportError:
    INQUIRER_AVAILABLE = False


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
    validation: Optional[callable] = None
    sensitive: bool = False
    env_var: str = field(init=False)

    def __post_init__(self):
        self.env_var = self.key
        # Get current value from environment
        if self.setting_type == SettingType.BOOLEAN:
            env_val = os.getenv(self.key, str(self.default_value)).lower()
            self.current_value = env_val in ["true", "1", "yes", "on"]
        elif self.setting_type in [SettingType.INTEGER, SettingType.FLOAT]:
            try:
                converter = int if self.setting_type == SettingType.INTEGER else float
                self.current_value = converter(os.getenv(self.key, str(self.default_value)))
            except (ValueError, TypeError):
                self.current_value = self.default_value
        else:
            self.current_value = os.getenv(self.key, self.default_value or "")


class InteractiveSettingsManager:
    """Manages interactive configuration settings."""

    def __init__(self):
        self.settings_definitions = self._create_settings_definitions()
        self.modified_settings: Dict[str, Any] = {}

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
        if setting.sensitive and setting.current_value:
            return "***SET***" if setting.current_value else "***NOT SET***"
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
        categories = {
            "🤖 LLM Provider": [],
            "🔑 API Keys": [],
            "⚡ Tool Toggles": [],
            "🔐 Security & Limits": [],
            "🌐 Network & Storage": [],
            "📊 System & Logging": [],
        }

        for setting in self.settings_definitions:
            if setting.key == "LLM_PROVIDER":
                categories["🤖 LLM Provider"].append(setting)
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
                "SAM_WALLET_PRIVATE_KEY",
                "SAM_DB_PATH",
                "OPENAI_BASE_URL",
                "LOCAL_LLM_BASE_URL",
                "ASTER_BASE_URL",
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

        print("\n" + "=" * 60)
        print("🛠️  SAM Framework Interactive Settings")
        print("=" * 60)

        categories = self._get_setting_categories()

        while True:
            # Main category selection
            category_choices = list(categories.keys()) + [
                "💾 Save & Exit",
                "❌ Exit without saving",
            ]

            try:
                selected_category = inquirer.list_input(
                    "Select category to configure:", choices=category_choices
                )
            except KeyboardInterrupt:
                print("\n❌ Cancelled.")
                return False

            if selected_category == "💾 Save & Exit":
                return self._save_settings()
            elif selected_category == "❌ Exit without saving":
                if self.modified_settings:
                    confirm = inquirer.confirm(
                        "You have unsaved changes. Are you sure you want to exit?", default=False
                    )
                    if not confirm:
                        continue
                return False
            else:
                self._show_category_settings(selected_category, categories[selected_category])

    def _show_category_settings(self, category_name: str, settings: List[SettingDefinition]):
        """Show settings for a specific category."""
        while True:
            print(f"\n📁 {category_name}")
            print("-" * 50)

            # Create choices with current values
            choices = []
            for setting in settings:
                current_display = self._format_current_value_display(setting)
                choice_text = f"{setting.display_name}: {current_display}"
                choices.append((choice_text, setting))

            choices.append(("⬅️  Back to categories", "back"))

            try:
                selected = inquirer.list_input("Select setting to modify:", choices=choices)
            except KeyboardInterrupt:
                return

            if selected == "back":
                return
            else:
                self._modify_setting(selected)

    def _modify_setting(self, setting: SettingDefinition):
        """Modify a specific setting."""
        print(f"\n🔧 Configuring: {setting.display_name}")
        print(f"📝 {setting.description}")

        current_display = self._format_current_value_display(setting)
        print(f"🔍 Current value: {current_display}")

        try:
            if setting.setting_type == SettingType.BOOLEAN:
                new_value = inquirer.confirm(
                    f"Enable {setting.display_name}?", default=setting.current_value
                )
            elif setting.setting_type == SettingType.CHOICE:
                new_value = inquirer.list_input(
                    f"Select {setting.display_name}:",
                    choices=setting.choices,
                    default=setting.current_value
                    if setting.current_value in setting.choices
                    else setting.choices[0],
                )
            elif setting.setting_type == SettingType.PASSWORD:
                new_value = inquirer.password(
                    f"Enter {setting.display_name} (leave blank to keep current):"
                )
                if not new_value.strip():  # Keep current if empty
                    return
            else:  # TEXT, INTEGER, FLOAT
                prompt_text = f"Enter {setting.display_name}"
                if setting.current_value:
                    prompt_text += f" (current: {setting.current_value})"
                prompt_text += ":"

                new_value = inquirer.text(
                    prompt_text, default=str(setting.current_value) if setting.current_value else ""
                )

                # Type conversion and validation
                if setting.setting_type == SettingType.INTEGER:
                    try:
                        new_value = int(new_value)
                    except ValueError:
                        print("❌ Invalid integer value!")
                        return
                elif setting.setting_type == SettingType.FLOAT:
                    try:
                        new_value = float(new_value)
                    except ValueError:
                        print("❌ Invalid number value!")
                        return

            # Apply validation if provided
            if setting.validation:
                try:
                    if not setting.validation(new_value):
                        print("❌ Validation failed!")
                        return
                except Exception as e:
                    print(f"❌ Validation error: {e}")
                    return

            # Store the modification
            self.modified_settings[setting.key] = new_value
            setting.current_value = new_value
            print(f"✅ {setting.display_name} updated!")

        except KeyboardInterrupt:
            return

    def _save_settings(self) -> bool:
        """Save modified settings to .env file."""
        if not self.modified_settings:
            print("ℹ️  No changes to save.")
            return False

        env_path = Path(".env")

        print(f"\n💾 Saving {len(self.modified_settings)} setting(s) to {env_path}...")

        # Read existing .env file content
        existing_env = {}
        if env_path.exists():
            with open(env_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        existing_env[key] = value

        # Update with modified settings
        for key, value in self.modified_settings.items():
            if isinstance(value, bool):
                existing_env[key] = "true" if value else "false"
            else:
                existing_env[key] = str(value)

        # Write back to .env file
        try:
            with open(env_path, "w") as f:
                f.write("# SAM Framework Configuration\n")
                f.write("# Generated by interactive settings\n\n")

                for key, value in sorted(existing_env.items()):
                    f.write(f"{key}={value}\n")

            print("✅ Settings saved successfully!")
            print("ℹ️  Restart SAM for changes to take effect.")

            # Clear modifications
            self.modified_settings.clear()
            return True

        except Exception as e:
            print(f"❌ Error saving settings: {e}")
            return False


def run_interactive_settings():
    """Entry point for interactive settings."""
    manager = InteractiveSettingsManager()
    return manager.show_interactive_settings()


if __name__ == "__main__":
    run_interactive_settings()
