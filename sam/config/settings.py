"""Application settings with profile-store backed persistence."""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from dotenv import load_dotenv

from .profile_store import PROFILE_KEYS, load_profile, migrate_env_to_profile
from ..utils.secure_storage import get_secure_storage

load_dotenv()

logger = logging.getLogger(__name__)

# Settings we manage inside the profile store. Secrets (API keys, private keys)
# stay in secure storage or environment variables for now.
PROFILE_CACHE = load_profile()
migrate_env_to_profile(PROFILE_KEYS)


def _reload_profile_cache() -> None:
    global PROFILE_CACHE
    PROFILE_CACHE = load_profile()


_SECURE_STORAGE = None


def _get_storage():
    global _SECURE_STORAGE
    if _SECURE_STORAGE is None:
        try:
            _SECURE_STORAGE = get_secure_storage()
        except Exception as exc:
            logger.warning("Failed to initialise secure storage: %s", exc)
            _SECURE_STORAGE = None
    return _SECURE_STORAGE


def _get_vault_api(key: str) -> Optional[str]:
    storage = _get_storage()
    if storage is None:
        return None
    try:
        return storage.get_api_key(key)
    except Exception:
        return None


def _value_from_sources(key: str, default: Any = None) -> Any:
    if key in PROFILE_CACHE:
        return PROFILE_CACHE[key]
    env_val = os.getenv(key)
    if env_val is not None:
        return env_val
    return default


def _as_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return str(value)


def _as_optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return str(value)


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        return normalized in {"1", "true", "yes", "on"}
    return default


def _as_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (ValueError, TypeError):
        return default


API_KEY_ALIASES = {
    "OPENAI_API_KEY": "openai_api_key",
    "ANTHROPIC_API_KEY": "anthropic_api_key",
    "XAI_API_KEY": "xai_api_key",
    "LOCAL_LLM_API_KEY": "local_llm_api_key",
    "ASTER_API_KEY": "aster_api",
    "BRAVE_API_KEY": "brave_api_key",
}

PRIVATE_KEY_ALIASES = {
    "ASTER_API_SECRET": "aster_api_secret",
    "SAM_WALLET_PRIVATE_KEY": "default",
    "HYPERLIQUID_PRIVATE_KEY": "hyperliquid_private_key",
}

# Forbidden patterns that indicate test/mock API keys
FORBIDDEN_KEY_PATTERNS = [
    "test-key",
    "testing-only",
    "sk-test-",
    "sk-ant-test-",
    "xai-test-",
    "mock",
    "dummy",
    "fake",
    "example",
]


def _validate_api_key(key: str, provider: str) -> str:
    """Validate that API key is not a test/mock key.

    Args:
        key: API key to validate
        provider: Provider name for error messages

    Returns:
        Validated API key

    Raises:
        ValueError: If key matches forbidden test patterns (unless in test mode)
    """
    if not key or not key.strip():
        return key

    # Allow test keys when SAM_TEST_MODE is explicitly set
    if os.getenv("SAM_TEST_MODE") == "1":
        return key

    key_lower = key.lower()
    for pattern in FORBIDDEN_KEY_PATTERNS:
        if pattern in key_lower:
            raise ValueError(
                f"Detected test/mock API key for {provider} (contains '{pattern}'). "
                "Please set a valid production API key in environment variables or secure storage. "
                "Set SAM_TEST_MODE=1 to allow test keys during development."
            )

    return key


def _api_key(alias_key: str, env_var: str) -> Optional[str]:
    alias = API_KEY_ALIASES.get(alias_key)
    storage = _get_storage()
    if storage and alias:
        try:
            stored = storage.get_api_key(alias)
        except Exception as exc:
            logger.debug("Secure storage read failed for %s: %s", alias, exc)
            stored = None
        if stored:
            return stored
    env_val = os.getenv(env_var)
    if env_val and storage and alias:
        try:
            storage.store_api_key(alias, env_val)
        except Exception as exc:
            logger.debug("Secure storage write failed for %s: %s", alias, exc)
    return env_val


def _private_secret(alias_key: str, env_var: str) -> Optional[str]:
    alias = PRIVATE_KEY_ALIASES.get(alias_key)
    storage = _get_storage()
    if storage and alias:
        try:
            stored = storage.get_private_key(alias)
        except Exception as exc:
            logger.debug("Secure storage read failed for %s: %s", alias, exc)
            stored = None
        if stored:
            return stored
    env_val = os.getenv(env_var)
    if env_val and storage and alias:
        try:
            storage.store_private_key(alias, env_val)
        except Exception as exc:
            logger.debug("Secure storage write failed for %s: %s", alias, exc)
    return env_val


