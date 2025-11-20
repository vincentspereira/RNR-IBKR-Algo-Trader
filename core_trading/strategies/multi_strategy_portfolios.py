import asyncio
import logging
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple, Type, Union
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.covariance import LedoitWolf

# Multi-Strategy Portfolio Management for Nautilus Trader Engine
# Provides comprehensive portfolio management with dynamic strategy allocation and risk management."




logger = logging.getLogger(__name__)


class AllocationMethod(Enum):""
# "Methods for capital allocation across strategies.
# "
#     EQUAL_WEIGHT = "equal_weight"
#     PERFORMANCE_BASED = "performance_based"
#     RISK_PARITY = "risk_parity"
#     MINIMUM_VARIANCE = "minimum_variance"
#     MAXIMUM_SHARPE = "maximum_sharpe"
#     BLACK_LITTERMAN = "black_litterman"
#     KELLY_CRITERION = "kelly_criterion"


# "

class RebalancingFrequency(Enum):""
# "Rebalancing frequencies.
# "
#     DAILY = "daily"
#     WEEKLY = "weekly"
#     MONTHLY = "monthly"
#     QUARTERLY = "quarterly"
#     CONDITION_BASED = "condition_based"


# "

# @dataclass
class StrategyAllocation:""
#     "Allocation for a single strategy."

#     strategy_name: str
#     target_weight: float
#     current_weight: float = 0.0
#     min_weight: float = 0.0
#     max_weight: float = 1.0
#     last_rebalanced: Optional[datetime] = None


# @dataclass
class PortfolioMetrics:""
#     "Portfolio-level performance metrics."

#     total_value: float = 0.0
#     total_return: float = 0.0
#     annualized_return: float = 0.0
#     volatility: float = 0.0
#     sharpe_ratio: float = 0.0
#     max_drawdown: float = 0.0
#     win_rate: float = 0.0
#     profit_factor: float = 1.0
#     diversification_ratio: float = 1.0
#     strategy_correlation: float = 0.0


# @dataclass
class RebalancingTrigger:""
#     "Conditions that trigger rebalancing."

#     threshold_return: float = 0.05  # 5% return deviation
#     threshold_volatility: float = 0.1  # 10% volatility deviation
#     threshold_correlation: float = 0.2  # 20% correlation change
#     max_holding_period: int = 30  # days
#     min_holding_period: int = 1  # day


class StrategyInterface(ABC):""
#     "Interface for trading strategies."

#     @property
#     @abstractmethod
#     def name(self):
#         "Strategy name."
#         try:
            # Return the strategy's unique identifier"
#             strategy_name = getattr(self, "_name", None)
#             if strategy_name:
#                 return strategy_name

            # Fallback to class name if no explicit name set"
# class_name = self.__class__.__name__"
#             return class_name.replace("Strategy", ").replace("_", " ").title()"

#         except Exception as e:""
# logger.error(f"Error getting strategy name: {str(e)}")"
#             return "Unknown Strategy"

#     @abstractmethod
#     def get_current_allocation(self):
#         "Get current capital allocation."
#         try:
            # Get current allocation from strategy state"
#             current_allocation = getattr(self, "_current_allocation", 0.0)

            # Validate allocation is non-negative
#             if current_allocation < 0:
# logger.warning("
#                     f"Negative allocation detected for {self.name}: {current_allocation}"
# )
#                 return 0.0

#             return float(current_allocation)

#         except Exception as e:""
#             logger.error(f"Error getting current allocation for {self.name}: {str(e)}")
#             return 0.0

#     @abstractmethod
#     def get_performance_metrics(self):
#         "Get strategy performance metrics."
#         try:
            # Get performance data from strategy"
#             performance_data = getattr(self, "_performance_data", {})

            # Calculate basic performance metrics"
#             returns = performance_data.get("returns", [])
#             if not returns:
#                 return {
# "total_return": 0.0,"
# "annualized_return": 0.0,"
# "sharpe_ratio": 0.0,"
# "win_rate": 0.0,"
# "profit_factor": 1.0,"
# "max_drawdown": 0.0,"
# "volatility": 0.0,
# }

#             returns_array = np.array(returns)

            # Total return
#             total_return = np.prod(1 + returns_array) - 1

            # Annualized return (assuming daily returns)
#             periods_per_year = 252
# annualized_return = (1 + total_return) ** (
#                 periods_per_year / len(returns)
# ) - 1

            # Volatility
#             volatility = np.std(returns_array) * np.sqrt(periods_per_year)

            # Sharpe ratio (assuming risk-free rate of 2%)
