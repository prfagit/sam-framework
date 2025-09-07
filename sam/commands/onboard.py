"""Onboarding command implementation extracted from CLI.

Keeps behavior equivalent while avoiding tight coupling to CLI internals.
"""

import os
import getpass

from ..config.settings import Settings
from ..utils.cli_helpers import CLIFormatter
from ..utils.env_files import find_env_path, write_env_file
from ..utils.ascii_loader import show_sam_intro
from ..utils.secure_storage import get_secure_storage
from ..utils.crypto import generate_encryption_key


async def run_onboarding() -> int:
    """Streamlined onboarding with provider selection."""
    await show_sam_intro("static")

    print(CLIFormatter.header("SAM Setup"))

    try:
        # Step 1: LLM Provider Configuration
        print(CLIFormatter.header("Step 1: LLM Configuration"))
        print(CLIFormatter.info("Select your LLM provider:"))
        print("1. OpenAI")
        print("2. Anthropic (Claude)")
        print("3. xAI (Grok)")
        print("4. Local OpenAI-compatible (e.g., Ollama)")
        provider_choice = input("Choice (1-4, default: 1): ").strip() or "1"

        provider_map = {
            "1": "openai",
            "2": "anthropic",
            "3": "xai",
            "4": "local",
        }
        provider = provider_map.get(provider_choice, "openai")

        # Collect provider-specific config
        config_data = {"LLM_PROVIDER": provider}

        if provider == "openai":
            print(CLIFormatter.info("OpenAI API Key (https://platform.openai.com/api-keys)"))
            openai_key = getpass.getpass("Enter your OpenAI API Key (hidden): ").strip()
            while not openai_key:
                print(CLIFormatter.warning("API key is required."))
                openai_key = getpass.getpass("Enter your OpenAI API Key: ").strip()
            model = input("OpenAI Model (default: gpt-4o-mini): ").strip() or "gpt-4o-mini"
            base_url = input("OpenAI Base URL (blank for default): ").strip()
            config_data.update({"OPENAI_API_KEY": openai_key, "OPENAI_MODEL": model})
            if base_url:
                config_data["OPENAI_BASE_URL"] = base_url

        elif provider == "anthropic":
            print(CLIFormatter.info("Anthropic API Key (https://console.anthropic.com/)"))
            ant_key = getpass.getpass("Enter your Anthropic API Key (hidden): ").strip()
            while not ant_key:
                print(CLIFormatter.warning("API key is required."))
                ant_key = getpass.getpass("Enter your Anthropic API Key: ").strip()
            model = input("Anthropic Model (default: claude-3-5-sonnet-latest): ").strip() or (
                "claude-3-5-sonnet-latest"
            )
            base_url = input("Anthropic Base URL (blank for default): ").strip()
            config_data.update({"ANTHROPIC_API_KEY": ant_key, "ANTHROPIC_MODEL": model})
            if base_url:
                config_data["ANTHROPIC_BASE_URL"] = base_url

        elif provider == "xai":
            print(CLIFormatter.info("xAI API Key (https://docs.x.ai/ )"))
            xai_key = getpass.getpass("Enter your xAI API Key (hidden): ").strip()
            while not xai_key:
                print(CLIFormatter.warning("API key is required."))
                xai_key = getpass.getpass("Enter your xAI API Key: ").strip()
            model = input("xAI Model (default: grok-2-latest): ").strip() or "grok-2-latest"
            base_url = input("xAI Base URL (default: https://api.x.ai/v1): ").strip() or (
                "https://api.x.ai/v1"
            )
            config_data.update(
                {"XAI_API_KEY": xai_key, "XAI_MODEL": model, "XAI_BASE_URL": base_url}
            )

        elif provider == "local":
            print(CLIFormatter.info("Local OpenAI-compatible endpoint (e.g., Ollama/LM Studio)"))
            base_url = input("Base URL (default: http://localhost:11434/v1): ").strip() or (
                "http://localhost:11434/v1"
            )
            model = input("Model name (e.g., llama3.1): ").strip() or "llama3.1"
            api_key = getpass.getpass("API Key if required (optional, hidden): ").strip()
            config_data.update({"LOCAL_LLM_BASE_URL": base_url, "LOCAL_LLM_MODEL": model})
            if api_key:
                config_data["LOCAL_LLM_API_KEY"] = api_key

        # Step 2: Solana Configuration
        print(CLIFormatter.header("Step 2: Solana Configuration"))
        print(CLIFormatter.info("Choose RPC endpoint (default: mainnet):"))
        print("1. Mainnet (https://api.mainnet-beta.solana.com)")
        print("2. Devnet (https://api.devnet.solana.com)")
        print("3. Custom URL")
        rpc_choice = input("Choice (1-3): ").strip() or "1"

        if rpc_choice == "2":
            rpc_url = "https://api.devnet.solana.com"
        elif rpc_choice == "3":
            rpc_url = input("Enter custom RPC URL: ").strip()
            while not rpc_url:
                rpc_url = input("RPC URL is required: ").strip()
        else:
            rpc_url = "https://api.mainnet-beta.solana.com"

        print(
            CLIFormatter.info(
                "Your key enables trading and balance checks. It is encrypted and stored securely."
            )
        )
        private_key = getpass.getpass("Enter your Solana private key (hidden): ").strip()
        while not private_key:
            print(CLIFormatter.warning("Private key is required for wallet operations."))
            private_key = getpass.getpass("Enter your Solana private key: ").strip()

        # Step 3: Brave Search API (Optional)
        print(CLIFormatter.header("Step 3: Brave Search API (Optional)"))
        print(CLIFormatter.info("Enables web search functionality. Leave empty to skip."))
        print(CLIFormatter.info("Get API key from: https://api.search.brave.com/"))
        brave_key = getpass.getpass("Enter Brave API Key (optional, hidden): ").strip()

        print(CLIFormatter.info("Configuring SAM with optimal defaults..."))
        fernet_key = generate_encryption_key()

        # Merge common config defaults
        config_data.update(
            {
                "SAM_FERNET_KEY": fernet_key,
                "SAM_DB_PATH": ".sam/sam_memory.db",
                "SAM_SOLANA_RPC_URL": rpc_url,
                "RATE_LIMITING_ENABLED": "false",
                "MAX_TRANSACTION_SOL": "1000",
                "DEFAULT_SLIPPAGE": "1",
                "LOG_LEVEL": "NO",
            }
        )
        if brave_key:
            config_data["BRAVE_API_KEY"] = brave_key

        # Update .env
        env_path = find_env_path()
        write_env_file(env_path, config_data)

        # Ensure DB dir exists
        db_path = config_data["SAM_DB_PATH"]
        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

        # Apply to current environment
        for key, value in config_data.items():
            os.environ[key] = value
        Settings.refresh_from_env()

        # Store private key securely
        storage = get_secure_storage()
        success = storage.store_private_key("default", private_key)
        if not success:
            print(CLIFormatter.error("Failed to store private key securely."))
            return 1

        # Verify storage
        if not storage.get_private_key("default"):
            print(CLIFormatter.error("Could not verify private key storage."))
            return 1

        print(CLIFormatter.success("SAM configured successfully!"))
        return 0

    except KeyboardInterrupt:
        print("\n" + CLIFormatter.error("Setup cancelled."))
        return 1
    except Exception as e:
        print(CLIFormatter.error(f"Setup failed: {e}"))
        return 1

