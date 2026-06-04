"""Rebalancing triggers and turnover budgeting (Phase 6.7).

Decides WHEN to trade the book back towards its target weights, and HOW
MUCH of the gap to close, separating the trigger policy from the
optimisers that produce the targets.

Triggers
--------
* ``"calendar"``  -- rebalance every ``calendar_period`` bars regardless
  of drift (the classic monthly/quarterly policy).
* ``"threshold"`` -- rebalance only when the L1 drift
  ``sum_i |current_i - target_i|`` reaches ``threshold`` (Masters 2003:
  trade the deviation, not the calendar).
* ``"hybrid"``    -- rebalance when EITHER fires.  Empirically dominates
  either pure policy on cost-adjusted tracking error (Sun et al. 2006).

Turnover budget
---------------
When a rebalance fires, the desired trade vector is
``target - current``.  With a ``turnover_budget`` set and the desired L1
turnover above it, the trade is scaled PROPORTIONALLY:

    trades = (target - current) * turnover_budget / ||target - current||_1

which moves the book along the straight line towards the target as far
as the budget allows (partial rebalancing; Donohue & Yip 2003).  Note
the proportional rule preserves the net-exposure difference pro rata, so
a budget-limited trade between two fully-invested books remains
self-financing (trades sum to 0).

Weight drift
------------
Between rebalances, buy-and-hold weights drift with returns:

    drifted_i = w_i (1 + r_i) / sum_j w_j (1 + r_j)

(:func:`drift_weights`), which is what the trigger should be fed as
``current``.

Mathematical references
-----------------------
  * Sun, W., Fan, A., Chen, L.-W., Schouwenaars, T. & Albota, M. (2006).
    "Optimal Rebalancing for Institutional Portfolios."
    Journal of Portfolio Management, 32(2), 33-43.
  * Donohue, C. & Yip, K. (2003). "Optimal Portfolio Rebalancing with
    Transaction Costs." Journal of Portfolio Management, 29(4), 49-63.
  * Masters, S.J. (2003). "Rebalancing."
    Journal of Portfolio Management, 29(3), 52-57.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

__all__ = [
    "RebalanceConfig",
    "RebalanceDecision",
    "drift_weights",
    "rebalance_decision",
]

_ALLOWED_TRIGGERS = ("calendar", "threshold", "hybrid")


# ---------------------------------------------------------------------------
# Configuration / result DTOs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RebalanceConfig:
    """Parameters for the rebalance trigger.

    Attributes
    ----------
    trigger:
        ``"calendar"``, ``"threshold"`` or ``"hybrid"`` (see module
        docstring).
    calendar_period:
        Bars between scheduled rebalances (>= 1).
    threshold:
        L1 drift level that fires the threshold trigger (> 0).
    turnover_budget:
        Maximum L1 turnover executed per rebalance; ``None`` = trade all
        the way to target.  0 is allowed (decision fires, nothing trades
        -- useful for dry runs).
    """

    trigger: str = "hybrid"
    calendar_period: int = 21
    threshold: float = 0.05
    turnover_budget: float | None = None

    def __post_init__(self) -> None:
        """Validate parameter consistency."""
        if self.trigger not in _ALLOWED_TRIGGERS:
            raise ValueError(
                f"trigger must be one of {_ALLOWED_TRIGGERS}, got {self.trigger!r}"
            )
        if self.calendar_period < 1:
            raise ValueError(
                f"calendar_period must be >= 1, got {self.calendar_period}"
            )
        if not np.isfinite(self.threshold) or self.threshold <= 0.0:
            raise ValueError(
                f"threshold must be a finite positive float, got {self.threshold}"
            )
        if self.turnover_budget is not None and (
            not np.isfinite(self.turnover_budget) or self.turnover_budget < 0.0
        ):
            raise ValueError(
                f"turnover_budget must be a finite non-negative float, "
                f"got {self.turnover_budget}"
            )


@dataclass(frozen=True, slots=True)
class RebalanceDecision:
    """Outcome of one trigger evaluation.

    Attributes
    ----------
    should_rebalance:
        Whether any trigger fired.
    reason:
        ``"calendar"``, ``"threshold"``, ``"both"`` or ``"none"``.
    drift:
        L1 distance between current and target weights at evaluation.
    trades:
        Signed trade per asset AFTER the turnover budget (all zero when
        no trigger fired).
    new_weights:
        ``current + trades``.
    turnover:
        Executed L1 turnover ``sum(|trades|)``.
    """

    should_rebalance: bool
    reason: str
    drift: float
    trades: pd.Series = field(compare=False)
    new_weights: pd.Series = field(compare=False)
    turnover: float = 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def drift_weights(weights: pd.Series, period_returns: pd.Series) -> pd.Series:
    """Buy-and-hold weight drift over one holding period.

    Computes ``w_i (1 + r_i) / sum_j w_j (1 + r_j)`` -- the weights a
    untouched book shows after its assets earn ``period_returns``.

    Parameters
    ----------
    weights:
        Signed start-of-period weights.
    period_returns:
        Per-asset simple returns over the period, aligned to ``weights``
        (same labels, same order).

    Returns
    -------
    pd.Series
        End-of-period drifted weights (same labels).

    Raises
    ------
    ValueError
        On misalignment, non-finite inputs, a return <= -100%, or a
        degenerate portfolio whose end-of-period value is ~0 (the drift
        is undefined).
    """
    if list(weights.index) != list(period_returns.index):
        raise ValueError(
            "period_returns index must match weights index in the same order."
        )
    w = weights.to_numpy(dtype=float)
    r = period_returns.to_numpy(dtype=float)
    if not np.isfinite(w).all():
        raise ValueError("weights contain NaN or infinite values.")
    if not np.isfinite(r).all():
        raise ValueError("period_returns contain NaN or infinite values.")
    if bool((r <= -1.0).any()):
        raise ValueError("period_returns contain values <= -100%.")
    grown = w * (1.0 + r)
    total = float(grown.sum())
    if abs(total) < 1e-12:
        raise ValueError(
            "portfolio value is ~0 after the period; drifted weights are "
            "undefined (degenerate long-short book)."
        )
    return pd.Series(grown / total, index=weights.index)


def rebalance_decision(
    current: pd.Series,
    target: pd.Series,
    *,
    bars_since_rebalance: int,
    config: RebalanceConfig | None = None,
) -> RebalanceDecision:
    """Evaluate the rebalance trigger and size the trade.

    See the module docstring for trigger semantics and the proportional
    turnover budget.

    Parameters
    ----------
    current:
        Current (drifted) weights.
    target:
        Target weights from an optimiser, aligned to ``current``.
    bars_since_rebalance:
        Bars elapsed since the last executed rebalance (>= 0).
    config:
        :class:`RebalanceConfig`; ``None`` uses the defaults (hybrid,
        21 bars, 5% drift).

    Returns
    -------
    RebalanceDecision

    Raises
    ------
    ValueError
        On misalignment, non-finite inputs, or a negative
        ``bars_since_rebalance``.
    """
    cfg = config if config is not None else RebalanceConfig()
    if list(current.index) != list(target.index):
        raise ValueError(
            "target index must match current index in the same order."
        )
    cur = current.to_numpy(dtype=float)
    tgt = target.to_numpy(dtype=float)
    if not np.isfinite(cur).all():
        raise ValueError("current weights contain NaN or infinite values.")
    if not np.isfinite(tgt).all():
        raise ValueError("target weights contain NaN or infinite values.")
    if bars_since_rebalance < 0:
        raise ValueError(
            f"bars_since_rebalance must be >= 0, got {bars_since_rebalance}"
        )

    drift = float(np.abs(cur - tgt).sum())
    calendar_due = bars_since_rebalance >= cfg.calendar_period
    threshold_due = drift >= cfg.threshold

    if cfg.trigger == "calendar":
        fired = calendar_due
    elif cfg.trigger == "threshold":
        fired = threshold_due
    else:  # hybrid
        fired = calendar_due or threshold_due

    if not fired:
        zero = pd.Series(np.zeros_like(cur), index=current.index)
        return RebalanceDecision(
            should_rebalance=False,
            reason="none",
            drift=drift,
            trades=zero,
            new_weights=current.copy(),
            turnover=0.0,
        )

    if calendar_due and threshold_due:
        reason = "both"
    elif calendar_due:
        reason = "calendar"
    else:
        reason = "threshold"

    desired = tgt - cur
    desired_turnover = float(np.abs(desired).sum())
    if (
        cfg.turnover_budget is not None
        and desired_turnover > cfg.turnover_budget
        and desired_turnover > 0.0
    ):
        trades_arr = desired * (cfg.turnover_budget / desired_turnover)
    else:
        trades_arr = desired

    trades = pd.Series(trades_arr, index=current.index)
    return RebalanceDecision(
        should_rebalance=True,
        reason=reason,
        drift=drift,
        trades=trades,
        new_weights=current + trades,
        turnover=float(np.abs(trades_arr).sum()),
    )