#             risk_free_rate = 0.02
# sharpe_ratio = (
#                 (annualized_return - risk_free_rate) / volatility
#                 if volatility > 0
# else 0.0
# )

            # Win rate
#             winning_trades = len([r for r in returns if r > 0])
#             win_rate = winning_trades / len(returns) if returns else 0.0

            # Profit factor
#             gross_profit = sum([r for r in returns if r > 0])
#             gross_loss = abs(sum([r for r in returns if r < 0]))
# profit_factor = ("
#                 gross_profit / gross_loss if gross_loss > 0 else float("inf")
# )

            # Maximum drawdown
#             cumulative_returns = np.cumprod(1 + returns_array)
#             running_max = np.maximum.accumulate(cumulative_returns)
#             drawdowns = (cumulative_returns - running_max) / running_max
#             max_drawdown = abs(np.min(drawdowns)) if len(drawdowns) > 0 else 0.0

#             return {
# "total_return": float(total_return),"
# "annualized_return": float(annualized_return),"
# "sharpe_ratio": float(sharpe_ratio),"
# "win_rate": float(win_rate),"
# "profit_factor": float(profit_factor),"
# "max_drawdown": float(max_drawdown),"
# "volatility": float(volatility),
# }

#         except Exception as e:
# logger.error("
#                 f"Error calculating performance metrics for {self.name}: {str(e)}"
# )
#             return {
# "total_return": 0.0,"
# "annualized_return": 0.0,"
# "sharpe_ratio": 0.0,"
# "win_rate": 0.0,"
# "profit_factor": 1.0,"
# "max_drawdown": 0.0,"
# "volatility": 0.0,
# }

#     @abstractmethod
#     def get_risk_metrics(self):
#         "Get strategy risk metrics."
#         try:
            # Get performance data for risk calculations"
# performance_data = getattr(self, "_performance_data", {})"
#             returns = performance_data.get("returns", [])

#             if not returns:
#                 return {
# "volatility": 0.0,"
# "var_95": 0.0,"
# "var_99": 0.0,"
# "expected_shortfall": 0.0,"
# "beta": 0.0,"
# "tracking_error": 0.0,"
# "information_ratio": 0.0,"
# "downside_deviation": 0.0,
# }

#             returns_array = np.array(returns)

            # Volatility (annualized)
#             volatility = np.std(returns_array) * np.sqrt(252)

            # Value at Risk (95% and 99%)
#             var_95 = np.percentile(returns_array, 5)
#             var_99 = np.percentile(returns_array, 1)

            # Expected Shortfall (Conditional VaR)
#             tail_returns = returns_array[returns_array <= var_95]
#             expected_shortfall = np.mean(tail_returns) if len(tail_returns) > 0 else 0.0

            # Beta (assuming market returns available)"
#             market_returns = performance_data.get("market_returns", [])
#             beta = 0.0
#             if len(market_returns) == len(returns) and len(returns) > 1:
#                 covariance = np.cov(returns_array, market_returns)[0, 1]
#                 market_variance = np.var(market_returns)
#                 beta = covariance / market_variance if market_variance > 0 else 0.0

            # Tracking error"
#             benchmark_returns = performance_data.get("benchmark_returns", [])
#             tracking_error = 0.0
#             if len(benchmark_returns) == len(returns):
#                 excess_returns = returns_array - np.array(benchmark_returns)
#                 tracking_error = np.std(excess_returns) * np.sqrt(252)

            # Information ratio
#             information_ratio = 0.0
#             if tracking_error > 0 and len(benchmark_returns) == len(returns):
#                 excess_returns = returns_array - np.array(benchmark_returns)
#                 information_ratio = np.mean(excess_returns) * 252 / tracking_error

            # Downside deviation
#             negative_returns = returns_array[returns_array < 0]
# downside_deviation = (
#                 np.std(negative_returns) * np.sqrt(252)
#                 if len(negative_returns) > 0
# else 0.0
# )

#             return {
# "volatility": float(volatility),"
# "var_95": float(var_95),"
# "var_99": float(var_99),"
# "expected_shortfall": float(expected_shortfall),"
# "beta": float(beta),"
# "tracking_error": float(tracking_error),"
# "information_ratio": float(information_ratio),"
# "downside_deviation": float(downside_deviation),
# }

#         except Exception as e:""
#             logger.error(f"Error calculating risk metrics for {self.name}: {str(e)}")
#             return {
# "volatility": 0.0,"
# "var_95": 0.0,"
# "var_99": 0.0,"
# "expected_shortfall": 0.0,"
# "beta": 0.0,"
# "tracking_error": 0.0,"
# "information_ratio": 0.0,"
# "downside_deviation": 0.0,
# }

