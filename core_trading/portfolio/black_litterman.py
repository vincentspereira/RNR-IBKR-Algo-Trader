"""Black-Litterman expected returns (Phase 6.2).

Blends a market-equilibrium prior with subjective (or signal-driven) views
to produce posterior expected returns that a constrained mean-variance
optimiser can digest without producing the extreme corner solutions that
raw forecasts cause.  In the Phase 6 stack the "views" slot is where
Phase 5 alpha signals inject their information, with the Omega confidence
matrix controlling how hard each signal is allowed to pull the portfolio
away from equilibrium.

Model
-----
Prior (reverse optimisation; Black-Litterman 1992):
    pi = delta * Sigma * w_mkt
where w_mkt are observed market-capitalisation weights and delta is the
market's risk aversion -- so the prior is, by construction, the return
vector that makes the market portfolio mean-variance optimal.

Views: a (k x N) pick matrix P, view returns Q (k,), and view-uncertainty
covariance Omega (k x k).  The posterior follows from mixing the two
Gaussian sources of information (He & Litterman 1999, stable k x k form
-- only the small (P tau Sigma P' + Omega) matrix is ever inverted):

    mu_BL    = pi + tau Sigma P' (P tau Sigma P' + Omega)^{-1} (Q - P pi)
    M        = tau Sigma
               - tau Sigma P' (P tau Sigma P' + Omega)^{-1} P tau Sigma
    Sigma_BL = Sigma + M

where tau scales the uncertainty of the prior mean (small, conventionally
0.01-0.1) and M is the posterior covariance OF THE MEAN estimate.  With no
views the posterior degenerates to the prior: mu_BL = pi and
Sigma_BL = (1 + tau) Sigma.

Omega and view confidence
-------------------------
When ``omega`` is not supplied the He-Litterman proportional convention is
used,
    Omega = diag( P (tau Sigma) P' ) / c
with per-view confidences c_k > 0 (default 1): doubling a view's
confidence halves its uncertainty, pulling the posterior harder towards
that view (the Idzorek 2005 dial).  Limits behave correctly:
c -> infinity reproduces P mu_BL -> Q (the view is imposed), and
c -> 0 leaves the prior untouched.

Mathematical references
-----------------------
  * Black, F. & Litterman, R. (1992). "Global Portfolio Optimization."
    Financial Analysts Journal, 48(5), 28-43.
  * He, G. & Litterman, R. (1999). "The Intuition Behind Black-Litterman
    Model Portfolios." Goldman Sachs Investment Management Research.
  * Idzorek, T. (2005). "A Step-by-Step Guide to the Black-Litterman
    Model." Zephyr Associates working paper.
  * Meucci, A. (2010). "The Black-Litterman Approach: Original Model and
    Extensions." The Encyclopedia of Quantitative Finance, Wiley.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

__all__ = [
    "BlackLittermanResult",
    "black_litterman",
    "implied_equilibrium_returns",
]


# ---------------------------------------------------------------------------
# Result DTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BlackLittermanResult:
    """Posterior of the Black-Litterman blend.

    Attributes
    ----------
    posterior_means:
        mu_BL per bar, indexed by asset symbol.
    posterior_covariance:
        Sigma_BL = Sigma + M: the return covariance inflated by the
        remaining uncertainty of the mean estimate.  This is what the
        downstream optimiser should consume.
    equilibrium_returns:
        The prior pi actually used (computed from market weights, or the
        ``prior_means`` passed in).
    omega:
        The view-uncertainty matrix actually used (supplied or
        proportional default), indexed by view label; ``None`` when no
        views were given.
    tau:
        The prior-uncertainty scale used.
    """

    posterior_means: pd.Series = field(compare=False)
    posterior_covariance: pd.DataFrame = field(compare=False)
    equilibrium_returns: pd.Series = field(compare=False)
    omega: pd.DataFrame | None = field(compare=False)
    tau: float


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_sigma(sigma: pd.DataFrame) -> np.ndarray:
    """Validate the covariance matrix (square, labelled, symmetric, PSD-ish)."""
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
    if float(eigenvalues[0]) < -1e-8 * float(np.abs(eigenvalues).max()):
        raise ValueError(
            "sigma is materially indefinite (smallest eigenvalue "
            f"{eigenvalues[0]:.3e}); repair it with "
            "core_trading.portfolio.covariance.nearest_psd before use."
        )
    return sym


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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def implied_equilibrium_returns(
    sigma: pd.DataFrame,
    market_weights: pd.Series,
    *,
    risk_aversion: float = 2.5,
) -> pd.Series:
    """Reverse-optimised equilibrium returns pi = delta * Sigma * w_mkt.

    The prior that makes the observed market portfolio mean-variance
    optimal at risk aversion ``delta``: feeding pi and Sigma back into an
    unconstrained Markowitz optimiser with gamma = delta returns w_mkt
    exactly (round-trip verified in the test suite against
    :func:`core_trading.portfolio.mvo.mean_variance_weights`).

    Parameters
    ----------
    sigma:
        Covariance matrix per bar^2.
    market_weights:
        Market-capitalisation weights aligned to ``sigma``.  Typically
        non-negative and summing to 1, but any finite vector is accepted
        (the formula is linear).
    risk_aversion:
        Market risk-aversion delta > 0.  He-Litterman use 2.5.

    Returns
    -------
    pd.Series
        Equilibrium expected returns per bar, indexed like ``sigma``.

    Raises
    ------
    ValueError
        On invalid inputs.
    """
    if not np.isfinite(risk_aversion) or risk_aversion <= 0.0:
        raise ValueError(
            f"risk_aversion must be a finite positive float, got {risk_aversion}"
        )
    sigma_arr = _validate_sigma(sigma)
    w = _validate_aligned_series(market_weights, sigma, "market_weights")
    return pd.Series(risk_aversion * (sigma_arr @ w), index=sigma.index)


def black_litterman(
    sigma: pd.DataFrame,
    *,
    market_weights: pd.Series | None = None,
    risk_aversion: float = 2.5,
    prior_means: pd.Series | None = None,
    views: pd.DataFrame | None = None,
    view_returns: pd.Series | None = None,
    omega: pd.DataFrame | None = None,
    view_confidences: pd.Series | None = None,
    tau: float = 0.05,
) -> BlackLittermanResult:
    """Blend the equilibrium prior with views into posterior returns.

    See the module docstring for the model.  Exactly one of
    ``market_weights`` (prior computed by reverse optimisation) or
    ``prior_means`` (prior supplied directly) must be given.

    Parameters
    ----------
    sigma:
        Covariance matrix per bar^2 (index/columns = asset labels).
    market_weights:
        Market-cap weights for the reverse-optimised prior.
    risk_aversion:
        Delta for the reverse optimisation (ignored when ``prior_means``
        is supplied).
    prior_means:
        Directly supplied prior pi (alternative to ``market_weights``).
    views:
        Pick matrix P as a DataFrame: one row per view (index = view
        labels), columns = ALL of sigma's assets in the same order.
        Each row must have at least one non-zero entry.
    view_returns:
        Q: expected return of each view portfolio, indexed exactly like
        ``views``.
    omega:
        View-uncertainty covariance (k x k, index/columns = view labels).
        ``None`` selects the proportional default
        ``diag(P tau Sigma P') / view_confidences``.
    view_confidences:
        Per-view positive confidence multipliers for the default omega
        (ignored when ``omega`` is supplied -- passing both raises).
    tau:
        Prior-uncertainty scale; must be > 0.

    Returns
    -------
    BlackLittermanResult

    Raises
    ------
    ValueError
        On inconsistent prior specification, misaligned views/Q/omega,
        empty or all-zero view rows, non-positive confidences, invalid
        tau, or a singular (P tau Sigma P' + Omega) system.
    """
    if not np.isfinite(tau) or tau <= 0.0:
        raise ValueError(f"tau must be a finite positive float, got {tau}")
    if (market_weights is None) == (prior_means is None):
        raise ValueError(
            "exactly one of market_weights or prior_means must be supplied."
        )

    sigma_arr = _validate_sigma(sigma)
    assets = list(sigma.index)

    if market_weights is not None:
        pi = implied_equilibrium_returns(
            sigma, market_weights, risk_aversion=risk_aversion
        ).to_numpy()
    else:
        assert prior_means is not None  # narrowed by the XOR check above
        pi = _validate_aligned_series(prior_means, sigma, "prior_means")

    tau_sigma = tau * sigma_arr

    # ----- no views: posterior == prior ---------------------------------
    if views is None and view_returns is None:
        return BlackLittermanResult(
            posterior_means=pd.Series(pi, index=assets),
            posterior_covariance=pd.DataFrame(
                sigma_arr + tau_sigma, index=assets, columns=assets
            ),
            equilibrium_returns=pd.Series(pi, index=assets),
            omega=None,
            tau=tau,
        )
    if views is None or view_returns is None:
        raise ValueError("views and view_returns must be supplied together.")

    # ----- validate the view block --------------------------------------
    if views.shape[0] < 1:
        raise ValueError("views must contain at least one row (one view).")
    if list(views.columns) != assets:
        raise ValueError(
            "views columns must match sigma's asset labels in the same order."
        )
    view_labels = [str(v) for v in views.index]
    if list(view_returns.index) != list(views.index):
        raise ValueError("view_returns index must match views index exactly.")
    p: np.ndarray = views.to_numpy(dtype=float)
    q: np.ndarray = view_returns.to_numpy(dtype=float)
    if not np.isfinite(p).all():
        raise ValueError("views contain NaN or infinite values.")
    if not np.isfinite(q).all():
        raise ValueError("view_returns contain NaN or infinite values.")
    if bool((np.abs(p).sum(axis=1) == 0.0).any()):
        raise ValueError("every view row must have at least one non-zero entry.")
    k = p.shape[0]

    # ----- omega ----------------------------------------------------------
    if omega is not None and view_confidences is not None:
        raise ValueError(
            "supply either an explicit omega or view_confidences, not both."
        )
    if omega is not None:
        if list(omega.index) != view_labels or list(omega.columns) != view_labels:
            raise ValueError(
                "omega index and columns must match the view labels exactly."
            )
        omega_arr: np.ndarray = omega.to_numpy(dtype=float)
        if not np.isfinite(omega_arr).all():
            raise ValueError("omega contains NaN or infinite values.")
        if float(np.abs(omega_arr - omega_arr.T).max()) > 1e-10 * max(
            float(np.abs(omega_arr).max()), 1e-300
        ):
            raise ValueError("omega must be symmetric.")
        if bool((np.diag(omega_arr) <= 0.0).any()):
            raise ValueError("omega diagonal entries must be strictly positive.")
    else:
        confidences = np.ones(k)
        if view_confidences is not None:
            if list(view_confidences.index) != list(views.index):
                raise ValueError(
                    "view_confidences index must match views index exactly."
                )
            confidences = view_confidences.to_numpy(dtype=float)
            if not np.isfinite(confidences).all() or bool(
                (confidences <= 0.0).any()
            ):
                raise ValueError(
                    "view_confidences must be finite and strictly positive."
                )
        # He-Litterman proportional convention, scaled by confidence.
        omega_arr = np.diag(
            np.einsum("ij,jk,ik->i", p, tau_sigma, p) / confidences
        )

    # ----- posterior (stable k x k form) ---------------------------------
    # A = P tau Sigma P' + Omega is k x k; everything else is mat-vec.
    pts: np.ndarray = p @ tau_sigma  # (k, N)
    a = pts @ p.T + omega_arr  # (k, k)
    residual = q - p @ pi  # (k,)
    try:
        adjustment = np.linalg.solve(a, residual)  # (k,)
        gain = np.linalg.solve(a, pts)  # (k, N)
    except np.linalg.LinAlgError as exc:
        raise ValueError(
            "the view system (P tau Sigma P' + Omega) is singular; check for "
            "duplicate or contradictory zero-uncertainty views."
        ) from exc

    mu_bl = pi + pts.T @ adjustment
    m = tau_sigma - pts.T @ gain
    # Re-symmetrise M against float drift before adding to Sigma.
    m = (m + m.T) / 2.0
    sigma_bl = sigma_arr + m

    return BlackLittermanResult(
        posterior_means=pd.Series(mu_bl, index=assets),
        posterior_covariance=pd.DataFrame(sigma_bl, index=assets, columns=assets),
        equilibrium_returns=pd.Series(pi, index=assets),
        omega=pd.DataFrame(omega_arr, index=view_labels, columns=view_labels),
        tau=tau,
    )
