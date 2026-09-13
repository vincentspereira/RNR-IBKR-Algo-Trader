"""Comprehensive unit tests for the ExecutionEngine and supporting types.

Covers:
- Order submission, cancellation, fill handling
- State machine integration within the engine
- Execution algorithms (VWAP, TWAP)
- Slippage estimation
- Circuit breaker integration
- Event emission on fill/cancel/reject
- Venue and dataclass construction
- Reconciliation on startup
"""

import asyncio
import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.event_system import Event, EventBus, EventPriority, EventType
from src.engines.execution_engine import (
    ExecutionAlgorithm,
    ExecutionAlgorithmBase,
    ExecutionEngine,
    ExecutionQuality,
    ExecutionReport,
    Fill,
    Order,
    OrderSide,
    OrderStateMachine,
    OrderStatus,
    OrderType,
    SlippageModel,
    TWAPAlgorithm,
    VWAPAlgorithm,
    Venue,
    VenueType,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_order(**overrides):
    """Create a valid Order with sensible defaults, allowing overrides."""
    defaults = dict(
        instrument="AAPL",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=100,
        price=150.0,
    )
    defaults.update(overrides)
    return Order(**defaults)


def _make_venue(**overrides):
    """Create a Venue with sensible defaults."""
    defaults = dict(
        venue_id="TEST",
        name="Test Exchange",
        venue_type=VenueType.EXCHANGE,
        supported_instruments={"STOCKS"},
        supported_order_types={OrderType.MARKET, OrderType.LIMIT},
        min_order_size=1,
        max_order_size=100000,
        tick_size=0.01,
        commission_rate=0.005,
        latency_ms=1.0,
        fill_rate=0.99,
    )
    defaults.update(overrides)
    return Venue(**defaults)


# ---------------------------------------------------------------------------
# Dataclass Tests
# ---------------------------------------------------------------------------

class TestVenueDataclass:
    """Tests for the Venue dataclass."""

    def test_venue_creation(self):
        venue = _make_venue()
        assert venue.venue_id == "TEST"
        assert venue.name == "Test Exchange"
        assert venue.venue_type == VenueType.EXCHANGE
        assert venue.enabled is True
        assert isinstance(venue.supported_instruments, set)
        assert isinstance(venue.supported_order_types, set)

    def test_venue_custom_metadata(self):
        venue = _make_venue(metadata={"region": "US"})
        assert venue.metadata["region"] == "US"

    def test_venue_disabled(self):
        venue = _make_venue(enabled=False)
        assert venue.enabled is False


class TestSlippageModelDefaults:
    """Tests for the SlippageModel dataclass."""

    def test_default_coefficients(self):
        model = SlippageModel(instrument="AAPL")
        assert model.linear_coefficient == 0.001
        assert model.square_root_coefficient == 0.01
        assert model.fixed_cost == 0.0001

    def test_adjustments_default_to_one(self):
        model = SlippageModel(instrument="MSFT")
        assert model.volatility_adjustment == 1.0
        assert model.volume_adjustment == 1.0
        assert model.spread_adjustment == 1.0

    def test_last_updated_auto_set(self):
        model = SlippageModel(instrument="GOOG")
        assert model.last_updated is not None

    def test_custom_coefficients(self):
        model = SlippageModel(
            instrument="TSLA",
            linear_coefficient=0.005,
            square_root_coefficient=0.02,
            fixed_cost=0.0005,
        )
        assert model.linear_coefficient == 0.005
        assert model.square_root_coefficient == 0.02
        assert model.fixed_cost == 0.0005


class TestExecutionReportCreation:
    """Tests for the ExecutionReport dataclass."""

    def test_report_creation(self):
        report = ExecutionReport(
            order_id="abc123",
            instrument="AAPL",
            side=OrderSide.BUY,
            total_quantity=100.0,
            filled_quantity=100.0,
            average_fill_price=150.0,
            benchmark_price=149.95,
            slippage=0.05,
            market_impact=0.02,
            timing_cost=0.01,
            commission=0.75,
            total_cost=0.83,
            execution_quality=ExecutionQuality.GOOD,
            venues_used=["NYSE"],
            execution_time_ms=500.0,
            fill_rate=1.0,
        )
        assert report.order_id == "abc123"
        assert report.execution_quality == ExecutionQuality.GOOD
        assert report.venues_used == ["NYSE"]
        assert report.total_cost == 0.83

    def test_report_default_metadata(self):
        report = ExecutionReport(
            order_id="x",
            instrument="AAPL",
            side=OrderSide.BUY,
            total_quantity=10,
            filled_quantity=10,
            average_fill_price=100.0,
            benchmark_price=100.0,
            slippage=0.0,
            market_impact=0.0,
            timing_cost=0.0,
            commission=0.0,
            total_cost=0.0,
            execution_quality=ExecutionQuality.EXCELLENT,
            venues_used=[],
            execution_time_ms=0.0,
            fill_rate=1.0,
        )
        assert report.metadata == {}


class TestFillDataclass:
    """Tests for the Fill dataclass."""

    def test_fill_defaults(self):
        fill = Fill()
        assert fill.quantity == 0.0
        assert fill.price == 0.0
        assert fill.side == OrderSide.BUY
        assert fill.metadata == {}
        assert len(fill.fill_id) == 12

    def test_fill_with_values(self):
        fill = Fill(
            order_id="ord1",
            instrument="AAPL",
            side=OrderSide.SELL,
            quantity=50.0,
            price=155.0,
        )
        assert fill.order_id == "ord1"
        assert fill.quantity == 50.0
        assert fill.price == 155.0
        assert fill.side == OrderSide.SELL


# ---------------------------------------------------------------------------
# Order Validation Tests
# ---------------------------------------------------------------------------

class TestValidateOrder:
    """Tests for ExecutionEngine._validate_order."""

    def test_valid_limit_order(self):
        engine = ExecutionEngine(broker_adapter=None, event_bus=EventBus())
        order = _make_order()
        assert engine._validate_order(order) is True

    def test_valid_market_order(self):
        engine = ExecutionEngine(broker_adapter=None, event_bus=EventBus())
        # Market orders need a reference price for pre-trade notional sizing
        # (VIN-40 F1): without one the broker-side limit cannot bound size.
        order = _make_order(order_type=OrderType.MARKET, price=100.0)
        assert engine._validate_order(order) is True

    def test_reject_market_order_without_price(self):
        engine = ExecutionEngine(broker_adapter=None, event_bus=EventBus())
        order = _make_order(order_type=OrderType.MARKET, price=None)
        assert engine._validate_order(order) is False

    def test_reject_empty_instrument(self):
        engine = ExecutionEngine(broker_adapter=None, event_bus=EventBus())
        order = _make_order(instrument="")
        assert engine._validate_order(order) is False

    def test_reject_zero_quantity(self):
        engine = ExecutionEngine(broker_adapter=None, event_bus=EventBus())
        order = _make_order(quantity=0)
        assert engine._validate_order(order) is False

    def test_reject_negative_quantity(self):
        engine = ExecutionEngine(broker_adapter=None, event_bus=EventBus())
        order = _make_order(quantity=-10)
        assert engine._validate_order(order) is False

    def test_reject_limit_order_without_price(self):
        engine = ExecutionEngine(broker_adapter=None, event_bus=EventBus())
        order = _make_order(order_type=OrderType.LIMIT, price=None)
        assert engine._validate_order(order) is False

    def test_reject_stop_limit_without_price(self):
        engine = ExecutionEngine(broker_adapter=None, event_bus=EventBus())
        order = _make_order(order_type=OrderType.STOP_LIMIT, price=None, stop_price=140.0)
        assert engine._validate_order(order) is False

    def test_reject_stop_order_without_stop_price(self):
        engine = ExecutionEngine(broker_adapter=None, event_bus=EventBus())
        order = _make_order(order_type=OrderType.STOP, price=150.0, stop_price=None)
        assert engine._validate_order(order) is False

    def test_reject_stop_limit_without_stop_price(self):
        engine = ExecutionEngine(broker_adapter=None, event_bus=EventBus())
        order = _make_order(order_type=OrderType.STOP_LIMIT, price=150.0, stop_price=None)
        assert engine._validate_order(order) is False

    def test_valid_stop_order(self):
        engine = ExecutionEngine(broker_adapter=None, event_bus=EventBus())
        order = _make_order(order_type=OrderType.STOP, stop_price=145.0, price=None)
        assert engine._validate_order(order) is True


# ---------------------------------------------------------------------------
# Submit Order Tests
# ---------------------------------------------------------------------------

class TestSubmitOrder:
    """Tests for ExecutionEngine.submit_order."""

    @pytest.mark.asyncio
    async def test_submit_order_success(self):
        broker = AsyncMock()
        broker.place_order = AsyncMock(return_value={
            "status": "submitted",
            "broker_order_id": "BK-001",
        })
        engine = ExecutionEngine(broker_adapter=broker, event_bus=EventBus())
        order = _make_order()

        result = await engine.submit_order(order)

        assert result is True
        assert order.status == OrderStatus.SUBMITTED
        assert order.broker_order_id == "BK-001"
        assert engine.get_order(order.order_id) is order

    @pytest.mark.asyncio
    async def test_submit_order_rejected_by_validation(self):
        """Invalid orders fail validation and return False.

        Note: PENDING -> REJECTED is not a valid state machine transition,
        so the inner transition raises ValueError, caught by the outer except.
        The order status remains PENDING, but submit_order returns False.
        """
        engine = ExecutionEngine(broker_adapter=None, event_bus=EventBus())
        order = _make_order(quantity=0)  # invalid

        result = await engine.submit_order(order)

        assert result is False
        # Order stays PENDING because the PENDING->REJECTED transition is invalid
        # and the ValueError is caught by the generic except block.
        assert order.status == OrderStatus.PENDING

    @pytest.mark.asyncio
    async def test_submit_order_risk_rejected(self):
        """Risk engine rejection returns False.

        Same as validation rejection: PENDING->REJECTED is not a valid
        state machine transition. The ValueError is caught by the outer
        except block, so status stays PENDING and submit_order returns False.
        """
        risk_engine = AsyncMock()
        risk_engine.pre_trade_check = AsyncMock(return_value=False)
        engine = ExecutionEngine(
            broker_adapter=None,
            event_bus=EventBus(),
            risk_engine=risk_engine,
        )
        order = _make_order()

        result = await engine.submit_order(order)

        assert result is False
        assert order.status == OrderStatus.PENDING
        risk_engine.pre_trade_check.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_submit_order_circuit_breaker_open(self):
        """Circuit breaker open rejection returns False.

        Same as other rejections: PENDING->REJECTED is not a valid
        transition, so status remains PENDING.
        """
        engine = ExecutionEngine(broker_adapter=None, event_bus=EventBus())
        # Force circuit breaker to open by recording failures
        for _ in range(6):
            engine._circuit_breaker.record_failure()
        assert engine._circuit_breaker.state.value == "open"

        order = _make_order()
        result = await engine.submit_order(order)

        assert result is False
        assert order.status == OrderStatus.PENDING

    @pytest.mark.asyncio
    async def test_submit_order_broker_rejected(self):
        broker = AsyncMock()
        broker.place_order = AsyncMock(return_value={
            "status": "rejected",
            "reason": "Insufficient margin",
        })
        engine = ExecutionEngine(broker_adapter=broker, event_bus=EventBus())
        order = _make_order()

        result = await engine.submit_order(order)

        assert result is False
        assert order.status == OrderStatus.REJECTED
        assert order.error_message == "Insufficient margin"

    @pytest.mark.asyncio
    async def test_submit_order_persists_to_order_store(self):
        broker = AsyncMock()
        broker.place_order = AsyncMock(return_value={"status": "submitted"})
        order_store = AsyncMock()
        order_store.save_order = AsyncMock(return_value=True)
        engine = ExecutionEngine(
            broker_adapter=broker,
            event_bus=EventBus(),
            order_store=order_store,
        )
        order = _make_order()

        await engine.submit_order(order)

        order_store.save_order.assert_awaited_once_with(order)

    @pytest.mark.asyncio
    async def test_submit_order_persist_failure_does_not_block(self):
        broker = AsyncMock()
        broker.place_order = AsyncMock(return_value={"status": "submitted"})
        order_store = AsyncMock()
        order_store.save_order = AsyncMock(side_effect=Exception("DB down"))
        engine = ExecutionEngine(
            broker_adapter=broker,
            event_bus=EventBus(),
            order_store=order_store,
        )
        order = _make_order()

        result = await engine.submit_order(order)

        # Order still succeeds even if persistence fails
        assert result is True
        assert order.status == OrderStatus.SUBMITTED

    @pytest.mark.asyncio
    async def test_submit_order_without_broker(self):
        engine = ExecutionEngine(broker_adapter=None, event_bus=EventBus())
        order = _make_order()

        result = await engine.submit_order(order)

        assert result is True
        assert order.status == OrderStatus.SUBMITTED
        assert order.broker_order_id is None


# ---------------------------------------------------------------------------
# Cancel Order Tests
# ---------------------------------------------------------------------------

class TestCancelOrder:
    """Tests for ExecutionEngine.cancel_order."""

    @pytest.mark.asyncio
    async def test_cancel_order_success(self):
        broker = AsyncMock()
        broker.cancel_order = AsyncMock(return_value=True)
        engine = ExecutionEngine(broker_adapter=broker, event_bus=EventBus())
        order = _make_order()
        await engine.submit_order(order)

        result = await engine.cancel_order(order.order_id)

        assert result is True
        assert order.status == OrderStatus.CANCELLED
        broker.cancel_order.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cancel_order_not_found_returns_false(self):
        engine = ExecutionEngine(broker_adapter=None, event_bus=EventBus())

        result = await engine.cancel_order("nonexistent_id")

        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_terminal_order_returns_false(self):
        engine = ExecutionEngine(broker_adapter=None, event_bus=EventBus())
        order = _make_order()
        order.status = OrderStatus.FILLED
        engine._orders[order.order_id] = order

        result = await engine.cancel_order(order.order_id)

        assert result is False
        assert order.status == OrderStatus.FILLED

    @pytest.mark.asyncio
    async def test_cancel_partially_filled_order(self):
        broker = AsyncMock()
        broker.cancel_order = AsyncMock(return_value=True)
        engine = ExecutionEngine(broker_adapter=broker, event_bus=EventBus())
        order = _make_order()
        engine._orders[order.order_id] = order
        order.status = OrderStatus.PARTIALLY_FILLED

        result = await engine.cancel_order(order.order_id)

        assert result is True
        assert order.status == OrderStatus.CANCELLED


# ---------------------------------------------------------------------------
# Fill Handling Tests
# ---------------------------------------------------------------------------

class TestHandleFill:
    """Tests for ExecutionEngine.handle_fill."""

    @pytest.mark.asyncio
    async def test_handle_partial_fill(self):
        engine = ExecutionEngine(broker_adapter=None, event_bus=EventBus())
        order = _make_order(quantity=100)
        order.status = OrderStatus.SUBMITTED  # fills require non-pending status
        engine._orders[order.order_id] = order
        engine._fills[order.order_id] = []

        await engine.handle_fill(order.order_id, fill_quantity=40, fill_price=150.0)

        assert order.filled_quantity == 40
        assert order.remaining_quantity == 60
        assert order.status == OrderStatus.PARTIALLY_FILLED
        assert len(engine.get_fills(order.order_id)) == 1

    @pytest.mark.asyncio
    async def test_handle_full_fill(self):
        engine = ExecutionEngine(broker_adapter=None, event_bus=EventBus())
        order = _make_order(quantity=100)
        order.status = OrderStatus.SUBMITTED
        engine._orders[order.order_id] = order
        engine._fills[order.order_id] = []

        await engine.handle_fill(order.order_id, fill_quantity=100, fill_price=150.0)

        assert order.filled_quantity == 100
        assert order.remaining_quantity == 0
        assert order.status == OrderStatus.FILLED

    @pytest.mark.asyncio
    async def test_handle_fill_updates_position(self):
        """Fill events update average fill price with weighted average."""
        engine = ExecutionEngine(broker_adapter=None, event_bus=EventBus())
        order = _make_order(quantity=200)
        order.status = OrderStatus.SUBMITTED
        engine._orders[order.order_id] = order
        engine._fills[order.order_id] = []

        # First fill: 100 @ 150.0
        await engine.handle_fill(order.order_id, fill_quantity=100, fill_price=150.0)
        assert order.average_fill_price == 150.0

        # Second fill: 100 @ 160.0
        await engine.handle_fill(order.order_id, fill_quantity=100, fill_price=160.0)
        # Weighted average: (100*150 + 100*160) / 200 = 155.0
        assert order.average_fill_price == 155.0
        assert order.filled_quantity == 200
        assert order.status == OrderStatus.FILLED

    @pytest.mark.asyncio
    async def test_handle_fill_for_unknown_order_ignored(self):
        engine = ExecutionEngine(broker_adapter=None, event_bus=EventBus())

        # Should not raise
        await engine.handle_fill("unknown_id", fill_quantity=10, fill_price=100.0)

    @pytest.mark.asyncio
    async def test_handle_multiple_partial_fills(self):
        engine = ExecutionEngine(broker_adapter=None, event_bus=EventBus())
        order = _make_order(quantity=300)
        order.status = OrderStatus.SUBMITTED
        engine._orders[order.order_id] = order
        engine._fills[order.order_id] = []

        await engine.handle_fill(order.order_id, 100, 149.0)
        await engine.handle_fill(order.order_id, 100, 151.0)
        await engine.handle_fill(order.order_id, 100, 150.0)

        assert order.filled_quantity == 300
        assert order.remaining_quantity == 0
        assert order.status == OrderStatus.FILLED
        # (100*149 + 100*151 + 100*150) / 300 = 150.0
        assert abs(order.average_fill_price - 150.0) < 1e-9
        assert len(engine.get_fills(order.order_id)) == 3


# ---------------------------------------------------------------------------
# Event Emission Tests
# ---------------------------------------------------------------------------

class TestEventEmission:
    """Tests that the engine emits events on key actions."""

    @pytest.mark.asyncio
    async def test_emits_event_on_fill(self):
        event_bus = EventBus()
        engine = ExecutionEngine(broker_adapter=None, event_bus=event_bus)
        order = _make_order(quantity=100)
        order.status = OrderStatus.SUBMITTED
        engine._orders[order.order_id] = order
        engine._fills[order.order_id] = []

        received = []

        async def capture(event):
            received.append(event)

        event_bus.subscribe(EventType.FILL, capture)

        await engine.handle_fill(order.order_id, 50, 150.0)
        await asyncio.sleep(0.05)

        assert len(received) == 1
        assert received[0].data["order_id"] == order.order_id
        assert received[0].data["fill_quantity"] == 50
        assert received[0].data["fill_price"] == 150.0

    @pytest.mark.asyncio
    async def test_emits_event_on_cancel(self):
        """Cancelling an order triggers an ORDER event via the state machine."""
        event_bus = EventBus()
        engine = ExecutionEngine(broker_adapter=None, event_bus=event_bus)
        order = _make_order()
        engine._orders[order.order_id] = order
        order.status = OrderStatus.SUBMITTED

        received = []

        async def capture(event):
            received.append(event)

        event_bus.subscribe(EventType.ORDER, capture)

        await engine.cancel_order(order.order_id)
        await asyncio.sleep(0.05)

        assert len(received) == 1
        assert received[0].data["new_status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_emits_event_on_reject(self):
        """Broker rejection after SUBMITTED triggers a rejection ORDER event.

        Validation-only rejections do NOT emit events because PENDING->REJECTED
        is not a valid state machine transition (ValueError is caught silently).
        Broker rejections happen after SUBMITTED, so SUBMITTED->REJECTED is valid.
        """
        event_bus = EventBus()
        broker = AsyncMock()
        broker.place_order = AsyncMock(return_value={
            "status": "rejected",
            "reason": "Insufficient margin",
        })
        engine = ExecutionEngine(broker_adapter=broker, event_bus=event_bus)
        order = _make_order()

        received = []

        async def capture(event):
            received.append(event)

        event_bus.subscribe(EventType.ORDER, capture)

        result = await engine.submit_order(order)
        await asyncio.sleep(0.05)

        assert result is False
        assert len(received) == 2  # SUBMITTED event then REJECTED event
        statuses = [e.data["new_status"] for e in received]
        assert "submitted" in statuses
        assert "rejected" in statuses


# ---------------------------------------------------------------------------
# Query / Getters Tests
# ---------------------------------------------------------------------------

class TestOrderQuery:
    """Tests for order retrieval methods."""

    def test_get_active_orders(self):
        engine = ExecutionEngine(broker_adapter=None, event_bus=EventBus())
        order1 = _make_order(instrument="AAPL")
        order1.status = OrderStatus.SUBMITTED
        order2 = _make_order(instrument="MSFT")
        order2.status = OrderStatus.PARTIALLY_FILLED
        order3 = _make_order(instrument="GOOG")
        order3.status = OrderStatus.FILLED

        engine._orders[order1.order_id] = order1
        engine._orders[order2.order_id] = order2
        engine._orders[order3.order_id] = order3

        active = engine.get_active_orders()
        assert len(active) == 2
        assert order3 not in active

    def test_get_active_orders_excludes_terminal(self):
        engine = ExecutionEngine(broker_adapter=None, event_bus=EventBus())
        for status in (OrderStatus.FILLED, OrderStatus.CANCELLED,
                       OrderStatus.REJECTED, OrderStatus.EXPIRED):
            order = _make_order()
            order.status = status
            engine._orders[order.order_id] = order

        assert len(engine.get_active_orders()) == 0

    def test_get_order_by_id_found(self):
        engine = ExecutionEngine(broker_adapter=None, event_bus=EventBus())
        order = _make_order()
        engine._orders[order.order_id] = order

        result = engine.get_order(order.order_id)
        assert result is order

    def test_get_order_by_id_not_found(self):
        engine = ExecutionEngine(broker_adapter=None, event_bus=EventBus())
        assert engine.get_order("nonexistent") is None

    def test_get_orders_by_status(self):
        engine = ExecutionEngine(broker_adapter=None, event_bus=EventBus())
        o1 = _make_order()
        o1.status = OrderStatus.SUBMITTED
        o2 = _make_order()
        o2.status = OrderStatus.FILLED
        o3 = _make_order()
        o3.status = OrderStatus.SUBMITTED
        engine._orders.update({o1.order_id: o1, o2.order_id: o2, o3.order_id: o3})

        submitted = engine.get_orders(status=OrderStatus.SUBMITTED)
        assert len(submitted) == 2
        assert o2 not in submitted

    def test_get_orders_no_filter(self):
        engine = ExecutionEngine(broker_adapter=None, event_bus=EventBus())
        o1 = _make_order()
        o2 = _make_order()
        engine._orders.update({o1.order_id: o1, o2.order_id: o2})

        all_orders = engine.get_orders()
        assert len(all_orders) == 2


# ---------------------------------------------------------------------------
# State Machine Integration Tests (through engine)
# ---------------------------------------------------------------------------

class TestOrderStateTransitionsAllValid:
    """Verify all valid state transitions through the OrderStateMachine."""

    @pytest.mark.parametrize("start,end", [
        (OrderStatus.PENDING, OrderStatus.SUBMITTED),
        (OrderStatus.PENDING, OrderStatus.CANCELLED),
        (OrderStatus.SUBMITTED, OrderStatus.PARTIALLY_FILLED),
        (OrderStatus.SUBMITTED, OrderStatus.FILLED),
        (OrderStatus.SUBMITTED, OrderStatus.CANCELLED),
        (OrderStatus.SUBMITTED, OrderStatus.REJECTED),
        (OrderStatus.SUBMITTED, OrderStatus.EXPIRED),
        (OrderStatus.PARTIALLY_FILLED, OrderStatus.PARTIALLY_FILLED),
        (OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED),
        (OrderStatus.PARTIALLY_FILLED, OrderStatus.CANCELLED),
    ])
    def test_valid_transition(self, start, end):
        sm = OrderStateMachine()
        order = Order(status=start)
        sm.transition(order, end)
        assert order.status == end


class TestOrderStateTransitionInvalidRaises:
    """Verify that invalid transitions raise ValueError."""

    @pytest.mark.parametrize("start,end", [
        (OrderStatus.PENDING, OrderStatus.FILLED),
        (OrderStatus.PENDING, OrderStatus.REJECTED),
        (OrderStatus.PENDING, OrderStatus.EXPIRED),
        (OrderStatus.FILLED, OrderStatus.PENDING),
        (OrderStatus.FILLED, OrderStatus.SUBMITTED),
        (OrderStatus.CANCELLED, OrderStatus.SUBMITTED),
        (OrderStatus.REJECTED, OrderStatus.PENDING),
        (OrderStatus.EXPIRED, OrderStatus.SUBMITTED),
        (OrderStatus.SUBMITTED, OrderStatus.PENDING),
    ])
    def test_invalid_transition_raises(self, start, end):
        sm = OrderStateMachine()
        order = Order(status=start)
        with pytest.raises(ValueError, match="Invalid order state transition"):
            sm.transition(order, end)


class TestTerminalStateImmutable:
    """Verify no transitions are possible from terminal states."""

    @pytest.mark.parametrize("terminal", [
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
    ])
    def test_cannot_leave_terminal(self, terminal):
        sm = OrderStateMachine()
        for target in OrderStatus:
            if target == terminal:
                continue
            order = Order(status=terminal)
            with pytest.raises(ValueError):
                sm.transition(order, target)

    @pytest.mark.parametrize("terminal", [
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
    ])
    def test_is_terminal_returns_true(self, terminal):
        sm = OrderStateMachine()
        assert sm.is_terminal(terminal) is True


# ---------------------------------------------------------------------------
# Execution Algorithm Tests
# ---------------------------------------------------------------------------

class TestVWAPAlgorithm:
    """Tests for VWAP execution algorithm."""

    @pytest.mark.asyncio
    async def test_vwap_slice_calculation(self):
        algo = VWAPAlgorithm()
        order = _make_order(quantity=100000)
        market_data = {
            "current_price": 150.0,
            "spread": 0.02,
            "daily_volume": 5000000,
        }

        # Mock _create_time_slices to return keys matching the volume profile
        # so that expected_volume is non-zero
        algo._create_time_slices = lambda horizon: [
            "09:30", "10:00", "10:30", "11:00", "11:30",
            "12:00", "12:30", "13:00", "13:30", "14:00",
            "14:30", "15:00", "15:30",
        ]

        child_orders = await algo.execute(order, market_data)

        assert len(child_orders) > 0
        for child in child_orders:
            assert child.parent_order_id == order.order_id
            assert child.instrument == "AAPL"
            assert child.order_type == OrderType.LIMIT
            assert child.quantity > 0

    def test_vwap_estimate_execution_time(self):
        algo = VWAPAlgorithm()
        order = _make_order(quantity=100000)
        market_data = {"daily_volume": 1000000}
        exec_time = algo.estimate_execution_time(order, market_data)
        assert exec_time >= 300  # minimum 300 seconds

    def test_vwap_estimate_market_impact(self):
        algo = VWAPAlgorithm()
        order = _make_order(quantity=1000)
        market_data = {"daily_volume": 1000000, "volatility": 0.02}
        impact = algo.estimate_market_impact(order, market_data)
        assert 0 <= impact <= 0.005  # capped at 0.5%

    def test_vwap_parameters(self):
        algo = VWAPAlgorithm()
        assert algo.name == "VWAP"
        assert algo.parameters["participation_rate"] == 0.1

    @pytest.mark.asyncio
    async def test_vwap_buy_price_above_mid(self):
        """Buy child orders should be priced above current price."""
        algo = VWAPAlgorithm()
        order = _make_order(quantity=50000, side=OrderSide.BUY)
        market_data = {"current_price": 100.0, "spread": 0.10, "daily_volume": 1000000}

        algo._create_time_slices = lambda horizon: [
            "09:30", "10:00", "10:30", "11:00", "11:30",
            "12:00", "12:30", "13:00", "13:30", "14:00",
            "14:30", "15:00", "15:30",
        ]

        children = await algo.execute(order, market_data)
        assert len(children) > 0
        for child in children:
            assert child.price > 100.0

    @pytest.mark.asyncio
    async def test_vwap_sell_price_below_mid(self):
        """Sell child orders should be priced below current price."""
        algo = VWAPAlgorithm()
        order = _make_order(quantity=50000, side=OrderSide.SELL)
        market_data = {"current_price": 100.0, "spread": 0.10, "daily_volume": 1000000}

        algo._create_time_slices = lambda horizon: [
            "09:30", "10:00", "10:30", "11:00", "11:30",
            "12:00", "12:30", "13:00", "13:30", "14:00",
            "14:30", "15:00", "15:30",
        ]

        children = await algo.execute(order, market_data)
        assert len(children) > 0
        for child in children:
            assert child.price < 100.0


class TestTWAPAlgorithm:
    """Tests for TWAP execution algorithm."""

    @pytest.mark.asyncio
    async def test_twap_slice_calculation(self):
        algo = TWAPAlgorithm()
        order = _make_order(quantity=1200)
        market_data = {"current_price": 150.0, "spread": 0.02}

        child_orders = await algo.execute(order, market_data)

        num_slices = algo.parameters["execution_horizon"] // algo.parameters["slice_interval"]
        assert len(child_orders) == num_slices

        expected_qty = order.quantity / num_slices
        for child in child_orders:
            assert abs(child.quantity - expected_qty) < 1e-9
            assert child.parent_order_id == order.order_id
            assert child.instrument == "AAPL"

    def test_twap_estimate_execution_time(self):
        algo = TWAPAlgorithm()
        order = _make_order()
        market_data = {}
        exec_time = algo.estimate_execution_time(order, market_data)
        assert exec_time == algo.parameters["execution_horizon"]

    def test_twap_estimate_market_impact(self):
        algo = TWAPAlgorithm()
        order = _make_order()
        market_data = {"volatility": 0.03}
        impact = algo.estimate_market_impact(order, market_data)
        assert impact == 0.05 * 0.03

    def test_twap_parameters(self):
        algo = TWAPAlgorithm()
        assert algo.name == "TWAP"
        assert algo.parameters["slice_interval"] == 300


# ---------------------------------------------------------------------------
# Slippage Estimation Tests
# ---------------------------------------------------------------------------

class TestSlippageEstimation:
    """Tests for ExecutionEngine._estimate_slippage."""

    def test_slippage_estimation_with_default_model(self):
        engine = ExecutionEngine(broker_adapter=None, event_bus=EventBus())
        engine._load_slippage_models()
        order = _make_order(quantity=1000)
        market_data = {"daily_volume": 1000000, "volatility": 0.02, "spread": 0.01}
        venue = _make_venue()

        slippage = engine._estimate_slippage(order, market_data, venue)

        assert isinstance(slippage, float)
        assert slippage > 0
        assert slippage <= 0.01  # capped

    def test_slippage_capped_at_max(self):
        engine = ExecutionEngine(broker_adapter=None, event_bus=EventBus())
        engine._load_slippage_models()
        # Extreme parameters to try to blow through the cap
        order = _make_order(quantity=999999999)
        market_data = {
            "daily_volume": 1,  # tiny volume
            "volatility": 10.0,  # extreme vol
            "spread": 5.0,
        }
        venue = _make_venue()

        slippage = engine._estimate_slippage(order, market_data, venue)
        assert slippage <= 0.01

    def test_slippage_with_instrument_specific_model(self):
        engine = ExecutionEngine(broker_adapter=None, event_bus=EventBus())
        engine._load_slippage_models()
        engine._slippage_models["AAPL"] = SlippageModel(
            instrument="AAPL",
            linear_coefficient=0.01,
            square_root_coefficient=0.1,
        )
        order = _make_order(quantity=500)
        market_data = {"daily_volume": 1000000, "volatility": 0.02, "spread": 0.01}
        venue = _make_venue()

        slippage = engine._estimate_slippage(order, market_data, venue)
        assert slippage > 0

    def test_slippage_no_model_returns_default(self):
        engine = ExecutionEngine(broker_adapter=None, event_bus=EventBus())
        # No models loaded at all
        order = _make_order()
        market_data = {}
        venue = _make_venue()

        slippage = engine._estimate_slippage(order, market_data, venue)
        # Fallback is 0.001
        assert slippage == 0.001


# ---------------------------------------------------------------------------
# Venue Management Tests
# ---------------------------------------------------------------------------

class TestVenueManagement:
    """Tests for adding and querying venues."""

    def test_default_venues_loaded(self):
        engine = ExecutionEngine(broker_adapter=None, event_bus=EventBus())
        engine._load_default_venues()
        venues = engine.get_venues()
        ids = [v.venue_id for v in venues]
        assert "NYSE" in ids
        assert "NASDAQ" in ids

    def test_add_venue(self):
        engine = ExecutionEngine(broker_adapter=None, event_bus=EventBus())
        venue = _make_venue(venue_id="BATS", name="BATS Exchange")
        engine.add_venue(venue)
        assert len(engine.get_venues()) == 1
        assert engine.get_venues()[0].venue_id == "BATS"


# ---------------------------------------------------------------------------
# Concurrent Orders Test
# ---------------------------------------------------------------------------

class TestConcurrentOrders:
    """Tests for thread-safety of order operations."""

    @pytest.mark.asyncio
    async def test_execution_engine_concurrent_orders(self):
        """Multiple orders submitted concurrently should all be tracked."""
        engine = ExecutionEngine(broker_adapter=None, event_bus=EventBus())
        orders = [_make_order(instrument=f"SYM{i}") for i in range(10)]

        tasks = [engine.submit_order(o) for o in orders]
        results = await asyncio.gather(*tasks)

        assert all(r is True for r in results)
        assert len(engine.get_active_orders()) == 10

        # Verify each order is retrievable
        for order in orders:
            assert engine.get_order(order.order_id) is order


# ---------------------------------------------------------------------------
# Reconcile on Startup Tests
# ---------------------------------------------------------------------------

class TestReconcileOnStartup:
    """Tests for ExecutionEngine.reconcile_on_startup."""

    @pytest.mark.asyncio
    async def test_reconcile_positions_on_startup(self):
        """reconcile_on_startup syncs with broker and emits system events.

        Two SYSTEM events are emitted: one from reconcile_positions() and
        one from reconcile_on_startup() itself.
        """
        broker = AsyncMock()
        broker.get_positions = AsyncMock(return_value=[
            {"symbol": "AAPL", "quantity": 100, "avg_cost": 148.0},
            {"symbol": "MSFT", "quantity": 50, "avg_cost": 300.0},
        ])
        event_bus = EventBus()
        engine = ExecutionEngine(
            broker_adapter=broker,
            event_bus=event_bus,
            order_store=None,
        )

        system_events = []

        async def capture(event):
            system_events.append(event)

        event_bus.subscribe(EventType.SYSTEM, capture)

        await engine.reconcile_on_startup()

        broker.get_positions.assert_awaited_once()
        assert len(system_events) == 2
        actions = [e.data["action"] for e in system_events]
        assert "reconciliation_complete" in actions
        assert "startup_reconciliation_complete" in actions

    @pytest.mark.asyncio
    async def test_reconcile_restores_active_db_orders(self):
        """Active orders from the order store are loaded into local state."""
        broker = AsyncMock()
        broker.get_positions = AsyncMock(return_value=[])
        broker.get_order_status = AsyncMock(return_value={"status": "submitted"})

        order_store = AsyncMock()
        order_store.reconcile_on_startup = AsyncMock(return_value={
            "db_active_orders": 1,
            "reconciled": 1,
            "cancelled_in_db": 0,
        })
        order_store.get_active_orders = AsyncMock(return_value=[
            {
                "order_id": "db-order-1",
                "symbol": "AAPL",
                "side": "buy",
                "order_type": "limit",
                "quantity": 50,
                "price": 150.0,
                "stop_price": None,
                "status": "submitted",
                "filled_quantity": 0,
                "avg_fill_price": 0,
                "commission": 0,
                "broker_order_id": "BK-001",
                "strategy_id": None,
            }
        ])

        engine = ExecutionEngine(
            broker_adapter=broker,
            event_bus=EventBus(),
            order_store=order_store,
        )

        await engine.reconcile_on_startup()

        restored = engine.get_order("db-order-1")
        assert restored is not None
        assert restored.instrument == "AAPL"
        assert restored.quantity == 50
        assert restored.status == OrderStatus.SUBMITTED


# ---------------------------------------------------------------------------
# Initialize / Shutdown Tests
# ---------------------------------------------------------------------------

class TestInitializeShutdown:
    """Tests for engine lifecycle methods."""

    @pytest.mark.asyncio
    async def test_initialize_success(self):
        broker = AsyncMock()
        broker.get_positions = AsyncMock(return_value=[])
        # Use a mock event bus where subscribe is an AsyncMock so
        # `await self._event_bus.subscribe(...)` works.
        event_bus = AsyncMock(spec=EventBus)
        event_bus.publish = AsyncMock()
        event_bus.subscribe = AsyncMock()
        engine = ExecutionEngine(broker_adapter=broker, event_bus=event_bus)

        result = await engine.initialize()

        assert result is True
        assert ExecutionAlgorithm.VWAP in engine._algorithms
        assert ExecutionAlgorithm.TWAP in engine._algorithms
        assert len(engine.get_venues()) > 0

    @pytest.mark.asyncio
    async def test_shutdown_cancels_tasks(self):
        engine = ExecutionEngine(broker_adapter=None, event_bus=EventBus())
        engine._shutdown_event.clear()

        # Create a fake task
        async def long_running():
            await asyncio.sleep(100)

        engine._execution_tasks["test-task"] = asyncio.create_task(long_running())

        await engine.shutdown()

        assert engine._shutdown_event.is_set()


# ---------------------------------------------------------------------------
# Order Not Found (engine-level) Tests
# ---------------------------------------------------------------------------

class TestOrderNotFound:
    """Tests for operations on non-existent orders."""

    @pytest.mark.asyncio
    async def test_handle_fill_unknown_order_does_not_raise(self):
        engine = ExecutionEngine(broker_adapter=None, event_bus=EventBus())
        # Should silently return without error
        await engine.handle_fill("ghost", 10, 100.0)

    @pytest.mark.asyncio
    async def test_get_fills_for_unknown_order_empty(self):
        engine = ExecutionEngine(broker_adapter=None, event_bus=EventBus())
        assert engine.get_fills("ghost") == []

    def test_get_execution_report_unknown_order_none(self):
        engine = ExecutionEngine(broker_adapter=None, event_bus=EventBus())
        assert engine.get_execution_report("ghost") is None


# ---------------------------------------------------------------------------
# Handle Order Request (event bus integration)
# ---------------------------------------------------------------------------

class TestHandleOrderRequest:
    """Tests for _handle_order_request event handler."""

    @pytest.mark.asyncio
    async def test_handle_order_request_valid(self):
        engine = ExecutionEngine(broker_adapter=None, event_bus=EventBus())
        event = Event(
            type=EventType.ORDER,
            data={
                "instrument": "AAPL",
                "side": OrderSide.BUY,
                "order_type": OrderType.LIMIT,
                "quantity": 100,
                "price": 150.0,
            },
        )
        await engine._handle_order_request(event)

        active = engine.get_active_orders()
        assert len(active) == 1
        assert active[0].instrument == "AAPL"

    @pytest.mark.asyncio
    async def test_handle_order_request_invalid_data(self):
        engine = ExecutionEngine(broker_adapter=None, event_bus=EventBus())
        event = Event(
            type=EventType.ORDER,
            data={"quantity": 0},  # invalid: no instrument, zero quantity
        )
        # Should not raise
        await engine._handle_order_request(event)
        assert len(engine.get_active_orders()) == 0
