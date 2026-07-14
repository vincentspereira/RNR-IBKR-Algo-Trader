"""Order lifecycle state machine and daily reconciliation (master plan Phase 9.6).

This module provides two cooperating capabilities for the execution layer:

Order lifecycle state machine
    A replayable, deterministic state machine that tracks a single order from
    submission through to a terminal state.  Events are typed, immutable
    dataclasses; transitions are table-driven; every transition is recorded in
    an ordered audit trail of ``(timestamp, from_state, event, to_state)``
    tuples that can be replayed to reconstruct the order's full history.

    The canonical happy path is::

        NEW -> ACK -> PARTIAL -> ... -> PARTIAL -> FILLED

    with these additional legal paths:

    * ``NEW -> REJECTED``        broker rejects before acknowledging.
    * ``ACK -> FILLED``          a single full fill (no intervening partials).
    * ``ACK -> CANCELLED``       cancelled after ack, before any fill.
    * ``PARTIAL -> CANCELLED``   cancelled after one or more partial fills; any
                                 fills already received are retained.
    * ``PARTIAL -> PARTIAL``     successive partial fills accumulate quantity.

    ``FILLED``, ``CANCELLED`` and ``REJECTED`` are terminal: any subsequent
    event raises :class:`IllegalTransitionError`.  An :class:`AckEvent` after a
    cancel, or a :class:`FillEvent` after any terminal state, are the
    archetypal illegal transitions.  Cumulative filled quantity is tracked and
    an overfill (cumulative fill strictly greater than the order quantity)
    raises :class:`OverfillError`.

A multi-order registry (:class:`LifecycleTracker`) manages many orders by
``order_id`` and supports idempotent duplicate-event detection keyed on
``event_id`` -- see the dedup contract documented on
:meth:`LifecycleTracker.apply`.

Daily reconciliation
    :func:`reconcile` matches internally recorded fills against broker-reported
    fills, aggregating partial fills per ``order_id``, and classifies any
    mismatches (missing on either side, quantity, price, or fee mismatch beyond
    configured tolerances).  :func:`run_daily_reconciliation` wraps it with an
    injectable ``alert_fn`` hook -- mirroring the injectable kill-switch /
    callback pattern used by the Phase 7 pre-trade gate
    (:mod:`core_trading.risk.pretrade`) and circuit breakers -- and
    :func:`render_reconciliation` renders an ASCII-only operator summary in the
    style of :mod:`core_trading.risk.daily_report`.

Design principles
-----------------
* **Pure / replayable**: transitions accept caller-supplied timestamps.  No
  wall-clock reads occur on any legal-transition path.  Where a default
  timestamp is convenient (event construction), it is injectable so tests stay
  deterministic.
* **ASCII only**: all rendered output is 7-bit ASCII for terminal portability
  consoles, ops email bodies and log files.

References
----------
* SEC Rule 15c3-5 (Market Access Rule) -- post-trade reconciliation controls.
* FIX protocol order state model (ExecType / OrdStatus) -- the NEW/ACK/PARTIAL/
  FILLED/CANCELLED/REJECTED lattice is a simplification of FIX OrdStatus.
"""
from __future__ import annotations

import enum
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import pandas as pd

__all__ = [
    # State machine
    "OrderState",
    "AckEvent",
    "FillEvent",
    "CancelEvent",
    "RejectEvent",
    "OrderEvent",
    "AuditRecord",
    "OrderLifecycle",
    "LifecycleTracker",
    "IllegalTransitionError",
    "OverfillError",
    # Reconciliation
    "MismatchClass",
    "ReconciliationConfig",
    "Mismatch",
    "ReconciliationReport",
    "ReconciliationAlert",
    "reconcile",
    "run_daily_reconciliation",
    "render_reconciliation",
    "DEFAULT_RECON_CONFIG",
    "INTERNAL_FILL_COLUMNS",
    "BROKER_FILL_COLUMNS",
]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class IllegalTransitionError(Exception):
    """Raised when an event is applied that is not legal from the current state.

    The error message names the originating state and the event type so the
    audit log pinpoints exactly which broker message was rejected, e.g.
    ``"Illegal transition: AckEvent not permitted from CANCELLED"``.
    """


