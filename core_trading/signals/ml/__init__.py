"""Machine-learning signal family (master plan Phase 5.D).

The 5.D family ships the supervised / reinforcement learning signals. It begins
with the labeling foundation -- the path-dependent triple-barrier labels of
Lopez de Prado (2018) -- on which the downstream models (tree ensembles,
meta-labelling, etc.) are trained:

* :mod:`~core_trading.signals.ml.labeling` -- triple-barrier method, CUSUM event
  sampling, volatility-scaled barriers, and meta-labelling targets.

Model-fitting modules (5.D.1 trees, 5.D.2 random forest with purged CV, 5.D.5
meta-labelling) build on these labels and land in later batches; they replace the
99%-commented `ai_enhanced_signal_engine.py` and 77%-commented
`reinforcement_learning.py` legacy shells.
"""
from __future__ import annotations

from core_trading.signals.ml.labeling import (
    add_vertical_barrier,
    cusum_filter,
    daily_volatility,
    get_bins,
    triple_barrier_events,
)

__all__ = [
    "daily_volatility",
    "cusum_filter",
    "add_vertical_barrier",
    "triple_barrier_events",
    "get_bins",
]
