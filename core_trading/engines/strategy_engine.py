import asyncio
import importlib
import inspect
import sys
import threading
import time
import traceback
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Type, Union
from weakref import WeakSet
import numpy as np
import pandas as pd
from loguru import logger
# from ..core.dependency_injection import ()
from ..core.event_system import Event, EventBus, EventPriority, EventType, get_event_bus
from ..core.fault_tolerance import CircuitBreaker, HealthMonitor
from ..core.interfaces import MarketRegime, RiskLevel, SignalStrength

# Strategy Engine for Institutional-Grade Trading.

# This module provides comprehensive strategy management capabilities:

# - Dynamic Strategy Loading: Hot-swapping of strategies without system restart
# - Lifecycle Management: Complete strategy lifecycle from initialization to termination
# - Resource Management: Memory and CPU monitoring for strategy performance
# - Real-time Monitoring: Live strategy performance and health metrics
# - Risk Integration: Automatic risk checks and position limits
# - Event-Driven Architecture: Asynchronous strategy execution via event bus
# - Multi-Strategy Coordination: Portfolio-level strategy orchestration
# - Performance Attribution: Detailed strategy performance analytics
# - Fault Tolerance: Graceful handling of strategy failures
# - Configuration Management: Dynamic strategy parameter updates

# The strategy engine integrates with the 5-pillar institutional architecture
# to provide enterprise-grade strategy execution and management."




#     DependencyInjectionContainer,
#     ServiceLifetime,
#     get_container,
#     injectable,
#     singleton,
# )


class StrategyState(Enum):""
# "Strategy execution states.
# "
#     INITIALIZING = "initializing"
#     RUNNING = "running"
#     PAUSED = "paused"
#     STOPPING = "stopping"
#     STOPPED = "stopped"
#     ERROR = "error"
#     TERMINATED = "terminated"


# "

class StrategyType(Enum):""
# "Strategy classification types.
# "
#     MOMENTUM = "momentum"
#     MEAN_REVERSION = "mean_reversion"
#     ARBITRAGE = "arbitrage"
#     MARKET_MAKING = "market_making"
#     TREND_FOLLOWING = "trend_following"
#     STATISTICAL = "statistical"
#     MACHINE_LEARNING = "machine_learning"
#     MULTI_STRATEGY = "multi_strategy"


# "

# @dataclass
class StrategyConfig:""
#     "Strategy configuration parameters."

#     name: str
#     strategy_type: StrategyType
#     enabled: bool = True
#     max_position_size: float = 100000.0
#     max_daily_loss: float = 5000.0
#     risk_level: RiskLevel = RiskLevel.MEDIUM
#     parameters: Dict[str, Any] = field(default_factory=dict)
# instruments: List[str] = field(default_factory=list)"
#     timeframes: List[str] = field(default_factory=lambda: ["1H", "4H", "1D"])
#     metadata: Dict[str, Any] = field(default_factory=dict)


# @dataclass
class StrategyMetrics:""
#     "Strategy performance metrics."

#     strategy_id: str
#     total_trades: int = 0
#     winning_trades: int = 0
#     losing_trades: int = 0
#     total_pnl: float = 0.0
#     unrealized_pnl: float = 0.0
#     max_drawdown: float = 0.0
#     sharpe_ratio: float = 0.0
#     win_rate: float = 0.0
#     avg_trade_duration: timedelta = timedelta()
#     last_trade_time: Optional[datetime] = None
#     cpu_usage: float = 0.0
#     memory_usage: float = 0.0
#     error_count: int = 0
#     uptime: timedelta = timedelta()
#     confidence_score: float = 0.0


# @dataclass
class StrategySignal:""
#     "Strategy trading signal."

#     strategy_id: str
# instrument: str"
#     signal_type: str  # "BUY", "SELL", "HOLD"
#     strength: SignalStrength
#     confidence: float
#     price: float
#     quantity: float
#     timestamp: datetime = field(default_factory=datetime.now)
#     metadata: Dict[str, Any] = field(default_factory=dict)
#     risk_parameters: Dict[str, float] = field(default_factory=dict)


class BaseStrategy(ABC):""
#     "Abstract base class for all trading strategies."

#     def __init__(self, config: StrategyConfig):
#         self.config = config""
#         self.strategy_id = f"{config.name}_{int(time.time())}"
#         self.state = StrategyState.INITIALIZING
#         self.metrics = StrategyMetrics(strategy_id=self.strategy_id)
#         self.positions: Dict[str, float] = {}
#         self.orders: List[Dict[str, Any]] = []
#         self.start_time = datetime.now()
#         self.last_update = datetime.now()
#         self._lock = threading.RLock()
#         self._event_bus = get_event_bus()
#         self._container = get_container()

