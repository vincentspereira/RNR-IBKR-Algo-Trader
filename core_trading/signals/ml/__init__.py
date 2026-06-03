"""Machine-learning signal family (master plan Phase 5.D).

The 5.D family ships the supervised / reinforcement learning signals. It begins
with the labeling foundation -- the path-dependent triple-barrier labels of
Lopez de Prado (2018) -- on which the downstream models (tree ensembles,
meta-labelling, etc.) are trained:

* :mod:`~core_trading.signals.ml.labeling` -- triple-barrier method, CUSUM event
  sampling, volatility-scaled barriers, and meta-labelling targets.
* :mod:`~core_trading.signals.ml.meta_labelling` -- the secondary classifier that
  decides whether to act on, and how large to size, a primary signal (the
  *model* layer trained on the labeling targets, AFML ch. 3 / ch. 10).

Remaining 5.D model-fitting modules (5.D.1 trees, 5.D.2 random forest with purged
CV, AFML ch. 7 leakage-aware evaluation) land in later batches; they replace the
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
from core_trading.signals.ml.meta_labelling import (
    MetaLabelConfig,
    MetaLabeler,
    bet_size_from_prob,
)

__all__ = [
    "daily_volatility",
    "cusum_filter",
    "add_vertical_barrier",
    "triple_barrier_events",
    "get_bins",
    "MetaLabelConfig",
    "MetaLabeler",
    "bet_size_from_prob",
]
