"""Stochastic process signal modules (master plan Phase 5.B).

Sub-modules
-----------
* :mod:`core_trading.signals.stochastic.ou` -- Ornstein-Uhlenbeck mean-reverting
  process; simulate + OLS / exact-MLE estimators (Phase 5.B.1).
* :mod:`core_trading.signals.stochastic.jump_diffusion` -- Merton jump-diffusion;
  simulate + finite-mixture MLE + model moments (Phase 5.B.2).
* :mod:`core_trading.signals.stochastic.heston` -- Heston stochastic volatility;
  full-truncation Euler simulation, characteristic-function call pricing, and
  calibration (Phase 5.B.3).
* :mod:`core_trading.signals.stochastic.gbm` -- Geometric Brownian Motion
  baseline; simulate + closed-form MLE (Phase 5.B.4).

Shared ``simulate`` name
------------------------
Every process module exposes a ``simulate`` function.  Because the name is
shared, the package-level ``simulate`` re-export is bound to the
Ornstein-Uhlenbeck process for backward compatibility.  For the other
processes, use the submodule form, e.g. ``gbm.simulate(...)`` or
``from core_trading.signals.stochastic.heston import simulate``.

The fitted-parameter DTOs (``OUParams``, ``GBMParams``, ``MertonParams``,
``HestonParams``) and the uniquely-named functions are re-exported here for
convenience.
"""
from __future__ import annotations

from core_trading.signals.stochastic import gbm, heston, jump_diffusion, ou
from core_trading.signals.stochastic.gbm import GBMParams, fit_gbm
from core_trading.signals.stochastic.heston import (
    HestonParams,
    calibrate,
    call_price,
    characteristic_function,
)
from core_trading.signals.stochastic.jump_diffusion import (
    MertonParams,
    fit_merton,
    model_moments,
)
from core_trading.signals.stochastic.ou import (
    OUParams,
    fit_ou_mle,
    fit_ou_ols,
    simulate,
)

__all__ = [
    # Process submodules (use these for the shared ``simulate`` name).
    "ou",
    "gbm",
    "jump_diffusion",
    "heston",
    # Ornstein-Uhlenbeck (5.B.1); ``simulate`` is the OU simulator.
    "OUParams",
    "simulate",
    "fit_ou_ols",
    "fit_ou_mle",
    # Geometric Brownian Motion (5.B.4).
    "GBMParams",
    "fit_gbm",
    # Merton jump-diffusion (5.B.2).
    "MertonParams",
    "fit_merton",
    "model_moments",
    # Heston stochastic volatility (5.B.3).
    "HestonParams",
    "characteristic_function",
    "call_price",
    "calibrate",
]
