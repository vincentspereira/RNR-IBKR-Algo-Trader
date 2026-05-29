"""Statistical test toolkit (master plan Phase 2.3).

Cleanly implemented, unit-tested statistical tests used throughout research:
stationarity, cointegration, long-memory, mean-reversion, autocorrelation,
normality, volatility clustering, structural breaks, and multiple-testing
corrections.

Design notes
------------
* Each hypothesis test returns a :class:`StatTestResult` carrying the statistic,
  p-value (where defined), critical values, the null hypothesis in plain
  English, and a convenience :meth:`StatTestResult.is_significant`.
* Estimation routines (Hurst exponent, mean-reversion half-life / OU process)
  return purpose-built result objects since they have no p-value.
* Well-validated third-party implementations (``statsmodels``, ``arch``) are
  used where they exist; thin wrappers normalise their return shapes and
  capture expected informational warnings (e.g. KPSS p-value interpolation)
  into ``result.notes`` rather than letting them propagate. Hand-rolled methods
  (Hurst, OU half-life, Chow) are validated against textbook expectations in the
  test-suite.

All inputs accept ``pandas.Series`` or 1-D array-likes; NaNs are dropped at the
boundary so callers do not have to pre-clean.
"""
from __future__ import annotations

import warnings
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

__all__ = [
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
]


@dataclass(frozen=True, slots=True)
class StatTestResult:
    """Outcome of a hypothesis test.

    Attributes
    ----------
    name:
        Human-readable test name.
    statistic:
        The test statistic.
    pvalue:
        The p-value, or ``None`` for tests that report only critical values.
    null_hypothesis:
        Plain-English statement of H0, so callers know which direction a
        rejection points.
    crit_values:
        Mapping of significance level (e.g. ``"5%"``) to critical value.
    lags:
        Lag/order parameter used, where relevant.
    notes:
        Diagnostic notes (e.g. captured interpolation warnings).
    extra:
        Test-specific scalar outputs.
    """

    name: str
    statistic: float
    pvalue: float | None = None
    null_hypothesis: str = ""
    crit_values: dict[str, float] = field(default_factory=dict)
    lags: int | None = None
    notes: tuple[str, ...] = ()
    extra: dict[str, float] = field(default_factory=dict)

    def is_significant(self, alpha: float = 0.05) -> bool:
        """Return ``True`` when H0 is rejected at level ``alpha``.

        Uses the p-value when available, otherwise compares the (absolute)
        statistic against the critical value bracketing ``alpha``.
        """
        if self.pvalue is not None:
            return self.pvalue < alpha
        key = f"{int(round(alpha * 100))}%"
        if key not in self.crit_values:
            raise ValueError(f"no p-value and no '{key}' critical value for {self.name}")
        # Unit-root / cointegration statistics are negative; rejection is when
        # the statistic is *more negative* than the critical value.
        return self.statistic < self.crit_values[key]


@dataclass(frozen=True, slots=True)
class HurstResult:
    """Hurst-exponent estimate and its interpretation."""

    exponent: float
    method: str
    n_obs: int

    @property
    def interpretation(self) -> str:
        if self.exponent < 0.45:
            return "mean-reverting"
        if self.exponent > 0.55:
            return "trending"
        return "random-walk"


@dataclass(frozen=True, slots=True)
class HalfLifeResult:
    """Ornstein-Uhlenbeck mean-reversion estimate.

    Attributes
    ----------
    half_life:
        Periods for the spread to revert half-way to its mean, ``ln(2)/kappa``.
        ``inf`` when the series is not mean-reverting (non-negative slope).
    kappa:
        Mean-reversion speed (per period).
    mu:
        Long-run mean of the level.
    sigma:
        Instantaneous volatility of the OU process.
    n_obs:
        Sample size used.
    """

    half_life: float
    kappa: float
    mu: float
    sigma: float
    n_obs: int

    @property
    def is_mean_reverting(self) -> bool:
        return np.isfinite(self.half_life) and self.kappa > 0