#     @abstractmethod
#     def can_accept_allocation(self, allocation: float):
#         "Check if strategy can accept the given allocation."
#         try:
            # Validate allocation is non-negative
#             if allocation < 0:
# logger.debug("
#                     f"Strategy {self.name} cannot accept negative allocation: {allocation}"
# )
#                 return False

            # Check strategy-specific constraints"
# min_allocation = getattr(self, "_min_allocation", 0.0)"
#             max_allocation = getattr(self, "_max_allocation", float("inf"))

#             if allocation < min_allocation:
# logger.debug("
#                     f"Strategy {self.name} allocation {allocation} below minimum {min_allocation}"
# )
#                 return False

#             if allocation > max_allocation:
# logger.debug("
#                     f"Strategy {self.name} allocation {allocation} above maximum {max_allocation}"
# )
#                 return False

            # Check strategy status"
# strategy_status = getattr(self, "_status", "active")"
#             if strategy_status not in ["active", "running"]:
# logger.debug("
#                     f"Strategy {self.name} not active, status: {strategy_status}"
# )
#                 return False

            # Check if strategy has capacity for additional allocation"
# current_allocation = self.get_current_allocation()"
#             capacity_limit = getattr(self, "_capacity_limit", float("inf"))

#             if allocation > capacity_limit:
# logger.debug("
#                     f"Strategy {self.name} allocation {allocation} exceeds capacity {capacity_limit}"
# )
#                 return False

            # Check risk constraints"
# risk_metrics = self.get_risk_metrics()"
#             max_volatility = getattr(self, "_max_volatility", 1.0)
# "
#             if risk_metrics.get("volatility", 0) > max_volatility:""
#                 logger.debug(f"Strategy {self.name} volatility too high for allocation")
#                 return False

#             return True

#         except Exception as e:
# logger.error("
#                 f"Error checking allocation acceptance for {self.name}: {str(e)}"
# )
#             return False

#     @abstractmethod
#     def update_allocation(self, new_allocation: float):
#         "Update strategy allocation."
#         try:
            # Validate the new allocation
#             if not self.can_accept_allocation(new_allocation):
# logger.warning("
#                     f"Strategy {self.name} cannot accept allocation: {new_allocation}"
# )
#                 return False

            # Store previous allocation for rollback if needed"
#             previous_allocation = getattr(self, "_current_allocation", 0.0)

            # Update allocation
#             self._current_allocation = float(new_allocation)

            # Update allocation timestamp
#             self._last_allocation_update = datetime.now()

            # Log allocation change"
# logger.info("
#                 f"Strategy {self.name} allocation updated: {previous_allocation} -> {new_allocation}"
# )

            # Update strategy parameters based on new allocation
#             self._update_strategy_parameters(new_allocation)

            # Validate the update was successful"
#             if abs(self.get_current_allocation() - new_allocation) > 1e-6:""
#                 logger.error(f"Allocation update failed for {self.name}")
                # Rollback
#                 self._current_allocation = previous_allocation
#                 return False

#             return True

#         except Exception as e:""
#             logger.error(f"Error updating allocation for {self.name}: {str(e)}")
#             return False

#     def _update_strategy_parameters(self, new_allocation: float):
#         "Update strategy parameters based on new allocation."
#         try:
            # Update position sizing parameters"
#             if hasattr(self, "_position_sizer"):
#                 self._position_sizer.update_capital(new_allocation)

            # Update risk management parameters"
#             if hasattr(self, "_risk_manager"):
#                 self._risk_manager.update_capital(new_allocation)

            # Update any allocation-dependent parameters"
# allocation_ratio = ("
# new_allocation / getattr(self, "_initial_allocation", new_allocation)"
#                 if getattr(self, "_initial_allocation", 0) > 0
# else 1.0
# )

            # Scale position sizes proportionally"
#             if hasattr(self, "_base_position_size"):
#                 self._current_position_size = (
#                     self._base_position_size * allocation_ratio
# )

            # Update stop loss and take profit levels if needed"
#             if hasattr(self, "_stop_loss_pct"):
                # Keep percentage-based stops the same, but update absolute amounts"
#                 logger.debug("Stop loss percentage update logic pending implementation")

#         except Exception as e:
# logger.error("
#                 f"Error updating strategy parameters for {self.name}: {str(e)}"
# )


class AllocationOptimizer:""
# "
# Optimizes capital allocation across multiple strategies."


# "

