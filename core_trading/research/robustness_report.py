"""Automated statistical robustness report (master plan Phase 10.2).

The Phase 10 Definition-of-Done requires that *strategy promotion requires a
fresh statistical robustness report*. This module is the composition + report
layer that closes that gate: it takes a candidate strategy's realised return
series (plus, when available, the full bank of *trial* returns that were searched
during research) and runs the anti-overfitting battery from
:mod:`core_trading.research.overfitting` and the leakage-free cross-validation
splitters from :mod:`core_trading.research.cross_validation`, then emits a single
machine-readable verdict (``PROMOTE`` / ``REJECT`` / ``INSUFFICIENT_DATA``).

It mirrors :mod:`core_trading.risk.daily_report`: a *pure generator* that never
touches the clock, filesystem, or any live feed (the ``generated_at`` timestamp
is injectable and the only data source on the CLI is ``--demo``).

Tests assembled
---------------
* **Bootstrap CI on the annualised Sharpe** -- a stationary-bootstrap percentile
  confidence interval (Politis & Romano 1994). We reuse the package-internal
  :func:`~core_trading.research.overfitting._stationary_bootstrap_indices`: it is
  the exact index generator that White's Reality Check already relies on, so
  resampling the Sharpe with the same routine keeps one canonical bootstrap in
  the codebase rather than forking a second implementation. The dependency is
  documented here and re-exported through the thin public wrapper
  :func:`stationary_bootstrap_sharpe_ci`.
* **Deflated Sharpe Ratio** (Bailey & Lopez de Prado 2014) -- PSR against the
  *expected maximum* Sharpe of the trial set. When no trial returns are supplied
  the trial count and its Sharpe spread are unknown, so DSR is *not evaluated*
  (we never fabricate ``n_trials``); the report falls back to the PSR-vs-zero
  number alone and marks the DSR gate ``not evaluated``.
* **Probability of Backtest Overfitting** via CSCV (Bailey, Borwein, Lopez de
  Prado & Zhu 2017) -- requires the trial matrix; skipped + marked otherwise.
* **White's Reality Check** for data snooping (White 2000) -- requires the trial
  matrix; skipped + marked otherwise.
* **Hansen's SPA** (Hansen 2005) -- optional studentised refinement of the
  Reality Check, computed on the trial matrix when present.
* **CPCV out-of-sample Sharpe distribution** -- the strategy's own return series
  is run through :class:`~core_trading.research.cross_validation.CombinatorialPurgedCV`
  and a per-test-set Sharpe is computed for every combination, summarised by
  mean / std / 5th-percentile / fraction-negative.

Verdict
-------
Every configured gate reports *observed vs limit*. All configured gates must
pass for ``PROMOTE``; any hard failure yields ``REJECT``; fewer than
``min_observations`` returns yields ``INSUFFICIENT_DATA`` (the statistical tests
are not run at all in that case).

CLI entry point
---------------
``python -m core_trading.research.robustness_report --demo``
    Runs a seeded synthetic *skilled* strategy with a trial bank end-to-end and
    prints the full ASCII report.

``python -m core_trading.research.robustness_report --demo --output <path>``
    Same, but also writes the report to the given path.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd

from core_trading.research.cross_validation import CombinatorialPurgedCV
from core_trading.research.overfitting import (
    BootstrapTestResult,
    DeflatedSharpeResult,
    PBOResult,
    _stationary_bootstrap_indices,
    deflated_sharpe_ratio,
    hansens_spa_test,
    probabilistic_sharpe_ratio,
    probability_of_backtest_overfitting,
    sharpe_ratio,
    whites_reality_check,
)

__all__ = [
    "RobustnessConfig",
    "GateResult",
    "BootstrapCIResult",
    "CPCVDistribution",
    "RobustnessReport",
    "Verdict",
    "stationary_bootstrap_sharpe_ci",
    "run_robustness_report",
    "render_robustness_report",
    "main",
]

Verdict = Literal["PROMOTE", "REJECT", "INSUFFICIENT_DATA"]

# Gate status tokens (ASCII, machine-readable).
_PASS = "PASS"
_FAIL = "FAIL"
_NOT_EVALUATED = "NOT_EVALUATED"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RobustnessConfig:
    """Configuration for the statistical robustness report.

    Attributes
    ----------
    bootstrap_iterations:
        Number of stationary-bootstrap resamples for the Sharpe confidence
        interval and for the reality-check / SPA tests. Default 1000.
    block_length:
        Mean block length (in bars) of the stationary bootstrap (Politis &
        Romano 1994). Larger blocks preserve more serial dependence. Default 20.
    confidence_level:
        Two-sided confidence level for the bootstrap Sharpe CI, e.g. 0.95 gives
        a [2.5%, 97.5%] percentile interval. Default 0.95.
    periods_per_year:
        Annualisation factor for the Sharpe ratio (252 trading days). Default 252.
    cpcv_n_groups:
        ``n_groups`` for the Combinatorial Purged CV splitter. Default 6.
    cpcv_n_test_groups:
        ``n_test_groups`` for the CPCV splitter. Default 2.
    cpcv_embargo_pct:
        Embargo fraction for the CPCV splitter. Default 0.01.
    pbo_n_splits:
        Number of (even) CSCV splits for the PBO estimate. Default 16.
    dsr_min:
        Minimum Deflated Sharpe probability for the DSR gate to pass.
        Default 0.95 (Bailey & Lopez de Prado convention).
    pbo_max:
        Maximum Probability of Backtest Overfitting for the PBO gate to pass.
        Default 0.5 (above 0.5 the selection is worse than a coin flip).
    reality_check_p_max:
        Maximum White's Reality Check p-value for the data-snooping gate to
        pass. Default 0.10.
    sharpe_ci_lower_min:
        Minimum acceptable lower bound of the bootstrap Sharpe CI. Default 0.0
        (the CI must exclude a zero annualised Sharpe).
    cpcv_frac_negative_max:
        Maximum fraction of CPCV out-of-sample folds with a negative Sharpe for
        the CPCV stability gate to pass. Default 0.5.
    require_reality_check:
        Whether the Reality-Check gate is a hard requirement when trials are
        present. Default True.
    require_pbo:
        Whether the PBO gate is a hard requirement when trials are present.
        Default True.
    require_dsr:
        Whether the DSR gate is a hard requirement when trials are present.
        Default True.
    min_observations:
        Minimum number of finite returns required to run the battery; below this
        the verdict is ``INSUFFICIENT_DATA``. Default 252 (~one trading year).
    risk_free:
        Per-period risk-free rate used by the Sharpe ratio. Default 0.0.
    """

    bootstrap_iterations: int = 1000
    block_length: float = 20.0
    confidence_level: float = 0.95
    periods_per_year: int = 252
    cpcv_n_groups: int = 6
    cpcv_n_test_groups: int = 2
    cpcv_embargo_pct: float = 0.01
    pbo_n_splits: int = 16
    dsr_min: float = 0.95
    pbo_max: float = 0.5
    reality_check_p_max: float = 0.10
    sharpe_ci_lower_min: float = 0.0
    cpcv_frac_negative_max: float = 0.5
    require_reality_check: bool = True
    require_pbo: bool = True
    require_dsr: bool = True
    min_observations: int = 252
    risk_free: float = 0.0

    def __post_init__(self) -> None:
        if self.bootstrap_iterations < 1:
            raise ValueError("bootstrap_iterations must be >= 1.")
        if self.block_length <= 0.0:
            raise ValueError("block_length must be > 0.")
        if not (0.0 < self.confidence_level < 1.0):
            raise ValueError("confidence_level must be in (0, 1).")
        if self.periods_per_year < 1:
            raise ValueError("periods_per_year must be >= 1.")
        if self.cpcv_n_groups < 3:
            raise ValueError("cpcv_n_groups must be >= 3.")
        if not (1 <= self.cpcv_n_test_groups < self.cpcv_n_groups):
            raise ValueError("cpcv_n_test_groups must be in [1, cpcv_n_groups).")
        if not (0.0 <= self.cpcv_embargo_pct < 1.0):
            raise ValueError("cpcv_embargo_pct must be in [0, 1).")
        if self.pbo_n_splits < 2 or self.pbo_n_splits % 2 != 0:
            raise ValueError("pbo_n_splits must be even and >= 2.")
        if not (0.0 < self.dsr_min < 1.0):
            raise ValueError("dsr_min must be in (0, 1).")
        if not (0.0 < self.pbo_max < 1.0):
            raise ValueError("pbo_max must be in (0, 1).")
        if not (0.0 < self.reality_check_p_max < 1.0):
            raise ValueError("reality_check_p_max must be in (0, 1).")
        if not (0.0 <= self.cpcv_frac_negative_max <= 1.0):
            raise ValueError("cpcv_frac_negative_max must be in [0, 1].")
        if self.min_observations < 2:
            raise ValueError("min_observations must be >= 2.")


# ---------------------------------------------------------------------------
# Result DTOs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GateResult:
    """One pass/fail gate with its observed value, limit, and status.

    Attributes
    ----------
    name:
        Human-readable gate name.
    status:
        One of ``"PASS"``, ``"FAIL"``, ``"NOT_EVALUATED"``.
    observed:
        Observed statistic (``None`` when not evaluated).
    limit:
        The threshold the observed value is compared against.
    comparison:
        ASCII operator describing the pass condition, e.g. ``">="`` or ``"<="``.
    required:
        Whether the gate is a hard requirement for ``PROMOTE``. A failed
        non-required gate is advisory and does not force ``REJECT``.
    reason:
        Machine-readable explanation of the status.
    """

    name: str
    status: str
    observed: float | None
    limit: float
    comparison: str
    required: bool
    reason: str

    @property
    def passed(self) -> bool:
        """True only when the gate's status is exactly ``PASS``."""
        return self.status == _PASS

    @property
    def evaluated(self) -> bool:
        """True when the gate produced a PASS or FAIL (not skipped)."""
        return self.status in (_PASS, _FAIL)


