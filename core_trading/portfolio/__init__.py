"""Portfolio-construction layer (master plan Phase 4.5 / Phase 6).

Phase 4 ships the pairs portfolio constructor (inverse-variance allocation,
gross-leverage cap, sector-exposure limit, market-beta neutralisation).
"""
from core_trading.portfolio.pairs_portfolio import (
    PairAllocation,
    PortfolioConfig,
    PortfolioWeights,
    construct_pairs_portfolio,
    inverse_variance_weights,
)

__all__ = [
    "PairAllocation",
    "PortfolioConfig",
    "PortfolioWeights",
    "inverse_variance_weights",
    "construct_pairs_portfolio",
]
