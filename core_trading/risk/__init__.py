"""Risk-management layer (master plan Phase 4.6 / Phase 7).

Phase 4 ships the pairs risk manager: pre-trade limit checks, real-time spread
divergence alerts, and daily VaR / drawdown circuit breakers.

Phase 7 builds out the full risk stack:

- ``var``  -- portfolio VaR (parametric / historical / Monte Carlo) with
  Kupiec and Christoffersen backtests (7.3).
- ``cvar`` -- CVaR / Expected Shortfall (historical / parametric normal+t /
  Monte Carlo), Rockafellar-Uryasev linearization, Acerbi-Szekely backtest
  (7.4).
- ``vol_forecast`` -- GARCH/GJR-GARCH multi-step vol forecasts with EWMA
  fallback and CCC forward covariance for Phase 6 / VaR consumption (7.6).
- ``correlation_regime`` -- rolling correlations, spectral market mode,
  absorption ratio, Marchenko-Pastur noise floor, regime-shift alerts (7.9).
"""
from core_trading.risk.correlation_regime import (
    AbsorptionShiftResult,
    CorrelationAlert,
    RollingCorrelationResult,
    SpectralResult,
    absorption_shift,
    detect_regime_alerts,
    frobenius_distance,
    market_mode_rotation,
    rolling_correlation,
    spectral_analysis,
)
from core_trading.risk.cvar import (
    AcerbiSzekelyResult,
    ESConfig,
    ESResult,
    PortfolioESResult,
    RUPieces,
    acerbi_szekely_test,
    historical_es,
    monte_carlo_es,
    parametric_es,
    portfolio_es,
    ru_linearization,
)
from core_trading.risk.pairs_risk import (
    DEFAULT_LIMITS,
    DivergenceAlert,
    PairsRiskManager,
    RiskCheck,
    RiskLimits,
)
from core_trading.risk.var import (
    BacktestResult,
    VaRConfig,
    VaRResult,
    christoffersen_test,
    historical_var,
    kupiec_test,
    monte_carlo_var,
    parametric_var,
)
from core_trading.risk.vol_forecast import (
    AssetVolForecast,
    CCCCovResult,
    VolForecastConfig,
    VolForecastResult,
    ewma_variance,
    forecast_cov_matrix,
    forecast_panel_vols,
)

__all__ = [
    # Phase 4 pairs risk
    "RiskLimits",
    "RiskCheck",
    "DivergenceAlert",
    "PairsRiskManager",
    "DEFAULT_LIMITS",
    # 7.3 VaR
    "VaRConfig",
    "VaRResult",
    "BacktestResult",
    "parametric_var",
    "historical_var",
    "monte_carlo_var",
    "kupiec_test",
    "christoffersen_test",
    # 7.4 CVaR / Expected Shortfall
    "ESConfig",
    "ESResult",
    "PortfolioESResult",
    "RUPieces",
    "AcerbiSzekelyResult",
    "historical_es",
    "parametric_es",
    "monte_carlo_es",
    "portfolio_es",
    "ru_linearization",
    "acerbi_szekely_test",
    # 7.6 vol forecasting
    "VolForecastConfig",
    "AssetVolForecast",
    "VolForecastResult",
    "CCCCovResult",
    "ewma_variance",
    "forecast_panel_vols",
    "forecast_cov_matrix",
    # 7.9 correlation regime
    "RollingCorrelationResult",
    "SpectralResult",
    "AbsorptionShiftResult",
    "CorrelationAlert",
    "rolling_correlation",
    "spectral_analysis",
    "absorption_shift",
    "frobenius_distance",
    "market_mode_rotation",
    "detect_regime_alerts",
]
