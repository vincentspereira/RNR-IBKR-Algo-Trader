"""Cross-sectional factor signals (master plan Phase 5.C).

The factor family operates on MULTI-ASSET PANELS (an ascending ``DatetimeIndex``
of rows by asset-symbol columns) rather than the single series used by the
time-series and stochastic families. Phase 5.C ships the price/return-based
factors first:

* :mod:`~core_trading.signals.factors.momentum` -- cross-sectional momentum
  (5.C.4): formation-window returns, volatility-scaling, cross-sectional
  z-scoring, and dollar-neutral long/short portfolio construction.
* :mod:`~core_trading.signals.factors.pca_factors` -- PCA statistical factor
  extraction (5.C.3): eigenportfolios, factor returns, and idiosyncratic
  residual returns (Avellaneda-Lee).

Fundamental-data factors (Fama-French SMB/HML/RMW/CMA, Barra industry/style,
Quality/Value -- 5.C.1 / 5.C.2 / 5.C.5) are deferred until point-in-time
fundamental data is available; they cannot be constructed from price/return
panels alone.
"""
from __future__ import annotations

from core_trading.signals.factors.momentum import (
    MomentumConfig,
    cross_sectional_zscore,
    long_short_weights,
    momentum_portfolio,
    momentum_scores,
    risk_adjusted_momentum,
)
from core_trading.signals.factors.pca_factors import (
    PCAFactorResult,
    fit_pca_factors,
    reconstruct,
    residual_returns,
)

__all__ = [
    # momentum (5.C.4)
    "MomentumConfig",
    "momentum_scores",
    "risk_adjusted_momentum",
    "cross_sectional_zscore",
    "long_short_weights",
    "momentum_portfolio",
    # PCA factors (5.C.3)
    "PCAFactorResult",
    "fit_pca_factors",
    "residual_returns",
    "reconstruct",
]
