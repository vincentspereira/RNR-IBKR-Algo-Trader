"""Robust covariance estimators for portfolio construction (Phase 6, Batch 1).

Every Phase 6 optimiser (MVO, risk parity, HRP, Black-Litterman, robust opt)
consumes an estimate of the asset-return covariance matrix.  The raw sample
covariance is notoriously ill-conditioned when the number of assets N is not
tiny relative to the number of observations T: its smallest eigenvalues are
biased towards zero and its inverse (which mean-variance optimisation needs)
amplifies estimation error into extreme, unstable weights.  This module
provides the standard remedies:

1. ``sample_covariance``                  -- baseline (for comparison / inputs).
2. ``ledoit_wolf_covariance``             -- shrinkage towards the scaled
                                             identity (Ledoit-Wolf 2004a).
3. ``oas_covariance``                     -- Oracle Approximating Shrinkage
                                             towards the scaled identity
                                             (Chen-Wiesel-Eldar-Hero 2010).
4. ``constant_correlation_covariance``    -- shrinkage towards the constant-
                                             correlation target ("Honey, I
                                             Shrunk", Ledoit-Wolf 2004b).
5. ``factor_model_covariance``            -- low-rank-plus-diagonal estimate
                                             from PCA statistical factors
                                             (Fan-Fan-Lv 2008).
6. ``nearest_psd``                        -- eigenvalue-clipping projection to
                                             the PSD cone (Higham 1988).
7. ``condition_number``                   -- spectral condition number
                                             diagnostic.

Panel convention
----------------
All estimators take a *returns panel*: a ``pandas.DataFrame`` whose index is
an ascending ``DatetimeIndex`` (one row per bar) and whose columns are asset
symbols, holding simple returns.  Panels must be NaN-free (align and drop or
fill missing data upstream); estimators raise ``ValueError`` otherwise.
Covariances are returned in (return units)^2 per bar -- annualisation is the
caller's concern.

Normalisation conventions
-------------------------
* ``sample_covariance`` uses the unbiased ``ddof=1`` divisor by default.
* The shrinkage estimators (Ledoit-Wolf, OAS, constant-correlation) follow
  their papers and use the maximum-likelihood ``1/T`` divisor on demeaned
  returns.  The difference is a factor T/(T-1), immaterial at portfolio
  horizons, but documented here so cross-estimator comparisons are exact.
* ``factor_model_covariance`` inherits the ``ddof=1`` convention from
  :func:`core_trading.signals.factors.pca_factors.fit_pca_factors`.

Mathematical references
-----------------------
Ledoit-Wolf identity-target shrinkage (2004a):
    S      = X'X / T                       (X demeaned, shape T x N)
    m      = tr(S) / N
    d^2    = ||S - m I||_F^2 / N
    b_bar2 = (1 / (T^2 N)) * sum_t ||x_t x_t' - S||_F^2
           = (sum_t (x_t' x_t)^2 - T ||S||_F^2) / (T^2 N)
    b^2    = min(b_bar2, d^2)
    Sigma* = (b^2 / d^2) m I + (1 - b^2 / d^2) S
The shrinkage intensity delta = b^2 / d^2 is in [0, 1] by construction.

Oracle Approximating Shrinkage (Chen et al. 2010, Eq. 23):
    rho_OAS = [ (1 - 2/N) tr(S^2) + tr(S)^2 ]
              / [ (T + 1 - 2/N) (tr(S^2) - tr(S)^2 / N) ]
    delta   = min(rho_OAS, 1)
    Sigma*  = (1 - delta) S + delta (tr(S)/N) I
OAS dominates the Ledoit-Wolf identity-target estimator in MSE for Gaussian
data, especially at small T/N.  (Note: scikit-learn implements a variant of
this formula without the 2/N correction terms; this module follows the paper.)

Constant-correlation shrinkage (Ledoit-Wolf 2004b, Appendix A/B):
    target F:  F_ii = s_ii,  F_ij = r_bar sqrt(s_ii s_jj)
    where r_bar is the average of the off-diagonal sample correlations.
    pi_hat    = sum_ij (1/T) sum_t (x_it x_jt - s_ij)^2
    rho_hat   = sum_i pi_ii + sum_{i != j} (r_bar / 2)
                ( sqrt(s_jj / s_ii) theta_ii,ij + sqrt(s_ii / s_jj) theta_jj,ij )
    theta_ii,ij = (1/T) sum_t (x_it^2 - s_ii)(x_it x_jt - s_ij)
    gamma_hat = ||F - S||_F^2
    delta     = clip((pi_hat - rho_hat) / gamma_hat / T, 0, 1)
    Sigma*    = delta F + (1 - delta) S
For N = 2 the target equals the sample matrix exactly (gamma_hat = 0); the
estimator then returns the sample matrix with delta = 0 by convention.

PCA factor-model covariance (Fan-Fan-Lv 2008):
    Sigma_k = V_k Lambda_k V_k' + D
    where V_k / Lambda_k are the top-k eigenvectors / eigenvalues of the
    sample covariance and D = diag(S - V_k Lambda_k V_k') >= 0 holds the
    idiosyncratic variances (non-negative because the discarded eigenvalues
    of a PSD matrix are non-negative; clamped at zero against float error).

Nearest PSD projection (Higham 1988):
    P(A) = V max(Lambda, eps) V'   for the symmetrised A = (A + A') / 2.
This is the Frobenius-norm projection onto the cone of symmetric PSD
matrices (with optional eigenvalue floor eps > 0 for strict PD).

References:
  * Ledoit, O. & Wolf, M. (2004a). "A Well-Conditioned Estimator for
    Large-Dimensional Covariance Matrices."
    Journal of Multivariate Analysis, 88(2), 365-411.
  * Ledoit, O. & Wolf, M. (2004b). "Honey, I Shrunk the Sample Covariance
    Matrix." Journal of Portfolio Management, 30(4), 110-119.
  * Chen, Y., Wiesel, A., Eldar, Y.C. & Hero, A.O. (2010). "Shrinkage
    Algorithms for MMSE Covariance Estimation."
    IEEE Transactions on Signal Processing, 58(10), 5016-5029.
  * Fan, J., Fan, Y. & Lv, J. (2008). "High Dimensional Covariance Matrix
    Estimation Using a Factor Model."
    Journal of Econometrics, 147(1), 186-197.
  * Higham, N.J. (1988). "Computing a Nearest Symmetric Positive Semidefinite
    Matrix." Linear Algebra and its Applications, 103, 103-118.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from core_trading.signals.factors.pca_factors import fit_pca_factors

__all__ = [
    "CovarianceResult",
    "sample_covariance",
    "ledoit_wolf_covariance",
    "oas_covariance",
    "constant_correlation_covariance",
    "factor_model_covariance",
    "nearest_psd",
    "condition_number",
]


# ---------------------------------------------------------------------------
# Data-transfer object
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CovarianceResult:
    """Result of a covariance estimation.

    The ``covariance`` field is excluded from dataclass equality (DataFrame
    equality is elementwise and would raise "truth value is ambiguous");
    compare ``method`` / ``shrinkage`` / ``n_factors`` metadata instead, or
    the matrices explicitly via ``numpy.allclose``.

    Attributes
    ----------
    covariance:
        Symmetric N x N covariance matrix as a ``pandas.DataFrame`` whose
        index and columns are both the asset symbols of the input panel,
        in input order.
    method:
        Estimator identifier: ``"sample"``, ``"ledoit_wolf"``, ``"oas"``,
        ``"constant_correlation"`` or ``"factor_model"``.
    shrinkage:
        Shrinkage intensity delta in [0, 1] for the shrinkage estimators;
        ``None`` for ``sample`` and ``factor_model``.
    n_factors:
        Number of statistical factors retained; ``None`` except for
        ``factor_model``.
    """

    covariance: pd.DataFrame = field(compare=False)
    method: str
    shrinkage: float | None = None
    n_factors: int | None = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validated_array(returns: pd.DataFrame) -> np.ndarray:
    """Validate a returns panel and return it as a float64 array.

    Parameters
    ----------
    returns:
        Returns panel: DatetimeIndex rows x asset-symbol columns.

    Returns
    -------
    numpy.ndarray
        The panel values, shape (n_obs, n_assets), dtype float64.

    Raises
    ------
    ValueError
        If the panel contains NaN, has fewer than 2 asset columns, or has
        fewer than 2 observation rows.
    """
    if returns.isnull().any().any():
        raise ValueError(
            "returns panel contains NaN values; "
            "align and fill or drop missing data before estimating covariance."
        )
    n_obs, n_assets = returns.shape
    if n_assets < 2:
        raise ValueError(
            f"returns panel must have at least 2 asset columns; got {n_assets}."
        )
    if n_obs < 2:
        raise ValueError(
            f"returns panel must have at least 2 observation rows; got {n_obs}."
        )
    arr: np.ndarray = returns.to_numpy(dtype=float)
    return arr


def _as_frame(matrix: np.ndarray, returns: pd.DataFrame) -> pd.DataFrame:
    """Wrap a covariance array in a symmetric labelled DataFrame."""
    cols = returns.columns
    return pd.DataFrame(matrix, index=cols, columns=cols)


def _ml_covariance(arr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Demean and return (X_demeaned, S) with the 1/T maximum-likelihood divisor."""
    n_obs = arr.shape[0]
    x = arr - arr.mean(axis=0)
    s = (x.T @ x) / float(n_obs)
    return x, s


