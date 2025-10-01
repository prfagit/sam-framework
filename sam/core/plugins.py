import logging
import os
from importlib import import_module
from typing import Any, Callable, Optional

from ..config.plugin_policy import PluginPolicy
from .tools import ToolRegistry

logger = logging.getLogger(__name__)


def _call_plugin_register(
    fn: Callable[..., Any], registry: ToolRegistry, agent: Optional[Any]
) -> None:
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


def load_plugins(
    registry: ToolRegistry,
    agent: Optional[Any] = None,
    *,
    policy: Optional[PluginPolicy] = None,
) -> None:
    """Discover and load external plugins.

    Supports two mechanisms (both optional):
    - Entry points: group 'sam.plugins' — each entry should be a callable
      that takes (registry, agent) or (registry) and registers tools.
    - Environment variable: SAM_PLUGINS — comma-separated module paths.
      Each module may expose a 'register' or 'register_tools' callable.
    """
    policy = policy or PluginPolicy.from_env()

    if not policy.enabled:
        logger.info("Plugin loading disabled by policy")
        return

    # 1) Python entry points
    try:
        from importlib.metadata import entry_points

        eps = entry_points(group="sam.plugins")
        for ep in eps:
            try:
                metadata = policy.resolve_metadata(ep.module)
                if not policy.permits(metadata=metadata, entry_point=ep.name):
                    continue

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
            metadata = policy.resolve_metadata(mod_path)
            if not policy.permits(metadata=metadata, entry_point=None):
                continue

            module = import_module(mod_path)
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
