"""Tests for core_trading.signals.regimes.hmm (Phase 5.A.1).

Simulation strategy
-------------------
All tests that require a known ground truth generate data from a
parametrically defined HMM with well-separated regime means:
    bear state:  log-return mean = -0.005, vol = 0.0020
    bull state:  log-return mean = +0.005, vol = 0.0010
    sideways state (3/4-state): mean = 0.001, vol = 0.0015
    crisis state (4-state):     mean = -0.010, vol = 0.0040

With these separations and N >= 500 observations the Baum-Welch EM
algorithm consistently recovers the true state ordering, and the Viterbi
accuracy against the known true path exceeds 0.90.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core_trading.signals.regimes.hmm import (  # noqa: I001
    LABEL_BEAR,
    LABEL_BULL,
    RegimeConfig,
    RegimeDetector,
    RegimeResult,
    _build_feature_matrix,
)

# ---------------------------------------------------------------------------
# Simulation helpers
# ---------------------------------------------------------------------------


def _simulate_hmm(
    n_obs: int,
    means: list[float],
    stds: list[float],
    trans: list[list[float]],
    seed: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    """Simulate observations and hidden states from a Gaussian HMM.

    Parameters
    ----------
    n_obs:
        Number of observations to generate.
    means:
        Per-state mean log-return (one float per state).
    stds:
        Per-state standard deviation (one float per state).
    trans:
        Row-stochastic transition matrix as a list-of-lists.
    seed:
        Numpy seed for reproducibility.

    Returns
    -------
    obs:
        1-D float array of simulated log-returns, length ``n_obs``.
    states:
        1-D int array of true hidden states, length ``n_obs``.
    """
    rng = np.random.default_rng(seed)
    n_states = len(means)
    trans_arr = np.array(trans, dtype=float)
    states = np.empty(n_obs, dtype=int)
    obs = np.empty(n_obs, dtype=float)

    # Start in state 0
    state = 0
    for i in range(n_obs):
        states[i] = state
        obs[i] = rng.normal(means[state], stds[state])
        state = int(rng.choice(n_states, p=trans_arr[state]))

    return obs, states


def _log_returns_to_prices(log_returns: np.ndarray, seed: int = 1) -> pd.Series:
    """Convert an array of log-returns to a synthetic price Series.

    Starts at price 100 and uses DatetimeIndex for realism.
    """
    rng = np.random.default_rng(seed)
    _ = rng  # not used -- just maintains consistent API for future expansion
    prices = np.empty(len(log_returns) + 1)
    prices[0] = 100.0
    for i, r in enumerate(log_returns):
        prices[i + 1] = prices[i] * np.exp(r)
    idx = pd.date_range("2010-01-01", periods=len(prices), freq="B")
    return pd.Series(prices, index=idx, name="price")


# Standard 2-state simulation used by multiple tests.
_BEAR_MEAN = -0.005
_BULL_MEAN = +0.005
_N_OBS = 800
_TRANS_2 = [[0.95, 0.05], [0.05, 0.95]]


def _make_2state_prices(seed: int = 42) -> tuple[pd.Series, np.ndarray]:
    """Return (prices, true_states) for the canonical 2-state simulation."""
    obs, states = _simulate_hmm(
        n_obs=_N_OBS,
        means=[_BEAR_MEAN, _BULL_MEAN],
        stds=[0.0020, 0.0010],
        trans=_TRANS_2,
        seed=seed,
    )
    prices = _log_returns_to_prices(obs, seed=seed)
    return prices, states


# ---------------------------------------------------------------------------
# Unit tests for _build_feature_matrix
# ---------------------------------------------------------------------------


class TestBuildFeatureMatrix:
    """Unit tests for the internal feature construction helper."""

    def test_output_shape(self) -> None:
        """Output rows equal n_obs - vol_window + 1."""
        n = 100
        vol_window = 21
        ret = np.random.default_rng(0).standard_normal(n)
        features, valid = _build_feature_matrix(ret, vol_window)
        expected_rows = n - vol_window + 1
        assert features.shape == (expected_rows, 2)
        assert valid.sum() == expected_rows

    def test_first_column_is_returns(self) -> None:
        """Column 0 must equal the corresponding log-return values."""
        ret = np.arange(50, dtype=float)
        features, valid = _build_feature_matrix(ret, vol_window=5)
        np.testing.assert_array_equal(features[:, 0], ret[valid])

    def test_vol_is_positive(self) -> None:
        """Realised volatility column must be strictly positive."""
        rng = np.random.default_rng(7)
        ret = rng.standard_normal(200)
        features, _ = _build_feature_matrix(ret, vol_window=21)
        assert np.all(features[:, 1] > 0)

    def test_no_lookahead(self) -> None:
        """Changing a future return must not affect earlier vol estimates."""
        rng = np.random.default_rng(9)
        ret = rng.standard_normal(50)
        features_orig, _ = _build_feature_matrix(ret.copy(), vol_window=10)

        ret_modified = ret.copy()
        ret_modified[-1] = 999.0  # perturb the last observation
        features_mod, _ = _build_feature_matrix(ret_modified, vol_window=10)

        # Only the last vol entry should differ
        np.testing.assert_array_equal(
            features_orig[:-1, 1], features_mod[:-1, 1]
        )
        assert features_orig[-1, 1] != features_mod[-1, 1]


# ---------------------------------------------------------------------------
# RegimeConfig validation
# ---------------------------------------------------------------------------


class TestRegimeConfig:
    """RegimeConfig validation tests."""

    def test_valid_defaults(self) -> None:
        cfg = RegimeConfig()
        assert cfg.n_states == 2
        assert cfg.covariance_type == "full"
        assert cfg.vol_window == 21

    def test_invalid_n_states(self) -> None:
        with pytest.raises(ValueError, match="n_states"):
            RegimeConfig(n_states=5)

    def test_invalid_n_states_one(self) -> None:
        with pytest.raises(ValueError, match="n_states"):
            RegimeConfig(n_states=1)

    def test_invalid_vol_window(self) -> None:
        with pytest.raises(ValueError, match="vol_window"):
            RegimeConfig(vol_window=1)

    def test_invalid_n_iter(self) -> None:
        with pytest.raises(ValueError, match="n_iter"):
            RegimeConfig(n_iter=0)

    def test_invalid_covariance_type(self) -> None:
        with pytest.raises(ValueError, match="covariance_type"):
            RegimeConfig(covariance_type="bad")

    def test_valid_3_states(self) -> None:
        cfg = RegimeConfig(n_states=3)
        assert cfg.n_states == 3

    def test_valid_4_states(self) -> None:
        cfg = RegimeConfig(n_states=4)
        assert cfg.n_states == 4


# ---------------------------------------------------------------------------
# RegimeDetector -- basic API
# ---------------------------------------------------------------------------


class TestRegimeDetectorAPI:
    """Tests that the public API surface behaves correctly."""

    def test_is_fitted_false_before_fit(self) -> None:
        det = RegimeDetector()
        assert not det.is_fitted

    def test_is_fitted_true_after_fit(self) -> None:
        prices, _ = _make_2state_prices()
        det = RegimeDetector()
        det.fit(prices)
        assert det.is_fitted

    def test_predict_before_fit_raises(self) -> None:
        det = RegimeDetector()
        prices, _ = _make_2state_prices()
        with pytest.raises(RuntimeError, match="fit"):
            det.predict(prices)

    def test_config_property(self) -> None:
        cfg = RegimeConfig(n_states=3, random_state=7)
        det = RegimeDetector(cfg)
        assert det.config is cfg

    def test_default_config(self) -> None:
        det = RegimeDetector()
        assert det.config.n_states == 2

    def test_too_few_observations_raises(self) -> None:
        """A very short series must raise ValueError."""
        prices = pd.Series([100.0, 101.0, 102.0])
        det = RegimeDetector(RegimeConfig(n_states=2, vol_window=21))
        with pytest.raises(ValueError):
            det.fit(prices)

    def test_fit_returns_self(self) -> None:
        prices, _ = _make_2state_prices()
        det = RegimeDetector()
        result = det.fit(prices)
        assert result is det


# ---------------------------------------------------------------------------
# RegimeResult shape / invariants
# ---------------------------------------------------------------------------


class TestRegimeResultShape:
    """Test that RegimeResult fields have the correct shapes and invariants."""

    def _result(self, n_states: int = 2) -> tuple[RegimeResult, int]:
        prices, _ = _make_2state_prices()
        cfg = RegimeConfig(n_states=n_states, random_state=0)
        det = RegimeDetector(cfg)
        result = det.fit_predict(prices)
        n_obs = result.posterior_probs.shape[0]
        return result, n_obs

    def test_posterior_shape_2state(self) -> None:
        result, n_obs = self._result(2)
        assert result.posterior_probs.shape == (n_obs, 2)

    def test_posterior_shape_3state(self) -> None:
        prices, _ = _make_2state_prices()
        cfg = RegimeConfig(n_states=3, random_state=0)
        det = RegimeDetector(cfg)
        result = det.fit_predict(prices)
        n_obs = result.posterior_probs.shape[0]
        assert result.posterior_probs.shape == (n_obs, 3)

    def test_posterior_shape_4state(self) -> None:
        prices, _ = _make_2state_prices()
        cfg = RegimeConfig(n_states=4, random_state=0)
        det = RegimeDetector(cfg)
        result = det.fit_predict(prices)
        n_obs = result.posterior_probs.shape[0]
        assert result.posterior_probs.shape == (n_obs, 4)

    def test_posterior_rows_sum_to_one(self) -> None:
        """Every row of posterior_probs must sum to 1 within floating tolerance."""
        result, _ = self._result(2)
        row_sums = result.posterior_probs.sum(axis=1)
        np.testing.assert_allclose(row_sums.to_numpy(), 1.0, atol=1e-6)

    def test_posterior_rows_sum_to_one_3state(self) -> None:
        prices, _ = _make_2state_prices()
        cfg = RegimeConfig(n_states=3, random_state=0)
        det = RegimeDetector(cfg)
        result = det.fit_predict(prices)
        row_sums = result.posterior_probs.sum(axis=1)
        np.testing.assert_allclose(row_sums.to_numpy(), 1.0, atol=1e-6)

    def test_posterior_rows_sum_to_one_4state(self) -> None:
        prices, _ = _make_2state_prices()
        cfg = RegimeConfig(n_states=4, random_state=0)
        det = RegimeDetector(cfg)
        result = det.fit_predict(prices)
        row_sums = result.posterior_probs.sum(axis=1)
        np.testing.assert_allclose(row_sums.to_numpy(), 1.0, atol=1e-6)

    def test_viterbi_path_shape(self) -> None:
        result, n_obs = self._result(2)
        assert result.viterbi_path.shape == (n_obs,)

    def test_viterbi_values_in_range(self) -> None:
        result, _ = self._result(2)
        assert result.viterbi_path.min() >= 0
        assert result.viterbi_path.max() < 2

    def test_viterbi_values_in_range_3state(self) -> None:
        prices, _ = _make_2state_prices()
        cfg = RegimeConfig(n_states=3, random_state=0)
        det = RegimeDetector(cfg)
        result = det.fit_predict(prices)
        assert result.viterbi_path.min() >= 0
        assert result.viterbi_path.max() < 3

    def test_state_means_shape(self) -> None:
        result, _ = self._result(2)
        assert result.state_means.shape == (2, 2)

    def test_state_covariances_shape(self) -> None:
        result, _ = self._result(2)
        assert result.state_covariances.shape == (2, 2, 2)

    def test_n_states_field(self) -> None:
        result, _ = self._result(3)
        assert result.n_states == 3

    def test_log_likelihood_finite(self) -> None:
        result, _ = self._result(2)
        assert np.isfinite(result.log_likelihood)

    def test_posterior_index_matches_viterbi_index(self) -> None:
        result, _ = self._result(2)
        pd.testing.assert_index_equal(
            result.posterior_probs.index, result.viterbi_path.index
        )


# ---------------------------------------------------------------------------
# Stable labelling -- state 0 is most bearish
# ---------------------------------------------------------------------------


class TestStableLabelling:
    """State ordering must be deterministic: ascending mean return."""

    def test_bear_state_has_lowest_mean_return(self) -> None:
        """state_means[0, 0] (return feature) <= state_means[1, 0]."""
        prices, _ = _make_2state_prices()
        cfg = RegimeConfig(n_states=2, random_state=0)
        det = RegimeDetector(cfg)
        result = det.fit_predict(prices)
        assert result.state_means[0, 0] <= result.state_means[1, 0]

    def test_ascending_means_3state(self) -> None:
        """Mean returns must be non-decreasing across states for 3-state."""
        prices, _ = _make_2state_prices()
        cfg = RegimeConfig(n_states=3, random_state=0)
        det = RegimeDetector(cfg)
        result = det.fit_predict(prices)
        means = result.state_means[:, 0]
        for i in range(len(means) - 1):
            assert means[i] <= means[i + 1], (
                f"State {i} mean {means[i]} > state {i+1} mean {means[i+1]}"
            )

    def test_ascending_means_4state(self) -> None:
        """Mean returns must be non-decreasing across states for 4-state."""
        prices, _ = _make_2state_prices()
        cfg = RegimeConfig(n_states=4, random_state=0)
        det = RegimeDetector(cfg)
        result = det.fit_predict(prices)
        means = result.state_means[:, 0]
        for i in range(len(means) - 1):
            assert means[i] <= means[i + 1], (
                f"State {i} mean {means[i]} > state {i+1} mean {means[i+1]}"
            )

    def test_label_constants(self) -> None:
        """LABEL_BEAR must be 0 and LABEL_BULL must be 1."""
        assert LABEL_BEAR == 0
        assert LABEL_BULL == 1


# ---------------------------------------------------------------------------
# Recovery accuracy test
# ---------------------------------------------------------------------------


class TestRecoveryAccuracy:
    """Fit on a known 2-state HMM and verify regime classification accuracy.

    The simulation uses well-separated means so the HMM should recover the
    true hidden path with accuracy > 0.90.

    State ordering: true state 0 = bear (negative mean), true state 1 = bull
    (positive mean).  After stable relabelling by ascending mean return, the
    recovered state 0 should correspond to the true bear regime.
    """

    def _run(self, seed: int = 42) -> tuple[np.ndarray, np.ndarray]:
        """Return (true_states_trimmed, recovered_viterbi)."""
        prices, true_states = _make_2state_prices(seed=seed)
        cfg = RegimeConfig(n_states=2, n_iter=500, tol=1e-6, random_state=seed)
        det = RegimeDetector(cfg)
        result = det.fit_predict(prices)

        recovered = result.viterbi_path.to_numpy()

        # true_states has length _N_OBS.
        # log_ret = diff of prices => _N_OBS rows.
        # _build_feature_matrix with vol_window=21 drops first 20 rows.
        # So recovered aligns to true_states[20:] (indices 20 .. N_OBS-1).
        vol_window = cfg.vol_window
        trimmed_true = true_states[vol_window - 1 :]
        assert len(trimmed_true) == len(recovered), (
            f"Length mismatch: true={len(trimmed_true)}, recovered={len(recovered)}"
        )
        return trimmed_true, recovered

    def _accuracy(self, true: np.ndarray, pred: np.ndarray) -> float:
        """Fraction of correctly classified observations (handling label swap)."""
        acc_direct = float((true == pred).mean())
        acc_flipped = float((true == (1 - pred)).mean())
        return max(acc_direct, acc_flipped)

    def test_recovery_accuracy_above_threshold(self) -> None:
        """Regime classification accuracy must exceed 0.90."""
        true_states, recovered = self._run(seed=42)
        acc = self._accuracy(true_states, recovered)
        assert acc > 0.90, f"Recovery accuracy {acc:.3f} is below 0.90"

    def test_recovered_mean_ordering_matches_simulation(self) -> None:
        """The fitted bear-state mean return must be negative (< 0)."""
        prices, _ = _make_2state_prices(seed=42)
        cfg = RegimeConfig(n_states=2, n_iter=500, tol=1e-6, random_state=42)
        det = RegimeDetector(cfg)
        result = det.fit_predict(prices)
        # After stable relabelling, state 0 must have a negative mean return
        assert result.state_means[0, 0] < 0.0, (
            f"Bear state mean {result.state_means[0, 0]} is not negative"
        )
        # And state 1 must have a positive mean return
        assert result.state_means[1, 0] > 0.0, (
            f"Bull state mean {result.state_means[1, 0]} is not positive"
        )


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class TestDeterminism:
    """Same random_state must produce identical results across two fits."""

    def test_identical_labels_same_seed(self) -> None:
        prices, _ = _make_2state_prices(seed=42)
        cfg = RegimeConfig(n_states=2, random_state=0)

        det1 = RegimeDetector(cfg)
        result1 = det1.fit_predict(prices)

        det2 = RegimeDetector(cfg)
        result2 = det2.fit_predict(prices)

        np.testing.assert_array_equal(
            result1.viterbi_path.to_numpy(),
            result2.viterbi_path.to_numpy(),
        )
        np.testing.assert_allclose(
            result1.state_means, result2.state_means, atol=0.0
        )

    def test_different_seeds_may_differ(self) -> None:
        """Different random_states on a non-trivial problem need not be equal."""
        prices, _ = _make_2state_prices(seed=42)
        cfg0 = RegimeConfig(n_states=3, random_state=0)
        cfg1 = RegimeConfig(n_states=3, random_state=99)

        det0 = RegimeDetector(cfg0)
        result0 = det0.fit_predict(prices)

        det1 = RegimeDetector(cfg1)
        result1 = det1.fit_predict(prices)

        # We can only assert shapes are the same; label sequences may differ.
        assert result0.viterbi_path.shape == result1.viterbi_path.shape


# ---------------------------------------------------------------------------
# Walk-forward (fit then predict) mode
# ---------------------------------------------------------------------------


class TestWalkForward:
    """fit() on train, predict() on test -- look-ahead-free path."""

    def test_walk_forward_returns_result(self) -> None:
        prices, _ = _make_2state_prices(seed=42)
        split = len(prices) // 2
        train = prices.iloc[:split]
        test = prices.iloc[split:]

        cfg = RegimeConfig(n_states=2, random_state=0)
        det = RegimeDetector(cfg)
        det.fit(train)
        result = det.predict(test)

        assert isinstance(result, RegimeResult)
        assert result.posterior_probs.shape[1] == 2

    def test_walk_forward_posteriors_sum_to_one(self) -> None:
        prices, _ = _make_2state_prices(seed=42)
        split = len(prices) // 2
        train = prices.iloc[:split]
        test = prices.iloc[split:]

        cfg = RegimeConfig(n_states=2, random_state=0)
        det = RegimeDetector(cfg)
        det.fit(train)
        result = det.predict(test)

        row_sums = result.posterior_probs.sum(axis=1)
        np.testing.assert_allclose(row_sums.to_numpy(), 1.0, atol=1e-6)

    def test_fit_preserves_state_for_reuse(self) -> None:
        """Calling predict() twice on the same fitted detector gives same result."""
        prices, _ = _make_2state_prices(seed=42)
        split = len(prices) // 2
        train = prices.iloc[:split]
        test = prices.iloc[split:]

        cfg = RegimeConfig(n_states=2, random_state=0)
        det = RegimeDetector(cfg)
        det.fit(train)

        result1 = det.predict(test)
        result2 = det.predict(test)

        np.testing.assert_array_equal(
            result1.viterbi_path.to_numpy(),
            result2.viterbi_path.to_numpy(),
        )


# ---------------------------------------------------------------------------
# Alternative covariance types
# ---------------------------------------------------------------------------


class TestCovarianceTypes:
    """Verify that all four covariance types run and produce valid outputs."""

    def _fit_with_cov(self, cov_type: str) -> RegimeResult:
        prices, _ = _make_2state_prices(seed=42)
        cfg = RegimeConfig(n_states=2, covariance_type=cov_type, random_state=42)
        det = RegimeDetector(cfg)
        return det.fit_predict(prices)

    def test_tied_covariance(self) -> None:
        result = self._fit_with_cov("tied")
        row_sums = result.posterior_probs.sum(axis=1)
        np.testing.assert_allclose(row_sums.to_numpy(), 1.0, atol=1e-6)
        # tied: all n_states covariance matrices must be identical
        np.testing.assert_allclose(
            result.state_covariances[0], result.state_covariances[1], atol=1e-12
        )

    def test_diag_covariance(self) -> None:
        result = self._fit_with_cov("diag")
        row_sums = result.posterior_probs.sum(axis=1)
        np.testing.assert_allclose(row_sums.to_numpy(), 1.0, atol=1e-6)
        assert result.state_covariances.shape == (2, 2, 2)

    def test_spherical_covariance(self) -> None:
        result = self._fit_with_cov("spherical")
        row_sums = result.posterior_probs.sum(axis=1)
        np.testing.assert_allclose(row_sums.to_numpy(), 1.0, atol=1e-6)
        assert result.state_covariances.shape == (2, 2, 2)


# ---------------------------------------------------------------------------
# Edge-case error paths
# ---------------------------------------------------------------------------


class TestErrorPaths:
    """Cover error branches in _log_returns and related helpers."""

    def test_single_observation_raises(self) -> None:
        """A series with one value cannot produce log-returns."""
        prices = pd.Series([100.0])
        det = RegimeDetector()
        with pytest.raises(ValueError, match="at least 2"):
            det.fit(prices)
