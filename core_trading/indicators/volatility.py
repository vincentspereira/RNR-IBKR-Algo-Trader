"""Vectorised volatility indicator functions.

All functions return ``pd.Series`` (or ``pd.DataFrame``) indexed exactly like
the input, ``float64``, with ``NaN`` during warm-up.  Every function is
look-ahead-free: value at index ``t`` uses only data at indices <= ``t``.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core_trading.indicators.moving_averages import ema

__all__ = [
    "true_range",
    "atr",
    "natr",
    "bollinger_bands",
    "keltner_channels",
    "donchian_channels",
    "ulcer_index",
    "historical_volatility",
]


def _validate_ohlc(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
) -> None:
    if not (
        isinstance(high, pd.Series)
        and isinstance(low, pd.Series)
        and isinstance(close, pd.Series)
    ):
        raise ValueError("high, low, close must all be pd.Series")
    if not (high.index.equals(low.index) and high.index.equals(close.index)):
        raise ValueError("high, low, close must share the same index")


# ---------------------------------------------------------------------------
# True Range
# ---------------------------------------------------------------------------


def true_range(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
) -> pd.Series:
    """True Range.

    Formula::

        TR_t = max(high_t - low_t,
                   |high_t - close_{t-1}|,
                   |low_t  - close_{t-1}|)

    At ``t=0`` (no previous close), TR = high - low.

    Parameters
    ----------
    high, low, close:
        OHLC series sharing the same index.

    Returns
    -------
    pd.Series
        Float64 series.  All values are valid (no NaN warm-up for TR itself).
    """
    _validate_ohlc(high, low, close)
    prev_close = close.shift(1)
    hl = high - low
    hpc = (high - prev_close).abs()
    lpc = (low - prev_close).abs()
    tr = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
    # At index 0, prev_close is NaN; fall back to hl
    tr.iloc[0] = hl.iloc[0]
    return tr.astype("float64")


# ---------------------------------------------------------------------------
# ATR -- Wilder smoothing
# ---------------------------------------------------------------------------


def atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    window: int = 14,
) -> pd.Series:
    """Average True Range (Wilder 1978).

    Uses Wilder's smoothing (alpha = 1/n).

    Formula::

        ATR_0 = SMA(TR, n)    [seed at bar window-1]
        ATR_t = (ATR_{t-1} * (n-1) + TR_t) / n

    Wilder's alpha = 1/n vs standard EMA alpha = 2/(n+1).  The Wilder form
    is the conventional choice for ATR.

    Parameters
    ----------
    high, low, close:
        OHLC series sharing the same index.
    window:
        Period.  Default 14.

    Returns
    -------
    pd.Series
        Float64 series.  First ``window-1`` values are ``NaN``.
    """
    _validate_ohlc(high, low, close)
    if window < 1:
        raise ValueError(f"window must be >= 1, got {window}")

    tr = true_range(high, low, close).to_numpy(dtype=float)
    n = len(tr)
    out = np.full(n, np.nan)

    if n < window:
        return pd.Series(out, index=close.index, dtype="float64")

    # Seed: SMA of first `window` TR values
    out[window - 1] = float(np.mean(tr[:window]))
    for i in range(window, n):
        out[i] = (out[i - 1] * (window - 1) + tr[i]) / window

    return pd.Series(out, index=close.index, dtype="float64")


# ---------------------------------------------------------------------------
# NATR
# ---------------------------------------------------------------------------


def natr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    window: int = 14,
) -> pd.Series:
    """Normalised Average True Range (ATR / close * 100).

    Formula::

        NATR_t = ATR_t / close_t * 100

    Parameters
    ----------
    high, low, close:
        OHLC series sharing the same index.
    window:
        ATR period.  Default 14.

    Returns
    -------
    pd.Series
        Float64 series (percentage of price).
    """
    atr_vals = atr(high, low, close, window)
    result = 100.0 * atr_vals / close
    return result.astype("float64")


# ---------------------------------------------------------------------------
# Bollinger Bands
# ---------------------------------------------------------------------------


def bollinger_bands(
    close: pd.Series,
    window: int = 20,
    num_std: float = 2.0,
) -> pd.DataFrame:
    """Bollinger Bands (John Bollinger 1983).

    Uses the population standard deviation (ddof=1, Pandas rolling default).

    Formula::

        mid    = SMA(close, n)
        std    = rolling_std(close, n, ddof=1)
        upper  = mid + num_std * std
        lower  = mid - num_std * std
        bw     = (upper - lower) / mid          [bandwidth]
        pct_b  = (close - lower) / (upper - lower)   [%B]

    Parameters
    ----------
    close:
        Price series.
    window:
        SMA / std period.  Default 20.
    num_std:
        Standard deviation multiplier.  Default 2.0.

    Returns
    -------
    pd.DataFrame
        Columns: ``mid``, ``upper``, ``lower``, ``bandwidth``, ``pct_b``.
    """
    if not isinstance(close, pd.Series):
        raise ValueError("close must be a pd.Series")
    if window < 1:
        raise ValueError(f"window must be >= 1, got {window}")

    mid = close.rolling(window, min_periods=window).mean()
    std = close.rolling(window, min_periods=window).std(ddof=1)
    upper = mid + num_std * std
    lower = mid - num_std * std
    band_width = upper - lower
    bw = (band_width / mid).astype("float64")
    # Safe-denominator: avoid RuntimeWarning from 0/0 in both np.where branches.
    safe_bw = np.where(band_width.values == 0.0, 1.0, band_width.values)
    pct_b = pd.Series(
        np.where(band_width.values == 0.0, 0.5, (close.values - lower.values) / safe_bw),
        index=close.index,
        dtype="float64",
    ).where(mid.notna(), other=np.nan)

    return pd.DataFrame(
        {
            "mid": mid.astype("float64"),
            "upper": upper.astype("float64"),
            "lower": lower.astype("float64"),
            "bandwidth": bw,
            "pct_b": pct_b,
        },
        index=close.index,
    )


# ---------------------------------------------------------------------------
# Keltner Channels
# ---------------------------------------------------------------------------


def keltner_channels(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    ema_period: int = 20,
    atr_period: int = 10,
    multiplier: float = 2.0,
) -> pd.DataFrame:
    """Keltner Channels (Chester Keltner 1960; modern form Linda Raschke).

    Formula::

        mid   = EMA(close, ema_period)
        atr_v = ATR(high, low, close, atr_period)   [Wilder smoothing]
        upper = mid + multiplier * atr_v
        lower = mid - multiplier * atr_v

    Parameters
    ----------
    high, low, close:
        OHLC series sharing the same index.
    ema_period:
        EMA period for the midline.  Default 20.
    atr_period:
        ATR period.  Default 10.
    multiplier:
        ATR multiplier for channel width.  Default 2.0.

    Returns
    -------
    pd.DataFrame
        Columns: ``mid``, ``upper``, ``lower``.
    """
    _validate_ohlc(high, low, close)
    if ema_period < 1:
        raise ValueError(f"ema_period must be >= 1, got {ema_period}")
    if atr_period < 1:
        raise ValueError(f"atr_period must be >= 1, got {atr_period}")

    mid = ema(close, ema_period)
    atr_v = atr(high, low, close, atr_period)
    upper = mid + multiplier * atr_v
    lower = mid - multiplier * atr_v

    return pd.DataFrame(
        {
            "mid": mid.astype("float64"),
            "upper": upper.astype("float64"),
            "lower": lower.astype("float64"),
        },
        index=close.index,
    )


# ---------------------------------------------------------------------------
# Donchian Channels
# ---------------------------------------------------------------------------


def donchian_channels(
    high: pd.Series,
    low: pd.Series,
    window: int = 20,
) -> pd.DataFrame:
    """Donchian Channels (Richard Donchian 1948).

    Formula::

        upper  = rolling_max(high, n)
        lower  = rolling_min(low,  n)
        mid    = (upper + lower) / 2

    Parameters
    ----------
    high, low:
        High and low price series sharing the same index.
    window:
        Lookback period.  Default 20.

    Returns
    -------
    pd.DataFrame
        Columns: ``upper``, ``mid``, ``lower``.
    """
    if not (isinstance(high, pd.Series) and isinstance(low, pd.Series)):
        raise ValueError("high, low must be pd.Series")
    if not high.index.equals(low.index):
        raise ValueError("high and low must share the same index")
    if window < 1:
        raise ValueError(f"window must be >= 1, got {window}")

    upper = high.rolling(window, min_periods=window).max().astype("float64")
    lower = low.rolling(window, min_periods=window).min().astype("float64")
    mid = ((upper + lower) / 2.0).astype("float64")

    return pd.DataFrame({"upper": upper, "mid": mid, "lower": lower}, index=high.index)


# ---------------------------------------------------------------------------
# Ulcer Index
# ---------------------------------------------------------------------------


def ulcer_index(close: pd.Series, window: int = 14) -> pd.Series:
    """Ulcer Index (Peter Martin 1989).

    Measures the depth and duration of drawdowns from the rolling high.

    Formula::

        peak_t    = rolling_max(close, n)
        dd_pct_t  = 100 * (close_t - peak_t) / peak_t
        UI_t      = sqrt( mean(dd_pct_t ^ 2, n) )

    Parameters
    ----------
    close:
        Price series.
    window:
        Lookback period.  Default 14.

    Returns
    -------
    pd.Series
        Float64 series.  First ``window-1`` values are ``NaN``.
    """
    if not isinstance(close, pd.Series):
        raise ValueError("close must be a pd.Series")
    if window < 1:
        raise ValueError(f"window must be >= 1, got {window}")

    peak = close.rolling(window, min_periods=window).max()
    dd_pct = 100.0 * (close - peak) / peak
    dd_sq = dd_pct**2
    ui = dd_sq.rolling(window, min_periods=window).mean().apply(np.sqrt)
    return ui.astype("float64")


# ---------------------------------------------------------------------------
# Historical Volatility
# ---------------------------------------------------------------------------


def historical_volatility(
    close: pd.Series,
    window: int = 20,
    trading_periods: int = 252,
) -> pd.Series:
    """Annualised Close-to-Close Historical Volatility.

    Formula::

        log_ret_t = ln(close_t / close_{t-1})
        HV_t = std(log_ret, n, ddof=1) * sqrt(trading_periods)

    Parameters
    ----------
    close:
        Price series.
    window:
        Lookback period for std computation.  Default 20.
    trading_periods:
        Annualisation factor (252 for daily, 52 for weekly).  Default 252.

    Returns
    -------
    pd.Series
        Float64 series.  First ``window`` values are ``NaN`` (need ``window``
        log returns, which requires ``window+1`` prices).
    """
    if not isinstance(close, pd.Series):
        raise ValueError("close must be a pd.Series")
    if window < 1:
        raise ValueError(f"window must be >= 1, got {window}")
    if trading_periods < 1:
        raise ValueError(f"trading_periods must be >= 1, got {trading_periods}")

    log_ret = np.log(close / close.shift(1))
    hv = log_ret.rolling(window, min_periods=window).std(ddof=1) * np.sqrt(
        float(trading_periods)
    )
    return hv.astype("float64")
