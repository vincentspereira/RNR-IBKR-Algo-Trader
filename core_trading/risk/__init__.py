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
- ``stress`` -- historical / hypothetical / reverse stress testing with a
  built-in scenario library and daily report generator (7.5).
- ``copulas`` -- Gaussian, Student-t, and C/D-vine copulas with tail
  dependence coefficients and PIT utilities (7.7).
- ``position_risk`` -- stop-losses (absolute / ATR / vol), trailing stops,
  component VaR (Euler), BSM option greeks, position snapshots (7.2).
- ``liquidity`` -- days-to-liquidate, BDSS liquidity-adjusted VaR with
  square-root impact add-on, spread-stress reports (7.10).
- ``pretrade`` -- universal six-check pre-trade gate (liquidity,
  concentration, exposure, margin, restricted list, kill switch) with the
  PairOrder execution-layer adapter (7.1).
- ``circuit_breakers`` -- strategy / portfolio / daily-loss drawdown
  breakers as a replayable state machine with audit events (7.8).
- ``daily_report`` -- daily risk report generator (VaR / ES / stress /
  liquidity sections) with CLI entry (DOD).

Note: ``pretrade.DEFAULT_CONFIG`` and ``circuit_breakers.DEFAULT_CONFIG``
are re-exported here as ``DEFAULT_GATE_CONFIG`` / ``DEFAULT_BREAKER_CONFIG``
to avoid the name collision.
"""
from core_trading.risk.circuit_breakers import (
    DEFAULT_CONFIG as DEFAULT_BREAKER_CONFIG,
)
from core_trading.risk.circuit_breakers import (
    BreakerConfig,
    BreakerEvent,
    BreakerState,
    BreakerType,
    CircuitBreakerEngine,
)
from core_trading.risk.copulas import (
    CopulaFitResult,
    CVineCopula,
    DVineCopula,
    GaussianCopula,
    StudentTCopula,
    empirical_pit,
    empirical_pit_inverse,
    tail_dependence_empirical,
    tail_dependence_gaussian,
    tail_dependence_student_t,
)
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
from core_trading.risk.daily_report import (
    DailyRiskConfig,
    DailyRiskReport,
    ESSection,
    LiquiditySection,
    StressSection,
    VaRSection,
    generate_daily_risk_report,
    render_daily_risk_report_markdown,
)
from core_trading.risk.liquidity import (
    AssetLiquidityResult,
    LiquidationSchedule,
    LiquidityConfig,
    LiquidityStressReport,
    LVaRResult,
    PortfolioLiquidityResult,
    days_to_liquidate,
    liquidity_adjusted_var,
    render_liquidity_stress_markdown,
    stress_liquidity,
)
from core_trading.risk.pairs_risk import (
    DEFAULT_LIMITS,
    DivergenceAlert,
    PairsRiskManager,
    RiskCheck,
    RiskLimits,
)
from core_trading.risk.position_risk import (
    ComponentVaRResult,
    GreeksResult,
    PositionGreeksResult,
    PositionRiskSnapshot,
    StopHitResult,
    StopLevel,
    TrailingStopResult,
    absolute_stop,
    atr_stop,
    bsm_greeks,
    build_snapshot,
    check_stop_hit,
    component_var,
    position_greeks,
    trailing_stop,
    volatility_stop,
    wilder_atr,
)
from core_trading.risk.pretrade import (
    DEFAULT_CONFIG as DEFAULT_GATE_CONFIG,
)
from core_trading.risk.pretrade import (
    AssetClass,
    CheckDetail,
    GateConfig,
    PairGateResult,
    PortfolioState,
    PreTradeDecision,
    PreTradeGate,
    ProposedOrder,
    gate_pair_order,
)
from core_trading.risk.stress import (
    HISTORICAL_SCENARIOS,
    FactorShock,
    HistoricalScenario,
    ScenarioResult,
    StressReport,
    apply_scenario,
    build_stress_report,
    hypothetical_shock,
    render_stress_report_markdown,
    reverse_stress_linear,
    reverse_stress_numeric,
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
    # 7.5 stress testing
    "FactorShock",
    "HistoricalScenario",
    "HISTORICAL_SCENARIOS",
    "ScenarioResult",
    "StressReport",
    "apply_scenario",
    "hypothetical_shock",
    "reverse_stress_linear",
    "reverse_stress_numeric",
    "build_stress_report",
    "render_stress_report_markdown",
    # 7.7 copulas
    "CopulaFitResult",
    "GaussianCopula",
    "StudentTCopula",
    "CVineCopula",
    "DVineCopula",
    "empirical_pit",
    "empirical_pit_inverse",
    "tail_dependence_gaussian",
    "tail_dependence_student_t",
    "tail_dependence_empirical",
    # 7.2 position-level risk
    "StopLevel",
    "StopHitResult",
    "TrailingStopResult",
    "ComponentVaRResult",
    "GreeksResult",
    "PositionGreeksResult",
    "PositionRiskSnapshot",
    "absolute_stop",
    "atr_stop",
    "volatility_stop",
    "check_stop_hit",
    "wilder_atr",
    "trailing_stop",
    "component_var",
    "bsm_greeks",
    "position_greeks",
    "build_snapshot",
    # 7.10 liquidity risk
    "LiquidityConfig",
    "LiquidationSchedule",
    "AssetLiquidityResult",
    "PortfolioLiquidityResult",
    "LVaRResult",
    "LiquidityStressReport",
    "days_to_liquidate",
    "liquidity_adjusted_var",
    "stress_liquidity",
    "render_liquidity_stress_markdown",
    # 7.1 pre-trade gate
    "AssetClass",
    "ProposedOrder",
    "PortfolioState",
    "GateConfig",
    "DEFAULT_GATE_CONFIG",
    "CheckDetail",
    "PreTradeDecision",
    "PreTradeGate",
    "PairGateResult",
    "gate_pair_order",
    # 7.8 circuit breakers
    "BreakerState",
    "BreakerType",
    "BreakerEvent",
    "BreakerConfig",
    "DEFAULT_BREAKER_CONFIG",
    "CircuitBreakerEngine",
    # daily risk report (DOD)
    "DailyRiskConfig",
    "VaRSection",
    "ESSection",
    "StressSection",
    "LiquiditySection",
    "DailyRiskReport",
    "generate_daily_risk_report",
    "render_daily_risk_report_markdown",
]
