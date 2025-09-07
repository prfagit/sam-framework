import os
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def _read_toml(path: str) -> Optional[Dict[str, Any]]:
    try:
        import tomllib  # Python 3.11+

        with open(path, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return None
    except Exception as e:
        logger.warning(f"Failed to parse TOML at {path}: {e}")
        return None


def load_config() -> Dict[str, Any]:
    """Load SAM configuration from file if present.

    Search order:
    1) SAM_CONFIG env var (file path)
    2) ./sam.toml (cwd)
    3) $XDG_CONFIG_HOME/sam/sam.toml or ~/.config/sam/sam.toml
    Returns an empty dict when no config is present.
    """
    # 1) Explicit path
    env_path = os.getenv("SAM_CONFIG")
    if env_path:
        cfg = _read_toml(env_path)
        if cfg is not None:
            return cfg

    # 2) Current working directory
    cwd_path = os.path.abspath(os.path.join(os.getcwd(), "sam.toml"))
    cfg = _read_toml(cwd_path)
    if cfg is not None:
        return cfg

    # 3) XDG config or ~/.config
    xdg = os.getenv("XDG_CONFIG_HOME")
    if xdg:
        xdg_path = os.path.join(xdg, "sam", "sam.toml")
        cfg = _read_toml(xdg_path)
        if cfg is not None:
            return cfg

    home = os.path.expanduser("~")
    default_path = os.path.join(home, ".config", "sam", "sam.toml")
    cfg = _read_toml(default_path)
    if cfg is not None:
        return cfg

    return {}


def load_middleware_config() -> Optional[Dict[str, Any]]:
    cfg = load_config()
    mw = cfg.get("middleware")
    return mw if isinstance(mw, dict) else None
