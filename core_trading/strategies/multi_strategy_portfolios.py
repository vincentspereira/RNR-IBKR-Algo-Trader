"""Multi-Strategy Portfolio Management.

Provides comprehensive portfolio management with dynamic strategy allocation
and risk management.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class AllocationMethod(Enum):
    EQUAL_WEIGHT = "equal_weight"
    PERFORMANCE_BASED = "performance_based"
    RISK_PARITY = "risk_parity"
    MINIMUM_VARIANCE = "minimum_variance"
    MAXIMUM_SHARPE = "maximum_sharpe"
    BLACK_LITTERMAN = "black_litterman"
    KELLY_CRITERION = "kelly_criterion"


class RebalancingFrequency(Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    CONDITION_BASED = "condition_based"


@dataclass
class StrategyAllocation:
    """Allocation for a single strategy."""
    strategy_name: str
    target_weight: float
    current_weight: float = 0.0
    min_weight: float = 0.0
    max_weight: float = 1.0
    last_rebalanced: Optional[str] = None


@dataclass
class StrategyPerformance:
    """Performance metrics for a strategy."""
    strategy_name: str
    total_return: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0
    avg_trade_return: float = 0.0
    volatility: float = 0.0


@dataclass
class PortfolioState:
    """Current state of the portfolio."""
    total_equity: float = 100000.0
    cash: float = 100000.0
    invested: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    num_positions: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class PortfolioConfig:
    """Configuration for the portfolio manager."""
    initial_capital: float = 100000.0
    allocation_method: AllocationMethod = AllocationMethod.EQUAL_WEIGHT
    rebalancing_frequency: RebalancingFrequency = RebalancingFrequency.MONTHLY
    max_strategy_weight: float = 0.4
    min_strategy_weight: float = 0.05
    max_total_leverage: float = 1.0
    rebalance_threshold: float = 0.05
    risk_free_rate: float = 0.02


class PortfolioAllocator:
    """Handles capital allocation across strategies."""

    def __init__(self, method: AllocationMethod = AllocationMethod.EQUAL_WEIGHT):
        self.method = method

    def allocate(self, strategies: List[str], performances: Optional[Dict[str, StrategyPerformance]] = None) -> Dict[str, float]:
        """Calculate target allocation weights."""
        if not strategies:
            return {}

        if self.method == AllocationMethod.EQUAL_WEIGHT:
            weight = 1.0 / len(strategies)
            return {s: weight for s in strategies}

        elif self.method == AllocationMethod.PERFORMANCE_BASED:
            return self._performance_based(strategies, performances or {})

        elif self.method == AllocationMethod.RISK_PARITY:
            return self._risk_parity(strategies, performances or {})

        return {s: 1.0 / len(strategies) for s in strategies}

    def _performance_based(self, strategies: List[str], performances: Dict[str, StrategyPerformance]) -> Dict[str, float]:
        """Allocate based on performance metrics."""
        scores = {}
        for s in strategies:
            perf = performances.get(s)
            if perf:
                scores[s] = max(0.01, perf.sharpe_ratio + perf.total_return)
            else:
                scores[s] = 1.0
        total = sum(scores.values())
        return {s: scores[s] / total for s in strategies}

    def _risk_parity(self, strategies: List[str], performances: Dict[str, StrategyPerformance]) -> Dict[str, float]:
        """Allocate based on inverse volatility."""
        inv_vols = {}
        for s in strategies:
            perf = performances.get(s)
            vol = perf.volatility if perf and perf.volatility > 0 else 0.1
            inv_vols[s] = 1.0 / vol
        total = sum(inv_vols.values())
        return {s: inv_vols[s] / total for s in strategies}


class MultiStrategyPortfolio:
    """Manages a portfolio of multiple trading strategies."""

    def __init__(self, config: Optional[PortfolioConfig] = None):
        self.config = config or PortfolioConfig()
        self._strategies: Dict[str, Any] = {}
        self._allocations: Dict[str, StrategyAllocation] = {}
        self._performances: Dict[str, StrategyPerformance] = {}
        self._state = PortfolioState(total_equity=self.config.initial_capital, cash=self.config.initial_capital)
        self._allocator = PortfolioAllocator(self.config.allocation_method)
        self._trade_history: List[Dict[str, Any]] = []
        self._equity_curve: List[float] = [self.config.initial_capital]
        logger.info("MultiStrategyPortfolio initialized")

    def register_strategy(self, name: str, strategy: Any, weight: Optional[float] = None) -> None:
        """Register a strategy with the portfolio."""
        self._strategies[name] = strategy
        self._performances[name] = StrategyPerformance(strategy_name=name)
        if weight is not None:
            self._allocations[name] = StrategyAllocation(
                strategy_name=name,
                target_weight=weight,
                current_weight=0.0,
            )
        else:
            self._rebalance()

    def unregister_strategy(self, name: str) -> None:
        """Remove a strategy from the portfolio."""
        self._strategies.pop(name, None)
        self._allocations.pop(name, None)
        self._performances.pop(name, None)
        self._rebalance()

    def get_allocation(self, name: str) -> Optional[StrategyAllocation]:
        """Get allocation for a strategy."""
        return self._allocations.get(name)

    def get_all_allocations(self) -> Dict[str, StrategyAllocation]:
        """Get all strategy allocations."""
        return dict(self._allocations)

    def get_performance(self, name: str) -> Optional[StrategyPerformance]:
        """Get performance for a strategy."""
        return self._performances.get(name)

    def update_performance(self, name: str, metrics: Dict[str, Any]) -> None:
        """Update performance metrics for a strategy."""
        perf = self._performances.get(name)
        if perf:
            for k, v in metrics.items():
                if hasattr(perf, k):
                    setattr(perf, k, v)

    def _rebalance(self) -> None:
        """Rebalance allocations across strategies."""
        strategy_names = list(self._strategies.keys())
        if not strategy_names:
            return
        weights = self._allocator.allocate(strategy_names, self._performances)
        for name, weight in weights.items():
            clamped = max(self.config.min_strategy_weight, min(self.config.max_strategy_weight, weight))
            self._allocations[name] = StrategyAllocation(
                strategy_name=name,
                target_weight=clamped,
                current_weight=self._allocations.get(name, StrategyAllocation(strategy_name=name, target_weight=0)).current_weight,
            )

    def execute_strategy(self, name: str, data: pd.DataFrame) -> List[Dict[str, Any]]:
        """Execute a strategy and record results."""
        strategy = self._strategies.get(name)
        if strategy is None:
            return []

        allocation = self._allocations.get(name)
        if allocation is None:
            return []

        capital = self._state.total_equity * allocation.target_weight
        try:
            if hasattr(strategy, "generate_signals"):
                signals = strategy.generate_signals(data)
            else:
                signals = []
        except Exception as e:
            logger.error(f"Error executing strategy {name}: {e}")
            return []

        trades = [{"strategy": name, "capital": capital, "signals": len(signals) if isinstance(signals, list) else 0}]
        self._trade_history.extend(trades)
        return trades

    def execute_all(self, data: pd.DataFrame) -> Dict[str, List[Dict[str, Any]]]:
        """Execute all strategies."""
        results = {}
        for name in self._strategies:
            results[name] = self.execute_strategy(name, data)
        return results

    def update_equity(self, equity: float) -> None:
        """Update portfolio equity."""
        self._state.total_equity = equity
        self._equity_curve.append(equity)

    @property
    def state(self) -> PortfolioState:
        return self._state

    @property
    def equity_curve(self) -> List[float]:
        return self._equity_curve

    def get_portfolio_metrics(self) -> Dict[str, Any]:
        """Calculate portfolio-level metrics."""
        equity = np.array(self._equity_curve)
        if len(equity) > 1:
            returns = np.diff(equity) / equity[:-1]
            total_return = float((equity[-1] / equity[0]) - 1)
            sharpe = float(np.mean(returns) / (np.std(returns) + 1e-10) * np.sqrt(252)) if np.std(returns) > 0 else 0.0
            peak = np.maximum.accumulate(equity)
            max_dd = float(np.min((equity - peak) / peak))
        else:
            total_return = 0.0
            sharpe = 0.0
            max_dd = 0.0

        return {
            "total_return": total_return,
            "sharpe_ratio": sharpe,
            "max_drawdown": max_dd,
            "total_strategies": len(self._strategies),
            "total_equity": self._state.total_equity,
        }

    def get_status(self) -> Dict[str, Any]:
        """Get portfolio status."""
        return {
            "state": {
                "total_equity": self._state.total_equity,
                "cash": self._state.cash,
                "num_positions": self._state.num_positions,
            },
            "strategies": list(self._strategies.keys()),
            "allocation_method": self.config.allocation_method.value,
            "rebalancing_frequency": self.config.rebalancing_frequency.value,
        }