@dataclass(frozen=True, slots=True)
class BootstrapCIResult:
    """Stationary-bootstrap percentile CI on the annualised Sharpe.

    Attributes
    ----------
    point_sharpe:
        Annualised Sharpe of the full sample.
    lower:
        Lower percentile bound of the bootstrap distribution.
    upper:
        Upper percentile bound of the bootstrap distribution.
    confidence_level:
        Two-sided confidence level of the interval.
    n_bootstrap:
        Number of bootstrap resamples.
    block_length:
        Mean block length of the stationary bootstrap.
    """

    point_sharpe: float
    lower: float
    upper: float
    confidence_level: float
    n_bootstrap: int
    block_length: float


@dataclass(frozen=True, slots=True)
class CPCVDistribution:
    """Summary of the CPCV out-of-sample Sharpe distribution.

    Attributes
    ----------
    sharpes:
        Per-test-set annualised Sharpe for every CPCV combination.
    mean:
        Mean of ``sharpes``.
    std:
        Sample standard deviation of ``sharpes``.
    p05:
        5th percentile of ``sharpes``.
    fraction_negative:
        Fraction of folds with a negative Sharpe.
    n_combinations:
        Number of CPCV combinations evaluated.
    """

    sharpes: np.ndarray = field(repr=False)
    mean: float
    std: float
    p05: float
    fraction_negative: float
    n_combinations: int


