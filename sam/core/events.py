import logging
from collections import defaultdict
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

Subscriber = Callable[[str, Dict[str, Any]], Awaitable[None]]


class EventBus:
    """A minimal async event bus for agent/tool lifecycle hooks."""

    def __init__(self) -> None:
        self._subs: Dict[str, List[Subscriber]] = defaultdict(list)

    def subscribe(self, event: str, handler: Subscriber) -> None:
        self._subs[event].append(handler)

    def unsubscribe(self, event: str, handler: Subscriber) -> None:
        """Remove a previously subscribed handler if present.

        Safe to call multiple times; ignores if the handler is not registered.
        """
        try:
            handlers = self._subs.get(event)
            if not handlers:
                return
            # Remove all matching references
            self._subs[event] = [h for h in handlers if h is not handler]
        except Exception as e:
            logger.warning(f"Failed to unsubscribe handler for {event}: {e}")

    async def publish(self, event: str, payload: Dict[str, Any]) -> None:
        handlers = list(self._subs.get(event, []))
        for h in handlers:
            try:
                await h(event, payload)
            except Exception as e:
                logger.warning(f"Event handler error for {event}: {e}")


# Global bus for convenience (optional; hosts may provide their own)
_global_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    global _global_bus
    if _global_bus is None:
        _global_bus = EventBus()
    return _global_bus