class Settings:
    """Application settings resolved from profile storage and environment."""

    LLM_PROVIDER: str = "openai"

    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4o-mini"

    ANTHROPIC_API_KEY: Optional[str] = None
    ANTHROPIC_BASE_URL: Optional[str] = "https://api.anthropic.com"
    ANTHROPIC_MODEL: str = "claude-3-5-sonnet-latest"

    XAI_API_KEY: Optional[str] = None
    XAI_BASE_URL: Optional[str] = "https://api.x.ai/v1"
    XAI_MODEL: str = "grok-2-latest"

    LOCAL_LLM_BASE_URL: Optional[str] = "http://localhost:11434/v1"
    LOCAL_LLM_API_KEY: Optional[str] = None
    LOCAL_LLM_MODEL: str = "llama3.1"

    SAM_SOLANA_RPC_URL: str = "https://api.mainnet-beta.solana.com"
    SAM_SOLANA_ADDRESS: Optional[str] = None
    SAM_WALLET_PRIVATE_KEY: Optional[str] = None

    SAM_DB_PATH: str = ".sam/sam_memory.db"

    RATE_LIMITING_ENABLED: bool = False

    ENABLE_SOLANA_TOOLS: bool = True
    ENABLE_PUMP_FUN_TOOLS: bool = True
    ENABLE_DEXSCREENER_TOOLS: bool = True
    ENABLE_JUPITER_TOOLS: bool = True
    ENABLE_SEARCH_TOOLS: bool = True
    ENABLE_POLYMARKET_TOOLS: bool = True
    ENABLE_ASTER_FUTURES_TOOLS: bool = False
    ENABLE_HYPERLIQUID_TOOLS: bool = False

    ASTER_BASE_URL: str = "https://fapi.asterdex.com"
    ASTER_API_KEY: Optional[str] = None
    ASTER_API_SECRET: Optional[str] = None
    ASTER_DEFAULT_RECV_WINDOW: int = 5000

    HYPERLIQUID_API_URL: str = "https://api.hyperliquid.xyz"
    HYPERLIQUID_PRIVATE_KEY: Optional[str] = None
    HYPERLIQUID_ACCOUNT_ADDRESS: Optional[str] = None
    HYPERLIQUID_DEFAULT_SLIPPAGE: float = 0.05
    HYPERLIQUID_REQUEST_TIMEOUT: Optional[float] = None
    EVM_WALLET_ADDRESS: Optional[str] = None

    SAM_FERNET_KEY: Optional[str] = None

    MAX_TRANSACTION_SOL: float = 1000.0
    DEFAULT_SLIPPAGE: int = 1

    LOG_LEVEL: str = "INFO"
    SAM_LEGAL_ACCEPTED: bool = False
    BRAVE_API_KEY: Optional[str] = None
    BRAVE_API_KEY_PRESENT: bool = False

    @classmethod
    def _populate(cls) -> None:
        cls.LLM_PROVIDER = _as_str(_value_from_sources("LLM_PROVIDER", "openai")).lower()

        # Provider credentials (still env-backed for secrets)
        # Validate API keys to prevent test/mock keys in production
        openai_key = _as_str(_api_key("OPENAI_API_KEY", "OPENAI_API_KEY"), "")
        cls.OPENAI_API_KEY = _validate_api_key(openai_key, "OpenAI") if openai_key else ""
        cls.OPENAI_BASE_URL = _as_optional_str(_value_from_sources("OPENAI_BASE_URL"))
        cls.OPENAI_MODEL = _as_str(_value_from_sources("OPENAI_MODEL", "gpt-4o-mini"))

        anthropic_key = _as_optional_str(_api_key("ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"))
        cls.ANTHROPIC_API_KEY = (
            _validate_api_key(anthropic_key, "Anthropic") if anthropic_key else None
        )
        cls.ANTHROPIC_BASE_URL = _as_optional_str(
            _value_from_sources("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
        )
        cls.ANTHROPIC_MODEL = _as_str(
            _value_from_sources("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
        )

        xai_key = _as_optional_str(_api_key("XAI_API_KEY", "XAI_API_KEY"))
        cls.XAI_API_KEY = _validate_api_key(xai_key, "xAI") if xai_key else None
        cls.XAI_BASE_URL = _as_optional_str(
            _value_from_sources("XAI_BASE_URL", "https://api.x.ai/v1")
        )
        cls.XAI_MODEL = _as_str(_value_from_sources("XAI_MODEL", "grok-2-latest"))

        cls.LOCAL_LLM_BASE_URL = _as_optional_str(
            _value_from_sources("LOCAL_LLM_BASE_URL", "http://localhost:11434/v1")
        )
        # Local LLM keys often don't need validation (localhost)
        cls.LOCAL_LLM_API_KEY = _as_optional_str(_api_key("LOCAL_LLM_API_KEY", "LOCAL_LLM_API_KEY"))
        cls.LOCAL_LLM_MODEL = _as_str(_value_from_sources("LOCAL_LLM_MODEL", "llama3.1"))

        cls.SAM_SOLANA_RPC_URL = _as_str(
            _value_from_sources("SAM_SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
        )
        cls.SAM_SOLANA_ADDRESS = _as_optional_str(_value_from_sources("SAM_SOLANA_ADDRESS"))
        cls.SAM_WALLET_PRIVATE_KEY = _as_optional_str(
            _private_secret("SAM_WALLET_PRIVATE_KEY", "SAM_WALLET_PRIVATE_KEY")
        )

        cls.SAM_DB_PATH = _as_str(_value_from_sources("SAM_DB_PATH", ".sam/sam_memory.db"))

        cls.RATE_LIMITING_ENABLED = _as_bool(
            _value_from_sources("RATE_LIMITING_ENABLED", "false"), False
        )

        cls.ENABLE_SOLANA_TOOLS = _as_bool(_value_from_sources("ENABLE_SOLANA_TOOLS", "true"), True)
        cls.ENABLE_PUMP_FUN_TOOLS = _as_bool(
            _value_from_sources("ENABLE_PUMP_FUN_TOOLS", "true"), True
        )
        cls.ENABLE_DEXSCREENER_TOOLS = _as_bool(
            _value_from_sources("ENABLE_DEXSCREENER_TOOLS", "true"), True
        )
        cls.ENABLE_JUPITER_TOOLS = _as_bool(
            _value_from_sources("ENABLE_JUPITER_TOOLS", "true"), True
        )
        cls.ENABLE_SEARCH_TOOLS = _as_bool(_value_from_sources("ENABLE_SEARCH_TOOLS", "true"), True)
        cls.ENABLE_POLYMARKET_TOOLS = _as_bool(
            _value_from_sources("ENABLE_POLYMARKET_TOOLS", "true"), True
        )
        cls.ENABLE_ASTER_FUTURES_TOOLS = _as_bool(
            _value_from_sources("ENABLE_ASTER_FUTURES_TOOLS", "false"), False
        )
        cls.ENABLE_HYPERLIQUID_TOOLS = _as_bool(
            _value_from_sources("ENABLE_HYPERLIQUID_TOOLS", "false"), False
        )

        cls.ASTER_BASE_URL = _as_str(
            _value_from_sources("ASTER_BASE_URL", "https://fapi.asterdex.com")
        )
        aster_key = _as_optional_str(_api_key("ASTER_API_KEY", "ASTER_API_KEY"))
        cls.ASTER_API_KEY = _validate_api_key(aster_key, "Aster") if aster_key else None
        cls.ASTER_API_SECRET = _as_optional_str(
            _private_secret("ASTER_API_SECRET", "ASTER_API_SECRET")
        )
        cls.ASTER_DEFAULT_RECV_WINDOW = _as_int(
            _value_from_sources("ASTER_DEFAULT_RECV_WINDOW", 5000), 5000
        )

        cls.HYPERLIQUID_API_URL = _as_str(
            _value_from_sources("HYPERLIQUID_API_URL", "https://api.hyperliquid.xyz")
        )
        cls.HYPERLIQUID_PRIVATE_KEY = _as_optional_str(
            _private_secret("HYPERLIQUID_PRIVATE_KEY", "HYPERLIQUID_PRIVATE_KEY")
        )
        cls.HYPERLIQUID_ACCOUNT_ADDRESS = _as_optional_str(
            _value_from_sources("HYPERLIQUID_ACCOUNT_ADDRESS")
        )
        if not cls.HYPERLIQUID_ACCOUNT_ADDRESS:
            cls.HYPERLIQUID_ACCOUNT_ADDRESS = _as_optional_str(
                _get_vault_api("hyperliquid_account_address")
            )
        cls.HYPERLIQUID_DEFAULT_SLIPPAGE = _as_float(
            _value_from_sources("HYPERLIQUID_DEFAULT_SLIPPAGE", 0.05), 0.05
        )
        timeout_value = _value_from_sources("HYPERLIQUID_REQUEST_TIMEOUT")
        cls.HYPERLIQUID_REQUEST_TIMEOUT = (
            _as_float(timeout_value) if timeout_value is not None else None
        )
        cls.EVM_WALLET_ADDRESS = _as_optional_str(_value_from_sources("EVM_WALLET_ADDRESS"))

        if cls.HYPERLIQUID_ACCOUNT_ADDRESS and not cls.EVM_WALLET_ADDRESS:
            cls.EVM_WALLET_ADDRESS = cls.HYPERLIQUID_ACCOUNT_ADDRESS
        if cls.EVM_WALLET_ADDRESS and cls.HYPERLIQUID_ACCOUNT_ADDRESS != cls.EVM_WALLET_ADDRESS:
            cls.HYPERLIQUID_ACCOUNT_ADDRESS = cls.EVM_WALLET_ADDRESS

        cls.SAM_FERNET_KEY = _as_optional_str(os.getenv("SAM_FERNET_KEY"))

        cls.MAX_TRANSACTION_SOL = _as_float(
            _value_from_sources("MAX_TRANSACTION_SOL", 1000.0), 1000.0
        )
        cls.DEFAULT_SLIPPAGE = _as_int(_value_from_sources("DEFAULT_SLIPPAGE", 1), 1)

        cls.LOG_LEVEL = _as_str(_value_from_sources("LOG_LEVEL", "INFO"), "INFO")
        cls.SAM_LEGAL_ACCEPTED = _as_bool(_value_from_sources("SAM_LEGAL_ACCEPTED", False), False)
        brave_key = _as_optional_str(_api_key("BRAVE_API_KEY", "BRAVE_API_KEY"))
        cls.BRAVE_API_KEY = _validate_api_key(brave_key, "Brave") if brave_key else None
        cls.BRAVE_API_KEY_PRESENT = bool(cls.BRAVE_API_KEY)

    @classmethod
    def refresh_from_env(cls) -> None:
        _reload_profile_cache()
        cls._populate()

    @classmethod
    def validate(cls) -> bool:
        errors = []

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
        elif provider in {"openai_compat", "local"}:
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
        logger.info(f"  Solana Address: {cls.SAM_SOLANA_ADDRESS or 'not set'}")
        logger.info(f"  Database Path: {cls.SAM_DB_PATH}")
        logger.info(f"  Rate Limiting: {'Enabled' if cls.RATE_LIMITING_ENABLED else 'Disabled'}")
        logger.info(
            "  Tool Toggles: Solana=%s Pump.fun=%s DexScreener=%s Jupiter=%s Search=%s Polymarket=%s Aster=%s Hyperliquid=%s",
            cls.ENABLE_SOLANA_TOOLS,
            cls.ENABLE_PUMP_FUN_TOOLS,
            cls.ENABLE_DEXSCREENER_TOOLS,
            cls.ENABLE_JUPITER_TOOLS,
            cls.ENABLE_SEARCH_TOOLS,
            cls.ENABLE_POLYMARKET_TOOLS,
            cls.ENABLE_ASTER_FUTURES_TOOLS,
            cls.ENABLE_HYPERLIQUID_TOOLS,
        )


# Populate class attributes on import
Settings.refresh_from_env()


def setup_logging(level_override: Optional[str] = None) -> None:
    """Configure root logging using profile or override."""

    level_name = (level_override or Settings.LOG_LEVEL or "WARNING").upper()

    if level_name in {"NO", "NONE", "OFF"}:
        # Use a level above CRITICAL to ensure all logging is effectively disabled
        level = logging.CRITICAL + 10
    else:
        level = getattr(logging, level_name, logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        force=True,
    )

    logging.getLogger("sam").setLevel(level)

    # Keep noisy third-party loggers at INFO or higher to avoid chatty output
    noisy_logger_level = max(level, logging.INFO)
    for name in ("aiohttp", "solana", "urllib3"):
        logging.getLogger(name).setLevel(noisy_logger_level)
