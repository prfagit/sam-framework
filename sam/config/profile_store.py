"""Profile storage for non-secret SAM configuration.

The goal is to keep .env limited to bootstrap values (encryption key,
database path, etc.) while persisting user-configurable preferences in a
managed location that can be shared between the CLI, the interactive
settings flow, and future front-end surfaces.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

PROFILE_SCHEMA_VERSION = 1

PROFILE_SCHEMA: Dict[str, Dict[str, Any]] = {
    "LLM_PROVIDER": {"default": "openai", "type": str},
    "OPENAI_BASE_URL": {"default": None, "type": str},
    "OPENAI_MODEL": {"default": "gpt-4o-mini", "type": str},
    "ANTHROPIC_BASE_URL": {"default": "https://api.anthropic.com", "type": str},
    "ANTHROPIC_MODEL": {"default": "claude-3-5-sonnet-latest", "type": str},
    "XAI_BASE_URL": {"default": "https://api.x.ai/v1", "type": str},
    "XAI_MODEL": {"default": "grok-2-latest", "type": str},
    "LOCAL_LLM_BASE_URL": {"default": "http://localhost:11434/v1", "type": str},
    "LOCAL_LLM_MODEL": {"default": "llama3.1", "type": str},
    "SAM_SOLANA_RPC_URL": {"default": "https://api.mainnet-beta.solana.com", "type": str},
    "SAM_SOLANA_ADDRESS": {"default": None, "type": str},
    "SAM_DB_PATH": {"default": ".sam/sam_memory.db", "type": str},
    "RATE_LIMITING_ENABLED": {"default": False, "type": bool},
    "ENABLE_SOLANA_TOOLS": {"default": True, "type": bool},
    "ENABLE_PUMP_FUN_TOOLS": {"default": True, "type": bool},
    "ENABLE_DEXSCREENER_TOOLS": {"default": True, "type": bool},
    "ENABLE_JUPITER_TOOLS": {"default": True, "type": bool},
    "ENABLE_SEARCH_TOOLS": {"default": True, "type": bool},
    "ENABLE_POLYMARKET_TOOLS": {"default": True, "type": bool},
    "ENABLE_ASTER_FUTURES_TOOLS": {"default": False, "type": bool},
    "ENABLE_HYPERLIQUID_TOOLS": {"default": False, "type": bool},
    "ASTER_BASE_URL": {"default": "https://fapi.asterdex.com", "type": str},
    "ASTER_DEFAULT_RECV_WINDOW": {"default": 5000, "type": int},
    "HYPERLIQUID_API_URL": {"default": "https://api.hyperliquid.xyz", "type": str},
    "HYPERLIQUID_DEFAULT_SLIPPAGE": {"default": 0.05, "type": float},
    "HYPERLIQUID_REQUEST_TIMEOUT": {"default": None, "type": float},
    "HYPERLIQUID_ACCOUNT_ADDRESS": {"default": None, "type": str},
    "EVM_WALLET_ADDRESS": {"default": None, "type": str},
    "MAX_TRANSACTION_SOL": {"default": 1000.0, "type": float},
    "DEFAULT_SLIPPAGE": {"default": 1, "type": int},
    "LOG_LEVEL": {"default": "INFO", "type": str},
    "SAM_LEGAL_ACCEPTED": {"default": False, "type": bool},
    "BRAVE_API_KEY_PRESENT": {"default": False, "type": bool},
}

PROFILE_KEYS = set(PROFILE_SCHEMA.keys())

PROFILE_DIR_ENV = "SAM_PROFILE_DIR"
DEFAULT_PROFILE_SUBDIR = ".sam"
PROFILE_FILENAME = "settings.json"


def _profile_dir() -> Path:
    """Return the directory that should hold the profile file."""

    root = os.getenv(PROFILE_DIR_ENV)
    if root:
        return Path(root).expanduser().resolve()
    return Path(DEFAULT_PROFILE_SUBDIR)


def _profile_path() -> Path:
    return _profile_dir() / PROFILE_FILENAME


def _coerce(value: Any, expected_type: type) -> Any:
    if value is None:
        return None
    if expected_type is bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "on"}:
                return True
            if normalized in {"false", "0", "no", "off"}:
                return False
        raise ValueError(f"Cannot coerce value '{value}' to bool")
    if expected_type is int:
        if isinstance(value, int):
            return value
        try:
            return int(value)
        except Exception as exc:
            raise ValueError(f"Cannot coerce value '{value}' to int") from exc
    if expected_type is float:
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(value)
        except Exception as exc:
            raise ValueError(f"Cannot coerce value '{value}' to float") from exc
    if expected_type is str:
        if value is None:
            return None
        return str(value)
    return value


def _apply_schema(data: Dict[str, Any]) -> Dict[str, Any]:
    validated: Dict[str, Any] = {}
    for key, meta in PROFILE_SCHEMA.items():
        expected_type = meta.get("type", str)
        default = meta.get("default")
        if key not in data or data[key] is None:
            validated[key] = default
            continue
        try:
            validated[key] = _coerce(data[key], expected_type)
        except ValueError:
            validated[key] = default
    # Carry through unknown keys to avoid data loss
    for key, value in data.items():
        if key not in validated:
            validated[key] = value
    return validated


class ProfileStore:
    """Thin JSON-backed key-value store for user-facing configuration."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or _profile_path()
        self._data: Dict[str, Any] = {}
        self._loaded = False
        self._meta: Dict[str, Any] = {"schema_version": PROFILE_SCHEMA_VERSION}

    @property
    def data(self) -> Dict[str, Any]:
        self._ensure_loaded()
        return self._data

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._data = {}
        if self.path.exists():
            try:
                with self.path.open("r", encoding="utf-8") as fh:
                    payload = json.load(fh)
                if isinstance(payload, dict) and "data" in payload:
                    self._data = payload.get("data", {}) or {}
                    self._meta = payload.get("meta", {}) or {}
                    self._meta.setdefault("schema_version", payload.get("schema_version", 0))
                elif isinstance(payload, dict):
                    self._data = payload
                    self._meta = {"schema_version": 0}
            except Exception:
                self._data = {}
                self._meta = {"schema_version": 0}
        self._data = _apply_schema(self._data)
        self._meta.setdefault("schema_version", PROFILE_SCHEMA_VERSION)
        self._loaded = True

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._ensure_loaded()
        merged = self._data.copy()
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
        self._data = _apply_schema(merged)
        self._write()

    def update(self, values: Dict[str, Any]) -> None:
        if not values:
            return
        self._ensure_loaded()
        merged = self._data.copy()
        for key, value in values.items():
            if value is None:
                merged.pop(key, None)
            else:
                merged[key] = value
        validated = _apply_schema(merged)
        if validated != self._data:
            self._data = validated
            self._write()

    def remove(self, key: str) -> None:
        self._ensure_loaded()
        if key in self._data:
            self._data.pop(key, None)
            self._write()

    def _write(self) -> None:
        self._ensure_loaded()
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        payload = {
            "data": self._data,
            "meta": {"schema_version": PROFILE_SCHEMA_VERSION},
        }
        with tmp_path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.write("\n")
        tmp_path.replace(path)


_PROFILE_STORE: Optional[ProfileStore] = None


def get_profile_store() -> ProfileStore:
    global _PROFILE_STORE
    if _PROFILE_STORE is None:
        _PROFILE_STORE = ProfileStore()
    return _PROFILE_STORE


def load_profile() -> Dict[str, Any]:
    return get_profile_store().data.copy()


def migrate_env_to_profile(keys: Iterable[str]) -> Dict[str, Any]:
    """Populate profile from environment variables when first-run.

    Returns the dictionary of values that were written so callers can decide
    whether to update the legacy .env file or display migration messages.
    """

    store = get_profile_store()
    snapshot = store.data.copy()
    new_values: Dict[str, Any] = {}
    for key in keys:
        if key in snapshot:
            continue
        val = os.getenv(key)
        if val is not None:
            new_values[key] = val
    if new_values:
        store.update(new_values)
    return new_values
