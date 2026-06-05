"""Money-management layer (master plan Phase 8).

This package owns *how much* to trade -- position sizing, leverage,
capital allocation across strategies, drawdown-based de-risking, and
turnover / cost budgeting.  Direction and conviction are owned by the
signal layer; portfolio construction by :mod:`core_trading.portfolio`;
risk measurement by :mod:`core_trading.risk`.

Package contents
----------------
:mod:`core_trading.money.sizing` -- position sizing (Phase 8.1)
    Fractional Kelly, volatility targeting, per-position caps, fixed
    fractional, fixed dollar, naive risk-parity sizing, and Ralph
    Vince's Optimal f.  ``size_position`` combines Kelly / vol-target /
    cap by taking the most conservative magnitude.

:mod:`core_trading.money.leverage` -- leverage management (Phase 8.2)
    Gross / net / per-asset-class leverage limits with proportional
    scale-down (``apply_leverage_limits``) and dynamic delevering on
    drawdown or high-vol regimes (``dynamic_delever_factor``).

:mod:`core_trading.money.capital_allocation` -- strategy lifecycle (Phase 8.3)
    Research -> paper -> small live -> scaled live lifecycle with
    machine-readable promotion / scaling / decommission decisions
    (``evaluate_lifecycle``) and the live-capital overlay on the
    Phase 6 multi-strategy allocator (``allocate_live_capital``).

:mod:`core_trading.money.drawdown_management` -- continuous de-risking (Phase 8.4)
    Exposure ladder by drawdown depth, vol-of-vol halving, and
    new-high-water-mark re-leverage hysteresis (``target_exposure``).
    Complements the *discrete* Phase 7 circuit breakers in
    :mod:`core_trading.risk.circuit_breakers`.

:mod:`core_trading.money.turnover` -- turnover and cost budget (Phase 8.5)
    Monthly turnover cap with budget-aware rebalance scaling
    (``check_turnover_budget``), cost-vs-alpha budget enforcement, and
    the edge > 2x cost trade filter.

Conventions
-----------
* Weights are signed fractions of portfolio NAV.
* Drawdowns use the positive-loss convention (0.12 == 12% below the
  high-water mark), matching Phase 7.
* Turnover is one-sided: ``sum(|dw|) / 2`` per period.
"""
from core_trading.money.capital_allocation import (
    DEFAULT_LIFECYCLE_CONFIG,
    LifecycleAction,
    LifecycleConfig,
    LifecycleDecision,
    StrategyRecord,
    StrategyStage,
    allocate_live_capital,
    evaluate_lifecycle,
)
from core_trading.money.drawdown_management import (
    DEFAULT_DRAWDOWN_CONFIG,
    DrawdownConfig,
    compute_drawdown,
    exposure_multiplier,
    releverage_allowed,
    target_exposure,
    vol_of_vol_indicator,
)
from core_trading.money.leverage import (
    LeverageConfig,
    LeverageReport,
    apply_dynamic_delever,
    apply_leverage_limits,
    dynamic_delever_factor,
)
from core_trading.money.sizing import (
    PositionSize,
    SizingConfig,
    fixed_dollar,
    fixed_fractional,
    fractional_kelly,
    optimal_f,
    risk_parity_size,
    scale_to_budget,
    size_position,
    vol_target_weight,
)
from core_trading.money.turnover import (
    TurnoverConfig,
    TurnoverDecision,
    check_turnover_budget,
    cost_budget_ok,
    cost_budget_ratio,
    edge_exceeds_cost,
    filter_trades_by_edge,
    monthly_turnover,
    realised_turnover,
    turnover_headroom,
)

__all__ = [
    # sizing (8.1)
    "SizingConfig",
    "PositionSize",
    "fractional_kelly",
    "vol_target_weight",
    "size_position",
    "scale_to_budget",
    "fixed_fractional",
    "fixed_dollar",
    "risk_parity_size",
    "optimal_f",
    # leverage (8.2)
    "LeverageConfig",
    "LeverageReport",
    "apply_leverage_limits",
    "dynamic_delever_factor",
    "apply_dynamic_delever",
    # capital allocation (8.3)
    "StrategyStage",
    "LifecycleAction",
    "LifecycleConfig",
    "StrategyRecord",
    "LifecycleDecision",
    "evaluate_lifecycle",
    "allocate_live_capital",
    "DEFAULT_LIFECYCLE_CONFIG",
    # drawdown management (8.4)
    "DrawdownConfig",
    "compute_drawdown",
    "exposure_multiplier",
    "vol_of_vol_indicator",
    "releverage_allowed",
    "target_exposure",
    "DEFAULT_DRAWDOWN_CONFIG",
    # turnover (8.5)
    "TurnoverConfig",
    "TurnoverDecision",
    "realised_turnover",
    "monthly_turnover",
    "turnover_headroom",
    "check_turnover_budget",
    "cost_budget_ok",
    "cost_budget_ratio",
    "edge_exceeds_cost",
    "filter_trades_by_edge",
]
