"""Portfolio-construction layer (master plan Phase 4.5 / Phase 6).

Phase 4 ships the pairs portfolio constructor (inverse-variance allocation,
gross-leverage cap, sector-exposure limit, market-beta neutralisation).

Phase 6 builds the general portfolio-construction stack on top:

* :mod:`core_trading.portfolio.covariance` -- robust covariance estimators
  (Ledoit-Wolf / OAS / constant-correlation shrinkage, PCA factor-model
  covariance, nearest-PSD projection) consumed by every Phase 6 optimiser.
* :mod:`core_trading.portfolio.mvo` -- constrained Markowitz (6.1): utility /
  target-return / minimum-variance modes under long-only, gross-leverage,
  per-asset, sector and turnover constraints; Bayes-Stein robust means.
* :mod:`core_trading.portfolio.risk_parity` -- equal risk contribution and
  risk budgeting (6.4) via cyclical coordinate descent, with volatility
  targeting.
* :mod:`core_trading.portfolio.hrp` -- de Prado Hierarchical Risk Parity
  (6.3): correlation-distance clustering, quasi-diagonalisation, recursive
  bisection; no matrix inversion anywhere.
* :mod:`core_trading.portfolio.black_litterman` -- equilibrium prior +
  views posterior (6.2) with Omega confidence control of signal injection.
* :mod:`core_trading.portfolio.robust_opt` -- Michaud resampled efficiency,
  Rockafellar-Uryasev / Zhu-Fukushima (worst-case) CVaR, and DRO
  mean-variance under ellipsoidal mean ambiguity (6.5).
* :mod:`core_trading.portfolio.strategy_allocator` -- capital across
  strategies (6.6): equal / risk parity / Bayesian-Sharpe weighting, the
  live-Sharpe decommission rule, and the asset-book netting glue to the
  Phase 4 pairs vertical.
* :mod:`core_trading.portfolio.rebalance` -- calendar / threshold / hybrid
  triggers with a proportional turnover budget (6.7).
* :mod:`core_trading.portfolio.comparison` -- the Phase 6 DOD cross-method
  comparison (equal / min-var / MVO / HRP / risk parity, OOS split).
"""
from core_trading.portfolio.black_litterman import (
    BlackLittermanResult,
    black_litterman,
    implied_equilibrium_returns,
)
from core_trading.portfolio.comparison import (
    MethodComparison,
    compare_methods,
    comparison_report,
)
from core_trading.portfolio.covariance import (
    CovarianceResult,
    condition_number,
    constant_correlation_covariance,
    factor_model_covariance,
    ledoit_wolf_covariance,
    nearest_psd,
    oas_covariance,
    sample_covariance,
)
from core_trading.portfolio.hrp import (
    HRPConfig,
    HRPResult,
    correlation_distance,
    hrp_weights,
)
from core_trading.portfolio.mvo import (
    MVOConfig,
    MVOResult,
    RobustMeanResult,
    bayes_stein_means,
    mean_variance_weights,
    min_variance_weights,
)
from core_trading.portfolio.pairs_portfolio import (
    PairAllocation,
    PortfolioConfig,
    PortfolioWeights,
    construct_pairs_portfolio,
    inverse_variance_weights,
)
from core_trading.portfolio.rebalance import (
    RebalanceConfig,
    RebalanceDecision,
    drift_weights,
    rebalance_decision,
)
from core_trading.portfolio.risk_parity import (
    RiskParityConfig,
    RiskParityResult,
    risk_contributions,
    risk_parity_weights,
)
from core_trading.portfolio.robust_opt import (
    CVaRConfig,
    CVaRResult,
    MichaudResult,
    cvar_weights,
    empirical_cvar,
    michaud_weights,
    robust_mean_variance_weights,
    worst_case_cvar_weights,
)
from core_trading.portfolio.strategy_allocator import (
    StrategyAllocation,
    StrategyAllocatorConfig,
    allocate_strategies,
    combine_strategy_weights,
)

__all__ = [
    # pairs portfolio (Phase 4.5)
    "PairAllocation",
    "PortfolioConfig",
    "PortfolioWeights",
    "inverse_variance_weights",
    "construct_pairs_portfolio",
    # covariance estimators (Phase 6, Batch 1)
    "CovarianceResult",
    "sample_covariance",
    "ledoit_wolf_covariance",
    "oas_covariance",
    "constant_correlation_covariance",
    "factor_model_covariance",
    "nearest_psd",
    "condition_number",
    # constrained Markowitz (Phase 6.1)
    "MVOConfig",
    "MVOResult",
    "RobustMeanResult",
    "bayes_stein_means",
    "mean_variance_weights",
    "min_variance_weights",
    # risk parity (Phase 6.4)
    "RiskParityConfig",
    "RiskParityResult",
    "risk_contributions",
    "risk_parity_weights",
    # hierarchical risk parity (Phase 6.3)
    "HRPConfig",
    "HRPResult",
    "correlation_distance",
    "hrp_weights",
    # Black-Litterman (Phase 6.2)
    "BlackLittermanResult",
    "black_litterman",
    "implied_equilibrium_returns",
    # robust optimisation (Phase 6.5)
    "CVaRConfig",
    "CVaRResult",
    "MichaudResult",
    "cvar_weights",
    "empirical_cvar",
    "michaud_weights",
    "robust_mean_variance_weights",
    "worst_case_cvar_weights",
    # strategy allocation (Phase 6.6)
    "StrategyAllocation",
    "StrategyAllocatorConfig",
    "allocate_strategies",
    "combine_strategy_weights",
    # rebalancing (Phase 6.7)
    "RebalanceConfig",
    "RebalanceDecision",
    "drift_weights",
    "rebalance_decision",
    # cross-method comparison (Phase 6 DOD)
    "MethodComparison",
    "compare_methods",
    "comparison_report",
]
