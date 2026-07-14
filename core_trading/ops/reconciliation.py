"""Daily broker-vs-internal reconciliation engine (master plan Phase 12.5 / 12.6).

This module is a *pure generator* -- it never touches the clock, filesystem,
or any live data source.  The ``generated_at`` timestamp is injectable, and the
only data source on the CLI is ``--demo``.  It mirrors the structure of
:mod:`core_trading.ops.attribution` and :mod:`core_trading.risk.daily_report`.

Four reconciliation sections are provided:

1. **Position reconciliation** -- compares internal vs broker symbol quantities,
   flags per-symbol matches, mismatches, and one-sided positions.  Configurable
   quantity tolerance (default 0, exact match).

2. **Fill reconciliation** -- matches internal and broker fill records for a day,
   order_id-first, then greedy (symbol, side, quantity) fallback.  Reports
   unmatched fills on each side and price discrepancies beyond a bps tolerance.

3. **Cash reconciliation** -- compares internal cash balance to broker cash
   within configurable absolute and relative tolerances.

4. **Wash-sale tracking** (Phase 12.6) -- given realised-loss sale events and
   buy events, flags wash sales under the IRS 30-day before/after replacement
   rule (61-day window) and computes disallowed loss amounts using the
   proportional-replacement rule.  **This is informational personal-records
   tooling only, not tax advice.**  Consult a qualified tax professional for
   all tax-related decisions.

Incident strings
----------------
Any mismatch produces machine-readable incident strings in the style used by
:mod:`core_trading.ops.pairs_live_runner` (``"{date}: {description}"``).
These strings flow directly into an operator's incident pipeline without
further processing.

CLI entry point
---------------
``python -m core_trading.ops.reconciliation --demo``
    Runs seeded synthetic data through all sections and prints the full ASCII
    report, demonstrating one CLEAN and one MISMATCH scenario.

``python -m core_trading.ops.reconciliation --demo --output <path>``
    Same as ``--demo`` but also writes the report to the given file path.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import date as _date
from datetime import timedelta
from typing import Any

__all__ = [
    # Config
    "ReconciliationConfig",
    # Position reconciliation
    "PositionRecord",
    "PositionReconciliationResult",
    "reconcile_positions",
    # Fill reconciliation
    "FillMatchRecord",
    "FillReconciliationResult",
    "reconcile_fills",
    # Cash reconciliation
    "CashReconciliationResult",
    "reconcile_cash",
    # Overall report
    "ReconciliationStatus",
    "ReconciliationReport",
    "build_reconciliation_report",
    # Wash-sale tracking
    "SaleEvent",
    "BuyEvent",
    "WashSaleFlag",
    "WashSaleReport",
    "flag_wash_sales",
    # Renderer + CLI
    "render_reconciliation_report",
    "main",
]

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReconciliationConfig:
    """Configuration for all reconciliation sections.

    Attributes
    ----------
    position_qty_tol:
        Absolute tolerance for position quantity comparison.  Two quantities
        that differ by at most this value are considered matching.
        Default 0.0 (exact match).
    fill_price_bps_tol:
        Tolerance for fill price discrepancy expressed in basis points of the
        internal fill price.  Discrepancies at or below this threshold are
        considered acceptable price variation (e.g., sub-cent rounding).
        Default 0.5 bps.
    cash_abs_tol:
        Absolute cash tolerance in the account's base currency.  Differences
        at or below this value are considered clean.  Default 0.01.
    cash_rel_tol:
        Relative cash tolerance as a fraction of the larger of internal and
        broker cash balances.  Applied in addition to ``cash_abs_tol``; the
        balances are clean when ``abs(diff) <= max(cash_abs_tol,
        cash_rel_tol * max(abs(internal), abs(broker)))``.  Default 1e-5.
    generated_at:
        Optional UTC timestamp string embedded in the rendered report.
        ``None`` causes :func:`render_reconciliation_report` to embed an
        empty string.
    bps_scale:
        Multiplier to convert a fractional price difference to basis points.
        Default 10_000.0.
    """

    position_qty_tol: float = 0.0
    fill_price_bps_tol: float = 0.5
    cash_abs_tol: float = 0.01
    cash_rel_tol: float = 1e-5
    generated_at: str | None = None
    bps_scale: float = 10_000.0

    def __post_init__(self) -> None:
        if self.position_qty_tol < 0.0:
            raise ValueError(
                f"position_qty_tol must be >= 0; got {self.position_qty_tol!r}."
            )
        if self.fill_price_bps_tol < 0.0:
            raise ValueError(
                f"fill_price_bps_tol must be >= 0; got {self.fill_price_bps_tol!r}."
            )
        if self.cash_abs_tol < 0.0:
            raise ValueError(
                f"cash_abs_tol must be >= 0; got {self.cash_abs_tol!r}."
            )
        if self.cash_rel_tol < 0.0:
            raise ValueError(
                f"cash_rel_tol must be >= 0; got {self.cash_rel_tol!r}."
            )
        if self.bps_scale <= 0.0:
            raise ValueError(
                f"bps_scale must be > 0; got {self.bps_scale!r}."
            )


# ---------------------------------------------------------------------------
# Position reconciliation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PositionRecord:
    """Reconciliation outcome for a single symbol's position.

    Attributes
    ----------
    symbol:
        Ticker or instrument identifier.
    internal_qty:
        Quantity held according to the internal book.  ``None`` when the
        symbol is only known to the broker.
    broker_qty:
        Quantity held according to the broker.  ``None`` when the symbol is
        only known internally.
    diff:
        ``broker_qty - internal_qty`` when both sides are present; ``None``
        when the symbol is one-sided.
    matched:
        ``True`` when both sides are present and ``abs(diff) <= position_qty_tol``.
    """

    symbol: str
    internal_qty: float | None
    broker_qty: float | None
    diff: float | None
    matched: bool


@dataclass(frozen=True, slots=True)
class PositionReconciliationResult:
    """Result of comparing internal and broker position snapshots.

    Attributes
    ----------
    records:
        Per-symbol reconciliation records, one per union of symbols.
    n_matched:
        Number of symbols where both sides agree within tolerance.
    n_mismatch:
        Number of symbols where both sides are present but disagree.
    n_internal_only:
        Number of symbols present in the internal book only.
    n_broker_only:
        Number of symbols present in the broker snapshot only.
    clean:
        ``True`` when ``n_mismatch == 0`` and no one-sided positions exist.
    incidents:
        Machine-readable incident strings (empty when ``clean`` is ``True``).
    """

    records: list[PositionRecord]
    n_matched: int
    n_mismatch: int
    n_internal_only: int
    n_broker_only: int
    clean: bool
    incidents: list[str]


def reconcile_positions(
    internal: dict[str, float],
    broker: dict[str, float],
    *,
    run_date: str = "",
    config: ReconciliationConfig | None = None,
) -> PositionReconciliationResult:
    """Compare internal vs broker position snapshots symbol by symbol.

    Parameters
    ----------
    internal:
        Mapping of symbol -> quantity from the internal book.
    broker:
        Mapping of symbol -> quantity from the broker snapshot.
    run_date:
        Date string prepended to incident messages (e.g. ``"2026-06-05"``).
        Pass an empty string when the date is embedded elsewhere.
    config:
        :class:`ReconciliationConfig`.  Defaults to ``ReconciliationConfig()``.

    Returns
    -------
    PositionReconciliationResult
        Per-symbol records plus aggregate counts and incident strings.
    """
    cfg = config if config is not None else ReconciliationConfig()

    all_symbols = sorted(set(internal) | set(broker))
    records: list[PositionRecord] = []
    incidents: list[str] = []
    n_matched = 0
    n_mismatch = 0
    n_internal_only = 0
    n_broker_only = 0

    for sym in all_symbols:
        has_internal = sym in internal
        has_broker = sym in broker

        if has_internal and has_broker:
            iqty = float(internal[sym])
            bqty = float(broker[sym])
            diff = bqty - iqty
            matched = abs(diff) <= cfg.position_qty_tol
            record = PositionRecord(
                symbol=sym,
                internal_qty=iqty,
                broker_qty=bqty,
                diff=diff,
                matched=matched,
            )
            if matched:
                n_matched += 1
            else:
                n_mismatch += 1
                prefix = f"{run_date}: " if run_date else ""
                incidents.append(
                    f"{prefix}position mismatch {sym}: "
                    f"internal={iqty}, broker={bqty}, diff={diff:+.4f}"
                )
        elif has_internal:
            n_internal_only += 1
            record = PositionRecord(
                symbol=sym,
                internal_qty=float(internal[sym]),
                broker_qty=None,
                diff=None,
                matched=False,
            )
            prefix = f"{run_date}: " if run_date else ""
            incidents.append(
                f"{prefix}position internal-only {sym}: "
                f"qty={internal[sym]}"
            )
        else:
            n_broker_only += 1
            record = PositionRecord(
                symbol=sym,
                internal_qty=None,
                broker_qty=float(broker[sym]),
                diff=None,
                matched=False,
            )
            prefix = f"{run_date}: " if run_date else ""
            incidents.append(
                f"{prefix}position broker-only {sym}: "
                f"qty={broker[sym]}"
            )
        records.append(record)

    clean = (n_mismatch == 0 and n_internal_only == 0 and n_broker_only == 0)

    return PositionReconciliationResult(
        records=records,
        n_matched=n_matched,
        n_mismatch=n_mismatch,
        n_internal_only=n_internal_only,
        n_broker_only=n_broker_only,
        clean=clean,
        incidents=incidents,
    )


# ---------------------------------------------------------------------------
# Fill reconciliation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FillMatchRecord:
    """Outcome for a single matched or unmatched fill pair.

    Attributes
    ----------
    internal_fill:
        The internal fill dict, or ``None`` when broker-only.
    broker_fill:
        The broker fill dict, or ``None`` when internal-only.
    match_key:
        The key used to establish the match: ``"order_id"`` when matched by
        order_id, ``"greedy"`` when matched by (symbol, side, quantity),
        ``"unmatched_internal"`` or ``"unmatched_broker"`` for one-sided.
    price_diff_bps:
        Absolute price difference in basis points (relative to internal fill
        price), or ``None`` for one-sided records.
    price_ok:
        ``True`` when ``price_diff_bps <= fill_price_bps_tol`` or when
        either side has no price (one-sided).
    """

    internal_fill: dict[str, Any] | None
    broker_fill: dict[str, Any] | None
    match_key: str
    price_diff_bps: float | None
    price_ok: bool


@dataclass(frozen=True, slots=True)
class FillReconciliationResult:
    """Result of matching internal and broker fill records for one day.

    Attributes
    ----------
    matches:
        All match records (paired + unmatched from both sides).
    n_matched:
        Number of fills matched (by order_id or greedy).
    n_price_discrepancy:
        Number of matched fills where price differs beyond bps tolerance.
    n_unmatched_internal:
        Number of internal fills with no broker counterpart.
    n_unmatched_broker:
        Number of broker fills with no internal counterpart.
    clean:
        ``True`` when no unmatched fills and no price discrepancies.
    incidents:
        Machine-readable incident strings.
    """

    matches: list[FillMatchRecord]
    n_matched: int
    n_price_discrepancy: int
    n_unmatched_internal: int
    n_unmatched_broker: int
    clean: bool
    incidents: list[str]


def _fill_price_bps(internal_fill: dict[str, Any], broker_fill: dict[str, Any],
                    bps_scale: float) -> float:
    """Return abs price diff in bps relative to internal price; 0 if prices missing."""
    ip = float(internal_fill.get("price", 0.0))
    bp = float(broker_fill.get("price", 0.0))
    if ip == 0.0:
        return 0.0
    return abs(bp - ip) / ip * bps_scale


def _fill_greedy_key(fill: dict[str, Any]) -> tuple[str, str, float]:
    """Return the (symbol, side, quantity) tuple for greedy matching."""
    return (
        str(fill.get("symbol", "")),
        str(fill.get("side", "")).upper(),
        float(fill.get("quantity", 0.0)),
    )


def reconcile_fills(
    internal_fills: list[dict[str, Any]],
    broker_fills: list[dict[str, Any]],
    *,
    run_date: str = "",
    config: ReconciliationConfig | None = None,
) -> FillReconciliationResult:
    """Match internal and broker fill records for one trading day.

    Matching is two-pass:

    1. **order_id pass** -- any fill with an ``order_id`` key on both sides
       that share the same value is matched first.
    2. **Greedy pass** -- remaining fills are matched by ``(symbol, side,
       quantity)``; the first available broker fill with the same key is
       consumed.

    Each fill dict must contain at least ``symbol``, ``side``, and
    ``quantity``.  An optional ``price`` key is used for price discrepancy
    checking.  An optional ``order_id`` key is used for the first-pass match.

    Parameters
    ----------
    internal_fills:
        Fill records from the internal ledger.
    broker_fills:
        Fill records from the broker execution report.
    run_date:
        Date string prepended to incident messages.
    config:
        :class:`ReconciliationConfig`.  Defaults to ``ReconciliationConfig()``.

    Returns
    -------
    FillReconciliationResult
        Matched pairs plus unmatched singles and price discrepancy flags.
    """
    cfg = config if config is not None else ReconciliationConfig()

    # Work with index-tagged copies so we can track consumption.
    broker_available: dict[int, dict[str, Any]] = {
        i: f for i, f in enumerate(broker_fills)
    }

    matches: list[FillMatchRecord] = []
    incidents: list[str] = []
    internal_consumed: set[int] = set()
    broker_consumed: set[int] = set()

    # --- Pass 1: match by order_id ---
    # Build index: order_id -> list of broker-fill indices
    broker_by_order: dict[str, list[int]] = {}
    for bi, bf in broker_available.items():
        oid = bf.get("order_id")
        if oid is not None:
            key = str(oid)
            broker_by_order.setdefault(key, []).append(bi)

    for ii, inf in enumerate(internal_fills):
        oid = inf.get("order_id")
        if oid is None:
            continue
        key = str(oid)
        candidates = [
            bi for bi in broker_by_order.get(key, [])
            if bi not in broker_consumed
        ]
        if not candidates:
            continue
        bi = candidates[0]
        bf = broker_available[bi]
        bps = _fill_price_bps(inf, bf, cfg.bps_scale)
        price_ok = bps <= cfg.fill_price_bps_tol
        matches.append(FillMatchRecord(
            internal_fill=inf,
            broker_fill=bf,
            match_key="order_id",
            price_diff_bps=bps,
            price_ok=price_ok,
        ))
        if not price_ok:
            prefix = f"{run_date}: " if run_date else ""
            incidents.append(
                f"{prefix}fill price discrepancy order_id={key} "
                f"sym={inf.get('symbol')} "
                f"internal_price={inf.get('price')} "
                f"broker_price={bf.get('price')} "
                f"diff_bps={bps:.2f}"
            )
        internal_consumed.add(ii)
        broker_consumed.add(bi)

    # --- Pass 2: greedy match by (symbol, side, quantity) ---
    # Build index of available broker fills keyed by greedy key.
    broker_by_greedy: dict[tuple[str, str, float], list[int]] = {}
    for bi, bf in broker_available.items():
        if bi in broker_consumed:
            continue
        gkey = _fill_greedy_key(bf)
        broker_by_greedy.setdefault(gkey, []).append(bi)

    for ii, inf in enumerate(internal_fills):
        if ii in internal_consumed:
            continue
        gkey = _fill_greedy_key(inf)
        candidates = [
            bi for bi in broker_by_greedy.get(gkey, [])
            if bi not in broker_consumed
        ]
        if not candidates:
            continue
        bi = candidates[0]
        bf = broker_available[bi]
        bps = _fill_price_bps(inf, bf, cfg.bps_scale)
        price_ok = bps <= cfg.fill_price_bps_tol
        matches.append(FillMatchRecord(
            internal_fill=inf,
            broker_fill=bf,
            match_key="greedy",
            price_diff_bps=bps,
            price_ok=price_ok,
        ))
        if not price_ok:
            prefix = f"{run_date}: " if run_date else ""
            incidents.append(
                f"{prefix}fill price discrepancy greedy "
                f"sym={inf.get('symbol')} side={inf.get('side')} "
                f"qty={inf.get('quantity')} "
                f"internal_price={inf.get('price')} "
                f"broker_price={bf.get('price')} "
                f"diff_bps={bps:.2f}"
            )
        internal_consumed.add(ii)
        broker_consumed.add(bi)

    # --- Collect unmatched ---
    n_price_discrepancy = sum(1 for m in matches if not m.price_ok)

    for ii, inf in enumerate(internal_fills):
        if ii not in internal_consumed:
            prefix = f"{run_date}: " if run_date else ""
            incidents.append(
                f"{prefix}fill unmatched internal "
                f"sym={inf.get('symbol')} side={inf.get('side')} "
                f"qty={inf.get('quantity')}"
            )
            matches.append(FillMatchRecord(
                internal_fill=inf,
                broker_fill=None,
                match_key="unmatched_internal",
                price_diff_bps=None,
                price_ok=True,
            ))

    for bi, bf in broker_available.items():
        if bi not in broker_consumed:
            prefix = f"{run_date}: " if run_date else ""
            incidents.append(
                f"{prefix}fill unmatched broker "
                f"sym={bf.get('symbol')} side={bf.get('side')} "
                f"qty={bf.get('quantity')}"
            )
            matches.append(FillMatchRecord(
                internal_fill=None,
                broker_fill=bf,
                match_key="unmatched_broker",
                price_diff_bps=None,
                price_ok=True,
            ))

    n_matched = len(internal_consumed)
    n_unmatched_internal = sum(
        1 for m in matches if m.match_key == "unmatched_internal"
    )
    n_unmatched_broker = sum(
        1 for m in matches if m.match_key == "unmatched_broker"
    )
    clean = (
        n_unmatched_internal == 0
        and n_unmatched_broker == 0
        and n_price_discrepancy == 0
    )

    return FillReconciliationResult(
        matches=matches,
        n_matched=n_matched,
        n_price_discrepancy=n_price_discrepancy,
        n_unmatched_internal=n_unmatched_internal,
        n_unmatched_broker=n_unmatched_broker,
        clean=clean,
        incidents=incidents,
    )


# ---------------------------------------------------------------------------
# Cash reconciliation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CashReconciliationResult:
    """Result of comparing internal and broker cash balances.

    Attributes
    ----------
    internal_cash:
        Cash balance from the internal ledger.
    broker_cash:
        Cash balance from the broker account snapshot.
    diff:
        ``broker_cash - internal_cash``.
    diff_abs:
        ``abs(diff)``.
    diff_rel:
        ``diff_abs / max(abs(internal_cash), abs(broker_cash))`` when the
        denominator is non-zero; ``0.0`` otherwise.
    clean:
        ``True`` when ``diff_abs <= max(cash_abs_tol, cash_rel_tol *
        max(abs(internal_cash), abs(broker_cash)))``.
    incidents:
        Machine-readable incident strings (empty when ``clean``).
    """

    internal_cash: float
    broker_cash: float
    diff: float
    diff_abs: float
    diff_rel: float
    clean: bool
    incidents: list[str]


def reconcile_cash(
    internal_cash: float,
    broker_cash: float,
    *,
    run_date: str = "",
    config: ReconciliationConfig | None = None,
) -> CashReconciliationResult:
    """Compare internal and broker cash balances within configured tolerances.

    Parameters
    ----------
    internal_cash:
        Cash balance from the internal ledger.
    broker_cash:
        Cash balance from the broker account snapshot.
    run_date:
        Date string prepended to incident messages.
    config:
        :class:`ReconciliationConfig`.  Defaults to ``ReconciliationConfig()``.

    Returns
    -------
    CashReconciliationResult
        Difference metrics and clean/mismatch verdict with incident strings.
    """
    cfg = config if config is not None else ReconciliationConfig()

    diff = broker_cash - internal_cash
    diff_abs = abs(diff)
    denom = max(abs(internal_cash), abs(broker_cash))
    diff_rel = diff_abs / denom if denom > 0.0 else 0.0

    tolerance = max(cfg.cash_abs_tol, cfg.cash_rel_tol * denom)
    clean = diff_abs <= tolerance

    incidents: list[str] = []
    if not clean:
        prefix = f"{run_date}: " if run_date else ""
        incidents.append(
            f"{prefix}cash mismatch: "
            f"internal={internal_cash:.4f} broker={broker_cash:.4f} "
            f"diff={diff:+.4f} diff_rel={diff_rel:.2e}"
        )

    return CashReconciliationResult(
        internal_cash=internal_cash,
        broker_cash=broker_cash,
        diff=diff,
        diff_abs=diff_abs,
        diff_rel=diff_rel,
        clean=clean,
        incidents=incidents,
    )


# ---------------------------------------------------------------------------
# Overall reconciliation report
# ---------------------------------------------------------------------------


class ReconciliationStatus:
    """String constants for the overall reconciliation verdict."""

    CLEAN = "CLEAN"
    MISMATCH = "MISMATCH"


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    """Top-level reconciliation report combining all three sections.

    Attributes
    ----------
    position:
        Result of position reconciliation (or ``None`` if not performed).
    fills:
        Result of fill reconciliation (or ``None`` if not performed).
    cash:
        Result of cash reconciliation (or ``None`` if not performed).
    status:
        Overall verdict: ``ReconciliationStatus.CLEAN`` when all sections
        that were run are clean, ``ReconciliationStatus.MISMATCH`` otherwise.
    all_incidents:
        Flat list of all incident strings from all sections, in section order
        (positions first, then fills, then cash).  Empty when ``status`` is
        ``CLEAN``.
    generated_at:
        UTC timestamp string embedded in the report.
    """

    position: PositionReconciliationResult | None
    fills: FillReconciliationResult | None
    cash: CashReconciliationResult | None
    status: str
    all_incidents: list[str]
    generated_at: str


def build_reconciliation_report(
    *,
    position_result: PositionReconciliationResult | None = None,
    fill_result: FillReconciliationResult | None = None,
    cash_result: CashReconciliationResult | None = None,
    generated_at: str = "",
) -> ReconciliationReport:
    """Assemble a :class:`ReconciliationReport` from individual section results.

    Parameters
    ----------
    position_result:
        Output of :func:`reconcile_positions`, or ``None`` to skip.
    fill_result:
        Output of :func:`reconcile_fills`, or ``None`` to skip.
    cash_result:
        Output of :func:`reconcile_cash`, or ``None`` to skip.
    generated_at:
        UTC timestamp string embedded in the report header.

    Returns
    -------
    ReconciliationReport
        Aggregated report with overall CLEAN / MISMATCH verdict.
    """
    all_incidents: list[str] = []
    section_clean: list[bool] = []

    if position_result is not None:
        all_incidents.extend(position_result.incidents)
        section_clean.append(position_result.clean)

    if fill_result is not None:
        all_incidents.extend(fill_result.incidents)
        section_clean.append(fill_result.clean)

    if cash_result is not None:
        all_incidents.extend(cash_result.incidents)
        section_clean.append(cash_result.clean)

    overall_clean = all(section_clean) if section_clean else True
    status = ReconciliationStatus.CLEAN if overall_clean else ReconciliationStatus.MISMATCH

    return ReconciliationReport(
        position=position_result,
        fills=fill_result,
        cash=cash_result,
        status=status,
        all_incidents=all_incidents,
        generated_at=generated_at,
    )


# ---------------------------------------------------------------------------
# Wash-sale tracking (Phase 12.6)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SaleEvent:
    """A realised-loss sale event for wash-sale analysis.

    Attributes
    ----------
    symbol:
        Ticker or instrument identifier.
    date:
        Settlement or execution date of the sale.
    quantity:
        Number of shares/units sold (must be > 0).
    loss_amount:
        Realised loss from the sale (must be > 0; this is the magnitude of
        the loss, i.e. ``cost_basis - proceeds``).  Sales with ``loss_amount
        <= 0`` are not subject to the wash-sale rule and should not be passed
        to :func:`flag_wash_sales`.
    """

    symbol: str
    date: _date
    quantity: float
    loss_amount: float


@dataclass(frozen=True, slots=True)
class BuyEvent:
    """A buy (replacement purchase) event for wash-sale analysis.

    Attributes
    ----------
    symbol:
        Ticker or instrument identifier.
    date:
        Settlement or execution date of the purchase.
    quantity:
        Number of shares/units purchased (must be > 0).
    """

    symbol: str
    date: _date
    quantity: float


@dataclass(frozen=True, slots=True)
class WashSaleFlag:
    """A single detected wash-sale pairing.

    Attributes
    ----------
    sale:
        The triggering loss sale event.
    buy:
        The replacement purchase that triggered the wash-sale rule.
    replacement_ratio:
        ``min(buy.quantity, sale.quantity) / sale.quantity``, capped at 1.0.
        This is the fraction of the sold position replaced.
    disallowed_loss:
        ``loss_amount * replacement_ratio`` -- the portion of the realised
        loss that is disallowed under the wash-sale rule.
    days_apart:
        Signed calendar days from ``sale.date`` to ``buy.date``; negative
        means the buy preceded the sale (pre-sale replacement).
    note:
        Human-readable description of the pairing, including the 30-day
        window direction.
    """

    sale: SaleEvent
    buy: BuyEvent
    replacement_ratio: float
    disallowed_loss: float
    days_apart: int
    note: str


@dataclass(frozen=True, slots=True)
class WashSaleReport:
    """Summary of all detected wash-sale pairings for a set of events.

    Attributes
    ----------
    flags:
        All detected wash-sale :class:`WashSaleFlag` records, sorted by
        sale date then symbol.
    total_disallowed_loss:
        Sum of all ``flag.disallowed_loss`` values.
    n_sales_affected:
        Number of distinct loss sale events that triggered at least one
        wash-sale flag.
    disclaimer:
        Informational disclaimer string embedded in the report.
    """

    flags: list[WashSaleFlag]
    total_disallowed_loss: float
    n_sales_affected: int
    disclaimer: str = field(default=(
        "INFORMATIONAL PERSONAL-RECORDS TOOLING ONLY -- NOT TAX ADVICE.  "
        "Consult a qualified tax professional for all tax-related decisions."
    ))


_WASH_SALE_WINDOW_DAYS = 30  # 30 days before + 30 days after = 61-day window


def flag_wash_sales(
    sales: list[SaleEvent],
    buys: list[BuyEvent],
) -> WashSaleReport:
    """Flag wash sales under the IRS 30-day before/after replacement rule.

    The wash-sale rule disallows a realised loss when the taxpayer purchases
    the *substantially identical* security within 30 calendar days before or
    after the sale date (a 61-day window inclusive of the sale date itself).
    When only a portion of the sold shares are replaced, the disallowed loss
    is proportional: ``disallowed = loss * (replacement_qty / sold_qty)``,
    capped at the full loss.

    **This function is informational personal-records tooling only.  It is
    not tax advice.  The IRS rules are complex and include provisions for
    substantially identical securities, short positions, options, and other
    instruments that this function does not cover.  Consult a qualified tax
    professional for all tax-related decisions.**

    Algorithm
    ---------
    For each loss sale (sorted by date ascending), find all buy events for
    the same symbol within the 61-day window ``[sale.date - 30, sale.date +
    30]``.  Buys are consumed greedily (earliest first) against the sold
    quantity; each buy that partially or fully replaces the sold shares
    generates one :class:`WashSaleFlag`.

    Parameters
    ----------
    sales:
        Realised-loss sale events.  Only sales with ``loss_amount > 0``
        contribute wash-sale flags; zero-loss sales are skipped silently.
    buys:
        Purchase events to test as potential replacements.  Multiple buys
        for the same symbol within the window may collectively trigger the
        rule.

    Returns
    -------
    WashSaleReport
        All detected flags, total disallowed loss, and count of affected sales.
    """
    flags: list[WashSaleFlag] = []
    affected_sale_ids: set[int] = set()  # index into sorted sales

    # Sort sales by date ascending for deterministic processing order.
    sorted_sales = sorted(enumerate(sales), key=lambda x: (x[1].date, x[1].symbol))

    # Pre-group buys by symbol; sort by date ascending so greedy consumption
    # is chronological (earliest replacement buy consumed first).
    buys_by_symbol: dict[str, list[BuyEvent]] = {}
    for b in buys:
        buys_by_symbol.setdefault(b.symbol, []).append(b)
    for sym_buys in buys_by_symbol.values():
        sym_buys.sort(key=lambda b: b.date)

    # Track remaining available quantity for each buy to allow partial matches.
    # Key: (symbol, date, index-within-sorted-group) -> remaining qty
    buy_remaining: dict[tuple[str, _date, int], float] = {}
    for sym, sym_buys in buys_by_symbol.items():
        for idx, b in enumerate(sym_buys):
            buy_remaining[(sym, b.date, idx)] = b.quantity

    for sale_idx, sale in sorted_sales:
        if sale.loss_amount <= 0.0:
            continue
        if sale.quantity <= 0.0:
            continue

        window_start = sale.date - timedelta(days=_WASH_SALE_WINDOW_DAYS)
        window_end = sale.date + timedelta(days=_WASH_SALE_WINDOW_DAYS)

        # Find buy events for this symbol within the wash-sale window.
        sym_buys = buys_by_symbol.get(sale.symbol, [])
        remaining_sold = sale.quantity

        for bidx, buy in enumerate(sym_buys):
            if buy.date < window_start or buy.date > window_end:
                continue

            bkey = (sale.symbol, buy.date, bidx)
            avail = buy_remaining.get(bkey, 0.0)
            if avail <= 0.0:
                continue

            # How much of this buy covers the remaining sold quantity?
            matched = min(avail, remaining_sold)
            if matched <= 0.0:
                continue

            replacement_ratio = min(matched / sale.quantity, 1.0)
            disallowed = sale.loss_amount * replacement_ratio
            days_apart = (buy.date - sale.date).days

            if days_apart < 0:
                direction = f"{abs(days_apart)} days before"
            elif days_apart == 0:
                direction = "same day"
            else:
                direction = f"{days_apart} days after"

            note = (
                f"wash sale {sale.symbol}: sale {sale.date} buy {buy.date} "
                f"({direction}); replaced {matched:.2f}/{sale.quantity:.2f} "
                f"shares; disallowed loss {disallowed:.4f}"
            )

            flags.append(WashSaleFlag(
                sale=sale,
                buy=buy,
                replacement_ratio=replacement_ratio,
                disallowed_loss=disallowed,
                days_apart=days_apart,
                note=note,
            ))

            buy_remaining[bkey] = avail - matched
            remaining_sold -= matched
            affected_sale_ids.add(sale_idx)

            if remaining_sold <= 0.0:
                break

    # Sort output by sale date then symbol for deterministic reporting.
    flags.sort(key=lambda f: (f.sale.date, f.sale.symbol))

    total_disallowed = sum(f.disallowed_loss for f in flags)

    return WashSaleReport(
        flags=flags,
        total_disallowed_loss=total_disallowed,
        n_sales_affected=len(affected_sale_ids),
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _fmt_float(value: float, decimals: int = 4) -> str:
    """Format a float for ASCII tables; handles inf and nan."""
    if value != value:  # NaN
        return "n/a"
    if value == float("inf"):
        return "+inf"
    if value == float("-inf"):
        return "-inf"
    return f"{value:.{decimals}f}"


def _fmt_opt_float(value: float | None, decimals: int = 4) -> str:
    """Format an optional float; returns 'n/a' for None."""
    if value is None:
        return "n/a"
    return _fmt_float(value, decimals)


# ---------------------------------------------------------------------------
# ASCII renderer
# ---------------------------------------------------------------------------


def render_reconciliation_report(
    report: ReconciliationReport,
    wash_report: WashSaleReport | None = None,
    *,
    config: ReconciliationConfig | None = None,
) -> str:
    """Render the reconciliation report and optional wash-sale report as ASCII.

    All output is 7-bit ASCII (``ord < 128``), suitable for terminal portability
    consoles, ops email bodies, and log files.

    Parameters
    ----------
    report:
        Assembled :class:`ReconciliationReport`.
    wash_report:
        Optional :class:`WashSaleReport` from :func:`flag_wash_sales`; pass
        ``None`` to skip the wash-sale section.
    config:
        :class:`ReconciliationConfig` for display parameters.  Defaults to
        ``ReconciliationConfig()``.

    Returns
    -------
    str
        ASCII-only multi-line report string.
    """
    _ = config  # reserved for future display parameters
    lines: list[str] = []

    lines.append("# Daily Reconciliation Report")
    lines.append("")
    lines.append(f"Generated : {report.generated_at}")
    lines.append(f"Status    : {report.status}")
    lines.append("")

    # ----- Section 1: Positions -----
    lines.append("## 1. Position Reconciliation")
    lines.append("")
    pos = report.position
    if pos is None:
        lines.append("Not available: no position reconciliation result supplied.")
    else:
        clean_str = "CLEAN" if pos.clean else "MISMATCH"
        lines.append(f"Verdict          : {clean_str}")
        lines.append(f"Matched          : {pos.n_matched}")
        lines.append(f"Mismatch         : {pos.n_mismatch}")
        lines.append(f"Internal-only    : {pos.n_internal_only}")
        lines.append(f"Broker-only      : {pos.n_broker_only}")
        lines.append("")
        if pos.records:
            w_sym = max(len(r.symbol) for r in pos.records) + 2
            w_sym = max(w_sym, 10)
            w_q = 14
            header = (
                f"| {'Symbol':<{w_sym}} "
                f"| {'Internal Qty':<{w_q}} "
                f"| {'Broker Qty':<{w_q}} "
                f"| {'Diff':<{w_q}} "
                f"| {'Match':<8} |"
            )
            divider = (
                f"|{'-' * (w_sym + 2)}"
                f"|{'-' * (w_q + 2)}"
                f"|{'-' * (w_q + 2)}"
                f"|{'-' * (w_q + 2)}"
                f"|{'-' * 10}|"
            )
            lines.append(header)
            lines.append(divider)
            for rec in pos.records:
                match_str = "OK" if rec.matched else "MISMATCH"
                row = (
                    f"| {rec.symbol:<{w_sym}} "
                    f"| {_fmt_opt_float(rec.internal_qty, 2):<{w_q}} "
                    f"| {_fmt_opt_float(rec.broker_qty, 2):<{w_q}} "
                    f"| {_fmt_opt_float(rec.diff, 4):<{w_q}} "
                    f"| {match_str:<8} |"
                )
                lines.append(row)
        lines.append("")

    # ----- Section 2: Fills -----
    lines.append("## 2. Fill Reconciliation")
    lines.append("")
    fll = report.fills
    if fll is None:
        lines.append("Not available: no fill reconciliation result supplied.")
    else:
        clean_str = "CLEAN" if fll.clean else "MISMATCH"
        lines.append(f"Verdict              : {clean_str}")
        lines.append(f"Matched fills        : {fll.n_matched}")
        lines.append(f"Price discrepancies  : {fll.n_price_discrepancy}")
        lines.append(f"Unmatched internal   : {fll.n_unmatched_internal}")
        lines.append(f"Unmatched broker     : {fll.n_unmatched_broker}")
        lines.append("")
        matched_records = [
            m for m in fll.matches
            if m.match_key in ("order_id", "greedy")
        ]
        if matched_records:
            lines.append("### Matched Fills")
            lines.append("")
            w_k = 12
            w_s = 10
            w_q = 10
            w_p = 12
            w_bps = 12
            header = (
                f"| {'MatchKey':<{w_k}} "
                f"| {'Symbol':<{w_s}} "
                f"| {'Qty':<{w_q}} "
                f"| {'Int Price':<{w_p}} "
                f"| {'Brk Price':<{w_p}} "
                f"| {'Diff bps':<{w_bps}} "
                f"| {'PriceOK':<8} |"
            )
            divider = (
                f"|{'-' * (w_k + 2)}"
                f"|{'-' * (w_s + 2)}"
                f"|{'-' * (w_q + 2)}"
                f"|{'-' * (w_p + 2)}"
                f"|{'-' * (w_p + 2)}"
                f"|{'-' * (w_bps + 2)}"
                f"|{'-' * 10}|"
            )
            lines.append(header)
            lines.append(divider)
            for m in matched_records:
                inf = m.internal_fill or {}
                bkf = m.broker_fill or {}
                sym = str(inf.get("symbol", bkf.get("symbol", "")))
                qty = _fmt_opt_float(
                    float(inf["quantity"]) if "quantity" in inf else None, 2
                )
                ip = _fmt_opt_float(
                    float(inf["price"]) if "price" in inf else None, 4
                )
                bp = _fmt_opt_float(
                    float(bkf["price"]) if "price" in bkf else None, 4
                )
                bps_str = _fmt_opt_float(m.price_diff_bps, 2)
                ok_str = "OK" if m.price_ok else "MISMATCH"
                row = (
                    f"| {m.match_key:<{w_k}} "
                    f"| {sym:<{w_s}} "
                    f"| {qty:<{w_q}} "
                    f"| {ip:<{w_p}} "
                    f"| {bp:<{w_p}} "
                    f"| {bps_str:<{w_bps}} "
                    f"| {ok_str:<8} |"
                )
                lines.append(row)
        lines.append("")

    # ----- Section 3: Cash -----
    lines.append("## 3. Cash Reconciliation")
    lines.append("")
    csh = report.cash
    if csh is None:
        lines.append("Not available: no cash reconciliation result supplied.")
    else:
        clean_str = "CLEAN" if csh.clean else "MISMATCH"
        lines.append(f"Verdict          : {clean_str}")
        lines.append(f"Internal cash    : {_fmt_float(csh.internal_cash, 2)}")
        lines.append(f"Broker cash      : {_fmt_float(csh.broker_cash, 2)}")
        lines.append(f"Diff             : {_fmt_float(csh.diff, 4)}")
        lines.append(f"Diff (relative)  : {csh.diff_rel:.2e}")
        lines.append("")

    # ----- Section 4: Incidents -----
    lines.append("## 4. Incidents")
    lines.append("")
    if not report.all_incidents:
        lines.append("No incidents.")
    else:
        for inc in report.all_incidents:
            lines.append(f"  - {inc}")
    lines.append("")

    # ----- Section 5: Wash-Sale Tracking -----
    lines.append("## 5. Wash-Sale Tracking (Informational)")
    lines.append("")
    if wash_report is None:
        lines.append("Not available: no wash-sale report supplied.")
    else:
        lines.append(f"DISCLAIMER: {wash_report.disclaimer}")
        lines.append("")
        lines.append(f"Sales affected       : {wash_report.n_sales_affected}")
        lines.append(
            f"Total disallowed loss: {_fmt_float(wash_report.total_disallowed_loss, 4)}"
        )
        lines.append("")
        if wash_report.flags:
            lines.append("### Wash-Sale Flags")
            lines.append("")
            w_sym = max(len(f.sale.symbol) for f in wash_report.flags) + 2
            w_sym = max(w_sym, 10)
            w_d = 12
            w_q = 10
            w_r = 10
            w_dl = 14
            w_da = 10
            header = (
                f"| {'Symbol':<{w_sym}} "
                f"| {'Sale Date':<{w_d}} "
                f"| {'Buy Date':<{w_d}} "
                f"| {'Sold Qty':<{w_q}} "
                f"| {'Ratio':<{w_r}} "
                f"| {'Disallowed':<{w_dl}} "
                f"| {'Days Apart':<{w_da}} |"
            )
            divider = (
                f"|{'-' * (w_sym + 2)}"
                f"|{'-' * (w_d + 2)}"
                f"|{'-' * (w_d + 2)}"
                f"|{'-' * (w_q + 2)}"
                f"|{'-' * (w_r + 2)}"
                f"|{'-' * (w_dl + 2)}"
                f"|{'-' * (w_da + 2)}|"
            )
            lines.append(header)
            lines.append(divider)
            for fl in wash_report.flags:
                row = (
                    f"| {fl.sale.symbol:<{w_sym}} "
                    f"| {str(fl.sale.date):<{w_d}} "
                    f"| {str(fl.buy.date):<{w_d}} "
                    f"| {_fmt_float(fl.sale.quantity, 2):<{w_q}} "
                    f"| {_fmt_float(fl.replacement_ratio, 4):<{w_r}} "
                    f"| {_fmt_float(fl.disallowed_loss, 4):<{w_dl}} "
                    f"| {fl.days_apart:<{w_da}} |"
                )
                lines.append(row)
        else:
            lines.append("No wash-sale flags detected.")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Demo synthetic data builder
# ---------------------------------------------------------------------------


def _build_demo_data() -> dict[str, Any]:
    """Build two scenarios -- CLEAN and MISMATCH -- for the CLI demo.

    Returns
    -------
    dict
        Keys: ``clean``, ``mismatch`` -- each is a dict of inputs for
        :func:`build_reconciliation_report`.
    """
    # ---- CLEAN scenario ----
    clean_internal_pos = {"AAPL": 100.0, "MSFT": 50.0, "SPY": 200.0}
    clean_broker_pos = {"AAPL": 100.0, "MSFT": 50.0, "SPY": 200.0}

    clean_int_fills = [
        {"symbol": "AAPL", "side": "BUY", "quantity": 10.0, "price": 182.50,
         "order_id": "ORD-001"},
        {"symbol": "MSFT", "side": "SELL", "quantity": 5.0, "price": 415.20,
         "order_id": "ORD-002"},
    ]
    clean_brk_fills = [
        # 0.44 bps diff -- within 0.5 bps default tolerance
        {"symbol": "AAPL", "side": "BUY", "quantity": 10.0, "price": 182.508,
         "order_id": "ORD-001"},
        {"symbol": "MSFT", "side": "SELL", "quantity": 5.0, "price": 415.19,
         "order_id": "ORD-002"},
    ]

    clean_int_cash = 50_000.00
    clean_brk_cash = 50_000.00

    # ---- MISMATCH scenario ----
    mismatch_internal_pos = {"AAPL": 100.0, "MSFT": 50.0, "SPY": 200.0, "GLD": 30.0}
    mismatch_broker_pos = {"AAPL": 95.0, "MSFT": 50.0, "QQQ": 10.0}

    mismatch_int_fills = [
        {"symbol": "AAPL", "side": "BUY", "quantity": 20.0, "price": 182.50,
         "order_id": "ORD-010"},
        {"symbol": "MSFT", "side": "BUY", "quantity": 3.0, "price": 415.00},
        {"symbol": "GLD", "side": "SELL", "quantity": 5.0, "price": 190.00},
    ]
    mismatch_brk_fills = [
        {"symbol": "AAPL", "side": "BUY", "quantity": 20.0, "price": 185.00,
         "order_id": "ORD-010"},
        # MSFT fill missing from broker
        # Extra broker fill not in internal
        {"symbol": "SPY", "side": "BUY", "quantity": 8.0, "price": 530.00},
    ]

    mismatch_int_cash = 50_000.00
    mismatch_brk_cash = 49_750.33

    # ---- Wash-sale demo data ----
    from datetime import date as _d
    wash_sales = [
        SaleEvent(symbol="AAPL", date=_d(2026, 1, 10), quantity=100.0,
                  loss_amount=450.00),
        SaleEvent(symbol="MSFT", date=_d(2026, 1, 15), quantity=50.0,
                  loss_amount=200.00),
        # Zero-loss sale -- should not flag
        SaleEvent(symbol="SPY", date=_d(2026, 1, 20), quantity=20.0,
                  loss_amount=0.0),
    ]
    wash_buys = [
        # AAPL repurchased 5 days after sale (within 30-day window)
        BuyEvent(symbol="AAPL", date=_d(2026, 1, 15), quantity=80.0),
        # MSFT repurchased 35 days after sale (outside window)
        BuyEvent(symbol="MSFT", date=_d(2026, 2, 19), quantity=50.0),
        # AAPL bought 25 days before sale (within pre-sale window)
        BuyEvent(symbol="AAPL", date=_d(2025, 12, 16), quantity=30.0),
    ]

    return {
        "clean": {
            "internal_pos": clean_internal_pos,
            "broker_pos": clean_broker_pos,
            "int_fills": clean_int_fills,
            "brk_fills": clean_brk_fills,
            "int_cash": clean_int_cash,
            "brk_cash": clean_brk_cash,
        },
        "mismatch": {
            "internal_pos": mismatch_internal_pos,
            "broker_pos": mismatch_broker_pos,
            "int_fills": mismatch_int_fills,
            "brk_fills": mismatch_brk_fills,
            "int_cash": mismatch_int_cash,
            "brk_cash": mismatch_brk_cash,
        },
        "wash_sales": wash_sales,
        "wash_buys": wash_buys,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """Parse args and run the reconciliation report generator.

    Parameters
    ----------
    argv:
        Argument list (``sys.argv[1:]`` when ``None``).  Testable without a
        subprocess by passing a list directly.
    """
    parser = argparse.ArgumentParser(
        prog="python -m core_trading.ops.reconciliation",
        description=(
            "Daily broker-vs-internal reconciliation report generator.  "
            "Use --demo to run on seeded synthetic data."
        ),
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run on seeded synthetic data (no live data needed).",
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        default=None,
        help="Write the report to this file path.",
    )
    args = parser.parse_args(argv)

    if not args.demo:
        parser.error(
            "--demo is required (wiring live broker state into the CLI "
            "is a later operational concern; see module docstring)."
        )

    demo = _build_demo_data()
    full_report_lines: list[str] = []

    for scenario_name, scenario in (
        ("CLEAN SCENARIO", demo["clean"]),
        ("MISMATCH SCENARIO", demo["mismatch"]),
    ):
        run_date = "2026-06-05"
        cfg = ReconciliationConfig(generated_at=f"{run_date}T16:00:00Z")

        pos_result = reconcile_positions(
            scenario["internal_pos"],
            scenario["broker_pos"],
            run_date=run_date,
            config=cfg,
        )
        fill_result = reconcile_fills(
            scenario["int_fills"],
            scenario["brk_fills"],
            run_date=run_date,
            config=cfg,
        )
        cash_result = reconcile_cash(
            scenario["int_cash"],
            scenario["brk_cash"],
            run_date=run_date,
            config=cfg,
        )
        report = build_reconciliation_report(
            position_result=pos_result,
            fill_result=fill_result,
            cash_result=cash_result,
            generated_at=cfg.generated_at or run_date,
        )

        full_report_lines.append(f"{'=' * 60}")
        full_report_lines.append(f"  {scenario_name}")
        full_report_lines.append(f"{'=' * 60}")
        full_report_lines.append("")
        full_report_lines.append(
            render_reconciliation_report(report, config=cfg)
        )

    # Wash-sale section -- shown once after both scenarios
    wash_report = flag_wash_sales(demo["wash_sales"], demo["wash_buys"])
    # Build a minimal report shell to reuse the renderer's section 5
    ws_position = reconcile_positions({}, {}, config=ReconciliationConfig())
    ws_fill = reconcile_fills([], [], config=ReconciliationConfig())
    ws_cash = reconcile_cash(0.0, 0.0, config=ReconciliationConfig())
    ws_outer = build_reconciliation_report(
        position_result=ws_position,
        fill_result=ws_fill,
        cash_result=ws_cash,
        generated_at="2026-06-05T16:00:00Z",
    )
    full_report_lines.append(f"{'=' * 60}")
    full_report_lines.append("  WASH-SALE TRACKING DEMO")
    full_report_lines.append(f"{'=' * 60}")
    full_report_lines.append("")
    full_report_lines.append(
        render_reconciliation_report(
            ws_outer,
            wash_report=wash_report,
            config=ReconciliationConfig(generated_at="2026-06-05T16:00:00Z"),
        )
    )

    output = "\n".join(full_report_lines)
    print(output)

    if args.output is not None:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(output)
        print(f"[reconciliation] Report written to {args.output}")


if __name__ == "__main__":  # pragma: no cover - exercised via main() in tests
    main(sys.argv[1:])
