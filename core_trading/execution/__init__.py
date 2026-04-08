"""Execution algorithms package for the IBKR Algo Trader.

Provides TWAP and VWAP execution algorithms for institutional-grade
order slicing and time/volume-weighted execution strategies.
"""

from .algo_orders import (
    AlgoConfig,
    AlgoOrder,
    AlgoOrderResult,
    SliceResult,
    TWAPExecutor,
    VWAPExecutor,
    VolumeProfile,
)

__all__ = [
    "AlgoConfig",
    "AlgoOrder",
    "AlgoOrderResult",
    "SliceResult",
    "TWAPExecutor",
    "VWAPExecutor",
    "VolumeProfile",
]
