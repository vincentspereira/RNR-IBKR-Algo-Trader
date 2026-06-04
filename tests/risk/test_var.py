"""Tests for core_trading.risk.var (Phase 7, module 7.3).

Covers:
* VaRConfig: validation, alpha property, defaults.
* VaRResult / BacktestResult: frozen dataclasses, field values.
* parametric_var:
  - Mode A (single series): normal returns -> analytic 1.645*sigma at 95%.
  - Mode B (weights + cov): exact agreement with analytic formula.
  - Cornish-Fisher: reduces to normal when skew=0, excess-kurtosis=0.
  - Cornish-Fisher: adjusts non-trivially for skewed / fat-tailed data.
  - cornish_fisher=True rejected in Mode B.
  - 10-day scaling: sqrt(10) relationship vs 1-day result.
  - 99% confidence level.
  - Input validation (no NaN, shape mismatches).
* historical_var:
  - Normal returns: converges to 1.645*sigma at large N.
  - Portfolio mode: matches pre-computed weighted-series result.
  - 10-day scaling.
  - Conflict / missing input guards.
* monte_carlo_var:
  - Normal distribution: converges to 1.645*sigma at large N.
  - Student-t distribution: converges with tight tolerance at large N.
  - Portfolio mode.
  - Seedability / reproducibility.
  - Invalid distribution name rejected.
  - Conflict / missing input guards.
* kupiec_test:
  - Correctly-specified exceptions (iid at rate alpha) PASS.
  - Over-specified exceptions (rate 2*alpha) FAIL.
  - Zero exceptions edge case.
  - All-exceptions edge case.
  - LR statistic non-negative, chi-squared(1) p-value correct direction.
  - Input validation.
* christoffersen_test:
  - Clustered exceptions FAIL independence.
  - iid exceptions PASS independence.
  - CC test: iid at correct rate PASSES CC; clustered FAILS CC.
  - Orthogonality: LR_CC = LR_POF + LR_IND.
  - Fewer than 2 observations rejected.
* Sign convention: VaR is a POSITIVE loss number throughout.
* Performance: full VaR stack on 1000-obs series completes in < 2 s.
"""
from __future__ import annotations

import dataclasses
import time

import numpy as np
import pandas as pd
import pytest

from core_trading.risk.var import (
    VaRConfig,
    christoffersen_test,
    historical_var,
    kupiec_test,
    monte_carlo_var,
    parametric_var,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _returns_series(seed: int, n: int, sigma: float = 0.01) -> np.ndarray:
    """Generate i.i.d. N(0, sigma^2) returns."""
    rng = np.random.default_rng(seed)
    return rng.normal(loc=0.0, scale=sigma, size=n)


def _panel(
    seed: int,
    n_obs: int,
    n_assets: int,
    sigma: float = 0.01,
) -> pd.DataFrame:
    """Generate a NaN-free returns panel."""
    rng = np.random.default_rng(seed)
    arr = rng.normal(0.0, sigma, size=(n_obs, n_assets))
    index = pd.date_range("2024-01-01", periods=n_obs, freq="B")
    cols = [f"A{i:02d}" for i in range(n_assets)]
    return pd.DataFrame(arr, index=index, columns=cols)


def _iid_exceptions(
    seed: int,
    n: int,
    alpha: float,
) -> np.ndarray:
    """Simulate i.i.d. Bernoulli exception indicators at rate alpha."""
    rng = np.random.default_rng(seed)
    return (rng.uniform(size=n) < alpha).astype(int)


def _clustered_exceptions(n: int, alpha: float, cluster_len: int = 5) -> np.ndarray:
    """Create a pathological exception sequence with burst clusters.

    Roughly alpha*n total exceptions arranged in contiguous runs of length
    cluster_len so that the Markov transition matrix has high pi11.
    """
    exc = np.zeros(n, dtype=int)
    n_bursts = max(1, int(round(alpha * n / cluster_len)))
    rng = np.random.default_rng(77)
    starts = rng.choice(n - cluster_len, size=n_bursts, replace=False)
    for s in starts:
        exc[s : s + cluster_len] = 1
    return exc


# ---------------------------------------------------------------------------
# VaRConfig
# ---------------------------------------------------------------------------


class TestVaRConfig:
    def test_defaults(self) -> None:
        cfg = VaRConfig()
        assert cfg.confidence == 0.95
        assert cfg.horizon == 1
        assert cfg.n_simulations == 50_000
        assert cfg.rng_seed == 42
        assert cfg.significance == 0.05
        assert cfg.alpha == pytest.approx(0.05)

    def test_alpha_property(self) -> None:
        cfg = VaRConfig(confidence=0.99)
        assert cfg.alpha == pytest.approx(0.01)

    def test_confidence_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="confidence"):
            VaRConfig(confidence=0.0)
        with pytest.raises(ValueError, match="confidence"):
            VaRConfig(confidence=1.0)
        with pytest.raises(ValueError, match="confidence"):
            VaRConfig(confidence=1.5)

    def test_horizon_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="horizon"):
            VaRConfig(horizon=0)

    def test_n_simulations_too_small_raises(self) -> None:
        with pytest.raises(ValueError, match="n_simulations"):
            VaRConfig(n_simulations=500)

    def test_significance_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="significance"):
            VaRConfig(significance=0.0)
        with pytest.raises(ValueError, match="significance"):
            VaRConfig(significance=1.0)

    def test_frozen(self) -> None:
        cfg = VaRConfig()
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.confidence = 0.99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Parametric VaR
# ---------------------------------------------------------------------------


