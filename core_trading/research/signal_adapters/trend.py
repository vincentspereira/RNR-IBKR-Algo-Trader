"""Phase 5 signal-evaluation adapter: local-linear-trend (trend-following).

Wires the state-space local-linear-trend smoother
(:func:`~core_trading.signals.filters.state_space.fit_local_linear_trend`) through
the evaluation gate (:mod:`~core_trading.research.signal_evaluation`) to close the
per-signal Definition-of-Done items 3-5 (backtest run + deflated Sharpe +
PROMOTE/ARCHIVE verdict) for a TREND-FOLLOWING signal.

How it works
------------
The Kalman smoother estimates a stochastic slope nu_t at each bar.  A
rolling re-fit on a look-ahead-free trailing window of length ``lookback``
produces a sequence of slope estimates; the final element of each trailing
window's smoothed-state array is the slope at the last observed bar.  Those
slope estimates are standardised by their own trailing standard deviation to
produce a dimensionless directional signal.  A deadband filter converts the
signal to a {-1, 0, +1} position: long above the deadband, short below,
flat inside.  The threshold magnitude (``deadband``) is the one tunable
parameter swept by the evaluation grid.

The "compute expensive path once, sweep cheap threshold" pattern mirrors the
OU mean-reversion adapter in :mod:`~core_trading.research.signal_evaluation`:
the rolling re-fit is performed once in :func:`build_trend_weight_fn`; the
returned :data:`WeightRule` closure only applies the cheap threshold logic,
so sweeping ``deadband`` over :func:`trend_grid` reuses the single computed
signal series.

Mathematical references
-----------------------
* Harvey, A.C. (1989). "Forecasting, Structural Time Series Models and the
  Kalman Filter." Cambridge University Press.  Section 2.4 (local linear
  trend model) and Chapter 4 (forecasting).
* Trend-following / time-series momentum: Moskowitz, T., Ooi, Y.H. and
  Pedersen, L.H. (2012). "Time Series Momentum." Journal of Financial
  Economics 104(2), 228-250.
* Standardisation by rolling standard deviation: standard feature-engineering
  practice in signal research (Lopez de Prado 2018, ch. 17).
"""
from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from core_trading.research.signal_evaluation import WeightRule, positions_to_weights
from core_trading.signals.filters.state_space import fit_local_linear_trend

__all__ = [
    "trend_slope_series",
    "trend_positions",
    "build_trend_weight_fn",
    "trend_grid",
]


# ---------------------------------------------------------------------------
# Step 1 -- look-ahead-free slope series (the expensive path)
# ---------------------------------------------------------------------------


def trend_slope_series(
    close: pd.Series,
    *,
    lookback: int = 150,
    refit_every: int = 10,
) -> pd.DataFrame:
    """Look-ahead-free local-linear-trend slope of a price series.

    At each timestamp ``t`` (warmup permitting) the local-linear-trend model
    is fitted on the trailing window ``close[t - lookback + 1 : t + 1]`` via
    :func:`~core_trading.signals.filters.state_space.fit_local_linear_trend`.
    Taking ``result.trend[-1]`` -- the smoothed slope at the *last* bar of
    that window -- uses only data up to and including ``t``, so the estimate
    is look-ahead-free.

    The raw slope is in price-change units per bar and varies in magnitude
    across different price levels; to produce a scale-free directional signal
    each slope estimate is divided by the expanding standard deviation of all
    slope estimates seen so far (computed only from data up to ``t``).

    To keep the rolling estimation cheap the model is re-fitted every
    ``refit_every`` bars; the stale *past* slope estimate is carried between
    refits.  The standardised signal is recomputed on every bar because it
    uses the up-to-date expanding standard deviation.

    Parameters
    ----------
    close:
        Price series.
    lookback:
        Length of the trailing estimation window.  Recommended >= 60;
        must be >= 30.
    refit_every:
        Re-fit the state-space model every this many bars (>= 1).  Higher
        values are faster but produce coarser slope tracking.

    Returns
    -------
    pd.DataFrame
        Columns ``raw_slope`` and ``signal`` indexed like ``close``; both are
        NaN during the warmup and the first bar of valid data (no history yet
        for the expanding std).

    Raises
    ------
    ValueError
        If ``lookback < 30`` or ``refit_every < 1``.
    """
    if lookback < 30:
        raise ValueError("lookback must be >= 30 (recommended >= 60)")
    if refit_every < 1:
        raise ValueError("refit_every must be >= 1")

    values = np.asarray(close.to_numpy(), dtype=float)
    n = values.size
    raw_slope = np.full(n, np.nan, dtype=float)
    signal = np.full(n, np.nan, dtype=float)

    # Stale slope carried between refits.
    current_slope = float("nan")
    bars_since_fit = refit_every  # force a fit on the first eligible bar

    for t in range(lookback - 1, n):
        if bars_since_fit >= refit_every:
            window = pd.Series(values[t - lookback + 1 : t + 1])
            result = fit_local_linear_trend(window)
            # trend[-1] is the RTS-smoothed slope at the last bar of the
            # trailing window, using only data <= t.  Look-ahead-free.
            current_slope = float(result.trend[-1])
            bars_since_fit = 0
        else:
            bars_since_fit += 1

        raw_slope[t] = current_slope

        # Expanding standard deviation of raw_slope up to and including t.
        # Only use finite values (skip initial NaNs).
        valid_slopes = raw_slope[: t + 1]
        finite_mask = np.isfinite(valid_slopes)
        n_finite = int(np.sum(finite_mask))
        if n_finite >= 2:
            expanding_std = float(np.std(valid_slopes[finite_mask], ddof=1))
            if expanding_std > 0.0:
                signal[t] = current_slope / expanding_std
            # else leave signal[t] as NaN (all-same slope history)

    return pd.DataFrame({"raw_slope": raw_slope, "signal": signal}, index=close.index)


