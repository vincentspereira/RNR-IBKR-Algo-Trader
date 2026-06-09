import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Deque, Dict, List, Optional, Tuple, Union
import numpy as np
import pandas as pd
#!/usr/bin/env python3

# Order Flow Scalping Strategy Implementation

# This module implements an advanced order flow scalping strategy that analyzes
# Level II market data, order book dynamics, and institutional flow patterns.

# Features:
# - Level II order book analysis
# - Institutional order flow detection
# - Market maker vs. taker identification
# - Liquidity pool analysis
# - Smart money tracking
# - Ultra-low latency execution

# ""Author: Algorithmic Trading System"
# Version: 1.0.0
# Date: 15 October 2025"




# Import base strategy components
# try:
#     from ..core.base_institutional_strategy import ()
#         BaseInstitutionalStrategy,
#         ExecutionOrder,
#         MarketRegime,
#         PerformanceMetrics,
#         RiskLevel,
#         RiskMetrics,
#         SignalData,
#         SignalType,
#         StrategyState,
# )
#     from .scalping_strategy import MarketMicrostructure, ScalpingMode, ScalpingSignal
# except ImportError:
    # Fallback for development
#     from dataclasses import dataclass
#     from enum import Enum

#     class StrategyState(Enum):""
#         INACTIVE = "inactive"
#         ACTIVE = "active"
#         PAUSED = "paused"

# "

#     class SignalType(Enum):""
#         BUY = "buy"
#         SELL = "sell"
#         HOLD = "hold"


# "

class OrderFlowType(Enum):""
# "Types of order flow patterns
# "
#     AGGRESSIVE_BUYING = "aggressive_buying"
#     AGGRESSIVE_SELLING = "aggressive_selling"
#     PASSIVE_ACCUMULATION = "passive_accumulation"
#     PASSIVE_DISTRIBUTION = "passive_distribution"
#     ICEBERG_BUYING = "iceberg_buying"
#     ICEBERG_SELLING = "iceberg_selling"
#     SWEEP_BUYING = "sweep_buying"
#     SWEEP_SELLING = "sweep_selling"


# "

class LiquidityType(Enum):""
# "Types of liquidity conditions
# "
#     HIGH_LIQUIDITY = "high_liquidity"
#     MEDIUM_LIQUIDITY = "medium_liquidity"
#     LOW_LIQUIDITY = "low_liquidity"
#     FRAGMENTED = "fragmented"
#     CONCENTRATED = "concentrated"


# "

class InstitutionalActivity(Enum):""
# "Types of institutional activity
# "
#     ACCUMULATION = "accumulation"
#     DISTRIBUTION = "distribution"
#     ROTATION = "rotation"
#     HEDGING = "hedging"
#     ARBITRAGE = "arbitrage"
#     NONE = "none"


# "

# @dataclass
class OrderBookLevel:""
#     "Individual order book level data"

#     price: Decimal
#     size: int
#     orders: int
#     timestamp: datetime
#     side: str  # 'bid' or 'ask'


# @dataclass
class OrderBookSnapshot:""
#     "Complete order book snapshot"

#     timestamp: datetime
#     bids: List[OrderBookLevel]
#     asks: List[OrderBookLevel]
#     spread: Decimal
#     mid_price: Decimal
#     total_bid_size: int
#     total_ask_size: int
#     imbalance: float  # (bid_size - ask_size) / (bid_size + ask_size)


# @dataclass
class TradeExecution:""
#     "Individual trade execution data"

#     timestamp: datetime
# price: Decimal'
# size: int'
#     side: str  # 'buy' or 'sell'
#     aggressor: str  # 'buyer' or 'seller'
#     venue: str
#     trade_id: str


# '

# @dataclass
class OrderFlowMetrics:""
#     "Order flow analysis metrics"

#     buy_volume: int
#     sell_volume: int
#     net_volume: int
#     volume_imbalance: float
#     aggressive_buy_ratio: float
#     aggressive_sell_ratio: float
#     average_trade_size: float
#     large_trade_count: int
#     institutional_flow_score: float
#     liquidity_score: float


# @dataclass
class OrderFlowScalpingConfig:""
#     "Configuration for order flow scalping strategy"

    # Order book parameters
