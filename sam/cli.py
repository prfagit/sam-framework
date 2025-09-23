#!/usr/bin/env python3
"""SAM Framework CLI - Interactive Solana agent interface.

Polished, minimal CLI with subtle styling, a lightweight spinner
animation, and handy slash-commands for a clean contributor UX.
"""

import asyncio
import sys
import os
import argparse
import logging
import shutil
import textwrap
from typing import Optional

try:
    import uvloop

    uvloop.install()
except ImportError:
    pass  # Fallback to standard asyncio

from .core.agent import SAMAgent
from .core.builder import AgentBuilder, cleanup_agent_fast
from .config.settings import Settings, setup_logging
from .config.plugin_policy import PluginPolicy, load_allowlist_document

# crypto helpers are used in commands; CLI no longer needs them directly
# secure storage used in subcommands; not needed at CLI top-level anymore
from .utils.cli_helpers import (
    CLIFormatter,
    show_setup_status,
    show_onboarding_guide,
    show_startup_summary,
    check_setup_status,
)
from .commands.providers import (
    list_providers as cmd_list_providers,
    show_current_provider as cmd_show_current_provider,
    switch_provider as cmd_switch_provider,
    test_provider as cmd_test_provider,
)
from .commands.onboard import run_onboarding
from .commands.keys import (
    import_private_key as cmd_import_key,
    generate_key as cmd_generate_key,
    rotate_key as cmd_rotate_key,
)
from .commands.maintenance import run_maintenance as cmd_run_maintenance
from .commands.health import run_health_check as cmd_run_health
from .commands.plugins import run_plugins_command as cmd_run_plugins
from .utils.env_files import find_env_path
from .utils.ascii_loader import show_sam_intro
# Note: integrations are now wired inside AgentBuilder

logger = logging.getLogger(__name__)


# Optional interactive UI (menus, prompts) — lazily imported to avoid hard deps
_INQ = None  # type: ignore


def _ensure_inquirer() -> bool:
    global _INQ
    if _INQ is not None:
        return True
    try:
        import inquirer as _inquirer  # type: ignore

        _INQ = _inquirer
        return True
    except Exception:
        return False


