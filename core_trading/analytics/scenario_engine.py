"""Scenario and Stress-Test Engine for portfolio risk analysis.

Provides predefined historical scenarios, custom shock scenarios,
and Monte Carlo stress testing with correlated asset moves.
"""

import logging
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


class ScenarioType(Enum):
    PREDEFINED = "predefined"
    CUSTOM = "custom"
    MONTE_CARLO = "monte_carlo"


@dataclass
class Position:
    """Simple position for scenario testing."""
    symbol: str
    quantity: float
    current_price: float
    avg_cost: float
    position_type: str = "equity"

    @property
    def market_value(self) -> float:
        return self.quantity * self.current_price

    @property
    def unrealized_pnl(self) -> float:
        return (self.current_price - self.avg_cost) * self.quantity


@dataclass
class Portfolio:
    """Simple portfolio for scenario testing."""
    positions: Dict[str, Position] = field(default_factory=dict)
    cash: float = 0.0

    @property
    def total_value(self) -> float:
        return self.cash + sum(p.market_value for p in self.positions.values())

    @property
    def total_unrealized_pnl(self) -> float:
        return sum(p.unrealized_pnl for p in self.positions.values())


@dataclass
class ScenarioShock:
    """A single shock applied to a portfolio."""
    symbol: str
    price_change_pct: float
    volatility_change: float = 0.0
    correlation_change: float = 0.0


@dataclass
class StressTestResult:
    """Result of a stress test scenario."""
    scenario_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    scenario_name: str = ""
    scenario_type: ScenarioType = ScenarioType.PREDEFINED
    portfolio_value_before: float = 0.0
    portfolio_value_after: float = 0.0
    portfolio_pnl: float = 0.0
    portfolio_pnl_pct: float = 0.0
    position_results: Dict[str, float] = field(default_factory=dict)
    max_loss_symbol: str = ""
    max_loss_amount: float = 0.0
    n_simulations: int = 1
    var_95: float = 0.0
    var_99: float = 0.0
    expected_shortfall_95: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)