# ---------------------------------------------------------------------------
# Estimators
# ---------------------------------------------------------------------------


def sample_covariance(returns: pd.DataFrame, *, ddof: int = 1) -> CovarianceResult:
    """Plain sample covariance of a returns panel.

    Provided as the baseline against which the robust estimators are
    compared, and as the input to estimators that need the unbiased sample
    matrix (e.g. the factor-model residual diagonal).

    Parameters
    ----------
    returns:
        Returns panel.  See module docstring for the shape convention.
    ddof:
        Delta degrees of freedom for the divisor ``1 / (T - ddof)``.
        Default 1 (unbiased).  Must satisfy ``0 <= ddof < n_obs``.

    Returns
    -------
    CovarianceResult
        ``method="sample"``, ``shrinkage=None``.

    Raises
    ------
    ValueError
        On an invalid panel (see :func:`_validated_array`) or invalid ddof.
    """
    arr = _validated_array(returns)
    n_obs = arr.shape[0]
    if not 0 <= ddof < n_obs:
        raise ValueError(
            f"ddof must satisfy 0 <= ddof < n_obs ({n_obs}); got {ddof}."
        )
    x = arr - arr.mean(axis=0)
    s = (x.T @ x) / float(n_obs - ddof)
    return CovarianceResult(covariance=_as_frame(s, returns), method="sample")


