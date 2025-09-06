#!/usr/bin/env python3
"""SAM Framework CLI - Interactive Solana agent interface.

Polished, minimal CLI with subtle styling, a lightweight spinner
animation, and handy slash-commands for a clean contributor UX.
"""

import asyncio
import sys
import os
import getpass
import argparse
import logging
import shutil
import textwrap
import time

try:
    import uvloop
    uvloop.install()
except ImportError:
    pass  # Fallback to standard asyncio

from .core.agent import SAMAgent
from .core.llm_provider import LLMProvider, create_llm_provider
from .core.memory import MemoryManager
from .core.tools import ToolRegistry
from .config.prompts import SOLANA_AGENT_PROMPT
from .config.settings import Settings, setup_logging
from .utils.crypto import encrypt_private_key, decrypt_private_key, generate_encryption_key
from .utils.secure_storage import get_secure_storage
from .utils.http_client import cleanup_http_client
from .utils.connection_pool import cleanup_database_pool
from .utils.rate_limiter import cleanup_rate_limiter
from .utils.cli_helpers import (
    CLIFormatter, show_setup_status, show_onboarding_guide,
    show_first_run_experience, show_startup_summary, check_setup_status
)
from .utils.price_service import cleanup_price_service
from .integrations.solana.solana_tools import SolanaTools, create_solana_tools
from .integrations.pump_fun import PumpFunTools, create_pump_fun_tools
from .integrations.dexscreener import DexScreenerTools, create_dexscreener_tools
from .integrations.jupiter import JupiterTools, create_jupiter_tools
from .integrations.search import SearchTools, create_search_tools

logger = logging.getLogger(__name__)


# Tool name mappings for friendly display
TOOL_DISPLAY_NAMES = {
    'get_balance': '💰 Checking balance',
    'transfer_sol': '💸 Transferring SOL',
    'get_token_data': '📊 Getting token data',
    'pump_fun_buy': '🚀 Buying on pump.fun',
    'pump_fun_sell': '📉 Selling on pump.fun',
    'get_token_trades': '📈 Getting trade data',
    'get_pump_token_info': '🔍 Getting token info',
    'search_pairs': '🔎 Searching pairs',
    'get_token_pairs': '📝 Getting token pairs',
    'get_solana_pair': '⚡ Getting pair data',
    'get_trending_pairs': '🔥 Getting trending pairs',
    'get_swap_quote': '💱 Getting swap quote',
    'jupiter_swap': '🌌 Swapping on Jupiter',
    'search_web': '🔍 Searching web',
    'search_news': '📰 Searching news'
}


# ---------------------------
# Minimal Styling Utilities
# ---------------------------
class Style:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"

    # Foreground (subtle palette)
    FG_CYAN = "\033[36m"
    FG_GREEN = "\033[32m"
    FG_YELLOW = "\033[33m"
    FG_BLUE = "\033[34m"
    FG_GRAY = "\033[90m"


def supports_ansi() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def colorize(text: str, *styles: str) -> str:
    if not supports_ansi() or not styles:
        return text
    return f"{''.join(styles)}{text}{Style.RESET}"


def term_width(default: int = 80) -> int:
    try:
        return shutil.get_terminal_size().columns
    except (OSError, ValueError):
        return default


def hr(char: str = "─") -> str:
    return char * max(20, min(120, term_width()))


def wrap(text: str, width_offset: int = 0) -> str:
    width = max(40, min(120, term_width() - width_offset))
    return "\n".join(textwrap.wrap(text, width=width)) if text else ""


def banner(title: str) -> str:
    """Clean, minimal banner with subtle styling."""
    return f"{colorize('🤖 SAM', Style.BOLD, Style.FG_CYAN)} {colorize('• Solana Agent •', Style.DIM, Style.FG_GRAY)}"


class Spinner:
    """Lightweight async spinner for long-running tasks."""

    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, message: str = "Working", interval: float = 0.08):
        self.message = message
        self.interval = interval
        self._task = None
        self._running = False
        self._current_status = message

    async def __aenter__(self):
        if supports_ansi():
            self._running = True
            self._task = asyncio.create_task(self._spin())
        else:
            # Fallback single-line status for non-ANSI terminals
            sys.stdout.write(f"{self.message}...\n")
            sys.stdout.flush()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.stop()

    def update_status(self, new_message: str):
        """Update the spinner message during execution."""
        self._current_status = new_message

    async def _spin(self):
        i = 0
        while self._running:
            frame = self.FRAMES[i % len(self.FRAMES)]
            line = f" {colorize(frame, Style.FG_CYAN)} {colorize(self._current_status, Style.DIM)}"
            sys.stdout.write(f"\r{line}")
            sys.stdout.flush()
            i += 1
            await asyncio.sleep(self.interval)

    async def stop(self):
        if self._running:
            self._running = False
            if self._task:
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
            # Clear spinner line
            sys.stdout.write("\r" + " " * max(0, term_width() - 1) + "\r")
            sys.stdout.flush()