class OverfillError(Exception):
    """Raised when cumulative filled quantity would exceed the order quantity."""


# ---------------------------------------------------------------------------
# Order states
# ---------------------------------------------------------------------------


class OrderState(enum.Enum):
    """Lifecycle states for a single order.

    NEW
        Order created internally / submitted, not yet acknowledged by broker.
    ACK
        Broker acknowledged the order; it is live but unfilled.
    PARTIAL
        One or more partial fills received; more quantity remains open.
    FILLED
        Fully filled (cumulative quantity == order quantity).  Terminal.
    CANCELLED
        Cancelled; any partial fills already received are retained.  Terminal.
    REJECTED
        Rejected by the broker (before or after ack).  Terminal.
    """

    NEW = "NEW"
    ACK = "ACK"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


_TERMINAL_STATES: frozenset[OrderState] = frozenset(
    {OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED}
)


# ---------------------------------------------------------------------------
# Typed events
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AckEvent:
    """Broker acknowledgement of a live order.

    Attributes
    ----------
    timestamp:
        Caller-supplied event time.
    event_id:
        Optional broker-unique identifier used for idempotent dedup.  ``None``
        disables dedup for this event (it is always applied).
    """

    timestamp: pd.Timestamp
    event_id: str | None = None


@dataclass(frozen=True, slots=True)
class FillEvent:
    """A (partial or full) execution against the order.

    Attributes
    ----------
    qty:
        Filled quantity for *this* event (the increment, not cumulative).
        Must be strictly positive; sign of the order is carried by the order
        quantity, not the fill increment.
    price:
        Execution price for this fill.  Must be strictly positive.
    timestamp:
        Caller-supplied event time.
    fees:
        Fees/commissions charged on this fill (non-negative).
    event_id:
        Optional broker-unique identifier used for idempotent dedup.
    """

    qty: float
    price: float
    timestamp: pd.Timestamp
    fees: float = 0.0
    event_id: str | None = None

    def __post_init__(self) -> None:
        if not (self.qty > 0.0):
            raise ValueError(f"FillEvent.qty must be > 0, got {self.qty!r}")
        if not (self.price > 0.0):
            raise ValueError(f"FillEvent.price must be > 0, got {self.price!r}")
        if self.fees < 0.0:
            raise ValueError(f"FillEvent.fees must be >= 0, got {self.fees!r}")


@dataclass(frozen=True, slots=True)
class CancelEvent:
    """Confirmation that the order was cancelled.

    Attributes
    ----------
    timestamp:
        Caller-supplied event time.
    event_id:
        Optional broker-unique identifier used for idempotent dedup.
    """

    timestamp: pd.Timestamp
    event_id: str | None = None


@dataclass(frozen=True, slots=True)
class RejectEvent:
    """Broker rejection of the order.

    Attributes
    ----------
    reason:
        Human-readable ASCII rejection reason.
    timestamp:
        Caller-supplied event time.
    event_id:
        Optional broker-unique identifier used for idempotent dedup.
    """

    reason: str
    timestamp: pd.Timestamp
    event_id: str | None = None


# Union of all event types.
OrderEvent = AckEvent | FillEvent | CancelEvent | RejectEvent


@dataclass(frozen=True, slots=True)
class AuditRecord:
    """One immutable entry in an order's replayable audit trail.

    Attributes
    ----------
    timestamp:
        Event timestamp.
    from_state:
        State before the transition.
    event:
        The typed event that drove the transition.
    to_state:
        State after the transition.
    """

    timestamp: pd.Timestamp
    from_state: OrderState
    event: OrderEvent
    to_state: OrderState


