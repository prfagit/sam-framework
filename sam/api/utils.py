"""Utility helpers shared across API modules."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from ..config.settings import Settings

_SAFE_ID_PATTERN = re.compile(r"[^a-zA-Z0-9_.-]+")


def normalize_user_id(raw: str | None) -> str:
    if raw is None:
        return "default"
    cleaned = raw.strip()
    if not cleaned:
        return "default"
    sanitized = _SAFE_ID_PATTERN.sub("-", cleaned)
    return sanitized.strip("-") or "default"


def sanitize_agent_name(raw: str) -> str:
    cleaned = raw.strip()
    if not cleaned:
        return "agent"
    sanitized = _SAFE_ID_PATTERN.sub("-", cleaned)
    return sanitized.strip("-") or "agent"


def get_user_agents_dir(user_id: str) -> Path:
    base = Path(Settings.SAM_API_AGENT_ROOT).expanduser()
    normalized = normalize_user_id(user_id)
    path = base / normalized / "agents"
    path.mkdir(parents=True, exist_ok=True)
    return path


def generate_session_id(prefix: str | None = None) -> str:
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    if prefix:
        base = sanitize_agent_name(prefix)
    else:
        base = "sess"
    return f"{base}-{stamp}"


__all__ = ["generate_session_id", "get_user_agents_dir", "normalize_user_id", "sanitize_agent_name"]
