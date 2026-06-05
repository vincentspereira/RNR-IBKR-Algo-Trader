"""Vectorised volume indicator functions.

All functions accept ``pd.Series`` arguments and return ``pd.Series``
indexed exactly like the input, ``float64``, with ``NaN`` during warm-up.
Every function is look-ahead-free: value at index ``t`` uses only data
at indices <= ``t``.

VWAP note
---------
True session-anchored VWAP resets the cumulative sum each trading day and
requires intraday data (each row = one intraday bar, with a date label).
The daily-bar approximation implemented here treats each row as a single
"session" and computes a rolling VWAP over ``window`` bars instead.  This
is a reasonable proxy for daily analysis but IS NOT the same as the
intraday VWAP institutional traders use for execution benchmarking.

``vwap_rolling`` -- rolling window approximation, works on daily data.
``vwap_anchored`` -- true cumulative session reset using the Date part of
   a DatetimeIndex; falls back to ``vwap_rolling`` if the index is not a
   DatetimeIndex.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core_trading.indicators.moving_averages import sma

__all__ = [
    "obv",
    "vwap_rolling",
    "vwap_anchored",
    "mfi",
    "cmf",
    "ad_line",
    "force_index",
    "eom",
]


def _validate_cv(close: pd.Series, volume: pd.Series, name: str = "volume") -> None:
    if not isinstance(close, pd.Series):
        raise ValueError("close must be a pd.Series")
    if not isinstance(volume, pd.Series):
        raise ValueError(f"{name} must be a pd.Series")
    if not close.index.equals(volume.index):
        raise ValueError("close and volume must share the same index")


def _validate_ohlcv(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
) -> None:
    if not all(isinstance(s, pd.Series) for s in [high, low, close, volume]):
        raise ValueError("high, low, close, volume must all be pd.Series")
    if not (
        high.index.equals(low.index)
        and high.index.equals(close.index)
        and high.index.equals(volume.index)
    ):
        raise ValueError("high, low, close, volume must share the same index")


# ---------------------------------------------------------------------------
# On-Balance Volume
# ---------------------------------------------------------------------------


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume (Joe Granville 1963).

    Formula::

        OBV_0 = volume_0
        OBV_t = OBV_{t-1} + volume_t   if close_t > close_{t-1}
        OBV_t = OBV_{t-1} - volume_t   if close_t < close_{t-1}
        OBV_t = OBV_{t-1}              if close_t == close_{t-1}

    Parameters
    ----------
    close:
        Price series.
    volume:
        Volume series sharing the same index as ``close``.

    Returns
    -------
    pd.Series
        Float64 cumulative series.  All values are valid (no NaN warm-up).
    """
    _validate_cv(close, volume)
    close_arr = close.to_numpy(dtype=float)
    vol_arr = volume.to_numpy(dtype=float)
    n = len(close_arr)
    out = np.empty(n, dtype=float)
    out[0] = vol_arr[0]
    for i in range(1, n):
        if close_arr[i] > close_arr[i - 1]:
            out[i] = out[i - 1] + vol_arr[i]
        elif close_arr[i] < close_arr[i - 1]:
            out[i] = out[i - 1] - vol_arr[i]
        else:
            out[i] = out[i - 1]
    return pd.Series(out, index=close.index, dtype="float64")


# ---------------------------------------------------------------------------
# VWAP -- rolling (daily-bar approximation)
# ---------------------------------------------------------------------------


def vwap_rolling(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
    window: int = 20,
) -> pd.Series:
    """Rolling VWAP over a fixed window (daily-bar approximation).

    Formula::

        TP    = (high + low + close) / 3
        VWAP  = sum(TP * volume, n) / sum(volume, n)

    Note: This is a *rolling* approximation, NOT the session-anchored VWAP
    used by institutional traders for execution benchmarking.  Session-anchored
    VWAP requires intraday data where each row is a sub-daily bar and the
    cumulative sum resets each calendar day.

    Parameters
    ----------
    high, low, close:
        OHLC series sharing the same index.
    volume:
        Volume series.
    window:
        Lookback period.  Default 20.

    Returns
    -------
    pd.Series
        Float64 series.  First ``window-1`` values are ``NaN``.
    """
    _validate_ohlcv(high, low, close, volume)
    if window < 1:
        raise ValueError(f"window must be >= 1, got {window}")

    tp = (high + low + close) / 3.0
    pv = tp * volume
    vwap_val = (
        pv.rolling(window, min_periods=window).sum()
        / volume.rolling(window, min_periods=window).sum()
    )
    return vwap_val.astype("float64")


