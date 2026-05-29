"""Tests for core_trading.backtest.metrics, validated against analytic values."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core_trading.backtest import metrics as m
from core_trading.backtest.orders import Trade

TS = pd.Timestamp("2022-01-03", tz="UTC")


def _trade(pnl: float, direction: int = 1) -> Trade:
    return Trade("AAA", direction, 100, TS, TS, 10.0, 11.0, pnl=pnl)


class TestReturnsAndAggregates:
    def test_returns_from_equity(self) -> None:
        eq = pd.Series([100.0, 110.0, 99.0])
        r = m.returns_from_equity(eq)
        assert r.iloc[0] == pytest.approx(0.10)
        assert r.iloc[1] == pytest.approx(-0.10)

    def test_annualized_return_doubling(self) -> None:
        # 252 days each +x where prod=2 -> annualized ~ 2x-1 per year
        rets = np.full(252, 2 ** (1 / 252) - 1)
        assert m.annualized_return(rets, 252) == pytest.approx(1.0, rel=1e-6)

    def test_annualized_vol(self) -> None:
        rets = np.array([0.01, -0.01, 0.02, -0.02, 0.0])
        expected = np.std(rets, ddof=1) * np.sqrt(252)
        assert m.annualized_volatility(rets) == pytest.approx(expected)

    def test_cagr(self) -> None:
        eq = pd.Series(np.linspace(100, 200, 253))  # ~1 year
        assert m.cagr(eq, 252) > 0

    def test_empty_inputs(self) -> None:
        assert m.annualized_return([]) == 0.0
        assert m.annualized_volatility([0.0]) == 0.0
        assert m.cagr(pd.Series([100.0])) == 0.0

    def test_total_wipeout_returns(self) -> None:
        # a -100% return wipes the account: growth 0 -> annualised -1
        assert m.annualized_return(np.array([-1.0, 0.0])) == -1.0

    def test_cagr_wipeout(self) -> None:
        assert m.cagr(pd.Series([100.0, 0.0])) == -1.0


class TestRatios:
    def test_sharpe_zero_variance(self) -> None:
        assert m.sharpe_ratio(np.full(10, 0.01)) == 0.0

    def test_sharpe_sign(self) -> None:
        rng = np.random.default_rng(0)
        good = rng.normal(0.002, 0.005, 500)
        assert m.sharpe_ratio(good) > 0

    def test_sharpe_analytic(self) -> None:
        rets = np.array([0.01, 0.02, 0.0, 0.01, -0.01])
        expected = np.mean(rets) / np.std(rets, ddof=1) * np.sqrt(252)
        assert m.sharpe_ratio(rets) == pytest.approx(expected)

    def test_sortino_only_downside(self) -> None:
        rets = np.array([0.01, 0.02, -0.01, 0.03, -0.02])
        downside = rets[rets < 0]
        dd = np.sqrt(np.mean(downside**2))
        expected = np.mean(rets) / dd * np.sqrt(252)
        assert m.sortino_ratio(rets) == pytest.approx(expected)

    def test_sortino_no_downside(self) -> None:
        assert m.sortino_ratio(np.array([0.01, 0.02, 0.03])) == 0.0

    def test_sortino_too_short(self) -> None:
        assert m.sortino_ratio(np.array([0.01])) == 0.0

    def test_sortino_negligible_downside(self) -> None:
        # a downside that is floating-point noise yields 0, not a huge ratio
        assert m.sortino_ratio(np.array([0.01, 0.02, -1e-14])) == 0.0


class TestEmptyEdges:
    def test_var_cvar_empty(self) -> None:
        assert m.value_at_risk(np.array([])) == 0.0
        assert m.conditional_value_at_risk(np.array([])) == 0.0

    def test_ulcer_empty(self) -> None:
        assert m.ulcer_index(pd.Series(dtype=float)) == 0.0

    def test_omega_empty(self) -> None:
        assert m.omega_ratio(np.array([])) == 0.0

    def test_tail_empty(self) -> None:
        assert m.tail_ratio(np.array([])) == 0.0

    def test_max_drawdown_empty(self) -> None:
        assert m.max_drawdown(pd.Series(dtype=float)) == 0.0

    def test_omega_no_gains_zero(self) -> None:
        assert m.omega_ratio(np.array([-0.01, -0.02]), 0.0) == 0.0

    def test_tail_no_left_infinite(self) -> None:
        assert m.tail_ratio(np.array([0.0, 0.0, 0.05])) == float("inf")


class TestDrawdown:
    def test_max_drawdown_known(self) -> None:
        eq = pd.Series([100.0, 120.0, 90.0, 110.0])
        # peak 120 -> trough 90 = 25% drawdown
        assert m.max_drawdown(eq) == pytest.approx(0.25)

    def test_drawdown_series_nonpositive(self) -> None:
        eq = pd.Series([100.0, 110.0, 105.0])
        dd = m.drawdown_series(eq)
        assert (dd <= 1e-12).all()

    def test_calmar(self) -> None:
        eq = pd.Series(np.linspace(100, 150, 253))
        # monotone up -> zero drawdown -> calmar 0 by guard
        assert m.calmar_ratio(eq) == 0.0

    def test_mar_equals_calmar(self) -> None:
        eq = pd.Series([100.0, 120.0, 90.0, 130.0])
        assert m.mar_ratio(eq) == pytest.approx(m.calmar_ratio(eq))

    def test_ulcer_index(self) -> None:
        eq = pd.Series([100.0, 90.0, 100.0])
        assert m.ulcer_index(eq) > 0


class TestTailRisk:
    def test_var_positive_loss(self) -> None:
        rng = np.random.default_rng(1)
        rets = rng.normal(0, 0.01, 10000)
        var = m.value_at_risk(rets, 0.05)
        assert var == pytest.approx(0.01 * 1.645, rel=0.1)

    def test_cvar_worse_than_var(self) -> None:
        rng = np.random.default_rng(2)
        rets = rng.normal(0, 0.01, 10000)
        assert m.conditional_value_at_risk(rets, 0.05) > m.value_at_risk(rets, 0.05)

    def test_var_bad_alpha(self) -> None:
        with pytest.raises(ValueError):
            m.value_at_risk([0.01], 1.5)
        with pytest.raises(ValueError):
            m.conditional_value_at_risk([0.01], 0.0)

    def test_omega_above_one_for_positive_drift(self) -> None:
        rng = np.random.default_rng(3)
        rets = rng.normal(0.001, 0.01, 5000)
        assert m.omega_ratio(rets, 0.0) > 1.0

    def test_omega_no_losses_infinite(self) -> None:
        assert m.omega_ratio(np.array([0.01, 0.02]), 0.0) == float("inf")

    def test_tail_ratio(self) -> None:
        rets = np.array([-0.05, -0.01, 0.0, 0.01, 0.05])
        assert m.tail_ratio(rets) > 0


class TestTradeMetrics:
    def test_profit_factor(self) -> None:
        trades = [_trade(100), _trade(50), _trade(-30)]
        assert m.profit_factor(trades) == pytest.approx(150 / 30)

    def test_profit_factor_no_losses(self) -> None:
        assert m.profit_factor([_trade(100)]) == float("inf")

    def test_profit_factor_empty(self) -> None:
        assert m.profit_factor([]) == 0.0

    def test_win_rate(self) -> None:
        trades = [_trade(10), _trade(-5), _trade(20), _trade(-1)]
        assert m.win_rate(trades) == pytest.approx(0.5)

    def test_average_win_loss(self) -> None:
        avg_win, avg_loss = m.average_win_loss([_trade(10), _trade(20), _trade(-6)])
        assert avg_win == pytest.approx(15.0)
        assert avg_loss == pytest.approx(-6.0)

    def test_expectancy(self) -> None:
        assert m.expectancy([_trade(10), _trade(-4)]) == pytest.approx(3.0)

    def test_empty_trade_metrics(self) -> None:
        assert m.win_rate([]) == 0.0
        assert m.expectancy([]) == 0.0
        assert m.average_win_loss([]) == (0.0, 0.0)


class TestComputeMetrics:
    def test_full_summary(self) -> None:
        eq = pd.Series(
            [100.0, 105.0, 102.0, 110.0, 108.0],
            index=pd.date_range("2022-01-03", periods=5, freq="B", tz="UTC"),
        )
        trades = [_trade(10), _trade(-5)]
        out = m.compute_metrics(eq, trades, turnover=2.5)
        assert out.n_trades == 2
        assert out.total_return == pytest.approx(0.08)
        assert out.turnover == pytest.approx(2.5)
        assert out.max_drawdown >= 0
        d = out.to_dict()
        assert d["n_trades"] == 2.0
        assert "sharpe" in d

    def test_degenerate_equity(self) -> None:
        out = m.compute_metrics(pd.Series([100.0]))
        assert out.total_return == 0.0
        assert out.sharpe == 0.0

    def test_extra_merged_into_dict(self) -> None:
        pm = m.PerformanceMetrics(extra={"custom": 1.23})
        assert pm.to_dict()["custom"] == 1.23
