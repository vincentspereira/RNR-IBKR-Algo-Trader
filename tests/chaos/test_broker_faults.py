"""Broker fault-injection chaos tests (master plan Phase 10.4).

Each test injects a specific broker fault against an existing execution seam
and asserts that the system degrades gracefully -- no overfill, no zombie
state, no unhandled exception, and a deterministic terminal outcome.  All
faults are simulated via event ordering and mocked broker objects; there are
NO real sleeps, timers, or sockets.

Fault matrix
------------
+----------------------------------+------------------------------------------+
| Fault injected                   | Expected graceful behaviour              |
+==================================+==========================================+
| Duplicate fill (broker resend)   | Dedup absorbs (order_id, event_id);      |
|                                  | cumulative qty unchanged.                |
| Partial fills then cancel        | Terminal CANCELLED; partial fills kept;  |
|                                  | no overfill.                             |
| Fill after terminal              | IllegalTransitionError; state unchanged. |
| Out-of-order ack after cancel    | IllegalTransitionError; state unchanged. |
| Broker rejection mid-flow        | Terminal REJECTED; tracker partitions.   |
| Adapter connect failure          | connect() -> False, status ERROR, no     |
|                                  | zombie; disconnect() safe afterwards.    |
| placeOrder raises                | Order recorded rejected; no unhandled    |
|                                  | exception reaches the caller.            |
| Slow / interleaved market data   | Consumer never deadlocks or double-      |
|                                  | processes (event-sequenced, no sleep).   |
+----------------------------------+------------------------------------------+
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

import core_trading.adapters.ibkr_adapter as ibkr_mod
from core_trading.adapters.base import ConnectionStatus
from core_trading.adapters.ibkr_adapter import IBKRAdapter
from core_trading.execution.lifecycle import (
    AckEvent,
    CancelEvent,
    FillEvent,
    IllegalTransitionError,
    LifecycleTracker,
    OrderState,
    OverfillError,
    RejectEvent,
)
from core_trading.execution.pairs_execution import (
    Leg,
    PairExecutor,
    PairOrder,
)

TEST_ACCOUNT = "DU_TEST_ACCOUNT"


def _ts(offset: int = 0) -> pd.Timestamp:
    """Deterministic, monotonically increasing event timestamp."""
    return pd.Timestamp("2026-06-05T10:00:00Z") + pd.Timedelta(seconds=offset)


# ===========================================================================
# Lifecycle-seam faults (LifecycleTracker / OrderLifecycle)
# ===========================================================================


class TestDuplicateFillResend:
    """FAULT: broker resends the SAME execution report twice (at-least-once
    delivery, reconnect replay). EXPECTED: dedup on (order_id, event_id)
    absorbs the duplicate; cumulative filled quantity is unchanged and no
    second audit record is appended."""

    def test_duplicate_fill_is_idempotent(self):
        tracker = LifecycleTracker()
        lc = tracker.register("O1", quantity=100.0)
        tracker.apply("O1", AckEvent(timestamp=_ts(0), event_id="ack-1"))

        fill = FillEvent(qty=40.0, price=10.0, timestamp=_ts(1), event_id="exec-1")
        tracker.apply("O1", fill)
        first_filled = lc.filled_qty
        first_audit_len = len(lc.audit_trail)

        # Broker RESENDS the identical execution report.
        state = tracker.apply("O1", fill)

        assert lc.filled_qty == first_filled == 40.0
        assert len(lc.audit_trail) == first_audit_len  # no duplicate record
        assert state == OrderState.PARTIAL

    def test_distinct_event_ids_both_apply(self):
        """Control: two DIFFERENT event_ids for genuinely distinct fills both
        apply (the dedup must not over-absorb)."""
        tracker = LifecycleTracker()
        lc = tracker.register("O1", quantity=100.0)
        tracker.apply("O1", AckEvent(timestamp=_ts(0), event_id="ack-1"))
        tracker.apply("O1", FillEvent(40.0, 10.0, _ts(1), event_id="exec-1"))
        tracker.apply("O1", FillEvent(40.0, 10.0, _ts(2), event_id="exec-2"))
        assert lc.filled_qty == 80.0


class TestPartialThenCancel:
    """FAULT: order receives partial fills, then a cancel arrives while
    quantity is still open. EXPECTED: terminal CANCELLED with the partial
    fills RETAINED; no overfill; remaining quantity is not forced to zero."""

    def test_partial_fills_then_cancel_retains_fills(self):
        tracker = LifecycleTracker()
        lc = tracker.register("O1", quantity=100.0)
        tracker.apply("O1", AckEvent(timestamp=_ts(0)))
        tracker.apply("O1", FillEvent(30.0, 10.0, _ts(1)))
        tracker.apply("O1", FillEvent(20.0, 11.0, _ts(2)))
        assert lc.state == OrderState.PARTIAL
        assert lc.filled_qty == 50.0

        state = tracker.apply("O1", CancelEvent(timestamp=_ts(3)))
        assert state == OrderState.CANCELLED
        assert lc.is_terminal is True
        # Partial fills retained, not wiped.
        assert lc.filled_qty == 50.0
        assert lc.remaining_qty == 50.0

    def test_no_overfill_on_excess_fill(self):
        """FAULT: a fill increment would push cumulative qty above the order
        quantity (broker double-counts). EXPECTED: OverfillError, state and
        filled qty unchanged from before the bad fill."""
        tracker = LifecycleTracker()
        lc = tracker.register("O1", quantity=100.0)
        tracker.apply("O1", AckEvent(timestamp=_ts(0)))
        tracker.apply("O1", FillEvent(80.0, 10.0, _ts(1)))
        with pytest.raises(OverfillError):
            tracker.apply("O1", FillEvent(40.0, 10.0, _ts(2)))  # 120 > 100
        assert lc.filled_qty == 80.0
        assert lc.state == OrderState.PARTIAL


class TestFillAfterTerminal:
    """FAULT: a fill (or ack) arrives AFTER the order reached a terminal state
    (out-of-order / late broker message). EXPECTED: IllegalTransitionError is
    raised and the terminal state is left unchanged -- the late message can be
    logged and dropped without corrupting the book."""

    def test_fill_after_filled_raises(self):
        tracker = LifecycleTracker()
        lc = tracker.register("O1", quantity=100.0)
        tracker.apply("O1", AckEvent(timestamp=_ts(0)))
        tracker.apply("O1", FillEvent(100.0, 10.0, _ts(1)))
        assert lc.state == OrderState.FILLED
        with pytest.raises(IllegalTransitionError):
            tracker.apply("O1", FillEvent(1.0, 10.0, _ts(2)))
        assert lc.state == OrderState.FILLED
        assert lc.filled_qty == 100.0

    def test_fill_after_cancelled_raises(self):
        tracker = LifecycleTracker()
        lc = tracker.register("O1", quantity=100.0)
        tracker.apply("O1", AckEvent(timestamp=_ts(0)))
        tracker.apply("O1", FillEvent(30.0, 10.0, _ts(1)))
        tracker.apply("O1", CancelEvent(timestamp=_ts(2)))
        assert lc.state == OrderState.CANCELLED
        with pytest.raises(IllegalTransitionError):
            tracker.apply("O1", FillEvent(10.0, 10.0, _ts(3)))
        assert lc.state == OrderState.CANCELLED
        assert lc.filled_qty == 30.0

    def test_ack_after_cancel_out_of_order_raises(self):
        """FAULT: an Ack arrives AFTER a Cancel (events delivered out of
        order). EXPECTED: IllegalTransitionError; state stays CANCELLED."""
        tracker = LifecycleTracker()
        lc = tracker.register("O1", quantity=50.0)
        tracker.apply("O1", AckEvent(timestamp=_ts(0)))
        tracker.apply("O1", CancelEvent(timestamp=_ts(1)))
        audit_len = len(lc.audit_trail)
        with pytest.raises(IllegalTransitionError):
            tracker.apply("O1", AckEvent(timestamp=_ts(2)))
        assert lc.state == OrderState.CANCELLED
        assert len(lc.audit_trail) == audit_len  # failed transition not recorded


class TestRejectionMidFlow:
    """FAULT: broker rejects an order mid-flow (e.g. after ack, before fill).
    EXPECTED: terminal REJECTED; the tracker partitions the rejected order out
    of the open set, and a clean order in the same tracker is unaffected."""

    def test_reject_after_ack_partitions_tracker(self):
        tracker = LifecycleTracker()
        bad = tracker.register("BAD", quantity=100.0)
        good = tracker.register("GOOD", quantity=100.0)

        tracker.apply("BAD", AckEvent(timestamp=_ts(0)))
        tracker.apply("BAD", RejectEvent(reason="risk", timestamp=_ts(1)))

        tracker.apply("GOOD", AckEvent(timestamp=_ts(0)))
        tracker.apply("GOOD", FillEvent(100.0, 10.0, _ts(1)))

        assert bad.state == OrderState.REJECTED
        assert good.state == OrderState.FILLED
        # Partitioning: rejected order is terminal, good order is terminal too,
        # neither remains open.
        terminal_ids = {lc.order_id for lc in tracker.terminal_orders()}
        assert terminal_ids == {"BAD", "GOOD"}
        assert tracker.open_orders() == []

    def test_reject_before_ack_is_terminal(self):
        """FAULT: broker rejects before acknowledging (NEW -> REJECTED).
        EXPECTED: terminal REJECTED with zero fills; subsequent events raise."""
        tracker = LifecycleTracker()
        lc = tracker.register("O1", quantity=100.0)
        tracker.apply("O1", RejectEvent(reason="symbol halted", timestamp=_ts(0)))
        assert lc.state == OrderState.REJECTED
        assert lc.filled_qty == 0.0
        with pytest.raises(IllegalTransitionError):
            tracker.apply("O1", AckEvent(timestamp=_ts(1)))


# ===========================================================================
# Adapter-seam faults (IBKRAdapter connect / placeOrder)
# ===========================================================================


@pytest.fixture
def fake_ib():
    """A fake ib_insync.IB instance whose connectAsync is awaitable."""
    ib = MagicMock(name="IBInstance")
    ib.connectAsync = AsyncMock(return_value=True)
    ib.isConnected = MagicMock(return_value=True)
    ib.disconnect = MagicMock()
    ib.disconnectedEvent = MagicMock()
    ib.errorEvent = MagicMock()
    ib.execDetailsEvent = MagicMock()
    ib.orderStatusEvent = MagicMock()
    return ib


@pytest.fixture
def patched_ib(fake_ib, monkeypatch):
    """Patch module-level IB so IB() returns the fake, with IBKR_AVAILABLE."""
    monkeypatch.setenv("IBKR_ACCOUNT_ID", TEST_ACCOUNT)
    ib_class = MagicMock(name="IBClass", return_value=fake_ib)
    with patch.object(ibkr_mod, "IB", ib_class), \
         patch.object(ibkr_mod, "IBKR_AVAILABLE", True):
        yield fake_ib


class TestAdapterConnectFailure:
    """FAULT: ib.connectAsync raises (TWS down / refused). EXPECTED: connect()
    returns False, status is ERROR, the adapter is NOT left in a half-open
    'zombie' connected state, and a follow-up disconnect() is safe."""

    @pytest.mark.asyncio
    async def test_connect_failure_no_zombie_state(self, patched_ib, monkeypatch):
        monkeypatch.setenv("IBKR_ACCOUNT_ID", TEST_ACCOUNT)
        patched_ib.connectAsync.side_effect = ConnectionRefusedError("no TWS")
        adapter = IBKRAdapter()

        result = await adapter.connect()

        assert result is False
        assert adapter.status == ConnectionStatus.ERROR
        assert adapter.is_connected is False

        # No zombie: a follow-up disconnect must not raise and lands the
        # adapter cleanly in DISCONNECTED.
        # The fake IB reports isConnected() True, so disconnect() will call
        # ib.disconnect(); that must be tolerated without error.
        ok = await adapter.disconnect()
        assert ok is True
        assert adapter.status == ConnectionStatus.DISCONNECTED

    @pytest.mark.asyncio
    async def test_connect_unavailable_sets_error(self, monkeypatch):
        """FAULT: ib_insync not installed. EXPECTED: RuntimeError AND status
        ERROR (honest failure, never a silent simulated connection)."""
        monkeypatch.setenv("IBKR_ACCOUNT_ID", TEST_ACCOUNT)
        adapter = IBKRAdapter()
        with patch.object(ibkr_mod, "IBKR_AVAILABLE", False), \
             pytest.raises(RuntimeError, match="ib_insync is not installed"):
            await adapter.connect()
        assert adapter.status == ConnectionStatus.ERROR
        assert adapter.is_connected is False


class TestAdapterPlaceOrderFault:
    """FAULT: ib.placeOrder raises inside the adapter (broker boom).
    EXPECTED: the adapter catches it, records the order as 'rejected', and
    returns a structured result -- NO unhandled exception escapes to the
    engine-side caller."""

    @pytest.mark.asyncio
    async def test_place_order_exception_recorded_rejected(self, patched_ib):
        adapter = IBKRAdapter()
        assert await adapter.connect() is True

        patched_ib.placeOrder.side_effect = RuntimeError("broker boom")
        result = await adapter.place_order({
            "symbol": "AAPL",
            "side": "buy",
            "quantity": 1,
            "price": 10.0,
            "order_type": "limit",
        })

        assert result["status"] == "rejected"
        assert "broker boom" in result["reason"]
        # Internal book records the rejected order (no silent drop).
        order_id = result["order_id"]
        assert adapter._orders[order_id]["status"] == "rejected"

    @pytest.mark.asyncio
    async def test_subsequent_order_after_fault_succeeds(self, patched_ib):
        """After a placeOrder fault, the adapter must remain usable: a later,
        clean placeOrder succeeds (the fault did not corrupt adapter state)."""
        adapter = IBKRAdapter()
        await adapter.connect()

        patched_ib.placeOrder.side_effect = RuntimeError("transient")
        bad = await adapter.place_order({
            "symbol": "AAPL", "side": "buy", "quantity": 1,
            "price": 10.0, "order_type": "limit",
        })
        assert bad["status"] == "rejected"

        # Recover: broker behaves normally now.
        good_trade = MagicMock()
        good_trade.order = MagicMock()
        good_trade.order.orderId = "5005"
        patched_ib.placeOrder.side_effect = None
        patched_ib.placeOrder.return_value = good_trade
        good = await adapter.place_order({
            "symbol": "MSFT", "side": "buy", "quantity": 1,
            "price": 10.0, "order_type": "limit",
        })
        assert good["status"] == "submitted"
        assert good["broker_order_id"] == "5005"


# ===========================================================================
# Market-data / FillModel seam: slow / interleaved data without deadlock
# ===========================================================================


class _SequencedFillModel:
    """A FillModel whose responses are driven by a pre-set EVENT SEQUENCE
    rather than wall-clock time, simulating 'slow' or stalled market data.

    Each ``fill_slice`` call pops the next scripted response from ``script``.
    A ``None`` entry models a slice that the (slow) market never fills; a
    tuple models a normal fill.  Every call is recorded in ``calls`` so the
    test can assert there is NO double-processing of the same slice and NO
    deadlock (the consumer always makes forward progress and terminates).
    """

    def __init__(self, script: list[tuple[float, float] | None]) -> None:
        self._script = list(script)
        self._idx = 0
        self.calls: list[tuple[str, float, float, float]] = []

    def fill_slice(
        self,
        symbol: str,
        quantity: float,
        decision_price: float,
        bar_volume: float,
    ) -> tuple[float, float] | None:
        self.calls.append((symbol, quantity, decision_price, bar_volume))
        response = self._script[self._idx]
        self._idx += 1
        return response


class TestSlowMarketDataNoDeadlock:
    """FAULT: market data is 'slow' -- a slice's fill response is delayed or
    missing, modelled via event sequencing (NOT real sleeps). EXPECTED: the
    consuming pairs-execution logic makes forward progress, never blocks, and
    never processes the same slice twice; a missing fill cleanly fails the leg
    (both-legs-or-none) instead of hanging."""

    def test_consumer_terminates_and_no_double_process(self):
        # Both legs single-slice (no slicing): script two clean fills.
        model = _SequencedFillModel([(100.0, 10.0), (-50.0, 20.0)])
        executor = PairExecutor(model)
        order = PairOrder(
            pair_id="P1",
            leg_y=Leg("AAA", 100.0, 10.0),
            leg_x=Leg("BBB", -50.0, 20.0),
        )
        result = executor.execute(order)
        assert result.filled is True
        # Exactly one fill_slice call per leg -- no double-processing, no spin.
        assert len(model.calls) == 2

    def test_stalled_slice_fails_leg_without_hanging(self):
        # Leg Y fills, leg X's data 'stalls' (None) -> leg X fails -> both-or-
        # none cancels. The call must RETURN (no deadlock), reason=leg_failed.
        model = _SequencedFillModel([(100.0, 10.0), None])
        executor = PairExecutor(model)
        order = PairOrder(
            pair_id="P2",
            leg_y=Leg("AAA", 100.0, 10.0),
            leg_x=Leg("BBB", -50.0, 20.0),
        )
        result = executor.execute(order)
        assert result.filled is False
        assert result.reason == "leg_failed"
        # Leg Y fully processed (1 call), leg X attempted exactly once then
        # short-circuited -- no retry storm.
        assert len(model.calls) == 2

    def test_interleaved_partial_then_stall_is_bounded(self):
        """FAULT: a sliced leg gets a partial fill then a stalled slice.
        EXPECTED: bounded number of slice calls (no unbounded retry), leg fails
        under require_full_fill, both-legs-or-none triggers, call returns."""
        from core_trading.execution.pairs_execution import ExecutionConfig

        # Force slicing on leg Y only (5 slices), with slice 3 stalling (None).
        # Leg X is left UN-sliced (its symbol absent from bar_volume -> infinite
        # assumed volume -> single slice) so the script length is deterministic:
        # 3 calls on leg Y (the 3rd stalls and short-circuits the leg) followed
        # by 1 call on leg X.
        cfg = ExecutionConfig(max_participation=0.01, twap_slices=5)
        # Leg Y |qty| 100 > 0.01 * bar_vol(100) = 1 -> sliced into 5.
        script: list[tuple[float, float] | None] = [
            (20.0, 10.0), (20.0, 10.0), None,  # leg Y: third slice stalls
            (-50.0, 20.0),                       # leg X: single clean slice
        ]
        model = _SequencedFillModel(script)
        executor = PairExecutor(model, cfg)
        order = PairOrder(
            pair_id="P3",
            leg_y=Leg("AAA", 100.0, 10.0),
            leg_x=Leg("BBB", -50.0, 20.0),
        )
        result = executor.execute(order, bar_volume={"AAA": 100.0})
        assert result.filled is False
        assert result.reason == "leg_failed"
        # Leg Y stopped at the stalled 3rd slice (NOT all 5 -> early-out), then
        # leg X executed once: 4 calls total, bounded -- no retry storm.
        assert len(model.calls) == 4
        # Leg Y consumed exactly 3 of its slices before failing.
        leg_y_calls = [c for c in model.calls if c[0] == "AAA"]
        assert len(leg_y_calls) == 3
