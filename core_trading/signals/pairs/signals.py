"""Z-score-driven pairs-trading signal state machine (master plan Phase 4.3).

Generates entry, exit, stop-loss, and time-stop signals from a z-score series
produced by :mod:`core_trading.signals.pairs.spread`.

Design notes
------------
* The state machine is purely functional: :func:`generate_pair_signals` walks
  the z-score series bar-by-bar with no look-ahead.  The ``position`` column
  at bar t reflects the trade you *hold* after acting on bar-t information, so
  a backtest applies bar-t position to bar-(t+1) returns.
* NaN z-scores propagate the current state without triggering new entries.
* When ``half_life`` is ``inf`` or NaN the time-stop is disabled.
* Config validation is enforced at construction time via ``__post_init__`` so
  bad parameters are caught early.
"""
from __future__ import annotations

import enum
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

__all__ = [
    "PairState",
    "SignalConfig",
    "generate_pair_signals",
    "signal_to_weights",
]


# ---------------------------------------------------------------------------
# Enumerations and configuration
# ---------------------------------------------------------------------------


class PairState(enum.Enum):
    """Trade state for one pair.

    FLAT:
        No open position.
    LONG_SPREAD:
        Long y / short x (spread expected to rise toward its mean).
    SHORT_SPREAD:
        Short y / long x (spread expected to fall toward its mean).
    """

    FLAT = "flat"
    LONG_SPREAD = "long_spread"
    SHORT_SPREAD = "short_spread"


@dataclass(frozen=True, slots=True)
class SignalConfig:
    """Parameters that control the entry/exit/stop logic.

    Attributes
    ----------
    entry_z:
        Absolute z-score threshold to open a new position. Default 2.0.
    exit_z:
        Absolute z-score threshold at which a position is closed on mean
        reversion (|z| falls below this). Default 0.5.
    stop_z:
        Absolute z-score threshold triggering a stop-loss exit (|z| exceeds
        this). Default 4.0.
    time_stop_mult:
        Multiplier on the half-life: maximum number of bars to hold a
        position = round(time_stop_mult * half_life). Default 3.0.

    Constraints
    -----------
    * entry_z > exit_z >= 0
    * stop_z > entry_z
    * time_stop_mult > 0
    """

    entry_z: float = 2.0
    exit_z: float = 0.5
    stop_z: float = 4.0
    time_stop_mult: float = 3.0

    def __post_init__(self) -> None:
        if self.exit_z < 0:
            raise ValueError("exit_z must be >= 0")
        if self.entry_z <= self.exit_z:
            raise ValueError("entry_z must be strictly greater than exit_z")
        if self.stop_z <= self.entry_z:
            raise ValueError("stop_z must be strictly greater than entry_z")
        if self.time_stop_mult <= 0:
            raise ValueError("time_stop_mult must be > 0")


# ---------------------------------------------------------------------------
# Signal generation
# ---------------------------------------------------------------------------

_REASON_FLAT = "flat"
_REASON_ENTRY_LONG = "entry_long"
_REASON_ENTRY_SHORT = "entry_short"
_REASON_EXIT_MEANREV = "exit_meanrev"
_REASON_STOP_LOSS = "stop_loss"
_REASON_TIME_STOP = "time_stop"
_REASON_HOLD = "hold"

# Module-level default config singleton (avoids B008 mutable-default lint).
_DEFAULT_CONFIG = SignalConfig()