# ---------------------------------------------------------------------------
# VWAP -- session-anchored (resets each date)
# ---------------------------------------------------------------------------


def vwap_anchored(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
) -> pd.Series:
    """Session-anchored VWAP (requires intraday data or daily data with dates).

    The cumulative TP*Volume and Volume sums are reset at the start of each
    calendar day (using the Date portion of a DatetimeIndex).

    If the index is NOT a DatetimeIndex the function falls back to a simple
    cumulative VWAP over the entire series (equivalent to setting window to
    the full length).

    Note: True intraday VWAP is only meaningful on sub-daily data (1-min,
    5-min, etc.).  On daily OHLCV bars this function resets each row and
    therefore degenerates to a single-bar TP (i.e., VWAP = TP for each day).
    Use ``vwap_rolling`` for daily-bar analysis instead.

    Parameters
    ----------
    high, low, close:
        OHLC series sharing the same index.
    volume:
        Volume series.

    Returns
    -------
    pd.Series
        Float64 series.
    """
    _validate_ohlcv(high, low, close, volume)
    tp = (high + low + close) / 3.0
    pv = tp * volume

    if isinstance(close.index, pd.DatetimeIndex):
        dates = close.index.date
        out = np.empty(len(close), dtype=float)
        cum_pv = 0.0
        cum_vol = 0.0
        prev_date = None
        for i, d in enumerate(dates):
            if d != prev_date:
                cum_pv = 0.0
                cum_vol = 0.0
                prev_date = d
            cum_pv += float(pv.iloc[i])
            cum_vol += float(volume.iloc[i])
            out[i] = cum_pv / cum_vol if cum_vol != 0.0 else float("nan")
        return pd.Series(out, index=close.index, dtype="float64")

    # Fallback: cumulative VWAP over entire series
    cum_pv = pv.cumsum()
    cum_vol = volume.cumsum()
    return (cum_pv / cum_vol).astype("float64")


# ---------------------------------------------------------------------------
# Money Flow Index
# ---------------------------------------------------------------------------


def mfi(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
    window: int = 14,
) -> pd.Series:
    """Money Flow Index (Gene Quong & Avrum Soudack 1989).

    Volume-weighted RSI using typical price direction.

    Formula::

        TP = (high + low + close) / 3
        raw_MF = TP * volume
        positive_MF if TP_t > TP_{t-1}, else negative_MF
        MFR = sum(positive_MF, n) / sum(negative_MF, n)
        MFI = 100 - 100 / (1 + MFR)

    When sum(negative_MF) == 0, MFI = 100.

    Parameters
    ----------
    high, low, close:
        OHLC series sharing the same index.
    volume:
        Volume series.
    window:
        Lookback period.  Default 14.

    Returns
    -------
    pd.Series
        Float64 in [0, 100].  First ``window`` values are ``NaN``.
    """
    _validate_ohlcv(high, low, close, volume)
    if window < 1:
        raise ValueError(f"window must be >= 1, got {window}")

    tp = (high + low + close) / 3.0
    raw_mf = tp * volume
    tp_shift = tp.shift(1)

    pos_mf = raw_mf.where(tp > tp_shift, other=0.0)
    neg_mf = raw_mf.where(tp < tp_shift, other=0.0)

    pos_sum = pos_mf.rolling(window, min_periods=window).sum()
    neg_sum = neg_mf.rolling(window, min_periods=window).sum()

    mfi_arr = np.where(
        neg_sum == 0.0,
        100.0,
        100.0 - 100.0 / (1.0 + pos_sum.values / neg_sum.values),
    )
    result = pd.Series(mfi_arr, index=close.index, dtype="float64")
    return result.where(pos_sum.notna(), other=np.nan)


# ---------------------------------------------------------------------------
# Chaikin Money Flow
# ---------------------------------------------------------------------------


