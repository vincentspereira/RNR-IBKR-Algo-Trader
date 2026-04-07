"""Unit tests for the Event Bus."""

import asyncio
import pytest

from src.core.event_system import (
    Event,
    EventBus,
    EventPriority,
    EventType,
)


class TestEventBusPublishSubscribe:
    """Tests for publish/subscribe mechanics."""

    @pytest.mark.asyncio
    async def test_publish_delivers_to_subscribers(self, event_bus):
        received = []

        async def handler(event):
            received.append(event)

        event_bus.subscribe(EventType.ORDER, handler)
        event = Event(type=EventType.ORDER, data={"action": "buy"})
        await event_bus.publish(event)

        assert len(received) == 1
        assert received[0].data["action"] == "buy"

    @pytest.mark.asyncio
    async def test_subscribe_multiple_callbacks(self, event_bus):
        results_a = []
        results_b = []

        async def handler_a(event):
            results_a.append(event)

        async def handler_b(event):
            results_b.append(event)

        event_bus.subscribe(EventType.SIGNAL, handler_a)
        event_bus.subscribe(EventType.SIGNAL, handler_b)
        await event_bus.publish(Event(type=EventType.SIGNAL))

        assert len(results_a) == 1
        assert len(results_b) == 1

    @pytest.mark.asyncio
    async def test_subscribers_only_receive_subscribed_type(self, event_bus):
        order_events = []

        async def handler(event):
            order_events.append(event)

        event_bus.subscribe(EventType.ORDER, handler)
        await event_bus.publish(Event(type=EventType.SIGNAL))
        await event_bus.publish(Event(type=EventType.FILL))

        assert len(order_events) == 0

    @pytest.mark.asyncio
    async def test_sync_callback_wrapped_as_coroutine(self, event_bus):
        received = []

        def sync_handler(event):
            received.append(event)

        event_bus.subscribe(EventType.ERROR, sync_handler)
        await event_bus.publish(Event(type=EventType.ERROR, data={"msg": "oops"}))

        assert len(received) == 1
        assert received[0].data["msg"] == "oops"


class TestEventBusUnsubscribe:
    """Tests for unsubscribe functionality."""

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_callback(self, event_bus):
        received = []

        async def handler(event):
            received.append(event)

        event_bus.subscribe(EventType.ORDER, handler)
        event_bus.unsubscribe(EventType.ORDER, handler)
        await event_bus.publish(Event(type=EventType.ORDER))

        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_unsubscribe_only_removes_target_callback(self, event_bus):
        kept = []
        removed = []

        async def handler_a(event):
            kept.append(event)

        async def handler_b(event):
            removed.append(event)

        event_bus.subscribe(EventType.ORDER, handler_a)
        event_bus.subscribe(EventType.ORDER, handler_b)
        event_bus.unsubscribe(EventType.ORDER, handler_b)
        await event_bus.publish(Event(type=EventType.ORDER))

        assert len(kept) == 1
        assert len(removed) == 0


class TestEventBusGlobalSubscriber:
    """Tests for subscribe_all (global subscriber)."""

    @pytest.mark.asyncio
    async def test_global_subscriber_receives_all_events(self, event_bus):
        received = []

        async def global_handler(event):
            received.append(event)

        event_bus.subscribe_all(global_handler)
        await event_bus.publish(Event(type=EventType.ORDER))
        await event_bus.publish(Event(type=EventType.SIGNAL))
        await event_bus.publish(Event(type=EventType.FILL))

        assert len(received) == 3

    @pytest.mark.asyncio
    async def test_global_and_specific_subscribers_both_fire(self, event_bus):
        specific = []
        global_events = []

        async def specific_handler(event):
            specific.append(event)

        async def global_handler(event):
            global_events.append(event)

        event_bus.subscribe(EventType.ORDER, specific_handler)
        event_bus.subscribe_all(global_handler)
        await event_bus.publish(Event(type=EventType.ORDER))

        assert len(specific) == 1
        assert len(global_events) == 1


class TestEventHistory:
    """Tests for event history tracking."""

    @pytest.mark.asyncio
    async def test_event_history_records_published_events(self, event_bus):
        await event_bus.publish(Event(type=EventType.ORDER, data={"id": 1}))
        await event_bus.publish(Event(type=EventType.SIGNAL, data={"id": 2}))

        history = await event_bus.get_history()
        assert len(history) == 2

    @pytest.mark.asyncio
    async def test_event_history_filter_by_type(self, event_bus):
        await event_bus.publish(Event(type=EventType.ORDER))
        await event_bus.publish(Event(type=EventType.SIGNAL))
        await event_bus.publish(Event(type=EventType.ORDER))

        order_history = await event_bus.get_history(event_type=EventType.ORDER)
        assert len(order_history) == 2
        assert all(e.type == EventType.ORDER for e in order_history)

    @pytest.mark.asyncio
    async def test_event_history_limit(self, event_bus):
        for i in range(10):
            await event_bus.publish(Event(type=EventType.SYSTEM, data={"i": i}))

        history = await event_bus.get_history(limit=3)
        assert len(history) == 3
        assert history[0].data["i"] == 7
        assert history[2].data["i"] == 9

    @pytest.mark.asyncio
    async def test_event_history_respects_max(self, event_bus):
        event_bus._max_history = 5
        for i in range(10):
            await event_bus.publish(Event(type=EventType.SYSTEM, data={"i": i}))

        history = await event_bus.get_history()
        assert len(history) == 5
        assert history[0].data["i"] == 5


class TestEventCallbackErrorHandling:
    """Tests that errors in callbacks don't break the event bus."""

    @pytest.mark.asyncio
    async def test_failing_callback_does_not_stop_others(self, event_bus):
        good_results = []

        async def bad_handler(event):
            raise ValueError("boom")

        async def good_handler(event):
            good_results.append(event)

        event_bus.subscribe(EventType.ORDER, bad_handler)
        event_bus.subscribe(EventType.ORDER, good_handler)
        await event_bus.publish(Event(type=EventType.ORDER))

        assert len(good_results) == 1


class TestEventDataclass:
    """Tests for Event dataclass defaults."""

    def test_event_has_uuid_id(self):
        event = Event()
        assert len(event.id) == 32  # uuid hex

    def test_event_default_type_is_system(self):
        event = Event()
        assert event.type == EventType.SYSTEM

    def test_event_default_priority_is_normal(self):
        event = Event()
        assert event.priority == EventPriority.NORMAL

    def test_event_timestamp_is_utc(self):
        event = Event()
        assert event.timestamp.tzinfo is not None
