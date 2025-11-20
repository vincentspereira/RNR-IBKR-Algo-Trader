import asyncio
import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union
import numpy as np
import pandas as pd
from ...indicators.consolidated_indicators import ConsolidatedIndicators

# Unified Base Strategy Implementation

# This module consolidates the two different BaseStrategy implementations into a single,
# cohesive base class that can work both independently and with NautilusTrader.
# This eliminates the confusion and architectural inconsistency identified in the analysis.

# Key Features:
# - Unified strategy interface that adapts to different contexts
# - Consolidated configuration management
# - Common signal generation and position sizing logic
# - Performance tracking and risk management
# - Support for both standalone and NautilusTrader-integrated usage

# Author: AI Assistant
# Date: 17 October 2025
# Version: 1.0.0"




# Try to import NautilusTrader - optional dependency
# try:
#     from nautilus_trader.model.data.bar import Bar
#     from nautilus_trader.model.data.tick import QuoteTick, TradeTick
#     from nautilus_trader.model.events.order import OrderEvent
#     from nautilus_trader.model.events.position import PositionEvent
#     from nautilus_trader.model.identifiers import InstrumentId, StrategyId
#     from nautilus_trader.model.instruments.base import Instrument
#     from nautilus_trader.model.orders.base import Order
#     from nautilus_trader.model.position import Position
#     from nautilus_trader.trading.strategy import Strategy
#     NAUTILUS_AVAILABLE = True
# except ImportError:
#     NAUTILUS_AVAILABLE = False
    # Create mock classes for type hints when Nautilus not available
#     class Bar: pass
#     class QuoteTick: pass
#     class TradeTick: pass
#     class OrderEvent: pass
#     class PositionEvent: pass
#     class InstrumentId: pass
#     class Instrument: pass
#     class Order: pass
#     class Position: pass
#     class Strategy: pass
#     class StrategyId: pass



class SignalType(Enum):""
# "Enumeration of trading signal types.
# "
#     BUY = "buy"
#     SELL = "sell"
#     HOLD = "hold"
#     CLOSE_LONG = "close_long"
#     CLOSE_SHORT = "close_short"


# "

class StrategyStatus(Enum):""
# "Strategy status enumeration.
# "
#     INITIALIZED = "initialized"
#     STARTING = "starting"
#     RUNNING = "running"
#     STOPPING = "stopping"
#     STOPPED = "stopped"
#     ERROR = "error"
#     PAUSED = "paused"
#     DEGRADED = "degraded"


# "

class PositionSide(Enum):""
# "Enumeration of position sides.
# "
#     LONG = "long"
#     SHORT = "short"
#     FLAT = "flat"


# "

class OrderType(Enum):""
# "Order types.
# "
#     MARKET = "market"
#     LIMIT = "limit"
#     STOP = "stop"
#     STOP_LIMIT = "stop_limit"


# "

class StrategyType(Enum):""
# "Strategy type enumeration.
# "
#     MOMENTUM = "momentum"
#     MEAN_REVERSION = "mean_reversion"
#     ARBITRAGE = "arbitrage"
#     MACHINE_LEARNING = "machine_learning"
#     MULTI_ASSET = "multi_asset"
#     VOLATILITY = "volatility"
#     PAIRS_TRADING = "pairs_trading"
#     STATISTICAL_ARBITRAGE = "statistical_arbitrage"
#     MARKET_MAKING = "market_making"
#     NEWS_BASED = "news_based"


# "

class PositionSizing(Enum):""
# "Position sizing method enumeration.
# "
#     FIXED = "fixed"
#     PERCENT_RISK = "percent_risk"
#     VOLATILITY_ADJUSTED = "volatility_adjusted"
#     KELLY_CRITERION = "kelly_criterion"
#     OPTIMAL_F = "optimal_f"
#     EQUAL_WEIGHT = "equal_weight"
#     RISK_PARITY = "risk_parity"


# "

# @dataclass
class Signal:""
#     "Trading signal with metadata."