async def setup_agent() -> SAMAgent:
    """Initialize the SAM agent with all tools and integrations."""
    
    # Initialize core components
    llm = create_llm_provider()
    
    memory = MemoryManager(Settings.SAM_DB_PATH)
    await memory.initialize()  # Initialize database tables
    tools = ToolRegistry()
    
    # Initialize Solana tools with secure storage
    private_key = None
    secure_storage = get_secure_storage()
    
    # Try to get private key from secure storage first
    private_key = secure_storage.get_private_key("default")
    
    # Fallback to environment variable (for backward compatibility)
    if not private_key and Settings.SAM_WALLET_PRIVATE_KEY:
        try:
            # Try to decrypt if it looks encrypted, otherwise use as-is
            if Settings.SAM_WALLET_PRIVATE_KEY.startswith('gAAAAA'):
                private_key = decrypt_private_key(Settings.SAM_WALLET_PRIVATE_KEY)
            else:
                private_key = Settings.SAM_WALLET_PRIVATE_KEY
                
            # Store in secure storage for next time
            if private_key:
                secure_storage.store_private_key("default", private_key)
                logger.info("Migrated private key from environment to secure storage")
                
        except Exception as e:
            logger.warning(f"Could not decrypt private key: {e}")
    
    solana_tools = SolanaTools(Settings.SAM_SOLANA_RPC_URL, private_key)
    
    # Create agent first (with empty tool registry initially)
    agent = SAMAgent(
        llm=llm,
        tools=tools,
        memory=memory,
        system_prompt=SOLANA_AGENT_PROMPT
    )
    
    # Register Solana tools (with agent reference for caching)
    for tool in create_solana_tools(solana_tools, agent=agent):
        tools.register(tool)
    
    # Initialize and register Pump.fun tools (with solana_tools for signing)
    pump_tools = PumpFunTools(solana_tools)
    for tool in create_pump_fun_tools(pump_tools, agent=agent):
        tools.register(tool)
    
    # Initialize and register DexScreener tools
    dex_tools = DexScreenerTools()
    for tool in create_dexscreener_tools(dex_tools):
        tools.register(tool)
    
    # Initialize and register Jupiter tools
    jupiter_tools = JupiterTools(solana_tools)
    for tool in create_jupiter_tools(jupiter_tools):
        tools.register(tool)
    
    # Initialize and register Search tools
    brave_api_key = os.getenv("BRAVE_API_KEY")  # Optional
    search_tools = SearchTools(api_key=brave_api_key)
    for tool in create_search_tools(search_tools):
        tools.register(tool)
    
    # Store references to tools that need cleanup
    agent._solana_tools = solana_tools
    agent._pump_tools = pump_tools
    agent._dex_tools = dex_tools
    agent._jupiter_tools = jupiter_tools
    agent._search_tools = search_tools
    agent._llm = llm
    
    logger.info(f"Agent initialized with {len(tools.list_specs())} tools")
    return agent


async def cleanup_agent(agent):
    """Clean up agent resources."""
    try:
        # Close network connections
        if hasattr(agent, '_solana_tools') and hasattr(agent._solana_tools, 'close'):
            await agent._solana_tools.close()
        
        if hasattr(agent, '_jupiter_tools') and hasattr(agent._jupiter_tools, 'close'):
            await agent._jupiter_tools.close()
        
        if hasattr(agent, '_pump_tools') and hasattr(agent._pump_tools, 'close'):
            await agent._pump_tools.close()
        
        if hasattr(agent, '_search_tools') and hasattr(agent._search_tools, 'close'):
            await agent._search_tools.close()
        
        if hasattr(agent, '_llm') and hasattr(agent._llm, 'close'):
            await agent._llm.close()
        
        # Cleanup shared resources
        await cleanup_http_client()
        await cleanup_database_pool()
        await cleanup_rate_limiter()
        await cleanup_price_service()
        
        logger.info("Agent cleanup completed")
    except Exception as e:
        logger.error(f"Error during agent cleanup: {e}")


