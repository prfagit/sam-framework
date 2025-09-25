"""Provider subcommands for SAM CLI."""

from typing import Dict, List, Optional, TypedDict

from ..config.settings import Settings
from ..utils.cli_helpers import CLIFormatter
from ..utils.env_files import find_env_path, write_env_file
from ..core.llm_provider import LLMProvider, create_llm_provider


class ProviderInfo(TypedDict):
    """Metadata describing an LLM provider for CLI display."""

    name: str
    models: List[str]
    description: str


def list_providers() -> None:
    """List available LLM providers."""
    providers: Dict[str, ProviderInfo] = {
        "openai": {
            "name": "OpenAI",
            "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
            "description": "OpenAI GPT models",
        },
        "anthropic": {
            "name": "Anthropic Claude",
            "models": [
                "claude-3-5-sonnet-latest",
                "claude-3-5-haiku-latest",
                "claude-3-opus-latest",
            ],
            "description": "Anthropic Claude models",
        },
        "xai": {
            "name": "xAI Grok",
            "models": ["grok-2-latest", "grok-beta"],
            "description": "xAI Grok models",
        },
        "local": {
            "name": "Local/Ollama",
            "models": ["llama3.1", "llama3.2", "mixtral", "custom"],
            "description": "Local OpenAI-compatible server",
        },
    }

    print(CLIFormatter.header("🤖 Available LLM Providers"))
    current = Settings.LLM_PROVIDER
    for key, info in providers.items():
        is_current = key == current
        name = f"→ {key}" if is_current else f"  {key}"
        status = " (current)" if is_current else ""
        print(CLIFormatter.colorize(f"{name} - {info['name']}{status}", CLIFormatter.CYAN))
        print(CLIFormatter.colorize(info["description"], CLIFormatter.DIM))
        models_preview = ", ".join(info["models"][:3]) + ("..." if len(info["models"]) > 3 else "")
        print(f"   Models: {models_preview}\n")


def show_current_provider() -> None:
    """Show current provider configuration."""
    provider = Settings.LLM_PROVIDER
    print(CLIFormatter.header("🔧 Current Provider Configuration"))
    print(f"Provider: {CLIFormatter.colorize(provider, CLIFormatter.GREEN)}")

    if provider == "openai":
        print(f"Model: {Settings.OPENAI_MODEL}")
        print(f"Base URL: {Settings.OPENAI_BASE_URL or 'default'}")
        print(f"API Key: {'✓ configured' if Settings.OPENAI_API_KEY else '✗ missing'}")
    elif provider == "anthropic":
        print(f"Model: {Settings.ANTHROPIC_MODEL}")
        print(f"Base URL: {Settings.ANTHROPIC_BASE_URL}")
        print(f"API Key: {'✓ configured' if Settings.ANTHROPIC_API_KEY else '✗ missing'}")
    elif provider == "xai":
        print(f"Model: {Settings.XAI_MODEL}")
        print(f"Base URL: {Settings.XAI_BASE_URL}")
        print(f"API Key: {'✓ configured' if Settings.XAI_API_KEY else '✗ missing'}")
    elif provider == "local":
        print(f"Model: {Settings.LOCAL_LLM_MODEL}")
        print(f"Base URL: {Settings.LOCAL_LLM_BASE_URL}")
        print(f"API Key: {'✓ configured' if Settings.LOCAL_LLM_API_KEY else 'not required'}")


def switch_provider(provider_name: str) -> int:
    """Switch to a different LLM provider by updating .env and process env."""
    valid_providers = ["openai", "anthropic", "xai", "local", "openai_compat"]
    if provider_name not in valid_providers:
        print(CLIFormatter.error(f"Invalid provider. Choose from: {', '.join(valid_providers)}"))
        return 1

    env_path = find_env_path()

    try:
        # Read existing .env
        config_data = {}
        try:
            with open(env_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and "=" in line and not line.startswith("#"):
                        key, value = line.split("=", 1)
                        config_data[key] = value
        except FileNotFoundError:
            pass

        # Update provider
        config_data["LLM_PROVIDER"] = provider_name

        # Persist
        write_env_file(env_path, config_data)

        # Update class and process env for current session
        import os

        os.environ["LLM_PROVIDER"] = provider_name
        Settings.LLM_PROVIDER = provider_name

        print(CLIFormatter.success(f"Switched to provider: {provider_name}"))

        # Hint about API keys
        key_configured = False
        if provider_name == "openai":
            key_configured = bool(Settings.OPENAI_API_KEY)
        elif provider_name == "anthropic":
            key_configured = bool(Settings.ANTHROPIC_API_KEY)
        elif provider_name == "xai":
            key_configured = bool(Settings.XAI_API_KEY)
        elif provider_name == "local":
            key_configured = True
        if not key_configured:
            print(
                CLIFormatter.warning(
                    f"{provider_name.upper()}_API_KEY not configured. Add it to your .env or run 'uv run sam onboard'."
                )
            )

        return 0

    except Exception as e:
        print(CLIFormatter.error(f"Failed to switch provider: {e}"))
        return 1


async def test_provider(provider_name: Optional[str] = None) -> int:
    """Test connection to LLM provider."""
    target_provider = provider_name or Settings.LLM_PROVIDER
    print(f"🧪 Testing {target_provider} provider...")

    original_provider = Settings.LLM_PROVIDER
    llm: Optional[LLMProvider] = None

    try:
        Settings.LLM_PROVIDER = target_provider

        llm = create_llm_provider()
        test_messages = [
            {"role": "user", "content": "Say 'Hello from SAM!' and nothing else."}
        ]

        response = await llm.chat_completion(test_messages)

        if response.content:
            print(f"✅ {target_provider} test successful!")
            print(f"   Response: {response.content.strip()}")
            if response.usage:
                tokens = response.usage.get("total_tokens", 0)
                if tokens > 0:
                    print(f"   Tokens used: {tokens}")
            return 0

        print(f"❌ {target_provider} test failed: Empty response")
        return 1

    except Exception as exc:  # pragma: no cover - network/runtime errors
        print(f"❌ {target_provider} test failed: {exc}")
        return 1

    finally:
        Settings.LLM_PROVIDER = original_provider
        if llm is not None:
            await llm.close()