#     def __init__(self, method: AllocationMethod = AllocationMethod.RISK_PARITY):
#         self.method = method
#         self.risk_free_rate = 0.02
#         self.executor = ThreadPoolExecutor(max_workers=4)

#     def optimize_allocation(
#         self,
# strategies: List[StrategyInterface],
# total_capital: float,
#         constraints: Optional[Dict[str, Any]] = None,
# ) -> Dict[str, float]:"
#         "Optimize capital allocation across strategies."
#         if not strategies:
#             return {}

#         strategy_names = [s.name for s in strategies]

#         if self.method == AllocationMethod.EQUAL_WEIGHT:
#             return self._equal_weight_allocation(strategy_names, total_capital)

#         elif self.method == AllocationMethod.PERFORMANCE_BASED:
#             return self._performance_based_allocation(strategies, total_capital)

#         elif self.method == AllocationMethod.RISK_PARITY:
#             return self._risk_parity_allocation(strategies, total_capital)

#         elif self.method == AllocationMethod.MINIMUM_VARIANCE:
#             return self._minimum_variance_allocation(strategies, total_capital)

#         elif self.method == AllocationMethod.MAXIMUM_SHARPE:
#             return self._maximum_sharpe_allocation(strategies, total_capital)

#         elif self.method == AllocationMethod.KELLY_CRITERION:
#             return self._kelly_criterion_allocation(strategies, total_capital)

#         else:
#             return self._equal_weight_allocation(strategy_names, total_capital)

#     def _equal_weight_allocation(
# self, strategy_names: List[str], total_capital: float
# ) -> Dict[str, float]:"
#         "Equal weight allocation."
#         num_strategies = len(strategy_names)
#         if num_strategies == 0:
#             return {}

#         equal_weight = total_capital / num_strategies
#         return {name: equal_weight for name in strategy_names}

#     def _performance_based_allocation(
# self, strategies: List[StrategyInterface], total_capital: float
# ) -> Dict[str, float]:"
#         "Allocate based on recent performance."
#         if not strategies:
#             return {}

        # Get performance scores
#         performance_scores = {}
#         total_score = 0

#         for strategy in strategies:
# metrics = strategy.get_performance_metrics()"
# sharpe = metrics.get("sharpe_ratio", 0)"
# win_rate = metrics.get("win_rate", 0)"
#             profit_factor = metrics.get("profit_factor", 1)

            # Composite performance score
#             score = sharpe * 0.4 + win_rate * 0.3 + min(profit_factor, 3) * 0.3
#             performance_scores[strategy.name] = max(score, 0.1)  # Minimum score
#             total_score += performance_scores[strategy.name]

#         if total_score == 0:
#             return self._equal_weight_allocation(
#                 [s.name for s in strategies], total_capital
# )

        # Allocate based on performance
#         allocations = {}
#         for strategy in strategies:
#             weight = performance_scores[strategy.name] / total_score
#             allocations[strategy.name] = weight * total_capital

#         return allocations

#     def _risk_parity_allocation(
# self, strategies: List[StrategyInterface], total_capital: float
# ) -> Dict[str, float]:"
#         "Risk parity allocation - equal risk contribution."
#         if not strategies:
#             return {}

        # Get volatilities
#         volatilities = {}
#         for strategy in strategies:
# risk_metrics = strategy.get_risk_metrics()"
#             vol = risk_metrics.get("volatility", 0.1)  # Default 10% if not available
#             volatilities[strategy.name] = max(vol, 0.01)  # Minimum volatility

        # Risk parity weights
#         inv_volatilities = {name: 1 / vol for name, vol in volatilities.items()}
#         total_inv_vol = sum(inv_volatilities.values())

#         allocations = {}
#         for strategy in strategies:
#             weight = inv_volatilities[strategy.name] / total_inv_vol
#             allocations[strategy.name] = weight * total_capital

#         return allocations

#     def _minimum_variance_allocation(
# self, strategies: List[StrategyInterface], total_capital: float
# ) -> Dict[str, float]:"
#         "Minimum variance portfolio optimization."
#         if len(strategies) < 2:
#             return self._equal_weight_allocation(
#                 [s.name for s in strategies], total_capital
# )

#         try:
            # Get returns and covariance
#             returns = []
#             names = []

#             for strategy in strategies:
# metrics = strategy.get_performance_metrics()"
#                 ret = metrics.get("total_return", 0)
#                 returns.append(ret)
#                 names.append(strategy.name)

            # Simple covariance estimation (would use real historical data in practice)
#             returns_array = np.array(returns).reshape(-1, 1)
#             cov_matrix = np.cov(returns_array.T)

