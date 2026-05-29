"""Tests for core_trading.research.stat_tests.

Validation strategy: every test is checked against a *known* generating
process -- ADF/KPSS on white noise vs a random walk, Engle-Granger/Johansen on
a constructed cointegrated pair, half-life against the analytic value of an OU
process, etc. This is the "textbook validation" the Phase 2 DOD requires.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core_trading.research import stat_tests as st


@pytest.fixture
def rng() -> np.random.Generator:
    return np.random.default_rng(20260529)


@pytest.fixture
def white_noise(rng) -> np.ndarray:
    return rng.standard_normal(800)


@pytest.fixture
def random_walk(rng) -> np.ndarray:
    return np.cumsum(rng.standard_normal(800))


@pytest.fixture
def cointegrated_pair(rng):
    x = np.cumsum(rng.standard_normal(600))
    y = 1.5 * x + rng.standard_normal(600)  # stationary residual => cointegrated
    return y, x


def _fractional_noise(n: int, d: float, rng: np.random.Generator) -> np.ndarray:
    """ARFIMA(0,d,0) long-memory series via the (1-L)^-d MA weights."""
    weights = np.empty(n)
    weights[0] = 1.0
    for k in range(1, n):
        weights[k] = weights[k - 1] * (k - 1 + d) / k
    return np.convolve(rng.standard_normal(n), weights)[:n]


# ----------------------------------------------------------------- stationarity
class TestADF:
    def test_random_walk_not_stationary(self, random_walk) -> None:
        assert st.adf_test(random_walk).is_significant() is False

    def test_white_noise_stationary(self, white_noise) -> None:
        assert st.adf_test(white_noise).is_significant() is True

    def test_result_fields(self, white_noise) -> None:
        res = st.adf_test(white_noise)
        assert res.name == "Augmented Dickey-Fuller"
        assert res.pvalue is not None
        assert "5%" in res.crit_values
        assert res.lags is not None

    def test_too_few_observations(self) -> None:
        with pytest.raises(ValueError):
            st.adf_test([1.0, 2.0])

    def test_accepts_pandas_series(self, white_noise) -> None:
        s = pd.Series(white_noise)
        assert st.adf_test(s).is_significant() is True


class TestKPSS:
    def test_white_noise_is_stationary(self, white_noise) -> None:
        # KPSS H0 is stationarity; should NOT reject for white noise.
        assert st.kpss_test(white_noise).is_significant() is False

    def test_random_walk_rejects(self, random_walk) -> None:
        assert st.kpss_test(random_walk).is_significant() is True

    def test_interpolation_note_captured(self, random_walk) -> None:
        # A strong unit root drives the statistic past the lookup table, which
        # statsmodels flags via InterpolationWarning -- captured into notes,
        # not raised.
        res = st.kpss_test(random_walk)
        assert res.notes  # at least one note recorded

    def test_too_few_observations(self) -> None:
        with pytest.raises(ValueError):
            st.kpss_test([1.0, 2.0, 3.0])


class TestPhillipsPerron:
    def test_random_walk_not_stationary(self, random_walk) -> None:
        assert st.phillips_perron_test(random_walk).is_significant() is False

    def test_white_noise_stationary(self, white_noise) -> None:
        assert st.phillips_perron_test(white_noise).is_significant() is True

    def test_too_few(self) -> None:
        with pytest.raises(ValueError):
            st.phillips_perron_test([1.0, 2.0])


# ----------------------------------------------------------------- cointegration
class TestEngleGranger:
    def test_detects_cointegration(self, cointegrated_pair) -> None:
        y, x = cointegrated_pair
        res = st.engle_granger_test(y, x)
        assert res.is_significant() is True
        assert res.extra["hedge_ratio"] == pytest.approx(1.5, abs=0.1)

    def test_independent_walks_not_cointegrated(self, rng) -> None:
        a = np.cumsum(rng.standard_normal(600))
        b = np.cumsum(rng.standard_normal(600))
        assert st.engle_granger_test(a, b).is_significant() is False

    def test_length_mismatch(self) -> None:
        with pytest.raises(ValueError):
            st.engle_granger_test([1.0, 2.0, 3.0], [1.0, 2.0])

    def test_too_few(self, rng) -> None:
        with pytest.raises(ValueError):
            st.engle_granger_test(rng.standard_normal(5), rng.standard_normal(5))


class TestJohansen:
    def test_rank_one_for_cointegrated_pair(self, cointegrated_pair) -> None:
        y, x = cointegrated_pair
        res = st.johansen_test(pd.DataFrame({"y": y, "x": x}))
        assert res.rank() == 1
        assert res.n_series == 2

    def test_rank_zero_for_independent(self, rng) -> None:
        a = np.cumsum(rng.standard_normal(600))
        b = np.cumsum(rng.standard_normal(600))
        res = st.johansen_test(pd.DataFrame({"a": a, "b": b}))
        assert res.rank() == 0

    def test_hedge_ratios_normalised(self, cointegrated_pair) -> None:
        y, x = cointegrated_pair
        res = st.johansen_test(pd.DataFrame({"y": y, "x": x}))
        hedge = res.hedge_ratios()
        assert hedge[0] == pytest.approx(1.0)

    def test_requires_two_series(self, rng) -> None:
        with pytest.raises(ValueError):
            st.johansen_test(pd.DataFrame({"a": rng.standard_normal(50)}))

    def test_too_few_rows(self, rng) -> None:
        with pytest.raises(ValueError):
            st.johansen_test(
                pd.DataFrame({"a": rng.standard_normal(5), "b": rng.standard_normal(5)})
            )


# ------------------------------------------------------------------- long memory
class TestHurst:
    def test_random_walk_near_half(self, random_walk) -> None:
        h = st.hurst_exponent(random_walk)
        assert 0.40 <= h.exponent <= 0.60
        assert h.method == "variance-of-differences"

    def test_persistent_series_high(self, rng) -> None:
        # Integrate long-memory (d=0.4) increments => level has H = d + 0.5 ~ 0.9.
        level = np.cumsum(_fractional_noise(2000, 0.4, rng))
        assert st.hurst_exponent(level).exponent > 0.60

    def test_mean_reverting_low(self, rng) -> None:
        n = 2000
        s = np.zeros(n)
        for t in range(1, n):
            s[t] = 0.5 * (0.0 - s[t - 1]) + s[t - 1] + rng.standard_normal()
        assert st.hurst_exponent(s).exponent < 0.5

    def test_interpretation_strings(self) -> None:
        assert st.HurstResult(0.3, "m", 10).interpretation == "mean-reverting"
        assert st.HurstResult(0.5, "m", 10).interpretation == "random-walk"
        assert st.HurstResult(0.8, "m", 10).interpretation == "trending"

    def test_too_few(self) -> None:
        with pytest.raises(ValueError):
            st.hurst_exponent([1.0, 2.0], min_lag=2)

    def test_bad_max_lag(self, white_noise) -> None:
        with pytest.raises(ValueError):
            st.hurst_exponent(white_noise, min_lag=5, max_lag=4)


class TestHalfLife:
    def test_ou_half_life_matches_theory(self, rng) -> None:
        n, theta = 4000, 0.04
        s = np.zeros(n)
        for t in range(1, n):
            s[t] = s[t - 1] + theta * (0.0 - s[t - 1]) + rng.standard_normal()
        hl = st.half_life(s)
        expected = np.log(2) / theta
        assert hl.is_mean_reverting
        assert hl.half_life == pytest.approx(expected, rel=0.30)
        assert hl.kappa == pytest.approx(theta, rel=0.30)

    def test_random_walk_has_long_half_life(self, random_walk) -> None:
        # A random walk has no real mean reversion; small-sample DF bias yields
        # a slightly negative slope, so the half-life is large (>> the OU value).
        assert st.half_life(random_walk).half_life > 40.0

    def test_explosive_series_not_mean_reverting(self, rng) -> None:
        n = 500
        s = np.zeros(n)
        for t in range(1, n):
            s[t] = 1.01 * s[t - 1] + rng.standard_normal()
        hl = st.half_life(s)
        assert not hl.is_mean_reverting
        assert np.isinf(hl.half_life)

    def test_too_few(self) -> None:
        with pytest.raises(ValueError):
            st.half_life([1.0, 2.0])


# ---------------------------------------------------------- variance ratio / etc
class TestVarianceRatio:
    def test_random_walk_not_rejected(self, random_walk) -> None:
        assert st.variance_ratio_test(random_walk, lags=4).is_significant() is False

    def test_extra_has_ratio(self, random_walk) -> None:
        res = st.variance_ratio_test(random_walk, lags=2)
        assert "variance_ratio" in res.extra

    def test_too_few(self) -> None:
        with pytest.raises(ValueError):
            st.variance_ratio_test([1.0, 2.0], lags=4)


class TestLjungBox:
    def test_iid_no_autocorrelation(self, white_noise) -> None:
        assert st.ljung_box_test(white_noise, lags=10).is_significant() is False

    def test_ar1_has_autocorrelation(self, rng) -> None:
        n = 800
        x = np.zeros(n)
        for t in range(1, n):
            x[t] = 0.7 * x[t - 1] + rng.standard_normal()
        assert st.ljung_box_test(x, lags=10).is_significant() is True

    def test_too_few(self) -> None:
        with pytest.raises(ValueError):
            st.ljung_box_test([1.0, 2.0], lags=10)


class TestJarqueBera:
    def test_normal_not_rejected(self, rng) -> None:
        assert st.jarque_bera_test(rng.standard_normal(2000)).is_significant() is False

    def test_fat_tailed_rejected(self, rng) -> None:
        fat = rng.standard_t(3, size=2000)
        assert st.jarque_bera_test(fat).is_significant() is True

    def test_extra_moments(self, rng) -> None:
        res = st.jarque_bera_test(rng.standard_normal(1000))
        assert "skew" in res.extra and "excess_kurtosis" in res.extra

    def test_too_few(self) -> None:
        with pytest.raises(ValueError):
            st.jarque_bera_test([1.0])


class TestArchLM:
    def test_homoskedastic_not_rejected(self, white_noise) -> None:
        assert st.arch_lm_test(white_noise, lags=5).is_significant() is False

    def test_garch_like_rejected(self, rng) -> None:
        n = 2000
        eps = np.zeros(n)
        sigma2 = np.ones(n)
        for t in range(1, n):
            sigma2[t] = 0.05 + 0.90 * eps[t - 1] ** 2 + 0.05 * sigma2[t - 1]
            eps[t] = np.sqrt(sigma2[t]) * rng.standard_normal()
        assert st.arch_lm_test(eps, lags=10).is_significant() is True

    def test_too_few(self) -> None:
        with pytest.raises(ValueError):
            st.arch_lm_test([1.0, 2.0], lags=12)


# ------------------------------------------------------------- structural breaks
class TestChow:
    def test_detects_break(self, rng) -> None:
        x = np.linspace(0, 10, 400)
        y = np.concatenate([2 * x[:200], -3 * x[200:] + 50]) + rng.standard_normal(400) * 0.5
        res = st.chow_test(y, x, break_index=200)
        assert res.is_significant() is True

    def test_no_break_stable(self, rng) -> None:
        x = np.linspace(0, 10, 400)
        y = 2 * x + rng.standard_normal(400) * 0.5
        assert st.chow_test(y, x, break_index=200).is_significant() is False

    def test_break_index_bounds(self, rng) -> None:
        x = rng.standard_normal(100)
        y = rng.standard_normal(100)
        with pytest.raises(ValueError):
            st.chow_test(y, x, break_index=1)

    def test_length_mismatch(self) -> None:
        with pytest.raises(ValueError):
            st.chow_test([1.0, 2.0, 3.0], [1.0, 2.0], break_index=1)


class TestCusumStability:
    def test_stable_not_rejected(self, rng) -> None:
        x = np.linspace(0, 10, 400)
        y = 2 * x + rng.standard_normal(400) * 0.5
        assert st.cusum_stability_test(y, x).is_significant() is False

    def test_break_detected(self, rng) -> None:
        x = np.linspace(0, 10, 400)
        y = np.concatenate([2 * x[:200], 8 * x[200:] - 60]) + rng.standard_normal(400) * 0.3
        assert st.cusum_stability_test(y, x).is_significant() is True

    def test_length_mismatch(self) -> None:
        with pytest.raises(ValueError):
            st.cusum_stability_test([1.0, 2.0, 3.0], [1.0, 2.0])

    def test_too_few(self) -> None:
        with pytest.raises(ValueError):
            st.cusum_stability_test([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])


# ------------------------------------------------------- multiple-testing & misc
class TestAdjustPValues:
    def test_bonferroni(self) -> None:
        reject, adj = st.adjust_pvalues([0.01, 0.04, 0.03], method="bonferroni", alpha=0.05)
        assert adj[0] == pytest.approx(0.03)
        assert reject[0]

    def test_holm(self) -> None:
        reject, adj = st.adjust_pvalues([0.01, 0.02, 0.5], method="holm")
        assert reject.tolist() == [True, True, False]

    def test_bh_alias(self) -> None:
        reject, adj = st.adjust_pvalues([0.001, 0.2, 0.3], method="bh")
        assert reject[0]

    def test_empty(self) -> None:
        reject, adj = st.adjust_pvalues([])
        assert reject.size == 0 and adj.size == 0


class TestStatTestResult:
    def test_is_significant_uses_pvalue(self) -> None:
        r = st.StatTestResult(name="x", statistic=1.0, pvalue=0.01)
        assert r.is_significant(0.05) is True
        assert r.is_significant(0.001) is False

    def test_is_significant_uses_crit_value(self) -> None:
        r = st.StatTestResult(name="x", statistic=-4.0, crit_values={"5%": -2.86})
        assert r.is_significant(0.05) is True

    def test_missing_crit_value_raises(self) -> None:
        r = st.StatTestResult(name="x", statistic=-4.0, crit_values={})
        with pytest.raises(ValueError):
            r.is_significant(0.05)


class TestDefensiveGuards:
    def test_johansen_hedge_zero_lead(self) -> None:
        evec = np.array([[0.0, 1.0], [1.0, 0.0]])
        res = st.JohansenResult(
            trace_stats=np.array([1.0, 0.5]),
            trace_crit=np.zeros((2, 3)),
            max_eig_stats=np.array([1.0, 0.5]),
            max_eig_crit=np.zeros((2, 3)),
            eigenvalues=np.array([0.1, 0.05]),
            eigenvectors=evec,
            n_series=2,
        )
        # First eigenvector leads with 0 -> returned unnormalised.
        assert np.array_equal(res.hedge_ratios(), evec[:, 0])

    def test_hurst_constant_series_raises(self) -> None:
        with pytest.raises(ValueError):
            st.hurst_exponent(np.full(200, 5.0))