# ---------------------------------------------------------------------------
# Step 2 -- deadband position rule (cheap, swept by the grid)
# ---------------------------------------------------------------------------


def trend_positions(
    signal: pd.Series,
    *,
    deadband: float = 0.5,
) -> pd.Series:
    """Convert a standardised slope signal into a long / flat / short position.

    The trend-following rule: go long when the slope signal is strongly
    positive (signal > deadband), go short when strongly negative
    (signal < -deadband), and stay flat inside the deadband.  NaN signal
    values produce a flat (0.0) position.

    Parameters
    ----------
    signal:
        Standardised slope values (output of :func:`trend_slope_series`).
    deadband:
        Symmetric threshold; must be >= 0.

    Returns
    -------
    pd.Series
        Position in ``{-1.0, 0.0, 1.0}`` indexed like ``signal``.

    Raises
    ------
    ValueError
        If ``deadband < 0``.
    """
    if deadband < 0.0:
        raise ValueError("deadband must be >= 0")

    sig = np.asarray(signal.to_numpy(), dtype=float)
    positions = np.where(
        np.isnan(sig),
        0.0,
        np.where(sig > deadband, 1.0, np.where(sig < -deadband, -1.0, 0.0)),
    )
    return pd.Series(positions.astype(float), index=signal.index, name="position")


# ---------------------------------------------------------------------------
# Step 3 -- weight-rule factory (computes signal once, sweeps threshold)
# ---------------------------------------------------------------------------


def build_trend_weight_fn(
    close: pd.Series,
    *,
    symbol: str = "SIM",
    lookback: int = 150,
    refit_every: int = 10,
) -> WeightRule:
    """Build a :data:`WeightRule` for local-linear-trend trend-following.

    The expensive look-ahead-free slope series is computed *once* here; the
    returned rule only applies the (cheap) deadband threshold from ``params``,
    so a parameter sweep over deadband values -- as fed to
    :func:`~core_trading.research.signal_evaluation.evaluate_signal` -- reuses
    the same slope series.  Each configuration must supply ``deadband``.

    Parameters
    ----------
    close:
        Price series used to compute the slope signal.
    symbol:
        Symbol label; must match the label used in
        :func:`~core_trading.research.signal_evaluation.price_panel_from_series`.
    lookback:
        Trailing window length passed to :func:`trend_slope_series`.
    refit_every:
        Refit cadence passed to :func:`trend_slope_series`.

    Returns
    -------
    WeightRule
        A ``(panel, params) -> weights`` callable.  ``params`` must contain
        the key ``"deadband"`` (float >= 0).
    """
    slope_df = trend_slope_series(close, lookback=lookback, refit_every=refit_every)
    sig_series = slope_df["signal"]

    def weight_rule(panel: pd.DataFrame, params: Mapping[str, float]) -> pd.DataFrame:
        positions = trend_positions(sig_series, deadband=float(params["deadband"]))
        # Defensively reindex positions onto the panel's per-symbol timestamp
        # index.  The slope was computed from ``close`` whose index may differ
        # from the panel's; the two share the same chronological observations
        # in the same order, so a positional (numpy-array) reindex is correct
        # and prevents silent all-zero misalignment.
        sym_index = panel.xs(symbol, level="symbol").index
        if len(sym_index) == len(positions):
            positions = pd.Series(
                positions.to_numpy(), index=sym_index, name="position"
            )
        return positions_to_weights(positions, symbol=symbol)

    return weight_rule


# ---------------------------------------------------------------------------
# Step 4 -- parameter grid
# ---------------------------------------------------------------------------


def trend_grid(
    *,
    deadbands: tuple[float, ...] = (0.0, 0.25, 0.5, 0.75, 1.0),
) -> list[dict[str, float]]:
    """Standard deadband parameter grid for the trend-following sweep.

    Parameters
    ----------
    deadbands:
        Sequence of deadband thresholds to evaluate.  Must contain >= 1
        element; the default (0.0, 0.25, 0.5, 0.75, 1.0) gives 5 trials,
        which is sufficient for a meaningful deflated-Sharpe discount.

    Returns
    -------
    list[dict[str, float]]
        One configuration dict per deadband value.
    """
    return [{"deadband": float(d)} for d in deadbands]
