"""Stochastic process signal modules (master plan Phase 5.B.1).

Re-exports the public API of the Ornstein-Uhlenbeck module so that callers
can import directly from ``core_trading.signals.stochastic``.

Example::

    from core_trading.signals.stochastic import OUParams, simulate, fit_ou_mle

See :mod:`core_trading.signals.stochastic.ou` for full documentation.
"""
from __future__ import annotations

from core_trading.signals.stochastic.ou import (
    OUParams,
    fit_ou_mle,
    fit_ou_ols,
    simulate,
)

__all__ = [
    "OUParams",
    "simulate",
    "fit_ou_ols",
    "fit_ou_mle",
]
