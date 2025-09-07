import asyncio
from sam.core.builder import AgentBuilder
from sam.core.events import get_event_bus


async def on_event(event: str, payload):
    # Minimal printout; in real apps you might push to metrics or a UI
    name = payload.get("name") or event
    print(f"EVENT {event}: {name}")


async def main():
    bus = get_event_bus()
    bus.subscribe("tool.called", on_event)
    bus.subscribe("tool.succeeded", on_event)
    bus.subscribe("tool.failed", on_event)
    bus.subscribe("llm.usage", on_event)

    agent = await AgentBuilder().build()
    print(await agent.run("Search Solana news", session_id="sdk_events"))


if __name__ == "__main__":
    asyncio.run(main())