#             if cov_matrix.shape[0] != len(strategies):
#                 return self._equal_weight_allocation(names, total_capital)

            # Minimize variance
#             n = len(strategies)

#             def objective(weights):
#                 return np.dot(weights.T, np.dot(cov_matrix, weights))

# constraints = ["
#                 {"type": "eq", "fun": lambda x: np.sum(x) - 1},  # Weights sum to 1
# ]
#             bounds = [(0, 1) for _ in range(n)]
#             initial_weights = np.array([1 / n] * n)

# result = minimize(
#                 objective,
# initial_weights,"
#                 method="SLSQP",
#                 bounds=bounds,
#                 constraints=constraints,
# )

#             if result.success:
#                 allocations = {}
#                 for i, name in enumerate(names):
#                     allocations[name] = result.x[i] * total_capital
#                 return allocations
#             else:
#                 return self._equal_weight_allocation(names, total_capital)

#         except Exception as e:""
#             logger.error(f"Error in minimum variance optimization: {e}")
#             return self._equal_weight_allocation(
#                 [s.name for s in strategies], total_capital
# )

#     def _maximum_sharpe_allocation(
# self, strategies: List[StrategyInterface], total_capital: float
# ) -> Dict[str, float]:"
#         "Maximum Sharpe ratio portfolio optimization."
#         if len(strategies) < 2:
#             return self._equal_weight_allocation(
#                 [s.name for s in strategies], total_capital
# )

#         try:
            # Get returns and volatilities
#             returns = []
#             volatilities = []
#             names = []

#             for strategy in strategies:
#                 perf_metrics = strategy.get_performance_metrics()
#                 risk_metrics = strategy.get_risk_metrics()
# "
# ret = perf_metrics.get("total_return", 0)"
#                 vol = risk_metrics.get("volatility", 0.1)

#                 returns.append(ret)
#                 volatilities.append(vol)
#                 names.append(strategy.name)

            # Maximize Sharpe ratio
#             n = len(strategies)

#             def objective(weights):
#                 "portfolio_return = np.sum(weights * np.array(returns))"
# portfolio_vol = np.sqrt(
#                     np.dot(weights.T, np.dot(np.diag(volatilities), weights))
# )
# sharpe = (
#                     (portfolio_return - self.risk_free_rate) / portfolio_vol
#                     if portfolio_vol > 0
# else 0
# )
#                 return -sharpe  # Minimize negative Sharpe

# constraints = ["
#                 {"type": "eq", "fun": lambda x: np.sum(x) - 1},
# ]
#             bounds = [(0, 1) for _ in range(n)]
#             initial_weights = np.array([1 / n] * n)

# result = minimize(
#                 objective,
# initial_weights,"
#                 method="SLSQP",
#                 bounds=bounds,
#                 constraints=constraints,
# )

#             if result.success:
#                 allocations = {}
#                 for i, name in enumerate(names):
#                     allocations[name] = result.x[i] * total_capital
#                 return allocations
#             else:
#                 return self._equal_weight_allocation(names, total_capital)

#         except Exception as e:""
#             logger.error(f"Error in maximum Sharpe optimization: {e}")
#             return self._equal_weight_allocation(
#                 [s.name for s in strategies], total_capital
# )

#     def _kelly_criterion_allocation(
# self, strategies: List[StrategyInterface], total_capital: float
# ) -> Dict[str, float]:"
#         "Kelly Criterion based allocation."
#         allocations = {}

#         for strategy in strategies:
#             perf_metrics = strategy.get_performance_metrics()
#             risk_metrics = strategy.get_risk_metrics()
# "
# win_rate = perf_metrics.get("win_rate", 0.5)"
# avg_win = perf_metrics.get("avg_win", 0)"
#             avg_loss = abs(perf_metrics.get("avg_loss", 0))

#             if avg_loss > 0:
                # Kelly formula: f = (bp - q) / b
                # where b = odds, p = win probability, q = loss probability
#                 b = avg_win / avg_loss
#                 kelly_fraction = (win_rate * b - (1 - win_rate)) / b
#                 kelly_fraction = max(0, min(0.5, kelly_fraction))  # Conservative Kelly
#             else:
#                 kelly_fraction = 0.1  # Default allocation

#             allocations[strategy.name] = kelly_fraction * total_capital

#         return allocations


class MultiStrategyPortfolio:""
# "
# Manages a portfolio of multiple trading strategies with dynamic allocation."


# "