#     signal_type: SignalType
#     timestamp: datetime
#     symbol: str
#     price: float
#     quantity: Optional[float] = None
#     confidence: float = 1.0
#     strength: float = 1.0
#     metadata: Dict[str, Any] = field(default_factory=dict)
#     order_type: OrderType = OrderType.MARKET
#     stop_loss: Optional[float] = None
#     take_profit: Optional[float] = None

#     def __post_init__(self):
# "Validate signal after initialization.
#         if not 0 <= self.confidence <= 1:""
#             raise ValueError("Confidence must be between 0 and 1")
#         if not 0 <= self.strength <= 1:""
#             raise ValueError("Strength must be between 0 and 1")
#         if self.price <= 0:""
#             raise ValueError("Price must be positive")


# "

# @dataclass
class UnifiedPosition:""
#     "Represents a trading position with P&L tracking."

#     symbol: str
#     side: PositionSide
#     quantity: float
#     entry_price: float
#     entry_time: datetime
#     current_price: Optional[float] = None
#     unrealized_pnl: float = 0.0
#     realized_pnl: float = 0.0
#     stop_loss: Optional[float] = None
#     take_profit: Optional[float] = None
#     metadata: Dict[str, Any] = field(default_factory=dict)

#     @property
#     def market_value(self):
#         "Calculate current market value of the position."
#         if self.current_price is None:
#             return self.quantity * self.entry_price
#         return self.quantity * self.current_price

#     @property
#     def pnl(self):
#         "Calculate total profit and loss."
#         return self.realized_pnl + self.unrealized_pnl

#     def update_price(self, new_price: float):
# "Update current price and recalculate unrealized P&L.
#         if new_price <= 0:""
#             raise ValueError("Price must be positive")

#         self.current_price = new_price
#         if self.side == PositionSide.LONG:
#             self.unrealized_pnl = self.quantity * (new_price - self.entry_price)
#         elif self.side == PositionSide.SHORT:
#             self.unrealized_pnl = self.quantity * (self.entry_price - new_price)


# "

# @dataclass
class RiskParameters:""
#     "Risk management parameters."

    # Position sizing
#     max_position_size: float = 0.1
#     max_portfolio_risk: float = 0.02
#     position_sizing_method: PositionSizing = PositionSizing.PERCENT_RISK

    # Stop losses and take profits
#     stop_loss_pct: Optional[float] = None
#     take_profit_pct: Optional[float] = None
#     trailing_stop_pct: Optional[float] = None

    # Risk limits
#     max_daily_loss: float = 0.05
#     max_drawdown: float = 0.15
#     max_consecutive_losses: int = 5

    # Exposure limits
#     max_sector_exposure: float = 0.3
#     max_single_position: float = 0.1
#     max_correlation: float = 0.7

    # Time-based limits
#     max_holding_period: Optional[int] = None
#     min_holding_period: Optional[int] = None

    # Volatility adjustments
#     volatility_lookback: int = 20
#     volatility_target: Optional[float] = None

    # Emergency controls
#     circuit_breaker_threshold: float = 0.1
#     emergency_liquidation: bool = True


# @dataclass
class StrategyMetrics:""
#     "Strategy performance metrics."

    # Basic metrics
#     total_return: float = 0.0
#     annualized_return: float = 0.0
#     volatility: float = 0.0
#     sharpe_ratio: float = 0.0
#     sortino_ratio: float = 0.0
#     calmar_ratio: float = 0.0

    # Risk metrics
#     max_drawdown: float = 0.0
#     var_95: float = 0.0
#     cvar_95: float = 0.0
#     beta: float = 0.0
#     alpha: float = 0.0

    # Trade metrics
#     total_trades: int = 0
#     winning_trades: int = 0
#     losing_trades: int = 0
#     win_rate: float = 0.0
#     avg_win: float = 0.0
#     avg_loss: float = 0.0
#     profit_factor: float = 0.0

    # Real-time metrics
#     current_drawdown: float = 0.0
#     days_since_high: int = 0
#     consecutive_losses: int = 0
#     daily_pnl: float = 0.0

    # Timestamps