def ledoit_wolf_covariance(returns: pd.DataFrame) -> CovarianceResult:
    """Ledoit-Wolf shrinkage towards the scaled identity (2004a).

    Shrinks the maximum-likelihood sample covariance S towards m*I, where
    m = tr(S)/N, with the analytically optimal (asymptotic expected
    Frobenius loss) intensity.  See the module docstring for the formulas.

    The estimator is guaranteed well-conditioned for delta > 0 and is
    invertible whenever m > 0.  When S is already a scaled identity
    (d^2 = 0) the shrinkage is reported as 0 and S is returned unchanged
    (target and sample coincide).

    Parameters
    ----------
    returns:
        Returns panel.  See module docstring for the shape convention.

    Returns
    -------
    CovarianceResult
        ``method="ledoit_wolf"`` with ``shrinkage`` = delta in [0, 1].

    Raises
    ------
    ValueError
        On an invalid panel (see :func:`_validated_array`).
    """
    arr = _validated_array(returns)
    n_obs, n_assets = arr.shape
    x, s = _ml_covariance(arr)

    m = float(np.trace(s)) / float(n_assets)
    d2 = float(((s - m * np.eye(n_assets)) ** 2).sum()) / float(n_assets)

    # sum_t (x_t' x_t)^2  computed without materialising the T outer products.
    row_sq_norms = (x * x).sum(axis=1)
    b_bar2 = (
        float((row_sq_norms**2).sum()) - float(n_obs) * float((s**2).sum())
    ) / (float(n_obs) ** 2 * float(n_assets))
    b_bar2 = max(b_bar2, 0.0)  # non-negative in exact arithmetic
    b2 = min(b_bar2, d2)

    delta = 0.0 if d2 <= 0.0 else b2 / d2
    sigma = delta * m * np.eye(n_assets) + (1.0 - delta) * s
    return CovarianceResult(
        covariance=_as_frame(sigma, returns),
        method="ledoit_wolf",
        shrinkage=delta,
    )


