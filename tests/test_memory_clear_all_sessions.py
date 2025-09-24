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
        await mem.save_session("a", [{"role": "user", "content": "hi"}], user_id="alice")
        await mem.save_session("b", [], user_id="alice")
        await mem.save_session("c", [], user_id="bob")

        listed = await mem.list_sessions(limit=10, user_id="alice")
        assert len(listed) == 2

        deleted = await mem.clear_all_sessions(user_id="alice")
        assert deleted == 2

        listed_after = await mem.list_sessions(limit=10, user_id="alice")
        assert listed_after == []

        # Bob's session should remain
        remaining = await mem.list_sessions(limit=10, user_id="bob")
        assert len(remaining) == 1