#     last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
#     start_date: Optional[datetime] = None
#     end_date: Optional[datetime] = None


# @dataclass
class UnifiedStrategyConfig:""
#     "Unified configuration for trading strategies."

    # Basic configuration"
# strategy_id: str = field(default_factory=lambda: str(uuid.uuid4()))"
# strategy_name: str = "UnifiedStrategy
# strategy_type: StrategyType = StrategyType.MOMENTUM"
# description: str = "
#     version: str = "1.0.0"
# "
    # Instruments and markets
#     symbols: List[str] = field(default_factory=list)
#     primary_instrument: Optional[str] = None
#     market_hours_only: bool = True
#     supported_venues: List[str] = field(default_factory=list)
# "
    # Timeframes and data"
#     timeframe: str = "1D"
#     lookback_period: int = 252
#     warmup_periods: int = 50
# "
    # Risk management
#     risk_parameters: RiskParameters = field(default_factory=RiskParameters)
#     max_position_size: float = 0.1  # Legacy field
#     risk_per_trade: float = 0.02
#     max_positions: int = 10
# "
    # Strategy-specific parameters
#     parameters: Dict[str, Any] = field(default_factory=dict)
# "
    # Monitoring and alerting"
# enable_monitoring: bool = True"
#     log_level: str = "INFO"
#     debug_mode: bool = False
# "
    # Backtesting configuration
#     initial_capital: float = 100000.0
#     paper_trading: bool = True
#     live_trading_enabled: bool = False

    # Integration settings
#     use_nautilus_trader: bool = False
#     kafka_topics: List[str] = field(default_factory=list)
#     database_config: Dict[str, Any] = field(default_factory=dict)

# "

#     def __post_init__(self):
# "Validate configuration.
#         if not 0 < self.max_position_size <= 1:""
#             raise ValueError("max_position_size must be between 0 and 1")
#         if not 0 < self.risk_per_trade <= 1:""
#             raise ValueError("risk_per_trade must be between 0 and 1")
#         if self.max_positions <= 0:""
#             raise ValueError("max_positions must be positive")


# "

class UnifiedBaseStrategy(ABC):""

# Unified base class for all trading strategies.

# This class provides a single, consistent interface for strategy development
# that works both independently and with NautilusTrader integration."


#     def __init__(self, config: UnifiedStrategyConfig):
# "Initialize the unified base strategy.
#         if not isinstance(config, UnifiedStrategyConfig):""
#             raise TypeError("config must be a UnifiedStrategyConfig instance")
# "
#         self.config = config
#         self.use_nautilus = config.use_nautilus_trader and NAUTILUS_AVAILABLE
# "
        # Set up logger"
#         self.logger = logging.getLogger(""
#             f"{self.__class__.__name__}.{config.strategy_id}"
# )
# "
        # Strategy state
#         self.is_initialized = False
#         self._status = StrategyStatus.INITIALIZED
#         self._start_time: Optional[datetime] = None
#         self._stop_time: Optional[datetime] = None
# "
        # Trading components
#         self.positions: Dict[str, UnifiedPosition] = {}
#         self.signals: List[Signal] = []
#         self.state: Dict[str, Any] = {}
# "
        # Performance tracking
#         self.performance_metrics: Dict[str, float] = {}
#         self.metrics = StrategyMetrics()
# "
        # Risk management
#         self._trade_history: List[Dict[str, Any]] = []
#         self._signal_history: List[Dict[str, Any]] = []
#         self._daily_pnl = 0.0
#         self._peak_equity = config.initial_capital
#         self._current_drawdown = 0.0
# "
        # Data management
#         self._bars: Dict[str, pd.DataFrame] = {}
#         self._indicators: Dict[str, Any] = {}
# "
        # Event handlers
#         self._event_handlers: Dict[str, List[Callable]] = {}
# "
        # Initialize technical indicators
#         try:
#             self.indicators = ConsolidatedIndicators()
#         except Exception as e:
#             self.indicators = None""
#             self.logger.warning(f"Could not initialize indicators: {e}")
# "
        # NautilusTrader-specific initialization