class ScenarioEngine:
    """What-if analysis with custom stress test scenarios."""

    PREDEFINED_SCENARIOS = {
        "2008_financial_crisis": {
            "description": "2008 Financial Crisis - S&P 500 dropped 37%",
            "shocks": {"SPY": -0.37, "QQQ": -0.42, "XLF": -0.55, "IWM": -0.40},
            "vol_spike": 3.5,
            "correlation": 0.95,
        },
        "covid_crash_2020": {
            "description": "COVID-19 Crash - S&P 500 dropped 34%",
            "shocks": {"SPY": -0.34, "QQQ": -0.30, "XLF": -0.35, "IWM": -0.38},
            "vol_spike": 4.0,
            "correlation": 0.90,
        },
        "flash_crash": {
            "description": "Flash Crash - S&P 500 dropped 9% in 36 minutes",
            "shocks": {"SPY": -0.09, "QQQ": -0.10, "IWM": -0.12},
            "vol_spike": 2.0,
            "correlation": 0.98,
        },
        "interest_rate_shock": {
            "description": "200bps interest rate increase",
            "shocks": {"TLT": -0.15, "SPY": -0.05, "XLF": 0.08},
            "vol_spike": 1.5,
            "correlation": 0.70,
        },
        "sector_rotation": {
            "description": "Tech drops 20%, Value rises 15%",
            "shocks": {"QQQ": -0.20, "XLF": 0.15, "SPY": -0.05},
            "vol_spike": 1.2,
            "correlation": 0.60,
        },
    }

    def __init__(self, event_bus=None, default_correlation: float = 0.5):
        self._event_bus = event_bus
        self._default_correlation = default_correlation
        self._correlation_matrix: Dict[Tuple[str, str], float] = {}
        self._logger = logging.getLogger(__name__)

    async def run_scenario(self, scenario_name: str, portfolio: Portfolio) -> StressTestResult:
        """Apply a predefined scenario to the portfolio."""
        if scenario_name not in self.PREDEFINED_SCENARIOS:
            raise ValueError(f"Unknown scenario: {scenario_name}")

        scenario = self.PREDEFINED_SCENARIOS[scenario_name]
        shocks = [
            ScenarioShock(
                symbol=sym,
                price_change_pct=pct,
                volatility_change=scenario.get("vol_spike", 0.0),
                correlation_change=scenario.get("correlation", 0.0),
            )
            for sym, pct in scenario["shocks"].items()
        ]
        return self._apply_shocks(
            scenario_name, ScenarioType.PREDEFINED, portfolio, shocks,
            metadata={"description": scenario.get("description", "")},
        )

    async def run_custom_scenario(
        self, shocks: Dict[str, float], portfolio: Portfolio,
        scenario_name: str = "custom",
    ) -> StressTestResult:
        """Apply custom shocks (symbol -> pct_change) to portfolio."""
        shock_list = [
            ScenarioShock(symbol=sym, price_change_pct=pct)
            for sym, pct in shocks.items()
        ]
        return self._apply_shocks(scenario_name, ScenarioType.CUSTOM, portfolio, shock_list)

    async def run_monte_carlo_stress(
        self,
        portfolio: Portfolio,
        n_simulations: int = 10000,
        confidence_level: float = 0.95,
        time_horizon_days: int = 1,
        annual_volatility: float = 0.20,
    ) -> StressTestResult:
        """Monte Carlo stress test with correlated asset moves."""
        symbols = list(portfolio.positions.keys())
        n_assets = len(symbols)
        value_before = portfolio.total_value

        if n_assets == 0:
            return StressTestResult(
                scenario_name="monte_carlo",
                scenario_type=ScenarioType.MONTE_CARLO,
                portfolio_value_before=value_before,
                portfolio_value_after=value_before,
                n_simulations=n_simulations,
            )

        corr_matrix = self._build_correlation_matrix(symbols)
        daily_vol = annual_volatility / math.sqrt(252) * math.sqrt(time_horizon_days)

        try:
            L = np.linalg.cholesky(corr_matrix)
        except np.linalg.LinAlgError:
            L = np.eye(n_assets)

        Z = np.random.standard_normal((n_simulations, n_assets))
        correlated_Z = Z @ L.T
        returns = daily_vol * correlated_Z

        weights = np.array([
            portfolio.positions[s].market_value / value_before if value_before > 0 else 0.0
            for s in symbols
        ])

        portfolio_returns = returns @ weights
        portfolio_pnl = portfolio_returns * value_before

        sorted_pnl = np.sort(portfolio_pnl)
        n = len(sorted_pnl)
        idx_95 = max(0, int(n * 0.05))
        idx_99 = max(0, int(n * 0.01))
        var_95 = float(sorted_pnl[idx_95])
        var_99 = float(sorted_pnl[idx_99])
        es_95 = float(np.mean(sorted_pnl[:idx_95])) if idx_95 > 0 else var_95

        worst_idx = int(np.argmin(portfolio_pnl))
        worst_returns = returns[worst_idx]

        position_results = {}
        max_loss_amount = 0.0
        max_loss_symbol = ""
        for i, sym in enumerate(symbols):
            pos = portfolio.positions[sym]
            pos_pnl = worst_returns[i] * pos.market_value
            position_results[sym] = pos_pnl
            if pos_pnl < max_loss_amount:
                max_loss_amount = pos_pnl
                max_loss_symbol = sym

        worst_pnl = float(portfolio_pnl[worst_idx])

        return StressTestResult(
            scenario_name="monte_carlo",
            scenario_type=ScenarioType.MONTE_CARLO,
            portfolio_value_before=value_before,
            portfolio_value_after=value_before + worst_pnl,
            portfolio_pnl=worst_pnl,
            portfolio_pnl_pct=(worst_pnl / value_before * 100) if value_before > 0 else 0.0,
            position_results=position_results,
            max_loss_symbol=max_loss_symbol,
            max_loss_amount=max_loss_amount,
            n_simulations=n_simulations,
            var_95=var_95,
            var_99=var_99,
            expected_shortfall_95=es_95,
            metadata={
                "time_horizon_days": time_horizon_days,
                "annual_volatility": annual_volatility,
            },
        )

    def _apply_shocks(
        self,
        name: str,
        stype: ScenarioType,
        portfolio: Portfolio,
        shocks: List[ScenarioShock],
        metadata: Optional[Dict] = None,
    ) -> StressTestResult:
        """Apply a list of shocks to a portfolio and compute results."""
        value_before = portfolio.total_value
        total_pnl = 0.0
        position_results: Dict[str, float] = {}
        max_loss_amount = 0.0
        max_loss_symbol = ""

        shock_lookup = {s.symbol: s for s in shocks}

        for sym, pos in portfolio.positions.items():
            shock = shock_lookup.get(sym)
            if shock:
                shocked_price = pos.current_price * (1.0 + shock.price_change_pct)
                pos_pnl = (shocked_price - pos.current_price) * pos.quantity
            else:
                pos_pnl = 0.0

            position_results[sym] = pos_pnl
            total_pnl += pos_pnl
            if pos_pnl < max_loss_amount:
                max_loss_amount = pos_pnl
                max_loss_symbol = sym

        value_after = value_before + total_pnl

        return StressTestResult(
            scenario_name=name,
            scenario_type=stype,
            portfolio_value_before=value_before,
            portfolio_value_after=value_after,
            portfolio_pnl=total_pnl,
            portfolio_pnl_pct=(total_pnl / value_before * 100) if value_before > 0 else 0.0,
            position_results=position_results,
            max_loss_symbol=max_loss_symbol,
            max_loss_amount=max_loss_amount,
            metadata=metadata or {},
        )

    def _build_correlation_matrix(self, symbols: List[str]) -> np.ndarray:
        """Build a correlation matrix for the given symbols."""
        n = len(symbols)
        matrix = np.eye(n)
        for i in range(n):
            for j in range(i + 1, n):
                corr = self._correlation_matrix.get(
                    (symbols[i], symbols[j]),
                    self._correlation_matrix.get(
                        (symbols[j], symbols[i]),
                        self._default_correlation,
                    ),
                )
                matrix[i][j] = corr
                matrix[j][i] = corr
        return matrix

    def set_correlation(self, symbol_a: str, symbol_b: str, correlation: float):
        """Set the correlation between two symbols."""
        self._correlation_matrix[(symbol_a, symbol_b)] = max(-1.0, min(1.0, correlation))

    def get_predefined_scenarios(self) -> Dict[str, Dict]:
        """Get all predefined scenarios."""
        return dict(self.PREDEFINED_SCENARIOS)
