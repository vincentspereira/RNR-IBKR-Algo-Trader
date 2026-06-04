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

The fundamental-data factors consume, in addition to the price panel, a tidy
point-in-time fundamentals panel in the
:meth:`~core_trading.data.fundamentals.FundamentalSource.records_to_dataframe`
shape (one row per disclosed fact, carrying both ``period_end`` and
``filing_date``). A value enters the cross-section at date ``t`` only once its
``filing_date <= t``, so the factors are leakage-free; the free SEC EDGAR adapter
(:mod:`core_trading.data.sources.edgar_source`) supplies that panel:

* :mod:`~core_trading.signals.factors.fama_french` -- Fama-French SMB/HML/RMW/CMA
  (+ UMD momentum) factor returns from 2x3 sorts (5.C.1).
* :mod:`~core_trading.signals.factors.barra` -- Barra-style cross-sectional risk
  model: style + industry exposures, factor returns, idiosyncratic residuals
  (5.C.2).
* :mod:`~core_trading.signals.factors.style_factors` -- Quality / Value /
  Low-volatility style premia (5.C.5); the low-vol leg is price-only.
"""
from __future__ import annotations

from core_trading.signals.factors.barra import (
    BarraConfig,
    BarraResult,
    build_industry_exposures,
    build_style_exposures,
    fit_barra,
    idiosyncratic_returns,
)
from core_trading.signals.factors.fama_french import (
    FamaFrenchConfig,
    build_characteristic_panel,
    compute_book_to_market,
    compute_cma,
    compute_fama_french_factors,
    compute_market_equity,
    compute_rmw,
    compute_umd,
    factor_returns_from_portfolios,
    form_ff_portfolios,
    pit_latest_value,
)
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
from core_trading.signals.factors.style_factors import (
    StyleFactorConfig,
    lowvol_scores,
    pit_characteristic,
    quality_scores,
    style_factor_panels,
    style_factor_weights,
    value_scores,
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
    # Fama-French factor returns (5.C.1)
    "FamaFrenchConfig",
    "pit_latest_value",
    "build_characteristic_panel",
    "compute_market_equity",
    "compute_book_to_market",
    "compute_rmw",
    "compute_cma",
    "form_ff_portfolios",
    "factor_returns_from_portfolios",
    "compute_umd",
    "compute_fama_french_factors",
    # Barra cross-sectional risk model (5.C.2)
    "BarraConfig",
    "BarraResult",
    "build_style_exposures",
    "build_industry_exposures",
    "fit_barra",
    "idiosyncratic_returns",
    # Quality / Value / Low-vol style premia (5.C.5)
    "StyleFactorConfig",
    "pit_characteristic",
    "value_scores",
    "quality_scores",
    "lowvol_scores",
    "style_factor_weights",
    "style_factor_panels",
]
