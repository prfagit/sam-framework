import logging
import os
from typing import Any, Callable, Optional

from .tools import ToolRegistry

logger = logging.getLogger(__name__)


def _call_plugin_register(fn: Callable, registry: ToolRegistry, agent: Optional[Any]) -> None:
    try:
        # Try common signatures in order
        try:
            fn(registry, agent)
            return
        except TypeError:
            pass
        try:
            fn(registry)
            return
        except TypeError:
            pass
        res = fn()
        # Allow returning iterable of tools (callers can register themselves otherwise)
        try:
            for tool in res or []:
                registry.register(tool)
        except Exception:
            # Not iterable or not tools; ignore
            pass
    except Exception as e:
        logger.warning(f"Plugin register callable failed: {e}")


def load_plugins(registry: ToolRegistry, agent: Optional[Any] = None) -> None:
    """Discover and load external plugins.

    Supports two mechanisms (both optional):
    - Entry points: group 'sam.plugins' — each entry should be a callable
      that takes (registry, agent) or (registry) and registers tools.
    - Environment variable: SAM_PLUGINS — comma-separated module paths.
      Each module may expose a 'register' or 'register_tools' callable.
    """
    # 1) Python entry points
    try:
        from importlib.metadata import entry_points

        eps = entry_points(group="sam.plugins")  # type: ignore[arg-type]
        for ep in eps:
            try:
                plugin = ep.load()
                _call_plugin_register(plugin, registry, agent)
                logger.info(f"Loaded plugin from entry point: {ep.name}")
            except Exception as e:
                logger.warning(f"Failed loading plugin entry point {ep.name}: {e}")
    except Exception as e:
        # Safe to continue if entry point discovery not possible
        logger.debug(f"Entry point discovery skipped: {e}")

    # 2) Environment-driven module list
    modules = os.getenv("SAM_PLUGINS", "").strip()
    if not modules:
        return

    for mod_path in [m.strip() for m in modules.split(",") if m.strip()]:
        try:
            module = __import__(mod_path, fromlist=["register", "register_tools"])
            register_fn = getattr(module, "register", None) or getattr(
                module, "register_tools", None
            )
            if callable(register_fn):
                _call_plugin_register(register_fn, registry, agent)
                logger.info(f"Loaded plugin module: {mod_path}")
            else:
                logger.warning(
                    f"Plugin module {mod_path} has no callable 'register' or 'register_tools'"
                )
        except Exception as e:
            logger.warning(f"Failed loading plugin module {mod_path}: {e}")