def generate_pair_signals(
    zscore: pd.Series,
    *,
    config: SignalConfig = _DEFAULT_CONFIG,
    half_life: float = float("inf"),
) -> pd.DataFrame:
    """Run the z-score state machine and return per-bar signal data.

    Walks each bar in chronological order, maintaining a state variable and
    a bars-held counter.  No look-ahead: the position at bar t is determined
    solely by z-scores at t and earlier.

    Parameters
    ----------
    zscore:
        The normalised spread z-score series.
    config:
        Entry/exit/stop thresholds.  Defaults to :class:`SignalConfig`.
    half_life:
        Mean-reversion half-life (bars).  Used only for the time-stop.
        Pass ``float("inf")`` or NaN to disable the time-stop.

    Returns
    -------
    pd.DataFrame
        Columns:

        * ``zscore`` -- float, the input z-score at each bar.
        * ``state``  -- str, :class:`PairState` value after acting on bar t.
        * ``position`` -- int in {-1, 0, +1}:
            +1 = long spread (long y / short x),
            -1 = short spread (short y / long x),
            0  = flat.
        * ``reason`` -- str, one of ``"entry_long"``, ``"entry_short"``,
            ``"exit_meanrev"``, ``"stop_loss"``, ``"time_stop"``, ``"hold"``,
            ``"flat"``.
    """
    # Compute the time-stop bar count once.
    if math.isfinite(half_life) and half_life > 0:
        max_bars_held = round(config.time_stop_mult * half_life)
        time_stop_enabled = True
    else:
        max_bars_held = 0
        time_stop_enabled = False

    states: list[str] = []
    positions: list[int] = []
    reasons: list[str] = []

    state = PairState.FLAT
    bars_held = 0

    for z in zscore:
        z_is_nan = not np.isfinite(z) if not isinstance(z, float) else not math.isfinite(z)

        if state == PairState.FLAT:
            if z_is_nan:
                # Stay flat; no new entry on NaN.
                states.append(state.value)
                positions.append(0)
                reasons.append(_REASON_FLAT)
                continue

            if z <= -config.entry_z:
                state = PairState.LONG_SPREAD
                bars_held = 1
                states.append(state.value)
                positions.append(1)
                reasons.append(_REASON_ENTRY_LONG)
            elif z >= config.entry_z:
                state = PairState.SHORT_SPREAD
                bars_held = 1
                states.append(state.value)
                positions.append(-1)
                reasons.append(_REASON_ENTRY_SHORT)
            else:
                states.append(state.value)
                positions.append(0)
                reasons.append(_REASON_FLAT)

        else:
            # In a position (LONG_SPREAD or SHORT_SPREAD).
            position_sign = 1 if state == PairState.LONG_SPREAD else -1

            if z_is_nan:
                # Hold current position; do not count the bar toward time-stop.
                states.append(state.value)
                positions.append(position_sign)
                reasons.append(_REASON_HOLD)
                continue

            # Check exit conditions in priority order:
            # 1. Stop-loss (|z| > stop_z)
            # 2. Time-stop (bars_held >= max_bars_held)
            # 3. Mean-reversion exit (|z| < exit_z)
            # 4. Hold

            abs_z = abs(z)

            if abs_z > config.stop_z:
                state = PairState.FLAT
                bars_held = 0
                states.append(state.value)
                positions.append(0)
                reasons.append(_REASON_STOP_LOSS)
            elif time_stop_enabled and bars_held >= max_bars_held:
                state = PairState.FLAT
                bars_held = 0
                states.append(state.value)
                positions.append(0)
                reasons.append(_REASON_TIME_STOP)
            elif abs_z < config.exit_z:
                state = PairState.FLAT
                bars_held = 0
                states.append(state.value)
                positions.append(0)
                reasons.append(_REASON_EXIT_MEANREV)
            else:
                bars_held += 1
                states.append(state.value)
                positions.append(position_sign)
                reasons.append(_REASON_HOLD)

    return pd.DataFrame(
        {
            "zscore": zscore.to_numpy(dtype=float),
            "state": states,
            "position": positions,
            "reason": reasons,
        },
        index=zscore.index,
    )


# ---------------------------------------------------------------------------
# Convenience helper
# ---------------------------------------------------------------------------


def signal_to_weights(signals: pd.DataFrame, *, gross: float = 1.0) -> pd.Series:
    """Convert the position column to a spread-weight series.

    Maps ``position`` in {-1, 0, +1} to a single per-pair weight scaled by
    ``gross``.  For a gross exposure of 1.0 (default), the spread weight is
    directly the position sign.

    Parameters
    ----------
    signals:
        DataFrame returned by :func:`generate_pair_signals`.
    gross:
        Gross notional multiplier.  Default 1.0.

    Returns
    -------
    pd.Series
        Spread weight series with the same index as ``signals``.
    """
    weights = signals["position"].astype(float) * gross
    weights.name = "spread_weight"
    return weights
