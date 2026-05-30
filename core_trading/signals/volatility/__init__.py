"""Volatility signal models (master plan Phase 5.A.5).

* :mod:`core_trading.signals.volatility.garch` -- GARCH-family conditional
  volatility estimation (GARCH, EGARCH, GJR-GARCH) and HAR-RV.
"""
from core_trading.signals.volatility.garch import (
    GARCHConfig,
    GARCHResult,
    HARRVConfig,
    HARRVResult,
    fit_garch,
    fit_har_rv,
    forecast_har_rv,
    forecast_variance,
    realised_variance,
)

__all__ = [
    "GARCHConfig",
    "GARCHResult",
    "HARRVConfig",
    "HARRVResult",
    "fit_garch",
    "fit_har_rv",
    "forecast_har_rv",
    "forecast_variance",
    "realised_variance",
]