@dataclass(frozen=True, slots=True)
class JohansenResult:
    """Johansen cointegration test (trace and max-eigenvalue statistics)."""

    trace_stats: np.ndarray
    trace_crit: np.ndarray  # columns: 90%, 95%, 99%
    max_eig_stats: np.ndarray
    max_eig_crit: np.ndarray
    eigenvalues: np.ndarray
    eigenvectors: np.ndarray
    n_series: int

    def rank(self, alpha: str = "95%") -> int:
        """Number of cointegrating relations via the trace test at ``alpha``.

        ``alpha`` is one of ``"90%"``, ``"95%"``, ``"99%"`` (column index into
        the critical-value table).
        """
        col = {"90%": 0, "95%": 1, "99%": 2}[alpha]
        rank = 0
        for stat, crit in zip(self.trace_stats, self.trace_crit[:, col], strict=False):
            if stat > crit:
                rank += 1
            else:
                break
        return rank

    def hedge_ratios(self) -> np.ndarray:
        """First cointegrating vector, normalised so the first element is 1."""
        vec = self.eigenvectors[:, 0]
        if vec[0] == 0:
            return vec
        return vec / vec[0]


def _clean(x: Sequence[float] | pd.Series) -> np.ndarray:
    """Coerce to a 1-D float array with NaNs/Infs removed."""
    arr = np.asarray(x, dtype=float).ravel()
    return arr[np.isfinite(arr)]


def adf_test(
    series: Sequence[float] | pd.Series,
    *,
    regression: str = "c",
    max_lag: int | None = None,
    autolag: str | None = "AIC",
) -> StatTestResult:
    """Augmented Dickey-Fuller unit-root test.

    H0: the series has a unit root (is non-stationary). A small p-value implies
    stationarity. ``regression`` is one of ``"c"`` (constant), ``"ct"``
    (constant+trend), ``"ctt"``, ``"n"`` (none).
    """
    from statsmodels.tsa.stattools import adfuller

    arr = _clean(series)
    if arr.size < 4:
        raise ValueError("adf_test needs at least 4 observations")
    stat, pvalue, usedlag, _nobs, crit, _icbest = adfuller(
        arr, maxlag=max_lag, regression=regression, autolag=autolag
    )
    return StatTestResult(
        name="Augmented Dickey-Fuller",
        statistic=float(stat),
        pvalue=float(pvalue),
        null_hypothesis="series has a unit root (non-stationary)",
        crit_values={k: float(v) for k, v in crit.items()},
        lags=int(usedlag),
    )


def kpss_test(
    series: Sequence[float] | pd.Series,
    *,
    regression: str = "c",
    nlags: str | int = "auto",
) -> StatTestResult:
    """KPSS stationarity test.

    H0: the series is (trend-)stationary. A small p-value implies a unit root --
    the *opposite* null to ADF, so the two are used together. ``regression`` is
    ``"c"`` (level-stationary) or ``"ct"`` (trend-stationary).
    """
    from statsmodels.tools.sm_exceptions import InterpolationWarning
    from statsmodels.tsa.stattools import kpss

    arr = _clean(series)
    if arr.size < 4:
        raise ValueError("kpss_test needs at least 4 observations")
    notes: list[str] = []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", InterpolationWarning)
        stat, pvalue, usedlag, crit = kpss(arr, regression=regression, nlags=nlags)
    for w in caught:
        if issubclass(w.category, InterpolationWarning):
            notes.append(
                "p-value outside lookup table; reported value is a boundary "
                "(actual p-value is smaller/larger than stated)"
            )
    return StatTestResult(
        name="KPSS",
        statistic=float(stat),
        pvalue=float(pvalue),
        null_hypothesis="series is (trend-)stationary",
        crit_values={k: float(v) for k, v in crit.items()},
        lags=int(usedlag),
        notes=tuple(notes),
    )


def phillips_perron_test(
    series: Sequence[float] | pd.Series,
    *,
    trend: str = "c",
) -> StatTestResult:
    """Phillips-Perron unit-root test (HAC-robust alternative to ADF).

    H0: the series has a unit root. ``trend`` is ``"n"``, ``"c"`` or ``"ct"``.
    """
    from arch.unitroot import PhillipsPerron

    arr = _clean(series)
    if arr.size < 4:
        raise ValueError("phillips_perron_test needs at least 4 observations")
    pp = PhillipsPerron(arr, trend=trend)
    return StatTestResult(
        name="Phillips-Perron",
        statistic=float(pp.stat),
        pvalue=float(pp.pvalue),
        null_hypothesis="series has a unit root (non-stationary)",
        crit_values={k: float(v) for k, v in pp.critical_values.items()},
        lags=int(pp.lags),
    )