#     order_book_depth: int = 10  # Number of levels to analyze
#     min_spread_bps: int = 1  # Minimum spread in basis points
#     max_spread_bps: int = 50  # Maximum spread in basis points

    # Flow detection parameters
#     large_trade_threshold: int = 10000  # Size threshold for large trades
#     institutional_threshold: float = 0.7  # Threshold for institutional activity
#     imbalance_threshold: float = 0.3  # Order book imbalance threshold

    # Execution parameters
#     max_position_size: float = 0.005  # 0.5% of account per trade
#     entry_timeout_ms: int = 100  # Maximum time to enter position
#     exit_timeout_ms: int = 200  # Maximum time to exit position

    # Risk management
#     max_adverse_ticks: int = 3  # Maximum adverse price movement
#     profit_target_ticks: int = 5  # Profit target in ticks
#     max_hold_time_seconds: int = 30  # Maximum hold time

    # Market making parameters
#     make_spread_bps: int = 2  # Spread for market making
#     min_edge_bps: int = 1  # Minimum edge required

    # Smart money detection
#     block_size_threshold: int = 50000  # Block trade size threshold
#     iceberg_detection_window: int = 10  # Window for iceberg detection
#     sweep_detection_levels: int = 3  # Levels for sweep detection


class OrderFlowScalpingStrategy(BaseInstitutionalStrategy):""

# Order Flow Scalping Strategy

# Implements ultra-high-frequency scalping based on:
# - Level II order book analysis
# - Institutional order flow detection
# - Market microstructure patterns
# - Smart money tracking
# - Liquidity provision and taking"


#     def __init__(self, config: OrderFlowScalpingConfig):
#         "Initialize order flow scalping strategy"
#         super().__init__()
#         self.config = config
#         self.logger = logging.getLogger(self.__class__.__name__)

        # Strategy state
#         self.state = StrategyState.INACTIVE
#         self.current_position = 0
#         self.entry_price: Optional[Decimal] = None
#         self.entry_time: Optional[datetime] = None

        # Order book tracking
#         self.order_book_history: Deque[OrderBookSnapshot] = deque(maxlen=1000)
#         self.trade_history: Deque[TradeExecution] = deque(maxlen=5000)

        # Flow analysis
#         self.flow_metrics_history: Deque[OrderFlowMetrics] = deque(maxlen=100)
#         self.institutional_activity: Dict[str, InstitutionalActivity] = {}

        # Smart money tracking
#         self.large_orders: List[TradeExecution] = []
#         self.iceberg_orders: Dict[Decimal, List[datetime]] = defaultdict(list)
#         self.sweep_patterns: List[Dict] = []

        # Performance tracking"
#         self.trades_today = 0""
#         self.pnl_today = Decimal("0")
#         self.win_rate = 0.0
#         self.avg_hold_time = 0.0
# "
#         self.logger.info("Order flow scalping strategy initialized")

#     def process_order_book_update(self, order_book: OrderBookSnapshot):
#         "Process incoming order book update"
#         try:
            # Store order book snapshot
#             self.order_book_history.append(order_book)

            # Analyze order book changes
#             if len(self.order_book_history) >= 2:
#                 self._analyze_order_book_changes()

            # Update flow metrics
#             self._update_flow_metrics()

            # Detect institutional activity
#             self._detect_institutional_activity()

#         except Exception as e:""
#             self.logger.error(f"Error processing order book update: {e}")

#     def process_trade_execution(self, trade: TradeExecution):
#         "Process incoming trade execution"
#         try:
            # Store trade execution
#             self.trade_history.append(trade)

            # Analyze trade patterns
#             self._analyze_trade_patterns(trade)

            # Detect large orders and smart money
#             if trade.size >= self.config.large_trade_threshold:
#                 self.large_orders.append(trade)
#                 self._detect_smart_money_patterns(trade)

            # Update institutional flow scoring
#             self._update_institutional_flow_score()

#         except Exception as e:""
#             self.logger.error(f"Error processing trade execution: {e}")

#     def _analyze_order_book_changes(self):
#         "Analyze changes in order book structure"
#         try:
#             current_book = self.order_book_history[-1]
#             previous_book = self.order_book_history[-2]

            # Detect iceberg orders
#             self._detect_iceberg_orders(current_book, previous_book)

            # Detect order book sweeps
#             self._detect_order_sweeps(current_book, previous_book)

            # Analyze liquidity changes
