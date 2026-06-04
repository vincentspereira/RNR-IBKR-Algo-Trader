"""Hierarchical Risk Parity (Phase 6.3).

Lopez de Prado's HRP allocates capital through a cluster hierarchy instead
of through a quadratic program, which means it NEVER inverts the covariance
matrix.  That is its entire reason for existing in the Phase 6 stack: the
sample covariance of a realistic universe is near-singular (T not much
larger than N), Markowitz weights explode through Sigma^{-1}, while HRP
remains well-behaved on exactly the same input -- it even accepts a
singular (rank-deficient) PSD matrix outright.

The three steps (de Prado 2016, Snippets 16.1-16.4 in AFML 2018):

1. **Tree clustering.**  Convert the correlation matrix rho to the metric
       d_ij = sqrt( (1 - rho_ij) / 2 )
   (a true distance: d in [0, 1], 0 iff perfectly correlated) and run
   agglomerative hierarchical clustering on it (single linkage in the
   original paper; this module also allows complete / average / ward).

2. **Quasi-diagonalisation.**  Reorder assets into the dendrogram's
   leaf order so that highly correlated assets sit next to each other and
   the reordered covariance matrix is approximately block-diagonal.

3. **Recursive bisection.**  Starting from the full sorted list with unit
   weight, repeatedly split each contiguous cluster in half and divide
   the cluster's weight between the halves in inverse proportion to
   their variances:
       alpha_left = 1 - V_left / (V_left + V_right)
   where a half's variance is computed with inverse-variance weights
   within the half:
       V = w_ivp' Sigma_sub w_ivp,   w_ivp proportional to 1 / diag(Sigma_sub).

Known closed-form behaviour used by the test suite:
  * For a DIAGONAL covariance with a power-of-two number of assets, the
    recursive bisection reproduces the global inverse-variance portfolio
    exactly (each split allocates harmonic-mean cluster variances, which
    telescope to 1/sigma_i^2 weighting).
  * Weights are strictly positive and sum to 1 by construction (each
    split conserves the parent's weight).

Mathematical references
-----------------------
  * Lopez de Prado, M. (2016). "Building Diversified Portfolios that
    Outperform Out of Sample."
    Journal of Portfolio Management, 42(4), 59-69.
  * Lopez de Prado, M. (2018). "Advances in Financial Machine Learning."
    Wiley.  Chapter 16, Snippets 16.1-16.4.
  * Mueller, P. & Sibbertsen, P. (2021) and Raffinot, T. (2017) document
    the linkage-method sensitivity; the default here follows the paper
    (single linkage).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

__all__ = [
    "HRPConfig",
    "HRPResult",
    "correlation_distance",
    "hrp_weights",
]

_ALLOWED_LINKAGE = ("single", "complete", "average", "ward")


# ---------------------------------------------------------------------------
# Configuration / result DTOs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HRPConfig:
    """Parameters for Hierarchical Risk Parity.

    Attributes
    ----------
    linkage_method:
        Agglomerative linkage criterion passed to
        ``scipy.cluster.hierarchy.linkage``.  ``"single"`` is de Prado's
        original choice; ``"complete"``, ``"average"`` and ``"ward"`` are
        accepted alternatives.
    """

    linkage_method: str = "single"

    def __post_init__(self) -> None:
        """Validate parameter consistency."""
        if self.linkage_method not in _ALLOWED_LINKAGE:
            raise ValueError(
                f"linkage_method must be one of {_ALLOWED_LINKAGE}, "
                f"got {self.linkage_method!r}"
            )


@dataclass(frozen=True, slots=True)
class HRPResult:
    """Solved HRP portfolio.

    Attributes
    ----------
    weights:
        Long-only weights in the ORIGINAL asset order; strictly positive,
        sum exactly 1.
    sort_order:
        The quasi-diagonal (dendrogram leaf) ordering of the assets used
        by the recursive bisection.
    linkage:
        The (N-1, 4) scipy linkage matrix from the clustering step,
        retained for diagnostics / dendrogram plotting.
    """

    weights: pd.Series = field(compare=False)
    sort_order: tuple[str, ...]
    linkage: np.ndarray = field(compare=False)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_sigma(sigma: pd.DataFrame) -> np.ndarray:
    """Validate a covariance DataFrame for HRP.

    HRP needs symmetry, finite entries and strictly positive variances
    (the correlation transform divides by sqrt(diag)); it does NOT need
    positive definiteness -- rank-deficient PSD matrices are fine, which
    is the point of the method.

    Raises
    ------
    ValueError
        On shape/label problems, NaN, asymmetry, or a non-positive
        diagonal entry.
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
    diag = np.diag(arr)
    if bool((diag <= 0.0).any()):
        bad = [
            str(c) for c, v in zip(sigma.columns, diag, strict=True) if v <= 0.0
        ]
        raise ValueError(
            "HRP requires strictly positive variances (the correlation "
            f"transform divides by them); non-positive columns: {bad}."
        )
    sym: np.ndarray = (arr + arr.T) / 2.0
    return sym


