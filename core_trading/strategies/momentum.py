"""Momentum strategy module - re-exports from momentum subpackage."""

from .momentum.macd_crossover_strategy import MACDCrossoverStrategy
from .momentum.supertrend_strategy import SupertrendStrategy
from .momentum.adx_trend_following_strategy import ADXTrendFollowingStrategy
from .momentum.roc_momentum_strategy import ROCMomentumStrategy
from .momentum.ichimoku_cloud_strategy import IchimokuCloudStrategy
from .momentum.parabolic_sar_strategy import ParabolicSARStrategy
from .momentum.turtle_trading_strategy import TurtleTradingStrategy
from .momentum.obv_trend_strategy import OBVTrendStrategy
from .momentum.vortex_indicator_strategy import VortexIndicatorStrategy
from .momentum.dual_momentum_strategy import DualMomentumStrategy
from .momentum.augmented_ma_crossover import AugmentedMACrossover

__all__ = [
    "MACDCrossoverStrategy",
    "SupertrendStrategy",
    "ADXTrendFollowingStrategy",
    "ROCMomentumStrategy",
    "IchimokuCloudStrategy",
    "ParabolicSARStrategy",
    "TurtleTradingStrategy",
    "OBVTrendStrategy",
    "VortexIndicatorStrategy",
    "DualMomentumStrategy",
    "AugmentedMACrossover",
]