#             self._analyze_liquidity_changes(current_book, previous_book)

#         except Exception as e:""
#             self.logger.error(f"Error analyzing order book changes: {e}")

#     def _detect_iceberg_orders(
# self, current: OrderBookSnapshot, previous: OrderBookSnapshot
# ):"
#         "Detect iceberg order patterns"
#         try:
            # Look for consistent size at same price level
#             for current_bid in current.bids[:5]:  # Top 5 levels
                # Find matching price in previous book
# matching_previous = next(
#                     (bid for bid in previous.bids if bid.price == current_bid.price),
#                     None,
# )

#                 if matching_previous and current_bid.size == matching_previous.size:
                    # Potential iceberg - same size maintained
#                     self.iceberg_orders[current_bid.price].append(current.timestamp)

                    # Clean old timestamps
# cutoff_time = current.timestamp - timedelta(
#                         seconds=self.config.iceberg_detection_window
# )
#                     self.iceberg_orders[current_bid.price] = [
#                         ts
#                         for ts in self.iceberg_orders[current_bid.price]
#                         if ts > cutoff_time
# ]

            # Same for asks
#             for current_ask in current.asks[:5]:
# matching_previous = next(
#                     (ask for ask in previous.asks if ask.price == current_ask.price),
#                     None,
# )

#                 if matching_previous and current_ask.size == matching_previous.size:
#                     self.iceberg_orders[current_ask.price].append(current.timestamp)

# cutoff_time = current.timestamp - timedelta(
#                         seconds=self.config.iceberg_detection_window
# )
#                     self.iceberg_orders[current_ask.price] = [
#                         ts
#                         for ts in self.iceberg_orders[current_ask.price]
#                         if ts > cutoff_time
# ]

#         except Exception as e:""
#             self.logger.error(f"Error detecting iceberg orders: {e}")

#     def _detect_order_sweeps(
# self, current: OrderBookSnapshot, previous: OrderBookSnapshot
# ):"
#         "Detect order book sweep patterns"
#         try:
            # Detect bid sweeps (aggressive selling)
#             bid_levels_removed = 0
#             for prev_bid in previous.bids[: self.config.sweep_detection_levels]:
#                 if not any(bid.price >= prev_bid.price for bid in current.bids):
#                     bid_levels_removed += 1

#             if bid_levels_removed >= 2:
#                 self.sweep_patterns.append(
# {"
# "type": "bid_sweep","
# "timestamp": current.timestamp,"
# "levels_removed": bid_levels_removed,"
# "direction": "bearish",
# }
# )

            # Detect ask sweeps (aggressive buying)
#             ask_levels_removed = 0
#             for prev_ask in previous.asks[: self.config.sweep_detection_levels]:
#                 if not any(ask.price <= prev_ask.price for ask in current.asks):
#                     ask_levels_removed += 1

#             if ask_levels_removed >= 2:
#                 self.sweep_patterns.append(
# {
# "type": "ask_sweep","
# "timestamp": current.timestamp,"
# "levels_removed": ask_levels_removed,"
# "direction": "bullish",
# }
# )

            # Keep only recent sweep patterns
#             cutoff_time = current.timestamp - timedelta(seconds=60)
#             self.sweep_patterns = [
#                 pattern
#                 for pattern in self.sweep_patterns""
#                 if pattern["timestamp"] > cutoff_time
# ]

#         except Exception as e:""
#             self.logger.error(f"Error detecting order sweeps: {e}")

#     def _analyze_liquidity_changes(
# self, current: OrderBookSnapshot, previous: OrderBookSnapshot
# ):"
#         "Analyze changes in market liquidity"
#         try:
            # Calculate liquidity metrics
# current_liquidity = sum(level.size for level in current.bids[:5]) + sum(
# level.size for level in current.asks[:5]
# )

# previous_liquidity = sum(level.size for level in previous.bids[:5]) + sum(
# level.size for level in previous.asks[:5]
# )

# liquidity_change = (
#                 (current_liquidity - previous_liquidity) / previous_liquidity
#                 if previous_liquidity > 0
# else 0
# )

            # Detect significant liquidity changes
#             if abs(liquidity_change) > 0.2:  # 20% change
#                 self.logger.info(""
#                     f"Significant liquidity change: {liquidity_change:.2%}"
# )

