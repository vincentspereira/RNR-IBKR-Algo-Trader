"""Constrained mean-variance optimisation (Phase 6.1).

Markowitz portfolio selection with the constraint set that real portfolios
actually run under -- long-only, net-budget, gross-leverage cap, per-asset
caps, sector caps and a turnover budget -- plus the estimation hygiene the
master plan mandates: covariance comes from the robust estimators in
:mod:`core_trading.portfolio.covariance` (Ledoit-Wolf / OAS / factor model),
and expected returns come from a shrinkage estimator
(:func:`bayes_stein_means`), never the raw sample mean.

Why shrinkage is non-negotiable here: the unconstrained Markowitz solution
w* = (1/gamma) Sigma^{-1} mu amplifies estimation error through the inverse
of an ill-conditioned matrix -- Michaud (1989) calls MVO an "estimation-error
maximizer".  The Phase 6 DOD sensitivity tests verify directly that small
input perturbations produce small weight changes once shrinkage is applied,
and large ones when it is not.

Optimisation modes
------------------
Given expected returns mu (per bar), covariance Sigma (per bar^2) and
config gamma:

1. Utility mode (``target_return=None``):
       minimise  (gamma / 2) w' Sigma w  -  mu' w
2. Target-return mode (``target_return=r``):
       minimise  w' Sigma w   subject to   mu' w >= r
3. Minimum variance (:func:`min_variance_weights`, no mu needed):
       minimise  w' Sigma w

All three share the constraint set:
    sum(w) == budget                      (net exposure)
    w >= 0                                (if long_only)
    sum(|w|) <= gross_cap                 (if set)
    |w_i| <= max_weight                   (if set)
    sum_{i in sector s} w_i <= cap_s      (per sector cap, if set)
    sum(|w - w_prev|) <= turnover_cap     (if set, needs prev_weights)

Problems are quadratic programs solved through cvxpy (CLARABEL by default).
Infeasible or unbounded problems raise ``ValueError`` with the solver
status -- silent garbage weights are never returned.

Bayes-Stein expected returns (Jorion 1986)
------------------------------------------
    mu_BS = (1 - v) mu_hat + v mu_g 1
    mu_g  = (1' P mu_hat) / (1' P 1)          (grand mean implied by the
                                               minimum-variance portfolio)
    P     = Sigma_adj^{-1},
    Sigma_adj = S (T - 1) / (T - N - 2)       (unbiased precision scaling;
                                               requires T >= N + 3)
    lam   = (N + 2) / ((mu_hat - mu_g 1)' P (mu_hat - mu_g 1))
    v     = lam / (lam + T),  clipped to [0, 1]
The estimator shrinks each asset's sample mean towards the grand mean with
data-driven intensity: the noisier the dispersion of sample means, the
harder the shrink.  When all sample means coincide the intensity is 1.

Mathematical references
-----------------------
  * Markowitz, H. (1952). "Portfolio Selection."
    Journal of Finance, 7(1), 77-91.
  * Jorion, P. (1986). "Bayes-Stein Estimation for Portfolio Analysis."
    Journal of Financial and Quantitative Analysis, 21(3), 279-292.
  * Michaud, R.O. (1989). "The Markowitz Optimization Enigma: Is 'Optimized'
    Optimal?" Financial Analysts Journal, 45(1), 31-42.
  * Boyd, S. & Vandenberghe, L. (2004). "Convex Optimization." Cambridge
    University Press.  (QP formulation of constrained mean-variance.)
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from core_trading.portfolio.covariance import nearest_psd

__all__ = [
    "MVOConfig",
    "MVOResult",
    "RobustMeanResult",
    "bayes_stein_means",
    "mean_variance_weights",
    "min_variance_weights",
]


# ---------------------------------------------------------------------------
# Configuration / result DTOs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MVOConfig:
    """Parameters for constrained mean-variance optimisation.

    Attributes
    ----------
    risk_aversion:
        Utility-mode risk aversion gamma > 0.  Larger values produce more
        conservative portfolios.  Ignored in target-return mode.
    target_return:
        If set, switch to target-return mode: minimise variance subject to
        ``mu' w >= target_return`` (same per-bar units as ``mu``).
    long_only:
        If ``True`` (default) constrain w >= 0.
    budget:
        Net exposure: ``sum(w) == budget``.  Default 1.0 (fully invested).
    gross_cap:
        Gross leverage cap ``sum(|w|) <= gross_cap``; ``None`` disables.
        Must be >= ``abs(budget)`` (otherwise infeasible by construction).
    max_weight:
        Per-asset cap ``|w_i| <= max_weight``; ``None`` disables.
    turnover_cap:
        Turnover budget ``sum(|w - w_prev|) <= turnover_cap``; ``None``
        disables.  Requires ``prev_weights`` at solve time.
    solver:
        cvxpy solver name override (e.g. ``"CLARABEL"``, ``"OSQP"``).
        ``None`` uses CLARABEL.
    """

    risk_aversion: float = 1.0
    target_return: float | None = None
    long_only: bool = True
    budget: float = 1.0
    gross_cap: float | None = None
    max_weight: float | None = None
    turnover_cap: float | None = None
    solver: str | None = None

    def __post_init__(self) -> None:
        """Validate parameter consistency."""
        if not np.isfinite(self.risk_aversion) or self.risk_aversion <= 0.0:
            raise ValueError(
                f"risk_aversion must be a finite positive float, got {self.risk_aversion}"
            )
        if self.target_return is not None and not np.isfinite(self.target_return):
            raise ValueError(f"target_return must be finite, got {self.target_return}")
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
                    f"({abs(self.budget)}); the net constraint makes the "
                    "problem infeasible otherwise."
                )
        if self.max_weight is not None and (
            not np.isfinite(self.max_weight) or self.max_weight <= 0.0
        ):
            raise ValueError(
                f"max_weight must be a finite positive float, got {self.max_weight}"
            )
        if self.turnover_cap is not None and (
            not np.isfinite(self.turnover_cap) or self.turnover_cap < 0.0
        ):
            raise ValueError(
                f"turnover_cap must be a finite non-negative float, "
                f"got {self.turnover_cap}"
            )


@dataclass(frozen=True, slots=True)
class MVOResult:
    """Solved portfolio.

    Attributes
    ----------
    weights:
        Optimal weights as a ``pandas.Series`` indexed by asset symbol
        (input order preserved).  Near-zero solver residue (< 1e-10) is
        snapped to exactly 0.
    expected_return:
        ``mu' w`` per bar; ``None`` when solved without expected returns
        (minimum variance).
    volatility:
        ``sqrt(w' Sigma w)`` per bar.
    objective_value:
        The solver's objective at the optimum (mode-dependent).
    status:
        cvxpy termination status (``"optimal"`` or ``"optimal_inaccurate"``;
        anything else raises instead of returning).
    """

    weights: pd.Series = field(compare=False)
    expected_return: float | None
    volatility: float
    objective_value: float
    status: str


@dataclass(frozen=True, slots=True)
class RobustMeanResult:
    """Shrunk expected-return vector.

    Attributes
    ----------
    means:
        Shrunk per-bar expected returns, indexed by asset symbol.
    intensity:
        Shrinkage intensity v in [0, 1]; 0 keeps the sample means, 1
        replaces every mean with the grand mean.
    grand_mean:
        The shrinkage target mu_g (minimum-variance-implied grand mean).
    method:
        Estimator identifier (``"bayes_stein"``).
    """

    means: pd.Series = field(compare=False)
    intensity: float
    grand_mean: float
    method: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_PSD_TOL = 1e-8


def _validate_sigma(sigma: pd.DataFrame) -> np.ndarray:
    """Validate a covariance DataFrame and return a PSD-repaired float array.

    Requires a square, NaN-free, symmetric (to 1e-10 relative) matrix with
    matching index/columns whose smallest eigenvalue is no more negative
    than ``-_PSD_TOL * max(|eigenvalues|)``.  The tiny negative residue
    tolerated by that check is then clipped to zero via
    :func:`~core_trading.portfolio.covariance.nearest_psd` so downstream
    solvers receive an exactly-PSD matrix.

    Raises
    ------
    ValueError
        On shape/label mismatch, NaN, asymmetry, or a materially indefinite
        matrix (advice: repair with ``nearest_psd`` first).
    """
    if sigma.shape[0] != sigma.shape[1]:
        raise ValueError(f"sigma must be square; got shape {sigma.shape}.")
    if list(sigma.index) != list(sigma.columns):
        raise ValueError("sigma index and columns must be identical asset labels.")
    if sigma.shape[0] < 2:
        raise ValueError(
            f"sigma must cover at least 2 assets; got {sigma.shape[0]}."
        )
    arr: np.ndarray = sigma.to_numpy(dtype=float)
    if not np.isfinite(arr).all():
        raise ValueError("sigma contains NaN or infinite values.")
    scale = float(np.abs(arr).max())
    if scale <= 0.0:
        raise ValueError("sigma is identically zero.")
    if float(np.abs(arr - arr.T).max()) > 1e-10 * scale:
        raise ValueError("sigma must be symmetric (relative tolerance 1e-10).")
    sym: np.ndarray = (arr + arr.T) / 2.0
    eigenvalues = np.linalg.eigvalsh(sym)
    if float(eigenvalues[0]) < -_PSD_TOL * float(np.abs(eigenvalues).max()):
        raise ValueError(
            "sigma is materially indefinite (smallest eigenvalue "
            f"{eigenvalues[0]:.3e}); repair it with "
            "core_trading.portfolio.covariance.nearest_psd before optimising."
        )
    return nearest_psd(sym)


def _validate_aligned_series(
    values: pd.Series, sigma: pd.DataFrame, name: str
) -> np.ndarray:
    """Validate that a Series aligns exactly with sigma's asset labels."""
    if list(values.index) != list(sigma.index):
        raise ValueError(
            f"{name} index must match sigma's asset labels in the same order."
        )
    arr: np.ndarray = values.to_numpy(dtype=float)
    if not np.isfinite(arr).all():
        raise ValueError(f"{name} contains NaN or infinite values.")
    return arr


def _sector_index_groups(
    assets: list[str],
    sectors: Mapping[str, str] | None,
    sector_caps: Mapping[str, float] | None,
) -> list[tuple[str, list[int], float]]:
    """Resolve sector caps into (sector, asset positions, cap) triples.

    Raises
    ------
    ValueError
        If caps are given without a sector mapping, a cap is non-positive,
        or a capped sector matches no asset in the universe (typo guard).
    """
    if sector_caps is None:
        return []
    if sectors is None:
        raise ValueError("sector_caps given but sectors mapping is None.")
    groups: list[tuple[str, list[int], float]] = []
    for sector, cap in sector_caps.items():
        if not np.isfinite(cap) or cap <= 0.0:
            raise ValueError(
                f"sector cap for {sector!r} must be a finite positive float, got {cap}"
            )
        positions = [
            i for i, asset in enumerate(assets) if sectors.get(asset) == sector
        ]
        if not positions:
            raise ValueError(
                f"sector_caps references sector {sector!r} but no asset in the "
                "universe maps to it; check the sectors mapping."
            )
        groups.append((sector, positions, float(cap)))
    return groups


def _clean_weights(weights: np.ndarray, *, snap_tol: float = 1e-8) -> np.ndarray:
    """Snap solver residue below ``snap_tol`` to exact zeros."""
    out = weights.copy()
    out[np.abs(out) < snap_tol] = 0.0
    return out


def _solve_qp(
    mu_arr: np.ndarray | None,
    sigma_arr: np.ndarray,
    assets: list[str],
    config: MVOConfig,
    prev_arr: np.ndarray | None,
    sector_groups: list[tuple[str, list[int], float]],
) -> MVOResult:
    """Build and solve the constrained QP; shared by all public entry points."""
    import cvxpy as cp  # heavy import deferred to the call site

    n = sigma_arr.shape[0]
    w = cp.Variable(n)
    risk = cp.quad_form(w, cp.psd_wrap(sigma_arr))

    constraints = [cp.sum(w) == config.budget]
    if config.long_only:
        constraints.append(w >= 0)
    if config.gross_cap is not None:
        constraints.append(cp.norm1(w) <= config.gross_cap)
    if config.max_weight is not None:
        constraints.append(cp.abs(w) <= config.max_weight)
    for _sector, positions, cap in sector_groups:
        constraints.append(cp.sum(w[positions]) <= cap)
    if config.turnover_cap is not None:
        if prev_arr is None:
            raise ValueError(
                "config.turnover_cap is set but prev_weights was not provided."
            )
        constraints.append(cp.norm1(w - prev_arr) <= config.turnover_cap)

    if mu_arr is None:
        objective = cp.Minimize(risk)
    elif config.target_return is not None:
        constraints.append(mu_arr @ w >= config.target_return)
        objective = cp.Minimize(risk)
    else:
        objective = cp.Minimize(
            0.5 * config.risk_aversion * risk - mu_arr @ w
        )

    problem = cp.Problem(objective, constraints)
    solver = config.solver if config.solver is not None else "CLARABEL"
    problem.solve(solver=solver)

    if problem.status not in ("optimal", "optimal_inaccurate"):
        raise ValueError(
            f"mean-variance problem terminated with status {problem.status!r}; "
            "the constraint set is likely infeasible (check budget vs caps)."
        )

    raw = np.asarray(w.value, dtype=float).reshape(-1)
    weights = _clean_weights(raw)
    volatility = float(np.sqrt(max(float(weights @ sigma_arr @ weights), 0.0)))
    expected = None if mu_arr is None else float(mu_arr @ weights)
    return MVOResult(
        weights=pd.Series(weights, index=assets),
        expected_return=expected,
        volatility=volatility,
        objective_value=float(problem.value),
        status=str(problem.status),
    )


# ---------------------------------------------------------------------------
# Robust expected returns
# ---------------------------------------------------------------------------


def bayes_stein_means(returns: pd.DataFrame) -> RobustMeanResult:
    """Jorion (1986) Bayes-Stein shrinkage of sample mean returns.

    Shrinks each asset's sample mean towards the grand mean implied by the
    minimum-variance portfolio, with intensity driven by the dispersion of
    the sample means (see module docstring for the formulas).  This is the
    Phase 6 default expected-return estimator: raw sample means are never
    fed to the optimiser.

    Parameters
    ----------
    returns:
        Returns panel: ascending DatetimeIndex rows x asset columns,
        NaN-free, with T >= N + 3 observations (required by the unbiased
        precision scaling (T - 1) / (T - N - 2)).

    Returns
    -------
    RobustMeanResult
        Shrunk means, intensity v in [0, 1], grand mean, method tag.

    Raises
    ------
    ValueError
        On NaN, fewer than 2 assets, or T < N + 3 observations.
    """
    if returns.isnull().any().any():
        raise ValueError(
            "returns panel contains NaN values; "
            "align and fill or drop missing data before estimating means."
        )
    n_obs, n_assets = returns.shape
    if n_assets < 2:
        raise ValueError(
            f"returns panel must have at least 2 asset columns; got {n_assets}."
        )
    if n_obs < n_assets + 3:
        raise ValueError(
            "Bayes-Stein estimation requires T >= N + 3 observations "
            f"(got T={n_obs}, N={n_assets}); the precision scaling "
            "(T - 1) / (T - N - 2) is undefined otherwise."
        )

    arr: np.ndarray = returns.to_numpy(dtype=float)
    mu_hat = arr.mean(axis=0)
    x = arr - mu_hat
    sample_cov = (x.T @ x) / float(n_obs - 1)
    sigma_adj = sample_cov * (float(n_obs - 1) / float(n_obs - n_assets - 2))

    ones = np.ones(n_assets)
    # Solve instead of inverting: P @ v computed via solve(sigma_adj, v).
    try:
        p_ones = np.linalg.solve(sigma_adj, ones)
        p_mu = np.linalg.solve(sigma_adj, mu_hat)
    except np.linalg.LinAlgError as exc:
        raise ValueError(
            "Bayes-Stein estimation failed: the adjusted sample covariance "
            "is singular; supply a longer history or fewer assets."
        ) from exc

    grand_mean = float(ones @ p_mu) / float(ones @ p_ones)
    deviation = mu_hat - grand_mean
    dispersion = float(deviation @ np.linalg.solve(sigma_adj, deviation))

    if dispersion <= 0.0:
        intensity = 1.0  # all sample means coincide with the grand mean
    else:
        lam = float(n_assets + 2) / dispersion
        intensity = float(np.clip(lam / (lam + float(n_obs)), 0.0, 1.0))

    shrunk = (1.0 - intensity) * mu_hat + intensity * grand_mean
    return RobustMeanResult(
        means=pd.Series(shrunk, index=returns.columns),
        intensity=intensity,
        grand_mean=grand_mean,
        method="bayes_stein",
    )


# ---------------------------------------------------------------------------
# Optimisers
# ---------------------------------------------------------------------------


def mean_variance_weights(
    mu: pd.Series,
    sigma: pd.DataFrame,
    config: MVOConfig | None = None,
    *,
    prev_weights: pd.Series | None = None,
    sectors: Mapping[str, str] | None = None,
    sector_caps: Mapping[str, float] | None = None,
) -> MVOResult:
    """Solve the constrained Markowitz problem (utility or target-return mode).

    See the module docstring for the optimisation modes and constraint set.
    ``mu`` must come from a robust estimator such as
    :func:`bayes_stein_means` -- never the raw sample mean (master plan
    Phase 6.1 requirement).

    Parameters
    ----------
    mu:
        Expected returns per bar, indexed by asset symbol; must align with
        ``sigma`` exactly (same labels, same order).
    sigma:
        Covariance matrix per bar^2, e.g.
        ``ledoit_wolf_covariance(returns).covariance``.
    config:
        :class:`MVOConfig`; ``None`` uses the defaults (long-only, fully
        invested, utility mode with gamma = 1).
    prev_weights:
        Current portfolio weights, required when ``config.turnover_cap``
        is set; aligned to ``sigma``.
    sectors:
        Asset -> sector mapping (only needed with ``sector_caps``).
    sector_caps:
        Sector -> cap on ``sum(w_i)`` over that sector's assets.

    Returns
    -------
    MVOResult

    Raises
    ------
    ValueError
        On invalid/misaligned inputs, an indefinite sigma, a missing
        ``prev_weights`` when the turnover cap is active, or an infeasible
        problem (solver status in the message).
    """
    cfg = config if config is not None else MVOConfig()
    sigma_arr = _validate_sigma(sigma)
    mu_arr = _validate_aligned_series(mu, sigma, "mu")
    prev_arr = (
        None
        if prev_weights is None
        else _validate_aligned_series(prev_weights, sigma, "prev_weights")
    )
    assets = [str(c) for c in sigma.index]
    sector_groups = _sector_index_groups(assets, sectors, sector_caps)
    return _solve_qp(mu_arr, sigma_arr, assets, cfg, prev_arr, sector_groups)


def min_variance_weights(
    sigma: pd.DataFrame,
    config: MVOConfig | None = None,
    *,
    prev_weights: pd.Series | None = None,
    sectors: Mapping[str, str] | None = None,
    sector_caps: Mapping[str, float] | None = None,
) -> MVOResult:
    """Solve the minimum-variance problem (no expected returns needed).

    The constraint set is identical to :func:`mean_variance_weights`;
    ``config.risk_aversion`` and ``config.target_return`` are ignored.
    Useful both as a portfolio in its own right (the only point on the
    frontier free of mean-estimation error) and as the conservative
    fallback when no return forecast is trusted.

    Parameters / Returns / Raises
    -----------------------------
    As :func:`mean_variance_weights`, minus ``mu``.
    """
    cfg = config if config is not None else MVOConfig()
    sigma_arr = _validate_sigma(sigma)
    prev_arr = (
        None
        if prev_weights is None
        else _validate_aligned_series(prev_weights, sigma, "prev_weights")
    )
    assets = [str(c) for c in sigma.index]
    sector_groups = _sector_index_groups(assets, sectors, sector_caps)
    return _solve_qp(None, sigma_arr, assets, cfg, prev_arr, sector_groups)
