"""Portfolio-level Value-at-Risk (Phase 7, module 7.3).

This module provides three complementary VaR estimators -- parametric
(variance-covariance), historical simulation, and Monte Carlo -- together with
the two principal statistical backtests for evaluating VaR model performance:
the Kupiec (1995) proportion-of-failures likelihood-ratio test and the
Christoffersen (1998) independence and conditional-coverage tests.

Sign convention
---------------
**VaR is reported as a POSITIVE loss number.**  A VaR of 0.02 means the model
expects a loss of at least 2% of portfolio value will be exceeded with
probability ``1 - confidence`` over the stated horizon.  This is consistent
with ``core_trading.risk.pairs_risk`` and
``core_trading.backtest.metrics.value_at_risk``, both of which negate the
left-tail quantile before returning.

Parametric VaR (iid assumption)
--------------------------------
The sqrt-time scaling rule ``VaR_h = VaR_1 * sqrt(h)`` applied in
:func:`parametric_var` and :func:`monte_carlo_var` rests on the assumption
that returns are independent and identically distributed (iid) over successive
periods.  Under this assumption the h-period variance is h times the 1-period
variance.  **The iid assumption is violated in practice** -- autocorrelation and
volatility clustering both invalidate it -- so 10-day parametric VaR should be
treated as a rough approximation only; historical and Monte Carlo VaR with
direct multi-step simulation are more reliable for longer horizons.

Cornish-Fisher VaR
------------------
The Cornish-Fisher expansion (Zangari 1996 / Favre-Galeano 2002) adjusts the
normal z-quantile for the skewness (gamma_1) and excess kurtosis (gamma_2) of
the return distribution:

    z_CF = z + (z^2 - 1) * gamma_1 / 6
             + (z^3 - 3z) * gamma_2 / 24
             - (2z^3 - 5z) * gamma_1^2 / 36

When gamma_1 = 0 and gamma_2 = 0 (normal distribution) the formula reduces to
the plain normal z-quantile, so Cornish-Fisher subsumes the standard parametric
VaR as a special case.

Mathematical references
-----------------------
  * Jorion, P. (2006). "Value at Risk: The New Benchmark for Managing Financial
    Risk." 3rd ed. McGraw-Hill.
  * Kupiec, P. (1995). "Techniques for Verifying the Accuracy of Risk
    Measurement Models." Journal of Derivatives, 3(2), 73-84.
  * Christoffersen, P. (1998). "Evaluating Interval Forecasts." International
    Economic Review, 39(4), 841-862.
  * Zangari, P. (1996). "A VaR Methodology for Portfolios That Include Options."
    RiskMetrics Monitor, Q1.
  * Favre, L. & Galeano, J.-A. (2002). "Mean-Modified Value-at-Risk Optimization
    with Hedge Funds." Journal of Alternative Investments, 5(2), 21-25.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import overload

import numpy as np
import pandas as pd
import scipy.stats as stats

__all__ = [
    "VaRConfig",
    "VaRResult",
    "BacktestResult",
    "parametric_var",
    "historical_var",
    "monte_carlo_var",
    "kupiec_test",
    "christoffersen_test",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Supported confidence levels and their normal z-quantiles (upper-tail).
# z_alpha satisfies P(Z <= z_alpha) = 1 - alpha for Z ~ N(0, 1).
# E.g. alpha = 0.05 -> confidence = 0.95 -> z = 1.6449.
_Z_NORMAL: dict[float, float] = {
    0.05: float(stats.norm.ppf(0.95)),   # 1.6449
    0.01: float(stats.norm.ppf(0.99)),   # 2.3263
}

# ---------------------------------------------------------------------------
# Configuration and result DTOs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VaRConfig:
    """Immutable configuration for VaR estimation.

    Attributes
    ----------
    confidence:
        Confidence level in (0, 1).  Standard values are 0.95 and 0.99.
        The tail probability is ``alpha = 1 - confidence``.
    horizon:
        Holding period in days.  Standard values are 1 and 10.
        Parametric and Monte Carlo VaR apply sqrt-time scaling (see module
        docstring for the iid caveat).  Historical VaR uses empirical quantiles
        of 1-day returns scaled by sqrt(horizon).
    n_simulations:
        Number of Monte Carlo paths.  Default 50_000.  Must be >= 1000.
    rng_seed:
        Seed for the numpy ``default_rng`` Generator used in Monte Carlo.
        Pass ``None`` for a non-reproducible draw.
    significance:
        Size of the hypothesis tests in :func:`kupiec_test` and
        :func:`christoffersen_test`.  Default 0.05 (5% significance).
    """

    confidence: float = 0.95
    horizon: int = 1
    n_simulations: int = 50_000
    rng_seed: int | None = 42
    significance: float = 0.05

    def __post_init__(self) -> None:
        """Validate all configuration fields."""
        if not (0.0 < self.confidence < 1.0):
            raise ValueError(
                f"confidence must be in (0, 1), got {self.confidence!r}"
            )
        if self.horizon < 1:
            raise ValueError(
                f"horizon must be >= 1, got {self.horizon!r}"
            )
        if self.n_simulations < 1000:
            raise ValueError(
                f"n_simulations must be >= 1000, got {self.n_simulations!r}"
            )
        if not (0.0 < self.significance < 1.0):
            raise ValueError(
                f"significance must be in (0, 1), got {self.significance!r}"
            )

    @property
    def alpha(self) -> float:
        """Tail probability; ``1 - confidence``."""
        return 1.0 - self.confidence


@dataclass(frozen=True, slots=True)
class VaRResult:
    """Output of a single VaR computation.

    Attributes
    ----------
    var:
        Value-at-Risk as a POSITIVE loss fraction (or dollar amount if the
        inputs are in dollar terms).  Equals the alpha-quantile of the loss
        distribution, negated.
    method:
        Estimator identifier: ``"parametric"``, ``"parametric_cornish_fisher"``,
        ``"historical"``, or ``"monte_carlo"``.
    confidence:
        Confidence level used, mirroring :attr:`VaRConfig.confidence`.
    horizon:
        Holding-period horizon in days.
    alpha:
        Tail probability; ``1 - confidence``.
    """

    var: float
    method: str
    confidence: float
    horizon: int
    alpha: float


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """Output of a VaR backtest (Kupiec or Christoffersen test).

    Attributes
    ----------
    test_name:
        One of ``"kupiec_pof"``, ``"christoffersen_independence"``, or
        ``"christoffersen_cc"``.
    lr_statistic:
        Likelihood-ratio test statistic (chi-squared distributed under H0).
    p_value:
        P-value of the LR test; small values indicate model mis-specification.
    degrees_of_freedom:
        Degrees of freedom of the chi-squared reference distribution.
    n_exceptions:
        Observed number of VaR breaches (returns that exceeded the VaR).
    expected_exceptions:
        Expected number of exceptions under a correctly specified model;
        ``alpha * n_observations`` for POF.
    n_observations:
        Total number of return observations tested.
    passed:
        ``True`` when ``p_value >= significance``; the model is not rejected
        at the configured significance level.
    significance:
        Significance level used for the pass/fail decision.
    """

    test_name: str
    lr_statistic: float
    p_value: float
    degrees_of_freedom: int
    n_exceptions: int
    expected_exceptions: float
    n_observations: int
    passed: bool
    significance: float


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_returns_1d(returns: pd.Series | np.ndarray, name: str = "returns") -> np.ndarray:
    """Validate and flatten a 1-D return series, stripping NaN.

    Parameters
    ----------
    returns:
        1-D array-like of period returns.
    name:
        Variable name for error messages.

    Returns
    -------
    numpy.ndarray
        Finite-valued 1-D float64 array.

    Raises
    ------
    ValueError
        If the result is empty or all-NaN.
    """
    arr: np.ndarray = np.asarray(returns, dtype=float).ravel()
    finite: np.ndarray = arr[np.isfinite(arr)]
    if finite.size == 0:
        raise ValueError(
            f"{name} must contain at least one finite value; got {arr.size} total "
            f"with {arr.size - finite.size} non-finite."
        )
    return finite


def _validate_weights_panel(
    weights: np.ndarray,
    returns: pd.DataFrame,
    label: str = "weights",
) -> tuple[np.ndarray, np.ndarray]:
    """Validate aligned portfolio weights and returns panel.

    Parameters
    ----------
    weights:
        1-D array of asset weights, length N.  Need not sum to 1.
    returns:
        DataFrame with T rows (observations) and N columns (assets).
    label:
        Label for ``weights`` used in error messages.

    Returns
    -------
    tuple[numpy.ndarray, numpy.ndarray]
        ``(w, R)`` where ``w`` is float64 shape (N,) and ``R`` is float64
        shape (T, N).

    Raises
    ------
    ValueError
        On shape mismatch, NaN values, or empty inputs.
    """
    w = np.asarray(weights, dtype=float).ravel()
    r = returns.to_numpy(dtype=float)
    if w.shape[0] != r.shape[1]:
        raise ValueError(
            f"{label} has {w.shape[0]} elements but returns DataFrame has "
            f"{r.shape[1]} columns; they must match."
        )
    if np.isnan(r).any():
        raise ValueError(
            "returns panel must not contain NaN values; "
            "align and fill or drop missing data upstream."
        )
    if r.shape[0] < 2:
        raise ValueError(
            f"returns panel must have at least 2 observation rows; "
            f"got {r.shape[0]}."
        )
    return w, r


def _portfolio_returns(weights: np.ndarray, returns_matrix: np.ndarray) -> np.ndarray:
    """Compute weighted portfolio returns from a panel.

    Parameters
    ----------
    weights:
        Shape (N,) array of portfolio weights.
    returns_matrix:
        Shape (T, N) returns panel.

    Returns
    -------
    numpy.ndarray
        Shape (T,) portfolio return series.
    """
    result: np.ndarray = returns_matrix @ weights
    return result


def _cornish_fisher_z(z_normal: float, skew: float, ex_kurtosis: float) -> float:
    """Apply the Cornish-Fisher expansion to a normal z-quantile.

    Returns the modified quantile z_CF that accounts for distributional
    skewness and excess kurtosis (Zangari 1996).  When skew = 0 and
    ex_kurtosis = 0 the expansion collapses to z_normal exactly.

    Parameters
    ----------
    z_normal:
        Normal z-quantile (negative for the left tail, e.g. -1.645 at 5%).
    skew:
        Third standardised central moment (Fisher skewness) of the distribution.
    ex_kurtosis:
        Fourth standardised central moment minus 3 (excess kurtosis / kurtosis
        in the Fisher sense).

    Returns
    -------
    float
        Cornish-Fisher adjusted z-quantile.
    """
    z = z_normal
    g1 = skew
    g2 = ex_kurtosis
    z_cf = (
        z
        + (z ** 2 - 1.0) * g1 / 6.0
        + (z ** 3 - 3.0 * z) * g2 / 24.0
        - (2.0 * z ** 3 - 5.0 * z) * g1 ** 2 / 36.0
    )
    return float(z_cf)


def _sqrt_time_scale(var_1d: float, horizon: int) -> float:
    """Scale a 1-day VaR to a multi-day VaR via sqrt-time rule.

    Parameters
    ----------
    var_1d:
        One-day VaR as a positive loss fraction.
    horizon:
        Target horizon in days.  If 1 the input is returned unchanged.

    Returns
    -------
    float
        Horizon-scaled VaR.
    """
    if horizon == 1:
        return var_1d
    return var_1d * float(np.sqrt(horizon))


# ---------------------------------------------------------------------------
# Parametric VaR
# ---------------------------------------------------------------------------


@overload
def parametric_var(
    returns: pd.Series | np.ndarray,
    *,
    config: VaRConfig | None = ...,
    cornish_fisher: bool = ...,
) -> VaRResult: ...


@overload
def parametric_var(
    returns: None,
    *,
    weights: np.ndarray,
    cov: np.ndarray,
    config: VaRConfig | None = ...,
    cornish_fisher: bool = ...,
) -> VaRResult: ...


def parametric_var(  # type: ignore[misc]
    returns: pd.Series | np.ndarray | None = None,
    *,
    weights: np.ndarray | None = None,
    cov: np.ndarray | None = None,
    config: VaRConfig | None = None,
    cornish_fisher: bool = False,
) -> VaRResult:
    """Parametric (variance-covariance) Value-at-Risk.

    Supports two calling modes:

    **Mode A -- single return series:**
        Pass a 1-D ``returns`` array.  The standard deviation is estimated from
        the sample.  Skewness and excess kurtosis are used when
        ``cornish_fisher=True``.

    **Mode B -- portfolio weights + covariance:**
        Pass ``returns=None`` together with ``weights`` (shape N) and ``cov``
        (shape N x N).  Portfolio variance is computed as w' @ cov @ w.
        Cornish-Fisher is unavailable in this mode (requires higher moments
        not captured by a covariance matrix alone); ``cornish_fisher=True``
        raises ``ValueError`` in this mode.

    Sign convention: VaR is returned as a **positive** loss fraction.

    The ``sqrt(horizon)`` scaling rule rests on the iid return assumption; see
    the module docstring for the caveat.

    Parameters
    ----------
    returns:
        1-D return series (Mode A) or ``None`` (Mode B).
    weights:
        Portfolio weights, shape (N,).  Required in Mode B, ignored in Mode A.
    cov:
        Asset covariance matrix, shape (N, N).  Required in Mode B, ignored in
        Mode A.
    config:
        :class:`VaRConfig` controlling confidence, horizon, etc.  Defaults to
        ``VaRConfig()`` (95% confidence, 1-day horizon).
    cornish_fisher:
        If ``True``, apply the Cornish-Fisher expansion (Mode A only).

    Returns
    -------
    VaRResult
        ``method="parametric"`` or ``"parametric_cornish_fisher"``.

    Raises
    ------
    ValueError
        On invalid inputs or incompatible mode/option combination.
    """
    cfg = config if config is not None else VaRConfig()

    if returns is not None:
        # Mode A: single series.
        arr = _validate_returns_1d(returns, "returns")
        port_std = float(np.std(arr, ddof=1))
        if cornish_fisher:
            port_skew = float(stats.skew(arr))
            port_ex_kurt = float(stats.kurtosis(arr, fisher=True))
        else:
            port_skew = 0.0
            port_ex_kurt = 0.0
    else:
        # Mode B: weights + covariance.
        if weights is None or cov is None:
            raise ValueError(
                "When returns=None, both weights and cov must be provided."
            )
        if cornish_fisher:
            raise ValueError(
                "cornish_fisher=True is not supported in weights+cov mode; "
                "higher moments are not available from a covariance matrix."
            )
        w = np.asarray(weights, dtype=float).ravel()
        c = np.asarray(cov, dtype=float)
        if c.ndim != 2 or c.shape[0] != c.shape[1]:
            raise ValueError(
                f"cov must be a square 2-D matrix; got shape {c.shape}."
            )
        if c.shape[0] != w.shape[0]:
            raise ValueError(
                f"weights has {w.shape[0]} elements but cov is {c.shape[0]}x{c.shape[1]}."
            )
        port_variance = float(w @ c @ w)
        if port_variance < 0.0:
            raise ValueError(
                f"Portfolio variance w'Cw = {port_variance:.6g} < 0; "
                "cov must be positive semidefinite."
            )
        port_std = float(np.sqrt(max(port_variance, 0.0)))
        port_skew = 0.0
        port_ex_kurt = 0.0

    alpha = cfg.alpha
    z_normal = float(stats.norm.ppf(alpha))   # negative (left-tail quantile)

    if cornish_fisher and (port_skew != 0.0 or port_ex_kurt != 0.0):
        z_used = _cornish_fisher_z(z_normal, port_skew, port_ex_kurt)
        method = "parametric_cornish_fisher"
    else:
        z_used = z_normal
        method = "parametric" if not cornish_fisher else "parametric_cornish_fisher"

    # VaR_1d = -z_used * sigma  (positive because z_used < 0 for left tail).
    var_1d = -z_used * port_std
    var_h = _sqrt_time_scale(var_1d, cfg.horizon)

    return VaRResult(
        var=var_h,
        method=method,
        confidence=cfg.confidence,
        horizon=cfg.horizon,
        alpha=alpha,
    )


# ---------------------------------------------------------------------------
# Historical VaR
# ---------------------------------------------------------------------------


def historical_var(
    returns: pd.Series | np.ndarray | None = None,
    *,
    weights: np.ndarray | None = None,
    returns_panel: pd.DataFrame | None = None,
    config: VaRConfig | None = None,
) -> VaRResult:
    """Historical simulation Value-at-Risk.

    Computes the empirical alpha-quantile of realized returns and negates it to
    produce a positive loss number.  Supports both a single pre-computed return
    series and a portfolio-level computation from weights + returns panel.

    For horizons > 1 the 1-day historical VaR is scaled by sqrt(horizon).  This
    is a conservative approximation; true multi-day historical VaR would require
    overlapping or block-resampled windows.

    Sign convention: VaR is returned as a **positive** loss fraction.

    Parameters
    ----------
    returns:
        1-D return series.  Use this when you have already computed portfolio
        returns (or are working at the single-asset level).  Mutually exclusive
        with ``weights`` / ``returns_panel``.
    weights:
        Portfolio weights, shape (N,).  Must be supplied together with
        ``returns_panel``.
    returns_panel:
        Returns DataFrame, shape (T, N).  Must be NaN-free.  Must be supplied
        together with ``weights``.
    config:
        :class:`VaRConfig` controlling confidence level, horizon, etc.

    Returns
    -------
    VaRResult
        ``method="historical"``.

    Raises
    ------
    ValueError
        On conflicting or missing inputs.
    """
    cfg = config if config is not None else VaRConfig()

    if returns is not None:
        if weights is not None or returns_panel is not None:
            raise ValueError(
                "Provide either returns (1-D series) OR weights+returns_panel, not both."
            )
        arr = _validate_returns_1d(returns, "returns")
    else:
        if weights is None or returns_panel is None:
            raise ValueError(
                "When returns=None, both weights and returns_panel must be provided."
            )
        w, r_mat = _validate_weights_panel(weights, returns_panel)
        arr = _portfolio_returns(w, r_mat)
        arr = arr[np.isfinite(arr)]
        if arr.size == 0:
            raise ValueError(
                "Portfolio returns are all non-finite after applying weights."
            )

    var_1d = float(-np.quantile(arr, cfg.alpha))
    var_h = _sqrt_time_scale(var_1d, cfg.horizon)

    return VaRResult(
        var=var_h,
        method="historical",
        confidence=cfg.confidence,
        horizon=cfg.horizon,
        alpha=cfg.alpha,
    )


# ---------------------------------------------------------------------------
# Monte Carlo VaR
# ---------------------------------------------------------------------------


def monte_carlo_var(
    returns: pd.Series | np.ndarray | None = None,
    *,
    weights: np.ndarray | None = None,
    returns_panel: pd.DataFrame | None = None,
    config: VaRConfig | None = None,
    distribution: str = "student_t",
) -> VaRResult:
    """Monte Carlo Value-at-Risk via parametric distributional simulation.

    Fits a statistical distribution to the return series (or portfolio returns),
    draws ``n_simulations`` samples, and computes the empirical alpha-quantile.

    Supported distributions
    -----------------------
    * ``"student_t"`` (default): Fits a Student-t distribution (location, scale,
      degrees of freedom) via maximum-likelihood estimation using
      ``scipy.stats.t.fit``.  Degrees of freedom are constrained to >= 2.01 so
      that variance is finite.  The fitted t captures fat tails far better than
      the normal distribution.
    * ``"normal"``: Fits a Normal distribution (mu, sigma) and draws from it.
      Equivalent to a parametric normal VaR with MC noise.

    For horizons > 1 the 1-day MC VaR is scaled by sqrt(horizon).  The iid
    assumption applies; see the module docstring.

    Sign convention: VaR is returned as a **positive** loss fraction.

    Parameters
    ----------
    returns:
        1-D return series, OR ``None`` when using ``weights`` / ``returns_panel``.
    weights:
        Portfolio weights, shape (N,).
    returns_panel:
        Returns DataFrame, shape (T, N), NaN-free.
    config:
        :class:`VaRConfig` controlling simulation count, seed, horizon, etc.
    distribution:
        One of ``"student_t"`` or ``"normal"``.

    Returns
    -------
    VaRResult
        ``method="monte_carlo"``.

    Raises
    ------
    ValueError
        On invalid distribution name or conflicting inputs.
    """
    cfg = config if config is not None else VaRConfig()

    if distribution not in ("student_t", "normal"):
        raise ValueError(
            f"distribution must be 'student_t' or 'normal'; got {distribution!r}"
        )

    if returns is not None:
        if weights is not None or returns_panel is not None:
            raise ValueError(
                "Provide either returns (1-D series) OR weights+returns_panel, not both."
            )
        arr = _validate_returns_1d(returns, "returns")
    else:
        if weights is None or returns_panel is None:
            raise ValueError(
                "When returns=None, both weights and returns_panel must be provided."
            )
        w, r_mat = _validate_weights_panel(weights, returns_panel)
        arr = _portfolio_returns(w, r_mat)
        arr = arr[np.isfinite(arr)]
        if arr.size == 0:
            raise ValueError(
                "Portfolio returns are all non-finite after applying weights."
            )

    rng = np.random.default_rng(cfg.rng_seed)

    if distribution == "student_t":
        # MLE fit of Student-t: returns (df, loc, scale) from scipy convention.
        df_fit, loc_fit, scale_fit = stats.t.fit(arr)
        # Enforce df >= 2.01 so that variance is finite.
        df_fit = max(float(df_fit), 2.01)
        # Draw samples using numpy for reproducibility with the provided Generator.
        t_samples = rng.standard_t(df=df_fit, size=cfg.n_simulations)
        simulated = loc_fit + scale_fit * t_samples
    else:
        mu = float(np.mean(arr))
        sigma = float(np.std(arr, ddof=1))
        simulated = rng.normal(loc=mu, scale=sigma, size=cfg.n_simulations)

    var_1d = float(-np.quantile(simulated, cfg.alpha))
    var_h = _sqrt_time_scale(var_1d, cfg.horizon)

    return VaRResult(
        var=var_h,
        method="monte_carlo",
        confidence=cfg.confidence,
        horizon=cfg.horizon,
        alpha=cfg.alpha,
    )


# ---------------------------------------------------------------------------
# VaR Backtesting
# ---------------------------------------------------------------------------


def kupiec_test(
    exceptions: np.ndarray | pd.Series,
    *,
    n_observations: int | None = None,
    alpha: float = 0.05,
    significance: float = 0.05,
) -> BacktestResult:
    """Kupiec (1995) proportion-of-failures likelihood-ratio test.

    Tests whether the empirical exception rate equals the nominal tail
    probability alpha.  The null hypothesis is H0: p = alpha, where p is the
    true probability of a VaR breach on any given day.

    Under H0 the LR statistic is chi-squared distributed with 1 degree of
    freedom:

        LR_POF = -2 * [ log(alpha^x * (1-alpha)^(n-x))
                      - log((x/n)^x * (1 - x/n)^(n-x)) ]

    where x = number of exceptions, n = total observations.

    An exception on day t is defined as: ``realized_return_t < -VaR_t``
    (i.e., the loss exceeded the VaR forecast), which maps to a 1 in the
    boolean exceptions series and 0 otherwise.  Alternatively, pass in
    pre-computed boolean or integer (0/1) arrays.

    Parameters
    ----------
    exceptions:
        Boolean or integer (0/1) 1-D array where 1 indicates a VaR breach on
        that day.  Can also be a pre-computed array of exception indicators.
    n_observations:
        Total number of observations.  Defaults to ``len(exceptions)``; pass
        a larger value if you are testing a subset.
    alpha:
        Nominal VaR tail probability (1 - confidence).  Default 0.05.
    significance:
        Significance level for the pass/fail decision.  Default 0.05.

    Returns
    -------
    BacktestResult
        ``test_name="kupiec_pof"``.

    Raises
    ------
    ValueError
        On invalid inputs.
    """
    if not (0.0 < alpha < 1.0):
        raise ValueError(f"alpha must be in (0, 1), got {alpha!r}")
    if not (0.0 < significance < 1.0):
        raise ValueError(f"significance must be in (0, 1), got {significance!r}")

    exc_arr = np.asarray(exceptions, dtype=float).ravel()
    x = int(np.sum(exc_arr > 0.5))   # number of exceptions

    n = n_observations if n_observations is not None else len(exc_arr)
    if n < 1:
        raise ValueError(f"n_observations must be >= 1, got {n}")
    if x > n:
        raise ValueError(
            f"Number of exceptions ({x}) exceeds n_observations ({n})."
        )

    expected = float(alpha) * float(n)

    # LR_POF: special cases to avoid log(0).
    if x == 0:
        # MLE log-likelihood has p_hat = 0; log(0^0) = 0 by convention.
        lr = -2.0 * (float(n) * np.log1p(-alpha))
    elif x == n:
        lr = -2.0 * (float(n) * np.log(alpha))
    else:
        p_hat = float(x) / float(n)
        ll_null = float(x) * np.log(alpha) + float(n - x) * np.log1p(-alpha)
        ll_alt = float(x) * np.log(p_hat) + float(n - x) * np.log1p(-p_hat)
        lr = -2.0 * (ll_null - ll_alt)

    lr = max(lr, 0.0)   # guard against tiny negative float residue
    p_value = float(stats.chi2.sf(lr, df=1))

    return BacktestResult(
        test_name="kupiec_pof",
        lr_statistic=lr,
        p_value=p_value,
        degrees_of_freedom=1,
        n_exceptions=x,
        expected_exceptions=expected,
        n_observations=n,
        passed=p_value >= significance,
        significance=significance,
    )


def christoffersen_test(
    exceptions: np.ndarray | pd.Series,
    *,
    alpha: float = 0.05,
    significance: float = 0.05,
) -> tuple[BacktestResult, BacktestResult]:
    """Christoffersen (1998) independence and conditional-coverage LR tests.

    Decomposes the VaR backtest into two orthogonal components:

    **Independence test (IND)**
        Tests H0: VaR exceptions are independent of one another -- i.e.,
        today's exception probability does not depend on whether there was an
        exception yesterday.  Clustered exceptions (e.g. during a volatility
        regime) violate this hypothesis.  The LR statistic has a chi-squared(1)
        reference distribution.

        LR_IND = -2 * [log L(pi) - log L(pi01, pi11)]

        where:
          pi   = unconditional exception probability (x/n)
          pi01 = P(exception | no exception yesterday)
          pi11 = P(exception | exception yesterday)
          n_ij = transition counts (i=0 no-exc, i=1 exc; j=next-period exc state)

    **Conditional coverage test (CC)**
        Joint test of both correct coverage (Kupiec) and independence.  The LR
        statistic is the sum of LR_POF and LR_IND and has a chi-squared(2)
        reference distribution.

    An exception indicator of 1 means the return exceeded the VaR in absolute
    terms (loss was larger than VaR) on that period.

    Parameters
    ----------
    exceptions:
        Boolean or integer (0/1) 1-D array of exception indicators, ordered
        chronologically.  Must have at least 2 observations.
    alpha:
        Nominal VaR tail probability.  Default 0.05.
    significance:
        Significance level for pass/fail decisions.  Default 0.05.

    Returns
    -------
    tuple[BacktestResult, BacktestResult]
        ``(independence_result, conditional_coverage_result)``.

    Raises
    ------
    ValueError
        On invalid inputs or fewer than 2 observations.
    """
    if not (0.0 < alpha < 1.0):
        raise ValueError(f"alpha must be in (0, 1), got {alpha!r}")
    if not (0.0 < significance < 1.0):
        raise ValueError(f"significance must be in (0, 1), got {significance!r}")

    exc_arr = np.asarray(exceptions, dtype=int).ravel()
    n = len(exc_arr)
    if n < 2:
        raise ValueError(
            f"christoffersen_test requires at least 2 observations, got {n}."
        )

    x = int(np.sum(exc_arr))
    expected = float(alpha) * float(n)

    # Transition counts: n_ij where i = state(t-1), j = state(t).
    i_prev = exc_arr[:-1]
    i_curr = exc_arr[1:]
    n00 = int(np.sum((i_prev == 0) & (i_curr == 0)))
    n01 = int(np.sum((i_prev == 0) & (i_curr == 1)))
    n10 = int(np.sum((i_prev == 1) & (i_curr == 0)))
    n11 = int(np.sum((i_prev == 1) & (i_curr == 1)))

    # Conditional transition probabilities (MLE).
    n0_row = n00 + n01    # total rows starting from state 0
    n1_row = n10 + n11    # total rows starting from state 1

    # Unconditional probability under independence.
    pi = float(n01 + n11) / float(n - 1) if (n - 1) > 0 else 0.0

    # Conditional probabilities (bounded away from 0 and 1 for log stability).
    _eps = 1e-10
    pi01 = float(n01) / float(n0_row) if n0_row > 0 else pi
    pi11 = float(n11) / float(n1_row) if n1_row > 0 else pi

    # Independence LR statistic.
    # Under H0 (independence): log L = (n01+n11)*log(pi) + (n00+n10)*log(1-pi)
    # Under H1 (Markov):       log L = n01*log(pi01) + n00*log(1-pi01)
    #                                + n11*log(pi11) + n10*log(1-pi11)
    def _safe_log(x_val: float) -> float:
        return float(np.log(max(x_val, _eps)))

    ll_h0 = (
        float(n01 + n11) * _safe_log(pi)
        + float(n00 + n10) * _safe_log(1.0 - pi)
    )
    ll_h1 = (
        float(n01) * _safe_log(pi01)
        + float(n00) * _safe_log(1.0 - pi01)
        + float(n11) * _safe_log(pi11)
        + float(n10) * _safe_log(1.0 - pi11)
    )
    lr_ind = max(-2.0 * (ll_h0 - ll_h1), 0.0)

    p_value_ind = float(stats.chi2.sf(lr_ind, df=1))
    ind_result = BacktestResult(
        test_name="christoffersen_independence",
        lr_statistic=lr_ind,
        p_value=p_value_ind,
        degrees_of_freedom=1,
        n_exceptions=x,
        expected_exceptions=expected,
        n_observations=n,
        passed=p_value_ind >= significance,
        significance=significance,
    )

    # Conditional coverage: Kupiec POF + independence (chi-squared 2 dof).
    kupiec_result = kupiec_test(
        exc_arr,
        n_observations=n,
        alpha=alpha,
        significance=significance,
    )
    lr_cc = max(kupiec_result.lr_statistic + lr_ind, 0.0)
    p_value_cc = float(stats.chi2.sf(lr_cc, df=2))
    cc_result = BacktestResult(
        test_name="christoffersen_cc",
        lr_statistic=lr_cc,
        p_value=p_value_cc,
        degrees_of_freedom=2,
        n_exceptions=x,
        expected_exceptions=expected,
        n_observations=n,
        passed=p_value_cc >= significance,
        significance=significance,
    )

    return ind_result, cc_result
