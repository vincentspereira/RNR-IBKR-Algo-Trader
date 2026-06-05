"""Crabel-class volatility-breakout strategy (classical Tier-1 representative).

This module is a from-scratch rewrite of the legacy
``core_trading/strategies/volatility_breakout`` reference (a heavily-commented
institutional skeleton). The distilled, tradeable core is kept; the speculative
five-pillar scaffolding (execution intents, regime DTOs, smart-money scores) is
discarded. What remains is a single pure rule.

The rule (entry / filter / confirmation / exit)
-----------------------------------------------
Bollinger bands are the volatility envelope: a ``band_window``-bar simple moving
average ``mid`` plus/minus ``band_k`` rolling standard deviations
(``upper = mid + band_k * sd``, ``lower = mid - band_k * sd``). Trading logic, in
priority order at each bar ``t`` (all quantities use data through ``t`` only):

1. **Volatility squeeze filter.** Band width ``w_t = (upper - lower) / mid`` is
   compared against its own trailing distribution over ``squeeze_window`` bars.
   A *squeeze* holds when ``w_t`` sits in the lower ``squeeze_q`` quantile of that
   window -- compressed volatility that historically precedes an expansion
   (Bollinger 2001; Crabel 1990 opening-range/short-pattern breakouts). A breakout
   is only *initiated* when a squeeze occurred on the breakout bar or within the
   preceding ``squeeze_lookback`` bars (contraction precedes expansion), raising
   the breakout's hit rate.
2. **Volume-surge confirmation.** A breakout is confirmed only when current volume
   exceeds ``vol_k`` times its ``vol_window``-bar trailing mean -- the expansion
   must be backed by participation, not a thin-tape spike.
3. **Entry.** With both filters satisfied and the close strictly above ``upper``,
   go long (``+1``); strictly below ``lower``, go short (``-1``).
4. **Exit.** A position is closed when the close returns to the middle band (long
   exits at ``close <= mid``; short exits at ``close >= mid``) -- the classic
   "ride the expansion, exit on mean touch" stop -- or when an opposite-side
   breakout fires (which both exits and *reverses* into the new direction). While
   neither exit nor a fresh squeeze-entry triggers, the existing position is held.

When ``use_atr`` is set, the band half-width is an ATR-based envelope
(``mid +/- band_k * ATR``, Wilder ATR over ``band_window``) instead of the
standard-deviation envelope; the squeeze and volume logic are unchanged. This is
the optional ATR variant the triage flagged.

Look-ahead freeness
-------------------
Every rolling statistic uses pandas' trailing (right-aligned) windows, and the
position state machine is a forward scan that reads only ``t`` and the carried
state from ``< t``. The signal at bar ``t`` is therefore a function of bars
``<= t`` only; the engine earns bar ``t+1``'s return on it. Truncation-invariance
(appending future bars never changes an earlier signal) is unit-tested.

References
----------
* Crabel, T. (1990). "Day Trading with Short Term Price Patterns and Opening
  Range Breakout." Traders Press. (Volatility-expansion breakouts after
  contraction; the squeeze-then-expand premise.)
* Bollinger, J. (2001). "Bollinger on Bollinger Bands." McGraw-Hill. (Band width
  as a volatility gauge; "the Squeeze".)
* Wilder, J.W. (1978). "New Concepts in Technical Trading Systems." (ATR.)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

__all__ = [
    "BreakoutConfig",
    "bollinger_bands",
    "band_width",
    "squeeze_mask",
    "volume_surge_mask",
    "breakout_signal",
    "breakout_weights",
]

_REQUIRED_COLUMNS = ("high", "low", "close", "volume")


@dataclass(frozen=True, slots=True)
class BreakoutConfig:
    """Configuration for the volatility-breakout signal.

    Attributes
    ----------
    band_window:
        Lookback (bars) for the Bollinger middle band and its rolling standard
        deviation (or ATR when ``use_atr`` is set). Must be >= 2.
    band_k:
        Band half-width in standard deviations (or ATR multiples). Must be > 0.
    squeeze_window:
        Trailing window (bars) over which the band width's quantile is measured.
        Must be >= 2.
    squeeze_q:
        Quantile (in ``[0, 1]``) defining the squeeze: a bar is "in a squeeze"
        when its band width is at or below this quantile of the trailing window.
        Lower is stricter.
    squeeze_lookback:
        A breakout is eligible to be initiated if a squeeze occurred on the
        breakout bar OR within the preceding ``squeeze_lookback`` bars -- the
        Crabel premise that *contraction precedes expansion*, so the breakout bar
        itself (now expanding) need not still be inside the squeeze. Must be >= 1.
    vol_window:
        Trailing window (bars) for the average-volume baseline. Must be >= 2.
    vol_k:
        Volume-surge multiple: volume must exceed ``vol_k`` times the trailing
        mean to confirm a breakout. Must be > 0.
    use_atr:
        When ``True`` use a Wilder-ATR band envelope instead of the
        standard-deviation envelope.
    """

    band_window: int = 20
    band_k: float = 2.0
    squeeze_window: int = 50
    squeeze_q: float = 0.25
    squeeze_lookback: int = 5
    vol_window: int = 20
    vol_k: float = 1.5
    use_atr: bool = False

    def __post_init__(self) -> None:
        if self.band_window < 2:
            raise ValueError("band_window must be at least 2 bars")
        if self.band_k <= 0.0:
            raise ValueError("band_k must be positive")
        if self.squeeze_window < 2:
            raise ValueError("squeeze_window must be at least 2 bars")
        if not 0.0 <= self.squeeze_q <= 1.0:
            raise ValueError("squeeze_q must be in [0, 1]")
        if self.squeeze_lookback < 1:
            raise ValueError("squeeze_lookback must be at least 1")
        if self.vol_window < 2:
            raise ValueError("vol_window must be at least 2 bars")
        if self.vol_k <= 0.0:
            raise ValueError("vol_k must be positive")


# ---------------------------------------------------------------------------
# Indicator primitives (each pure, trailing-window, look-ahead-free)
# ---------------------------------------------------------------------------


def _wilder_atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int) -> pd.Series:
    """Wilder's Average True Range over ``window`` bars.

    The true range is ``max(high - low, |high - prev_close|, |low - prev_close|)``;
    the ATR is Wilder's recursive smoothing of it, seeded by the simple mean of the
    first ``window`` true ranges. Returns NaN before the seed is available. Uses
    only trailing data, so it is look-ahead-free.
    """
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    # Wilder smoothing == exponential moving average with alpha = 1/window,
    # seeded by the simple average of the first ``window`` true ranges.
    values = tr.to_numpy(dtype=float)
    n = values.size
    atr = np.full(n, np.nan, dtype=float)
    if n >= window:
        seed = float(np.mean(values[1 : window + 1])) if window >= 1 else np.nan
        # First valid TR is at index 1 (needs prev_close); seed uses bars 1..window.
        atr[window] = seed
        for t in range(window + 1, n):
            atr[t] = (atr[t - 1] * (window - 1) + values[t]) / window
    return pd.Series(atr, index=close.index, name="atr")


def bollinger_bands(
    ohlcv: pd.DataFrame, config: BreakoutConfig
) -> pd.DataFrame:
    """Bollinger (or ATR) band envelope.

    Parameters
    ----------
    ohlcv:
        Frame with at least ``high``, ``low``, ``close`` columns.
    config:
        Band parameters.

    Returns
    -------
    pd.DataFrame
        Columns ``mid``, ``upper``, ``lower`` indexed like ``ohlcv``. NaN during
        the warmup window.
    """
    close = ohlcv["close"].astype(float)
    mid = close.rolling(config.band_window, min_periods=config.band_window).mean()
    if config.use_atr:
        half = config.band_k * _wilder_atr(
            ohlcv["high"].astype(float),
            ohlcv["low"].astype(float),
            close,
            config.band_window,
        )
    else:
        sd = close.rolling(config.band_window, min_periods=config.band_window).std(ddof=0)
        half = config.band_k * sd
    upper = mid + half
    lower = mid - half
    return pd.DataFrame({"mid": mid, "upper": upper, "lower": lower})


def band_width(bands: pd.DataFrame) -> pd.Series:
    """Relative Bollinger band width ``(upper - lower) / mid``.

    A scale-free volatility gauge; NaN where ``mid`` is non-positive or NaN.
    """
    mid = bands["mid"]
    width = (bands["upper"] - bands["lower"]) / mid.where(mid > 0.0)
    return width.rename("band_width")


def squeeze_mask(width: pd.Series, config: BreakoutConfig) -> pd.Series:
    """Boolean squeeze mask: band width in the lower ``squeeze_q`` quantile.

    At each bar the trailing ``squeeze_window`` band-width values are summarised
    by their ``squeeze_q`` quantile (trailing, look-ahead-free); a bar is in a
    squeeze when its own width is at or below that quantile. The first
    ``squeeze_window`` bars (incomplete window) are ``False``.
    """
    threshold = width.rolling(config.squeeze_window, min_periods=config.squeeze_window).quantile(
        config.squeeze_q
    )
    mask = width <= threshold
    return (mask & threshold.notna() & width.notna()).rename("squeeze")


def volume_surge_mask(volume: pd.Series, config: BreakoutConfig) -> pd.Series:
    """Boolean volume-surge mask: volume above ``vol_k`` x trailing mean.

    Uses a trailing ``vol_window`` mean (look-ahead-free); the warmup window is
    ``False``.
    """
    baseline = volume.rolling(config.vol_window, min_periods=config.vol_window).mean()
    mask = volume > config.vol_k * baseline
    return (mask & baseline.notna()).rename("volume_surge")


# ---------------------------------------------------------------------------
# Signal state machine
# ---------------------------------------------------------------------------


def breakout_signal(ohlcv: pd.DataFrame, config: BreakoutConfig | None = None) -> pd.Series:
    """Volatility-breakout position series in ``{-1, 0, +1}``.

    Implements the entry/filter/confirmation/exit rule documented in the module
    docstring. The value at bar ``t`` uses only bars ``<= t``.

    Parameters
    ----------
    ohlcv:
        Frame with ``high``, ``low``, ``close``, ``volume`` columns and an
        ascending index.
    config:
        Strategy configuration; defaults to :class:`BreakoutConfig`.

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
    cfg = config or BreakoutConfig()
    missing = [c for c in _REQUIRED_COLUMNS if c not in ohlcv.columns]
    if missing:
        raise ValueError(f"ohlcv missing required columns: {missing}")

    close = ohlcv["close"].astype(float)
    volume = ohlcv["volume"].astype(float)
    bands = bollinger_bands(ohlcv, cfg)
    width = band_width(bands)
    squeeze = squeeze_mask(width, cfg)
    surge = volume_surge_mask(volume, cfg)
    # A breakout is eligible if a squeeze occurred on this bar OR within the
    # preceding ``squeeze_lookback`` bars (trailing rolling-any, look-ahead-free):
    # contraction precedes the expansion that produces the break.
    recent_squeeze = (
        squeeze.rolling(cfg.squeeze_lookback, min_periods=1).max().astype(bool)
    )

    px = close.to_numpy(dtype=float)
    up = bands["upper"].to_numpy(dtype=float)
    lo = bands["lower"].to_numpy(dtype=float)
    mid = bands["mid"].to_numpy(dtype=float)
    sq = recent_squeeze.to_numpy(dtype=bool)
    vs = surge.to_numpy(dtype=bool)

    n = px.size
    positions = np.zeros(n, dtype=float)
    current = 0.0
    for t in range(n):
        if not (np.isfinite(up[t]) and np.isfinite(lo[t]) and np.isfinite(mid[t])):
            current = 0.0
            positions[t] = 0.0
            continue

        long_break = px[t] > up[t]
        short_break = px[t] < lo[t]
        confirmed = sq[t] and vs[t]

        if current == 0.0:
            # Only initiate out of a confirmed squeeze breakout.
            if confirmed and long_break:
                current = 1.0
            elif confirmed and short_break:
                current = -1.0
        elif current == 1.0:
            # Opposite confirmed breakout reverses; mid touch exits to flat.
            if confirmed and short_break:
                current = -1.0
            elif px[t] <= mid[t]:
                current = 0.0
        else:  # current == -1.0
            if confirmed and long_break:
                current = 1.0
            elif px[t] >= mid[t]:
                current = 0.0
        positions[t] = current

    return pd.Series(positions, index=ohlcv.index, name="position")


def breakout_weights(ohlcv: pd.DataFrame, config: BreakoutConfig | None = None) -> pd.Series:
    """Target-weight series for the volatility-breakout rule.

    A position of ``+1 / 0 / -1`` maps to a target weight of ``+1 / 0 / -1`` (full
    long / flat / full short of equity), matching the single-instrument convention
    used across the Phase 5 adapters. The result is look-ahead-free because it is a
    direct relabel of :func:`breakout_signal`.

    Parameters
    ----------
    ohlcv:
        OHLCV frame (see :func:`breakout_signal`).
    config:
        Strategy configuration.

    Returns
    -------
    pd.Series
        Target weight indexed like ``ohlcv``, named ``"weight"``.
    """
    return breakout_signal(ohlcv, config).rename("weight")
