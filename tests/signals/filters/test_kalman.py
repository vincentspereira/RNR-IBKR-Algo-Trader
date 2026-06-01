"""Tests for core_trading.signals.filters.kalman (Phase 5.A.2).

Covers:
* KalmanResult -- frozen dataclass contract.
* KalmanFilter -- construction and shape validation.
* KalmanFilter.predict -- single-step predict correctness.
* KalmanFilter.update -- innovation / posterior correctness.
* KalmanFilter.filter -- filterpy agreement (1-D and 2-D systems).
* KalmanFilter.filter -- state recovery on local-level model.
* KalmanFilter.filter -- missing-observation (NaN) handling.
* KalmanFilter.filter -- log-likelihood finiteness.
* KalmanFilter.rts_smooth -- smoothed variance <= filtered variance.
* KalmanFilter.rts_smooth -- correctness on local-level model.
* time_varying_beta -- recovers a known slow-drifting slope.
* time_varying_beta -- output shape and index alignment.
* ValueError guards -- shape mismatches, bad delta, bad obs_var, too few obs.
* TestPublicAPI -- package re-exports.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core_trading.signals.filters.kalman import (
    KalmanFilter,
    KalmanResult,
    time_varying_beta,
)

# ---------------------------------------------------------------------------
# Shared constants and helpers
# ---------------------------------------------------------------------------

SEED = 20240601
N_LONG = 500  # length for state-recovery tests


def _local_level_kf(
    process_var: float = 0.1,
    obs_var: float = 1.0,
    init_cov: float = 10.0,
) -> KalmanFilter:
    """Return a 1-D local-level (random-walk + noise) KalmanFilter."""
    return KalmanFilter(
        transition_matrix=np.eye(1),
        observation_matrix=np.eye(1),
        process_covariance=np.array([[process_var]]),
        observation_covariance=np.array([[obs_var]]),
        initial_state_mean=np.array([0.0]),
        initial_state_covariance=np.array([[init_cov]]),
    )


def _simulate_local_level(
    n: int,
    process_std: float = 0.3,
    obs_std: float = 1.0,
    seed: int = SEED,
) -> tuple[np.ndarray, np.ndarray]:
    """Simulate a local-level model.

    Returns (latent_state, noisy_observations) each of shape (n,).
    """
    rng = np.random.default_rng(seed)
    latent = np.empty(n)
    latent[0] = 0.0
    for t in range(1, n):
        latent[t] = latent[t - 1] + rng.normal(0.0, process_std)
    obs = latent + rng.normal(0.0, obs_std, size=n)
    return latent, obs


# ---------------------------------------------------------------------------
# KalmanResult contract
# ---------------------------------------------------------------------------


class TestKalmanResult:
    """KalmanResult frozen dataclass contract."""

    def test_is_frozen(self) -> None:
        T, n = 10, 2
        r = KalmanResult(
            filtered_state_means=np.zeros((T, n)),
            filtered_state_covariances=np.zeros((T, n, n)),
            predicted_state_means=np.zeros((T, n)),
            predicted_state_covariances=np.zeros((T, n, n)),
            log_likelihood=-50.0,
        )
        with pytest.raises((AttributeError, TypeError)):
            r.log_likelihood = 0.0  # type: ignore[misc]

    def test_field_shapes(self) -> None:
        T, n = 5, 3
        r = KalmanResult(
            filtered_state_means=np.ones((T, n)),
            filtered_state_covariances=np.zeros((T, n, n)),
            predicted_state_means=np.ones((T, n)),
            predicted_state_covariances=np.zeros((T, n, n)),
            log_likelihood=-10.0,
        )
        assert r.filtered_state_means.shape == (T, n)
        assert r.filtered_state_covariances.shape == (T, n, n)
        assert isinstance(r.log_likelihood, float)


# ---------------------------------------------------------------------------
# KalmanFilter construction validation
# ---------------------------------------------------------------------------


class TestKalmanFilterConstruction:
    """KalmanFilter raises ValueError on shape mismatches."""

    def test_bad_transition_matrix(self) -> None:
        # F must be square; pass a non-square (2x3) matrix
        with pytest.raises(ValueError, match="transition_matrix"):
            KalmanFilter(
                transition_matrix=np.ones((2, 3)),     # non-square: n=2 but shape is (2,3)
                observation_matrix=np.ones((1, 2)),    # m=1, n=2
                process_covariance=np.eye(2),
                observation_covariance=np.eye(1),
                initial_state_mean=np.zeros(2),
                initial_state_covariance=np.eye(2),
            )

    def test_bad_observation_matrix(self) -> None:
        with pytest.raises(ValueError, match="observation_matrix"):
            KalmanFilter(
                transition_matrix=np.eye(2),
                observation_matrix=np.ones((1, 3)),   # wrong n
                process_covariance=np.eye(2),
                observation_covariance=np.eye(1),
                initial_state_mean=np.zeros(2),
                initial_state_covariance=np.eye(2),
            )

    def test_bad_process_covariance(self) -> None:
        with pytest.raises(ValueError, match="process_covariance"):
            KalmanFilter(
                transition_matrix=np.eye(2),
                observation_matrix=np.ones((1, 2)),
                process_covariance=np.eye(3),          # wrong size
                observation_covariance=np.eye(1),
                initial_state_mean=np.zeros(2),
                initial_state_covariance=np.eye(2),
            )

    def test_bad_obs_covariance(self) -> None:
        with pytest.raises(ValueError, match="observation_covariance"):
            KalmanFilter(
                transition_matrix=np.eye(2),
                observation_matrix=np.ones((1, 2)),
                process_covariance=np.eye(2),
                observation_covariance=np.eye(2),      # wrong m
                initial_state_mean=np.zeros(2),
                initial_state_covariance=np.eye(2),
            )

    def test_bad_initial_state_mean(self) -> None:
        with pytest.raises(ValueError, match="initial_state_mean"):
            KalmanFilter(
                transition_matrix=np.eye(2),
                observation_matrix=np.ones((1, 2)),
                process_covariance=np.eye(2),
                observation_covariance=np.eye(1),
                initial_state_mean=np.zeros(3),        # wrong length
                initial_state_covariance=np.eye(2),
            )

    def test_bad_initial_state_cov(self) -> None:
        with pytest.raises(ValueError, match="initial_state_covariance"):
            KalmanFilter(
                transition_matrix=np.eye(2),
                observation_matrix=np.ones((1, 2)),
                process_covariance=np.eye(2),
                observation_covariance=np.eye(1),
                initial_state_mean=np.zeros(2),
                initial_state_covariance=np.eye(3),    # wrong size
            )

    def test_properties(self) -> None:
        kf = _local_level_kf()
        assert kf.n_states == 1
        assert kf.n_obs == 1


# ---------------------------------------------------------------------------
# Single-step predict and update
# ---------------------------------------------------------------------------


class TestPredictUpdate:
    """KalmanFilter.predict and .update single-step correctness."""

    def test_predict_local_level(self) -> None:
        """For F=I, predict should return the same mean."""
        kf = _local_level_kf(process_var=0.5)
        x = np.array([3.0])
        P = np.array([[2.0]])
        x_pred, P_pred = kf.predict(x, P)
        np.testing.assert_allclose(x_pred, np.array([3.0]))
        # P_pred = P + Q = 2.0 + 0.5 = 2.5
        np.testing.assert_allclose(P_pred, np.array([[2.5]]))

    def test_update_perfect_obs(self) -> None:
        """With R -> 0 the posterior should collapse to the observation."""
        kf = KalmanFilter(
            transition_matrix=np.eye(1),
            observation_matrix=np.eye(1),
            process_covariance=np.eye(1) * 1e-6,
            observation_covariance=np.eye(1) * 1e-10,
            initial_state_mean=np.array([0.0]),
            initial_state_covariance=np.eye(1),
        )
        x_pred = np.array([0.0])
        P_pred = np.array([[1.0]])
        z = np.array([5.0])
        x_post, P_post, ll = kf.update(x_pred, P_pred, z)
        np.testing.assert_allclose(x_post, np.array([5.0]), atol=1e-4)
        assert np.all(P_post >= 0)
        assert np.isfinite(ll)

    def test_update_log_likelihood_finite(self) -> None:
        kf = _local_level_kf()
        x_pred = np.array([0.0])
        P_pred = np.array([[1.0]])
        z = np.array([1.0])
        _, _, ll = kf.update(x_pred, P_pred, z)
        assert np.isfinite(ll)


# ---------------------------------------------------------------------------
# Filterpy agreement test
# ---------------------------------------------------------------------------


class TestFilterpyAgreement:
    """Validate our filter against filterpy's reference implementation.

    Uses the same 1-D and 2-D linear-Gaussian systems for comparison.

    Notes
    -----
    filterpy 1.4.5 contains a bare f-string (no expression) in helpers.py
    that triggers a SyntaxWarning on import in Python 3.12.  The warning is
    benign and irrelevant to our numeric results; we suppress it via
    pytest.warns/filterwarnings at import time only.
    """

    def test_1d_local_level_agreement(self) -> None:
        """1-D local-level: our filtered means must match filterpy's to atol=1e-8."""
        from filterpy.kalman import KalmanFilter as FPKF

        T = 200
        rng = np.random.default_rng(SEED)
        obs_std = 1.0
        obs = rng.normal(0.0, obs_std, size=T)

        # Our filter
        kf = _local_level_kf(process_var=0.1, obs_var=obs_std ** 2, init_cov=1.0)
        result = kf.filter(obs)
        our_means = result.filtered_state_means.flatten()

        # filterpy reference
        fp = FPKF(dim_x=1, dim_z=1)
        fp.F = np.eye(1)
        fp.H = np.eye(1)
        fp.Q = np.array([[0.1]])
        fp.R = np.array([[obs_std ** 2]])
        fp.x = np.array([[0.0]])
        fp.P = np.eye(1) * 1.0

        fp_means = []
        for z_val in obs:
            fp.predict()
            fp.update(np.array([[z_val]]))
            fp_means.append(float(fp.x[0, 0]))

        fp_means_arr = np.array(fp_means)
        np.testing.assert_allclose(our_means, fp_means_arr, atol=1e-8)

    def test_2d_constant_velocity_agreement(self) -> None:
        """2-D constant-velocity model: our filter must match filterpy to atol=1e-8."""
        from filterpy.kalman import KalmanFilter as FPKF

        # State: [position, velocity]; observe position only
        dt = 1.0
        F = np.array([[1.0, dt], [0.0, 1.0]])
        H = np.array([[1.0, 0.0]])
        Q = np.eye(2) * 0.01
        R = np.array([[1.0]])
        x0 = np.array([0.0, 1.0])
        P0 = np.eye(2) * 1.0

        T = 100
        rng = np.random.default_rng(SEED + 1)
        # Simulate true trajectory
        x_true = np.zeros((T, 2))
        x_true[0] = x0
        for t in range(1, T):
            x_true[t] = F @ x_true[t - 1]
        obs = x_true[:, 0:1] + rng.normal(0.0, 1.0, size=(T, 1))

        kf = KalmanFilter(
            transition_matrix=F,
            observation_matrix=H,
            process_covariance=Q,
            observation_covariance=R,
            initial_state_mean=x0,
            initial_state_covariance=P0,
        )
        result = kf.filter(obs)
        our_means = result.filtered_state_means  # (T, 2)

        fp = FPKF(dim_x=2, dim_z=1)
        fp.F = F.copy()
        fp.H = H.copy()
        fp.Q = Q.copy()
        fp.R = R.copy()
        fp.x = x0.reshape(2, 1).copy()
        fp.P = P0.copy()

        fp_means = []
        for z_val in obs:
            fp.predict()
            fp.update(z_val.reshape(1, 1))
            fp_means.append(fp.x.flatten().copy())
        fp_means_arr = np.array(fp_means)  # (T, 2)

        np.testing.assert_allclose(our_means, fp_means_arr, atol=1e-8)