#         if self.use_nautilus:
#             self.strategy_id = StrategyId(config.strategy_id)
            # Initialize NautilusTrader base class if available
#             if NAUTILUS_AVAILABLE:
#                 super().__init__(config=config.parameters)
# "
        # Initialize components
#         self._initialize_risk_management()
#         self._initialize_indicators()
#         self._initialize_event_handlers()

    # Abstract methods - must be implemented by subclasses

# "

#     @abstractmethod
#     async def on_start(self):
#         "Called when strategy starts."
#         raise NotImplementedError("Subclasses must implement on_start method")

#     @abstractmethod
#     async def on_stop(self):
#         "Called when strategy stops."
#         raise NotImplementedError("Subclasses must implement on_stop method")

#     @abstractmethod
#     async def generate_signals(self, data: pd.DataFrame):
#         "Generate trading signals based on market data."
#         raise NotImplementedError("Subclasses must implement generate_signals method")

#     @abstractmethod
#     async def calculate_position_size(self, signal: Signal, portfolio_value: float):
#         "Calculate appropriate position size for a trading signal."
#         raise NotImplementedError("Subclasses must implement calculate_position_size method")

    # Optional abstract methods for NautilusTrader integration"
#     async def on_bar(self, bar: Union[Bar, pd.Series]):
#         "Process new bar data and generate signals."
#         if isinstance(bar, Bar):
            # Convert NautilusTrader Bar to pandas Series
# bar_data = pd.Series({
# 'open': bar.open,'
# 'high': bar.high,'
# 'low': bar.low,'
# 'close': bar.close,'
# 'volume': bar.volume,'
# 'timestamp': bar.ts_event
# })
#             return await self.generate_signals(pd.DataFrame([bar_data]))
#         else:
            # Handle pandas Series
#             df = pd.DataFrame([bar])
#             return await self.generate_signals(df)

#     async def on_quote_tick(self, tick: QuoteTick):
#         "Process new quote tick - optional implementation."
#         return []

#     async def on_trade_tick(self, tick: TradeTick):
#         "Process new trade tick - optional implementation."
#         return []

    # Common initialization and lifecycle methods

#     async def initialize(self, data: pd.DataFrame):
#         "Initialize strategy with historical data."
#         try:
            # Validate input data"
#             if data is None or data.empty:""
#                 raise ValueError("Data cannot be None or empty")
# "
#             required_columns = ["open", "high", "low", "close", "volume"]
# missing_columns = [
# col for col in required_columns if col not in data.columns
# ]
#             if missing_columns:""
#                 raise ValueError(f"Missing required columns: {missing_columns}")

#             if len(data) < self.config.lookback_period:
# raise ValueError("
#                     f"Insufficient data: need at least {self.config.lookback_period} periods"
# )

            # Initialize strategy state"
#             self.state = {
# "last_update": datetime.now(),"
# "data_length": len(data),"
# "symbols_initialized": set(),"
# "warmup_complete": False,
# }

            # Initialize indicators if available
#             if self.indicators:
#                 try:
#                     for symbol in self.config.symbols:""
#                         if symbol in data.columns or "symbol" in data.columns:
# symbol_data = (
# data"
#                                 if "symbol" not in data.columns""
# else data[data["symbol"] == symbol]
# )
#                             if not symbol_data.empty:
#                                 self.indicators.update_all(
#                                     symbol_data.iloc[-1].to_dict()
# )"
#                                 self.state["symbols_initialized"].add(symbol)
#                 except Exception as e:""
#                     self.logger.warning(f"Could not initialize indicators: {e}")

            # Initialize performance tracking"
#             self.performance_metrics = {
# "total_trades": 0,"
# "winning_trades": 0,"
# "losing_trades": 0,"
# "total_pnl": 0.0,"
# "max_drawdown": 0.0,"
# "sharpe_ratio": 0.0,"
# "win_rate": 0.0,
# }

            # Mark as initialized"
