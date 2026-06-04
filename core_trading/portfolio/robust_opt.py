"""Robust portfolio optimisation (Phase 6.5).

Three complementary defences against the estimation error that plain
Markowitz amplifies, per the master plan: Michaud resampling, worst-case
CVaR over scenario sets, and distributionally robust mean-variance under
an ellipsoidal ambiguity set for the mean.

1. Michaud resampled efficiency (:func:`michaud_weights`)
---------------------------------------------------------
Monte-Carlo average of constrained MVO solutions over resampled inputs:
draw an estimation window of T observations from N(mu, Sigma), re-estimate
(mu_r, Sigma_r), solve the SAME constrained problem, and average the
optimal weights across resamples.  Averaging is feasibility-preserving
because every constraint handled by :mod:`core_trading.portfolio.mvo`
(budget equality, long-only, gross cap, per-asset cap, sector caps,
turnover ball) defines a CONVEX set, so the mean of feasible points is
feasible.  The averaged portfolio is deliberately less extreme than any
single-draw optimum -- that is the point: Michaud (1998) shows the
single-sample optimum is an artefact of estimation noise.

2. Worst-case CVaR (:func:`cvar_weights`, :func:`worst_case_cvar_weights`)
---------------------------------------------------------------------------
Scenario-based CVaR minimisation via the Rockafellar-Uryasev (2000) LP:
with portfolio loss L_s = -r_s' w over S scenarios,

    CVaR_alpha(w) = min_z  z + (1 / ((1 - alpha) S)) sum_s max(L_s - z, 0)

which is linear in (w, z, u) after the standard epigraph lift.  The
worst-case variant follows Zhu & Fukushima (2009): given several scenario
BLOCKS (e.g. one per regime, or per resampled history -- a mixture
ambiguity set), minimise the maximum block CVaR:

    min_w max_l CVaR_alpha^{(l)}(w)

via one epigraph variable across the per-block LP lifts.  This is
distributional robustness over the mixture family: the optimiser defends
against whichever block distribution turns out to be the truth.

3. DRO mean-variance (:func:`robust_mean_variance_weights`)
------------------------------------------------------------
Distributionally robust counterpart of the Markowitz utility under an
ellipsoidal ambiguity set for the MEAN (Delage & Ye 2010; Garlappi, Uppal
& Wang 2007).  With mu constrained to the set
{ mu : (mu - mu_0)' Sigma_mu^{-1} (mu - mu_0) <= kappa^2 } the inner
minimisation is available in closed form and the problem becomes the
deterministic SOCP

    maximise  mu_0' w - kappa * || Sigma_mu^{1/2} w ||_2
              - (gamma / 2) w' Sigma w

over the same constraint set as plain MVO.  kappa = 0 recovers Markowitz
exactly; kappa -> infinity drives the solution to the minimum-variance
portfolio (the mean forecast is fully distrusted).  The default
Sigma_mu = Sigma / n_obs is the sampling covariance of the mean estimate,
so kappa is measured in standard errors of the forecast.

.. warning::
    Windows entrypoint rule: ``import cvxpy`` before pandas in any
    process that calls these optimisers -- see the warning in
    :mod:`core_trading.portfolio.mvo` for the failure mode.

Mathematical references
-----------------------
  * Michaud, R.O. (1998). "Efficient Asset Management." Harvard Business
    School Press.  (Resampled efficiency; see also Michaud & Michaud 2008.)
  * Rockafellar, R.T. & Uryasev, S. (2000). "Optimization of Conditional
    Value-at-Risk." Journal of Risk, 2(3), 21-41.
  * Zhu, S. & Fukushima, M. (2009). "Worst-Case Conditional Value-at-Risk
    with Application to Robust Portfolio Management."
    Operations Research, 57(5), 1155-1168.
  * Delage, E. & Ye, Y. (2010). "Distributionally Robust Optimization
    Under Moment Uncertainty with Application to Data-Driven Problems."
    Operations Research, 58(3), 595-612.
  * Garlappi, L., Uppal, R. & Wang, T. (2007). "Portfolio Selection with
    Parameter and Model Uncertainty: A Multi-Prior Approach."
    Review of Financial Studies, 20(1), 41-81.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from core_trading.portfolio.mvo import (
    MVOConfig,
    MVOResult,
    _sector_index_groups,
    _validate_aligned_series,
    _validate_sigma,
    mean_variance_weights,
)

__all__ = [
    "CVaRConfig",
    "CVaRResult",
    "MichaudResult",
    "cvar_weights",
    "empirical_cvar",
    "michaud_weights",
    "robust_mean_variance_weights",
    "worst_case_cvar_weights",
]


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MichaudResult:
    """Michaud resampled-efficiency portfolio.

    Attributes
    ----------
    weights:
        Average of the per-resample optimal weights (feasible for every
        convex constraint of the base problem).
    weight_dispersion:
        Per-asset standard deviation of the optimal weights across
        resamples -- the estimation-noise diagnostic Michaud emphasises.
    n_resamples:
        Number of Monte-Carlo resamples averaged.
    estimation_window:
        Observations T drawn per resample.
    """

    weights: pd.Series = field(compare=False)
    weight_dispersion: pd.Series = field(compare=False)
    n_resamples: int
    estimation_window: int


@dataclass(frozen=True, slots=True)
class CVaRConfig:
    """Parameters for (worst-case) CVaR optimisation.

    Attributes
    ----------
    alpha:
        Tail level in (0, 1); CVaR_alpha averages the worst (1 - alpha)
        fraction of losses.  Typical: 0.95.
    budget:
        Net exposure: ``sum(w) == budget``.
    long_only:
        If ``True`` (default) constrain w >= 0.
    gross_cap:
        Gross leverage cap ``sum(|w|) <= gross_cap``; ``None`` disables.
    max_weight:
        Per-asset cap ``|w_i| <= max_weight``; ``None`` disables.
    min_expected_return:
        If set, require the scenario-mean return of the portfolio to be
        at least this value -- in EVERY block for the worst-case variant
        (robust return constraint).
    solver:
        cvxpy solver name override; ``None`` uses CLARABEL.
    """

    alpha: float = 0.95
    budget: float = 1.0
    long_only: bool = True
    gross_cap: float | None = None
    max_weight: float | None = None
    min_expected_return: float | None = None
    solver: str | None = None

    def __post_init__(self) -> None:
        """Validate parameter consistency."""
        if not 0.0 < self.alpha < 1.0:
            raise ValueError(f"alpha must be in (0, 1), got {self.alpha}")
        if not np.isfinite(self.budget):
            raise ValueError(f"budget must be finite, got {self.budget}")
        if self.gross_cap is not None:
            if not np.isfinite(self.gross_cap) or self.gross_cap <= 0.0:
                raise ValueError(
                    f"gross_cap must be a finite positive float, got {self.gross_cap}"
                )
            if self.gross_cap < abs(self.budget):
                raise ValueError(
                    f"gross_cap ({self.gross_cap}) must be >= |budget| "
                    f"({abs(self.budget)})."
                )
        if self.max_weight is not None and (
            not np.isfinite(self.max_weight) or self.max_weight <= 0.0
        ):
            raise ValueError(
                f"max_weight must be a finite positive float, got {self.max_weight}"
            )
        if self.min_expected_return is not None and not np.isfinite(
            self.min_expected_return
        ):
            raise ValueError(
                f"min_expected_return must be finite, got {self.min_expected_return}"
            )


@dataclass(frozen=True, slots=True)
class CVaRResult:
    """Solved (worst-case) CVaR portfolio.

    Attributes
    ----------
    weights:
        Optimal weights, indexed by asset symbol.
    cvar:
        The optimised CVaR_alpha of the portfolio loss -- for the
        worst-case variant, the WORST block's CVaR.
    block_cvars:
        Per-block CVaR at the optimum (single entry for the plain
        variant), in block order.
    expected_return:
        Scenario-mean portfolio return -- for the worst-case variant the
        WORST block's mean (consistent with the robust return constraint).
    alpha:
        Tail level used.
    status:
        cvxpy termination status.
    """

    weights: pd.Series = field(compare=False)
    cvar: float
    block_cvars: tuple[float, ...]
    expected_return: float
    alpha: float
    status: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_scenarios(scenarios: pd.DataFrame, name: str) -> np.ndarray:
    """Validate a scenario return matrix (rows = scenarios, cols = assets)."""
    n_scen, n_assets = scenarios.shape
    if n_assets < 2:
        raise ValueError(
            f"{name} must have at least 2 asset columns; got {n_assets}."
        )
    if n_scen < 2:
        raise ValueError(
            f"{name} must have at least 2 scenario rows; got {n_scen}."
        )
    arr: np.ndarray = scenarios.to_numpy(dtype=float)
    if not np.isfinite(arr).all():
        raise ValueError(f"{name} contains NaN or infinite values.")
    return arr


def _psd_sqrt(matrix: np.ndarray) -> np.ndarray:
    """Symmetric PSD square root via eigendecomposition (clipped at 0)."""
    eigenvalues, eigenvectors = np.linalg.eigh((matrix + matrix.T) / 2.0)
    clipped = np.sqrt(np.maximum(eigenvalues, 0.0))
    out: np.ndarray = (eigenvectors * clipped[np.newaxis, :]) @ eigenvectors.T
    return out


def _clean_weights(weights: np.ndarray, *, snap_tol: float = 1e-8) -> np.ndarray:
    """Snap solver residue below ``snap_tol`` to exact zeros."""
    out = weights.copy()
    out[np.abs(out) < snap_tol] = 0.0
    return out


# ---------------------------------------------------------------------------
# Michaud resampled efficiency
# ---------------------------------------------------------------------------


def michaud_weights(
    mu: pd.Series,
    sigma: pd.DataFrame,
    config: MVOConfig | None = None,
    *,
    n_resamples: int = 100,
    estimation_window: int = 60,
    resample_covariance: bool = True,
    seed: int = 0,
    prev_weights: pd.Series | None = None,
    sectors: Mapping[str, str] | None = None,
    sector_caps: Mapping[str, float] | None = None,
) -> MichaudResult:
    """Michaud resampled-efficiency weights (see module docstring).

    Each resample draws ``estimation_window`` observations from
    N(mu, Sigma) via the PSD square root of ``sigma``, re-estimates the
    inputs (sample mean; sample covariance when ``resample_covariance``),
    solves the identical constrained problem through
    :func:`core_trading.portfolio.mvo.mean_variance_weights`, and the
    optimal weights are averaged.

    Parameters
    ----------
    mu, sigma, config, prev_weights, sectors, sector_caps:
        Exactly as :func:`core_trading.portfolio.mvo.mean_variance_weights`.
    n_resamples:
        Monte-Carlo resamples to average; must be >= 1.
    estimation_window:
        Observations T per resample; must be >= 2.  Smaller T = more
        estimation noise = stronger smoothing of the averaged weights.
    resample_covariance:
        If ``True`` (default, Michaud's prescription) re-estimate the
        covariance per resample; if ``False`` only the mean is resampled.
    seed:
        Seed for the resampling generator (deterministic output).

    Returns
    -------
    MichaudResult

    Raises
    ------
    ValueError
        On invalid resampling parameters, or anything the underlying
        constrained solver rejects (propagated unchanged).
    """
    if n_resamples < 1:
        raise ValueError(f"n_resamples must be >= 1, got {n_resamples}")
    if estimation_window < 2:
        raise ValueError(
            f"estimation_window must be >= 2, got {estimation_window}"
        )

    rng = np.random.default_rng(seed)
    sigma_sqrt = _psd_sqrt(sigma.to_numpy(dtype=float))
    mu_arr = mu.to_numpy(dtype=float)
    assets = list(sigma.index)

    all_weights = np.empty((n_resamples, len(assets)), dtype=float)
    for r in range(n_resamples):
        draws = (
            rng.standard_normal((estimation_window, len(assets))) @ sigma_sqrt
            + mu_arr
        )
        mu_r = pd.Series(draws.mean(axis=0), index=assets)
        if resample_covariance:
            centred = draws - draws.mean(axis=0)
            cov_r = pd.DataFrame(
                (centred.T @ centred) / float(estimation_window - 1),
                index=assets,
                columns=assets,
            )
        else:
            cov_r = sigma
        result = mean_variance_weights(
            mu_r,
            cov_r,
            config,
            prev_weights=prev_weights,
            sectors=sectors,
            sector_caps=sector_caps,
        )
        all_weights[r] = result.weights.to_numpy()

    averaged = all_weights.mean(axis=0)
    dispersion = all_weights.std(axis=0, ddof=0)
    return MichaudResult(
        weights=pd.Series(_clean_weights(averaged), index=assets),
        weight_dispersion=pd.Series(dispersion, index=assets),
        n_resamples=int(n_resamples),
        estimation_window=int(estimation_window),
    )


# ---------------------------------------------------------------------------
# Empirical CVaR
# ---------------------------------------------------------------------------


def empirical_cvar(portfolio_returns: np.ndarray | pd.Series, alpha: float) -> float:
    """Discrete CVaR_alpha of a return sample (Rockafellar-Uryasev).

    Computes the exact optimum of the discrete RU program
    ``min_z z + mean(max(loss - z, 0)) / (1 - alpha)`` with
    loss = -return: sort the S losses ascending, set j = ceil(S * alpha);
    the tail then mixes the fractional scenario at the VaR boundary with
    the strictly-worse tail:

        CVaR = [ (j - S alpha) L_(j) + sum_{i > j} L_(i) ] / (S (1 - alpha))

    Exported for the Phase 6 comparison report and used by the test suite
    to cross-check the LP optimiser's objective.

    Parameters
    ----------
    portfolio_returns:
        1-D sample of portfolio returns (NOT losses).
    alpha:
        Tail level in (0, 1).

    Returns
    -------
    float
        CVaR of the loss distribution (positive = losing tail).

    Raises
    ------
    ValueError
        On an empty/NaN sample or alpha outside (0, 1).
    """
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")
    arr = np.asarray(portfolio_returns, dtype=float).reshape(-1)
    if arr.shape[0] < 1:
        raise ValueError("portfolio_returns must contain at least one value.")
    if not np.isfinite(arr).all():
        raise ValueError("portfolio_returns contain NaN or infinite values.")
    losses = np.sort(-arr)  # ascending
    n = losses.shape[0]
    j = int(np.ceil(n * alpha))
    if j >= n:
        # The tail is thinner than one scenario: CVaR is the worst loss.
        return float(losses[-1])
    boundary_mass = float(j) - n * alpha
    tail_sum = float(losses[j:].sum())
    return float(
        (boundary_mass * losses[j - 1] + tail_sum) / (n * (1.0 - alpha))
    )


# ---------------------------------------------------------------------------
# (Worst-case) CVaR optimisation
# ---------------------------------------------------------------------------


def worst_case_cvar_weights(
    scenario_blocks: Sequence[pd.DataFrame],
    config: CVaRConfig | None = None,
) -> CVaRResult:
    """Minimise the worst block CVaR over a mixture ambiguity set.

    Implements Zhu-Fukushima worst-case CVaR (see module docstring): one
    Rockafellar-Uryasev LP lift per scenario block, a shared epigraph
    variable bounding every block's CVaR, and the common portfolio
    constraint set from :class:`CVaRConfig`.  With a single block this is
    exactly plain CVaR minimisation (:func:`cvar_weights` is that
    convenience wrapper).

    Parameters
    ----------
    scenario_blocks:
        Non-empty sequence of scenario return matrices, each with rows =
        scenarios and IDENTICAL asset columns (same labels, same order).
    config:
        :class:`CVaRConfig`; ``None`` uses the defaults.

    Returns
    -------
    CVaRResult

    Raises
    ------
    ValueError
        On invalid blocks (empty sequence, mismatched columns, NaN, too
        few rows/columns) or an infeasible problem (status in message).
    """
    import cvxpy as cp  # heavy import deferred to the call site

    cfg = config if config is not None else CVaRConfig()
    if len(scenario_blocks) < 1:
        raise ValueError("scenario_blocks must contain at least one block.")
    first_cols = list(scenario_blocks[0].columns)
    arrays: list[np.ndarray] = []
    for b, block in enumerate(scenario_blocks):
        if list(block.columns) != first_cols:
            raise ValueError(
                f"scenario block {b} columns do not match block 0 "
                "(same assets, same order, required)."
            )
        arrays.append(_validate_scenarios(block, f"scenario block {b}"))
    assets = [str(c) for c in first_cols]
    n_assets = len(assets)

    w = cp.Variable(n_assets)
    worst = cp.Variable()
    constraints = [cp.sum(w) == cfg.budget]
    if cfg.long_only:
        constraints.append(w >= 0)
    if cfg.gross_cap is not None:
        constraints.append(cp.norm1(w) <= cfg.gross_cap)
    if cfg.max_weight is not None:
        constraints.append(cp.abs(w) <= cfg.max_weight)

    for arr in arrays:
        n_scen = arr.shape[0]
        z = cp.Variable()
        u = cp.Variable(n_scen, nonneg=True)
        losses = -arr @ w
        constraints.append(u >= losses - z)
        cvar_expr = z + cp.sum(u) / ((1.0 - cfg.alpha) * float(n_scen))
        constraints.append(cvar_expr <= worst)
        if cfg.min_expected_return is not None:
            constraints.append(
                arr.mean(axis=0) @ w >= cfg.min_expected_return
            )

    problem = cp.Problem(cp.Minimize(worst), constraints)
    solver = cfg.solver if cfg.solver is not None else "CLARABEL"
    problem.solve(solver=solver)

    if problem.status not in ("optimal", "optimal_inaccurate"):
        raise ValueError(
            f"CVaR problem terminated with status {problem.status!r}; "
            "the constraint set is likely infeasible (check "
            "min_expected_return vs the scenario means)."
        )

    weights = _clean_weights(np.asarray(w.value, dtype=float).reshape(-1))
    # Report exact empirical CVaRs of the SOLVED weights (not the solver's
    # epigraph values, which can sit slightly above at the tolerance).
    block_cvars = tuple(
        empirical_cvar(arr @ weights, cfg.alpha) for arr in arrays
    )
    block_means = [float(arr.mean(axis=0) @ weights) for arr in arrays]
    return CVaRResult(
        weights=pd.Series(weights, index=assets),
        cvar=float(max(block_cvars)),
        block_cvars=block_cvars,
        expected_return=float(min(block_means)),
        alpha=cfg.alpha,
        status=str(problem.status),
    )


def cvar_weights(
    scenarios: pd.DataFrame,
    config: CVaRConfig | None = None,
) -> CVaRResult:
    """Minimise CVaR_alpha over a single scenario set (RU 2000 LP).

    Convenience wrapper over :func:`worst_case_cvar_weights` with one
    block; see there for details.

    Parameters
    ----------
    scenarios:
        Scenario return matrix: rows = scenarios (e.g. historical or
        simulated bars), columns = assets.
    config:
        :class:`CVaRConfig`; ``None`` uses the defaults.

    Returns
    -------
    CVaRResult

    Raises
    ------
    ValueError
        As :func:`worst_case_cvar_weights`.
    """
    return worst_case_cvar_weights([scenarios], config)


# ---------------------------------------------------------------------------
# DRO mean-variance (ellipsoidal mean ambiguity)
# ---------------------------------------------------------------------------


def robust_mean_variance_weights(
    mu: pd.Series,
    sigma: pd.DataFrame,
    config: MVOConfig | None = None,
    *,
    kappa: float,
    mean_uncertainty: pd.DataFrame | None = None,
    n_obs: int | None = None,
    prev_weights: pd.Series | None = None,
    sectors: Mapping[str, str] | None = None,
    sector_caps: Mapping[str, float] | None = None,
) -> MVOResult:
    """Distributionally robust Markowitz under ellipsoidal mean ambiguity.

    Solves the SOCP (see module docstring)

        maximise  mu' w - kappa ||Sigma_mu^{1/2} w||_2 - (gamma/2) w' Sigma w

    over the full MVO constraint set, where Sigma_mu is the covariance of
    the mean ESTIMATE.  ``kappa = 0`` reproduces
    :func:`core_trading.portfolio.mvo.mean_variance_weights` exactly;
    larger kappa expresses less trust in the forecast and drives the
    solution towards minimum variance.

    Parameters
    ----------
    mu, sigma, config, prev_weights, sectors, sector_caps:
        Exactly as :func:`core_trading.portfolio.mvo.mean_variance_weights`
        (``config.target_return`` is not supported here -- the robust
        utility form is the canonical DRO objective; a set value raises).
    kappa:
        Ambiguity radius >= 0, in standard errors of the mean forecast
        under the default ``mean_uncertainty``.
    mean_uncertainty:
        Sigma_mu override (asset-labelled, PSD).  Default:
        ``sigma / n_obs``.
    n_obs:
        Estimation sample size for the default ``mean_uncertainty``;
        required when ``mean_uncertainty`` is None.

    Returns
    -------
    MVOResult
        ``expected_return`` is evaluated at the NOMINAL mu (the
        worst-case return is ``expected_return - kappa * ||...||``).

    Raises
    ------
    ValueError
        On invalid inputs or an infeasible/unbounded problem.
    """
    import cvxpy as cp  # heavy import deferred to the call site

    cfg = config if config is not None else MVOConfig()
    if cfg.target_return is not None:
        raise ValueError(
            "robust_mean_variance_weights supports the utility objective "
            "only; config.target_return must be None."
        )
    if not np.isfinite(kappa) or kappa < 0.0:
        raise ValueError(f"kappa must be a finite non-negative float, got {kappa}")
    if kappa == 0.0:
        # Exact Markowitz degeneracy -- delegate to the plain solver.
        return mean_variance_weights(
            mu,
            sigma,
            cfg,
            prev_weights=prev_weights,
            sectors=sectors,
            sector_caps=sector_caps,
        )

    # Same validation semantics as the plain solver (shared helpers).
    sigma_arr = _validate_sigma(sigma)
    mu_arr = _validate_aligned_series(mu, sigma, "mu")
    prev_arr = (
        None
        if prev_weights is None
        else _validate_aligned_series(prev_weights, sigma, "prev_weights")
    )
    assets = [str(c) for c in sigma.index]
    sector_groups = _sector_index_groups(assets, sectors, sector_caps)

    if mean_uncertainty is None:
        if n_obs is None or n_obs < 2:
            raise ValueError(
                "n_obs >= 2 is required when mean_uncertainty is None "
                "(default Sigma_mu = sigma / n_obs)."
            )
        sigma_mu_arr = sigma_arr / float(n_obs)
    else:
        if list(mean_uncertainty.index) != list(sigma.index) or list(
            mean_uncertainty.columns
        ) != list(sigma.columns):
            raise ValueError(
                "mean_uncertainty labels must match sigma's asset labels."
            )
        sigma_mu_arr = mean_uncertainty.to_numpy(dtype=float)
        if not np.isfinite(sigma_mu_arr).all():
            raise ValueError("mean_uncertainty contains NaN or infinite values.")

    n_assets = len(assets)
    sqrt_sigma_mu = _psd_sqrt(sigma_mu_arr)

    w = cp.Variable(n_assets)
    constraints = [cp.sum(w) == cfg.budget]
    if cfg.long_only:
        constraints.append(w >= 0)
    if cfg.gross_cap is not None:
        constraints.append(cp.norm1(w) <= cfg.gross_cap)
    if cfg.max_weight is not None:
        constraints.append(cp.abs(w) <= cfg.max_weight)
    for _sector, positions, cap in sector_groups:
        constraints.append(cp.sum(w[positions]) <= cap)
    if cfg.turnover_cap is not None:
        if prev_arr is None:
            raise ValueError(
                "config.turnover_cap is set but prev_weights was not provided."
            )
        constraints.append(cp.norm1(w - prev_arr) <= cfg.turnover_cap)

    risk = cp.quad_form(w, cp.psd_wrap(sigma_arr))
    ambiguity = kappa * cp.norm2(sqrt_sigma_mu @ w)
    objective = cp.Minimize(
        0.5 * cfg.risk_aversion * risk - mu_arr @ w + ambiguity
    )
    problem = cp.Problem(objective, constraints)
    solver = cfg.solver if cfg.solver is not None else "CLARABEL"
    problem.solve(solver=solver)

    if problem.status not in ("optimal", "optimal_inaccurate"):
        raise ValueError(
            f"robust mean-variance problem terminated with status "
            f"{problem.status!r}; the constraint set is likely infeasible."
        )

    weights = _clean_weights(np.asarray(w.value, dtype=float).reshape(-1))
    volatility = float(np.sqrt(max(float(weights @ sigma_arr @ weights), 0.0)))
    return MVOResult(
        weights=pd.Series(weights, index=assets),
        expected_return=float(mu_arr @ weights),
        volatility=volatility,
        objective_value=float(problem.value),
        status=str(problem.status),
    )
