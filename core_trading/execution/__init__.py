"""Execution algorithms package for the IBKR Algo Trader.

Provides TWAP and VWAP execution algorithms for institutional-grade
order slicing and time/volume-weighted execution strategies, plus the Phase 4
pairs execution module (atomic both-legs-or-none fills with TWAP slicing and
implementation-shortfall tracking).
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
from .pairs_execution import (
    DeterministicFillModel,
    ExecutionConfig,
    FillModel,
    Leg,
    LegFill,
    PairExecutionResult,
    PairExecutor,
    PairOrder,
    twap_schedule,
)

__all__ = [
    "AlgoConfig",
    "AlgoOrder",
    "AlgoOrderResult",
    "SliceResult",
    "TWAPExecutor",
    "VWAPExecutor",
    "VolumeProfile",
    # pairs execution (Phase 4.7)
    "Leg",
    "PairOrder",
    "LegFill",
    "PairExecutionResult",
    "FillModel",
    "DeterministicFillModel",
    "ExecutionConfig",
    "twap_schedule",
    "PairExecutor",
]