#             self.is_initialized = True""
#             self.state["warmup_complete"] = True""
#             self.logger.info("Strategy initialized successfully")

#         except Exception as e:
#             self.is_initialized = False""
#             raise ValueError(f"Failed to initialize strategy: {e}")

#     async def start_strategy(self):
#         "Start the strategy."
#         try:
#             self._status = StrategyStatus.STARTING
#             self._start_time = datetime.now(timezone.utc)
# "
#             self.logger.info(f"Starting strategy: {self.config.strategy_name}")

            # Call strategy-specific start logic
#             await self.on_start()

#             self._status = StrategyStatus.RUNNING""
#             self.logger.info("Strategy started successfully")

            # Emit event"
# await self._emit_event("
#                 "strategy_started",
# {
# "strategy_id": self.config.strategy_id,"
# "start_time": self._start_time,
# },
# )

#         except Exception as e:
#             self._status = StrategyStatus.ERROR""
#             self.logger.error(f"Error starting strategy: {e}")
#             raise

#     async def stop_strategy(self):
#         "Stop the strategy."
#         try:
#             self._status = StrategyStatus.STOPPING
#             self._stop_time = datetime.now(timezone.utc)
# "
#             self.logger.info("Stopping strategy")

            # Close all positions if configured
#             if self.config.risk_parameters.emergency_liquidation:
#                 await self._emergency_liquidation()

            # Call strategy-specific stop logic
#             await self.on_stop()

#             self._status = StrategyStatus.STOPPED""
#             self.logger.info("Strategy stopped successfully")

            # Emit event"
# await self._emit_event("
#                 "strategy_stopped",
# {
# "strategy_id": self.config.strategy_id,"
# "stop_time": self._stop_time,"
# "final_metrics": self.metrics,
# },
# )

#         except Exception as e:
#             self._status = StrategyStatus.ERROR""
#             self.logger.error(f"Error stopping strategy: {e}")
#             raise

    # Position and signal management

#     def update_positions(self, market_data: Dict[str, float]):
#         "Update all positions with current market prices."
#         for symbol, position in self.positions.items():
#             if symbol in market_data:
#                 position.update_price(market_data[symbol])

#     def get_portfolio_value(self, market_data: Dict[str, float]):
#         "Calculate total portfolio value."
#         total_value = 0.0
#         for position in self.positions.values():
#             if position.symbol in market_data:
#                 position.update_price(market_data[position.symbol])
#                 total_value += position.market_value
#         return total_value

#     def get_performance_summary(self):
#         "Get performance summary statistics."
#         total_pnl = sum(pos.pnl for pos in self.positions.values())
#         total_positions = len(self.positions)

#         return {
# "total_pnl": total_pnl,"
# "total_positions": total_positions,"
# "avg_pnl_per_position": total_pnl / max(total_positions, 1),
# **self.performance_metrics,
# }

#     def reset(self):
#         "Reset strategy state."
#         self.positions.clear()
#         self.signals.clear()
#         self.performance_metrics.clear()
#         self.state.clear()
#         self._trade_history.clear()
#         self._signal_history.clear()
#         self.is_initialized = False
#         self._status = StrategyStatus.INITIALIZED

    # Risk management methods

#     def _initialize_risk_management(self):
#         "Initialize risk management components."
#         self.logger.debug("Initializing risk management")

#         self._risk_checks = {
# "position_size": self._check_position_size,"
# "portfolio_risk": self._check_portfolio_risk,"
# "daily_loss": self._check_daily_loss,"
# "drawdown": self._check_drawdown,"
# "correlation": self._check_correlation,
# }

#     async def _check_risk_limits(self, signal: Signal):
#         "Check if signal passes risk limits."
#         try:
#             for check_name, check_func in self._risk_checks.items():
#                 if not await check_func(signal):""
#                     self.logger.warning(f"Risk check failed: {check_name}")
#                     return False
#             return True
#         except Exception as e:""
#             self.logger.error(f"Error in risk check: {e}")
#             return False