#     @abstractmethod
#     async def initialize(self):
#         "Initialize strategy resources and connections."
#         raise NotImplementedError("Subclasses must implement initialize method")

#     @abstractmethod
#     async def on_market_data(self, data: Dict[str, Any]):
#         "Process market data and generate trading signals."
#         raise NotImplementedError("Subclasses must implement on_market_data method")

#     @abstractmethod
#     async def on_trade_update(self, trade: Dict[str, Any]):
#         "Handle trade execution updates."
#         raise NotImplementedError("Subclasses must implement on_trade_update method")

#     @abstractmethod
#     async def cleanup(self):
#         "Clean up strategy resources."
#         raise NotImplementedError("Subclasses must implement cleanup method")

#     async def start(self):
#         "Start strategy execution."
#         try:
#             if await self.initialize():
#                 self.state = StrategyState.RUNNING""
#                 logger.info(f"Strategy {self.strategy_id} started successfully")
#                 return True
#             else:
#                 self.state = StrategyState.ERROR""
#                 logger.error(f"Failed to initialize strategy {self.strategy_id}")
#                 return False
#         except Exception as e:
#             self.state = StrategyState.ERROR""
#             logger.error(f"Error starting strategy {self.strategy_id}: {e}")
#             return False

#     async def stop(self):
#         "Stop strategy execution."
#         try:
#             self.state = StrategyState.STOPPING
#             await self.cleanup()
#             self.state = StrategyState.STOPPED""
#             logger.info(f"Strategy {self.strategy_id} stopped successfully")
#             return True
#         except Exception as e:
#             self.state = StrategyState.ERROR""
#             logger.error(f"Error stopping strategy {self.strategy_id}: {e}")
#             return False

#     def update_metrics(
# self, trade_pnl: float = 0.0, is_winning_trade: bool = False
# ) -> None:"
#         "Update strategy performance metrics."
#         with self._lock:
#             if trade_pnl != 0.0:
#                 self.metrics.total_trades += 1
#                 self.metrics.total_pnl += trade_pnl
#                 if is_winning_trade:
#                     self.metrics.winning_trades += 1
#                 else:
#                     self.metrics.losing_trades += 1
#                 self.metrics.win_rate = (
#                     self.metrics.winning_trades / self.metrics.total_trades
#                     if self.metrics.total_trades > 0
# else 0.0
# )
#                 self.metrics.last_trade_time = datetime.now()

#             self.metrics.uptime = datetime.now() - self.start_time
#             self.last_update = datetime.now()


# @singleton
class StrategyRegistry:""
#     "Registry for managing strategy classes and instances."

#     def __init__(self):
#         self._strategy_classes: Dict[str, Type[BaseStrategy]] = {}
#         self._strategy_instances: Dict[str, BaseStrategy] = {}
#         self._lock = threading.RLock()

#     def register_strategy_class(
# self, name: str, strategy_class: Type[BaseStrategy]
# ) -> None:"
#         "Register a strategy class."
#         with self._lock:
#             self._strategy_classes[name] = strategy_class""
#             logger.info(f"Registered strategy class: {name}")

#     def get_strategy_class(self, name: str):
#         "Get a registered strategy class."
#         return self._strategy_classes.get(name)

#     def list_strategy_classes(self):
#         "List all registered strategy classes."
#         return list(self._strategy_classes.keys())

#     def register_strategy_instance(self, strategy: BaseStrategy):
#         "Register a strategy instance."
#         with self._lock:
#             self._strategy_instances[strategy.strategy_id] = strategy""
#             logger.info(f"Registered strategy instance: {strategy.strategy_id}")

#     def get_strategy_instance(self, strategy_id: str):
#         "Get a strategy instance."
#         return self._strategy_instances.get(strategy_id)

#     def remove_strategy_instance(self, strategy_id: str):
#         "Remove a strategy instance."
#         with self._lock:
#             if strategy_id in self._strategy_instances:
# del self._strategy_instances[strategy_id]"
#                 logger.info(f"Removed strategy instance: {strategy_id}")
#                 return True
#             return False

#     def list_strategy_instances(self):
#         "List all strategy instance IDs."
#         return list(self._strategy_instances.keys())


# @singleton
class StrategyEngine:""

# Core strategy engine for managing trading strategies.

# Provides dynamic loading, lifecycle management, and real-time monitoring
# of trading strategies with enterprise-grade reliability and performance."