def oas_covariance(returns: pd.DataFrame) -> CovarianceResult:
    """Oracle Approximating Shrinkage towards the scaled identity.

    Implements Eq. 23 of Chen, Wiesel, Eldar & Hero (2010) exactly (with the
    2/N correction terms; scikit-learn omits them).  OAS dominates the
    Ledoit-Wolf identity-target estimator in MSE under Gaussian returns,
    with the advantage concentrated at small T/N.

    When the sample covariance is already a scaled identity the denominator
    of rho_OAS vanishes; the shrinkage is then reported as 1 (sample and
    target coincide, so the returned matrix is the same either way).

    Parameters
    ----------
    returns:
        Returns panel.  See module docstring for the shape convention.

    Returns
    -------
    CovarianceResult
        ``method="oas"`` with ``shrinkage`` = delta in [0, 1].

    Raises
    ------
    ValueError
        On an invalid panel (see :func:`_validated_array`).
    """
    arr = _validated_array(returns)
    n_obs, n_assets = arr.shape
    _, s = _ml_covariance(arr)

    n = float(n_assets)
    t = float(n_obs)
    tr_s = float(np.trace(s))
    tr_s2 = float((s**2).sum())  # tr(S^2) = ||S||_F^2 for symmetric S

    numerator = (1.0 - 2.0 / n) * tr_s2 + tr_s**2
    denominator = (t + 1.0 - 2.0 / n) * (tr_s2 - tr_s**2 / n)

    delta = 1.0 if denominator <= 0.0 else min(numerator / denominator, 1.0)
    m = tr_s / n
    sigma = (1.0 - delta) * s + delta * m * np.eye(n_assets)
    return CovarianceResult(
        covariance=_as_frame(sigma, returns),
        method="oas",
        shrinkage=delta,
    )


