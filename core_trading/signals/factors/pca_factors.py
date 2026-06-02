"""PCA statistical factor extraction for cross-sectional returns panels (Phase 5.C.3).

This module implements Principal Component Analysis (PCA) over a multi-asset
returns panel to extract statistical (latent) factors and their associated
eigenportfolios.  It is the foundational building block for the cross-sectional
("factor") signal family introduced in Phase 5.C.

Cross-sectional panel convention
---------------------------------
A cross-sectional returns panel is a ``pandas.DataFrame`` indexed by an
ascending ``DatetimeIndex`` (timestamps / bars), with one column per asset
symbol.  Values are simple or log returns.  The PCA fit operates on a complete
(no-NaN) window; the module validates this and raises a ``ValueError`` if the
panel contains NaN, has too few assets, or has too few observations.

Observation count rule: the number of rows (time bars) must be at least as
large as the number of asset columns (n_obs >= n_assets).  This ensures the
sample covariance / correlation matrix is at least rank-1 and that the
eigendecomposition is well-conditioned.  In practice 5-to-10x more observations
than assets is recommended for stable estimates.

Eigenportfolio construction (Avellaneda-Lee, 2010)
---------------------------------------------------
After computing the top-k eigenvectors of the sample correlation matrix, the
Avellaneda-Lee eigenportfolio for factor j is:

    w_{j,i} = v_{j,i} / sigma_i

where v_{j,i} is the i-th component of eigenvector j and sigma_i is the
cross-sectional standard deviation (time-series std) of asset i's (raw)
returns.  These weights reflect the eigenvector direction normalised to
dollar-return units.  Factor returns are then:

    F_{t,j} = sum_i  r_{t,i} * w_{j,i}    (or equivalently: R_std @ V_k)

where R_std is the standardised returns matrix and V_k is the (n_assets x k)
loading matrix of top-k eigenvectors.

Residual (idiosyncratic) returns
---------------------------------
Given fitted factor loadings B and factor returns F (both from the PCA), the
residual for asset i at time t is:

    e_{t,i} = r_{t,i} - F_t * b_i^T

where b_i is asset i's row in the OLS-regression loading matrix.  These
residuals are the idiosyncratic components; a subsequent mean-reversion / stat-
arb signal would trade on the mis-pricing in e.

Mathematical references
-----------------------
* Connor, G. & Korajczyk, R. (1986).  "Performance measurement with the
  arbitrage pricing theory."  Journal of Financial Economics, 15, 373-394.
* Avellaneda, M. & Lee, J.H. (2010).  "Statistical Arbitrage in the US
  Equities Market."  Quantitative Finance, 10(7), 761-782.  -- the
  eigenportfolio / PCA stat-arb construction.
* Jolliffe, I.T. (2002).  "Principal Component Analysis."  Springer, 2nd ed.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

__all__ = [
    "PCAFactorResult",
    "fit_pca_factors",
    "residual_returns",
    "reconstruct",
]


# ---------------------------------------------------------------------------
# Data-transfer object
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PCAFactorResult:
    """Results of a PCA factor extraction from a cross-sectional returns panel.

    All array fields are excluded from dataclass equality so that instances
    can be compared without triggering the "truth value of an array is
    ambiguous" error.

    Attributes
    ----------
    eigenvalues:
        1-D array of shape (k,) holding the top-k eigenvalues of the sample
        correlation (or covariance) matrix, sorted in descending order.  Each
        eigenvalue represents the variance of the data captured by the
        corresponding principal component.
    loadings:
        2-D array of shape (n_assets, k) holding the eigenvectors as columns.
        ``loadings[:, j]`` is the j-th principal direction in asset space.
        These are the raw eigenvectors of the correlation/covariance matrix;
        they map assets to factor scores.
    variance_explained:
        1-D array of shape (k,) holding the fraction of total variance
        captured by each factor: ``eigenvalue[j] / sum(all eigenvalues)``.
        Values are in (0, 1] and non-increasing; they sum to at most 1 across
        all k factors (sum equals 1 iff k == n_assets).
    factor_returns:
        2-D array of shape (n_obs, k) holding the time-series of factor
        returns.  ``factor_returns[:, j]`` is the return of the j-th
        eigenportfolio at each bar.
    eigenportfolio_weights:
        2-D array of shape (k, n_assets) holding the Avellaneda-Lee
        eigenportfolio weights.  ``eigenportfolio_weights[j, :]`` is the
        weight vector for factor j, normalised by per-asset volatility.
    n_factors:
        Number of factors k retained.
    asset_names:
        Ordered tuple of asset column names from the input returns panel.
    """

    eigenvalues: np.ndarray = field(compare=False)
    loadings: np.ndarray = field(compare=False)
    variance_explained: np.ndarray = field(compare=False)
    factor_returns: np.ndarray = field(compare=False)
    eigenportfolio_weights: np.ndarray = field(compare=False)
    n_factors: int
    asset_names: tuple[str, ...]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_panel(returns: pd.DataFrame, n_factors: int) -> None:
    """Raise ``ValueError`` on any invalid input combination.

    Parameters
    ----------
    returns:
        The raw returns panel to be validated.
    n_factors:
        Requested number of PCA factors.

    Raises
    ------
    ValueError
        On NaN values, too few assets, too few observations, or n_factors
        outside the valid range [1, n_assets].
    """
    if returns.isnull().any().any():
        raise ValueError(
            "returns panel contains NaN values; "
            "fill or drop missing data before calling fit_pca_factors."
        )
    n_obs, n_assets = returns.shape
    if n_assets < 2:
        raise ValueError(
            f"returns panel must have at least 2 asset columns; got {n_assets}."
        )
    if n_obs < n_assets:
        raise ValueError(
            f"returns panel must have at least as many observations (rows) as "
            f"assets (columns); got n_obs={n_obs} < n_assets={n_assets}.  "
            f"Provide a longer history or reduce n_factors."
        )
    if n_factors < 1:
        raise ValueError(
            f"n_factors must be >= 1; got {n_factors}."
        )
    if n_factors > n_assets:
        raise ValueError(
            f"n_factors ({n_factors}) cannot exceed the number of assets "
            f"({n_assets})."
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fit_pca_factors(
    returns: pd.DataFrame,
    *,
    n_factors: int,
    standardize: bool = True,
) -> PCAFactorResult:
    """Extract the top-k statistical factors from a cross-sectional returns panel.

    Uses ``numpy.linalg.eigh`` on the sample correlation matrix (when
    ``standardize=True``, the Avellaneda-Lee choice) or the sample covariance
    matrix (when ``standardize=False``) to find the principal components.
    ``eigh`` exploits the symmetry of the matrix for numerical stability and
    guarantees real eigenvalues.

    The standardize=True path (default)
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Each asset's returns are normalised to zero mean and unit variance before
    computing the sample correlation matrix.  This is the correct choice when
    assets have different return scales (e.g. mixing low-vol bonds with high-
    vol equities) because it prevents high-variance assets from dominating
    purely by scale.  Avellaneda & Lee (2010) use this construction for the
    US equities stat-arb model.

    Parameters
    ----------
    returns:
        Cross-sectional returns panel: ``DatetimeIndex`` rows x asset-symbol
        columns.  Must be NaN-free, have at least 2 columns, and at least as
        many rows as columns.
    n_factors:
        Number of top principal components (eigenportfolios) to retain.
        Must satisfy 1 <= n_factors <= n_assets.
    standardize:
        If ``True`` (default) standardise each asset's returns column to
        zero mean / unit variance and compute the correlation matrix.
        If ``False`` use the raw returns and compute the covariance matrix.

    Returns
    -------
    PCAFactorResult
        Fitted factor extraction result containing eigenvalues, loadings,
        variance_explained, factor_returns, eigenportfolio_weights,
        n_factors, and asset_names.

    Raises
    ------
    ValueError
        If the panel contains NaN, has too few assets, too few observations,
        or n_factors is outside the valid range [1, n_assets].

    Notes
    -----
    Eigenvector sign convention: ``eigh`` returns eigenvectors with arbitrary
    sign.  The module makes no sign correction; callers that compare loadings
    across fits should use absolute correlations or subspace comparison rather
    than raw eigenvector equality (see the test module for examples).
    """
    _validate_panel(returns, n_factors)

    n_obs, n_assets = returns.shape
    asset_names: tuple[str, ...] = tuple(str(c) for c in returns.columns)

    R: np.ndarray = returns.to_numpy(dtype=float)

    # Per-asset means and standard deviations (time-series statistics).
    asset_means: np.ndarray = R.mean(axis=0)
    asset_stds: np.ndarray = R.std(axis=0, ddof=1)
    # Guard against zero-variance assets (constant series).
    asset_stds = np.where(asset_stds == 0.0, 1.0, asset_stds)

    if standardize:
        # Standardise to correlation-matrix PCA.
        R_std: np.ndarray = (R - asset_means) / asset_stds
    else:
        # Demean only; covariance-matrix PCA.
        R_std = R - asset_means

    # Sample covariance / correlation matrix (T x T avoidance: use (n_assets x n_assets)).
    # Shape: (n_assets, n_assets); divide by (n_obs - 1) for unbiased estimate.
    cov_mat: np.ndarray = (R_std.T @ R_std) / float(n_obs - 1)

    # Eigendecomposition with numpy.linalg.eigh (symmetric real matrix).
    # eigh returns eigenvalues in ASCENDING order; we reverse to get descending.
    raw_eigenvalues: np.ndarray
    raw_eigenvectors: np.ndarray
    raw_eigenvalues, raw_eigenvectors = np.linalg.eigh(cov_mat)

    # Sort descending.
    sort_idx: np.ndarray = np.argsort(raw_eigenvalues)[::-1]
    all_eigenvalues: np.ndarray = raw_eigenvalues[sort_idx]
    all_eigenvectors: np.ndarray = raw_eigenvectors[:, sort_idx]  # shape (n_assets, n_assets)

    # Keep only the top n_factors components.
    eigenvalues: np.ndarray = all_eigenvalues[:n_factors].copy()
    loadings: np.ndarray = all_eigenvectors[:, :n_factors].copy()  # (n_assets, k)

    # Variance explained per factor.
    # numpy.linalg.eigh guarantees non-negative eigenvalues for a PSD matrix;
    # total_variance is always >= 0.  Guard against the exact-zero edge case
    # (all-constant, zero-variance panel) by clamping to max(total, eps).
    total_variance: float = float(max(all_eigenvalues.sum(), 1e-300))
    variance_explained = (eigenvalues / total_variance).astype(float)

    # Eigenportfolio weights (Avellaneda-Lee): w_j = v_j / sigma (per asset).
    # loadings shape: (n_assets, k); asset_stds shape: (n_assets,).
    # Reshape asset_stds to (n_assets, 1) so division broadcasts across k columns.
    # Result shape: (k, n_assets) -- one weight vector per factor.
    eigenportfolio_weights: np.ndarray = (loadings / asset_stds[:, np.newaxis]).T  # (k, n_assets)

    # Factor returns: project standardised returns onto the loading directions.
    # R_std shape: (n_obs, n_assets); loadings shape: (n_assets, k)
    # => factor_returns shape: (n_obs, k)
    factor_returns: np.ndarray = R_std @ loadings  # (n_obs, k)

    return PCAFactorResult(
        eigenvalues=eigenvalues,
        loadings=loadings,
        variance_explained=variance_explained,
        factor_returns=factor_returns,
        eigenportfolio_weights=eigenportfolio_weights,
        n_factors=int(n_factors),
        asset_names=asset_names,
    )


def residual_returns(
    returns: pd.DataFrame,
    result: PCAFactorResult,
) -> pd.DataFrame:
    """Remove the systematic (factor) component and return idiosyncratic residuals.

    For each asset i, estimates the factor loadings via OLS regression of
    the raw returns on the factor_returns from the PCA fit, then subtracts
    the systematic component:

        residual_{t,i} = r_{t,i} - F_t * beta_i^T

    where F_t is the (1 x k) vector of factor returns at time t and beta_i
    is the (k,) OLS coefficient vector for asset i.

    The residuals represent the idiosyncratic return component -- the part of
    each asset's return that is not explained by the common statistical factors.
    These are the series that a mean-reversion / stat-arb signal would trade.

    Parameters
    ----------
    returns:
        The same (or a compatible) cross-sectional returns panel used for the
        original PCA fit.  Must have the same columns (assets) in the same
        order as ``result.asset_names``.
    result:
        A fitted ``PCAFactorResult`` from :func:`fit_pca_factors`.

    Returns
    -------
    pd.DataFrame
        Idiosyncratic residual returns, same shape (n_obs x n_assets) and
        same index / columns as ``returns``.

    Raises
    ------
    ValueError
        If ``returns`` contains NaN values.
    """
    if returns.isnull().any().any():
        raise ValueError(
            "returns panel passed to residual_returns contains NaN values."
        )

    R: np.ndarray = returns.to_numpy(dtype=float)
    F: np.ndarray = result.factor_returns  # (n_obs, k)

    # OLS: R = F @ Beta^T + E  =>  Beta = (F^T F)^{-1} F^T R  shape (k, n_assets)
    # numpy.linalg.lstsq solves for each asset column simultaneously.
    design: np.ndarray = np.column_stack([np.ones(F.shape[0]), F])  # (n_obs, k+1)
    coef: np.ndarray
    coef, *_ = np.linalg.lstsq(design, R, rcond=None)  # (k+1, n_assets)

    # Systematic component: intercept + factor contribution.
    systematic: np.ndarray = design @ coef  # (n_obs, n_assets)
    residuals: np.ndarray = R - systematic  # (n_obs, n_assets)

    return pd.DataFrame(residuals, index=returns.index, columns=returns.columns)


def reconstruct(result: PCAFactorResult) -> np.ndarray:
    """Reconstruct the rank-k approximation of the standardised returns.

    Projects the factor returns back into asset space using the loadings:

        R_reconstructed = F_k @ loadings^T

    where F_k = factor_returns (n_obs x k) and loadings (n_assets x k).
    The result is the low-rank (rank-k) approximation of the standardised
    returns matrix.  The reconstruction error ||R_std - R_reconstructed||_F
    decreases as k increases and is zero when k == n_assets.

    Parameters
    ----------
    result:
        A fitted ``PCAFactorResult`` from :func:`fit_pca_factors`.

    Returns
    -------
    numpy.ndarray
        Rank-k reconstruction of the standardised returns, shape (n_obs, n_assets).
    """
    out: np.ndarray = np.asarray(result.factor_returns @ result.loadings.T, dtype=float)
    return out
