"""Tests for core_trading.signals.pairs.spread (Phase 4.2).

Covers:
* static_hedge_ratio -- recovery of known alpha/beta from synthetic data.
* compute_spread -- correct residual given StaticHedge and bare float.
* fit_ou -- recovery of kappa/mu/sigma/half_life from a simulated OU process.
* KalmanHedge.filter -- tracking a linearly-drifting beta; look-ahead check.
* KalmanHedge.dynamic_spread -- shape and alignment.
* zscore -- all three modes (rolling, OU, full-sample); edge cases.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from core_trading.signals.pairs.spread import (
    KalmanHedge,
    OUParams,
    StaticHedge,
    compute_spread,
    fit_ou,
    static_hedge_ratio,
    zscore,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

RNG = np.random.default_rng(42)


def _make_index(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2020-01-01", periods=n, freq="D")


def _ou_path(
    kappa: float,
    mu: float,
    sigma: float,
    n: int = 1000,
    *,
    rng: np.random.Generator | None = None,
) -> np.ndarray:
    """Simulate a discrete-time OU path via Euler-Maruyama."""
    gen = rng if rng is not None else RNG
    s = np.empty(n)
    s[0] = mu
    eps = gen.standard_normal(n - 1)
    for t in range(1, n):
        s[t] = s[t - 1] + kappa * (mu - s[t - 1]) + sigma * eps[t - 1]
    return s


# ---------------------------------------------------------------------------
# StaticHedge
# ---------------------------------------------------------------------------


class TestStaticHedgeRatio:
    """static_hedge_ratio recovers known alpha and beta."""

    def test_recovers_known_params(self) -> None:
        true_alpha = 5.0
        true_beta = 2.5
        n = 500
        idx = _make_index(n)
        x = pd.Series(RNG.standard_normal(n).cumsum(), index=idx)
        y = pd.Series(true_alpha + true_beta * x.values + RNG.standard_normal(n) * 0.01, index=idx)

        hedge = static_hedge_ratio(y, x)

        assert isinstance(hedge, StaticHedge)
        assert abs(hedge.alpha - true_alpha) < 0.5
        assert abs(hedge.beta - true_beta) < 0.05

    def test_misaligned_index_handled(self) -> None:
        """Series with different indices are aligned by common dates."""
        n = 200
        idx_full = _make_index(n)
        x = pd.Series(RNG.standard_normal(n), index=idx_full)
        y = pd.Series(
            1.0 + 2.0 * x.values + RNG.standard_normal(n) * 0.01,
            index=idx_full,
        )
        # Drop the first 50 rows of y
        hedge = static_hedge_ratio(y.iloc[50:], x)
        assert abs(hedge.beta - 2.0) < 0.1

    def test_raises_on_too_few_obs(self) -> None:
        s = pd.Series([1.0])
        with pytest.raises(ValueError, match="at least 2"):
            static_hedge_ratio(s, s)


# ---------------------------------------------------------------------------
# compute_spread
# ---------------------------------------------------------------------------


class TestComputeSpread:
    def test_static_hedge(self) -> None:
        n = 100
        idx = _make_index(n)
        x = pd.Series(RNG.standard_normal(n), index=idx)
        hedge = StaticHedge(alpha=1.0, beta=2.0)
        y = pd.Series(hedge.alpha + hedge.beta * x.values, index=idx)

        sp = compute_spread(y, x, hedge)

        assert isinstance(sp, pd.Series)
        np.testing.assert_allclose(sp.values, 0.0, atol=1e-10)

    def test_float_hedge(self) -> None:
        n = 100
        idx = _make_index(n)
        x = pd.Series(np.ones(n), index=idx)
        y = pd.Series(3.0 * np.ones(n), index=idx)

        sp = compute_spread(y, x, 3.0)
        np.testing.assert_allclose(sp.values, 0.0, atol=1e-10)

    def test_returns_common_index(self) -> None:
        idx = _make_index(10)
        x = pd.Series(RNG.standard_normal(10), index=idx)
        y = pd.Series(RNG.standard_normal(10), index=idx)
        sp = compute_spread(y, x, 1.0)
        assert len(sp) == 10


# ---------------------------------------------------------------------------
# fit_ou
# ---------------------------------------------------------------------------


class TestFitOU:
    """fit_ou recovers known OU parameters within reasonable tolerance."""

    def test_recovers_kappa_mu_sigma(self) -> None:
        true_kappa = 0.1
        true_mu = 5.0
        true_sigma = 0.5
        n = 2000

        rng = np.random.default_rng(7)
        path = _ou_path(true_kappa, true_mu, true_sigma, n=n, rng=rng)
        idx = _make_index(n)
        spread = pd.Series(path, index=idx)

        params = fit_ou(spread)

        assert isinstance(params, OUParams)
        assert abs(params.kappa - true_kappa) < 0.05, f"kappa={params.kappa}"
        assert abs(params.mu - true_mu) < 0.5, f"mu={params.mu}"
        assert abs(params.sigma - true_sigma) < 0.1, f"sigma={params.sigma}"

    def test_half_life_formula(self) -> None:
        true_kappa = 0.2
        n = 2000
        rng = np.random.default_rng(11)
        path = _ou_path(true_kappa, 0.0, 0.3, n=n, rng=rng)
        idx = _make_index(n)
        params = fit_ou(pd.Series(path, index=idx))

        expected_hl = math.log(2.0) / true_kappa
        assert abs(params.half_life - expected_hl) < 2.0, f"half_life={params.half_life}"

    def test_is_mean_reverting(self) -> None:
        rng = np.random.default_rng(99)
        path = _ou_path(0.15, 0.0, 0.2, n=1000, rng=rng)
        params = fit_ou(pd.Series(path, index=_make_index(1000)))
        assert params.is_mean_reverting

    def test_sigma_eq(self) -> None:
        # For kappa>0 sigma_eq = sigma/sqrt(2*kappa)
        params = OUParams(kappa=0.1, mu=0.0, sigma=0.4, half_life=math.log(2) / 0.1)
        expected = 0.4 / math.sqrt(0.2)
        assert abs(params.sigma_eq - expected) < 1e-10

    def test_sigma_eq_non_mean_reverting(self) -> None:
        params = OUParams(kappa=0.0, mu=float("nan"), sigma=0.3, half_life=float("inf"))
        assert params.sigma_eq == float("inf")


# ---------------------------------------------------------------------------
# KalmanHedge
# ---------------------------------------------------------------------------


class TestKalmanHedge:
    """KalmanHedge tracks a slowly-drifting beta better than static OLS."""

    def _drifting_beta_data(
        self,
        n: int = 600,
    ) -> tuple[pd.Series, pd.Series, np.ndarray]:
        """Construct (y, x) where beta drifts linearly from 1 to 3."""
        rng = np.random.default_rng(17)
        idx = _make_index(n)
        x = pd.Series(rng.standard_normal(n).cumsum() + 100.0, index=idx)
        beta_true = np.linspace(1.0, 3.0, n)
        noise = rng.standard_normal(n) * 0.5
        y = pd.Series(beta_true * x.values + noise, index=idx)
        return y, x, beta_true

    def test_filter_tracks_drifting_beta(self) -> None:
        y, x, beta_true = self._drifting_beta_data()
        kh = KalmanHedge(delta=1e-3, obs_cov=0.5)
        hedge_df = kh.filter(y, x)

        # End-of-sample: Kalman beta should be close to true_beta[-1] = 3.0
        kalman_end_err = abs(hedge_df["beta"].iloc[-1] - beta_true[-1])
        # Static OLS gives a single average beta ~= 2.0
        static = static_hedge_ratio(y, x)
        static_end_err = abs(static.beta - beta_true[-1])

        assert kalman_end_err < static_end_err, (
            f"Kalman err={kalman_end_err:.3f} not better than static err={static_end_err:.3f}"
        )
        assert kalman_end_err < 0.5, f"Kalman beta too far from truth: err={kalman_end_err:.3f}"

    def test_output_shape_and_index(self) -> None:
        n = 100
        idx = _make_index(n)
        x = pd.Series(RNG.standard_normal(n), index=idx)
        y = pd.Series(RNG.standard_normal(n), index=idx)
        kh = KalmanHedge()
        hedge_df = kh.filter(y, x)

        assert hedge_df.shape == (n, 2)
        assert list(hedge_df.columns) == ["alpha", "beta"]
        assert (hedge_df.index == idx).all()

    def test_no_look_ahead(self) -> None:
        """Filter result at time t must not change when we add future data."""
        n = 200
        idx = _make_index(n)
        x = pd.Series(RNG.standard_normal(n), index=idx)
        y = pd.Series(2.0 * x.values + RNG.standard_normal(n) * 0.1, index=idx)

        kh = KalmanHedge()
        full = kh.filter(y, x)
        partial = kh.filter(y.iloc[:100], x.iloc[:100])

        # The estimates for the first 100 bars should match
        np.testing.assert_allclose(
            full["beta"].iloc[:100].values,
            partial["beta"].values,
            rtol=1e-10,
        )

    def test_dynamic_spread_shape(self) -> None:
        n = 100
        idx = _make_index(n)
        x = pd.Series(RNG.standard_normal(n), index=idx)
        y = pd.Series(RNG.standard_normal(n), index=idx)
        kh = KalmanHedge()
        sp = kh.dynamic_spread(y, x)
        assert isinstance(sp, pd.Series)
        assert len(sp) == n

    def test_raises_on_bad_delta(self) -> None:
        with pytest.raises(ValueError):
            KalmanHedge(delta=0.0)
        with pytest.raises(ValueError):
            KalmanHedge(delta=1.0)

    def test_raises_on_bad_obs_cov(self) -> None:
        with pytest.raises(ValueError):
            KalmanHedge(obs_cov=-1.0)

    def test_raises_on_too_few_obs(self) -> None:
        s = pd.Series([1.0])
        with pytest.raises(ValueError, match="at least 2"):
            KalmanHedge().filter(s, s)


# ---------------------------------------------------------------------------
# zscore
# ---------------------------------------------------------------------------


class TestZscore:
    def _std_normal_series(self, n: int = 300) -> pd.Series:
        idx = _make_index(n)
        return pd.Series(RNG.standard_normal(n), index=idx)

    def test_full_sample_mean_zero_std_one(self) -> None:
        s = self._std_normal_series()
        z = zscore(s)
        assert abs(z.mean()) < 0.01
        assert abs(z.std(ddof=1) - 1.0) < 0.01

    def test_rolling_look_ahead_free(self) -> None:
        """Rolling z-score at bar t must use only data up to t."""
        n = 200
        s = self._std_normal_series(n)
        window = 30
        z = zscore(s, window=window)

        # Early bars (before window is full) must be NaN
        assert z.iloc[: window - 1].isna().all(), "early bars should be NaN"
        assert z.iloc[window:].notna().all(), "bars from window onward should be finite"

    def test_rolling_stats_correct(self) -> None:
        n = 200
        idx = _make_index(n)
        vals = np.arange(n, dtype=float)
        s = pd.Series(vals, index=idx)
        window = 10
        z = zscore(s, window=window)

        # Manual check at bar 15 (0-indexed): window=[5..15]
        bar = 15
        roll_mean = vals[bar - window + 1 : bar + 1].mean()
        roll_std = vals[bar - window + 1 : bar + 1].std(ddof=1)
        expected = (vals[bar] - roll_mean) / roll_std
        assert abs(z.iloc[bar] - expected) < 1e-10

    def test_ou_mode(self) -> None:
        ou = OUParams(kappa=0.1, mu=2.0, sigma=0.4, half_life=math.log(2) / 0.1)
        n = 100
        idx = _make_index(n)
        spread = pd.Series(np.full(n, ou.mu), index=idx)
        z = zscore(spread, ou=ou)
        np.testing.assert_allclose(z.values, 0.0, atol=1e-10)

    def test_raises_window_too_small(self) -> None:
        s = self._std_normal_series()
        with pytest.raises(ValueError, match="window must be"):
            zscore(s, window=1)

    def test_raises_zero_std(self) -> None:
        s = pd.Series([1.0, 1.0, 1.0])
        with pytest.raises(ValueError, match="zero or non-finite"):
            zscore(s)

    def test_ou_non_mean_reverting_raises(self) -> None:
        ou = OUParams(kappa=0.0, mu=0.0, sigma=0.3, half_life=float("inf"))
        s = pd.Series([0.0, 1.0, 2.0])
        with pytest.raises(ValueError, match="sigma_eq"):
            zscore(s, ou=ou)