#         except Exception as e:""
#             self.logger.error(f"Error analyzing liquidity changes: {e}")

#     def _analyze_trade_patterns(self, trade: TradeExecution):
#         "Analyze individual trade for patterns"
#         try:
            # Classify trade aggressiveness
#             if len(self.order_book_history) > 0:
#                 current_book = self.order_book_history[-1]

                # Determine if trade was at bid, ask, or mid"
# best_bid = ("
#                     current_book.bids[0].price if current_book.bids else Decimal("0")
# )
# best_ask = (
#                     current_book.asks[0].price
#                     if current_book.asks""
# else Decimal("999999")
# )

#                 if trade.price <= best_bid:""
# trade.aggressor = "seller
#                 elif trade.price >= best_ask:""
# trade.aggressor = "buyer
#                 else:""
#                     trade.aggressor = "unknown"

#         except Exception as e:""
#             self.logger.error(f"Error analyzing trade patterns: {e}")

#     def _detect_smart_money_patterns(self, trade: TradeExecution):
#         "Detect smart money activity patterns"
#         try:
            # Block trade detection"
#             if trade.size >= self.config.block_size_threshold:""
#                 self.logger.info(f"Block trade detected: {trade.size} @ {trade.price}")

            # Time-based clustering of large trades
# recent_large_trades = [
#                 t
#                 for t in self.large_orders
#                 if (trade.timestamp - t.timestamp).total_seconds() <= 300  # 5 minutes
# ]

#             if len(recent_large_trades) >= 3:
                # Multiple large trades in short time - potential institutional activity
#                 total_volume = sum(t.size for t in recent_large_trades)
# avg_price = (
#                     sum(float(t.price) * t.size for t in recent_large_trades)
# / total_volume
# )

#                 self.logger.info(""
#                     f"Institutional activity detected: {len(recent_large_trades)} trades, "
#                     f"total volume: {total_volume}, avg price: {avg_price:.2f}"
# )

#         except Exception as e:""
#             self.logger.error(f"Error detecting smart money patterns: {e}")

# "

#     def _update_flow_metrics(self):
#         "Update order flow metrics"
#         try:
#             if len(self.trade_history) < 10:
#                 return

            # Analyze recent trades (last 1 minute)
#             current_time = datetime.now()
# recent_trades = [
#                 trade
#                 for trade in self.trade_history
#                 if (current_time - trade.timestamp).total_seconds() <= 60
# ]

#             if not recent_trades:
#                 return

            # Calculate flow metrics"
# buy_volume = sum("
# trade.size for trade in recent_trades if trade.aggressor == "buyer"
# )
# sell_volume = sum("
# trade.size for trade in recent_trades if trade.aggressor == "seller"
# )
#             total_volume = buy_volume + sell_volume

#             if total_volume == 0:
#                 return

#             net_volume = buy_volume - sell_volume
#             volume_imbalance = net_volume / total_volume

#             aggressive_buy_ratio = buy_volume / total_volume
#             aggressive_sell_ratio = sell_volume / total_volume

#             average_trade_size = total_volume / len(recent_trades)
# large_trade_count = sum(
#                 1
#                 for trade in recent_trades
#                 if trade.size >= self.config.large_trade_threshold
# )

            # Calculate institutional flow score
# institutional_flow_score = self._calculate_institutional_flow_score(
#                 recent_trades
# )

            # Calculate liquidity score
#             liquidity_score = self._calculate_liquidity_score()

            # Create metrics object
# metrics = OrderFlowMetrics(
#                 buy_volume=buy_volume,
#                 sell_volume=sell_volume,
#                 net_volume=net_volume,
#                 volume_imbalance=volume_imbalance,
#                 aggressive_buy_ratio=aggressive_buy_ratio,
#                 aggressive_sell_ratio=aggressive_sell_ratio,
#                 average_trade_size=average_trade_size,
#                 large_trade_count=large_trade_count,
#                 institutional_flow_score=institutional_flow_score,
#                 liquidity_score=liquidity_score,
# )

#             self.flow_metrics_history.append(metrics)

#         except Exception as e:""
#             self.logger.error(f"Error updating flow metrics: {e}")

#     def _calculate_institutional_flow_score(
# self, trades: List[TradeExecution]
# ) -> float:"
#         "Calculate institutional flow score based on trade characteristics"
#         try:
#             if not trades:
#                 return 0.0