#     async def _check_position_size(self, signal: Signal):
#         "Check position size limits."
#         max_size = self.config.risk_parameters.max_position_size
        # Simple check - would be enhanced with actual position calculation
#         return max_size <= 1.0

#     async def _check_portfolio_risk(self, signal: Signal):
#         "Check portfolio risk limits."
#         return True  # Implementation depends on portfolio manager integration

#     async def _check_daily_loss(self, signal: Signal):
#         "Check daily loss limits."
#         max_daily_loss = self.config.risk_parameters.max_daily_loss
#         current_loss = abs(self._daily_pnl) / self.config.initial_capital
#         return current_loss <= max_daily_loss

#     async def _check_drawdown(self, signal: Signal):
#         "Check drawdown limits."
#         max_drawdown = self.config.risk_parameters.max_drawdown
#         return self._current_drawdown <= max_drawdown

#     async def _check_correlation(self, signal: Signal):
#         "Check correlation limits."
#         return True  # Implementation depends on correlation calculation

#     async def _emergency_liquidation(self):
#         "Emergency liquidation of all positions."
#         self.logger.warning("Initiating emergency liquidation")
#         self.positions.clear()

    # Event handling methods

#     def _initialize_event_handlers(self):
# "Initialize event handlers.
#         self._event_handlers = {""
# "strategy_started": [],"
# "strategy_stopped": [],"
# "signal_generated": [],"
# "order_placed": [],"
# "position_opened": [],"
# "position_closed": [],"
# "risk_limit_breached": [],"
# "error_occurred": [],
# }

# "

#     def _initialize_indicators(self):
#         "Initialize technical indicators."
#         self.logger.debug("Initializing indicators")
#         self._indicators = {}

#     async def _emit_event(self, event_type: str, data: Dict[str, Any]):
#         "Emit strategy event."
#         try:
#             for handler in self._event_handlers.get(event_type, []):
#                 if asyncio.iscoroutinefunction(handler):
#                     await handler(data)
#                 else:
#                     handler(data)
#         except Exception as e:""
#             self.logger.error(f"Error emitting event {event_type}: {e}")

    # Utility methods

#     def get_status(self):
#         "Get current strategy status."
#         return self._status

#     def get_metrics(self):
#         "Get current strategy metrics."
#         return self.metrics

#     def add_event_handler(self, event_type: str, handler: Callable):
#         "Add event handler."
#         if event_type in self._event_handlers:
#             self._event_handlers[event_type].append(handler)

#     def remove_event_handler(self, event_type: str, handler: Callable):
#         "Remove event handler."
#         if (
#             event_type in self._event_handlers
# and handler in self._event_handlers[event_type]
# ):
#             self._event_handlers[event_type].remove(handler)


# Utility functions

# def create_signal(
# signal_type: SignalType,
# symbol: str,
# price: float,
#     timestamp: Optional[datetime] = None,
# **kwargs,
# ) -> Signal:"
#     "Convenience function to create a trading signal."
#     if timestamp is None:
#         timestamp = datetime.now()

#     return Signal(
#         signal_type=signal_type,
#         timestamp=timestamp,
#         symbol=symbol,
#         price=price,
# **kwargs,
# )


# def validate_ohlcv_data(data: pd.DataFrame):
#     "Validate OHLCV data format."
#     required_columns = ["open", "high", "low", "close", "volume"]

    # Check if all required columns exist
#     if not all(col in data.columns for col in required_columns):
#         return False

    # Check for valid price relationships"
#     if not (data["high"] >= data["low"]).all():
#         return False
# "
#     if not (data["high"] >= data["open"]).all():
#         return False
# "
#     if not (data["high"] >= data["close"]).all():
#         return False
# "
#     if not (data["low"] <= data["open"]).all():
#         return False
# "
#     if not (data["low"] <= data["close"]).all():
#         return False

    # Check for positive values"
#     if not (data[["open", "high", "low", "close", "volume"]] > 0).all().all():
#         return False

#     return True


# Backward compatibility aliases
BaseStrategy = UnifiedBaseStrategy
# StrategyConfig = UnifiedStrategyConfig"'"'