@dataclass(frozen=True, slots=True)
class RobustnessReport:
    """Assembled statistical robustness report and overall verdict.

    Attributes
    ----------
    verdict:
        ``"PROMOTE"``, ``"REJECT"``, or ``"INSUFFICIENT_DATA"``.
    gates:
        Ordered tuple of :class:`GateResult` -- the machine-readable per-gate
        pass/fail record.
    n_obs:
        Number of finite returns in the strategy series.
    point_sharpe:
        Annualised Sharpe of the strategy series (``None`` when insufficient
        data).
    bootstrap_ci:
        Bootstrap Sharpe CI (``None`` when insufficient data).
    deflated_sharpe:
        DSR result (``None`` when no trials were supplied).
    psr:
        Probabilistic Sharpe vs zero (always computed when data is sufficient).
    pbo:
        PBO result (``None`` when no trials were supplied).
    reality_check:
        White's Reality Check result (``None`` when no trials were supplied).
    spa:
        Hansen's SPA result (``None`` when no trials were supplied).
    cpcv:
        CPCV out-of-sample Sharpe distribution (``None`` when insufficient data).
    n_trials:
        Number of trial strategies considered (``0`` when none supplied).
    generated_at:
        Injected ISO/UTC timestamp string.
    config:
        The :class:`RobustnessConfig` used.
    """

    verdict: Verdict
    gates: tuple[GateResult, ...]
    n_obs: int
    point_sharpe: float | None
    bootstrap_ci: BootstrapCIResult | None
    deflated_sharpe: DeflatedSharpeResult | None
    psr: float | None
    pbo: PBOResult | None
    reality_check: BootstrapTestResult | None
    spa: BootstrapTestResult | None
    cpcv: CPCVDistribution | None
    n_trials: int
    generated_at: str
    config: RobustnessConfig

    @property
    def promoted(self) -> bool:
        """Convenience: True only for a ``PROMOTE`` verdict."""
        return self.verdict == "PROMOTE"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _utcnow_str() -> str:
    ts = pd.Timestamp.utcnow()
    return str(ts.strftime("%Y-%m-%dT%H:%M:%SZ"))