#             score = 0.0
#             total_volume = sum(trade.size for trade in trades)

            # Large trade ratio
# large_volume = sum(
#                 trade.size
#                 for trade in trades
#                 if trade.size >= self.config.large_trade_threshold
# )
#             large_ratio = large_volume / total_volume if total_volume > 0 else 0
#             score += large_ratio * 0.4

            # Block trade presence
# block_trades = sum(
# 1 for trade in trades if trade.size >= self.config.block_size_threshold
# )
#             if block_trades > 0:
#                 score += 0.3

            # Consistent direction"
# buy_volume = sum("
# trade.size for trade in trades if trade.aggressor == "buyer"
# )
# sell_volume = sum("
# trade.size for trade in trades if trade.aggressor == "seller"
# )

#             if total_volume > 0:
#                 directional_consistency = abs(buy_volume - sell_volume) / total_volume
#                 score += directional_consistency * 0.3

#             return min(score, 1.0)

#         except Exception as e:""
#             self.logger.error(f"Error calculating institutional flow score: {e}")
#             return 0.0

#     def _calculate_liquidity_score(self):
#         "Calculate current market liquidity score"
#         try:
#             if not self.order_book_history:
#                 return 0.0

#             current_book = self.order_book_history[-1]

            # Calculate spread as percentage of mid price
# spread_pct = (
#                 float(current_book.spread) / float(current_book.mid_price) * 100
# )

            # Calculate depth score (top 5 levels)
# total_depth = sum(level.size for level in current_book.bids[:5]) + sum(
# level.size for level in current_book.asks[:5]
# )

            # Normalize scores
#             spread_score = max(0, 1 - spread_pct / 0.5)  # Good if spread < 0.5%
#             depth_score = min(total_depth / 100000, 1.0)  # Good if depth > 100k

#             return (spread_score + depth_score) / 2

#         except Exception as e:""
#             self.logger.error(f"Error calculating liquidity score: {e}")
#             return 0.0

#     def _update_institutional_flow_score(self):
#         "Update institutional activity detection"
#         try:
#             if not self.flow_metrics_history:
#                 return

#             current_metrics = self.flow_metrics_history[-1]

            # Determine institutional activity type
#             if (
#                 current_metrics.institutional_flow_score
# >= self.config.institutional_threshold
# ):
#                 if current_metrics.volume_imbalance > 0.3:
#                     self.institutional_activity[""
#                         "current"
# ] = InstitutionalActivity.ACCUMULATION
#                 elif current_metrics.volume_imbalance < -0.3:
#                     self.institutional_activity[""
#                         "current"
# ] = InstitutionalActivity.DISTRIBUTION
#                 else:
#                     self.institutional_activity[""
#                         "current"
# ] = InstitutionalActivity.ROTATION
#             else:""
#                 self.institutional_activity["current"] = InstitutionalActivity.NONE

#         except Exception as e:""
#             self.logger.error(f"Error updating institutional flow score: {e}")

#     def _detect_institutional_activity(self):
#         "Detect various types of institutional activity"
#         try:
#             if not self.flow_metrics_history or len(self.flow_metrics_history) < 3:
#                 return

#             recent_metrics = list(self.flow_metrics_history)[-3:]

            # Look for consistent patterns
# avg_imbalance = sum(m.volume_imbalance for m in recent_metrics) / len(
#                 recent_metrics
# )
# avg_institutional_score = sum(
# m.institutional_flow_score for m in recent_metrics
# ) / len(recent_metrics)

            # Detect accumulation/distribution patterns
#             if avg_institutional_score > 0.6:
#                 if avg_imbalance > 0.2:""
#                     self.logger.info("Institutional accumulation detected")
#                 elif avg_imbalance < -0.2:""
#                     self.logger.info("Institutional distribution detected")

#         except Exception as e:""
#             self.logger.error(f"Error detecting institutional activity: {e}")

#     def generate_signals(
# self, market_data: pd.DataFrame = None
# ) -> List[ScalpingSignal]:"
#         "Generate trading signals based on order flow analysis"
#         try:
#             if not self.flow_metrics_history or not self.order_book_history:
#                 return []

#             signals = []
#             current_metrics = self.flow_metrics_history[-1]
#             current_book = self.order_book_history[-1]

            # Check if market conditions are suitable for scalping
