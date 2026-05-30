"""Risk-management layer (master plan Phase 4.6 / Phase 7).

Phase 4 ships the pairs risk manager: pre-trade limit checks, real-time spread
divergence alerts, and daily VaR / drawdown circuit breakers.
"""
from core_trading.risk.pairs_risk import (
    DEFAULT_LIMITS,
    DivergenceAlert,
    PairsRiskManager,
    RiskCheck,
    RiskLimits,
)

__all__ = [
    "RiskLimits",
    "RiskCheck",
    "DivergenceAlert",
    "PairsRiskManager",
    "DEFAULT_LIMITS",
]
