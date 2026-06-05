"""Vectorised momentum / oscillator functions.

All functions accept ``pd.Series`` or explicit high/low/close/volume Series
arguments and return ``pd.Series`` (or ``pd.DataFrame`` for multi-output)
indexed exactly like the input, ``float64``, with ``NaN`` during warm-up.

Every function is look-ahead-free: value at index ``t`` uses only data
at indices <= ``t``.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core_trading.indicators.moving_averages import ema

__all__ = [
    "rsi",
    "macd",
    "stochastic",
    "stochrsi",
    "cci",
    "williams_r",
    "roc",
    "tsi",
    "ultimate_oscillator",
]


def _validate_series(s: pd.Series, window: int, name: str = "window") -> None:
    if not isinstance(s, pd.Series):
        raise ValueError(f"Expected pd.Series, got {type(s)}")
    if window < 1:
        raise ValueError(f"{name} must be >= 1, got {window}")


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
# RSI -- Wilder smoothing
# ---------------------------------------------------------------------------


def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    """Relative Strength Index (Wilder 1978).

    Uses Wilder's smoothing (alpha = 1/n), not the standard EMA (2/(n+1)).

    Formula::

        delta = close.diff()
        gain_t = max(delta_t, 0)
        loss_t = max(-delta_t, 0)
        avg_gain_0 = SMA(gain, n)
        avg_gain_t = (avg_gain_{t-1} * (n-1) + gain_t) / n   [Wilder]
        RS_t = avg_gain_t / avg_loss_t
        RSI_t = 100 - 100 / (1 + RS_t)

    When avg_loss == 0 and avg_gain > 0, RSI = 100.
    When both are 0, RSI = 50 (convention: no change).

    Wilder's alpha = 1/n vs the standard EMA alpha = 2/(n+1).  The Wilder
    form is the universal standard for RSI and ATR.

    Parameters
    ----------
    close:
        Price series.
    window:
        Period ``n``.  Default 14.

    Returns
    -------
    pd.Series
        Float64 in [0, 100].  First ``window`` values are ``NaN``.
    """
    _validate_series(close, window)
    arr = close.to_numpy(dtype=float)
    n = len(arr)
    out = np.full(n, np.nan)

    if n < window + 1:
        return pd.Series(out, index=close.index, dtype="float64")

    delta = np.diff(arr, prepend=np.nan)  # length n, delta[0] = nan
    gains = np.where(delta > 0, delta, 0.0)
    losses = np.where(delta < 0, -delta, 0.0)

    # Seed: SMA of first `window` changes (indices 1..window)
    avg_gain = float(np.mean(gains[1 : window + 1]))
    avg_loss = float(np.mean(losses[1 : window + 1]))

    def _rs_to_rsi(ag: float, al: float) -> float:
        if al == 0.0:
            return 100.0 if ag > 0.0 else 50.0
        return 100.0 - 100.0 / (1.0 + ag / al)

    out[window] = _rs_to_rsi(avg_gain, avg_loss)

    # Wilder smoothing: alpha = 1/n
    for i in range(window + 1, n):
        avg_gain = (avg_gain * (window - 1) + gains[i]) / window
        avg_loss = (avg_loss * (window - 1) + losses[i]) / window
        out[i] = _rs_to_rsi(avg_gain, avg_loss)

    return pd.Series(out, index=close.index, dtype="float64")


# ---------------------------------------------------------------------------
# MACD
# ---------------------------------------------------------------------------


def macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> pd.DataFrame:
    """Moving Average Convergence/Divergence.

    Formula::

        macd_line  = EMA(close, fast) - EMA(close, slow)
        signal     = EMA(macd_line, signal_period)
        histogram  = macd_line - signal

    All EMAs use the SMA-seed convention (see :func:`ema`).

    Parameters
    ----------
    close:
        Price series.
    fast:
        Fast EMA period.  Default 12.
    slow:
        Slow EMA period.  Default 26.
    signal_period:
        Signal EMA period.  Default 9.

    Returns
    -------
    pd.DataFrame
        Columns: ``macd``, ``signal``, ``histogram``.  Indexed like ``close``.
    """
    _validate_series(close, slow, "slow")
    if fast < 1:
        raise ValueError(f"fast must be >= 1, got {fast}")
    if signal_period < 1:
        raise ValueError(f"signal_period must be >= 1, got {signal_period}")

    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = ema(macd_line, signal_period)
    histogram = macd_line - signal_line

    return pd.DataFrame(
        {
            "macd": macd_line.astype("float64"),
            "signal": signal_line.astype("float64"),
            "histogram": histogram.astype("float64"),
        },
        index=close.index,
    )


# ---------------------------------------------------------------------------
# Stochastic Oscillator
# ---------------------------------------------------------------------------


def stochastic(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    k_period: int = 14,
    d_period: int = 3,
    smooth_k: int = 3,
) -> pd.DataFrame:
    """Stochastic Oscillator (%K and %D).

    Formula::

        raw_K_t = 100 * (close_t - LL_t) / (HH_t - LL_t)
        where HH = rolling max(high, k_period)
              LL = rolling min(low,  k_period)
        %K = SMA(raw_K, smooth_k)       [use smooth_k=1 for fast stochastic]
        %D = SMA(%K, d_period)

    When ``HH == LL``, ``raw_K = 50`` (convention: mid-range).

    Parameters
    ----------
    high, low, close:
        OHLC series sharing the same index.
    k_period:
        %K lookback.  Default 14.
    d_period:
        %D smoothing period.  Default 3.
    smooth_k:
        %K smoothing period (1 = fast stochastic).  Default 3.

    Returns
    -------
    pd.DataFrame
        Columns: ``pct_k``, ``pct_d``.  Indexed like ``close``.
    """
    _validate_ohlc(high, low, close)
    if k_period < 1:
        raise ValueError(f"k_period must be >= 1, got {k_period}")
    if d_period < 1:
        raise ValueError(f"d_period must be >= 1, got {d_period}")
    if smooth_k < 1:
        raise ValueError(f"smooth_k must be >= 1, got {smooth_k}")

    hh = high.rolling(k_period, min_periods=k_period).max()
    ll = low.rolling(k_period, min_periods=k_period).min()
    rng = hh - ll
    raw_k = pd.Series(
        np.where(rng == 0.0, 50.0, 100.0 * (close.values - ll.values) / rng.values),
        index=close.index,
        dtype="float64",
    )
    # Set NaN where hh/ll are NaN (warm-up)
    raw_k = raw_k.where(hh.notna(), other=np.nan)

    pct_k = raw_k.rolling(smooth_k, min_periods=smooth_k).mean().astype("float64")
    pct_d = pct_k.rolling(d_period, min_periods=d_period).mean().astype("float64")

    return pd.DataFrame({"pct_k": pct_k, "pct_d": pct_d}, index=close.index)


# ---------------------------------------------------------------------------
# Stochastic RSI
# ---------------------------------------------------------------------------


def stochrsi(
    close: pd.Series,
    rsi_period: int = 14,
    stoch_period: int = 14,
    k_smooth: int = 3,
    d_smooth: int = 3,
) -> pd.DataFrame:
    """Stochastic RSI.

    Formula::

        RSI_t = rsi(close, rsi_period)
        min_rsi = rolling_min(RSI, stoch_period)
        max_rsi = rolling_max(RSI, stoch_period)
        raw_stochrsi = 100 * (RSI - min_rsi) / (max_rsi - min_rsi)
        %K = SMA(raw_stochrsi, k_smooth)
        %D = SMA(%K, d_smooth)

    When ``max_rsi == min_rsi``, raw value = 50.

    Parameters
    ----------
    close:
        Price series.
    rsi_period:
        RSI calculation period.  Default 14.
    stoch_period:
        Stochastic lookback on RSI values.  Default 14.
    k_smooth:
        %K smoothing.  Default 3.
    d_smooth:
        %D smoothing.  Default 3.

    Returns
    -------
    pd.DataFrame
        Columns: ``pct_k``, ``pct_d``.
    """
    _validate_series(close, rsi_period, "rsi_period")
    if stoch_period < 1:
        raise ValueError(f"stoch_period must be >= 1, got {stoch_period}")

    rsi_vals = rsi(close, rsi_period)
    rsi_min = rsi_vals.rolling(stoch_period, min_periods=stoch_period).min()
    rsi_max = rsi_vals.rolling(stoch_period, min_periods=stoch_period).max()
    rng = rsi_max - rsi_min
    raw = pd.Series(
        np.where(rng == 0.0, 50.0, 100.0 * (rsi_vals.values - rsi_min.values) / rng.values),
        index=close.index,
        dtype="float64",
    )
    raw = raw.where(rsi_min.notna(), other=np.nan)

    pct_k = raw.rolling(k_smooth, min_periods=k_smooth).mean().astype("float64")
    pct_d = pct_k.rolling(d_smooth, min_periods=d_smooth).mean().astype("float64")
    return pd.DataFrame({"pct_k": pct_k, "pct_d": pct_d}, index=close.index)


# ---------------------------------------------------------------------------
# Commodity Channel Index
# ---------------------------------------------------------------------------


def cci(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    window: int = 20,
    constant: float = 0.015,
) -> pd.Series:
    """Commodity Channel Index (Lambert 1980).

    Formula::

        TP  = (high + low + close) / 3
        SMA = rolling_mean(TP, n)
        MAD = rolling_mean(|TP - SMA|, n)
        CCI = (TP - SMA) / (constant * MAD)

    Parameters
    ----------
    high, low, close:
        OHLC series sharing the same index.
    window:
        Lookback period.  Default 20.
    constant:
        Scaling constant, typically 0.015.

    Returns
    -------
    pd.Series
        Float64 series.
    """
    _validate_ohlc(high, low, close)
    if window < 1:
        raise ValueError(f"window must be >= 1, got {window}")

    tp = (high + low + close) / 3.0
    tp_sma = tp.rolling(window, min_periods=window).mean()
    mad = (tp - tp_sma).abs().rolling(window, min_periods=window).mean()
    # Use np.divide with where to avoid RuntimeWarning from 0-division in NaN-masked cells.
    safe_denom = np.where(mad.values == 0.0, 1.0, constant * mad.values)
    raw = np.where(mad.values == 0.0, 0.0, (tp.values - tp_sma.values) / safe_denom)
    result = pd.Series(raw, index=close.index, dtype="float64")
    return result.where(tp_sma.notna(), other=np.nan)


# ---------------------------------------------------------------------------
# Williams %R
# ---------------------------------------------------------------------------


def williams_r(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    window: int = 14,
) -> pd.Series:
    """Williams Percent Range (Larry Williams 1973).

    Formula::

        HH = rolling_max(high, n)
        LL = rolling_min(low,  n)
        %R = -100 * (HH - close) / (HH - LL)

    Range is [-100, 0].  When HH == LL, returns -50 (convention).

    Parameters
    ----------
    high, low, close:
        OHLC series sharing the same index.
    window:
        Lookback period.  Default 14.

    Returns
    -------
    pd.Series
        Float64 series in [-100, 0].
    """
    _validate_ohlc(high, low, close)
    if window < 1:
        raise ValueError(f"window must be >= 1, got {window}")

    hh = high.rolling(window, min_periods=window).max()
    ll = low.rolling(window, min_periods=window).min()
    rng = hh - ll
    result = pd.Series(
        np.where(rng == 0.0, -50.0, -100.0 * (hh.values - close.values) / rng.values),
        index=close.index,
        dtype="float64",
    )
    return result.where(hh.notna(), other=np.nan)


# ---------------------------------------------------------------------------
# Rate of Change
# ---------------------------------------------------------------------------


def roc(close: pd.Series, window: int = 12) -> pd.Series:
    """Rate of Change (percentage momentum).

    Formula::

        ROC_t = 100 * (close_t - close_{t-n}) / close_{t-n}

    Parameters
    ----------
    close:
        Price series.
    window:
        Lookback period.  Default 12.

    Returns
    -------
    pd.Series
        Float64 series.  First ``window`` values are ``NaN``.
    """
    _validate_series(close, window)
    shifted = close.shift(window)
    result = 100.0 * (close - shifted) / shifted
    return result.astype("float64")


# ---------------------------------------------------------------------------
# True Strength Index
# ---------------------------------------------------------------------------


def tsi(
    close: pd.Series,
    long_period: int = 25,
    short_period: int = 13,
    signal_period: int = 7,
) -> pd.DataFrame:
    """True Strength Index (William Blau 1991).

    Formula::

        PC  = close.diff()
        DS1 = EMA(PC, long_period)        [double-smooth numerator]
        DS2 = EMA(DS1, short_period)
        ADS1= EMA(|PC|, long_period)      [double-smooth denominator]
        ADS2= EMA(ADS1, short_period)
        TSI = 100 * DS2 / ADS2
        signal = EMA(TSI, signal_period)

    Parameters
    ----------
    close:
        Price series.
    long_period:
        First smoothing period.  Default 25.
    short_period:
        Second smoothing period.  Default 13.
    signal_period:
        Signal line period.  Default 7.

    Returns
    -------
    pd.DataFrame
        Columns: ``tsi``, ``signal``.
    """
    _validate_series(close, long_period, "long_period")
    if short_period < 1:
        raise ValueError(f"short_period must be >= 1, got {short_period}")
    if signal_period < 1:
        raise ValueError(f"signal_period must be >= 1, got {signal_period}")

    pc = close.diff()
    abs_pc = pc.abs()

    ds2 = ema(ema(pc.fillna(0.0), long_period), short_period)
    ads2 = ema(ema(abs_pc.fillna(0.0), long_period), short_period)

    # NaN where warm-up is incomplete
    tsi_vals = pd.Series(
        np.where(ads2 == 0.0, 0.0, 100.0 * ds2.values / ads2.values),
        index=close.index,
        dtype="float64",
    )
    # Restore NaN during joint warm-up
    valid_mask = ds2.notna() & ads2.notna() & pc.notna()
    tsi_vals = tsi_vals.where(valid_mask, other=np.nan)

    signal_vals = ema(tsi_vals, signal_period).astype("float64")
    return pd.DataFrame({"tsi": tsi_vals, "signal": signal_vals}, index=close.index)


# ---------------------------------------------------------------------------
# Ultimate Oscillator
# ---------------------------------------------------------------------------


def ultimate_oscillator(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period1: int = 7,
    period2: int = 14,
    period3: int = 28,
) -> pd.Series:
    """Ultimate Oscillator (Larry Williams 1976).

    Formula::

        BP_t = close_t - min(low_t, close_{t-1})
        TR_t = max(high_t, close_{t-1}) - min(low_t, close_{t-1})
        avg_p = sum(BP, p) / sum(TR, p)  for p in {period1, period2, period3}
        UO = 100 * (4*avg1 + 2*avg2 + avg3) / 7

    Parameters
    ----------
    high, low, close:
        OHLC series sharing the same index.
    period1:
        Short period.  Default 7.
    period2:
        Medium period.  Default 14.
    period3:
        Long period.  Default 28.

    Returns
    -------
    pd.Series
        Float64 in [0, 100].  Warm-up is ``period3`` bars.
    """
    _validate_ohlc(high, low, close)
    for p, name in [(period1, "period1"), (period2, "period2"), (period3, "period3")]:
        if p < 1:
            raise ValueError(f"{name} must be >= 1, got {p}")

    prev_close = close.shift(1)
    bp = close - pd.concat([low, prev_close], axis=1).min(axis=1)
    tr = pd.concat([high, prev_close], axis=1).max(axis=1) - pd.concat(
        [low, prev_close], axis=1
    ).min(axis=1)

    # Rolling sums -- NaN where window is not full
    def _avg(p: int) -> pd.Series:
        bp_sum = bp.rolling(p, min_periods=p).sum()
        tr_sum = tr.rolling(p, min_periods=p).sum()
        return pd.Series(
            np.where(tr_sum == 0.0, 0.0, bp_sum.values / tr_sum.values),
            index=close.index,
            dtype="float64",
        ).where(tr_sum.notna(), other=np.nan)

    avg1 = _avg(period1)
    avg2 = _avg(period2)
    avg3 = _avg(period3)

    uo = 100.0 * (4.0 * avg1 + 2.0 * avg2 + avg3) / 7.0
    return uo.astype("float64")
