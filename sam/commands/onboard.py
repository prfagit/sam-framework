"""Onboarding command implementation extracted from CLI.

Keeps behavior equivalent while avoiding tight coupling to CLI internals.
"""

import getpass
import os
from typing import Any, Dict, Optional

from ..config.profile_store import get_profile_store
from ..config.settings import Settings
from ..utils.cli_helpers import CLIFormatter
from ..utils.env_files import find_env_path, write_env_file
from ..utils.ascii_loader import show_sam_intro
from ..utils.secure_storage import get_secure_storage
from ..utils.crypto import generate_encryption_key
from ..utils.wallets import (
    WalletError,
    derive_evm_address,
    derive_solana_address,
    generate_evm_wallet,
    generate_solana_wallet,
)


async def run_onboarding() -> int:
    """Streamlined onboarding with provider selection."""
    await show_sam_intro("static")

    print(CLIFormatter.header("SAM Setup"))

    storage = get_secure_storage()
    profile_store = get_profile_store()

    profile_updates: Dict[str, Any] = {}
    env_updates: Dict[str, str] = {}

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
        profile_updates["LLM_PROVIDER"] = provider

        if provider == "openai":
            print(CLIFormatter.info("OpenAI API Key (https://platform.openai.com/api-keys)"))
            openai_key = getpass.getpass("Enter your OpenAI API Key (hidden): ").strip()
            while not openai_key:
                print(CLIFormatter.warning("API key is required."))
                openai_key = getpass.getpass("Enter your OpenAI API Key: ").strip()
            model = input("OpenAI Model (default: gpt-4o-mini): ").strip() or "gpt-4o-mini"
            base_url = input("OpenAI Base URL (blank for default): ").strip()
            storage.store_api_key("openai_api_key", openai_key)
            profile_updates["OPENAI_MODEL"] = model
            if base_url:
                profile_updates["OPENAI_BASE_URL"] = base_url

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
            storage.store_api_key("anthropic_api_key", ant_key)
            profile_updates["ANTHROPIC_MODEL"] = model
            if base_url:
                profile_updates["ANTHROPIC_BASE_URL"] = base_url

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
            storage.store_api_key("xai_api_key", xai_key)
            profile_updates.update({"XAI_MODEL": model, "XAI_BASE_URL": base_url})

        elif provider == "local":
            print(CLIFormatter.info("Local OpenAI-compatible endpoint (e.g., Ollama/LM Studio)"))
            base_url = input("Base URL (default: http://localhost:11434/v1): ").strip() or (
                "http://localhost:11434/v1"
            )
            model = input("Model name (e.g., llama3.1): ").strip() or "llama3.1"
            api_key = getpass.getpass("API Key if required (optional, hidden): ").strip()
            profile_updates.update({"LOCAL_LLM_BASE_URL": base_url, "LOCAL_LLM_MODEL": model})
            if api_key:
                storage.store_api_key("local_llm_api_key", api_key)

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

        profile_updates["SAM_SOLANA_RPC_URL"] = rpc_url

        solana_private_key: Optional[str] = None
        solana_public_address: Optional[str] = None

        print(
            CLIFormatter.info(
                "Your key enables trading and balance checks. It is encrypted and stored securely."
            )
        )
        while solana_private_key is None:
            wallet_choice = (
                input(
                    "Press Enter to import an existing Solana private key, or type 'generate' to create a new wallet: "
                )
                .strip()
                .lower()
            )

            if wallet_choice in {"generate", "g", "2"}:
                solana_private_key, solana_public_address = generate_solana_wallet()
                print(
                    CLIFormatter.box(
                        "Solana wallet generated",
                        (
                            f"Public address: {solana_public_address}\n"
                            f"Private key (base58): {solana_private_key}\n\n"
                            "Copy this private key to a secure password manager before continuing."
                        ),
                    )
                )
                break

            provided_key = getpass.getpass("Enter your Solana private key (hidden): ").strip()
            while not provided_key:
                print(CLIFormatter.warning("Private key is required for wallet operations."))
                provided_key = getpass.getpass("Enter your Solana private key: ").strip()

            try:
                solana_public_address = derive_solana_address(provided_key)
            except WalletError as exc:
                print(CLIFormatter.error(f"Could not parse Solana private key: {exc}"))
                continue

            solana_private_key = provided_key

        print(
            CLIFormatter.info(
                f"Solana wallet configured with public address: {solana_public_address}"
            )
        )
        if solana_public_address:
            profile_updates["SAM_SOLANA_ADDRESS"] = solana_public_address

        # Step 3: Hyperliquid Configuration (Optional)
        print(CLIFormatter.header("Step 3: Hyperliquid Configuration"))
        enable_hyperliquid_input = (
            input("Enable Hyperliquid trading tools now? [y/N]: ").strip().lower()
        )

        hyperliquid_enabled = enable_hyperliquid_input in {"y", "yes"}
        hyperliquid_private_key: Optional[str] = None
        hyperliquid_wallet_address: Optional[str] = None

        if hyperliquid_enabled:
            wallet_choice = (
                input(
                    "Press Enter to import an existing Hyperliquid private key, or type 'generate' to create a new EVM wallet: "
                )
                .strip()
                .lower()
            )

            if wallet_choice in {"generate", "g", "2"}:
                hyperliquid_private_key, hyperliquid_wallet_address = generate_evm_wallet()
                print(
                    CLIFormatter.box(
                        "EVM wallet generated",
                        (
                            f"Wallet address: {hyperliquid_wallet_address}\n"
                            f"Private key (hex): {hyperliquid_private_key}\n\n"
                            "Store this private key securely (usable for Hyperliquid or other EVM integrations)."
                        ),
                    )
                )
            else:
                while True:
                    provided_key = getpass.getpass(
                        "Enter your Hyperliquid private key (hex, hidden): "
                    ).strip()
                    if not provided_key:
                        print(
                            CLIFormatter.warning("Private key is required for Hyperliquid trading.")
                        )
                        continue
                    try:
                        hyperliquid_wallet_address = derive_evm_address(provided_key)
                    except WalletError as exc:
                        print(CLIFormatter.error(f"Invalid Hyperliquid private key: {exc}"))
                        continue
                    hyperliquid_private_key = provided_key
                    break

            if hyperliquid_wallet_address is None and hyperliquid_private_key:
                hyperliquid_wallet_address = derive_evm_address(hyperliquid_private_key)

            if hyperliquid_wallet_address:
                print(
                    CLIFormatter.info(
                        "Hyperliquid account configured to use your EVM wallet address: "
                        f"{hyperliquid_wallet_address}"
                    )
                )

            profile_updates["ENABLE_HYPERLIQUID_TOOLS"] = True
            if hyperliquid_private_key:
                if not storage.store_private_key(
                    "hyperliquid_private_key", hyperliquid_private_key
                ):
                    print(CLIFormatter.error("Failed to store Hyperliquid private key securely."))
                    return 1
            if hyperliquid_wallet_address:
                profile_updates["EVM_WALLET_ADDRESS"] = hyperliquid_wallet_address
                if not storage.store_api_key(
                    "hyperliquid_account_address", hyperliquid_wallet_address
                ):
                    print(CLIFormatter.error("Failed to store Hyperliquid account address."))
                    return 1
        else:
            profile_updates["ENABLE_HYPERLIQUID_TOOLS"] = False

        # Step 4: Brave Search API (Optional)
        print(CLIFormatter.header("Step 4: Brave Search API (Optional)"))
        print(CLIFormatter.info("Enables web search functionality. Leave empty to skip."))
        print(CLIFormatter.info("Get API key from: https://api.search.brave.com/"))
        brave_key = getpass.getpass("Enter Brave API Key (optional, hidden): ").strip()

        # Step 5: Legal & Risk Disclosure
        print(CLIFormatter.header("Step 5: Legal & Risk Disclosure"))
        print(
            CLIFormatter.info(
                "SAM is an automation framework that can use tools to access networks and execute blockchain transactions you authorize."
            )
        )
        print(
            "By continuing you acknowledge: 1) blockchain transactions are irreversible; 2) market data can be unreliable; 3) you are responsible for reviewing outputs and confirming actions; 4) no warranty is provided."
        )
        accept = input("Type 'I AGREE' to accept and continue: ").strip()
        if accept.upper() != "I AGREE":
            print(CLIFormatter.warning("You must accept the disclosure to proceed."))
            return 1

        print(CLIFormatter.info("Configuring SAM with optimal defaults..."))
        fernet_key = generate_encryption_key()

        # Merge common config defaults
        profile_updates.update(
            {
                "SAM_DB_PATH": ".sam/sam_memory.db",
                "RATE_LIMITING_ENABLED": False,
                "MAX_TRANSACTION_SOL": 1000,
                "DEFAULT_SLIPPAGE": 1,
                "LOG_LEVEL": "NO",
                "SAM_LEGAL_ACCEPTED": True,
            }
        )

        env_updates["SAM_FERNET_KEY"] = fernet_key
        env_updates["SAM_DB_PATH"] = profile_updates["SAM_DB_PATH"]
        if brave_key:
            storage.store_api_key("brave_api_key", brave_key)

        # Persist profile settings
        profile_store.update(profile_updates)

        # Persist bootstrap env file
        env_path = find_env_path()
        write_env_file(env_path, env_updates)

        # Ensure DB dir exists
        db_path = profile_updates["SAM_DB_PATH"]
        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)

        # Apply to current environment
        for key, value in profile_updates.items():
            if isinstance(value, bool):
                os.environ[key] = "true" if value else "false"
            else:
                os.environ[key] = str(value)
        for key, value in env_updates.items():
            os.environ[key] = value
        Settings.refresh_from_env()

        # Store private keys securely
        if not solana_private_key:
            print(CLIFormatter.error("Solana private key was not captured."))
            return 1

        if not storage.store_private_key("default", solana_private_key):
            print(CLIFormatter.error("Failed to store Solana private key securely."))
            return 1

        if not storage.get_private_key("default"):
            print(CLIFormatter.error("Could not verify Solana private key storage."))
            return 1

        summary_lines = [f"Solana wallet: {solana_public_address}"]
        if hyperliquid_enabled and hyperliquid_wallet_address:
            summary_lines.append(f"Hyperliquid wallet: {hyperliquid_wallet_address}")

        print(
            CLIFormatter.box(
                "Wallet Summary",
                "\n".join(summary_lines),
            )
        )

        print(CLIFormatter.success("SAM configured successfully!"))
        return 0

    except KeyboardInterrupt:
        print("\n" + CLIFormatter.error("Setup cancelled."))
        return 1
    except Exception as e:
        print(CLIFormatter.error(f"Setup failed: {e}"))
        return 1
