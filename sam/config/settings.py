import os
from dotenv import load_dotenv
from typing import Optional
import logging

# Load environment variables from .env file if it exists
load_dotenv()

logger = logging.getLogger(__name__)


class Settings:
    """Application settings loaded from environment variables."""

    # LLM Configuration
    # Provider can be: 'openai' (default), 'anthropic', 'xai', 'openai_compat', 'local'
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "openai").lower()

    # OpenAI / OpenAI-compatible
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL: Optional[str] = os.getenv("OPENAI_BASE_URL")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    # Anthropic (Claude)
    ANTHROPIC_API_KEY: Optional[str] = os.getenv("ANTHROPIC_API_KEY")
    ANTHROPIC_BASE_URL: Optional[str] = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")

    # xAI (Grok) — OpenAI-compatible chat API
    XAI_API_KEY: Optional[str] = os.getenv("XAI_API_KEY")
    XAI_BASE_URL: Optional[str] = os.getenv("XAI_BASE_URL", "https://api.x.ai/v1")
    XAI_MODEL: str = os.getenv("XAI_MODEL", "grok-2-latest")

    # Local LLM via OpenAI-compatible server (e.g., Ollama/LM Studio/vLLM)
    LOCAL_LLM_BASE_URL: Optional[str] = os.getenv("LOCAL_LLM_BASE_URL", "http://localhost:11434/v1")
    LOCAL_LLM_API_KEY: Optional[str] = os.getenv("LOCAL_LLM_API_KEY")
    LOCAL_LLM_MODEL: str = os.getenv("LOCAL_LLM_MODEL", "llama3.1")

    # Solana Configuration
    SAM_SOLANA_RPC_URL: str = os.getenv("SAM_SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
    SAM_WALLET_PRIVATE_KEY: Optional[str] = os.getenv("SAM_WALLET_PRIVATE_KEY")

    # Database Configuration
    SAM_DB_PATH: str = os.getenv("SAM_DB_PATH", ".sam/sam_memory.db")

    # Rate Limiting Configuration (disabled by default for better UX)
    RATE_LIMITING_ENABLED: bool = os.getenv("RATE_LIMITING_ENABLED", "false").lower() == "true"

    # Tool/Integration Toggles (enabled by default)
    ENABLE_SOLANA_TOOLS: bool = os.getenv("ENABLE_SOLANA_TOOLS", "true").lower() == "true"
    ENABLE_PUMP_FUN_TOOLS: bool = os.getenv("ENABLE_PUMP_FUN_TOOLS", "true").lower() == "true"
    ENABLE_DEXSCREENER_TOOLS: bool = os.getenv("ENABLE_DEXSCREENER_TOOLS", "true").lower() == "true"
    ENABLE_JUPITER_TOOLS: bool = os.getenv("ENABLE_JUPITER_TOOLS", "true").lower() == "true"
    ENABLE_SEARCH_TOOLS: bool = os.getenv("ENABLE_SEARCH_TOOLS", "true").lower() == "true"
    ENABLE_POLYMARKET_TOOLS: bool = (
        os.getenv("ENABLE_POLYMARKET_TOOLS", "true").lower() == "true"
    )
    ENABLE_ASTER_FUTURES_TOOLS: bool = (
        os.getenv("ENABLE_ASTER_FUTURES_TOOLS", "false").lower() == "true"
    )

    # Aster futures configuration
    ASTER_BASE_URL: str = os.getenv("ASTER_BASE_URL", "https://fapi.asterdex.com")
    ASTER_API_KEY: Optional[str] = os.getenv("ASTER_API_KEY")
    ASTER_API_SECRET: Optional[str] = os.getenv("ASTER_API_SECRET")
    ASTER_DEFAULT_RECV_WINDOW: int = int(os.getenv("ASTER_DEFAULT_RECV_WINDOW", "5000"))

    # Encryption Configuration
    SAM_FERNET_KEY: Optional[str] = os.getenv("SAM_FERNET_KEY")

    # Safety Limits
    MAX_TRANSACTION_SOL: float = float(os.getenv("MAX_TRANSACTION_SOL", "1000"))
    DEFAULT_SLIPPAGE: int = int(os.getenv("DEFAULT_SLIPPAGE", "1"))

    # Logging Configuration
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    @classmethod
    def refresh_from_env(cls) -> None:
        """Refresh Settings class attributes from current environment.
        Use this instead of reloading the module to avoid stale references.
        """
        # LLM provider
        cls.LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").lower()

        # OpenAI / OpenAI-compatible
        cls.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
        cls.OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
        cls.OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

        # Anthropic
        cls.ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
        cls.ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
        cls.ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")

        # xAI (Grok)
        cls.XAI_API_KEY = os.getenv("XAI_API_KEY")
        cls.XAI_BASE_URL = os.getenv("XAI_BASE_URL", "https://api.x.ai/v1")
        cls.XAI_MODEL = os.getenv("XAI_MODEL", "grok-2-latest")

        # Local LLM
        cls.LOCAL_LLM_BASE_URL = os.getenv("LOCAL_LLM_BASE_URL", "http://localhost:11434/v1")
        cls.LOCAL_LLM_API_KEY = os.getenv("LOCAL_LLM_API_KEY")
        cls.LOCAL_LLM_MODEL = os.getenv("LOCAL_LLM_MODEL", "llama3.1")

        # Solana
        cls.SAM_SOLANA_RPC_URL = os.getenv(
            "SAM_SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com"
        )
        cls.SAM_WALLET_PRIVATE_KEY = os.getenv("SAM_WALLET_PRIVATE_KEY")

        # Database
        cls.SAM_DB_PATH = os.getenv("SAM_DB_PATH", ".sam/sam_memory.db")

        # Rate limiting
        cls.RATE_LIMITING_ENABLED = os.getenv("RATE_LIMITING_ENABLED", "false").lower() == "true"

        # Tool/Integration Toggles
        cls.ENABLE_SOLANA_TOOLS = os.getenv("ENABLE_SOLANA_TOOLS", "true").lower() == "true"
        cls.ENABLE_PUMP_FUN_TOOLS = os.getenv("ENABLE_PUMP_FUN_TOOLS", "true").lower() == "true"
        cls.ENABLE_DEXSCREENER_TOOLS = (
            os.getenv("ENABLE_DEXSCREENER_TOOLS", "true").lower() == "true"
        )
        cls.ENABLE_JUPITER_TOOLS = os.getenv("ENABLE_JUPITER_TOOLS", "true").lower() == "true"
        cls.ENABLE_SEARCH_TOOLS = os.getenv("ENABLE_SEARCH_TOOLS", "true").lower() == "true"
        cls.ENABLE_POLYMARKET_TOOLS = (
            os.getenv("ENABLE_POLYMARKET_TOOLS", "true").lower() == "true"
        )
        cls.ENABLE_ASTER_FUTURES_TOOLS = (
            os.getenv("ENABLE_ASTER_FUTURES_TOOLS", "false").lower() == "true"
        )

        cls.ASTER_BASE_URL = os.getenv("ASTER_BASE_URL", "https://fapi.asterdex.com")
        cls.ASTER_API_KEY = os.getenv("ASTER_API_KEY")
        cls.ASTER_API_SECRET = os.getenv("ASTER_API_SECRET")
        cls.ASTER_DEFAULT_RECV_WINDOW = int(os.getenv("ASTER_DEFAULT_RECV_WINDOW", "5000"))

        # Encryption
        cls.SAM_FERNET_KEY = os.getenv("SAM_FERNET_KEY")

        # Safety
        cls.MAX_TRANSACTION_SOL = float(os.getenv("MAX_TRANSACTION_SOL", "1000"))
        cls.DEFAULT_SLIPPAGE = int(os.getenv("DEFAULT_SLIPPAGE", "1"))

        # Logging
        cls.LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

    @classmethod
    def validate(cls) -> bool:
        """Validate that required settings are present."""
        errors = []

        # Validate LLM provider specific keys
        provider = cls.LLM_PROVIDER
        if provider == "openai":
            if not cls.OPENAI_API_KEY:
                errors.append("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        elif provider == "anthropic":
            if not cls.ANTHROPIC_API_KEY:
                errors.append("ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic")
        elif provider == "xai":
            if not cls.XAI_API_KEY:
                errors.append("XAI_API_KEY is required when LLM_PROVIDER=xai")
        elif provider in ("openai_compat", "local"):
            # For OpenAI-compatible servers, a base URL is necessary
            base = cls.OPENAI_BASE_URL if provider == "openai_compat" else cls.LOCAL_LLM_BASE_URL
            if not base:
                errors.append("An OpenAI-compatible BASE_URL is required for the selected provider")

        if not cls.SAM_FERNET_KEY:
            errors.append("SAM_FERNET_KEY is required for secure storage")

        if errors:
            logger.error("Configuration validation failed:")
            for error in errors:
                logger.error(f"  - {error}")
            return False

        return True

    @classmethod
    def log_config(cls) -> None:
        """Log current configuration (excluding sensitive data)."""
        logger.info("SAM Framework Configuration:")
        logger.info(f"  LLM Provider: {cls.LLM_PROVIDER}")
        if cls.LLM_PROVIDER == "openai":
            logger.info(f"  OpenAI Model: {cls.OPENAI_MODEL}")
            logger.info(f"  OpenAI Base URL: {cls.OPENAI_BASE_URL or 'default'}")
        elif cls.LLM_PROVIDER == "anthropic":
            logger.info(f"  Anthropic Model: {cls.ANTHROPIC_MODEL}")
            logger.info(f"  Anthropic Base URL: {cls.ANTHROPIC_BASE_URL}")
        elif cls.LLM_PROVIDER == "xai":
            logger.info(f"  xAI Model: {cls.XAI_MODEL}")
            logger.info(f"  xAI Base URL: {cls.XAI_BASE_URL}")
        elif cls.LLM_PROVIDER in ("openai_compat", "local"):
            model = cls.OPENAI_MODEL if cls.LLM_PROVIDER == "openai_compat" else cls.LOCAL_LLM_MODEL
            base = (
                cls.OPENAI_BASE_URL
                if cls.LLM_PROVIDER == "openai_compat"
                else cls.LOCAL_LLM_BASE_URL
            )
            logger.info(f"  Compatible Model: {model}")
            logger.info(f"  Compatible Base URL: {base}")
        logger.info(f"  Solana RPC: {cls.SAM_SOLANA_RPC_URL}")
        logger.info(f"  Database Path: {cls.SAM_DB_PATH}")
        logger.info(f"  Rate Limiting: {'Enabled' if cls.RATE_LIMITING_ENABLED else 'Disabled'}")
        logger.info(
            "  Tools: Solana=%s, Pump.fun=%s, DexScreener=%s, Jupiter=%s, Search=%s",
            "On" if cls.ENABLE_SOLANA_TOOLS else "Off",
            "On" if cls.ENABLE_PUMP_FUN_TOOLS else "Off",
            "On" if cls.ENABLE_DEXSCREENER_TOOLS else "Off",
            "On" if cls.ENABLE_JUPITER_TOOLS else "Off",
            "On" if cls.ENABLE_SEARCH_TOOLS else "Off",
        )
        logger.info("  Aster Futures Tools: %s", "On" if cls.ENABLE_ASTER_FUTURES_TOOLS else "Off")
        if cls.ENABLE_ASTER_FUTURES_TOOLS:
            logger.info("    Aster Base URL: %s", cls.ASTER_BASE_URL)
            logger.info(
                "    Aster API Key: %s",
                "configured" if cls.ASTER_API_KEY else "missing",
            )
        logger.info(f"  Max Transaction: {cls.MAX_TRANSACTION_SOL} SOL")
        logger.info(f"  Default Slippage: {cls.DEFAULT_SLIPPAGE}%")
        logger.info(f"  Log Level: {cls.LOG_LEVEL}")
        logger.info(f"  Wallet Configured: {'Yes' if cls.SAM_WALLET_PRIVATE_KEY else 'No'}")
        logger.info(f"  Encryption Key: {'Set' if cls.SAM_FERNET_KEY else 'Missing'}")


def setup_logging(level: Optional[str] = None) -> None:
    """Set up logging configuration."""
    log_level = level or Settings.LOG_LEVEL

    # Handle special "NO" level to disable all logging
    if log_level.upper() == "NO":
        numeric_level = logging.CRITICAL + 1  # Disable all logging
        # Don't log the configuration message when logging is disabled
    else:
        # Convert string level to logging constant
        numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    # Configure logging format
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Reduce noise from third-party libraries
    logging.getLogger("aiohttp").setLevel(max(numeric_level, logging.WARNING))
    logging.getLogger("solana").setLevel(max(numeric_level, logging.WARNING))
    logging.getLogger("urllib3").setLevel(max(numeric_level, logging.WARNING))

    # Only log configuration if logging is enabled
    if log_level.upper() != "NO":
        logger.info(f"Logging configured at {log_level.upper()} level")