#             if not self._is_suitable_for_scalping(current_book, current_metrics):
#                 return []

            # Generate signals based on different patterns

            # 1. Order flow imbalance signals
# imbalance_signal = self._generate_imbalance_signal(
#                 current_metrics, current_book
# )
#             if imbalance_signal:
#                 signals.append(imbalance_signal)

            # 2. Institutional flow signals
# institutional_signal = self._generate_institutional_signal(
#                 current_metrics, current_book
# )
#             if institutional_signal:
#                 signals.append(institutional_signal)

            # 3. Sweep pattern signals
#             sweep_signal = self._generate_sweep_signal(current_book)
#             if sweep_signal:
#                 signals.append(sweep_signal)

            # 4. Iceberg detection signals
#             iceberg_signal = self._generate_iceberg_signal(current_book)
#             if iceberg_signal:
#                 signals.append(iceberg_signal)

#             return signals

#         except Exception as e:""
#             self.logger.error(f"Error generating order flow signals: {e}")
#             return []

#     def _is_suitable_for_scalping(
# self, order_book: OrderBookSnapshot, metrics: OrderFlowMetrics
# ) -> bool:"
#         "Check if current market conditions are suitable for scalping"
#         try:
            # Check spread constraints
#             spread_bps = float(order_book.spread) / float(order_book.mid_price) * 10000
#             if (
#                 spread_bps < self.config.min_spread_bps
# or spread_bps > self.config.max_spread_bps
# ):
#                 return False

            # Check liquidity
#             if metrics.liquidity_score < 0.3:
#                 return False

            # Check order book depth
#             if len(order_book.bids) < 5 or len(order_book.asks) < 5:
#                 return False

#             return True

#         except Exception as e:""
#             self.logger.error(f"Error checking scalping suitability: {e}")
#             return False

#     def _generate_imbalance_signal(
# self, metrics: OrderFlowMetrics, order_book: OrderBookSnapshot
# ) -> Optional[ScalpingSignal]:"
#         "Generate signal based on order flow imbalance"
#         try:
#             if abs(metrics.volume_imbalance) < self.config.imbalance_threshold:
#                 return None

            # Determine signal direction
#             if metrics.volume_imbalance > self.config.imbalance_threshold:
#                 signal_type = SignalType.BUY
# target_price = (
#                     order_book.asks[0].price
#                     if order_book.asks
# else order_book.mid_price
# )
#             else:
#                 signal_type = SignalType.SELL
# target_price = (
#                     order_book.bids[0].price
#                     if order_book.bids
# else order_book.mid_price
# )

            # Calculate signal strength and confidence
#             strength = min(abs(metrics.volume_imbalance) * 2, 1.0)
# confidence = (
#                 metrics.institutional_flow_score * 0.7 + metrics.liquidity_score * 0.3
# )

#             return ScalpingSignal(
#                 signal_type=signal_type,
#                 strength=strength,
#                 confidence=confidence,
#                 timestamp=datetime.now(),
#                 price=target_price,
#                 volume=int(metrics.buy_volume + metrics.sell_volume),
#                 bid_ask_spread=float(order_book.spread),
#                 order_book_imbalance=order_book.imbalance,
#                 tick_direction=1 if signal_type == SignalType.BUY else -1,
#                 momentum_score=abs(metrics.volume_imbalance),
#                 liquidity_score=metrics.liquidity_score,
#                 microstructure=MarketMicrostructure.MOMENTUM,
#                 expected_hold_time=self.config.max_hold_time_seconds,
#                 risk_reward_ratio=self.config.profit_target_ticks
# / self.config.max_adverse_ticks,
# )

#         except Exception as e:""
#             self.logger.error(f"Error generating imbalance signal: {e}")
#             return None

#     def _generate_institutional_signal(
# self, metrics: OrderFlowMetrics, order_book: OrderBookSnapshot
# ) -> Optional[ScalpingSignal]:"
#         "Generate signal based on institutional activity"
#         try:
#             if metrics.institutional_flow_score < self.config.institutional_threshold:
#                 return None

# current_activity = self.institutional_activity.get("
#                 "current", InstitutionalActivity.NONE
# )

