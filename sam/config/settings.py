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
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-5-nano")
    
    # Solana Configuration  
    SAM_SOLANA_RPC_URL: str = os.getenv("SAM_SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
    SAM_WALLET_PRIVATE_KEY: Optional[str] = os.getenv("SAM_WALLET_PRIVATE_KEY")
    
    # Database Configuration
    SAM_DB_PATH: str = os.getenv("SAM_DB_PATH", ".sam/sam_memory.db")
    
    # Rate Limiting Configuration (disabled by default for better UX)
    RATE_LIMITING_ENABLED: bool = os.getenv("RATE_LIMITING_ENABLED", "false").lower() == "true"
    
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
        logger.info(f"  Rate Limiting: {'Enabled' if cls.RATE_LIMITING_ENABLED else 'Disabled'}")
        logger.info(f"  Max Transaction: {cls.MAX_TRANSACTION_SOL} SOL")
        logger.info(f"  Default Slippage: {cls.DEFAULT_SLIPPAGE}%")
        logger.info(f"  Log Level: {cls.LOG_LEVEL}")
        logger.info(f"  Wallet Configured: {'Yes' if cls.SAM_WALLET_PRIVATE_KEY else 'No'}")
        logger.info(f"  Encryption Key: {'Set' if cls.SAM_FERNET_KEY else 'Missing'}")


def setup_logging(level: Optional[str] = None):
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
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Reduce noise from third-party libraries
    logging.getLogger('aiohttp').setLevel(max(numeric_level, logging.WARNING))
    logging.getLogger('solana').setLevel(max(numeric_level, logging.WARNING))
    logging.getLogger('urllib3').setLevel(max(numeric_level, logging.WARNING))
    
    # Only log configuration if logging is enabled
    if log_level.upper() != "NO":
        logger.info(f"Logging configured at {log_level.upper()} level")