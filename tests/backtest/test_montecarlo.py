"""Tests for core_trading.backtest.montecarlo."""
from __future__ import annotations

import numpy as np
import pytest

from core_trading.backtest.montecarlo import (
    block_bootstrap_paths,
    gaussian_paths,
    iid_bootstrap_paths,
    monte_carlo_analysis,
)


@pytest.fixture
def returns() -> np.ndarray:
    rng = np.random.default_rng(5)
    return rng.normal(0.0005, 0.01, 500)


class TestPathGenerators:
    def test_iid_shape_and_membership(self, returns: np.ndarray) -> None:
        rng = np.random.default_rng(0)
        paths = iid_bootstrap_paths(returns, 50, rng)
        assert paths.shape == (50, returns.size)
        assert set(np.unique(paths)).issubset(set(returns.tolist()))

    def test_block_shape(self, returns: np.ndarray) -> None:
        rng = np.random.default_rng(0)
        paths = block_bootstrap_paths(returns, 30, block_size=20, rng=rng)
        assert paths.shape == (30, returns.size)

    def test_block_size_one(self, returns: np.ndarray) -> None:
        rng = np.random.default_rng(0)
        paths = block_bootstrap_paths(returns, 10, block_size=1, rng=rng)
        assert paths.shape == (10, returns.size)

    def test_block_bad_size(self, returns: np.ndarray) -> None:
        with pytest.raises(ValueError):
            block_bootstrap_paths(returns, 10, block_size=0, rng=np.random.default_rng(0))

    def test_gaussian_shape(self, returns: np.ndarray) -> None:
        rng = np.random.default_rng(0)
        paths = gaussian_paths(returns, 25, rng)
        assert paths.shape == (25, returns.size)


class TestAnalysis:
    def test_block_summary_keys(self, returns: np.ndarray) -> None:
        res = monte_carlo_analysis(returns, n_sims=300, method="block", seed=1)
        s = res.summary()
        for k in (
            "median_terminal_wealth",
            "p05_terminal_wealth",
            "p95_terminal_wealth",
            "median_max_drawdown",
            "median_sharpe",
            "probability_of_loss",
        ):
            assert k in s
        assert res.terminal_wealth.shape == (300,)

    def test_methods_run(self, returns: np.ndarray) -> None:
        for method in ("iid", "block", "gaussian"):
            res = monte_carlo_analysis(returns, n_sims=100, method=method, seed=2)
            assert res.method == method
            assert res.sharpe.shape == (100,)

    def test_positive_drift_grows_wealth(self) -> None:
        rng = np.random.default_rng(7)
        good = rng.normal(0.002, 0.005, 500)
        res = monte_carlo_analysis(good, n_sims=500, method="iid", seed=3)
        assert res.summary()["median_terminal_wealth"] > 1.0
        assert res.probability_of_loss() < 0.5

    def test_percentiles_monotone(self, returns: np.ndarray) -> None:
        res = monte_carlo_analysis(returns, n_sims=400, method="block", seed=4)
        pct = res.percentiles("terminal_wealth", (5, 50, 95))
        assert pct[5] <= pct[50] <= pct[95]

    def test_deterministic_with_seed(self, returns: np.ndarray) -> None:
        a = monte_carlo_analysis(returns, n_sims=100, method="block", seed=9)
        b = monte_carlo_analysis(returns, n_sims=100, method="block", seed=9)
        np.testing.assert_array_equal(a.terminal_wealth, b.terminal_wealth)

    def test_too_few_returns(self) -> None:
        with pytest.raises(ValueError, match="at least 2"):
            monte_carlo_analysis([0.01], n_sims=10)

    def test_bad_method(self, returns: np.ndarray) -> None:
        with pytest.raises(ValueError, match="unknown method"):
            monte_carlo_analysis(returns, method="magic")

    def test_bad_n_sims(self, returns: np.ndarray) -> None:
        with pytest.raises(ValueError, match="n_sims"):
            monte_carlo_analysis(returns, n_sims=0)
