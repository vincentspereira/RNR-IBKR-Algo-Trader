"""Bid-ask spread estimators from OHLCV data (Phase 5.E microstructure).

This module implements two classical bid-ask spread proxies that can be
estimated from daily OHLCV bars, without requiring trade-level tick data or
Level-2 order book data.

Module overview
---------------
1. ``SpreadConfig``           -- frozen DTO capturing rolling-window parameters.
2. ``roll_spread``            -- Roll (1984) implied spread via serial price-change
                                 covariance.
3. ``corwin_schultz_spread``  -- Corwin-Schultz (2012) high-low spread estimator.

Mathematical references
-----------------------
Roll (1984) implied spread
    Assume the observed price P_t = M_t + q_t * s/2 where M_t is the efficient
    (random-walk) midprice and q_t in {-1, +1} is the trade direction (i.e.
    whether the trade hits the ask or the bid).  The first-order autocovariance
    of price changes is:

        cov(dP_t, dP_{t-1}) = -( s/2 )^2

    when the efficient price has no serial correlation.  Solving for s:

        s = 2 * sqrt( -cov(dP_t, dP_{t-1}) )

    When the sample covariance is non-negative (which can happen due to noise or
    a trending efficient price), the square root is undefined.  The convention
    adopted here (per de Jong & Rindi 2009, pp. 68-70) is to return NaN for
    those observations rather than forcing zero, so the caller can distinguish
    ``no negative autocovariance'' from ``zero spread''.

Corwin-Schultz (2012) high-low spread estimator
    Uses the log high-low ratio over single-day and two-day windows to separate
    the variance component (which grows with the window) from the spread
    component (which is constant per trade).  Define:

        beta = E[ (ln H_t/L_t)^2 + (ln H_{t+1}/L_{t+1})^2 ]
             = (single-day) squared log HL ratio summed over two consecutive days.

        gamma = (ln max(H_t,H_{t+1}) / min(L_t,L_{t+1}))^2
             = squared log HL ratio over the two-day window.

    The estimator (Corwin & Schultz eq. 12) is:

        alpha = ( sqrt(2*beta) - sqrt(beta) ) / ( 3 - 2*sqrt(2) )
                 - sqrt( gamma / (3 - 2*sqrt(2)) )

        spread = 2 * ( exp(alpha) - 1 ) / ( 1 + exp(alpha) )

    When alpha is negative (also possible due to noise), the paper recommends
    setting spread = 0.  This implementation sets the result to 0 in that case,
    with NaN only when the input prices themselves are non-positive or NaN.

References
----------
Roll, R. (1984). "A Simple Implicit Measure of the Effective Bid-Ask Spread
    in an Efficient Market." Journal of Finance, 39(4), 1127-1139.

Corwin, S.A. & Schultz, P. (2012). "A Simple Way to Estimate Bid-Ask Spreads
    from Daily High and Low Prices." Journal of Finance, 67(2), 719-760.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

__all__ = [
    "SpreadConfig",
    "roll_spread",
    "corwin_schultz_spread",
]

# ---------------------------------------------------------------------------
# Configuration DTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SpreadConfig:
    """Parameters shared by the rolling spread estimators.

    Attributes
    ----------
    window:
        Rolling window length in bars used to estimate the serial covariance
        (Roll) or to smooth the Corwin-Schultz estimate.  Must be >= 2.
    min_periods:
        Minimum number of non-NaN observations required within the window for
        an output value to be produced.  Defaults to ``window``.  Must be >= 2.
    """

    window: int = 60
    min_periods: int | None = None

    def __post_init__(self) -> None:
        if self.window < 2:
            raise ValueError(f"window must be >= 2, got {self.window}")
        effective_min = self.min_periods if self.min_periods is not None else self.window
        if effective_min < 2:
            raise ValueError(f"min_periods must be >= 2, got {self.min_periods}")
        if effective_min > self.window:
            raise ValueError(
                f"min_periods ({self.min_periods}) must be <= window ({self.window})"
            )

    @property
    def effective_min_periods(self) -> int:
        return self.min_periods if self.min_periods is not None else self.window


# ---------------------------------------------------------------------------
# Roll (1984) implied spread
# ---------------------------------------------------------------------------


def roll_spread(
    close: pd.Series,
    *,
    window: int = 60,
    min_periods: int | None = None,
) -> pd.Series:
    """Estimate the effective bid-ask spread using Roll (1984).

    Computes the rolling first-order serial covariance of close-to-close price
    changes and converts it to the implied spread:

        spread_t = 2 * sqrt( -cov(dP_t, dP_{t-1}) )

    where the covariance is estimated over a rolling window.  When the
    estimated covariance is >= 0 (i.e. no negative autocovariance in the
    window), the output is NaN for that observation -- this is the documented
    convention (see module docstring) indicating that Roll's assumption is
    violated in that sample; it is distinct from a zero spread.

    The first ``window`` observations are NaN due to the rolling warm-up, and
    the very first price-change observation is also NaN by construction.

    Parameters
    ----------
    close:
        Series of closing prices (must be positive; NaN is propagated).
    window:
        Rolling window length in bars.  Must be >= 2.
    min_periods:
        Minimum observations required in the window.  Defaults to ``window``
        (strict).  Must be >= 2 and <= ``window``.

    Returns
    -------
    pd.Series
        Estimated spread series indexed the same as ``close``.
        Values are >= 0 or NaN.  NaN means either (a) insufficient history or
        (b) the sample autocovariance was non-negative (per Roll's model,
        the spread is then 0 or undefined).

    Raises
    ------
    ValueError
        If ``window < 2`` or ``min_periods`` is out of range.
    """
    cfg = SpreadConfig(window=window, min_periods=min_periods)
    mp = cfg.effective_min_periods

    prices = close.astype(float)
    dp = prices.diff()  # dP_t = P_t - P_{t-1}; index-0 is NaN by definition

    dp_arr = dp.to_numpy(dtype=float)
    n = len(dp_arr)

    result = np.full(n, np.nan, dtype=float)

    # Rolling covariance of dp[t] and dp[t-1] requires at least 2 data points
    # (one pair).  We use an expanding-pair view: at each t, collect pairs
    # (dp[i], dp[i-1]) for i in [t-window+1, t] and compute their covariance.
    for t in range(window - 1, n):
        start = t - window + 1
        y = dp_arr[start : t + 1]       # dp_t  values in window (shape window)
        x = dp_arr[start - 1 : t]       # dp_{t-1} values (one step earlier)
        # Both slices must exist and be the same length
        if len(x) < mp or len(y) < mp:
            continue
        # Find valid pairs: both elements finite
        valid = np.isfinite(x) & np.isfinite(y)
        n_valid = int(valid.sum())
        if n_valid < mp:
            continue
        xv = x[valid]
        yv = y[valid]
        # Sample covariance (ddof=1 is conventional; Roll uses population but
        # sample is standard in rolling estimation with finite windows)
        cov_val = float(np.cov(xv, yv, ddof=1)[0, 1])
        if cov_val < 0.0:
            result[t] = 2.0 * np.sqrt(-cov_val)
        # else: result stays NaN (non-negative covariance; see docstring)

    return pd.Series(result, index=close.index, name="roll_spread")


# ---------------------------------------------------------------------------
# Corwin-Schultz (2012) high-low spread estimator
# ---------------------------------------------------------------------------


def corwin_schultz_spread(
    high: pd.Series,
    low: pd.Series,
) -> pd.Series:
    """Estimate the bid-ask spread using Corwin & Schultz (2012).

    Computes the spread at each bar t using bars t-1 and t (a two-day rolling
    window per the paper).  The result is a per-observation spread estimate;
    no additional smoothing window is applied -- callers may smooth with a
    rolling mean if desired.

    The formulas (Corwin & Schultz 2012, eq. 12) are:

        beta_t   = (ln H_{t-1}/L_{t-1})^2 + (ln H_t/L_t)^2
        gamma_t  = (ln max(H_{t-1},H_t) / min(L_{t-1},L_t))^2
        alpha_t  = ( sqrt(2*beta_t) - sqrt(beta_t) ) / (3 - 2*sqrt(2))
                   - sqrt( gamma_t / (3 - 2*sqrt(2)) )
        spread_t = 2*(exp(alpha_t) - 1) / (1 + exp(alpha_t))

    When alpha_t <= 0 (a boundary case the paper acknowledges as noise),
    spread_t = 0.  When any input price is <= 0 or NaN, spread_t = NaN.

    The first observation (index 0) is always NaN because it requires a
    previous bar.

    Parameters
    ----------
    high:
        Series of daily high prices (must be positive; NaN is propagated).
    low:
        Series of daily low prices (must be positive, <= high; NaN is
        propagated).

    Returns
    -------
    pd.Series
        Per-bar spread estimates in [0, 1) or NaN.
        Index matches ``high`` and ``low``.

    Raises
    ------
    ValueError
        If ``high`` and ``low`` have different lengths or indices.
    """
    if len(high) != len(low):
        raise ValueError("high and low must have the same length")
    if not high.index.equals(low.index):
        raise ValueError("high and low must share the same index")

    h = high.astype(float).to_numpy()
    lo = low.astype(float).to_numpy()
    n = len(h)

    result = np.full(n, np.nan, dtype=float)

    # Precompute log-HL ratios per bar; NaN where prices are invalid
    with np.errstate(divide="ignore", invalid="ignore"):
        log_hl = np.where(
            (np.isfinite(h) & np.isfinite(lo) & (h > 0.0) & (lo > 0.0) & (h >= lo)),
            np.log(h / lo),
            np.nan,
        )

    # Constant: 3 - 2*sqrt(2)
    denom = 3.0 - 2.0 * np.sqrt(2.0)

    for t in range(1, n):
        lhl_prev = log_hl[t - 1]
        lhl_curr = log_hl[t]
        # log_hl is NaN whenever h or lo is non-positive or NaN; only proceed
        # when both consecutive per-bar ratios are finite.
        if not np.isfinite(lhl_prev) or not np.isfinite(lhl_curr):
            continue

        beta = lhl_prev**2 + lhl_curr**2

        h_two = max(h[t - 1], h[t])
        l_two = min(lo[t - 1], lo[t])
        gamma = np.log(h_two / l_two) ** 2

        alpha = (np.sqrt(2.0 * beta) - np.sqrt(beta)) / denom - np.sqrt(gamma / denom)

        if alpha <= 0.0:
            result[t] = 0.0
        else:
            exp_a = np.exp(alpha)
            result[t] = 2.0 * (exp_a - 1.0) / (1.0 + exp_a)

    return pd.Series(result, index=high.index, name="cs_spread")
