"""Money-management layer (master plan Phase 4.4 / Phase 8).

Position sizing: fractional Kelly, volatility targeting, and per-position caps.
"""
from core_trading.money.sizing import (
    PositionSize,
    SizingConfig,
    fractional_kelly,
    scale_to_budget,
    size_position,
    vol_target_weight,
)

__all__ = [
    "SizingConfig",
    "PositionSize",
    "fractional_kelly",
    "vol_target_weight",
    "size_position",
    "scale_to_budget",
]
