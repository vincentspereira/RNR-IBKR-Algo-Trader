"""Range-based realised volatility estimators from OHLC data (Phase 5.E microstructure).

This module provides five classical OHLC-based volatility estimators, each
returning a rolling annualisable volatility (standard deviation) series.  All
estimators are superior to close-to-close in terms of statistical efficiency
because they incorporate the information in the daily high-low range.

Module overview
---------------
1. ``VolConfig``             -- frozen DTO capturing window / annualisation params.
2. ``close_to_close_vol``    -- benchmark estimator (squared log-returns).
3. ``parkinson_vol``         -- Parkinson (1980) high-low range estimator.
4. ``garman_klass_vol``      -- Garman-Klass (1980) OHLC estimator.
5. ``rogers_satchell_vol``   -- Rogers-Satchell (1991) drift-robust estimator.
6. ``yang_zhang_vol``        -- Yang-Zhang (2000) overnight-gap-robust estimator.

Mathematical references
-----------------------
Let notation be:
    o = log(Open),  h = log(High),  l = log(Low),  c = log(Close)
    c_prev = log(Close_{t-1})
    Annualisation factor K = trading_periods (default 252 for daily bars).

Close-to-close (classic):
    Estimator: sigma^2 = (1/N) sum (c_i - c_{i-1})^2
    Annualised: sigma_ann = sqrt( K * sigma^2 )
    Efficiency: 1 (baseline).  Unbiased under GBM.

Parkinson (1980):
    Estimator: sigma^2 = 1/(4*ln2) * (h - l)^2
    Annualised: sigma_ann = sqrt( K * sigma^2 )
    Efficiency: ~5.2x relative to close-to-close (Parkinson 1980).
    Assumes no drift; ignores opening gaps.

Garman-Klass (1980):
    Estimator: sigma^2 = 0.5*(h-l)^2 - (2*ln2-1)*(c-o)^2
    Annualised: sigma_ann = sqrt( K * sigma^2 )
    Efficiency: ~7.4x relative to close-to-close (Garman & Klass 1980).
    Allows for drift; ignores overnight gaps.

Rogers-Satchell (1991):
    Estimator: sigma^2 = h*(h-c) + l*(l-c)   [using log-prices]
               i.e.     (h-c)*(h-o) + (l-c)*(l-o)
    Annualised: sigma_ann = sqrt( K * sigma^2 )
    Efficiency: ~8x relative to close-to-close.
    Drift-robust (consistent even when mu != 0); ignores overnight gaps.

Yang-Zhang (2000):
    Combines an overnight-gap estimator (sigma_ov), an open-to-close estimator
    (sigma_oc), and the Rogers-Satchell within-day estimator (sigma_rs):

        k = 0.34 / (1.34 + (window+1)/(window-1))

        sigma^2 = sigma_ov^2 + k * sigma_oc^2 + (1-k) * sigma_rs^2

    where:
        sigma_ov^2 = (1/N) sum (o_i - c_{i-1})^2     [overnight variance]
        sigma_oc^2 = (1/N) sum (c_i - o_i)^2          [open-to-close variance]
        sigma_rs^2 = (1/N) sum RS_i                    [Rogers-Satchell]

    Annualised: sigma_ann = sqrt( K * sigma^2 )
    Efficiency: ~14x relative to close-to-close (Yang & Zhang 2000).
    Robust to both drift and overnight gaps -- the most comprehensive of the
    five estimators.

All estimators produce NaN for any bar where the required OHLC inputs are
non-positive or NaN.  NaN is also produced during the rolling warm-up period
(first ``window - 1`` bars for all estimators; Yang-Zhang additionally requires
``c_prev`` so its first bar is always NaN).

References
----------
Parkinson, M. (1980). "The Extreme Value Method for Estimating the Variance of
    the Rate of Return." Journal of Business, 53(1), 61-65.

Garman, M.B. & Klass, M.J. (1980). "On the Estimation of Security Price
    Volatilities from Historical Data." Journal of Business, 53(1), 67-78.

Rogers, L.C.G. & Satchell, S.E. (1991). "Estimating Variance from High, Low
    and Closing Prices." Annals of Applied Probability, 1(4), 504-512.

Yang, D. & Zhang, Q. (2000). "Drift-Independent Volatility Estimation Based
    on High, Low, Open, and Close Prices." Journal of Business, 73(3), 477-491.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import cast

import numpy as np
import pandas as pd

__all__ = [
    "VolConfig",
    "close_to_close_vol",
    "parkinson_vol",
    "garman_klass_vol",
    "rogers_satchell_vol",
    "yang_zhang_vol",
]

# ---------------------------------------------------------------------------
# Configuration DTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VolConfig:
    """Parameters shared by all rolling OHLC volatility estimators.

    Attributes
    ----------
    window:
        Rolling window length in bars.  Must be >= 2.
    min_periods:
        Minimum number of valid (non-NaN) observations required within the
        window.  Defaults to ``window`` (strict).  Must be >= 2.
    trading_periods:
        Number of trading periods per year used for annualisation.
        Default 252 (daily bars).  Must be >= 1.
    """

    window: int = 21
    min_periods: int | None = None
    trading_periods: int = 252

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
        if self.trading_periods < 1:
            raise ValueError(f"trading_periods must be >= 1, got {self.trading_periods}")

    @property
    def effective_min_periods(self) -> int:
        return self.min_periods if self.min_periods is not None else self.window


# ---------------------------------------------------------------------------
# Internal helper: safe log prices from a price series
# ---------------------------------------------------------------------------


def _log_price(s: pd.Series) -> np.ndarray:
    """Return log of a price series; NaN where price is non-positive or NaN."""
    arr = s.astype(float).to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(np.isfinite(arr) & (arr > 0.0), np.log(arr), np.nan)


def _rolling_mean_of(arr: np.ndarray, window: int, min_periods: int) -> np.ndarray:
    """Rolling mean of a 1-D float array, returning an array of the same length."""
    s = pd.Series(arr)
    raw = s.rolling(window=window, min_periods=min_periods).mean().to_numpy(dtype=float)
    return cast(np.ndarray, raw)


def _vol_from_var(var_arr: np.ndarray, trading_periods: int) -> np.ndarray:
    """Convert a variance array to annualised volatility.  Negative -> NaN."""
    with np.errstate(invalid="ignore"):
        return np.where(var_arr >= 0.0, np.sqrt(var_arr * trading_periods), np.nan)


# ---------------------------------------------------------------------------
# 1. Close-to-close (baseline)
# ---------------------------------------------------------------------------


def close_to_close_vol(
    close: pd.Series,
    *,
    window: int = 21,
    min_periods: int | None = None,
    trading_periods: int = 252,
) -> pd.Series:
    """Estimate volatility from close-to-close log-returns.

    Computes the rolling mean squared log-return and converts to annualised
    standard deviation:

        var_t = (1/N) * sum_{i in window} (ln C_i - ln C_{i-1})^2
        sigma_t = sqrt( trading_periods * var_t )

    This is the classical baseline estimator.  It is unbiased under GBM but
    has low statistical efficiency (~1x) relative to range-based estimators
    because it discards intraday price information.

    Parameters
    ----------
    close:
        Series of closing prices (positive; NaN propagated).
    window:
        Rolling window length in bars.  Must be >= 2.
    min_periods:
        Minimum valid observations in the window.  Defaults to ``window``.
    trading_periods:
        Annual trading periods for annualisation.  Default 252.

    Returns
    -------
    pd.Series
        Annualised volatility estimates (standard deviation units).
        NaN for the first ``window`` bars and where inputs are invalid.

    Raises
    ------
    ValueError
        If parameters are invalid.
    """
    cfg = VolConfig(window=window, min_periods=min_periods, trading_periods=trading_periods)
    mp = cfg.effective_min_periods

    lc = _log_price(close)
    n = len(lc)

    sq_ret = np.full(n, np.nan, dtype=float)
    with np.errstate(invalid="ignore"):
        diff = lc[1:] - lc[:-1]
        sq_ret[1:] = diff**2

    rolling_var = _rolling_mean_of(sq_ret, window=window, min_periods=mp)
    result = _vol_from_var(rolling_var, trading_periods=cfg.trading_periods)

    return pd.Series(result, index=close.index, name="cc_vol")


# ---------------------------------------------------------------------------
# 2. Parkinson (1980)
# ---------------------------------------------------------------------------


def parkinson_vol(
    high: pd.Series,
    low: pd.Series,
    *,
    window: int = 21,
    min_periods: int | None = None,
    trading_periods: int = 252,
) -> pd.Series:
    """Estimate volatility using the Parkinson (1980) high-low range estimator.

    Per-bar variance contribution:

        pk_i = 1 / (4 * ln2) * (ln H_i - ln L_i)^2

    Rolling estimator:

        var_t = (1/N) * sum_{i in window} pk_i
        sigma_t = sqrt( trading_periods * var_t )

    Efficiency ~5.2x relative to close-to-close.  Unbiased under GBM without
    drift; assumes no overnight gaps.

    Parameters
    ----------
    high:
        Series of daily high prices (positive; NaN propagated).
    low:
        Series of daily low prices (positive, <= high; NaN propagated).
    window:
        Rolling window length in bars.  Must be >= 2.
    min_periods:
        Minimum valid observations in the window.  Defaults to ``window``.
    trading_periods:
        Annual trading periods for annualisation.  Default 252.

    Returns
    -------
    pd.Series
        Annualised Parkinson volatility estimates.  NaN during warm-up and
        where inputs are invalid.

    Raises
    ------
    ValueError
        If ``high`` and ``low`` have mismatched lengths / indices, or
        parameters are invalid.
    """
    if len(high) != len(low):
        raise ValueError("high and low must have the same length")
    if not high.index.equals(low.index):
        raise ValueError("high and low must share the same index")

    cfg = VolConfig(window=window, min_periods=min_periods, trading_periods=trading_periods)
    mp = cfg.effective_min_periods

    lh = _log_price(high)
    ll = _log_price(low)

    _4ln2 = 4.0 * np.log(2.0)
    with np.errstate(invalid="ignore"):
        pk = np.where(
            np.isfinite(lh) & np.isfinite(ll),
            (lh - ll) ** 2 / _4ln2,
            np.nan,
        )

    rolling_var = _rolling_mean_of(pk, window=window, min_periods=mp)
    result = _vol_from_var(rolling_var, trading_periods=cfg.trading_periods)

    return pd.Series(result, index=high.index, name="parkinson_vol")


# ---------------------------------------------------------------------------
# 3. Garman-Klass (1980)
# ---------------------------------------------------------------------------


def garman_klass_vol(
    open_: pd.Series,
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    *,
    window: int = 21,
    min_periods: int | None = None,
    trading_periods: int = 252,
) -> pd.Series:
    """Estimate volatility using the Garman-Klass (1980) OHLC estimator.

    Per-bar variance contribution:

        gk_i = 0.5 * (ln H_i - ln L_i)^2
                - (2*ln2 - 1) * (ln C_i - ln O_i)^2

    Rolling estimator:

        var_t = (1/N) * sum_{i in window} gk_i
        sigma_t = sqrt( trading_periods * var_t )

    Efficiency ~7.4x relative to close-to-close.  Allows for drift within the
    day; ignores overnight (close-to-open) gaps.  Can become negative per-bar
    in extreme price action (e.g. when close is very far from open relative to
    the range) -- negative per-bar contributions are carried into the average;
    if the rolling mean goes negative, NaN is returned.

    Parameters
    ----------
    open_:
        Series of daily open prices.  Named with trailing underscore to avoid
        shadowing the Python built-in ``open``.
    high:
        Series of daily high prices.
    low:
        Series of daily low prices.
    close:
        Series of daily closing prices.
    window:
        Rolling window length in bars.  Must be >= 2.
    min_periods:
        Minimum valid observations in the window.  Defaults to ``window``.
    trading_periods:
        Annual trading periods for annualisation.  Default 252.

    Returns
    -------
    pd.Series
        Annualised Garman-Klass volatility estimates.

    Raises
    ------
    ValueError
        If any series have mismatched lengths / indices, or parameters are
        invalid.
    """
    for name, s in [("high", high), ("low", low), ("close", close)]:
        if len(open_) != len(s):
            raise ValueError(f"open_ and {name} must have the same length")
        if not open_.index.equals(s.index):
            raise ValueError(f"open_ and {name} must share the same index")

    cfg = VolConfig(window=window, min_periods=min_periods, trading_periods=trading_periods)
    mp = cfg.effective_min_periods

    lo = _log_price(open_)
    lh = _log_price(high)
    ll = _log_price(low)
    lc = _log_price(close)

    _2ln2m1 = 2.0 * np.log(2.0) - 1.0
    with np.errstate(invalid="ignore"):
        all_finite = np.isfinite(lo) & np.isfinite(lh) & np.isfinite(ll) & np.isfinite(lc)
        gk = np.where(
            all_finite,
            0.5 * (lh - ll) ** 2 - _2ln2m1 * (lc - lo) ** 2,
            np.nan,
        )

    rolling_var = _rolling_mean_of(gk, window=window, min_periods=mp)
    result = _vol_from_var(rolling_var, trading_periods=cfg.trading_periods)

    return pd.Series(result, index=open_.index, name="garman_klass_vol")


# ---------------------------------------------------------------------------
# 4. Rogers-Satchell (1991)
# ---------------------------------------------------------------------------


def rogers_satchell_vol(
    open_: pd.Series,
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    *,
    window: int = 21,
    min_periods: int | None = None,
    trading_periods: int = 252,
) -> pd.Series:
    """Estimate volatility using the Rogers-Satchell (1991) estimator.

    Per-bar variance contribution (in log-prices):

        rs_i = (h-c)*(h-o) + (l-c)*(l-o)

    where h = ln H, l = ln L, o = ln O, c = ln C.

    Rolling estimator:

        var_t = (1/N) * sum_{i in window} rs_i
        sigma_t = sqrt( trading_periods * var_t )

    Efficiency ~8x relative to close-to-close.  Drift-robust (consistent for
    any mu) because the drift cancels algebraically.  Ignores overnight gaps.

    Parameters
    ----------
    open_:
        Series of daily open prices.
    high:
        Series of daily high prices.
    low:
        Series of daily low prices.
    close:
        Series of daily closing prices.
    window:
        Rolling window length in bars.  Must be >= 2.
    min_periods:
        Minimum valid observations in the window.  Defaults to ``window``.
    trading_periods:
        Annual trading periods for annualisation.  Default 252.

    Returns
    -------
    pd.Series
        Annualised Rogers-Satchell volatility estimates.

    Raises
    ------
    ValueError
        If any series have mismatched lengths / indices, or parameters are
        invalid.
    """
    for name, s in [("high", high), ("low", low), ("close", close)]:
        if len(open_) != len(s):
            raise ValueError(f"open_ and {name} must have the same length")
        if not open_.index.equals(s.index):
            raise ValueError(f"open_ and {name} must share the same index")

    cfg = VolConfig(window=window, min_periods=min_periods, trading_periods=trading_periods)
    mp = cfg.effective_min_periods

    lo = _log_price(open_)
    lh = _log_price(high)
    ll = _log_price(low)
    lc = _log_price(close)

    with np.errstate(invalid="ignore"):
        all_finite = np.isfinite(lo) & np.isfinite(lh) & np.isfinite(ll) & np.isfinite(lc)
        rs = np.where(
            all_finite,
            (lh - lc) * (lh - lo) + (ll - lc) * (ll - lo),
            np.nan,
        )

    rolling_var = _rolling_mean_of(rs, window=window, min_periods=mp)
    result = _vol_from_var(rolling_var, trading_periods=cfg.trading_periods)

    return pd.Series(result, index=open_.index, name="rogers_satchell_vol")


# ---------------------------------------------------------------------------
# 5. Yang-Zhang (2000)
# ---------------------------------------------------------------------------


def yang_zhang_vol(
    open_: pd.Series,
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    *,
    window: int = 21,
    min_periods: int | None = None,
    trading_periods: int = 252,
) -> pd.Series:
    """Estimate volatility using the Yang-Zhang (2000) estimator.

    Combines three variance components:

        sigma_ov^2 = (1/N) sum (ln O_i - ln C_{i-1})^2   [overnight]
        sigma_oc^2 = (1/N) sum (ln C_i - ln O_i)^2        [open-to-close]
        sigma_rs^2 = (1/N) sum RS_i                         [Rogers-Satchell]

    with mixture coefficient:

        k = 0.34 / (1.34 + (window+1)/(window-1))

    Combined variance:

        sigma^2 = sigma_ov^2 + k * sigma_oc^2 + (1-k) * sigma_rs^2
        sigma_t  = sqrt( trading_periods * sigma^2 )

    Efficiency ~14x relative to close-to-close.  The most general of the five
    estimators: robust to drift AND overnight gaps.

    Because the overnight component requires the previous close, the first bar
    is always NaN regardless of the window setting.

    Parameters
    ----------
    open_:
        Series of daily open prices.
    high:
        Series of daily high prices.
    low:
        Series of daily low prices.
    close:
        Series of daily closing prices.
    window:
        Rolling window length in bars.  Must be >= 2.
    min_periods:
        Minimum valid observations in the window.  Defaults to ``window``.
    trading_periods:
        Annual trading periods for annualisation.  Default 252.

    Returns
    -------
    pd.Series
        Annualised Yang-Zhang volatility estimates.

    Raises
    ------
    ValueError
        If any series have mismatched lengths / indices, or parameters are
        invalid.
    """
    for name, s in [("high", high), ("low", low), ("close", close)]:
        if len(open_) != len(s):
            raise ValueError(f"open_ and {name} must have the same length")
        if not open_.index.equals(s.index):
            raise ValueError(f"open_ and {name} must share the same index")

    cfg = VolConfig(window=window, min_periods=min_periods, trading_periods=trading_periods)
    mp = cfg.effective_min_periods
    N = float(cfg.window)

    lo = _log_price(open_)
    lh = _log_price(high)
    ll = _log_price(low)
    lc = _log_price(close)
    n = len(lo)

    # Overnight component: (ln O_i - ln C_{i-1})^2
    ov = np.full(n, np.nan, dtype=float)
    with np.errstate(invalid="ignore"):
        ov[1:] = np.where(
            np.isfinite(lo[1:]) & np.isfinite(lc[:-1]),
            (lo[1:] - lc[:-1]) ** 2,
            np.nan,
        )

    # Open-to-close component: (ln C_i - ln O_i)^2
    with np.errstate(invalid="ignore"):
        all_oc = np.isfinite(lc) & np.isfinite(lo)
        oc = np.where(all_oc, (lc - lo) ** 2, np.nan)

    # Rogers-Satchell within-day component
    with np.errstate(invalid="ignore"):
        all_fin = np.isfinite(lo) & np.isfinite(lh) & np.isfinite(ll) & np.isfinite(lc)
        rs = np.where(
            all_fin,
            (lh - lc) * (lh - lo) + (ll - lc) * (ll - lo),
            np.nan,
        )

    # Rolling means (suppress the RuntimeWarning about all-NaN windows)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        var_ov = _rolling_mean_of(ov, window=window, min_periods=mp)
        var_oc = _rolling_mean_of(oc, window=window, min_periods=mp)
        var_rs = _rolling_mean_of(rs, window=window, min_periods=mp)

    k = 0.34 / (1.34 + (N + 1.0) / (N - 1.0))

    with np.errstate(invalid="ignore"):
        all_defined = np.isfinite(var_ov) & np.isfinite(var_oc) & np.isfinite(var_rs)
        combined_var = np.where(
            all_defined,
            var_ov + k * var_oc + (1.0 - k) * var_rs,
            np.nan,
        )

    result = _vol_from_var(combined_var, trading_periods=cfg.trading_periods)

    return pd.Series(result, index=open_.index, name="yang_zhang_vol")
