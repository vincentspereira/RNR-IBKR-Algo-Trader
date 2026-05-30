"""Operations layer (master plan Phase 4.9 / Phase 12).

Phase 4 ships the pairs paper-trading harness: a day-by-day driver that wraps the
pilot strategy with pre-trade risk gating, a kill switch, daily monitoring
snapshots, and the paper-to-live promotion gate. It is the operational seam where
the IBKR paper account plugs in; over historical data it runs as a risk-gated
walk-forward so the monitoring and promotion logic can be tested before any live
capital is involved.
"""
from core_trading.ops.pairs_paper_trading import (
    DailySnapshot,
    PairsPaperTrader,
    PaperConfig,
    PromotionDecision,
)

__all__ = [
    "PaperConfig",
    "DailySnapshot",
    "PromotionDecision",
    "PairsPaperTrader",
]
