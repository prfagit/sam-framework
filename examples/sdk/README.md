# SDK Examples

Minimal examples for using SAM programmatically (without the CLI).

## 1) Direct Tool Calls

```python
import asyncio
from sam.core.builder import AgentBuilder

async def main():
    agent = await AgentBuilder().build()

    # Call a tool directly via the registry
    result = await agent.tools.call("search_web", {"query": "Solana news", "count": 3})
    print(result)

asyncio.run(main())
```

## 2) Headless Agent Loop

```python
import asyncio
from sam.core.builder import AgentBuilder

async def main():
    agent = await AgentBuilder().build()
    resp = await agent.run("Check my SOL balance", session_id="sdk_demo")
    print(resp)

asyncio.run(main())
```

## 3) Subscribe to Events

```python
import asyncio
from sam.core.builder import AgentBuilder
from sam.core.events import get_event_bus

async def on_tool(event, payload):
    print("EVENT:", event, payload["name"])

async def main():
    bus = get_event_bus()
    bus.subscribe("tool.called", on_tool)
    bus.subscribe("tool.succeeded", on_tool)
    bus.subscribe("tool.failed", on_tool)

    agent = await AgentBuilder().build()
    print(await agent.run("Search Solana news", session_id="sdk_events"))

asyncio.run(main())
```

