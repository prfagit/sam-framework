"""Configuration and environment variable validation."""

import os
import logging
from typing import Dict, Any, List, Optional, Union, Callable
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class EnvVarSpec:
    """Specification for environment variable validation."""

    name: str
    required: bool = False
    default: Optional[str] = None
    validator: Optional[Callable[[str], bool]] = None
    description: str = ""
    sensitive: bool = False  # If True, don't log the value


class ConfigValidationError(Exception):
    """Raised when configuration validation fails."""

    pass


class ConfigValidator:
    """Validates environment variables and configuration."""

    def __init__(self) -> None:
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.validated_vars: Dict[str, str] = {}

    def add_env_var(self, spec: EnvVarSpec) -> None:
        """Add environment variable for validation."""
        value = os.getenv(spec.name, spec.default)

        # Check if required variable is missing
        if spec.required and not value:
            self.errors.append(f"Required environment variable '{spec.name}' is not set")
            return

        # Skip validation if no value and not required
        if not value and not spec.required:
            if spec.description:
                logger.debug(f"Optional env var '{spec.name}' not set: {spec.description}")
            return

        # Run custom validator if provided
        if spec.validator and value:
            try:
                if not spec.validator(value):
                    self.errors.append(f"Environment variable '{spec.name}' has invalid value")
                    return
            except Exception as e:
                self.errors.append(f"Error validating '{spec.name}': {e}")
                return

        # Store validated value
        if value is not None:
            self.validated_vars[spec.name] = value

        # Log validation result (mask sensitive values)
        display_value = "***" if spec.sensitive else value
        logger.info(f"Validated env var '{spec.name}': {display_value}")

    def validate_all(self) -> Dict[str, str]:
        """Validate all registered environment variables."""
        if self.errors:
            error_msg = "Environment validation failed:\n" + "\n".join(
                f"  - {err}" for err in self.errors
            )
            raise ConfigValidationError(error_msg)

        if self.warnings:
            for warning in self.warnings:
                logger.warning(warning)

        logger.info(
            f"Environment validation successful: {len(self.validated_vars)} variables validated"
        )
        return self.validated_vars


def create_sam_config_validator() -> ConfigValidator:
    """Create validator for SAM framework configuration."""
    validator = ConfigValidator()

    # Core encryption key (required)
    validator.add_env_var(
        EnvVarSpec(
            name="SAM_FERNET_KEY",
            required=True,
            validator=lambda x: len(x) == 44 and x.endswith("="),  # Fernet key format
            description="Encryption key for secure wallet storage",
            sensitive=True,
        )
    )

    # LLM provider configuration
    validator.add_env_var(
        EnvVarSpec(
            name="LLM_PROVIDER",
            required=False,
            default="openai",
            validator=lambda x: x in ["openai", "anthropic", "xai", "openai_compat", "local"],
            description="LLM provider to use for AI operations",
        )
    )

    # Solana RPC configuration
    validator.add_env_var(
        EnvVarSpec(
            name="SAM_SOLANA_RPC_URL",
            required=False,
            default="https://api.mainnet-beta.solana.com",
            validator=lambda x: x.startswith(("http://", "https://")),
            description="Solana RPC endpoint URL",
        )
    )

    # Rate limiting toggle
    validator.add_env_var(
        EnvVarSpec(
            name="RATE_LIMITING_ENABLED",
            required=False,
            default="true",
            validator=lambda x: x.lower() in ["true", "false", "1", "0", "yes", "no"],
            description="Enable/disable rate limiting for API calls",
        )
    )

    # Transaction safety limits
    validator.add_env_var(
        EnvVarSpec(
            name="MAX_TRANSACTION_SOL",
            required=False,
            default="1.0",
            validator=lambda x: float(x) > 0 and float(x) <= 100,
            description="Maximum SOL amount per transaction",
        )
    )

    # Search API key (optional)
    validator.add_env_var(
        EnvVarSpec(
            name="BRAVE_API_KEY",
            required=False,
            validator=lambda x: len(x) > 10,  # Basic length check
            description="Brave Search API key for web search functionality",
            sensitive=True,
        )
    )

    # OpenAI API key (conditional on LLM provider)
    openai_key = os.getenv("OPENAI_API_KEY")
    llm_provider = os.getenv("LLM_PROVIDER", "openai")
    if llm_provider in ["openai", "openai_compat"] and not openai_key:
        validator.warnings.append(f"LLM_PROVIDER is '{llm_provider}' but OPENAI_API_KEY is not set")

    # Anthropic API key (conditional)
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    if llm_provider == "anthropic" and not anthropic_key:
        validator.warnings.append("LLM_PROVIDER is 'anthropic' but ANTHROPIC_API_KEY is not set")

    # xAI API key (conditional)
    xai_key = os.getenv("XAI_API_KEY")
    if llm_provider == "xai" and not xai_key:
        validator.warnings.append("LLM_PROVIDER is 'xai' but XAI_API_KEY is not set")

    return validator


