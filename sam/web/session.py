"""Web adapter utilities for integrating the SAM agent with GUI frontends.

This module provides a cached agent builder and convenient runner helpers
that expose agent/tool lifecycle through events suitable for UI updates.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, Optional

from ..core.agent import SAMAgent
from ..core.builder import AgentBuilder, cleanup_agent_fast
from ..core.events import get_event_bus


_agent_singleton: Optional[SAMAgent] = None


async def get_agent() -> SAMAgent:
    """Get or build a cached SAMAgent instance.

    Safe to call multiple times; builds the agent once per process.
    """
    global _agent_singleton
    if _agent_singleton is not None:
        return _agent_singleton
    # Lock-free init to avoid cross-loop lock issues in Streamlit reruns
    if _agent_singleton is None:
        _agent_singleton = await AgentBuilder().build()
    return _agent_singleton


async def close_agent() -> None:
    """Cleanup shared resources quickly.

    Useful for application shutdown or Streamlit 'Reset' actions.
    """
    global _agent_singleton
    try:
        # Attempt graceful agent.close if available
        if _agent_singleton and hasattr(_agent_singleton, "close"):
            try:
                await asyncio.wait_for(_agent_singleton.close(), timeout=1.0)
            except Exception:
                pass
        await cleanup_agent_fast()
    except Exception:
        # Swallow cleanup errors to avoid crashing callers
        pass
    finally:
        _agent_singleton = None


async def list_sessions(limit: int = 20):
    """List recent sessions via the agent's memory manager."""
    agent = await get_agent()
    try:
        return await agent.memory.list_sessions(limit=limit)
    except Exception:
        return []


async def get_default_session_id() -> str:
    """Return the latest session id or create a new dated one."""
    agent = await get_agent()
    latest = await agent.memory.get_latest_session()
    if latest:
        return latest.get("session_id", "default")
    from datetime import datetime
    new_id = f"sess-{datetime.utcnow().strftime('%Y%m%d-%H%M')}"
    await agent.memory.create_session(new_id)
    return new_id


async def new_session_id() -> str:
    """Create a new dated session and return its id."""
    agent = await get_agent()
    from datetime import datetime
    new_id = f"sess-{datetime.utcnow().strftime('%Y%m%d-%H%M')}"
    await agent.memory.create_session(new_id)
    return new_id


async def clear_all_sessions() -> int:
    """Delete all sessions; returns deleted count."""
    agent = await get_agent()
    return await agent.memory.clear_all_sessions()


def run_once(prompt: str, session_id: str = "default") -> str:
    """Synchronous helper for single-turn runs (non-streaming)."""

    async def _run() -> str:
        agent = await get_agent()
        return await agent.run(prompt, session_id)

    return asyncio.run(_run())


@asynccontextmanager
async def run_with_events(
    prompt: str, session_id: str = "default"
) -> AsyncIterator[AsyncIterator[Dict[str, Any]]]:
    """Context manager yielding an async iterator of events for a single run.

    Yields an iterator producing dictionaries like:
    - {"event": "tool.called", "payload": {...}}
    - {"event": "tool.succeeded", "payload": {...}}
    - {"event": "tool.failed", "payload": {...}}
    - {"event": "llm.usage", "payload": {...}}
    - {"event": "agent.message", "payload": {...}}  # final assistant message

    The iterator completes when the run finishes.
    """

    bus = get_event_bus()
    queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
    done = asyncio.Event()
    run_exc: Optional[Exception] = None

    async def handler(evt: str, payload: Dict[str, Any]) -> None:
        # Only forward events for our session_id (if provided)
        if payload.get("session_id") == session_id:
            await queue.put({"event": evt, "payload": payload})

    # Register temporary subscribers
    for evt in (
        "tool.called",
        "tool.succeeded",
        "tool.failed",
        "llm.usage",
        "agent.status",
        "agent.delta",
        "agent.message",
    ):
        bus.subscribe(evt, handler)

    async def _runner():
        nonlocal run_exc
        try:
            agent = await get_agent()
            # Do not publish final event here; adapter will stream and publish
            reply = await agent.run(prompt, session_id, publish_final_event=False)

            # Simulate delta streaming for UIs that render progressively
            text = reply or ""
            if text:
                chunk_size = 20
                for i in range(0, len(text), chunk_size):
                    delta = text[i : i + chunk_size]
                    try:
                        await bus.publish(
                            "agent.delta",
                            {"session_id": session_id, "content": delta},
                        )
                    except Exception:
                        pass
                    await asyncio.sleep(0.03)

            # Publish final message event with usage snapshot
            try:
                await bus.publish(
                    "agent.message",
                    {
                        "session_id": session_id,
                        "content": text,
                        "usage": dict(getattr(agent, "session_stats", {}) or {}),
                    },
                )
            except Exception:
                pass
        except Exception as e:
            run_exc = e
        finally:
            done.set()

    task = asyncio.create_task(_runner())

    async def _aiter() -> AsyncIterator[Dict[str, Any]]:
        try:
            while True:
                if done.is_set() and queue.empty():
                    break
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=0.1)
                    yield item
                except asyncio.TimeoutError:
                    continue
        finally:
            # Ensure the runner completes
            try:
                await asyncio.wait_for(task, timeout=0.1)
            except Exception:
                pass

    try:
        yield _aiter()
    finally:
        # Unsubscribe handlers to prevent leaks across reruns
        for evt in (
            "tool.called",
            "tool.succeeded",
            "tool.failed",
            "llm.usage",
            "agent.status",
            "agent.delta",
            "agent.message",
        ):
            bus.unsubscribe(evt, handler)
        # Ensure the runner finished before propagating any error
        try:
            await asyncio.wait_for(task, timeout=0.2)
        except Exception:
            pass
        # Propagate any runner exception to the caller
        if run_exc is not None:
            raise run_exc
