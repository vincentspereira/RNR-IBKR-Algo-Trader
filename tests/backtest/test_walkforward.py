"""Tests for core_trading.backtest.walkforward."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from core_trading.backtest.engine import BacktestConfig, Strategy, WeightStrategy
from core_trading.backtest.walkforward import cpcv_sharpe_distribution, walk_forward


def _sma_weights(prices: pd.DataFrame, window: int) -> pd.DataFrame:
    """Long when close > rolling SMA, else flat. Look-ahead-free."""
    close = prices["close"].unstack("symbol").sort_index()
    sma = close.rolling(window, min_periods=1).mean()
    signal = (close > sma).astype(float)
    return signal / max(signal.shape[1], 1)


def _build_strategy(params: dict[str, object]) -> Strategy:
    window = int(params["window"])  # type: ignore[call-overload]

    class _S:
        def generate_weights(self, prices: pd.DataFrame) -> pd.DataFrame:
            return _sma_weights(prices, window)

    return _S()


_CFG = BacktestConfig(cost_model_name="zero", max_participation_rate=1.0)
_GRID = [{"window": 5}, {"window": 20}, {"window": 60}]


class TestWalkForward:
    def test_returns_folds(self, panel: pd.DataFrame) -> None:
        res = walk_forward(panel, _build_strategy, _GRID, n_splits=4, config=_CFG)
        assert len(res.folds) == 4
        for f in res.folds:
            assert f.best_params["window"] in (5, 20, 60)
            assert f.n_train > 0
            assert f.n_test > 0

    def test_parameter_stability_bounds(self, panel: pd.DataFrame) -> None:
        res = walk_forward(panel, _build_strategy, _GRID, n_splits=4, config=_CFG)
        for v in res.parameter_stability.values():
            assert 0.0 < v <= 1.0

    def test_oos_equity_concatenated(self, panel: pd.DataFrame) -> None:
        res = walk_forward(panel, _build_strategy, _GRID, n_splits=4, config=_CFG)
        assert not res.oos_equity.empty
        assert res.oos_equity.index.is_monotonic_increasing

    def test_mean_and_degradation_defined(self, panel: pd.DataFrame) -> None:
        res = walk_forward(panel, _build_strategy, _GRID, n_splits=3, config=_CFG)
        assert isinstance(res.mean_test_sharpe, float)
        assert isinstance(res.degradation, float)

    def test_rolling_window(self, panel: pd.DataFrame) -> None:
        res = walk_forward(
            panel,
            _build_strategy,
            _GRID,
            n_splits=3,
            train_size=60,
            anchored=False,
            config=_CFG,
        )
        assert len(res.folds) == 3

    def test_single_param_always_chosen(self, panel: pd.DataFrame) -> None:
        res = walk_forward(panel, _build_strategy, [{"window": 10}], n_splits=3, config=_CFG)
        assert all(f.best_params["window"] == 10 for f in res.folds)
        assert res.parameter_stability["window"] == pytest.approx(1.0)

    def test_empty_grid_raises(self, panel: pd.DataFrame) -> None:
        with pytest.raises(ValueError, match="param_grid"):
            walk_forward(panel, _build_strategy, [], config=_CFG)

    def test_empty_result_helpers(self) -> None:
        from core_trading.backtest.walkforward import WalkForwardResult

        empty = WalkForwardResult()
        assert empty.mean_test_sharpe == 0.0
        assert empty.degradation == 0.0

    def test_parameter_stability_empty(self) -> None:
        from core_trading.backtest.walkforward import _parameter_stability

        assert _parameter_stability([]) == {}


class TestCpcv:
    def test_distribution_length(self, panel: pd.DataFrame) -> None:
        strat = WeightStrategy(_sma_weights(panel, 20))
        dist = cpcv_sharpe_distribution(panel, strat, n_groups=6, n_test_groups=2, config=_CFG)
        # one Sharpe per combination C(6, 2) = 15
        assert dist.shape == (math.comb(6, 2),)
        assert np.all(np.isfinite(dist))

    def test_distribution_has_spread(self, panel: pd.DataFrame) -> None:
        strat = WeightStrategy(_sma_weights(panel, 10))
        dist = cpcv_sharpe_distribution(panel, strat, n_groups=5, n_test_groups=2, config=_CFG)
        assert dist.shape == (math.comb(5, 2),)
        # a genuine distribution, not a constant
        assert dist.std() > 0