def engle_granger_test(
    y: Sequence[float] | pd.Series,
    x: Sequence[float] | pd.Series,
    *,
    trend: str = "c",
) -> StatTestResult:
    """Engle-Granger two-step cointegration test.

    Regresses ``y`` on ``x`` and tests the residual for a unit root. H0: the two
    series are **not** cointegrated; a small p-value implies cointegration. The
    fitted hedge ratio is returned in ``extra["hedge_ratio"]``.
    """
    from statsmodels.regression.linear_model import OLS
    from statsmodels.tools import add_constant
    from statsmodels.tsa.stattools import coint

    ya = _clean(y)
    xa = _clean(x)
    if ya.size != xa.size:
        raise ValueError("engle_granger_test requires equal-length series")
    if ya.size < 12:
        raise ValueError("engle_granger_test needs at least 12 observations")

    stat, pvalue, crit = coint(ya, xa, trend=trend)
    # Recover the static hedge ratio (slope of y on x).
    design = add_constant(xa) if trend in ("c", "ct") else xa.reshape(-1, 1)
    beta = OLS(ya, design).fit().params
    hedge = float(beta[-1])
    crit_map = {"1%": float(crit[0]), "5%": float(crit[1]), "10%": float(crit[2])}
    return StatTestResult(
        name="Engle-Granger",
        statistic=float(stat),
        pvalue=float(pvalue),
        null_hypothesis="series are not cointegrated",
        crit_values=crit_map,
        extra={"hedge_ratio": hedge},
    )


def johansen_test(
    frame: pd.DataFrame,
    *,
    det_order: int = 0,
    k_ar_diff: int = 1,
) -> JohansenResult:
    """Johansen cointegration test for a system of series.

    ``frame`` columns are the series. ``det_order`` is ``-1`` (no deterministic
    term), ``0`` (constant) or ``1`` (linear trend). ``k_ar_diff`` is the number
    of lagged differences. Returns trace and max-eigenvalue statistics with
    their 90/95/99% critical values; use :meth:`JohansenResult.rank`.
    """
    from statsmodels.tsa.vector_ar.vecm import coint_johansen

    data = frame.dropna()
    if data.shape[1] < 2:
        raise ValueError("johansen_test needs at least 2 series")
    if data.shape[0] < 12:
        raise ValueError("johansen_test needs at least 12 observations")

    res = coint_johansen(data.values, det_order, k_ar_diff)
    return JohansenResult(
        trace_stats=np.asarray(res.lr1, dtype=float),
        trace_crit=np.asarray(res.cvt, dtype=float),
        max_eig_stats=np.asarray(res.lr2, dtype=float),
        max_eig_crit=np.asarray(res.cvm, dtype=float),
        eigenvalues=np.asarray(res.eig, dtype=float),
        eigenvectors=np.asarray(res.evec, dtype=float),
        n_series=int(data.shape[1]),
    )


def hurst_exponent(
    series: Sequence[float] | pd.Series,
    *,
    min_lag: int = 2,
    max_lag: int = 100,
) -> HurstResult:
    """Estimate the Hurst exponent via the variance-of-lagged-differences method.

    For a process whose lag-``k`` increments have standard deviation scaling as
    ``k**H``, the slope of ``log(std)`` against ``log(k)`` is ``H``. A random
    walk gives ``H≈0.5``; ``H<0.5`` indicates mean reversion, ``H>0.5`` trending
    (long memory). Applied to a *price level* series.
    """
    arr = _clean(series)
    n = arr.size
    if n < min_lag + 2:
        raise ValueError("hurst_exponent needs more observations than min_lag")
    top = min(max_lag, n - 1)
    if top <= min_lag:
        raise ValueError("max_lag too small for the series length")

    lags = np.arange(min_lag, top + 1)
    taus = []
    valid_lags = []
    for lag in lags:
        diff = arr[lag:] - arr[:-lag]
        sd = diff.std()
        if sd > 0:
            taus.append(sd)
            valid_lags.append(lag)
    if len(valid_lags) < 2:
        raise ValueError("insufficient variation to estimate Hurst exponent")

    slope = np.polyfit(np.log(valid_lags), np.log(taus), 1)[0]
    return HurstResult(exponent=float(slope), method="variance-of-differences", n_obs=n)


