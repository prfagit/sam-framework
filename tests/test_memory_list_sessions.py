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
        await mem.save_session("s1", [{"role": "user", "content": "hi"}], user_id="alice")
        await mem.save_session(
            "s2",
            [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}],
            user_id="alice",
        )
        await mem.save_session("s3", [], user_id="bob")

        # Update s1 to ensure updated_at ordering changes
        await mem.save_session("s1", [{"role": "user", "content": "hi again"}], user_id="alice")

        sessions = await mem.list_sessions(limit=10, user_id="alice")
        assert isinstance(sessions, list)
        assert len(sessions) == 2
        # Newest first; s1 was updated last
        assert sessions[0]["session_id"] == "s1"
        # message_count present
        assert all("message_count" in s for s in sessions)
        assert all(s["user_id"] == "alice" for s in sessions)

        # ensure filtering works for other user
        sessions_bob = await mem.list_sessions(limit=10, user_id="bob")
        assert [s["session_id"] for s in sessions_bob] == ["s3"]
