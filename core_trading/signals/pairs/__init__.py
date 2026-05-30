"""Pairs-trading signal stack (master plan Phase 4.1-4.3).

* :mod:`core_trading.signals.pairs.selection` -- pair selection (distance,
  cointegration, Johansen, copula) with multiple-testing correction.
* :mod:`core_trading.signals.pairs.spread` -- static (OLS) and dynamic (Kalman)
  hedge ratios; Ornstein-Uhlenbeck spread modelling; z-scores.
* :mod:`core_trading.signals.pairs.signals` -- z-score entry/exit/stop/time-stop
  signal state machine.
"""
from core_trading.signals.pairs.selection import (
    PairCandidate,
    distance_score,
    select_pairs_cointegration,
    select_pairs_copula,
    select_pairs_distance,
    select_pairs_johansen,
)
from core_trading.signals.pairs.signals import (
    PairState,
    SignalConfig,
    generate_pair_signals,
    signal_to_weights,
)
from core_trading.signals.pairs.spread import (
    KalmanHedge,
    OUParams,
    StaticHedge,
    compute_spread,
    fit_ou,
    static_hedge_ratio,
    zscore,
)

__all__ = [
    # selection
    "PairCandidate",
    "distance_score",
    "select_pairs_distance",
    "select_pairs_cointegration",
    "select_pairs_johansen",
    "select_pairs_copula",
    # spread
    "StaticHedge",
    "OUParams",
    "KalmanHedge",
    "static_hedge_ratio",
    "compute_spread",
    "fit_ou",
    "zscore",
    # signals
    "PairState",
    "SignalConfig",
    "generate_pair_signals",
    "signal_to_weights",
]