def half_life(series: Sequence[float] | pd.Series) -> HalfLifeResult:
    """Estimate Ornstein-Uhlenbeck mean-reversion parameters and half-life.

    Fits ``Δs_t = a + b·s_{t-1} + ε`` by OLS. The mean-reversion speed is
    ``κ = -b``; half-life is ``ln(2)/κ`` (``inf`` when ``b ≥ 0``). The long-run
    mean is ``μ = -a/b`` and ``σ`` is derived from the residual variance.
    """
    arr = _clean(series)
    if arr.size < 3:
        raise ValueError("half_life needs at least 3 observations")

    lagged = arr[:-1]
    delta = arr[1:] - lagged
    design = np.column_stack([np.ones_like(lagged), lagged])
    coef, *_ = np.linalg.lstsq(design, delta, rcond=None)
    a, b = float(coef[0]), float(coef[1])

    resid = delta - design @ coef
    dof = max(len(delta) - 2, 1)
    resid_var = float(resid @ resid) / dof

    kappa = -b
    if b < 0:
        hl = float(np.log(2.0) / kappa)
        mu = -a / b
        sigma = float(np.sqrt(resid_var))
    else:
        hl = float("inf")
        mu = float("nan")
        sigma = float(np.sqrt(resid_var))
    return HalfLifeResult(
        half_life=hl, kappa=float(kappa), mu=float(mu), sigma=sigma, n_obs=arr.size
    )


def variance_ratio_test(
    series: Sequence[float] | pd.Series,
    *,
    lags: int = 2,
    trend: str = "c",
    overlap: bool = True,
) -> StatTestResult:
    """Lo-MacKinlay variance-ratio test for a random walk.

    H0: the series follows a random walk (variance ratio = 1). A significant
    result with VR > 1 indicates positive autocorrelation (trending); VR < 1
    indicates mean reversion. ``series`` is a price level (the test differences
    it internally).
    """
    from arch.unitroot import VarianceRatio

    arr = _clean(series)
    if arr.size < lags + 2:
        raise ValueError("variance_ratio_test needs more observations than lags")
    vr = VarianceRatio(arr, lags=lags, trend=trend, overlap=overlap)
    return StatTestResult(
        name="Variance Ratio (Lo-MacKinlay)",
        statistic=float(vr.stat),
        pvalue=float(vr.pvalue),
        null_hypothesis="series follows a random walk (VR = 1)",
        lags=lags,
        extra={"variance_ratio": float(vr.vr)},
    )


def ljung_box_test(
    series: Sequence[float] | pd.Series,
    *,
    lags: int = 10,
) -> StatTestResult:
    """Ljung-Box test for autocorrelation up to ``lags``.

    H0: no autocorrelation. A small p-value implies the series is
    autocorrelated. The statistic/p-value reported are for the largest lag.
    """
    from statsmodels.stats.diagnostic import acorr_ljungbox

    arr = _clean(series)
    if arr.size < lags + 1:
        raise ValueError("ljung_box_test needs more observations than lags")
    out = acorr_ljungbox(arr, lags=[lags], return_df=True)
    stat = float(out["lb_stat"].iloc[-1])
    pvalue = float(out["lb_pvalue"].iloc[-1])
    return StatTestResult(
        name="Ljung-Box",
        statistic=stat,
        pvalue=pvalue,
        null_hypothesis="no autocorrelation up to the tested lag",
        lags=lags,
    )


def jarque_bera_test(series: Sequence[float] | pd.Series) -> StatTestResult:
    """Jarque-Bera normality test (skewness + kurtosis).

    H0: the data are normally distributed. Skewness and excess kurtosis are
    returned in ``extra``.
    """
    from scipy import stats as scipy_stats

    arr = _clean(series)
    if arr.size < 2:
        raise ValueError("jarque_bera_test needs at least 2 observations")
    stat, pvalue = scipy_stats.jarque_bera(arr)
    return StatTestResult(
        name="Jarque-Bera",
        statistic=float(stat),
        pvalue=float(pvalue),
        null_hypothesis="data are normally distributed",
        extra={
            "skew": float(scipy_stats.skew(arr)),
            "excess_kurtosis": float(scipy_stats.kurtosis(arr)),
        },
    )


def arch_lm_test(
    series: Sequence[float] | pd.Series,
    *,
    lags: int = 12,
) -> StatTestResult:
    """Engle's ARCH-LM test for conditional heteroskedasticity (vol clustering).

    H0: no ARCH effects (homoskedastic). A small p-value implies volatility
    clustering. ``series`` is typically a residual or return series.
    """
    from statsmodels.stats.diagnostic import het_arch

    arr = _clean(series)
    if arr.size < lags + 1:
        raise ValueError("arch_lm_test needs more observations than lags")
    lm_stat, lm_pvalue, f_stat, f_pvalue = het_arch(arr, nlags=lags)
    return StatTestResult(
        name="Engle ARCH-LM",
        statistic=float(lm_stat),
        pvalue=float(lm_pvalue),
        null_hypothesis="no ARCH effects (homoskedastic)",
        lags=lags,
        extra={"f_statistic": float(f_stat), "f_pvalue": float(f_pvalue)},
    )


