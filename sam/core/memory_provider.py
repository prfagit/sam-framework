from typing import Optional
from importlib.metadata import entry_points
import importlib
import os
import logging

from .memory import MemoryManager
from ..config.settings import Settings
from ..config.config_loader import load_config

logger = logging.getLogger(__name__)


def _get_backend_name() -> str:
    # Prefer config file then env var (Settings could be extended in future)
    cfg = load_config()
    backend = None
    if isinstance(cfg, dict):
        backend = (
            cfg.get("memory", {}).get("backend") if isinstance(cfg.get("memory"), dict) else None
        )
    return str(backend) if backend else "sqlite"


def _load_from_env(db_path: str) -> Optional[MemoryManager]:
    spec = os.getenv("SAM_MEMORY_BACKEND")
    if not spec:
        return None
    try:
        if ":" in spec:
            mod_name, func_name = spec.split(":", 1)
        else:
            mod_name, func_name = spec, "create_backend"
        mod = importlib.import_module(mod_name)
        factory = getattr(mod, func_name, None)
        if callable(factory):
            mm = factory(db_path)
            return mm
        logger.warning(f"SAM_MEMORY_BACKEND callable not found: {spec}")
    except Exception as e:
        logger.warning(f"Failed to load SAM_MEMORY_BACKEND {spec}: {e}")
    return None


def create_memory_manager(db_path: Optional[str] = None) -> MemoryManager:
    """Create the memory manager, allowing plugin backends via entry points.

    Entry point group: `sam.memory_backends`. The entry name should match the
    configured backend (e.g., 'sqlite', 'redis', 'dynamodb', etc.) and the
    callable should return a MemoryManager-compatible object.
    """
    name = _get_backend_name()

    # Attempt explicit env override first for convenience
    dbp = db_path or Settings.SAM_DB_PATH
    env_mm = _load_from_env(dbp)
    if env_mm is not None:
        return env_mm

    # Attempt plugin backend via entry points
    try:
        eps = entry_points(group="sam.memory_backends")  # type: ignore[arg-type]
        for ep in eps:
            if ep.name == name:
                try:
                    factory = ep.load()
                    mm = factory(dbp)
                    if isinstance(mm, MemoryManager):
                        logger.info(f"Loaded memory backend via plugin: {name}")
                    else:
                        logger.info(f"Loaded custom memory backend: {name}")
                    return mm
                except Exception as e:
                    logger.warning(f"Failed to load memory backend '{name}': {e}")
                    break
    except Exception:
        pass

    # Fallback to built-in SQLite manager
    return MemoryManager(dbp)