async def run_interactive_session(session_id: str):
    """Run interactive REPL session."""
    # Banner
    print(banner("SAM Framework — Solana Agent Middleware"))
    print(colorize("Type /help for commands. Ctrl+C to exit.", Style.DIM))
    print()

    agent = None
    # Initialize agent with a spinner
    try:
        async with Spinner("Initializing agent"):
            agent = await setup_agent()
    except Exception as e:
        print(f"{colorize('❌ Failed to initialize agent:', Style.FG_YELLOW)} {e}")
        return 1

    # Show a friendly ready message
    tools_count = len(agent.tools.list_specs())
    print()
    print(banner("SAM"))
    print(colorize(f"✨ Ready! {tools_count} tools loaded. Type", Style.FG_GREEN), colorize("/help", Style.FG_CYAN), colorize("for commands.", Style.FG_GREEN))
    print()

    # Command helpers
    async def show_tools():
        specs = agent.tools.list_specs()
        print()
        print(colorize("🔧 Available Tools", Style.BOLD, Style.FG_CYAN))
        print()
        
        # Group tools by category
        categories = {
            "💰 Wallet & Balance": ["get_balance", "transfer_sol"],
            "📊 Token Data": ["get_token_data", "get_token_pairs", "search_pairs", "get_solana_pair"],
            "🚀 Pump.fun": ["pump_fun_buy", "pump_fun_sell", "get_pump_token_info", "get_token_trades"],
            "🌌 Jupiter Swaps": ["get_swap_quote", "jupiter_swap"],
            "📈 Market Data": ["get_trending_pairs"],
            "🌐 Web Search": ["search_web", "search_news"]
        }
        
        for category, tool_names in categories.items():
            print(colorize(category, Style.BOLD))
            for spec in specs:
                name = spec.get("name", "")
                if name in tool_names:
                    emoji = TOOL_DISPLAY_NAMES.get(name, name).split(' ')[0]
                    print(f"   {emoji} {colorize(name, Style.FG_GREEN)}")
            print()
        print()

    def show_config():
        print(colorize(hr(), Style.FG_GRAY))
        print(colorize("Configuration", Style.BOLD))
        from .config.settings import Settings
        print(f" LLM Provider: {Settings.LLM_PROVIDER}")
        if Settings.LLM_PROVIDER == 'openai':
            print(f" OpenAI Model: {Settings.OPENAI_MODEL}")
            print(f" OpenAI Base URL: {Settings.OPENAI_BASE_URL or 'default'}")
        elif Settings.LLM_PROVIDER == 'anthropic':
            print(f" Anthropic Model: {Settings.ANTHROPIC_MODEL}")
            print(f" Anthropic Base URL: {Settings.ANTHROPIC_BASE_URL}")
        elif Settings.LLM_PROVIDER == 'xai':
            print(f" xAI Model: {Settings.XAI_MODEL}")
            print(f" xAI Base URL: {Settings.XAI_BASE_URL}")
        elif Settings.LLM_PROVIDER in ('openai_compat', 'local'):
            model = Settings.OPENAI_MODEL if Settings.LLM_PROVIDER == 'openai_compat' else Settings.LOCAL_LLM_MODEL
            base = Settings.OPENAI_BASE_URL if Settings.LLM_PROVIDER == 'openai_compat' else Settings.LOCAL_LLM_BASE_URL
            print(f" Compatible Model: {model}")
            print(f" Compatible Base URL: {base}")
        print(f" Solana RPC: {Settings.SAM_SOLANA_RPC_URL}")
        print(f" DB Path: {Settings.SAM_DB_PATH}")
        print(f" Rate Limiting: {'Enabled' if Settings.RATE_LIMITING_ENABLED else 'Disabled'}")
        brave_set = 'Yes' if os.environ.get('BRAVE_API_KEY') else 'No'
        print(f" Brave API Key configured: {brave_set}")
        try:
            wallet = getattr(getattr(agent, '_solana_tools', None), 'wallet_address', None)
            if wallet:
                print(f" Wallet Address: {wallet}")
        except Exception:
            pass
        print(colorize(hr(), Style.FG_GRAY))

    def clear_screen():
        os.system('cls' if os.name == 'nt' else 'clear')
        print(banner("SAM"))

    def show_context_info():
        """Display context info below the input field."""
        stats = agent.session_stats
        context_length = stats.get("context_length", 0)
        total_tokens = stats.get("total_tokens", 0)
        requests = stats.get("requests", 0)
        
        info_parts = []
        if context_length > 0:
            info_parts.append(f"Context: {context_length} msgs")
        if total_tokens > 0:
            info_parts.append(f"Tokens: {total_tokens:,}")
        if requests > 0:
            info_parts.append(f"Requests: {requests}")
        
        if info_parts:
            info_str = " • ".join(info_parts)
            print(colorize(f"  {info_str}", Style.DIM, Style.FG_GRAY))

    try:
        while True:
            try:
                show_context_info()
                user_input = input(colorize("🤖 ", Style.FG_CYAN) + colorize("» ", Style.DIM)).strip()

                if not user_input:
                    continue

                # Slash-commands
                if user_input in ('exit', 'quit', 'bye', '/exit', '/quit'):
                    print("👋 Goodbye!")
                    break
                if user_input in ('help', '/help'):
                    print_help()
                    continue
                if user_input in ('/tools',):
                    await show_tools()
                    continue
                if user_input in ('/config',):
                    show_config()
                    continue
                if user_input in ('/provider', '/providers'):
                    list_providers()
                    continue
                if user_input.startswith('/switch '):
                    provider = user_input.split(' ', 1)[1] if len(user_input.split(' ')) > 1 else ""
                    if provider:
                        result = switch_provider(provider)
                        if result == 0:
                            print(colorize("🔄 Restart SAM to use the new provider", Style.FG_YELLOW))
                    else:
                        print(colorize("Usage: /switch <provider>", Style.FG_YELLOW))
                    continue
                if user_input in ('/clear', '/cls'):
                    clear_screen()
                    continue
                if user_input in ('/clear-context',):
                    async with Spinner("Clearing conversation context"):
                        result = await agent.clear_context(session_id)
                    print(colorize("✨ " + result, Style.FG_GREEN))
                    continue
                if user_input in ('/compact',):
                    async with Spinner("Compacting conversation"):
                        result = await agent.compact_conversation(session_id)
                    print(colorize("📋 " + result, Style.FG_GREEN))
                    continue

                # Diagnostics: /wallet and /balance [address]
                if user_input in ('/wallet',):
                    w = getattr(agent, '_solana_tools', None)
                    addr = getattr(w, 'wallet_address', None) if w else None
                    if addr:
                        print(colorize(hr(), Style.FG_GRAY))
                        print(f" Wallet: {addr}")
                        print(colorize(hr(), Style.FG_GRAY))
                    else:
                        print(colorize("No wallet configured.", Style.FG_YELLOW))
                    continue
                if user_input.startswith('/balance'):
                    parts = user_input.split()
                    address = parts[1] if len(parts) > 1 else None
                    w = getattr(agent, '_solana_tools', None)
                    if not w:
                        print(colorize("Solana tools unavailable.", Style.FG_YELLOW))
                        continue
                    async with Spinner("Querying balance"):
                        result = await w.get_balance(address)
                    print(colorize(hr(), Style.FG_GRAY))
                    print(wrap(str(result)))
                    print(colorize(hr(), Style.FG_GRAY))
                    continue

                # Process user input through agent with enhanced spinner
                current_spinner = None
                
                def tool_callback(tool_name: str, tool_args: dict):
                    """Update spinner when tools are used."""
                    nonlocal current_spinner
                    if current_spinner:
                        display_name = TOOL_DISPLAY_NAMES.get(tool_name, f"🔧 {tool_name}")
                        current_spinner.update_status(display_name)
                
                async with Spinner("🤔 Thinking") as spinner:
                    current_spinner = spinner
                    agent.tool_callback = tool_callback
                    try:
                        response = await agent.run(user_input, session_id)
                    finally:
                        agent.tool_callback = None

                # Render response in a clean block with better formatting
                print()
                print(colorize("│", Style.FG_CYAN), end=" ")
                
                # Format response with casual styling
                formatted_response = response.replace('\n', f'\n{colorize("│", Style.FG_CYAN)} ')
                print(formatted_response)
                print()

            except KeyboardInterrupt:
                print(colorize("\n🫡 Later!", Style.FG_CYAN))
                break
            except EOFError:
                break
            except Exception as e:
                logger.error(f"Error in session: {e}")
                print(f"{colorize('😅 Oops:', Style.FG_YELLOW)} {e}")
    finally:
        # Always cleanup resources
        if agent:
            await cleanup_agent(agent)

    return 0