class TestParametricVaR:
    def test_analytic_normal_95_1d(self) -> None:
        """VaR = 1.6449 * sigma for N(0, sigma^2) returns at 95% confidence."""
        rng = np.random.default_rng(1)
        sigma = 0.02
        # Large sample to reduce estimation error.
        returns = rng.normal(0.0, sigma, size=100_000)
        result = parametric_var(returns, config=VaRConfig(confidence=0.95))
        expected = 1.6449 * sigma
        assert result.var == pytest.approx(expected, rel=0.01)
        assert result.method == "parametric"
        assert result.confidence == 0.95
        assert result.horizon == 1
        assert result.alpha == pytest.approx(0.05)

    def test_analytic_normal_99_1d(self) -> None:
        """VaR = 2.3263 * sigma for N(0, sigma^2) returns at 99% confidence."""
        rng = np.random.default_rng(2)
        sigma = 0.015
        returns = rng.normal(0.0, sigma, size=100_000)
        result = parametric_var(returns, config=VaRConfig(confidence=0.99))
        expected = 2.3263 * sigma
        assert result.var == pytest.approx(expected, rel=0.01)

    def test_10day_sqrt_scaling(self) -> None:
        """10-day VaR = sqrt(10) * 1-day VaR for parametric."""
        returns = _returns_series(3, 5000, sigma=0.01)
        cfg1 = VaRConfig(confidence=0.95, horizon=1)
        cfg10 = VaRConfig(confidence=0.95, horizon=10)
        var_1d = parametric_var(returns, config=cfg1).var
        var_10d = parametric_var(returns, config=cfg10).var
        assert var_10d == pytest.approx(var_1d * np.sqrt(10), rel=1e-9)

    def test_mode_b_weights_cov(self) -> None:
        """Mode B: w'Cw -> portfolio_std -> VaR = 1.6449 * portfolio_std."""
        n = 4
        rng = np.random.default_rng(10)
        q, _ = np.linalg.qr(rng.standard_normal((n, n)))
        ev = np.array([0.01, 0.005, 0.003, 0.002]) ** 2
        cov = (q * ev) @ q.T
        weights = np.array([0.4, 0.3, 0.2, 0.1])
        port_var = float(weights @ cov @ weights)
        port_std = np.sqrt(port_var)
        expected_var = float(1.6449 * port_std)

        cfg = VaRConfig(confidence=0.95)
        result = parametric_var(None, weights=weights, cov=cov, config=cfg)
        assert result.var == pytest.approx(expected_var, rel=1e-4)
        assert result.method == "parametric"

    def test_mode_b_cornish_fisher_raises(self) -> None:
        """cornish_fisher=True is not supported in Mode B."""
        cov = np.eye(2) * 0.01 ** 2
        weights = np.array([0.5, 0.5])
        with pytest.raises(ValueError, match="cornish_fisher"):
            parametric_var(None, weights=weights, cov=cov, cornish_fisher=True)

    def test_mode_b_missing_weights_raises(self) -> None:
        with pytest.raises(ValueError, match="weights and cov must be provided"):
            parametric_var(None, cov=np.eye(2))

    def test_mode_b_missing_cov_raises(self) -> None:
        with pytest.raises(ValueError, match="weights and cov must be provided"):
            parametric_var(None, weights=np.array([0.5, 0.5]))

    def test_mode_b_shape_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match="weights has"):
            parametric_var(
                None,
                weights=np.array([0.5, 0.5, 0.0]),
                cov=np.eye(2),
            )

    def test_mode_b_non_square_cov_raises(self) -> None:
        with pytest.raises(ValueError, match="square"):
            parametric_var(
                None,
                weights=np.array([0.5, 0.5]),
                cov=np.zeros((2, 3)),
            )

    def test_var_is_positive(self) -> None:
        """VaR must be a positive loss number."""
        for seed in range(5):
            arr = _returns_series(seed, 500)
            result = parametric_var(arr)
            assert result.var >= 0.0

    def test_cornish_fisher_reduces_to_normal_when_gaussian(self) -> None:
        """CF expansion = normal VaR when skew=0 and excess kurtosis=0.

        For exactly normal data the empirical skew/kurtosis are tiny but not
        zero; we verify convergence at large N rather than exact equality.
        """
        rng = np.random.default_rng(20)
        returns = rng.normal(0.0, 0.01, size=500_000)
        cfg = VaRConfig(confidence=0.95)
        var_normal = parametric_var(returns, config=cfg, cornish_fisher=False).var
        var_cf = parametric_var(returns, config=cfg, cornish_fisher=True).var
        assert var_cf == pytest.approx(var_normal, rel=0.01)
        assert var_cf > 0.0

    def test_cornish_fisher_adjusts_for_skew(self) -> None:
        """Negative skew (fat left tail) should push CF VaR above normal VaR."""
        rng = np.random.default_rng(21)
        # Chi-squared(3) minus its mean: right-skewed; negate for left-skewed.
        raw = -(rng.chisquare(3, size=50_000) - 3.0)
        raw = raw / raw.std() * 0.01  # standardise scale
        cfg = VaRConfig(confidence=0.95)
        var_normal = parametric_var(raw, config=cfg, cornish_fisher=False).var
        var_cf = parametric_var(raw, config=cfg, cornish_fisher=True).var
        # Negative skew should increase the estimated loss.
        assert var_cf > var_normal

    def test_cornish_fisher_method_label(self) -> None:
        arr = _returns_series(22, 200)
        result = parametric_var(arr, cornish_fisher=True)
        assert result.method == "parametric_cornish_fisher"

    def test_all_nan_raises(self) -> None:
        arr = np.full(50, np.nan)
        with pytest.raises(ValueError, match="finite"):
            parametric_var(arr)

    def test_mode_b_negative_portfolio_variance_raises(self) -> None:
        """Negative portfolio variance (non-PSD cov) must raise."""
        # Construct a clearly non-PSD matrix by negating a valid one.
        cov = -np.eye(2) * 0.01 ** 2
        weights = np.array([1.0, 0.0])
        with pytest.raises(ValueError, match="variance w'Cw"):
            parametric_var(None, weights=weights, cov=cov)


