"""Phase-5-style evaluation adapter: classical volume-weighted trend (gate wiring).

Wires :mod:`core_trading.strategies.classical.volume_weighted_trend` through the
evaluation gate (:mod:`core_trading.research.signal_evaluation`) to close the
Definition-of-Done loop (backtest + deflated Sharpe + PROMOTE/ARCHIVE verdict).

Like the breakout adapter, the VW-trend rule needs the full
``high / low / close / volume`` panel (Wilder ADX uses high/low; the VW-EMA uses
volume), so it reuses :func:`~core_trading.research.signal_adapters.classical_breakout.ohlcv_panel`
to build a real OHLCV engine panel and reads those columns back out inside the
weight rule.

Swept knobs
-----------
The cheap swept parameters are the ADX gate thresholds (``adx_strong`` /
``adx_medium``) -- how demanding the trend-strength filter is. The VW-EMA / MACD
periods are held fixed at their classical defaults (12 / 26 / 9).
"""
from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from core_trading.research.signal_adapters.classical_breakout import ohlcv_panel
from core_trading.research.signal_evaluation import (
    SignalEvaluation,
    WeightRule,
    evaluate_signal,
    positions_to_weights,
)
from core_trading.strategies.classical.volume_weighted_trend import (
    VWTrendConfig,
    vw_trend_signal,
)

__all__ = [
    "build_vw_trend_weight_fn",
    "vw_trend_grid",
    "evaluate_vw_trend",
]


def build_vw_trend_weight_fn(
    *,
    symbol: str = "SIM",
    base_config: VWTrendConfig | None = None,
) -> WeightRule:
    """Build a :data:`WeightRule` for the volume-weighted trend rule.

    The returned rule reads ``high / low / close / volume`` out of the engine panel
    and applies :func:`vw_trend_signal` with the swept ADX thresholds overlaid on
    ``base_config``. Each configuration may supply ``"adx_strong"`` and/or
    ``"adx_medium"``; absent keys fall back to ``base_config``.

    Parameters
    ----------
    symbol:
        Symbol label matching the panel.
    base_config:
        Fixed configuration; the swept keys override its ADX thresholds.

    Returns
    -------
    WeightRule
        A ``(panel, params) -> weights`` callable.
    """
    base = base_config or VWTrendConfig()

    def weight_rule(panel: pd.DataFrame, params: Mapping[str, float]) -> pd.DataFrame:
        frame = panel.xs(symbol, level="symbol")
        cfg = VWTrendConfig(
            fast_window=base.fast_window,
            slow_window=base.slow_window,
            signal_window=base.signal_window,
            adx_window=base.adx_window,
            adx_strong=float(params.get("adx_strong", base.adx_strong)),
            adx_medium=float(params.get("adx_medium", base.adx_medium)),
            vol_window=base.vol_window,
            weight_clip=base.weight_clip,
        )
        positions = vw_trend_signal(frame, cfg)
        return positions_to_weights(positions, symbol=symbol)

    return weight_rule


def vw_trend_grid(
    *,
    thresholds: tuple[tuple[float, float], ...] = (
        (20.0, 15.0),
        (25.0, 20.0),
        (30.0, 22.0),
        (35.0, 25.0),
    ),
) -> list[dict[str, float]]:
    """ADX-threshold grid for the volume-weighted trend sweep.

    Parameters
    ----------
    thresholds:
        Sequence of ``(adx_strong, adx_medium)`` pairs. Each pair must satisfy
        ``0 < adx_medium <= adx_strong`` (enforced by :class:`VWTrendConfig`). The
        default gives 4 trials.

    Returns
    -------
    list[dict[str, float]]
        One configuration dict per threshold pair.
    """
    return [
        {"adx_strong": float(strong), "adx_medium": float(medium)}
        for strong, medium in thresholds
    ]


def evaluate_vw_trend(
    ohlcv: pd.DataFrame,
    *,
    symbol: str = "SIM",
    base_config: VWTrendConfig | None = None,
    signal_name: str = "classical-vw-trend",
) -> SignalEvaluation:
    """Run the volume-weighted trend rule through the deflated-Sharpe gate.

    Convenience wrapper that builds the panel, weight rule and grid and calls the
    real :func:`~core_trading.research.signal_evaluation.evaluate_signal`.

    Parameters
    ----------
    ohlcv:
        OHLCV frame to evaluate.
    symbol:
        Symbol label.
    base_config:
        Fixed VW-trend configuration; the grid sweeps the ADX thresholds.
    signal_name:
        Label for the result and memo.

    Returns
    -------
    SignalEvaluation
        Verdict, deflated-Sharpe result, and memo.
    """
    panel = ohlcv_panel(ohlcv, symbol=symbol)
    weight_fn = build_vw_trend_weight_fn(symbol=symbol, base_config=base_config)
    grid = vw_trend_grid()
    return evaluate_signal(panel, weight_fn, grid, signal_name=signal_name)
