"""Anti-overfitting guardrails (master plan Phase 2.5).

The single biggest risk in quant research is mistaking luck for skill after
trying many configurations. This module quantifies that risk:

* :func:`probabilistic_sharpe_ratio` -- PSR: confidence a Sharpe exceeds a
  benchmark, correcting for sample length, skew and fat tails (Bailey & de
  Prado 2012).
* :func:`deflated_sharpe_ratio` -- DSR: PSR against the *expected maximum*
  Sharpe from N trials, i.e. Sharpe deflated for selection bias.
* :func:`probability_of_backtest_overfitting` -- PBO via Combinatorially
  Symmetric Cross-Validation (Bailey, Borwein, de Prado, Zhu 2017).
* :func:`whites_reality_check` and :func:`hansens_spa_test` -- test whether the
  best of many strategies genuinely beats a benchmark, via the stationary
  bootstrap.
* :class:`OutOfSampleLockbox` -- enforces the "touch the final slice exactly
  once" discipline with a persistent ledger.

Bootstrap routines take an explicit ``seed`` so results are reproducible.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as _scs

__all__ = [
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
]

_EULER_MASCHERONI = 0.5772156649015329


@dataclass(frozen=True, slots=True)
class DeflatedSharpeResult:
    """Deflated Sharpe ratio and its inputs."""

    deflated_sharpe: float
    probabilistic_sharpe: float
    observed_sharpe: float
    expected_max_sharpe: float
    n_trials: int
    n_obs: int

    @property
    def is_significant(self) -> bool:
        """DSR > 0.95 is the conventional promotion threshold."""
        return self.deflated_sharpe > 0.95


@dataclass(frozen=True, slots=True)
class PBOResult:
    """Probability of Backtest Overfitting and its diagnostics."""

    pbo: float
    logits: np.ndarray
    n_combinations: int
    n_strategies: int

    @property
    def is_overfit(self) -> bool:
        """PBO above 0.5 means the selection process is worse than a coin flip."""
        return self.pbo > 0.5


@dataclass(frozen=True, slots=True)
class BootstrapTestResult:
    """Outcome of a multiple-strategy superiority test."""

    name: str
    statistic: float
    pvalue: float
    n_bootstrap: int
    best_strategy: int

    def is_significant(self, alpha: float = 0.05) -> bool:
        return self.pvalue < alpha


def sharpe_ratio(
    returns: Sequence[float] | pd.Series,
    *,
    periods_per_year: int = 252,
    risk_free: float = 0.0,
    annualised: bool = True,
) -> float:
    """Sharpe ratio of a per-period return series.

    ``risk_free`` is expressed per period. With ``annualised=True`` the result is
    scaled by ``sqrt(periods_per_year)``; set it False to obtain the per-period
    Sharpe required by PSR/DSR.
    """
    arr = np.asarray(returns, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size < 2:
        raise ValueError("sharpe_ratio needs at least 2 observations")
    excess = arr - risk_free
    sd = excess.std(ddof=1)
    if sd == 0:
        return 0.0
    sr = excess.mean() / sd
    return sr * math.sqrt(periods_per_year) if annualised else float(sr)


def probabilistic_sharpe_ratio(
    observed_sharpe: float,
    n_obs: int,
    *,
    benchmark_sharpe: float = 0.0,
    skew: float = 0.0,
    kurtosis: float = 3.0,
) -> float:
    """Probabilistic Sharpe Ratio (Bailey & de Prado 2012).

    Probability that the true (per-period) Sharpe exceeds ``benchmark_sharpe``,
    correcting for sample length and non-normality. ``observed_sharpe`` and
    ``benchmark_sharpe`` are **per-period** (non-annualised). ``kurtosis`` is the
    raw fourth moment (3 for a normal distribution).
    """
    if n_obs < 2:
        raise ValueError("probabilistic_sharpe_ratio needs n_obs >= 2")
    denom = 1.0 - skew * observed_sharpe + ((kurtosis - 1.0) / 4.0) * observed_sharpe**2
    if denom <= 0:
        raise ValueError("non-finite PSR denominator; check skew/kurtosis inputs")
    z = (observed_sharpe - benchmark_sharpe) * math.sqrt(n_obs - 1) / math.sqrt(denom)
    return float(_scs.norm.cdf(z))


def _expected_max_sharpe(trial_sharpe_std: float, n_trials: int) -> float:
    """Expected maximum of ``n_trials`` Sharpe estimates (Bailey & de Prado).

    ``E[max] ≈ σ·[(1-γ)·Z⁻¹(1-1/N) + γ·Z⁻¹(1-1/(N·e))]`` where ``σ`` is the
    cross-trial std of Sharpe estimates and ``γ`` is Euler-Mascheroni.
    """
    if n_trials < 1:
        raise ValueError("n_trials must be >= 1")
    if n_trials == 1:
        return 0.0
    gamma = _EULER_MASCHERONI
    z1 = _scs.norm.ppf(1.0 - 1.0 / n_trials)
    z2 = _scs.norm.ppf(1.0 - 1.0 / (n_trials * math.e))
    return float(trial_sharpe_std * ((1.0 - gamma) * z1 + gamma * z2))


def deflated_sharpe_ratio(
    returns: Sequence[float] | pd.Series,
    *,
    n_trials: int,
    trial_sharpe_std: float | None = None,
    trial_sharpes: Sequence[float] | None = None,
) -> DeflatedSharpeResult:
    """Deflated Sharpe Ratio: PSR against the expected max Sharpe of N trials.

    Provide the spread of the trials either as ``trial_sharpe_std`` directly or
    as the full set of ``trial_sharpes`` (its std is used). The benchmark is the
    expected maximum Sharpe under the null of zero true skill, so a high DSR
    means the strategy beats what selection bias alone would produce.

    ``returns`` are per-period; the observed Sharpe, skew and kurtosis are taken
    from them.
    """
    arr = np.asarray(returns, dtype=float)
    arr = arr[np.isfinite(arr)]
    n_obs = arr.size
    if n_obs < 2:
        raise ValueError("deflated_sharpe_ratio needs at least 2 returns")
    if trial_sharpe_std is None:
        if trial_sharpes is None:
            raise ValueError("provide trial_sharpe_std or trial_sharpes")
        trials = np.asarray(trial_sharpes, dtype=float)
        if trials.size < 2:
            raise ValueError("trial_sharpes needs at least 2 values")
        trial_sharpe_std = float(trials.std(ddof=1))

    observed = sharpe_ratio(arr, annualised=False)
    skew = float(_scs.skew(arr))
    kurt = float(_scs.kurtosis(arr, fisher=False))
    sr0 = _expected_max_sharpe(trial_sharpe_std, n_trials)
    psr_vs_zero = probabilistic_sharpe_ratio(
        observed, n_obs, benchmark_sharpe=0.0, skew=skew, kurtosis=kurt
    )
    dsr = probabilistic_sharpe_ratio(
        observed, n_obs, benchmark_sharpe=sr0, skew=skew, kurtosis=kurt
    )
    return DeflatedSharpeResult(
        deflated_sharpe=dsr,
        probabilistic_sharpe=psr_vs_zero,
        observed_sharpe=observed,
        expected_max_sharpe=sr0,
        n_trials=n_trials,
        n_obs=n_obs,
    )


def _sharpe_columns(matrix: np.ndarray) -> np.ndarray:
    """Per-period Sharpe of each column; zero where a column has no dispersion."""
    mean = matrix.mean(axis=0)
    sd = matrix.std(axis=0, ddof=1)
    out = np.zeros_like(mean)
    nz = sd > 0
    out[nz] = mean[nz] / sd[nz]
    return out


def probability_of_backtest_overfitting(
    returns_matrix: np.ndarray | pd.DataFrame,
    *,
    n_splits: int = 16,
) -> PBOResult:
    """Probability of Backtest Overfitting via CSCV.

    ``returns_matrix`` is ``(T, N)``: ``T`` time observations of ``N`` strategy
    configurations. The series is cut into ``n_splits`` contiguous blocks; for
    every way of choosing half the blocks as in-sample (the rest out-of-sample)
    the best in-sample strategy's out-of-sample rank is measured. PBO is the
    fraction of cases where the in-sample winner lands in the bottom half
    out-of-sample.
    """
    m = np.asarray(returns_matrix, dtype=float)
    if m.ndim != 2:
        raise ValueError("returns_matrix must be 2-D (T x N)")
    t, n_strat = m.shape
    if n_strat < 2:
        raise ValueError("PBO needs at least 2 strategies")
    if n_splits % 2 != 0 or n_splits < 2:
        raise ValueError("n_splits must be even and >= 2")
    if t < n_splits:
        raise ValueError("fewer observations than n_splits")

    blocks = np.array_split(np.arange(t), n_splits)
    half = n_splits // 2
    logits: list[float] = []

    for is_combo in combinations(range(n_splits), half):
        is_set = set(is_combo)
        is_rows = np.concatenate([blocks[b] for b in range(n_splits) if b in is_set])
        oos_rows = np.concatenate([blocks[b] for b in range(n_splits) if b not in is_set])
        is_perf = _sharpe_columns(m[is_rows])
        oos_perf = _sharpe_columns(m[oos_rows])

        best = int(np.argmax(is_perf))
        # Relative rank of the IS winner among OOS performances (1..N).
        rank = float(_scs.rankdata(oos_perf)[best])
        omega = rank / (n_strat + 1)
        omega = min(max(omega, 1e-6), 1 - 1e-6)
        logits.append(math.log(omega / (1.0 - omega)))

    logit_arr = np.asarray(logits, dtype=float)
    pbo = float(np.mean(logit_arr <= 0.0))
    return PBOResult(
        pbo=pbo,
        logits=logit_arr,
        n_combinations=logit_arr.size,
        n_strategies=n_strat,
    )


def _stationary_bootstrap_indices(
    n: int, mean_block: float, n_boot: int, rng: np.random.Generator
) -> np.ndarray:
    """Politis-Romano stationary bootstrap index matrix of shape (n_boot, n)."""
    p = 1.0 / mean_block
    out = np.empty((n_boot, n), dtype=np.intp)
    for b in range(n_boot):
        idx = np.empty(n, dtype=np.intp)
        cur = rng.integers(0, n)
        for i in range(n):
            if i > 0 and rng.random() < p:
                cur = rng.integers(0, n)
            idx[i] = cur
            cur = (cur + 1) % n
        out[b] = idx
    return out


def _newey_west_var(x: np.ndarray) -> float:
    """Newey-West long-run variance of a single series (auto bandwidth)."""
    n = x.size
    xc = x - x.mean()
    gamma0 = float(xc @ xc) / n
    if n < 3:
        return max(gamma0, 1e-12)
    lag_max = int(np.floor(4 * (n / 100.0) ** (2.0 / 9.0)))
    lag_max = max(min(lag_max, n - 1), 1)
    lrv = gamma0
    for lag in range(1, lag_max + 1):
        cov = float(xc[lag:] @ xc[:-lag]) / n
        weight = 1.0 - lag / (lag_max + 1.0)
        lrv += 2.0 * weight * cov
    return max(lrv, 1e-12)


def _superiority_inputs(returns_matrix: np.ndarray | pd.DataFrame, benchmark: float) -> np.ndarray:
    d = np.asarray(returns_matrix, dtype=float)
    if d.ndim != 2:
        raise ValueError("returns_matrix must be 2-D (T x N)")
    if d.shape[1] < 1:
        raise ValueError("need at least one strategy")
    return d - benchmark


def whites_reality_check(
    returns_matrix: np.ndarray | pd.DataFrame,
    *,
    benchmark: float = 0.0,
    n_bootstrap: int = 1000,
    mean_block: float = 10.0,
    seed: int = 0,
) -> BootstrapTestResult:
    """White's Reality Check for data snooping (White 2000).

    Tests H0: the best of ``N`` strategies does not outperform the benchmark.
    ``returns_matrix`` is ``(T, N)`` of per-period returns; ``benchmark`` is the
    per-period benchmark return. Uses the stationary bootstrap.
    """
    d = _superiority_inputs(returns_matrix, benchmark)
    t, _n = d.shape
    means = d.mean(axis=0)
    v_stat = math.sqrt(t) * float(means.max())
    best = int(np.argmax(means))

    rng = np.random.default_rng(seed)
    boot_idx = _stationary_bootstrap_indices(t, mean_block, n_bootstrap, rng)
    count = 0
    for b in range(n_bootstrap):
        sample = d[boot_idx[b]]
        boot_means = sample.mean(axis=0) - means  # recentre under H0
        v_boot = math.sqrt(t) * float(boot_means.max())
        if v_boot >= v_stat:
            count += 1
    pvalue = (count + 1) / (n_bootstrap + 1)
    return BootstrapTestResult(
        name="White's Reality Check",
        statistic=v_stat,
        pvalue=pvalue,
        n_bootstrap=n_bootstrap,
        best_strategy=best,
    )


def hansens_spa_test(
    returns_matrix: np.ndarray | pd.DataFrame,
    *,
    benchmark: float = 0.0,
    n_bootstrap: int = 1000,
    mean_block: float = 10.0,
    seed: int = 0,
) -> BootstrapTestResult:
    """Hansen's Superior Predictive Ability test (consistent variant, 2005).

    A studentised, less conservative refinement of White's Reality Check: each
    strategy is scaled by its long-run standard deviation and obviously-inferior
    strategies are removed from the null distribution by the consistent
    recentring rule. Tests H0: no strategy beats the benchmark.
    """
    d = _superiority_inputs(returns_matrix, benchmark)
    t, n = d.shape
    means = d.mean(axis=0)
    omega = np.sqrt(np.array([_newey_west_var(d[:, j]) for j in range(n)]))

    studentised = math.sqrt(t) * means / omega
    t_spa = max(float(studentised.max()), 0.0)
    best = int(np.argmax(studentised))

    # Consistent recentring: keep the mean only for strategies that are not
    # clearly inferior (Hansen 2005, eq. for SPA_c).
    threshold = -omega * math.sqrt(2.0 * math.log(math.log(t)) / t) if t >= 3 else -omega
    mu_c = np.where(means >= threshold, means, 0.0)

    rng = np.random.default_rng(seed)
    boot_idx = _stationary_bootstrap_indices(t, mean_block, n_bootstrap, rng)
    count = 0
    for b in range(n_bootstrap):
        sample = d[boot_idx[b]]
        boot_means = sample.mean(axis=0) - mu_c
        z = math.sqrt(t) * float((boot_means / omega).max())
        if max(z, 0.0) >= t_spa:
            count += 1
    pvalue = (count + 1) / (n_bootstrap + 1)
    return BootstrapTestResult(
        name="Hansen's SPA (consistent)",
        statistic=t_spa,
        pvalue=pvalue,
        n_bootstrap=n_bootstrap,
        best_strategy=best,
    )


class LockboxAlreadyOpenedError(RuntimeError):
    """Raised when an out-of-sample lockbox is opened more than once."""


class OutOfSampleLockbox:
    """Enforces the "touch the final slice exactly once" discipline.

    The final ``lockbox_fraction`` of a chronologically-ordered dataset is
    sealed. :attr:`development_set` is freely usable for research; the held-out
    tail is returned only by :meth:`open_lockbox`, which records the access
    (timestamp, reason, data fingerprint) to a JSON ledger and refuses a second
    open. The ledger persists across sessions so the discipline survives process
    restarts.
    """

    def __init__(
        self,
        data: pd.DataFrame | pd.Series,
        *,
        lockbox_fraction: float = 0.2,
        ledger_path: str | Path,
        name: str = "default",
    ) -> None:
        if not 0.0 < lockbox_fraction < 1.0:
            raise ValueError("lockbox_fraction must be in (0, 1)")
        if len(data) < 2:
            raise ValueError("dataset too small to split")
        self._data = data
        self.name = name
        self.ledger_path = Path(ledger_path)
        split = int(len(data) * (1.0 - lockbox_fraction))
        split = min(max(split, 1), len(data) - 1)
        self._split = split

    @property
    def development_set(self) -> pd.DataFrame | pd.Series:
        """The in-development portion -- safe to use repeatedly."""
        return self._data.iloc[: self._split]

    @property
    def lockbox_size(self) -> int:
        return len(self._data) - self._split

    def _fingerprint(self) -> str:
        tail = self._data.iloc[self._split :]
        raw = pd.util.hash_pandas_object(tail, index=True).values.tobytes()
        return hashlib.sha256(raw).hexdigest()

    def _read_ledger(self) -> dict:
        if self.ledger_path.exists():
            return json.loads(self.ledger_path.read_text(encoding="utf-8"))
        return {}

    def _write_ledger(self, ledger: dict) -> None:
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self.ledger_path.write_text(json.dumps(ledger, indent=2), encoding="utf-8")

    def is_opened(self) -> bool:
        return self.name in self._read_ledger()

    def open_lockbox(self, reason: str, *, force: bool = False) -> pd.DataFrame | pd.Series:
        """Return the held-out data exactly once, logging the access.

        Raises :class:`LockboxAlreadyOpenedError` on a second open unless
        ``force=True``, which is permitted but recorded as a discipline
        violation in the ledger.
        """
        if not reason or not reason.strip():
            raise ValueError("open_lockbox requires a non-empty reason")
        ledger = self._read_ledger()
        already = self.name in ledger
        if already and not force:
            prior = ledger[self.name]
            raise LockboxAlreadyOpenedError(
                f"lockbox '{self.name}' was already opened at {prior['opened_at']} "
                f"(reason: {prior['reason']!r}). Out-of-sample data is single-use."
            )

        record = {
            "opened_at": datetime.now(UTC).isoformat(),
            "reason": reason.strip(),
            "fingerprint": self._fingerprint(),
            "lockbox_size": self.lockbox_size,
            "forced": bool(already and force),
        }
        entry = ledger.get(self.name)
        if entry is None:
            ledger[self.name] = record
        else:
            entry.setdefault("violations", []).append(record)
        self._write_ledger(ledger)
        return self._data.iloc[self._split :]
