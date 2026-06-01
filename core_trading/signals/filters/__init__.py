"""Signal filtering modules: Kalman filter and structural time series (Phase 5.A.2-3).

Re-exports the public API of both submodules so that callers can import
directly from ``core_trading.signals.filters``.

Examples::

    from core_trading.signals.filters import KalmanFilter, KalmanResult
    from core_trading.signals.filters import time_varying_beta
    from core_trading.signals.filters import (
        StateSpaceResult,
        fit_local_level,
        fit_local_linear_trend,
        fit_basic_structural,
        fit_unobserved_components,
    )

See :mod:`core_trading.signals.filters.kalman` and
:mod:`core_trading.signals.filters.state_space` for full documentation.
"""
from __future__ import annotations

from core_trading.signals.filters.kalman import (
    KalmanFilter,
    KalmanResult,
    time_varying_beta,
)
from core_trading.signals.filters.state_space import (
    StateSpaceResult,
    fit_basic_structural,
    fit_local_level,
    fit_local_linear_trend,
    fit_unobserved_components,
)

__all__ = [
    # kalman
    "KalmanFilter",
    "KalmanResult",
    "time_varying_beta",
    # state_space
    "StateSpaceResult",
    "fit_local_level",
    "fit_local_linear_trend",
    "fit_basic_structural",
    "fit_unobserved_components",
]
