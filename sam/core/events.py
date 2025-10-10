import asyncio
import logging
import os
from collections import defaultdict, deque
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Awaitable, Callable, Deque, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

Subscriber = Callable[[str, Dict[str, Any]], Awaitable[None]]


# Event system configuration
EVENT_QUEUE_MAX_SIZE = int(os.getenv("SAM_EVENT_QUEUE_MAX_SIZE", "1000"))
EVENT_ENABLE_FILTERING = os.getenv("SAM_EVENT_ENABLE_FILTERING", "1") == "1"
EVENT_ENABLE_PRIORITIES = os.getenv("SAM_EVENT_ENABLE_PRIORITIES", "1") == "1"


class EventPriority(IntEnum):
    """Event priority levels (higher = more important)."""

    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass
class EventStats:
    """Event bus statistics."""

    total_published: int = 0
    total_delivered: int = 0
    total_dropped: int = 0
    total_errors: int = 0
    filtered_count: int = 0
    queue_size: int = 0
    subscriber_count: int = 0


class EventBus:
    """Enhanced async event bus with filtering, priorities, and backpressure handling."""

    def __init__(
        self,
        max_queue_size: int = EVENT_QUEUE_MAX_SIZE,
        enable_filtering: bool = EVENT_ENABLE_FILTERING,
        enable_priorities: bool = EVENT_ENABLE_PRIORITIES,
    ) -> None:
        self._subs: Dict[str, List[Subscriber]] = defaultdict(list)
        self._filters: Set[str] = set()  # Event names to filter out
        self._priority_map: Dict[str, EventPriority] = {}  # Event -> priority mapping
        self._sync_mode = (
            os.getenv("SAM_EVENT_SYNC_MODE", "0") == "1" or os.getenv("SAM_TEST_MODE") == "1"
        )

        # Backpressure handling
        self._max_queue_size = max_queue_size
        self._queue: Deque[tuple[EventPriority, str, Dict[str, Any]]] = deque()
        self._queue_task: Optional[asyncio.Task[None]] = None

        # Configuration flags
        self._enable_filtering = enable_filtering
        self._enable_priorities = enable_priorities and not self._sync_mode

        # Statistics
        self._stats = EventStats()

        # Start queue processor unless running in sync mode (used for deterministic tests)
        if not self._sync_mode:
            self._start_queue_processor()

        logger.info(
            f"Initialized event bus (max_queue: {max_queue_size}, "
            f"filtering: {enable_filtering}, priorities: {enable_priorities and not self._sync_mode}, "
            f"sync_mode: {self._sync_mode})"
        )

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

    async def publish(
        self, event: str, payload: Dict[str, Any], priority: EventPriority = EventPriority.NORMAL
    ) -> None:
        """Publish an event with optional priority.

        Args:
            event: Event name
            payload: Event data
            priority: Event priority (higher = more important)
        """
        self._stats.total_published += 1

        # Check if event is filtered
        if self._enable_filtering and event in self._filters:
            self._stats.filtered_count += 1
            logger.debug(f"Event filtered: {event}")
            return

        # Use configured priority if available
        if self._enable_priorities and event in self._priority_map:
            priority = self._priority_map[event]

        if self._sync_mode:
            handlers = list(self._subs.get(event, []))
            for h in handlers:
                try:
                    await h(event, payload)
                    self._stats.total_delivered += 1
                except Exception as e:
                    self._stats.total_errors += 1
                    logger.warning(f"Event handler error for {event}: {e}")
            self._stats.queue_size = 0
            return

        # Add to queue for async processing
        if len(self._queue) >= self._max_queue_size:
            # Backpressure: drop lowest priority event
            self._drop_lowest_priority_event()
            self._stats.total_dropped += 1
            logger.warning(f"Event queue full, dropped event: {event}")

        self._queue.append((priority, event, payload))
        self._stats.queue_size = len(self._queue)

    def _drop_lowest_priority_event(self) -> None:
        """Drop the lowest priority event from the queue."""
        if not self._queue:
            return

        # Find lowest priority event
        min_priority = min(item[0] for item in self._queue)

        # Remove first occurrence of lowest priority
        for i, (priority, event, payload) in enumerate(self._queue):
            if priority == min_priority:
                del self._queue[i]
                break

    def _start_queue_processor(self) -> None:
        """Start the async queue processor task."""
        try:
            asyncio.get_running_loop()
            self._queue_task = asyncio.create_task(self._process_queue())
        except RuntimeError:
            # No running loop yet
            pass

    async def _process_queue(self) -> None:
        """Process events from queue in priority order."""
        while True:
            try:
                if not self._queue:
                    await asyncio.sleep(0.01)  # Small delay when queue empty
                    continue

                # Sort queue by priority (highest first)
                if self._enable_priorities and len(self._queue) > 1:
                    self._queue = deque(sorted(self._queue, key=lambda x: x[0], reverse=True))

                # Get highest priority event
                priority, event, payload = self._queue.popleft()
                self._stats.queue_size = len(self._queue)

                # Deliver to all subscribers
                handlers = list(self._subs.get(event, []))
                for h in handlers:
                    try:
                        await h(event, payload)
                        self._stats.total_delivered += 1
                    except Exception as e:
                        self._stats.total_errors += 1
                        logger.warning(f"Event handler error for {event}: {e}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in event queue processor: {e}")
                await asyncio.sleep(0.1)

    def add_filter(self, event: str) -> None:
        """Add an event name to the filter list (will be ignored).

        Args:
            event: Event name to filter
        """
        self._filters.add(event)
        logger.debug(f"Added event filter: {event}")

    def remove_filter(self, event: str) -> None:
        """Remove an event from the filter list.

        Args:
            event: Event name to unfilter
        """
        self._filters.discard(event)
        logger.debug(f"Removed event filter: {event}")

    def set_priority(self, event: str, priority: EventPriority) -> None:
        """Set the priority for a specific event type.

        Args:
            event: Event name
            priority: Priority level
        """
        self._priority_map[event] = priority
        logger.debug(f"Set event priority: {event} -> {priority.name}")

    def get_stats(self) -> Dict[str, Any]:
        """Get event bus statistics.

        Returns:
            Dictionary with statistics
        """
        self._stats.subscriber_count = sum(len(handlers) for handlers in self._subs.values())
        self._stats.queue_size = len(self._queue)

        return {
            "total_published": self._stats.total_published,
            "total_delivered": self._stats.total_delivered,
            "total_dropped": self._stats.total_dropped,
            "total_errors": self._stats.total_errors,
            "filtered_count": self._stats.filtered_count,
            "queue_size": self._stats.queue_size,
            "subscriber_count": self._stats.subscriber_count,
            "max_queue_size": self._max_queue_size,
            "enable_filtering": self._enable_filtering,
            "enable_priorities": self._enable_priorities,
            "active_filters": len(self._filters),
            "priority_mappings": len(self._priority_map),
        }

    async def shutdown(self) -> None:
        """Shutdown the event bus and stop queue processor."""
        if self._queue_task and not self._queue_task.done():
            self._queue_task.cancel()
            try:
                await self._queue_task
            except asyncio.CancelledError:
                pass

        # Clear queue
        self._queue.clear()
        logger.info("Event bus shutdown completed")


# Global bus for convenience (optional; hosts may provide their own)
_global_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    global _global_bus
    if _global_bus is None:
        _global_bus = EventBus()
    return _global_bus
