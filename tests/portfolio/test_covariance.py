"""Tests for core_trading.portfolio.covariance (Phase 6, Batch 1).

Covers:
* Panel validation shared across all five estimators.
* sample_covariance: exact agreement with numpy/pandas, ddof handling.
* ledoit_wolf_covariance: agreement with an independent loop-based
  transcription of Ledoit-Wolf (2004a) AND with scikit-learn's
  implementation (same estimator); shrinkage bounds; the d^2 = 0 guard;
  parameter recovery against synthetic truth (must beat the sample
  estimator in Frobenius error when T is small relative to N); the
  condition-number repair that motivates shrinkage.
* oas_covariance: agreement with a literal eigenvalue-based transcription
  of Chen et al. (2010) Eq. 23; shrinkage bounds and monotonicity in T;
  the zero-denominator guard; parameter recovery against synthetic truth.
* constant_correlation_covariance: agreement with the loop-based
  Appendix-A/B reference; variance preservation on the diagonal; the
  N = 2 gamma_hat = 0 short-circuit; the zero-variance rejection;
  parameter recovery on a true constant-correlation universe.
* factor_model_covariance: PSD-by-construction, diagonal preservation,
  k = N degeneracy to the sample matrix, low-rank structure, parameter
  recovery on a true k-factor universe, validation propagation.
* nearest_psd: projection of indefinite matrices, identity on PSD input,
  epsilon floor, symmetrisation, input validation.
* condition_number: known values, singular -> inf, input validation.
* CovarianceResult DTO semantics (frozen, matrix excluded from equality).
* Phase 6 DOD: all estimators on a 20-asset universe complete in < 1 s.
"""

from __future__ import annotations

import dataclasses
import time

import numpy as np
import pandas as pd
import pytest

