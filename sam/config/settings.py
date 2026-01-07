"""Application settings with profile-store backed persistence."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any, List, Optional

from dotenv import load_dotenv

from .profile_store import PROFILE_KEYS, load_profile, migrate_env_to_profile
from ..utils.secure_storage import get_secure_storage

if TYPE_CHECKING:
    from ..utils.secure_storage import BaseSecretStore

load_dotenv()

logger = logging.getLogger(__name__)

# Settings we manage inside the profile store. Secrets (API keys, private keys)
# stay in secure storage or environment variables for now.
PROFILE_CACHE = load_profile()
migrate_env_to_profile(PROFILE_KEYS)


def _reload_profile_cache() -> None:
    global PROFILE_CACHE
    PROFILE_CACHE = load_profile()


_SECURE_STORAGE: Optional["BaseSecretStore"] = None


def _get_storage() -> Optional["BaseSecretStore"]:
    """Get or create the secure storage instance.

    Returns:
        BaseSecretStore instance or None if initialization fails
    """
    global _SECURE_STORAGE
    if _SECURE_STORAGE is None:
        try:
            _SECURE_STORAGE = get_secure_storage()
        except Exception as exc:
            logger.warning("Failed to initialise secure storage: %s", exc)
            _SECURE_STORAGE = None
    return _SECURE_STORAGE


def _get_vault_api(key: str) -> Optional[str]:
    """Get API key from secure storage.

    Args:
        key: Service name for the API key

    Returns:
        API key string or None if not found
    """
    storage = _get_storage()
    if storage is None:
        return None
    try:
        result: Optional[str] = storage.get_api_key(key)
        return result
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


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",")]
        return [part for part in parts if part]
    return [str(value).strip()]


API_KEY_ALIASES = {
    "OPENAI_API_KEY": "openai_api_key",
    "ANTHROPIC_API_KEY": "anthropic_api_key",
    "XAI_API_KEY": "xai_api_key",
    "LOCAL_LLM_API_KEY": "local_llm_api_key",
    "ASTER_API_KEY": "aster_api",
    "BRAVE_API_KEY": "brave_api_key",
    "COINBASE_X402_API_KEY": "coinbase_x402_api_key",
}

PRIVATE_KEY_ALIASES = {
    "ASTER_API_SECRET": "aster_api_secret",
    "SAM_WALLET_PRIVATE_KEY": "default",
    "HYPERLIQUID_PRIVATE_KEY": "hyperliquid_private_key",
    "AIXBT_PRIVATE_KEY": "aixbt_private_key",
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
    """Get API key from storage or environment.

    Args:
        alias_key: Key alias for looking up service name
        env_var: Environment variable name

    Returns:
        API key string or None if not found
    """
    alias = API_KEY_ALIASES.get(alias_key)
    storage = _get_storage()
    if storage and alias:
        try:
            stored: Optional[str] = storage.get_api_key(alias)
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
    """Get private key from storage or environment.

    Args:
        alias_key: Key alias for looking up service name
        env_var: Environment variable name

    Returns:
        Private key string or None if not found
    """
    alias = PRIVATE_KEY_ALIASES.get(alias_key)
    storage = _get_storage()
    if storage and alias:
        try:
            stored: Optional[str] = storage.get_private_key(alias)
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

    # Production database and cache settings
    SAM_DATABASE_URL: Optional[str] = None  # postgresql://user:pass@host:5432/sam_db
    SAM_REDIS_URL: Optional[str] = None  # redis://localhost:6379/0
    SAM_DB_POOL_MIN_SIZE: int = 5
    SAM_DB_POOL_MAX_SIZE: int = 50
    SAM_CACHE_PREFIX: str = "sam:"
    SAM_CACHE_DEFAULT_TTL: int = 3600
    SAM_CACHE_MAX_SIZE: int = 10000  # For in-memory cache

    SAM_API_HOST: str = "0.0.0.0"
    SAM_API_PORT: int = 8000
    SAM_API_ROOT_PATH: str = ""
    SAM_API_AGENT_ROOT: str = ".sam/users"
    SAM_API_CORS_ORIGINS: List[str] = []
    SAM_API_USER_HEADER: str = "X-User-Id"
    SAM_API_TOKEN_SECRET: Optional[str] = None
    SAM_API_TOKEN_EXPIRE_MINUTES: int = 15  # Reduced from 24 hours to 15 minutes for security
    SAM_API_REFRESH_TOKEN_EXPIRE_DAYS: int = 7  # Refresh tokens valid for 7 days
    SAM_API_ALLOW_REGISTRATION: bool = False
    SAM_API_MAX_LOGIN_ATTEMPTS: int = 5  # Maximum failed login attempts before lockout
    SAM_API_LOCKOUT_DURATION_MINUTES: int = 15  # Account lockout duration in minutes

    # Production mode settings
    SAM_PRODUCTION_MODE: bool = False  # Enable strict production validations
    SAM_AGENT_STORAGE: str = "database"  # 'database' (recommended) or 'file'
    SAM_DEV_MODE: bool = False  # Development mode - relaxed security checks

    # Per-user quota defaults
    SAM_QUOTA_MAX_SESSIONS: int = 50
    SAM_QUOTA_MAX_MESSAGES_PER_SESSION: int = 1000
    SAM_QUOTA_MAX_TOKENS_PER_DAY: int = 1000000
    SAM_QUOTA_MAX_AGENTS: int = 20

    RATE_LIMITING_ENABLED: bool = False

    ENABLE_SOLANA_TOOLS: bool = True
    ENABLE_PUMP_FUN_TOOLS: bool = True
    ENABLE_DEXSCREENER_TOOLS: bool = True
    ENABLE_JUPITER_TOOLS: bool = True
    ENABLE_SEARCH_TOOLS: bool = True
    ENABLE_POLYMARKET_TOOLS: bool = True
    ENABLE_KALSHI_TOOLS: bool = True
    ENABLE_ASTER_FUTURES_TOOLS: bool = False
    ENABLE_HYPERLIQUID_TOOLS: bool = False
    ENABLE_URANUS_TOOLS: bool = True
    ENABLE_PAYAI_FACILITATOR_TOOLS: bool = True
    ENABLE_AIXBT_TOOLS: bool = False
    ENABLE_COINBASE_X402_TOOLS: bool = False

    ASTER_BASE_URL: str = "https://fapi.asterdex.com"
    ASTER_API_KEY: Optional[str] = None
    ASTER_API_SECRET: Optional[str] = None
    ASTER_DEFAULT_RECV_WINDOW: int = 5000

    AIXBT_API_BASE_URL: str = "https://api.aixbt.tech"
    AIXBT_REQUEST_TIMEOUT: Optional[float] = 60.0  # Base network needs time for onchain settlement
    AIXBT_PRIVATE_KEY: Optional[str] = None

    COINBASE_X402_FACILITATOR_URL: str = "https://x402.org/facilitator"
    COINBASE_X402_API_KEY: Optional[str] = None

    HYPERLIQUID_API_URL: str = "https://api.hyperliquid.xyz"
    HYPERLIQUID_PRIVATE_KEY: Optional[str] = None
    HYPERLIQUID_ACCOUNT_ADDRESS: Optional[str] = None
    HYPERLIQUID_DEFAULT_SLIPPAGE: float = 0.05
    HYPERLIQUID_REQUEST_TIMEOUT: Optional[float] = None
    EVM_WALLET_ADDRESS: Optional[str] = None
    EVM_RPC_URL: str = "https://eth.llamarpc.com"
    EVM_PRIVATE_KEY: Optional[str] = None
    ENABLE_EVM_TOOLS: bool = True

    SAM_FERNET_KEY: Optional[str] = None

    MAX_TRANSACTION_SOL: float = 1000.0
    DEFAULT_SLIPPAGE: int = 1

    PAYAI_FACILITATOR_URL: str = "https://facilitator.payai.network"
    PAYAI_FACILITATOR_API_KEY: Optional[str] = None
    PAYAI_FACILITATOR_DEFAULT_NETWORK: str = "solana"

    # Kalshi Configuration
    KALSHI_API_BASE_URL: str = "https://api.elections.kalshi.com/trade-api/v2"
    KALSHI_DEMO_API_BASE_URL: str = "https://demo-api.kalshi.co/trade-api/v2"
    KALSHI_MARKET_URL: str = "https://kalshi.com/markets"
    KALSHI_USE_DEMO: bool = False
    KALSHI_API_KEY_ID: Optional[str] = None  # The Key ID from Kalshi
    KALSHI_PRIVATE_KEY_PATH: Optional[str] = None  # Path to RSA private key file

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

        # Production database and cache settings
        cls.SAM_DATABASE_URL = _as_str(_value_from_sources("SAM_DATABASE_URL", None))
        cls.SAM_REDIS_URL = _as_str(_value_from_sources("SAM_REDIS_URL", None))
        cls.SAM_DB_POOL_MIN_SIZE = _as_int(_value_from_sources("SAM_DB_POOL_MIN_SIZE", 5), 5)
        cls.SAM_DB_POOL_MAX_SIZE = _as_int(_value_from_sources("SAM_DB_POOL_MAX_SIZE", 50), 50)
        cls.SAM_CACHE_PREFIX = _as_str(_value_from_sources("SAM_CACHE_PREFIX", "sam:"), "sam:")
        cls.SAM_CACHE_DEFAULT_TTL = _as_int(
            _value_from_sources("SAM_CACHE_DEFAULT_TTL", 3600), 3600
        )
        cls.SAM_CACHE_MAX_SIZE = _as_int(_value_from_sources("SAM_CACHE_MAX_SIZE", 10000), 10000)

        cls.SAM_API_HOST = _as_str(_value_from_sources("SAM_API_HOST", "0.0.0.0"), "0.0.0.0")
        cls.SAM_API_PORT = _as_int(_value_from_sources("SAM_API_PORT", 8000), 8000)
        cls.SAM_API_ROOT_PATH = _as_str(_value_from_sources("SAM_API_ROOT_PATH", ""), "")
        cls.SAM_API_AGENT_ROOT = _as_str(
            _value_from_sources("SAM_API_AGENT_ROOT", ".sam/users"), ".sam/users"
        )
        cls.SAM_API_CORS_ORIGINS = _as_list(_value_from_sources("SAM_API_CORS_ORIGINS", []))
        cls.SAM_API_USER_HEADER = _as_str(
            _value_from_sources("SAM_API_USER_HEADER", "X-User-Id"), "X-User-Id"
        )
        cls.SAM_API_TOKEN_SECRET = _as_optional_str(_value_from_sources("SAM_API_TOKEN_SECRET"))
        cls.SAM_API_TOKEN_EXPIRE_MINUTES = _as_int(
            _value_from_sources("SAM_API_TOKEN_EXPIRE_MINUTES", cls.SAM_API_TOKEN_EXPIRE_MINUTES),
            cls.SAM_API_TOKEN_EXPIRE_MINUTES,
        )
        cls.SAM_API_ALLOW_REGISTRATION = _as_bool(
            _value_from_sources("SAM_API_ALLOW_REGISTRATION", False), False
        )
        cls.SAM_API_MAX_LOGIN_ATTEMPTS = _as_int(
            _value_from_sources("SAM_API_MAX_LOGIN_ATTEMPTS", cls.SAM_API_MAX_LOGIN_ATTEMPTS),
            cls.SAM_API_MAX_LOGIN_ATTEMPTS,
        )
        cls.SAM_API_LOCKOUT_DURATION_MINUTES = _as_int(
            _value_from_sources(
                "SAM_API_LOCKOUT_DURATION_MINUTES", cls.SAM_API_LOCKOUT_DURATION_MINUTES
            ),
            cls.SAM_API_LOCKOUT_DURATION_MINUTES,
        )

        # Production mode settings
        cls.SAM_PRODUCTION_MODE = _as_bool(_value_from_sources("SAM_PRODUCTION_MODE", False), False)
        cls.SAM_AGENT_STORAGE = _as_str(
            _value_from_sources("SAM_AGENT_STORAGE", "database"), "database"
        ).lower()
        cls.SAM_DEV_MODE = _as_bool(_value_from_sources("SAM_DEV_MODE", False), False)

        # Per-user quota settings
        cls.SAM_QUOTA_MAX_SESSIONS = _as_int(
            _value_from_sources("SAM_QUOTA_MAX_SESSIONS", cls.SAM_QUOTA_MAX_SESSIONS),
            cls.SAM_QUOTA_MAX_SESSIONS,
        )
        cls.SAM_QUOTA_MAX_MESSAGES_PER_SESSION = _as_int(
            _value_from_sources(
                "SAM_QUOTA_MAX_MESSAGES_PER_SESSION", cls.SAM_QUOTA_MAX_MESSAGES_PER_SESSION
            ),
            cls.SAM_QUOTA_MAX_MESSAGES_PER_SESSION,
        )
        cls.SAM_QUOTA_MAX_TOKENS_PER_DAY = _as_int(
            _value_from_sources("SAM_QUOTA_MAX_TOKENS_PER_DAY", cls.SAM_QUOTA_MAX_TOKENS_PER_DAY),
            cls.SAM_QUOTA_MAX_TOKENS_PER_DAY,
        )
        cls.SAM_QUOTA_MAX_AGENTS = _as_int(
            _value_from_sources("SAM_QUOTA_MAX_AGENTS", cls.SAM_QUOTA_MAX_AGENTS),
            cls.SAM_QUOTA_MAX_AGENTS,
        )

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
        cls.ENABLE_KALSHI_TOOLS = _as_bool(_value_from_sources("ENABLE_KALSHI_TOOLS", "true"), True)
        cls.ENABLE_ASTER_FUTURES_TOOLS = _as_bool(
            _value_from_sources("ENABLE_ASTER_FUTURES_TOOLS", "false"), False
        )
        cls.ENABLE_HYPERLIQUID_TOOLS = _as_bool(
            _value_from_sources("ENABLE_HYPERLIQUID_TOOLS", "false"), False
        )
        cls.ENABLE_URANUS_TOOLS = _as_bool(_value_from_sources("ENABLE_URANUS_TOOLS", "true"), True)
        cls.ENABLE_PAYAI_FACILITATOR_TOOLS = _as_bool(
            _value_from_sources("ENABLE_PAYAI_FACILITATOR_TOOLS", "true"), True
        )
        cls.ENABLE_AIXBT_TOOLS = _as_bool(_value_from_sources("ENABLE_AIXBT_TOOLS", "false"), False)
        cls.ENABLE_COINBASE_X402_TOOLS = _as_bool(
            _value_from_sources("ENABLE_COINBASE_X402_TOOLS", "false"), False
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

        cls.AIXBT_API_BASE_URL = _as_str(
            _value_from_sources("AIXBT_API_BASE_URL", "https://api.aixbt.tech")
        )
        aixbt_timeout = _value_from_sources("AIXBT_REQUEST_TIMEOUT")
        cls.AIXBT_REQUEST_TIMEOUT = _as_float(aixbt_timeout) if aixbt_timeout is not None else 60.0
        cls.AIXBT_PRIVATE_KEY = _as_optional_str(
            _private_secret("AIXBT_PRIVATE_KEY", "AIXBT_PRIVATE_KEY")
        )
        cls.COINBASE_X402_FACILITATOR_URL = _as_str(
            _value_from_sources("COINBASE_X402_FACILITATOR_URL", "https://x402.org/facilitator")
        )
        cls.COINBASE_X402_API_KEY = _as_optional_str(
            _api_key("COINBASE_X402_API_KEY", "COINBASE_X402_API_KEY")
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
        cls.EVM_RPC_URL = _as_str(_value_from_sources("EVM_RPC_URL", "https://eth.llamarpc.com"))
        cls.EVM_PRIVATE_KEY = _as_optional_str(_value_from_sources("EVM_PRIVATE_KEY"))
        cls.ENABLE_EVM_TOOLS = _as_bool(_value_from_sources("ENABLE_EVM_TOOLS", "true"), True)

        facilitator_url = _as_optional_str(_value_from_sources("PAYAI_FACILITATOR_URL"))
        if not facilitator_url:
            facilitator_url = _as_optional_str(_value_from_sources("FACILITATOR_URL"))
        cls.PAYAI_FACILITATOR_URL = facilitator_url or "https://facilitator.payai.network"
        cls.PAYAI_FACILITATOR_API_KEY = _as_optional_str(
            _api_key("PAYAI_FACILITATOR_API_KEY", "PAYAI_FACILITATOR_API_KEY")
        )
        cls.PAYAI_FACILITATOR_DEFAULT_NETWORK = _as_str(
            _value_from_sources("PAYAI_FACILITATOR_DEFAULT_NETWORK", "solana"), "solana"
        ).lower()
        # Kalshi Configuration
        cls.KALSHI_API_BASE_URL = _as_str(
            _value_from_sources(
                "KALSHI_API_BASE_URL", "https://api.elections.kalshi.com/trade-api/v2"
            ),
            "https://api.elections.kalshi.com/trade-api/v2",
        )
        cls.KALSHI_DEMO_API_BASE_URL = _as_str(
            _value_from_sources(
                "KALSHI_DEMO_API_BASE_URL", "https://demo-api.kalshi.co/trade-api/v2"
            ),
            "https://demo-api.kalshi.co/trade-api/v2",
        )
        cls.KALSHI_MARKET_URL = _as_str(
            _value_from_sources("KALSHI_MARKET_URL", "https://kalshi.com/markets"),
            "https://kalshi.com/markets",
        )
        cls.KALSHI_USE_DEMO = _as_bool(_value_from_sources("KALSHI_USE_DEMO", "false"), False)
        cls.KALSHI_API_KEY_ID = os.getenv("KALSHI_API_KEY_ID")
        cls.KALSHI_PRIVATE_KEY_PATH = os.getenv("KALSHI_PRIVATE_KEY_PATH")

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
    def validate(cls, strict: bool = False) -> bool:
        """Validate configuration settings.

        Args:
            strict: If True, enforce production-grade requirements

        Returns:
            True if valid, False otherwise
        """
        errors = []
        warnings = []

        # Use strict mode if SAM_PRODUCTION_MODE is enabled
        strict = strict or cls.SAM_PRODUCTION_MODE

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

        # Encryption key validation
        if not cls.SAM_FERNET_KEY:
            if strict:
                errors.append(
                    "SAM_FERNET_KEY is required for secure storage in production. "
                    'Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
                )
            else:
                warnings.append("SAM_FERNET_KEY not set - secrets will not be encrypted")

        # Production-only validations
        if strict:
            # Require explicit JWT secret (don't fall back to Fernet key)
            if not cls.SAM_API_TOKEN_SECRET:
                errors.append(
                    "SAM_API_TOKEN_SECRET is required in production mode. "
                    "Set a unique secret for JWT signing."
                )

            # Require database storage for agents
            if cls.SAM_AGENT_STORAGE != "database":
                errors.append(
                    "SAM_AGENT_STORAGE must be 'database' in production mode. "
                    "File-based storage is not recommended for production."
                )

            # Require explicit CORS origins (no wildcards)
            if not cls.SAM_API_CORS_ORIGINS or "*" in cls.SAM_API_CORS_ORIGINS:
                errors.append(
                    "SAM_API_CORS_ORIGINS must be explicitly set in production mode. "
                    "Wildcard '*' is not allowed."
                )

            # Warn about registration being enabled
            if cls.SAM_API_ALLOW_REGISTRATION:
                warnings.append(
                    "SAM_API_ALLOW_REGISTRATION is enabled. "
                    "Ensure this is intentional for public-facing deployments."
                )

            # Check for secure database URL in production
            if not cls.SAM_DATABASE_URL:
                warnings.append(
                    "SAM_DATABASE_URL not set. Using SQLite is not recommended for production. "
                    "Consider using PostgreSQL for better concurrency and reliability."
                )

            # Ensure rate limiting is enabled
            if not cls.RATE_LIMITING_ENABLED:
                warnings.append(
                    "RATE_LIMITING_ENABLED is False. "
                    "Rate limiting is recommended for production deployments."
                )

        # Log warnings
        if warnings:
            logger.warning("Configuration warnings:")
            for warning in warnings:
                logger.warning(f"  - {warning}")

        # Log errors and return
        if errors:
            logger.error("Configuration validation failed:")
            for error in errors:
                logger.error(f"  - {error}")
            return False

        return True

    @classmethod
    def validate_production(cls) -> bool:
        """Validate configuration for production deployment.

        This method enforces strict production requirements and should be called
        before starting the API server in production.

        Returns:
            True if configuration is production-ready, False otherwise
        """
        return cls.validate(strict=True)

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
            "  Tool Toggles: Solana=%s Pump.fun=%s DexScreener=%s Jupiter=%s Search=%s Polymarket=%s Aster=%s Hyperliquid=%s Uranus=%s PayAI=%s",
            cls.ENABLE_SOLANA_TOOLS,
            cls.ENABLE_PUMP_FUN_TOOLS,
            cls.ENABLE_DEXSCREENER_TOOLS,
            cls.ENABLE_JUPITER_TOOLS,
            cls.ENABLE_SEARCH_TOOLS,
            cls.ENABLE_POLYMARKET_TOOLS,
            cls.ENABLE_ASTER_FUTURES_TOOLS,
            cls.ENABLE_HYPERLIQUID_TOOLS,
            cls.ENABLE_URANUS_TOOLS,
            cls.ENABLE_PAYAI_FACILITATOR_TOOLS,
        )
        logger.info(
            "  API Server: host=%s port=%s root_path=%s",
            cls.SAM_API_HOST,
            cls.SAM_API_PORT,
            cls.SAM_API_ROOT_PATH or "/",
        )
        if cls.SAM_API_CORS_ORIGINS:
            logger.info("  API CORS Origins: %s", ",".join(cls.SAM_API_CORS_ORIGINS))
        logger.info(
            "  API Auth: token_expiry=%s minutes registration=%s",
            cls.SAM_API_TOKEN_EXPIRE_MINUTES,
            "enabled" if cls.SAM_API_ALLOW_REGISTRATION else "disabled",
        )
        logger.info("  PayAI Facilitator URL: %s", cls.PAYAI_FACILITATOR_URL or "not set")
        logger.info(
            "  PayAI Default Network: %s",
            cls.PAYAI_FACILITATOR_DEFAULT_NETWORK or "not set",
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