#             if current_activity == InstitutionalActivity.ACCUMULATION:
#                 signal_type = SignalType.BUY
# target_price = (
#                     order_book.asks[0].price
#                     if order_book.asks
# else order_book.mid_price
# )
#             elif current_activity == InstitutionalActivity.DISTRIBUTION:
#                 signal_type = SignalType.SELL
# target_price = (
#                     order_book.bids[0].price
#                     if order_book.bids
# else order_book.mid_price
# )
#             else:
#                 return None

#             strength = metrics.institutional_flow_score
# confidence = min(
#                 metrics.institutional_flow_score + metrics.liquidity_score * 0.3, 1.0
# )

#             return ScalpingSignal(
#                 signal_type=signal_type,
#                 strength=strength,
#                 confidence=confidence,
#                 timestamp=datetime.now(),
#                 price=target_price,
#                 volume=int(metrics.buy_volume + metrics.sell_volume),
#                 bid_ask_spread=float(order_book.spread),
#                 order_book_imbalance=order_book.imbalance,
#                 tick_direction=1 if signal_type == SignalType.BUY else -1,
#                 momentum_score=metrics.institutional_flow_score,
#                 liquidity_score=metrics.liquidity_score,
#                 microstructure=MarketMicrostructure.INSTITUTIONAL,
#                 expected_hold_time=self.config.max_hold_time_seconds
#                 * 2,  # Hold longer for institutional signals
#                 risk_reward_ratio=self.config.profit_target_ticks
# / self.config.max_adverse_ticks,
# )

#         except Exception as e:""
#             self.logger.error(f"Error generating institutional signal: {e}")
#             return None

#     def _generate_sweep_signal(
# self, order_book: OrderBookSnapshot
# ) -> Optional[ScalpingSignal]:"
#         "Generate signal based on order book sweep patterns"
#         try:
#             if not self.sweep_patterns:
#                 return None

            # Get most recent sweep
#             recent_sweep = self.sweep_patterns[-1]

            # Check if sweep is recent enough"
#             if (datetime.now() - recent_sweep["timestamp"]).total_seconds() > 10:
#                 return None
# "
#             if recent_sweep["direction"] == "bullish":
#                 signal_type = SignalType.BUY
# target_price = (
#                     order_book.asks[0].price
#                     if order_book.asks
# else order_book.mid_price
# )
#             else:
#                 signal_type = SignalType.SELL
# target_price = (
#                     order_book.bids[0].price
#                     if order_book.bids
# else order_book.mid_price
# )

            # Strength based on levels removed"
# strength = min("
#                 recent_sweep["levels_removed"] / self.config.sweep_detection_levels, 1.0
# )
#             confidence = 0.8  # High confidence for sweep patterns

#             return ScalpingSignal(
#                 signal_type=signal_type,
#                 strength=strength,
#                 confidence=confidence,
#                 timestamp=datetime.now(),
#                 price=target_price,
#                 volume=0,  # Unknown volume for sweep signals
#                 bid_ask_spread=float(order_book.spread),
#                 order_book_imbalance=order_book.imbalance,
#                 tick_direction=1 if signal_type == SignalType.BUY else -1,
#                 momentum_score=strength,
#                 liquidity_score=0.5,  # Neutral liquidity assumption
#                 microstructure=MarketMicrostructure.MOMENTUM,
#                 expected_hold_time=self.config.max_hold_time_seconds
# // 2,  # Shorter hold for sweep signals
#                 risk_reward_ratio=self.config.profit_target_ticks
# / self.config.max_adverse_ticks,
# )

#         except Exception as e:""
#             self.logger.error(f"Error generating sweep signal: {e}")
#             return None

#     def _generate_iceberg_signal(
# self, order_book: OrderBookSnapshot
# ) -> Optional[ScalpingSignal]:"
#         "Generate signal based on iceberg order detection"
#         try:
            # Look for iceberg orders at current price levels
#             for price, timestamps in self.iceberg_orders.items():
#                 if len(timestamps) >= 3:  # Consistent iceberg activity
                    # Determine if this is a support (bid) or resistance (ask) level
#                     is_support = any(bid.price == price for bid in order_book.bids[:3])
# is_resistance = any(
# ask.price == price for ask in order_book.asks[:3]
# )

#                     if is_support:
                        # Iceberg bid suggests buying interest - bullish signal