# ---------------------------------------------------------------------------
# Single-order lifecycle state machine
# ---------------------------------------------------------------------------


class OrderLifecycle:
    """Replayable state machine for a single order.

    Parameters
    ----------
    order_id:
        Unique identifier for this order.
    quantity:
        Total order quantity (absolute, strictly positive).  Cumulative fills
        are compared against this value; exceeding it raises
        :class:`OverfillError`.

    Attributes
    ----------
    state:
        Current :class:`OrderState`.
    filled_qty:
        Cumulative filled quantity.
    avg_fill_price:
        Quantity-weighted average fill price, or ``0.0`` if unfilled.
    total_fees:
        Sum of fees across all applied fills.
    audit_trail:
        Ordered list of :class:`AuditRecord` entries; deterministic and
        replayable.

    Examples
    --------
    >>> lc = OrderLifecycle("O1", quantity=100.0)
    >>> ts = pd.Timestamp("2024-01-02T10:00:00Z")
    >>> _ = lc.apply(AckEvent(timestamp=ts))
    >>> _ = lc.apply(FillEvent(qty=100.0, price=10.0, timestamp=ts))
    >>> lc.state
    <OrderState.FILLED: 'FILLED'>
    """

    def __init__(self, order_id: str, quantity: float) -> None:
        if not order_id:
            raise ValueError("order_id must be a non-empty string.")
        if not (quantity > 0.0):
            raise ValueError(f"quantity must be > 0, got {quantity!r}")
        self.order_id = order_id
        self.quantity = float(quantity)
        self.state: OrderState = OrderState.NEW
        self.filled_qty: float = 0.0
        self._fill_notional: float = 0.0
        self.total_fees: float = 0.0
        self.audit_trail: list[AuditRecord] = []

    # ------------------------------------------------------------------
    # Derived quantities
    # ------------------------------------------------------------------

    @property
    def avg_fill_price(self) -> float:
        """Quantity-weighted average fill price (0.0 when unfilled)."""
        if self.filled_qty <= 0.0:
            return 0.0
        return self._fill_notional / self.filled_qty

    @property
    def remaining_qty(self) -> float:
        """Open quantity not yet filled."""
        return self.quantity - self.filled_qty

    @property
    def is_terminal(self) -> bool:
        """``True`` when the order has reached a terminal state."""
        return self.state in _TERMINAL_STATES

    # ------------------------------------------------------------------
    # Transition application
    # ------------------------------------------------------------------

    def apply(self, event: OrderEvent) -> OrderState:
        """Apply a single event, mutating state and appending an audit record.

        Parameters
        ----------
        event:
            One of :class:`AckEvent`, :class:`FillEvent`, :class:`CancelEvent`
            or :class:`RejectEvent`.

        Returns
        -------
        OrderState
            The new state after the transition.

        Raises
        ------
        IllegalTransitionError
            If the event is not legal from the current state.
        OverfillError
            If a fill would push cumulative quantity above the order quantity.
        """
        from_state = self.state

        if isinstance(event, AckEvent):
            to_state = self._apply_ack(from_state)
        elif isinstance(event, FillEvent):
            to_state = self._apply_fill(from_state, event)
        elif isinstance(event, CancelEvent):
            to_state = self._apply_cancel(from_state)
        elif isinstance(event, RejectEvent):
            to_state = self._apply_reject(from_state)
        else:  # pragma: no cover - exhaustive over the OrderEvent union
            raise IllegalTransitionError(
                f"Unknown event type: {type(event).__name__}"
            )

        self.state = to_state
        self.audit_trail.append(
            AuditRecord(
                timestamp=event.timestamp,
                from_state=from_state,
                event=event,
                to_state=to_state,
            )
        )
        return to_state

    def _illegal(self, from_state: OrderState, event: OrderEvent) -> IllegalTransitionError:
        return IllegalTransitionError(
            f"Illegal transition: {type(event).__name__} not permitted from "
            f"{from_state.value}"
        )

    def _apply_ack(self, from_state: OrderState) -> OrderState:
        # Ack is only legal from NEW.
        if from_state is OrderState.NEW:
            return OrderState.ACK
        raise self._illegal(from_state, AckEvent(timestamp=pd.Timestamp(0)))

    def _apply_fill(self, from_state: OrderState, event: FillEvent) -> OrderState:
        if from_state not in (OrderState.ACK, OrderState.PARTIAL):
            raise self._illegal(from_state, event)
        new_filled = self.filled_qty + event.qty
        # Overfill guard with a small tolerance for float accumulation.
        if new_filled > self.quantity + 1e-9:
            raise OverfillError(
                f"Overfill on order {self.order_id}: cumulative fill "
                f"{new_filled!r} exceeds order quantity {self.quantity!r}"
            )
        self.filled_qty = new_filled
        self._fill_notional += event.qty * event.price
        self.total_fees += event.fees
        if new_filled >= self.quantity - 1e-9:
            return OrderState.FILLED
        return OrderState.PARTIAL

    def _apply_cancel(self, from_state: OrderState) -> OrderState:
        # Cancel is legal from ACK or PARTIAL (retain any partial fills).
        if from_state in (OrderState.ACK, OrderState.PARTIAL):
            return OrderState.CANCELLED
        raise self._illegal(from_state, CancelEvent(timestamp=pd.Timestamp(0)))

    def _apply_reject(self, from_state: OrderState) -> OrderState:
        # Reject is legal from NEW (pre-ack) or ACK (post-ack, pre-fill).
        if from_state in (OrderState.NEW, OrderState.ACK):
            return OrderState.REJECTED
        raise self._illegal(
            from_state, RejectEvent(reason="", timestamp=pd.Timestamp(0))
        )