#     def __init__(
#         self,
# name: str,
#         initial_capital: float = 1000000.0,
#         allocation_method: AllocationMethod = AllocationMethod.RISK_PARITY,
#         rebalancing_freq: RebalancingFrequency = RebalancingFrequency.WEEKLY,
# ):
#         self.name = name
#         self.initial_capital = initial_capital
#         self.current_capital = initial_capital
#         self.allocation_method = allocation_method
#         self.rebalancing_freq = rebalancing_freq

#         self.strategies: Dict[str, StrategyInterface] = {}
#         self.allocations: Dict[str, StrategyAllocation] = {}
#         self.portfolio_history: List[Tuple[datetime, PortfolioMetrics]] = []

#         self.optimizer = AllocationOptimizer(allocation_method)
#         self.rebalancing_trigger = RebalancingTrigger()
#         self.last_rebalancing = datetime.now()

#         self.executor = ThreadPoolExecutor(max_workers=8)

#     def add_strategy(
#         self,
# strategy: StrategyInterface,
#         min_weight: float = 0.0,
#         max_weight: float = 1.0,
# ) -> None:"
# "Add a strategy to the portfolio.
#         if strategy.name in self.strategies:""
#             logger.warning(f"Strategy {strategy.name} already exists in portfolio")
#             return
# "
#         self.strategies[strategy.name] = strategy
#         self.allocations[strategy.name] = StrategyAllocation(
#             strategy_name=strategy.name,
#             target_weight=0.0,  # Will be set during rebalancing
#             min_weight=min_weight,
#             max_weight=max_weight,
# )
# "
#         logger.info(f"Added strategy {strategy.name} to portfolio {self.name}")

# "

#     def remove_strategy(self, strategy_name: str):
#         "Remove a strategy from the portfolio."
#         if strategy_name not in self.strategies:
#             return False

        # Close all positions for this strategy
#         strategy = self.strategies[strategy_name]
#         current_allocation = strategy.get_current_allocation()

#         if current_allocation > 0:
            # In a real implementation, this would close positions"
#             logger.info(f"Closing positions for strategy {strategy_name}")

#         del self.strategies[strategy_name]
#         del self.allocations[strategy_name]
# "
#         logger.info(f"Removed strategy {strategy_name} from portfolio {self.name}")
#         return True

#     def rebalance_portfolio(self):
#         "Rebalance the portfolio according to the allocation method."
#         if not self.strategies:
#             return False

#         try:
            # Get optimal allocations
# optimal_allocations = self.optimizer.optimize_allocation(
#                 list(self.strategies.values()), self.current_capital
# )

            # Apply allocations
#             total_allocated = 0
#             for strategy_name, allocation in optimal_allocations.items():
#                 if strategy_name in self.strategies:
#                     strategy = self.strategies[strategy_name]
#                     alloc_obj = self.allocations[strategy_name]

                    # Check constraints
#                     min_alloc = alloc_obj.min_weight * self.current_capital
#                     max_alloc = alloc_obj.max_weight * self.current_capital

#                     allocation = max(min_alloc, min(max_alloc, allocation))

                    # Update strategy allocation
#                     if strategy.can_accept_allocation(allocation):
#                         strategy.update_allocation(allocation)
#                         alloc_obj.target_weight = allocation / self.current_capital
#                         alloc_obj.current_weight = allocation / self.current_capital
#                         alloc_obj.last_rebalanced = datetime.now()
#                         total_allocated += allocation

#             self.last_rebalancing = datetime.now()
# logger.info("
#                 f"Rebalanced portfolio {self.name} with total allocation: {total_allocated:.2f}"
# )

#             return True

#         except Exception as e:""
#             logger.error(f"Error rebalancing portfolio {self.name}: {e}")
#             return False

#     def should_rebalance(self):
#         "Check if portfolio should be rebalanced."
#         if not self.strategies:
#             return False

#         current_time = datetime.now()

        # Check time-based rebalancing
#         if self.rebalancing_freq == RebalancingFrequency.DAILY:
#             time_threshold = timedelta(days=1)
#         elif self.rebalancing_freq == RebalancingFrequency.WEEKLY:
#             time_threshold = timedelta(weeks=1)
#         elif self.rebalancing_freq == RebalancingFrequency.MONTHLY:
#             time_threshold = timedelta(days=30)
#         else:
#             time_threshold = timedelta(days=90)  # Quarterly default

#         time_based = (current_time - self.last_rebalancing) >= time_threshold

#         if time_based:
#             return True

        # Check condition-based triggers
#         for alloc in self.allocations.values():
#             if alloc.current_weight > 0:
#                 deviation = abs(alloc.current_weight - alloc.target_weight)
#                 if deviation > self.rebalancing_trigger.threshold_return:
#                     return True

#         return False

