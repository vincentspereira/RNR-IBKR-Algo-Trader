"""Time-series signal stack (master plan Phase 5.A.4).

* :mod:`core_trading.signals.timeseries.arima` -- ARIMA/SARIMA short-term
  forecasting via the state-space SARIMAX framework; fractional differencing
  (FFD and expanding-window) for memory-preserving stationarity.
"""
from core_trading.signals.timeseries.arima import (
    ArimaConfig,
    ArimaResult,
    FracDiffResult,
    fit_arima,
    frac_diff,
    frac_diff_ffd,
    min_frac_diff,
)

__all__ = [
    "ArimaConfig",
    "ArimaResult",
    "FracDiffResult",
    "fit_arima",
    "frac_diff_ffd",
    "frac_diff",
    "min_frac_diff",
]