# ---------------------------------------------------------------------------
# State recovery
# ---------------------------------------------------------------------------


class TestStateRecovery:
    """KalmanFilter.filter tracks the latent state closely on simulated data."""

    def test_rmse_local_level(self) -> None:
        """Filtered mean should track latent state with RMSE < 2 * obs_std."""
        latent, obs = _simulate_local_level(
            N_LONG, process_std=0.3, obs_std=1.0, seed=SEED
        )
        kf = _local_level_kf(process_var=0.09, obs_var=1.0, init_cov=1.0)
        result = kf.filter(obs)
        filtered = result.filtered_state_means.flatten()
        rmse = float(np.sqrt(np.mean((filtered - latent) ** 2)))
        # Kalman-filtered RMSE must be well below obs_std
        assert rmse < 1.0, f"RMSE={rmse:.3f} too high"

    def test_filtered_better_than_raw(self) -> None:
        """Filtered RMSE should beat raw observation RMSE."""
        latent, obs = _simulate_local_level(
            N_LONG, process_std=0.3, obs_std=1.0, seed=SEED
        )
        kf = _local_level_kf(process_var=0.09, obs_var=1.0, init_cov=1.0)
        result = kf.filter(obs)
        filtered = result.filtered_state_means.flatten()
        rmse_filtered = float(np.sqrt(np.mean((filtered - latent) ** 2)))
        rmse_raw = float(np.sqrt(np.mean((obs - latent) ** 2)))
        assert rmse_filtered < rmse_raw