# ---------------------------------------------------------------------------
# Historical VaR
# ---------------------------------------------------------------------------


class TestHistoricalVaR:
    def test_converges_to_normal_95_at_large_n(self) -> None:
        """Historical VaR converges to 1.645*sigma for N(0,sigma^2) at large N."""
        rng = np.random.default_rng(30)
        sigma = 0.01
        returns = rng.normal(0.0, sigma, size=200_000)
        result = historical_var(returns, config=VaRConfig(confidence=0.95))
        assert result.var == pytest.approx(1.6449 * sigma, rel=0.02)
        assert result.method == "historical"
        assert result.confidence == 0.95

    def test_10day_sqrt_scaling(self) -> None:
        """10-day historical VaR = sqrt(10) * 1-day historical VaR."""
        arr = _returns_series(31, 5000)
        var_1d = historical_var(arr, config=VaRConfig(horizon=1)).var
        var_10d = historical_var(arr, config=VaRConfig(horizon=10)).var
        assert var_10d == pytest.approx(var_1d * np.sqrt(10), rel=1e-9)

    def test_portfolio_mode_matches_weighted_series(self) -> None:
        """Panel + weights must equal pre-weighted series result."""
        weights = np.array([0.6, 0.4])
        panel = _panel(32, 1000, 2, sigma=0.01)
        port_ret = panel.to_numpy() @ weights

        result_panel = historical_var(
            weights=weights,
            returns_panel=panel,
            config=VaRConfig(confidence=0.95),
        )
        result_series = historical_var(
            port_ret,
            config=VaRConfig(confidence=0.95),
        )
        assert result_panel.var == pytest.approx(result_series.var, rel=1e-9)

    def test_conflict_returns_and_panel_raises(self) -> None:
        arr = _returns_series(33, 100)
        panel = _panel(33, 100, 2)
        with pytest.raises(ValueError, match="not both"):
            historical_var(arr, weights=np.array([0.5, 0.5]), returns_panel=panel)

    def test_missing_weights_raises(self) -> None:
        panel = _panel(34, 100, 2)
        with pytest.raises(ValueError, match="weights and returns_panel must be provided"):
            historical_var(returns_panel=panel)

    def test_missing_panel_raises(self) -> None:
        with pytest.raises(ValueError, match="weights and returns_panel must be provided"):
            historical_var(weights=np.array([0.5, 0.5]))

    def test_panel_with_nan_raises(self) -> None:
        panel = _panel(35, 50, 2)
        panel.iloc[10, 0] = np.nan
        with pytest.raises(ValueError, match="NaN"):
            historical_var(weights=np.array([0.5, 0.5]), returns_panel=panel)

    def test_panel_too_few_rows_raises(self) -> None:
        """Single-row panel must be rejected via _validate_weights_panel."""
        arr = np.array([[0.01, -0.01]])   # 1 row, 2 assets
        panel = pd.DataFrame(arr, columns=["A00", "A01"])
        with pytest.raises(ValueError, match="at least 2 observation rows"):
            historical_var(weights=np.array([0.5, 0.5]), returns_panel=panel)

    def test_panel_weights_shape_mismatch_raises(self) -> None:
        """Weights length != number of columns must be rejected."""
        panel = _panel(36, 50, 3)
        with pytest.raises(ValueError, match="elements but returns DataFrame"):
            historical_var(weights=np.array([0.5, 0.5]), returns_panel=panel)

    def test_nan_weights_produces_nonfinite_portfolio_returns_raises(self) -> None:
        """NaN weights produce all-NaN portfolio returns; the guard catches it."""
        panel = _panel(37, 50, 2)
        weights_nan = np.array([np.nan, np.nan])
        with pytest.raises(ValueError, match="all non-finite"):
            historical_var(weights=weights_nan, returns_panel=panel)

    def test_var_is_positive(self) -> None:
        for seed in range(5):
            arr = _returns_series(seed, 500)
            assert historical_var(arr).var >= 0.0

    def test_99_confidence(self) -> None:
        rng = np.random.default_rng(36)
        returns = rng.normal(0.0, 0.01, size=200_000)
        var_95 = historical_var(returns, config=VaRConfig(confidence=0.95)).var
        var_99 = historical_var(returns, config=VaRConfig(confidence=0.99)).var
        assert var_99 > var_95


