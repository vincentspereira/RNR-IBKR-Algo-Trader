"""Unit tests for the Order State Machine and ExecutionEngine."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from src.engines.execution_engine import (
    Order,
    OrderSide,
    OrderStateMachine,
    OrderStatus,
    OrderType,
)


class TestOrderStateMachineTransitions:
    """Tests for valid and invalid state transitions."""

    def test_pending_to_submitted(self):
        sm = OrderStateMachine()
        order = Order(status=OrderStatus.PENDING)
        sm.transition(order, OrderStatus.SUBMITTED)
        assert order.status == OrderStatus.SUBMITTED

    def test_pending_to_cancelled(self):
        sm = OrderStateMachine()
        order = Order(status=OrderStatus.PENDING)
        sm.transition(order, OrderStatus.CANCELLED)
        assert order.status == OrderStatus.CANCELLED

    def test_submitted_to_partially_filled(self):
        sm = OrderStateMachine()
        order = Order(status=OrderStatus.SUBMITTED)
        sm.transition(order, OrderStatus.PARTIALLY_FILLED)
        assert order.status == OrderStatus.PARTIALLY_FILLED

    def test_submitted_to_filled(self):
        sm = OrderStateMachine()
        order = Order(status=OrderStatus.SUBMITTED)
        sm.transition(order, OrderStatus.FILLED)
        assert order.status == OrderStatus.FILLED

    def test_submitted_to_cancelled(self):
        sm = OrderStateMachine()
        order = Order(status=OrderStatus.SUBMITTED)
        sm.transition(order, OrderStatus.CANCELLED)
        assert order.status == OrderStatus.CANCELLED

    def test_submitted_to_rejected(self):
        sm = OrderStateMachine()
        order = Order(status=OrderStatus.SUBMITTED)
        sm.transition(order, OrderStatus.REJECTED)
        assert order.status == OrderStatus.REJECTED

    def test_submitted_to_expired(self):
        sm = OrderStateMachine()
        order = Order(status=OrderStatus.SUBMITTED)
        sm.transition(order, OrderStatus.EXPIRED)
        assert order.status == OrderStatus.EXPIRED

    def test_partially_filled_to_filled(self):
        sm = OrderStateMachine()
        order = Order(status=OrderStatus.PARTIALLY_FILLED)
        sm.transition(order, OrderStatus.FILLED)
        assert order.status == OrderStatus.FILLED

    def test_partially_filled_to_partially_filled(self):
        sm = OrderStateMachine()
        order = Order(status=OrderStatus.PARTIALLY_FILLED)
        sm.transition(order, OrderStatus.PARTIALLY_FILLED)
        assert order.status == OrderStatus.PARTIALLY_FILLED

    def test_partially_filled_to_cancelled(self):
        sm = OrderStateMachine()
        order = Order(status=OrderStatus.PARTIALLY_FILLED)
        sm.transition(order, OrderStatus.CANCELLED)
        assert order.status == OrderStatus.CANCELLED


class TestOrderStateMachineInvalidTransitions:
    """Tests that invalid transitions raise ValueError."""

    def test_pending_to_filled_is_invalid(self):
        sm = OrderStateMachine()
        order = Order(status=OrderStatus.PENDING)
        with pytest.raises(ValueError, match="Invalid order state transition"):
            sm.transition(order, OrderStatus.FILLED)

    def test_pending_to_rejected_via_wrong_path(self):
        sm = OrderStateMachine()
        order = Order(status=OrderStatus.PENDING)
        with pytest.raises(ValueError, match="Invalid order state transition"):
            sm.transition(order, OrderStatus.REJECTED)

    def test_filled_is_terminal(self):
        sm = OrderStateMachine()
        order = Order(status=OrderStatus.FILLED)
        with pytest.raises(ValueError, match="Invalid order state transition"):
            sm.transition(order, OrderStatus.PENDING)

    def test_cancelled_is_terminal(self):
        sm = OrderStateMachine()
        order = Order(status=OrderStatus.CANCELLED)
        with pytest.raises(ValueError, match="Invalid order state transition"):
            sm.transition(order, OrderStatus.SUBMITTED)

    def test_rejected_is_terminal(self):
        sm = OrderStateMachine()
        order = Order(status=OrderStatus.REJECTED)
        with pytest.raises(ValueError, match="Invalid order state transition"):
            sm.transition(order, OrderStatus.PENDING)

    def test_expired_is_terminal(self):
        sm = OrderStateMachine()
        order = Order(status=OrderStatus.EXPIRED)
        with pytest.raises(ValueError, match="Invalid order state transition"):
            sm.transition(order, OrderStatus.SUBMITTED)

    def test_submitted_to_pending_is_invalid(self):
        sm = OrderStateMachine()
        order = Order(status=OrderStatus.SUBMITTED)
        with pytest.raises(ValueError, match="Invalid order state transition"):
            sm.transition(order, OrderStatus.PENDING)


class TestOrderStateMachineTerminal:
    """Tests for terminal state detection."""

    def test_filled_is_terminal(self):
        sm = OrderStateMachine()
        assert sm.is_terminal(OrderStatus.FILLED) is True

    def test_cancelled_is_terminal(self):
        sm = OrderStateMachine()
        assert sm.is_terminal(OrderStatus.CANCELLED) is True

    def test_rejected_is_terminal(self):
        sm = OrderStateMachine()
        assert sm.is_terminal(OrderStatus.REJECTED) is True

    def test_expired_is_terminal(self):
        sm = OrderStateMachine()
        assert sm.is_terminal(OrderStatus.EXPIRED) is True

    def test_pending_is_not_terminal(self):
        sm = OrderStateMachine()
        assert sm.is_terminal(OrderStatus.PENDING) is False

    def test_submitted_is_not_terminal(self):
        sm = OrderStateMachine()
        assert sm.is_terminal(OrderStatus.SUBMITTED) is False

    def test_partially_filled_is_not_terminal(self):
        sm = OrderStateMachine()
        assert sm.is_terminal(OrderStatus.PARTIALLY_FILLED) is False


class TestOrderStateMachineWithEventBus:
    """Tests that state transitions emit events."""

    @pytest.mark.asyncio
    async def test_transition_publishes_event(self, event_bus):
        sm = OrderStateMachine(event_bus=event_bus)
        received = []

        async def handler(event):
            received.append(event)

        from src.core.event_system import EventType
        event_bus.subscribe(EventType.ORDER, handler)

        order = Order(status=OrderStatus.PENDING)
        sm.transition(order, OrderStatus.SUBMITTED)

        # Give the async task time to run
        await asyncio.sleep(0.05)

        assert len(received) == 1
        assert received[0].data["old_status"] == "pending"
        assert received[0].data["new_status"] == "submitted"


class TestOrderDataclass:
    """Tests for the Order dataclass."""

    def test_order_defaults(self):
        order = Order()
        assert order.status == OrderStatus.PENDING
        assert order.order_type == OrderType.MARKET
        assert order.side == OrderSide.BUY
        assert order.quantity == 0.0
        assert order.instrument == ""

    def test_order_post_init_remaining_quantity(self):
        order = Order(quantity=100.0)
        assert order.remaining_quantity == 100.0

    def test_order_has_uuid_id(self):
        order = Order()
        assert len(order.order_id) == 32

    def test_order_custom_fields(self):
        order = Order(
            instrument="AAPL",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=50.0,
            price=155.0,
        )
        assert order.instrument == "AAPL"
        assert order.side == OrderSide.SELL
        assert order.remaining_quantity == 50.0