# ---------------------------------------------------------------------------
# Multi-order registry
# ---------------------------------------------------------------------------


class LifecycleTracker:
    """Registry that manages many :class:`OrderLifecycle` instances by id.

    Dedup contract
    --------------
    Broker APIs (FIX drop-copy, IBKR ``execDetails``, REST polling) routinely
    *resend* execution reports -- on reconnect, on heartbeat recovery, or
    simply because at-least-once delivery is the norm.  To keep the lifecycle
    deterministic under replay, :meth:`apply` deduplicates on ``event_id``:

    * Each ``(order_id, event_id)`` pair is applied **at most once**.  A second
      event carrying an ``event_id`` already seen for that order is silently
      ignored and the order's current state is returned unchanged.  No audit
      record is appended for the duplicate.
    * An event whose ``event_id`` is ``None`` is treated as *not deduplicated*
      and is always applied.  Callers that need idempotency MUST supply a
      stable, broker-unique ``event_id``.
    * Dedup is scoped per ``order_id``; the same ``event_id`` string may legally
      recur across different orders.

    Parameters
    ----------
    None.
    """

    def __init__(self) -> None:
        self._orders: dict[str, OrderLifecycle] = {}
        # Per-order set of event_ids already consumed (dedup ledger).
        self._seen: dict[str, set[str]] = {}

    # ------------------------------------------------------------------
    # Registration / lookup
    # ------------------------------------------------------------------

    def register(self, order_id: str, quantity: float) -> OrderLifecycle:
        """Create and register a new :class:`OrderLifecycle`.

        Raises
        ------
        ValueError
            If ``order_id`` is already registered.
        """
        if order_id in self._orders:
            raise ValueError(f"order_id {order_id!r} already registered.")
        lc = OrderLifecycle(order_id, quantity)
        self._orders[order_id] = lc
        self._seen[order_id] = set()
        return lc

    def get(self, order_id: str) -> OrderLifecycle:
        """Return the :class:`OrderLifecycle` for ``order_id``.

        Raises
        ------
        KeyError
            If the order is not registered.
        """
        return self._orders[order_id]

    def __contains__(self, order_id: object) -> bool:
        return order_id in self._orders

    def __len__(self) -> int:
        return len(self._orders)

    # ------------------------------------------------------------------
    # Event application
    # ------------------------------------------------------------------

    def apply(self, order_id: str, event: OrderEvent) -> OrderState:
        """Apply ``event`` to the named order with idempotent dedup.

        See the class-level dedup contract for the ``event_id`` semantics.

        Parameters
        ----------
        order_id:
            Identifier of a previously registered order.
        event:
            The typed event to apply.

        Returns
        -------
        OrderState
            The order state after applying (or the unchanged state if the
            event was a deduplicated duplicate).

        Raises
        ------
        KeyError
            If the order is not registered.
        IllegalTransitionError, OverfillError
            Propagated from :meth:`OrderLifecycle.apply`.
        """
        lc = self._orders[order_id]
        eid = event.event_id
        if eid is not None:
            seen = self._seen[order_id]
            if eid in seen:
                return lc.state
            seen.add(eid)
        return lc.apply(event)

    # ------------------------------------------------------------------
    # Bulk queries
    # ------------------------------------------------------------------

    def open_orders(self) -> list[OrderLifecycle]:
        """Return all orders not yet in a terminal state."""
        return [lc for lc in self._orders.values() if not lc.is_terminal]

    def terminal_orders(self) -> list[OrderLifecycle]:
        """Return all orders that have reached a terminal state."""
        return [lc for lc in self._orders.values() if lc.is_terminal]

    def all_orders(self) -> list[OrderLifecycle]:
        """Return every registered order (registration order preserved)."""
        return list(self._orders.values())