def _ivp_weights(sub_cov: np.ndarray) -> np.ndarray:
    """Inverse-variance weights within a cluster (Snippet 16.1)."""
    inv = 1.0 / np.diag(sub_cov)
    out: np.ndarray = inv / float(inv.sum())
    return out


def _cluster_variance(cov: np.ndarray, items: list[int]) -> float:
    """Variance of a cluster under its internal IVP weights (Snippet 16.4)."""
    sub = cov[np.ix_(items, items)]
    w = _ivp_weights(sub)
    return float(w @ sub @ w)


def _recursive_bisection(cov: np.ndarray, sort_order: list[int]) -> np.ndarray:
    """De Prado's recursive bisection (Snippet 16.2) over integer positions.

    Returns weights aligned to the ORIGINAL asset positions (not the
    sorted order).
    """
    weights = np.ones(cov.shape[0], dtype=float)
    clusters: list[list[int]] = [list(sort_order)]
    while clusters:
        # Split every cluster with more than one element into halves.
        clusters = [
            half
            for cluster in clusters
            for half in (cluster[: len(cluster) // 2], cluster[len(cluster) // 2 :])
            if len(cluster) > 1
        ]
        # Pairs (left, right) sit at even/odd positions.
        for k in range(0, len(clusters), 2):
            left = clusters[k]
            right = clusters[k + 1]
            var_left = _cluster_variance(cov, left)
            var_right = _cluster_variance(cov, right)
            alpha = 1.0 - var_left / (var_left + var_right)
            weights[left] *= alpha
            weights[right] *= 1.0 - alpha
    return weights


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def correlation_distance(corr: np.ndarray) -> np.ndarray:
    """De Prado's correlation metric d = sqrt((1 - rho) / 2) (Snippet 16.4).

    Float residue can push a perfect correlation marginally above 1 (or
    below -1), which would make the square root NaN; inputs are therefore
    clipped to [-1, 1] and the diagonal is forced to exactly zero.

    Parameters
    ----------
    corr:
        Square correlation matrix (entries in [-1, 1] up to float noise).

    Returns
    -------
    numpy.ndarray
        Distance matrix in [0, 1] with a zero diagonal.

    Raises
    ------
    ValueError
        If the input is not a square 2-D array or strays materially
        (> 1e-8) outside [-1, 1].
    """
    arr = np.asarray(corr, dtype=float)
    if arr.ndim != 2 or arr.shape[0] != arr.shape[1]:
        raise ValueError(f"corr must be square 2-D; got shape {arr.shape}.")
    if float(np.abs(arr).max()) > 1.0 + 1e-8:
        raise ValueError(
            "corr contains entries materially outside [-1, 1]; "
            "this is not a correlation matrix."
        )
    clipped = np.clip(arr, -1.0, 1.0)
    dist: np.ndarray = np.sqrt((1.0 - clipped) / 2.0)
    np.fill_diagonal(dist, 0.0)
    return dist


def hrp_weights(
    sigma: pd.DataFrame,
    config: HRPConfig | None = None,
) -> HRPResult:
    """Compute the Hierarchical Risk Parity portfolio.

    Runs the three de Prado steps (cluster, quasi-diagonalise, recursively
    bisect; see module docstring) on the covariance matrix.  No matrix is
    inverted at any point, so a singular PSD ``sigma`` (e.g. a sample
    covariance with T < N) is perfectly acceptable input.

    Parameters
    ----------
    sigma:
        Covariance matrix: square, symmetric, finite, strictly positive
        diagonal, identical index/columns (asset labels).
    config:
        :class:`HRPConfig`; ``None`` uses single linkage (the paper).

    Returns
    -------
    HRPResult
        Long-only weights (original asset order), the quasi-diagonal
        sort order, and the scipy linkage matrix.

    Raises
    ------
    ValueError
        On invalid input (see :func:`_validate_sigma`).
    """
    from scipy.cluster.hierarchy import leaves_list, linkage  # deferred heavy import
    from scipy.spatial.distance import squareform

    cfg = config if config is not None else HRPConfig()
    cov = _validate_sigma(sigma)
    assets = [str(c) for c in sigma.index]

    vols = np.sqrt(np.diag(cov))
    corr = cov / np.outer(vols, vols)
    dist = correlation_distance(corr)

    # squareform requires an exactly-symmetric zero-diagonal matrix; the
    # validated symmetrised input guarantees it.
    condensed = squareform(dist, checks=False)
    link: np.ndarray = linkage(condensed, method=cfg.linkage_method)
    sort_order = [int(i) for i in leaves_list(link)]

    weights = _recursive_bisection(cov, sort_order)

    return HRPResult(
        weights=pd.Series(weights, index=assets),
        sort_order=tuple(assets[i] for i in sort_order),
        linkage=link,
    )
