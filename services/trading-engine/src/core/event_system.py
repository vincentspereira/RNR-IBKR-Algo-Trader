from enum import Enum, auto
from typing import Any, Dict, Optional, Callable, Awaitable

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
    ERROR = auto()

class Event:
    def __init__(self, type: EventType, data: Any, priority: EventPriority = EventPriority.NORMAL):
        self.type = type
        self.data = data
        self.priority = priority

class EventBus:
    def __init__(self):
        self.subscribers = {}

    async def publish(self, event: Event):
        pass

    def subscribe(self, event_type: EventType, callback: Callable[[Event], Awaitable[None]]):
        pass

def get_event_bus() -> EventBus:
    return EventBus()
