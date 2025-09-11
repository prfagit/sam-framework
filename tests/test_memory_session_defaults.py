import os
import tempfile
import pytest

from sam.core.memory import MemoryManager


@pytest.mark.asyncio
async def test_get_latest_and_create_session_defaults():
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "mem.db")
        mem = MemoryManager(db)
        await mem.initialize()

        latest = await mem.get_latest_session()
        assert latest is None

        created = await mem.create_session("sess-20240101-0000")
        assert created is True

        latest = await mem.get_latest_session()
        assert latest is not None
        assert latest["session_id"].startswith("sess-")
