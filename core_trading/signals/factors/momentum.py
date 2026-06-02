"""Cross-sectional momentum factor signal (Phase 5.C.4).

This module is the canonical implementation of cross-sectional momentum for the
IBKR Algo Trader quant library.  It operates on MULTI-ASSET PANELS -- a
different data shape from the single-series signal modules in the stochastic
and pairs packages.

Cross-sectional panel convention
---------------------------------
A *price panel* is a ``pandas.DataFrame`` whose:
  - Index  : ascending ``DatetimeIndex`` (timestamps / bars, one row per bar).
  - Columns: one column per asset symbol (strings); values are prices (floats).
  - NaN cells are permitted -- an asset may not yet be listed, or data may be
    missing for a given bar.  All ranking and scoring operations at each
    timestamp use only the assets that have a valid (non-NaN) score at that
    timestamp.  NaN is propagated forward into any output panel for the same
    (timestamp, asset) pair.

A *returns panel* and a *scores panel* follow the same shape convention.

Module overview
---------------
1. ``MomentumConfig``           -- frozen DTO capturing the signal parameters.
2. ``momentum_scores``          -- raw cross-sectional momentum per asset per bar.
3. ``risk_adjusted_momentum``   -- momentum scaled by trailing realized vol
                                   (Moskowitz-Ooi-Pedersen vol-scaling).
4. ``cross_sectional_zscore``   -- row-wise standardisation across assets.
5. ``long_short_weights``       -- dollar-neutral long/short target weights.
6. ``momentum_portfolio``       -- convenience pipeline: prices -> weights.

Mathematical references
-----------------------
Raw cross-sectional momentum score at time t for asset i:
    score_{i,t} = price_{i, t-skip} / price_{i, t-lookback} - 1

where *lookback* is the formation window length (e.g. 252 bars ~ 12 months)
and *skip* is the recency gap (e.g. 21 bars ~ 1 month) that removes the
short-term reversal effect identified by Jegadeesh & Titman (1993).
The formula is look-ahead-free: at row t we use only prices at or before t.

Risk-adjusted momentum (Moskowitz-Ooi-Pedersen vol-scaling):
    adj_score_{i,t} = score_{i,t} / sigma_{i,t}
where sigma_{i,t} is the trailing realized volatility of daily returns over
a rolling vol_window, estimated as:
    sigma_{i,t} = std( r_{i, t-vol_window+1 : t} )
computed on a look-ahead-free basis.

References:
  * Jegadeesh, N. & Titman, S. (1993). "Returns to Buying Winners and Selling
    Losers: Implications for Stock Market Efficiency."
    Journal of Finance, 48(1), 65-91.

  * Moskowitz, T., Ooi, Y.H. & Pedersen, L.H. (2012). "Time Series Momentum."
    Journal of Financial Economics, 104(2), 228-250.

  * Asness, C., Moskowitz, T. & Pedersen, L.H. (2013). "Value and Momentum
    Everywhere."
    Journal of Finance, 68(3), 929-985.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd

__all__ = [
    "MomentumConfig",
    "momentum_scores",
    "risk_adjusted_momentum",
    "cross_sectional_zscore",
    "long_short_weights",
    "momentum_portfolio",
]

# ---------------------------------------------------------------------------
# Configuration DTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MomentumConfig:
    """Parameters for the cross-sectional momentum signal.

    Attributes
    ----------
    lookback:
        Formation window in bars.  The cumulative return is computed from
        bar ``t - lookback`` to bar ``t - skip``.  Must be strictly greater
        than ``skip``.  Typical equity value: 252 (approx. 12 months daily).
    skip:
        Recency gap in bars.  The most recent ``skip`` bars are excluded from
        the return computation to avoid the short-term reversal effect.
        Must be >= 0.  Typical equity value: 21 (approx. 1 month daily).
    vol_window:
        Rolling window (in bars) used to estimate trailing realized volatility
        of returns for risk adjustment.  Must be >= 2.
        Typical equity value: 60 (approx. 3 months daily).
    """

    lookback: int
    skip: int = 21
    vol_window: int = 60

    def __post_init__(self) -> None:
        """Validate parameter consistency."""
        if self.skip < 0:
            raise ValueError(
                f"skip must be >= 0, got {self.skip}"
            )
        if self.lookback <= self.skip:
            raise ValueError(
                f"lookback ({self.lookback}) must be strictly greater than "
                f"skip ({self.skip})"
            )
        if self.vol_window < 2:
            raise ValueError(
                f"vol_window must be >= 2, got {self.vol_window}"
            )


# ---------------------------------------------------------------------------
# Core computations
# ---------------------------------------------------------------------------


def momentum_scores(
    prices: pd.DataFrame,
    *,
    lookback: int,
    skip: int = 0,
) -> pd.DataFrame:
    """Compute cross-sectional momentum scores for every (timestamp, asset).

    The momentum score at bar t for asset i is:

        score_{i,t} = price_{i, t-skip} / price_{i, t-lookback} - 1

    This captures the cumulative return over the window
    [t - lookback, t - skip] exclusive of the most recent ``skip`` bars.
    The computation is look-ahead-free: row t uses only prices at or before t.

    Rows 0 .. lookback-1 are NaN (insufficient history).
    Any (t, i) pair where ``price_{i, t-skip}`` or ``price_{i, t-lookback}``
    is NaN or non-positive produces NaN in the output.

    Parameters
    ----------
    prices:
        Price panel: DatetimeIndex rows, one column per asset symbol.
        Values must be positive prices (NaN permitted for missing data).
    lookback:
        Formation window length in bars.  Must be > skip >= 0.
    skip:
        Recency gap in bars (default 0 -- no skip).

    Returns
    -------
    pd.DataFrame
        Scores panel with the same index and columns as ``prices``.
        Values in [-1, inf) or NaN.

    Raises
    ------
    ValueError
        If lookback <= skip or skip < 0.
    """
    if skip < 0:
        raise ValueError(f"skip must be >= 0, got {skip}")
    if lookback <= skip:
        raise ValueError(
            f"lookback ({lookback}) must be strictly greater than skip ({skip})"
        )

    arr = prices.to_numpy(dtype=float)  # shape (T, N)
    T, N = arr.shape

    scores = np.full((T, N), np.nan, dtype=float)

    for t in range(lookback, T):
        p_end = arr[t - skip]       # price at t - skip   (shape N)
        p_start = arr[t - lookback] # price at t - lookback (shape N)
        # Vectorised: NaN or non-positive prices propagate NaN
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = np.where(
                (np.isfinite(p_start) & (p_start > 0.0) &
                 np.isfinite(p_end)   & (p_end   > 0.0)),
                p_end / p_start - 1.0,
                np.nan,
            )
        scores[t] = ratio

    return pd.DataFrame(scores, index=prices.index, columns=prices.columns)


def risk_adjusted_momentum(
    prices: pd.DataFrame,
    *,
    lookback: int,
    skip: int = 0,
    vol_window: int,
) -> pd.DataFrame:
    """Compute momentum scores scaled by trailing realized volatility.

    Implements the Moskowitz-Ooi-Pedersen vol-scaling:

        adj_score_{i,t} = raw_score_{i,t} / trailing_vol_{i,t}

    where trailing_vol is the rolling standard deviation of daily returns
    over ``vol_window`` bars, computed look-ahead-free (using only returns
    up to and including bar t-1, since return at t = price[t]/price[t-1]-1
    requires price[t]).

    NaN is produced when:
    - The raw momentum score is NaN.
    - trailing_vol is NaN (insufficient history) or zero.

    Parameters
    ----------
    prices:
        Price panel.  See :func:`momentum_scores` for shape convention.
    lookback:
        Formation window for momentum in bars.
    skip:
        Recency gap in bars (default 0).
    vol_window:
        Rolling window for realized volatility in bars.  Must be >= 2.

    Returns
    -------
    pd.DataFrame
        Risk-adjusted scores panel; same index and columns as ``prices``.

    Raises
    ------
    ValueError
        If lookback <= skip, skip < 0, or vol_window < 2.
    """
    if skip < 0:
        raise ValueError(f"skip must be >= 0, got {skip}")
    if lookback <= skip:
        raise ValueError(
            f"lookback ({lookback}) must be strictly greater than skip ({skip})"
        )
    if vol_window < 2:
        raise ValueError(f"vol_window must be >= 2, got {vol_window}")

    # Raw momentum scores
    raw = momentum_scores(prices, lookback=lookback, skip=skip)

    # Returns panel: simple daily returns (look-ahead-free -- ret[t] uses price[t-1]).
    # Computed via numpy diff to avoid the pandas pct_change fill_method deprecation
    # (pandas 2.1+).  ret[t] = price[t] / price[t-1] - 1.
    price_arr = prices.to_numpy(dtype=float)  # shape (T, N)
    with np.errstate(divide="ignore", invalid="ignore"):
        # diff over axis=0: shape (T-1, N); prepend a row of NaN to keep (T, N)
        raw_ret = np.empty_like(price_arr)
        raw_ret[0] = np.nan
        raw_ret[1:] = price_arr[1:] / price_arr[:-1] - 1.0
    returns = pd.DataFrame(raw_ret, index=prices.index, columns=prices.columns)

    # Trailing vol: std of returns over the past vol_window bars ending at t-1.
    # We shift returns by 1 so the window [t-vol_window, t-1] is used at row t.
    shifted_returns = returns.shift(1)
    trailing_vol = shifted_returns.rolling(window=vol_window, min_periods=vol_window).std()

    raw_arr = raw.to_numpy(dtype=float)
    vol_arr = trailing_vol.to_numpy(dtype=float)

    with np.errstate(divide="ignore", invalid="ignore"):
        adj = np.where(
            np.isfinite(vol_arr) & (vol_arr > 0.0),
            raw_arr / vol_arr,
            np.nan,
        )

    return pd.DataFrame(adj, index=prices.index, columns=prices.columns)


def cross_sectional_zscore(scores: pd.DataFrame) -> pd.DataFrame:
    """Standardise each row of the scores panel across assets.

    For each timestamp t, computes:

        z_{i,t} = (score_{i,t} - mean_cross(t)) / std_cross(t)

    where mean_cross and std_cross ignore NaN values.  Rows where all assets
    are NaN, or where the cross-sectional std is zero, produce all-NaN output.

    Parameters
    ----------
    scores:
        Scores panel: DatetimeIndex rows, one column per asset.

    Returns
    -------
    pd.DataFrame
        Z-scored panel; same index and columns as ``scores``.
    """
    arr = scores.to_numpy(dtype=float)

    # nanmean / nanstd along axis=1 (across assets, per row).
    # numpy emits RuntimeWarning: "Mean of empty slice" for all-NaN rows; that
    # is the intended behaviour (NaN output) so we suppress that specific warning
    # rather than letting it propagate and trip -W error.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        row_mean = np.nanmean(arr, axis=1, keepdims=True)  # (T, 1)
        row_std  = np.nanstd(arr,  axis=1, keepdims=True, ddof=0)  # (T, 1) -- population

    centered = arr - row_mean
    # Avoid divide-by-zero; rows with std == 0 or all-NaN -> NaN
    zero_std = (row_std == 0.0) | ~np.isfinite(row_std)
    row_std_safe = np.where(zero_std, 1.0, row_std)  # safe denominator (masked to NaN below)

    z = centered / row_std_safe
    # Mark rows that had std == 0 (all-NaN or all-identical) as NaN
    z[np.broadcast_to(zero_std, z.shape)] = np.nan

    return pd.DataFrame(z, index=scores.index, columns=scores.columns)


def long_short_weights(
    scores: pd.DataFrame,
    *,
    quantile: float = 0.2,
) -> pd.DataFrame:
    """Compute dollar-neutral long/short target weights at each timestamp.

    At each bar t:
    1. Consider only assets with a finite (non-NaN) score.
    2. Rank assets by score.
    3. Long the top ``quantile`` fraction (the winners).
    4. Short the bottom ``quantile`` fraction (the losers).
    5. Scale so that the long leg sums to exactly +1 and the short leg to -1
       (equal-weighted within each leg).  Net weight = 0, gross exposure = 2.

    If the number of assets with valid scores is too small to form both legs
    (i.e., fewer than ``ceil(1/quantile)`` valid assets, so at least one leg
    would be empty), the row output is all zeros.

    Parameters
    ----------
    scores:
        Scores panel: DatetimeIndex rows, one column per asset.
    quantile:
        Fraction of the cross-section to include in each leg (0 < quantile < 1).
        Default 0.2 (top/bottom quintile).

    Returns
    -------
    pd.DataFrame
        Weights panel; same index and columns as ``scores``.
        Row sums are 0 (or all-NaN rows produce 0 via fill with 0).

    Raises
    ------
    ValueError
        If quantile is not in (0, 1).
    """
    if not (0.0 < quantile < 1.0):
        raise ValueError(f"quantile must be in (0, 1), got {quantile}")

    arr = scores.to_numpy(dtype=float)
    T, N = arr.shape
    weights = np.zeros((T, N), dtype=float)

    for t in range(T):
        row = arr[t]
        valid_mask = np.isfinite(row)
        valid_idx = np.where(valid_mask)[0]
        n_valid = int(valid_idx.shape[0])

        if n_valid < 2:
            # Not enough assets to form even one leg
            continue

        # Number of assets per leg (at least 1)
        n_leg = max(1, int(np.floor(n_valid * quantile)))

        # Check that both legs can coexist (non-overlapping)
        if 2 * n_leg > n_valid:
            # Legs would overlap -- skip this row
            continue

        # Sort valid asset indices by score (ascending)
        sorted_by_score = valid_idx[np.argsort(row[valid_idx])]

        short_idx = sorted_by_score[:n_leg]   # bottom quantile  -> short
        long_idx  = sorted_by_score[-n_leg:]  # top quantile     -> long

        long_w  = 1.0 / float(n_leg)
        short_w = -1.0 / float(n_leg)

        weights[t, long_idx]  = long_w
        weights[t, short_idx] = short_w

    return pd.DataFrame(weights, index=scores.index, columns=scores.columns)


# ---------------------------------------------------------------------------
# Convenience pipeline
# ---------------------------------------------------------------------------


def momentum_portfolio(
    prices: pd.DataFrame,
    config: MomentumConfig,
    *,
    quantile: float = 0.2,
    risk_adjusted: bool = True,
) -> pd.DataFrame:
    """End-to-end pipeline: price panel -> target weight panel.

    Chains the following steps:
      1. Compute raw or risk-adjusted momentum scores.
      2. Cross-sectionally z-score the scores.
      3. Compute dollar-neutral long/short weights.

    Parameters
    ----------
    prices:
        Price panel.  See module docstring for shape convention.
    config:
        ``MomentumConfig`` DTO with lookback, skip, vol_window parameters.
    quantile:
        Fraction of the cross-section per leg (passed to
        :func:`long_short_weights`).
    risk_adjusted:
        If ``True`` (default), use :func:`risk_adjusted_momentum` (vol-scaled).
        If ``False``, use raw :func:`momentum_scores`.

    Returns
    -------
    pd.DataFrame
        Target weights panel; same index and columns as ``prices``.
    """
    if risk_adjusted:
        scores = risk_adjusted_momentum(
            prices,
            lookback=config.lookback,
            skip=config.skip,
            vol_window=config.vol_window,
        )
    else:
        scores = momentum_scores(
            prices,
            lookback=config.lookback,
            skip=config.skip,
        )

    z = cross_sectional_zscore(scores)
    return long_short_weights(z, quantile=quantile)
