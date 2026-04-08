"""Tests for scenario/stress-test engine."""

import math

import numpy as np
import pytest

from core_trading.analytics.scenario_engine import (
    Portfolio,
    Position,
    ScenarioEngine,
    ScenarioShock,
    ScenarioType,
    StressTestResult,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_portfolio():
    return Portfolio(
        positions={
            "SPY": Position(symbol="SPY", quantity=100, current_price=450.0, avg_cost=440.0),
            "QQQ": Position(symbol="QQQ", quantity=50, current_price=380.0, avg_cost=370.0),
        },
        cash=10000.0,
    )


@pytest.fixture
def engine():
    return ScenarioEngine(default_correlation=0.5)


@pytest.fixture(autouse=True)
def set_seed():
    np.random.seed(42)


# ---------------------------------------------------------------------------
# Position & Portfolio Tests
# ---------------------------------------------------------------------------


class TestPositionAndPortfolio:
    def test_position_market_value(self):
        pos = Position(symbol="AAPL", quantity=100, current_price=150.0, avg_cost=140.0)
        assert pos.market_value == 15000.0

    def test_position_unrealized_pnl_long(self):
        pos = Position(symbol="AAPL", quantity=100, current_price=150.0, avg_cost=140.0)
        assert pos.unrealized_pnl == 1000.0

    def test_position_unrealized_pnl_short(self):
        pos = Position(symbol="AAPL", quantity=-100, current_price=150.0, avg_cost=140.0)
        assert pos.unrealized_pnl == -1000.0

    def test_portfolio_total_value(self):
        portfolio = Portfolio(
            positions={
                "AAPL": Position(symbol="AAPL", quantity=100, current_price=150.0, avg_cost=140.0),
            },
            cash=5000.0,
        )
        assert portfolio.total_value == 20000.0

    def test_portfolio_total_value_with_cash(self, sample_portfolio):
        expected = 10000.0 + 100 * 450.0 + 50 * 380.0
        assert sample_portfolio.total_value == expected

    def test_portfolio_empty(self):
        portfolio = Portfolio()
        assert portfolio.total_value == 0.0
        assert portfolio.total_unrealized_pnl == 0.0


# ---------------------------------------------------------------------------
# ScenarioEngine Tests
# ---------------------------------------------------------------------------


class TestScenarioEngine:
    def test_initialization(self):
        engine = ScenarioEngine(default_correlation=0.7)
        assert engine._default_correlation == 0.7

    def test_get_predefined_scenarios(self, engine):
        scenarios = engine.get_predefined_scenarios()
        assert "2008_financial_crisis" in scenarios
        assert "covid_crash_2020" in scenarios
        assert "flash_crash" in scenarios
        assert len(scenarios) == 5

    @pytest.mark.asyncio
    async def test_run_scenario_2008_crisis(self, engine, sample_portfolio):
        result = await engine.run_scenario("2008_financial_crisis", sample_portfolio)
        assert result.scenario_name == "2008_financial_crisis"
        assert result.scenario_type == ScenarioType.PREDEFINED
        assert result.portfolio_value_before == sample_portfolio.total_value
        assert result.portfolio_pnl < 0  # crisis means losses
        assert "SPY" in result.position_results
        assert result.position_results["SPY"] < 0

    @pytest.mark.asyncio
    async def test_run_scenario_covid_crash(self, engine, sample_portfolio):
        result = await engine.run_scenario("covid_crash_2020", sample_portfolio)
        assert result.portfolio_pnl < 0
        assert result.portfolio_value_after < result.portfolio_value_before

    @pytest.mark.asyncio
    async def test_run_scenario_flash_crash(self, engine, sample_portfolio):
        result = await engine.run_scenario("flash_crash", sample_portfolio)
        assert result.portfolio_pnl < 0

    @pytest.mark.asyncio
    async def test_run_scenario_unknown_raises(self, engine, sample_portfolio):
        with pytest.raises(ValueError, match="Unknown scenario"):
            await engine.run_scenario("nonexistent_scenario", sample_portfolio)

    @pytest.mark.asyncio
    async def test_run_custom_scenario(self, engine, sample_portfolio):
        result = await engine.run_custom_scenario(
            {"SPY": -0.10, "QQQ": -0.15}, sample_portfolio,
        )
        assert result.scenario_type == ScenarioType.CUSTOM
        assert result.portfolio_pnl < 0
        assert result.position_results["SPY"] == pytest.approx(-4500.0)
        assert result.position_results["QQQ"] == pytest.approx(-2850.0)

    @pytest.mark.asyncio
    async def test_run_custom_scenario_multiple_shocks(self, engine):
        portfolio = Portfolio(
            positions={
                "AAPL": Position(symbol="AAPL", quantity=100, current_price=150.0, avg_cost=140.0),
                "MSFT": Position(symbol="MSFT", quantity=50, current_price=300.0, avg_cost=290.0),
            },
        )
        result = await engine.run_custom_scenario(
            {"AAPL": 0.10, "MSFT": -0.05}, portfolio,
        )
        assert result.position_results["AAPL"] > 0
        assert result.position_results["MSFT"] < 0

    @pytest.mark.asyncio
    async def test_run_custom_scenario_no_shock(self, engine, sample_portfolio):
        result = await engine.run_custom_scenario({}, sample_portfolio)
        assert result.portfolio_pnl == 0.0

    @pytest.mark.asyncio
    async def test_run_monte_carlo_basic(self, engine, sample_portfolio):
        result = await engine.run_monte_carlo_stress(sample_portfolio, n_simulations=1000)
        assert result.scenario_type == ScenarioType.MONTE_CARLO
        assert result.n_simulations == 1000
        assert result.portfolio_value_before == sample_portfolio.total_value

    @pytest.mark.asyncio
    async def test_run_monte_carlo_var_positive(self, engine, sample_portfolio):
        result = await engine.run_monte_carlo_stress(sample_portfolio, n_simulations=5000)
        # VaR should be negative (representing a loss)
        assert result.var_95 < 0
        assert result.var_99 < 0

    @pytest.mark.asyncio
    async def test_run_monte_carlo_var_99_worse_than_95(self, engine, sample_portfolio):
        result = await engine.run_monte_carlo_stress(sample_portfolio, n_simulations=5000)
        assert result.var_99 <= result.var_95

    @pytest.mark.asyncio
    async def test_run_monte_carlo_expected_shortfall(self, engine, sample_portfolio):
        result = await engine.run_monte_carlo_stress(sample_portfolio, n_simulations=5000)
        # ES should be worse than VaR
        assert result.expected_shortfall_95 <= result.var_95

    @pytest.mark.asyncio
    async def test_run_monte_carlo_empty_portfolio(self, engine):
        portfolio = Portfolio()
        result = await engine.run_monte_carlo_stress(portfolio)
        assert result.portfolio_value_before == 0.0

    @pytest.mark.asyncio
    async def test_run_monte_carlo_single_asset(self, engine):
        portfolio = Portfolio(
            positions={
                "AAPL": Position(symbol="AAPL", quantity=100, current_price=150.0, avg_cost=140.0),
            },
        )
        result = await engine.run_monte_carlo_stress(portfolio, n_simulations=1000)
        assert result.n_simulations == 1000
        assert "AAPL" in result.position_results

    @pytest.mark.asyncio
    async def test_run_monte_carlo_n_simulations(self, engine, sample_portfolio):
        result = await engine.run_monte_carlo_stress(sample_portfolio, n_simulations=500)
        assert result.n_simulations == 500

    def test_set_correlation(self, engine):
        engine.set_correlation("AAPL", "MSFT", 0.8)
        assert engine._correlation_matrix[("AAPL", "MSFT")] == 0.8

    def test_set_correlation_clamped(self, engine):
        engine.set_correlation("AAPL", "MSFT", 1.5)
        assert engine._correlation_matrix[("AAPL", "MSFT")] == 1.0
        engine.set_correlation("AAPL", "MSFT", -2.0)
        assert engine._correlation_matrix[("AAPL", "MSFT")] == -1.0

    @pytest.mark.asyncio
    async def test_apply_shocks_with_loss(self, engine):
        portfolio = Portfolio(
            positions={
                "AAPL": Position(symbol="AAPL", quantity=100, current_price=150.0, avg_cost=140.0),
            },
        )
        shocks = [ScenarioShock(symbol="AAPL", price_change_pct=-0.20)]
        result = engine._apply_shocks("test_loss", ScenarioType.CUSTOM, portfolio, shocks)
        assert result.portfolio_pnl < 0
        assert result.portfolio_pnl == pytest.approx(-3000.0)

    @pytest.mark.asyncio
    async def test_apply_shocks_with_gain(self, engine):
        portfolio = Portfolio(
            positions={
                "AAPL": Position(symbol="AAPL", quantity=100, current_price=150.0, avg_cost=140.0),
            },
        )
        shocks = [ScenarioShock(symbol="AAPL", price_change_pct=0.10)]
        result = engine._apply_shocks("test_gain", ScenarioType.CUSTOM, portfolio, shocks)
        assert result.portfolio_pnl > 0
        assert result.portfolio_pnl == pytest.approx(1500.0)

    @pytest.mark.asyncio
    async def test_stress_test_result_fields(self, engine, sample_portfolio):
        result = await engine.run_scenario("flash_crash", sample_portfolio)
        assert result.scenario_id  # non-empty
        assert result.timestamp
        assert isinstance(result.position_results, dict)
        assert isinstance(result.metadata, dict)

    @pytest.mark.asyncio
    async def test_portfolio_pnl_pct(self, engine):
        portfolio = Portfolio(
            positions={
                "AAPL": Position(symbol="AAPL", quantity=100, current_price=100.0, avg_cost=100.0),
            },
            cash=0.0,
        )
        result = await engine.run_custom_scenario({"AAPL": -0.50}, portfolio)
        assert result.portfolio_pnl_pct == pytest.approx(-50.0)
