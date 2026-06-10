"""Example custom strategy for the strategy lab.

The contract: define ``build()`` returning ``(name, factory)`` where
``factory()`` yields an object implementing the engine Strategy protocol --
``generate_weights(prices) -> DataFrame`` taking the engine's
``(symbol, timestamp)`` MultiIndex OHLCV panel and returning a
``(timestamp x symbol)`` target-weight frame (NaN-free; sum of absolute
weights is your gross exposure).

Two ways to author a strategy:

1. EASY -- compose existing TA primaries and quant overlays (this file):
   pick a primary, tune its config, stack overlays. You inherit vectorised
   execution, the cost model, and every robustness gate for free.

2. FULL CONTROL -- write your own class with ``generate_weights`` from
   scratch (see ``core_trading/strategies/ta_quant/strategy.py`` for the
   panel-unpacking idiom). Keep it look-ahead-free: only data at or before
   bar t may influence the weight at bar t. The CPCV/walk-forward harness
   will catch egregious leaks, but the first line of defence is you.

Try it:
    .venv/Scripts/python.exe tools/strategy_lab.py chart    --custom examples/custom_strategy_example.py
    .venv/Scripts/python.exe tools/strategy_lab.py backtest --custom examples/custom_strategy_example.py --universe etf
"""
from __future__ import annotations

from core_trading.strategies.ta_quant import TAQuantConfig, TAQuantStrategy
from core_trading.strategies.ta_quant.primaries import RSIDipConfig
from core_trading.strategies.ta_quant.strategy import OverlaySpec


def build():
    """A milder RSI dip-buyer: RSI(4) < 25, calm-vol gate, 8% vol target."""
    config = TAQuantConfig(
        primary="rsi_dip",
        primary_config=RSIDipConfig(
            rsi_window=4,
            lower_thresh=25.0,
            upper_thresh=75.0,
            exit_thresh=55.0,
            trend_window=150,
            allow_short=False,
        ),
        overlay_specs=(
            OverlaySpec("vol_regime", {"vol_window": 20, "percentile_threshold": 75.0,
                                       "trade_in_calm": True}),
            OverlaySpec("vol_target", {"target_vol": 0.08, "vol_window": 60,
                                       "max_leverage": 1.5}),
        ),
        gross_cap=1.0,
    )
    return "rsi4t25_calm75_volt8_example", lambda: TAQuantStrategy(config)
