from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class RequestContext:
    """Lightweight context object describing the caller of an agent run.

    The framework keeps all fields optional so existing single-tenant flows
    can continue using the implicit "default" user without passing any data.
    Hosted applications can populate user identifiers, wallet handles, or
    configuration overrides while still sharing the same agent-building code.
    """

    user_id: str = "default"
    session_id: Optional[str] = None
    metadata: Optional[Mapping[str, Any]] = None
    config_overrides: Optional[Mapping[str, Any]] = None
    wallet_key_id: Optional[str] = None

    def cache_key(self) -> str:
        """Return a stable key for caching agents built for this context."""
        return self.user_id or "default"
