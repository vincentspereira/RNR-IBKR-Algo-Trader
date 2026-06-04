"""Risk parity / equal risk contribution portfolios (Phase 6.4).

Allocates capital so that every asset contributes the same share of total
portfolio risk (or an arbitrary target share, "risk budgeting"), then
optionally levers the portfolio to a target volatility.  Unlike
mean-variance optimisation, risk parity needs no expected-return forecast
at all -- it is purely covariance-driven, which makes it the natural
robust complement to MVO in the Phase 6 cross-method comparison.

Definitions
-----------
For weights w and covariance Sigma, asset i's *risk contribution* is

    RC_i = w_i * (Sigma w)_i / sqrt(w' Sigma w)

and sum_i RC_i = sqrt(w' Sigma w) (Euler decomposition of the portfolio
volatility, which is homogeneous of degree 1).  The *fractional* risk
contribution is rc_i = RC_i / sum_j RC_j; equal risk contribution (ERC)
demands rc_i = 1/N, and risk budgeting demands rc_i = b_i for a given
positive budget vector b with sum(b) = 1.

Algorithm
---------
Spinu (2013) shows the long-only risk-budgeting weights are the unique
minimiser of the strictly convex function

    F(x) = (1/2) x' Sigma x - sum_i b_i log(x_i),   x > 0

(first-order condition: (Sigma x)_i = b_i / x_i, i.e. exact budgets), with
the portfolio weights recovered by normalising w = x / sum(x).  This module
solves F via the cyclical coordinate descent of Griveau-Billion, Richard &
Roncalli (2013): holding all coordinates but i fixed, the optimal x_i is
the positive root of a quadratic,

    x_i = ( -c_i + sqrt(c_i^2 + 4 sigma_ii b_i) ) / (2 sigma_ii),
    c_i = (Sigma x)_i - sigma_ii x_i,

iterated over coordinates until the fractional risk contributions match
the budgets to tolerance.  CCD is globally convergent on this objective,
needs no line search, and costs O(N) per coordinate update.

Volatility targeting
--------------------
The unlevered ERC portfolio has volatility sigma_p = sqrt(w' Sigma w)
(per bar, in the units of Sigma).  With ``target_vol`` set, the portfolio
is scaled by leverage = target_vol / sigma_p (optionally clamped by
``max_leverage``); the remainder (1 - leverage) is implicitly cash.  This
is the construction used by the canonical risk-parity funds (Asness,
Frazzini & Pedersen 2012).

Mathematical references
-----------------------
  * Maillard, S., Roncalli, T. & Teiletche, J. (2010). "The Properties of
    Equally Weighted Risk Contribution Portfolios."
    Journal of Portfolio Management, 36(4), 60-70.
  * Spinu, F. (2013). "An Algorithm for Computing Risk Parity Weights."
    SSRN 2297383.
  * Griveau-Billion, T., Richard, J.-C. & Roncalli, T. (2013). "A Fast
    Algorithm for Computing High-dimensional Risk Parity Portfolios."
    SSRN 2325255.
  * Asness, C., Frazzini, A. & Pedersen, L.H. (2012). "Leverage Aversion
    and Risk Parity." Financial Analysts Journal, 68(1), 47-59.

Closed forms used by the test suite (Maillard et al. 2010):
  * Diagonal Sigma:  w_i proportional to sqrt(b_i) / sigma_i (ERC: 1/sigma_i).
  * Constant pairwise correlation: ERC weights equal inverse-volatility
    weights regardless of the correlation level.
  * N = 2: w_1 = sigma_2 / (sigma_1 + sigma_2) for any correlation.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

__all__ = [
    "RiskParityConfig",
    "RiskParityResult",
    "risk_contributions",
    "risk_parity_weights",
]


# ---------------------------------------------------------------------------
# Configuration / result DTOs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RiskParityConfig:
    """Parameters for the risk-parity solver.

    Attributes
    ----------
    target_vol:
        Target portfolio volatility per bar (same units as sqrt of Sigma's
        entries).  ``None`` disables volatility targeting (leverage 1).
    max_leverage:
        Cap on the leverage applied by volatility targeting; ``None``
        disables the cap.
    tol:
        Convergence tolerance: the iteration stops when
        ``max_i |rc_i - b_i| < tol`` (fractional contributions vs budgets).
    max_iter:
        Maximum number of full coordinate-descent sweeps before declaring
        non-convergence (which raises).
    """

    target_vol: float | None = None
    max_leverage: float | None = None
    tol: float = 1e-10
    max_iter: int = 10_000

    def __post_init__(self) -> None:
        """Validate parameter consistency."""
        if self.target_vol is not None and (
            not np.isfinite(self.target_vol) or self.target_vol <= 0.0
        ):
            raise ValueError(
                f"target_vol must be a finite positive float, got {self.target_vol}"
            )
        if self.max_leverage is not None and (
            not np.isfinite(self.max_leverage) or self.max_leverage <= 0.0
        ):
            raise ValueError(
                f"max_leverage must be a finite positive float, got {self.max_leverage}"
            )
        if not np.isfinite(self.tol) or self.tol <= 0.0:
            raise ValueError(f"tol must be a finite positive float, got {self.tol}")
        if self.max_iter < 1:
            raise ValueError(f"max_iter must be >= 1, got {self.max_iter}")


@dataclass(frozen=True, slots=True)
class RiskParityResult:
    """Solved risk-parity portfolio.

    Attributes
    ----------
    weights:
        Unlevered weights: strictly positive, sum exactly 1, indexed by
        asset symbol in input order.
    risk_contributions:
        Fractional risk contributions rc_i of the unlevered portfolio;
        equal to the requested budgets within ``config.tol``.  Sums to 1.
    portfolio_vol:
        Unlevered portfolio volatility sqrt(w' Sigma w) per bar.
    leverage:
        Scaling applied by volatility targeting (1.0 when disabled).
    levered_weights:
        ``weights * leverage``; the implicit cash position is
        ``1 - leverage``.
    n_iterations:
        Number of full coordinate-descent sweeps used.
    """

    weights: pd.Series = field(compare=False)
    risk_contributions: pd.Series = field(compare=False)
    portfolio_vol: float
    leverage: float
    levered_weights: pd.Series = field(compare=False)
    n_iterations: int


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_pd_sigma(sigma: pd.DataFrame) -> np.ndarray:
    """Validate a covariance DataFrame for risk parity (needs strict PD).

    Risk-budgeting weights are defined and unique only for a positive
    definite covariance (Spinu 2013); a singular matrix admits zero-risk
    directions along which the log-barrier objective is unbounded.

    Raises
    ------
    ValueError
        On shape/label problems, NaN, asymmetry, or a non-PD matrix
        (advice: repair with ``nearest_psd(..., epsilon=...)`` first).
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
    if float(eigenvalues[0]) <= 0.0:
        raise ValueError(
            "risk parity requires a strictly positive definite sigma "
            f"(smallest eigenvalue {eigenvalues[0]:.3e}); repair it with "
            "core_trading.portfolio.covariance.nearest_psd(..., epsilon=...) "
            "before solving."
        )
    return sym


def _validate_budgets(
    budgets: pd.Series | None, sigma: pd.DataFrame
) -> np.ndarray:
    """Validate / default the risk budgets and normalise them to sum 1."""
    n_assets = sigma.shape[0]
    if budgets is None:
        return np.full(n_assets, 1.0 / float(n_assets))
    if list(budgets.index) != list(sigma.index):
        raise ValueError(
            "budgets index must match sigma's asset labels in the same order."
        )
    arr: np.ndarray = budgets.to_numpy(dtype=float)
    if not np.isfinite(arr).all():
        raise ValueError("budgets contain NaN or infinite values.")
    if bool((arr <= 0.0).any()):
        raise ValueError(
            "all risk budgets must be strictly positive "
            "(a zero budget asset should simply be excluded)."
        )
    out: np.ndarray = arr / float(arr.sum())
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def risk_contributions(weights: pd.Series, sigma: pd.DataFrame) -> pd.Series:
    """Fractional risk contributions rc_i of an arbitrary portfolio.

    Computes ``rc_i = w_i (Sigma w)_i / (w' Sigma w)`` (Euler decomposition;
    fractions sum to 1).  Exported for the Phase 6 cross-method comparison
    report, which inspects how concentrated each optimiser's risk is.

    Parameters
    ----------
    weights:
        Portfolio weights aligned to ``sigma`` (same labels, same order).
    sigma:
        Covariance matrix (positive definite).

    Returns
    -------
    pd.Series
        Fractional risk contributions, indexed like ``weights``.

    Raises
    ------
    ValueError
        On misaligned/invalid inputs or a portfolio with zero variance.
    """
    sigma_arr = _validate_pd_sigma(sigma)
    if list(weights.index) != list(sigma.index):
        raise ValueError(
            "weights index must match sigma's asset labels in the same order."
        )
    w: np.ndarray = weights.to_numpy(dtype=float)
    if not np.isfinite(w).all():
        raise ValueError("weights contain NaN or infinite values.")
    marginal = sigma_arr @ w
    variance = float(w @ marginal)
    if variance <= 0.0:
        raise ValueError(
            "portfolio variance is zero; risk contributions are undefined."
        )
    return pd.Series(w * marginal / variance, index=weights.index)


def risk_parity_weights(
    sigma: pd.DataFrame,
    *,
    budgets: pd.Series | None = None,
    config: RiskParityConfig | None = None,
) -> RiskParityResult:
    """Solve the long-only risk-budgeting portfolio (ERC by default).

    Runs the Griveau-Billion et al. (2013) cyclical coordinate descent on
    Spinu's convex formulation (see module docstring), then normalises to
    fully-invested weights and applies optional volatility targeting.

    Parameters
    ----------
    sigma:
        Covariance matrix per bar^2, strictly positive definite, e.g.
        ``ledoit_wolf_covariance(returns).covariance``.
    budgets:
        Target fractional risk contributions (positive; normalised to sum
        1 internally).  ``None`` (default) requests equal contributions.
    config:
        :class:`RiskParityConfig`; ``None`` uses the defaults.

    Returns
    -------
    RiskParityResult

    Raises
    ------
    ValueError
        On invalid inputs.
    RuntimeError
        If coordinate descent fails to reach ``config.tol`` within
        ``config.max_iter`` sweeps (never observed for valid PD inputs;
        indicates a pathological matrix).
    """
    cfg = config if config is not None else RiskParityConfig()
    sigma_arr = _validate_pd_sigma(sigma)
    budget_arr = _validate_budgets(budgets, sigma)
    n_assets = sigma_arr.shape[0]
    assets = [str(c) for c in sigma.index]

    diag = np.diag(sigma_arr).copy()
    vols = np.sqrt(diag)

    # Spinu's first-order condition is scale-free in x; start from the
    # diagonal closed form x_i = sqrt(b_i) / sigma_i.
    x = np.sqrt(budget_arr) / vols
    sigma_x = sigma_arr @ x

    n_iterations = 0
    converged = False
    for sweep in range(1, cfg.max_iter + 1):
        for i in range(n_assets):
            c_i = sigma_x[i] - diag[i] * x[i]
            x_new = (-c_i + np.sqrt(c_i * c_i + 4.0 * diag[i] * budget_arr[i])) / (
                2.0 * diag[i]
            )
            delta = x_new - x[i]
            if delta != 0.0:
                sigma_x = sigma_x + delta * sigma_arr[:, i]
                x[i] = x_new
        n_iterations = sweep
        variance = float(x @ sigma_x)
        rc = x * sigma_x / variance
        if float(np.abs(rc - budget_arr).max()) < cfg.tol:
            converged = True
            break

    if not converged:
        raise RuntimeError(
            f"risk-parity coordinate descent did not reach tol={cfg.tol} "
            f"within {cfg.max_iter} sweeps; last max budget error was "
            f"{float(np.abs(rc - budget_arr).max()):.3e}."
        )

    weights = x / float(x.sum())
    marginal = sigma_arr @ weights
    variance_w = float(weights @ marginal)
    portfolio_vol = float(np.sqrt(variance_w))
    fractional_rc = weights * marginal / variance_w

    leverage = 1.0
    if cfg.target_vol is not None:
        leverage = cfg.target_vol / portfolio_vol
        if cfg.max_leverage is not None:
            leverage = min(leverage, cfg.max_leverage)

    weights_series = pd.Series(weights, index=assets)
    return RiskParityResult(
        weights=weights_series,
        risk_contributions=pd.Series(fractional_rc, index=assets),
        portfolio_vol=portfolio_vol,
        leverage=float(leverage),
        levered_weights=weights_series * float(leverage),
        n_iterations=n_iterations,
    )