# ---------------------------------------------------------------------------
# Reconciliation: mismatch taxonomy
# ---------------------------------------------------------------------------


class MismatchClass(enum.Enum):
    """Classification of a single reconciliation mismatch.

    MISSING_INTERNAL
        Broker reports a fill for an order we have no internal record of.
    MISSING_BROKER
        We recorded a fill the broker does not show.
    QTY_MISMATCH
        Aggregate filled quantity differs beyond ``qty_tolerance``.
    PRICE_MISMATCH
        Quantity-weighted average price differs beyond ``price_tolerance``.
    FEE_MISMATCH
        Aggregate fees differ beyond ``fee_tolerance``.
    """

    MISSING_INTERNAL = "MISSING_INTERNAL"
    MISSING_BROKER = "MISSING_BROKER"
    QTY_MISMATCH = "QTY_MISMATCH"
    PRICE_MISMATCH = "PRICE_MISMATCH"
    FEE_MISMATCH = "FEE_MISMATCH"


# Required DataFrame columns for the reconciliation inputs.
INTERNAL_FILL_COLUMNS: tuple[str, ...] = ("order_id", "qty", "price", "fees")
BROKER_FILL_COLUMNS: tuple[str, ...] = ("order_id", "qty", "price", "fees")


@dataclass(frozen=True, slots=True)
class ReconciliationConfig:
    """Tolerances for reconciliation matching.

    Attributes
    ----------
    qty_tolerance:
        Absolute tolerance on aggregate filled quantity.  A difference whose
        absolute value is ``<= qty_tolerance`` is considered a match.  Default
        ``1e-6``.
    price_tolerance:
        Absolute tolerance on the quantity-weighted average fill price.
        Default ``1e-4``.
    fee_tolerance:
        Absolute tolerance on aggregate fees.  Default ``1e-4``.
    """

    qty_tolerance: float = 1e-6
    price_tolerance: float = 1e-4
    fee_tolerance: float = 1e-4

    def __post_init__(self) -> None:
        for name, val in (
            ("qty_tolerance", self.qty_tolerance),
            ("price_tolerance", self.price_tolerance),
            ("fee_tolerance", self.fee_tolerance),
        ):
            if val < 0.0:
                raise ValueError(
                    f"ReconciliationConfig.{name} must be >= 0, got {val!r}"
                )


