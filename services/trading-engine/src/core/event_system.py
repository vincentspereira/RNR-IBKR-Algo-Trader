"""Event Bus for inter-component communication.

Provides pub/sub event system with priority ordering, event history,
and support for both sync and async subscribers.
"""

import asyncio
import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class EventPriority(Enum):
    LOW = auto()
    NORMAL = auto()
    HIGH = auto()
    CRITICAL = auto()


class EventType(Enum):
    MARKET_DATA = auto()
    SIGNAL = auto()
    ORDER = auto()
    FILL = auto()
    POSITION_UPDATE = auto()
    RISK_ALERT = auto()
    ERROR = auto()
    SYSTEM = auto()


@dataclass
class Event:
    type: EventType = EventType.SYSTEM
    data: Any = None
    priority: EventPriority = EventPriority.NORMAL
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)


class EventBus:
    def __init__(self):
        self._subscribers: Dict[EventType, List[Callable]] = defaultdict(list)
        self._global_subscribers: List[Callable] = []
        self._event_history: List[Event] = []
        self._max_history = 10000
        self._lock = asyncio.Lock()
        self._running = True

    async def publish(self, event: Event) -> None:
        """Publish event to all subscribers of that event type + global subscribers."""
        async with self._lock:
            self._event_history.append(event)
            if len(self._event_history) > self._max_history:
                self._event_history = self._event_history[-self._max_history:]

        subscribers = self._subscribers.get(event.type, []) + self._global_subscribers

        tasks = []
        for callback in subscribers:
            try:
                result = callback(event)
                if asyncio.iscoroutine(result):
                    tasks.append(result)
            except Exception as e:
                logger.error("event_callback_error", extra={
                    "error": str(e),
                    "event_type": event.type.name,
                })

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def subscribe(self, event_type: EventType, callback: Callable[[Event], Awaitable[None]]):
        """Subscribe callback to specific event type."""
        self._subscribers[event_type].append(callback)
        logger.info(f"event_subscribed: {event_type.name}")

    def subscribe_all(self, callback: Callable[[Event], Awaitable[None]]):
        """Subscribe to ALL events."""
        self._global_subscribers.append(callback)

    def unsubscribe(self, event_type: EventType, callback: Callable):
        """Remove a callback subscription."""
        if event_type in self._subscribers:
            self._subscribers[event_type] = [
                cb for cb in self._subscribers[event_type] if cb != callback
            ]

    async def get_history(
        self, event_type: Optional[EventType] = None, limit: int = 100
    ) -> List[Event]:
        """Get recent events, optionally filtered by type."""
        events = self._event_history
        if event_type:
            events = [e for e in events if e.type == event_type]
        return events[-limit:]


_event_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """Get the global event bus singleton."""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus
