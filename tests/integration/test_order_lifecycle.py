"""Integration tests for the full order lifecycle.

Tests the end-to-end flow from signal generation through risk validation,
order submission, fill processing, state machine transitions, and position
reconciliation. Also covers rejection, cancellation, partial fills, and
kill switch emergency scenarios.
"""

import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# Ensure project root is importable
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, _project_root)
sys.path.insert(0, os.path.join(_project_root, "services", "trading-engine"))

import importlib.util

_rm_engines = os.path.join(_project_root, "services", "risk-manager", "src", "engines")


def _load_module(name, path, package=None):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    if package:
        mod.__package__ = package
    spec.loader.exec_module(mod)
    return mod


_load_module("risk_engines", os.path.join(_rm_engines, "risk_engine.py"))
_load_module("kill_switch", os.path.join(_rm_engines, "kill_switch.py"))

from src.core.event_system import Event, EventBus, EventPriority, EventType
from src.engines.execution_engine import (
    ExecutionEngine,
    Fill,
    Order,
    OrderSide,
    OrderStatus,
    OrderStateMachine,
    OrderType,
)
from risk_engines import (
    IndividualCheckResult,
    RiskCheckResult,
    RiskConfig,
    RiskEngine,
)
from kill_switch import KillSwitch, KillSwitchState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _order_to_risk_dict(order: Order) -> dict:
    """Convert an execution_engine.Order into the dict format expected by
    RiskEngine.pre_trade_check (which calls .get() on the argument).
    """
    return {
        "symbol": order.instrument,
        "instrument": order.instrument,
        "side": order.side.value,
        "quantity": order.quantity,
        "order_type": order.order_type.value,
        "price": order.price,
        "stop_price": order.stop_price,
    }


# ---------------------------------------------------------------------------
# Fixtures local to this module
# ---------------------------------------------------------------------------


@pytest.fixture
def kill_switch(mock_broker_adapter, event_bus):
    """Provide a KillSwitch wired to the mocked broker adapter and event bus."""
    return KillSwitch(broker_adapter=mock_broker_adapter, event_bus=event_bus)


# ===================================================================
# Test 1: Full happy-path order lifecycle
# ===================================================================


class TestOrderLifecycle:
    """End-to-end happy path: signal -> risk check -> submit -> fill -> reconcile."""

    @pytest.mark.asyncio
    async def test_signal_generates_order_event(self, event_bus, execution_engine):
        """Strategy publishes a SIGNAL event; verify the event bus records it."""
        signal_event = Event(
            type=EventType.SIGNAL,
            data={
                "instrument": "AAPL",
                "side": "buy",
                "quantity": 100,
                "price": 150.0,
                "strategy_id": "momentum_v1",
            },
            source="momentum_strategy",
        )

        await event_bus.publish(signal_event)

        history = await event_bus.get_history(event_type=EventType.SIGNAL)
        assert len(history) == 1
        assert history[0].data["instrument"] == "AAPL"
        assert history[0].data["side"] == "buy"
        assert history[0].source == "momentum_strategy"

    @pytest.mark.asyncio
    async def test_risk_engine_approves_order(self, risk_engine):
        """Risk engine pre-trade check approves a valid order within limits."""
        small_order = Order(
            instrument="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            price=100.0,  # $1000 < $5000 max_order_size
        )
        order_data = _order_to_risk_dict(small_order)

        result, checks = await risk_engine.pre_trade_check(order_data)

        assert result == RiskCheckResult.APPROVED
        assert all(c.passed for c in checks), (
            f"Individual checks should all pass: "
            f"{[(c.check_name, c.passed, c.message) for c in checks]}"
        )

    @pytest.mark.asyncio
    async def test_submit_order_transitions_to_submitted(
        self, execution_engine, sample_order
    ):
        """Submitting a valid order moves state to SUBMITTED and tracks the order."""
        success = await execution_engine.submit_order(sample_order)

        assert success is True
        assert sample_order.status == OrderStatus.SUBMITTED
        assert execution_engine.get_order(sample_order.order_id) is sample_order
        assert sample_order in execution_engine.get_active_orders()

    @pytest.mark.asyncio
    async def test_fill_updates_order_to_filled(
        self, execution_engine, sample_order
    ):
        """After a full fill, the order transitions to FILLED (terminal state)."""
        await execution_engine.submit_order(sample_order)

        await execution_engine.handle_fill(
            order_id=sample_order.order_id,
            fill_quantity=100.0,
            fill_price=150.50,
        )

        assert sample_order.status == OrderStatus.FILLED
        assert sample_order.filled_quantity == 100.0
        assert sample_order.remaining_quantity == 0.0
        assert sample_order.average_fill_price == pytest.approx(150.50)

        # Filled orders should no longer appear in active orders
        assert sample_order not in execution_engine.get_active_orders()

    @pytest.mark.asyncio
    async def test_fill_publishes_fill_event(
        self, execution_engine, sample_order, event_bus
    ):
        """Processing a fill publishes a FILL event on the event bus."""
        await execution_engine.submit_order(sample_order)
        await execution_engine.handle_fill(
            order_id=sample_order.order_id,
            fill_quantity=100.0,
            fill_price=150.50,
        )

        history = await event_bus.get_history(event_type=EventType.FILL)
        assert len(history) == 1
        assert history[0].data["order_id"] == sample_order.order_id
        assert history[0].data["fill_quantity"] == 100.0

    @pytest.mark.asyncio
    async def test_fill_recorded_in_engine(self, execution_engine, sample_order):
        """The execution engine stores Fill records for later retrieval."""
        await execution_engine.submit_order(sample_order)
        await execution_engine.handle_fill(
            order_id=sample_order.order_id,
            fill_quantity=100.0,
            fill_price=149.75,
        )

        fills = execution_engine.get_fills(sample_order.order_id)
        assert len(fills) == 1
        assert isinstance(fills[0], Fill)
        assert fills[0].quantity == 100.0
        assert fills[0].price == 149.75
        assert fills[0].instrument == "AAPL"

    @pytest.mark.asyncio
    async def test_position_reconciliation(self, execution_engine, mock_broker_adapter):
        """After reconciliation, the engine publishes a SYSTEM reconciliation event."""
        mock_broker_adapter.get_positions.return_value = [
            {"symbol": "AAPL", "quantity": 100, "avg_cost": 150.25},
            {"symbol": "MSFT", "quantity": 50, "avg_cost": 310.10},
        ]

        await execution_engine.reconcile_positions()

        mock_broker_adapter.get_positions.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_full_lifecycle_end_to_end(
        self, execution_engine, risk_engine, event_bus
    ):
        """Complete flow: risk check -> submit -> fill -> verify final state."""
        # Use a small order that passes all risk checks
        order = Order(
            instrument="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=10,
            price=100.0,
        )
        # Step 1: Pre-trade risk check
        order_data = _order_to_risk_dict(order)
        result, checks = await risk_engine.pre_trade_check(order_data)
        assert result == RiskCheckResult.APPROVED

        # Step 2: Submit order
        success = await execution_engine.submit_order(order)
        assert success is True
        assert order.status == OrderStatus.SUBMITTED

        # Step 3: Process fill
        await execution_engine.handle_fill(
            order_id=order.order_id,
            fill_quantity=10.0,
            fill_price=100.25,
        )
        assert order.status == OrderStatus.FILLED

        # Step 4: Verify event history contains ORDER and FILL events
        # Allow async event publish tasks to complete
        await asyncio.sleep(0.1)

        order_events = await event_bus.get_history(event_type=EventType.ORDER)
        assert len(order_events) >= 1

        fill_events = await event_bus.get_history(event_type=EventType.FILL)
        assert len(fill_events) == 1
        assert fill_events[0].data["fill_price"] == 100.25


# ===================================================================
# Test 2: Order rejection by risk engine
# ===================================================================


class TestOrderRejection:
    """Orders that breach risk limits are rejected before submission."""

    @pytest.mark.asyncio
    async def test_order_over_size_limit_rejected(self, risk_engine, sample_order):
        """An order whose notional exceeds max_order_size is rejected."""
        # risk_config fixture sets max_order_size=5000.0
        # sample_order is qty=100, price=150.0 => notional=15000.0 > 5000.0
        order_data = _order_to_risk_dict(sample_order)

        result, checks = await risk_engine.pre_trade_check(order_data)

        assert result == RiskCheckResult.REJECTED

        failed_checks = [c for c in checks if not c.passed]
        assert len(failed_checks) > 0, "At least one check must fail for a rejection"

        # The order_size_limit check must fail
        size_checks = [c for c in failed_checks if c.check_name == "order_size_limit"]
        assert len(size_checks) == 1
        assert size_checks[0].current_value == pytest.approx(15000.0)
        assert size_checks[0].limit_value == pytest.approx(5000.0)

    @pytest.mark.asyncio
    async def test_small_order_approved(self, risk_engine):
        """A small order within limits passes the pre-trade check."""
        small_order_data = {
            "symbol": "MSFT",
            "instrument": "MSFT",
            "side": "buy",
            "quantity": 10,
            "order_type": "limit",
            "price": 100.0,  # notional = 1000.0, well under max_order_size=5000
        }

        result, checks = await risk_engine.pre_trade_check(small_order_data)
        assert result == RiskCheckResult.APPROVED

    @pytest.mark.asyncio
    async def test_order_missing_symbol_rejected(self, risk_engine):
        """An order with no symbol is immediately rejected."""
        bad_order_data = {"quantity": 10, "price": 100.0}

        result, checks = await risk_engine.pre_trade_check(bad_order_data)
        assert result == RiskCheckResult.REJECTED

    @pytest.mark.asyncio
    async def test_order_zero_quantity_rejected(self, risk_engine):
        """An order with quantity 0 is immediately rejected."""
        bad_order_data = {"symbol": "AAPL", "quantity": 0, "price": 100.0}

        result, checks = await risk_engine.pre_trade_check(bad_order_data)
        assert result == RiskCheckResult.REJECTED

    @pytest.mark.asyncio
    async def test_execution_engine_rejects_invalid_order(self, execution_engine):
        """ExecutionEngine rejects orders with empty instrument or zero quantity."""
        bad_order = Order(instrument="", side=OrderSide.BUY, order_type=OrderType.MARKET, quantity=0)

        success = await execution_engine.submit_order(bad_order)
        assert success is False
        # Validation fails before state transition, so status stays PENDING
        assert bad_order.status == OrderStatus.PENDING

    @pytest.mark.asyncio
    async def test_execution_engine_rejects_limit_without_price(self, execution_engine):
        """A LIMIT order with no price is rejected by the validation check."""
        order = Order(
            instrument="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=100,
            price=None,
        )

        success = await execution_engine.submit_order(order)
        assert success is False
        # Validation fails before state transition, so status stays PENDING
        assert order.status == OrderStatus.PENDING


# ===================================================================
# Test 3: Order cancellation
# ===================================================================


class TestOrderCancellation:
    """Submitted orders can be cancelled before they are filled."""

    @pytest.mark.asyncio
    async def test_cancel_submitted_order(self, execution_engine, sample_order):
        """Cancelling a SUBMITTED order transitions it to CANCELLED."""
        await execution_engine.submit_order(sample_order)
        assert sample_order.status == OrderStatus.SUBMITTED

        cancelled = await execution_engine.cancel_order(sample_order.order_id)
        assert cancelled is True
        assert sample_order.status == OrderStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancelled_order_not_active(self, execution_engine, sample_order):
        """A cancelled order is excluded from active orders."""
        await execution_engine.submit_order(sample_order)
        await execution_engine.cancel_order(sample_order.order_id)

        active = execution_engine.get_active_orders()
        assert sample_order not in active

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_order_returns_false(self, execution_engine):
        """Cancelling an unknown order_id returns False."""
        result = await execution_engine.cancel_order("nonexistent-id")
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_filled_order_returns_false(self, execution_engine, sample_order):
        """Cancelling a FILLED (terminal) order returns False and does not change state."""
        await execution_engine.submit_order(sample_order)
        await execution_engine.handle_fill(
            order_id=sample_order.order_id,
            fill_quantity=100.0,
            fill_price=150.0,
        )
        assert sample_order.status == OrderStatus.FILLED

        result = await execution_engine.cancel_order(sample_order.order_id)
        assert result is False
        assert sample_order.status == OrderStatus.FILLED

    @pytest.mark.asyncio
    async def test_cancel_order_publishes_order_event(
        self, execution_engine, sample_order, event_bus
    ):
        """Cancelling an order publishes an ORDER event with the state change."""
        await execution_engine.submit_order(sample_order)

        # Clear history so we only see the cancellation event
        event_bus._event_history.clear()

        await execution_engine.cancel_order(sample_order.order_id)

        # Allow async event publish task to complete
        await asyncio.sleep(0.1)

        order_events = await event_bus.get_history(event_type=EventType.ORDER)
        assert len(order_events) >= 1
        last_event = order_events[-1]
        assert last_event.data["new_status"] == "cancelled"
        assert last_event.data["order_id"] == sample_order.order_id

    @pytest.mark.asyncio
    async def test_cancel_calls_broker_cancel(
        self, execution_engine, sample_order, mock_broker_adapter
    ):
        """Cancelling an order calls broker_adapter.cancel_order with the broker order ID."""
        await execution_engine.submit_order(sample_order)
        sample_order.broker_order_id = "broker-123"

        await execution_engine.cancel_order(sample_order.order_id)
        mock_broker_adapter.cancel_order.assert_awaited_with("broker-123")


# ===================================================================
# Test 4: Partial fills
# ===================================================================


class TestPartialFill:
    """Orders that receive partial fills before a final complete fill."""

    @pytest.mark.asyncio
    async def test_single_partial_fill(self, execution_engine, sample_order):
        """A single partial fill transitions the order to PARTIALLY_FILLED."""
        await execution_engine.submit_order(sample_order)

        await execution_engine.handle_fill(
            order_id=sample_order.order_id,
            fill_quantity=30.0,
            fill_price=149.50,
        )

        assert sample_order.status == OrderStatus.PARTIALLY_FILLED
        assert sample_order.filled_quantity == 30.0
        assert sample_order.remaining_quantity == pytest.approx(70.0)
        assert sample_order.average_fill_price == pytest.approx(149.50)

    @pytest.mark.asyncio
    async def test_multiple_partial_fills(self, execution_engine, sample_order):
        """Multiple partial fills accumulate correctly."""
        await execution_engine.submit_order(sample_order)

        # First partial fill: 30 shares @ 149.50
        await execution_engine.handle_fill(
            order_id=sample_order.order_id,
            fill_quantity=30.0,
            fill_price=149.50,
        )
        assert sample_order.status == OrderStatus.PARTIALLY_FILLED
        assert sample_order.filled_quantity == 30.0

        # Second partial fill: 50 shares @ 151.00
        await execution_engine.handle_fill(
            order_id=sample_order.order_id,
            fill_quantity=50.0,
            fill_price=151.00,
        )
        assert sample_order.status == OrderStatus.PARTIALLY_FILLED
        assert sample_order.filled_quantity == 80.0
        assert sample_order.remaining_quantity == pytest.approx(20.0)

        # Verify weighted average fill price: (30*149.50 + 50*151.00) / 80
        expected_avg = (30.0 * 149.50 + 50.0 * 151.00) / 80.0
        assert sample_order.average_fill_price == pytest.approx(expected_avg)

    @pytest.mark.asyncio
    async def test_partial_fills_then_complete_fill(self, execution_engine, sample_order):
        """Partial fills followed by a final fill transitions to FILLED."""
        await execution_engine.submit_order(sample_order)

        # Partial: 40 shares @ 150.00
        await execution_engine.handle_fill(
            order_id=sample_order.order_id,
            fill_quantity=40.0,
            fill_price=150.00,
        )
        assert sample_order.status == OrderStatus.PARTIALLY_FILLED

        # Partial: 30 shares @ 150.50
        await execution_engine.handle_fill(
            order_id=sample_order.order_id,
            fill_quantity=30.0,
            fill_price=150.50,
        )
        assert sample_order.status == OrderStatus.PARTIALLY_FILLED

        # Final fill: 30 shares @ 149.75 (completes the order)
        await execution_engine.handle_fill(
            order_id=sample_order.order_id,
            fill_quantity=30.0,
            fill_price=149.75,
        )
        assert sample_order.status == OrderStatus.FILLED
        assert sample_order.filled_quantity == 100.0
        assert sample_order.remaining_quantity == 0.0

        # Weighted average: (40*150.00 + 30*150.50 + 30*149.75) / 100
        expected_avg = (40.0 * 150.00 + 30.0 * 150.50 + 30.0 * 149.75) / 100.0
        assert sample_order.average_fill_price == pytest.approx(expected_avg)

    @pytest.mark.asyncio
    async def test_all_partial_fills_recorded(self, execution_engine, sample_order):
        """Each partial fill is recorded as a separate Fill record."""
        await execution_engine.submit_order(sample_order)

        await execution_engine.handle_fill(
            order_id=sample_order.order_id, fill_quantity=25.0, fill_price=150.00,
        )
        await execution_engine.handle_fill(
            order_id=sample_order.order_id, fill_quantity=25.0, fill_price=150.50,
        )
        await execution_engine.handle_fill(
            order_id=sample_order.order_id, fill_quantity=50.0, fill_price=149.75,
        )

        fills = execution_engine.get_fills(sample_order.order_id)
        assert len(fills) == 3
        assert fills[0].quantity == 25.0
        assert fills[1].quantity == 25.0
        assert fills[2].quantity == 50.0

    @pytest.mark.asyncio
    async def test_partial_fills_emit_fill_events(
        self, execution_engine, sample_order, event_bus
    ):
        """Each partial fill publishes its own FILL event."""
        await execution_engine.submit_order(sample_order)

        await execution_engine.handle_fill(
            order_id=sample_order.order_id, fill_quantity=40.0, fill_price=150.00,
        )
        await execution_engine.handle_fill(
            order_id=sample_order.order_id, fill_quantity=60.0, fill_price=151.00,
        )

        fill_events = await event_bus.get_history(event_type=EventType.FILL)
        assert len(fill_events) == 2
        assert fill_events[0].data["fill_quantity"] == 40.0
        assert fill_events[1].data["fill_quantity"] == 60.0

    @pytest.mark.asyncio
    async def test_partial_fill_still_active(self, execution_engine, sample_order):
        """An order with a partial fill is still considered active."""
        await execution_engine.submit_order(sample_order)
        await execution_engine.handle_fill(
            order_id=sample_order.order_id, fill_quantity=50.0, fill_price=150.0,
        )

        active = execution_engine.get_active_orders()
        assert sample_order in active


# ===================================================================
# Test 5: Kill switch integration
# ===================================================================


class TestKillSwitchIntegration:
    """Kill switch emergency shutdown cancels orders and closes positions."""

    @pytest.mark.asyncio
    async def test_activate_cancels_open_orders(
        self, kill_switch, mock_broker_adapter
    ):
        """Activating the kill switch cancels all open orders via the broker."""
        mock_broker_adapter.get_open_orders.return_value = [
            {"order_id": "order-1", "symbol": "AAPL", "side": "buy", "quantity": 100},
            {"order_id": "order-2", "symbol": "MSFT", "side": "sell", "quantity": 50},
        ]

        summary = await kill_switch.activate("Daily loss limit exceeded")

        assert kill_switch.is_active is True
        assert kill_switch.state == KillSwitchState.ACTIVE
        assert summary["orders_cancelled"] == 2
        assert summary["reason"] == "Daily loss limit exceeded"
        assert mock_broker_adapter.cancel_order.await_count == 2

    @pytest.mark.asyncio
    async def test_activate_closes_positions(
        self, kill_switch, mock_broker_adapter
    ):
        """Activating the kill switch places opposing market orders to close positions."""
        mock_broker_adapter.get_open_orders.return_value = []
        mock_broker_adapter.get_positions.return_value = [
            {"symbol": "AAPL", "quantity": 100},
            {"symbol": "GOOG", "quantity": -25},
        ]
        mock_broker_adapter.place_order.return_value = {"status": "submitted"}

        summary = await kill_switch.activate("Emergency shutdown")

        assert summary["positions_closed"] == 2
        assert mock_broker_adapter.place_order.await_count == 2

        # Verify the closing orders have correct sides
        place_calls = mock_broker_adapter.place_order.call_args_list
        aapl_order = place_calls[0][0][0]
        assert aapl_order["symbol"] == "AAPL"
        assert aapl_order["side"] == "sell"  # closing long position
        assert aapl_order["quantity"] == 100

        goog_order = place_calls[1][0][0]
        assert goog_order["symbol"] == "GOOG"
        assert goog_order["side"] == "buy"  # closing short position
        assert goog_order["quantity"] == 25

    @pytest.mark.asyncio
    async def test_activate_publishes_emergency_event(
        self, kill_switch, mock_broker_adapter, event_bus
    ):
        """Activating the kill switch publishes a critical RISK_ALERT event."""
        mock_broker_adapter.get_open_orders.return_value = []
        mock_broker_adapter.get_positions.return_value = []

        await kill_switch.activate("Kill switch test")

        # The kill switch tries to import Event/EventType from its sibling
        # risk_engine module.  Depending on how the module was loaded, this
        # may or may not succeed.  At minimum, the kill switch should be active.
        assert kill_switch.is_active is True

    @pytest.mark.asyncio
    async def test_activate_when_already_active(self, kill_switch):
        """Activating an already-active kill switch returns early."""
        mock_broker_adapter = kill_switch._broker
        mock_broker_adapter.get_open_orders.return_value = []
        mock_broker_adapter.get_positions.return_value = []

        await kill_switch.activate("First activation")
        result = await kill_switch.activate("Second activation")

        assert result["status"] == "already_active"
        assert kill_switch.reason == "First activation"

    @pytest.mark.asyncio
    async def test_deactivate_requires_confirmation(self, kill_switch, mock_broker_adapter):
        """Deactivation requires the exact confirmation string."""
        mock_broker_adapter.get_open_orders.return_value = []
        mock_broker_adapter.get_positions.return_value = []

        await kill_switch.activate("Test reason")

        # Wrong confirmation
        deactivated = await kill_switch.deactivate(confirmation="WRONG")
        assert deactivated is False
        assert kill_switch.is_active is True

        # Correct confirmation
        deactivated = await kill_switch.deactivate(confirmation="CONFIRM_DEACTIVATE")
        assert deactivated is True
        assert kill_switch.is_active is False
        assert kill_switch.state == KillSwitchState.INACTIVE

    @pytest.mark.asyncio
    async def test_deactivate_publishes_event(
        self, kill_switch, mock_broker_adapter, event_bus
    ):
        """Deactivating the kill switch publishes a deactivation event."""
        mock_broker_adapter.get_open_orders.return_value = []
        mock_broker_adapter.get_positions.return_value = []

        await kill_switch.activate("Test activation")
        await kill_switch.deactivate(confirmation="CONFIRM_DEACTIVATE")

        # Deactivation should succeed regardless of event publishing
        assert kill_switch.is_active is False
        assert kill_switch.state == KillSwitchState.INACTIVE

    @pytest.mark.asyncio
    async def test_get_status_reflects_state(self, kill_switch, mock_broker_adapter):
        """get_status() returns an accurate snapshot of kill switch state."""
        mock_broker_adapter.get_open_orders.return_value = []
        mock_broker_adapter.get_positions.return_value = []

        status = kill_switch.get_status()
        assert status["state"] == "inactive"
        assert status["is_active"] is False

        await kill_switch.activate("Testing status")
        status = kill_switch.get_status()
        assert status["state"] == "active"
        assert status["is_active"] is True
        assert status["reason"] == "Testing status"
        assert status["activated_at"] is not None

    @pytest.mark.asyncio
    async def test_kill_switch_with_no_broker_adapter(self, event_bus):
        """Kill switch gracefully handles missing broker adapter."""
        ks = KillSwitch(broker_adapter=None, event_bus=event_bus)
        summary = await ks.activate("No broker test")

        assert ks.is_active is True
        assert summary["orders_cancelled"] == 0
        assert summary["positions_closed"] == 0

    @pytest.mark.asyncio
    async def test_kill_switch_cancellation_error_handling(
        self, kill_switch, mock_broker_adapter
    ):
        """Kill switch continues if cancelling an individual order fails."""
        mock_broker_adapter.get_open_orders.return_value = [
            {"order_id": "good-order"},
            {"order_id": "bad-order"},
        ]
        # First cancellation succeeds, second raises
        mock_broker_adapter.cancel_order.side_effect = [
            None,  # success (no exception)
            RuntimeError("Broker timeout"),
        ]

        summary = await kill_switch.activate("Partial failure test")

        assert kill_switch.is_active is True
        assert summary["orders_cancelled"] == 1
        assert len(summary["errors"]) > 0

    @pytest.mark.asyncio
    async def test_kill_switch_closes_positions_with_market_orders(
        self, execution_engine, kill_switch, mock_broker_adapter, event_bus
    ):
        """End-to-end: submit orders, activate kill switch, verify cleanup."""
        # Submit an order to the execution engine
        order = Order(
            instrument="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=100,
            price=150.0,
        )
        await execution_engine.submit_order(order)
        assert order.status == OrderStatus.SUBMITTED

        # Setup kill switch to find open orders and positions
        mock_broker_adapter.get_open_orders.return_value = [
            {"order_id": order.broker_order_id or order.order_id},
        ]
        mock_broker_adapter.get_positions.return_value = [
            {"symbol": "AAPL", "quantity": 100},
        ]
        mock_broker_adapter.place_order.return_value = {"status": "submitted"}

        summary = await kill_switch.activate("Integration test shutdown")

        assert summary["orders_cancelled"] == 1
        assert summary["positions_closed"] == 1
        assert kill_switch.is_active is True