def constant_correlation_covariance(returns: pd.DataFrame) -> CovarianceResult:
    """Ledoit-Wolf shrinkage towards the constant-correlation target (2004b).

    The "Honey, I Shrunk the Sample Covariance Matrix" estimator: keeps the
    sample variances on the diagonal and shrinks all off-diagonal entries
    towards the average sample correlation.  See the module docstring for
    the pi-hat / rho-hat / gamma-hat formulas (paper Appendix A/B).

    For N = 2 the target coincides with the sample matrix (gamma_hat = 0);
    the sample matrix is returned with shrinkage 0 by convention.

    Parameters
    ----------
    returns:
        Returns panel.  All assets must have strictly positive sample
        variance (the constant-correlation target divides by sqrt(s_ii)).

    Returns
    -------
    CovarianceResult
        ``method="constant_correlation"`` with ``shrinkage`` = delta in [0, 1].

    Raises
    ------
    ValueError
        On an invalid panel, or if any asset has zero sample variance.
    """
    arr = _validated_array(returns)
    n_obs, n_assets = arr.shape
    x, s = _ml_covariance(arr)

    variances = np.diag(s).copy()
    # A constant column demeans to float residue rather than exact zeros, so
    # "zero variance" is detected relative to the column's mean square level.
    var_floor = (100.0 * float(np.finfo(float).eps)) ** 2 * (arr**2).mean(axis=0)
    degenerate = variances <= var_floor
    if bool(degenerate.any()):
        zero_cols = [
            str(c)
            for c, bad in zip(returns.columns, degenerate, strict=True)
            if bad
        ]
        raise ValueError(
            "constant-correlation shrinkage requires strictly positive sample "
            f"variance for every asset; zero-variance columns: {zero_cols}."
        )
    sqrt_var = np.sqrt(variances)

    # Average off-diagonal sample correlation r_bar.
    corr = s / np.outer(sqrt_var, sqrt_var)
    r_bar = float(corr.sum() - np.trace(corr)) / float(n_assets * (n_assets - 1))

    # Constant-correlation target F.
    target = r_bar * np.outer(sqrt_var, sqrt_var)
    np.fill_diagonal(target, variances)

    # pi_hat: sum of asymptotic variances of the sample covariance entries.
    x2 = x * x
    pi_mat = (x2.T @ x2) / float(n_obs) - s**2
    pi_hat = float(pi_mat.sum())

    # rho_hat: diagonal part plus the off-diagonal covariance correction.
    # theta_mat[i, j] = (1/T) sum_t (x_it^2 - s_ii)(x_it x_jt - s_ij)
    theta_mat = ((x**3).T @ x) / float(n_obs) - variances[:, np.newaxis] * s
    scale = np.outer(1.0 / sqrt_var, sqrt_var)  # scale[i, j] = sqrt(s_jj / s_ii)
    off_diag = np.ones((n_assets, n_assets), dtype=float) - np.eye(n_assets)
    rho_hat = float(np.trace(pi_mat)) + r_bar * float(
        (scale * theta_mat * off_diag).sum()
    )

    # gamma_hat: squared Frobenius distance between target and sample.
    # In exact arithmetic gamma_hat = 0 whenever target == S (always true for
    # N == 2); in floats it is then ~1e-30 rather than 0, which would blow up
    # kappa -- so the degeneracy is detected with a relative tolerance.
    gamma_hat = float(((target - s) ** 2).sum())

    if gamma_hat <= 1e-12 * float((s**2).sum()):
        delta = 0.0  # target == sample (always the case for N == 2)
    else:
        kappa = (pi_hat - rho_hat) / gamma_hat
        delta = float(np.clip(kappa / float(n_obs), 0.0, 1.0))

    sigma = delta * target + (1.0 - delta) * s
    return CovarianceResult(
        covariance=_as_frame(sigma, returns),
        method="constant_correlation",
        shrinkage=delta,
    )


def factor_model_covariance(
    returns: pd.DataFrame,
    *,
    n_factors: int,
) -> CovarianceResult:
    """Low-rank-plus-diagonal covariance from PCA statistical factors.

    Builds Sigma_k = V_k Lambda_k V_k' + D from the top-k eigenpairs of the
    sample covariance matrix (Fan-Fan-Lv 2008), where D holds the per-asset
    residual variances diag(S) - diag(V_k Lambda_k V_k'), clamped at zero
    against floating-point error.  The result is PSD by construction and,
    unlike the raw sample matrix, remains well-conditioned when T is small
    relative to N because the noise in the discarded eigenpairs is replaced
    by a diagonal.

    Eigenpairs are computed by
    :func:`core_trading.signals.factors.pca_factors.fit_pca_factors` with
    ``standardize=False`` (covariance PCA, unbiased ``ddof=1`` divisor).

    Parameters
    ----------
    returns:
        Returns panel.  ``fit_pca_factors`` additionally requires
        ``n_obs >= n_assets``.
    n_factors:
        Number of statistical factors k to retain; ``1 <= k <= n_assets``.

    Returns
    -------
    CovarianceResult
        ``method="factor_model"`` with ``n_factors`` set; ``shrinkage=None``.

    Raises
    ------
    ValueError
        On an invalid panel or n_factors outside [1, n_assets] (propagated
        from ``fit_pca_factors``), or n_obs < n_assets.
    """
    arr = _validated_array(returns)
    result = fit_pca_factors(returns, n_factors=n_factors, standardize=False)

    # Systematic part: V_k Lambda_k V_k'.
    loadings = result.loadings  # (N, k) eigenvectors of the ddof=1 sample cov
    eigenvalues = result.eigenvalues  # (k,) descending
    systematic = (loadings * eigenvalues[np.newaxis, :]) @ loadings.T

    # Residual diagonal from the ddof=1 sample covariance.
    x = arr - arr.mean(axis=0)
    s = (x.T @ x) / float(arr.shape[0] - 1)
    residual_var = np.maximum(np.diag(s) - np.diag(systematic), 0.0)

    sigma = systematic + np.diag(residual_var)
    return CovarianceResult(
        covariance=_as_frame(sigma, returns),
        method="factor_model",
        n_factors=int(n_factors),
    )