# ---------------------------------------------------------------------------
# Filter output contracts
# ---------------------------------------------------------------------------


class TestFilterContracts:
    """KalmanFilter.filter output shape and contract tests."""

    def test_output_shapes_1d(self) -> None:
        T = 50
        kf = _local_level_kf()
        obs = np.random.default_rng(1).normal(size=T)
        result = kf.filter(obs)
        assert result.filtered_state_means.shape == (T, 1)
        assert result.filtered_state_covariances.shape == (T, 1, 1)
        assert result.predicted_state_means.shape == (T, 1)
        assert result.predicted_state_covariances.shape == (T, 1, 1)

    def test_log_likelihood_finite(self) -> None:
        T = 100
        kf = _local_level_kf()
        obs = np.random.default_rng(2).normal(size=T)
        result = kf.filter(obs)
        assert np.isfinite(result.log_likelihood)

    def test_log_likelihood_negative(self) -> None:
        """Log-likelihood of a Gaussian model should be negative."""
        T = 200
        kf = _local_level_kf()
        rng = np.random.default_rng(3)
        obs = rng.normal(size=T)
        result = kf.filter(obs)
        assert result.log_likelihood < 0.0

    def test_missing_observations_nan(self) -> None:
        """NaN observations must not raise and must produce finite filtered means."""
        T = 100
        rng = np.random.default_rng(4)
        obs = rng.normal(size=T).astype(float)
        obs[::5] = np.nan  # every 5th is missing
        kf = _local_level_kf()
        result = kf.filter(obs)
        assert result.filtered_state_means.shape == (T, 1)
        # Non-missing steps should be finite
        non_missing = ~np.isnan(obs)
        assert np.all(np.isfinite(result.filtered_state_means[non_missing]))

    def test_wrong_obs_columns_raises(self) -> None:
        kf = _local_level_kf()  # expects m=1
        obs = np.random.default_rng(5).normal(size=(50, 2))  # m=2
        with pytest.raises(ValueError, match="columns"):
            kf.filter(obs)

    def test_1d_array_accepted(self) -> None:
        """1-D observation array should be accepted and reshaped internally."""
        kf = _local_level_kf()
        obs = np.random.default_rng(6).normal(size=30)  # shape (30,)
        result = kf.filter(obs)
        assert result.filtered_state_means.shape == (30, 1)