# Tool name mappings for friendly display
TOOL_DISPLAY_NAMES = {
    "get_balance": "💰 Checking balance",
    "transfer_sol": "💸 Transferring SOL",
    "get_token_data": "📊 Getting token data",
    "pump_fun_buy": "🚀 Buying on pump.fun",
    "pump_fun_sell": "📉 Selling on pump.fun",
    "get_token_trades": "📈 Getting trade data",
    "get_pump_token_info": "🔍 Getting token info",
    "search_pairs": "🔎 Searching pairs",
    "get_token_pairs": "📝 Getting token pairs",
    "get_solana_pair": "⚡ Getting pair data",
    "get_trending_pairs": "🔥 Getting trending pairs",
    "get_swap_quote": "💱 Getting swap quote",
    "jupiter_swap": "🌌 Swapping on Jupiter",
    "get_token_price": "💲 Getting token price",
    "search_web": "🔍 Searching web",
    "search_news": "📰 Searching news",
    "smart_buy": "🧠 Smart buy",
    "smart_sell": "🧠 Smart sell",
    "aster_account_balance": "💰 Checking Aster balance",
    "aster_account_info": "📊 Getting Aster account info",
    "aster_position_check": "📈 Checking Aster positions",
    "aster_trade_history": "📜 Getting Aster trade history",
    "aster_open_long": "⚡ Opening long position",
    "aster_close_position": "📉 Closing position",
    "polymarket_list_markets": "🎯 Listing Polymarket markets",
    "polymarket_opportunity_scan": "🎯 Scanning Polymarket opportunities",
    "polymarket_strategy_brief": "🧠 Crafting Polymarket strategy",
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
    """Clean, minimal banner with subtle styling (use title)."""
    left = f"🤖 {title}" if title else "🤖 SAM"
    return f"{colorize(left, Style.BOLD, Style.FG_CYAN)} {colorize('• Solana Agent •', Style.DIM, Style.FG_GRAY)}"


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
    """Initialize the SAM agent with all tools and integrations.

    Delegates to core.AgentBuilder for modular construction.
    """
    builder = AgentBuilder()
    return await builder.build()


async def cleanup_agent(agent):
    """Clean up agent resources quickly (delegated)."""
    try:
        if agent and hasattr(agent, "close"):
            # Give agent a chance to close owned resources
            await asyncio.wait_for(agent.close(), timeout=1.0)
    except Exception:
        pass
    # Also run shared cleanup (HTTP client, DB pool, rate limiter, price service)
    await cleanup_agent_fast()


async def run_interactive_session(session_id: str, no_animation: bool = False, *, clear_sessions: bool = False):
    """Run interactive REPL session."""
    # Show fast glitch intro (unless disabled)
    if not no_animation:
        await show_sam_intro("glitch")

    agent = None
    # Initialize agent
    try:
        async with Spinner("Loading SAM"):
            agent = await setup_agent()

    except Exception as e:
        print(f"{colorize('❌ Failed to initialize agent:', Style.FG_YELLOW)} {e}")
        return 1

    # Optionally clear all saved sessions before proceeding
    try:
        if clear_sessions:
            _ = await agent.memory.clear_all_sessions()
    except Exception:
        pass

    # Determine default session behavior: if session_id is 'default' or 'latest',
    # switch to the most recently updated session, creating a new dated one if none exists.
    try:
        if session_id in {None, "", "default", "latest"}:  # type: ignore[comparison-overlap]
            latest = await agent.memory.get_latest_session()
            if latest:
                session_id = latest.get("session_id", "default")
            else:
                # Create a new dated session id
                from datetime import datetime

                new_id = f"sess-{datetime.utcnow().strftime('%Y%m%d-%H%M')}"
                await agent.memory.create_session(new_id)
                session_id = new_id
    except Exception:
        pass

    # Show a friendly ready message with clean banner
    tools_count = len(agent.tools.list_specs())

    # Clear screen and show final ready state
    if supports_ansi():
        print("\033[2J\033[H")  # Clear screen

    print()
    print(banner("SAM"))
    print(
        colorize(f"✨ Ready! {tools_count} tools loaded. Type", Style.FG_GREEN),
        colorize("/help", Style.FG_CYAN),
        colorize("for commands.", Style.FG_GREEN),
    )

    # Show recent sessions (top 5) to help users resume
    try:
        recent = await agent.memory.list_sessions(limit=5)
        if recent:
            labels = []
            for s in recent:
                sid = s.get("session_id")
                mc = s.get("message_count", 0)
                mark = "(current)" if sid == session_id else ""
                labels.append(f"{sid} [{mc}] {mark}".strip())
            print(colorize("Recent sessions:", Style.FG_GRAY))
            print("  " + ", ".join(labels))
            print(colorize("Use /sessions to view/switch.", Style.FG_GRAY))
    except Exception:
        pass
    print()

    # Subtle status strip with quick hints
    try:
        provider = Settings.LLM_PROVIDER
    except Exception:
        provider = "unknown"
    try:
        w = getattr(agent, "_solana_tools", None)
        addr = getattr(w, "wallet_address", None) if w else None
        short_addr = (addr[:4] + "…" + addr[-4:]) if addr and len(addr) > 8 else (addr or "unset")
    except Exception:
        short_addr = "unset"
    print(
        colorize(
            f"[{provider}]  wallet:{short_addr}  session:{session_id}  (ESC: interrupt • Ctrl+C: exit)",
            Style.DIM,
            Style.FG_GRAY,
        )
    )
    # Defer history rendering until helpers below are defined
    print()

    # Command helpers
    try:
        MAX_CONTEXT_MSGS = int(os.getenv("SAM_MAX_CONTEXT_MSGS", "80"))
    except Exception:
        MAX_CONTEXT_MSGS = 80  # reasonable working window before auto-compaction

    def model_short() -> str:
        try:
            if Settings.LLM_PROVIDER == "openai":
                return Settings.OPENAI_MODEL
            if Settings.LLM_PROVIDER == "anthropic":
                return Settings.ANTHROPIC_MODEL
            if Settings.LLM_PROVIDER == "xai":
                return Settings.XAI_MODEL
            if Settings.LLM_PROVIDER == "local":
                return Settings.LOCAL_LLM_MODEL
            if Settings.LLM_PROVIDER == "openai_compat":
                return Settings.OPENAI_MODEL
            return Settings.LLM_PROVIDER
        except Exception:
            return "model"

    def wallet_short() -> str:
        try:
            w = getattr(agent, "_solana_tools", None)
            addr = getattr(w, "wallet_address", None) if w else None
            return (addr[:4] + "…" + addr[-4:]) if addr and len(addr) > 8 else (addr or "unset")
        except Exception:
            return "unset"

    async def show_tools():
        specs = agent.tools.list_specs()
        print()
        print(colorize("🔧 Available Tools", Style.BOLD, Style.FG_CYAN))
        print()

        # Group tools by category
        categories = {
            "💰 Wallet & Balance": ["get_balance", "transfer_sol"],
            "📊 Token Data": [
                "get_token_data",
                "get_token_pairs",
                "search_pairs",
                "get_solana_pair",
            ],
            "🧠 Smart Trader": ["smart_buy", "smart_sell"],
            "🚀 Pump.fun": [
                "pump_fun_buy",
                "pump_fun_sell",
                "get_pump_token_info",
                "get_token_trades",
            ],
            "🌌 Jupiter Swaps": ["get_swap_quote", "jupiter_swap"],
            "📈 Market Data": ["get_trending_pairs"],
            "🎯 Polymarket": [
                "polymarket_list_markets",
                "polymarket_opportunity_scan",
                "polymarket_strategy_brief",
            ],
            "🌐 Web Search": ["search_web", "search_news"],
            "⚡ Aster Futures": [
                "aster_account_balance",
                "aster_account_info",
                "aster_position_check",
                "aster_trade_history",
                "aster_open_long",
                "aster_close_position",
            ],
        }

        for category, tool_names in categories.items():
            print(colorize(category, Style.BOLD))
            for spec in specs:
                name = spec.get("name", "")
                if name in tool_names:
                    emoji = TOOL_DISPLAY_NAMES.get(name, name).split(" ")[0]
                    print(f"   {emoji} {colorize(name, Style.FG_GREEN)}")
            print()
        print()

    def show_config():
        print(colorize(hr(), Style.FG_GRAY))
        print(colorize("Configuration", Style.BOLD))

        print(f" LLM Provider: {Settings.LLM_PROVIDER}")
        if Settings.LLM_PROVIDER == "openai":
            print(f" OpenAI Model: {Settings.OPENAI_MODEL}")
            print(f" OpenAI Base URL: {Settings.OPENAI_BASE_URL or 'default'}")
        elif Settings.LLM_PROVIDER == "anthropic":
            print(f" Anthropic Model: {Settings.ANTHROPIC_MODEL}")
            print(f" Anthropic Base URL: {Settings.ANTHROPIC_BASE_URL}")
        elif Settings.LLM_PROVIDER == "xai":
            print(f" xAI Model: {Settings.XAI_MODEL}")
            print(f" xAI Base URL: {Settings.XAI_BASE_URL}")
        elif Settings.LLM_PROVIDER in ("openai_compat", "local"):
            model = (
                Settings.OPENAI_MODEL
                if Settings.LLM_PROVIDER == "openai_compat"
                else Settings.LOCAL_LLM_MODEL
            )
            base = (
                Settings.OPENAI_BASE_URL
                if Settings.LLM_PROVIDER == "openai_compat"
                else Settings.LOCAL_LLM_BASE_URL
            )
            print(f" Compatible Model: {model}")
            print(f" Compatible Base URL: {base}")
        print(f" Solana RPC: {Settings.SAM_SOLANA_RPC_URL}")
        print(f" DB Path: {Settings.SAM_DB_PATH}")
        print(f" Rate Limiting: {'Enabled' if Settings.RATE_LIMITING_ENABLED else 'Disabled'}")
        print(" Tools:")
        print(
            f"  - Solana:    {'On' if Settings.ENABLE_SOLANA_TOOLS else 'Off'}\n"
            f"  - Pump.fun:  {'On' if Settings.ENABLE_PUMP_FUN_TOOLS else 'Off'}\n"
            f"  - DexScreen: {'On' if Settings.ENABLE_DEXSCREENER_TOOLS else 'Off'}\n"
            f"  - Jupiter:   {'On' if Settings.ENABLE_JUPITER_TOOLS else 'Off'}\n"
            f"  - Polymarket: {'On' if Settings.ENABLE_POLYMARKET_TOOLS else 'Off'}\n"
            f"  - Search:    {'On' if Settings.ENABLE_SEARCH_TOOLS else 'Off'}"
        )
        brave_set = "Yes" if os.environ.get("BRAVE_API_KEY") else "No"
        print(f" Brave API Key configured: {brave_set}")
        try:
            wallet = getattr(getattr(agent, "_solana_tools", None), "wallet_address", None)
            if wallet:
                print(f" Wallet Address: {wallet}")
        except Exception:
            pass
        print(colorize(hr(), Style.FG_GRAY))

    def clear_screen():
        os.system("cls" if os.name == "nt" else "clear")
        print(banner("SAM"))

    def show_context_info():
        """Show compact status line beneath prompt area (no tokens for now)."""
        stats = agent.session_stats
        context_length = int(stats.get("context_length", 0) or 0)
        pct = min(100, int((context_length / MAX_CONTEXT_MSGS) * 100)) if MAX_CONTEXT_MSGS else 0
        line = f"model:{model_short()} • ctx:{pct}% ({context_length}/{MAX_CONTEXT_MSGS}) • wallet:{wallet_short()}"
        print(colorize(f"  {line}", Style.DIM, Style.FG_GRAY))

    def _format_history_entry(msg: dict) -> Optional[str]:
        role = msg.get("role")
        # Hide internal system notes
        if role == "system":
            return None
        if role == "tool":
            name = msg.get("name", "tool")
            content = msg.get("content", "")
            status = "done"
            try:
                import json as _json

                parsed = _json.loads(content) if isinstance(content, str) else content
                if isinstance(parsed, dict):
                    if parsed.get("success") is True:
                        status = "ok"
                    elif parsed.get("error"):
                        err = parsed.get("error")
                        status = f"error: {str(err)[:60]}"
            except Exception:
                pass
            return f"🔧 {name}: {status}"
        # user/assistant
        content = str(msg.get("content", "")).strip()
        if not content:
            return None
        if role == "user":
            return f"You: {content}"
        if role == "assistant":
            return f"Assistant: {content}"
        return f"{role}: {content}"

    async def show_history(limit: Optional[int] = None):
        try:
            ctx = await agent.memory.load_session(session_id)
        except Exception as e:
            print(colorize(f"Failed to load history: {e}", Style.FG_YELLOW))
            return
        if not ctx:
            print(colorize("No prior messages in this session.", Style.FG_YELLOW))
            return
        # Update session stats context length for status line accuracy
        try:
            agent.session_stats["context_length"] = len(ctx) + 1
        except Exception:
            pass
        print(colorize(hr(), Style.FG_GRAY))
        title = "Conversation" if limit is None else f"History (last {limit})"
        print(colorize(title, Style.BOLD))
        to_show = ctx if limit is None else ctx[-limit:]
        for m in to_show:
            line = _format_history_entry(m)
            if not line:
                continue
            if line.startswith("Assistant:"):
                print(colorize("Assistant:", Style.FG_CYAN), end=" ")
                print(wrap(line[len("Assistant:") + 1 :], width_offset=4))
            elif line.startswith("You:"):
                print(colorize("You:", Style.FG_GREEN), end=" ")
                print(wrap(line[len("You:") + 1 :], width_offset=4))
            else:
                print(colorize(line, Style.FG_GRAY))
        print(colorize(hr(), Style.FG_GRAY))

    async def list_and_maybe_switch_session():
        nonlocal session_id
        try:
            sessions = await agent.memory.list_sessions(limit=25)
        except Exception as e:
            print(colorize(f"Failed to list sessions: {e}", Style.FG_YELLOW))
            return
        if not sessions:
            print(colorize("No stored sessions found.", Style.FG_YELLOW))
            return
        print(colorize(hr(), Style.FG_GRAY))
        print(colorize("Sessions (newest first):", Style.BOLD))
        for i, s in enumerate(sessions, 1):
            sid = s.get("session_id")
            mark = " (current)" if sid == session_id else ""
            print(f" {i:2d}. {sid}  msgs:{s.get('message_count',0)}  updated:{s.get('updated_at','')}" + mark)
        print(colorize(hr(), Style.FG_GRAY))
        # Offer interactive switch if inquirer available
        if _ensure_inquirer():
            try:
                choice = _INQ.list_input(
                    "Switch to session? (ESC to cancel)",
                    choices=[s.get("session_id") for s in sessions],
                )
                if choice:
                    session_id = choice
                    print(colorize(f"Switched to session: {session_id}", Style.FG_GREEN))
                    await show_history(limit=None)
            except Exception:
                pass

    # Unified interactive helpers (inquirer when available)
    try:
        pass  # local alias to avoid top imports noise
    except Exception:
        pass

    def interactive_select(title: str, options: list[tuple[str, str]]):
        if _ensure_inquirer():
            try:
                choice_map = {label: value for label, value in options}
                choice = _INQ.list_input(title, choices=list(choice_map.keys()))  # type: ignore
                return choice_map.get(choice)
            except KeyboardInterrupt:
                return None
            except Exception as e:
                print(colorize(f"❌ Menu error: {e}", Style.FG_YELLOW))
                return None
        # No numeric fallback to keep UX consistent with settings
        print(
            colorize(
                "Interactive menu requires 'inquirer'. Type commands or run /help.", Style.FG_YELLOW
            )
        )
        print(colorize("Tip: install with `uv add inquirer`", Style.FG_GRAY))
        return None

    def interactive_text(title: str, default: str = ""):
        if _ensure_inquirer():
            try:
                return _INQ.text(title, default=default)  # type: ignore
            except KeyboardInterrupt:
                return None
            except Exception:
                pass
        prompt = f"{title}"
        if default:
            prompt += f" (default: {default})"
        prompt += ": "
        val = input(prompt).strip()
        return val or default

    # Now that helpers are defined, show the full conversation once on startup
    try:
        await show_history(limit=None)
    except Exception:
        pass

    def interactive_confirm(title: str, default: bool = False) -> bool:
        if _ensure_inquirer():
            try:
                return bool(_INQ.confirm(title, default=default))  # type: ignore
            except KeyboardInterrupt:
                return False
            except Exception:
                pass
        ans = input(f"{title} (Y/n): ").strip().lower()
        if ans == "":
            return default
        return ans in {"y", "yes"}

    # Keep input simple and stable across platforms

    last_compacted_at = 0
    try:
        while True:
            try:
                # Auto-compact when context exceeds window
                try:
                    ctx_len = int(agent.session_stats.get("context_length", 0) or 0)
                    if ctx_len >= MAX_CONTEXT_MSGS and ctx_len != last_compacted_at:
                        async with Spinner("Auto-compacting conversation"):
                            msg = await agent.compact_conversation(session_id, keep_recent=0)
                        print(colorize(f"📋 {msg}", Style.FG_GREEN))
                        # Show the now-clean summary-only conversation
                        await show_history(limit=None)
                        # Update marker to avoid repeated compaction in same state
                        last_compacted_at = int(
                            agent.session_stats.get("context_length", 0) or ctx_len
                        )
                except Exception:
                    pass

                prompt_text = colorize("🤖 ", Style.FG_CYAN) + colorize("» ", Style.DIM)
                user_input = input(prompt_text).strip()
                # Render status just below the input line for a cleaner look
                if user_input:
                    show_context_info()
                    print()  # spacer before handling output/menus

                if not user_input:
                    continue

                # Slash-commands
                if user_input in ("exit", "quit", "bye", "/exit", "/quit"):
                    print("👋 Goodbye!")
                    break
                if user_input in ("help", "/help", "/?"):
                    print_help()
                    continue
                if user_input in ("/tools",):
                    await show_tools()
                    continue
                if user_input in ("/config",):
                    show_config()
                    continue
                if user_input in ("/sessions",):
                    await list_and_maybe_switch_session()
                    continue
                if user_input in ("/clear-sessions",):
                    ok = interactive_confirm("Delete ALL saved sessions? This cannot be undone.", False)
                    if ok:
                        try:
                            deleted = await agent.memory.clear_all_sessions()
                            from datetime import datetime
                            new_id = f"sess-{datetime.utcnow().strftime('%Y%m%d-%H%M')}"
                            await agent.memory.create_session(new_id)
                            session_id = new_id
                            print(colorize(f"Deleted {deleted} sessions. Started new session: {session_id}", Style.FG_GREEN))
                            await show_history(limit=None)
                        except Exception as e:
                            print(colorize(f"Failed to clear sessions: {e}", Style.FG_YELLOW))
                    continue
                if user_input in ("/new",):
                    from datetime import datetime
                    new_id = f"sess-{datetime.utcnow().strftime('%Y%m%d-%H%M')}"
                    try:
                        await agent.memory.create_session(new_id)
                        session_id = new_id
                        print(colorize(f"Created new session: {session_id}", Style.FG_GREEN))
                    except Exception as e:
                        print(colorize(f"Failed to create session: {e}", Style.FG_YELLOW))
                    continue
                if user_input.startswith("/history"):
                    parts = user_input.split()
                    if len(parts) == 1:
                        await show_history(limit=None)
                    else:
                        if parts[1].lower() in {"all", "full", "*"}:
                            await show_history(limit=None)
                        else:
                            try:
                                n = int(parts[1])
                                await show_history(limit=max(1, min(1000, n)))
                            except Exception:
                                await show_history(limit=None)
                    continue
                if user_input in ("/settings",):
                    from .interactive_settings import run_interactive_settings

                    try:
                        if run_interactive_settings():
                            print("Settings saved! Please restart SAM for changes to take effect.")
                            print("Use: Ctrl+C to exit, then run 'uv run sam' again")
                        else:
                            print("No changes made.")
                    except Exception as e:
                        print(f"❌ Error with interactive settings: {e}")
                    continue
                if user_input in ("/provider", "/providers"):
                    sel = interactive_select(
                        "Provider actions:",
                        [
                            ("📡 List providers", "list"),
                            ("🔎 Show current provider", "current"),
                            ("🧪 Test provider", "test"),
                            ("🔄 Switch provider", "switch"),
                        ],
                    )
                    if sel == "list":
                        cmd_list_providers()
                    elif sel == "current":
                        cmd_show_current_provider()
                    elif sel == "test":
                        await cmd_test_provider(None)
                    elif sel == "switch":
                        name = interactive_select(
                            "Switch to provider:",
                            [
                                ("openai", "openai"),
                                ("anthropic", "anthropic"),
                                ("xai", "xai"),
                                ("openai_compat", "openai_compat"),
                                ("local", "local"),
                            ],
                        )
                        if name:
                            result = cmd_switch_provider(name)
                            if result == 0:
                                print(
                                    colorize(
                                        "🔄 Restart SAM to use the new provider", Style.FG_YELLOW
                                    )
                                )
                    continue
                if user_input.startswith("/switch "):
                    provider = user_input.split(" ", 1)[1] if len(user_input.split(" ")) > 1 else ""
                    if provider:
                        result = cmd_switch_provider(provider)
                        if result == 0:
                            print(
                                colorize("🔄 Restart SAM to use the new provider", Style.FG_YELLOW)
                            )
                    else:
                        print(colorize("Usage: /switch <provider>", Style.FG_YELLOW))
                    continue
                if user_input in ("/clear", "/cls"):
                    clear_screen()
                    continue
                if user_input in ("/clear-context",):
                    async with Spinner("Clearing conversation context"):
                        result = await agent.clear_context(session_id)
                    print(colorize("✨ " + result, Style.FG_GREEN))
                    continue
                if user_input in ("/compact",):
                    async with Spinner("Compacting conversation"):
                        result = await agent.compact_conversation(session_id, keep_recent=0)
                    print(colorize("📋 " + result, Style.FG_GREEN))
                    await show_history(limit=None)
                    continue
                # Diagnostics: /wallet and /balance [address]
                if user_input in ("/wallet",):
                    w = getattr(agent, "_solana_tools", None)
                    addr = getattr(w, "wallet_address", None) if w else None
                    if addr:
                        print(colorize(hr(), Style.FG_GRAY))
                        print(f" Wallet: {addr}")
                        print(colorize(hr(), Style.FG_GRAY))
                    else:
                        print(colorize("No wallet configured.", Style.FG_YELLOW))
                    continue
                if user_input.startswith("/balance"):
                    parts = user_input.split()
                    address = parts[1] if len(parts) > 1 else None
                    if not address:
                        address = interactive_text("Address (leave blank for default):", "")
                    w = getattr(agent, "_solana_tools", None)
                    if not w:
                        print(colorize("Solana tools unavailable.", Style.FG_YELLOW))
                        continue
                    async with Spinner("Querying balance"):
                        result = await w.get_balance(address or None)
                    print(colorize(hr(), Style.FG_GRAY))
                    print(wrap(str(result)))
                    print(colorize(hr(), Style.FG_GRAY))
                    continue

                # Unknown slash command → show help
                if user_input.startswith("/"):
                    print_help()
                    continue

                # Process user input through agent with enhanced spinner
                current_spinner = None

                def tool_callback(tool_name: str, tool_args: dict):
                    """Update spinner when tools are used."""
                    nonlocal current_spinner
                    if current_spinner:
                        display_name = TOOL_DISPLAY_NAMES.get(tool_name, f"🔧 {tool_name}")
                        current_spinner.update_status(display_name)

                # Run agent in a task we can cancel via ESC
                async def _listen_for_escape(cancel_task: asyncio.Task):
                    """Listen for ESC key and cancel the current task. Portable best-effort."""
                    try:
                        if os.name == "nt":
                            import msvcrt  # type: ignore

                            while not cancel_task.done():
                                if msvcrt.kbhit():
                                    ch = msvcrt.getch()
                                    if ch in (b"\x1b",):  # ESC
                                        cancel_task.cancel()
                                        return
                                await asyncio.sleep(0.03)
                        else:
                            import termios
                            import tty
                            import select

                            fd = sys.stdin.fileno()
                            old_settings = termios.tcgetattr(fd)
                            try:
                                tty.setcbreak(fd)
                                while not cancel_task.done():
                                    r, _, _ = select.select([sys.stdin], [], [], 0.05)
                                    if r:
                                        ch = sys.stdin.read(1)
                                        if ch == "\x1b":  # ESC
                                            cancel_task.cancel()
                                            return
                                    await asyncio.sleep(0.01)
                            finally:
                                # Restore terminal settings
                                try:
                                    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                                except Exception:
                                    pass
                    except Exception:
                        # Fallback: do nothing if listener fails
                        return

                async with Spinner("🤔 Thinking — press ESC to interrupt") as spinner:
                    current_spinner = spinner
                    agent.tool_callback = tool_callback
                    task = asyncio.create_task(agent.run(user_input, session_id))
                    esc_task = asyncio.create_task(_listen_for_escape(task))
                    try:
                        response = await task
                    except asyncio.CancelledError:
                        print(colorize("\n⏹️  Interrupted.", Style.FG_YELLOW))
                        continue
                    finally:
                        agent.tool_callback = None
                        # Ensure listener stops
                        try:
                            esc_task.cancel()
                        except Exception:
                            pass

                # Render response in a clean block with better formatting
                print()
                print(colorize("│", Style.FG_CYAN), end=" ")

                # Format response with casual styling
                formatted_response = response.replace("\n", f"\n{colorize('│', Style.FG_CYAN)} ")
                print(formatted_response)
                print()

            except KeyboardInterrupt:
                # Exit immediately on Ctrl+C as requested
                raise
            except EOFError:
                break
            except Exception as e:
                logger.error(f"Error in session: {e}")
                print(f"{colorize('😅 Oops:', Style.FG_YELLOW)} {e}")
    finally:
        # Fast cleanup with timeout
        if agent:
            try:
                await asyncio.wait_for(cleanup_agent(agent), timeout=2.0)
            except asyncio.TimeoutError:
                # Force exit if cleanup takes too long
                pass
            except Exception:
                # Ignore all cleanup errors
                pass

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
    print(f"  {colorize('/settings', Style.FG_GREEN)}       Interactive settings editor")
    print(f"  {colorize('/clear', Style.FG_GREEN)}         Clear screen")
    print(f"  {colorize('/clear-context', Style.FG_GREEN)} Clear conversation context")
    print(f"  {colorize('/clear-sessions', Style.FG_GREEN)} Delete ALL saved sessions")
    print(f"  {colorize('/compact', Style.FG_GREEN)}       Compact conversation history")
    print(f"  {colorize('exit', Style.FG_GREEN)}           Exit SAM")
    print()
    print(colorize("⌨️  Shortcuts", Style.BOLD, Style.FG_CYAN))
    print("  • ESC: interrupt current agent run")
    print("  • Ctrl+C: exit immediately")
    print()
    print(colorize("💡 Try saying:", Style.BOLD, Style.FG_CYAN))
    print("   • check balance")
    print("   • buy 0.01 sol of [token_address]")
    print("   • show trending pairs")
    print("   • search for BONK pairs")
    print("   • /history 10  # show last 10 messages")
    print()


def _onboarded_flag_path() -> str:
    # Keep alongside the default DB in .sam
    root = os.getcwd()
    sam_dir = os.path.join(root, ".sam")
    os.makedirs(sam_dir, exist_ok=True)
    return os.path.join(sam_dir, ".onboarded")


def import_private_key():
    """Shim delegating to commands.keys.import_private_key."""
    from .commands.keys import import_private_key as _import

    return _import()


def import_private_key_legacy():
    """Shim delegating to commands.keys.import_private_key_legacy."""
    from .commands.keys import import_private_key_legacy as _legacy

    return _legacy()


def generate_key():
    """Shim delegating to commands.keys.generate_key."""
    from .commands.keys import generate_key as _gen

    return _gen()


# moved to sam.commands.maintenance.run_maintenance


# Provider subcommands moved to sam.cli.commands.providers


async def test_provider(provider_name: Optional[str] = None):
    """Shim delegating to commands.providers.test_provider."""
    from .commands.providers import test_provider as _test

    return await _test(provider_name)


# moved to sam.commands.health.run_health_check


async def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="SAM Framework CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Run command (default)
    run_parser = subparsers.add_parser("run", help="Start the interactive agent")
    run_parser.add_argument(
        "--session", "-s", default="default", help="Session ID for conversation context"
    )
    run_parser.add_argument(
        "--no-animation", action="store_true", help="Skip startup animation for faster loading"
    )
    run_parser.add_argument(
        "--clear-sessions",
        action="store_true",
        help="Delete all saved conversation sessions before starting",
    )

    # Key management
    key_parser = subparsers.add_parser("key", help="Private key management")
    key_subparsers = key_parser.add_subparsers(dest="key_action")
    key_subparsers.add_parser("import", help="Import private key securely")
    key_subparsers.add_parser("generate", help="Generate new encryption key")
    rotate_parser = key_subparsers.add_parser(
        "rotate", help="Rotate Fernet encryption key and re-encrypt secrets"
    )
    rotate_parser.add_argument(
        "--new-key",
        dest="new_key",
        help="Optional base64 key to rotate to (otherwise a new key is generated)",
    )
    rotate_parser.add_argument(
        "--yes",
        "-y",
        dest="assume_yes",
        action="store_true",
        help="Skip interactive confirmation",
    )

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
    subparsers.add_parser("debug", help="Show runtime plugins and middleware")

    plugins_parser = subparsers.add_parser(
        "plugins", help="Manage plugin trust policy and allowlist"
    )
    plugins_subparsers = plugins_parser.add_subparsers(dest="plugins_action")
    trust_parser = plugins_subparsers.add_parser(
        "trust", help="Compute hash and record plugin module in allowlist"
    )
    trust_parser.add_argument("module", help="Importable module path for plugin")
    trust_parser.add_argument(
        "--entry-point", dest="entry_point", help="Optional entry point name to map"
    )
    trust_parser.add_argument(
        "--label", dest="label", help="Optional friendly name stored in allowlist"
    )

    # Global arguments
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Set log level",
    )

    args = parser.parse_args()

    # Default to run command if no command specified
    if args.command is None:
        args.command = "run"
        # Create a simple namespace for session since it belongs to run subparser
        if not hasattr(args, "session"):
            args.session = "default"
        if not hasattr(args, "no_animation"):
            args.no_animation = False

    # Setup logging
    setup_logging(args.log_level)

    # Handle different commands
    if args.command == "key":
        if hasattr(args, "key_action") and args.key_action:
            if args.key_action == "import":
                return cmd_import_key()
            elif args.key_action == "generate":
                return cmd_generate_key()
            elif args.key_action == "rotate":
                return cmd_rotate_key(
                    getattr(args, "new_key", None), assume_yes=getattr(args, "assume_yes", False)
                )
        else:
            print("Usage: sam key {import|generate|rotate}")
            return 1

    if args.command == "provider":
        if hasattr(args, "provider_action") and args.provider_action:
            if args.provider_action == "list":
                cmd_list_providers()
                return 0
            elif args.provider_action == "current":
                cmd_show_current_provider()
                return 0
            elif args.provider_action == "switch":
                if hasattr(args, "name"):
                    return cmd_switch_provider(args.name)
                else:
                    print(
                        colorize(
                            "❌ Provider name required. Usage: sam provider switch <name>",
                            Style.FG_YELLOW,
                        )
                    )
                    return 1
            elif args.provider_action == "test":
                return await cmd_test_provider(getattr(args, "provider", None))
        else:
            print("Usage: sam provider {list|current|switch|test}")
            return 1

    if args.command == "setup":
        show_setup_status(verbose=True)
        status = check_setup_status()
        if status["issues"]:
            print(f"\n{CLIFormatter.info('Run setup guide?')} ", end="")
            if input("(Y/n): ").strip().lower() != "n":
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
        return await cmd_run_maintenance()

    if args.command == "health":
        return await cmd_run_health()

    if args.command == "onboard":
        return await run_onboarding()

    if args.command == "plugins":
        return cmd_run_plugins(args)

    if args.command == "debug":
        # Build agent to introspect configured middlewares and registered tools
        from importlib.metadata import entry_points
        from .core.builder import AgentBuilder

        agent = await AgentBuilder().build()
        print(colorize("🔌 Plugins", Style.BOLD, Style.FG_CYAN))
        policy = PluginPolicy.from_env()
        status = "enabled" if policy.enabled else "disabled"
        print(f" Policy: {status} (allow unverified: {'on' if policy.allow_unverified else 'off'})")
        print(f" Allowlist: {policy.allowlist_path}")
        doc = load_allowlist_document(policy.allowlist_path)
        modules = doc.get("modules", {})
        if modules:
            print(" Trusted modules:")
            for name, meta in list(modules.items())[:10]:
                digest = meta.get("sha256", "<missing>") if isinstance(meta, dict) else str(meta)
                label = meta.get("label") if isinstance(meta, dict) else None
                note = f" ({label})" if label else ""
                print(f"  - {name}{note} :: {digest[:12]}…")
            if len(modules) > 10:
                print(f"    … {len(modules) - 10} more")
        else:
            print(" Trusted modules: none recorded")
        try:
            eps_tools = [e.name for e in entry_points(group="sam.plugins")]
        except Exception:
            eps_tools = []
        try:
            eps_llm = [e.name for e in entry_points(group="sam.llm_providers")]
        except Exception:
            eps_llm = []
        try:
            eps_mem = [e.name for e in entry_points(group="sam.memory_backends")]
        except Exception:
            eps_mem = []
        try:
            eps_sec = [e.name for e in entry_points(group="sam.secure_storage")]
        except Exception:
            eps_sec = []

        print(" Entry points:")
        print(f"  - sam.plugins: {', '.join(eps_tools) or 'none'}")
        print(f"  - sam.llm_providers: {', '.join(eps_llm) or 'none'}")
        print(f"  - sam.memory_backends: {', '.join(eps_mem) or 'none'}")
        print(f"  - sam.secure_storage: {', '.join(eps_sec) or 'none'}")

        env_plugins = os.getenv("SAM_PLUGINS") or ""
        env_mem = os.getenv("SAM_MEMORY_BACKEND") or ""
        print(" Environment:")
        print(f"  - SAM_PLUGINS: {env_plugins or 'unset'}")
        print(f"  - SAM_MEMORY_BACKEND: {env_mem or 'unset'}")

        # Middlewares (best-effort introspection)
        print(colorize("\n🧩 Middlewares", Style.BOLD, Style.FG_CYAN))
        try:
            mws = getattr(agent.tools, "_middlewares", [])
            for mw in mws:
                print(f"  - {mw.__class__.__name__}")
        except Exception as e:
            print(f"  (could not inspect middlewares: {e})")

        # Tools list
        print(colorize("\n🔧 Tools", Style.BOLD, Style.FG_CYAN))
        for spec in agent.tools.list_specs():
            ns = spec.get("namespace")
            vers = spec.get("version")
            name = spec.get("name")
            label = name if not ns else f"{ns}/{name}"
            if vers:
                label = f"{label} ({vers})"
            print(f"  - {label}")

        return 0

    if args.command == "run":
        # FIRST: Ensure .env is loaded before checking anything
        from dotenv import load_dotenv

        # Prefer a stable .env location (CWD/repo) over module path
        env_path = find_env_path()
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

            env_path = find_env_path()
            load_dotenv(env_path, override=True)
            Settings.refresh_from_env()

            print(CLIFormatter.success("Setup complete! Starting SAM agent..."))
            print()

        # Show startup summary for configured systems
        show_startup_summary()

        Settings.log_config()
        session_id = getattr(args, "session", "default")
        no_animation = getattr(args, "no_animation", False)
        return await run_interactive_session(session_id, no_animation, clear_sessions=getattr(args, "clear_sessions", False))

    return 1


def app():
    """Entry point for the CLI application."""
    import os

    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        # Force immediate exit without cleanup
        print("\n👋 Goodbye!")
        os._exit(0)  # Force exit without cleanup
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        print(f"❌ Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    app()