def print_help():
    """Print available commands and usage."""
    print()
    print(colorize("🛠️  Quick Commands", Style.BOLD, Style.FG_CYAN))
    print(f"  {colorize('/help', Style.FG_GREEN)}          Show this help")
    print(f"  {colorize('/tools', Style.FG_GREEN)}         List available tools")
    print(f"  {colorize('/provider', Style.FG_GREEN)}      List LLM providers")
    print(f"  {colorize('/switch <name>', Style.FG_GREEN)}  Switch LLM provider")
    print(f"  {colorize('/config', Style.FG_GREEN)}        Show configuration")
    print(f"  {colorize('/clear', Style.FG_GREEN)}         Clear screen")
    print(f"  {colorize('/clear-context', Style.FG_GREEN)} Clear conversation context")
    print(f"  {colorize('/compact', Style.FG_GREEN)}       Compact conversation history")
    print(f"  {colorize('exit', Style.FG_GREEN)}           Exit SAM")
    print()
    print(colorize("💡 Try saying:", Style.BOLD, Style.FG_CYAN))
    print("   • check balance")
    print("   • buy 0.01 sol of [token_address]")
    print("   • show trending pairs")
    print("   • search for BONK pairs")
    print()


# ---------------------------
# Onboarding
# ---------------------------
def _onboarded_flag_path() -> str:
    # Keep alongside the default DB in .sam
    root = os.getcwd()
    sam_dir = os.path.join(root, ".sam")
    os.makedirs(sam_dir, exist_ok=True)
    return os.path.join(sam_dir, ".onboarded")

def _find_env_path() -> str:
    """Determine a good location for the .env file.
    Prefers existing .env in CWD; else sam_framework/.env next to example; else CWD/.env
    """
    cwd_env = os.path.join(os.getcwd(), ".env")
    if os.path.exists(cwd_env):
        return cwd_env
    repo_env_example = os.path.join(os.getcwd(), "sam_framework", ".env.example")
    if os.path.exists(repo_env_example):
        return os.path.join(os.path.dirname(repo_env_example), ".env")
    return cwd_env


def _write_env_file(path: str, values: dict) -> None:
    existing = {}
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                for line in f:
                    if "=" in line and not line.strip().startswith("#"):
                        k, v = line.strip().split("=", 1)
                        existing[k] = v
        except Exception:
            pass
    existing.update(values)
    lines = ["# SAM Framework configuration", "# Generated by onboarding", ""]
    for k, v in existing.items():
        lines.append(f"{k}={v}")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


