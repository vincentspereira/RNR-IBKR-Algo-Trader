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
"""
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
from core_trading.portfolio.risk_parity import (
    RiskParityConfig,
    RiskParityResult,
    risk_contributions,
    risk_parity_weights,
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
]
