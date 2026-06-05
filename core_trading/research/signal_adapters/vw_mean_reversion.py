"""Phase-5-style evaluation adapter: classical VW mean-reversion (gate wiring).

Wires :mod:`core_trading.strategies.classical.vw_mean_reversion` through the
evaluation gate (:mod:`core_trading.research.signal_evaluation`) to close the
Definition-of-Done loop: backtest run, deflated-Sharpe score, PROMOTE / ARCHIVE
verdict.

Like the other OHLCV adapters (breakout, VW-trend), this strategy reads
``close`` and ``volume`` from the engine panel, so it reuses
:func:`~core_trading.research.signal_adapters.classical_breakout.ohlcv_panel`
to build the ``(symbol, timestamp)`` multi-index frame. High and low are
preserved in the panel (even though this strategy ignores them) so the panel
format is compatible with cross-adapter tests and the OHLCV panel validator.

Swept knobs
-----------
The cheap swept parameters are the entry and exit z-score thresholds
(``entry_z`` / ``exit_z``) -- how demanding the mean-reversion trigger is. The
VWMA and z-score window lengths are held fixed at their classical defaults
(20 / 20) to keep the grid small (< 10 trials) and the deflated-Sharpe
discount meaningful.
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
from core_trading.strategies.classical.vw_mean_reversion import (
    VWMeanReversionConfig,
    vw_mean_reversion_signal,
)

__all__ = [
    "build_vw_mr_weight_fn",
    "vw_mr_grid",
    "evaluate_vw_mr",
]


def build_vw_mr_weight_fn(
    *,
    symbol: str = "SIM",
    base_config: VWMeanReversionConfig | None = None,
) -> WeightRule:
    """Build a :data:`WeightRule` for the VW mean-reversion rule.

    The returned rule reads ``close`` and ``volume`` back out of the engine
    panel and applies :func:`vw_mean_reversion_signal` with the swept
    ``entry_z`` and ``exit_z`` overlaid on ``base_config``. Each configuration
    may supply ``"entry_z"`` and/or ``"exit_z"``; absent keys fall back to
    ``base_config``.

    The ``exit_z`` from the grid is clamped to ``[0, entry_z)`` before being
    passed to the config constructor to guarantee ``VWMeanReversionConfig``
    validation does not reject borderline grid values.

    Parameters
    ----------
    symbol:
        Symbol label matching :func:`~.classical_breakout.ohlcv_panel`.
    base_config:
        Fixed configuration; the swept keys override its ``entry_z`` /
        ``exit_z``.

    Returns
    -------
    WeightRule
        A ``(panel, params) -> weights`` callable.
    """
    base = base_config or VWMeanReversionConfig()

    def weight_rule(panel: pd.DataFrame, params: Mapping[str, float]) -> pd.DataFrame:
        frame = panel.xs(symbol, level="symbol")
        entry_z = float(params.get("entry_z", base.entry_z))
        # Clamp exit_z to [0, entry_z) so the config validator is always happy.
        raw_exit_z = float(params.get("exit_z", base.exit_z))
        exit_z = min(raw_exit_z, entry_z * 0.99)
        exit_z = max(exit_z, 0.0)
        cfg = VWMeanReversionConfig(
            vwma_window=base.vwma_window,
            zscore_window=base.zscore_window,
            entry_z=entry_z,
            exit_z=exit_z,
            vol_window=base.vol_window,
            vol_k=base.vol_k,
        )
        positions = vw_mean_reversion_signal(frame, cfg)
        return positions_to_weights(positions, symbol=symbol)

    return weight_rule


def vw_mr_grid(
    *,
    entry_zs: tuple[float, ...] = (1.5, 2.0, 2.5),
    exit_zs: tuple[float, ...] = (0.25, 0.5),
) -> list[dict[str, float]]:
    """Parameter grid for the VW mean-reversion sweep.

    Parameters
    ----------
    entry_zs:
        Entry z-score thresholds to evaluate (smaller = more trades, wider
        nets; larger = fewer, higher-conviction trades).
    exit_zs:
        Exit z-score thresholds to evaluate (smaller = tighter exit, more
        reversion captured; larger = quicker exit before full reversion). Each
        value must be strictly less than the corresponding ``entry_z``; the
        weight rule clamps automatically, so no cross-product is invalid.

    Returns
    -------
    list[dict[str, float]]
        One configuration dict per ``(entry_z, exit_z)`` pair. The default
        gives 6 trials -- enough for a meaningful deflated-Sharpe discount.
    """
    return [
        {"entry_z": float(ez), "exit_z": float(xz)}
        for ez in entry_zs
        for xz in exit_zs
    ]


def evaluate_vw_mr(
    ohlcv: pd.DataFrame,
    *,
    symbol: str = "SIM",
    base_config: VWMeanReversionConfig | None = None,
    signal_name: str = "classical-vw-mean-reversion",
) -> SignalEvaluation:
    """Run the VW mean-reversion rule through the deflated-Sharpe gate.

    Convenience wrapper that builds the panel, weight rule and grid and calls
    the real :func:`~core_trading.research.signal_evaluation.evaluate_signal`.

    Parameters
    ----------
    ohlcv:
        OHLCV frame to evaluate. Must have ``high``, ``low``, ``close``,
        ``volume`` columns (the panel builder requires high/low even though
        this signal only reads close/volume).
    symbol:
        Symbol label.
    base_config:
        Fixed VW mean-reversion configuration; the grid sweeps ``entry_z`` /
        ``exit_z``.
    signal_name:
        Label for the result and memo.

    Returns
    -------
    SignalEvaluation
        Verdict, deflated-Sharpe result, and memo.
    """
    panel = ohlcv_panel(ohlcv, symbol=symbol)
    weight_fn = build_vw_mr_weight_fn(symbol=symbol, base_config=base_config)
    grid = vw_mr_grid()
    return evaluate_signal(panel, weight_fn, grid, signal_name=signal_name)
