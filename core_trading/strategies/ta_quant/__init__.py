"""core_trading.strategies.ta_quant -- TA x quant mix-and-match strategy factory.

Exports the public surface of the four sub-modules:

* :mod:`.primaries` -- six look-ahead-free TA primary position rules.
* :mod:`.overlays` -- three composable quantitative overlay transforms.
* :mod:`.strategy` -- :class:`TAQuantStrategy` implementing the engine
  ``Strategy`` protocol.
* :mod:`.grid` -- :func:`build_ta_quant_grid` trial bank for the robustness
  sweep.
"""
from __future__ import annotations

from core_trading.strategies.ta_quant.grid import build_ta_quant_grid
from core_trading.strategies.ta_quant.overlays import (
    TrendRegimeGate,
    VolRegimeGate,
    VolTargetScaler,
)
from core_trading.strategies.ta_quant.primaries import (
    BollingerFadeConfig,
    DonchianBreakoutConfig,
    KeltnerSqueezeConfig,
    MACDTrendConfig,
    MACrossConfig,
    RSIDipConfig,
    bollinger_fade,
    donchian_breakout,
    keltner_squeeze,
    ma_cross,
    macd_trend,
    rsi_dip,
)
from core_trading.strategies.ta_quant.strategy import (
    OverlaySpec,
    TAQuantConfig,
    TAQuantStrategy,
)

__all__ = [
    # primaries
    "DonchianBreakoutConfig",
    "donchian_breakout",
    "MACrossConfig",
    "ma_cross",
    "RSIDipConfig",
    "rsi_dip",
    "MACDTrendConfig",
    "macd_trend",
    "BollingerFadeConfig",
    "bollinger_fade",
    "KeltnerSqueezeConfig",
    "keltner_squeeze",
    # overlays
    "VolRegimeGate",
    "TrendRegimeGate",
    "VolTargetScaler",
    # strategy
    "OverlaySpec",
    "TAQuantConfig",
    "TAQuantStrategy",
    # grid
    "build_ta_quant_grid",
]
