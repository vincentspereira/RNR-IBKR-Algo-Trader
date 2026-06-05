"""Classical technical-analysis strategies, rewritten from legacy references.

This package holds the Tier-1 "classical" representatives selected by the
master-plan C.2 triage ("rewrite 5-8 representatives, archive rest"). Each module
distils a single, well-known technical rule into a *pure, vectorised,
look-ahead-free* signal function plus a target-weight wrapper, in the same shape
as :mod:`core_trading.strategies.pairs_trading` and the Phase 5 signal adapters.

Modules
-------
volatility_breakout:
    Crabel-class Bollinger-band breakout, gated by a volatility squeeze and a
    volume surge, exiting on a return to the middle band.
volume_weighted_trend:
    Volume-weighted EMA crossover confirmed by a volume-weighted MACD and
    filtered by a Wilder ADX trend-strength gate.

Conventions
-----------
Every signal function returns a :class:`pandas.Series` in ``{-1, 0, +1}`` (or a
weight series) whose value at bar ``t`` uses information only through bar ``t``.
The Phase 3 backtest engine applies that decision to bar ``t+1``'s return, so the
strategies are leakage-free by construction (and that property is unit-tested via
truncation-invariance).
"""
from __future__ import annotations

from core_trading.strategies.classical.volatility_breakout import (
    BreakoutConfig,
    breakout_signal,
    breakout_weights,
)
from core_trading.strategies.classical.volume_weighted_trend import (
    VWTrendConfig,
    vw_trend_signal,
    vw_trend_weights,
)

__all__ = [
    "BreakoutConfig",
    "breakout_signal",
    "breakout_weights",
    "VWTrendConfig",
    "vw_trend_signal",
    "vw_trend_weights",
]