DEFAULT_RECON_CONFIG: ReconciliationConfig = ReconciliationConfig()


@dataclass(frozen=True, slots=True)
class Mismatch:
    """A single machine-readable reconciliation discrepancy.

    Attributes
    ----------
    order_id:
        The order on which the discrepancy was found.
    kind:
        The :class:`MismatchClass` of the discrepancy.
    field:
        The field name that differs (``"qty"``, ``"price"``, ``"fees"``), or
        ``"order"`` for whole-order presence mismatches.
    internal_value:
        The internal aggregate value (``None`` if absent internally).
    broker_value:
        The broker aggregate value (``None`` if absent at the broker).
    """

    order_id: str
    kind: MismatchClass
    field: str
    internal_value: float | None
    broker_value: float | None


@dataclass(frozen=True, slots=True)
class ReconciliationAlert:
    """Alert payload dispatched once per mismatch via the injected hook.

    Attributes
    ----------
    mismatch:
        The :class:`Mismatch` that triggered the alert.
    generated_at:
        ISO-8601 UTC timestamp string recorded when the report was produced.
    """

    mismatch: Mismatch
    generated_at: str


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    """Result of a reconciliation run.

    Attributes
    ----------
    matched:
        Count of order_ids that reconciled cleanly across all fields.
    mismatches:
        All discrepancies, ordered deterministically by (order_id, kind).
    generated_at:
        ISO-8601 UTC timestamp string.
    config:
        The :class:`ReconciliationConfig` used.
    """

    matched: int
    mismatches: tuple[Mismatch, ...]
    generated_at: str
    config: ReconciliationConfig

    @property
    def clean(self) -> bool:
        """``True`` when there are zero mismatches (Phase 9 DOD predicate)."""
        return len(self.mismatches) == 0

    def by_class(self, kind: MismatchClass) -> tuple[Mismatch, ...]:
        """Return all mismatches of a given :class:`MismatchClass`."""
        return tuple(m for m in self.mismatches if m.kind is kind)


# ---------------------------------------------------------------------------
# Reconciliation engine
# ---------------------------------------------------------------------------


def _utcnow_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _validate_columns(frame: pd.DataFrame, required: tuple[str, ...], label: str) -> None:
    missing = [c for c in required if c not in frame.columns]
    if missing:
        raise ValueError(
            f"{label} is missing required column(s): {', '.join(missing)}"
        )


def _aggregate_fills(frame: pd.DataFrame) -> dict[str, dict[str, float]]:
    """Aggregate per-order: total qty, qty-weighted avg price, total fees.

    Returns a mapping ``order_id -> {"qty", "price", "fees"}``.  Partial fills
    for the same ``order_id`` are summed; price is the quantity-weighted mean.
    """
    out: dict[str, dict[str, float]] = {}
    for oid_raw, qty_raw, price_raw, fees_raw in zip(
        frame["order_id"].to_numpy(),
        frame["qty"].to_numpy(dtype=float),
        frame["price"].to_numpy(dtype=float),
        frame["fees"].to_numpy(dtype=float),
        strict=True,
    ):
        oid = str(oid_raw)
        rec = out.setdefault(oid, {"qty": 0.0, "notional": 0.0, "fees": 0.0})
        rec["qty"] += float(qty_raw)
        rec["notional"] += float(qty_raw) * float(price_raw)
        rec["fees"] += float(fees_raw)
    # Collapse notional into a weighted-average price.
    result: dict[str, dict[str, float]] = {}
    for oid, rec in out.items():
        qty = rec["qty"]
        price = rec["notional"] / qty if qty != 0.0 else 0.0
        result[oid] = {"qty": qty, "price": price, "fees": rec["fees"]}
    return result


