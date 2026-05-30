"""Tests for core_trading.signals.pairs.selection (Phase 4.1).

Covers:
* PairCandidate construction and frozen-dataclass semantics.
* distance_score: normalisation and ordering.
* select_pairs_distance: top-n, sector filter, volume filter, min_obs skip.
* select_pairs_cointegration: recovers known cointegrated pair, excludes
  spurious pairs, hedge_ratio ~ 1.5, max_half_life filter, sector filter,
  volume filter.
* select_pairs_johansen: recovers cointegrated pair, max_half_life filter.
* select_pairs_copula: top-n, correlated vs uncorrelated ranking.
* All tests use np.random.default_rng for reproducibility.
* No flaky statsmodels warnings escape under -W error.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import pytest

from core_trading.signals.pairs.selection import (
    PairCandidate,
    distance_score,
    select_pairs_cointegration,
    select_pairs_copula,
    select_pairs_distance,
    select_pairs_johansen,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

N = 300  # default series length; long enough for robust cointegration tests


def _make_rng(seed: int = 42) -> np.random.Generator:
    return np.random.default_rng(seed)


def _random_walk(rng: np.random.Generator, n: int = N, scale: float = 1.0) -> np.ndarray:
    """Returns a simple random walk starting at 100."""
    steps = rng.normal(0.0, scale, size=n)
    return 100.0 + np.cumsum(steps)


def _make_cointegrated_frame(
    rng: np.random.Generator, hedge: float = 1.5, n: int = N
) -> pd.DataFrame:
    """Build a prices frame with a known cointegrated pair (y, x) plus a
    spurious random walk z.

    y = hedge * x + noise  (cointegrated, hedge ratio = hedge)
    z = independent random walk
    """
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    x = _random_walk(rng, n)
    noise = rng.normal(0.0, 1.0, size=n)
    y = hedge * x + noise
    z = _random_walk(rng, n)
    return pd.DataFrame({"y": y, "x": x, "z": z}, index=dates)


def _make_distance_frame(rng: np.random.Generator, n: int = N) -> pd.DataFrame:
    """Build a frame with a near-identical pair (a, b) and an unrelated series c."""
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    base = _random_walk(rng, n)
    a = base + rng.normal(0.0, 0.01, size=n)  # very close to base
    b = base + rng.normal(0.0, 0.01, size=n)  # also very close to base
    c = _random_walk(rng, n, scale=3.0)        # unrelated; different vol
    return pd.DataFrame({"a": a, "b": b, "c": c}, index=dates)


# ---------------------------------------------------------------------------
# PairCandidate
# ---------------------------------------------------------------------------


class TestPairCandidate:
    def test_construction(self) -> None:
        pc = PairCandidate(
            symbol_y="A",
            symbol_x="B",
            hedge_ratio=1.5,
            pvalue=0.02,
            pvalue_adj=0.05,
            half_life=10.0,
            method="engle_granger",
            score=0.05,
            sector="tech",
        )
        assert pc.symbol_y == "A"
        assert pc.symbol_x == "B"
        assert pc.hedge_ratio == 1.5
        assert pc.sector == "tech"

    def test_frozen(self) -> None:
        pc = PairCandidate(
            symbol_y="A",
            symbol_x="B",
            hedge_ratio=1.0,
            pvalue=float("nan"),
            pvalue_adj=float("nan"),
            half_life=5.0,
            method="distance",
            score=0.1,
        )
        with pytest.raises((AttributeError, TypeError)):
            pc.symbol_y = "Z"  # type: ignore[misc]

    def test_sector_default_none(self) -> None:
        pc = PairCandidate(
            symbol_y="A",
            symbol_x="B",
            hedge_ratio=1.0,
            pvalue=float("nan"),
            pvalue_adj=float("nan"),
            half_life=5.0,
            method="distance",
            score=0.1,
        )
        assert pc.sector is None


# ---------------------------------------------------------------------------
# distance_score
# ---------------------------------------------------------------------------


class TestDistanceScore:
    def test_identical_series_zero(self) -> None:
        rng = _make_rng()
        s = pd.Series(_random_walk(rng, 100))
        assert distance_score(s, s) == pytest.approx(0.0, abs=1e-10)

    def test_different_series_positive(self) -> None:
        rng = _make_rng()
        s1 = pd.Series(_random_walk(rng, 100))
        s2 = pd.Series(_random_walk(rng, 100))
        assert distance_score(s1, s2) > 0.0

    def test_close_pair_beats_distant_pair(self) -> None:
        rng = _make_rng(1)
        base = _random_walk(rng, 200)
        close = base + rng.normal(0.0, 0.01, 200)
        unrelated = _random_walk(rng, 200, scale=5.0)
        s_base = pd.Series(base)
        s_close = pd.Series(close)
        s_unrelated = pd.Series(unrelated)
        assert distance_score(s_base, s_close) < distance_score(s_base, s_unrelated)

    def test_nan_filtering(self) -> None:
        s1 = pd.Series([1.0, 2.0, float("nan"), 4.0, 5.0])
        s2 = pd.Series([1.1, 2.1, 3.1, float("nan"), 5.1])
        # Should not raise; NaNs are dropped jointly.
        score = distance_score(s1, s2)
        assert np.isfinite(score)

    def test_all_nan_returns_inf(self) -> None:
        s = pd.Series([float("nan")] * 10)
        assert not np.isfinite(distance_score(s, s))


# ---------------------------------------------------------------------------
# select_pairs_distance
# ---------------------------------------------------------------------------


class TestSelectPairsDistance:
    def test_near_identical_pair_ranked_first(self) -> None:
        rng = _make_rng(2)
        prices = _make_distance_frame(rng)
        results = select_pairs_distance(prices, top_n=3, min_obs=50)
        assert len(results) >= 1
        # (a, b) should be ranked first (smallest distance).
        first = results[0]
        pair = {first.symbol_y, first.symbol_x}
        assert pair == {"a", "b"}, f"Expected (a,b) first, got {pair}"

    def test_top_n_respected(self) -> None:
        rng = _make_rng(3)
        prices = _make_distance_frame(rng)
        results = select_pairs_distance(prices, top_n=2)
        assert len(results) <= 2

    def test_sorted_ascending(self) -> None:
        rng = _make_rng(4)
        prices = _make_distance_frame(rng)
        results = select_pairs_distance(prices, top_n=5)
        scores = [r.score for r in results]
        assert scores == sorted(scores)

    def test_method_label(self) -> None:
        rng = _make_rng(5)
        prices = _make_distance_frame(rng)
        results = select_pairs_distance(prices, top_n=1)
        assert results[0].method == "distance"

    def test_pvalue_nan(self) -> None:
        rng = _make_rng(6)
        prices = _make_distance_frame(rng)
        results = select_pairs_distance(prices, top_n=1)
        assert np.isnan(results[0].pvalue)
        assert np.isnan(results[0].pvalue_adj)

    def test_hedge_ratio_computed(self) -> None:
        rng = _make_rng(7)
        prices = _make_distance_frame(rng)
        results = select_pairs_distance(prices, top_n=1)
        assert np.isfinite(results[0].hedge_ratio)

    def test_sector_filter_excludes_cross_sector_pairs(self) -> None:
        rng = _make_rng(8)
        prices = _make_distance_frame(rng)
        sectors = {"a": "tech", "b": "finance", "c": "tech"}
        results = select_pairs_distance(
            prices, top_n=10, sectors=sectors, require_same_sector=True
        )
        # Only (a, c) share sector "tech".
        for r in results:
            assert r.symbol_y in {"a", "c"} and r.symbol_x in {"a", "c"}

    def test_sector_label_assigned(self) -> None:
        rng = _make_rng(9)
        prices = _make_distance_frame(rng)
        sectors = {"a": "tech", "b": "tech", "c": "finance"}
        results = select_pairs_distance(prices, top_n=1, sectors=sectors)
        assert results[0].sector == "tech"

    def test_volume_filter_drops_low_volume_symbol(self) -> None:
        rng = _make_rng(10)
        prices = _make_distance_frame(rng)
        dates = prices.index
        # Give (a, b) high volume, c near-zero volume.
        volume = pd.DataFrame(
            {
                "a": np.full(len(dates), 1_000_000.0),
                "b": np.full(len(dates), 1_000_000.0),
                "c": np.full(len(dates), 1.0),  # below threshold
            },
            index=dates,
        )
        results = select_pairs_distance(
            prices, top_n=10, volume=volume, min_avg_volume=1000.0
        )
        # No pair involving "c" should appear.
        for r in results:
            assert r.symbol_y != "c" and r.symbol_x != "c"

    def test_min_obs_skips_short_pairs(self) -> None:
        rng = _make_rng(11)
        # Only 30 rows -- below default min_obs=60.
        short_prices = pd.DataFrame(
            {"a": _random_walk(rng, 30), "b": _random_walk(rng, 30)},
            index=pd.date_range("2020-01-01", periods=30, freq="B"),
        )
        results = select_pairs_distance(short_prices, min_obs=60)
        assert results == []

    def test_min_obs_allows_exact_threshold(self) -> None:
        rng = _make_rng(12)
        n = 60
        prices = pd.DataFrame(
            {"a": _random_walk(rng, n), "b": _random_walk(rng, n)},
            index=pd.date_range("2020-01-01", periods=n, freq="B"),
        )
        # Should not skip -- exactly at threshold.
        results = select_pairs_distance(prices, min_obs=60)
        assert len(results) == 1


# ---------------------------------------------------------------------------
# select_pairs_cointegration
# ---------------------------------------------------------------------------


class TestSelectPairsCointegration:
    def _run_coint(
        self,
        rng: np.random.Generator,
        n: int = N,
        hedge: float = 1.5,
        alpha: float = 0.05,
        correction: str = "bonferroni",
        max_half_life: float = 30.0,
    ) -> list[PairCandidate]:
        prices = _make_cointegrated_frame(rng, hedge=hedge, n=n)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return select_pairs_cointegration(
                prices,
                alpha=alpha,
                max_half_life=max_half_life,
                correction=correction,
                min_obs=60,
            )

    def test_recovers_cointegrated_pair(self) -> None:
        rng = _make_rng(20)
        results = self._run_coint(rng)
        pairs = [({r.symbol_y, r.symbol_x}) for r in results]
        assert {"y", "x"} in pairs, "Cointegrated pair (y,x) not found in results"

    def test_spurious_pairs_excluded(self) -> None:
        rng = _make_rng(21)
        results = self._run_coint(rng, correction="bonferroni")
        spurious = [r for r in results if "z" in (r.symbol_y, r.symbol_x)]
        assert spurious == [], f"Spurious z-pairs passed the filter: {spurious}"

    def test_cointegrated_pair_ranked_first(self) -> None:
        rng = _make_rng(22)
        results = self._run_coint(rng)
        assert results, "No cointegrated pairs found"
        first = {results[0].symbol_y, results[0].symbol_x}
        assert first == {"y", "x"}

    def test_hedge_ratio_close_to_true_value(self) -> None:
        rng = _make_rng(23)
        results = self._run_coint(rng, hedge=1.5)
        assert results, "No cointegrated pairs found"
        yx = next(
            (r for r in results if {r.symbol_y, r.symbol_x} == {"y", "x"}), None
        )
        assert yx is not None
        # OLS convention: if symbol_y == "y", hedge_ratio ~ 1.5;
        # if symbol_y == "x", hedge_ratio ~ 1/1.5.
        if yx.symbol_y == "y":
            assert yx.hedge_ratio == pytest.approx(1.5, abs=0.25), (
                f"Expected hedge ~1.5, got {yx.hedge_ratio}"
            )
        else:
            assert yx.hedge_ratio == pytest.approx(1.0 / 1.5, abs=0.2), (
                f"Expected hedge ~{1/1.5:.3f}, got {yx.hedge_ratio}"
            )

    def test_method_label(self) -> None:
        rng = _make_rng(24)
        results = self._run_coint(rng)
        for r in results:
            assert r.method == "engle_granger"

    def test_pvalue_adj_is_not_nan(self) -> None:
        rng = _make_rng(25)
        results = self._run_coint(rng)
        for r in results:
            assert np.isfinite(r.pvalue_adj)

    def test_sorted_ascending_by_score(self) -> None:
        rng = _make_rng(26)
        results = self._run_coint(rng)
        scores = [r.score for r in results]
        assert scores == sorted(scores)

    def test_max_half_life_filter_drops_slow_reverting(self) -> None:
        """A spread with a very short max_half_life should exclude pairs that
        revert too slowly."""
        rng = _make_rng(27)
        # With max_half_life=0.1, no pair should pass the half-life filter.
        results = self._run_coint(rng, max_half_life=0.1)
        assert results == [], "Expected no pairs with max_half_life=0.1"

    def test_sector_filter(self) -> None:
        rng = _make_rng(28)
        prices = _make_cointegrated_frame(rng)
        sectors = {"y": "tech", "x": "finance", "z": "tech"}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            results = select_pairs_cointegration(
                prices,
                sectors=sectors,
                require_same_sector=True,
                min_obs=60,
            )
        # (y, x) cross-sector should be excluded regardless of cointegration.
        for r in results:
            assert not (r.symbol_y in {"y", "x"} and r.symbol_x in {"y", "x"}), (
                "Cross-sector pair (y,x) should have been excluded"
            )

    def test_volume_filter(self) -> None:
        rng = _make_rng(29)
        prices = _make_cointegrated_frame(rng)
        dates = prices.index
        # Give x near-zero volume so it is dropped.
        volume = pd.DataFrame(
            {
                "y": np.full(len(dates), 1_000_000.0),
                "x": np.full(len(dates), 1.0),
                "z": np.full(len(dates), 1_000_000.0),
            },
            index=dates,
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            results = select_pairs_cointegration(
                prices, volume=volume, min_avg_volume=1000.0, min_obs=60
            )
        for r in results:
            assert r.symbol_y != "x" and r.symbol_x != "x"

    def test_empty_prices_returns_empty(self) -> None:
        prices = pd.DataFrame(
            {"a": [1.0, 2.0, 3.0]},
            index=pd.date_range("2020-01-01", periods=3, freq="B"),
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            results = select_pairs_cointegration(prices, min_obs=2)
        # Only one symbol, no pairs.
        assert results == []

    def test_holm_and_fdr_bh_corrections_run(self) -> None:
        rng = _make_rng(30)
        prices = _make_cointegrated_frame(rng)
        for method in ("holm", "fdr_bh"):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                results = select_pairs_cointegration(
                    prices, correction=method, min_obs=60
                )
            assert isinstance(results, list)

    def test_min_obs_skips_short_pairs(self) -> None:
        rng = _make_rng(31)
        short = pd.DataFrame(
            {
                "a": _random_walk(rng, 30),
                "b": _random_walk(rng, 30),
            },
            index=pd.date_range("2020-01-01", periods=30, freq="B"),
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            results = select_pairs_cointegration(short, min_obs=60)
        assert results == []


# ---------------------------------------------------------------------------
# select_pairs_johansen
# ---------------------------------------------------------------------------


class TestSelectPairsJohansen:
    def _run_johansen(
        self,
        rng: np.random.Generator,
        n: int = N,
        hedge: float = 1.5,
        max_half_life: float = 30.0,
    ) -> list[PairCandidate]:
        prices = _make_cointegrated_frame(rng, hedge=hedge, n=n)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return select_pairs_johansen(prices, max_half_life=max_half_life, min_obs=60)

    def test_recovers_cointegrated_pair(self) -> None:
        rng = _make_rng(40)
        results = self._run_johansen(rng)
        pairs = [{r.symbol_y, r.symbol_x} for r in results]
        assert {"y", "x"} in pairs, f"(y,x) not found; got: {pairs}"

    def test_method_label(self) -> None:
        rng = _make_rng(41)
        results = self._run_johansen(rng)
        for r in results:
            assert r.method == "johansen"

    def test_pvalue_is_nan(self) -> None:
        rng = _make_rng(42)
        results = self._run_johansen(rng)
        for r in results:
            assert np.isnan(r.pvalue)
            assert np.isnan(r.pvalue_adj)

    def test_sorted_ascending_by_half_life(self) -> None:
        rng = _make_rng(43)
        results = self._run_johansen(rng)
        half_lives = [r.half_life for r in results]
        assert half_lives == sorted(half_lives)

    def test_score_equals_half_life(self) -> None:
        rng = _make_rng(44)
        results = self._run_johansen(rng)
        for r in results:
            assert r.score == r.half_life

    def test_max_half_life_filter(self) -> None:
        rng = _make_rng(45)
        results = self._run_johansen(rng, max_half_life=0.1)
        assert results == [], "Expected no pairs with max_half_life=0.1"

    def test_sector_filter(self) -> None:
        rng = _make_rng(46)
        prices = _make_cointegrated_frame(rng)
        sectors = {"y": "tech", "x": "finance", "z": "tech"}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            results = select_pairs_johansen(
                prices,
                sectors=sectors,
                require_same_sector=True,
                min_obs=60,
            )
        for r in results:
            assert not (r.symbol_y in {"y", "x"} and r.symbol_x in {"y", "x"})

    def test_min_obs_skips_short_pairs(self) -> None:
        rng = _make_rng(47)
        short = pd.DataFrame(
            {
                "a": _random_walk(rng, 30),
                "b": _random_walk(rng, 30),
            },
            index=pd.date_range("2020-01-01", periods=30, freq="B"),
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            results = select_pairs_johansen(short, min_obs=60)
        assert results == []

    def test_hedge_ratio_finite(self) -> None:
        rng = _make_rng(48)
        results = self._run_johansen(rng)
        for r in results:
            assert np.isfinite(r.hedge_ratio)


# ---------------------------------------------------------------------------
# select_pairs_copula
# ---------------------------------------------------------------------------


class TestSelectPairsCopula:
    def test_correlated_pair_ranked_first(self) -> None:
        """A nearly identical pair should score better than an unrelated pair."""
        rng = _make_rng(60)
        prices = _make_distance_frame(rng, n=N)
        results = select_pairs_copula(prices, top_n=3, min_obs=50)
        assert results, "No pairs returned by copula selector"
        first = {results[0].symbol_y, results[0].symbol_x}
        assert first == {"a", "b"}, f"Expected (a,b) first, got {first}"

    def test_top_n_respected(self) -> None:
        rng = _make_rng(61)
        prices = _make_distance_frame(rng)
        results = select_pairs_copula(prices, top_n=2)
        assert len(results) <= 2

    def test_sorted_ascending(self) -> None:
        rng = _make_rng(62)
        prices = _make_distance_frame(rng)
        results = select_pairs_copula(prices, top_n=5)
        scores = [r.score for r in results]
        assert scores == sorted(scores)

    def test_score_in_zero_one(self) -> None:
        rng = _make_rng(63)
        prices = _make_distance_frame(rng)
        results = select_pairs_copula(prices)
        for r in results:
            assert 0.0 <= r.score <= 1.0

    def test_method_label(self) -> None:
        rng = _make_rng(64)
        prices = _make_distance_frame(rng)
        results = select_pairs_copula(prices, top_n=1)
        assert results[0].method == "copula"

    def test_pvalue_is_nan(self) -> None:
        rng = _make_rng(65)
        prices = _make_distance_frame(rng)
        results = select_pairs_copula(prices, top_n=1)
        assert np.isnan(results[0].pvalue)
        assert np.isnan(results[0].pvalue_adj)

    def test_sector_filter(self) -> None:
        rng = _make_rng(66)
        prices = _make_distance_frame(rng)
        sectors = {"a": "tech", "b": "finance", "c": "tech"}
        results = select_pairs_copula(
            prices, top_n=10, sectors=sectors, require_same_sector=True
        )
        # Only (a, c) share sector "tech".
        for r in results:
            assert r.symbol_y in {"a", "c"} and r.symbol_x in {"a", "c"}

    def test_min_obs_skips_short_pairs(self) -> None:
        rng = _make_rng(67)
        short = pd.DataFrame(
            {
                "a": _random_walk(rng, 30),
                "b": _random_walk(rng, 30),
            },
            index=pd.date_range("2020-01-01", periods=30, freq="B"),
        )
        results = select_pairs_copula(short, min_obs=60)
        assert results == []

    def test_hedge_ratio_finite(self) -> None:
        rng = _make_rng(68)
        prices = _make_distance_frame(rng)
        results = select_pairs_copula(prices, top_n=3)
        for r in results:
            assert np.isfinite(r.hedge_ratio)

    def test_uncorrelated_pairs_have_high_score(self) -> None:
        """Completely uncorrelated pairs should have score close to 1."""
        rng = _make_rng(69)
        # Use a geometric (log-normal) random walk so prices stay strictly positive,
        # avoiding log(<=0) RuntimeWarning under -W error.
        n = N
        dates = pd.date_range("2020-01-01", periods=n, freq="B")
        log_ret_a = rng.normal(0.0, 0.01, size=n)
        log_ret_b = rng.normal(0.0, 0.01, size=n)
        a = 100.0 * np.exp(np.cumsum(log_ret_a))
        b = 50.0 * np.exp(np.cumsum(log_ret_b))
        prices = pd.DataFrame({"a": a, "b": b}, index=dates)
        results = select_pairs_copula(prices, top_n=1, min_obs=50)
        # For independent series, rho ~ 0, score ~ 1.0.
        if results:
            assert results[0].score > 0.5
