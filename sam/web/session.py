"""Web adapter utilities for integrating the SAM agent with GUI frontends.

This module provides a cached agent builder and convenient runner helpers
that expose agent/tool lifecycle through events suitable for UI updates.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, Optional

from ..core.agent import SAMAgent
from ..core.agent_factory import AgentFactory, get_default_factory
from ..core.builder import cleanup_agent_fast
from ..core.context import RequestContext
from ..core.events import get_event_bus


_legacy_singleton: Optional[SAMAgent] = None
_agent_singleton: Optional[SAMAgent] = None  # Backward compatibility alias
_factory: AgentFactory = get_default_factory()


def _context_user_id(context: Optional[RequestContext]) -> str:
    if context and context.user_id:
        return context.user_id
    return "default"


async def get_agent(context: Optional[RequestContext] = None) -> SAMAgent:
    """Get or build a cached SAMAgent instance.

    Safe to call multiple times; builds the agent once per process.
    """
    global _legacy_singleton, _agent_singleton
    if context is None and _legacy_singleton is not None:
        return _legacy_singleton

    agent = await _factory.get_agent(context)

    # Preserve legacy behavior for callers that do not supply context by
    # keeping a shared singleton reference in addition to the factory cache.
    if context is None:
        _legacy_singleton = agent
        _agent_singleton = agent
    return agent


async def close_agent(context: Optional[RequestContext] = None) -> None:
    """Cleanup shared resources quickly.

    Useful for application shutdown or Streamlit 'Reset' actions.
    """
    global _legacy_singleton, _agent_singleton
    try:
        if context is None and _legacy_singleton is not None:
            if hasattr(_legacy_singleton, "close"):
                try:
                    await asyncio.wait_for(_legacy_singleton.close(), timeout=1.0)
                except Exception:
                    pass
        else:
            await _factory.clear(context)
        await cleanup_agent_fast()
    except Exception:
        # Swallow cleanup errors to avoid crashing callers
        pass
    finally:
        if context is None:
            _legacy_singleton = None
            _agent_singleton = None


async def list_sessions(
    limit: int = 20, context: Optional[RequestContext] = None
) -> list[dict[str, Any]]:
    """List recent sessions via the agent's memory manager."""
    agent = await get_agent(context)
    try:
        user_id = _context_user_id(context)
        sessions: list[dict[str, Any]] = await agent.memory.list_sessions(
            limit=limit, user_id=user_id
        )
        return sessions
    except Exception:
        return []


async def get_default_session_id(context: Optional[RequestContext] = None) -> str:
    """Return the latest session id or create a new dated one."""
    agent = await get_agent(context)
    user_id = _context_user_id(context)
    latest = await agent.memory.get_latest_session(user_id=user_id)
    if isinstance(latest, dict):
        session_val = latest.get("session_id", "default")
        return session_val if isinstance(session_val, str) else "default"
    from datetime import datetime
    new_id = f"sess-{datetime.utcnow().strftime('%Y%m%d-%H%M')}"
    await agent.memory.create_session(new_id, user_id=user_id)
    return new_id


async def new_session_id(context: Optional[RequestContext] = None) -> str:
    """Create a new dated session and return its id."""
    agent = await get_agent(context)
    from datetime import datetime
    user_id = _context_user_id(context)
    new_id = f"sess-{datetime.utcnow().strftime('%Y%m%d-%H%M')}"
    await agent.memory.create_session(new_id, user_id=user_id)
    return new_id


async def clear_all_sessions(context: Optional[RequestContext] = None) -> int:
    """Delete all sessions; returns deleted count."""
    agent = await get_agent(context)
    user_id = _context_user_id(context)
    return await agent.memory.clear_all_sessions(user_id=user_id)


def run_once(prompt: str, session_id: str = "default", context: Optional[RequestContext] = None) -> str:
    """Synchronous helper for single-turn runs (non-streaming)."""

    async def _run() -> str:
        agent = await get_agent(context)
        return await agent.run(prompt, session_id, context=context)

    return asyncio.run(_run())


@asynccontextmanager
async def run_with_events(
    prompt: str,
    session_id: str = "default",
    context: Optional[RequestContext] = None,
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

    expected_user_id = _context_user_id(context)

    async def handler(evt: str, payload: Dict[str, Any]) -> None:
        # Only forward events for our session_id (if provided)
        payload_user = payload.get("user_id", "default")
        if payload.get("session_id") == session_id and payload_user == expected_user_id:
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

    async def _runner() -> None:
        nonlocal run_exc
        try:
            agent = await get_agent(context)
            # Do not publish final event here; adapter will stream and publish
            reply = await agent.run(
                prompt, session_id, publish_final_event=False, context=context
            )

            # Simulate delta streaming for UIs that render progressively
            text = reply or ""
            if text:
                chunk_size = 20
                for i in range(0, len(text), chunk_size):
                    delta = text[i : i + chunk_size]
                    try:
                        await bus.publish(
                            "agent.delta",
                            {
                                "session_id": session_id,
                                "user_id": expected_user_id,
                                "content": delta,
                            },
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
                        "user_id": expected_user_id,
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