def reconcile(
    internal_fills: pd.DataFrame,
    broker_fills: pd.DataFrame,
    *,
    config: ReconciliationConfig = DEFAULT_RECON_CONFIG,
) -> ReconciliationReport:
    """Reconcile internal fills against broker fills, by ``order_id``.

    Fills are aggregated per order (partial fills summed; price is the
    quantity-weighted mean) before comparison.

    Required columns
    ----------------
    Both ``internal_fills`` and ``broker_fills`` must contain the columns
    ``order_id``, ``qty``, ``price``, ``fees``.  A missing column raises
    :class:`ValueError` naming the offending column(s).

    Parameters
    ----------
    internal_fills:
        Internally recorded fills.
    broker_fills:
        Broker-reported fills (e.g. from a daily drop-copy file).
    config:
        Tolerances; defaults to :data:`DEFAULT_RECON_CONFIG`.

    Returns
    -------
    ReconciliationReport
        Matched count and an ordered tuple of :class:`Mismatch` records.

    Raises
    ------
    ValueError
        If either frame is missing a required column.
    """
    _validate_columns(internal_fills, INTERNAL_FILL_COLUMNS, "internal_fills")
    _validate_columns(broker_fills, BROKER_FILL_COLUMNS, "broker_fills")

    internal = _aggregate_fills(internal_fills)
    broker = _aggregate_fills(broker_fills)

    generated_at = _utcnow_iso()
    mismatches: list[Mismatch] = []
    matched = 0

    all_ids = sorted(set(internal) | set(broker))
    for oid in all_ids:
        in_internal = oid in internal
        in_broker = oid in broker

        if in_internal and not in_broker:
            mismatches.append(
                Mismatch(
                    order_id=oid,
                    kind=MismatchClass.MISSING_BROKER,
                    field="order",
                    internal_value=internal[oid]["qty"],
                    broker_value=None,
                )
            )
            continue
        if in_broker and not in_internal:
            mismatches.append(
                Mismatch(
                    order_id=oid,
                    kind=MismatchClass.MISSING_INTERNAL,
                    field="order",
                    internal_value=None,
                    broker_value=broker[oid]["qty"],
                )
            )
            continue

        # Present on both sides: field-level comparison.
        i_rec = internal[oid]
        b_rec = broker[oid]
        order_clean = True

        if abs(i_rec["qty"] - b_rec["qty"]) > config.qty_tolerance:
            order_clean = False
            mismatches.append(
                Mismatch(
                    order_id=oid,
                    kind=MismatchClass.QTY_MISMATCH,
                    field="qty",
                    internal_value=i_rec["qty"],
                    broker_value=b_rec["qty"],
                )
            )
        if abs(i_rec["price"] - b_rec["price"]) > config.price_tolerance:
            order_clean = False
            mismatches.append(
                Mismatch(
                    order_id=oid,
                    kind=MismatchClass.PRICE_MISMATCH,
                    field="price",
                    internal_value=i_rec["price"],
                    broker_value=b_rec["price"],
                )
            )
        if abs(i_rec["fees"] - b_rec["fees"]) > config.fee_tolerance:
            order_clean = False
            mismatches.append(
                Mismatch(
                    order_id=oid,
                    kind=MismatchClass.FEE_MISMATCH,
                    field="fees",
                    internal_value=i_rec["fees"],
                    broker_value=b_rec["fees"],
                )
            )

        if order_clean:
            matched += 1

    # Deterministic ordering: by order_id then class name.
    mismatches.sort(key=lambda m: (m.order_id, m.kind.value))

    return ReconciliationReport(
        matched=matched,
        mismatches=tuple(mismatches),
        generated_at=generated_at,
        config=config,
    )


