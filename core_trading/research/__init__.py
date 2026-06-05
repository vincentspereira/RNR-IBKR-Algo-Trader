"""Research framework (master plan Phase 2 + Phase 0.5 reproducibility).

Provides the leakage-resistant research toolkit:

* :mod:`core_trading.research.reproducibility` -- global seeding, MLflow runs
* :mod:`core_trading.research.feature_store` -- versioned, look-ahead-free features
* :mod:`core_trading.research.stat_tests` -- stationarity, cointegration,
  long-memory, mean-reversion, normality, structural-break tests
* :mod:`core_trading.research.cross_validation` -- purged k-fold, CPCV,
  walk-forward
* :mod:`core_trading.research.overfitting` -- Deflated Sharpe, PBO, reality
  checks, out-of-sample lockbox
* :mod:`core_trading.research.robustness_report` -- Phase 10.2 automated
  per-strategy robustness battery (bootstrap Sharpe CI, DSR, PBO, White RC,
  Hansen SPA, CPCV OOS distribution) with PROMOTE/REJECT verdict + ASCII
  report + ``--demo`` CLI; the Phase 10 strategy-promotion gate
* :mod:`core_trading.research.signal_decay` -- Phase 13.1+13.4 signal decay
  monitoring (rolling/expanding Sharpe, HEALTHY/WARN/RETIRE verdicts) and
  retraining cadence registry (RetrainPolicy, due_for_retrain) with ASCII
  report + ``--demo`` CLI
"""

from core_trading.research.cross_validation import (
    CombinatorialPurgedCV,
    CVSplit,
    PurgedKFold,
    WalkForwardSplit,
    make_label_end_times,
)
from core_trading.research.feature_store import Feature, FeatureStore, default_feature_store
from core_trading.research.overfitting import (
    BootstrapTestResult,
    DeflatedSharpeResult,
    LockboxAlreadyOpenedError,
    OutOfSampleLockbox,
    PBOResult,
    deflated_sharpe_ratio,
    hansens_spa_test,
    probabilistic_sharpe_ratio,
    probability_of_backtest_overfitting,
    sharpe_ratio,
    whites_reality_check,
)
from core_trading.research.reproducibility import (
    DEFAULT_SEED,
    ExperimentConfig,
    mlflow_run,
    set_seeds,
)
from core_trading.research.robustness_report import (
    BootstrapCIResult,
    CPCVDistribution,
    GateResult,
    RobustnessConfig,
    RobustnessReport,
    render_robustness_report,
    run_robustness_report,
    stationary_bootstrap_sharpe_ci,
)
from core_trading.research.signal_decay import (
    DEFAULT_RETRAIN_POLICIES,
    DecayConfig,
    DecayReport,
    RetrainPolicy,
    RollingSharpeSeries,
    SignalVerdict,
    assess_signal,
    build_decay_report,
    compute_rolling_metrics,
    due_for_retrain,
    render_decay_report,
)
from core_trading.research.stat_tests import (
    HalfLifeResult,
    HurstResult,
    JohansenResult,
    StatTestResult,
    adf_test,
    adjust_pvalues,
    arch_lm_test,
    chow_test,
    cusum_stability_test,
    engle_granger_test,
    half_life,
    hurst_exponent,
    jarque_bera_test,
    johansen_test,
    kpss_test,
    ljung_box_test,
    phillips_perron_test,
    variance_ratio_test,
)

__all__ = [
    # reproducibility
    "DEFAULT_SEED",
    "ExperimentConfig",
    "mlflow_run",
    "set_seeds",
    # feature store
    "Feature",
    "FeatureStore",
    "default_feature_store",
    # stat tests
    "StatTestResult",
    "HurstResult",
    "HalfLifeResult",
    "JohansenResult",
    "adf_test",
    "kpss_test",
    "phillips_perron_test",
    "engle_granger_test",
    "johansen_test",
    "hurst_exponent",
    "half_life",
    "variance_ratio_test",
    "ljung_box_test",
    "jarque_bera_test",
    "arch_lm_test",
    "chow_test",
    "cusum_stability_test",
    "adjust_pvalues",
    # cross-validation
    "CVSplit",
    "make_label_end_times",
    "PurgedKFold",
    "CombinatorialPurgedCV",
    "WalkForwardSplit",
    # overfitting
    "DeflatedSharpeResult",
    "PBOResult",
    "BootstrapTestResult",
    "sharpe_ratio",
    "probabilistic_sharpe_ratio",
    "deflated_sharpe_ratio",
    "probability_of_backtest_overfitting",
    "whites_reality_check",
    "hansens_spa_test",
    "OutOfSampleLockbox",
    "LockboxAlreadyOpenedError",
    # robustness report (Phase 10.2)
    "RobustnessConfig",
    "RobustnessReport",
    "GateResult",
    "BootstrapCIResult",
    "CPCVDistribution",
    "run_robustness_report",
    "render_robustness_report",
    "stationary_bootstrap_sharpe_ci",
    # signal decay (Phase 13.1 + 13.4)
    "DecayConfig",
    "SignalVerdict",
    "RollingSharpeSeries",
    "DecayReport",
    "RetrainPolicy",
    "DEFAULT_RETRAIN_POLICIES",
    "due_for_retrain",
    "compute_rolling_metrics",
    "assess_signal",
    "build_decay_report",
    "render_decay_report",
]
