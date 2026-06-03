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
* :mod:`~core_trading.signals.ml.sample_weights` -- uniqueness / return-
  attribution / time-decay weights that correct for overlapping (non-IID) labels
  before training (AFML ch. 4).
* :mod:`~core_trading.signals.ml.cross_validation` -- purged, embargoed K-fold
  cross-validation for honest out-of-sample evaluation under overlapping labels
  (AFML ch. 7).
* :mod:`~core_trading.signals.ml.feature_importance` -- MDI / MDA / SFI feature
  importance, telling which features actually drive a trained model (AFML ch. 8).

Remaining 5.D model-fitting modules (5.D.1 tree-ensemble signals, 5.D.3 neural
nets) land in later batches; they replace the 99%-commented
`ai_enhanced_signal_engine.py` and 77%-commented `reinforcement_learning.py`
legacy shells.
"""
from __future__ import annotations

from core_trading.signals.ml.cross_validation import (
    PurgedKFold,
    purged_cv_score,
    purged_train_times,
)
from core_trading.signals.ml.feature_importance import (
    mda_feature_importance,
    mdi_feature_importance,
    single_feature_importance,
)
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
from core_trading.signals.ml.sample_weights import (
    average_uniqueness,
    num_concurrent_events,
    return_attribution_weights,
    time_decay_weights,
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
    "num_concurrent_events",
    "average_uniqueness",
    "return_attribution_weights",
    "time_decay_weights",
    "purged_train_times",
    "PurgedKFold",
    "purged_cv_score",
    "mdi_feature_importance",
    "mda_feature_importance",
    "single_feature_importance",
]
