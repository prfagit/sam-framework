"""Plugin trust policy configuration and verification utilities."""

from __future__ import annotations

import json
import logging
import os
import hmac
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple, Any
import importlib.util

logger = logging.getLogger(__name__)


@dataclass
class PluginRule:
    """Trust record for a plugin module."""

    module: str
    sha256: Optional[str] = None
    label: Optional[str] = None


@dataclass
class ModuleMetadata:
    """Resolved module metadata used for trust decisions."""

    name: str
    origin: Optional[str]
    sha256: Optional[str]


class PluginPolicy:
    """Represents plugin trust policy as loaded from configuration and env."""

    def __init__(
        self,
        *,
        enabled: bool,
        allow_unverified: bool,
        module_rules: Dict[str, PluginRule],
        entry_point_rules: Dict[str, PluginRule],
        allowlist_path: Path,
    ) -> None:
        self.enabled = enabled
        self.allow_unverified = allow_unverified
        self._module_rules = module_rules
        self._entry_point_rules = entry_point_rules
        self.allowlist_path = allowlist_path

    @classmethod
    def from_env(cls) -> "PluginPolicy":
        """Construct a policy using environment variables and allowlist file."""
        enabled = os.getenv("SAM_ENABLE_PLUGINS", "false").strip().lower() == "true"
        allow_unverified = (
            os.getenv("SAM_PLUGIN_ALLOW_UNVERIFIED", "false").strip().lower() == "true"
        )
        default_path = Path(__file__).with_name("plugin_allowlist.json")
        allowlist_override = os.getenv("SAM_PLUGIN_ALLOWLIST_FILE")
        allowlist_path = Path(allowlist_override) if allowlist_override else default_path

        module_rules, entry_point_rules = cls._load_allowlist(allowlist_path)

        return cls(
            enabled=enabled,
            allow_unverified=allow_unverified,
            module_rules=module_rules,
            entry_point_rules=entry_point_rules,
            allowlist_path=allowlist_path,
        )

    @staticmethod
    def _load_allowlist(path: Path) -> Tuple[Dict[str, PluginRule], Dict[str, PluginRule]]:
        module_rules: Dict[str, PluginRule] = {}
        entry_point_rules: Dict[str, PluginRule] = {}

        raw = load_allowlist_document(path)

        modules_obj = raw.get("modules", {})
        if isinstance(modules_obj, dict):
            for module_name, val in modules_obj.items():
                rule = _rule_from_obj(module_name, val)
                if rule:
                    module_rules[module_name] = rule

        entry_points_obj = raw.get("entry_points", {})
        if isinstance(entry_points_obj, dict):
            for ep_name, val in entry_points_obj.items():
                rule = _rule_from_obj(ep_name, val)
                if rule and rule.module:
                    entry_point_rules[ep_name] = rule

        return module_rules, entry_point_rules

    def to_document(self) -> Dict[str, Any]:
        modules = {
            name: {"module": rule.module, **({"sha256": rule.sha256} if rule.sha256 else {}), **({"label": rule.label} if rule.label else {})}
            for name, rule in self._module_rules.items()
        }
        entry_points = {
            name: {
                "module": rule.module,
                **({"sha256": rule.sha256} if rule.sha256 else {}),
                **({"label": rule.label} if rule.label else {}),
            }
            for name, rule in self._entry_point_rules.items()
        }
        return {"modules": modules, "entry_points": entry_points}

    def resolve_metadata(self, module_name: str) -> ModuleMetadata:
        """Inspect module without importing it and compute metadata."""
        try:
            spec = importlib.util.find_spec(module_name)
        except Exception as exc:
            logger.warning("Failed to locate module '%s': %s", module_name, exc)
            return ModuleMetadata(module_name, None, None)

        if spec is None:
            logger.warning("Module '%s' not found when resolving plugin metadata", module_name)
            return ModuleMetadata(module_name, None, None)

        origin: Optional[str] = None
        if spec.origin and spec.origin not in {"built-in", "frozen"}:
            origin = spec.origin
        elif spec.submodule_search_locations:
            # Package: inspect __init__.py
            for loc in spec.submodule_search_locations:
                candidate = Path(loc) / "__init__.py"
                if candidate.exists():
                    origin = str(candidate)
                    break

        sha256 = self._compute_digest(spec, origin)
        return ModuleMetadata(module_name, origin, sha256)

    def permits(self, *, metadata: ModuleMetadata, entry_point: Optional[str]) -> bool:
        """Determine if the module metadata satisfies policy rules."""
        rule = None

        if entry_point:
            rule = self._entry_point_rules.get(entry_point)
            if rule and rule.module and rule.module != metadata.name:
                logger.warning(
                    "Entry point '%s' is mapped to module '%s' in allowlist but resolves to '%s'",
                    entry_point,
                    rule.module,
                    metadata.name,
                )
                # Treat mismatch as policy failure unless unverified is allowed
                if not self.allow_unverified:
                    return False

        if rule is None:
            rule = self._module_rules.get(metadata.name)

        if rule is None:
            if self.allow_unverified:
                logger.warning(
                    "Allowing unverified plugin '%s' (%s); update %s to pin its digest.",
                    entry_point or metadata.name,
                    metadata.origin or "unknown origin",
                    self.allowlist_path,
                )
                return True

            logger.warning(
                "Blocked plugin '%s' (%s) — not present in allowlist %s",
                entry_point or metadata.name,
                metadata.origin or "unknown origin",
                self.allowlist_path,
            )
            return False

        if rule.sha256:
            if metadata.sha256 is None:
                logger.error(
                    "Cannot verify plugin '%s'; no digest available but allowlist requires sha256.",
                    metadata.name,
                )
                return False
            if not hmac.compare_digest(metadata.sha256, rule.sha256):
                logger.error(
                    "Plugin digest mismatch for '%s'. Expected %s, got %s. Update %s if upgrade intentional.",
                    metadata.name,
                    rule.sha256,
                    metadata.sha256,
                    self.allowlist_path,
                )
                return False

        logger.info(
            "Verified plugin '%s' (%s) with digest %s",
            entry_point or metadata.name,
            metadata.origin or "unknown origin",
            metadata.sha256 or "unavailable",
        )
        return True

    @staticmethod
    def _compute_digest(spec, origin: Optional[str]) -> Optional[str]:  # type: ignore[no-untyped-def]
        loader = spec.loader
        data: Optional[bytes] = None

        if origin:
            if loader and hasattr(loader, "get_data"):
                try:
                    data = loader.get_data(origin)
                except FileNotFoundError:
                    data = None
                except Exception as exc:
                    logger.debug("Loader failed to read %s: %s", origin, exc)
            if data is None:
                try:
                    data = Path(origin).read_bytes()
                except Exception as exc:
                    logger.debug("Failed to read %s for digest: %s", origin, exc)

        if data is None and loader and hasattr(loader, "get_source"):
            try:
                source = loader.get_source(spec.name)
                if source is not None:
                    data = source.encode("utf-8")
            except Exception as exc:
                logger.debug("Failed to get source for %s: %s", spec.name, exc)

        if data is None:
            return None

        return hashlib.sha256(data).hexdigest()


