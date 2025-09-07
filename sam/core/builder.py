import asyncio
import logging
import os
from typing import Optional

from .agent import SAMAgent
from .llm_provider import create_llm_provider
from .memory import MemoryManager
from .tools import ToolRegistry
from ..config.prompts import SOLANA_AGENT_PROMPT
from ..config.settings import Settings
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
        memory = MemoryManager(Settings.SAM_DB_PATH)
        await memory.initialize()

        # Tool registry
        tools = ToolRegistry()

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

