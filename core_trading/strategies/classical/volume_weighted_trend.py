"""Volume-weighted trend-following strategy (classical Tier-1 representative).

A from-scratch rewrite of the legacy
``core_trading/strategies/volume_weighted/vw_trend_following_strategies.py``
reference. The distilled, tradeable core is kept; the speculative pillar
machinery (smart-money scores, regime DTOs, execution priorities, Nautilus order
plumbing) is discarded.

The rule (entry / confirmation / filter / exit)
-----------------------------------------------
1. **Trend direction -- volume-weighted EMA crossover.** A fast and a slow
   volume-weighted EMA (default 12 / 26) are computed. Long bias when
   ``vw_ema_fast > vw_ema_slow``; short bias when ``vw_ema_fast < vw_ema_slow``.
2. **Momentum confirmation -- volume-weighted MACD.** The VW-MACD line is
   ``vw_ema_fast - vw_ema_slow``; its signal line is a *plain* EMA of the MACD
   line over ``signal_window`` (default 9). A long is confirmed only when
   ``macd > macd_signal`` (positive momentum); a short only when
   ``macd < macd_signal``. This prevents acting on a stale crossover.
3. **Strength filter -- Wilder ADX.** ADX (default 14) gates trading: ADX >=
   ``adx_strong`` (default 25) is a strong trend (trade), ``adx_medium`` (default
   20) <= ADX < ``adx_strong`` is a medium trend (trade), and ADX <
   ``adx_medium`` is no-trade (flat) -- a chop filter. Both bands trade; only the
   sub-``adx_medium`` regime is suppressed.
4. **Position / exit.** The bar's position is the agreed direction when the trend,
   momentum *and* strength conditions all align, else flat. There is no separate
   stop: a trend reversal or a fall into the no-trade ADX band flattens (or flips)
   the position on the next qualifying bar. The position is a stateless function
   of the indicators at ``t``, so it is trivially look-ahead-free.

Volume-weighted EMA (precise definition)
----------------------------------------
The volume-weighted EMA blends the standard EMA recursion with the bar's volume
weight so that high-volume bars move the average more. With smoothing
``alpha = 2 / (period + 1)`` and a per-bar relative volume weight
``v_t = volume_t / sma(volume, period)_t`` (clipped to ``[w_min, w_max]`` for
numerical safety), the recursion is::

    a_t   = alpha * v_t                  (effective, volume-scaled smoothing)
    vwema_t = (1 - a_t) * vwema_{t-1} + a_t * price_t

seeded with ``vwema_0 = price_0``. When every ``v_t == 1`` (constant volume) this
collapses *exactly* to the standard EMA ``vwema_t = (1-alpha) vwema_{t-1} + alpha
price_t`` -- a property pinned by a unit test against ``pandas.Series.ewm``. The
weight is a trailing ratio, so the recursion is causal / look-ahead-free.

Wilder ADX
----------
Standard Wilder (1978) construction: directional movement ``+DM`` / ``-DM`` from
successive highs/lows, smoothed true range, ``+DI`` / ``-DI`` ratios,
``DX = 100 * |+DI - -DI| / (+DI + -DI)`` and ``ADX`` as the Wilder-smoothed DX.

References
----------
* Wilder, J.W. (1978). "New Concepts in Technical Trading Systems." (ADX, ATR.)
* Appel, G. (2005). "Technical Analysis: Power Tools for Active Investors."
  (MACD.)
* Volume weighting follows the standard VWMA/VWAP intuition (high-volume bars
  carry more weight); see Bollinger (2001) for volume-weighted band variants.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

__all__ = [
    "VWTrendConfig",
    "vw_ema",
    "vw_macd",
    "wilder_adx",
    "vw_trend_signal",
    "vw_trend_weights",
]

_REQUIRED_COLUMNS = ("high", "low", "close", "volume")


@dataclass(frozen=True, slots=True)
class VWTrendConfig:
    """Configuration for the volume-weighted trend signal.

    Attributes
    ----------
    fast_window, slow_window:
        VW-EMA periods for the crossover (``fast < slow``). Both >= 2.
    signal_window:
        EMA period of the MACD signal line. Must be >= 2.
    adx_window:
        Wilder ADX period. Must be >= 2.
    adx_strong, adx_medium:
        ADX thresholds. ADX >= ``adx_strong`` is a strong trend; ``adx_medium`` <=
        ADX < ``adx_strong`` is a medium trend (both trade). ADX < ``adx_medium``
        is the no-trade band. Require ``0 < adx_medium <= adx_strong``.
    vol_window:
        Trailing window for the relative-volume baseline used by the VW-EMA. >= 2.
    weight_clip:
        ``(w_min, w_max)`` clip applied to the per-bar relative volume weight to
        keep the volume-scaled smoothing in ``(0, 1)`` and numerically stable.
        Require ``0 < w_min <= 1 <= w_max``.
    """

    fast_window: int = 12
    slow_window: int = 26
    signal_window: int = 9
    adx_window: int = 14
    adx_strong: float = 25.0
    adx_medium: float = 20.0
    vol_window: int = 20
    weight_clip: tuple[float, float] = (0.2, 3.0)

    def __post_init__(self) -> None:
        if self.fast_window < 2 or self.slow_window < 2:
            raise ValueError("fast_window and slow_window must be at least 2")
        if self.fast_window >= self.slow_window:
            raise ValueError("fast_window must be strictly less than slow_window")
        if self.signal_window < 2:
            raise ValueError("signal_window must be at least 2")
        if self.adx_window < 2:
            raise ValueError("adx_window must be at least 2")
        if not (0.0 < self.adx_medium <= self.adx_strong):
            raise ValueError("require 0 < adx_medium <= adx_strong")
        if self.vol_window < 2:
            raise ValueError("vol_window must be at least 2")
        w_min, w_max = self.weight_clip
        if not (0.0 < w_min <= 1.0 <= w_max):
            raise ValueError("weight_clip must satisfy 0 < w_min <= 1 <= w_max")


# ---------------------------------------------------------------------------
# Volume-weighted EMA and MACD
# ---------------------------------------------------------------------------


def vw_ema(
    price: pd.Series,
    volume: pd.Series,
    *,
    period: int,
    vol_window: int,
    weight_clip: tuple[float, float] = (0.2, 3.0),
) -> pd.Series:
    """Volume-weighted EMA (see module docstring for the precise recursion).

    Parameters
    ----------
    price, volume:
        Aligned price and volume series.
    period:
        EMA period; ``alpha = 2 / (period + 1)``. Must be >= 1.
    vol_window:
        Trailing window for the relative-volume baseline ``sma(volume)``.
    weight_clip:
        Clip applied to the relative volume weight ``v_t``.

    Returns
    -------
    pd.Series
        VW-EMA indexed like ``price``, named ``"vw_ema"``.

    Notes
    -----
    With constant volume every ``v_t == 1`` and the series equals the standard
    ``price.ewm(span=period, adjust=False).mean()`` exactly.
    """
    if period < 1:
        raise ValueError("period must be at least 1")
    alpha = 2.0 / (period + 1.0)
    w_min, w_max = weight_clip

    p = price.to_numpy(dtype=float)
    v = volume.to_numpy(dtype=float)
    n = p.size

    # Trailing relative-volume weight. min_periods=1 so early bars (before the
    # full vol_window) still get a sensible baseline from the bars seen so far;
    # under constant volume the ratio is 1 from bar 0, preserving the EMA identity.
    baseline = (
        pd.Series(v, index=price.index)
        .rolling(vol_window, min_periods=1)
        .mean()
        .to_numpy(dtype=float)
    )

    out = np.full(n, np.nan, dtype=float)
    if n == 0:
        return pd.Series(out, index=price.index, name="vw_ema")

    out[0] = p[0]
    prev = p[0]
    for t in range(1, n):
        base = baseline[t]
        rel = v[t] / base if (base > 0.0 and np.isfinite(base)) else 1.0
        rel = min(max(rel, w_min), w_max)
        a = alpha * rel
        prev = (1.0 - a) * prev + a * p[t]
        out[t] = prev
    return pd.Series(out, index=price.index, name="vw_ema")


def vw_macd(
    price: pd.Series,
    volume: pd.Series,
    config: VWTrendConfig,
) -> pd.DataFrame:
    """Volume-weighted MACD line and its (plain-EMA) signal line.

    The MACD line is ``vw_ema(fast) - vw_ema(slow)``; the signal line is a standard
    EMA of the MACD line over ``signal_window``. Both are causal.

    Returns
    -------
    pd.DataFrame
        Columns ``vw_ema_fast``, ``vw_ema_slow``, ``macd``, ``macd_signal``.
    """
    fast = vw_ema(
        price,
        volume,
        period=config.fast_window,
        vol_window=config.vol_window,
        weight_clip=config.weight_clip,
    )
    slow = vw_ema(
        price,
        volume,
        period=config.slow_window,
        vol_window=config.vol_window,
        weight_clip=config.weight_clip,
    )
    macd = fast - slow
    signal = macd.ewm(span=config.signal_window, adjust=False).mean()
    return pd.DataFrame(
        {
            "vw_ema_fast": fast,
            "vw_ema_slow": slow,
            "macd": macd,
            "macd_signal": signal,
        }
    )


# ---------------------------------------------------------------------------
# Wilder ADX
# ---------------------------------------------------------------------------


def _wilder_smooth(values: np.ndarray, window: int) -> np.ndarray:
    """Wilder's recursive smoothing seeded by the sum of the first ``window`` bars.

    Returns an array aligned to ``values``; entries before the seed are NaN. This
    is the running-sum form Wilder used for +DM/-DM/TR (``S_t = S_{t-1} -
    S_{t-1}/window + x_t``), not the mean form.
    """
    n = values.size
    out = np.full(n, np.nan, dtype=float)
    if n <= window:
        return out
    # Seed at index ``window`` with the sum of bars 1..window (index 0 has no DM/TR).
    seed = float(np.sum(values[1 : window + 1]))
    out[window] = seed
    for t in range(window + 1, n):
        out[t] = out[t - 1] - out[t - 1] / window + values[t]
    return out


def wilder_adx(
    high: pd.Series, low: pd.Series, close: pd.Series, *, window: int
) -> pd.Series:
    """Wilder's Average Directional Index (ADX).

    Standard construction: directional movement, Wilder-smoothed TR/+DM/-DM,
    ``+DI`` / ``-DI``, ``DX = 100 |+DI - -DI| / (+DI + -DI)`` and the Wilder-smoothed
    DX. Uses only trailing data, so it is look-ahead-free.

    Parameters
    ----------
    high, low, close:
        Aligned OHLC series.
    window:
        Wilder period (>= 2).

    Returns
    -------
    pd.Series
        ADX in ``[0, 100]`` indexed like ``close``, named ``"adx"``; NaN during the
        (double) warmup.
    """
    if window < 2:
        raise ValueError("window must be at least 2")
    h = high.to_numpy(dtype=float)
    lo = low.to_numpy(dtype=float)
    c = close.to_numpy(dtype=float)
    n = c.size

    up_move = np.zeros(n, dtype=float)
    down_move = np.zeros(n, dtype=float)
    tr = np.zeros(n, dtype=float)
    for t in range(1, n):
        up = h[t] - h[t - 1]
        down = lo[t - 1] - lo[t]
        up_move[t] = up if (up > down and up > 0.0) else 0.0
        down_move[t] = down if (down > up and down > 0.0) else 0.0
        tr[t] = max(h[t] - lo[t], abs(h[t] - c[t - 1]), abs(lo[t] - c[t - 1]))

    sm_tr = _wilder_smooth(tr, window)
    sm_plus = _wilder_smooth(up_move, window)
    sm_minus = _wilder_smooth(down_move, window)

    with np.errstate(divide="ignore", invalid="ignore"):
        plus_di = 100.0 * sm_plus / sm_tr
        minus_di = 100.0 * sm_minus / sm_tr
        di_sum = plus_di + minus_di
        dx = 100.0 * np.abs(plus_di - minus_di) / di_sum
    dx = np.where(np.isfinite(dx), dx, np.nan)

    # ADX = Wilder-smoothed (mean form) DX, seeded by the mean of the first
    # ``window`` valid DX values, which begin at index ``window``.
    adx = np.full(n, np.nan, dtype=float)
    first = window  # first index with a finite DX
    seed_end = first + window
    if seed_end <= n:
        seed_slice = dx[first:seed_end]
        if np.all(np.isfinite(seed_slice)):
            adx[seed_end - 1] = float(np.mean(seed_slice))
            for t in range(seed_end, n):
                prev = adx[t - 1]
                cur = dx[t]
                if np.isfinite(cur):
                    adx[t] = (prev * (window - 1) + cur) / window
                else:  # pragma: no cover - defensive: DX is finite once ADX is seeded
                    adx[t] = prev
    return pd.Series(adx, index=close.index, name="adx")


# ---------------------------------------------------------------------------
# Combined signal
# ---------------------------------------------------------------------------


def vw_trend_signal(ohlcv: pd.DataFrame, config: VWTrendConfig | None = None) -> pd.Series:
    """Volume-weighted trend position series in ``{-1, 0, +1}``.

    Combines the VW-EMA crossover (direction), VW-MACD (momentum confirmation) and
    Wilder ADX (strength gate) per the module docstring. The value at bar ``t``
    uses only bars ``<= t``.

    Parameters
    ----------
    ohlcv:
        Frame with ``high``, ``low``, ``close``, ``volume`` columns.
    config:
        Strategy configuration; defaults to :class:`VWTrendConfig`.

    Returns
    -------
    pd.Series
        Position in ``{-1.0, 0.0, 1.0}`` indexed like ``ohlcv``, named
        ``"position"``.

    Raises
    ------
    ValueError
        If a required column is missing.
    """
    cfg = config or VWTrendConfig()
    missing = [col for col in _REQUIRED_COLUMNS if col not in ohlcv.columns]
    if missing:
        raise ValueError(f"ohlcv missing required columns: {missing}")

    close = ohlcv["close"].astype(float)
    volume = ohlcv["volume"].astype(float)
    macd_df = vw_macd(close, volume, cfg)
    adx = wilder_adx(
        ohlcv["high"].astype(float),
        ohlcv["low"].astype(float),
        close,
        window=cfg.adx_window,
    )

    fast = macd_df["vw_ema_fast"].to_numpy(dtype=float)
    slow = macd_df["vw_ema_slow"].to_numpy(dtype=float)
    macd = macd_df["macd"].to_numpy(dtype=float)
    macd_sig = macd_df["macd_signal"].to_numpy(dtype=float)
    adx_v = adx.to_numpy(dtype=float)

    n = close.shape[0]
    positions = np.zeros(n, dtype=float)
    for t in range(n):
        if not np.isfinite(adx_v[t]):
            continue
        if adx_v[t] < cfg.adx_medium:
            continue  # no-trade chop band -> flat
        if not (np.isfinite(fast[t]) and np.isfinite(slow[t])
                and np.isfinite(macd[t]) and np.isfinite(macd_sig[t])):
            continue  # pragma: no cover - defensive: VW-EMA finite once ADX is
        long_ok = fast[t] > slow[t] and macd[t] > macd_sig[t]
        short_ok = fast[t] < slow[t] and macd[t] < macd_sig[t]
        if long_ok:
            positions[t] = 1.0
        elif short_ok:
            positions[t] = -1.0
    return pd.Series(positions, index=ohlcv.index, name="position")


def vw_trend_weights(ohlcv: pd.DataFrame, config: VWTrendConfig | None = None) -> pd.Series:
    """Target-weight series for the volume-weighted trend rule.

    A position of ``+1 / 0 / -1`` maps to a target weight of ``+1 / 0 / -1`` (full
    long / flat / full short of equity). A direct relabel of
    :func:`vw_trend_signal`, so it inherits look-ahead freeness.

    Parameters
    ----------
    ohlcv:
        OHLCV frame (see :func:`vw_trend_signal`).
    config:
        Strategy configuration.

    Returns
    -------
    pd.Series
        Target weight indexed like ``ohlcv``, named ``"weight"``.
    """
    return vw_trend_signal(ohlcv, config).rename("weight")