def validate_file_paths(paths: Dict[str, str]) -> Dict[str, str]:
    """Validate file paths and create directories if needed."""
    validated_paths = {}

    for name, path_str in paths.items():
        try:
            path = Path(path_str).expanduser().resolve()

            # Create parent directories if they don't exist
            if name.endswith("_dir") or name.endswith("_path"):
                path.parent.mkdir(parents=True, exist_ok=True)
                if name.endswith("_dir"):
                    path.mkdir(parents=True, exist_ok=True)

            validated_paths[name] = str(path)
            logger.debug(f"Validated path '{name}': {path}")

        except Exception as e:
            raise ConfigValidationError(f"Invalid path for '{name}': {e}")

    return validated_paths


def validate_numeric_ranges(values: Dict[str, str]) -> Dict[str, Union[int, float]]:
    """Validate numeric values are within expected ranges."""
    validated_values = {}

    ranges = {
        "MAX_TRANSACTION_SOL": (0.001, 100.0, float),
        "DEFAULT_SLIPPAGE": (1, 50, int),
        "MAX_RETRIES": (1, 10, int),
        "TIMEOUT_SECONDS": (5, 300, int),
        "POOL_SIZE": (1, 20, int),
    }

    for name, value_str in values.items():
        if name in ranges:
            min_val, max_val, type_func = ranges[name]
            try:
                value = type_func(value_str)
                if not (min_val <= value <= max_val):
                    raise ConfigValidationError(
                        f"{name} must be between {min_val} and {max_val}, got {value}"
                    )
                validated_values[name] = value
                logger.debug(f"Validated numeric value '{name}': {value}")
            except (ValueError, TypeError) as e:
                raise ConfigValidationError(f"Invalid numeric value for '{name}': {e}")

    return validated_values


def check_system_requirements() -> Dict[str, Any]:
    """Check system requirements and capabilities."""
    import sys
    import platform

    requirements = {
        "python_version": {
            "current": f"{sys.version_info.major}.{sys.version_info.minor}",
            "required": "3.11",
            "met": sys.version_info >= (3, 11),
        },
        "platform": {
            "system": platform.system(),
            "architecture": platform.architecture()[0],
            "supported": platform.system() in ["Darwin", "Linux", "Windows"],
        },
        "memory": {"available_gb": 0, "recommended_gb": 2, "sufficient": False},
    }

    # Check available memory
    try:
        import psutil

        memory = psutil.virtual_memory()
        available_gb = memory.available / 1024**3
        requirements["memory"]["available_gb"] = round(available_gb, 1)
        requirements["memory"]["sufficient"] = available_gb >= 2.0
    except ImportError:
        logger.warning("psutil not available for memory check")

    return requirements


def log_system_info() -> None:
    """Log system information for debugging."""
    try:
        import sys
        import platform

        logger.info("=== SAM Framework System Information ===")
        logger.info(f"Python: {sys.version}")
        logger.info(f"Platform: {platform.platform()}")
        logger.info(f"Architecture: {platform.architecture()}")
        logger.info(f"Processor: {platform.processor()}")

        try:
            import psutil

            memory = psutil.virtual_memory()
            logger.info(
                f"Memory: {memory.total / 1024**3:.1f}GB total, {memory.available / 1024**3:.1f}GB available"
            )
            logger.info(f"CPU: {psutil.cpu_count()} cores, {psutil.cpu_percent(interval=1)}% usage")
        except ImportError:
            logger.warning("psutil not available for detailed system info")

    except Exception as e:
        logger.error(f"Error gathering system info: {e}")


def validate_sam_environment() -> Dict[str, Any]:
    """Complete environment validation for SAM framework."""
    logger.info("Starting SAM environment validation...")

    try:
        # Log system information
        log_system_info()

        # Check system requirements
        requirements = check_system_requirements()
        if not requirements["python_version"]["met"]:
            raise ConfigValidationError(
                f"Python {requirements['python_version']['required']}+ required, "
                f"got {requirements['python_version']['current']}"
            )

        if not requirements["platform"]["supported"]:
            logger.warning(
                f"Platform {requirements['platform']['system']} may not be fully supported"
            )

        # Validate environment variables
        config_validator = create_sam_config_validator()
        env_vars = config_validator.validate_all()

        # Validate paths
        paths = {
            "sam_data_dir": os.path.expanduser("~/.sam"),
            "sam_db_path": os.path.expanduser("~/.sam/sam_memory.db"),
        }
        validated_paths = validate_file_paths(paths)

        # Validate numeric values
        numeric_values = {
            k: v for k, v in env_vars.items() if k in ["MAX_TRANSACTION_SOL", "DEFAULT_SLIPPAGE"]
        }
        validated_numerics = validate_numeric_ranges(numeric_values)

        result = {
            "success": True,
            "environment": env_vars,
            "paths": validated_paths,
            "numeric_values": validated_numerics,
            "system_requirements": requirements,
            "warnings": config_validator.warnings,
        }

        logger.info("SAM environment validation completed successfully")
        return result

    except ConfigValidationError as e:
        logger.error(f"Environment validation failed: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error during validation: {e}")
        raise ConfigValidationError(f"Validation error: {e}")