#     async def update_portfolio(
# self, market_data: Optional[pd.DataFrame] = None
# ) -> None:"
#         "Update portfolio with latest market data."
#         if not self.strategies:
#             return

        # Update all strategies concurrently
#         update_tasks = []
#         for strategy in self.strategies.values():
# task = asyncio.get_event_loop().run_in_executor(
#                 self.executor, self._update_strategy, strategy, market_data
# )
#             update_tasks.append(task)

#         await asyncio.gather(*update_tasks, return_exceptions=True)

        # Check if rebalancing is needed
#         if self.should_rebalance():
# await asyncio.get_event_loop().run_in_executor(
#                 self.executor, self.rebalance_portfolio
# )

        # Update portfolio metrics
#         self._update_portfolio_metrics()

#     def _update_strategy(
# self, strategy: StrategyInterface, market_data: Optional[pd.DataFrame]
# ) -> None:"
#         "Update a single strategy."
#         try:
            # In a real implementation, this would update the strategy with market data
            # and get updated allocations
#             current_allocation = strategy.get_current_allocation()
#             alloc_obj = self.allocations[strategy.name]
#             alloc_obj.current_weight = current_allocation / self.current_capital

#         except Exception as e:""
#             logger.error(f"Error updating strategy {strategy.name}: {e}")

#     def _update_portfolio_metrics(self):
#         "Update portfolio-level performance metrics."
#         if not self.strategies:
#             return

#         try:
            # Calculate portfolio metrics
#             total_value = self.current_capital
#             strategy_returns = []
#             strategy_volatilities = []

#             for strategy in self.strategies.values():
#                 perf_metrics = strategy.get_performance_metrics()
#                 risk_metrics = strategy.get_risk_metrics()

#                 allocation = strategy.get_current_allocation()
#                 total_value += allocation
# "
# ret = perf_metrics.get("total_return", 0)"
#                 vol = risk_metrics.get("volatility", 0.1)

#                 strategy_returns.append(ret)
#                 strategy_volatilities.append(vol)

            # Portfolio return (simplified)
# portfolio_return = (
#                 total_value - self.initial_capital
# ) / self.initial_capital

            # Portfolio volatility (simplified)
#             if strategy_returns:
#                 portfolio_volatility = np.std(strategy_returns)
#             else:
#                 portfolio_volatility = 0

            # Sharpe ratio
#             if portfolio_volatility > 0:
#                 sharpe_ratio = (portfolio_return - 0.02) / portfolio_volatility
#             else:
#                 sharpe_ratio = 0

            # Diversification ratio
#             if strategy_volatilities:
#                 avg_individual_vol = np.mean(strategy_volatilities)
#                 portfolio_vol = portfolio_volatility
# diversification_ratio = (
#                     avg_individual_vol / portfolio_vol if portfolio_vol > 0 else 1
# )
#             else:
#                 diversification_ratio = 1

# metrics = PortfolioMetrics(
#                 total_value=total_value,
#                 total_return=portfolio_return,
#                 volatility=portfolio_volatility,
#                 sharpe_ratio=sharpe_ratio,
#                 diversification_ratio=diversification_ratio,
# )

#             self.portfolio_history.append((datetime.now(), metrics))

            # Keep only recent history
#             if len(self.portfolio_history) > 1000:
#                 self.portfolio_history = self.portfolio_history[-500:]

#         except Exception as e:""
#             logger.error(f"Error updating portfolio metrics: {e}")

#     def get_portfolio_status(self):
#         "Get current portfolio status."
#         if not self.portfolio_history:
#             return {}

#         latest_metrics = self.portfolio_history[-1][1]

#         strategy_status = {}
#         for name, strategy in self.strategies.items():
#             alloc = self.allocations[name]
# strategy_status[name] = {
# "current_allocation": strategy.get_current_allocation(),"
# "target_weight": alloc.target_weight,"
# "current_weight": alloc.current_weight,"
# "performance": strategy.get_performance_metrics(),"
# "risk": strategy.get_risk_metrics(),
# }

#         return {
# "portfolio_name": self.name,"
# "total_value": latest_metrics.total_value,"
# "total_return": latest_metrics.total_return,"
# "sharpe_ratio": latest_metrics.sharpe_ratio,"
# "volatility": latest_metrics.volatility,"
# "diversification_ratio": latest_metrics.diversification_ratio,"
# "num_strategies": len(self.strategies),"
# "allocation_method": self.allocation_method.value,"
# "last_rebalancing": self.last_rebalancing.isoformat(),"
# "strategies": strategy_status,
# }