def chow_test(
    y: Sequence[float] | pd.Series,
    x: Sequence[float] | pd.Series,
    break_index: int,
) -> StatTestResult:
    """Chow test for a structural break at a known point.

    Fits ``y = a + b·x`` on the full sample and on the two sub-samples split at
    ``break_index`` and compares residual sums of squares with an F-test.
    H0: no structural break (coefficients stable across the break).
    """
    from scipy import stats as scipy_stats

    ya = _clean(y)
    xa = _clean(x)
    if ya.size != xa.size:
        raise ValueError("chow_test requires equal-length series")
    n = ya.size
    k = 2  # intercept + slope
    if break_index <= k or break_index >= n - k:
        raise ValueError("break_index too close to the sample boundary")

    def _rss(yy: np.ndarray, xx: np.ndarray) -> float:
        design = np.column_stack([np.ones_like(xx), xx])
        coef, *_ = np.linalg.lstsq(design, yy, rcond=None)
        resid = yy - design @ coef
        return float(resid @ resid)

    rss_pooled = _rss(ya, xa)
    rss1 = _rss(ya[:break_index], xa[:break_index])
    rss2 = _rss(ya[break_index:], xa[break_index:])
    rss_split = rss1 + rss2
    denom = rss_split / (n - 2 * k)
    if denom <= 0:
        raise ValueError("degenerate sub-sample fit; cannot compute Chow test")
    f_stat = ((rss_pooled - rss_split) / k) / denom
    pvalue = float(scipy_stats.f.sf(f_stat, k, n - 2 * k))
    return StatTestResult(
        name="Chow",
        statistic=float(f_stat),
        pvalue=pvalue,
        null_hypothesis="no structural break (stable coefficients)",
        extra={"break_index": float(break_index)},
    )


def cusum_stability_test(
    y: Sequence[float] | pd.Series,
    x: Sequence[float] | pd.Series,
) -> StatTestResult:
    """Brown-Durbin-Evans CUSUM test of parameter stability (unknown break).

    Uses recursive residuals of ``y = a + b·x``. H0: coefficients are stable
    over the sample. The statistic is the maximum absolute scaled CUSUM; it is
    compared against the 5% boundary (a≈0.948 line), reported as a critical
    value so :meth:`StatTestResult.is_significant` works without a p-value.
    """
    from statsmodels.stats.diagnostic import breaks_cusumolsresid
    from statsmodels.tools import add_constant

    ya = _clean(y)
    xa = _clean(x)
    if ya.size != xa.size:
        raise ValueError("cusum_stability_test requires equal-length series")
    if ya.size < 8:
        raise ValueError("cusum_stability_test needs at least 8 observations")

    from statsmodels.regression.linear_model import OLS

    design = add_constant(xa)
    resid = OLS(ya, design).fit().resid
    stat, pvalue, _crit = breaks_cusumolsresid(resid, ddof=design.shape[1])
    return StatTestResult(
        name="CUSUM (Brown-Durbin-Evans)",
        statistic=float(stat),
        pvalue=float(pvalue),
        null_hypothesis="regression coefficients are stable over the sample",
    )


def adjust_pvalues(
    pvalues: Sequence[float],
    *,
    method: str = "holm",
    alpha: float = 0.05,
) -> tuple[np.ndarray, np.ndarray]:
    """Correct a family of p-values for multiple testing.

    ``method`` is ``"bonferroni"``, ``"holm"`` or ``"fdr_bh"``
    (Benjamini-Hochberg). Returns ``(reject, adjusted_pvalues)`` where
    ``reject`` is a boolean array of which hypotheses survive at ``alpha``.
    """
    from statsmodels.stats.multitest import multipletests

    arr = np.asarray(pvalues, dtype=float)
    if arr.size == 0:
        return np.array([], dtype=bool), np.array([], dtype=float)
    alias = {"bh": "fdr_bh", "benjamini-hochberg": "fdr_bh"}
    method = alias.get(method.lower(), method)
    reject, adjusted, _a1, _a2 = multipletests(arr, alpha=alpha, method=method)
    return reject, adjusted
