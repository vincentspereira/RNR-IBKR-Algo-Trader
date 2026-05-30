"""Hidden Markov Model regime detection (master plan Phase 5.A.1).

Provides Gaussian HMM-based market regime classification with stable
state labelling, look-ahead-free feature construction, and both
full-sample smoothing and walk-forward inference modes.

Public API
----------
* :class:`RegimeConfig` -- frozen configuration dataclass.
* :class:`RegimeResult` -- frozen result dataclass (posteriors, Viterbi path).
* :class:`RegimeDetector` -- main detector: fit / predict / fit_predict.
* :data:`LABEL_BEAR`, :data:`LABEL_BULL`, :data:`LABEL_SIDEWAYS`,
  :data:`LABEL_CRISIS` -- state-index constants after stable relabelling.
"""
from core_trading.signals.regimes.hmm import (
    LABEL_BEAR,
    LABEL_BULL,
    LABEL_CRISIS,
    LABEL_SIDEWAYS,
    RegimeConfig,
    RegimeDetector,
    RegimeResult,
)

__all__ = [
    "RegimeConfig",
    "RegimeResult",
    "RegimeDetector",
    "LABEL_BEAR",
    "LABEL_BULL",
    "LABEL_SIDEWAYS",
    "LABEL_CRISIS",
]
