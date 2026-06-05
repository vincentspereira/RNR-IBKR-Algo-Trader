"""Turnover and cost-budget controls (master plan Phase 8.5).

This module enforces three independent money-management guardrails that sit
between the portfolio target weights and order submission:

1. **Monthly turnover cap** -- a hard limit on how much trading a strategy may
   do per rolling month, expressed as a fraction of NAV.
2. **Cost budget** -- caps the share of expected gross alpha that may be
   consumed by trading costs (default 30 %).
3. **Edge-vs-cost filter** -- only trade an idea when the expected edge exceeds
   a multiple (default 2x) of the expected cost.

Turnover convention (ONE-SIDED)
-------------------------------
For a transition from weight vector ``w_prev`` to ``w_curr`` (each a vector of
NAV fractions across assets), the per-period turnover is

    turnover = sum_i |w_curr[i] - w_prev[i]| / 2

i.e. *half* the L1 norm of the weight change.  This is the standard "one-sided"
convention: a full liquidation of a 100 %-invested long book and reinvestment
into a disjoint set of names changes weights by an L1 distance of 2.0 but counts
as 1.0 (100 %) of turnover, because you sold one unit of NAV and bought one unit
of NAV -- a single round-trip of the capital.  A monthly cap of ``2.0`` (the
default) therefore permits rotating the entire book twice per month.

Assets that enter or leave the universe are handled by treating a missing
(NaN) weight as ``0.0`` (no position), so opening a brand-new position of
weight ``w`` contributes ``|w|`` to the L1 change and ``|w| / 2`` to turnover.

Units
-----
* Weights are NAV fractions (decimals): ``0.05`` == 5 % of NAV.
* ``expected_gross_alpha``, ``expected_costs``, ``expected_edge`` and
  ``expected_cost`` are all in the **same** per-period decimal-return units
  (e.g. ``0.01`` == 1 % expected return / cost over the holding period).

All routines are pure NumPy/pandas -- no external optimisation libraries.

References
----------
Grinold & Kahn (2000), *Active Portfolio Management*, ch. 16 (transaction
costs and turnover).  Novy-Marx & Velikov (2016), *A Taxonomy of Anomalies and
Their Trading Costs*, for the cost-vs-alpha budgeting framing.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

__all__ = [
    "TurnoverConfig",
    "TurnoverDecision",
    "realised_turnover",
    "monthly_turnover",
    "turnover_headroom",
    "check_turnover_budget",
    "cost_budget_ok",
    "cost_budget_ratio",
    "edge_exceeds_cost",
    "filter_trades_by_edge",
]


# ---------------------------------------------------------------------------
# Configuration and result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TurnoverConfig:
    """Immutable configuration for the turnover and cost-budget controls.

    Attributes
    ----------
    max_monthly_turnover:
        Hard cap on rolling monthly turnover, in one-sided units (see module
        docstring).  ``2.0`` (the default) == 200 % of NAV per month, i.e. the
        whole book may be rotated twice a month.  Must be ``>= 0``.
    max_cost_alpha_ratio:
        Maximum fraction of expected gross alpha that may be consumed by costs,
        in ``[0, 1]``.  Default ``0.30`` (costs <= 30 % of gross alpha).
    min_edge_cost_multiple:
        A trade is only worthwhile when expected edge exceeds this multiple of
        expected cost.  Default ``2.0`` (edge must beat 2x cost).  Must be
        ``> 0``.
    periods_per_month:
        Number of trading periods that constitute one "month" for the rolling
        turnover sum.  Default ``21`` (trading days per calendar month).  Must
        be a positive integer.
    """

    max_monthly_turnover: float = 2.0
    max_cost_alpha_ratio: float = 0.30
    min_edge_cost_multiple: float = 2.0
    periods_per_month: int = 21

    def __post_init__(self) -> None:
        if not np.isfinite(self.max_monthly_turnover) or self.max_monthly_turnover < 0:
            raise ValueError(
                "max_monthly_turnover must be a finite non-negative float; "
                f"got {self.max_monthly_turnover}"
            )
        if not (0 <= self.max_cost_alpha_ratio <= 1):
            raise ValueError(
                "max_cost_alpha_ratio must be in [0, 1]; "
                f"got {self.max_cost_alpha_ratio}"
            )
        if not np.isfinite(self.min_edge_cost_multiple) or (
            self.min_edge_cost_multiple <= 0
        ):
            raise ValueError(
                "min_edge_cost_multiple must be a finite positive float; "
                f"got {self.min_edge_cost_multiple}"
            )
        if self.periods_per_month <= 0:
            raise ValueError(
                f"periods_per_month must be a positive integer; "
                f"got {self.periods_per_month}"
            )


@dataclass(frozen=True, slots=True)
class TurnoverDecision:
    """Outcome of :func:`check_turnover_budget`.

    Attributes
    ----------
    allowed:
        ``True`` if the *full* proposed rebalance fits inside the remaining
        monthly turnover budget; ``False`` if it would breach the cap (in which
        case ``scaled_weights`` holds a budget-respecting partial rebalance).
    proposed_turnover:
        One-sided turnover of the full proposed move (current -> proposed).
    used_budget:
        Turnover already consumed in the trailing ``periods_per_month - 1``
        periods of ``weight_history`` (the part of the rolling window that has
        already happened).
    remaining_budget:
        ``max_monthly_turnover - used_budget``, floored at ``0.0``.
    scaled_weights:
        Weights to actually trade to.  Equal to the proposed weights when
        ``allowed`` is ``True``; otherwise a proportional partial move from
        ``current`` toward ``proposed`` that exactly consumes the remaining
        budget.  Keys are the union of current and proposed asset identifiers.
    reason:
        Machine-readable reason code: ``"within_budget"``, ``"breach_scaled"``,
        ``"no_budget"`` (remaining budget is zero, nothing trades), or
        ``"no_trade"`` (the proposed move has zero turnover).
    """

    allowed: bool
    proposed_turnover: float
    used_budget: float
    remaining_budget: float
    scaled_weights: dict[str, float]
    reason: str


# Module-level singleton used as the default config so that ruff B008 (no
# function calls in argument defaults) is satisfied without recomputing the
# config object on every call.
_DEFAULT_TURNOVER_CONFIG = TurnoverConfig()


# ---------------------------------------------------------------------------
# Turnover measurement
# ---------------------------------------------------------------------------


def _one_sided_turnover(prev: pd.Series, curr: pd.Series) -> float:
    """Return one-sided turnover between two aligned weight Series.

    Both Series are reindexed onto the union of their labels with missing
    entries treated as ``0.0`` (no position), then::

        turnover = sum |curr - prev| / 2
    """
    idx = prev.index.union(curr.index)
    p = prev.reindex(idx).fillna(0.0).to_numpy(dtype=float)
    c = curr.reindex(idx).fillna(0.0).to_numpy(dtype=float)
    return float(np.abs(c - p).sum() / 2.0)


def realised_turnover(weight_history: pd.DataFrame) -> pd.Series:
    """Per-period one-sided turnover from a wide weight history.

    Parameters
    ----------
    weight_history:
        Wide DataFrame of NAV-fraction weights with rows indexed by time
        (ascending) and columns indexed by asset.  ``NaN`` entries are treated
        as ``0.0`` (the asset was not held), so assets entering or leaving the
        universe are handled naturally.

    Returns
    -------
    pandas.Series
        Turnover for each period *after the first*, indexed by the same time
        index as rows ``1..n-1`` of ``weight_history``.  Row 0 has no prior
        period and is therefore omitted.  An empty or single-row input yields
        an empty Series.

    Notes
    -----
    For consecutive weight rows ``w_{t-1}`` and ``w_t``::

        turnover_t = sum_i |w_t[i] - w_{t-1}[i]| / 2

    (one-sided convention; see module docstring).
    """
    if weight_history.shape[0] < 2:
        return pd.Series(dtype=float, index=weight_history.index[1:])
    filled = weight_history.fillna(0.0)
    diffs = filled.diff().iloc[1:]
    turnover = diffs.abs().sum(axis=1) / 2.0
    return turnover.astype(float)


def monthly_turnover(weight_history: pd.DataFrame, *, periods_per_month: int = 21) -> pd.Series:
    """Rolling ``periods_per_month``-period sum of per-period turnover.

    Parameters
    ----------
    weight_history:
        Wide weight DataFrame (see :func:`realised_turnover`).
    periods_per_month:
        Window length, in periods, for the trailing turnover sum.

    Returns
    -------
    pandas.Series
        Rolling sum of per-period turnover with a minimum of one observation,
        indexed like :func:`realised_turnover`.  Each value is the total
        one-sided turnover over the trailing ``periods_per_month`` periods
        ending at that timestamp.

    Notes
    -----
    Because per-period turnover begins at row 1, an input with fewer than two
    rows yields an empty Series.
    """
    if periods_per_month <= 0:
        raise ValueError(
            f"periods_per_month must be positive; got {periods_per_month}"
        )
    per_period = realised_turnover(weight_history)
    if per_period.empty:
        return per_period
    return (
        per_period.rolling(window=periods_per_month, min_periods=1).sum().astype(float)
    )


def turnover_headroom(
    weight_history: pd.DataFrame,
    *,
    config: TurnoverConfig = _DEFAULT_TURNOVER_CONFIG,
) -> float:
    """Remaining monthly turnover budget given recent trading.

    Looks at the turnover already consumed over the trailing
    ``periods_per_month - 1`` periods (the part of the current rolling month
    that has already elapsed) and returns how much budget is left before the
    monthly cap is hit.

    Parameters
    ----------
    weight_history:
        Wide weight DataFrame of realised weights up to and including the most
        recent period.
    config:
        Turnover configuration.

    Returns
    -------
    float
        ``max_monthly_turnover - used``, floored at ``0.0`` where ``used`` is
        the trailing one-sided turnover already incurred this month.
    """
    used = _used_budget(weight_history, config=config)
    return max(0.0, config.max_monthly_turnover - used)


def _used_budget(
    weight_history: pd.DataFrame,
    *,
    config: TurnoverConfig,
) -> float:
    """Trailing turnover already consumed within the current rolling month.

    The proposed (not-yet-executed) rebalance will become the next period, so
    the window that it must share the monthly cap with is the most recent
    ``periods_per_month - 1`` realised per-period turnovers.
    """
    per_period = realised_turnover(weight_history)
    if per_period.empty:
        return 0.0
    window = config.periods_per_month - 1
    if window <= 0:
        return 0.0
    return float(per_period.tail(window).sum())


# ---------------------------------------------------------------------------
# Turnover budgeting decision
# ---------------------------------------------------------------------------


def check_turnover_budget(
    current_weights: Mapping[str, float],
    proposed_weights: Mapping[str, float],
    weight_history: pd.DataFrame,
    *,
    config: TurnoverConfig = _DEFAULT_TURNOVER_CONFIG,
) -> TurnoverDecision:
    """Decide whether a proposed rebalance fits the monthly turnover cap.

    The proposed move ``current -> proposed`` is costed in one-sided turnover.
    If it fits inside the remaining monthly budget (the cap less turnover
    already incurred over the trailing ``periods_per_month - 1`` periods of
    ``weight_history``) the move is allowed unchanged.  Otherwise it is scaled
    down proportionally so the executed turnover exactly equals the remaining
    budget, moving the book along the straight line from ``current`` toward
    ``proposed``::

        scaled = current + (proposed - current) * (remaining / proposed_turnover)

    Parameters
    ----------
    current_weights:
        Mapping of asset -> current NAV-fraction weight.
    proposed_weights:
        Mapping of asset -> desired NAV-fraction weight after rebalance.
    weight_history:
        Wide DataFrame of realised weights used to compute the budget already
        consumed this month.  May be empty (no prior trading).
    config:
        Turnover configuration.

    Returns
    -------
    TurnoverDecision
        Decision with ``allowed`` flag, proposed/used/remaining turnover, the
        weights to actually trade to, and a machine-readable ``reason``.
    """
    cur = pd.Series(dict(current_weights), dtype=float)
    prop = pd.Series(dict(proposed_weights), dtype=float)
    idx = cur.index.union(prop.index)
    cur = cur.reindex(idx).fillna(0.0)
    prop = prop.reindex(idx).fillna(0.0)

    proposed_turnover = _one_sided_turnover(cur, prop)
    used = _used_budget(weight_history, config=config)
    remaining = max(0.0, config.max_monthly_turnover - used)

    # No move requested: nothing to trade, trivially allowed.
    if proposed_turnover == 0.0:
        return TurnoverDecision(
            allowed=True,
            proposed_turnover=0.0,
            used_budget=used,
            remaining_budget=remaining,
            scaled_weights={k: float(v) for k, v in prop.items()},
            reason="no_trade",
        )

    # Full move fits the remaining budget.
    if proposed_turnover <= remaining:
        return TurnoverDecision(
            allowed=True,
            proposed_turnover=proposed_turnover,
            used_budget=used,
            remaining_budget=remaining,
            scaled_weights={k: float(v) for k, v in prop.items()},
            reason="within_budget",
        )

    # Budget exhausted: stay put.
    if remaining == 0.0:
        return TurnoverDecision(
            allowed=False,
            proposed_turnover=proposed_turnover,
            used_budget=used,
            remaining_budget=0.0,
            scaled_weights={k: float(v) for k, v in cur.items()},
            reason="no_budget",
        )

    # Partial move: scale proportionally toward proposed.
    scale = remaining / proposed_turnover
    scaled = cur + (prop - cur) * scale
    return TurnoverDecision(
        allowed=False,
        proposed_turnover=proposed_turnover,
        used_budget=used,
        remaining_budget=remaining,
        scaled_weights={k: float(v) for k, v in scaled.items()},
        reason="breach_scaled",
    )


# ---------------------------------------------------------------------------
# Cost budget
# ---------------------------------------------------------------------------


def cost_budget_ratio(expected_gross_alpha: float, expected_costs: float) -> float:
    """Return the fraction of expected gross alpha consumed by costs.

    Parameters
    ----------
    expected_gross_alpha:
        Expected gross alpha (per-period decimal return *before* costs).
    expected_costs:
        Expected trading costs in the same per-period decimal units.  Must be
        ``>= 0``.

    Returns
    -------
    float
        ``expected_costs / expected_gross_alpha``.  When gross alpha is
        ``<= 0`` there is no positive alpha to spend, so the ratio is
        ``inf`` (any cost is unaffordable) -- unless costs are also ``0``, in
        which case it is ``0.0``.

    Raises
    ------
    ValueError
        If ``expected_costs`` is negative.
    """
    if expected_costs < 0:
        raise ValueError(
            f"expected_costs must be non-negative; got {expected_costs}"
        )
    if expected_gross_alpha <= 0:
        return 0.0 if expected_costs == 0 else float("inf")
    return expected_costs / expected_gross_alpha


def cost_budget_ok(
    expected_gross_alpha: float,
    expected_costs: float,
    *,
    config: TurnoverConfig = _DEFAULT_TURNOVER_CONFIG,
) -> bool:
    """Whether expected costs fit the alpha-share budget.

    Enforces::

        expected_costs <= max_cost_alpha_ratio * expected_gross_alpha

    which is equivalent to ``cost_budget_ratio(...) <= max_cost_alpha_ratio``.

    Parameters
    ----------
    expected_gross_alpha:
        Expected gross alpha (per-period decimal return before costs).
    expected_costs:
        Expected trading costs in the same units (``>= 0``).
    config:
        Turnover configuration supplying ``max_cost_alpha_ratio``.

    Returns
    -------
    bool
        ``True`` if costs are within budget.  When gross alpha is ``<= 0`` the
        result is ``True`` only if costs are exactly ``0``.
    """
    return cost_budget_ratio(expected_gross_alpha, expected_costs) <= (
        config.max_cost_alpha_ratio
    )


# ---------------------------------------------------------------------------
# Edge-vs-cost filter
# ---------------------------------------------------------------------------


def edge_exceeds_cost(
    expected_edge: float,
    expected_cost: float,
    *,
    config: TurnoverConfig = _DEFAULT_TURNOVER_CONFIG,
) -> bool:
    """Whether a trade's expected edge beats the cost multiple.

    A trade clears the filter when::

        expected_edge > min_edge_cost_multiple * expected_cost

    Parameters
    ----------
    expected_edge:
        Expected edge of the trade (per-period decimal return before costs).
    expected_cost:
        Expected cost of the trade in the same units (``>= 0``).
    config:
        Turnover configuration supplying ``min_edge_cost_multiple``.

    Returns
    -------
    bool
        ``True`` if the edge strictly exceeds ``min_edge_cost_multiple`` times
        the cost.

    Raises
    ------
    ValueError
        If ``expected_cost`` is negative.
    """
    if expected_cost < 0:
        raise ValueError(
            f"expected_cost must be non-negative; got {expected_cost}"
        )
    return expected_edge > config.min_edge_cost_multiple * expected_cost


def filter_trades_by_edge(
    edges: pd.Series,
    costs: pd.Series,
    *,
    config: TurnoverConfig = _DEFAULT_TURNOVER_CONFIG,
) -> pd.Series:
    """Vectorised per-asset edge-vs-cost filter.

    Parameters
    ----------
    edges:
        Series of expected edges indexed by asset (per-period decimal units).
    costs:
        Series of expected costs indexed by asset, in the same units.  Must be
        aligned to (have the same index as) ``edges`` and be non-negative.
    config:
        Turnover configuration supplying ``min_edge_cost_multiple``.

    Returns
    -------
    pandas.Series
        Boolean Series, ``True`` where ``edge > min_edge_cost_multiple * cost``,
        indexed like ``edges``.

    Raises
    ------
    ValueError
        If the two Series are not index-aligned, or any cost is negative.
    """
    if not edges.index.equals(costs.index):
        raise ValueError("edges and costs must share the same index")
    aligned_costs = costs.astype(float)
    if (aligned_costs < 0).any():
        raise ValueError("all costs must be non-negative")
    threshold = config.min_edge_cost_multiple * aligned_costs
    return (edges.astype(float) > threshold).astype(bool)