# ---------------------------------------------------------------------------
# Matrix diagnostics / repair
# ---------------------------------------------------------------------------


def nearest_psd(matrix: np.ndarray, *, epsilon: float = 0.0) -> np.ndarray:
    """Project a square matrix onto the symmetric PSD cone (Higham 1988).

    Symmetrises the input as (A + A')/2, eigendecomposes, floors the
    eigenvalues at ``epsilon`` and reconstructs.  With ``epsilon = 0`` this
    is the Frobenius-norm projection onto the PSD cone; with
    ``epsilon > 0`` the result is strictly positive definite with smallest
    eigenvalue >= epsilon (useful before a Cholesky factorisation).

    A matrix that already satisfies the floor is returned unchanged up to
    the symmetrisation (no spurious reconstruction error).

    Parameters
    ----------
    matrix:
        Square 2-D array.
    epsilon:
        Eigenvalue floor; must be >= 0.

    Returns
    -------
    numpy.ndarray
        Symmetric matrix with all eigenvalues >= epsilon.

    Raises
    ------
    ValueError
        If the input is not a square 2-D array or epsilon < 0.
    """
    arr = np.asarray(matrix, dtype=float)
    if arr.ndim != 2 or arr.shape[0] != arr.shape[1]:
        raise ValueError(f"matrix must be square 2-D; got shape {arr.shape}.")
    if epsilon < 0.0:
        raise ValueError(f"epsilon must be >= 0, got {epsilon}.")

    sym: np.ndarray = (arr + arr.T) / 2.0
    eigenvalues, eigenvectors = np.linalg.eigh(sym)
    if bool((eigenvalues >= epsilon).all()):
        return sym
    clipped = np.maximum(eigenvalues, epsilon)
    repaired = (eigenvectors * clipped[np.newaxis, :]) @ eigenvectors.T
    # Re-symmetrise against float error from the reconstruction product.
    out: np.ndarray = (repaired + repaired.T) / 2.0
    return out


def condition_number(matrix: np.ndarray) -> float:
    """Spectral condition number lambda_max / lambda_min of a symmetric matrix.

    The headline diagnostic for covariance quality: the raw sample matrix
    becomes near-singular (huge condition number) as N approaches T, which
    is exactly what shrinkage repairs.  Returns ``inf`` when the smallest
    eigenvalue is <= 0 (singular or indefinite matrix).

    Parameters
    ----------
    matrix:
        Square 2-D array, assumed symmetric (symmetrised internally).

    Returns
    -------
    float
        Condition number >= 1, or ``inf`` if the matrix is singular or
        indefinite.

    Raises
    ------
    ValueError
        If the input is not a square 2-D array.
    """
    arr = np.asarray(matrix, dtype=float)
    if arr.ndim != 2 or arr.shape[0] != arr.shape[1]:
        raise ValueError(f"matrix must be square 2-D; got shape {arr.shape}.")
    eigenvalues = np.linalg.eigvalsh((arr + arr.T) / 2.0)
    smallest = float(eigenvalues[0])
    largest = float(eigenvalues[-1])
    if smallest <= 0.0:
        return float("inf")
    return largest / smallest