#                         signal_type = SignalType.BUY
# target_price = (
#                             order_book.asks[0].price
#                             if order_book.asks
# else order_book.mid_price
# )
#                     elif is_resistance:
                        # Iceberg ask suggests selling interest - bearish signal
#                         signal_type = SignalType.SELL
# target_price = (
#                             order_book.bids[0].price
#                             if order_book.bids
# else order_book.mid_price
# )
#                     else:
#                         continue

# strength = min(
#                         len(timestamps) / 5, 1.0
# )  # Max strength at 5 observations
#                     confidence = 0.6  # Moderate confidence for iceberg signals

#                     return ScalpingSignal(
#                         signal_type=signal_type,
#                         strength=strength,
#                         confidence=confidence,
#                         timestamp=datetime.now(),
#                         price=target_price,
#                         volume=0,  # Unknown volume for iceberg signals
#                         bid_ask_spread=float(order_book.spread),
#                         order_book_imbalance=order_book.imbalance,
#                         tick_direction=1 if signal_type == SignalType.BUY else -1,
#                         momentum_score=strength * 0.7,
#                         liquidity_score=0.8,  # Icebergs indicate hidden liquidity
#                         microstructure=MarketMicrostructure.INSTITUTIONAL,
#                         expected_hold_time=self.config.max_hold_time_seconds,
#                         risk_reward_ratio=self.config.profit_target_ticks
# / self.config.max_adverse_ticks,
# )

#             return None

#         except Exception as e:""
#             self.logger.error(f"Error generating iceberg signal: {e}")
#             return None

#     def get_strategy_status(self):
#         "Get current strategy status and metrics"
#         try:
# current_metrics = (
#                 self.flow_metrics_history[-1] if self.flow_metrics_history else None
# )
# current_book = (
#                 self.order_book_history[-1] if self.order_book_history else None
# )

#             return {
# "strategy_name": "OrderFlowScalpingStrategy","
# "state": self.state.value,"
# "current_position": self.current_position,"
# "trades_today": self.trades_today,"
# "pnl_today": float(self.pnl_today),"
# "win_rate": self.win_rate,"
# "avg_hold_time": self.avg_hold_time,"
# "order_book_updates": len(self.order_book_history),"
# "trade_executions": len(self.trade_history),"
# "large_orders_detected": len(self.large_orders),"
# "iceberg_orders_active": len(self.iceberg_orders),"
# "sweep_patterns_detected": len(self.sweep_patterns),"
# "current_flow_metrics": {
# "volume_imbalance": current_metrics.volume_imbalance
#                     if current_metrics
# else 0,"
# "institutional_flow_score": current_metrics.institutional_flow_score
#                     if current_metrics
# else 0,"
# "liquidity_score": current_metrics.liquidity_score
#                     if current_metrics
# else 0,
# }
#                 if current_metrics
# else None,"
# "current_order_book": {
# "spread_bps": float(current_book.spread)
# / float(current_book.mid_price)
#                     * 10000
#                     if current_book
# else 0,"
# "imbalance": current_book.imbalance if current_book else 0,"
# "total_depth": (
#                         current_book.total_bid_size + current_book.total_ask_size
# )
#                     if current_book
# else 0,
# }
#                 if current_book
# else None,"
# "institutional_activity": self.institutional_activity.get("
#                     "current", InstitutionalActivity.NONE
# ).value,"
# "last_update": datetime.now().isoformat(),
# }

#         except Exception as e:""
#             self.logger.error(f"Error getting strategy status: {e}")""
#             return {"error": str(e)}


# Example usage"
# def create_order_flow_config():
#     "Create a sample order flow scalping configuration"
#     return OrderFlowScalpingConfig(
#         order_book_depth=10,
#         min_spread_bps=1,
#         max_spread_bps=20,
#         large_trade_threshold=10000,
#         institutional_threshold=0.7,
#         imbalance_threshold=0.3,
#         max_position_size=0.005,
#         entry_timeout_ms=100,
#         exit_timeout_ms=200,
#         max_adverse_ticks=3,
#         profit_target_ticks=5,
#         max_hold_time_seconds=30,
# )

# "
# if __name__ == "__main__":
    # Example usage
#     config = create_order_flow_config()
#     strategy = OrderFlowScalpingStrategy(config)
# "
# print(f"Order flow scalping strategy initialized")"
#     print(f"Strategy Status: {strategy.get_strategy_status()}")
# "'"'