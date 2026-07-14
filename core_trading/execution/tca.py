"""Transaction Cost Analysis (TCA) -- master plan Phase 9.4.

This module is a *pure analytics generator*: it takes a frame of executed
fills (plus optional reference price series) and produces side-signed cost
metrics under the **positive-loss convention** used repo-wide -- a positive
number is a *cost* to the trader, a negative number is *price improvement*.

Metrics implemented
-------------------
* **Arrival-price slippage** -- ``(avg_fill - arrival) / arrival`` made
  side-signed so a buy filled *above* its arrival price (or a sell filled
  *below*) is reported as a positive cost.
* **VWAP slippage** -- average fill vs the interval VWAP over the order's
  active window, side-signed identically.
* **Implementation shortfall (Perold 1988)** -- the full "paper vs real"
  portfolio gap relative to the *decision* price, including the opportunity
  cost of any unfilled quantity (a paper return on the part that never
  executed).
* **Markout analysis** -- post-fill price drift at horizons 1s, 10s, 1m, 5m,
  1h and EOD, side-signed so a *positive* markout means the price moved
  *against* us after the fill (evidence of adverse selection; see
  :mod:`core_trading.execution.adverse_selection`).
* **Cost attribution** -- decompose the realised implementation shortfall
  into spread, impact, timing and opportunity components plus explicit fees.
  The four components and fees sum *exactly* to the total implementation
  shortfall (the decomposition identity, pinned by test).

The :func:`build_daily_tca_report` / :func:`render_report` / :func:`main`
trio mirrors :mod:`core_trading.risk.daily_report`: a pure builder, an
ASCII-only markdown renderer, and a ``--demo`` CLI smoke entry point.

CLI entry point
---------------
``python -m core_trading.execution.tca --demo``
    Build and print a TCA report from a seeded synthetic fills frame.

``python -m core_trading.execution.tca --demo --output <path>``
    Same, also writing the markdown to ``<path>``.

References
----------
Perold, A. F. (1988). "The Implementation Shortfall: Paper Versus Reality."
    *Journal of Portfolio Management*, 14(3), 4-9.
Kissell, R. (2013). *The Science of Algorithmic Trading and Portfolio
    Management*. Academic Press. (Cost attribution, markout analysis.)
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

__all__ = [
    "TCAConfig",
    "FillTCA",
    "DailyTCAReport",
    "REQUIRED_FILL_COLUMNS",
    "arrival_slippage_bps",
    "vwap_slippage_bps",
    "implementation_shortfall",
    "attribute_cost",
    "markouts",
    "compute_fill_tca",
    "build_daily_tca_report",
    "render_report",
    "main",
]

# ---------------------------------------------------------------------------
# Input contract
# ---------------------------------------------------------------------------

#: Columns a fills DataFrame must contain for :func:`build_daily_tca_report`.
#:
#: ============== =========================================================
#: column         meaning
#: ============== =========================================================
#: order_id       unique parent-order identifier (str)
#: symbol         instrument symbol (str)
#: side           ``"buy"`` or ``"sell"`` (case-insensitive)
#: quantity       *intended* order quantity (shares/units, > 0)
#: filled_quantity executed quantity (>= 0, <= quantity)
#: decision_price price at the moment the trade decision was made
#: arrival_price  prevailing price when the order reached the market
#: avg_fill_price quantity-weighted average execution price
#: mid_at_fill    mid price at the time of (last) fill
#: half_spread    half the quoted bid-ask spread at fill (price units, >= 0)
#: fill_time      timestamp of the (last) fill (pd.Timestamp)
#: close_price    reference close used for the unfilled opportunity cost
#: fees           explicit commissions/fees for the order (USD, >= 0)
#: ============== =========================================================
REQUIRED_FILL_COLUMNS: tuple[str, ...] = (
    "order_id",
    "symbol",
    "side",
    "quantity",
    "filled_quantity",
    "decision_price",
    "arrival_price",
    "avg_fill_price",
    "mid_at_fill",
    "half_spread",
    "fill_time",
    "close_price",
    "fees",
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TCAConfig:
    """Immutable configuration for the TCA toolkit.

    Attributes
    ----------
    horizons:
        Ordered ``(label, seconds)`` pairs at which markouts are measured.
        ``seconds`` may be ``None`` to denote the end-of-day (EOD) horizon,
        which is aligned to the *last* available price on the fill's calendar
        day rather than a fixed offset.  The default set is the master-plan
        canonical ladder ``1s, 10s, 1m, 5m, 1h, EOD``.
    bps_scale:
        Multiplier converting a fractional return into basis points.
        ``1e4`` by convention (1 bp = 1e-4); exposed for testing only.
    worst_n:
        Number of worst (highest-cost) fills retained per the report's
        ``worst_fills`` table.
    """

    horizons: tuple[tuple[str, float | None], ...] = (
        ("1s", 1.0),
        ("10s", 10.0),
        ("1m", 60.0),
        ("5m", 300.0),
        ("1h", 3600.0),
        ("EOD", None),
    )
    bps_scale: float = 1e4
    worst_n: int = 5

    def __post_init__(self) -> None:
        if not self.horizons:
            raise ValueError("horizons must be non-empty.")
        labels = [h[0] for h in self.horizons]
        if len(labels) != len(set(labels)):
            raise ValueError(f"horizon labels must be unique; got {labels!r}.")
        for label, secs in self.horizons:
            if secs is not None and secs <= 0.0:
                raise ValueError(
                    f"horizon {label!r} seconds must be positive or None; got {secs!r}."
                )
        if self.bps_scale <= 0.0:
            raise ValueError(f"bps_scale must be positive; got {self.bps_scale!r}.")
        if self.worst_n < 1:
            raise ValueError(f"worst_n must be >= 1; got {self.worst_n!r}.")


_DEFAULT_TCA_CONFIG = TCAConfig()


# ---------------------------------------------------------------------------
# Result DTOs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FillTCA:
    """Per-order TCA metrics.

    All ``*_bps`` fields are side-signed under the positive-loss convention
    (positive == cost to the trader).  All ``*_usd`` fields are signed dollar
    costs over the *filled* quantity unless noted.

    Attributes
    ----------
    order_id, symbol, side:
        Identity copied from the input row.  ``side`` is ``+1`` (buy) or
        ``-1`` (sell).
    quantity, filled_quantity:
        Intended and executed quantities (shares/units).
    fill_rate:
        ``filled_quantity / quantity`` in ``[0, 1]``.
    arrival_slippage_bps:
        Side-signed arrival-price slippage in bps.
    vwap_slippage_bps:
        Side-signed VWAP slippage in bps.  ``nan`` when no interval VWAP was
        supplied for the order.
    is_usd:
        Total implementation shortfall in USD (filled + opportunity + fees).
    is_bps:
        Implementation shortfall expressed in bps of the *decision notional*
        ``decision_price * quantity``.
    spread_usd, impact_usd, timing_usd, opportunity_usd, fees_usd:
        The cost-attribution components in USD.  By construction
        ``spread_usd + impact_usd + timing_usd + opportunity_usd + fees_usd
        == is_usd`` (the decomposition identity).
    markout_bps:
        Mapping of horizon label -> side-signed markout in bps; ``nan`` where
        the horizon falls beyond the supplied price series.
    """

    order_id: str
    symbol: str
    side: int
    quantity: float
    filled_quantity: float
    fill_rate: float
    arrival_slippage_bps: float
    vwap_slippage_bps: float
    is_usd: float
    is_bps: float
    spread_usd: float
    impact_usd: float
    timing_usd: float
    opportunity_usd: float
    fees_usd: float
    markout_bps: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DailyTCAReport:
    """Aggregated daily TCA report.

    Attributes
    ----------
    generated_at:
        ISO UTC timestamp of report generation.
    fills:
        The per-order :class:`FillTCA` list, in input order.
    per_symbol:
        Mapping of symbol -> summary stats (mean/median slippage bps, total
        cost USD, fill rate, order count).
    portfolio:
        Portfolio-level summary stats (same schema as a ``per_symbol`` value
        plus ``n_symbols``).
    worst_fills:
        The ``worst_n`` highest ``is_usd`` fills, descending.
    config:
        The :class:`TCAConfig` used.
    """

    generated_at: str
    fills: list[FillTCA]
    per_symbol: dict[str, dict[str, float]]
    portfolio: dict[str, float]
    worst_fills: list[FillTCA]
    config: TCAConfig


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _utcnow_str() -> str:
    ts = pd.Timestamp.utcnow()
    return str(ts.strftime("%Y-%m-%dT%H:%M:%SZ"))


def _side_to_sign(side: Any) -> int:
    """Map a side label to ``+1`` (buy) or ``-1`` (sell)."""
    s = str(side).strip().lower()
    if s in {"buy", "b", "+1", "1", "long"}:
        return 1
    if s in {"sell", "s", "-1", "short"}:
        return -1
    raise ValueError(f"Unrecognised side {side!r}; expected 'buy' or 'sell'.")


def _validate_columns(fills: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_FILL_COLUMNS if c not in fills.columns]
    if missing:
        raise ValueError(
            "fills DataFrame is missing required column(s): "
            + ", ".join(missing)
        )


# ---------------------------------------------------------------------------
# Slippage primitives
# ---------------------------------------------------------------------------


def arrival_slippage_bps(
    avg_fill_price: float,
    arrival_price: float,
    side: int,
    *,
    bps_scale: float = 1e4,
) -> float:
    """Side-signed arrival-price slippage in basis points.

    Defined as

        slippage = side * (avg_fill - arrival) / arrival * bps_scale

    where ``side`` is ``+1`` for a buy and ``-1`` for a sell.  Under the
    positive-loss convention a buy filled *above* arrival (``avg_fill >
    arrival``) is a positive cost; a sell filled *below* arrival is likewise a
    positive cost.  Negative values denote price improvement.

    Parameters
    ----------
    avg_fill_price:
        Quantity-weighted average execution price (> 0).
    arrival_price:
        Prevailing price when the order reached the market (> 0).
    side:
        ``+1`` (buy) or ``-1`` (sell).
    bps_scale:
        Fraction-to-bps multiplier (``1e4``).

    Returns
    -------
    float
        Side-signed slippage in bps; ``nan`` if ``arrival_price`` is
        non-positive.
    """
    if arrival_price <= 0.0:
        return float("nan")
    frac = (avg_fill_price - arrival_price) / arrival_price
    return float(side) * frac * bps_scale


def vwap_slippage_bps(
    avg_fill_price: float,
    interval_vwap: float,
    side: int,
    *,
    bps_scale: float = 1e4,
) -> float:
    """Side-signed slippage of the average fill vs the interval VWAP, in bps.

        slippage = side * (avg_fill - vwap) / vwap * bps_scale

    Same sign convention as :func:`arrival_slippage_bps`.  Beating VWAP (a buy
    filling below VWAP) yields a negative cost.

    Parameters
    ----------
    avg_fill_price:
        Quantity-weighted average execution price (> 0).
    interval_vwap:
        Volume-weighted average price over the order's active interval (> 0).
        ``nan`` propagates to a ``nan`` result.
    side:
        ``+1`` (buy) or ``-1`` (sell).
    bps_scale:
        Fraction-to-bps multiplier (``1e4``).

    Returns
    -------
    float
        Side-signed VWAP slippage in bps; ``nan`` if ``interval_vwap`` is
        non-positive or ``nan``.
    """
    if not np.isfinite(interval_vwap) or interval_vwap <= 0.0:
        return float("nan")
    frac = (avg_fill_price - interval_vwap) / interval_vwap
    return float(side) * frac * bps_scale


# ---------------------------------------------------------------------------
# Implementation shortfall + attribution
# ---------------------------------------------------------------------------


def implementation_shortfall(
    *,
    side: int,
    quantity: float,
    filled_quantity: float,
    decision_price: float,
    avg_fill_price: float,
    close_price: float,
    fees: float,
) -> dict[str, float]:
    """Perold (1988) implementation shortfall, decomposed by quantity.

    The implementation shortfall is the difference between a *paper* portfolio
    that transacts the full intended quantity costlessly at the decision price
    and the *real* portfolio that fills only part of it at real prices and pays
    fees.  Side-signed under the positive-loss convention:

        execution_cost = side * (avg_fill - decision) * filled_quantity
        opportunity_cost = side * (close - decision) * unfilled_quantity
        total_is = execution_cost + opportunity_cost + fees

    where ``unfilled_quantity = quantity - filled_quantity`` and ``close`` is
    the reference price used to mark the paper return on the part that never
    executed (a buy whose price ran away from us before we could fill incurs a
    positive opportunity cost).

    Parameters
    ----------
    side:
        ``+1`` (buy) or ``-1`` (sell).
    quantity:
        Intended order quantity (> 0).
    filled_quantity:
        Executed quantity in ``[0, quantity]``.
    decision_price:
        Price at the decision instant (> 0).
    avg_fill_price:
        Quantity-weighted average execution price (> 0).
    close_price:
        Reference price marking the unfilled remainder.
    fees:
        Explicit fees in USD (>= 0).

    Returns
    -------
    dict[str, float]
        Keys ``execution_cost``, ``opportunity_cost``, ``fees`` and
        ``total_is`` (all USD).
    """
    unfilled = quantity - filled_quantity
    execution_cost = float(side) * (avg_fill_price - decision_price) * filled_quantity
    opportunity_cost = float(side) * (close_price - decision_price) * unfilled
    total = execution_cost + opportunity_cost + fees
    return {
        "execution_cost": execution_cost,
        "opportunity_cost": opportunity_cost,
        "fees": fees,
        "total_is": total,
    }


def attribute_cost(
    *,
    side: int,
    quantity: float,
    filled_quantity: float,
    decision_price: float,
    arrival_price: float,
    avg_fill_price: float,
    mid_at_fill: float,
    half_spread: float,
    close_price: float,
    fees: float,
) -> dict[str, float]:
    """Decompose total implementation shortfall into named cost components.

    The realised per-share execution cost ``side * (avg_fill - decision)`` is
    split through two intermediate reference prices -- the arrival price and
    the mid at fill -- into three additive legs::

        timing = side * (arrival   - decision) * filled_qty
        impact = side * (mid_fill  - arrival ) * filled_qty
        spread = side * (avg_fill  - mid_fill) * filled_qty

    so that ``timing + impact + spread == side * (avg_fill - decision) *
    filled_qty`` identically (a telescoping sum).  ``spread`` is the
    *effective* half-spread paid at the fill; ``impact`` is the residual
    mid-price drift between order placement and fill; ``timing`` is the price
    drift between the decision and order placement.  Adding the unfilled
    opportunity cost and explicit fees recovers the full Perold shortfall:

    **Decomposition identity** ::

        spread + impact + timing + opportunity + fees == total_is

    Parameters
    ----------
    side:
        ``+1`` (buy) or ``-1`` (sell).
    quantity, filled_quantity:
        Intended and executed quantities.
    decision_price, arrival_price, avg_fill_price, mid_at_fill:
        The reference prices defining the three execution legs.
    half_spread:
        Quoted half-spread at fill (price units, >= 0).  Retained for
        diagnostics; the *effective* spread cost is derived from
        ``avg_fill - mid_at_fill`` so the identity holds exactly even when the
        realised spread differs from the quoted one.
    close_price:
        Reference price for the unfilled opportunity leg.
    fees:
        Explicit fees in USD (>= 0).

    Returns
    -------
    dict[str, float]
        Keys ``spread``, ``impact``, ``timing``, ``opportunity``, ``fees``,
        ``total_is`` and ``quoted_half_spread_usd`` (the quoted-spread
        reference) -- all USD.
    """
    s = float(side)
    timing = s * (arrival_price - decision_price) * filled_quantity
    impact = s * (mid_at_fill - arrival_price) * filled_quantity
    spread = s * (avg_fill_price - mid_at_fill) * filled_quantity
    unfilled = quantity - filled_quantity
    opportunity = s * (close_price - decision_price) * unfilled
    total = spread + impact + timing + opportunity + fees
    quoted_half_spread_usd = half_spread * filled_quantity
    return {
        "spread": spread,
        "impact": impact,
        "timing": timing,
        "opportunity": opportunity,
        "fees": fees,
        "total_is": total,
        "quoted_half_spread_usd": quoted_half_spread_usd,
    }


# ---------------------------------------------------------------------------
# Markout analysis
# ---------------------------------------------------------------------------


def markouts(
    fills: pd.DataFrame,
    prices: pd.Series,
    horizons: tuple[tuple[str, float | None], ...] = _DEFAULT_TCA_CONFIG.horizons,
    *,
    bps_scale: float = 1e4,
) -> pd.DataFrame:
    """Side-signed post-fill markouts at each horizon for every fill.

    For a fill at ``fill_time`` and reference price ``p0`` (the fill's
    ``avg_fill_price``), the markout at horizon ``h`` is

        markout_bps = side * (p_h - p0) / p0 * bps_scale

    where ``p_h`` is the price *at or after* ``fill_time + h`` (nearest
    forward tick/bar).  A *positive* markout means the price moved against the
    trader after the fill -- a buy whose price kept rising, or a sell whose
    price kept falling -- which is the signature of adverse selection.

    Timestamp-alignment rules
    -------------------------
    * The ``prices`` index must be a monotonic-increasing ``DatetimeIndex``.
    * For a finite horizon ``h`` seconds, the target time is
      ``fill_time + h``; the markout price is the **first** index entry at or
      after that target (``searchsorted(..., side="left")``).
    * For the ``EOD`` horizon (``seconds is None``) the target is the last
      price stamped on the fill's calendar day; ``nan`` if the day is absent.
    * If the target time is **beyond the last available price**, the markout
      is ``nan`` (documented "beyond data" rule).

    Parameters
    ----------
    fills:
        Frame with at least ``side``, ``avg_fill_price`` and ``fill_time``
        columns (the report's full column set is accepted too).
    prices:
        Reference price series indexed by timestamp (a tick or bar mid/last
        series), monotonic increasing in time.
    horizons:
        ``(label, seconds)`` pairs; ``seconds is None`` denotes EOD.
    bps_scale:
        Fraction-to-bps multiplier (``1e4``).

    Returns
    -------
    pd.DataFrame
        One row per input fill (same index), one column per horizon label,
        holding the side-signed markout in bps (``nan`` where unavailable).

    Raises
    ------
    ValueError
        If required columns are absent or the price index is not a monotonic
        ``DatetimeIndex``.
    """
    for col in ("side", "avg_fill_price", "fill_time"):
        if col not in fills.columns:
            raise ValueError(f"fills is missing required column {col!r} for markouts.")
    idx = prices.index
    if not isinstance(idx, pd.DatetimeIndex):
        raise ValueError("prices must be indexed by a DatetimeIndex.")
    if not idx.is_monotonic_increasing:
        raise ValueError("prices index must be monotonic increasing.")

    labels = [h[0] for h in horizons]
    out = pd.DataFrame(
        np.full((len(fills), len(labels)), np.nan, dtype=float),
        index=fills.index,
        columns=labels,
    )
    if len(idx) == 0:
        return out

    price_vals = prices.to_numpy(dtype=float)
    last_ts = idx[-1]

    for row_pos, (_row_idx, row) in enumerate(fills.iterrows()):
        sign = _side_to_sign(row["side"])
        p0 = float(row["avg_fill_price"])
        fill_ts = pd.Timestamp(row["fill_time"])
        if p0 <= 0.0:
            continue
        for label, secs in horizons:
            if secs is None:
                # EOD: last price stamped on the fill's calendar day.
                day = fill_ts.normalize()
                day_end = day + pd.Timedelta(days=1)
                lo = int(idx.searchsorted(day, side="left"))
                hi = int(idx.searchsorted(day_end, side="left"))
                if hi <= lo:
                    continue
                p_h = float(price_vals[hi - 1])
            else:
                target = fill_ts + pd.Timedelta(seconds=secs)
                if target > last_ts:
                    continue  # beyond data
                pos = int(idx.searchsorted(target, side="left"))
                if pos >= len(price_vals):  # pragma: no cover - guarded by target>last_ts
                    continue
                p_h = float(price_vals[pos])
            out.iat[row_pos, labels.index(label)] = sign * (p_h - p0) / p0 * bps_scale

    return out


# ---------------------------------------------------------------------------
# Per-order assembly
# ---------------------------------------------------------------------------


def compute_fill_tca(
    row: pd.Series,
    *,
    interval_vwap: float = float("nan"),
    markout_bps: dict[str, float] | None = None,
    config: TCAConfig = _DEFAULT_TCA_CONFIG,
) -> FillTCA:
    """Assemble a :class:`FillTCA` from a single fills-frame row.

    Parameters
    ----------
    row:
        A row of the fills DataFrame (must carry the required columns).
    interval_vwap:
        Optional interval VWAP for the VWAP-slippage metric; ``nan`` skips it.
    markout_bps:
        Optional precomputed markout mapping for this order.
    config:
        :class:`TCAConfig` controlling the bps scale.

    Returns
    -------
    FillTCA
        The per-order metrics DTO.
    """
    side = _side_to_sign(row["side"])
    qty = float(row["quantity"])
    filled = float(row["filled_quantity"])
    decision = float(row["decision_price"])
    arrival = float(row["arrival_price"])
    avg_fill = float(row["avg_fill_price"])
    mid_fill = float(row["mid_at_fill"])
    half_spread = float(row["half_spread"])
    close = float(row["close_price"])
    fees = float(row["fees"])

    fill_rate = filled / qty if qty > 0.0 else 0.0

    arr_bps = arrival_slippage_bps(
        avg_fill, arrival, side, bps_scale=config.bps_scale
    )
    vwap_bps = vwap_slippage_bps(
        avg_fill, interval_vwap, side, bps_scale=config.bps_scale
    )

    attr = attribute_cost(
        side=side,
        quantity=qty,
        filled_quantity=filled,
        decision_price=decision,
        arrival_price=arrival,
        avg_fill_price=avg_fill,
        mid_at_fill=mid_fill,
        half_spread=half_spread,
        close_price=close,
        fees=fees,
    )
    is_usd = attr["total_is"]
    decision_notional = decision * qty
    is_bps = (
        is_usd / decision_notional * config.bps_scale
        if decision_notional > 0.0
        else float("nan")
    )

    return FillTCA(
        order_id=str(row["order_id"]),
        symbol=str(row["symbol"]),
        side=side,
        quantity=qty,
        filled_quantity=filled,
        fill_rate=fill_rate,
        arrival_slippage_bps=arr_bps,
        vwap_slippage_bps=vwap_bps,
        is_usd=is_usd,
        is_bps=is_bps,
        spread_usd=attr["spread"],
        impact_usd=attr["impact"],
        timing_usd=attr["timing"],
        opportunity_usd=attr["opportunity"],
        fees_usd=attr["fees"],
        markout_bps=dict(markout_bps) if markout_bps is not None else {},
    )


# ---------------------------------------------------------------------------
# Aggregation helpers
# ---------------------------------------------------------------------------


def _summary_stats(fills: list[FillTCA]) -> dict[str, float]:
    """Aggregate a list of FillTCA into summary statistics."""
    if not fills:
        return {
            "n_orders": 0.0,
            "mean_arrival_bps": float("nan"),
            "median_arrival_bps": float("nan"),
            "mean_is_bps": float("nan"),
            "total_is_usd": 0.0,
            "fill_rate": float("nan"),
        }
    arr = np.array([f.arrival_slippage_bps for f in fills], dtype=float)
    is_bps = np.array([f.is_bps for f in fills], dtype=float)
    total_is = float(np.sum([f.is_usd for f in fills]))
    fill_rate = float(np.mean([f.fill_rate for f in fills]))
    return {
        "n_orders": float(len(fills)),
        "mean_arrival_bps": float(np.nanmean(arr)) if np.any(np.isfinite(arr)) else float("nan"),
        "median_arrival_bps": float(np.nanmedian(arr)) if np.any(np.isfinite(arr)) else float("nan"),
        "mean_is_bps": float(np.nanmean(is_bps)) if np.any(np.isfinite(is_bps)) else float("nan"),
        "total_is_usd": total_is,
        "fill_rate": fill_rate,
    }


# ---------------------------------------------------------------------------
# Public report builder
# ---------------------------------------------------------------------------


def build_daily_tca_report(
    fills: pd.DataFrame,
    *,
    prices: pd.Series | None = None,
    interval_vwaps: dict[str, float] | None = None,
    config: TCAConfig | None = None,
    generated_at: str | None = None,
) -> DailyTCAReport:
    """Build a :class:`DailyTCAReport` from a frame of executed fills.

    Parameters
    ----------
    fills:
        Fills DataFrame.  Must contain every column in
        :data:`REQUIRED_FILL_COLUMNS`; a :class:`ValueError` listing the
        missing names is raised otherwise.
    prices:
        Optional reference price series for markout analysis (see
        :func:`markouts`).  When ``None`` markout columns are empty.
    interval_vwaps:
        Optional mapping ``order_id -> interval VWAP`` for VWAP slippage.
    config:
        :class:`TCAConfig`; defaults to :data:`TCAConfig()`.
    generated_at:
        Optional ISO timestamp override; defaults to ``utcnow``.

    Returns
    -------
    DailyTCAReport
        Per-order, per-symbol and portfolio-level TCA.

    Raises
    ------
    ValueError
        On a missing required column.
    """
    cfg = config if config is not None else _DEFAULT_TCA_CONFIG
    _validate_columns(fills)
    stamp = generated_at if generated_at is not None else _utcnow_str()
    vwap_map = interval_vwaps if interval_vwaps is not None else {}

    markout_frame: pd.DataFrame | None = None
    if prices is not None:
        markout_frame = markouts(
            fills, prices, cfg.horizons, bps_scale=cfg.bps_scale
        )

    fill_tcas: list[FillTCA] = []
    for pos, (_idx, row) in enumerate(fills.iterrows()):
        order_id = str(row["order_id"])
        mk: dict[str, float] | None = None
        if markout_frame is not None:
            mk = {
                label: float(markout_frame.iat[pos, j])
                for j, label in enumerate(markout_frame.columns)
            }
        fill_tcas.append(
            compute_fill_tca(
                row,
                interval_vwap=vwap_map.get(order_id, float("nan")),
                markout_bps=mk,
                config=cfg,
            )
        )

    # Per-symbol aggregation.
    per_symbol: dict[str, dict[str, float]] = {}
    symbols = sorted({f.symbol for f in fill_tcas})
    for sym in symbols:
        per_symbol[sym] = _summary_stats(
            [f for f in fill_tcas if f.symbol == sym]
        )

    portfolio = _summary_stats(fill_tcas)
    portfolio["n_symbols"] = float(len(symbols))

    worst = sorted(fill_tcas, key=lambda f: f.is_usd, reverse=True)[: cfg.worst_n]

    return DailyTCAReport(
        generated_at=stamp,
        fills=fill_tcas,
        per_symbol=per_symbol,
        portfolio=portfolio,
        worst_fills=worst,
        config=cfg,
    )


# ---------------------------------------------------------------------------
# ASCII markdown renderer
# ---------------------------------------------------------------------------


def _fmt(value: float, prec: int = 2) -> str:
    """Format a float for the ASCII tables; 'nan' for non-finite."""
    if not np.isfinite(value):
        return "nan"
    return f"{value:.{prec}f}"


def _render_portfolio_section(report: DailyTCAReport) -> str:
    lines: list[str] = []
    p = report.portfolio
    lines.append("## Portfolio Summary")
    lines.append("")
    lines.append(f"Orders            : {int(p['n_orders'])}")
    lines.append(f"Symbols           : {int(p.get('n_symbols', 0.0))}")
    lines.append(f"Mean arrival bps  : {_fmt(p['mean_arrival_bps'])}")
    lines.append(f"Median arrival bps: {_fmt(p['median_arrival_bps'])}")
    lines.append(f"Mean IS bps       : {_fmt(p['mean_is_bps'])}")
    lines.append(f"Total cost USD    : {_fmt(p['total_is_usd'])}")
    lines.append(f"Avg fill rate     : {_fmt(p['fill_rate'], 4)}")
    lines.append("")
    return "\n".join(lines)


def _render_per_symbol_table(report: DailyTCAReport) -> str:
    lines: list[str] = []
    lines.append("## Per-Symbol TCA")
    lines.append("")
    w_sym, w_n, w_bps, w_usd = 10, 8, 16, 16
    header = (
        f"| {'Symbol':<{w_sym}} "
        f"| {'Orders':<{w_n}} "
        f"| {'Mean arr bps':<{w_bps}} "
        f"| {'Mean IS bps':<{w_bps}} "
        f"| {'Total cost USD':<{w_usd}} |"
    )
    divider = (
        f"|{'-' * (w_sym + 2)}"
        f"|{'-' * (w_n + 2)}"
        f"|{'-' * (w_bps + 2)}"
        f"|{'-' * (w_bps + 2)}"
        f"|{'-' * (w_usd + 2)}|"
    )
    lines.append(header)
    lines.append(divider)
    for sym in sorted(report.per_symbol):
        s = report.per_symbol[sym]
        row = (
            f"| {sym:<{w_sym}} "
            f"| {int(s['n_orders']):<{w_n}} "
            f"| {_fmt(s['mean_arrival_bps']):<{w_bps}} "
            f"| {_fmt(s['mean_is_bps']):<{w_bps}} "
            f"| {_fmt(s['total_is_usd']):<{w_usd}} |"
        )
        lines.append(row)
    lines.append("")
    return "\n".join(lines)


def _render_worst_fills(report: DailyTCAReport) -> str:
    lines: list[str] = []
    lines.append("## Worst Fills (by implementation shortfall USD)")
    lines.append("")
    w_oid, w_sym, w_side, w_usd, w_bps = 14, 10, 6, 14, 12
    header = (
        f"| {'Order':<{w_oid}} "
        f"| {'Symbol':<{w_sym}} "
        f"| {'Side':<{w_side}} "
        f"| {'IS USD':<{w_usd}} "
        f"| {'IS bps':<{w_bps}} |"
    )
    divider = (
        f"|{'-' * (w_oid + 2)}"
        f"|{'-' * (w_sym + 2)}"
        f"|{'-' * (w_side + 2)}"
        f"|{'-' * (w_usd + 2)}"
        f"|{'-' * (w_bps + 2)}|"
    )
    lines.append(header)
    lines.append(divider)
    for f in report.worst_fills:
        side_str = "BUY" if f.side > 0 else "SELL"
        row = (
            f"| {f.order_id:<{w_oid}} "
            f"| {f.symbol:<{w_sym}} "
            f"| {side_str:<{w_side}} "
            f"| {_fmt(f.is_usd):<{w_usd}} "
            f"| {_fmt(f.is_bps):<{w_bps}} |"
        )
        lines.append(row)
    lines.append("")
    return "\n".join(lines)


def render_report(report: DailyTCAReport) -> str:
    """Render a :class:`DailyTCAReport` as an ASCII-only markdown string.

    All output is 7-bit ASCII (``ord < 128``) -- suitable for terminal portability
    consoles, ops emails and log files.  No unicode box characters are used.

    Parameters
    ----------
    report:
        The report to render.

    Returns
    -------
    str
        ASCII-only markdown.
    """
    parts: list[str] = []
    parts.append("# Daily TCA Report")
    parts.append("")
    parts.append(f"Generated : {report.generated_at}")
    parts.append("")
    parts.append(_render_portfolio_section(report))
    parts.append(_render_per_symbol_table(report))
    parts.append(_render_worst_fills(report))
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Demo synthetic fills builder
# ---------------------------------------------------------------------------


def _build_demo_fills(
    seed: int = 42,
    n_orders: int = 12,
) -> dict[str, Any]:
    """Build a seeded synthetic fills frame + price series for the CLI demo."""
    rng = np.random.default_rng(seed)
    symbols = ["AAPL", "MSFT", "GOOG", "AMZN"]
    base_day = pd.Timestamp("2026-06-05 14:30:00")

    rows: list[dict[str, Any]] = []
    interval_vwaps: dict[str, float] = {}
    for i in range(n_orders):
        sym = symbols[i % len(symbols)]
        side = "buy" if rng.random() < 0.5 else "sell"
        s = 1.0 if side == "buy" else -1.0
        decision = float(rng.uniform(50.0, 300.0))
        # arrival drifts slightly from decision (timing); fill drifts from mid.
        arrival = decision * (1.0 + s * rng.uniform(0.0, 0.0008))
        half_spread = decision * rng.uniform(0.00005, 0.0003)
        mid_fill = arrival * (1.0 + s * rng.uniform(-0.0002, 0.0006))
        avg_fill = mid_fill + s * half_spread
        qty = float(rng.integers(100, 1000))
        fill_rate = float(rng.uniform(0.7, 1.0))
        filled = round(qty * fill_rate)
        close = decision * (1.0 + s * rng.uniform(-0.001, 0.002))
        fees = filled * 0.005
        fill_time = base_day + pd.Timedelta(minutes=int(rng.integers(0, 300)))
        order_id = f"ORD{i:04d}"
        interval_vwaps[order_id] = float(mid_fill)
        rows.append(
            {
                "order_id": order_id,
                "symbol": sym,
                "side": side,
                "quantity": qty,
                "filled_quantity": float(filled),
                "decision_price": decision,
                "arrival_price": arrival,
                "avg_fill_price": avg_fill,
                "mid_at_fill": mid_fill,
                "half_spread": half_spread,
                "fill_time": fill_time,
                "close_price": close,
                "fees": fees,
            }
        )
    fills = pd.DataFrame(rows)

    # Reference price series spanning the trading day at 1-second resolution
    # would be large; use a 1-minute grid which still satisfies the alignment
    # rules (nearest at-or-after) for sub-minute horizons.
    price_index = pd.date_range(base_day, periods=8 * 60, freq="1min")
    walk = 100.0 + np.cumsum(rng.normal(0.0, 0.05, size=len(price_index)))
    prices = pd.Series(walk, index=price_index)

    return {
        "fills": fills,
        "prices": prices,
        "interval_vwaps": interval_vwaps,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """Parse args and run the TCA report generator.

    Parameters
    ----------
    argv:
        Argument list (``sys.argv[1:]`` when ``None``).  Testable without a
        subprocess by passing a list directly.
    """
    parser = argparse.ArgumentParser(
        prog="python -m core_trading.execution.tca",
        description=(
            "Transaction Cost Analysis report generator.  "
            "Use --demo to run on a seeded synthetic fills frame."
        ),
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run on a seeded synthetic fills frame (no live data needed).",
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        default=None,
        help="Write the markdown report to this file path.",
    )
    args = parser.parse_args(argv)

    if not args.demo:
        parser.error(
            "--demo is required (reading live fills is a later "
            "operational-wiring concern; see module docstring)."
        )

    demo = _build_demo_fills(seed=42)
    report = build_daily_tca_report(
        demo["fills"],
        prices=demo["prices"],
        interval_vwaps=demo["interval_vwaps"],
    )
    markdown = render_report(report)
    print(markdown)

    if args.output is not None:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(markdown)
        print(f"[tca] Report written to {args.output}")


if __name__ == "__main__":  # pragma: no cover - exercised via main() in tests
    main(sys.argv[1:])
