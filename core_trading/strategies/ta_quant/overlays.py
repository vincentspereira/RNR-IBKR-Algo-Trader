"""Composable weight/position overlays for the TA x quant strategy factory.

Each overlay is a frozen-config callable class with a uniform interface::

    overlay.apply(positions_or_weights: pd.DataFrame, close: pd.DataFrame)
        -> pd.DataFrame

The overlay receives the current position or weight frame (same
``timestamp x symbol`` shape as ``close``) and returns a frame of the same
shape with the transformation applied.  Overlays are composable: pass the
output of one as the input of the next.

Trailing-only guarantee
-----------------------
All statistics computed here (volatility, percentiles, scaling factors) use
only data up to and including bar ``t`` at bar ``t`` -- either an expanding
window (for percentile baselines) or a rolling window.  There is no full-
sample normalisation.  The truncation invariance tests in ``tests/ta_quant/``
verify this contract.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from core_trading.indicators.moving_averages import sma as _sma_ind

__all__ = [
    "VolRegimeGate",
    "TrendRegimeGate",
    "VolTargetScaler",
]

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_TRADING_PERIODS = 252


def _rolling_realised_vol(close: pd.DataFrame, window: int) -> pd.Series:
    """Cross-sectional median of per-symbol rolling annualised realised vol.

    Returns a ``pd.Series`` indexed by timestamp (same as ``close.index``).
    Uses log returns and annualises by ``sqrt(252)``.
    """
    log_ret = np.log(close / close.shift(1))
    per_sym_vol = log_ret.rolling(window, min_periods=max(2, window // 2)).std(ddof=1) * np.sqrt(
        float(_TRADING_PERIODS)
    )
    return per_sym_vol.median(axis=1)


def _expanding_percentile(series: pd.Series, pct: float) -> pd.Series:
    """Trailing expanding-window percentile of a series.

    ``result[t] = percentile(series[:t+1], pct)``  (fully trailing, no leak).
    At the first valid bar the percentile equals the value itself.
    """
    arr = series.to_numpy(dtype=float)
    n = len(arr)
    out = np.full(n, np.nan)
    for i in range(n):
        window_vals = arr[: i + 1]
        finite = window_vals[np.isfinite(window_vals)]
        if len(finite) > 0:
            out[i] = float(np.percentile(finite, pct))
    return pd.Series(out, index=series.index, dtype="float64")


# ---------------------------------------------------------------------------
# 1. VolRegimeGate
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VolRegimeGate:
    """Zero out positions when the vol regime fails the gate.

    Parameters
    ----------
    vol_window:
        Rolling window (bars) for realised vol computation.  Default 20.
    percentile_threshold:
        Expanding-window percentile threshold (0-100).  Default 75.
    trade_in_calm:
        When ``True`` (default), pass positions only when current vol is *at
        or below* the threshold (trade the calm regime).
        When ``False``, pass positions only when vol is *above* the threshold
        (trade the stormy regime -- momentum strategies sometimes prefer this).
    """

    vol_window: int = 20
    percentile_threshold: float = 75.0
    trade_in_calm: bool = True

    def __post_init__(self) -> None:
        if self.vol_window < 2:
            raise ValueError("vol_window must be >= 2")
        if not (0.0 <= self.percentile_threshold <= 100.0):
            raise ValueError("percentile_threshold must be in [0, 100]")

    def apply(self, positions: pd.DataFrame, close: pd.DataFrame) -> pd.DataFrame:
        """Apply the vol-regime gate.

        Parameters
        ----------
        positions:
            ``(timestamp x symbol)`` frame of position or weight values.
        close:
            ``(timestamp x symbol)`` close-price frame (same index/columns).

        Returns
        -------
        pd.DataFrame
            Same shape; rows where the gate fires are zeroed.
        """
        med_vol = _rolling_realised_vol(close, self.vol_window)
        pct_threshold = _expanding_percentile(med_vol, self.percentile_threshold)

        gate_open = med_vol <= pct_threshold if self.trade_in_calm else med_vol > pct_threshold

        # Align to positions index (positions may be a subset of close)
        gate_open = gate_open.reindex(positions.index).fillna(False)
        mask = gate_open.to_numpy().reshape(-1, 1)
        result = positions.copy()
        result.values[:] = np.where(mask, positions.to_numpy(), 0.0)
        return result.astype("float64")


# ---------------------------------------------------------------------------
# 2. TrendRegimeGate
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TrendRegimeGate:
    """Per-symbol regime gate: filter positions by trend direction.

    Long positions are only allowed when ``close > SMA(trend_window)``.
    Short positions are only allowed when ``close < SMA(trend_window)``.
    Mixed positions (some symbols long, some short) are each gated per symbol.

    Parameters
    ----------
    trend_window:
        SMA period (bars).  Default 200.
    """

    trend_window: int = 200

    def __post_init__(self) -> None:
        if self.trend_window < 1:
            raise ValueError("trend_window must be >= 1")

    def apply(self, positions: pd.DataFrame, close: pd.DataFrame) -> pd.DataFrame:
        """Apply the per-symbol trend-regime gate.

        Parameters
        ----------
        positions:
            ``(timestamp x symbol)`` frame.
        close:
            ``(timestamp x symbol)`` close-price frame.

        Returns
        -------
        pd.DataFrame
            Positions filtered so longs (>0) only survive above SMA and
            shorts (<0) only survive below SMA.
        """
        sma_frames: dict[str, pd.Series] = {}
        for col in close.columns:
            sma_frames[col] = _sma_ind(close[col], self.trend_window)
        sma = pd.DataFrame(sma_frames, index=close.index).reindex(
            index=positions.index, columns=positions.columns
        )
        close_at_pos = close.reindex(index=positions.index, columns=positions.columns)
        above_trend = (close_at_pos > sma).fillna(False)

        pos_arr = positions.to_numpy(dtype=float)
        above_arr = above_trend.to_numpy()

        # Long allowed only above trend; short allowed only below trend.
        allow_long = above_arr
        allow_short = ~above_arr
        result = np.where(pos_arr > 0, np.where(allow_long, pos_arr, 0.0), pos_arr)
        result = np.where(result < 0, np.where(allow_short, result, 0.0), result)

        return pd.DataFrame(
            result, index=positions.index, columns=positions.columns, dtype="float64"
        )


# ---------------------------------------------------------------------------
# 3. VolTargetScaler
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VolTargetScaler:
    """Scale the weight frame to target a given annualised portfolio volatility.

    At each bar ``t``, the scaling factor is::

        trailing_port_vol = std( sum_i w_{i,t-1} * r_{i,t} , window=vol_window )
                            * sqrt(252)
        scale = target_vol / trailing_port_vol

    Scaling factor is capped at ``max_leverage`` to avoid runaway leverage.
    Trailing-only: only data <= ``t`` is used.

    Parameters
    ----------
    target_vol:
        Annualised target volatility (fraction, e.g. 0.10 = 10%).  Default 0.10.
    vol_window:
        Rolling window (bars) for trailing portfolio vol.  Default 60.
    max_leverage:
        Cap on the scaling factor.  Default 2.0.
    """

    target_vol: float = 0.10
    vol_window: int = 60
    max_leverage: float = 2.0

    def __post_init__(self) -> None:
        if self.target_vol <= 0.0:
            raise ValueError("target_vol must be > 0")
        if self.vol_window < 2:
            raise ValueError("vol_window must be >= 2")
        if self.max_leverage <= 0.0:
            raise ValueError("max_leverage must be > 0")

    def apply(self, weights: pd.DataFrame, close: pd.DataFrame) -> pd.DataFrame:
        """Scale the weight frame so trailing portfolio vol targets ``target_vol``.

        Parameters
        ----------
        weights:
            ``(timestamp x symbol)`` weight frame.
        close:
            ``(timestamp x symbol)`` close-price frame.

        Returns
        -------
        pd.DataFrame
            Rescaled weight frame, same shape.
        """
        close_aligned = close.reindex(index=weights.index, columns=weights.columns).ffill()
        returns = close_aligned.pct_change().fillna(0.0)

        # Realised portfolio return at each bar: use the prior bar's weights
        # (shift(1)) so bar t's return is earned from the position set at t-1.
        w_arr = weights.to_numpy(dtype=float)
        r_arr = returns.to_numpy(dtype=float)

        # Shift weights by 1 bar to get the held weight earning each return.
        w_held = np.vstack([np.zeros((1, w_arr.shape[1])), w_arr[:-1]])
        port_ret = (w_held * r_arr).sum(axis=1)

        port_ret_series = pd.Series(port_ret, index=weights.index)
        port_vol = (
            port_ret_series.rolling(self.vol_window, min_periods=max(2, self.vol_window // 4))
            .std(ddof=1)
            * np.sqrt(float(_TRADING_PERIODS))
        )

        # Compute per-bar scale factor; cap at max_leverage.
        scale = port_vol.copy()
        valid = port_vol.notna() & (port_vol > 0.0)
        scale[valid] = (self.target_vol / port_vol[valid]).clip(upper=self.max_leverage)
        scale[~valid] = 1.0

        scale_arr = scale.to_numpy(dtype=float).reshape(-1, 1)
        result = weights.to_numpy(dtype=float) * scale_arr
        return pd.DataFrame(result, index=weights.index, columns=weights.columns, dtype="float64")
