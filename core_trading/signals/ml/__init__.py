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
* :mod:`~core_trading.signals.ml.trees` -- the tree-ensemble directional signal:
  a random forest trained on the direction labels whose out-of-fold probabilities
  become bet-sized positions (the bridge from model to tradeable signal).
* :mod:`~core_trading.signals.ml.random_forest` -- the bagging/OOB ensemble
  (5.D.2): out-of-bag scoring as a free generalisation estimate, plus
  ``compare_oob_vs_purged_cv`` exposing the OOB optimism gap under overlapping
  labels (AFML ch. 6 / ch. 7).
* :mod:`~core_trading.signals.ml.neural` -- the LSTM directional net (5.D.3):
  a sequence model over rolling feature windows whose up-probabilities become
  bet-sized positions; deterministic CPU training (``torch`` is lazy-imported).
  Replaces the 99%-commented ``ai_enhanced_signal_engine.py`` legacy shell.
* :mod:`~core_trading.signals.ml.rl` -- the reinforcement-learning subpackage
  (5.D.4): a gymnasium trading environment with a differential-Sharpe-ratio
  reward (Moody-Saffell 1998) and a reproducible stable-baselines3 PPO/DQN
  agent wrapper. Kept as a subpackage (not re-exported here) because importing
  it pulls in ``gymnasium`` at module load; use
  ``from core_trading.signals.ml.rl import TradingEnv, RLTradingAgent``.
  Replaces the 77%-commented ``reinforcement_learning.py`` legacy shell.
"""
from __future__ import annotations

from core_trading.signals.ml.cross_validation import (
    PurgedKFold,
    purged_cv_predict,
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
from core_trading.signals.ml.neural import (
    LSTMConfig,
    LSTMSignal,
)
from core_trading.signals.ml.random_forest import (
    BaggingForestConfig,
    RandomForestOOB,
)
from core_trading.signals.ml.sample_weights import (
    average_uniqueness,
    num_concurrent_events,
    return_attribution_weights,
    time_decay_weights,
)
from core_trading.signals.ml.trees import (
    RandomForestSignal,
    TreeSignalConfig,
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
    "purged_cv_predict",
    "mdi_feature_importance",
    "mda_feature_importance",
    "single_feature_importance",
    "TreeSignalConfig",
    "RandomForestSignal",
    "BaggingForestConfig",
    "RandomForestOOB",
    "LSTMConfig",
    "LSTMSignal",
]
