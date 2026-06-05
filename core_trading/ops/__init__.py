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

Phase 11.4 adds performance attribution: factor, strategy, trade, and cost
attribution lenses delivered as a pure generator with an ASCII renderer and
a seeded --demo CLI.

Phase 12.5 adds daily broker-vs-internal reconciliation: position, fill, and
cash reconciliation sections with configurable tolerances, incident strings,
and an ASCII renderer.  Phase 12.6 adds wash-sale tracking.
"""
from core_trading.ops.reconciliation import (
    BuyEvent,
    CashReconciliationResult,
    FillMatchRecord,
    FillReconciliationResult,
    PositionRecord,
    PositionReconciliationResult,
    ReconciliationConfig,
    ReconciliationReport,
    ReconciliationStatus,
    SaleEvent,
    WashSaleFlag,
    WashSaleReport,
    build_reconciliation_report,
    flag_wash_sales,
    reconcile_cash,
    reconcile_fills,
    reconcile_positions,
    render_reconciliation_report,
)
from core_trading.ops.attribution import (
    AttributionConfig,
    CostAttributionResult,
    CostBreakdown,
    FactorAttributionResult,
    StrategyAttributionResult,
    SymbolPnL,
    TradeAttributionResult,
    cost_attribution,
    factor_attribution,
    render_attribution_report,
    strategy_attribution,
    trade_attribution,
)
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
    # performance attribution (Phase 11.4)
    "AttributionConfig",
    "FactorAttributionResult",
    "StrategyAttributionResult",
    "SymbolPnL",
    "TradeAttributionResult",
    "CostBreakdown",
    "CostAttributionResult",
    "factor_attribution",
    "strategy_attribution",
    "trade_attribution",
    "cost_attribution",
    "render_attribution_report",
    # reconciliation (Phase 12.5 / 12.6)
    "ReconciliationConfig",
    "PositionRecord",
    "PositionReconciliationResult",
    "reconcile_positions",
    "FillMatchRecord",
    "FillReconciliationResult",
    "reconcile_fills",
    "CashReconciliationResult",
    "reconcile_cash",
    "ReconciliationStatus",
    "ReconciliationReport",
    "build_reconciliation_report",
    "SaleEvent",
    "BuyEvent",
    "WashSaleFlag",
    "WashSaleReport",
    "flag_wash_sales",
    "render_reconciliation_report",
]