def _clean_returns(strategy_returns: pd.Series) -> np.ndarray:
    """Finite values of the strategy series as a 1-D float array."""
    arr = np.asarray(strategy_returns, dtype=float)
    finite: np.ndarray = arr[np.isfinite(arr)]
    return finite


def stationary_bootstrap_sharpe_ci(
    returns: pd.Series | np.ndarray,
    *,
    n_bootstrap: int = 1000,
    block_length: float = 20.0,
    confidence_level: float = 0.95,
    periods_per_year: int = 252,
    risk_free: float = 0.0,
    seed: int = 0,
) -> BootstrapCIResult:
    """Stationary-bootstrap percentile CI on the annualised Sharpe.

    Thin public wrapper over the package-internal Politis & Romano (1994)
    stationary-bootstrap index generator already used by White's Reality Check,
    so the report keeps a single canonical bootstrap implementation. Each
    resample reorders the returns with the same serial-dependence-preserving
    routine and the annualised Sharpe is recomputed; the two-sided percentile
    interval at ``confidence_level`` is returned.

    Parameters
    ----------
    returns:
        Per-period return series.
    n_bootstrap:
        Number of resamples.
    block_length:
        Mean block length of the stationary bootstrap.
    confidence_level:
        Two-sided confidence level (e.g. 0.95 -> [2.5%, 97.5%]).
    periods_per_year:
        Annualisation factor.
    risk_free:
        Per-period risk-free rate.
    seed:
        RNG seed for reproducibility.

    Returns
    -------
    BootstrapCIResult
    """
    arr = np.asarray(returns, dtype=float)
    arr = arr[np.isfinite(arr)]
    n = arr.size
    if n < 2:
        raise ValueError("stationary_bootstrap_sharpe_ci needs >= 2 returns.")
    point = sharpe_ratio(
        arr, periods_per_year=periods_per_year, risk_free=risk_free, annualised=True
    )
    rng = np.random.default_rng(seed)
    idx = _stationary_bootstrap_indices(n, block_length, n_bootstrap, rng)
    boot = np.empty(n_bootstrap, dtype=float)
    for b in range(n_bootstrap):
        sample = arr[idx[b]]
        sd = sample.std(ddof=1)
        if sd == 0.0:
            boot[b] = 0.0
        else:
            boot[b] = ((sample - risk_free).mean() / sd) * np.sqrt(periods_per_year)
    alpha = 1.0 - confidence_level
    lo, hi = np.percentile(boot, [100.0 * alpha / 2.0, 100.0 * (1.0 - alpha / 2.0)])
    return BootstrapCIResult(
        point_sharpe=float(point),
        lower=float(lo),
        upper=float(hi),
        confidence_level=confidence_level,
        n_bootstrap=n_bootstrap,
        block_length=block_length,
    )


def _cpcv_oos_distribution(
    returns: np.ndarray, config: RobustnessConfig
) -> CPCVDistribution:
    """Per-test-set annualised Sharpe across every CPCV combination."""
    n = returns.size
    event_times = pd.date_range("2000-01-03", periods=n, freq="B")
    cv = CombinatorialPurgedCV(
        n_groups=config.cpcv_n_groups,
        n_test_groups=config.cpcv_n_test_groups,
        embargo_pct=config.cpcv_embargo_pct,
    )
    sharpes: list[float] = []
    for split in cv.split(event_times):
        seg = returns[split.test_indices]
        # A fold with too few points or no meaningful dispersion has an
        # undefined Sharpe. The variance check is relative: an exact-equality
        # test on the std misses a (numerically) constant fold, whose
        # mean-subtraction residual is a tiny non-zero std that would otherwise
        # explode the ratio.
        seg_std = float(seg.std(ddof=1)) if seg.size >= 2 else 0.0
        seg_scale = float(np.abs(seg).mean()) if seg.size else 0.0
        if seg.size < 2 or seg_std <= 1e-12 * max(seg_scale, 1.0):
            sharpes.append(0.0)
            continue
        sharpes.append(
            sharpe_ratio(
                seg,
                periods_per_year=config.periods_per_year,
                risk_free=config.risk_free,
                annualised=True,
            )
        )
    arr = np.asarray(sharpes, dtype=float)
    return CPCVDistribution(
        sharpes=arr,
        mean=float(arr.mean()),
        std=float(arr.std(ddof=1)) if arr.size > 1 else 0.0,
        p05=float(np.percentile(arr, 5.0)),
        fraction_negative=float(np.mean(arr < 0.0)),
        n_combinations=arr.size,
    )