def _rule_from_obj(identifier: str, obj) -> Optional[PluginRule]:  # type: ignore[no-untyped-def]
    """Normalize allowlist entry from JSON to PluginRule."""
    if isinstance(obj, str):
        return PluginRule(module=identifier, sha256=obj)

    if not isinstance(obj, dict):
        logger.warning("Invalid plugin allowlist entry for %s: %r", identifier, obj)
        return None

    module = obj.get("module") or identifier
    sha256 = obj.get("sha256")
    label = obj.get("label")

    if module is None:
        logger.warning("Plugin allowlist entry for %s missing module name", identifier)
        return None

    return PluginRule(module=module, sha256=sha256, label=label)


def load_allowlist_document(path: Path) -> Dict[str, Any]:
    if not path.exists():
        logger.debug("Plugin allowlist file %s missing; treating as empty", path)
        return {"modules": {}, "entry_points": {}}

    try:
        with path.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
        if not isinstance(raw, dict):
            raise ValueError("Allowlist JSON must be an object")
        raw.setdefault("modules", {})
        raw.setdefault("entry_points", {})
        return raw
    except Exception as exc:
        logger.warning("Failed to read plugin allowlist %s: %s", path, exc)
        return {"modules": {}, "entry_points": {}}


def write_allowlist_document(path: Path, data: Dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.warning("Could not ensure directory for %s: %s", path, exc)

    payload = {
        "modules": data.get("modules", {}),
        "entry_points": data.get("entry_points", {}),
    }
    tmp_path = path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
    os.replace(tmp_path, path)
