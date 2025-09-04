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
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL: Optional[str] = os.getenv("OPENAI_BASE_URL")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    
    # Solana Configuration
    SAM_SOLANA_RPC_URL: str = os.getenv("SAM_SOLANA_RPC_URL", "https://api.devnet.solana.com")
    SAM_WALLET_PRIVATE_KEY: Optional[str] = os.getenv("SAM_WALLET_PRIVATE_KEY")
    
    # Database Configuration
    SAM_DB_PATH: str = os.getenv("SAM_DB_PATH", ".sam/sam_memory.db")
    
    # Redis Configuration
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    RATE_LIMITING_ENABLED: bool = os.getenv("RATE_LIMITING_ENABLED", "true").lower() == "true"
    
    # Encryption Configuration
    SAM_FERNET_KEY: Optional[str] = os.getenv("SAM_FERNET_KEY")
    
    # Safety Limits
    MAX_TRANSACTION_SOL: float = float(os.getenv("MAX_TRANSACTION_SOL", "1000"))
    DEFAULT_SLIPPAGE: int = int(os.getenv("DEFAULT_SLIPPAGE", "1"))
    
    # Logging Configuration
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    
    @classmethod
    def validate(cls) -> bool:
        """Validate that required settings are present."""
        errors = []
        
        if not cls.OPENAI_API_KEY:
            errors.append("OPENAI_API_KEY is required")
        
        if not cls.SAM_FERNET_KEY:
            errors.append("SAM_FERNET_KEY is required for secure storage")
        
        if errors:
            logger.error("Configuration validation failed:")
            for error in errors:
                logger.error(f"  - {error}")
            return False
        
        return True
    
    @classmethod
    def log_config(cls):
        """Log current configuration (excluding sensitive data)."""
        logger.info("SAM Framework Configuration:")
        logger.info(f"  OpenAI Model: {cls.OPENAI_MODEL}")
        logger.info(f"  OpenAI Base URL: {cls.OPENAI_BASE_URL or 'default'}")
        logger.info(f"  Solana RPC: {cls.SAM_SOLANA_RPC_URL}")
        logger.info(f"  Database Path: {cls.SAM_DB_PATH}")
        logger.info(f"  Redis URL: {cls.REDIS_URL}")
        logger.info(f"  Rate Limiting: {'Enabled' if cls.RATE_LIMITING_ENABLED else 'Disabled'}")
        logger.info(f"  Max Transaction: {cls.MAX_TRANSACTION_SOL} SOL")
        logger.info(f"  Default Slippage: {cls.DEFAULT_SLIPPAGE}%")
        logger.info(f"  Log Level: {cls.LOG_LEVEL}")
        logger.info(f"  Wallet Configured: {'Yes' if cls.SAM_WALLET_PRIVATE_KEY else 'No'}")
        logger.info(f"  Encryption Key: {'Set' if cls.SAM_FERNET_KEY else 'Missing'}")


def setup_logging(level: str = None):
    """Set up logging configuration."""
    log_level = level or Settings.LOG_LEVEL
    
    # Convert string level to logging constant
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    
    # Configure logging format
    logging.basicConfig(
        level=numeric_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Reduce noise from third-party libraries
    logging.getLogger('aiohttp').setLevel(logging.WARNING)
    logging.getLogger('solana').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    
    logger.info(f"Logging configured at {log_level.upper()} level")