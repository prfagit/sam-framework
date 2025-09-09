import asyncio
import logging
import os
import json
from typing import Optional, Dict, Any, List, Set

from .agent import SAMAgent
from .llm_provider import create_llm_provider
from .memory_provider import create_memory_manager
from .tools import ToolRegistry
from .middleware import LoggingMiddleware, RateLimitMiddleware, RetryMiddleware
from ..config.prompts import SOLANA_AGENT_PROMPT
from ..config.settings import Settings
from ..config.config_loader import load_middleware_config
from ..utils.crypto import decrypt_private_key
from ..utils.secure_storage import get_secure_storage
from ..utils.http_client import cleanup_http_client
from ..utils.connection_pool import cleanup_database_pool
from ..utils.rate_limiter import cleanup_rate_limiter
from ..utils.price_service import cleanup_price_service

# Integrations (kept optional behind flags)
from ..integrations.solana.solana_tools import SolanaTools, create_solana_tools
from ..integrations.pump_fun import PumpFunTools, create_pump_fun_tools
from ..integrations.dexscreener import DexScreenerTools, create_dexscreener_tools
from ..integrations.jupiter import JupiterTools, create_jupiter_tools
from ..integrations.search import SearchTools, create_search_tools
from ..integrations.smart_trader import SmartTrader, create_smart_trader_tools
from .plugins import load_plugins

logger = logging.getLogger(__name__)


