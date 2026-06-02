"""Phase 5 signal-evaluation adapter: cross-sectional momentum (multi-asset long/short).

Wires the cross-sectional momentum factor
(:mod:`~core_trading.signals.factors.momentum`, master plan 5.C.4) through the
evaluation gate (:mod:`~core_trading.research.signal_evaluation`) to close the
per-signal Definition-of-Done items 3-5 (backtest run + deflated Sharpe +
PROMOTE/ARCHIVE verdict) for a CROSS-SECTIONAL signal.

This is the FIRST multi-asset adapter. Unlike the single-instrument trend /
forecast / OU adapters -- whose weight rule emits a one-column ``{-1,0,+1}``
position -- the momentum rule emits a *dollar-neutral long/short weight panel*:
one column per symbol, each row summing to zero (long the top quantile, short the
bottom quantile of the cross-section). The backtest engine consumes that wide
weight frame directly (it reindexes weights onto the unstacked close panel), so
the engine earns ``sum_i w_{i,t-1} * r_{i,t}`` -- the look-ahead-free long/short
return -- with no per-symbol alignment gymnastics.

How it works
------------
The expensive look-ahead-free path -- formation-window momentum scores,
volatility scaling, and cross-sectional z-scoring -- is computed *once* in
:func:`build_momentum_weight_fn`. The returned :data:`WeightRule` closure only
applies the cheap long/short construction at a given ``quantile``, so a sweep
over :func:`momentum_grid` reuses the single computed z-score panel. This mirrors
the "compute expensive path once, sweep cheap threshold" pattern of the OU
mean-reversion adapter in :mod:`~core_trading.research.signal_evaluation`; here
the swept knob is the long/short ``quantile`` rather than an entry threshold.

Mathematical references
-----------------------
* Jegadeesh, N. & Titman, S. (1993). "Returns to Buying Winners and Selling
  Losers." Journal of Finance 48(1), 65-91.
* Moskowitz, T., Ooi, Y.H. & Pedersen, L.H. (2012). "Time Series Momentum."
  Journal of Financial Economics 104(2), 228-250 (the vol-scaling).
* Deflated Sharpe gate: Bailey, D. & Lopez de Prado, M. (2014), as applied by
  :mod:`~core_trading.research.signal_evaluation`.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence

import pandas as pd

from core_trading.research.signal_evaluation import WeightRule
from core_trading.signals.factors.momentum import (
    MomentumConfig,
    cross_sectional_zscore,
    long_short_weights,
    momentum_scores,
    risk_adjusted_momentum,
)

__all__ = [
    "momentum_score_panel",
    "momentum_weights",
    "build_momentum_weight_fn",
    "momentum_grid",
]


# ---------------------------------------------------------------------------
# Step 1 -- look-ahead-free cross-sectional z-score panel (the expensive path)
# ---------------------------------------------------------------------------


def momentum_score_panel(
    prices: pd.DataFrame,
    config: MomentumConfig,
    *,
    risk_adjusted: bool = True,
) -> pd.DataFrame:
    """Look-ahead-free cross-sectional momentum z-score panel.

    Computes formation-window momentum scores (optionally volatility-scaled per
    Moskowitz-Ooi-Pedersen) and standardises them across the cross-section at
    each bar. The score at bar ``t`` for asset ``i`` uses only prices at or
    before ``t`` (see :func:`~core_trading.signals.factors.momentum.momentum_scores`),
    so the panel is look-ahead-free.

    Parameters
    ----------
    prices:
        Wide price panel: ascending ``DatetimeIndex`` rows, one column per
        symbol, strictly positive values (NaN tolerated for missing data).
    config:
        :class:`~core_trading.signals.factors.momentum.MomentumConfig` carrying
        ``lookback`` / ``skip`` / ``vol_window``.
    risk_adjusted:
        When ``True`` (default) scale scores by trailing realised volatility;
        when ``False`` use raw formation returns.

    Returns
    -------
    pd.DataFrame
        Cross-sectionally standardised score panel, same index and columns as
        ``prices``; NaN during warmup and where a cross-section is degenerate.
    """
    if risk_adjusted:
        scores = risk_adjusted_momentum(
            prices,
            lookback=config.lookback,
            skip=config.skip,
            vol_window=config.vol_window,
        )
    else:
        scores = momentum_scores(prices, lookback=config.lookback, skip=config.skip)
    return cross_sectional_zscore(scores)


# ---------------------------------------------------------------------------
# Step 2 -- dollar-neutral long/short construction (cheap, swept by the grid)
# ---------------------------------------------------------------------------


def momentum_weights(scores: pd.DataFrame, *, quantile: float = 0.2) -> pd.DataFrame:
    """Dollar-neutral long/short target weights from a z-score panel.

    Thin wrapper over
    :func:`~core_trading.signals.factors.momentum.long_short_weights`: longs the
    top ``quantile`` and shorts the bottom ``quantile`` of each cross-section,
    equal-weighted within each leg so the long leg sums to +1, the short leg to
    -1 (net 0, gross 2). This is the cheap step swept by :func:`momentum_grid`.
    """
    return long_short_weights(scores, quantile=quantile)


# ---------------------------------------------------------------------------
# Step 3 -- weight-rule factory (computes z-scores once, sweeps quantile)
# ---------------------------------------------------------------------------


def build_momentum_weight_fn(
    prices: pd.DataFrame,
    *,
    config: MomentumConfig,
    risk_adjusted: bool = True,
) -> WeightRule:
    """Build a :data:`WeightRule` for cross-sectional momentum long/short.

    The expensive look-ahead-free z-score panel is computed *once* here; the
    returned rule only applies the cheap long/short construction from ``params``,
    so a sweep over the long/short ``quantile`` -- as fed to
    :func:`~core_trading.research.signal_evaluation.evaluate_signal` -- reuses the
    single computed z-score panel. Each configuration must supply ``"quantile"``.

    Parameters
    ----------
    prices:
        Wide price panel used to compute the z-scores; the same frame must back
        the OHLCV panel passed to the gate (see
        :func:`~core_trading.research.signal_evaluation.price_panel_from_frame`).
    config:
        Momentum parameters.
    risk_adjusted:
        Forwarded to :func:`momentum_score_panel`.

    Returns
    -------
    WeightRule
        A ``(panel, params) -> weights`` callable. ``params`` must contain the
        key ``"quantile"`` (float in ``(0, 1)``).
    """
    z = momentum_score_panel(prices, config, risk_adjusted=risk_adjusted)

    def weight_rule(panel: pd.DataFrame, params: Mapping[str, float]) -> pd.DataFrame:
        weights = momentum_weights(z, quantile=float(params["quantile"]))
        # Defensively reindex onto the panel's own (sorted, unique) timestamp
        # index. The z-scores were computed from ``prices`` whose index may
        # differ from the panel's; the two are the same chronological rows in
        # the same order, so a positional reindex is correct and prevents a
        # silent all-zero misalignment when the engine reindexes the weights.
        ts_index = panel.index.get_level_values("timestamp").unique().sort_values()
        if len(ts_index) == len(weights):
            weights = pd.DataFrame(
                weights.to_numpy(), index=ts_index, columns=weights.columns
            )
        return weights

    return weight_rule


# ---------------------------------------------------------------------------
# Step 4 -- parameter grid
# ---------------------------------------------------------------------------


def momentum_grid(
    *,
    quantiles: Sequence[float] = (0.1, 0.2, 0.3, 0.4),
) -> list[dict[str, float]]:
    """Standard long/short quantile grid for the cross-sectional momentum sweep.

    Parameters
    ----------
    quantiles:
        Long/short leg fractions to evaluate. Must contain >= 1 element; the
        default (0.1, 0.2, 0.3, 0.4) gives 4 trials, enough for a meaningful
        deflated-Sharpe discount.

    Returns
    -------
    list[dict[str, float]]
        One configuration dict per quantile.
    """
    return [{"quantile": float(q)} for q in quantiles]