from core_trading.portfolio.covariance import (
    CovarianceResult,
    condition_number,
    constant_correlation_covariance,
    factor_model_covariance,
    ledoit_wolf_covariance,
    nearest_psd,
    oas_covariance,
    sample_covariance,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _panel(arr: np.ndarray) -> pd.DataFrame:
    """Wrap an array in the standard returns-panel shape."""
    n_obs, n_assets = arr.shape
    index = pd.date_range("2024-01-01", periods=n_obs, freq="B")
    columns = [f"A{i:02d}" for i in range(n_assets)]
    return pd.DataFrame(arr, index=index, columns=columns)


def _random_panel(seed: int, n_obs: int, n_assets: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return _panel(rng.standard_normal((n_obs, n_assets)) * 0.01)


def _random_sigma(rng: np.random.Generator, n_assets: int) -> np.ndarray:
    """Random symmetric positive-definite matrix with moderate eigen spread."""
    q, _ = np.linalg.qr(rng.standard_normal((n_assets, n_assets)))
    eigenvalues = rng.uniform(0.5, 2.0, size=n_assets)
    sigma = (q * eigenvalues) @ q.T
    return (sigma + sigma.T) / 2.0


def _mvn_panel(
    rng: np.random.Generator, sigma: np.ndarray, n_obs: int
) -> pd.DataFrame:
    """Sample T observations from N(0, sigma) via Cholesky (no numpy warnings)."""
    chol = np.linalg.cholesky(sigma)
    z = rng.standard_normal((n_obs, sigma.shape[0]))
    return _panel(z @ chol.T)


def _frob_error(estimate: pd.DataFrame, truth: np.ndarray) -> float:
    return float(np.sqrt(((estimate.to_numpy() - truth) ** 2).sum()))


def _ml_sample_cov(arr: np.ndarray) -> np.ndarray:
    x = arr - arr.mean(axis=0)
    return (x.T @ x) / float(arr.shape[0])


# Orthogonal equal-variance columns: ML sample covariance is exactly the
# 2 x 2 identity, which exercises the scaled-identity degeneracy guards
# (d^2 = 0 in Ledoit-Wolf, zero denominator in OAS).
_IDENTITY_PANEL = _panel(
    np.array(
        [
            [1.0, 1.0],
            [-1.0, 1.0],
            [1.0, -1.0],
            [-1.0, -1.0],
        ]
    )
)


# ---------------------------------------------------------------------------
# Reference implementations (independent, loop-based, straight from the papers)
# ---------------------------------------------------------------------------


def _lw_reference(arr: np.ndarray) -> tuple[np.ndarray, float]:
    """Ledoit-Wolf (2004a) via explicit per-observation outer products."""
    n_obs, n_assets = arr.shape
    x = arr - arr.mean(axis=0)
    s = (x.T @ x) / float(n_obs)
    m = float(np.trace(s)) / n_assets
    d2 = float(((s - m * np.eye(n_assets)) ** 2).sum()) / n_assets
    b_bar2 = 0.0
    for t in range(n_obs):
        outer = np.outer(x[t], x[t])
        b_bar2 += float(((outer - s) ** 2).sum())
    b_bar2 /= float(n_obs) ** 2 * n_assets
    b2 = min(b_bar2, d2)
    delta = 0.0 if d2 <= 0.0 else b2 / d2
    return delta * m * np.eye(n_assets) + (1.0 - delta) * s, delta


def _oas_reference(arr: np.ndarray) -> tuple[np.ndarray, float]:
    """Chen et al. (2010) Eq. 23 via eigenvalues (tr(S^p) = sum eig^p)."""
    n_obs, n_assets = arr.shape
    s = _ml_sample_cov(arr)
    eig = np.linalg.eigvalsh(s)
    tr_s = float(eig.sum())
    tr_s2 = float((eig**2).sum())
    n = float(n_assets)
    t = float(n_obs)
    num = (1.0 - 2.0 / n) * tr_s2 + tr_s**2
    den = (t + 1.0 - 2.0 / n) * (tr_s2 - tr_s**2 / n)
    delta = 1.0 if den <= 0.0 else min(num / den, 1.0)
    m = tr_s / n
    return (1.0 - delta) * s + delta * m * np.eye(n_assets), delta


def _cc_reference(arr: np.ndarray) -> tuple[np.ndarray, float]:
    """Ledoit-Wolf (2004b) constant-correlation shrinkage, explicit loops."""
    n_obs, n_assets = arr.shape
    x = arr - arr.mean(axis=0)
    s = (x.T @ x) / float(n_obs)
    var = np.diag(s)
    sd = np.sqrt(var)

    r_sum = 0.0
    for i in range(n_assets):
        for j in range(n_assets):
            if i != j:
                r_sum += s[i, j] / (sd[i] * sd[j])
    r_bar = r_sum / float(n_assets * (n_assets - 1))

    target = np.empty((n_assets, n_assets))
    for i in range(n_assets):
        for j in range(n_assets):
            target[i, j] = var[i] if i == j else r_bar * sd[i] * sd[j]

    pi_mat = np.empty((n_assets, n_assets))
    for i in range(n_assets):
        for j in range(n_assets):
            pi_mat[i, j] = float(
                np.mean((x[:, i] * x[:, j] - s[i, j]) ** 2)
            )
    pi_hat = float(pi_mat.sum())

    def theta(i: int, j: int) -> float:
        return float(
            np.mean((x[:, i] ** 2 - var[i]) * (x[:, i] * x[:, j] - s[i, j]))
        )

    rho_hat = float(np.trace(pi_mat))
    for i in range(n_assets):
        for j in range(n_assets):
            if i != j:
                rho_hat += (
                    r_bar
                    / 2.0
                    * (
                        np.sqrt(var[j] / var[i]) * theta(i, j)
                        + np.sqrt(var[i] / var[j]) * theta(j, i)
                    )
                )

    gamma_hat = float(((target - s) ** 2).sum())
    if gamma_hat <= 0.0:
        delta = 0.0
    else:
        delta = float(np.clip((pi_hat - rho_hat) / gamma_hat / n_obs, 0.0, 1.0))
    return delta * target + (1.0 - delta) * s, delta


# ---------------------------------------------------------------------------
# Shared validation
# ---------------------------------------------------------------------------

_ESTIMATORS = [
    pytest.param(sample_covariance, id="sample"),
    pytest.param(ledoit_wolf_covariance, id="ledoit_wolf"),
    pytest.param(oas_covariance, id="oas"),
    pytest.param(constant_correlation_covariance, id="constant_correlation"),
    pytest.param(
        lambda df: factor_model_covariance(df, n_factors=1), id="factor_model"
    ),
]


class TestSharedValidation:
    @pytest.mark.parametrize("estimator", _ESTIMATORS)
    def test_nan_panel_raises(self, estimator) -> None:  # type: ignore[no-untyped-def]
        panel = _random_panel(0, 10, 3)
        panel.iloc[4, 1] = np.nan
        with pytest.raises(ValueError, match="NaN"):
            estimator(panel)

    @pytest.mark.parametrize("estimator", _ESTIMATORS)
    def test_single_asset_raises(self, estimator) -> None:  # type: ignore[no-untyped-def]
        panel = _random_panel(0, 10, 3).iloc[:, :1]
        with pytest.raises(ValueError, match="at least 2 asset"):
            estimator(panel)

    @pytest.mark.parametrize("estimator", _ESTIMATORS)
    def test_single_observation_raises(self, estimator) -> None:  # type: ignore[no-untyped-def]
        panel = _random_panel(0, 10, 3).iloc[:1, :]
        with pytest.raises(ValueError, match="at least 2 observation"):
            estimator(panel)

    @pytest.mark.parametrize("estimator", _ESTIMATORS)
    def test_labels_symmetry_and_finiteness(self, estimator) -> None:  # type: ignore[no-untyped-def]
        panel = _random_panel(7, 60, 5)
        result = estimator(panel)
        cov = result.covariance
        assert list(cov.index) == list(panel.columns)
        assert list(cov.columns) == list(panel.columns)
        arr = cov.to_numpy()
        assert np.isfinite(arr).all()
        np.testing.assert_allclose(arr, arr.T, atol=1e-14)


# ---------------------------------------------------------------------------
# sample_covariance
# ---------------------------------------------------------------------------


class TestSampleCovariance:
    def test_matches_pandas_and_numpy_ddof1(self) -> None:
        panel = _random_panel(1, 40, 4)
        result = sample_covariance(panel)
        np.testing.assert_allclose(
            result.covariance.to_numpy(), panel.cov().to_numpy(), atol=1e-15
        )
        np.testing.assert_allclose(
            result.covariance.to_numpy(),
            np.cov(panel.to_numpy().T, ddof=1),
            atol=1e-15,
        )
        assert result.method == "sample"
        assert result.shrinkage is None
        assert result.n_factors is None

    def test_ddof_zero_matches_numpy(self) -> None:
        panel = _random_panel(2, 25, 3)
        result = sample_covariance(panel, ddof=0)
        np.testing.assert_allclose(
            result.covariance.to_numpy(),
            np.cov(panel.to_numpy().T, ddof=0),
            atol=1e-15,
        )

    @pytest.mark.parametrize("bad_ddof", [-1, 25, 30])
    def test_invalid_ddof_raises(self, bad_ddof: int) -> None:
        panel = _random_panel(3, 25, 3)
        with pytest.raises(ValueError, match="ddof"):
            sample_covariance(panel, ddof=bad_ddof)


# ---------------------------------------------------------------------------
# ledoit_wolf_covariance
# ---------------------------------------------------------------------------


class TestLedoitWolf:
    @pytest.mark.parametrize("seed,n_obs,n_assets", [(0, 50, 5), (1, 30, 10), (2, 120, 8)])
    def test_matches_loop_reference(
        self, seed: int, n_obs: int, n_assets: int
    ) -> None:
        panel = _random_panel(seed, n_obs, n_assets)
        result = ledoit_wolf_covariance(panel)
        ref_cov, ref_delta = _lw_reference(panel.to_numpy())
        assert result.shrinkage == pytest.approx(ref_delta, abs=1e-12)
        np.testing.assert_allclose(
            result.covariance.to_numpy(), ref_cov, atol=1e-12
        )
        assert result.method == "ledoit_wolf"

    @pytest.mark.parametrize("seed,n_obs,n_assets", [(0, 50, 5), (4, 40, 12)])
    def test_matches_sklearn(self, seed: int, n_obs: int, n_assets: int) -> None:
        from sklearn.covariance import ledoit_wolf as sk_ledoit_wolf

        panel = _random_panel(seed, n_obs, n_assets)
        result = ledoit_wolf_covariance(panel)
        sk_cov, sk_delta = sk_ledoit_wolf(panel.to_numpy())
        assert result.shrinkage == pytest.approx(sk_delta, abs=1e-10)
        np.testing.assert_allclose(
            result.covariance.to_numpy(), sk_cov, atol=1e-12
        )

    def test_shrinkage_in_unit_interval(self) -> None:
        for seed in range(5):
            result = ledoit_wolf_covariance(_random_panel(seed, 15, 12))
            assert result.shrinkage is not None
            assert 0.0 <= result.shrinkage <= 1.0

    def test_scaled_identity_sample_short_circuit(self) -> None:
        result = ledoit_wolf_covariance(_IDENTITY_PANEL)
        assert result.shrinkage == 0.0
        np.testing.assert_allclose(
            result.covariance.to_numpy(), np.eye(2), atol=1e-15
        )

    def test_parameter_recovery_beats_sample(self) -> None:
        # T = 30 observations of N = 20 assets: the sample covariance is
        # near-singular; shrinkage must reduce Frobenius error to the truth.
        lw_errors = []
        sample_errors = []
        for seed in range(10):
            rng = np.random.default_rng(seed)
            sigma = _random_sigma(rng, 20)
            panel = _mvn_panel(rng, sigma, 30)
            lw_errors.append(_frob_error(ledoit_wolf_covariance(panel).covariance, sigma))
            sample_errors.append(
                _frob_error(sample_covariance(panel, ddof=0).covariance, sigma)
            )
        assert float(np.mean(lw_errors)) < float(np.mean(sample_errors))

    def test_repairs_condition_number(self) -> None:
        rng = np.random.default_rng(11)
        sigma = _random_sigma(rng, 20)
        panel = _mvn_panel(rng, sigma, 25)
        cond_sample = condition_number(sample_covariance(panel, ddof=0).covariance.to_numpy())
        cond_lw = condition_number(ledoit_wolf_covariance(panel).covariance.to_numpy())
        assert cond_lw < cond_sample


# ---------------------------------------------------------------------------
# oas_covariance
# ---------------------------------------------------------------------------


class TestOAS:
    @pytest.mark.parametrize("seed,n_obs,n_assets", [(0, 50, 5), (1, 30, 10), (2, 120, 8)])
    def test_matches_eigenvalue_reference(
        self, seed: int, n_obs: int, n_assets: int
    ) -> None:
        panel = _random_panel(seed, n_obs, n_assets)
        result = oas_covariance(panel)
        ref_cov, ref_delta = _oas_reference(panel.to_numpy())
        assert result.shrinkage == pytest.approx(ref_delta, abs=1e-12)
        np.testing.assert_allclose(
            result.covariance.to_numpy(), ref_cov, atol=1e-12
        )
        assert result.method == "oas"

    def test_shrinkage_in_unit_interval(self) -> None:
        for seed in range(5):
            result = oas_covariance(_random_panel(seed, 15, 12))
            assert result.shrinkage is not None
            assert 0.0 <= result.shrinkage <= 1.0

    def test_shrinkage_decreases_with_more_data(self) -> None:
        rng = np.random.default_rng(5)
        sigma = _random_sigma(rng, 10)
        small = oas_covariance(_mvn_panel(rng, sigma, 20)).shrinkage
        large = oas_covariance(_mvn_panel(rng, sigma, 2000)).shrinkage
        assert small is not None and large is not None
        assert large < small

    def test_zero_denominator_guard(self) -> None:
        result = oas_covariance(_IDENTITY_PANEL)
        assert result.shrinkage == 1.0
        np.testing.assert_allclose(
            result.covariance.to_numpy(), np.eye(2), atol=1e-15
        )

    def test_parameter_recovery_beats_sample(self) -> None:
        oas_errors = []
        sample_errors = []
        for seed in range(10):
            rng = np.random.default_rng(100 + seed)
            sigma = _random_sigma(rng, 20)
            panel = _mvn_panel(rng, sigma, 30)
            oas_errors.append(_frob_error(oas_covariance(panel).covariance, sigma))
            sample_errors.append(
                _frob_error(sample_covariance(panel, ddof=0).covariance, sigma)
            )
        assert float(np.mean(oas_errors)) < float(np.mean(sample_errors))


# ---------------------------------------------------------------------------
# constant_correlation_covariance
# ---------------------------------------------------------------------------


class TestConstantCorrelation:
    @pytest.mark.parametrize("seed,n_obs,n_assets", [(0, 40, 5), (1, 60, 8), (2, 35, 4)])
    def test_matches_loop_reference(
        self, seed: int, n_obs: int, n_assets: int
    ) -> None:
        panel = _random_panel(seed, n_obs, n_assets)
        result = constant_correlation_covariance(panel)
        ref_cov, ref_delta = _cc_reference(panel.to_numpy())
        assert result.shrinkage == pytest.approx(ref_delta, abs=1e-12)
        np.testing.assert_allclose(
            result.covariance.to_numpy(), ref_cov, atol=1e-12
        )
        assert result.method == "constant_correlation"

    def test_diagonal_preserves_sample_variances(self) -> None:
        panel = _random_panel(3, 50, 6)
        result = constant_correlation_covariance(panel)
        ml_cov = _ml_sample_cov(panel.to_numpy())
        np.testing.assert_allclose(
            np.diag(result.covariance.to_numpy()), np.diag(ml_cov), atol=1e-14
        )

    def test_shrinkage_in_unit_interval(self) -> None:
        for seed in range(5):
            result = constant_correlation_covariance(_random_panel(seed, 30, 6))
            assert result.shrinkage is not None
            assert 0.0 <= result.shrinkage <= 1.0

    def test_two_assets_short_circuits_to_sample(self) -> None:
        # With N = 2 the constant-correlation target equals the sample matrix
        # exactly (r_bar is the single off-diagonal correlation), so
        # gamma_hat = 0 and the estimator returns the ML sample covariance.
        panel = _random_panel(4, 30, 2)
        result = constant_correlation_covariance(panel)
        assert result.shrinkage == 0.0
        np.testing.assert_allclose(
            result.covariance.to_numpy(),
            _ml_sample_cov(panel.to_numpy()),
            atol=1e-14,
        )

    def test_zero_variance_asset_raises(self) -> None:
        panel = _random_panel(5, 20, 3)
        panel["A01"] = 0.0042  # constant column -> zero variance
        with pytest.raises(ValueError, match="A01"):
            constant_correlation_covariance(panel)

    def test_parameter_recovery_on_constant_correlation_truth(self) -> None:
        # True universe IS constant-correlation: the target is unbiased for
        # the truth, so shrinkage must beat the raw sample estimator.
        n_assets = 10
        rho = 0.5
        vols = np.linspace(0.01, 0.04, n_assets)
        corr = np.full((n_assets, n_assets), rho)
        np.fill_diagonal(corr, 1.0)
        sigma = corr * np.outer(vols, vols)
        cc_errors = []
        sample_errors = []
        for seed in range(10):
            rng = np.random.default_rng(200 + seed)
            panel = _mvn_panel(rng, sigma, 40)
            cc_errors.append(
                _frob_error(constant_correlation_covariance(panel).covariance, sigma)
            )
            sample_errors.append(
                _frob_error(sample_covariance(panel, ddof=0).covariance, sigma)
            )
        assert float(np.mean(cc_errors)) < float(np.mean(sample_errors))


# ---------------------------------------------------------------------------
# factor_model_covariance
# ---------------------------------------------------------------------------


class TestFactorModel:
    def test_psd_and_diagonal_preservation(self) -> None:
        panel = _random_panel(6, 60, 8)
        result = factor_model_covariance(panel, n_factors=3)
        cov = result.covariance.to_numpy()
        assert float(np.linalg.eigvalsh(cov)[0]) >= -1e-12
        # diag(Sigma_k) + residual = diag(S) exactly when no clamping occurs.
        sample = sample_covariance(panel).covariance.to_numpy()
        np.testing.assert_allclose(np.diag(cov), np.diag(sample), atol=1e-14)
        assert result.method == "factor_model"
        assert result.n_factors == 3
        assert result.shrinkage is None

    def test_full_rank_degenerates_to_sample(self) -> None:
        panel = _random_panel(7, 50, 5)
        result = factor_model_covariance(panel, n_factors=5)
        sample = sample_covariance(panel).covariance.to_numpy()
        np.testing.assert_allclose(result.covariance.to_numpy(), sample, atol=1e-12)

    @pytest.mark.parametrize("seed,n_obs,n_assets,k", [(8, 80, 10, 2), (9, 60, 6, 3)])
    def test_matches_eigh_reference(
        self, seed: int, n_obs: int, n_assets: int, k: int
    ) -> None:
        # Independent transcription of Fan-Fan-Lv: top-k eigenpairs of the
        # ddof=1 sample covariance plus the clamped residual diagonal.
        panel = _random_panel(seed, n_obs, n_assets)
        arr = panel.to_numpy()
        x = arr - arr.mean(axis=0)
        s = (x.T @ x) / float(n_obs - 1)
        eigenvalues, eigenvectors = np.linalg.eigh(s)
        order = np.argsort(eigenvalues)[::-1][:k]
        v = eigenvectors[:, order]
        systematic = v @ np.diag(eigenvalues[order]) @ v.T
        residual = np.maximum(np.diag(s) - np.diag(systematic), 0.0)
        reference = systematic + np.diag(residual)

        result = factor_model_covariance(panel, n_factors=k)
        np.testing.assert_allclose(
            result.covariance.to_numpy(), reference, atol=1e-12
        )

    def test_parameter_recovery_beats_sample_in_precision(self) -> None:
        # True universe IS a k-factor model: B B' + D with k = 3.  The metric
        # is PRECISION-matrix (inverse) recovery: that is what mean-variance
        # optimisation consumes, and it is where Fan-Fan-Lv (2008) prove the
        # factor estimator's gain -- the near-singular sample matrix inverts
        # into garbage at T = 30, N = 20, while the low-rank-plus-diagonal
        # estimate stays well-conditioned.  (On covariance Frobenius error
        # the two are near-par; on precision error the gap is decisive.)
        n_assets, k, n_obs = 20, 3, 30
        fm_errors = []
        sample_errors = []
        for seed in range(10):
            rng = np.random.default_rng(300 + seed)
            loadings = rng.standard_normal((n_assets, k)) * 0.01
            idio = np.diag(rng.uniform(0.0003, 0.0006, size=n_assets))
            sigma = loadings @ loadings.T + idio
            sigma = (sigma + sigma.T) / 2.0
            true_precision = np.linalg.inv(sigma)
            panel = _mvn_panel(rng, sigma, n_obs)
            fm_cov = factor_model_covariance(panel, n_factors=k).covariance
            sample_cov = sample_covariance(panel).covariance
            fm_errors.append(
                float(
                    np.sqrt(
                        (
                            (np.linalg.inv(fm_cov.to_numpy()) - true_precision)
                            ** 2
                        ).sum()
                    )
                )
            )
            sample_errors.append(
                float(
                    np.sqrt(
                        (
                            (np.linalg.inv(sample_cov.to_numpy()) - true_precision)
                            ** 2
                        ).sum()
                    )
                )
            )
        assert float(np.mean(fm_errors)) < float(np.mean(sample_errors))

    @pytest.mark.parametrize("bad_k", [0, -1, 6])
    def test_invalid_n_factors_raises(self, bad_k: int) -> None:
        panel = _random_panel(9, 30, 5)
        with pytest.raises(ValueError, match="n_factors"):
            factor_model_covariance(panel, n_factors=bad_k)

    def test_fewer_observations_than_assets_raises(self) -> None:
        panel = _random_panel(10, 4, 6)
        with pytest.raises(ValueError, match="observations"):
            factor_model_covariance(panel, n_factors=2)


# ---------------------------------------------------------------------------
# nearest_psd
# ---------------------------------------------------------------------------


class TestNearestPSD:
    # A classic invalid "correlation" matrix: pairwise feasible but jointly
    # indefinite (smallest eigenvalue is negative).
    _INDEFINITE = np.array(
        [
            [1.0, 0.9, -0.9],
            [0.9, 1.0, 0.9],
            [-0.9, 0.9, 1.0],
        ]
    )

    def test_input_is_indefinite(self) -> None:
        assert float(np.linalg.eigvalsh(self._INDEFINITE)[0]) < 0.0

    def test_projects_to_psd(self) -> None:
        repaired = nearest_psd(self._INDEFINITE)
        assert float(np.linalg.eigvalsh(repaired)[0]) >= -1e-12
        np.testing.assert_allclose(repaired, repaired.T, atol=1e-14)

    def test_projection_is_idempotent(self) -> None:
        once = nearest_psd(self._INDEFINITE)
        twice = nearest_psd(once)
        np.testing.assert_allclose(once, twice, atol=1e-12)

    def test_psd_input_returned_unchanged(self) -> None:
        rng = np.random.default_rng(12)
        sigma = _random_sigma(rng, 6)
        np.testing.assert_array_equal(nearest_psd(sigma), (sigma + sigma.T) / 2.0)

    def test_epsilon_floor(self) -> None:
        repaired = nearest_psd(self._INDEFINITE, epsilon=1e-4)
        assert float(np.linalg.eigvalsh(repaired)[0]) >= 1e-4 - 1e-12

    def test_asymmetric_input_symmetrised(self) -> None:
        asym = np.array([[1.0, 2.0], [0.0, 1.0]])
        np.testing.assert_allclose(
            nearest_psd(asym), np.array([[1.0, 1.0], [1.0, 1.0]]), atol=1e-14
        )

    @pytest.mark.parametrize(
        "bad",
        [np.zeros(3), np.zeros((2, 3)), np.zeros((2, 2, 2))],
        ids=["1d", "rectangular", "3d"],
    )
    def test_non_square_raises(self, bad: np.ndarray) -> None:
        with pytest.raises(ValueError, match="square"):
            nearest_psd(bad)

    def test_negative_epsilon_raises(self) -> None:
        with pytest.raises(ValueError, match="epsilon"):
            nearest_psd(np.eye(2), epsilon=-1e-6)


# ---------------------------------------------------------------------------
# condition_number
# ---------------------------------------------------------------------------


class TestConditionNumber:
    def test_identity_is_one(self) -> None:
        assert condition_number(np.eye(4)) == pytest.approx(1.0)

    def test_known_diagonal(self) -> None:
        assert condition_number(np.diag([4.0, 1.0])) == pytest.approx(4.0)

    def test_singular_is_inf(self) -> None:
        assert condition_number(np.diag([1.0, 0.0])) == float("inf")

    def test_indefinite_is_inf(self) -> None:
        assert condition_number(np.diag([1.0, -1.0])) == float("inf")

    def test_non_square_raises(self) -> None:
        with pytest.raises(ValueError, match="square"):
            condition_number(np.zeros((2, 3)))


# ---------------------------------------------------------------------------
# CovarianceResult DTO
# ---------------------------------------------------------------------------


class TestCovarianceResult:
    def test_frozen(self) -> None:
        result = sample_covariance(_random_panel(13, 20, 3))
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.method = "other"  # type: ignore[misc]

    def test_equality_ignores_matrix(self) -> None:
        a = CovarianceResult(
            covariance=pd.DataFrame(np.eye(2)), method="sample"
        )
        b = CovarianceResult(
            covariance=pd.DataFrame(np.zeros((2, 2))), method="sample"
        )
        assert a == b
        c = CovarianceResult(
            covariance=pd.DataFrame(np.eye(2)), method="oas", shrinkage=0.5
        )
        assert a != c


# ---------------------------------------------------------------------------
# Phase 6 DOD: 20-asset universe in < 1 s
# ---------------------------------------------------------------------------


class TestPerformance:
    def test_all_estimators_under_one_second_for_20_assets(self) -> None:
        panel = _random_panel(99, 252, 20)
        start = time.perf_counter()
        sample_covariance(panel)
        ledoit_wolf_covariance(panel)
        oas_covariance(panel)
        constant_correlation_covariance(panel)
        factor_model_covariance(panel, n_factors=5)
        elapsed = time.perf_counter() - start
        assert elapsed < 1.0, f"covariance stack took {elapsed:.3f}s for 20 assets"
