"""Tests for core_trading.signals.stochastic.gbm (Phase 5.B.4).

Covers:
* GBMParams -- is_valid property, frozen dataclass, direct construction.
* simulate -- output shape/type, first value == s0, determinism, lognormal mean check.
* simulate -- ValueError guards (n<1, dt<=0, s0<=0, sigma<=0).
* fit_gbm -- parameter recovery from a long simulated path.
* fit_gbm -- ValueError guards (too few obs, non-positive prices, dt<=0).
* fit_gbm -- NaN/Inf dropping.
* log_likelihood -- finite, maximized at true params vs random params.
* TestPublicAPI -- imports from the full submodule path.

Design notes
------------
Drift (mu) is notoriously hard to estimate from finite price series.  Its
standard error is sigma / sqrt(T) where T is total elapsed time.  With
daily data, even 20 000 observations span ~79 years of clock time, giving a
95% CI of roughly +/- 2 * sigma / sqrt(T).  We therefore use a generous
MU_TOL (absolute) and document it here rather than weaken it to triviality.

SIGMA_TOL of 5% is achievable with N=20 000 (asymptotic std ~ 1/sqrt(2*N)).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from core_trading.signals.stochastic.gbm import (
    GBMParams,
    fit_gbm,
    log_likelihood,
    simulate,
)

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

# Ground-truth GBM parameters used across recovery tests.
# mu=0.10/yr (10 % annual drift), sigma=0.20/yr (20 % annual vol) are
# realistic equity parameters.  dt=1/252 maps to one trading day.
TRUE_MU = 0.10
TRUE_SIGMA = 0.20
TRUE_DT = 1.0 / 252.0
TRUE_S0 = 100.0
N_LONG = 20_000
SEED = 20240601

# Recovery tolerances -- documented looseness is intentional.
# SIGMA_TOL: 5% relative (well-identified, CLT std ~ 1/sqrt(2N) ~ 0.5% at N=20k)
# MU_TOL: absolute; drift SE = sigma * sqrt(dt * N)^{-1} ~ 0.014 over 79 yrs.
#   With 20 000 daily obs: SE ~ sigma / sqrt(T) = 0.20 / sqrt(79) ~ 0.022.
#   We use 0.10 (about 4.5 SE) to be robust to different seeds.
SIGMA_TOL = 0.05   # 5% relative tolerance
MU_TOL = 0.10      # absolute tolerance (in same units as mu, i.e. per year)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _long_prices(
    mu: float = TRUE_MU,
    sigma: float = TRUE_SIGMA,
    n: int = N_LONG,
    dt: float = TRUE_DT,
    s0: float = TRUE_S0,
    seed: int = SEED,
) -> pd.Series:
    """Simulate a long GBM price path with the default true parameters."""
    return simulate(n=n, dt=dt, s0=s0, mu=mu, sigma=sigma, seed=seed)


# ---------------------------------------------------------------------------
# GBMParams tests
# ---------------------------------------------------------------------------


class TestGBMParams:
    """GBMParams properties, immutability, and direct construction."""

    def test_is_valid_true(self) -> None:
        params = GBMParams(mu=0.05, sigma=0.20)
        assert params.is_valid

    def test_is_valid_false_zero_sigma(self) -> None:
        params = GBMParams(mu=0.05, sigma=0.0)
        assert not params.is_valid

    def test_is_valid_false_negative_sigma(self) -> None:
        params = GBMParams(mu=0.05, sigma=-0.10)
        assert not params.is_valid

    def test_frozen_dataclass(self) -> None:
        """GBMParams instances must be immutable."""
        params = GBMParams(mu=0.05, sigma=0.20)
        with pytest.raises((AttributeError, TypeError)):
            params.mu = 0.99  # type: ignore[misc]

    def test_direct_construction(self) -> None:
        p = GBMParams(mu=0.08, sigma=0.25)
        assert p.mu == 0.08
        assert p.sigma == 0.25

    def test_slots(self) -> None:
        """Dataclass with slots=True should not have __dict__."""
        p = GBMParams(mu=0.1, sigma=0.2)
        assert not hasattr(p, "__dict__")


# ---------------------------------------------------------------------------
# simulate tests
# ---------------------------------------------------------------------------


class TestSimulate:
    """simulate: output contract, determinism, and lognormal moment checks."""

    def test_output_length(self) -> None:
        path = simulate(n=100, dt=TRUE_DT, s0=100.0, mu=0.10, sigma=0.20, seed=1)
        assert len(path) == 100

    def test_output_is_series(self) -> None:
        path = simulate(n=50, dt=TRUE_DT, s0=100.0, mu=0.10, sigma=0.20, seed=1)
        assert isinstance(path, pd.Series)

    def test_first_value_equals_s0(self) -> None:
        s0 = 42.5
        path = simulate(n=200, dt=TRUE_DT, s0=s0, mu=0.10, sigma=0.20, seed=1)
        assert path.iloc[0] == pytest.approx(s0)

    def test_all_prices_positive(self) -> None:
        """GBM prices can never become negative."""
        path = simulate(n=1000, dt=TRUE_DT, s0=100.0, mu=0.10, sigma=0.20, seed=7)
        assert (path.values > 0).all()

    def test_determinism_same_seed(self) -> None:
        """Same seed produces identical paths."""
        p1 = simulate(n=200, dt=TRUE_DT, s0=100.0, mu=0.10, sigma=0.20, seed=42)
        p2 = simulate(n=200, dt=TRUE_DT, s0=100.0, mu=0.10, sigma=0.20, seed=42)
        np.testing.assert_array_equal(p1.values, p2.values)

    def test_determinism_different_seed(self) -> None:
        """Different seeds produce different paths."""
        p1 = simulate(n=200, dt=TRUE_DT, s0=100.0, mu=0.10, sigma=0.20, seed=1)
        p2 = simulate(n=200, dt=TRUE_DT, s0=100.0, mu=0.10, sigma=0.20, seed=2)
        assert not np.array_equal(p1.values, p2.values)

    def test_n_equals_one(self) -> None:
        """n=1 should return a Series with a single value equal to s0."""
        path = simulate(n=1, dt=TRUE_DT, s0=55.0, mu=0.10, sigma=0.20, seed=0)
        assert len(path) == 1
        assert path.iloc[0] == pytest.approx(55.0)

    def test_log_price_mean(self) -> None:
        """Analytic check: E[log(S_t / S_0)] = (mu - 0.5*sigma^2) * t.

        With many steps we check the *terminal* log-price mean via a Monte Carlo
        average over independent paths, not just one path.
        """
        n_paths = 500
        steps = 252  # one simulated year
        expected = (TRUE_MU - 0.5 * TRUE_SIGMA ** 2) * steps * TRUE_DT
        log_ratios = []
        for seed in range(n_paths):
            path = simulate(n=steps + 1, dt=TRUE_DT, s0=TRUE_S0, mu=TRUE_MU,
                            sigma=TRUE_SIGMA, seed=seed)
            log_ratios.append(math.log(float(path.iloc[-1]) / TRUE_S0))
        mc_mean = float(np.mean(log_ratios))
        # With 500 paths the MC std on the mean is sigma*sqrt(T)/sqrt(500) ~ 0.009
        assert abs(mc_mean - expected) < 0.05, (
            f"MC log-return mean={mc_mean:.4f}, expected={expected:.4f}"
        )

    def test_raises_bad_n(self) -> None:
        with pytest.raises(ValueError, match="n must be"):
            simulate(n=0, dt=TRUE_DT, s0=100.0, mu=0.10, sigma=0.20)

    def test_raises_bad_dt(self) -> None:
        with pytest.raises(ValueError, match="dt must be positive"):
            simulate(n=100, dt=0.0, s0=100.0, mu=0.10, sigma=0.20)

    def test_raises_bad_s0(self) -> None:
        with pytest.raises(ValueError, match="s0 must be positive"):
            simulate(n=100, dt=TRUE_DT, s0=0.0, mu=0.10, sigma=0.20)

    def test_raises_bad_sigma(self) -> None:
        with pytest.raises(ValueError, match="sigma must be positive"):
            simulate(n=100, dt=TRUE_DT, s0=100.0, mu=0.10, sigma=0.0)


# ---------------------------------------------------------------------------
# fit_gbm parameter recovery
# ---------------------------------------------------------------------------


class TestFitGBM:
    """fit_gbm recovers known GBM parameters from a long simulated path.

    The long path (N=20 000 daily steps ~ 79 years) is needed because
    drift estimation variance decays only as 1/T (total time), not 1/N.
    """

    def test_sigma_recovery(self) -> None:
        """Sigma (vol) is well-identified; 5% relative tolerance."""
        prices = _long_prices()
        params = fit_gbm(prices, dt=TRUE_DT)
        assert isinstance(params, GBMParams)
        assert abs(params.sigma - TRUE_SIGMA) / TRUE_SIGMA < SIGMA_TOL, (
            f"sigma={params.sigma:.4f}, truth={TRUE_SIGMA}"
        )

    def test_mu_recovery(self) -> None:
        """Drift (mu) is weakly identified; absolute tolerance MU_TOL=0.10."""
        prices = _long_prices()
        params = fit_gbm(prices, dt=TRUE_DT)
        assert abs(params.mu - TRUE_MU) < MU_TOL, (
            f"mu={params.mu:.4f}, truth={TRUE_MU}"
        )

    def test_is_valid(self) -> None:
        """Fitted params must pass the is_valid check."""
        prices = _long_prices()
        params = fit_gbm(prices, dt=TRUE_DT)
        assert params.is_valid

    def test_drops_nan(self) -> None:
        """NaN values are silently dropped before fitting."""
        prices = _long_prices(n=1000)
        contaminated = prices.copy()
        contaminated.iloc[::20] = float("nan")
        params = fit_gbm(contaminated, dt=TRUE_DT)
        assert isinstance(params, GBMParams)

    def test_raises_too_few_obs(self) -> None:
        with pytest.raises(ValueError, match="at least 3"):
            fit_gbm(pd.Series([100.0, 101.0]), dt=TRUE_DT)

    def test_raises_non_positive_price(self) -> None:
        """Prices <= 0 raise a ValueError."""
        prices = pd.Series([100.0, 0.0, 101.0])
        with pytest.raises(ValueError, match="positive"):
            fit_gbm(prices, dt=TRUE_DT)

    def test_raises_bad_dt(self) -> None:
        prices = _long_prices(n=100)
        with pytest.raises(ValueError, match="dt must be positive"):
            fit_gbm(prices, dt=0.0)

    def test_ito_correction(self) -> None:
        """mu_hat should be mu_log_return/dt + 0.5*sigma_hat^2 (Ito correction).

        The mean log-return is (mu - 0.5*sigma^2)*dt.  Inverting must recover mu.
        We verify consistency: fit_gbm(simulate(...)) round-trips reasonably.
        """
        # Round-trip: simulate then fit
        prices = _long_prices()
        params = fit_gbm(prices, dt=TRUE_DT)
        # Reconstruct what the raw log-return mean implies for mu
        log_ret = np.diff(np.log(prices.values))
        mean_r = float(np.mean(log_ret))
        implied_mu = mean_r / TRUE_DT + 0.5 * params.sigma ** 2
        # params.mu must match this implied_mu by construction
        assert abs(params.mu - implied_mu) < 1e-10


# ---------------------------------------------------------------------------
# log_likelihood tests
# ---------------------------------------------------------------------------


class TestLogLikelihood:
    """log_likelihood: finite, maximized at true params, raises on bad inputs."""

    def test_finite_result(self) -> None:
        prices = _long_prices(n=500)
        params = GBMParams(mu=TRUE_MU, sigma=TRUE_SIGMA)
        ll = log_likelihood(prices, params, dt=TRUE_DT)
        assert math.isfinite(ll)

    def test_true_params_beat_random_params(self) -> None:
        """MLE should achieve higher log-likelihood than clearly wrong params."""
        prices = _long_prices(n=5000)
        params_true = GBMParams(mu=TRUE_MU, sigma=TRUE_SIGMA)
        params_wrong = GBMParams(mu=5.0, sigma=5.0)
        ll_true = log_likelihood(prices, params_true, dt=TRUE_DT)
        ll_wrong = log_likelihood(prices, params_wrong, dt=TRUE_DT)
        assert ll_true > ll_wrong

    def test_raises_bad_dt(self) -> None:
        prices = _long_prices(n=100)
        params = GBMParams(mu=TRUE_MU, sigma=TRUE_SIGMA)
        with pytest.raises(ValueError, match="dt must be positive"):
            log_likelihood(prices, params, dt=-1.0)

    def test_raises_bad_sigma(self) -> None:
        prices = _long_prices(n=100)
        params = GBMParams(mu=TRUE_MU, sigma=0.0)
        with pytest.raises(ValueError, match="sigma must be positive"):
            log_likelihood(prices, params, dt=TRUE_DT)

    def test_raises_too_few_obs(self) -> None:
        prices = pd.Series([100.0, 101.0])
        params = GBMParams(mu=TRUE_MU, sigma=TRUE_SIGMA)
        with pytest.raises(ValueError, match="at least 3"):
            log_likelihood(prices, params, dt=TRUE_DT)


# ---------------------------------------------------------------------------
# Public API test
# ---------------------------------------------------------------------------


class TestPublicAPI:
    """Imports from the full submodule path work as expected."""

    def test_imports_from_submodule(self) -> None:
        from core_trading.signals.stochastic.gbm import (  # noqa: F401
            GBMParams,
            fit_gbm,
            log_likelihood,
            simulate,
        )

    def test_all_contents(self) -> None:
        import core_trading.signals.stochastic.gbm as mod
        for name in ("GBMParams", "simulate", "fit_gbm", "log_likelihood"):
            assert hasattr(mod, name), f"missing from module: {name}"

    def test_all_list(self) -> None:
        import core_trading.signals.stochastic.gbm as mod
        for name in mod.__all__:
            assert hasattr(mod, name)
