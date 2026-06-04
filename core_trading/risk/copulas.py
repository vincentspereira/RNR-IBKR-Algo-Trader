"""Copula models for multivariate tail-risk analysis (Phase 7.7).

A copula is a multivariate CDF with uniform marginals.  By Sklar's theorem
(Sklar 1959), every multivariate distribution F can be written as

    F(x_1, ..., x_d) = C(F_1(x_1), ..., F_d(x_d))

where C is the copula and F_i are the marginal CDFs.  Copulas separate the
joint-dependence structure from the margins, enabling flexible tail-risk
modelling.

Implemented models
------------------
1. ``GaussianCopula`` -- baseline; zero tail dependence (rho < 1).
2. ``StudentTCopula`` -- fat-tailed; symmetric upper/lower tail dependence;
   correlation fitted by Kendall tau inversion and nu by profile MLE.
3. ``CVineCopula`` / ``DVineCopula`` -- regular vine copulas with bivariate
   Gaussian and Student-t pair-copulas (Aas-Czado-Frigessi-Bakken 2009).
   Scope note: only C-vine and D-vine structures are implemented (a general
   R-vine with arbitrary tree structure is beyond the intended scope of a
   single module); pair-copula families are restricted to Gaussian and
   Student-t.
4. Tail dependence utilities: analytic formulas (McNeil-Frey-Embrechts 2015
   Chapter 7) and a nonparametric threshold estimator.
5. PIT utilities: empirical CDF transform and its inverse.

Mathematical references
-----------------------
Sklar, A. (1959). "Fonctions de repartition a n dimensions et leurs marges."
    Publ. Inst. Statist. Univ. Paris, 8, 229-231.

Joe, H. (1997). "Multivariate Models and Dependence Concepts."
    Chapman & Hall, London.

Aas, K., Czado, C., Frigessi, A. & Bakken, H. (2009). "Pair-Copula
    Constructions of Multiple Dependence." Insurance: Mathematics and
    Economics, 44(2), 182-198.

McNeil, A.J., Frey, R. & Embrechts, P. (2015). "Quantitative Risk
    Management: Concepts, Techniques and Tools" (revised ed.).
    Princeton University Press.  Chapter 7 (copulas and dependence).

Demarta, S. & McNeil, A.J. (2005). "The t Copula and Related Copulas."
    International Statistical Review, 73(1), 111-129.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import scipy.optimize as opt
import scipy.special as special
import scipy.stats as stats

__all__ = [
    # DTOs
    "CopulaFitResult",
    # PIT
    "empirical_pit",
    "empirical_pit_inverse",
    # Gaussian copula
    "GaussianCopula",
    # Student-t copula
    "StudentTCopula",
    # Vine copulas
    "CVineCopula",
    "DVineCopula",
    # Tail dependence
    "tail_dependence_gaussian",
    "tail_dependence_student_t",
    "tail_dependence_empirical",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOG2PI = math.log(2.0 * math.pi)
_CLIP_LO = 1e-10
_CLIP_HI = 1.0 - 1e-10

PairFamily = Literal["gaussian", "student_t"]


# ---------------------------------------------------------------------------
# Data-transfer objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CopulaFitResult:
    """Result of fitting a copula to pseudo-observations.

    Attributes
    ----------
    model:
        Model identifier, e.g. ``"gaussian"``, ``"student_t"``,
        ``"c_vine_gaussian"``, ``"d_vine_student_t"``.
    params:
        Dictionary of fitted parameter names to values.  For the Gaussian
        copula: ``{"rho": array}``.  For the Student-t copula:
        ``{"rho": array, "nu": float}``.  For vines: ``{"trees": list}``
        where each entry is a list of per-edge dicts.
    loglik:
        Log-likelihood of the pseudo-observations under the fitted copula.
    aic:
        Akaike Information Criterion: ``-2 * loglik + 2 * n_params``.
    n_obs:
        Number of observations used to fit.
    n_dim:
        Dimension d of the copula.
    """

    model: str
    params: dict = field(compare=False)
    loglik: float
    aic: float
    n_obs: int
    n_dim: int


# ---------------------------------------------------------------------------
# PIT utilities
# ---------------------------------------------------------------------------


def empirical_pit(
    data: np.ndarray,
    *,
    clip: bool = True,
) -> np.ndarray:
    """Probability Integral Transform using empirical (rank-based) CDFs.

    Each column of ``data`` is independently transformed to pseudo-
    observations in (0, 1) using the empirical CDF  u_it = rank(x_it) /
    (n + 1)  (Hazen formula, ensuring values strictly inside (0, 1)).

    Parameters
    ----------
    data:
        2-D array of shape (n_obs, n_dim).  Rows are observations; columns
        are marginals.  May also be 1-D (single marginal), returned as 1-D.
    clip:
        If True (default), clip output to [1e-10, 1 - 1e-10] so that
        subsequent log-density calls do not encounter boundary infinities.
        Has no practical effect because the Hazen formula already maps into
        (0, 1) for finite n; included for robustness against edge cases.

    Returns
    -------
    numpy.ndarray
        Pseudo-observations in (0, 1), same shape as input.

    Raises
    ------
    ValueError
        If ``data`` has more than 2 dimensions or fewer than 2 rows.
    """
    arr = np.asarray(data, dtype=float)
    squeeze = arr.ndim == 1
    if arr.ndim > 2:
        raise ValueError(
            f"data must be 1-D or 2-D; got ndim={arr.ndim}."
        )
    if arr.ndim == 1:
        arr = arr[:, np.newaxis]
    n, d = arr.shape
    if n < 2:
        raise ValueError(
            f"data must have at least 2 rows; got {n}."
        )
    # Rank each column, use Hazen formula: rank / (n + 1)
    out = np.empty_like(arr)
    for j in range(d):
        ranks = stats.rankdata(arr[:, j])  # 1-based, average ties
        out[:, j] = ranks / (float(n) + 1.0)
    if clip:
        out = np.clip(out, _CLIP_LO, _CLIP_HI)
    return out[:, 0] if squeeze else out


def empirical_pit_inverse(
    u: np.ndarray,
    data: np.ndarray,
) -> np.ndarray:
    """Invert the empirical PIT: map pseudo-observations back to data space.

    For each pseudo-observation u_i, returns the empirical quantile of
    ``data`` at probability u_i (linear interpolation between sorted values).

    Parameters
    ----------
    u:
        Pseudo-observations in (0, 1), shape (n_query,) or (n_query, n_dim).
    data:
        Original data used to define the empirical CDF, shape (n_obs,) or
        (n_obs, n_dim).  ``n_dim`` of ``u`` and ``data`` must match.

    Returns
    -------
    numpy.ndarray
        Quantile values in data space, same shape as ``u``.

    Raises
    ------
    ValueError
        If shapes are incompatible.
    """
    u_arr = np.asarray(u, dtype=float)
    d_arr = np.asarray(data, dtype=float)
    squeeze = u_arr.ndim == 1 and d_arr.ndim == 1
    if u_arr.ndim == 1:
        u_arr = u_arr[:, np.newaxis]
    if d_arr.ndim == 1:
        d_arr = d_arr[:, np.newaxis]
    if u_arr.shape[1] != d_arr.shape[1]:
        raise ValueError(
            f"u has {u_arr.shape[1]} columns but data has {d_arr.shape[1]}."
        )
    out = np.empty_like(u_arr)
    for j in range(d_arr.shape[1]):
        out[:, j] = np.quantile(d_arr[:, j], u_arr[:, j])
    return out[:, 0] if squeeze else out


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _check_pseudo_obs(u: np.ndarray, name: str = "u") -> np.ndarray:
    """Validate and return a 2-D pseudo-observation matrix."""
    arr = np.asarray(u, dtype=float)
    if arr.ndim == 1:
        arr = arr[:, np.newaxis]
    if arr.ndim != 2:
        raise ValueError(
            f"{name} must be 1-D or 2-D; got ndim={arr.ndim}."
        )
    n, d = arr.shape
    if n < 2:
        raise ValueError(f"{name} must have at least 2 rows; got {n}.")
    if d < 2:
        raise ValueError(f"{name} must have at least 2 columns; got {d}.")
    if not (np.all(arr > 0.0) and np.all(arr < 1.0)):
        raise ValueError(
            f"{name} must be strictly in (0, 1); "
            "use empirical_pit(..., clip=True) first."
        )
    return arr


def _kendall_tau_to_rho(tau: float) -> float:
    """Convert Kendall tau to Gaussian/t-copula linear correlation.

    For both the Gaussian and Student-t copulas, the theoretical relationship
    between the copula correlation parameter rho and Kendall's tau is:

        tau = (2 / pi) * arcsin(rho)  =>  rho = sin(pi * tau / 2)

    (McNeil-Frey-Embrechts 2015, Proposition 7.37.)
    """
    return float(np.sin(0.5 * math.pi * tau))


def _pairwise_kendall_tau_matrix(u: np.ndarray) -> np.ndarray:
    """Compute the d x d Kendall tau matrix from pseudo-observations."""
    n, d = u.shape
    tau_mat = np.eye(d)
    for i in range(d):
        for j in range(i + 1, d):
            tau_ij = float(stats.kendalltau(u[:, i], u[:, j]).statistic)
            rho_ij = _kendall_tau_to_rho(tau_ij)
            rho_ij = float(np.clip(rho_ij, -1.0 + 1e-8, 1.0 - 1e-8))
            tau_mat[i, j] = rho_ij
            tau_mat[j, i] = rho_ij
    return tau_mat


def _nearest_pd(mat: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    """Project to nearest symmetric positive-definite matrix (Higham 1988)."""
    sym: np.ndarray = (mat + mat.T) / 2.0
    vals, vecs = np.linalg.eigh(sym)
    vals_cl: np.ndarray = np.maximum(vals, eps)
    out: np.ndarray = (vecs * vals_cl[np.newaxis, :]) @ vecs.T
    result: np.ndarray = (out + out.T) / 2.0
    return result


def _normal_ppf(u: np.ndarray) -> np.ndarray:
    """Standard normal quantile (vectorised)."""
    return np.asarray(stats.norm.ppf(u), dtype=float)


def _t_ppf(u: np.ndarray, nu: float) -> np.ndarray:
    """Student-t quantile (vectorised)."""
    return np.asarray(stats.t.ppf(u, df=nu), dtype=float)


def _t_cdf(x: np.ndarray, nu: float) -> np.ndarray:
    """Student-t CDF (vectorised)."""
    return np.asarray(stats.t.cdf(x, df=nu), dtype=float)


def _t_logpdf(x: np.ndarray, nu: float) -> np.ndarray:
    """Standard Student-t log-PDF (vectorised)."""
    return np.asarray(stats.t.logpdf(x, df=nu), dtype=float)


# ---------------------------------------------------------------------------
# Gaussian copula
# ---------------------------------------------------------------------------


class GaussianCopula:
    """Gaussian copula with correlation matrix fitted from pseudo-observations.

    The Gaussian copula is

        C(u_1, ..., u_d; R) = Phi_d(Phi^{-1}(u_1), ..., Phi^{-1}(u_d); R)

    where Phi_d(.; R) is the d-dimensional standard Gaussian CDF with
    correlation matrix R and Phi^{-1} is the standard normal quantile.

    Fitting
    -------
    The correlation matrix R is estimated from pairwise Kendall tau values
    via the inversion formula  rho = sin(pi * tau / 2)  (valid for the
    Gaussian copula; McNeil-Frey-Embrechts 2015, Proposition 7.37).  The
    resulting matrix is projected to the nearest PD matrix (Higham 1988) if
    necessary.  This is faster and more robust than a full MLE for moderate
    to high dimension d.

    Tail dependence
    ---------------
    lambda_L = lambda_U = 0 for all rho < 1 (no tail dependence).
    """

    def __init__(self) -> None:
        self._rho: np.ndarray | None = None
        self._result: CopulaFitResult | None = None

    # ------------------------------------------------------------------
    # Fitting
    # ------------------------------------------------------------------

    def fit(self, u: np.ndarray) -> CopulaFitResult:
        """Fit the Gaussian copula to pseudo-observations.

        Parameters
        ----------
        u:
            2-D array of pseudo-observations in (0, 1), shape (n_obs, n_dim).
            Use :func:`empirical_pit` to obtain from raw data.

        Returns
        -------
        CopulaFitResult
            ``model="gaussian"``, ``params={"rho": correlation_matrix}``.

        Raises
        ------
        ValueError
            On invalid pseudo-observations.
        """
        arr = _check_pseudo_obs(u)
        n, d = arr.shape
        rho = _pairwise_kendall_tau_matrix(arr)
        rho = _nearest_pd(rho)
        self._rho = rho
        ll = float(self._loglik(arr, rho))
        n_params = d * (d - 1) // 2
        result = CopulaFitResult(
            model="gaussian",
            params={"rho": rho.copy()},
            loglik=ll,
            aic=float(-2.0 * ll + 2.0 * n_params),
            n_obs=n,
            n_dim=d,
        )
        self._result = result
        return result

    # ------------------------------------------------------------------
    # Density
    # ------------------------------------------------------------------

    @staticmethod
    def _loglik(u: np.ndarray, rho: np.ndarray) -> float:
        """Log-likelihood of pseudo-observations under the Gaussian copula.

        The Gaussian copula log-density at u is

            log c(u; R) = -0.5 * log|R| - 0.5 * z' (R^{-1} - I) z

        summed over all n observations, where z_i = Phi^{-1}(u_i).
        """
        n, d = u.shape
        z = _normal_ppf(u)  # (n, d)
        sign, logdet = np.linalg.slogdet(rho)
        if sign <= 0:
            return float("-inf")
        r_inv = np.linalg.inv(rho)
        # per-obs: z @ (R^{-1} - I) @ z' diagonal
        diff = r_inv - np.eye(d)
        quad = float(np.einsum("ni,ij,nj->", z, diff, z))
        return float(-0.5 * float(n) * logdet - 0.5 * quad)

    def log_density(self, u: np.ndarray) -> np.ndarray:
        """Evaluate the Gaussian copula log-density at pseudo-observations.

        Parameters
        ----------
        u:
            2-D array of pseudo-observations, shape (n_query, n_dim).

        Returns
        -------
        numpy.ndarray
            Log-density values, shape (n_query,).

        Raises
        ------
        RuntimeError
            If :meth:`fit` has not been called.
        ValueError
            On invalid ``u``.
        """
        if self._rho is None:
            raise RuntimeError("Call fit() before log_density().")
        arr = _check_pseudo_obs(u)
        d = arr.shape[1]
        if d != self._rho.shape[0]:
            raise ValueError(
                f"u has {d} dimensions but fitted copula has "
                f"{self._rho.shape[0]}."
            )
        rho = self._rho
        sign, logdet = np.linalg.slogdet(rho)
        if sign <= 0:
            return np.full(arr.shape[0], float("-inf"))
        r_inv = np.linalg.inv(rho)
        diff = r_inv - np.eye(d)
        z = _normal_ppf(arr)
        quad = np.einsum("ni,ij,nj->n", z, diff, z)
        out: np.ndarray = -0.5 * logdet - 0.5 * quad
        return out

    # ------------------------------------------------------------------
    # Sampling
    # ------------------------------------------------------------------

    def sample(
        self, n: int, *, seed: int | None = None
    ) -> np.ndarray:
        """Draw samples from the fitted Gaussian copula.

        Parameters
        ----------
        n:
            Number of samples to draw.
        seed:
            Seed for the numpy Generator.  Pass ``None`` for
            non-reproducible draws.

        Returns
        -------
        numpy.ndarray
            Pseudo-observations in (0, 1), shape (n, d).

        Raises
        ------
        RuntimeError
            If :meth:`fit` has not been called.
        """
        if self._rho is None:
            raise RuntimeError("Call fit() before sample().")
        rho = self._rho
        d = rho.shape[0]
        rng = np.random.default_rng(seed)
        chol = np.linalg.cholesky(_nearest_pd(rho))
        z = rng.standard_normal((n, d)) @ chol.T
        u: np.ndarray = stats.norm.cdf(z)
        return np.clip(u, _CLIP_LO, _CLIP_HI)


# ---------------------------------------------------------------------------
# Student-t copula
# ---------------------------------------------------------------------------


class StudentTCopula:
    """Student-t copula with fat-tailed joint dependence.

    The t-copula with parameters (R, nu) is

        C(u; R, nu) = t_{d,nu,R}(t_nu^{-1}(u_1), ..., t_nu^{-1}(u_d))

    where t_{d,nu,R} is the d-dimensional Student-t CDF with nu degrees of
    freedom and correlation matrix R, and t_nu^{-1} is the univariate
    t_nu quantile.

    Fitting
    -------
    1. Correlation: estimate rho_ij = sin(pi * tau_ij / 2) from Kendall tau
       (tau inversion is exact for the t-copula; McNeil-Frey-Embrechts 2015,
       Proposition 7.37).
    2. Degrees of freedom: profile MLE over nu in [2.01, 80] using the
       gradient-free Brent method on the copula log-likelihood (with R
       fixed from step 1).

    Tail dependence
    ---------------
    Lambda_L = Lambda_U = 2 * t_{nu+1}(-sqrt((nu+1)(1-rho)/(1+rho)))
    (symmetric upper and lower tail dependence for rho > -1).  See
    :func:`tail_dependence_student_t`.
    """

    def __init__(self) -> None:
        self._rho: np.ndarray | None = None
        self._nu: float | None = None
        self._result: CopulaFitResult | None = None

    # ------------------------------------------------------------------
    # Fitting
    # ------------------------------------------------------------------

    def fit(
        self,
        u: np.ndarray,
        *,
        nu_bounds: tuple[float, float] = (2.01, 80.0),
    ) -> CopulaFitResult:
        """Fit the Student-t copula to pseudo-observations.

        Parameters
        ----------
        u:
            2-D array of pseudo-observations in (0, 1), shape (n_obs, n_dim).
        nu_bounds:
            Search interval for the degrees-of-freedom profile MLE.
            Lower bound must be > 2 (variance existence); default (2.01, 80).

        Returns
        -------
        CopulaFitResult
            ``model="student_t"``,
            ``params={"rho": correlation_matrix, "nu": float}``.

        Raises
        ------
        ValueError
            On invalid pseudo-observations or nu_bounds.
        """
        arr = _check_pseudo_obs(u)
        n, d = arr.shape
        nu_lo, nu_hi = nu_bounds
        if nu_lo <= 2.0:
            raise ValueError(
                f"nu_bounds lower must be > 2; got {nu_lo}."
            )
        # Step 1: estimate correlation from Kendall tau inversion
        rho = _pairwise_kendall_tau_matrix(arr)
        rho = _nearest_pd(rho)
        self._rho = rho

        # Step 2: profile MLE over nu with rho fixed
        def neg_ll(nu_val: float) -> float:
            return -self._copula_loglik(arr, rho, nu_val)

        result_brent = opt.minimize_scalar(
            neg_ll,
            bounds=(nu_lo, nu_hi),
            method="bounded",
            options={"xatol": 1e-4},
        )
        nu_hat = float(result_brent.x)
        self._nu = nu_hat
        ll = float(self._copula_loglik(arr, rho, nu_hat))
        n_params = d * (d - 1) // 2 + 1  # rho entries + nu
        result = CopulaFitResult(
            model="student_t",
            params={"rho": rho.copy(), "nu": nu_hat},
            loglik=ll,
            aic=float(-2.0 * ll + 2.0 * n_params),
            n_obs=n,
            n_dim=d,
        )
        self._result = result
        return result

    # ------------------------------------------------------------------
    # Log-likelihood
    # ------------------------------------------------------------------

    @staticmethod
    def _copula_loglik(u: np.ndarray, rho: np.ndarray, nu: float) -> float:
        """Log-likelihood of pseudo-observations under the t-copula.

        The t-copula log-density is (Demarta-McNeil 2005, eq. 2):

            log c(u; R, nu) = log t_{d,nu,R}(x) - sum_j log t_nu(x_j)

        where x_j = t_nu^{-1}(u_j) and t_{d,nu,R} is the multivariate
        Student-t density.  The multivariate t density is

            log f(x; R, nu) = log Gamma((nu+d)/2) - log Gamma(nu/2)
              - (d/2) log(nu pi) - 0.5 log|R|
              - ((nu+d)/2) log(1 + x'R^{-1}x / nu)
        """
        n, d = u.shape
        fd = float(d)
        x = _t_ppf(u, nu)  # (n, d)

        sign, logdet = np.linalg.slogdet(rho)
        if sign <= 0:
            return float("-inf")
        r_inv = np.linalg.inv(rho)

        # Multivariate t log-density sum
        log_gamma_nd = float(special.gammaln(0.5 * (nu + fd)))
        log_gamma_n = float(special.gammaln(0.5 * nu))
        const = (
            log_gamma_nd
            - log_gamma_n
            - 0.5 * fd * math.log(nu * math.pi)
            - 0.5 * logdet
        )
        quad = np.einsum("ni,ij,nj->n", x, r_inv, x)  # (n,)
        log_mv_t = const - 0.5 * (nu + fd) * np.log1p(quad / nu)  # (n,)

        # Subtract univariate t log-PDFs
        log_uni_t = _t_logpdf(x, nu).sum(axis=1)  # (n,)

        return float((log_mv_t - log_uni_t).sum())

    # ------------------------------------------------------------------
    # Density
    # ------------------------------------------------------------------

    def log_density(self, u: np.ndarray) -> np.ndarray:
        """Evaluate the Student-t copula log-density at pseudo-observations.

        Parameters
        ----------
        u:
            2-D array of pseudo-observations, shape (n_query, n_dim).

        Returns
        -------
        numpy.ndarray
            Log-density values, shape (n_query,).

        Raises
        ------
        RuntimeError
            If :meth:`fit` has not been called.
        """
        if self._rho is None or self._nu is None:
            raise RuntimeError("Call fit() before log_density().")
        arr = _check_pseudo_obs(u)
        d = arr.shape[1]
        if d != self._rho.shape[0]:
            raise ValueError(
                f"u has {d} dimensions but fitted copula has "
                f"{self._rho.shape[0]}."
            )
        n = arr.shape[0]
        nu = self._nu
        fd = float(d)
        rho = self._rho
        sign, logdet = np.linalg.slogdet(rho)
        if sign <= 0:
            return np.full(n, float("-inf"))
        r_inv = np.linalg.inv(rho)
        x = _t_ppf(arr, nu)
        log_gamma_nd = float(special.gammaln(0.5 * (nu + fd)))
        log_gamma_n = float(special.gammaln(0.5 * nu))
        const = (
            log_gamma_nd
            - log_gamma_n
            - 0.5 * fd * math.log(nu * math.pi)
            - 0.5 * logdet
        )
        quad = np.einsum("ni,ij,nj->n", x, r_inv, x)
        log_mv_t = const - 0.5 * (nu + fd) * np.log1p(quad / nu)
        log_uni_t = _t_logpdf(x, nu).sum(axis=1)
        out: np.ndarray = log_mv_t - log_uni_t
        return out

    # ------------------------------------------------------------------
    # Sampling
    # ------------------------------------------------------------------

    def sample(
        self, n: int, *, seed: int | None = None
    ) -> np.ndarray:
        """Draw samples from the fitted Student-t copula.

        Generates multivariate t samples via the stochastic representation

            X = sqrt(nu / W) * L * Z,  W ~ chi^2(nu) / nu,  Z ~ N(0, I)

        then maps each margin through t_nu.cdf.

        Parameters
        ----------
        n:
            Number of samples.
        seed:
            Seed for the numpy Generator.

        Returns
        -------
        numpy.ndarray
            Pseudo-observations in (0, 1), shape (n, d).

        Raises
        ------
        RuntimeError
            If :meth:`fit` has not been called.
        """
        if self._rho is None or self._nu is None:
            raise RuntimeError("Call fit() before sample().")
        rho = self._rho
        nu = self._nu
        d = rho.shape[0]
        rng = np.random.default_rng(seed)
        chol = np.linalg.cholesky(_nearest_pd(rho))
        z = rng.standard_normal((n, d)) @ chol.T  # correlated normals
        w = rng.chisquare(df=nu, size=n) / nu     # chi^2/nu mixing variable
        x = z / np.sqrt(w[:, np.newaxis])         # multivariate t
        u: np.ndarray = _t_cdf(x, nu)
        return np.clip(u, _CLIP_LO, _CLIP_HI)


# ---------------------------------------------------------------------------
# Vine copula helpers (pair-copula h-functions)
# ---------------------------------------------------------------------------


def _h_gaussian(u: np.ndarray, v: np.ndarray, rho: float) -> np.ndarray:
    """H-function for the bivariate Gaussian pair-copula.

    h(u|v; rho) = Phi( (Phi^{-1}(u) - rho * Phi^{-1}(v)) / sqrt(1 - rho^2) )

    This is the conditional CDF F(U <= u | V = v) for the Gaussian copula
    (Aas et al. 2009, Eq. 10).
    """
    eps = 1e-10
    rho = float(np.clip(rho, -1.0 + eps, 1.0 - eps))
    qu = _normal_ppf(np.clip(u, _CLIP_LO, _CLIP_HI))
    qv = _normal_ppf(np.clip(v, _CLIP_LO, _CLIP_HI))
    arg = (qu - rho * qv) / math.sqrt(1.0 - rho * rho)
    cdf_val: np.ndarray = np.asarray(stats.norm.cdf(arg), dtype=float)
    return np.clip(cdf_val, _CLIP_LO, _CLIP_HI)


def _h_student_t(
    u: np.ndarray, v: np.ndarray, rho: float, nu: float
) -> np.ndarray:
    """H-function for the bivariate Student-t pair-copula.

    h(u|v; rho, nu) = t_{nu+1}(
        (t_nu^{-1}(u) - rho * t_nu^{-1}(v))
        / sqrt( (nu + t_nu^{-1}(v)^2)(1 - rho^2) / (nu + 1) )
    )

    (Aas et al. 2009, Eq. 11.)
    """
    eps = 1e-10
    rho = float(np.clip(rho, -1.0 + eps, 1.0 - eps))
    qu = _t_ppf(np.clip(u, _CLIP_LO, _CLIP_HI), nu)
    qv = _t_ppf(np.clip(v, _CLIP_LO, _CLIP_HI), nu)
    numer = qu - rho * qv
    denom = np.sqrt((nu + qv * qv) * (1.0 - rho * rho) / (nu + 1.0))
    arg = numer / denom
    return np.clip(_t_cdf(arg, nu + 1.0), _CLIP_LO, _CLIP_HI)


def _fit_pair_gaussian(
    u: np.ndarray, v: np.ndarray
) -> tuple[float, float]:
    """Fit bivariate Gaussian pair-copula by Kendall tau inversion.

    Returns
    -------
    (rho, loglik)
    """
    tau = float(stats.kendalltau(u, v).statistic)
    rho = float(np.clip(_kendall_tau_to_rho(tau), -1.0 + 1e-8, 1.0 - 1e-8))
    n = len(u)
    # Bivariate Gaussian copula loglik
    qu = _normal_ppf(np.clip(u, _CLIP_LO, _CLIP_HI))
    qv = _normal_ppf(np.clip(v, _CLIP_LO, _CLIP_HI))
    ll = float(
        -0.5 * n * math.log(1.0 - rho * rho)
        - 0.5 / (1.0 - rho * rho)
        * float(
            np.sum(
                qu * qu * rho * rho
                - 2.0 * rho * qu * qv
                + qv * qv * rho * rho
            )
        )
    )
    return rho, ll


def _fit_pair_student_t(
    u: np.ndarray,
    v: np.ndarray,
    *,
    nu_bounds: tuple[float, float] = (2.01, 50.0),
) -> tuple[float, float, float]:
    """Fit bivariate Student-t pair-copula by tau inversion + profile MLE.

    Returns
    -------
    (rho, nu, loglik)
    """
    tau = float(stats.kendalltau(u, v).statistic)
    rho = float(np.clip(_kendall_tau_to_rho(tau), -1.0 + 1e-8, 1.0 - 1e-8))
    u2 = np.stack([u, v], axis=1)

    def neg_ll(nu_val: float) -> float:
        return -StudentTCopula._copula_loglik(u2, np.array([[1.0, rho], [rho, 1.0]]), nu_val)

    res = opt.minimize_scalar(
        neg_ll,
        bounds=nu_bounds,
        method="bounded",
        options={"xatol": 1e-3},
    )
    nu_hat = float(res.x)
    ll = float(
        StudentTCopula._copula_loglik(
            u2, np.array([[1.0, rho], [rho, 1.0]]), nu_hat
        )
    )
    return rho, nu_hat, ll


def _pair_loglik_gaussian(
    u: np.ndarray, v: np.ndarray, rho: float
) -> float:
    """Bivariate Gaussian copula log-likelihood."""
    arr = np.stack([u, v], axis=1)
    cop = np.array([[1.0, rho], [rho, 1.0]])
    return GaussianCopula._loglik(arr, cop)


def _pair_loglik_student_t(
    u: np.ndarray, v: np.ndarray, rho: float, nu: float
) -> float:
    """Bivariate Student-t copula log-likelihood."""
    arr = np.stack([u, v], axis=1)
    cop = np.array([[1.0, rho], [rho, 1.0]])
    return StudentTCopula._copula_loglik(arr, cop, nu)


# ---------------------------------------------------------------------------
# C-vine copula
# ---------------------------------------------------------------------------


class CVineCopula:
    """C-vine copula with Gaussian or Student-t bivariate pair-copulas.

    A C-vine is a special case of the regular vine (R-vine) where every
    tree has exactly one node connected to all other nodes (the "centre"
    node).  For d assets the structure has d-1 trees; tree k has d-k edges.

    Fitting follows the sequential algorithm of Aas et al. (2009) Section 3:
    tree 1 is fitted first on the original pseudo-observations; each
    subsequent tree uses h-function-transformed pseudo-observations from the
    previous tree.

    Scope limitation
    ----------------
    Only C-vine and D-vine structures are implemented.  A general R-vine
    with an arbitrary tree sequence selected by, e.g., the maximum spanning
    tree heuristic (Dissmann et al. 2013) is beyond the intended scope of
    a single module.  Pair-copula families are restricted to Gaussian and
    Student-t.

    Parameters
    ----------
    family:
        Pair-copula family for all edges: ``"gaussian"`` or ``"student_t"``.
    """

    def __init__(self, family: PairFamily = "gaussian") -> None:
        if family not in ("gaussian", "student_t"):
            raise ValueError(
                f"family must be 'gaussian' or 'student_t'; got {family!r}."
            )
        self.family: PairFamily = family
        self._trees: list[list[dict]] = []
        self._n_dim: int = 0
        self._result: CopulaFitResult | None = None

    # ------------------------------------------------------------------
    # Fitting
    # ------------------------------------------------------------------

    def fit(self, u: np.ndarray) -> CopulaFitResult:
        """Fit the C-vine copula by sequential tree construction.

        Parameters
        ----------
        u:
            2-D pseudo-observations in (0, 1), shape (n_obs, n_dim).

        Returns
        -------
        CopulaFitResult
            ``model="c_vine_<family>"``,
            ``params={"trees": list_of_edge_lists}``.
            Each edge dict has keys: ``"i"``, ``"j"``, ``"conditioned"``
            (frozenset of conditioning variables), ``"rho"`` (and ``"nu"``
            for Student-t), ``"loglik"``.

        Raises
        ------
        ValueError
            On invalid pseudo-observations.
        """
        arr = _check_pseudo_obs(u)
        n, d = arr.shape
        self._n_dim = d

        # v_mat[j] holds the current (possibly h-transformed) values for
        # column j; initialised to the raw pseudo-observations.
        v_mat = arr.copy()
        # h_mat[j] will hold h(u_j | u_root) for the next tree
        trees: list[list[dict]] = []
        total_ll = 0.0
        n_params = 0

        for k in range(d - 1):
            # Root node for tree k is column 0 of the current v_mat
            edges: list[dict] = []
            new_v = np.empty_like(v_mat)
            new_v[:, 0] = v_mat[:, 0]  # root carries through
            for j in range(1, d - k):
                u_root = v_mat[:, 0]
                u_j = v_mat[:, j]
                if self.family == "gaussian":
                    rho, ll = _fit_pair_gaussian(u_root, u_j)
                    edge: dict = {
                        "i": 0,
                        "j": j,
                        "conditioned": frozenset(range(k)),
                        "rho": rho,
                        "loglik": ll,
                    }
                    n_params += 1
                    new_v[:, j] = _h_gaussian(u_j, u_root, rho)
                else:
                    rho, nu, ll = _fit_pair_student_t(u_root, u_j)
                    edge = {
                        "i": 0,
                        "j": j,
                        "conditioned": frozenset(range(k)),
                        "rho": rho,
                        "nu": nu,
                        "loglik": ll,
                    }
                    n_params += 2
                    new_v[:, j] = _h_student_t(u_j, u_root, rho, nu)
                edges.append(edge)
                total_ll += ll
            v_mat = new_v
            trees.append(edges)

        self._trees = trees
        result = CopulaFitResult(
            model=f"c_vine_{self.family}",
            params={"trees": trees},
            loglik=total_ll,
            aic=float(-2.0 * total_ll + 2.0 * n_params),
            n_obs=n,
            n_dim=d,
        )
        self._result = result
        return result

    # ------------------------------------------------------------------
    # Log-likelihood
    # ------------------------------------------------------------------

    def loglik(self, u: np.ndarray) -> float:
        """Evaluate the vine log-likelihood on new pseudo-observations.

        Parameters
        ----------
        u:
            2-D pseudo-observations, shape (n_obs, n_dim).

        Returns
        -------
        float
            Sum of pair-copula log-likelihoods over all edges and trees.

        Raises
        ------
        RuntimeError
            If :meth:`fit` has not been called.
        """
        if not self._trees:
            raise RuntimeError("Call fit() before loglik().")
        arr = _check_pseudo_obs(u)
        n, d = arr.shape
        if d != self._n_dim:
            raise ValueError(
                f"u has {d} dimensions but fitted vine has {self._n_dim}."
            )
        v_mat = arr.copy()
        total = 0.0
        for edges in self._trees:
            new_v = np.empty_like(v_mat)
            new_v[:, 0] = v_mat[:, 0]
            for edge in edges:
                j = int(edge["j"])
                u_root = v_mat[:, 0]
                u_j = v_mat[:, j]
                rho = float(edge["rho"])
                if self.family == "gaussian":
                    total += _pair_loglik_gaussian(u_root, u_j, rho)
                    new_v[:, j] = _h_gaussian(u_j, u_root, rho)
                else:
                    nu = float(edge["nu"])
                    total += _pair_loglik_student_t(u_root, u_j, rho, nu)
                    new_v[:, j] = _h_student_t(u_j, u_root, rho, nu)
            v_mat = new_v
        return total

    # ------------------------------------------------------------------
    # Sampling
    # ------------------------------------------------------------------

    def sample(
        self, n: int, *, seed: int | None = None
    ) -> np.ndarray:
        """Sample from the fitted C-vine via the recursive inversion algorithm.

        The algorithm (Aas et al. 2009, Section 4) generates d uniform
        samples w_1, ..., w_d and inverts the h-functions from the last
        tree back to the first tree.

        Parameters
        ----------
        n:
            Number of samples.
        seed:
            Seed for the numpy Generator.

        Returns
        -------
        numpy.ndarray
            Pseudo-observations in (0, 1), shape (n, d).

        Raises
        ------
        RuntimeError
            If :meth:`fit` has not been called.
        """
        if not self._trees:
            raise RuntimeError("Call fit() before sample().")
        d = self._n_dim
        rng = np.random.default_rng(seed)
        # w is the array of uniform draws; x stores the resulting samples
        w = rng.random((n, d))
        x = np.empty_like(w)
        x[:, 0] = w[:, 0]

        # For the C-vine, the inversion is sequential.
        # Build a 2-D list: edge_params[k][j-1] for tree k, edge j (j=1..d-k-1)
        edge_params: list[list[dict]] = self._trees

        for j in range(1, d):
            # x[:, j] is obtained by inverting h-functions through trees 0..j-1
            v = w[:, j].copy()
            for k in range(j - 1, -1, -1):
                # Find the edge in tree k that involves column j (relative index)
                # In C-vine tree k, the edges connect root (col 0) to cols 1..d-k-1
                # We need the edge for col j in tree k
                if k < len(edge_params) and j - k - 1 < len(edge_params[k]):
                    edge = edge_params[k][j - k - 1]
                    rho = float(edge["rho"])
                    if self.family == "gaussian":
                        v = _h_gaussian_inv(v, x[:, k], rho)
                    else:
                        nu = float(edge["nu"])
                        v = _h_student_t_inv(v, x[:, k], rho, nu)
            x[:, j] = v

        return np.clip(x, _CLIP_LO, _CLIP_HI)


# ---------------------------------------------------------------------------
# D-vine copula
# ---------------------------------------------------------------------------


class DVineCopula:
    """D-vine copula with Gaussian or Student-t bivariate pair-copulas.

    A D-vine is a special case of the regular vine where every tree has a
    path structure (no node has degree > 2).  For d assets, tree k connects
    pairs (i, i+k) conditioned on {i+1, ..., i+k-1} for i = 1, ..., d-k.

    Fitting follows the sequential algorithm of Aas et al. (2009) Section 3:
    each tree is fitted on h-function-transformed pseudo-observations from
    the previous tree.  After fitting tree k, the h-functions h(u_{i+k} |
    u_{i+1:i+k-1}) and h(u_i | u_{i+1:i+k-1}) are computed for use in
    tree k+1.

    Parameters
    ----------
    family:
        Pair-copula family: ``"gaussian"`` or ``"student_t"``.
    """

    def __init__(self, family: PairFamily = "gaussian") -> None:
        if family not in ("gaussian", "student_t"):
            raise ValueError(
                f"family must be 'gaussian' or 'student_t'; got {family!r}."
            )
        self.family: PairFamily = family
        self._trees: list[list[dict]] = []
        self._n_dim: int = 0
        self._result: CopulaFitResult | None = None

    # ------------------------------------------------------------------
    # Fitting
    # ------------------------------------------------------------------

    def fit(self, u: np.ndarray) -> CopulaFitResult:
        """Fit the D-vine copula by sequential tree construction.

        Parameters
        ----------
        u:
            2-D pseudo-observations in (0, 1), shape (n_obs, n_dim).

        Returns
        -------
        CopulaFitResult
            ``model="d_vine_<family>"``,
            ``params={"trees": list_of_edge_lists}``.

        Raises
        ------
        ValueError
            On invalid pseudo-observations.
        """
        arr = _check_pseudo_obs(u)
        n, d = arr.shape
        self._n_dim = d

        # v[i][j] = h-function transformed value: h(u_j | u_{j-1:j-i})
        # Initialise with raw pseudo-observations (tree 0).
        # v_lo[i] = h(u_i | ...) from the "left" conditioning
        # v_hi[i] = h(u_i | ...) from the "right" conditioning
        # For tree 1: pair (i, i+1) uses original u_i, u_{i+1}.
        v_lo = arr.copy()  # v_lo[n, i] = current left conditioning of col i
        v_hi = arr.copy()  # v_hi[n, i] = current right conditioning of col i

        trees: list[list[dict]] = []
        total_ll = 0.0
        n_params = 0

        for k in range(1, d):
            edges: list[dict] = []
            new_lo = np.empty((n, d - k), dtype=float)
            new_hi = np.empty((n, d - k), dtype=float)
            for i in range(d - k):
                u_i = v_lo[:, i]
                u_ik = v_hi[:, i + 1]
                if self.family == "gaussian":
                    rho, ll = _fit_pair_gaussian(u_i, u_ik)
                    edge: dict = {
                        "i": i,
                        "j": i + k,
                        "conditioned": frozenset(range(i + 1, i + k)),
                        "rho": rho,
                        "loglik": ll,
                    }
                    n_params += 1
                    new_lo[:, i] = _h_gaussian(u_i, u_ik, rho)
                    new_hi[:, i] = _h_gaussian(u_ik, u_i, rho)
                else:
                    rho, nu, ll = _fit_pair_student_t(u_i, u_ik)
                    edge = {
                        "i": i,
                        "j": i + k,
                        "conditioned": frozenset(range(i + 1, i + k)),
                        "rho": rho,
                        "nu": nu,
                        "loglik": ll,
                    }
                    n_params += 2
                    new_lo[:, i] = _h_student_t(u_i, u_ik, rho, nu)
                    new_hi[:, i] = _h_student_t(u_ik, u_i, rho, nu)
                edges.append(edge)
                total_ll += ll
            v_lo = new_lo
            v_hi = new_hi
            trees.append(edges)

        self._trees = trees
        result = CopulaFitResult(
            model=f"d_vine_{self.family}",
            params={"trees": trees},
            loglik=total_ll,
            aic=float(-2.0 * total_ll + 2.0 * n_params),
            n_obs=n,
            n_dim=d,
        )
        self._result = result
        return result

    # ------------------------------------------------------------------
    # Log-likelihood
    # ------------------------------------------------------------------

    def loglik(self, u: np.ndarray) -> float:
        """Evaluate the D-vine log-likelihood on new pseudo-observations.

        Parameters
        ----------
        u:
            2-D pseudo-observations, shape (n_obs, n_dim).

        Returns
        -------
        float
            Sum of pair-copula log-likelihoods over all edges and trees.

        Raises
        ------
        RuntimeError
            If :meth:`fit` has not been called.
        """
        if not self._trees:
            raise RuntimeError("Call fit() before loglik().")
        arr = _check_pseudo_obs(u)
        n, d = arr.shape
        if d != self._n_dim:
            raise ValueError(
                f"u has {d} dimensions but fitted vine has {self._n_dim}."
            )
        v_lo = arr.copy()
        v_hi = arr.copy()
        total = 0.0
        for k, edges in enumerate(self._trees, start=1):
            new_lo = np.empty((n, d - k), dtype=float)
            new_hi = np.empty((n, d - k), dtype=float)
            for idx_e, edge in enumerate(edges):
                i = idx_e
                u_i = v_lo[:, i]
                u_ik = v_hi[:, i + 1]
                rho = float(edge["rho"])
                if self.family == "gaussian":
                    total += _pair_loglik_gaussian(u_i, u_ik, rho)
                    new_lo[:, i] = _h_gaussian(u_i, u_ik, rho)
                    new_hi[:, i] = _h_gaussian(u_ik, u_i, rho)
                else:
                    nu = float(edge["nu"])
                    total += _pair_loglik_student_t(u_i, u_ik, rho, nu)
                    new_lo[:, i] = _h_student_t(u_i, u_ik, rho, nu)
                    new_hi[:, i] = _h_student_t(u_ik, u_i, rho, nu)
            v_lo = new_lo
            v_hi = new_hi
        return total

    # ------------------------------------------------------------------
    # Sampling
    # ------------------------------------------------------------------

    def sample(
        self, n: int, *, seed: int | None = None
    ) -> np.ndarray:
        """Sample from the fitted D-vine via recursive h-function inversion.

        Implements Algorithm 2 from Aas et al. (2009) Section 4.  The
        algorithm maintains a d x d table v where v[i][j] holds the
        conditional CDF value F(x_j | x_{j-1}, ..., x_{j-i}) needed for
        the sequential inversion.

        Parameters
        ----------
        n:
            Number of samples.
        seed:
            Seed for the numpy Generator.

        Returns
        -------
        numpy.ndarray
            Pseudo-observations in (0, 1), shape (n, d).

        Raises
        ------
        RuntimeError
            If :meth:`fit` has not been called.
        """
        if not self._trees:
            raise RuntimeError("Call fit() before sample().")
        d = self._n_dim
        rng = np.random.default_rng(seed)
        w = rng.random((n, d))

        # v[j][k] = n-length array holding the conditional quantile at the
        # k-th level for the j-th variable.  v[j][j] = w[:,j] (input uniform).
        # After processing column j:
        #   v[j][0] = x[:,j]  (the sample)
        #   v[j][k] = h(x[:,j] | conditioning set of depth k)
        # v[k][k] stores the current conditioning value at depth k -- it is
        # the "diagonal" value from the previous inversion step.
        v: list[list[np.ndarray]] = [
            [np.empty(n, dtype=float) for _ in range(d)] for _ in range(d)
        ]
        x = np.empty((n, d), dtype=float)

        def _h_inv_e(u_v: np.ndarray, cond: np.ndarray, edge: dict) -> np.ndarray:
            rho_e = float(edge["rho"])
            if self.family == "gaussian":
                return _h_gaussian_inv(u_v, cond, rho_e)
            nu_e = float(edge["nu"])
            return _h_student_t_inv(u_v, cond, rho_e, nu_e)

        def _h_fwd_e(u_v: np.ndarray, cond: np.ndarray, edge: dict) -> np.ndarray:
            rho_e = float(edge["rho"])
            if self.family == "gaussian":
                return _h_gaussian(u_v, cond, rho_e)
            nu_e = float(edge["nu"])
            return _h_student_t(u_v, cond, rho_e, nu_e)

        # j=0: x[0] = w[0]; diagonal v[0][0] = x[0]
        x[:, 0] = w[:, 0]
        v[0][0] = w[:, 0].copy()

        for j in range(1, d):
            # Set starting value (innermost level)
            v[j][j] = w[:, j].copy()

            # Invert h-functions from tree j-1 down to tree 0.
            # By construction of the D-vine: tree k has d-k edges; for variable j,
            # tree k contributes the edge at position j-k-1 (0-indexed).
            # The loop range guarantees 0 <= j-k-1 <= len(self._trees[k])-1.
            for k in range(j - 1, -1, -1):
                edge = self._trees[k][j - k - 1]
                v[j][k] = _h_inv_e(v[j][k + 1], v[k][k], edge)

            x[:, j] = v[j][0]

            # Forward h-function pass: update the table for future columns.
            if j < d - 1:
                v[j][0] = x[:, j].copy()
                for k in range(1, j + 1):
                    edge = self._trees[k - 1][j - k]
                    v[j][k] = _h_fwd_e(v[j][k - 1], v[k - 1][k - 1], edge)
                # The new diagonal at level j is the deepest h-function value
                v[j][j] = v[j][j - 1].copy()

        return np.clip(x, _CLIP_LO, _CLIP_HI)


# ---------------------------------------------------------------------------
# H-function inverses (needed for sampling)
# ---------------------------------------------------------------------------


def _h_gaussian_inv(
    u: np.ndarray, v: np.ndarray, rho: float
) -> np.ndarray:
    """Inverse h-function for Gaussian pair-copula.

    Solves  u = h(x | v; rho) = Phi((Phi^{-1}(x) - rho Phi^{-1}(v)) / sqrt(1-rho^2))
    for x given u and v:
        x = Phi(u * sqrt(1 - rho^2) + rho * Phi^{-1}(v))
    """
    eps = 1e-10
    rho = float(np.clip(rho, -1.0 + eps, 1.0 - eps))
    qu = _normal_ppf(np.clip(u, _CLIP_LO, _CLIP_HI))
    qv = _normal_ppf(np.clip(v, _CLIP_LO, _CLIP_HI))
    arg = qu * math.sqrt(1.0 - rho * rho) + rho * qv
    cdf_val: np.ndarray = np.asarray(stats.norm.cdf(arg), dtype=float)
    return np.clip(cdf_val, _CLIP_LO, _CLIP_HI)


def _h_student_t_inv(
    u: np.ndarray, v: np.ndarray, rho: float, nu: float
) -> np.ndarray:
    """Inverse h-function for Student-t pair-copula.

    Solves  u = h(x | v; rho, nu)  for x:
        x = t_nu( t_{nu+1}^{-1}(u) * sqrt((nu + t_nu^{-1}(v)^2)(1-rho^2)/(nu+1))
                  + rho * t_nu^{-1}(v) )
    """
    eps = 1e-10
    rho = float(np.clip(rho, -1.0 + eps, 1.0 - eps))
    qu = _t_ppf(np.clip(u, _CLIP_LO, _CLIP_HI), nu + 1.0)
    qv = _t_ppf(np.clip(v, _CLIP_LO, _CLIP_HI), nu)
    scale = np.sqrt((nu + qv * qv) * (1.0 - rho * rho) / (nu + 1.0))
    arg = qu * scale + rho * qv
    return np.clip(_t_cdf(arg, nu), _CLIP_LO, _CLIP_HI)


# ---------------------------------------------------------------------------
# Tail dependence
# ---------------------------------------------------------------------------


def tail_dependence_gaussian(rho: float) -> float:
    """Analytic tail dependence coefficient for the Gaussian copula.

    For the Gaussian copula:

        lambda_L = lambda_U = 0  for all rho < 1.

    Parameters
    ----------
    rho:
        Correlation parameter in (-1, 1).

    Returns
    -------
    float
        0.0 (exact; no tail dependence for rho < 1).

    Raises
    ------
    ValueError
        If rho is outside (-1, 1].
    """
    if not -1.0 < rho <= 1.0:
        raise ValueError(
            f"rho must be in (-1, 1]; got {rho}."
        )
    if rho == 1.0:
        return 1.0
    return 0.0


def tail_dependence_student_t(rho: float, nu: float) -> float:
    """Analytic tail dependence for the Student-t copula.

    For the bivariate Student-t copula with parameters (rho, nu):

        lambda_L = lambda_U = 2 * t_{nu+1}(-sqrt((nu+1)(1-rho)/(1+rho)))

    (McNeil-Frey-Embrechts 2015, Proposition 7.40; Demarta-McNeil 2005.)
    The upper and lower tail dependence coefficients are equal (symmetric
    tails) for rho > -1 and nu < inf.  As nu -> inf, lambda -> 0 (Gaussian
    limit); as rho -> 1, lambda -> 1.

    Parameters
    ----------
    rho:
        Correlation parameter in (-1, 1].
    nu:
        Degrees of freedom; must be > 0.

    Returns
    -------
    float
        Tail dependence coefficient in [0, 1].

    Raises
    ------
    ValueError
        If rho or nu are outside valid ranges.
    """
    if not -1.0 < rho <= 1.0:
        raise ValueError(f"rho must be in (-1, 1]; got {rho}.")
    if nu <= 0.0:
        raise ValueError(f"nu must be > 0; got {nu}.")
    if rho == 1.0:
        return 1.0
    arg = -math.sqrt((nu + 1.0) * (1.0 - rho) / (1.0 + rho))
    return float(2.0 * stats.t.cdf(arg, df=nu + 1.0))


def tail_dependence_empirical(
    u: np.ndarray,
    *,
    threshold: float = 0.05,
    tail: Literal["lower", "upper"] = "lower",
) -> float:
    """Nonparametric threshold-based tail dependence estimator.

    For two variables (columns 0 and 1 of ``u``), estimates the tail
    dependence coefficient as the conditional probability that both
    variables are in the extreme tail simultaneously:

        lambda_L = P(U_1 < q | U_2 < q)  for q = threshold  (lower)
        lambda_U = P(U_1 > 1-q | U_2 > 1-q)  for q = threshold  (upper)

    This is the Schmidt-Stadtmuller (2006) estimator (equivalent form):
        lambda = count(u1 < q AND u2 < q) / count(u2 < q)

    Parameters
    ----------
    u:
        2-D array of pseudo-observations, shape (n_obs, 2).  Exactly two
        columns required (bivariate tail dependence).
    threshold:
        Tail probability q in (0, 0.5).
    tail:
        ``"lower"`` for lower tail dependence, ``"upper"`` for upper.

    Returns
    -------
    float
        Empirical tail dependence estimate in [0, 1].

    Raises
    ------
    ValueError
        If ``u`` does not have exactly 2 columns or threshold is outside
        (0, 0.5).
    """
    arr = np.asarray(u, dtype=float)
    if arr.ndim == 1:
        arr = arr[:, np.newaxis]
    if arr.ndim != 2 or arr.shape[1] != 2:
        raise ValueError(
            f"u must be a 2-D array with exactly 2 columns; "
            f"got shape {arr.shape}."
        )
    if not 0.0 < threshold < 0.5:
        raise ValueError(
            f"threshold must be in (0, 0.5); got {threshold}."
        )
    u1 = arr[:, 0]
    u2 = arr[:, 1]
    if tail == "lower":
        mask2 = u2 < threshold
        n_cond = int(mask2.sum())
        if n_cond == 0:
            return 0.0
        n_joint = int((mask2 & (u1 < threshold)).sum())
    else:
        mask2 = u2 > (1.0 - threshold)
        n_cond = int(mask2.sum())
        if n_cond == 0:
            return 0.0
        n_joint = int((mask2 & (u1 > (1.0 - threshold))).sum())
    return float(n_joint) / float(n_cond)
