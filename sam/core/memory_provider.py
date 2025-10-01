from __future__ import annotations

import importlib
import logging
import os
from importlib.metadata import EntryPoint, entry_points
from typing import Callable, Iterable, Optional, cast

from .memory import MemoryManager
from ..config.config_loader import load_config
from ..config.settings import Settings

logger = logging.getLogger(__name__)


MemoryFactory = Callable[[str], MemoryManager]


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
        factory_obj = getattr(mod, func_name, None)
        if callable(factory_obj):
            factory = cast(MemoryFactory, factory_obj)
            mm = factory(db_path)
            if isinstance(mm, MemoryManager):
                return mm
            logger.warning("SAM_MEMORY_BACKEND expected MemoryManager, got %s", type(mm).__name__)
        logger.warning(f"SAM_MEMORY_BACKEND callable not found: {spec}")
    except Exception as e:
        logger.warning(f"Failed to load SAM_MEMORY_BACKEND {spec}: {e}")
    return None


def _iter_memory_backends() -> Iterable[EntryPoint]:
    eps = entry_points()
    select = getattr(eps, "select", None)
    if callable(select):
        return cast(Iterable[EntryPoint], select(group="sam.memory_backends"))
    group = getattr(eps, "get", None)
    if callable(group):
        return cast(Iterable[EntryPoint], group("sam.memory_backends", []))
    return ()


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
    for ep in _iter_memory_backends():
        if ep.name != name:
            continue
        try:
            factory_obj = ep.load()
            if not callable(factory_obj):
                logger.warning("Memory backend '%s' entry_point is not callable", name)
                break
            factory = cast(MemoryFactory, factory_obj)
            memory_manager = factory(dbp)
            if isinstance(memory_manager, MemoryManager):
                logger.info(f"Loaded memory backend via plugin: {name}")
            else:
                logger.info(f"Loaded custom memory backend: {name}")
            return memory_manager
        except Exception as exc:
            logger.warning(f"Failed to load memory backend '{name}': {exc}")
            break

    # Fallback to built-in SQLite manager
    return MemoryManager(dbp)