def _gate(
    name: str,
    *,
    observed: float | None,
    limit: float,
    comparison: str,
    required: bool,
    passed: bool | None,
    reason: str,
) -> GateResult:
    """Build a :class:`GateResult`, deriving status from ``passed``."""
    status = _NOT_EVALUATED if passed is None else _PASS if passed else _FAIL
    return GateResult(
        name=name,
        status=status,
        observed=observed,
        limit=limit,
        comparison=comparison,
        required=required,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Public generator
# ---------------------------------------------------------------------------


def run_robustness_report(
    strategy_returns: pd.Series,
    *,
    trial_returns: pd.DataFrame | None = None,
    config: RobustnessConfig | None = None,
    generated_at: str | None = None,
) -> RobustnessReport:
    """Run the full statistical robustness battery and assign a verdict.

    Parameters
    ----------
    strategy_returns:
        The candidate strategy's realised per-period returns (Series).
    trial_returns:
        Optional ``(T, N)`` matrix of the *trial* strategies searched during
        research, the candidate ideally among them as one column. Required for
        DSR, PBO and the reality-check / SPA gates; when ``None`` those gates are
        marked ``NOT_EVALUATED`` and the verdict rests on the data-only gates.
    config:
        :class:`RobustnessConfig`. Defaults to ``RobustnessConfig()``.
    generated_at:
        Optional injected UTC timestamp string; ``None`` stamps the current UTC.

    Returns
    -------
    RobustnessReport
        Fully populated DTO with a machine-readable per-gate record and an
        overall ``PROMOTE`` / ``REJECT`` / ``INSUFFICIENT_DATA`` verdict.

    Notes
    -----
    Implements the Phase 10 DOD that "strategy promotion requires a fresh
    statistical robustness report". The statistical primitives are documented
    in :mod:`core_trading.research.overfitting` (Bailey & Lopez de Prado 2014
    DSR; Bailey et al. 2017 PBO; White 2000 Reality Check; Hansen 2005 SPA) and
    :mod:`core_trading.research.cross_validation` (de Prado CPCV).
    """
    cfg = config if config is not None else RobustnessConfig()
    stamp = generated_at if generated_at is not None else _utcnow_str()

    returns = _clean_returns(strategy_returns)
    n_obs = int(returns.size)

    has_trials = trial_returns is not None and trial_returns.shape[1] >= 2
    n_trials = int(trial_returns.shape[1]) if trial_returns is not None else 0

    # --- INSUFFICIENT_DATA short-circuit ---
    if n_obs < cfg.min_observations:
        reason = (
            f"only {n_obs} finite returns; need >= {cfg.min_observations} "
            "to run the robustness battery"
        )
        data_gate = _gate(
            "Minimum observations",
            observed=float(n_obs),
            limit=float(cfg.min_observations),
            comparison=">=",
            required=True,
            passed=False,
            reason=reason,
        )
        return RobustnessReport(
            verdict="INSUFFICIENT_DATA",
            gates=(data_gate,),
            n_obs=n_obs,
            point_sharpe=None,
            bootstrap_ci=None,
            deflated_sharpe=None,
            psr=None,
            pbo=None,
            reality_check=None,
            spa=None,
            cpcv=None,
            n_trials=n_trials,
            generated_at=stamp,
            config=cfg,
        )

    gates: list[GateResult] = []

    # --- (1) Bootstrap CI on annualised Sharpe ---
    point_sharpe = sharpe_ratio(
        returns,
        periods_per_year=cfg.periods_per_year,
        risk_free=cfg.risk_free,
        annualised=True,
    )
    ci = stationary_bootstrap_sharpe_ci(
        returns,
        n_bootstrap=cfg.bootstrap_iterations,
        block_length=cfg.block_length,
        confidence_level=cfg.confidence_level,
        periods_per_year=cfg.periods_per_year,
        risk_free=cfg.risk_free,
        seed=0,
    )
    ci_passed = ci.lower >= cfg.sharpe_ci_lower_min
    gates.append(
        _gate(
            "Bootstrap Sharpe CI lower bound",
            observed=ci.lower,
            limit=cfg.sharpe_ci_lower_min,
            comparison=">=",
            required=True,
            passed=ci_passed,
            reason=(
                f"{cfg.confidence_level:.0%} CI lower bound {ci.lower:.4f} "
                f"vs minimum {cfg.sharpe_ci_lower_min:.4f}"
            ),
        )
    )

    # --- PSR vs zero (always available when data is sufficient) ---
    from scipy import stats as _scs  # local import: scipy already a dependency

    per_period_sharpe = sharpe_ratio(returns, annualised=False, risk_free=cfg.risk_free)
    skew = float(_scs.skew(returns))
    kurt = float(_scs.kurtosis(returns, fisher=False))
    psr = probabilistic_sharpe_ratio(
        per_period_sharpe, n_obs, benchmark_sharpe=0.0, skew=skew, kurtosis=kurt
    )

    # --- (2) Deflated Sharpe Ratio (needs trials) ---
    dsr_result: DeflatedSharpeResult | None = None
    if has_trials:
        assert trial_returns is not None
        trial_mat = trial_returns.to_numpy(dtype=float)
        col_sd = trial_mat.std(axis=0, ddof=1)
        # Per-period Sharpe of every trial column; zero where a column is flat.
        trial_sharpes = np.divide(
            trial_mat.mean(axis=0),
            col_sd,
            out=np.zeros(trial_mat.shape[1], dtype=float),
            where=col_sd > 0,
        )
        dsr_result = deflated_sharpe_ratio(
            returns, n_trials=n_trials, trial_sharpes=trial_sharpes
        )
        dsr_passed = dsr_result.deflated_sharpe >= cfg.dsr_min
        gates.append(
            _gate(
                "Deflated Sharpe Ratio",
                observed=dsr_result.deflated_sharpe,
                limit=cfg.dsr_min,
                comparison=">=",
                required=cfg.require_dsr,
                passed=dsr_passed,
                reason=(
                    f"DSR {dsr_result.deflated_sharpe:.4f} vs minimum "
                    f"{cfg.dsr_min:.4f} across {n_trials} trials"
                ),
            )
        )
    else:
        gates.append(
            _gate(
                "Deflated Sharpe Ratio",
                observed=None,
                limit=cfg.dsr_min,
                comparison=">=",
                required=cfg.require_dsr,
                passed=None,
                reason=(
                    "no trial returns supplied; DSR not evaluated "
                    f"(PSR-vs-zero = {psr:.4f} reported instead)"
                ),
            )
        )

    # --- (3) Probability of Backtest Overfitting (needs trials) ---
    pbo_result: PBOResult | None = None
    if has_trials:
        assert trial_returns is not None
        pbo_result = probability_of_backtest_overfitting(
            trial_returns.to_numpy(dtype=float), n_splits=cfg.pbo_n_splits
        )
        pbo_passed = pbo_result.pbo <= cfg.pbo_max
        gates.append(
            _gate(
                "Probability of Backtest Overfitting",
                observed=pbo_result.pbo,
                limit=cfg.pbo_max,
                comparison="<=",
                required=cfg.require_pbo,
                passed=pbo_passed,
                reason=(
                    f"PBO {pbo_result.pbo:.4f} vs maximum {cfg.pbo_max:.4f} "
                    f"over {pbo_result.n_combinations} CSCV combinations"
                ),
            )
        )
    else:
        gates.append(
            _gate(
                "Probability of Backtest Overfitting",
                observed=None,
                limit=cfg.pbo_max,
                comparison="<=",
                required=cfg.require_pbo,
                passed=None,
                reason="no trial returns supplied; PBO not evaluated",
            )
        )

    # --- (4) White's Reality Check (needs trials) + optional Hansen SPA ---
    rc_result: BootstrapTestResult | None = None
    spa_result: BootstrapTestResult | None = None
    if has_trials:
        assert trial_returns is not None
        rc_result = whites_reality_check(
            trial_returns.to_numpy(dtype=float),
            benchmark=0.0,
            n_bootstrap=cfg.bootstrap_iterations,
            mean_block=cfg.block_length,
            seed=0,
        )
        spa_result = hansens_spa_test(
            trial_returns.to_numpy(dtype=float),
            benchmark=0.0,
            n_bootstrap=cfg.bootstrap_iterations,
            mean_block=cfg.block_length,
            seed=0,
        )
        rc_passed = rc_result.pvalue <= cfg.reality_check_p_max
        gates.append(
            _gate(
                "White's Reality Check",
                observed=rc_result.pvalue,
                limit=cfg.reality_check_p_max,
                comparison="<=",
                required=cfg.require_reality_check,
                passed=rc_passed,
                reason=(
                    f"Reality-Check p-value {rc_result.pvalue:.4f} vs maximum "
                    f"{cfg.reality_check_p_max:.4f}"
                ),
            )
        )
    else:
        gates.append(
            _gate(
                "White's Reality Check",
                observed=None,
                limit=cfg.reality_check_p_max,
                comparison="<=",
                required=cfg.require_reality_check,
                passed=None,
                reason="no trial returns supplied; Reality Check not evaluated",
            )
        )

    # --- (5) CPCV out-of-sample Sharpe distribution ---
    cpcv = _cpcv_oos_distribution(returns, cfg)
    cpcv_passed = cpcv.fraction_negative <= cfg.cpcv_frac_negative_max
    gates.append(
        _gate(
            "CPCV out-of-sample stability",
            observed=cpcv.fraction_negative,
            limit=cfg.cpcv_frac_negative_max,
            comparison="<=",
            required=True,
            passed=cpcv_passed,
            reason=(
                f"fraction of negative OOS folds {cpcv.fraction_negative:.4f} "
                f"vs maximum {cfg.cpcv_frac_negative_max:.4f} "
                f"(mean OOS Sharpe {cpcv.mean:.4f}, 5th pct {cpcv.p05:.4f})"
            ),
        )
    )

    # --- Verdict ---
    required_gates = [g for g in gates if g.required and g.evaluated]
    if any(not g.passed for g in required_gates):
        verdict: Verdict = "REJECT"
    else:
        verdict = "PROMOTE"

    return RobustnessReport(
        verdict=verdict,
        gates=tuple(gates),
        n_obs=n_obs,
        point_sharpe=float(point_sharpe),
        bootstrap_ci=ci,
        deflated_sharpe=dsr_result,
        psr=float(psr),
        pbo=pbo_result,
        reality_check=rc_result,
        spa=spa_result,
        cpcv=cpcv,
        n_trials=n_trials,
        generated_at=stamp,
        config=cfg,
    )


# ---------------------------------------------------------------------------
# ASCII renderer
# ---------------------------------------------------------------------------


def _fmt_observed(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.4f}"


def render_robustness_report(report: RobustnessReport) -> str:
    """Render a :class:`RobustnessReport` as an ASCII-only string.

    All output is 7-bit ASCII (``ord < 128``), suitable for Windows cp1252
    consoles, ops email bodies, and log files. Mirrors the renderer pattern of
    :func:`core_trading.risk.daily_report.render_daily_risk_report_markdown`.

    Parameters
    ----------
    report:
        The report to render.

    Returns
    -------
    str
        ASCII-only multi-line string.
    """
    lines: list[str] = []
    lines.append("# Statistical Robustness Report")
    lines.append("")
    lines.append(f"Verdict    : {report.verdict}")
    lines.append(f"Generated  : {report.generated_at}")
    lines.append(f"Observations: {report.n_obs}")
    lines.append(f"Trials     : {report.n_trials}")
    lines.append("")

    # Summary statistics
    lines.append("## Summary Statistics")
    lines.append("")
    if report.point_sharpe is not None:
        lines.append(f"Annualised Sharpe : {report.point_sharpe:.4f}")
    if report.bootstrap_ci is not None:
        ci = report.bootstrap_ci
        lines.append(
            f"Bootstrap CI      : [{ci.lower:.4f}, {ci.upper:.4f}] "
            f"at {ci.confidence_level:.0%} ({ci.n_bootstrap} resamples)"
        )
    if report.psr is not None:
        lines.append(f"PSR (vs zero)     : {report.psr:.4f}")
    if report.deflated_sharpe is not None:
        lines.append(f"Deflated Sharpe   : {report.deflated_sharpe.deflated_sharpe:.4f}")
    else:
        lines.append("Deflated Sharpe   : not evaluated (no trials)")
    if report.pbo is not None:
        lines.append(f"PBO               : {report.pbo.pbo:.4f}")
    if report.reality_check is not None:
        lines.append(f"Reality Check p   : {report.reality_check.pvalue:.4f}")
    if report.spa is not None:
        lines.append(f"Hansen SPA p      : {report.spa.pvalue:.4f}")
    if report.cpcv is not None:
        c = report.cpcv
        lines.append(
            f"CPCV OOS Sharpe   : mean {c.mean:.4f}, std {c.std:.4f}, "
            f"5th pct {c.p05:.4f}, frac_neg {c.fraction_negative:.4f} "
            f"({c.n_combinations} folds)"
        )
    lines.append("")

    # Gate table
    lines.append("## Promotion Gates")
    lines.append("")
    w_name = 36
    w_stat = 14
    w_obs = 10
    w_lim = 10
    header = (
        f"| {'Gate':<{w_name}} "
        f"| {'Status':<{w_stat}} "
        f"| {'Observed':<{w_obs}} "
        f"| {'Limit':<{w_lim}} | Req |"
    )
    divider = (
        f"|{'-' * (w_name + 2)}"
        f"|{'-' * (w_stat + 2)}"
        f"|{'-' * (w_obs + 2)}"
        f"|{'-' * (w_lim + 2)}|-----|"
    )
    lines.append(header)
    lines.append(divider)
    for g in report.gates:
        req = "yes" if g.required else "no "
        status_cell = f"{g.comparison} {g.status}"
        row = (
            f"| {g.name:<{w_name}} "
            f"| {status_cell:<{w_stat}} "
            f"| {_fmt_observed(g.observed):<{w_obs}} "
            f"| {g.limit:<{w_lim}.4f} | {req} |"
        )
        lines.append(row)
    lines.append("")

    # Per-gate reasons
    lines.append("## Gate Detail")
    lines.append("")
    for g in report.gates:
        lines.append(f"- [{g.status}] {g.name}: {g.reason}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Demo synthetic strategy + trials
# ---------------------------------------------------------------------------


def _build_demo_strategy(
    seed: int = 20240605,
    *,
    n_obs: int = 1008,
) -> tuple[pd.Series, pd.DataFrame]:
    """Build a seeded *skilled* strategy plus a trial bank for the CLI demo.

    The strategy has a genuine persistent positive drift; the trial matrix is
    the strategy itself (column 0) surrounded by pure-noise variants, so the
    in-sample winner remains the out-of-sample winner -- the regime the report
    should certify as ``PROMOTE``.
    """
    rng = np.random.default_rng(seed)
    sigma = 0.01
    drift = 1.6 / np.sqrt(252.0) * sigma  # annualised Sharpe ~ 1.6
    strategy = rng.normal(drift, sigma, n_obs)
    noise_bank = rng.normal(0.0, sigma, (n_obs, 15))
    trial_mat = np.column_stack([strategy, noise_bank])

    dates = pd.date_range("2020-01-01", periods=n_obs, freq="B")
    strat_series = pd.Series(strategy, index=dates, name="candidate")
    columns = ["candidate"] + [f"noise{i + 1}" for i in range(noise_bank.shape[1])]
    trials = pd.DataFrame(trial_mat, index=dates, columns=columns)
    return strat_series, trials


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """Parse args and run the robustness report.

    Parameters
    ----------
    argv:
        Argument list (``sys.argv[1:]`` when ``None``). Testable without a
        subprocess by passing a list directly.
    """
    parser = argparse.ArgumentParser(
        prog="python -m core_trading.research.robustness_report",
        description=(
            "Statistical robustness report. Use --demo to run on a seeded "
            "synthetic skilled strategy with a trial bank."
        ),
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run on a seeded synthetic strategy + trials (no live data needed).",
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        default=None,
        help="Write the report to this file path.",
    )
    args = parser.parse_args(argv)

    if not args.demo:
        parser.error(
            "--demo is required (wiring a researched strategy's returns into "
            "the CLI is a later operational concern; see module docstring)."
        )

    strat, trials = _build_demo_strategy()
    # A lighter bootstrap count keeps the demo snappy; the verdict is unchanged
    # because the skilled fixture separates with a wide margin on every gate.
    demo_config = RobustnessConfig(bootstrap_iterations=500)
    report = run_robustness_report(
        strat,
        trial_returns=trials,
        config=demo_config,
        generated_at="1970-01-01T00:00:00Z",
    )
    text = render_robustness_report(report)
    print(text)

    if args.output is not None:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"[robustness_report] Report written to {args.output}")


if __name__ == "__main__":  # pragma: no cover - exercised via main() in tests
    main(sys.argv[1:])
