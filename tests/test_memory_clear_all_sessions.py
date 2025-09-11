import os
import tempfile
import pytest

from sam.core.memory import MemoryManager


@pytest.mark.asyncio
async def test_clear_all_sessions():
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "mem.db")
        mem = MemoryManager(db)
        await mem.initialize()

        # Seed a few sessions
        await mem.save_session("a", [{"role": "user", "content": "hi"}])
        await mem.save_session("b", [])
        await mem.save_session("c", [])

        listed = await mem.list_sessions(limit=10)
        assert len(listed) >= 3

        deleted = await mem.clear_all_sessions()
        assert deleted >= 3

        listed_after = await mem.list_sessions(limit=10)
        assert listed_after == []

