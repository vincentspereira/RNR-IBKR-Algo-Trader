"""Operations layer (master plan Phase 4.9 / Phase 12).

Phase 4 ships the pairs paper-trading harness: a day-by-day driver that wraps the
pilot strategy with pre-trade risk gating, a kill switch, daily monitoring
snapshots, and the paper-to-live promotion gate. It is the operational seam where
the IBKR paper account plugs in; over historical data it runs as a risk-gated
walk-forward so the monitoring and promotion logic can be tested before any live
capital is involved.

Phase 10.3 adds the live-vs-backtest divergence comparator: daily residuals
between live PnL and a shadow backtest on the same data, with a z-score alert
when the latest residual exceeds the configured threshold of trailing residual
volatility.
"""
from core_trading.ops.divergence import (
    DEFAULT_DIVERGENCE_CONFIG,
    DivergenceConfig,
    DivergenceVerdict,
    divergence_alert,
    divergence_series,
    render_divergence,
)
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
    # live-vs-backtest divergence (Phase 10.3)
    "DivergenceConfig",
    "DivergenceVerdict",
    "divergence_series",
    "divergence_alert",
    "render_divergence",
    "DEFAULT_DIVERGENCE_CONFIG",
]
