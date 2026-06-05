"""Phase-5-style evaluation adapter: classical volatility breakout (gate wiring).

Wires :mod:`core_trading.strategies.classical.volatility_breakout` through the
evaluation gate (:mod:`core_trading.research.signal_evaluation`) to close the
Definition-of-Done loop for any *new* strategy: a backtest run, a deflated Sharpe
score, and a PROMOTE / ARCHIVE verdict.

Unlike the single-close adapters (trend / OU), the breakout rule needs the full
``high / low / close / volume`` panel -- its squeeze filter, volume-surge
confirmation and optional ATR bands read those columns. So this adapter:

* provides :func:`ohlcv_panel` to wrap a real OHLCV frame in the engine's
  ``(symbol, timestamp)`` panel (open = close, frictionless mode agreement); and
* builds a weight rule that reads the OHLCV columns straight back out of the panel
  and applies :func:`~core_trading.strategies.classical.volatility_breakout.breakout_weights`.

"Compute once, sweep cheap" pattern
-----------------------------------
The breakout signal is genuinely cheap (rolling stats + a single forward scan), so
the swept knobs (``squeeze_q``, ``vol_k``) recompute the signal per trial -- there
is no expensive pre-computation to cache, but the grid is still small (3-6 trials)
so the deflated-Sharpe discount stays meaningful.

References: see the strategy module and
:mod:`core_trading.research.signal_evaluation`.
"""
from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd

from core_trading.research.signal_evaluation import (
    SignalEvaluation,
    WeightRule,
    evaluate_signal,
    positions_to_weights,
)
from core_trading.strategies.classical.volatility_breakout import (
    BreakoutConfig,
    breakout_signal,
)

__all__ = [
    "ohlcv_panel",
    "build_breakout_weight_fn",
    "breakout_grid",
    "evaluate_breakout",
]


def ohlcv_panel(
    ohlcv: pd.DataFrame,
    *,
    symbol: str = "SIM",
) -> pd.DataFrame:
    """Wrap a real OHLCV frame in the engine's ``(symbol, timestamp)`` panel.

    Open is set equal to close so the vectorised and event-driven engine modes
    agree exactly under a frictionless cost model, while high / low / volume are
    preserved (the breakout rule needs them).

    Parameters
    ----------
    ohlcv:
        Frame with ``high``, ``low``, ``close``, ``volume`` columns. If the index
        is not a ``DatetimeIndex`` a business-day calendar is synthesised.
    symbol:
        Symbol label for the single instrument.

    Returns
    -------
    pd.DataFrame
        OHLCV panel indexed by ``["symbol", "timestamp"]``.

    Raises
    ------
    ValueError
        If fewer than two rows, a column is missing, or any close/high/low is not
        finite and strictly positive.
    """
    required = ("high", "low", "close", "volume")
    missing = [c for c in required if c not in ohlcv.columns]
    if missing:
        raise ValueError(f"ohlcv missing required columns: {missing}")
    if ohlcv.shape[0] < 2:
        raise ValueError("ohlcv_panel needs at least 2 rows")

    close = np.asarray(ohlcv["close"].to_numpy(), dtype=float)
    high = np.asarray(ohlcv["high"].to_numpy(), dtype=float)
    low = np.asarray(ohlcv["low"].to_numpy(), dtype=float)
    volume = np.asarray(ohlcv["volume"].to_numpy(), dtype=float)
    for name, arr in (("close", close), ("high", high), ("low", low)):
        if not np.all(np.isfinite(arr)) or np.any(arr <= 0.0):
            raise ValueError(f"{name} must be finite and strictly positive")

    if isinstance(ohlcv.index, pd.DatetimeIndex):
        timestamps = ohlcv.index
    else:
        timestamps = pd.date_range("2000-01-03", periods=close.size, freq="B", tz="UTC")

    return pd.DataFrame(
        {
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=pd.MultiIndex.from_product(
            [[symbol], timestamps], names=["symbol", "timestamp"]
        ),
    )


def build_breakout_weight_fn(
    *,
    symbol: str = "SIM",
    base_config: BreakoutConfig | None = None,
) -> WeightRule:
    """Build a :data:`WeightRule` for the volatility-breakout rule.

    The returned rule reads ``high / low / close / volume`` back out of the engine
    panel and applies :func:`breakout_signal` with the swept ``squeeze_q`` /
    ``vol_k`` overlaid on ``base_config``. Each configuration may supply
    ``"squeeze_q"`` and/or ``"vol_k"``; absent keys fall back to ``base_config``.

    Parameters
    ----------
    symbol:
        Symbol label matching :func:`ohlcv_panel`.
    base_config:
        Fixed configuration; the swept keys override its ``squeeze_q`` / ``vol_k``.

    Returns
    -------
    WeightRule
        A ``(panel, params) -> weights`` callable.
    """
    base = base_config or BreakoutConfig()

    def weight_rule(panel: pd.DataFrame, params: Mapping[str, float]) -> pd.DataFrame:
        frame = panel.xs(symbol, level="symbol")
        cfg = BreakoutConfig(
            band_window=base.band_window,
            band_k=base.band_k,
            squeeze_window=base.squeeze_window,
            squeeze_q=float(params.get("squeeze_q", base.squeeze_q)),
            vol_window=base.vol_window,
            vol_k=float(params.get("vol_k", base.vol_k)),
            use_atr=base.use_atr,
        )
        positions = breakout_signal(frame, cfg)
        return positions_to_weights(positions, symbol=symbol)

    return weight_rule


def breakout_grid(
    *,
    squeeze_qs: tuple[float, ...] = (0.2, 0.35, 0.5),
    vol_ks: tuple[float, ...] = (1.2, 1.5),
) -> list[dict[str, float]]:
    """Parameter grid for the volatility-breakout sweep.

    Parameters
    ----------
    squeeze_qs:
        Squeeze quantiles to evaluate (stricter -> fewer, higher-quality setups).
    vol_ks:
        Volume-surge multiples to evaluate.

    Returns
    -------
    list[dict[str, float]]
        One configuration dict per ``(squeeze_q, vol_k)`` pair. The default gives
        6 trials -- enough for a meaningful deflated-Sharpe discount.
    """
    return [
        {"squeeze_q": float(q), "vol_k": float(k)}
        for q in squeeze_qs
        for k in vol_ks
    ]


def evaluate_breakout(
    ohlcv: pd.DataFrame,
    *,
    symbol: str = "SIM",
    base_config: BreakoutConfig | None = None,
    signal_name: str = "classical-volatility-breakout",
) -> SignalEvaluation:
    """Run the volatility-breakout rule through the deflated-Sharpe gate.

    Convenience wrapper that builds the panel, weight rule and grid and calls the
    real :func:`~core_trading.research.signal_evaluation.evaluate_signal`.

    Parameters
    ----------
    ohlcv:
        OHLCV frame to evaluate.
    symbol:
        Symbol label.
    base_config:
        Fixed breakout configuration; the grid sweeps ``squeeze_q`` / ``vol_k``.
    signal_name:
        Label for the result and memo.

    Returns
    -------
    SignalEvaluation
        Verdict, deflated-Sharpe result, and memo.
    """
    panel = ohlcv_panel(ohlcv, symbol=symbol)
    weight_fn = build_breakout_weight_fn(symbol=symbol, base_config=base_config)
    grid = breakout_grid()
    return evaluate_signal(panel, weight_fn, grid, signal_name=signal_name)
