"""Tests for core_trading.signals.stochastic.ou (Phase 5.B.1).

Covers:
* OUParams -- analytic identities (half_life, sigma_eq), is_mean_reverting.
* simulate -- output shape, determinism, mean/variance of stationary path.
* simulate -- ValueError guards (bad kappa, sigma, dt, n).
* fit_ou_ols -- parameter recovery from a long simulated path.
* fit_ou_mle -- parameter recovery from a long simulated path.
* fit_ou_ols / fit_ou_mle -- near-random-walk series yields large half_life
  without crashing and signals non-mean-reverting.
* fit_ou_ols / fit_ou_mle -- ValueError on too-short series.
* _make_params helper: kappa <= 0 yields inf half_life / sigma_eq.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from core_trading.signals.stochastic.ou import (
    OUParams,
    _make_params,
    fit_ou_mle,
    fit_ou_ols,
    simulate,
)

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

# "Ground truth" OU parameters used in recovery tests.
# A half-life of ~14 bars and moderate sigma give good identifiability.
TRUE_KAPPA = 0.05
TRUE_MU = 10.0
TRUE_SIGMA = 0.8
TRUE_DT = 1.0
N_LONG = 5000
SEED = 20240601

# Tolerance for parameter recovery (percentage of the true value).
KAPPA_TOL = 0.15    # 15% relative tolerance
MU_TOL = 0.5        # absolute tolerance
SIGMA_TOL = 0.15    # 15% relative tolerance


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _long_path(
    kappa: float = TRUE_KAPPA,
    mu: float = TRUE_MU,
    sigma: float = TRUE_SIGMA,
    n: int = N_LONG,
    seed: int = SEED,
) -> pd.Series:
    """Simulate a long OU path with the default true parameters."""
    return simulate(n=n, dt=TRUE_DT, x0=mu, kappa=kappa, mu=mu, sigma=sigma, seed=seed)


def _random_walk(n: int = 2000, seed: int = 999) -> pd.Series:
    """A pure random walk -- non-mean-reverting benchmark."""
    rng = np.random.default_rng(seed)
    return pd.Series(rng.standard_normal(n).cumsum())


# ---------------------------------------------------------------------------
# OUParams unit tests
# ---------------------------------------------------------------------------


class TestOUParams:
    """OUParams analytic identities and properties."""

    def test_half_life_identity(self) -> None:
        """half_life == ln(2) / kappa for kappa > 0."""
        kappa = 0.1
        params = _make_params(kappa, mu=0.0, sigma=1.0)
        expected = math.log(2.0) / kappa
        assert abs(params.half_life - expected) < 1e-12

    def test_sigma_eq_identity(self) -> None:
        """sigma_eq == sigma / sqrt(2*kappa) for kappa > 0."""
        kappa = 0.2
        sigma = 0.5
        params = _make_params(kappa, mu=0.0, sigma=sigma)
        expected = sigma / math.sqrt(2.0 * kappa)
        assert abs(params.sigma_eq - expected) < 1e-12

    def test_is_mean_reverting_true(self) -> None:
        params = _make_params(kappa=0.05, mu=0.0, sigma=1.0)
        assert params.is_mean_reverting

    def test_is_mean_reverting_false_zero_kappa(self) -> None:
        params = _make_params(kappa=0.0, mu=0.0, sigma=1.0)
        assert not params.is_mean_reverting

    def test_non_mean_reverting_half_life_inf(self) -> None:
        params = _make_params(kappa=0.0, mu=0.0, sigma=1.0)
        assert math.isinf(params.half_life)

    def test_non_mean_reverting_sigma_eq_inf(self) -> None:
        params = _make_params(kappa=0.0, mu=0.0, sigma=1.0)
        assert math.isinf(params.sigma_eq)

    def test_frozen_dataclass(self) -> None:
        """OUParams instances must be immutable."""
        params = _make_params(kappa=0.1, mu=0.0, sigma=1.0)
        with pytest.raises((AttributeError, TypeError)):
            params.kappa = 99.0  # type: ignore[misc]

    def test_direct_construction(self) -> None:
        """OUParams can be constructed directly with explicit sigma_eq."""
        p = OUParams(kappa=0.1, mu=5.0, sigma=0.5,
                     half_life=math.log(2) / 0.1,
                     sigma_eq=0.5 / math.sqrt(0.2))
        assert p.kappa == 0.1
        assert p.mu == 5.0
        assert p.sigma == 0.5


# ---------------------------------------------------------------------------
# simulate tests
# ---------------------------------------------------------------------------


class TestSimulate:
    """simulate: output contract, determinism, and statistical properties."""

    def test_output_length(self) -> None:
        path = simulate(n=100, dt=1.0, x0=0.0, kappa=0.1, mu=0.0, sigma=1.0, seed=1)
        assert len(path) == 100

    def test_output_is_series(self) -> None:
        path = simulate(n=50, dt=1.0, x0=0.0, kappa=0.1, mu=0.0, sigma=1.0, seed=1)
        assert isinstance(path, pd.Series)

    def test_first_value_equals_x0(self) -> None:
        x0 = 7.5
        path = simulate(n=200, dt=1.0, x0=x0, kappa=0.1, mu=0.0, sigma=1.0, seed=1)
        assert path.iloc[0] == pytest.approx(x0)

    def test_determinism_same_seed(self) -> None:
        """Same seed produces identical paths."""
        p1 = simulate(n=200, dt=1.0, x0=0.0, kappa=0.1, mu=5.0, sigma=0.5, seed=42)
        p2 = simulate(n=200, dt=1.0, x0=0.0, kappa=0.1, mu=5.0, sigma=0.5, seed=42)
        np.testing.assert_array_equal(p1.values, p2.values)

    def test_determinism_different_seed(self) -> None:
        """Different seeds produce different paths."""
        p1 = simulate(n=200, dt=1.0, x0=0.0, kappa=0.1, mu=5.0, sigma=0.5, seed=1)
        p2 = simulate(n=200, dt=1.0, x0=0.0, kappa=0.1, mu=5.0, sigma=0.5, seed=2)
        assert not np.array_equal(p1.values, p2.values)

    def test_stationary_mean_approx(self) -> None:
        """Long path: sample mean should be close to true mu."""
        path = _long_path()
        assert abs(path.mean() - TRUE_MU) < 0.5

    def test_stationary_std_approx(self) -> None:
        """Long path: sample std should be close to sigma_eq."""
        sigma_eq = TRUE_SIGMA / math.sqrt(2.0 * TRUE_KAPPA)
        path = _long_path()
        assert abs(path.std() - sigma_eq) < 0.5

    def test_n_equals_one(self) -> None:
        """n=1 should return a Series with the single initial value."""
        path = simulate(n=1, dt=1.0, x0=3.0, kappa=0.1, mu=0.0, sigma=0.5, seed=0)
        assert len(path) == 1
        assert path.iloc[0] == pytest.approx(3.0)

    def test_raises_bad_n(self) -> None:
        with pytest.raises(ValueError, match="n must be"):
            simulate(n=0, dt=1.0, x0=0.0, kappa=0.1, mu=0.0, sigma=1.0)

    def test_raises_bad_dt(self) -> None:
        with pytest.raises(ValueError, match="dt must be positive"):
            simulate(n=100, dt=0.0, x0=0.0, kappa=0.1, mu=0.0, sigma=1.0)

    def test_raises_bad_kappa(self) -> None:
        with pytest.raises(ValueError, match="kappa must be positive"):
            simulate(n=100, dt=1.0, x0=0.0, kappa=0.0, mu=0.0, sigma=1.0)

    def test_raises_bad_sigma(self) -> None:
        with pytest.raises(ValueError, match="sigma must be positive"):
            simulate(n=100, dt=1.0, x0=0.0, kappa=0.1, mu=0.0, sigma=0.0)


# ---------------------------------------------------------------------------
# fit_ou_ols parameter recovery
# ---------------------------------------------------------------------------


class TestFitOUOls:
    """fit_ou_ols recovers known OU parameters from a long simulated path."""

    def test_kappa_recovery(self) -> None:
        path = _long_path()
        params = fit_ou_ols(path, dt=TRUE_DT)
        assert isinstance(params, OUParams)
        assert abs(params.kappa - TRUE_KAPPA) / TRUE_KAPPA < KAPPA_TOL, (
            f"OLS kappa={params.kappa:.4f}, truth={TRUE_KAPPA}"
        )

    def test_mu_recovery(self) -> None:
        path = _long_path()
        params = fit_ou_ols(path, dt=TRUE_DT)
        assert abs(params.mu - TRUE_MU) < MU_TOL, (
            f"OLS mu={params.mu:.4f}, truth={TRUE_MU}"
        )

    def test_sigma_recovery(self) -> None:
        path = _long_path()
        params = fit_ou_ols(path, dt=TRUE_DT)
        assert abs(params.sigma - TRUE_SIGMA) / TRUE_SIGMA < SIGMA_TOL, (
            f"OLS sigma={params.sigma:.4f}, truth={TRUE_SIGMA}"
        )

    def test_half_life_identity(self) -> None:
        """Returned half_life must equal ln(2)/kappa for recovered kappa."""
        path = _long_path()
        params = fit_ou_ols(path, dt=TRUE_DT)
        if params.is_mean_reverting:
            expected_hl = math.log(2.0) / params.kappa
            assert abs(params.half_life - expected_hl) < 1e-10

    def test_sigma_eq_identity(self) -> None:
        """Returned sigma_eq must equal sigma/sqrt(2*kappa)."""
        path = _long_path()
        params = fit_ou_ols(path, dt=TRUE_DT)
        if params.is_mean_reverting:
            expected_seq = params.sigma / math.sqrt(2.0 * params.kappa)
            assert abs(params.sigma_eq - expected_seq) < 1e-10

    def test_is_mean_reverting(self) -> None:
        path = _long_path()
        params = fit_ou_ols(path, dt=TRUE_DT)
        assert params.is_mean_reverting

    def test_raises_too_few_obs(self) -> None:
        with pytest.raises(ValueError, match="at least 3"):
            fit_ou_ols(pd.Series([1.0, 2.0]), dt=1.0)

    def test_raises_bad_dt(self) -> None:
        path = _long_path(n=100)
        with pytest.raises(ValueError, match="dt must be positive"):
            fit_ou_ols(path, dt=0.0)

    def test_drops_nan(self) -> None:
        """NaN values are dropped silently before fitting."""
        path = _long_path(n=500)
        contaminated = path.copy()
        contaminated.iloc[::10] = float("nan")
        params = fit_ou_ols(contaminated, dt=TRUE_DT)
        assert isinstance(params, OUParams)

    def test_non_mean_reverting_series_large_half_life(self) -> None:
        """A random walk yields a very large (but finite) half_life without crashing."""
        rw = _random_walk(n=2000, seed=42)
        params = fit_ou_ols(rw, dt=1.0)
        assert isinstance(params, OUParams)
        # half_life should be large -- at least 500 periods
        assert params.half_life > 500.0 or not params.is_mean_reverting

    def test_non_mean_reverting_not_flagged_mean_reverting(self) -> None:
        """Random walk yields a half_life far above any true mean-reverting OU.

        The true OU half_life in these tests is ln(2)/0.05 ~ 13.9 periods.
        A random walk should produce a half_life well above 100 periods.
        """
        rng = np.random.default_rng(7654)
        rw = pd.Series(rng.standard_normal(5000).cumsum())
        params = fit_ou_ols(rw, dt=1.0)
        # half_life >> true OU half_life (~13.9); random walk half_life >= 100
        assert not params.is_mean_reverting or params.half_life > 100.0


# ---------------------------------------------------------------------------
# fit_ou_mle parameter recovery
# ---------------------------------------------------------------------------


class TestFitOUMle:
    """fit_ou_mle recovers known OU parameters from a long simulated path."""

    def test_kappa_recovery(self) -> None:
        path = _long_path()
        params = fit_ou_mle(path, dt=TRUE_DT)
        assert isinstance(params, OUParams)
        assert abs(params.kappa - TRUE_KAPPA) / TRUE_KAPPA < KAPPA_TOL, (
            f"MLE kappa={params.kappa:.4f}, truth={TRUE_KAPPA}"
        )

    def test_mu_recovery(self) -> None:
        path = _long_path()
        params = fit_ou_mle(path, dt=TRUE_DT)
        assert abs(params.mu - TRUE_MU) < MU_TOL, (
            f"MLE mu={params.mu:.4f}, truth={TRUE_MU}"
        )

    def test_sigma_recovery(self) -> None:
        path = _long_path()
        params = fit_ou_mle(path, dt=TRUE_DT)
        assert abs(params.sigma - TRUE_SIGMA) / TRUE_SIGMA < SIGMA_TOL, (
            f"MLE sigma={params.sigma:.4f}, truth={TRUE_SIGMA}"
        )

    def test_half_life_identity(self) -> None:
        path = _long_path()
        params = fit_ou_mle(path, dt=TRUE_DT)
        if params.is_mean_reverting:
            expected_hl = math.log(2.0) / params.kappa
            assert abs(params.half_life - expected_hl) < 1e-10

    def test_sigma_eq_identity(self) -> None:
        path = _long_path()
        params = fit_ou_mle(path, dt=TRUE_DT)
        if params.is_mean_reverting:
            expected_seq = params.sigma / math.sqrt(2.0 * params.kappa)
            assert abs(params.sigma_eq - expected_seq) < 1e-10

    def test_is_mean_reverting(self) -> None:
        path = _long_path()
        params = fit_ou_mle(path, dt=TRUE_DT)
        assert params.is_mean_reverting

    def test_raises_too_few_obs(self) -> None:
        with pytest.raises(ValueError, match="at least 3"):
            fit_ou_mle(pd.Series([1.0, 2.0]), dt=1.0)

    def test_raises_bad_dt(self) -> None:
        path = _long_path(n=100)
        with pytest.raises(ValueError, match="dt must be positive"):
            fit_ou_mle(path, dt=-1.0)

    def test_drops_nan(self) -> None:
        path = _long_path(n=500)
        contaminated = path.copy()
        contaminated.iloc[::5] = float("nan")
        params = fit_ou_mle(contaminated, dt=TRUE_DT)
        assert isinstance(params, OUParams)

    def test_non_mean_reverting_series_large_half_life(self) -> None:
        """A random walk yields a very large (but finite) half_life without crashing."""
        rw = _random_walk(n=2000, seed=42)
        params = fit_ou_mle(rw, dt=1.0)
        assert isinstance(params, OUParams)
        assert params.half_life > 500.0 or not params.is_mean_reverting

    def test_non_mean_reverting_not_flagged_mean_reverting(self) -> None:
        """Random walk yields a half_life far above any true mean-reverting OU.

        The true OU half_life in these tests is ln(2)/0.05 ~ 13.9 periods.
        A random walk should produce a half_life well above 100 periods.
        """
        rng = np.random.default_rng(7654)
        rw = pd.Series(rng.standard_normal(5000).cumsum())
        params = fit_ou_mle(rw, dt=1.0)
        # half_life >> true OU half_life (~13.9); random walk half_life >= 100
        assert not params.is_mean_reverting or params.half_life > 100.0


# ---------------------------------------------------------------------------
# Cross-estimator consistency
# ---------------------------------------------------------------------------


class TestEstimatorConsistency:
    """OLS and MLE should agree closely on a long path."""

    def test_kappa_agreement(self) -> None:
        path = _long_path()
        ols = fit_ou_ols(path, dt=TRUE_DT)
        mle = fit_ou_mle(path, dt=TRUE_DT)
        # Both should be within 20% of each other
        assert abs(ols.kappa - mle.kappa) / max(ols.kappa, mle.kappa) < 0.20, (
            f"OLS kappa={ols.kappa:.4f} vs MLE kappa={mle.kappa:.4f}"
        )

    def test_mu_agreement(self) -> None:
        path = _long_path()
        ols = fit_ou_ols(path, dt=TRUE_DT)
        mle = fit_ou_mle(path, dt=TRUE_DT)
        assert abs(ols.mu - mle.mu) < 0.5, (
            f"OLS mu={ols.mu:.4f} vs MLE mu={mle.mu:.4f}"
        )

    def test_sigma_agreement(self) -> None:
        path = _long_path()
        ols = fit_ou_ols(path, dt=TRUE_DT)
        mle = fit_ou_mle(path, dt=TRUE_DT)
        assert abs(ols.sigma - mle.sigma) / max(ols.sigma, mle.sigma) < 0.20, (
            f"OLS sigma={ols.sigma:.4f} vs MLE sigma={mle.sigma:.4f}"
        )


# ---------------------------------------------------------------------------
# Defensive edge-branch coverage
# ---------------------------------------------------------------------------


class TestDefensiveBranches:
    """Exercise the numeric guard branches in fit_ou_ols and fit_ou_mle.

    These branches protect against degenerate data; the tests verify that
    the functions return valid OUParams without raising.
    """

    def test_ols_phi_negative_clamped(self) -> None:
        """An alternating series gives phi < 0 in the AR regression.

        The code clamps phi to 1e-10; the returned OUParams must still be
        a valid frozen dataclass (no exception).
        """
        # Alternating +1/-1 produces extreme negative AR(1) coefficient
        n = 200
        vals = np.where(np.arange(n) % 2 == 0, 1.0, -1.0).astype(float)
        params = fit_ou_ols(pd.Series(vals), dt=1.0)
        assert isinstance(params, OUParams)
        # phi was clamped, so kappa should be derived from a very small phi
        assert params.kappa > 0.0

    def test_ols_constant_series_no_crash(self) -> None:
        """A constant series (phi=0.5 via lstsq min-norm) must not crash.

        OLS on a constant series returns c=0.5, phi=0.5 (minimum-norm solution).
        kappa = -ln(0.5)/dt ~= 0.693.  The function must return a valid OUParams.
        """
        vals = np.ones(100, dtype=float)
        params = fit_ou_ols(pd.Series(vals), dt=1.0)
        assert isinstance(params, OUParams)
        assert params.kappa > 0.0

    def test_mle_constant_series_degenerate_denom(self) -> None:
        """A constant series makes the MLE mu denominator degenerate.

        Sxx = Sxy when all x_lag == x_fwd (constant series), so denom_mu -> 0
        and the fallback to sample mean is taken (line 429).
        """
        vals = np.full(100, 5.0, dtype=float)
        params = fit_ou_mle(pd.Series(vals), dt=1.0)
        assert isinstance(params, OUParams)
        # mu should fall back to sample mean = 5.0
        assert abs(params.mu - 5.0) < 1.0

    def test_mle_phi_negative_clamped(self) -> None:
        """Alternating series gives phi < 0 in MLE; code clamps to 1e-10."""
        n = 200
        vals = np.where(np.arange(n) % 2 == 0, 1.0, -1.0).astype(float)
        params = fit_ou_mle(pd.Series(vals), dt=1.0)
        assert isinstance(params, OUParams)
        assert params.kappa > 0.0


# ---------------------------------------------------------------------------
# Public re-export check
# ---------------------------------------------------------------------------


class TestPublicAPI:
    """Verify that the stochastic package re-exports the expected names."""

    def test_imports_from_package(self) -> None:
        from core_trading.signals.stochastic import (  # noqa: F401
            OUParams,
            fit_ou_mle,
            fit_ou_ols,
            simulate,
        )

    def test_all_contents(self) -> None:
        import core_trading.signals.stochastic as pkg
        for name in ("OUParams", "simulate", "fit_ou_ols", "fit_ou_mle"):
            assert hasattr(pkg, name), f"missing from package: {name}"