#     def get_performance_summary(
# self, periods: Optional[List[str]] = None
# ) -> Dict[str, Any]:"
#         "Get performance summary for different periods."
#         if not self.portfolio_history:
#             return {}
# "
#         periods = periods or ["1M", "3M", "6M", "1Y"]

#         summary = {}
#         current_time = datetime.now()

#         for period in periods:""
#             if period == "1M":
# days = 30"
#             elif period == "3M":
# days = 90"
#             elif period == "6M":
# days = 180"
#             elif period == "1Y":
#                 days = 365
#             else:
#                 continue

#             cutoff_time = current_time - timedelta(days=days)

            # Filter history for the period
# period_history = [
#                 (timestamp, metrics)
#                 for timestamp, metrics in self.portfolio_history
#                 if timestamp >= cutoff_time
# ]

#             if len(period_history) >= 2:
#                 start_metrics = period_history[0][1]
#                 end_metrics = period_history[-1][1]

#                 period_return = end_metrics.total_return - start_metrics.total_return
#                 period_volatility = np.std([m.total_return for _, m in period_history])

# summary[period] = {
# "return": period_return,"
# "volatility": period_volatility,"
# "sharpe_ratio": period_return / period_volatility
#                     if period_volatility > 0
# else 0,
# }

#         return summary

#     def set_allocation_method(self, method: AllocationMethod):
#         "Change the allocation method."
#         self.allocation_method = method
#         self.optimizer = AllocationOptimizer(method)
# logger.info("
#             f"Changed allocation method to {method.value} for portfolio {self.name}"
# )

#     def set_rebalancing_frequency(self, frequency: RebalancingFrequency):
#         "Change rebalancing frequency."
#         self.rebalancing_freq = frequency
# logger.info("
#             f"Changed rebalancing frequency to {frequency.value} for portfolio {self.name}"
# )


# Global portfolio registry
_portfolio_registry: Dict[str, MultiStrategyPortfolio] = {}


# def create_portfolio(
# name: str,
#     initial_capital: float = 1000000.0,
#     allocation_method: AllocationMethod = AllocationMethod.RISK_PARITY,
#     rebalancing_freq: RebalancingFrequency = RebalancingFrequency.WEEKLY,
# ) -> MultiStrategyPortfolio:"
#     "Create a new multi-strategy portfolio."
# portfolio = MultiStrategyPortfolio(
#         name, initial_capital, allocation_method, rebalancing_freq
# )
#     _portfolio_registry[name] = portfolio
#     return portfolio


# def get_portfolio(name: str):
#     "Get a portfolio by name."
#     return _portfolio_registry.get(name)


# def list_portfolios():
#     "List all portfolios."
#     return list(_portfolio_registry.keys())


# Example strategy implementation for testing"
class ExampleStrategy(StrategyInterface):""
#     "Example strategy implementation."

#     def __init__(self, name: str, initial_allocation: float = 0):
#         self._name = name
#         self._allocation = initial_allocation
#         self._performance = {""
# "total_return": 0.05,"
# "sharpe_ratio": 1.2,"
# "win_rate": 0.55,
# }
#         self._risk = {"volatility": 0.15}

#     @property
#     def name(self) -> str:
#         return self._name

#     def get_current_allocation(self) -> float:
#         return self._allocation

#     def get_performance_metrics(self) -> Dict[str, float]:
#         return self._performance.copy()

#     def get_risk_metrics(self) -> Dict[str, float]:
#         return self._risk.copy()

#     def can_accept_allocation(self, allocation: float) -> bool:
#         return allocation >= 0

#     def update_allocation(self, new_allocation: float) -> bool:
#         self._allocation = new_allocation
#         return True

# "
# if __name__ == "__main__":
    # Example usage
#     async def main():
        # Create portfolio"
#         portfolio = create_portfolio("Example_Portfolio", 1000000)

        # Add strategies"
# strategy1 = ExampleStrategy("Mean_Reversion_Strategy")"
# strategy2 = ExampleStrategy("Trend_Following_Strategy")"
#         strategy3 = ExampleStrategy("Arbitrage_Strategy")

#         portfolio.add_strategy(strategy1)
#         portfolio.add_strategy(strategy2)
#         portfolio.add_strategy(strategy3)

        # Initial rebalancing
#         portfolio.rebalance_portfolio()

        # Update portfolio
#         await portfolio.update_portfolio()

        # Get status"
# status = portfolio.get_portfolio_status()"
#         print(f"Portfolio Status: {status}")

        # Get performance summary"
# performance = portfolio.get_performance_summary()"
#         print(f"Performance Summary: {performance}")

    # Run example
#     asyncio.run(main())
# "'"'