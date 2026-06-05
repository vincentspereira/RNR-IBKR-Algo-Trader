"""Vectorised moving-average functions.

All functions accept a ``pd.Series`` (close prices, or any numeric series) and
return a ``pd.Series`` of the same index, ``float64``, with ``NaN`` during the
warm-up period.  Every function is look-ahead-free by construction: value at
index ``t`` uses only data at indices <= ``t``.

Recursive indicators (EMA, KAMA, McGinley) use a fixed SMA seed so that
truncation invariance holds exactly: ``f(x).iloc[:k] == f(x.iloc[:k])``
on the overlapping non-NaN region.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

__all__ = [
    "sma",
    "ema",
    "wma",
    "dema",
    "tema",
    "hma",
    "kama",
    "zlema",
    "vwma",
    "mcginley_dynamic",
]


def _validate_series(close: pd.Series, window: int, name: str = "window") -> None:
    """Raise ValueError for invalid inputs."""
    if not isinstance(close, pd.Series):
        raise ValueError("close must be a pd.Series")
    if window < 1:
        raise ValueError(f"{name} must be >= 1, got {window}")


# ---------------------------------------------------------------------------
# Simple Moving Average
# ---------------------------------------------------------------------------


def sma(close: pd.Series, window: int = 20) -> pd.Series:
    """Simple Moving Average.

    Formula::

        SMA_t = mean(close[t-window+1 : t+1])

    Parameters
    ----------
    close:
        Price series (typically close prices).
    window:
        Lookback period.  Default 20.

    Returns
    -------
    pd.Series
        Float64 series, indexed like ``close``.  First ``window-1`` values
        are ``NaN``.
    """
    _validate_series(close, window)
    return close.rolling(window=window, min_periods=window).mean().astype("float64")


# ---------------------------------------------------------------------------
# Exponential Moving Average
# ---------------------------------------------------------------------------


def ema(close: pd.Series, window: int = 20) -> pd.Series:
    """Exponential Moving Average seeded with SMA.

    Formula::

        alpha = 2 / (window + 1)
        EMA_t = alpha * close_t + (1 - alpha) * EMA_{t-1}

    The seed at bar ``window-1`` is ``SMA(close[:window])``.  This fixed-seed
    convention guarantees truncation invariance.

    Parameters
    ----------
    close:
        Price series.
    window:
        Lookback / smoothing period.  Default 20.
        Alpha = 2 / (window + 1).

    Returns
    -------
    pd.Series
        Float64 series, indexed like ``close``.  First ``window-1`` values
        are ``NaN``.
    """
    _validate_series(close, window)
    alpha = 2.0 / (window + 1)
    arr = close.to_numpy(dtype=float)
    n = len(arr)
    out = np.full(n, np.nan)

    # Find first run of `window` consecutive valid (non-NaN) values
    # This handles NaN-prefixed input (e.g. MACD line, double-EMA chains).
    valid_indices = np.where(~np.isnan(arr))[0]
    if len(valid_indices) < window:
        return pd.Series(out, index=close.index, dtype="float64")

    # Seed: SMA of first `window` valid values
    first_valid_window_end = valid_indices[window - 1]
    seed_vals = arr[valid_indices[:window]]
    seed = float(np.mean(seed_vals))
    out[first_valid_window_end] = seed

    for i in range(first_valid_window_end + 1, n):
        if not np.isnan(arr[i]):
            out[i] = alpha * arr[i] + (1.0 - alpha) * out[i - 1]
        elif not np.isnan(out[i - 1]):
            out[i] = out[i - 1]
    return pd.Series(out, index=close.index, dtype="float64")


# ---------------------------------------------------------------------------
# Weighted Moving Average
# ---------------------------------------------------------------------------


def wma(close: pd.Series, window: int = 20) -> pd.Series:
    """Linearly Weighted Moving Average.

    Formula::

        weights = [1, 2, ..., window]
        WMA_t = sum(close[t-window+1:t+1] * weights) / sum(weights)

    Parameters
    ----------
    close:
        Price series.
    window:
        Lookback period.  Default 20.

    Returns
    -------
    pd.Series
        Float64 series, indexed like ``close``.  First ``window-1`` values
        are ``NaN``.
    """
    _validate_series(close, window)
    weights = np.arange(1, window + 1, dtype=float)
    weight_sum = weights.sum()
    arr = close.to_numpy(dtype=float)
    n = len(arr)
    out = np.full(n, np.nan)
    for i in range(window - 1, n):
        out[i] = np.dot(arr[i - window + 1 : i + 1], weights) / weight_sum
    return pd.Series(out, index=close.index, dtype="float64")


# ---------------------------------------------------------------------------
# Double EMA
# ---------------------------------------------------------------------------


def dema(close: pd.Series, window: int = 20) -> pd.Series:
    """Double Exponential Moving Average (Appel 1994).

    Formula::

        DEMA = 2 * EMA(close, n) - EMA(EMA(close, n), n)

    Parameters
    ----------
    close:
        Price series.
    window:
        EMA period.  Default 20.

    Returns
    -------
    pd.Series
        Float64 series.  Warm-up requires 2*(window-1) bars.
    """
    _validate_series(close, window)
    e1 = ema(close, window)
    e2 = ema(e1, window)
    return (2.0 * e1 - e2).astype("float64")


# ---------------------------------------------------------------------------
# Triple EMA
# ---------------------------------------------------------------------------


def tema(close: pd.Series, window: int = 20) -> pd.Series:
    """Triple Exponential Moving Average (Mulloy 1994).

    Formula::

        TEMA = 3*EMA1 - 3*EMA2 + EMA3
        where EMA2 = EMA(EMA1, n), EMA3 = EMA(EMA2, n)

    Parameters
    ----------
    close:
        Price series.
    window:
        EMA period.  Default 20.

    Returns
    -------
    pd.Series
        Float64 series.  Warm-up requires 3*(window-1) bars.
    """
    _validate_series(close, window)
    e1 = ema(close, window)
    e2 = ema(e1, window)
    e3 = ema(e2, window)
    return (3.0 * e1 - 3.0 * e2 + e3).astype("float64")


# ---------------------------------------------------------------------------
# Hull Moving Average
# ---------------------------------------------------------------------------


def hma(close: pd.Series, window: int = 20) -> pd.Series:
    """Hull Moving Average (Alan Hull 2005).

    Formula::

        HMA(n) = WMA( 2*WMA(close, n//2) - WMA(close, n), sqrt(n) )

    Parameters
    ----------
    close:
        Price series.
    window:
        Primary WMA period.  Default 20.

    Returns
    -------
    pd.Series
        Float64 series.
    """
    _validate_series(close, window)
    half = max(1, window // 2)
    sqrtn = max(1, int(math.isqrt(window)))
    raw = 2.0 * wma(close, half) - wma(close, window)
    return wma(raw, sqrtn).astype("float64")


# ---------------------------------------------------------------------------
# Kaufman Adaptive Moving Average
# ---------------------------------------------------------------------------


def kama(
    close: pd.Series,
    window: int = 10,
    fast_period: int = 2,
    slow_period: int = 30,
) -> pd.Series:
    """Kaufman Adaptive Moving Average (Perry Kaufman 1995).

    Formula::

        ER_t = |close_t - close_{t-n}| / sum(|diff(close)|, n)
        fastest = 2 / (fast_period + 1)
        slowest = 2 / (slow_period + 1)
        SC_t = (ER_t * (fastest - slowest) + slowest) ** 2
        KAMA_t = KAMA_{t-1} + SC_t * (close_t - KAMA_{t-1})

    Seeded at bar ``window`` with SMA of the first ``window`` prices.

    Parameters
    ----------
    close:
        Price series.
    window:
        Efficiency Ratio period.  Default 10.
    fast_period:
        Fast EMA period.  Default 2.
    slow_period:
        Slow EMA period.  Default 30.

    Returns
    -------
    pd.Series
        Float64 series.  First ``window`` values are ``NaN``.
    """
    _validate_series(close, window)
    if fast_period < 1:
        raise ValueError(f"fast_period must be >= 1, got {fast_period}")
    if slow_period < 1:
        raise ValueError(f"slow_period must be >= 1, got {slow_period}")

    fastest = 2.0 / (fast_period + 1)
    slowest = 2.0 / (slow_period + 1)

    arr = close.to_numpy(dtype=float)
    n = len(arr)
    out = np.full(n, np.nan)

    if n <= window:
        return pd.Series(out, index=close.index, dtype="float64")

    # Seed: SMA of first `window` values
    seed_val = float(np.mean(arr[:window]))
    out[window] = seed_val

    for i in range(window + 1, n):
        direction = abs(arr[i] - arr[i - window])
        volatility = np.sum(np.abs(np.diff(arr[i - window : i + 1])))
        er = direction / volatility if volatility != 0.0 else 0.0
        sc = (er * (fastest - slowest) + slowest) ** 2
        out[i] = out[i - 1] + sc * (arr[i] - out[i - 1])

    return pd.Series(out, index=close.index, dtype="float64")


# ---------------------------------------------------------------------------
# Zero-Lag EMA
# ---------------------------------------------------------------------------


def zlema(close: pd.Series, window: int = 20) -> pd.Series:
    """Zero-Lag Exponential Moving Average (Ehlers & Way 2010).

    Formula::

        lag = (window - 1) // 2
        adjusted = close + (close - close.shift(lag))
        ZLEMA = EMA(adjusted, window)

    Parameters
    ----------
    close:
        Price series.
    window:
        EMA period.  Default 20.

    Returns
    -------
    pd.Series
        Float64 series.
    """
    _validate_series(close, window)
    lag = (window - 1) // 2
    adjusted = close + (close - close.shift(lag))
    return ema(adjusted, window).astype("float64")


# ---------------------------------------------------------------------------
# Volume-Weighted Moving Average
# ---------------------------------------------------------------------------


def vwma(close: pd.Series, volume: pd.Series, window: int = 20) -> pd.Series:
    """Volume-Weighted Moving Average.

    Formula::

        VWMA_t = sum(close * volume, window) / sum(volume, window)

    Parameters
    ----------
    close:
        Price series.
    volume:
        Volume series.  Must share the same index as ``close``.
    window:
        Lookback period.  Default 20.

    Returns
    -------
    pd.Series
        Float64 series.  First ``window-1`` values are ``NaN``.
    """
    _validate_series(close, window)
    if not isinstance(volume, pd.Series):
        raise ValueError("volume must be a pd.Series")
    if not close.index.equals(volume.index):
        raise ValueError("close and volume must share the same index")
    pv = close * volume
    return (
        pv.rolling(window=window, min_periods=window).sum()
        / volume.rolling(window=window, min_periods=window).sum()
    ).astype("float64")


# ---------------------------------------------------------------------------
# McGinley Dynamic
# ---------------------------------------------------------------------------


def mcginley_dynamic(close: pd.Series, window: int = 14, k: float = 0.6) -> pd.Series:
    """McGinley Dynamic Indicator (John McGinley 1997).

    Formula::

        MD_t = MD_{t-1} + (close_t - MD_{t-1}) / (k * n * (close_t / MD_{t-1})^4)

    Seeded at the first bar with ``close[0]`` (no warm-up NaN -- the seed is a
    single price, which is the conventional initialisation).  After the first
    bar the recursion runs indefinitely.  Truncation invariance holds because
    the seed is deterministic from the first element of the input.

    Parameters
    ----------
    close:
        Price series.
    window:
        Base period ``n``.  Default 14.
    k:
        Speed constant, conventionally 0.6.  Default 0.6.

    Returns
    -------
    pd.Series
        Float64 series.  All values are valid (seed at index 0).
    """
    _validate_series(close, window)
    arr = close.to_numpy(dtype=float)
    n = len(arr)
    out = np.empty(n, dtype=float)

    if n == 0:
        return pd.Series(out, index=close.index, dtype="float64")

    out[0] = arr[0]
    for i in range(1, n):
        prev = out[i - 1]
        price = arr[i]
        if prev == 0.0:
            out[i] = price
        else:
            denom = k * float(window) * (price / prev) ** 4
            out[i] = prev + (price - prev) / denom if denom != 0.0 else prev
    return pd.Series(out, index=close.index, dtype="float64")
