from __future__ import annotations

import asyncio
from typing import Dict, Optional

from .agent import SAMAgent
from .builder import AgentBuilder
from .context import RequestContext


class AgentFactory:
    """Build and cache agents for specific request contexts.

    The default behavior matches the previous singleton semantics: if no
    context is supplied, the factory returns a shared agent built once per
    process. Hosted services can provide user-specific contexts to isolate
    configuration, secure storage, and session state per caller.
    """

    def __init__(self, builder: Optional[AgentBuilder] = None) -> None:
        self._builder = builder or AgentBuilder()
        self._agents: Dict[str, SAMAgent] = {}
        self._lock = asyncio.Lock()

    async def get_agent(self, context: Optional[RequestContext] = None) -> SAMAgent:
        ctx = context or RequestContext()
        cache_key = ctx.cache_key()
        if cache_key in self._agents:
            return self._agents[cache_key]

        async with self._lock:
            # Double-check inside the lock to avoid duplicate builds
            agent = self._agents.get(cache_key)
            if agent is not None:
                return agent
            agent = await self._builder.build(context=ctx)
            self._agents[cache_key] = agent
            return agent

    async def clear(self, context: Optional[RequestContext] = None) -> None:
        """Dispose a cached agent for the given context (or the default)."""
        ctx = context or RequestContext()
        cache_key = ctx.cache_key()
        agent = self._agents.pop(cache_key, None)
        if agent and hasattr(agent, "close"):
            try:
                await agent.close()  # type: ignore[attr-defined]
            except Exception:
                pass

    async def clear_all(self) -> None:
        """Dispose every cached agent synchronously."""
        for cache_key, agent in list(self._agents.items()):
            try:
                if hasattr(agent, "close"):
                    await agent.close()  # type: ignore[attr-defined]
            except Exception:
                pass
            finally:
                self._agents.pop(cache_key, None)


_default_factory: Optional[AgentFactory] = None


def get_default_factory() -> AgentFactory:
    global _default_factory
    if _default_factory is None:
        _default_factory = AgentFactory()
    return _default_factory
