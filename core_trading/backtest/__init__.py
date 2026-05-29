"""Backtest engine v2 (master plan Phase 3).

A hybrid vectorised + event-driven backtester with realistic execution
(slippage, Almgren-Chriss market impact, partial fills), a per-broker cost-model
registry, Monte Carlo and walk-forward analysis, CPCV distribution-of-Sharpe, and
a standardised :class:`BacktestReport`.

Public surface:

* orders -- :class:`Order`, :class:`Fill`, :class:`Trade` and their enums
* costs -- :class:`CostModel` and components; broker registry
* execution -- :class:`ExecutionSimulator`, :class:`Bar`
* portfolio -- :class:`Portfolio`, :class:`Position`
* metrics -- :func:`compute_metrics`, :class:`PerformanceMetrics`
* engine -- :class:`BacktestEngine`, :class:`BacktestConfig`, :class:`BacktestResult`
* montecarlo -- :func:`monte_carlo_analysis`
* walkforward -- :func:`walk_forward`, :func:`cpcv_sharpe_distribution`
* report -- :class:`BacktestReport`
"""
from core_trading.backtest.costs import (
    AlmgrenChrissImpact,
    BorrowModel,
    CommissionSchedule,
    CostBreakdown,
    CostModel,
    LotMethod,
    RegulatoryFees,
    SpreadVolumeSlippage,
    TaxLotBook,
    available_cost_models,
    get_cost_model,
    register_cost_model,
)
from core_trading.backtest.engine import (
    BacktestConfig,
    BacktestEngine,
    BacktestResult,
    Strategy,
    WeightStrategy,
)
from core_trading.backtest.execution import (
    Bar,
    ExecutionConfig,
    ExecutionResult,
    ExecutionSimulator,
)
from core_trading.backtest.metrics import PerformanceMetrics, compute_metrics
from core_trading.backtest.montecarlo import (
    MonteCarloResult,
    block_bootstrap_paths,
    monte_carlo_analysis,
)
from core_trading.backtest.orders import (
    Fill,
    Order,
    OrderStatus,
    OrderType,
    Side,
    TimeInForce,
    Trade,
)
from core_trading.backtest.portfolio import Portfolio, Position
from core_trading.backtest.report import BacktestReport
from core_trading.backtest.walkforward import (
    WalkForwardResult,
    cpcv_sharpe_distribution,
    walk_forward,
)

__all__ = [
    # orders
    "Order",
    "Fill",
    "Trade",
    "Side",
    "OrderType",
    "OrderStatus",
    "TimeInForce",
    # costs
    "CostModel",
    "CommissionSchedule",
    "RegulatoryFees",
    "SpreadVolumeSlippage",
    "AlmgrenChrissImpact",
    "BorrowModel",
    "CostBreakdown",
    "TaxLotBook",
    "LotMethod",
    "get_cost_model",
    "register_cost_model",
    "available_cost_models",
    # execution
    "ExecutionSimulator",
    "ExecutionConfig",
    "ExecutionResult",
    "Bar",
    # portfolio
    "Portfolio",
    "Position",
    # metrics
    "compute_metrics",
    "PerformanceMetrics",
    # engine
    "BacktestEngine",
    "BacktestConfig",
    "BacktestResult",
    "Strategy",
    "WeightStrategy",
    # montecarlo
    "monte_carlo_analysis",
    "block_bootstrap_paths",
    "MonteCarloResult",
    # walkforward
    "walk_forward",
    "cpcv_sharpe_distribution",
    "WalkForwardResult",
    # report
    "BacktestReport",
]