# ---------------------------------------------------------------------------
# RTS smoother
# ---------------------------------------------------------------------------


class TestRTSSmoother:
    """KalmanFilter.rts_smooth produces valid smoothed estimates."""

    def test_smoothed_variance_le_filtered(self) -> None:
        """Diagonal entries of smoothed covariances must be <= filtered covariances."""
        latent, obs = _simulate_local_level(N_LONG, seed=SEED)
        kf = _local_level_kf(process_var=0.09, obs_var=1.0, init_cov=1.0)
        result = kf.filter(obs)
        sm_means, sm_covs = kf.rts_smooth(result)

        filt_diag = result.filtered_state_covariances[:, 0, 0]
        sm_diag = sm_covs[:, 0, 0]
        # Smoothed variance should be <= filtered variance at every step
        # (allow small numerical tolerance)
        assert np.all(sm_diag <= filt_diag + 1e-10), (
            f"Smoother increased variance at {np.sum(sm_diag > filt_diag + 1e-10)} steps"
        )

    def test_smoothed_rmse_le_filtered(self) -> None:
        """Smoothed RMSE should be <= filtered RMSE (or at most marginally higher)."""
        latent, obs = _simulate_local_level(N_LONG, seed=SEED)
        kf = _local_level_kf(process_var=0.09, obs_var=1.0, init_cov=1.0)
        result = kf.filter(obs)
        sm_means, _ = kf.rts_smooth(result)

        filtered = result.filtered_state_means.flatten()
        smoothed = sm_means.flatten()
        rmse_filt = float(np.sqrt(np.mean((filtered - latent) ** 2)))
        rmse_sm = float(np.sqrt(np.mean((smoothed - latent) ** 2)))
        # Smoothed may equal or beat filtered (allow 5% slack for sample variance)
        assert rmse_sm <= rmse_filt * 1.05

    def test_smoothed_output_shapes(self) -> None:
        T = 80
        n = 2
        kf = KalmanFilter(
            transition_matrix=np.eye(n),
            observation_matrix=np.ones((1, n)),
            process_covariance=np.eye(n) * 0.1,
            observation_covariance=np.eye(1),
            initial_state_mean=np.zeros(n),
            initial_state_covariance=np.eye(n),
        )
        obs = np.random.default_rng(7).normal(size=(T, 1))
        result = kf.filter(obs)
        sm_means, sm_covs = kf.rts_smooth(result)
        assert sm_means.shape == (T, n)
        assert sm_covs.shape == (T, n, n)