def cmf(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
    window: int = 20,
) -> pd.Series:
    """Chaikin Money Flow (Marc Chaikin 1989).

    Formula::

        CLV = ((close - low) - (high - close)) / (high - low)
        CMF = sum(CLV * volume, n) / sum(volume, n)

    When high == low, CLV = 0.

    Parameters
    ----------
    high, low, close:
        OHLC series sharing the same index.
    volume:
        Volume series.
    window:
        Lookback period.  Default 20.

    Returns
    -------
    pd.Series
        Float64 series in [-1, 1].
    """
    _validate_ohlcv(high, low, close, volume)
    if window < 1:
        raise ValueError(f"window must be >= 1, got {window}")

    hl = high - low
    clv = pd.Series(
        np.where(hl == 0.0, 0.0, ((close.values - low.values) - (high.values - close.values)) / hl.values),
        index=close.index,
        dtype="float64",
    )
    mfv = clv * volume
    mfv_sum = mfv.rolling(window, min_periods=window).sum()
    vol_sum = volume.rolling(window, min_periods=window).sum()
    result = pd.Series(
        np.where(vol_sum == 0.0, 0.0, mfv_sum.values / vol_sum.values),
        index=close.index,
        dtype="float64",
    )
    return result.where(mfv_sum.notna(), other=np.nan)


# ---------------------------------------------------------------------------
# Accumulation/Distribution Line
# ---------------------------------------------------------------------------


def ad_line(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
) -> pd.Series:
    """Accumulation/Distribution Line (Marc Chaikin).

    Cumulative indicator using the Close Location Value.

    Formula::

        CLV = ((close - low) - (high - close)) / (high - low)
        ADL = cumsum(CLV * volume)

    Parameters
    ----------
    high, low, close:
        OHLC series sharing the same index.
    volume:
        Volume series.

    Returns
    -------
    pd.Series
        Float64 cumulative series.  All values are valid.
    """
    _validate_ohlcv(high, low, close, volume)
    hl = high - low
    clv = pd.Series(
        np.where(hl == 0.0, 0.0, ((close.values - low.values) - (high.values - close.values)) / hl.values),
        index=close.index,
        dtype="float64",
    )
    return (clv * volume).cumsum().astype("float64")


# ---------------------------------------------------------------------------
# Force Index
# ---------------------------------------------------------------------------


def force_index(
    close: pd.Series,
    volume: pd.Series,
    window: int = 13,
) -> pd.Series:
    """Force Index (Alexander Elder 1993).

    Formula::

        raw_FI = (close_t - close_{t-1}) * volume_t
        FI     = EMA(raw_FI, window)

    Parameters
    ----------
    close:
        Price series.
    volume:
        Volume series sharing the same index.
    window:
        EMA smoothing period.  Default 13.

    Returns
    -------
    pd.Series
        Float64 series.
    """
    _validate_cv(close, volume)
    if window < 1:
        raise ValueError(f"window must be >= 1, got {window}")

    from core_trading.indicators.moving_averages import ema as _ema

    raw = (close.diff() * volume).fillna(0.0)
    return _ema(raw, window).astype("float64")


# ---------------------------------------------------------------------------
# Ease of Movement
# ---------------------------------------------------------------------------


def eom(
    high: pd.Series,
    low: pd.Series,
    volume: pd.Series,
    window: int = 14,
    volume_divisor: float = 1_000_000.0,
) -> pd.Series:
    """Ease of Movement (Richard Arms 1989).

    Formula::

        midpoint_move = (high_t + low_t) / 2 - (high_{t-1} + low_{t-1}) / 2
        box_ratio     = (volume / volume_divisor) / (high - low)
        raw_EOM       = midpoint_move / box_ratio
        EOM           = SMA(raw_EOM, window)

    When ``high == low``, box_ratio is set to a tiny value to avoid division
    by zero (result will be very large but finite).

    Parameters
    ----------
    high, low:
        High and low series sharing the same index.
    volume:
        Volume series.
    window:
        SMA smoothing period.  Default 14.
    volume_divisor:
        Scaling divisor for volume (default 1_000_000 scales to millions).

    Returns
    -------
    pd.Series
        Float64 series.  First ``window`` values are ``NaN``.
    """
    if not all(isinstance(s, pd.Series) for s in [high, low, volume]):
        raise ValueError("high, low, volume must all be pd.Series")
    if not (high.index.equals(low.index) and high.index.equals(volume.index)):
        raise ValueError("high, low, volume must share the same index")
    if window < 1:
        raise ValueError(f"window must be >= 1, got {window}")

    mid = (high + low) / 2.0
    mid_move = mid.diff()
    hl = (high - low).replace(0.0, 1e-10)
    box_ratio = (volume / volume_divisor) / hl
    raw = mid_move / box_ratio
    return sma(raw.fillna(0.0), window).astype("float64")
