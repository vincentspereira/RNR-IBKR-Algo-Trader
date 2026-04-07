"""Momentum Strategies Module."""

from .macd_crossover_strategy import (
    MACDCrossoverStrategy,
    MACDSignal,
    MACDResult,
    MACDConfig,
)
from .supertrend_strategy import (
    SupertrendStrategy,
    SupertrendSignal,
    SupertrendResult,
    SupertrendConfig,
)
from .adx_trend_following_strategy import (
    ADXTrendFollowingStrategy,
    ADXSignal,
    ADXResult,
    ADXConfig,
)
from .roc_momentum_strategy import (
    ROCMomentumStrategy,
    ROCSignal,
    ROCResult,
    ROCConfig,
)
from .ichimoku_cloud_strategy import (
    IchimokuCloudStrategy,
    IchimokuSignal,
    IchimokuResult,
    IchimokuConfig,
)
from .parabolic_sar_strategy import (
    ParabolicSARStrategy,
    SARSignal,
    SARResult,
    SARConfig,
)
from .turtle_trading_strategy import (
    TurtleTradingStrategy,
    TurtleSignal,
    TurtleResult,
    TurtleConfig,
)
from .obv_trend_strategy import (
    OBVTrendStrategy,
    OBVSignal,
    OBVResult,
    OBVConfig,
)
from .vortex_indicator_strategy import (
    VortexIndicatorStrategy,
    VortexSignal,
    VortexResult,
    VortexConfig,
)
from .dual_momentum_strategy import (
    DualMomentumStrategy,
    DualMomentumSignal,
    DualMomentumResult,
    DualMomentumConfig,
)
from .augmented_ma_crossover import (
    AugmentedMACrossoverStrategy,
    AugMACrossSignal,
    AugMACrossResult,
    AugMACrossConfig,
)
from .augmented_momentum_strategy import (
    AugmentedMomentumStrategy,
    AugMomentumSignal,
    AugMomentumConfig,
    AugMomentumResult,
)
from .coppock_curve_strategy import (
    CoppockCurveStrategy,
    CoppockSignal,
    CoppockConfig,
    CoppockResult,
)

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
    "AugmentedMACrossoverStrategy",
    "AugmentedMomentumStrategy",
    "CoppockCurveStrategy",
]