# ---------------------------------------------------------------------------
# time_varying_beta
# ---------------------------------------------------------------------------


class TestTimeVaryingBeta:
    """time_varying_beta recovers a known slowly-drifting slope."""

    def _make_drifting_beta(
        self,
        n: int = 1000,
        beta_start: float = 1.0,
        beta_end: float = 2.0,
        obs_noise: float = 0.05,
        seed: int = SEED,
    ) -> tuple[pd.Series, pd.Series, np.ndarray]:
        """Simulate y = alpha + beta_t * x + noise with linearly drifting beta."""
        rng = np.random.default_rng(seed)
        x = rng.normal(0.0, 1.0, size=n)
        beta_t = np.linspace(beta_start, beta_end, n)
        alpha_true = 0.5
        y = alpha_true + beta_t * x + rng.normal(0.0, obs_noise, size=n)
        return pd.Series(y), pd.Series(x), beta_t

    def test_beta_ends_near_true(self) -> None:
        """Recovered beta at end of series should be near beta_end=2.0."""
        y, x, beta_t = self._make_drifting_beta(n=1000, beta_start=1.0, beta_end=2.0)
        df = time_varying_beta(y, x, delta=5e-4, obs_var=0.05 ** 2)
        beta_tail = float(df["beta"].iloc[-50:].mean())
        assert abs(beta_tail - 2.0) < 0.25, f"beta_tail={beta_tail:.3f}, expected ~2.0"

    def test_beta_starts_near_true(self) -> None:
        """Recovered beta near start (after warm-up) should be near beta_start=1.0."""
        y, x, beta_t = self._make_drifting_beta(n=1000, beta_start=1.0, beta_end=2.0)
        df = time_varying_beta(y, x, delta=5e-4, obs_var=0.05 ** 2)
        # Allow a warm-up window of ~50 steps
        beta_head = float(df["beta"].iloc[50:100].mean())
        assert abs(beta_head - 1.0) < 0.4, f"beta_head={beta_head:.3f}, expected ~1.0"

    def test_output_columns(self) -> None:
        rng = np.random.default_rng(SEED + 10)
        y = pd.Series(rng.normal(size=200))
        x = pd.Series(rng.normal(size=200))
        df = time_varying_beta(y, x)
        assert "alpha" in df.columns
        assert "beta" in df.columns

    def test_output_index_matches_y(self) -> None:
        idx = pd.date_range("2020-01-01", periods=150, freq="D")
        rng = np.random.default_rng(SEED + 11)
        y = pd.Series(rng.normal(size=150), index=idx)
        x = pd.Series(rng.normal(size=150), index=idx)
        df = time_varying_beta(y, x)
        assert list(df.index) == list(y.index)

    def test_output_length_matches_y(self) -> None:
        rng = np.random.default_rng(SEED + 12)
        y = pd.Series(rng.normal(size=100))
        x = pd.Series(rng.normal(size=100))
        df = time_varying_beta(y, x)
        assert len(df) == len(y)

    def test_nan_propagation(self) -> None:
        """Rows where y or x is NaN should produce NaN in output."""
        rng = np.random.default_rng(SEED + 13)
        y = pd.Series(rng.normal(size=100))
        x = pd.Series(rng.normal(size=100))
        y.iloc[10] = np.nan
        df = time_varying_beta(y, x)
        assert np.isnan(df["beta"].iloc[10])

    def test_raises_bad_delta_zero(self) -> None:
        with pytest.raises(ValueError, match="delta"):
            rng = np.random.default_rng(0)
            time_varying_beta(pd.Series(rng.normal(size=50)), pd.Series(rng.normal(size=50)), delta=0.0)

    def test_raises_bad_delta_one(self) -> None:
        with pytest.raises(ValueError, match="delta"):
            rng = np.random.default_rng(0)
            time_varying_beta(pd.Series(rng.normal(size=50)), pd.Series(rng.normal(size=50)), delta=1.0)

    def test_raises_bad_obs_var(self) -> None:
        with pytest.raises(ValueError, match="obs_var"):
            rng = np.random.default_rng(0)
            time_varying_beta(pd.Series(rng.normal(size=50)), pd.Series(rng.normal(size=50)), obs_var=-1.0)

    def test_raises_too_few_obs(self) -> None:
        with pytest.raises(ValueError, match="at least 2"):
            time_varying_beta(pd.Series([1.0]), pd.Series([1.0]))


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------


class TestPublicAPI:
    """Verify that the filters package re-exports the expected names."""

    def test_imports_from_package(self) -> None:
        from core_trading.signals.filters import (  # noqa: F401
            KalmanFilter,
            KalmanResult,
            time_varying_beta,
        )

    def test_all_contents_kalman(self) -> None:
        import core_trading.signals.filters as pkg

        for name in ("KalmanFilter", "KalmanResult", "time_varying_beta"):
            assert hasattr(pkg, name), f"missing from package: {name}"
