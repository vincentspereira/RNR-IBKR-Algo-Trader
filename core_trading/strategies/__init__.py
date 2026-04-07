"""Trading strategies module."""

from .base import BaseStrategy, StrategyConfig, Signal, SignalType

__version__ = "1.0.0"
__status__ = "Production"

__all__ = [
    "BaseStrategy",
    "StrategyConfig",
    "Signal",
    "SignalType",
]
