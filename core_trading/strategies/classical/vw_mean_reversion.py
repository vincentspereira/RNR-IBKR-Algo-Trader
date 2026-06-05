"""Volume-weighted mean-reversion strategy (classical Tier-1 representative).

A from-scratch rewrite of the legacy
``core_trading/strategies/volume_weighted/vw_mean_reversion_strategies.py``
reference. The speculative pillar machinery (smart-money scores, RSI-based
z-score combinations, Nautilus order plumbing, regime DTOs) is discarded.
What remains is a single, clean, look-ahead-free rule.

The rule (entry / filter / exit)
---------------------------------
The strategy measures how far price has deviated from its volume-weighted moving
average (VWMA), normalised by a trailing rolling standard deviation of that
deviation. The resulting z-score is the signal.

1. **Volume-weighted mean.** The centre of the envelope is ``VWMA_t`` over
   ``vwma_window`` bars (sum(close * volume) / sum(volume) over the window).
   Using VWMA rather than a plain SMA means that high-volume bars carry more
   weight; the effective reference price better reflects where the *market*
   has anchored, not just the arithmetic midpoint.

2. **Deviation and rolling standard deviation.** The raw deviation is
   ``dev_t = close_t - VWMA_t``. To normalise it, a rolling standard deviation
   of ``dev`` over ``zscore_window`` bars is computed. The z-score is
   ``z_t = dev_t / rolling_std(dev, zscore_window)_t``.
   Both VWMA and the rolling std use trailing (right-aligned) windows -- the
   value at ``t`` uses only bars ``<= t``.

3. **Volume confirmation gate.** A signal is only acted on when the current
   bar's volume exceeds ``vol_k`` times its trailing ``vol_window``-bar mean.
   Low-volume extreme deviations are often artefacts of thin trading and are
   ignored. This prevents trading on illiquid spikes.

4. **Entry.** When the z-score falls below ``-entry_z`` *and* volume is
   elevated, go long (``+1``) -- the price has been pushed below the
   volume-weighted anchor by more than ``entry_z`` sigma with genuine
   participation. When the z-score exceeds ``+entry_z`` with volume surge, go
   short (``-1``).

5. **Exit.** The position is closed when the z-score reverts inside the
   ``exit_z`` band (``|z_t| < exit_z``). Symmetrically: a long exits when the
   z-score returns above ``-exit_z``; a short exits when the z-score falls
   below ``+exit_z``. The exit does not require a volume surge -- the
   *entry* filters for quality; the *exit* simply tracks price normalisation.
   An opposite-side entry also reverses the position directly.

Look-ahead freeness
-------------------
Every rolling statistic (VWMA, rolling std, rolling vol mean) uses pandas'
trailing (right-aligned) windows with ``min_periods`` set to the full window
so that warmup bars return NaN rather than misleadingly-small denominators.
The state machine is a single forward scan that reads only bar ``t`` and the
carried state from ``< t``. The signal at bar ``t`` is therefore a function
of bars ``<= t`` only. Truncation-invariance is unit-tested.

References
----------
* Bollinger, J. (2001). "Bollinger on Bollinger Bands." McGraw-Hill. (The
  Bollinger %b / z-score framing of price deviation from a moving average.)
* Kahn, M.N. (2006). "Technical Analysis Plain and Simple." FT Press. (VWMA
  as a volume-participation-weighted price anchor.)
* Chan, E.P. (2013). "Algorithmic Trading." Wiley. (Z-score mean-reversion
  entry/exit; OU-process motivation for threshold trading.)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from core_trading.indicators.moving_averages import vwma

__all__ = [
    "VWMeanReversionConfig",
    "vwma_zscore",
    "volume_surge_mask",
    "vw_mean_reversion_signal",
    "vw_mean_reversion_weights",
]

_REQUIRED_COLUMNS = ("close", "volume")


@dataclass(frozen=True, slots=True)
class VWMeanReversionConfig:
    """Configuration for the volume-weighted mean-reversion signal.

    Attributes
    ----------
    vwma_window:
        Lookback (bars) for the volume-weighted moving average centre-line.
        Must be >= 2.
    zscore_window:
        Trailing window (bars) over which the rolling standard deviation of the
        VWMA deviation is computed. Normalising by this rolling std gives the
        z-score. Must be >= 2.
    entry_z:
        Z-score magnitude at which to initiate a position: long when
        ``z < -entry_z``, short when ``z > entry_z``. Must be > 0.
    exit_z:
        Z-score magnitude at which to close the position: the trade exits when
        ``|z| < exit_z``. Must satisfy ``0 <= exit_z < entry_z``.
    vol_window:
        Trailing window (bars) for the volume baseline. Must be >= 2.
    vol_k:
        Volume-surge multiple: volume must exceed ``vol_k`` times the trailing
        mean to confirm a new entry. Must be > 0.
    """

    vwma_window: int = 20
    zscore_window: int = 20
    entry_z: float = 2.0
    exit_z: float = 0.5
    vol_window: int = 20
    vol_k: float = 1.2

    def __post_init__(self) -> None:
        if self.vwma_window < 2:
            raise ValueError("vwma_window must be at least 2 bars")
        if self.zscore_window < 2:
            raise ValueError("zscore_window must be at least 2 bars")
        if self.entry_z <= 0.0:
            raise ValueError("entry_z must be positive")
        if not (0.0 <= self.exit_z < self.entry_z):
            raise ValueError("exit_z must satisfy 0 <= exit_z < entry_z")
        if self.vol_window < 2:
            raise ValueError("vol_window must be at least 2 bars")
        if self.vol_k <= 0.0:
            raise ValueError("vol_k must be positive")


# ---------------------------------------------------------------------------
# Indicator primitives (each pure, trailing-window, look-ahead-free)
# ---------------------------------------------------------------------------


def vwma_zscore(close: pd.Series, volume: pd.Series, config: VWMeanReversionConfig) -> pd.Series:
    """Volume-weighted mean-reversion z-score.

    Computes the deviation of ``close`` from its VWMA, then normalises by the
    rolling standard deviation of that deviation. The result is a z-score that
    is positive when price is above its volume-weighted anchor and negative when
    below. All statistics are trailing (look-ahead-free); NaN during warmup.

    Parameters
    ----------
    close:
        Price series.
    volume:
        Volume series sharing the same index as ``close``.
    config:
        Strategy configuration.

    Returns
    -------
    pd.Series
        Z-score series indexed like ``close``, named ``"vwma_zscore"``.
    """
    anchor = vwma(close, volume, window=config.vwma_window)
    deviation = close - anchor
    rolling_std = deviation.rolling(config.zscore_window, min_periods=config.zscore_window).std(
        ddof=0
    )
    # Avoid division by zero: where rolling_std is zero (constant deviation),
    # the z-score is undefined -- treat as zero (no extreme deviation).
    z = deviation / rolling_std.where(rolling_std > 0.0)
    return z.rename("vwma_zscore")


def volume_surge_mask(volume: pd.Series, config: VWMeanReversionConfig) -> pd.Series:
    """Boolean volume-surge mask: volume above ``vol_k`` x trailing mean.

    Uses a trailing ``vol_window`` mean (look-ahead-free); the warmup window is
    ``False``.

    Parameters
    ----------
    volume:
        Volume series.
    config:
        Strategy configuration.

    Returns
    -------
    pd.Series
        Boolean series indexed like ``volume``, named ``"volume_surge"``.
    """
    baseline = volume.rolling(config.vol_window, min_periods=config.vol_window).mean()
    mask = volume > config.vol_k * baseline
    return (mask & baseline.notna()).rename("volume_surge")


# ---------------------------------------------------------------------------
# Signal state machine
# ---------------------------------------------------------------------------


def vw_mean_reversion_signal(
    ohlcv: pd.DataFrame, config: VWMeanReversionConfig | None = None
) -> pd.Series:
    """Volume-weighted mean-reversion position series in ``{-1, 0, +1}``.

    Implements the entry/filter/exit rule documented in the module docstring.
    The value at bar ``t`` uses only bars ``<= t``.

    Parameters
    ----------
    ohlcv:
        Frame with at least ``close`` and ``volume`` columns and an ascending
        index.
    config:
        Strategy configuration; defaults to :class:`VWMeanReversionConfig`.

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
    cfg = config or VWMeanReversionConfig()
    missing = [c for c in _REQUIRED_COLUMNS if c not in ohlcv.columns]
    if missing:
        raise ValueError(f"ohlcv missing required columns: {missing}")

    close = ohlcv["close"].astype(float)
    volume = ohlcv["volume"].astype(float)

    z = vwma_zscore(close, volume, cfg)
    surge = volume_surge_mask(volume, cfg)

    z_arr = z.to_numpy(dtype=float)
    surge_arr = surge.to_numpy(dtype=bool)

    n = close.shape[0]
    positions = np.zeros(n, dtype=float)
    current = 0.0

    for t in range(n):
        z_t = z_arr[t]
        if not np.isfinite(z_t):
            # Warmup -- all indicators NaN, stay flat.
            current = 0.0
            positions[t] = 0.0
            continue

        long_entry = z_t < -cfg.entry_z and surge_arr[t]
        short_entry = z_t > cfg.entry_z and surge_arr[t]
        long_exit = z_t > -cfg.exit_z  # z has reverted above the exit band
        short_exit = z_t < cfg.exit_z  # z has reverted below the exit band

        if current == 0.0:
            # Initiate only on a volume-confirmed deep deviation.
            if long_entry:
                current = 1.0
            elif short_entry:
                current = -1.0
        elif current == 1.0:
            # Opposite-side entry reverses directly; reversion exits.
            if short_entry:
                current = -1.0
            elif long_exit:
                current = 0.0
        else:  # current == -1.0
            if long_entry:
                current = 1.0
            elif short_exit:
                current = 0.0

        positions[t] = current

    return pd.Series(positions, index=ohlcv.index, name="position")


def vw_mean_reversion_weights(
    ohlcv: pd.DataFrame, config: VWMeanReversionConfig | None = None
) -> pd.Series:
    """Target-weight series for the volume-weighted mean-reversion rule.

    A position of ``+1 / 0 / -1`` maps to a target weight of ``+1 / 0 / -1``
    (full long / flat / full short of equity), matching the single-instrument
    convention used across the Phase 5 adapters. The result is look-ahead-free
    because it is a direct relabel of :func:`vw_mean_reversion_signal`.

    Parameters
    ----------
    ohlcv:
        OHLCV frame (see :func:`vw_mean_reversion_signal`).
    config:
        Strategy configuration.

    Returns
    -------
    pd.Series
        Target weight indexed like ``ohlcv``, named ``"weight"``.
    """
    return vw_mean_reversion_signal(ohlcv, config).rename("weight")
