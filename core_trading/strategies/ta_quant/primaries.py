"""TA primary position rules for the TA x quant mix-and-match strategy factory.

Each function accepts wide OHLCV frames (all ``timestamp x symbol`` DataFrames)
and a frozen config dataclass.  The return value is a
``(timestamp x symbol)`` POSITION frame with values in ``{-1.0, 0.0, +1.0}``.

Look-ahead-free contract
------------------------
Every rule uses only data up to and including bar ``t`` when computing the
position that is *set* at the close of bar ``t``.  The engine applies that
weight to bar ``t+1``'s return, so there is no leakage.  Comparisons against
shifted (lagged) indicator values enforce this: the breakout / cross signal
uses the prior bar's channel/MA to decide whether *today's close* broke out,
which is the correct lag structure for daily bars.

Truncation invariance
---------------------
Because every indicator call is a pure rolling function with a fixed SMA seed
(see ``core_trading.indicators``), and because we never reference global state,
``primary(close[:k], ...)`` equals ``primary(close, ...)[:k]`` on the
overlapping non-NaN region for every ``k``.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from core_trading.indicators.momentum import macd as _macd_ind
from core_trading.indicators.momentum import rsi as _rsi_ind
from core_trading.indicators.moving_averages import ema as _ema_ind
from core_trading.indicators.moving_averages import sma as _sma_ind
from core_trading.indicators.volatility import bollinger_bands as _bb_ind
from core_trading.indicators.volatility import donchian_channels as _dc_ind
from core_trading.indicators.volatility import keltner_channels as _kc_ind

__all__ = [
    "DonchianBreakoutConfig",
    "donchian_breakout",
    "MACrossConfig",
    "ma_cross",
    "RSIDipConfig",
    "rsi_dip",
    "MACDTrendConfig",
    "macd_trend",
    "BollingerFadeConfig",
    "bollinger_fade",
    "KeltnerSqueezeConfig",
    "keltner_squeeze",
]

# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

_POS_DTYPE = "float64"


def _zeros(close: pd.DataFrame) -> pd.DataFrame:
    """Return an all-zero frame with the same shape/index/columns."""
    return pd.DataFrame(
        np.zeros(close.shape, dtype=float), index=close.index, columns=close.columns
    )


def _apply_col(
    fn: Callable[..., pd.Series],
    *frames: pd.DataFrame,
    **kwargs: Any,
) -> pd.DataFrame:
    """Apply a Series -> Series function column-by-column; return a DataFrame."""
    results: dict[str, pd.Series] = {}
    for col in frames[0].columns:
        series_args = [frame[col] for frame in frames]
        results[col] = fn(*series_args, **kwargs)
    return pd.DataFrame(results, index=frames[0].index, dtype=_POS_DTYPE)


# ---------------------------------------------------------------------------
# 1. Donchian Breakout
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DonchianBreakoutConfig:
    """Configuration for :func:`donchian_breakout`.

    Attributes
    ----------
    channel_window:
        Lookback period for Donchian channels (bars).  Default 20 (Turtle
        classic is 20 for entries, 10 for exits).
    exit_window:
        Shorter Donchian window used for the mid-channel exit signal.  When
        ``None``, uses ``channel_window // 2``.
    allow_short:
        When ``True``, open a symmetric short on a lower-channel breakdown.
        Default ``False`` (long-only).
    """

    channel_window: int = 20
    exit_window: int | None = None
    allow_short: bool = False

    def __post_init__(self) -> None:
        if self.channel_window < 2:
            raise ValueError("channel_window must be >= 2")
        ew = self.exit_window if self.exit_window is not None else self.channel_window // 2
        if ew < 1:
            raise ValueError("exit_window must be >= 1")


def donchian_breakout(
    close: pd.DataFrame,
    high: pd.DataFrame,
    low: pd.DataFrame,
    config: DonchianBreakoutConfig,
) -> pd.DataFrame:
    """Classic turtle-style Donchian breakout.

    **Entry:** go long (or short) when close crosses above (below) the prior
    bar's Donchian upper (lower) channel.

    **Exit:** flatten when close crosses below (above) the mid-channel
    computed on a shorter ``exit_window``.

    The prior-bar channel means the breakout comparison is lag-1, which is
    standard for daily systems (you cannot trade the bar whose close set the
    new high -- you trade the *next* bar after the signal fires).

    Parameters
    ----------
    close:
        Wide close-price frame ``(timestamp x symbol)``.
    high:
        Wide high-price frame, same shape.
    low:
        Wide low-price frame, same shape.
    config:
        :class:`DonchianBreakoutConfig` frozen config.

    Returns
    -------
    pd.DataFrame
        Position frame in ``{-1.0, 0.0, +1.0}``.
    """
    exit_win = config.exit_window if config.exit_window is not None else config.channel_window // 2
    pos = _zeros(close)

    for col in close.columns:
        c = close[col]
        h = high[col]
        lo = low[col]

        dc_entry = _dc_ind(h, lo, config.channel_window)
        dc_exit = _dc_ind(h, lo, exit_win)

        # Shift by 1 so entry uses prior bar's channel level (look-ahead-free).
        upper_prev = dc_entry["upper"].shift(1)
        lower_prev = dc_entry["lower"].shift(1)
        mid_exit = dc_exit["mid"]

        position = np.zeros(len(c), dtype=float)
        cur = 0.0
        arr_c = c.to_numpy(dtype=float)
        arr_up = upper_prev.to_numpy(dtype=float)
        arr_lo = lower_prev.to_numpy(dtype=float)
        arr_mid = mid_exit.to_numpy(dtype=float)

        for i in range(len(arr_c)):
            if np.isnan(arr_up[i]) or np.isnan(arr_lo[i]) or np.isnan(arr_mid[i]):
                position[i] = cur
                continue
            price = arr_c[i]
            if cur == 0.0:
                if price > arr_up[i]:
                    cur = 1.0
                elif config.allow_short and price < arr_lo[i]:
                    cur = -1.0
            elif (cur == 1.0 and price < arr_mid[i]) or (cur == -1.0 and price > arr_mid[i]):
                cur = 0.0
            position[i] = cur

        pos[col] = position

    return pos.astype(_POS_DTYPE)


# ---------------------------------------------------------------------------
# 2. MA Cross
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MACrossConfig:
    """Configuration for :func:`ma_cross`.

    Attributes
    ----------
    fast_window:
        Fast EMA period.  Default 20.
    slow_window:
        Slow EMA period.  Default 50.
    long_only:
        When ``True``, hold flat instead of short when fast < slow.
        Default ``False``.
    """

    fast_window: int = 20
    slow_window: int = 50
    long_only: bool = False

    def __post_init__(self) -> None:
        if self.fast_window < 1:
            raise ValueError("fast_window must be >= 1")
        if self.slow_window <= self.fast_window:
            raise ValueError("slow_window must be strictly > fast_window")


def ma_cross(
    close: pd.DataFrame,
    config: MACrossConfig,
) -> pd.DataFrame:
    """EMA crossover trend-following rule.

    Long when the fast EMA is above the slow EMA; short (or flat for
    ``long_only``) when below.  Both EMAs must be valid (post warm-up)
    before any signal is generated.

    Parameters
    ----------
    close:
        Wide close-price frame ``(timestamp x symbol)``.
    config:
        :class:`MACrossConfig` frozen config.

    Returns
    -------
    pd.DataFrame
        Position frame in ``{-1.0, 0.0, +1.0}``.
    """

    def _col(c: pd.Series) -> pd.Series:
        fast = _ema_ind(c, config.fast_window)
        slow = _ema_ind(c, config.slow_window)
        valid = fast.notna() & slow.notna()
        raw = np.where(fast > slow, 1.0, -1.0 if not config.long_only else 0.0)
        result = pd.Series(raw, index=c.index, dtype=_POS_DTYPE)
        result[~valid] = 0.0
        return result

    return _apply_col(_col, close)


# ---------------------------------------------------------------------------
# 3. RSI Dip (Connors-style mean reversion)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RSIDipConfig:
    """Configuration for :func:`rsi_dip`.

    Attributes
    ----------
    rsi_window:
        RSI period.  Default 2 (Connors short-term RSI).
    lower_thresh:
        Entry threshold -- go long when RSI < ``lower_thresh`` (and close >
        trend filter).  Default 10.0.
    upper_thresh:
        Symmetric short entry threshold.  Default 90.0.
    exit_thresh:
        Close the long when RSI rises above ``exit_thresh``.  Default 70.0.
        For shorts the symmetric exit is ``100 - exit_thresh``.
    trend_window:
        SMA period for the trend filter (close must be above this SMA to go
        long, below it to go short).  Default 200.
    allow_short:
        Allow symmetric short trades above the trend filter.  Default ``False``.
    """

    rsi_window: int = 2
    lower_thresh: float = 10.0
    upper_thresh: float = 90.0
    exit_thresh: float = 70.0
    trend_window: int = 200
    allow_short: bool = False

    def __post_init__(self) -> None:
        if self.rsi_window < 1:
            raise ValueError("rsi_window must be >= 1")
        if not (0.0 < self.lower_thresh < self.upper_thresh < 100.0):
            raise ValueError("must have 0 < lower_thresh < upper_thresh < 100")
        if not (0.0 < self.exit_thresh < 100.0):
            raise ValueError("exit_thresh must be in (0, 100)")
        if self.trend_window < 1:
            raise ValueError("trend_window must be >= 1")


def rsi_dip(
    close: pd.DataFrame,
    config: RSIDipConfig,
) -> pd.DataFrame:
    """Connors-style short-term RSI mean-reversion.

    Long entry: RSI(2) < ``lower_thresh`` AND close > SMA(``trend_window``).
    Long exit: RSI(2) > ``exit_thresh``.
    Short entry (if ``allow_short``): RSI(2) > ``upper_thresh`` AND close <
    SMA(``trend_window``).

    Parameters
    ----------
    close:
        Wide close-price frame ``(timestamp x symbol)``.
    config:
        :class:`RSIDipConfig` frozen config.

    Returns
    -------
    pd.DataFrame
        Position frame in ``{-1.0, 0.0, +1.0}``.
    """

    def _col(c: pd.Series) -> pd.Series:
        rsi_vals = _rsi_ind(c, config.rsi_window)
        trend = _sma_ind(c, config.trend_window)
        arr_r = rsi_vals.to_numpy(dtype=float)
        arr_t = trend.to_numpy(dtype=float)
        arr_c = c.to_numpy(dtype=float)
        n = len(arr_c)
        position = np.zeros(n, dtype=float)
        cur = 0.0
        short_exit = 100.0 - config.exit_thresh
        for i in range(n):
            if np.isnan(arr_r[i]) or np.isnan(arr_t[i]):
                position[i] = cur
                continue
            rval = arr_r[i]
            above_trend = arr_c[i] > arr_t[i]
            if cur == 0.0:
                if rval < config.lower_thresh and above_trend:
                    cur = 1.0
                elif config.allow_short and rval > config.upper_thresh and not above_trend:
                    cur = -1.0
            elif (cur == 1.0 and rval > config.exit_thresh) or (
                cur == -1.0 and rval < short_exit
            ):
                cur = 0.0
            position[i] = cur
        return pd.Series(position, index=c.index, dtype=_POS_DTYPE)

    return _apply_col(_col, close)


# ---------------------------------------------------------------------------
# 4. MACD Trend
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MACDTrendConfig:
    """Configuration for :func:`macd_trend`.

    Attributes
    ----------
    fast:
        MACD fast EMA period.  Default 12.
    slow:
        MACD slow EMA period.  Default 26.
    signal_period:
        MACD signal line period.  Default 9.
    allow_short:
        Allow symmetric short when histogram is negative and falling.
        Default ``True``.
    """

    fast: int = 12
    slow: int = 26
    signal_period: int = 9
    allow_short: bool = True

    def __post_init__(self) -> None:
        if self.fast < 1:
            raise ValueError("fast must be >= 1")
        if self.slow <= self.fast:
            raise ValueError("slow must be > fast")
        if self.signal_period < 1:
            raise ValueError("signal_period must be >= 1")


def macd_trend(
    close: pd.DataFrame,
    config: MACDTrendConfig,
) -> pd.DataFrame:
    """MACD histogram trend rule.

    Long when histogram > 0 and rising (histogram > histogram[t-1]).
    Short (or flat if ``allow_short`` is False) when histogram < 0 and falling.

    Parameters
    ----------
    close:
        Wide close-price frame ``(timestamp x symbol)``.
    config:
        :class:`MACDTrendConfig` frozen config.

    Returns
    -------
    pd.DataFrame
        Position frame in ``{-1.0, 0.0, +1.0}``.
    """

    def _col(c: pd.Series) -> pd.Series:
        m = _macd_ind(c, fast=config.fast, slow=config.slow, signal_period=config.signal_period)
        hist = m["histogram"]
        hist_prev = hist.shift(1)
        valid = hist.notna() & hist_prev.notna()
        long_signal = (hist > 0) & (hist > hist_prev)
        short_signal = (hist < 0) & (hist < hist_prev) & config.allow_short
        raw = np.where(long_signal, 1.0, np.where(short_signal, -1.0, 0.0))
        result = pd.Series(raw, index=c.index, dtype=_POS_DTYPE)
        result[~valid] = 0.0
        return result

    return _apply_col(_col, close)


# ---------------------------------------------------------------------------
# 5. Bollinger Fade
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BollingerFadeConfig:
    """Configuration for :func:`bollinger_fade`.

    Attributes
    ----------
    window:
        Bollinger Band SMA/std period.  Default 20.
    num_std:
        Band width multiplier.  Default 2.0.
    min_bandwidth:
        Minimum ``(upper - lower) / mid`` to activate fades (band-width
        floor).  Prevents fading narrow bands during strong breakouts.
        Default 0.02 (2% of price).
    allow_short:
        Allow symmetric short on upper-band touch.  Default ``True``.
    """

    window: int = 20
    num_std: float = 2.0
    min_bandwidth: float = 0.02
    allow_short: bool = True

    def __post_init__(self) -> None:
        if self.window < 2:
            raise ValueError("window must be >= 2")
        if self.num_std <= 0.0:
            raise ValueError("num_std must be > 0")
        if self.min_bandwidth < 0.0:
            raise ValueError("min_bandwidth must be >= 0")


def bollinger_fade(
    close: pd.DataFrame,
    config: BollingerFadeConfig,
) -> pd.DataFrame:
    """Fade Bollinger Band touches back toward the mid.

    Long entry: close touches or goes below the lower band AND bandwidth is
    above ``min_bandwidth`` (i.e. bands are wide enough -- no fading breakouts).
    Exit: close crosses back above the mid (SMA).

    Short entry (if ``allow_short``): close touches or goes above the upper
    band AND bandwidth floor met.  Exit: close crosses below mid.

    Parameters
    ----------
    close:
        Wide close-price frame ``(timestamp x symbol)``.
    config:
        :class:`BollingerFadeConfig` frozen config.

    Returns
    -------
    pd.DataFrame
        Position frame in ``{-1.0, 0.0, +1.0}``.
    """

    def _col(c: pd.Series) -> pd.Series:
        bb = _bb_ind(c, window=config.window, num_std=config.num_std)
        arr_c = c.to_numpy(dtype=float)
        arr_upper = bb["upper"].to_numpy(dtype=float)
        arr_lower = bb["lower"].to_numpy(dtype=float)
        arr_mid = bb["mid"].to_numpy(dtype=float)
        arr_bw = bb["bandwidth"].to_numpy(dtype=float)
        n = len(arr_c)
        position = np.zeros(n, dtype=float)
        cur = 0.0
        for i in range(n):
            if (
                np.isnan(arr_upper[i])
                or np.isnan(arr_lower[i])
                or np.isnan(arr_mid[i])
                or np.isnan(arr_bw[i])
            ):
                position[i] = cur
                continue
            price = arr_c[i]
            wide_enough = arr_bw[i] >= config.min_bandwidth
            if cur == 0.0:
                if price <= arr_lower[i] and wide_enough:
                    cur = 1.0
                elif config.allow_short and price >= arr_upper[i] and wide_enough:
                    cur = -1.0
            elif (cur == 1.0 and price >= arr_mid[i]) or (cur == -1.0 and price <= arr_mid[i]):
                cur = 0.0
            position[i] = cur
        return pd.Series(position, index=c.index, dtype=_POS_DTYPE)

    return _apply_col(_col, close)


# ---------------------------------------------------------------------------
# 6. Keltner Squeeze
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class KeltnerSqueezeConfig:
    """Configuration for :func:`keltner_squeeze`.

    Attributes
    ----------
    bb_window:
        Bollinger Band SMA/std period.  Default 20.
    bb_num_std:
        Bollinger Band multiplier.  Default 2.0.
    kc_ema_period:
        Keltner Channel EMA period.  Default 20.
    kc_atr_period:
        Keltner Channel ATR period.  Default 10.
    kc_multiplier:
        Keltner Channel ATR multiplier.  Default 1.5.
    allow_short:
        Trade the downside expansion as well.  Default ``True``.
    """

    bb_window: int = 20
    bb_num_std: float = 2.0
    kc_ema_period: int = 20
    kc_atr_period: int = 10
    kc_multiplier: float = 1.5
    allow_short: bool = True

    def __post_init__(self) -> None:
        if self.bb_window < 2:
            raise ValueError("bb_window must be >= 2")
        if self.bb_num_std <= 0.0:
            raise ValueError("bb_num_std must be > 0")
        if self.kc_ema_period < 1:
            raise ValueError("kc_ema_period must be >= 1")
        if self.kc_atr_period < 1:
            raise ValueError("kc_atr_period must be >= 1")
        if self.kc_multiplier <= 0.0:
            raise ValueError("kc_multiplier must be > 0")


def keltner_squeeze(
    close: pd.DataFrame,
    high: pd.DataFrame,
    low: pd.DataFrame,
    config: KeltnerSqueezeConfig,
) -> pd.DataFrame:
    """Bollinger-inside-Keltner squeeze momentum breakout.

    **Squeeze:** Bollinger Bands contract inside Keltner Channels (BB upper <
    KC upper AND BB lower > KC lower).  While in squeeze, no position.

    **Breakout:** at the bar the squeeze ends, trade the direction of the
    expansion: long if BB upper >= KC upper (upside breakout), short if BB
    lower <= KC lower (downside) when ``allow_short`` is ``True``.

    **Exit:** hold until the opposite band is touched or the squeeze
    re-forms, at which point flatten.

    Parameters
    ----------
    close:
        Wide close-price frame ``(timestamp x symbol)``.
    high:
        Wide high-price frame.
    low:
        Wide low-price frame.
    config:
        :class:`KeltnerSqueezeConfig` frozen config.

    Returns
    -------
    pd.DataFrame
        Position frame in ``{-1.0, 0.0, +1.0}``.
    """

    def _col(c_s: pd.Series) -> pd.Series:
        hi = high[c_s.name]
        lo = low[c_s.name]
        bb = _bb_ind(c_s, window=config.bb_window, num_std=config.bb_num_std)
        kc = _kc_ind(
            hi,
            lo,
            c_s,
            ema_period=config.kc_ema_period,
            atr_period=config.kc_atr_period,
            multiplier=config.kc_multiplier,
        )
        arr_bb_up = bb["upper"].to_numpy(dtype=float)
        arr_bb_lo = bb["lower"].to_numpy(dtype=float)
        arr_kc_up = kc["upper"].to_numpy(dtype=float)
        arr_kc_lo = kc["lower"].to_numpy(dtype=float)
        n = len(c_s)
        position = np.zeros(n, dtype=float)
        cur = 0.0
        in_squeeze_prev = False
        for i in range(n):
            if (
                np.isnan(arr_bb_up[i])
                or np.isnan(arr_kc_up[i])
                or np.isnan(arr_bb_lo[i])
                or np.isnan(arr_kc_lo[i])
            ):
                in_squeeze_prev = False
                position[i] = cur
                continue
            in_squeeze = arr_bb_up[i] < arr_kc_up[i] and arr_bb_lo[i] > arr_kc_lo[i]
            # Breakout: squeeze just ended
            if in_squeeze_prev and not in_squeeze and cur == 0.0:
                if arr_bb_up[i] >= arr_kc_up[i]:
                    cur = 1.0
                elif config.allow_short and arr_bb_lo[i] <= arr_kc_lo[i]:
                    cur = -1.0
            # Exit: re-squeeze or opposite band touch
            if (cur == 1.0 or cur == -1.0) and in_squeeze:
                cur = 0.0
            position[i] = cur
            in_squeeze_prev = in_squeeze
        return pd.Series(position, index=c_s.index, dtype=_POS_DTYPE)

    results = {}
    for col in close.columns:
        col_series = close[col].copy()
        col_series.name = col
        results[col] = _col(col_series)
    return pd.DataFrame(results, index=close.index, dtype=_POS_DTYPE)