#     def __init__(self):
#         self._registry = StrategyRegistry()
#         self._running_strategies: Dict[str, BaseStrategy] = {}
#         self._strategy_tasks: Dict[str, asyncio.Task] = {}
#         self._executor = ThreadPoolExecutor(max_workers=10)
#         self._event_bus = get_event_bus()
#         self._container = get_container()
#         self._health_monitor = HealthMonitor()
#         self._circuit_breaker = CircuitBreaker()
#         self._lock = threading.RLock()
#         self._shutdown_event = asyncio.Event()
#         self._monitoring_task: Optional[asyncio.Task] = None

#     async def initialize(self):
#         "Initialize the strategy engine."
#         try:
            # Start monitoring task
#             self._monitoring_task = asyncio.create_task(self._monitor_strategies())

            # Subscribe to relevant events
# await self._event_bus.subscribe(
#                 EventType.MARKET_DATA, self._handle_market_data, EventPriority.HIGH
# )

# await self._event_bus.subscribe(
#                 EventType.TRADE_UPDATE, self._handle_trade_update, EventPriority.HIGH
# )
# "
#             logger.info("Strategy engine initialized successfully")
#             return True

#         except Exception as e:""
#             logger.error(f"Failed to initialize strategy engine: {e}")
#             return False

#     async def shutdown(self):
#         "Shutdown the strategy engine."
#         try:
#             self._shutdown_event.set()

            # Stop all running strategies
#             await self._stop_all_strategies()

            # Cancel monitoring task
#             if self._monitoring_task:
#                 self._monitoring_task.cancel()
#                 try:
#                     await self._monitoring_task
#                 except asyncio.CancelledError:
# logger.debug("
#                         "Strategy engine monitoring task cancelled during shutdown"
# )

            # Shutdown executor
#             self._executor.shutdown(wait=True)
# "
#             logger.info("Strategy engine shutdown completed")

#         except Exception as e:""
#             logger.error(f"Error during strategy engine shutdown: {e}")

#     def load_strategy_from_file(self, file_path: str):
#         "Dynamically load a strategy from a Python file."
#         try:
#             file_path = Path(file_path)
#             if not file_path.exists():""
#                 logger.error(f"Strategy file not found: {file_path}")
#                 return False

            # Import the module
#             spec = importlib.util.spec_from_file_location(file_path.stem, file_path)
#             module = importlib.util.module_from_spec(spec)
#             spec.loader.exec_module(module)

            # Find strategy classes in the module
#             for name, obj in inspect.getmembers(module):
#                 if (
#                     inspect.isclass(obj)
# and issubclass(obj, BaseStrategy)
# and obj != BaseStrategy
# ):
#                     self._registry.register_strategy_class(name, obj)""
#                     logger.info(f"Loaded strategy class {name} from {file_path}")

#             return True

#         except Exception as e:""
#             logger.error(f"Failed to load strategy from {file_path}: {e}")
#             return False

#     async def create_strategy(
# self, strategy_name: str, config: StrategyConfig
# ) -> Optional[str]:"
#         "Create and initialize a new strategy instance."
#         try:
#             strategy_class = self._registry.get_strategy_class(strategy_name)
#             if not strategy_class:""
#                 logger.error(f"Strategy class not found: {strategy_name}")
#                 return None

            # Create strategy instance
#             strategy = strategy_class(config)

            # Register the instance
#             self._registry.register_strategy_instance(strategy)

            # Initialize the strategy
#             if await strategy.start():
#                 with self._lock:
#                     self._running_strategies[strategy.strategy_id] = strategy
# "
#                 logger.info(f"Created and started strategy: {strategy.strategy_id}")
#                 return strategy.strategy_id
#             else:""
#                 logger.error(f"Failed to start strategy: {strategy.strategy_id}")
#                 return None

#         except Exception as e:""
#             logger.error(f"Failed to create strategy {strategy_name}: {e}")
#             return None

#     async def stop_strategy(self, strategy_id: str):
#         "Stop a running strategy."
#         try:
#             with self._lock:
#                 strategy = self._running_strategies.get(strategy_id)
#                 if not strategy:""
#                     logger.warning(f"Strategy not found: {strategy_id}")
#                     return False

                # Stop the strategy
#                 if await strategy.stop():
#                     del self._running_strategies[strategy_id]
#                     self._registry.remove_strategy_instance(strategy_id)

                    # Cancel associated task if exists
#                     if strategy_id in self._strategy_tasks:
#                         self._strategy_tasks[strategy_id].cancel()
#                         del self._strategy_tasks[strategy_id]
# "
#                     logger.info(f"Stopped strategy: {strategy_id}")
#                     return True
#                 else:""
#                     logger.error(f"Failed to stop strategy: {strategy_id}")
#                     return False

#         except Exception as e:""
#             logger.error(f"Error stopping strategy {strategy_id}: {e}")
#             return False

#     async def _stop_all_strategies(self):
#         "Stop all running strategies."
#         strategy_ids = list(self._running_strategies.keys())
#         for strategy_id in strategy_ids:
#             await self.stop_strategy(strategy_id)