# ---------------------------------------------------------------------------
# Monte Carlo VaR
# ---------------------------------------------------------------------------


class TestMonteCarloVaR:
    # Normal distribution MC: converges to analytic VaR at very large N.
    # We use loose tolerances since MC always has finite-sample noise.
    _MC_CFG = VaRConfig(confidence=0.95, n_simulations=200_000, rng_seed=0)

    def test_normal_distribution_converges(self) -> None:
        """MC normal converges to 1.645*sigma at large N."""
        sigma = 0.01
        rng = np.random.default_rng(40)
        returns = rng.normal(0.0, sigma, size=2000)
        result = monte_carlo_var(returns, config=self._MC_CFG, distribution="normal")
        assert result.var == pytest.approx(1.6449 * sigma, rel=0.05)
        assert result.method == "monte_carlo"
        assert result.confidence == 0.95

    def test_student_t_converges(self) -> None:
        """MC student_t converges to analytic normal VaR for large-df data."""
        sigma = 0.01
        rng = np.random.default_rng(41)
        # Use normal-like data so t-fit gives large df and converges to normal.
        returns = rng.normal(0.0, sigma, size=5000)
        cfg = VaRConfig(confidence=0.95, n_simulations=500_000, rng_seed=0)
        result = monte_carlo_var(returns, config=cfg, distribution="student_t")
        # With large-df student-t the VaR is close to normal but may be
        # slightly higher; we allow 15% relative tolerance.
        assert result.var == pytest.approx(1.6449 * sigma, rel=0.15)

    def test_portfolio_mode(self) -> None:
        """Panel + weights MC result must be close to single-series result."""
        weights = np.array([1.0, 0.0])   # 100% in first asset
        panel = _panel(42, 500, 2, sigma=0.01)
        result_panel = monte_carlo_var(
            weights=weights,
            returns_panel=panel,
            config=VaRConfig(confidence=0.95, n_simulations=100_000, rng_seed=1),
            distribution="normal",
        )
        result_series = monte_carlo_var(
            panel.iloc[:, 0].to_numpy(),
            config=VaRConfig(confidence=0.95, n_simulations=100_000, rng_seed=1),
            distribution="normal",
        )
        # Same fitted params -> same result (same data, same seed).
        assert result_panel.var == pytest.approx(result_series.var, rel=1e-9)

    def test_reproducible_with_seed(self) -> None:
        """Same seed gives identical results."""
        arr = _returns_series(43, 300)
        cfg = VaRConfig(n_simulations=10_000, rng_seed=99)
        r1 = monte_carlo_var(arr, config=cfg).var
        r2 = monte_carlo_var(arr, config=cfg).var
        assert r1 == r2

    def test_different_seeds_give_different_results(self) -> None:
        """Different seeds produce different (random) results."""
        arr = _returns_series(44, 300)
        r1 = monte_carlo_var(arr, config=VaRConfig(n_simulations=10_000, rng_seed=1)).var
        r2 = monte_carlo_var(arr, config=VaRConfig(n_simulations=10_000, rng_seed=2)).var
        assert r1 != r2

    def test_10day_sqrt_scaling(self) -> None:
        arr = _returns_series(45, 1000)
        cfg_seed = 7
        var_1d = monte_carlo_var(
            arr,
            config=VaRConfig(horizon=1, n_simulations=50_000, rng_seed=cfg_seed),
        ).var
        var_10d = monte_carlo_var(
            arr,
            config=VaRConfig(horizon=10, n_simulations=50_000, rng_seed=cfg_seed),
        ).var
        assert var_10d == pytest.approx(var_1d * np.sqrt(10), rel=1e-9)

    def test_invalid_distribution_raises(self) -> None:
        arr = _returns_series(46, 100)
        with pytest.raises(ValueError, match="distribution"):
            monte_carlo_var(arr, distribution="cauchy")

    def test_conflict_returns_and_panel_raises(self) -> None:
        arr = _returns_series(47, 100)
        panel = _panel(47, 100, 2)
        with pytest.raises(ValueError, match="not both"):
            monte_carlo_var(arr, weights=np.array([0.5, 0.5]), returns_panel=panel)

    def test_missing_weights_raises(self) -> None:
        panel = _panel(48, 100, 2)
        with pytest.raises(ValueError, match="weights and returns_panel must be provided"):
            monte_carlo_var(returns_panel=panel)

    def test_missing_panel_raises(self) -> None:
        with pytest.raises(ValueError, match="weights and returns_panel must be provided"):
            monte_carlo_var(weights=np.array([0.5, 0.5]))

    def test_var_is_positive(self) -> None:
        for seed in range(5):
            arr = _returns_series(seed, 300)
            assert monte_carlo_var(arr, config=VaRConfig(n_simulations=5000, rng_seed=0)).var >= 0.0

    def test_panel_weights_shape_mismatch_raises(self) -> None:
        panel = _panel(49, 50, 3)
        with pytest.raises(ValueError, match="elements but returns DataFrame"):
            monte_carlo_var(weights=np.array([0.5, 0.5]), returns_panel=panel)

    def test_panel_too_few_rows_raises(self) -> None:
        arr = np.array([[0.01, -0.01]])
        panel = pd.DataFrame(arr, columns=["A00", "A01"])
        with pytest.raises(ValueError, match="at least 2 observation rows"):
            monte_carlo_var(weights=np.array([0.5, 0.5]), returns_panel=panel)

    def test_nan_weights_produces_nonfinite_portfolio_returns_raises(self) -> None:
        """NaN weights produce all-NaN portfolio returns; the guard catches it."""
        panel = _panel(50, 50, 2)
        weights_nan = np.array([np.nan, np.nan])
        with pytest.raises(ValueError, match="all non-finite"):
            monte_carlo_var(weights=weights_nan, returns_panel=panel)


