import pytest

from sam.core.memory_provider import create_memory_manager


@pytest.mark.asyncio
async def test_memory_backend_env_override(monkeypatch):
    # Point to the example in-memory backend factory
    monkeypatch.setenv("SAM_MEMORY_BACKEND", "examples.plugins.memory_mock.backend:create_backend")

    mm = create_memory_manager(":memory:")
    # Should initialize without error
    await getattr(mm, "initialize")()

    # Save and load a session
    sid = "test_session"
    messages = [{"role": "user", "content": "hello"}]
    await mm.save_session(sid, messages)
    loaded = await mm.load_session(sid)
    assert loaded == messages