#     async def _handle_market_data(self, event: Event):
#         "Handle market data events and distribute to strategies."
#         try:
#             market_data = event.data

            # Distribute to all running strategies
#             for strategy in self._running_strategies.values():
#                 if strategy.state == StrategyState.RUNNING:
#                     try:
#                         signal = await strategy.on_market_data(market_data)
#                         if signal:
                            # Emit signal event
# await self._event_bus.emit(
#                                 EventType.STRATEGY_SIGNAL, signal, EventPriority.HIGH
# )
#                     except Exception as e:
# logger.error("
#                             f"Error in strategy {strategy.strategy_id} market data handler: {e}"
# )
#                         strategy.metrics.error_count += 1

#         except Exception as e:""
#             logger.error(f"Error handling market data event: {e}")

#     async def _handle_trade_update(self, event: Event):
#         "Handle trade update events and distribute to strategies."
#         try:
# trade_data = event.data"
#             strategy_id = trade_data.get("strategy_id")

#             if strategy_id and strategy_id in self._running_strategies:
#                 strategy = self._running_strategies[strategy_id]
#                 try:
#                     await strategy.on_trade_update(trade_data)
#                 except Exception as e:
# logger.error("
#                         f"Error in strategy {strategy_id} trade update handler: {e}"
# )
#                     strategy.metrics.error_count += 1

#         except Exception as e:""
#             logger.error(f"Error handling trade update event: {e}")

#     async def _monitor_strategies(self):
#         "Monitor strategy health and performance."
#         while not self._shutdown_event.is_set():
#             try:
#                 current_time = datetime.now()

#                 for strategy_id, strategy in list(self._running_strategies.items()):
                    # Check strategy health"
#                     if strategy.state == StrategyState.ERROR:""
#                         logger.warning(f"Strategy {strategy_id} is in error state")
#                         continue

                    # Update uptime
#                     strategy.metrics.uptime = current_time - strategy.start_time

                    # Check for stale strategies (no updates in 5 minutes)"
#                     if (current_time - strategy.last_update).total_seconds() > 300:""
#                         logger.warning(f"Strategy {strategy_id} appears stale")

                    # Emit metrics event
# await self._event_bus.emit(
#                         EventType.STRATEGY_METRICS, strategy.metrics, EventPriority.LOW
# )

#                 await asyncio.sleep(30)  # Monitor every 30 seconds

#             except asyncio.CancelledError:
#                 break
#             except Exception as e:""
#                 logger.error(f"Error in strategy monitoring: {e}")
#                 await asyncio.sleep(30)

#     def get_strategy_metrics(self, strategy_id: str):
#         "Get metrics for a specific strategy."
#         strategy = self._running_strategies.get(strategy_id)
#         return strategy.metrics if strategy else None

#     def get_all_strategy_metrics(self):
#         "Get metrics for all running strategies."
#         return {
#             strategy_id: strategy.metrics
#             for strategy_id, strategy in self._running_strategies.items()
# }

#     def list_running_strategies(self):
#         "List all running strategy IDs."
#         return list(self._running_strategies.keys())

#     def get_strategy_status(self, strategy_id: str):
#         "Get comprehensive status for a strategy."
#         strategy = self._running_strategies.get(strategy_id)
#         if not strategy:
#             return None

#         return {
# "strategy_id": strategy.strategy_id,"
# "name": strategy.config.name,"
# "type": strategy.config.strategy_type.value,"
# "state": strategy.state.value,"
# "uptime": strategy.metrics.uptime.total_seconds(),"
# "total_trades": strategy.metrics.total_trades,"
# "total_pnl": strategy.metrics.total_pnl,"
# "win_rate": strategy.metrics.win_rate,"
# "error_count": strategy.metrics.error_count,"
# "last_update": strategy.last_update.isoformat(),"
# "positions": strategy.positions.copy(),"
# "config": {
# "max_position_size": strategy.config.max_position_size,"
# "max_daily_loss": strategy.config.max_daily_loss,"
# "risk_level": strategy.config.risk_level.value,"
# "instruments": strategy.config.instruments,"
# "timeframes": strategy.config.timeframes,
# },
# }


# Global strategy engine instance
_strategy_engine: Optional[StrategyEngine] = None


# def get_strategy_engine():
#     "Get the global strategy engine instance."
#     global _strategy_engine
#     if _strategy_engine is None:
#         _strategy_engine = StrategyEngine()
#     return _strategy_engine


# Register with dependency injection container
# @injectable(ServiceLifetime.SINGLETON)
# def create_strategy_engine():
#     "Factory function for dependency injection."
#     return get_strategy_engine()
# "