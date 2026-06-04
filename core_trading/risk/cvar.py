"""CVaR / Expected Shortfall estimators and diagnostics (Phase 7.4).

Expected Shortfall (ES), also called Conditional Value-at-Risk (CVaR), is the
average loss over the worst (1 - alpha) fraction of outcomes.  It is the
canonical coherent risk measure that repairs the subadditivity failure of VaR:
for any two portfolios A and B,

    ES(A + B) <= ES(A) + ES(B)

while there exist distributions for which VaR(A + B) > VaR(A) + VaR(B).

Sign convention
---------------
All functions return *positive* loss magnitudes.  A portfolio that loses 2% in
its worst tail has ES = 0.02, not -0.02.  This is consistent with
:func:`core_trading.backtest.metrics.value_at_risk` and the ``var_alpha``
convention in :mod:`core_trading.risk.pairs_risk`.

Confidence level convention
----------------------------
``alpha`` is the CONFIDENCE level: alpha = 0.95 means 95% confidence, i.e.,
ES is the mean loss conditional on being in the worst 5% of outcomes.  The
complementary left-tail probability is ``1 - alpha``.

Horizon scaling
---------------
Multi-day horizons are handled by the square-root-of-time rule (iid assumption)
so that the 10-day figure equals the 1-day figure times sqrt(10).  This is
consistent with Basel / internal model conventions and with the VaR module.
Callers may override by passing ``horizon=1`` and scaling externally.

Module overview
---------------
1. ``ESResult``              -- frozen DTO for a single ES computation.
2. ``ESConfig``              -- frozen DTO capturing estimation parameters.
3. ``historical_es``         -- empirical tail mean (Acerbi-Tasche definition).
4. ``parametric_es``         -- analytic closed forms for Normal and Student-t.
5. ``monte_carlo_es``        -- simulation from fitted distributions.
6. ``portfolio_es``          -- weights + returns panel -> all three estimators.
7. ``ru_linearization``      -- Rockafellar-Uryasev (2000) objective pieces for
                                CVaR-minimising optimisers (estimation/reporting
                                side only; does not invoke a solver).
8. ``acerbi_szekely_test``   -- Z2 test statistic and simulation p-value
                                (Acerbi-Szekely 2014).

Relationship to Phase 6 robust_opt
-----------------------------------
:mod:`core_trading.portfolio.robust_opt` contains a Rockafellar-Uryasev LP
that *minimises* CVaR over portfolio weights using cvxpy.  This module is the
*measurement and reporting* complement: it provides estimators, diagnostics,
and the linearization pieces as numpy arrays.  The ``ru_linearization``
function here returns the discretized objective components so a downstream
optimiser can build its own constraint without importing cvxpy.  See
:func:`ru_linearization` for details.

Mathematical references
-----------------------
Rockafellar, R.T. & Uryasev, S. (2000). "Optimization of Conditional
    Value-at-Risk." Journal of Risk, 2(3), 21-41.

Acerbi, C. & Tasche, D. (2002). "On the Coherence of Expected Shortfall."
    Journal of Banking & Finance, 26(7), 1487-1503.

Acerbi, C. & Szekely, B. (2014). "Back-testing Expected Shortfall."
    Risk Magazine, November 2014, 76-81.

McNeil, A.J., Frey, R. & Embrechts, P. (2015). "Quantitative Risk Management:
    Concepts, Techniques and Tools" (revised ed.). Princeton University Press.
    Chapter 2, equation (2.27) for the Student-t ES closed form.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import scipy.stats as stats

__all__ = [
    "ESConfig",
    "ESResult",
    "PortfolioESResult",
    "RUPieces",
    "AcerbiSzekelyResult",
    "historical_es",
    "parametric_es",
    "monte_carlo_es",
    "portfolio_es",
    "ru_linearization",
    "acerbi_szekely_test",
]

# ---------------------------------------------------------------------------
# Data-transfer objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ESConfig:
    """Parameters controlling ES estimation.

    Attributes
    ----------
    alpha:
        Confidence level in (0, 1).  Typical values: 0.95, 0.99.
        ES_alpha is the mean loss in the worst (1 - alpha) fraction.
    horizon:
        Holding period in bars (days).  The 1-day ES is scaled by
        sqrt(horizon) under the iid square-root-of-time rule.  Default 1.
    dist:
        Parametric distribution family: ``"normal"`` or ``"student_t"``.
        Relevant only for :func:`parametric_es` and :func:`monte_carlo_es`.
    df:
        Degrees of freedom for Student-t.  Must be > 2 so that variance
        exists (required for the closed-form ES).  Ignored when
        ``dist="normal"``.
    n_simulations:
        Number of Monte Carlo draws per :func:`monte_carlo_es` call.
    seed:
        Seed for the numpy Generator used in Monte Carlo simulation.
        Pass ``None`` for non-reproducible draws.
    """

    alpha: float = 0.95
    horizon: int = 1
    dist: str = "normal"
    df: float = 5.0
    n_simulations: int = 100_000
    seed: int | None = 0

    def __post_init__(self) -> None:
        """Validate parameter consistency."""
        if not 0.0 < self.alpha < 1.0:
            raise ValueError(f"alpha must be in (0, 1); got {self.alpha}")
        if self.horizon < 1:
            raise ValueError(
                f"horizon must be >= 1; got {self.horizon}"
            )
        if self.dist not in ("normal", "student_t"):
            raise ValueError(
                f"dist must be 'normal' or 'student_t'; got {self.dist!r}"
            )
        if self.dist == "student_t" and self.df <= 2.0:
            raise ValueError(
                f"df must be > 2 for the Student-t ES closed form; got {self.df}"
            )
        if self.n_simulations < 1:
            raise ValueError(
                f"n_simulations must be >= 1; got {self.n_simulations}"
            )


@dataclass(frozen=True, slots=True)
class ESResult:
    """Result of a single-series ES computation.

    Attributes
    ----------
    es:
        Expected Shortfall (positive loss) at the requested horizon.
        Equals the 1-day ES scaled by sqrt(horizon).
    var:
        Value-at-Risk at the same confidence level and horizon (positive
        loss).  ES >= VaR always holds by construction.
    alpha:
        Confidence level used.
    horizon:
        Horizon in bars.
    method:
        Estimator: ``"historical"``, ``"parametric_normal"``,
        ``"parametric_student_t"``, or ``"monte_carlo"``.
    """

    es: float
    var: float
    alpha: float
    horizon: int
    method: str


@dataclass(frozen=True, slots=True)
class PortfolioESResult:
    """ES computed for a portfolio from a returns panel and weight vector.

    Attributes
    ----------
    historical:
        ES from the historical estimator.
    parametric:
        ES from the parametric (Normal or Student-t) estimator.
    monte_carlo:
        ES from Monte Carlo simulation.
    portfolio_returns:
        The weighted portfolio return series used for historical ES.
    alpha:
        Confidence level used.
    horizon:
        Horizon in bars.
    """

    historical: ESResult = field(compare=False)
    parametric: ESResult = field(compare=False)
    monte_carlo: ESResult = field(compare=False)
    portfolio_returns: pd.Series = field(compare=False)
    alpha: float
    horizon: int


@dataclass(frozen=True, slots=True)
class RUPieces:
    """Rockafellar-Uryasev (2000) linearization pieces.

    Holds the numpy arrays needed to construct the CVaR auxiliary-variable LP
    for a *fixed* weight vector and a given scenario set.  These pieces are the
    estimation/reporting output of this module; the caller is responsible for
    passing them to a solver (e.g. via
    :func:`core_trading.portfolio.robust_opt.cvar_weights` for the full
    optimisation).

    Given S loss scenarios ``losses[s] = -r_s' w``, the Rockafellar-Uryasev
    program is::

        CVaR_alpha(w) = min_z  z + (1 / ((1-alpha) * S)) * sum_s u_s
        subject to  u_s >= losses_s - z,  u_s >= 0,  for all s.

    At the optimal z* = VaR_alpha, u_s* = max(losses_s - VaR_alpha, 0).

    Attributes
    ----------
    losses:
        1-D array of portfolio losses (positive = loss), shape (S,).
        losses[s] = -r_s' w for the provided weights.
    z_star:
        Optimal auxiliary variable z* = VaR_alpha (positive loss).
    u_star:
        Optimal exceedance variables u_s* = max(losses_s - z*, 0), shape (S,).
    cvar:
        The resulting CVaR = z* + mean(u*) / (1 - alpha).
    alpha:
        Confidence level used.
    """

    losses: np.ndarray = field(compare=False)
    z_star: float
    u_star: np.ndarray = field(compare=False)
    cvar: float
    alpha: float


@dataclass(frozen=True, slots=True)
class AcerbiSzekelyResult:
    """Result of the Acerbi-Szekely (2014) ES backtest.

    Attributes
    ----------
    z2:
        The Z2 test statistic (equation 5 in the paper).  Under a
        correctly-specified model Z2 converges to 0 from below; a large
        negative value indicates the model understates tail risk.
    p_value:
        Simulation-based p-value: proportion of simulated Z2 values (under
        the null of a correctly-specified model) that are <= the observed Z2.
        Small p-value (<= 0.05) rejects the null, i.e., the model
        understates risk.
    n_exceedances:
        Number of VaR exceedances observed in the test window.
    alpha:
        Confidence level used.
    """

    z2: float
    p_value: float
    n_exceedances: int
    alpha: float


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_returns(arr: np.ndarray, name: str = "returns") -> np.ndarray:
    """Validate a 1-D float returns array.

    Parameters
    ----------
    arr:
        Input array (will be converted to float64 1-D).
    name:
        Label used in error messages.

    Returns
    -------
    numpy.ndarray
        1-D float64 array with at least 2 elements.

    Raises
    ------
    ValueError
        If the array contains NaN/Inf, or has fewer than 2 elements.
    """
    out = np.asarray(arr, dtype=float).reshape(-1)
    if out.shape[0] < 2:
        raise ValueError(
            f"{name} must contain at least 2 observations; got {out.shape[0]}."
        )
    if not np.isfinite(out).all():
        raise ValueError(f"{name} contains NaN or infinite values.")
    return out


def _horizon_scale(value: float, horizon: int) -> float:
    """Scale a 1-day risk figure to a multi-day horizon via sqrt(horizon)."""
    return value * float(np.sqrt(float(horizon)))


# ---------------------------------------------------------------------------
# Historical ES (Acerbi-Tasche definition)
# ---------------------------------------------------------------------------


def historical_es(
    returns: np.ndarray | pd.Series,
    config: ESConfig | None = None,
) -> ESResult:
    """Empirical Expected Shortfall via the Acerbi-Tasche (2002) tail mean.

    Implements the Acerbi-Tasche (2002) empirical definition: sort the n
    losses L_(1) <= L_(2) <= ... <= L_(n) in ascending order (L_i = -r_i).
    The worst (1-alpha) fraction of losses sits at the HIGH end of this
    sorted array.  With tail_mass = n * (1 - alpha) and j = floor(tail_mass):

        ES = [ L_(n-j+1) + ... + L_(n) + frac * L_(n-j) ] / tail_mass

    where frac = tail_mass - j is the weight of the boundary scenario.

    This correctly handles non-integer cutoffs: when tail_mass is not an
    integer, the boundary scenario at the alpha quantile is included with
    weight frac in (0, 1), satisfying the integral definition exactly.
    Special cases:
    - j >= n (alpha very small): all observations are in the tail.
    - j == 0: only the fractional boundary scenario contributes.

    Parameters
    ----------
    returns:
        1-D array of period returns (sign: positive = gain).
    config:
        :class:`ESConfig`; ``None`` uses the defaults.

    Returns
    -------
    ESResult
        ``method="historical"``.

    Raises
    ------
    ValueError
        On an invalid returns array (see :func:`_validate_returns`).
    """
    cfg = config if config is not None else ESConfig()
    arr = _validate_returns(
        returns if isinstance(returns, np.ndarray) else np.asarray(returns, dtype=float),
        "returns",
    )
    losses = np.sort(-arr)  # ascending losses: L_(1) <= ... <= L_(n)
    n_int = losses.shape[0]
    n = float(n_int)
    tail_mass = n * (1.0 - cfg.alpha)
    j = int(np.floor(tail_mass))  # integer part: j strictly-worst observations

    if j == 0:
        # tail_mass < 1: no full-tail observations; ES is the worst single
        # observation (the boundary scenario, weight frac=tail_mass, divided
        # by tail_mass cancels to 1).
        es_1d = float(losses[n_int - 1])
    else:
        # The j worst observations are at indices [n_int - j, ..., n_int - 1]
        tail_sum = float(losses[n_int - j:].sum())
        # Fractional weight for the boundary scenario at index n_int - j - 1
        frac = tail_mass - float(j)
        boundary = float(losses[n_int - j - 1])
        es_1d = (tail_sum + frac * boundary) / tail_mass

    # VaR: the alpha quantile of the LOSS distribution (positive loss)
    var_1d = float(np.quantile(losses, cfg.alpha))

    scale = _horizon_scale(1.0, cfg.horizon)
    return ESResult(
        es=es_1d * scale,
        var=var_1d * scale,
        alpha=cfg.alpha,
        horizon=cfg.horizon,
        method="historical",
    )


# ---------------------------------------------------------------------------
# Parametric ES: Normal and Student-t closed forms
# ---------------------------------------------------------------------------


def parametric_es(
    returns: np.ndarray | pd.Series,
    config: ESConfig | None = None,
) -> ESResult:
    """Analytic ES for Normal or Student-t fitted to the returns sample.

    Normal ES (closed form)
    ~~~~~~~~~~~~~~~~~~~~~~~
    Given sample mean mu and standard deviation sigma (ddof=1),
    ES_alpha = mu + sigma * phi(z_alpha) / (1 - alpha)
    where z_alpha = Phi^{-1}(alpha) is the standard-normal quantile and phi
    is the standard-normal PDF.  Equivalently (positive loss convention),
    ES = -mu + sigma * phi(z_alpha) / (1 - alpha).

    Student-t ES (McNeil-Frey-Embrechts 2015, eq. 2.27)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    For X ~ t_nu(mu, sigma^2) with nu > 2::

        ES_alpha = -mu + (sigma / (1 - alpha))
                   * [ t_{nu}(t_{nu}^{-1}(alpha)) * (nu + (t_{nu}^{-1}(alpha))^2)
                       / (nu - 1) ]

    where t_{nu} is the standard-t PDF and t_{nu}^{-1}(alpha) is its quantile.

    Parameters
    ----------
    returns:
        1-D array of period returns.  Mean and std are estimated from this
        sample; the distribution family is controlled by ``config.dist``.
    config:
        :class:`ESConfig`; ``None`` uses defaults.  ``config.dist``
        selects ``"normal"`` or ``"student_t"``; for Student-t
        ``config.df`` must be > 2.

    Returns
    -------
    ESResult
        ``method="parametric_normal"`` or ``"parametric_student_t"``.

    Raises
    ------
    ValueError
        On an invalid returns array, unsupported distribution, or df <= 2.
    """
    cfg = config if config is not None else ESConfig()
    arr = _validate_returns(
        returns if isinstance(returns, np.ndarray) else np.asarray(returns, dtype=float),
        "returns",
    )
    mu = float(arr.mean())
    sigma = float(arr.std(ddof=1))

    if cfg.dist == "normal":
        z_alpha = float(stats.norm.ppf(cfg.alpha))
        phi_z = float(stats.norm.pdf(z_alpha))
        # ES of a N(mu, sigma^2) loss distribution (positive-loss convention)
        es_1d = -mu + sigma * phi_z / (1.0 - cfg.alpha)
        var_1d = -mu + sigma * z_alpha
        method = "parametric_normal"
    else:
        # Student-t: McNeil-Frey-Embrechts (2015) eq. (2.27)
        nu = cfg.df
        t_alpha = float(stats.t.ppf(cfg.alpha, df=nu))
        t_pdf_at_q = float(stats.t.pdf(t_alpha, df=nu))
        # Tail integral factor: t_pdf * (nu + q^2) / (nu - 1)
        tail_factor = t_pdf_at_q * (nu + t_alpha**2) / (nu - 1.0)
        es_1d = -mu + sigma * tail_factor / (1.0 - cfg.alpha)
        var_1d = -mu + sigma * t_alpha
        method = "parametric_student_t"

    scale = _horizon_scale(1.0, cfg.horizon)
    return ESResult(
        es=max(es_1d, var_1d) * scale,  # ES >= VaR by definition
        var=var_1d * scale,
        alpha=cfg.alpha,
        horizon=cfg.horizon,
        method=method,
    )


# ---------------------------------------------------------------------------
# Monte Carlo ES
# ---------------------------------------------------------------------------


def monte_carlo_es(
    returns: np.ndarray | pd.Series,
    config: ESConfig | None = None,
) -> ESResult:
    """Monte Carlo ES from the fitted distribution.

    Fits the distribution parameters to ``returns``, draws
    ``config.n_simulations`` samples from the fitted model, and applies the
    historical estimator to the simulated sample.

    Normal: mu = sample mean, sigma = sample std (ddof=1).
    Student-t: mu = sample mean, sigma = sample std (ddof=1), df = config.df.

    Parameters
    ----------
    returns:
        1-D array of period returns.
    config:
        :class:`ESConfig`; ``None`` uses defaults.

    Returns
    -------
    ESResult
        ``method="monte_carlo"``.

    Raises
    ------
    ValueError
        On an invalid returns array.
    """
    cfg = config if config is not None else ESConfig()
    arr = _validate_returns(
        returns if isinstance(returns, np.ndarray) else np.asarray(returns, dtype=float),
        "returns",
    )
    mu = float(arr.mean())
    sigma = float(arr.std(ddof=1))
    rng = np.random.default_rng(cfg.seed)

    if cfg.dist == "normal":
        simulated = rng.normal(loc=mu, scale=sigma, size=cfg.n_simulations)
    else:
        # Scale a standard-t by sigma, shift by mu.
        std_t = rng.standard_t(df=cfg.df, size=cfg.n_simulations)
        simulated = mu + sigma * std_t

    # Reuse historical_es on the simulated sample (1-day, same alpha)
    mc_cfg = ESConfig(
        alpha=cfg.alpha,
        horizon=1,
        dist=cfg.dist,
        df=cfg.df,
        n_simulations=cfg.n_simulations,
        seed=cfg.seed,
    )
    inner = historical_es(simulated, mc_cfg)
    scale = _horizon_scale(1.0, cfg.horizon)
    return ESResult(
        es=inner.es * scale,
        var=inner.var * scale,
        alpha=cfg.alpha,
        horizon=cfg.horizon,
        method="monte_carlo",
    )


# ---------------------------------------------------------------------------
# Portfolio ES
# ---------------------------------------------------------------------------


def portfolio_es(
    weights: pd.Series | np.ndarray,
    returns: pd.DataFrame,
    config: ESConfig | None = None,
) -> PortfolioESResult:
    """Compute ES for a portfolio from asset weights and a returns panel.

    Contracts the asset-level returns panel down to a scalar portfolio return
    series via ``portfolio_returns = returns @ weights``, then applies all
    three estimators.

    Panel convention: ``returns`` is a DataFrame with assets as columns and
    bars as rows (same convention as :mod:`core_trading.portfolio.covariance`).

    Parameters
    ----------
    weights:
        Portfolio weights, aligned with ``returns.columns`` (same order).
        The weights need not sum to 1 (e.g. long-short books).
    returns:
        Returns panel: rows are bars, columns are asset symbols.  Must be
        NaN-free with at least 2 rows and 1 column.
    config:
        :class:`ESConfig`; ``None`` uses defaults.

    Returns
    -------
    PortfolioESResult

    Raises
    ------
    ValueError
        If ``returns`` contains NaN, has mismatched dimensions with
        ``weights``, or has fewer than 2 rows.
    """
    cfg = config if config is not None else ESConfig()
    w = np.asarray(weights, dtype=float).reshape(-1)
    ret_arr = returns.to_numpy(dtype=float)
    if ret_arr.ndim != 2:
        raise ValueError("returns must be a 2-D DataFrame.")
    n_obs, n_assets = ret_arr.shape
    if n_obs < 2:
        raise ValueError(
            f"returns must have at least 2 rows; got {n_obs}."
        )
    if w.shape[0] != n_assets:
        raise ValueError(
            f"weights length ({w.shape[0]}) does not match "
            f"returns column count ({n_assets})."
        )
    if not np.isfinite(ret_arr).all():
        raise ValueError("returns contains NaN or infinite values.")

    port_rets = ret_arr @ w
    port_series = pd.Series(
        port_rets,
        index=returns.index,
    )
    hist = historical_es(port_rets, cfg)
    para = parametric_es(port_rets, cfg)
    mc = monte_carlo_es(port_rets, cfg)
    return PortfolioESResult(
        historical=hist,
        parametric=para,
        monte_carlo=mc,
        portfolio_returns=port_series,
        alpha=cfg.alpha,
        horizon=cfg.horizon,
    )


# ---------------------------------------------------------------------------
# Rockafellar-Uryasev linearization helper
# ---------------------------------------------------------------------------


def ru_linearization(
    losses: np.ndarray,
    alpha: float = 0.95,
) -> RUPieces:
    """Return the Rockafellar-Uryasev (2000) linearization pieces.

    For a fixed scenario set of losses (already computed as L_s = -r_s' w for
    some weight vector w), this function evaluates the auxiliary variable z*
    (which equals VaR_alpha at the optimum) and the exceedance variables
    u_s* = max(L_s - z*, 0), allowing a downstream optimiser to construct the
    CVaR objective::

        CVaR_alpha = z* + (1 / ((1-alpha) * S)) * sum_s u_s*

    This is the *estimation side* of the Rockafellar-Uryasev approach.  The
    *optimisation side* (choosing w to minimise CVaR) is implemented in
    :mod:`core_trading.portfolio.robust_opt` via cvxpy; this module does not
    import cvxpy.  The returned ``RUPieces`` hold numpy arrays that a solver
    can reference directly when building its LP formulation.

    Parameters
    ----------
    losses:
        1-D array of portfolio losses (positive = loss), shape (S,).
        Typically ``losses = -(returns_matrix @ weights)``.
    alpha:
        Confidence level in (0, 1).

    Returns
    -------
    RUPieces

    Raises
    ------
    ValueError
        On an invalid losses array or alpha outside (0, 1).
    """
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1); got {alpha}")
    arr = np.asarray(losses, dtype=float).reshape(-1)
    if arr.shape[0] < 1:
        raise ValueError("losses must contain at least 1 element.")
    if not np.isfinite(arr).all():
        raise ValueError("losses contains NaN or infinite values.")

    # z* = VaR_alpha of the loss distribution
    z_star = float(np.quantile(arr, alpha))
    u_star = np.maximum(arr - z_star, 0.0)
    cvar = z_star + float(u_star.mean()) / (1.0 - alpha)
    return RUPieces(
        losses=arr.copy(),
        z_star=z_star,
        u_star=u_star,
        cvar=cvar,
        alpha=alpha,
    )


# ---------------------------------------------------------------------------
# Acerbi-Szekely (2014) ES backtest
# ---------------------------------------------------------------------------


def acerbi_szekely_test(
    returns: np.ndarray | pd.Series,
    es_forecasts: np.ndarray | pd.Series,
    alpha: float = 0.95,
    *,
    n_simulations: int = 10_000,
    seed: int | None = 0,
) -> AcerbiSzekelyResult:
    """Acerbi-Szekely (2014) Z2 test statistic with simulation p-value.

    Tests the null hypothesis that the ES model is correctly specified.  The
    Z2 statistic (Acerbi-Szekely 2014, equation 5) is::

        Z2 = (1 / (T * (1-alpha))) * sum_{t: r_t < -VaR_t} (r_t / ES_t) + 1

    where the sum is over all VaR exceedances (times when the realised return
    falls below minus the forecast VaR).  Under a correctly specified model
    Z2 has mean 0 (from above, converging as T -> inf); a strongly negative Z2
    indicates the model understates tail risk.

    The p-value is computed by simulation under the null: for each of
    ``n_simulations`` replications, standard-normal losses are drawn (same
    length as the test window), the corresponding ES forecast for a standard
    normal at level ``alpha`` is used, and Z2 is evaluated.  The p-value is
    the fraction of simulated Z2 values that are <= the observed Z2.

    Note: when there are zero VaR exceedances, Z2 = 1.0 (no evidence against
    the model); the p-value is reported as 1.0.

    Parameters
    ----------
    returns:
        1-D array of realised portfolio returns (positive = gain).
    es_forecasts:
        1-D array of forecast ES values (positive loss magnitude), aligned
        with ``returns``.  Length must equal ``len(returns)``.
    alpha:
        Confidence level in (0, 1).
    n_simulations:
        Number of simulation replications for the p-value.
    seed:
        RNG seed for reproducibility.

    Returns
    -------
    AcerbiSzekelyResult

    Raises
    ------
    ValueError
        On mismatched lengths, NaN/Inf values, or alpha outside (0, 1).
    """
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1); got {alpha}")
    ret_arr = _validate_returns(
        returns if isinstance(returns, np.ndarray) else np.asarray(returns, dtype=float),
        "returns",
    )
    es_arr = np.asarray(es_forecasts, dtype=float).reshape(-1)
    if es_arr.shape[0] != ret_arr.shape[0]:
        raise ValueError(
            f"returns and es_forecasts must have the same length; "
            f"got {ret_arr.shape[0]} vs {es_arr.shape[0]}."
        )
    if not np.isfinite(es_arr).all():
        raise ValueError("es_forecasts contains NaN or infinite values.")
    if (es_arr <= 0.0).any():
        raise ValueError(
            "es_forecasts must be strictly positive loss magnitudes; "
            "found non-positive values."
        )

    # VaR threshold: exceedance if return < -ES_t is a conservative proxy;
    # in practice the VaR forecast is often unavailable separately.  The
    # Acerbi-Szekely Z2 test only requires the ES forecast and the exceedance
    # indicator.  We use VaR = ES (conservative: if return < -ES, it certainly
    # exceeded VaR too).  For this implementation we identify exceedances as
    # returns worse than the negative of the ES forecast, which is a valid
    # conservative definition (ES >= VaR, so -ES <= -VaR).
    exceedance_mask = ret_arr < -es_arr
    n_exceed = int(exceedance_mask.sum())
    t = float(ret_arr.shape[0])

    if n_exceed == 0:
        z2_obs = 1.0
    else:
        z2_obs = float(
            np.sum(ret_arr[exceedance_mask] / es_arr[exceedance_mask])
            / (t * (1.0 - alpha))
            + 1.0
        )

    # Simulation-based p-value under the null (correctly specified N(0,1))
    # ES for N(0,1) at level alpha:
    z_alpha = float(stats.norm.ppf(alpha))
    phi_z = float(stats.norm.pdf(z_alpha))
    null_es = phi_z / (1.0 - alpha)  # ES of N(0,1)

    rng = np.random.default_rng(seed)
    n = ret_arr.shape[0]
    sim_z2 = np.empty(n_simulations, dtype=float)
    for i in range(n_simulations):
        sim_rets = rng.standard_normal(n)
        exc_mask = sim_rets < -null_es
        n_exc_sim = int(exc_mask.sum())
        if n_exc_sim == 0:
            sim_z2[i] = 1.0
        else:
            sim_z2[i] = float(
                np.sum(sim_rets[exc_mask]) / null_es
                / (float(n) * (1.0 - alpha))
                + 1.0
            )

    p_value = float(np.mean(sim_z2 <= z2_obs))
    return AcerbiSzekelyResult(
        z2=z2_obs,
        p_value=p_value,
        n_exceedances=n_exceed,
        alpha=alpha,
    )