async def run_onboarding() -> int:
    """Streamlined onboarding with provider selection."""
    print(banner("SAM Setup"))
    print()

    try:
        # Step 1: LLM Provider Configuration
        print(colorize("Step 1: LLM Configuration", Style.BOLD, Style.FG_CYAN))
        print(colorize("Select your LLM provider:", Style.DIM))
        print("1. OpenAI")
        print("2. Anthropic (Claude)")
        print("3. xAI (Grok)")
        print("4. Local OpenAI-compatible (e.g., Ollama)")
        provider_choice = (input("Choice (1-4, default: 1): ").strip() or "1")

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
            print()
            print(colorize("OpenAI API Key", Style.DIM))
            print(colorize("Get your key: https://platform.openai.com/api-keys", Style.DIM))
            openai_key = getpass.getpass("Enter your OpenAI API Key (hidden): ").strip()
            while not openai_key:
                print(colorize("API key is required.", Style.FG_YELLOW))
                openai_key = getpass.getpass("Enter your OpenAI API Key: ").strip()
            print()
            model = input("OpenAI Model (default: gpt-4o-mini): ").strip() or "gpt-4o-mini"
            base_url = input("OpenAI Base URL (blank for default): ").strip()
            config_data.update({
                "OPENAI_API_KEY": openai_key,
                "OPENAI_MODEL": model,
            })
            if base_url:
                config_data["OPENAI_BASE_URL"] = base_url

        elif provider == "anthropic":
            print()
            print(colorize("Anthropic API Key", Style.DIM))
            print(colorize("Get your key: https://console.anthropic.com/", Style.DIM))
            ant_key = getpass.getpass("Enter your Anthropic API Key (hidden): ").strip()
            while not ant_key:
                print(colorize("API key is required.", Style.FG_YELLOW))
                ant_key = getpass.getpass("Enter your Anthropic API Key: ").strip()
            model = input("Anthropic Model (default: claude-3-5-sonnet-latest): ").strip() or "claude-3-5-sonnet-latest"
            base_url = input("Anthropic Base URL (blank for default): ").strip()
            config_data.update({
                "ANTHROPIC_API_KEY": ant_key,
                "ANTHROPIC_MODEL": model,
            })
            if base_url:
                config_data["ANTHROPIC_BASE_URL"] = base_url

        elif provider == "xai":
            print()
            print(colorize("xAI (Grok) API Key", Style.DIM))
            print(colorize("Docs: https://docs.x.ai/", Style.DIM))
            xai_key = getpass.getpass("Enter your xAI API Key (hidden): ").strip()
            while not xai_key:
                print(colorize("API key is required.", Style.FG_YELLOW))
                xai_key = getpass.getpass("Enter your xAI API Key: ").strip()
            model = input("xAI Model (default: grok-2-latest): ").strip() or "grok-2-latest"
            base_url = input("xAI Base URL (default: https://api.x.ai/v1): ").strip() or "https://api.x.ai/v1"
            config_data.update({
                "XAI_API_KEY": xai_key,
                "XAI_MODEL": model,
                "XAI_BASE_URL": base_url,
            })

        elif provider == "local":
            print()
            print(colorize("Local OpenAI-compatible endpoint (e.g., Ollama/LM Studio)", Style.DIM))
            base_url = input("Base URL (default: http://localhost:11434/v1): ").strip() or "http://localhost:11434/v1"
            model = input("Model name (e.g., llama3.1): ").strip() or "llama3.1"
            api_key = getpass.getpass("API Key if required (optional, hidden): ").strip()
            config_data.update({
                "LOCAL_LLM_BASE_URL": base_url,
                "LOCAL_LLM_MODEL": model,
            })
            if api_key:
                config_data["LOCAL_LLM_API_KEY"] = api_key

        # Step 2: Solana Configuration
        print()
        print(colorize("Step 2: Solana Configuration", Style.BOLD, Style.FG_CYAN))
        print(colorize("Choose RPC endpoint (default: mainnet):", Style.DIM))
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

        # Solana Private Key
        print()
        print(colorize("This enables trading and balance checks. Your key is encrypted and stored securely.", Style.DIM))
        private_key = getpass.getpass("Enter your Solana private key (hidden): ").strip()
        while not private_key:
            print(colorize("Private key is required for wallet operations.", Style.FG_YELLOW))
            private_key = getpass.getpass("Enter your Solana private key: ").strip()

        # Step 3: Brave Search API (Optional)
        print()
        print(colorize("Step 3: Brave Search API (Optional)", Style.BOLD, Style.FG_CYAN))
        print(colorize("Enables web search functionality. Leave empty to skip.", Style.DIM))
        print(colorize("Get API key from: https://api.search.brave.com/", Style.DIM))
        brave_key = getpass.getpass("Enter Brave API Key (optional, hidden): ").strip()

        # Auto-generate everything else with sensible defaults
        print()
        print(colorize("Configuring SAM with optimal defaults...", Style.DIM))
        
        fernet_key = generate_encryption_key()
        
        # Merge common config defaults
        config_data.update({
            "SAM_FERNET_KEY": fernet_key,
            "SAM_DB_PATH": ".sam/sam_memory.db",
            "SAM_SOLANA_RPC_URL": rpc_url,
            "RATE_LIMITING_ENABLED": "false",
            "MAX_TRANSACTION_SOL": "1000",
            "DEFAULT_SLIPPAGE": "1",
            "LOG_LEVEL": "NO",
        })
        
        # Add Brave API key if provided
        if brave_key:
            config_data["BRAVE_API_KEY"] = brave_key
        
        # Create/update .env file at preferred location
        env_path = _find_env_path()
        _write_env_file(env_path, config_data)
        
        # Create database directory if it doesn't exist
        db_path = config_data["SAM_DB_PATH"]
        db_dir = os.path.dirname(db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
        
        # Apply to current environment
        for key, value in config_data.items():
            os.environ[key] = value

        # Refresh Settings from environment to reflect new values consistently
        Settings.refresh_from_env()
        
        # Store private key securely
        storage = get_secure_storage()
        success = storage.store_private_key("default", private_key)
        
        if not success:
            print(colorize("❌ Failed to store private key securely.", Style.FG_YELLOW))
            return 1
            
        # Verify storage worked
        test_key = storage.get_private_key("default")
        if not test_key:
            print(colorize("❌ Could not verify private key storage.", Style.FG_YELLOW))
            return 1

        print(colorize("✅ SAM configured successfully!", Style.FG_GREEN))
        return 0
        
    except KeyboardInterrupt:
        print("\n❌ Setup cancelled.")
        return 1
    except Exception as e:
        print(f"{colorize('❌ Setup failed:', Style.FG_YELLOW)} {e}")
        return 1


def import_private_key():
    """Import and securely store a private key using keyring."""
    print("🔐 Secure Private Key Import")
    print("This will encrypt and store your private key in the system keyring.")
    
    try:
        # Test keyring access
        secure_storage = get_secure_storage()
        keyring_test = secure_storage.test_keyring_access()
        
        if not keyring_test["keyring_available"]:
            print("❌ System keyring is not available. Falling back to environment variable method.")
            return import_private_key_legacy()
        
        print("✅ System keyring is available")
        
        # Get user ID (default to "default" for now)
        user_id = input("Enter user ID (or press enter for 'default'): ").strip() or "default"
        
        # Check if key already exists
        existing_key = secure_storage.get_private_key(user_id)
        if existing_key:
            overwrite = input(f"Private key for '{user_id}' already exists. Overwrite? (y/N): ").strip().lower()
            if overwrite != 'y':
                print("❌ Import cancelled")
                return 1
        
        private_key = getpass.getpass("Enter your private key (hidden): ")
        if not private_key.strip():
            print("❌ Private key cannot be empty")
            return 1
        
        # Store in secure storage
        success = secure_storage.store_private_key(user_id, private_key.strip())
        
        if success:
            print(f"✅ Private key securely stored in system keyring for user: {user_id}")
            print("The key is encrypted and will be automatically loaded when needed.")
            
            # Test retrieval
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


def import_private_key_legacy():
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
        
        # Encrypt the private key
        encrypted_key = encrypt_private_key(private_key.strip())
        
        # Store in environment (for this session) and suggest permanent storage
        os.environ["SAM_WALLET_PRIVATE_KEY"] = encrypted_key
        
        print("✅ Private key encrypted and stored for this session")
        print("To make permanent, add this to your .env file:")
        print(f"SAM_WALLET_PRIVATE_KEY={encrypted_key}")
        
        return 0
        
    except Exception as e:
        print(f"❌ Failed to import private key: {e}")
        return 1


def generate_key():
    """Generate a new Fernet encryption key and store it securely."""
    try:
        # Generate key
        key = generate_encryption_key()
        
        # Try to store in environment file automatically
        env_path = _find_env_path()
        if os.path.exists(env_path):
            print(f"🔐 Generated new encryption key and updated {env_path}")
            # Update existing .env file
            env_values = {}
            try:
                with open(env_path, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and '=' in line and not line.startswith('#'):
                            k, v = line.split('=', 1)
                            env_values[k] = v
            except Exception:
                pass
            
            env_values["SAM_FERNET_KEY"] = key
            _write_env_file(env_path, env_values)
            
            # Apply to current environment
            os.environ["SAM_FERNET_KEY"] = key
            print("✅ Key generated and configured automatically")
        else:
            print("🔐 Generated new encryption key")
            print(f"Key stored in new .env file: {env_path}")
            _write_env_file(env_path, {"SAM_FERNET_KEY": key})
            os.environ["SAM_FERNET_KEY"] = key
        
        print("🔒 Key is ready for use. Restart your session to apply changes.")
        return 0
        
    except Exception as e:
        print(f"❌ Failed to generate key: {e}")
        print("Manual fallback: Add SAM_FERNET_KEY to your .env file")
        return 1


async def run_maintenance():
    """Run database maintenance tasks."""
    print("🔧 SAM Framework Maintenance")
    print("Running database cleanup and maintenance tasks...")
    
    try:
        # Initialize components
        from .core.memory import MemoryManager
        from .utils.error_handling import get_error_tracker
        
        memory = MemoryManager(Settings.SAM_DB_PATH)
        await memory.initialize()
        
        error_tracker = await get_error_tracker()
        
        # Run cleanup tasks
        print("\n📊 Current database stats:")
        stats = await memory.get_session_stats()
        size_info = await memory.get_database_size()
        
        print(f"  Sessions: {stats.get('sessions', 0)}")
        print(f"  Preferences: {stats.get('preferences', 0)}")
        print(f"  Trades: {stats.get('trades', 0)}")
        print(f"  Secure data: {stats.get('secure_data', 0)}")
        print(f"  Database size: {size_info.get('size_mb', 0)} MB")
        
        # Clean up old sessions (30 days)
        print("\n🧹 Cleaning up old sessions...")
        deleted_sessions = await memory.cleanup_old_sessions(30)
        print(f"  Deleted {deleted_sessions} old sessions")
        
        # Clean up old trades (90 days)
        print("\n🧹 Cleaning up old trades...")
        deleted_trades = await memory.cleanup_old_trades(90)
        print(f"  Deleted {deleted_trades} old trades")
        
        # Clean up old errors (30 days)
        print("\n🧹 Cleaning up old errors...")
        deleted_errors = await error_tracker.cleanup_old_errors(30)
        print(f"  Deleted {deleted_errors} old error records")
        
        # Vacuum database
        print("\n🔧 Vacuuming database...")
        vacuum_success = await memory.vacuum_database()
        if vacuum_success:
            print("  Database vacuum completed successfully")
        else:
            print("  Database vacuum failed")
        
        # Final stats
        print("\n📊 Post-maintenance stats:")
        final_stats = await memory.get_session_stats()
        final_size = await memory.get_database_size()
        
        print(f"  Sessions: {final_stats.get('sessions', 0)}")
        print(f"  Database size: {final_size.get('size_mb', 0)} MB")
        
        size_saved = size_info.get('size_mb', 0) - final_size.get('size_mb', 0)
        if size_saved > 0:
            print(f"  Space saved: {size_saved:.2f} MB")
        
        print("\n✅ Maintenance completed successfully")
        return 0
        
    except Exception as e:
        print(f"❌ Maintenance failed: {e}")
        return 1


def list_providers():
    """List available LLM providers."""
    providers = {
        "openai": {
            "name": "OpenAI",
            "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
            "description": "OpenAI GPT models"
        },
        "anthropic": {
            "name": "Anthropic Claude",
            "models": ["claude-3-5-sonnet-latest", "claude-3-5-haiku-latest", "claude-3-opus-latest"],
            "description": "Anthropic Claude models"
        },
        "xai": {
            "name": "xAI Grok",
            "models": ["grok-2-latest", "grok-beta"],
            "description": "xAI Grok models"
        },
        "local": {
            "name": "Local/Ollama",
            "models": ["llama3.1", "llama3.2", "mixtral", "custom"],
            "description": "Local OpenAI-compatible server"
        }
    }
    
    print(colorize("🤖 Available LLM Providers", Style.BOLD, Style.FG_CYAN))
    print()
    
    current = Settings.LLM_PROVIDER
    for key, info in providers.items():
        marker = "→" if key == current else " "
        status = colorize("(current)", Style.FG_GREEN) if key == current else ""
        print(f" {marker} {colorize(key, Style.BOLD)} - {info['name']} {status}")
        print(f"   {colorize(info['description'], Style.DIM)}")
        print(f"   Models: {', '.join(info['models'][:3])}{'...' if len(info['models']) > 3 else ''}")
        print()


def show_current_provider():
    """Show current provider configuration."""
    provider = Settings.LLM_PROVIDER
    print(colorize("🔧 Current Provider Configuration", Style.BOLD, Style.FG_CYAN))
    print()
    print(f"Provider: {colorize(provider, Style.FG_GREEN)}")
    
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
    print()


def switch_provider(provider_name: str):
    """Switch to a different LLM provider."""
    valid_providers = ["openai", "anthropic", "xai", "local", "openai_compat"]
    
    if provider_name not in valid_providers:
        print(f"❌ Invalid provider. Choose from: {', '.join(valid_providers)}")
        return 1
    
    # Find and update .env file
    env_path = _find_env_path()
    
    try:
        # Read existing .env
        config_data = {}
        if os.path.exists(env_path):
            with open(env_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and '=' in line and not line.startswith('#'):
                        key, value = line.split('=', 1)
                        config_data[key] = value
        
        # Update provider
        config_data["LLM_PROVIDER"] = provider_name
        
        # Write back to .env
        _write_env_file(env_path, config_data)
        
        # Update current environment
        os.environ["LLM_PROVIDER"] = provider_name
        Settings.LLM_PROVIDER = provider_name
        
        print(f"✅ Switched to provider: {colorize(provider_name, Style.FG_GREEN)}")
        
        # Check if required API key is configured
        key_configured = False
        if provider_name == "openai":
            key_configured = bool(Settings.OPENAI_API_KEY)
        elif provider_name == "anthropic":
            key_configured = bool(Settings.ANTHROPIC_API_KEY)
        elif provider_name == "xai":
            key_configured = bool(Settings.XAI_API_KEY)
        elif provider_name == "local":
            key_configured = True  # API key not required for local
        
        if not key_configured:
            print(f"⚠️  {provider_name.upper()}_API_KEY not configured. Add it to your .env file.")
            print("   Or run 'uv run sam onboard' to reconfigure.")
        
        return 0
        
    except Exception as e:
        print(f"❌ Failed to switch provider: {e}")
        return 1


async def test_provider(provider_name: str = None):
    """Test connection to LLM provider."""
    if not provider_name:
        provider_name = Settings.LLM_PROVIDER
    
    print(f"🧪 Testing {provider_name} provider...")
    
    try:
        # Temporarily switch provider for testing
        original_provider = Settings.LLM_PROVIDER
        Settings.LLM_PROVIDER = provider_name
        
        # Create provider instance
        llm = create_llm_provider()
        
        # Test with a simple message
        test_messages = [
            {"role": "user", "content": "Say 'Hello from SAM!' and nothing else."}
        ]
        
        async with Spinner(f"Testing {provider_name} connection"):
            response = await llm.chat_completion(test_messages)
        
        # Restore original provider
        Settings.LLM_PROVIDER = original_provider
        
        if response and response.content:
            print(f"✅ {provider_name} test successful!")
            print(f"   Response: {response.content.strip()}")
            if response.usage:
                tokens = response.usage.get('total_tokens', 0)
                if tokens > 0:
                    print(f"   Tokens used: {tokens}")
            return 0
        else:
            print(f"❌ {provider_name} test failed: Empty response")
            return 1
            
    except Exception as e:
        # Restore original provider
        Settings.LLM_PROVIDER = original_provider
        print(f"❌ {provider_name} test failed: {e}")
        return 1
    finally:
        if 'llm' in locals():
            await llm.close()


async def run_health_check():
    """Run health checks on SAM framework components."""
    print("🏥 SAM Framework Health Check")
    
    try:
        from .utils.error_handling import get_health_checker, get_error_tracker
        from .utils.secure_storage import get_secure_storage
        from .utils.rate_limiter import get_rate_limiter
        from .core.memory import MemoryManager
        
        health_checker = get_health_checker()
        
        # Register health checks
        async def database_health():
            memory = MemoryManager(Settings.SAM_DB_PATH)
            await memory.initialize()
            stats = await memory.get_session_stats()
            return {"status": "ok", "stats": stats}
        
        async def secure_storage_health():
            storage = get_secure_storage()
            test_results = storage.test_keyring_access()
            return test_results
        
        async def rate_limiter_health():
            limiter = await get_rate_limiter()
            # Get stats about the in-memory rate limiter
            num_keys = len(limiter.request_history)
            return {"status": "healthy", "active_keys": num_keys}
        
        async def error_tracker_health():
            tracker = await get_error_tracker()
            stats = await tracker.get_error_stats(24)
            return {"recent_errors": stats.get("total_errors", 0)}
        
        health_checker.register_health_check("database", database_health, 0)
        health_checker.register_health_check("secure_storage", secure_storage_health, 0)
        health_checker.register_health_check("rate_limiter", rate_limiter_health, 0)
        health_checker.register_health_check("error_tracker", error_tracker_health, 0)
        
        # Run health checks
        results = await health_checker.run_health_checks()
        
        print("\n🔍 Component Health Status:")
        
        all_healthy = True
        for component, result in results.items():
            if result:
                status = result.get("status", "unknown")
                if status == "healthy":
                    print(f"  ✅ {component}: {status}")
                else:
                    print(f"  ❌ {component}: {status}")
                    if "error" in result:
                        print(f"     Error: {result['error']}")
                    all_healthy = False
                
                # Show additional details
                if "details" in result:
                    details = result["details"]
                    if isinstance(details, dict):
                        for key, value in details.items():
                            if key != "status":
                                print(f"     {key}: {value}")
            else:
                print(f"  ❓ {component}: no data")
                all_healthy = False
        
        # Show recent errors
        error_tracker = await get_error_tracker()
        error_stats = await error_tracker.get_error_stats(24)
        
        total_errors = error_stats.get("total_errors", 0)
        if total_errors > 0:
            print(f"\n⚠️  {total_errors} errors in the last 24 hours")
            
            severity_counts = error_stats.get("severity_counts", {})
            for severity, count in severity_counts.items():
                print(f"     {severity}: {count}")
            
            critical_errors = error_stats.get("critical_errors", [])
            if critical_errors:
                print("\n🚨 Recent critical errors:")
                for error in critical_errors[:3]:
                    print(f"     {error['timestamp']}: {error['component']} - {error['error_message']}")
        else:
            print("\n✅ No errors in the last 24 hours")
        
        if all_healthy and total_errors == 0:
            print("\n🎉 All systems healthy!")
            return 0
        else:
            print("\n⚠️  Some issues detected")
            return 1
        
    except Exception as e:
        print(f"❌ Health check failed: {e}")
        return 1


async def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="SAM Framework CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Run command (default)
    run_parser = subparsers.add_parser("run", help="Start the interactive agent")
    run_parser.add_argument("--session", "-s", default="default", help="Session ID for conversation context")
    
    # Key management
    key_parser = subparsers.add_parser("key", help="Private key management")
    key_subparsers = key_parser.add_subparsers(dest="key_action")
    key_subparsers.add_parser("import", help="Import private key securely")
    key_subparsers.add_parser("generate", help="Generate new encryption key")
    
    # Provider management
    provider_parser = subparsers.add_parser("provider", help="LLM provider management")
    provider_subparsers = provider_parser.add_subparsers(dest="provider_action")
    provider_subparsers.add_parser("list", help="List available providers")
    provider_subparsers.add_parser("current", help="Show current provider")
    switch_parser = provider_subparsers.add_parser("switch", help="Switch to different provider")
    switch_parser.add_argument("name", help="Provider name (openai, anthropic, xai, local)")
    test_parser = provider_subparsers.add_parser("test", help="Test provider connection")
    test_parser.add_argument("--provider", help="Provider to test (defaults to current)")
    
    # Other commands
    subparsers.add_parser("setup", help="Check setup status and configuration")
    subparsers.add_parser("tools", help="List available tools")
    subparsers.add_parser("health", help="System health check")
    subparsers.add_parser("maintenance", help="Database maintenance and cleanup")
    subparsers.add_parser("onboard", help="Run onboarding setup")
    
    # Global arguments
    parser.add_argument("--log-level", default=None,
                       choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                       help="Set log level")
    
    args = parser.parse_args()
    
    # Default to run command if no command specified
    if args.command is None:
        args.command = "run"
        # Create a simple namespace for session since it belongs to run subparser
        if not hasattr(args, 'session'):
            args.session = 'default'
    
    # Setup logging
    setup_logging(args.log_level)
    
    # Handle different commands
    if args.command == "key":
        if hasattr(args, 'key_action') and args.key_action:
            if args.key_action == "import":
                return import_private_key()
            elif args.key_action == "generate":
                return generate_key()
        else:
            print("Usage: sam key {import|generate}")
            return 1
    
    if args.command == "provider":
        if hasattr(args, 'provider_action') and args.provider_action:
            if args.provider_action == "list":
                list_providers()
                return 0
            elif args.provider_action == "current":
                show_current_provider()
                return 0
            elif args.provider_action == "switch":
                if hasattr(args, 'name'):
                    return switch_provider(args.name)
                else:
                    print(colorize("❌ Provider name required. Usage: sam provider switch <name>", Style.FG_YELLOW))
                    return 1
            elif args.provider_action == "test":
                return await test_provider(getattr(args, 'provider', None))
        else:
            print("Usage: sam provider {list|current|switch|test}")
            return 1
    
    if args.command == "setup":
        show_setup_status(verbose=True)
        status = check_setup_status()
        if status["issues"]:
            print(f"\n{CLIFormatter.info('Run setup guide?')} ", end="")
            if input("(Y/n): ").strip().lower() != 'n':
                show_onboarding_guide()
        return 0
    
    if args.command == "tools":
        # Add tool specs without initializing full agents
        solana_specs = [
            {"name": "get_balance", "description": "Check SOL balance for addresses"},
            {"name": "transfer_sol", "description": "Send SOL between addresses"},
            {"name": "get_token_data", "description": "Fetch token metadata"},
        ]

        pump_specs = [
            {"name": "pump_fun_buy", "description": "Buy tokens on pump.fun"},
            {"name": "pump_fun_sell", "description": "Sell tokens on pump.fun"},
            {"name": "get_token_trades", "description": "View trading activity"},
            {"name": "get_pump_token_info", "description": "Get token information"},
        ]

        jupiter_specs = [
            {"name": "get_swap_quote", "description": "Get swap quotes"},
            {"name": "jupiter_swap", "description": "Execute token swaps"},
        ]

        dex_specs = [
            {"name": "search_pairs", "description": "Find trading pairs"},
            {"name": "get_token_pairs", "description": "Get pairs for tokens"},
            {"name": "get_solana_pair", "description": "Detailed pair information"},
            {"name": "get_trending_pairs", "description": "Top performing pairs"},
        ]

        search_specs = [
            {"name": "search_web", "description": "Search internet content"},
            {"name": "search_news", "description": "Search news articles"},
        ]

        print(colorize("🔧 Available Tools", Style.BOLD, Style.FG_CYAN))
        print()

        for category, specs in [
            ("💰 Wallet & Balance", solana_specs),
            ("🚀 Pump.fun", pump_specs),
            ("🌌 Jupiter Swaps", jupiter_specs),
            ("📈 Market Data", dex_specs),
            ("🌐 Web Search", search_specs),
        ]:
            print(colorize(category, Style.BOLD))
            for spec in specs:
                print(f"   • {spec['name']}: {spec['description']}")
            print()

        return 0
    
    if args.command == "maintenance":
        return await run_maintenance()
    
    if args.command == "health":
        return await run_health_check()
    
    if args.command == "onboard":
        return await run_onboarding()
    
    if args.command == "run":
        # FIRST: Ensure .env is loaded before checking anything
        from dotenv import load_dotenv

        # Prefer a stable .env location (CWD/repo) over module path
        env_path = _find_env_path()
        load_dotenv(env_path, override=True)

        # Refresh Settings from current environment to avoid stale class attributes
        Settings.refresh_from_env()
        
        # Only require onboarding if primary LLM provider API key is missing.
        # Wallet setup can be done separately via `sam key import`.
        need_onboarding = False
        if Settings.LLM_PROVIDER == "openai" and not Settings.OPENAI_API_KEY:
            need_onboarding = True
        elif Settings.LLM_PROVIDER == "anthropic" and not Settings.ANTHROPIC_API_KEY:
            need_onboarding = True
        elif Settings.LLM_PROVIDER == "xai" and not Settings.XAI_API_KEY:
            need_onboarding = True
        # local/openai_compat may not need API keys in some cases
        
        if need_onboarding:
            print(CLIFormatter.info("Welcome to SAM! Let's get you set up quickly..."))
            result = await run_onboarding()
            if result != 0:
                return result
            
            # Reload environment and refresh Settings after onboarding
            from dotenv import load_dotenv
            env_path = _find_env_path()
            load_dotenv(env_path, override=True)
            Settings.refresh_from_env()
            
            print(CLIFormatter.success("Setup complete! Starting SAM agent..."))
            print()
        
        # Show startup summary for configured systems
        show_startup_summary()
        
        Settings.log_config()
        session_id = getattr(args, 'session', 'default')
        return await run_interactive_session(session_id)
    
    return 1


def app():
    """Entry point for the CLI application."""
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        print(f"❌ Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    app()
