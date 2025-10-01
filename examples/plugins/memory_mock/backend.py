"""In-memory memory backend plugin for SAM (example).

Usage options:

1) Via env var override (no packaging needed):

   export SAM_MEMORY_BACKEND="examples.plugins.memory_mock.backend:create_backend"

2) As a packaged plugin via entry points (requires packaging/install):

   [project.entry-points."sam.memory_backends"]
   in_memory = "examples.plugins.memory_mock.backend:create_backend"
"""

from __future__ import annotations

from typing import Any, Dict, List

from sam.core.memory import MemoryManager


class InMemoryMemoryManager(MemoryManager):
    def __init__(self, db_path: str = ":memory:"):
        # Reuse the same API but don't use filesystem
        super().__init__(db_path)
        self._sessions: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}

    async def initialize(self):
        # Nothing to initialize, keep API compatibility
        return None

    @staticmethod
    def _normalize_user(user_id: str | None) -> str:
        if user_id and user_id.strip():
            return user_id.strip()
        return "default"

    async def save_session(self, session_id: str, messages: List[Dict], user_id: str | None = None):
        uid = self._normalize_user(user_id)
        store = self._sessions.setdefault(uid, {})
        store[session_id] = list(messages)

    async def load_session(self, session_id: str, user_id: str | None = None) -> List[Dict]:
        uid = self._normalize_user(user_id)
        return list(self._sessions.get(uid, {}).get(session_id, []))


def create_backend(db_path: str) -> InMemoryMemoryManager:
    return InMemoryMemoryManager(db_path)