class AgentBuilder:
    """Constructs a SAMAgent with configurable components.

    This provides a modular seam independent of the CLI so that other
    applications (services, notebooks, alternative CLIs) can assemble
    agents without editing the main entrypoint.
    """

    def __init__(
        self,
        system_prompt: Optional[str] = None,
    ) -> None:
        self.system_prompt = system_prompt or SOLANA_AGENT_PROMPT

    async def build(self) -> SAMAgent:
        """Build and return a fully configured SAMAgent.

        Mirrors previous CLI setup behavior to remain non-breaking.
        """
        # LLM
        llm = create_llm_provider()

        # Memory
        memory = create_memory_manager(Settings.SAM_DB_PATH)
        await getattr(memory, "initialize")()

        # Tool registry
        tools = ToolRegistry()

        # Config-driven middleware with safe defaults
        mw_config_raw = os.getenv("SAM_MIDDLEWARE_JSON")
        file_mw_cfg = load_middleware_config() if not mw_config_raw else None

        def _to_set(v: Any) -> Set[str]:
            if isinstance(v, list):
                return {str(x) for x in v}
            return set()

        def _build_middlewares_from_config(cfg: Dict[str, Any]) -> List[Any]:
            middlewares: List[Any] = []

            # logging
            log_cfg = cfg.get("logging", {}) if isinstance(cfg, dict) else {}
            if isinstance(log_cfg, dict):
                middlewares.append(
                    LoggingMiddleware(
                        include_args=bool(log_cfg.get("include_args", False)),
                        include_result=bool(log_cfg.get("include_result", False)),
                        only=_to_set(log_cfg.get("only")) or None,
                        exclude=_to_set(log_cfg.get("exclude")) or None,
                    )
                )

            # rate limit
            rl_cfg = cfg.get("rate_limit", {}) if isinstance(cfg, dict) else {}
            if isinstance(rl_cfg, dict) and bool(
                rl_cfg.get("enabled", Settings.RATE_LIMITING_ENABLED)
            ):
                type_map: Dict[str, Dict[str, Any]] = (
                    rl_cfg.get("map", {}) if isinstance(rl_cfg.get("map"), dict) else {}
                )
                default_type = rl_cfg.get("default_type")
                only = _to_set(rl_cfg.get("only")) or set(type_map.keys())
                exclude = _to_set(rl_cfg.get("exclude"))

                def limit_type_fn(name: str) -> str:
                    if name in type_map and isinstance(type_map[name], dict):
                        t = type_map[name].get("type")
                        if isinstance(t, str) and t:
                            return t
                    return default_type or name

                def identifier_fn(name: str, args: Dict[str, Any], ctx):
                    if name in type_map and isinstance(type_map[name], dict):
                        field = type_map[name].get("identifier_field")
                        if isinstance(field, str) and field:
                            return str(args.get(field, name))
                    return name

                middlewares.append(
                    RateLimitMiddleware(
                        limit_type_fn=limit_type_fn,
                        identifier_fn=identifier_fn,
                        only=only if only else None,
                        exclude=exclude if exclude else None,
                    )
                )

            # retry
            retry_cfg = cfg.get("retry", []) if isinstance(cfg, dict) else []
            if isinstance(retry_cfg, list):
                for entry in retry_cfg:
                    if not isinstance(entry, dict):
                        continue
                    middlewares.append(
                        RetryMiddleware(
                            max_retries=int(entry.get("max_retries", 2)),
                            base_delay=float(entry.get("base_delay", 0.25)),
                            only=_to_set(entry.get("only")) or None,
                            exclude=_to_set(entry.get("exclude")) or None,
                        )
                    )

            return middlewares

        if mw_config_raw:
            try:
                cfg = json.loads(mw_config_raw)
                for mw in _build_middlewares_from_config(cfg):
                    tools.add_middleware(mw)
                logger.info("Configured middlewares from SAM_MIDDLEWARE_JSON")
            except Exception as e:
                logger.warning(f"Invalid SAM_MIDDLEWARE_JSON, falling back to defaults: {e}")
                tools.add_middleware(LoggingMiddleware(include_args=False, include_result=False))
                if Settings.RATE_LIMITING_ENABLED:
                    tools.add_middleware(
                        RateLimitMiddleware(
                            limit_type_fn=lambda n: "search"
                            if n in {"search_web", "search_news"}
                            else (
                                "jupiter"
                                if n in {"get_swap_quote", "jupiter_swap"}
                                else (
                                    "transfer_sol"
                                    if n == "transfer_sol"
                                    else (
                                        "solana_rpc"
                                        if n in {"get_balance", "get_token_data"}
                                        else n
                                    )
                                )
                            ),
                            identifier_fn=lambda n, a, c: (
                                a.get("query", n)
                                if n in {"search_web", "search_news"}
                                else (
                                    a.get("mint", n)
                                    if n in {"pump_fun_buy", "pump_fun_sell"}
                                    else n
                                )
                            ),
                            only={
                                "search_web",
                                "search_news",
                                "get_swap_quote",
                                "jupiter_swap",
                                "pump_fun_buy",
                                "pump_fun_sell",
                                "get_balance",
                                "get_token_data",
                                "transfer_sol",
                            },
                        )
                    )
                tools.add_middleware(
                    RetryMiddleware(
                        max_retries=2,
                        base_delay=0.25,
                        only={"search_web", "search_news", "get_balance", "get_token_data"},
                    )
                )
                tools.add_middleware(
                    RetryMiddleware(
                        max_retries=3, base_delay=0.25, only={"get_swap_quote", "jupiter_swap"}
                    )
                )
                tools.add_middleware(
                    RetryMiddleware(
                        max_retries=2, base_delay=0.25, only={"pump_fun_buy", "pump_fun_sell"}
                    )
                )
        elif file_mw_cfg:
            try:
                for mw in _build_middlewares_from_config(file_mw_cfg):
                    tools.add_middleware(mw)
                logger.info("Configured middlewares from sam.toml")
            except Exception as e:
                logger.warning(f"Invalid middleware config in sam.toml, using defaults: {e}")
                tools.add_middleware(LoggingMiddleware(include_args=False, include_result=False))
                if Settings.RATE_LIMITING_ENABLED:
                    tools.add_middleware(
                        RateLimitMiddleware(
                            limit_type_fn=lambda n: "search"
                            if n in {"search_web", "search_news"}
                            else (
                                "jupiter"
                                if n in {"get_swap_quote", "jupiter_swap"}
                                else (
                                    "transfer_sol"
                                    if n == "transfer_sol"
                                    else (
                                        "solana_rpc"
                                        if n in {"get_balance", "get_token_data"}
                                        else n
                                    )
                                )
                            ),
                            identifier_fn=lambda n, a, c: (
                                a.get("query", n)
                                if n in {"search_web", "search_news"}
                                else (
                                    a.get("mint", n)
                                    if n in {"pump_fun_buy", "pump_fun_sell"}
                                    else n
                                )
                            ),
                            only={
                                "search_web",
                                "search_news",
                                "get_swap_quote",
                                "jupiter_swap",
                                "pump_fun_buy",
                                "pump_fun_sell",
                                "get_balance",
                                "get_token_data",
                                "transfer_sol",
                            },
                        )
                    )
                tools.add_middleware(
                    RetryMiddleware(
                        max_retries=2,
                        base_delay=0.25,
                        only={"search_web", "search_news", "get_balance", "get_token_data"},
                    )
                )
                tools.add_middleware(
                    RetryMiddleware(
                        max_retries=3, base_delay=0.25, only={"get_swap_quote", "jupiter_swap"}
                    )
                )
                tools.add_middleware(
                    RetryMiddleware(
                        max_retries=2, base_delay=0.25, only={"pump_fun_buy", "pump_fun_sell"}
                    )
                )
        else:
            # Defaults when no JSON provided
            tools.add_middleware(LoggingMiddleware(include_args=False, include_result=False))
            if Settings.RATE_LIMITING_ENABLED:
                tools.add_middleware(
                    RateLimitMiddleware(
                        limit_type_fn=lambda n: "search"
                        if n in {"search_web", "search_news"}
                        else (
                            "jupiter"
                            if n in {"get_swap_quote", "jupiter_swap"}
                            else (
                                "transfer_sol"
                                if n == "transfer_sol"
                                else ("solana_rpc" if n in {"get_balance", "get_token_data"} else n)
                            )
                        ),
                        identifier_fn=lambda n, a, c: (
                            a.get("query", n)
                            if n in {"search_web", "search_news"}
                            else (a.get("mint", n) if n in {"pump_fun_buy", "pump_fun_sell"} else n)
                        ),
                        only={
                            "search_web",
                            "search_news",
                            "get_swap_quote",
                            "jupiter_swap",
                            "pump_fun_buy",
                            "pump_fun_sell",
                            "get_balance",
                            "get_token_data",
                            "transfer_sol",
                        },
                    )
                )
            tools.add_middleware(
                RetryMiddleware(
                    max_retries=2,
                    base_delay=0.25,
                    only={"search_web", "search_news", "get_balance", "get_token_data"},
                )
            )
            tools.add_middleware(
                RetryMiddleware(
                    max_retries=3, base_delay=0.25, only={"get_swap_quote", "jupiter_swap"}
                )
            )
            tools.add_middleware(
                RetryMiddleware(
                    max_retries=2, base_delay=0.25, only={"pump_fun_buy", "pump_fun_sell"}
                )
            )

        # Secure storage and wallet discovery/migration
        secure_storage = get_secure_storage()
        private_key: Optional[str] = secure_storage.get_private_key("default")

        if not private_key and Settings.SAM_WALLET_PRIVATE_KEY:
            try:
                if Settings.SAM_WALLET_PRIVATE_KEY.startswith("gAAAAA"):
                    private_key = decrypt_private_key(Settings.SAM_WALLET_PRIVATE_KEY)
                else:
                    private_key = Settings.SAM_WALLET_PRIVATE_KEY
                if private_key:
                    secure_storage.store_private_key("default", private_key)
                    logger.info("Migrated private key from environment to secure storage")
            except Exception as e:
                logger.warning(f"Could not decrypt private key: {e}")

        # Core Solana tools (wallet-aware)
        solana_tools = SolanaTools(Settings.SAM_SOLANA_RPC_URL, private_key)

        # Create agent before registering tools (for potential caching hooks)
        agent = SAMAgent(llm=llm, tools=tools, memory=memory, system_prompt=self.system_prompt)

        # Register integrations behind flags
        if Settings.ENABLE_SOLANA_TOOLS:
            for tool in create_solana_tools(solana_tools, agent=agent):
                tools.register(tool)

        pump_tools = PumpFunTools(solana_tools)
        if Settings.ENABLE_PUMP_FUN_TOOLS:
            for tool in create_pump_fun_tools(pump_tools, agent=agent):
                tools.register(tool)

        dex_tools = DexScreenerTools()
        if Settings.ENABLE_DEXSCREENER_TOOLS:
            for tool in create_dexscreener_tools(dex_tools):
                tools.register(tool)

        jupiter_tools = JupiterTools(solana_tools)
        if Settings.ENABLE_JUPITER_TOOLS:
            for tool in create_jupiter_tools(jupiter_tools):
                tools.register(tool)

        brave_api_key = os.getenv("BRAVE_API_KEY")
        search_tools = SearchTools(api_key=brave_api_key)
        if Settings.ENABLE_SEARCH_TOOLS:
            for tool in create_search_tools(search_tools):
                tools.register(tool)

        # Optional plugin discovery (entry points or env var SAM_PLUGINS)
        try:
            load_plugins(tools, agent=agent)
        except Exception as e:
            logger.warning(f"Plugin loading encountered an issue: {e}")

        # Smart trader (pump.fun -> Jupiter fallback)
        try:
            trader = SmartTrader(pump_tools, jupiter_tools, solana_tools)
            for tool in create_smart_trader_tools(trader):
                tools.register(tool)
        except Exception as e:
            logger.warning(f"Failed to register smart trader tools: {e}")

        # Keep references (mypy-friendly) as before
        setattr(agent, "_solana_tools", solana_tools)
        setattr(agent, "_pump_tools", pump_tools)
        setattr(agent, "_dex_tools", dex_tools)
        setattr(agent, "_jupiter_tools", jupiter_tools)
        setattr(agent, "_search_tools", search_tools)
        setattr(agent, "_llm", llm)

        logger.info(f"Agent built with {len(tools.list_specs())} tools")
        return agent


async def cleanup_agent_fast() -> None:
    """Non-blocking cleanup identical to CLI’s current behavior."""
    try:
        cleanup_funcs = [
            cleanup_http_client,
            cleanup_database_pool,
            cleanup_rate_limiter,
            cleanup_price_service,
        ]
        tasks = [asyncio.create_task(func()) for func in cleanup_funcs]
        try:
            await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=0.5)
        except asyncio.TimeoutError:
            for t in tasks:
                if not t.done():
                    t.cancel()
    except Exception:
        pass