# ---------------------------------------------------------------------------
# Kupiec test
# ---------------------------------------------------------------------------


class TestKupiecTest:
    def test_correct_rate_passes(self) -> None:
        """i.i.d. exceptions at the true alpha rate should not reject H0."""
        n = 1000
        alpha = 0.05
        # Run multiple seeds and verify the majority pass (type-I error control).
        passes = 0
        for seed in range(20):
            exc = _iid_exceptions(seed, n, alpha)
            result = kupiec_test(exc, alpha=alpha, significance=0.05)
            if result.passed:
                passes += 1
        # Under a 5% significance test, expect ~95% pass rate for true H0.
        assert passes >= 14, f"only {passes}/20 seeds passed Kupiec for true alpha"

    def test_double_rate_fails(self) -> None:
        """Exceptions at 2*alpha rate should clearly reject H0."""
        n = 2000
        alpha = 0.05
        # Force the exception count to be exactly 2*alpha*n.
        exc = np.zeros(n, dtype=int)
        exc[: int(2 * alpha * n)] = 1
        result = kupiec_test(exc, alpha=alpha, significance=0.05)
        assert not result.passed
        assert result.p_value < 0.05

    def test_zero_exceptions(self) -> None:
        """Zero exceptions with large n should fail (too few exceptions for alpha=0.05)."""
        exc = np.zeros(500, dtype=int)
        result = kupiec_test(exc, alpha=0.05, significance=0.05)
        assert result.n_exceptions == 0
        assert result.lr_statistic >= 0.0
        # 0 exceptions when expecting 25 -> strong rejection.
        assert not result.passed

    def test_all_exceptions(self) -> None:
        """100% exception rate should fail."""
        exc = np.ones(200, dtype=int)
        result = kupiec_test(exc, alpha=0.05, significance=0.05)
        assert result.n_exceptions == 200
        assert not result.passed

    def test_result_fields(self) -> None:
        exc = _iid_exceptions(5, 500, 0.05)
        result = kupiec_test(exc, alpha=0.05)
        assert result.test_name == "kupiec_pof"
        assert result.degrees_of_freedom == 1
        assert result.n_observations == 500
        assert result.expected_exceptions == pytest.approx(0.05 * 500)
        assert 0.0 <= result.p_value <= 1.0
        assert result.lr_statistic >= 0.0

    def test_lr_statistic_nonnegative(self) -> None:
        for seed in range(10):
            exc = _iid_exceptions(seed, 300, 0.05)
            result = kupiec_test(exc, alpha=0.05)
            assert result.lr_statistic >= 0.0

    def test_n_observations_override(self) -> None:
        exc = _iid_exceptions(6, 200, 0.05)
        result = kupiec_test(exc, n_observations=500, alpha=0.05)
        assert result.n_observations == 500
        assert result.expected_exceptions == pytest.approx(0.05 * 500)

    def test_invalid_alpha_raises(self) -> None:
        with pytest.raises(ValueError, match="alpha"):
            kupiec_test(np.zeros(100), alpha=0.0)
        with pytest.raises(ValueError, match="alpha"):
            kupiec_test(np.zeros(100), alpha=1.0)

    def test_invalid_significance_raises(self) -> None:
        with pytest.raises(ValueError, match="significance"):
            kupiec_test(np.zeros(100), significance=0.0)

    def test_exceptions_exceed_n_raises(self) -> None:
        exc = np.ones(100, dtype=int)
        with pytest.raises(ValueError, match="exceeds n_observations"):
            kupiec_test(exc, n_observations=50)

    def test_n_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="n_observations"):
            kupiec_test(np.zeros(10), n_observations=0)

    def test_frozen_result(self) -> None:
        result = kupiec_test(_iid_exceptions(0, 200, 0.05))
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.passed = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Christoffersen test
# ---------------------------------------------------------------------------