def run_daily_reconciliation(
    internal_fills: pd.DataFrame,
    broker_fills: pd.DataFrame,
    *,
    config: ReconciliationConfig = DEFAULT_RECON_CONFIG,
    alert_fn: Callable[[ReconciliationAlert], None] | None = None,
) -> ReconciliationReport:
    """Run :func:`reconcile` and dispatch one alert per mismatch.

    The ``alert_fn`` hook mirrors the injectable kill-switch / callback pattern
    used by the Phase 7 pre-trade gate and circuit breakers: there is **no**
    real pager / PagerDuty / e-mail integration in this module.  Operators wire
    a concrete dispatcher (Slack webhook, pager, log sink) by passing it as
    ``alert_fn``.  The callback is invoked exactly once per :class:`Mismatch`,
    in the report's deterministic mismatch order.

    Parameters
    ----------
    internal_fills, broker_fills:
        See :func:`reconcile`.
    config:
        Tolerances; defaults to :data:`DEFAULT_RECON_CONFIG`.
    alert_fn:
        Optional callback receiving a :class:`ReconciliationAlert` per
        mismatch.  ``None`` disables alerting (the report is still returned).

    Returns
    -------
    ReconciliationReport
        The same report :func:`reconcile` produces.
    """
    report = reconcile(internal_fills, broker_fills, config=config)
    if alert_fn is not None:
        for mismatch in report.mismatches:
            alert_fn(
                ReconciliationAlert(
                    mismatch=mismatch,
                    generated_at=report.generated_at,
                )
            )
    return report


# ---------------------------------------------------------------------------
# ASCII renderer
# ---------------------------------------------------------------------------


def _fmt_value(value: float | None) -> str:
    return "-" if value is None else f"{value:.6f}"


def render_reconciliation(report: ReconciliationReport) -> str:
    """Render a :class:`ReconciliationReport` as an ASCII-only summary string.

    All output is 7-bit ASCII -- suitable for terminal-portable consoles, ops
    email bodies and log files.

    Parameters
    ----------
    report:
        The report to render.

    Returns
    -------
    str
        ASCII-only multi-line summary.
    """
    lines: list[str] = []
    lines.append("# Daily Reconciliation Report")
    lines.append("")
    lines.append(f"Generated : {report.generated_at}")
    status = "CLEAN" if report.clean else "MISMATCHES FOUND"
    lines.append(f"Status    : {status}")
    lines.append(f"Matched   : {report.matched}")
    lines.append(f"Mismatches: {len(report.mismatches)}")
    lines.append("")

    if report.clean:
        lines.append("All orders reconciled within tolerance. No action required.")
        lines.append("")
        return "\n".join(lines)

    # Per-class counts.
    lines.append("## Mismatch Counts by Class")
    lines.append("")
    for kind in MismatchClass:
        count = len(report.by_class(kind))
        lines.append(f"{kind.value:<18}: {count}")
    lines.append("")

    # Detail table.
    lines.append("## Mismatch Detail")
    lines.append("")
    w_oid = 14
    w_kind = 18
    w_field = 8
    w_val = 16
    header = (
        f"| {'order_id':<{w_oid}} "
        f"| {'class':<{w_kind}} "
        f"| {'field':<{w_field}} "
        f"| {'internal':<{w_val}} "
        f"| {'broker':<{w_val}} |"
    )
    divider = (
        f"|{'-' * (w_oid + 2)}"
        f"|{'-' * (w_kind + 2)}"
        f"|{'-' * (w_field + 2)}"
        f"|{'-' * (w_val + 2)}"
        f"|{'-' * (w_val + 2)}|"
    )
    lines.append(header)
    lines.append(divider)
    for m in report.mismatches:
        row = (
            f"| {m.order_id:<{w_oid}} "
            f"| {m.kind.value:<{w_kind}} "
            f"| {m.field:<{w_field}} "
            f"| {_fmt_value(m.internal_value):<{w_val}} "
            f"| {_fmt_value(m.broker_value):<{w_val}} |"
        )
        lines.append(row)
    lines.append("")
    return "\n".join(lines)
