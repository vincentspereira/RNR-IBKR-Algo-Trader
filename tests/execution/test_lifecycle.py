"""Tests for core_trading.execution.lifecycle (Phase 9.6).

Coverage targets
----------------
State machine
    * Every legal transition pinned (NEW->ACK, NEW->REJECTED, ACK->FILLED,
      ACK->PARTIAL, ACK->CANCELLED, ACK->REJECTED, PARTIAL->PARTIAL,
      PARTIAL->FILLED, PARTIAL->CANCELLED).
    * Every illegal transition raises IllegalTransitionError with from-state +
      event detail (ack after cancel, fill after terminal, etc.).
    * Overfill guard raises OverfillError.
    * Cumulative qty, weighted avg price, total fees, audit trail replayability.
LifecycleTracker
    * Multi-order registration, open/terminal partitioning.
    * Idempotent duplicate-event dedup by event_id; event_id=None always applied.
Reconciliation
    * Clean case; each mismatch class; tolerance boundaries (at-tolerance passes,
      just-beyond fails); partial-fill aggregation; missing-column ValueError.
    * Alert callback invocation counts.
    * Renderer golden substrings (clean + mismatch paths).
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import pandas as pd
import pytest

from core_trading.execution.lifecycle import (
    BROKER_FILL_COLUMNS,
    DEFAULT_RECON_CONFIG,
    INTERNAL_FILL_COLUMNS,
    AckEvent,
    AuditRecord,
    CancelEvent,
    FillEvent,
    IllegalTransitionError,
    LifecycleTracker,
    Mismatch,
    MismatchClass,
    OrderLifecycle,
    OrderState,
    OverfillError,
    ReconciliationAlert,
    ReconciliationConfig,
    ReconciliationReport,
    RejectEvent,
    reconcile,
    render_reconciliation,
    run_daily_reconciliation,
)

# ---------------------------------------------------------------------------
# Deterministic timestamps
# ---------------------------------------------------------------------------

TS0 = pd.Timestamp("2024-01-02T10:00:00Z")
TS1 = pd.Timestamp("2024-01-02T10:00:01Z")
TS2 = pd.Timestamp("2024-01-02T10:00:02Z")
TS3 = pd.Timestamp("2024-01-02T10:00:03Z")


def _new_order(qty: float = 100.0, oid: str = "O1") -> OrderLifecycle:
    return OrderLifecycle(oid, quantity=qty)


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


def test_constructor_rejects_empty_order_id() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        OrderLifecycle("", quantity=10.0)


def test_constructor_rejects_nonpositive_quantity() -> None:
    with pytest.raises(ValueError, match="quantity must be"):
        OrderLifecycle("O1", quantity=0.0)


# ---------------------------------------------------------------------------
# Legal transitions
# ---------------------------------------------------------------------------


def test_new_to_ack() -> None:
    lc = _new_order()
    assert lc.state is OrderState.NEW
    assert lc.apply(AckEvent(timestamp=TS0)) is OrderState.ACK
    assert lc.state is OrderState.ACK


def test_new_to_rejected() -> None:
    lc = _new_order()
    state = lc.apply(RejectEvent(reason="too big", timestamp=TS0))
    assert state is OrderState.REJECTED
    assert lc.is_terminal


def test_ack_to_filled_single_full_fill() -> None:
    lc = _new_order(qty=100.0)
    lc.apply(AckEvent(timestamp=TS0))
    state = lc.apply(FillEvent(qty=100.0, price=10.0, timestamp=TS1, fees=1.0))
    assert state is OrderState.FILLED
    assert lc.filled_qty == 100.0
    assert lc.avg_fill_price == 10.0
    assert lc.total_fees == 1.0
    assert lc.remaining_qty == 0.0


def test_ack_to_partial() -> None:
    lc = _new_order(qty=100.0)
    lc.apply(AckEvent(timestamp=TS0))
    state = lc.apply(FillEvent(qty=40.0, price=10.0, timestamp=TS1))
    assert state is OrderState.PARTIAL
    assert lc.filled_qty == 40.0
    assert lc.remaining_qty == 60.0
    assert not lc.is_terminal


def test_ack_to_cancelled() -> None:
    lc = _new_order()
    lc.apply(AckEvent(timestamp=TS0))
    assert lc.apply(CancelEvent(timestamp=TS1)) is OrderState.CANCELLED
    assert lc.is_terminal


def test_ack_to_rejected() -> None:
    lc = _new_order()
    lc.apply(AckEvent(timestamp=TS0))
    assert lc.apply(RejectEvent(reason="halt", timestamp=TS1)) is OrderState.REJECTED


def test_partial_to_partial_to_filled_weighted_price() -> None:
    lc = _new_order(qty=100.0)
    lc.apply(AckEvent(timestamp=TS0))
    assert lc.apply(FillEvent(qty=40.0, price=10.0, timestamp=TS1, fees=0.4)) is (
        OrderState.PARTIAL
    )
    assert lc.apply(FillEvent(qty=30.0, price=12.0, timestamp=TS2, fees=0.3)) is (
        OrderState.PARTIAL
    )
    assert lc.apply(FillEvent(qty=30.0, price=14.0, timestamp=TS3, fees=0.3)) is (
        OrderState.FILLED
    )
    assert lc.filled_qty == 100.0
    # Weighted avg = (40*10 + 30*12 + 30*14) / 100 = (400+360+420)/100 = 11.8
    assert lc.avg_fill_price == pytest.approx(11.8)
    assert lc.total_fees == pytest.approx(1.0)


def test_partial_to_cancelled_retains_fills() -> None:
    lc = _new_order(qty=100.0)
    lc.apply(AckEvent(timestamp=TS0))
    lc.apply(FillEvent(qty=40.0, price=10.0, timestamp=TS1))
    assert lc.apply(CancelEvent(timestamp=TS2)) is OrderState.CANCELLED
    # Partial fill retained after cancel.
    assert lc.filled_qty == 40.0
    assert lc.avg_fill_price == 10.0


def test_avg_fill_price_zero_when_unfilled() -> None:
    lc = _new_order()
    assert lc.avg_fill_price == 0.0


# ---------------------------------------------------------------------------
# Audit trail replayability
# ---------------------------------------------------------------------------


def test_audit_trail_records_every_transition() -> None:
    lc = _new_order(qty=100.0)
    ack = AckEvent(timestamp=TS0)
    f1 = FillEvent(qty=50.0, price=10.0, timestamp=TS1)
    f2 = FillEvent(qty=50.0, price=11.0, timestamp=TS2)
    lc.apply(ack)
    lc.apply(f1)
    lc.apply(f2)

    trail = lc.audit_trail
    assert len(trail) == 3
    assert all(isinstance(r, AuditRecord) for r in trail)
    assert trail[0].from_state is OrderState.NEW
    assert trail[0].to_state is OrderState.ACK
    assert trail[0].event is ack
    assert trail[1].from_state is OrderState.ACK
    assert trail[1].to_state is OrderState.PARTIAL
    assert trail[2].to_state is OrderState.FILLED
    # Timestamps preserved in order.
    assert [r.timestamp for r in trail] == [TS0, TS1, TS2]


def test_audit_trail_replay_reconstructs_state() -> None:
    lc = _new_order(qty=100.0)
    lc.apply(AckEvent(timestamp=TS0))
    lc.apply(FillEvent(qty=60.0, price=10.0, timestamp=TS1))
    lc.apply(FillEvent(qty=40.0, price=10.0, timestamp=TS2))

    # Replay the recorded events into a fresh lifecycle -> identical end state.
    replay = _new_order(qty=100.0)
    for rec in lc.audit_trail:
        replay.apply(rec.event)
    assert replay.state is lc.state
    assert replay.filled_qty == lc.filled_qty
    assert replay.avg_fill_price == lc.avg_fill_price


# ---------------------------------------------------------------------------
# Illegal transitions
# ---------------------------------------------------------------------------


def test_ack_after_cancel_illegal() -> None:
    lc = _new_order()
    lc.apply(AckEvent(timestamp=TS0))
    lc.apply(CancelEvent(timestamp=TS1))
    with pytest.raises(IllegalTransitionError, match="AckEvent.*CANCELLED"):
        lc.apply(AckEvent(timestamp=TS2))


def test_fill_after_filled_illegal() -> None:
    lc = _new_order(qty=100.0)
    lc.apply(AckEvent(timestamp=TS0))
    lc.apply(FillEvent(qty=100.0, price=10.0, timestamp=TS1))
    with pytest.raises(IllegalTransitionError, match="FillEvent.*FILLED"):
        lc.apply(FillEvent(qty=1.0, price=10.0, timestamp=TS2))


def test_fill_after_rejected_illegal() -> None:
    lc = _new_order()
    lc.apply(RejectEvent(reason="x", timestamp=TS0))
    with pytest.raises(IllegalTransitionError, match="FillEvent.*REJECTED"):
        lc.apply(FillEvent(qty=1.0, price=10.0, timestamp=TS1))


def test_ack_twice_illegal() -> None:
    lc = _new_order()
    lc.apply(AckEvent(timestamp=TS0))
    with pytest.raises(IllegalTransitionError, match="AckEvent.*ACK"):
        lc.apply(AckEvent(timestamp=TS1))


def test_fill_before_ack_illegal() -> None:
    lc = _new_order()
    with pytest.raises(IllegalTransitionError, match="FillEvent.*NEW"):
        lc.apply(FillEvent(qty=1.0, price=10.0, timestamp=TS0))


def test_cancel_from_new_illegal() -> None:
    lc = _new_order()
    with pytest.raises(IllegalTransitionError, match="CancelEvent.*NEW"):
        lc.apply(CancelEvent(timestamp=TS0))


def test_cancel_after_terminal_illegal() -> None:
    lc = _new_order()
    lc.apply(AckEvent(timestamp=TS0))
    lc.apply(CancelEvent(timestamp=TS1))
    with pytest.raises(IllegalTransitionError, match="CancelEvent.*CANCELLED"):
        lc.apply(CancelEvent(timestamp=TS2))


def test_reject_after_partial_illegal() -> None:
    lc = _new_order(qty=100.0)
    lc.apply(AckEvent(timestamp=TS0))
    lc.apply(FillEvent(qty=10.0, price=10.0, timestamp=TS1))
    with pytest.raises(IllegalTransitionError, match="RejectEvent.*PARTIAL"):
        lc.apply(RejectEvent(reason="x", timestamp=TS2))


# ---------------------------------------------------------------------------
# Overfill guard + event validation
# ---------------------------------------------------------------------------


def test_overfill_raises() -> None:
    lc = _new_order(qty=100.0)
    lc.apply(AckEvent(timestamp=TS0))
    lc.apply(FillEvent(qty=60.0, price=10.0, timestamp=TS1))
    with pytest.raises(OverfillError, match="exceeds order quantity"):
        lc.apply(FillEvent(qty=50.0, price=10.0, timestamp=TS2))
    # State unchanged by the failed apply (no audit record appended).
    assert lc.state is OrderState.PARTIAL
    assert lc.filled_qty == 60.0


def test_fill_event_validates_qty() -> None:
    with pytest.raises(ValueError, match="qty must be"):
        FillEvent(qty=0.0, price=10.0, timestamp=TS0)


def test_fill_event_validates_price() -> None:
    with pytest.raises(ValueError, match="price must be"):
        FillEvent(qty=1.0, price=0.0, timestamp=TS0)


def test_fill_event_validates_fees() -> None:
    with pytest.raises(ValueError, match="fees must be"):
        FillEvent(qty=1.0, price=10.0, timestamp=TS0, fees=-1.0)


# ---------------------------------------------------------------------------
# LifecycleTracker: registration, partitioning
# ---------------------------------------------------------------------------


def test_tracker_register_and_get() -> None:
    tr = LifecycleTracker()
    lc = tr.register("O1", 100.0)
    assert tr.get("O1") is lc
    assert "O1" in tr
    assert len(tr) == 1


def test_tracker_duplicate_registration_raises() -> None:
    tr = LifecycleTracker()
    tr.register("O1", 100.0)
    with pytest.raises(ValueError, match="already registered"):
        tr.register("O1", 50.0)


def test_tracker_open_and_terminal_partition() -> None:
    tr = LifecycleTracker()
    tr.register("OPEN1", 100.0)
    tr.register("OPEN2", 100.0)
    tr.register("DONE", 100.0)

    tr.apply("OPEN1", AckEvent(timestamp=TS0))
    tr.apply("OPEN2", AckEvent(timestamp=TS0))
    tr.apply("OPEN2", FillEvent(qty=10.0, price=10.0, timestamp=TS1))
    tr.apply("DONE", AckEvent(timestamp=TS0))
    tr.apply("DONE", FillEvent(qty=100.0, price=10.0, timestamp=TS1))

    open_ids = {lc.order_id for lc in tr.open_orders()}
    term_ids = {lc.order_id for lc in tr.terminal_orders()}
    assert open_ids == {"OPEN1", "OPEN2"}
    assert term_ids == {"DONE"}
    assert len(tr.all_orders()) == 3


# ---------------------------------------------------------------------------
# LifecycleTracker: dedup contract
# ---------------------------------------------------------------------------


def test_tracker_dedups_duplicate_event_id() -> None:
    tr = LifecycleTracker()
    tr.register("O1", 100.0)
    tr.apply("O1", AckEvent(timestamp=TS0, event_id="ack-1"))
    fill = FillEvent(qty=40.0, price=10.0, timestamp=TS1, event_id="fill-1")
    state1 = tr.apply("O1", fill)
    # Broker resends the same execution report.
    state2 = tr.apply("O1", fill)
    assert state1 is OrderState.PARTIAL
    assert state2 is OrderState.PARTIAL
    lc = tr.get("O1")
    # Applied exactly once: qty not doubled.
    assert lc.filled_qty == 40.0
    # No audit record for the duplicate (ack + one fill == 2).
    assert len(lc.audit_trail) == 2


def test_tracker_none_event_id_always_applied() -> None:
    tr = LifecycleTracker()
    tr.register("O1", 100.0)
    tr.apply("O1", AckEvent(timestamp=TS0))
    f = FillEvent(qty=30.0, price=10.0, timestamp=TS1, event_id=None)
    tr.apply("O1", f)
    tr.apply("O1", f)  # event_id=None -> not deduplicated -> applied again
    lc = tr.get("O1")
    assert lc.filled_qty == 60.0
    assert len(lc.audit_trail) == 3


def test_tracker_event_id_scoped_per_order() -> None:
    tr = LifecycleTracker()
    tr.register("O1", 100.0)
    tr.register("O2", 100.0)
    # Same event_id "e1" across two different orders -> both applied.
    tr.apply("O1", AckEvent(timestamp=TS0, event_id="e1"))
    tr.apply("O2", AckEvent(timestamp=TS0, event_id="e1"))
    assert tr.get("O1").state is OrderState.ACK
    assert tr.get("O2").state is OrderState.ACK


# ---------------------------------------------------------------------------
# Reconciliation helpers
# ---------------------------------------------------------------------------


def _internal_df(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=list(INTERNAL_FILL_COLUMNS))


def _broker_df(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=list(BROKER_FILL_COLUMNS))


def test_default_recon_config_is_reconciliation_config() -> None:
    assert isinstance(DEFAULT_RECON_CONFIG, ReconciliationConfig)


def test_recon_config_rejects_negative_tolerance() -> None:
    with pytest.raises(ValueError, match="qty_tolerance"):
        ReconciliationConfig(qty_tolerance=-1.0)
    with pytest.raises(ValueError, match="price_tolerance"):
        ReconciliationConfig(price_tolerance=-1.0)
    with pytest.raises(ValueError, match="fee_tolerance"):
        ReconciliationConfig(fee_tolerance=-1.0)


# ---------------------------------------------------------------------------
# Reconciliation: clean case
# ---------------------------------------------------------------------------


def test_reconcile_clean() -> None:
    internal = _internal_df(
        [
            {"order_id": "O1", "qty": 100.0, "price": 10.0, "fees": 1.0},
            {"order_id": "O2", "qty": 50.0, "price": 20.0, "fees": 0.5},
        ]
    )
    broker = _broker_df(
        [
            {"order_id": "O1", "qty": 100.0, "price": 10.0, "fees": 1.0},
            {"order_id": "O2", "qty": 50.0, "price": 20.0, "fees": 0.5},
        ]
    )
    report = reconcile(internal, broker)
    assert report.clean
    assert report.matched == 2
    assert report.mismatches == ()


def test_reconcile_aggregates_partial_fills() -> None:
    # Internal has two partials for O1 that aggregate to the broker's single row.
    internal = _internal_df(
        [
            {"order_id": "O1", "qty": 60.0, "price": 10.0, "fees": 0.6},
            {"order_id": "O1", "qty": 40.0, "price": 15.0, "fees": 0.4},
        ]
    )
    broker = _broker_df(
        [
            # weighted price = (60*10 + 40*15)/100 = (600+600)/100 = 12.0
            {"order_id": "O1", "qty": 100.0, "price": 12.0, "fees": 1.0},
        ]
    )
    report = reconcile(internal, broker)
    assert report.clean
    assert report.matched == 1


# ---------------------------------------------------------------------------
# Reconciliation: each mismatch class
# ---------------------------------------------------------------------------


def test_reconcile_missing_broker() -> None:
    internal = _internal_df(
        [{"order_id": "O1", "qty": 100.0, "price": 10.0, "fees": 1.0}]
    )
    broker = _broker_df([])
    report = reconcile(internal, broker)
    assert not report.clean
    assert report.matched == 0
    ms = report.by_class(MismatchClass.MISSING_BROKER)
    assert len(ms) == 1
    assert ms[0].order_id == "O1"
    assert ms[0].internal_value == 100.0
    assert ms[0].broker_value is None


def test_reconcile_missing_internal() -> None:
    internal = _internal_df([])
    broker = _broker_df(
        [{"order_id": "O9", "qty": 25.0, "price": 5.0, "fees": 0.1}]
    )
    report = reconcile(internal, broker)
    ms = report.by_class(MismatchClass.MISSING_INTERNAL)
    assert len(ms) == 1
    assert ms[0].internal_value is None
    assert ms[0].broker_value == 25.0


def test_reconcile_qty_mismatch() -> None:
    internal = _internal_df(
        [{"order_id": "O1", "qty": 100.0, "price": 10.0, "fees": 1.0}]
    )
    broker = _broker_df(
        [{"order_id": "O1", "qty": 90.0, "price": 10.0, "fees": 1.0}]
    )
    report = reconcile(internal, broker)
    ms = report.by_class(MismatchClass.QTY_MISMATCH)
    assert len(ms) == 1
    assert ms[0].field == "qty"
    assert ms[0].internal_value == 100.0
    assert ms[0].broker_value == 90.0
    assert report.matched == 0


def test_reconcile_price_mismatch() -> None:
    internal = _internal_df(
        [{"order_id": "O1", "qty": 100.0, "price": 10.0, "fees": 1.0}]
    )
    broker = _broker_df(
        [{"order_id": "O1", "qty": 100.0, "price": 10.5, "fees": 1.0}]
    )
    report = reconcile(internal, broker)
    ms = report.by_class(MismatchClass.PRICE_MISMATCH)
    assert len(ms) == 1
    assert ms[0].field == "price"


def test_reconcile_fee_mismatch() -> None:
    internal = _internal_df(
        [{"order_id": "O1", "qty": 100.0, "price": 10.0, "fees": 1.0}]
    )
    broker = _broker_df(
        [{"order_id": "O1", "qty": 100.0, "price": 10.0, "fees": 2.0}]
    )
    report = reconcile(internal, broker)
    ms = report.by_class(MismatchClass.FEE_MISMATCH)
    assert len(ms) == 1
    assert ms[0].field == "fees"


def test_reconcile_multiple_fields_one_order() -> None:
    internal = _internal_df(
        [{"order_id": "O1", "qty": 100.0, "price": 10.0, "fees": 1.0}]
    )
    broker = _broker_df(
        [{"order_id": "O1", "qty": 90.0, "price": 11.0, "fees": 2.0}]
    )
    report = reconcile(internal, broker)
    # Three field-level mismatches on the same order, none counted as matched.
    assert len(report.mismatches) == 3
    assert report.matched == 0
    kinds = {m.kind for m in report.mismatches}
    assert kinds == {
        MismatchClass.QTY_MISMATCH,
        MismatchClass.PRICE_MISMATCH,
        MismatchClass.FEE_MISMATCH,
    }


# ---------------------------------------------------------------------------
# Reconciliation: tolerance boundaries
# ---------------------------------------------------------------------------


def test_reconcile_exactly_at_tolerance_passes() -> None:
    # Use deltas that are exactly representable in binary float so the
    # at-tolerance comparison is not perturbed by representation error.
    cfg = ReconciliationConfig(
        qty_tolerance=0.5, price_tolerance=0.25, fee_tolerance=0.125
    )
    internal = _internal_df(
        [{"order_id": "O1", "qty": 100.0, "price": 10.00, "fees": 1.00}]
    )
    broker = _broker_df(
        [{"order_id": "O1", "qty": 100.5, "price": 10.25, "fees": 1.125}]
    )
    report = reconcile(internal, broker, config=cfg)
    # All three deltas equal their tolerances exactly -> match.
    assert report.clean
    assert report.matched == 1


def test_reconcile_just_beyond_tolerance_fails() -> None:
    cfg = ReconciliationConfig(qty_tolerance=0.5)
    internal = _internal_df(
        [{"order_id": "O1", "qty": 100.0, "price": 10.0, "fees": 1.0}]
    )
    broker = _broker_df(
        [{"order_id": "O1", "qty": 100.51, "price": 10.0, "fees": 1.0}]
    )
    report = reconcile(internal, broker, config=cfg)
    assert not report.clean
    assert len(report.by_class(MismatchClass.QTY_MISMATCH)) == 1


# ---------------------------------------------------------------------------
# Reconciliation: column validation
# ---------------------------------------------------------------------------


def test_reconcile_missing_internal_column_raises() -> None:
    internal = pd.DataFrame({"order_id": ["O1"], "qty": [1.0], "price": [10.0]})
    broker = _broker_df(
        [{"order_id": "O1", "qty": 1.0, "price": 10.0, "fees": 0.0}]
    )
    with pytest.raises(ValueError, match="internal_fills.*fees"):
        reconcile(internal, broker)


def test_reconcile_missing_broker_column_raises() -> None:
    internal = _internal_df(
        [{"order_id": "O1", "qty": 1.0, "price": 10.0, "fees": 0.0}]
    )
    broker = pd.DataFrame({"order_id": ["O1"], "qty": [1.0], "fees": [0.0]})
    with pytest.raises(ValueError, match="broker_fills.*price"):
        reconcile(internal, broker)


# ---------------------------------------------------------------------------
# run_daily_reconciliation: alert dispatch
# ---------------------------------------------------------------------------


def test_run_daily_reconciliation_no_alert_fn_clean() -> None:
    internal = _internal_df(
        [{"order_id": "O1", "qty": 100.0, "price": 10.0, "fees": 1.0}]
    )
    broker = _broker_df(
        [{"order_id": "O1", "qty": 100.0, "price": 10.0, "fees": 1.0}]
    )
    report = run_daily_reconciliation(internal, broker)
    assert isinstance(report, ReconciliationReport)
    assert report.clean


def test_run_daily_reconciliation_alert_per_mismatch() -> None:
    internal = _internal_df(
        [
            {"order_id": "O1", "qty": 100.0, "price": 10.0, "fees": 1.0},
            {"order_id": "O2", "qty": 50.0, "price": 20.0, "fees": 0.5},
        ]
    )
    broker = _broker_df(
        [
            # O1: qty + fee mismatch (2 mismatches)
            {"order_id": "O1", "qty": 90.0, "price": 10.0, "fees": 5.0},
            # O3: present only at broker (1 mismatch: MISSING_INTERNAL)
            {"order_id": "O3", "qty": 10.0, "price": 1.0, "fees": 0.0},
            # O2 reconciles cleanly
            {"order_id": "O2", "qty": 50.0, "price": 20.0, "fees": 0.5},
        ]
    )
    alerts: list[ReconciliationAlert] = []
    report = run_daily_reconciliation(
        internal, broker, alert_fn=alerts.append
    )
    # 2 (O1 qty+fee) + 1 (O3 missing internal) = 3 mismatches -> 3 alerts.
    assert len(report.mismatches) == 3
    assert len(alerts) == 3
    assert all(isinstance(a, ReconciliationAlert) for a in alerts)
    assert {a.mismatch.order_id for a in alerts} == {"O1", "O3"}
    # Every alert carries the report's generated_at.
    assert all(a.generated_at == report.generated_at for a in alerts)
    assert report.matched == 1


def test_run_daily_reconciliation_no_alert_when_clean() -> None:
    internal = _internal_df(
        [{"order_id": "O1", "qty": 100.0, "price": 10.0, "fees": 1.0}]
    )
    broker = _broker_df(
        [{"order_id": "O1", "qty": 100.0, "price": 10.0, "fees": 1.0}]
    )
    alerts: list[ReconciliationAlert] = []
    run_daily_reconciliation(internal, broker, alert_fn=alerts.append)
    assert alerts == []


# ---------------------------------------------------------------------------
# Renderer golden substrings
# ---------------------------------------------------------------------------


def test_render_clean_report() -> None:
    internal = _internal_df(
        [{"order_id": "O1", "qty": 100.0, "price": 10.0, "fees": 1.0}]
    )
    broker = _broker_df(
        [{"order_id": "O1", "qty": 100.0, "price": 10.0, "fees": 1.0}]
    )
    report = reconcile(internal, broker)
    text = render_reconciliation(report)
    assert "# Daily Reconciliation Report" in text
    assert "Status    : CLEAN" in text
    assert "Matched   : 1" in text
    assert "No action required" in text
    # ASCII only.
    assert all(ord(ch) < 128 for ch in text)


def test_render_mismatch_report() -> None:
    internal = _internal_df(
        [{"order_id": "ORD1", "qty": 100.0, "price": 10.0, "fees": 1.0}]
    )
    broker = _broker_df(
        [{"order_id": "ORD1", "qty": 90.0, "price": 10.0, "fees": 1.0}]
    )
    report = reconcile(internal, broker)
    text = render_reconciliation(report)
    assert "Status    : MISMATCHES FOUND" in text
    assert "## Mismatch Counts by Class" in text
    assert "QTY_MISMATCH" in text
    assert "## Mismatch Detail" in text
    assert "ORD1" in text
    assert "100.000000" in text  # internal value
    assert "90.000000" in text   # broker value
    assert all(ord(ch) < 128 for ch in text)


def test_render_missing_side_shows_dash() -> None:
    internal = _internal_df([])
    broker = _broker_df(
        [{"order_id": "OX", "qty": 5.0, "price": 1.0, "fees": 0.0}]
    )
    report = reconcile(internal, broker)
    text = render_reconciliation(report)
    # internal value is None -> rendered as "-".
    assert "MISSING_INTERNAL" in text
    assert "| -" in text


# ---------------------------------------------------------------------------
# Mismatch dataclass surface
# ---------------------------------------------------------------------------


def test_mismatch_is_frozen() -> None:
    m = Mismatch(
        order_id="O1",
        kind=MismatchClass.QTY_MISMATCH,
        field="qty",
        internal_value=1.0,
        broker_value=2.0,
    )
    with pytest.raises(FrozenInstanceError):
        m.order_id = "O2"  # type: ignore[misc]