class TestChristoffersenTest:
    def test_iid_exceptions_pass_independence(self) -> None:
        """i.i.d. exceptions should not be rejected by the independence test."""
        n = 1000
        alpha = 0.05
        passes = 0
        for seed in range(20):
            exc = _iid_exceptions(seed, n, alpha)
            ind_result, _ = christoffersen_test(exc, alpha=alpha, significance=0.05)
            if ind_result.passed:
                passes += 1
        assert passes >= 14, f"only {passes}/20 passed IND test for iid exceptions"

    def test_clustered_exceptions_fail_independence(self) -> None:
        """Clustered exceptions (Markov bursts) must be rejected by independence test."""
        exc = _clustered_exceptions(1000, alpha=0.05, cluster_len=8)
        ind_result, _ = christoffersen_test(exc, alpha=0.05, significance=0.05)
        assert not ind_result.passed
        assert ind_result.p_value < 0.05

    def test_iid_correct_rate_passes_cc(self) -> None:
        """i.i.d. exceptions at the true rate should pass the CC test."""
        n = 1000
        alpha = 0.05
        passes = 0
        for seed in range(20):
            exc = _iid_exceptions(seed, n, alpha)
            _, cc_result = christoffersen_test(exc, alpha=alpha, significance=0.05)
            if cc_result.passed:
                passes += 1
        assert passes >= 13, f"only {passes}/20 passed CC test for iid correct-rate exceptions"

    def test_clustered_exceptions_fail_cc(self) -> None:
        """Clustered exceptions must fail the conditional-coverage test."""
        exc = _clustered_exceptions(1000, alpha=0.05, cluster_len=8)
        _, cc_result = christoffersen_test(exc, alpha=0.05, significance=0.05)
        assert not cc_result.passed

    def test_lr_cc_equals_lr_pof_plus_lr_ind(self) -> None:
        """LR_CC = LR_POF + LR_IND (Christoffersen 1998 decomposition)."""
        exc = _iid_exceptions(7, 500, 0.05)
        ind_result, cc_result = christoffersen_test(exc, alpha=0.05)
        pof_result = kupiec_test(exc, alpha=0.05)
        lr_sum = pof_result.lr_statistic + ind_result.lr_statistic
        assert cc_result.lr_statistic == pytest.approx(lr_sum, abs=1e-9)

    def test_cc_degrees_of_freedom(self) -> None:
        exc = _iid_exceptions(8, 300, 0.05)
        ind_result, cc_result = christoffersen_test(exc)
        assert ind_result.degrees_of_freedom == 1
        assert cc_result.degrees_of_freedom == 2

    def test_test_names(self) -> None:
        exc = _iid_exceptions(9, 100, 0.05)
        ind_result, cc_result = christoffersen_test(exc)
        assert ind_result.test_name == "christoffersen_independence"
        assert cc_result.test_name == "christoffersen_cc"

    def test_lr_statistics_nonnegative(self) -> None:
        for seed in range(10):
            exc = _iid_exceptions(seed, 300, 0.05)
            ind_result, cc_result = christoffersen_test(exc, alpha=0.05)
            assert ind_result.lr_statistic >= 0.0
            assert cc_result.lr_statistic >= 0.0

    def test_fewer_than_2_observations_raises(self) -> None:
        with pytest.raises(ValueError, match="at least 2 observations"):
            christoffersen_test(np.array([1]), alpha=0.05)

    def test_invalid_alpha_raises(self) -> None:
        with pytest.raises(ValueError, match="alpha"):
            christoffersen_test(np.zeros(50), alpha=1.1)

    def test_invalid_significance_raises(self) -> None:
        with pytest.raises(ValueError, match="significance"):
            christoffersen_test(np.zeros(50), significance=1.0)

    def test_miscalibrated_rate_fails_cc(self) -> None:
        """2x exception rate should fail CC (dominated by POF component)."""
        n = 2000
        alpha = 0.05
        exc = np.zeros(n, dtype=int)
        exc[: int(2 * alpha * n)] = 1
        _, cc_result = christoffersen_test(exc, alpha=alpha, significance=0.05)
        assert not cc_result.passed

    def test_all_zero_exceptions_n1_row_fallback(self) -> None:
        """All-zero exception sequence: n1_row=0, pi11 fallback to pi."""
        exc = np.zeros(100, dtype=int)
        # Should not raise; n1_row = 0 triggers the pi11 = pi fallback.
        ind_result, cc_result = christoffersen_test(exc, alpha=0.05)
        assert ind_result.n_exceptions == 0
        assert ind_result.lr_statistic >= 0.0

    def test_all_one_exceptions_n0_row_fallback(self) -> None:
        """All-one exception sequence: n0_row=0, pi01 fallback to pi."""
        exc = np.ones(100, dtype=int)
        ind_result, cc_result = christoffersen_test(exc, alpha=0.05)
        assert ind_result.n_exceptions == 100
        assert ind_result.lr_statistic >= 0.0


