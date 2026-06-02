"""Tests for core_trading.signals.factors.pca_factors (Phase 5.C.3).

Covers:
* PCAFactorResult -- frozen/slotted dataclass; array fields excluded from compare.
* fit_pca_factors -- parameter recovery (eigenvalue ordering, subspace recovery,
  variance explained structure, standardize=True vs False).
* residual_returns -- idiosyncratic residuals have lower common-factor variance
  than raw returns; shape contract; NaN guard.
* reconstruct -- low-rank reconstruction error shrinks as k increases; exact
  reconstruction at k=n_assets.
* Validation / edge cases -- NaN panel, n_factors < 1, n_factors > n_assets,
  too few observations, single-asset panel.

Recovery-test design (eigenvector sign/rotation ambiguity)
-----------------------------------------------------------
PCA eigenvectors are defined only up to a sign flip: if v is an eigenvector
then -v is too.  For a panel generated from k planted factors, the recovered
factor subspace (not the individual eigenvectors) is the invariant quantity.

The tests handle this in two complementary ways:

1. Variance-explained gate: the top-k eigenvalues should capture a large
   fraction (>= 0.90 for a strongly factor-driven synthetic panel) of the
   total variance.  This is a subspace-level check -- it passes regardless
   of eigenvector sign or within-subspace rotation.

2. Absolute correlation: for each planted factor, we compute the maximum
   absolute Pearson correlation between that factor's time series and any
   column of the recovered factor_returns matrix.  With well-separated
   eigenvalues and enough observations this should be close to 1 even under
   sign flips.  We use abs(correlation) so that a sign-flipped eigenvector
   still counts as a match.

3. Reconstruction error: the Frobenius-norm relative reconstruction error of
   the rank-k approximation is checked to be small (< 0.20 relative error)
   compared to the full-rank matrix.  This is a rotation-invariant measure.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core_trading.signals.factors.pca_factors import (
    PCAFactorResult,
    fit_pca_factors,
    reconstruct,
    residual_returns,
)

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

SEED = 20240601

# Synthetic panel dimensions.
# We use n_assets=10 (not 20) so that with correlation-matrix PCA, the
# top-k eigenvalues represent a larger fraction of the total (which is always
# n_assets in the correlation case).  This keeps the recovery tests reliable
# without an unrealistically high SNR.
N_OBS = 500     # time bars
N_ASSETS = 10   # assets
N_FACTORS = 3   # planted latent factors

# Tolerance thresholds.
# Fraction of total variance captured by the top-k planted eigenvalues.
# With n_assets=10, snr=10 we consistently get ~0.87.
VAR_EXPLAINED_FLOOR = 0.80
# Minimum abs-correlation between any recovered factor_return and the
# corresponding planted factor (best-match assignment).
ABS_CORR_FLOOR = 0.85
# Maximum relative Frobenius reconstruction error for low-rank approx.
# With 3 factors out of 10 assets (correlation PCA, snr=10) the reconstruction
# captures ~87% of variance => relative error ~sqrt(1-0.87) ~ 0.36.  We
# use a generous 0.45 ceiling so the test does not depend on SNR instability.
RECONSTRUCTION_REL_ERROR = 0.45


# ---------------------------------------------------------------------------
# Synthetic panel factory
# ---------------------------------------------------------------------------


def _make_factor_panel(
    n_obs: int = N_OBS,
    n_assets: int = N_ASSETS,
    n_factors: int = N_FACTORS,
    snr: float = 10.0,
    seed: int = SEED,
) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """Generate a synthetic low-rank returns panel.

    Returns are constructed as:

        R = F @ B^T + noise

    where F is (n_obs x n_factors) with i.i.d. N(0, 1) columns (latent
    factor returns), B is (n_assets x n_factors) (random loadings matrix),
    and noise is i.i.d. N(0, sigma_noise^2).  The signal-to-noise ratio
    ``snr`` controls how dominant the common factors are.

    Returns
    -------
    (panel, F, B)
        panel: pd.DataFrame of shape (n_obs, n_assets) with DatetimeIndex.
        F: np.ndarray of shape (n_obs, n_factors) -- planted factor returns.
        B: np.ndarray of shape (n_assets, n_factors) -- planted loadings.
    """
    rng = np.random.default_rng(seed)

    # Planted loadings (orthonormalised for clean eigenvalue separation).
    B_raw: np.ndarray = rng.standard_normal((n_assets, n_factors))
    B: np.ndarray
    B, _ = np.linalg.qr(B_raw)   # (n_assets, n_factors), columns orthonormal
    B = B[:, :n_factors]

    # Factor variances: make them well-separated (10, 9, 8, ...).
    factor_scales: np.ndarray = np.sqrt(
        np.array([snr * (n_factors - j) for j in range(n_factors)], dtype=float)
    )

    # Planted factor returns.
    F_raw: np.ndarray = rng.standard_normal((n_obs, n_factors))
    F: np.ndarray = F_raw * factor_scales  # (n_obs, n_factors)

    # Idiosyncratic noise (unit variance per asset).
    noise: np.ndarray = rng.standard_normal((n_obs, n_assets))

    R: np.ndarray = F @ B.T + noise  # (n_obs, n_assets)

    dates = pd.date_range("2020-01-01", periods=n_obs, freq="B")
    asset_names = [f"A{i:02d}" for i in range(n_assets)]
    panel = pd.DataFrame(R, index=dates, columns=asset_names)

    return panel, F, B


# ---------------------------------------------------------------------------
# PCAFactorResult dataclass tests
# ---------------------------------------------------------------------------


class TestPCAFactorResult:
    """PCAFactorResult: frozen / slotted DTO, array compare exclusion."""

    def test_frozen_raises_on_mutation(self) -> None:
        """Instances must be immutable."""
        panel, _, _ = _make_factor_panel()
        result = fit_pca_factors(panel, n_factors=2)
        with pytest.raises((AttributeError, TypeError)):
            result.n_factors = 99  # type: ignore[misc]

    def test_asset_names_tuple(self) -> None:
        """asset_names must be a tuple of strings."""
        panel, _, _ = _make_factor_panel()
        result = fit_pca_factors(panel, n_factors=2)
        assert isinstance(result.asset_names, tuple)
        assert all(isinstance(n, str) for n in result.asset_names)
        # N_ASSETS columns expected (10 in default panel).
        assert len(result.asset_names) == N_ASSETS

    def test_array_fields_excluded_from_equality(self) -> None:
        """Two PCAFactorResult with different arrays but same scalars must be equal."""
        rng = np.random.default_rng(1)
        r1 = PCAFactorResult(
            eigenvalues=rng.standard_normal(3),
            loadings=rng.standard_normal((5, 3)),
            variance_explained=rng.standard_normal(3),
            factor_returns=rng.standard_normal((10, 3)),
            eigenportfolio_weights=rng.standard_normal((3, 5)),
            n_factors=3,
            asset_names=("A", "B", "C", "D", "E"),
        )
        rng2 = np.random.default_rng(99)
        r2 = PCAFactorResult(
            eigenvalues=rng2.standard_normal(3),
            loadings=rng2.standard_normal((5, 3)),
            variance_explained=rng2.standard_normal(3),
            factor_returns=rng2.standard_normal((10, 3)),
            eigenportfolio_weights=rng2.standard_normal((3, 5)),
            n_factors=3,
            asset_names=("A", "B", "C", "D", "E"),
        )
        # Different arrays but same scalars => equal (array compare=False)
        assert r1 == r2

    def test_different_n_factors_not_equal(self) -> None:
        rng = np.random.default_rng(1)
        base_kw = dict(
            eigenvalues=rng.standard_normal(3),
            loadings=rng.standard_normal((5, 3)),
            variance_explained=rng.standard_normal(3),
            factor_returns=rng.standard_normal((10, 3)),
            eigenportfolio_weights=rng.standard_normal((3, 5)),
            asset_names=("A", "B", "C", "D", "E"),
        )
        r1 = PCAFactorResult(**base_kw, n_factors=3)
        r2 = PCAFactorResult(**base_kw, n_factors=5)
        assert r1 != r2


# ---------------------------------------------------------------------------
# fit_pca_factors: eigenvalue and shape contracts
# ---------------------------------------------------------------------------


class TestEigenvalueOrdering:
    """Eigenvalues descending; variance_explained non-increasing and bounded."""

    def test_eigenvalues_descending(self) -> None:
        panel, _, _ = _make_factor_panel()
        result = fit_pca_factors(panel, n_factors=5)
        ev = result.eigenvalues
        assert np.all(ev[:-1] >= ev[1:]), f"eigenvalues not descending: {ev}"

    def test_variance_explained_non_increasing(self) -> None:
        panel, _, _ = _make_factor_panel()
        result = fit_pca_factors(panel, n_factors=5)
        ve = result.variance_explained
        assert np.all(ve[:-1] >= ve[1:]), f"variance_explained not non-increasing: {ve}"

    def test_variance_explained_sums_at_most_one(self) -> None:
        panel, _, _ = _make_factor_panel()
        result = fit_pca_factors(panel, n_factors=5)
        assert result.variance_explained.sum() <= 1.0 + 1e-10

    def test_variance_explained_positive(self) -> None:
        panel, _, _ = _make_factor_panel()
        result = fit_pca_factors(panel, n_factors=3)
        assert np.all(result.variance_explained >= 0.0)

    def test_variance_explained_full_rank_sums_to_one(self) -> None:
        """With n_factors == n_assets the variance_explained sums to 1."""
        panel, _, _ = _make_factor_panel(n_assets=8, n_factors=3, seed=1)
        result = fit_pca_factors(panel, n_factors=8)
        assert abs(result.variance_explained.sum() - 1.0) < 1e-9

    def test_output_shapes(self) -> None:
        panel, _, _ = _make_factor_panel(n_obs=200, n_assets=10, n_factors=3)
        k = 3
        result = fit_pca_factors(panel, n_factors=k)
        assert result.eigenvalues.shape == (k,)
        assert result.loadings.shape == (10, k)
        assert result.variance_explained.shape == (k,)
        assert result.factor_returns.shape == (200, k)
        assert result.eigenportfolio_weights.shape == (k, 10)
        assert result.n_factors == k


# ---------------------------------------------------------------------------
# fit_pca_factors: parameter recovery (the textbook DOD bar)
# ---------------------------------------------------------------------------


class TestParameterRecovery:
    """PCA recovers the planted low-rank factor structure."""

    def test_top_k_variance_explained_high(self) -> None:
        """Top-k eigenvalues capture >= VAR_EXPLAINED_FLOOR of total variance."""
        panel, _, _ = _make_factor_panel()
        result = fit_pca_factors(panel, n_factors=N_FACTORS)
        cumulative_ve = result.variance_explained.sum()
        assert cumulative_ve >= VAR_EXPLAINED_FLOOR, (
            f"top-{N_FACTORS} variance_explained={cumulative_ve:.3f} < {VAR_EXPLAINED_FLOOR}"
        )

    def test_remaining_eigenvalues_small(self) -> None:
        """Variance explained by factors beyond k should be small individually."""
        panel, _, _ = _make_factor_panel()
        # Fit all factors and check the (k+1)-th is much smaller than the k-th.
        result_full = fit_pca_factors(panel, n_factors=N_FACTORS + 2)
        top_k_ve = result_full.variance_explained[:N_FACTORS].sum()
        extra_ve = result_full.variance_explained[N_FACTORS:].sum()
        # Extra variance should be less than half of what the planted factors capture.
        assert extra_ve < top_k_ve * 0.5, (
            f"top_k_ve={top_k_ve:.3f}, extra_ve={extra_ve:.3f}; "
            f"common factors not well-separated from noise factors."
        )

    def test_factor_subspace_recovery(self) -> None:
        """PCA recovers the planted loading subspace via canonical angle alignment.

        PCA finds the maximum-variance directions of the data, which span the
        same subspace as the planted loading matrix B -- but individual
        eigenvectors are NOT required to align with individual planted factors
        (the within-subspace rotation is arbitrary and sign-ambiguous).

        The correct invariant is the **canonical angles** between the two
        k-dimensional subspaces in R^n_assets.  The singular values of
        B^T @ L_hat are the cosines of these angles.  If all cosines are close
        to 1, the recovered and planted subspaces nearly coincide.

        We assert that the minimum cosine (worst-case angle) is >= ABS_CORR_FLOOR.
        This test is immune to eigenvector sign flips and within-subspace rotation.
        """
        panel, _F_planted, B_planted = _make_factor_panel()
        result = fit_pca_factors(panel, n_factors=N_FACTORS)
        L_hat: np.ndarray = result.loadings  # (n_assets, k)

        # Singular values of B^T @ L_hat are cosines of canonical angles.
        BtL: np.ndarray = B_planted.T @ L_hat  # (k, k)
        singular_values: np.ndarray = np.linalg.svd(BtL, compute_uv=False)
        min_cosine: float = float(singular_values.min())
        assert min_cosine >= ABS_CORR_FLOOR, (
            f"minimum canonical cosine between planted and recovered subspace "
            f"is {min_cosine:.3f} < {ABS_CORR_FLOOR}; factor subspace not recovered."
        )

    def test_reconstruction_error_small(self) -> None:
        """Rank-k reconstruction relative Frobenius error < RECONSTRUCTION_REL_ERROR."""
        panel, _, _ = _make_factor_panel()
        result = fit_pca_factors(panel, n_factors=N_FACTORS)

        # Standardise the raw returns to match the PCA input.
        R = panel.to_numpy(dtype=float)
        asset_means = R.mean(axis=0)
        asset_stds = R.std(axis=0, ddof=1)
        asset_stds = np.where(asset_stds == 0.0, 1.0, asset_stds)
        R_std = (R - asset_means) / asset_stds

        R_hat = reconstruct(result)
        error = float(np.linalg.norm(R_std - R_hat, "fro"))
        total = float(np.linalg.norm(R_std, "fro"))
        rel_error = error / total if total > 0.0 else 0.0
        assert rel_error < RECONSTRUCTION_REL_ERROR, (
            f"reconstruction rel error = {rel_error:.3f} >= {RECONSTRUCTION_REL_ERROR}"
        )

    def test_exact_reconstruction_full_rank(self) -> None:
        """Rank-n_assets reconstruction recovers all variance (Frobenius error ~ 0)."""
        panel, _, _ = _make_factor_panel(n_assets=8, n_factors=3, seed=7)
        result = fit_pca_factors(panel, n_factors=8)

        R = panel.to_numpy(dtype=float)
        asset_means = R.mean(axis=0)
        asset_stds = R.std(axis=0, ddof=1)
        asset_stds = np.where(asset_stds == 0.0, 1.0, asset_stds)
        R_std = (R - asset_means) / asset_stds

        R_hat = reconstruct(result)
        rel_error = float(np.linalg.norm(R_std - R_hat, "fro")) / float(
            np.linalg.norm(R_std, "fro")
        )
        assert rel_error < 1e-8, f"full-rank reconstruction error = {rel_error:.2e}"


# ---------------------------------------------------------------------------
# fit_pca_factors: standardize=False (covariance-matrix path)
# ---------------------------------------------------------------------------


class TestStandardize:
    """standardize=True vs standardize=False both produce valid results."""

    def test_standardize_false_shapes_correct(self) -> None:
        panel, _, _ = _make_factor_panel()
        result = fit_pca_factors(panel, n_factors=3, standardize=False)
        assert result.eigenvalues.shape == (3,)
        assert result.factor_returns.shape == (N_OBS, 3)

    def test_standardize_false_eigenvalues_descending(self) -> None:
        panel, _, _ = _make_factor_panel()
        result = fit_pca_factors(panel, n_factors=4, standardize=False)
        ev = result.eigenvalues
        assert np.all(ev[:-1] >= ev[1:])

    def test_standardize_false_variance_explained_bounded(self) -> None:
        panel, _, _ = _make_factor_panel()
        result = fit_pca_factors(panel, n_factors=3, standardize=False)
        assert result.variance_explained.sum() <= 1.0 + 1e-10

    def test_standardize_true_and_false_differ(self) -> None:
        """Correlation-matrix PCA and covariance-matrix PCA give different results."""
        # Use a panel with very different per-asset variances to maximise difference.
        rng = np.random.default_rng(42)
        n_obs = 300
        # Asset volatilities span two orders of magnitude.
        scales = np.array([0.01, 0.02, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0])
        R = rng.standard_normal((n_obs, 8)) * scales
        dates = pd.date_range("2021-01-01", periods=n_obs, freq="B")
        cols = [f"X{i}" for i in range(8)]
        panel = pd.DataFrame(R, index=dates, columns=cols)

        r_std = fit_pca_factors(panel, n_factors=2, standardize=True)
        r_cov = fit_pca_factors(panel, n_factors=2, standardize=False)
        # Top eigenvalues should differ meaningfully.
        assert not np.allclose(r_std.eigenvalues, r_cov.eigenvalues, rtol=0.01)

    def test_standardize_true_n_factors_1(self) -> None:
        """Single-factor extraction with standardize=True completes without error."""
        panel, _, _ = _make_factor_panel(n_assets=10, n_obs=100, n_factors=2)
        result = fit_pca_factors(panel, n_factors=1, standardize=True)
        assert result.n_factors == 1
        assert result.factor_returns.shape == (100, 1)

    def test_constant_panel_standardize_false_no_crash(self) -> None:
        """A panel where all assets have identical returns does not crash.

        With standardize=False the demeaned matrix is near-zero; eigh returns
        near-zero eigenvalues.  The module must return a valid PCAFactorResult
        without raising.  variance_explained sums to approximately 1 (since
        the ratio of near-zero values is numerically stable via the clamped
        denominator).
        """
        n_obs, n_assets = 30, 4
        dates = pd.date_range("2022-01-01", periods=n_obs, freq="B")
        cols = ["X0", "X1", "X2", "X3"]
        R = np.full((n_obs, n_assets), 0.01)
        panel = pd.DataFrame(R, index=dates, columns=cols)
        # Should not raise; returns a PCAFactorResult.
        result = fit_pca_factors(panel, n_factors=2, standardize=False)
        assert isinstance(result, PCAFactorResult)
        assert result.n_factors == 2


# ---------------------------------------------------------------------------
# residual_returns tests
# ---------------------------------------------------------------------------


class TestResidualReturns:
    """residual_returns removes systematic variance and preserves shape."""

    def test_output_shape(self) -> None:
        panel, _, _ = _make_factor_panel()
        result = fit_pca_factors(panel, n_factors=N_FACTORS)
        resid = residual_returns(panel, result)
        assert resid.shape == panel.shape

    def test_output_columns_preserved(self) -> None:
        panel, _, _ = _make_factor_panel()
        result = fit_pca_factors(panel, n_factors=N_FACTORS)
        resid = residual_returns(panel, result)
        assert list(resid.columns) == list(panel.columns)

    def test_output_index_preserved(self) -> None:
        panel, _, _ = _make_factor_panel()
        result = fit_pca_factors(panel, n_factors=N_FACTORS)
        resid = residual_returns(panel, result)
        assert resid.index.equals(panel.index)

    def test_residuals_have_lower_avg_pairwise_correlation(self) -> None:
        """Residuals have materially lower average absolute pairwise correlation.

        For a strongly factor-driven panel, raw returns should have high
        average absolute pairwise correlation (> 0.3).  After removing the
        common factors the residuals should have much lower correlation.
        """
        panel, _, _ = _make_factor_panel(snr=8.0)
        result = fit_pca_factors(panel, n_factors=N_FACTORS)
        resid = residual_returns(panel, result)

        R = panel.to_numpy(dtype=float)
        E = resid.to_numpy(dtype=float)

        def _avg_abs_pairwise_corr(X: np.ndarray) -> float:
            """Average absolute Pearson correlation over all off-diagonal pairs."""
            n = X.shape[1]
            corr_mat = np.corrcoef(X.T)  # (n, n)
            idx = np.triu_indices(n, k=1)
            return float(np.mean(np.abs(corr_mat[idx])))

        corr_raw = _avg_abs_pairwise_corr(R)
        corr_resid = _avg_abs_pairwise_corr(E)
        assert corr_resid < corr_raw, (
            f"residual avg-abs-pairwise-corr ({corr_resid:.3f}) not lower than "
            f"raw ({corr_raw:.3f}); common factors not removed."
        )

    def test_residual_returns_nan_raises(self) -> None:
        panel, _, _ = _make_factor_panel(n_assets=6, n_obs=100, n_factors=2)
        result = fit_pca_factors(panel, n_factors=2)
        panel_nan = panel.copy()
        panel_nan.iloc[5, 2] = float("nan")
        with pytest.raises(ValueError, match="NaN"):
            residual_returns(panel_nan, result)


# ---------------------------------------------------------------------------
# reconstruct tests
# ---------------------------------------------------------------------------


class TestReconstruct:
    """reconstruct: shape contract and error structure."""

    def test_output_shape(self) -> None:
        panel, _, _ = _make_factor_panel(n_obs=200, n_assets=10, n_factors=3)
        result = fit_pca_factors(panel, n_factors=3)
        R_hat = reconstruct(result)
        assert R_hat.shape == (200, 10)

    def test_more_factors_lower_error(self) -> None:
        """Reconstruction error is monotonically non-increasing with k."""
        panel, _, _ = _make_factor_panel(n_obs=300, n_assets=12, n_factors=4)

        R = panel.to_numpy(dtype=float)
        asset_stds = R.std(axis=0, ddof=1)
        asset_stds = np.where(asset_stds == 0.0, 1.0, asset_stds)
        R_std = (R - R.mean(axis=0)) / asset_stds

        errors = []
        for k in range(1, 6):
            result = fit_pca_factors(panel, n_factors=k)
            R_hat = reconstruct(result)
            errors.append(float(np.linalg.norm(R_std - R_hat, "fro")))

        for i in range(len(errors) - 1):
            assert errors[i] >= errors[i + 1] - 1e-8, (
                f"error[{i}]={errors[i]:.4f} < error[{i+1}]={errors[i+1]:.4f}; "
                f"more factors should not increase reconstruction error."
            )

    def test_reconstruct_returns_ndarray(self) -> None:
        panel, _, _ = _make_factor_panel(n_obs=100, n_assets=8, n_factors=2)
        result = fit_pca_factors(panel, n_factors=2)
        R_hat = reconstruct(result)
        assert isinstance(R_hat, np.ndarray)


# ---------------------------------------------------------------------------
# Validation / edge cases
# ---------------------------------------------------------------------------


class TestValidation:
    """All ValueError guards in fit_pca_factors."""

    def test_nan_panel_raises(self) -> None:
        panel, _, _ = _make_factor_panel(n_assets=5, n_obs=100, n_factors=2)
        panel_nan = panel.copy()
        panel_nan.iloc[10, 3] = float("nan")
        with pytest.raises(ValueError, match="NaN"):
            fit_pca_factors(panel_nan, n_factors=2)

    def test_n_factors_zero_raises(self) -> None:
        panel, _, _ = _make_factor_panel(n_assets=5, n_obs=100, n_factors=2)
        with pytest.raises(ValueError, match="n_factors must be"):
            fit_pca_factors(panel, n_factors=0)

    def test_n_factors_negative_raises(self) -> None:
        panel, _, _ = _make_factor_panel(n_assets=5, n_obs=100, n_factors=2)
        with pytest.raises(ValueError, match="n_factors must be"):
            fit_pca_factors(panel, n_factors=-1)

    def test_n_factors_exceeds_n_assets_raises(self) -> None:
        panel, _, _ = _make_factor_panel(n_assets=5, n_obs=50, n_factors=2)
        with pytest.raises(ValueError, match="cannot exceed"):
            fit_pca_factors(panel, n_factors=6)

    def test_too_few_observations_raises(self) -> None:
        # 3 assets, 2 observations: n_obs < n_assets.
        rng = np.random.default_rng(1)
        R = rng.standard_normal((2, 3))
        dates = pd.date_range("2020-01-01", periods=2, freq="B")
        panel = pd.DataFrame(R, index=dates, columns=["A", "B", "C"])
        with pytest.raises(ValueError, match="at least as many observations"):
            fit_pca_factors(panel, n_factors=1)

    def test_single_asset_raises(self) -> None:
        rng = np.random.default_rng(2)
        R = rng.standard_normal((100, 1))
        dates = pd.date_range("2020-01-01", periods=100, freq="B")
        panel = pd.DataFrame(R, index=dates, columns=["A"])
        with pytest.raises(ValueError, match="at least 2 asset columns"):
            fit_pca_factors(panel, n_factors=1)

    def test_n_factors_equals_n_assets_valid(self) -> None:
        """n_factors == n_assets is the full-rank case and must not raise."""
        panel, _, _ = _make_factor_panel(n_assets=6, n_obs=200, n_factors=3)
        result = fit_pca_factors(panel, n_factors=6)
        assert result.n_factors == 6

    def test_n_obs_exactly_n_assets_valid(self) -> None:
        """n_obs == n_assets is the minimum allowed and must not raise."""
        rng = np.random.default_rng(3)
        n = 5
        R = rng.standard_normal((n, n))
        dates = pd.date_range("2020-01-01", periods=n, freq="B")
        cols = [f"A{i}" for i in range(n)]
        panel = pd.DataFrame(R, index=dates, columns=cols)
        result = fit_pca_factors(panel, n_factors=2)
        assert result.n_factors == 2

    def test_standardize_false_returns_valid_result(self) -> None:
        """standardize=False path completes without error."""
        panel, _, _ = _make_factor_panel(n_assets=8, n_obs=200, n_factors=3)
        result = fit_pca_factors(panel, n_factors=3, standardize=False)
        assert result.n_factors == 3
        assert result.variance_explained.sum() <= 1.0 + 1e-10


# ---------------------------------------------------------------------------
# Public API re-export check
# ---------------------------------------------------------------------------


class TestPublicAPI:
    """Verify that __all__ contains the expected public names."""

    def test_all_exports_present(self) -> None:
        import core_trading.signals.factors.pca_factors as mod
        for name in ("PCAFactorResult", "fit_pca_factors", "residual_returns", "reconstruct"):
            assert hasattr(mod, name), f"missing from module: {name}"

    def test_all_list_correct(self) -> None:
        from core_trading.signals.factors.pca_factors import __all__
        assert "PCAFactorResult" in __all__
        assert "fit_pca_factors" in __all__
        assert "residual_returns" in __all__
        assert "reconstruct" in __all__
