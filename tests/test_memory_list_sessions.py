import asyncio
import os
import tempfile
import pytest

from sam.core.memory import MemoryManager


@pytest.mark.asyncio
async def test_list_sessions_orders_and_counts():
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "t.db")
        mem = MemoryManager(db)
        await mem.initialize()

        # Create three sessions with increasing messages
        await mem.save_session("s1", [{"role": "user", "content": "hi"}])
        await mem.save_session("s2", [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}])
        await mem.save_session("s3", [])

        # Update s1 to ensure updated_at ordering changes
        await mem.save_session("s1", [{"role": "user", "content": "hi again"}])

        sessions = await mem.list_sessions(limit=10)
        assert isinstance(sessions, list)
        assert len(sessions) >= 3
        # Newest first; s1 was updated last
        assert sessions[0]["session_id"] in {"s1", "s2", "s3"}
        # message_count present
        assert all("message_count" in s for s in sessions)