# ---------------------------------------------------------------------------
# Sign convention
# ---------------------------------------------------------------------------


class TestSignConvention:
    """VaR is always a positive loss number across all methods."""

    def test_positive_loss_parametric(self) -> None:
        arr = _returns_series(50, 1000)
        for conf in (0.95, 0.99):
            for h in (1, 10):
                r = parametric_var(arr, config=VaRConfig(confidence=conf, horizon=h))
                assert r.var >= 0.0, f"parametric VaR negative for conf={conf}, h={h}"

    def test_positive_loss_historical(self) -> None:
        arr = _returns_series(51, 1000)
        for conf in (0.95, 0.99):
            for h in (1, 10):
                r = historical_var(arr, config=VaRConfig(confidence=conf, horizon=h))
                assert r.var >= 0.0

    def test_positive_loss_mc(self) -> None:
        arr = _returns_series(52, 500)
        cfg = VaRConfig(confidence=0.95, n_simulations=5000, rng_seed=0)
        for dist in ("normal", "student_t"):
            r = monte_carlo_var(arr, config=cfg, distribution=dist)
            assert r.var >= 0.0, f"MC VaR negative for distribution={dist}"


# ---------------------------------------------------------------------------
# Higher moments: Cornish-Fisher analytic check
# ---------------------------------------------------------------------------


class TestCornishFisherAnalytic:
    def test_reduces_to_normal_zero_moments(self) -> None:
        """With skew=0, excess_kurtosis=0 the CF z equals the normal z."""
        import scipy.stats as _stats

        from core_trading.risk.var import _cornish_fisher_z

        alpha = 0.05
        z_normal = float(_stats.norm.ppf(alpha))
        z_cf = _cornish_fisher_z(z_normal, skew=0.0, ex_kurtosis=0.0)
        assert z_cf == pytest.approx(z_normal, abs=1e-12)

    def test_negative_skew_increases_loss_quantile(self) -> None:
        """Negative skew (left-fat-tail) makes z_CF more negative -> larger VaR."""
        import scipy.stats as _stats

        from core_trading.risk.var import _cornish_fisher_z

        alpha = 0.05
        z_normal = float(_stats.norm.ppf(alpha))  # ~ -1.645
        z_cf_neg_skew = _cornish_fisher_z(z_normal, skew=-1.0, ex_kurtosis=0.0)
        # z_CF < z_normal (more negative) means the loss quantile is larger in magnitude.
        assert z_cf_neg_skew < z_normal

    def test_excess_kurtosis_effect_on_quantile(self) -> None:
        """Cornish-Fisher correction is non-zero for positive excess kurtosis.

        The direction of the correction depends on the z-quantile value.
        At alpha=0.05 (z ~ -1.645) the cubic term (z^3 - 3z) is positive
        (~0.48), so positive excess kurtosis shifts z_CF *toward zero* -- a
        known property of the Cornish-Fisher approximation at this quantile.
        The key check is that the adjustment is nonzero and in the analytically
        correct direction per the Zangari (1996) formula.
        """
        import scipy.stats as _stats

        from core_trading.risk.var import _cornish_fisher_z

        alpha = 0.05
        z_normal = float(_stats.norm.ppf(alpha))   # approx -1.6449
        gamma_2 = 2.0
        z_cf_fat = _cornish_fisher_z(z_normal, skew=0.0, ex_kurtosis=gamma_2)
        # (z^3 - 3z) at z ~ -1.645 is approx 0.48 > 0, so with gamma_2 > 0
        # the CF correction is positive (z_CF > z_normal numerically).
        z_cubed_term = (z_normal ** 3 - 3.0 * z_normal) * gamma_2 / 24.0
        expected_z_cf = z_normal + z_cubed_term
        assert z_cf_fat == pytest.approx(expected_z_cf, abs=1e-12)
        # Nonzero adjustment.
        assert abs(z_cf_fat - z_normal) > 1e-6


# ---------------------------------------------------------------------------
# Methods agree at large N (convergence / consistency)
# ---------------------------------------------------------------------------


class TestMethodConvergence:
    def test_parametric_historical_mc_agree_normal_data(self) -> None:
        """All three methods converge on normal data at large N."""
        rng = np.random.default_rng(60)
        sigma = 0.01
        returns = rng.normal(0.0, sigma, size=100_000)
        cfg = VaRConfig(confidence=0.95, n_simulations=200_000, rng_seed=0)
        analytic = 1.6449 * sigma

        p_var = parametric_var(returns, config=cfg).var
        h_var = historical_var(returns, config=cfg).var
        mc_var = monte_carlo_var(returns, config=cfg, distribution="normal").var

        assert p_var == pytest.approx(analytic, rel=0.01)
        assert h_var == pytest.approx(analytic, rel=0.02)
        assert mc_var == pytest.approx(analytic, rel=0.05)

    def test_higher_confidence_gives_higher_var(self) -> None:
        """99% VaR must exceed 95% VaR for any reasonable return series."""
        arr = _returns_series(61, 5000)
        for method_fn, kwargs in [
            (parametric_var, {}),
            (historical_var, {}),
            (monte_carlo_var, {"distribution": "normal"}),
        ]:
            var_95 = method_fn(  # type: ignore[operator]
                arr, config=VaRConfig(confidence=0.95, n_simulations=20_000, rng_seed=0), **kwargs
            ).var
            var_99 = method_fn(  # type: ignore[operator]
                arr, config=VaRConfig(confidence=0.99, n_simulations=20_000, rng_seed=0), **kwargs
            ).var
            assert var_99 > var_95, f"{method_fn.__name__}: 99% VaR not > 95% VaR"


# ---------------------------------------------------------------------------
# Performance gate
# ---------------------------------------------------------------------------


class TestPerformance:
    def test_full_var_stack_under_two_seconds(self) -> None:
        """Parametric + historical + MC + backtests for 1000-obs series < 2 s."""
        arr = _returns_series(70, 1000, sigma=0.01)
        cfg = VaRConfig(confidence=0.95, n_simulations=20_000, rng_seed=0)

        start = time.perf_counter()
        parametric_var(arr, config=cfg)
        parametric_var(arr, config=cfg, cornish_fisher=True)
        historical_var(arr, config=cfg)
        monte_carlo_var(arr, config=cfg, distribution="student_t")
        monte_carlo_var(arr, config=cfg, distribution="normal")

        # Synthetic backtest: VaR at 95%, classify exceptions.
        var_level = parametric_var(arr, config=cfg).var
        exc = (arr < -var_level).astype(int)
        kupiec_test(exc, alpha=0.05)
        christoffersen_test(exc, alpha=0.05)

        elapsed = time.perf_counter() - start
        assert elapsed < 2.0, f"VaR stack took {elapsed:.3f}s"
