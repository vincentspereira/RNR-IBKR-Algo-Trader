import logging
import math
import threading
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np
import pandas as pd
from scipy import stats
from scipy.signal import find_peaks

# Enhanced Smart Money Analysis Engine

# Institutional-grade smart money flow detection and analysis system that combines:
# - September 2025 sophisticated smart money detection algorithms
# - Advanced institutional flow analysis and pattern recognition
# - Real-time anomaly detection and volume pattern analysis
# - ML-enhanced signal processing and meta-labeling integration
# - Dark pool and block trade activity tracking
# ""- API compatibility with existing trading system"

# Key Features:
# - Smart money flow detection using volume profile analysis
# - Institutional bias assessment through order flow patterns
# - Large order detection and tracking with urgency scoring
# - Market maker vs taker analysis with liquidity conditions
# - Liquidity analysis and absorption detection
# - Dark pool activity estimation and block trade monitoring
# - Institutional footprint analysis with phase detection
# - ML integration for regime-aware smart money signals
# - Real-time performance optimization for sub-100μs analysis

# Author: Vincent S. Pereira
# Version: 2.0.0 (Enhanced from September 2025)




# try:
#     from sklearn.ensemble import IsolationForest, RandomForestClassifier
#     from sklearn.preprocessing import StandardScaler
#     SKLEARN_AVAILABLE = True
# except ImportError:
#     SKLEARN_AVAILABLE = False
#     logging.warning("scikit-learn not available. Advanced smart money detection will be limited.")

# try:
#     from infrastructure.config.master_config import get_config
#     from infrastructure.wrappers.factory import WrapperFactory
#     logger = get_logger(__name__)
# except ImportError:
#     import logging
#     logger = logging.getLogger(__name__)

# Import ML integration for smart money
# try:
#     from ..analysis.indicators.machine_learning.smart_money_ml_integration import ()
#         SmartMoneyMLProcessor,
#         SmartMoneyMLSignal,
#         SmartMoneyMLConfig,
#         create_smart_money_ml_processor,
# )
#     ML_INTEGRATION_AVAILABLE = True
# except ImportError:
#     logger.warning("Could not import smart money ML integration")
#     ML_INTEGRATION_AVAILABLE = False

# ===========================================
# ENHANCED ENUMS AND DATA STRUCTURES
# ===========================================

# class TradingActivityType(Enum):
#     "Types of trading activity"
#     RETAIL = "retail"
#     INSTITUTIONAL = "institutional"
#     HIGH_FREQUENCY = "high_frequency"
#     ARBITRAGE = "arbitrage"
#     DARK_POOL = "dark_pool"
#     BLOCK_TRADE = "block_trade"

# class SmartMoneySignal(Enum):
#     "Smart money signal types"
#     STRONG_ACCUMULATION = "strong_accumulation"
#     ACCUMULATION = "accumulation"
#     DISTRIBUTION = "distribution"
#     STRONG_DISTRIBUTION = "strong_distribution"
#     NEUTRAL = "neutral"
#     MANIPULATION = "manipulation"

# class SmartMoneyBias(Enum):
#     "Enhanced smart money directional bias from September 2025"
#     STRONG_BULLISH = "strong_bullish"
#     BULLISH = "bullish"
#     NEUTRAL = "neutral"
#     BEARISH = "bearish"
#     STRONG_BEARISH = "strong_bearish"

# class InstitutionalActivity(Enum):
#     "Level of institutional activity from September 2025"
#     VERY_HIGH = "very_high"
#     HIGH = "high"
#     MODERATE = "moderate"
#     LOW = "low"
#     MINIMAL = "minimal"

# class OrderFlowType(Enum):
#     "Type of order flow detected from September 2025"
#     AGGRESSIVE_BUYING = "aggressive_buying"
#     AGGRESSIVE_SELLING = "aggressive_selling"
#     PASSIVE_ACCUMULATION = "passive_accumulation"
#     PASSIVE_DISTRIBUTION = "passive_distribution"
#     BALANCED = "balanced"
#     ABSORPTION = "absorption"

# class LiquidityCondition(Enum):
#     "Market liquidity conditions from September 2025"
#     ABUNDANT = "abundant"
#     NORMAL = "normal"
#     THIN = "thin"
#     VERY_THIN = "very_thin"
#     ILLIQUID = "illiquid"

# @dataclass
# class SmartMoneyConfig:
#     "Enhanced configuration for smart money analysis"

    # Detection parameters
#     volume_threshold_multiplier: float = 2.0  # Volume above average threshold
#     price_impact_threshold: float = 0.002  # 0.2% price impact
#     large_trade_threshold: float = 100000.0  # $100k trade size
#     anomaly_contamination: float = 0.1  # For anomaly detection

    # September 2025 enhanced parameters
#     lookback_period: int = 100
#     large_order_threshold: float = 2.0  # Multiple of average volume
#     block_trade_threshold: float = 5.0  # Multiple of average volume
#     institutional_threshold: float = 10.0  # Multiple of average volume

    # Analysis windows
#     short_window: int = 5   # 5 periods for short-term analysis
#     medium_window: int = 20  # 20 periods for medium-term analysis
#     long_window: int = 100  # 100 periods for long-term analysis

    # Signal generation
#     min_signal_strength: float = 0.3
#     signal_decay_rate: float = 0.95
#     confirmation_periods: int = 3

    # Features to analyze
#     enable_volume_analysis: bool = True
#     enable_price_impact_analysis: bool = True
#     enable_order_flow_analysis: bool = True
#     enable_anomaly_detection: bool = True
#     enable_dark_pool_detection: bool = True

    # ML Integration
#     enable_ml_enhancement: bool = True
#     enable_regime_aware_analysis: bool = True
#     enable_meta_labeling: bool = True

# @dataclass
# class SmartMoneyMetrics:
#     "Enhanced smart money flow metrics combining both systems"

    # Core metrics from current system
#     symbol: str
#     timestamp: datetime

    # Volume metrics from current system
#     volume_ratio: float  # Current volume vs average
#     volume_trend: float  # Volume trend strength
#     unusual_volume: bool  # Unusual volume detected

    # Price impact metrics from current system
#     price_impact: float  # Price change per volume unit
#     volume_price_correlation: float  # Correlation between volume and price
#     buying_pressure: float  # Net buying pressure
#     selling_pressure: float  # Net selling pressure

    # Institutional metrics from current system
#     institutional_flow: float  # Estimated institutional flow
#     large_trade_ratio: float  # Ratio of large trades
#     dark_pool_activity: float  # Dark pool activity estimate

    # Anomaly metrics from current system
#     anomaly_score: float  # Anomaly detection score
#     unusual_activity: bool  # Unusual activity detected

    # Enhanced metrics from September 2025
#     smart_money_index: float  # 0-1 scale
#     institutional_bias: SmartMoneyBias
#     activity_level: InstitutionalActivity
#     confidence: float  # 0-1 scale

    # Order flow analysis from September 2025
#     order_flow_type: OrderFlowType
#     flow_direction: object  # Provides .value attribute for compatibility
#     net_flow: float  # -1 to 1 scale

    # Enhanced volume analysis from September 2025
#     block_trade_activity: float  # 0-1 scale
#     dark_pool_estimate: float  # Estimated dark pool activity 0-1
#     institutional_activity: float  # 0-1 scale (unified score)
#     institutional_flow_ratio: float  # Alias for compatibility

    # Liquidity metrics from September 2025
#     liquidity_condition: LiquidityCondition
#     absorption_detected: bool
#     liquidity_stress: float  # 0-1 scale

    # Timing analysis from September 2025
#     accumulation_phase: bool
#     distribution_phase: bool
#     breakout_preparation: bool

    # Market structure from September 2025
#     support_strength: float  # 0-1 scale
#     resistance_strength: float  # 0-1 scale
#     structural_shift: bool

    # Signal metrics (unified)
#     smart_money_signal: SmartMoneySignal
#     signal_strength: float
#     signal_confidence: float

# @dataclass
# class SmartMoneyAlert:
#     "Enhanced smart money alert"

#     alert_type: str
#     severity: str  # 'low', 'medium', 'high', 'critical'
#     message: str
#     symbol: str
#     timestamp: datetime

    # Alert data
#     metrics: Dict[str, float]
#     threshold: float
#     actual_value: float

    # Enhanced alert data
#     institutional_bias: Optional[SmartMoneyBias] = None
#     order_flow_type: Optional[OrderFlowType] = None
#     ml_enhanced: bool = False

# @dataclass
# class OrderFlowData:
#     "Order flow data point from September 2025"
#     timestamp: datetime
#     price: float
#     volume: float
#     is_buy: bool
#     size_category: str  # 'small', 'medium', 'large', 'block', 'institutional'
#     urgency_score: float  # 0-1 scale

# ===========================================
# ENHANCED SMART MONEY ANALYSIS ENGINE
# ===========================================

# class EnhancedSmartMoneyAnalysisEngine:

# Enhanced Smart Money Analysis Engine combining September 2025 sophistication
#     with current system's ML integration and API compatibility'


#     def __init__(self, config: SmartMoneyConfig = None):
#         self.config = config or SmartMoneyConfig()
#         self.logger = logger

        # Initialize wrapper factory for external integrations
#         try:
#             self.wrapper_factory = WrapperFactory()
#         except Exception as e:
#             self.logger.warning(f"Could not initialize wrapper factory: {e}")
#             self.wrapper_factory = None

        # Data storage (enhanced from both systems)
#         self.price_data: Dict[str, deque] = defaultdict(lambda: deque(maxlen=500))
#         self.volume_data: Dict[str, deque] = defaultdict(lambda: deque(maxlen=500))
#         self.trade_data: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
#         self.metrics_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=200))

        # September 2025 enhanced data structures
#         self.order_flow_data: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
#         self.volume_profile: Dict[str, defaultdict] = defaultdict(lambda: defaultdict(float))
#         self.price_levels: Dict[str, deque] = defaultdict(lambda: deque(maxlen=50))
#         self.support_resistance: Dict[str, Dict] = defaultdict(lambda: {"support": [], "resistance": []})

        # Analysis components
#         self.current_signals: Dict[str, SmartMoneyMetrics] = {}

        # ML and anomaly detection models
#         self.anomaly_models: Dict[str, Any] = {}
#         self.scalers: Dict[str, Any] = {}
#         self.regime_models: Dict[str, Any] = {}

        # Alert system
#         self.alerts: deque = deque(maxlen=1000)
#         self.alert_thresholds = {
# 'volume_spike': self.config.volume_threshold_multiplier,
# 'price_impact': self.config.price_impact_threshold,
# 'anomaly_score': 0.7,
# 'smart_money_index': 0.8,
# 'institutional_flow': 0.6,
# }

        # Threading and performance
#         self.lock = threading.Lock()
#         self.analysis_count = 0
#         self.last_analysis = None

        # Statistics tracking
#         self.avg_volume: Dict[str, float] = defaultdict(float)
#         self.volume_std: Dict[str, float] = defaultdict(float)

        # ML Integration
#         self.ml_processor: Optional[SmartMoneyMLProcessor] = None
#         if ML_INTEGRATION_AVAILABLE and self.config.enable_ml_enhancement:
# ml_config = SmartMoneyMLConfig(
#                 enable_regime_detection=self.config.enable_regime_aware_analysis,
#                 enable_meta_labeling=self.config.enable_meta_labeling,
#                 enable_probabilistic_forecasting=True,
#                 enable_factor_validation=True,
#                 enable_signal_decay=True,
# )
#             self.ml_processor = create_smart_money_ml_processor(ml_config, self)
#             self.logger.info("Smart Money ML Integration enabled")

#         self.logger.info("Enhanced Smart Money Analysis Engine initialized")

#     def update_market_data(self, symbol: str, price: float, volume: float, timestamp: datetime = None):

# Update market data for analysis with enhanced September 2025 algorithms

#         if timestamp is None:
#             timestamp = datetime.now(timezone.utc)

#         with self.lock:
            # Store data (both systems)
#             self.price_data[symbol].append((timestamp, price))
#             self.volume_data[symbol].append((timestamp, volume))

            # September 2025: Update volume statistics
#             self._update_volume_statistics(symbol)

            # September 2025: Analyze order flow
#             order_flow = self._analyze_order_flow(symbol, price, volume, timestamp)
#             if order_flow:
#                 self.order_flow_data[symbol].append(order_flow)

            # September 2025: Update volume profile
#             self._update_volume_profile(symbol, price, volume)

            # Current system: Simulate trade data
#             if len(self.volume_data[symbol]) > 1:
#                 prev_volume = self.volume_data[symbol][-2][1]
#                 trade_volume = volume - prev_volume if volume > prev_volume else volume * 0.1
#                 trade_value = trade_volume * price

                # Categorize trade type based on size
#                 if trade_value > self.config.large_trade_threshold:
#                     trade_type = TradingActivityType.INSTITUTIONAL
#                 elif trade_value > 10000:  # $10k
#                     trade_type = TradingActivityType.RETAIL
#                 else:
#                     trade_type = TradingActivityType.HIGH_FREQUENCY

#                 self.trade_data[symbol].append({
# 'timestamp': timestamp,
# 'price': price,
# 'volume': trade_volume,
# 'value': trade_value,
# 'type': trade_type,
# })

        # Trigger analysis if conditions are met
#         if self._should_analyze(symbol):
#             self._analyze_symbol(symbol)

#     def _should_analyze(self, symbol: str) -> bool:
#         "Determine if analysis should be run"

        # Check data availability
#         if len(self.price_data[symbol]) < self.config.short_window:
#             return False

        # Check timing (enhanced for performance)
#         if self.last_analysis:
#             time_since = datetime.now(timezone.utc) - self.last_analysis
#             if time_since.total_seconds() < 30:  # Reduced from 60s for better responsiveness
#                 return False

#         return True

#     def _analyze_symbol(self, symbol: str):

# Enhanced smart money analysis combining both systems' capabilities

#         try:
            # Prepare data
#             prices = [p[1] for p in list(self.price_data[symbol])[-self.config.long_window:]]
#             volumes = [v[1] for v in list(self.volume_data[symbol])[-self.config.long_window:]]

#             if len(prices) < self.config.short_window:
#                 return

#             timestamp = self.price_data[symbol][-1][0]

            # Current system analyses
#             volume_metrics = self._analyze_volume_patterns(symbol, prices, volumes)
#             price_impact_metrics = self._analyze_price_impact(symbol, prices, volumes)
#             institutional_metrics = self._analyze_institutional_flow(symbol)
#             anomaly_metrics = self._detect_anomalies(symbol, prices, volumes)

            # September 2025 enhanced analyses
#             self._detect_key_levels(symbol)
#             smart_money_sept_metrics = self._generate_sept2025_metrics(symbol)

            # ML Enhancement (if available)
#             ml_metrics = {}
#             if self.config.enable_ml_enhancement:
#                 ml_metrics = self._apply_ml_enhancement(symbol, prices, volumes)

            # Generate unified smart money signal
# signal_metrics = self._generate_unified_signal(
#                 symbol, timestamp, volume_metrics, price_impact_metrics,
#                 institutional_metrics, anomaly_metrics, smart_money_sept_metrics, ml_metrics
# )

            # Store results
#             with self.lock:
#                 self.current_signals[symbol] = signal_metrics
#                 self.metrics_history[symbol].append(signal_metrics)
#                 self.analysis_count += 1
#                 self.last_analysis = datetime.now(timezone.utc)

            # Process through ML if available
#             ml_signal = None
#             if self.ml_processor:
#                 ml_signal = self.ml_processor.process_smart_money_signal(symbol, signal_metrics)

            # Check for alerts (enhanced with ML insights)
#             self._check_enhanced_alerts(signal_metrics, ml_signal)

#             self.logger.debug(f"Enhanced smart money analysis completed for {symbol}" +
# (f" with ML processing" if ml_signal else "))

#         except Exception as e:
#             self.logger.error(f"Error analyzing smart money for {symbol}: {e}")

#     def _update_volume_statistics(self, symbol: str):
#         "Update volume statistics for threshold calculations (September 2025)"
#         if len(self.volume_data[symbol]) < 20:
#             return

#         recent_volumes = [v[1] for v in list(self.volume_data[symbol])[-50:]]
#         self.avg_volume[symbol] = np.mean(recent_volumes)
#         self.volume_std[symbol] = np.std(recent_volumes)

#     def _analyze_order_flow(self, symbol: str, price: float, volume: float, timestamp: datetime) -> Optional[OrderFlowData]:
#         "Analyze individual order flow characteristics (September 2025 enhanced)"
#         if len(self.price_data[symbol]) < 2 or self.avg_volume[symbol] == 0:
#             return None

#         prev_price = self.price_data[symbol][-2][1]

        # Determine if buy or sell based on price movement
#         is_buy = price > prev_price

        # Categorize order size (enhanced from September 2025)
#         volume_ratio = volume / self.avg_volume[symbol] if self.avg_volume[symbol] > 0 else 1.0

#         if volume_ratio >= self.config.institutional_threshold:
#             size_category = "institutional"
#         elif volume_ratio >= self.config.block_trade_threshold:
#             size_category = "block"
#         elif volume_ratio >= self.config.large_order_threshold:
#             size_category = "large"
#         elif volume_ratio >= 1.5:
#             size_category = "medium"
#         else:
#             size_category = "small"

        # Calculate urgency score based on price impact and volume
#         price_change = abs(price - prev_price) / prev_price if prev_price != 0 else 0
#         urgency_score = min(1.0, (price_change * 100 + volume_ratio / 10) / 2)

#         return OrderFlowData(
#             timestamp=timestamp,
#             price=price,
#             volume=volume,
#             is_buy=is_buy,
#             size_category=size_category,
#             urgency_score=urgency_score,
# )

#     def _update_volume_profile(self, symbol: str, price: float, volume: float):
#         "Update volume profile for price level analysis (September 2025)"
#         price_level = round(price, 2)
#         self.volume_profile[symbol][price_level] += volume

        # Keep only recent price levels
#         if len(self.volume_profile[symbol]) > 200:
#             sorted_levels = sorted(self.volume_profile[symbol].items(), key=lambda x: x[1])
#             for level, _ in sorted_levels[:50]:
#                 del self.volume_profile[symbol][level]

#     def _detect_key_levels(self, symbol: str):
#         "Detect key support and resistance levels from volume profile (September 2025)"
#         if len(self.volume_profile[symbol]) < 10:
#             return

#         sorted_profile = sorted(self.volume_profile[symbol].items(), key=lambda x: x[1], reverse=True)
#         hvn_count = max(3, len(sorted_profile) // 5)
#         hvn_levels = [level for level, volume in sorted_profile[:hvn_count]]

#         current_price = self.price_data[symbol][-1][1] if self.price_data[symbol] else 0

#         self.support_resistance[symbol] = {"support": [], "resistance": []}

#         for level in hvn_levels:
#             if level < current_price:
#                 self.support_resistance[symbol]["support"].append(level)
#             else:
#                 self.support_resistance[symbol]["resistance"].append(level)

#         self.support_resistance[symbol]["support"].sort(reverse=True)
#         self.support_resistance[symbol]["resistance"].sort()

#     def _generate_sept2025_metrics(self, symbol: str) -> Dict[str, Any]:
#         "Generate September 2025 style metrics"
#         if len(self.order_flow_data[symbol]) < 10:
#             return {}

#         recent_flow = list(self.order_flow_data[symbol])[-20:]

        # Calculate buy/sell pressure
#         buy_volume = sum(flow.volume for flow in recent_flow if flow.is_buy)
#         sell_volume = sum(flow.volume for flow in recent_flow if not flow.is_buy)
#         total_volume = buy_volume + sell_volume

#         buy_pressure = buy_volume / total_volume if total_volume > 0 else 0.5
#         sell_pressure = sell_volume / total_volume if total_volume > 0 else 0.5
#         net_flow = buy_pressure - sell_pressure

        # Large order metrics
#         large_orders = [flow for flow in recent_flow if flow.size_category in ["large", "block", "institutional"]]
#         large_order_volume = sum(flow.volume for flow in large_orders)
#         large_order_ratio = large_order_volume / total_volume if total_volume > 0 else 0

        # Smart money index
#         smart_money_index = self._calculate_smart_money_index(recent_flow)

        # Institutional bias
#         institutional_bias = self._determine_institutional_bias(net_flow, smart_money_index)

        # Activity level
#         block_trades = [flow for flow in recent_flow if flow.size_category in ["block", "institutional"]]
#         block_trade_activity = len(block_trades) / len(recent_flow) if recent_flow else 0
#         activity_level = self._determine_activity_level(large_order_ratio, block_trade_activity)

        # Order flow type
#         order_flow_type = self._determine_order_flow_type(recent_flow, net_flow)

        # Liquidity analysis
#         liquidity_condition, absorption_detected, liquidity_stress = self._analyze_liquidity(recent_flow)

        # Phase detection
#         accumulation_phase, distribution_phase, breakout_preparation = self._detect_market_phases(symbol)

        # Support/resistance strength
#         support_strength, resistance_strength = self._calculate_level_strength(symbol)

        # Structural shift
#         structural_shift = self._detect_structural_shift(symbol)

        # Dark pool estimation
#         dark_pool_estimate = self._estimate_dark_pool_activity(recent_flow)

        # Confidence
#         confidence = self._calculate_confidence(smart_money_index, large_order_ratio, len(recent_flow))

        # Flow direction object with .value attribute
#         class _Flow:
#             def __init__(self, value: str):
#                 self.value = value

#         if dark_pool_estimate > 0.6:
#             flow_direction = _Flow("dark_pool_activity")
#         elif institutional_bias == SmartMoneyBias.BULLISH:
#             if large_order_ratio > 0.6:
#                 flow_direction = _Flow("institutional_buying")
#             elif net_flow > 0.05:
#                 flow_direction = _Flow("accumulation")
#             else:
#                 flow_direction = _Flow("neutral")
#         elif institutional_bias == SmartMoneyBias.BEARISH:
#             if large_order_ratio > 0.6:
#                 flow_direction = _Flow("institutional_selling")
#             elif net_flow < -0.05:
#                 flow_direction = _Flow("distribution")
#             else:
#                 flow_direction = _Flow("neutral")
#         else:
#             flow_direction = _Flow("neutral")

#         return {
# 'smart_money_index': smart_money_index,
# 'institutional_bias': institutional_bias,
# 'activity_level': activity_level,
# 'confidence': confidence,
# 'order_flow_type': order_flow_type,
# 'flow_direction': flow_direction,
# 'net_flow': net_flow,
# 'large_order_ratio': large_order_ratio,
# 'block_trade_activity': block_trade_activity,
# 'dark_pool_estimate': dark_pool_estimate,
# 'liquidity_condition': liquidity_condition,
# 'absorption_detected': absorption_detected,
# 'liquidity_stress': liquidity_stress,
# 'accumulation_phase': accumulation_phase,
# 'distribution_phase': distribution_phase,
# 'breakout_preparation': breakout_preparation,
# 'support_strength': support_strength,
# 'resistance_strength': resistance_strength,
# 'structural_shift': structural_shift,
# 'institutional_activity': min(1.0, max(0.0, (large_order_ratio + block_trade_activity) / 2.0)),
# 'dark_pool_activity': dark_pool_estimate,
# 'institutional_flow_ratio': large_order_ratio,
# }

#     def _calculate_smart_money_index(self, recent_flow: List[OrderFlowData]) -> float:
#         "Calculate smart money index based on order flow characteristics (September 2025)"
#         if not recent_flow:
#             return 0.5

#         size_weight = 0.4
#         urgency_weight = 0.3
#         timing_weight = 0.3

#         total_score = 0.0
#         total_weight = 0.0

#         for flow in recent_flow:
# size_scores = {
# "small": 0.1,
# "medium": 0.3,
# "large": 0.7,
# "block": 0.9,
# "institutional": 1.0,
# }
#             size_score = size_scores.get(flow.size_category, 0.1)
#             urgency_score = flow.urgency_score
#             timing_score = 0.5  # Simplified

# flow_score = (
# size_score * size_weight +
# urgency_score * urgency_weight +
#                 timing_score * timing_weight
# )

#             total_score += flow_score * flow.volume
#             total_weight += flow.volume

#         return total_score / total_weight if total_weight > 0 else 0.5

#     def _determine_institutional_bias(self, net_flow: float, smart_money_index: float) -> SmartMoneyBias:
#         "Determine institutional directional bias (September 2025)"
#         bias_score = (net_flow + (smart_money_index - 0.5) * 2) / 2

#         if bias_score > 0.6:
#             return SmartMoneyBias.STRONG_BULLISH
#         elif bias_score > 0.2:
#             return SmartMoneyBias.BULLISH
#         elif bias_score < -0.6:
#             return SmartMoneyBias.STRONG_BEARISH
#         elif bias_score < -0.2:
#             return SmartMoneyBias.BEARISH
#         else:
#             return SmartMoneyBias.NEUTRAL

#     def _determine_activity_level(self, large_order_ratio: float, block_trade_activity: float) -> InstitutionalActivity:
#         "Determine level of institutional activity (September 2025)"
#         activity_score = (large_order_ratio + block_trade_activity) / 2

#         if activity_score > 0.8:
#             return InstitutionalActivity.VERY_HIGH
#         elif activity_score > 0.6:
#             return InstitutionalActivity.HIGH
#         elif activity_score > 0.4:
#             return InstitutionalActivity.MODERATE
#         elif activity_score > 0.2:
#             return InstitutionalActivity.LOW
#         else:
#             return InstitutionalActivity.MINIMAL

#     def _determine_order_flow_type(self, recent_flow: List[OrderFlowData], net_flow: float) -> OrderFlowType:
#         "Determine the type of order flow pattern (September 2025)"
#         if not recent_flow:
#             return OrderFlowType.BALANCED

#         high_urgency_flows = [f for f in recent_flow if f.urgency_score > 0.7]
#         large_flows = [f for f in recent_flow if f.size_category in ["large", "block", "institutional"]]

#         urgency_ratio = len(high_urgency_flows) / len(recent_flow)
#         large_ratio = len(large_flows) / len(recent_flow)

#         if urgency_ratio > 0.6 and net_flow > 0.3:
#             return OrderFlowType.AGGRESSIVE_BUYING
#         elif urgency_ratio > 0.6 and net_flow < -0.3:
#             return OrderFlowType.AGGRESSIVE_SELLING
#         elif large_ratio > 0.4 and net_flow > 0.2:
#             return OrderFlowType.PASSIVE_ACCUMULATION
#         elif large_ratio > 0.4 and net_flow < -0.2:
#             return OrderFlowType.PASSIVE_DISTRIBUTION
#         elif urgency_ratio > 0.8:
#             return OrderFlowType.ABSORPTION
#         else:
#             return OrderFlowType.BALANCED

#     def _analyze_liquidity(self, recent_flow: List[OrderFlowData]) -> Tuple[LiquidityCondition, bool, float]:
#         "Analyze market liquidity conditions (September 2025)"
#         if not recent_flow:
#             return LiquidityCondition.NORMAL, False, 0.0

#         avg_urgency = np.mean([f.urgency_score for f in recent_flow])
#         volume_variance = np.var([f.volume for f in recent_flow])
#         avg_volume = np.mean([f.volume for f in recent_flow])
#         normalized_variance = volume_variance / (avg_volume ** 2) if avg_volume > 0 else 0

#         liquidity_stress = min(1.0, (avg_urgency + normalized_variance) / 2)
#         absorption_detected = avg_urgency > 0.8 and normalized_variance > 0.5

#         if liquidity_stress > 0.8:
#             condition = LiquidityCondition.ILLIQUID
#         elif liquidity_stress > 0.6:
#             condition = LiquidityCondition.VERY_THIN
#         elif liquidity_stress > 0.4:
#             condition = LiquidityCondition.THIN
#         elif liquidity_stress > 0.2:
#             condition = LiquidityCondition.NORMAL
#         else:
#             condition = LiquidityCondition.ABUNDANT

#         return condition, absorption_detected, liquidity_stress

#     def _detect_market_phases(self, symbol: str) -> Tuple[bool, bool, bool]:
#         "Detect market phases (September 2025)"
#         if len(self.price_data[symbol]) < 20:
#             return False, False, False

#         recent_prices = [p[1] for p in list(self.price_data[symbol])[-20:]]
#         recent_volumes = [v[1] for v in list(self.volume_data[symbol])[-20:]]

#         price_volatility = np.std(recent_prices) / np.mean(recent_prices) if np.mean(recent_prices) > 0 else 0
#         volume_trend = np.polyfit(range(len(recent_volumes)), recent_volumes, 1)[0]
#         avg_volume = np.mean(recent_volumes)
#         volume_trend_normalized = volume_trend / avg_volume if avg_volume > 0 else 0

#         accumulation_phase = price_volatility < 0.02 and volume_trend_normalized > 0.1
#         distribution_phase = price_volatility < 0.02 and volume_trend_normalized < -0.1
#         breakout_preparation = price_volatility < 0.015 and abs(volume_trend_normalized) > 0.15

#         return accumulation_phase, distribution_phase, breakout_preparation

#     def _calculate_level_strength(self, symbol: str) -> Tuple[float, float]:
#         "Calculate support and resistance level strength (September 2025)"
#         if (not self.support_resistance[symbol]["support"] and
# not self.support_resistance[symbol]["resistance"]):
#             return 0.0, 0.0

#         current_price = self.price_data[symbol][-1][1] if self.price_data[symbol] else 0

#         support_strength = 0.0
#         if self.support_resistance[symbol]["support"]:
#             closest_support = self.support_resistance[symbol]["support"][0]
#             support_volume = self.volume_profile[symbol].get(closest_support, 0)
#             total_volume = sum(self.volume_profile[symbol].values())
#             support_strength = support_volume / total_volume if total_volume > 0 else 0

#         resistance_strength = 0.0
#         if self.support_resistance[symbol]["resistance"]:
#             closest_resistance = self.support_resistance[symbol]["resistance"][0]
#             resistance_volume = self.volume_profile[symbol].get(closest_resistance, 0)
#             total_volume = sum(self.volume_profile[symbol].values())
#             resistance_strength = resistance_volume / total_volume if total_volume > 0 else 0

#         return support_strength, resistance_strength

#     def _detect_structural_shift(self, symbol: str) -> bool:
#         "Detect structural market shifts (September 2025)"
#         if len(self.price_data[symbol]) < 50:
#             return False

#         recent_prices = [p[1] for p in list(self.price_data[symbol])[-20:]]
#         historical_prices = [p[1] for p in list(self.price_data[symbol])[-50:-20]]

#         recent_volatility = np.std(recent_prices)
#         historical_volatility = np.std(historical_prices)

# volatility_ratio = (recent_volatility / historical_volatility
#                         if historical_volatility > 0 else 1)

#         return volatility_ratio > 2.0 or volatility_ratio < 0.5

#     def _estimate_dark_pool_activity(self, recent_flow: List[OrderFlowData]) -> float:
#         "Estimate dark pool activity based on order flow patterns (September 2025)"
#         if not recent_flow:
#             return 0.0

# large_low_urgency = [
# f for f in recent_flow
#             if f.size_category in ["large", "block", "institutional"] and f.urgency_score < 0.3
# ]

#         dark_pool_ratio = len(large_low_urgency) / len(recent_flow)
#         return min(1.0, dark_pool_ratio * 2)

#     def _calculate_confidence(self, smart_money_index: float, large_order_ratio: float, sample_size: int) -> float:
#         "Calculate confidence in the analysis (September 2025)"
#         data_quality = min(1.0, sample_size / 20)
#         signal_strength = abs(smart_money_index - 0.5) * 2
#         order_quality = large_order_ratio

#         confidence = data_quality * 0.4 + signal_strength * 0.4 + order_quality * 0.2
#         return min(1.0, confidence)

#     def _apply_ml_enhancement(self, symbol: str, prices: List[float], volumes: List[float]) -> Dict[str, Any]:
#         "Apply ML enhancements if available"
#         if not SKLEARN_AVAILABLE or not self.config.enable_ml_enhancement:
#             return {}

#         try:
            # Extract features for ML analysis
#             features = self._extract_ml_features(prices, volumes)

#             if len(features) < 10:
#                 return {}

            # Initialize or update regime model
#             if symbol not in self.regime_models:
#                 self.regime_models[symbol] = RandomForestClassifier(
#                     n_estimators=50,
#                     random_state=42,
#                     max_depth=5
# )

            # For now, return placeholder ML metrics
            # In a full implementation, this would use trained models
#             return {
# 'ml_regime_prediction': 'trending_up',  # Placeholder
# 'ml_confidence_score': 0.75,  # Placeholder
# 'ml_anomaly_probability': 0.1,  # Placeholder
# 'ml_signal_strength': 0.6,  # Placeholder
# }

#         except Exception as e:
#             self.logger.error(f"Error in ML enhancement for {symbol}: {e}")
#             return {}

#     def _extract_ml_features(self, prices: List[float], volumes: List[float]) -> np.ndarray:
#         "Extract features for ML analysis"
#         features = []
#         window_size = min(20, len(prices) // 2)

#         for i in range(window_size, len(prices)):
#             window_prices = prices[i-window_size:i]
#             window_volumes = volumes[i-window_size:i]

#             price_return = (window_prices[-1] - window_prices[0]) / window_prices[0] if window_prices[0] != 0 else 0
#             price_volatility = np.std(window_prices) / np.mean(window_prices) if np.mean(window_prices) > 0 else 0
#             volume_mean = np.mean(window_volumes)
#             volume_std = np.std(window_volumes)

#             features.append([price_return, price_volatility, volume_mean, volume_std])

#         return np.array(features)

    # Continue with the rest of the current system's methods but enhanced...
#     def _analyze_volume_patterns(self, symbol: str, prices: List[float], volumes: List[float]) -> Dict[str, float]:
#         "Analyze volume patterns (current system enhanced)"
#         if len(volumes) < self.config.short_window:
#             return {}

#         current_volume = volumes[-1]
#         avg_volume_short = np.mean(volumes[-self.config.short_window:])
#         avg_volume_medium = np.mean(volumes[-self.config.medium_window:])
#         avg_volume_long = np.mean(volumes[-self.config.long_window:]) if len(volumes) >= self.config.long_window else avg_volume_medium

#         volume_ratio_short = current_volume / avg_volume_short if avg_volume_short > 0 else 1.0
#         volume_ratio_medium = current_volume / avg_volume_medium if avg_volume_medium > 0 else 1.0
#         volume_ratio_long = current_volume / avg_volume_long if avg_volume_long > 0 else 1.0

#         volume_trend = np.corrcoef(range(len(volumes[-self.config.medium_window:])), volumes[-self.config.medium_window:])[0, 1]
#         volume_trend = 0 if np.isnan(volume_trend) else volume_trend

#         if len(volumes) >= 3:
#             volume_acceleration = (volumes[-1] - volumes[-3]) / 2
#         else:
#             volume_acceleration = 0

#         unusual_volume = volume_ratio_short > self.config.volume_threshold_multiplier

#         return {
# 'volume_ratio_short': volume_ratio_short,
# 'volume_ratio_medium': volume_ratio_medium,
# 'volume_ratio_long': volume_ratio_long,
# 'volume_trend': volume_trend,
# 'volume_acceleration': volume_acceleration,
# 'unusual_volume': unusual_volume,
# }

#     def _analyze_price_impact(self, symbol: str, prices: List[float], volumes: List[float]) -> Dict[str, float]:
#         "Analyze price impact of volume (current system)"
#         if len(prices) < self.config.short_window or len(volumes) < self.config.short_window:
#             return {}

#         price_changes = np.diff(prices)
#         aligned_volumes = volumes[1:]

#         if len(aligned_volumes) < self.config.short_window:
#             return {}

#         recent_period = min(self.config.short_window, len(price_changes))
#         price_impacts = price_changes[-recent_period:] / aligned_volumes[-recent_period:]
#         price_impact = np.mean(price_impacts) if len(price_impacts) > 0 else 0

# volume_price_corr = np.corrcoef(aligned_volumes[-self.config.medium_window:],
# price_changes[-self.config.medium_window:])[0, 1]
#         volume_price_corr = 0 if np.isnan(volume_price_corr) else volume_price_corr

#         buying_pressure = 0
#         selling_pressure = 0

#         for price_change, volume in zip(price_changes[-self.config.short_window:],
# aligned_volumes[-self.config.short_window:]):
#             if price_change > 0:
#                 buying_pressure += volume
#             elif price_change < 0:
#                 selling_pressure += volume

#         total_pressure = buying_pressure + selling_pressure
#         buying_pressure_ratio = buying_pressure / total_pressure if total_pressure > 0 else 0.5
#         selling_pressure_ratio = selling_pressure / total_pressure if total_pressure > 0 else 0.5

#         return {
# 'price_impact': price_impact,
# 'volume_price_correlation': volume_price_corr,
# 'buying_pressure': buying_pressure_ratio,
# 'selling_pressure': selling_pressure_ratio,
# 'net_pressure': buying_pressure_ratio - selling_pressure_ratio,
# }

#     def _analyze_institutional_flow(self, symbol: str) -> Dict[str, float]:
#         "Analyze institutional flow patterns (current system enhanced)"
#         if symbol not in self.trade_data or len(self.trade_data[symbol]) < 10:
#             return {}

#         recent_trades = list(self.trade_data[symbol])[-100:]

#         institutional_trades = [t for t in recent_trades if t['type'] == TradingActivityType.INSTITUTIONAL]
#         large_trades = [t for t in recent_trades if t['value'] > self.config.large_trade_threshold]

#         institutional_volume = sum(t['volume'] for t in institutional_trades)
#         institutional_value = sum(t['value'] for t in institutional_trades)

#         total_volume = sum(t['volume'] for t in recent_trades)
#         total_value = sum(t['value'] for t in recent_trades)

#         institutional_flow_ratio = institutional_volume / total_volume if total_volume > 0 else 0
#         large_trade_ratio = len(large_trades) / len(recent_trades) if recent_trades else 0

#         dark_pool_activity = self._estimate_dark_pool_activity_current(recent_trades)

#         block_trades = [t for t in recent_trades if t['value'] > self.config.large_trade_threshold * 5]
#         block_trade_activity = len(block_trades) / len(recent_trades) if recent_trades else 0

#         return {
# 'institutional_flow': institutional_flow_ratio,
# 'large_trade_ratio': large_trade_ratio,
# 'dark_pool_activity': dark_pool_activity,
# 'block_trade_activity': block_trade_activity,
# 'avg_institutional_size': np.mean([t['value'] for t in institutional_trades]) if institutional_trades else 0,
# }

#     def _estimate_dark_pool_activity_current(self, trades: List[Dict]) -> float:
#         "Estimate dark pool activity (current system)"
#         if len(trades) < 10:
#             return 0.0

#         large_trades = [t for t in trades if t['value'] > self.config.large_trade_threshold]

#         if not large_trades:
#             return 0.0

#         price_impacts = []
#         for i, trade in enumerate(large_trades[1:], 1):
#             prev_price = large_trades[i-1]['price']
#             price_change = abs(trade['price'] - prev_price) / prev_price
#             price_impacts.append(price_change)

#         avg_price_impact = np.mean(price_impacts) if price_impacts else 0
#         dark_pool_estimate = max(0, (0.01 - avg_price_impact) / 0.01)

#         return min(1.0, dark_pool_estimate)

#     def _detect_anomalies(self, symbol: str, prices: List[float], volumes: List[float]) -> Dict[str, float]:
#         "Detect anomalies in trading patterns (current system enhanced)"
#         if not SKLEARN_AVAILABLE:
#             return {'anomaly_score': 0.0, 'unusual_activity': False}

#         if len(prices) < self.config.medium_window:
#             return {'anomaly_score': 0.0, 'unusual_activity': False}

#         try:
#             features = self._extract_anomaly_features(prices, volumes)

#             if len(features) < 10:
#                 return {'anomaly_score': 0.0, 'unusual_activity': False}

#             if symbol not in self.anomaly_models:
#                 self.anomaly_models[symbol] = IsolationForest(
#                     contamination=self.config.anomaly_contamination,
#                     random_state=42
# )
#                 self.scalers[symbol] = StandardScaler()

#             features_scaled = self.scalers[symbol].fit_transform(features)
#             anomaly_scores = self.anomaly_models[symbol].fit_predict(features_scaled)
#             current_score = anomaly_scores[-1]

#             anomaly_score = 1.0 if current_score == -1 else 0.1
#             unusual_activity = current_score == -1

#             return {
# 'anomaly_score': anomaly_score,
# 'unusual_activity': unusual_activity,
# }

#         except Exception as e:
#             self.logger.error(f"Error in anomaly detection for {symbol}: {e}")
#             return {'anomaly_score': 0.0, 'unusual_activity': False}

#     def _extract_anomaly_features(self, prices: List[float], volumes: List[float]) -> np.ndarray:
#         "Extract features for anomaly detection (current system)"
#         features = []
#         window_size = min(20, len(prices) // 2)

#         for i in range(window_size, len(prices)):
#             window_prices = prices[i-window_size:i]
#             window_volumes = volumes[i-window_size:i]

#             price_return = (window_prices[-1] - window_prices[0]) / window_prices[0] if window_prices[0] != 0 else 0
#             price_volatility = np.std(window_prices) / np.mean(window_prices) if np.mean(window_prices) > 0 else 0
#             price_trend = np.corrcoef(range(len(window_prices)), window_prices)[0, 1] if len(window_prices) > 1 else 0

#             volume_mean = np.mean(window_volumes)
#             volume_std = np.std(window_volumes)
#             volume_trend = np.corrcoef(range(len(window_volumes)), window_volumes)[0, 1] if len(window_volumes) > 1 else 0

#             volume_price_corr = np.corrcoef(window_prices, window_volumes)[0, 1] if len(window_prices) > 1 and len(window_volumes) > 1 else 0

# features.append([
#                 price_return,
#                 price_volatility,
#                 price_trend,
#                 volume_mean,
#                 volume_std,
#                 volume_trend,
#                 volume_price_corr,
# ])

#         return np.array(features)

#     def _generate_unified_signal(self, symbol: str, timestamp: datetime,
# volume_metrics: Dict, price_impact_metrics: Dict,
# institutional_metrics: Dict, anomaly_metrics: Dict,
# sept_metrics: Dict, ml_metrics: Dict) -> SmartMoneyMetrics:
#         "Generate unified smart money signal combining all analyses"

        # Combine all metrics
# combined_metrics = {**volume_metrics, **price_impact_metrics, **institutional_metrics,
# **anomaly_metrics, **sept_metrics, **ml_metrics}

        # Calculate unified signal strength
#         signal_strength = self._calculate_unified_signal_strength(combined_metrics)

        # Determine signal type
#         smart_money_signal = self._determine_unified_smart_money_signal(signal_strength, combined_metrics)

        # Calculate unified confidence
#         confidence = self._calculate_unified_signal_confidence(combined_metrics)

        # Create SmartMoneyMetrics with all fields
#         return SmartMoneyMetrics(
            # Core fields
#             symbol=symbol,
#             timestamp=timestamp,

            # Current system volume metrics
#             volume_ratio=volume_metrics.get('volume_ratio_short', 1.0),
#             volume_trend=volume_metrics.get('volume_trend', 0.0),
#             unusual_volume=volume_metrics.get('unusual_volume', False),

            # Current system price impact metrics
#             price_impact=price_impact_metrics.get('price_impact', 0.0),
#             volume_price_correlation=price_impact_metrics.get('volume_price_correlation', 0.0),
#             buying_pressure=price_impact_metrics.get('buying_pressure', 0.5),
#             selling_pressure=price_impact_metrics.get('selling_pressure', 0.5),

            # Current system institutional metrics
#             institutional_flow=institutional_metrics.get('institutional_flow', 0.0),
#             large_trade_ratio=institutional_metrics.get('large_trade_ratio', 0.0),
#             dark_pool_activity=institutional_metrics.get('dark_pool_activity', 0.0),

            # Current system anomaly metrics
#             anomaly_score=anomaly_metrics.get('anomaly_score', 0.0),
#             unusual_activity=anomaly_metrics.get('unusual_activity', False),

            # September 2025 enhanced metrics
#             smart_money_index=sept_metrics.get('smart_money_index', 0.5),
#             institutional_bias=sept_metrics.get('institutional_bias', SmartMoneyBias.NEUTRAL),
#             activity_level=sept_metrics.get('activity_level', InstitutionalActivity.MINIMAL),
#             confidence=sept_metrics.get('confidence', confidence),
#             order_flow_type=sept_metrics.get('order_flow_type', OrderFlowType.BALANCED),
#             flow_direction=sept_metrics.get('flow_direction', type('Flow', (), {'value': 'neutral'})()),
#             net_flow=sept_metrics.get('net_flow', 0.0),
#             block_trade_activity=sept_metrics.get('block_trade_activity', 0.0),
#             dark_pool_estimate=sept_metrics.get('dark_pool_estimate', 0.0),
#             institutional_activity=sept_metrics.get('institutional_activity', 0.0),
#             institutional_flow_ratio=sept_metrics.get('institutional_flow_ratio', 0.0),
#             liquidity_condition=sept_metrics.get('liquidity_condition', LiquidityCondition.NORMAL),
#             absorption_detected=sept_metrics.get('absorption_detected', False),
#             liquidity_stress=sept_metrics.get('liquidity_stress', 0.0),
#             accumulation_phase=sept_metrics.get('accumulation_phase', False),
#             distribution_phase=sept_metrics.get('distribution_phase', False),
#             breakout_preparation=sept_metrics.get('breakout_preparation', False),
#             support_strength=sept_metrics.get('support_strength', 0.0),
#             resistance_strength=sept_metrics.get('resistance_strength', 0.0),
#             structural_shift=sept_metrics.get('structural_shift', False),

            # Unified signal metrics
#             smart_money_signal=smart_money_signal,
#             signal_strength=abs(signal_strength),
#             signal_confidence=confidence,
# )

#     def _calculate_unified_signal_strength(self, metrics: Dict[str, float]) -> float:
#         "Calculate unified smart money signal strength combining both systems"

#         strength = 0.0

        # Current system contributions
#         volume_ratio = metrics.get('volume_ratio_short', 1.0)
#         unusual_volume = metrics.get('unusual_volume', False)
#         volume_trend = metrics.get('volume_trend', 0.0)

#         if unusual_volume and volume_ratio > 1.5:
#             strength += 0.2 * (volume_ratio - 1.0) / volume_ratio
#         strength += 0.05 * max(0, volume_trend)

#         net_pressure = metrics.get('net_pressure', 0.0)
#         price_impact = metrics.get('price_impact', 0.0)

#         strength += 0.15 * net_pressure
#         if abs(price_impact) > 0.001:
#             strength += 0.1 * np.sign(price_impact)

        # September 2025 enhanced contributions
#         smart_money_index = metrics.get('smart_money_index', 0.5)
#         institutional_flow = metrics.get('institutional_flow', 0.0)
#         large_order_ratio = metrics.get('large_order_ratio', 0.0)
#         dark_pool_activity = metrics.get('dark_pool_activity', 0.0)

#         strength += 0.25 * (smart_money_index - 0.5) * 2  # Convert to -1 to 1 scale
#         strength += 0.15 * institutional_flow
#         strength += 0.1 * large_order_ratio
#         strength += 0.05 * dark_pool_activity

        # ML enhancement contributions
#         if metrics.get('ml_signal_strength'):
#             strength += 0.1 * metrics.get('ml_signal_strength', 0.0)

        # Anomaly contribution
#         anomaly_score = metrics.get('anomaly_score', 0.0)
#         unusual_activity = metrics.get('unusual_activity', False)

#         if unusual_activity:
#             strength += 0.05 * anomaly_score

#         return max(-1.0, min(1.0, strength))

#     def _determine_unified_smart_money_signal(self, strength: float, metrics: Dict[str, float]) -> SmartMoneySignal:
#         "Determine unified smart money signal type"

        # Check for manipulation patterns
#         unusual_activity = metrics.get('unusual_activity', False)
#         high_anomaly = metrics.get('anomaly_score', 0.0) > 0.8

#         if unusual_activity and high_anomaly:
#             return SmartMoneySignal.MANIPULATION

        # Consider September 2025 institutional bias
#         institutional_bias = metrics.get('institutional_bias', SmartMoneyBias.NEUTRAL)

        # Enhanced determination with institutional bias
#         if strength > 0.6 or institutional_bias in [SmartMoneyBias.STRONG_BULLISH, SmartMoneyBias.BULLISH]:
#             if strength > 0.8 or institutional_bias == SmartMoneyBias.STRONG_BULLISH:
#                 return SmartMoneySignal.STRONG_ACCUMULATION
#             else:
#                 return SmartMoneySignal.ACCUMULATION
#         elif strength < -0.6 or institutional_bias in [SmartMoneyBias.STRONG_BEARISH, SmartMoneyBias.BEARISH]:
#             if strength < -0.8 or institutional_bias == SmartMoneyBias.STRONG_BEARISH:
#                 return SmartMoneySignal.STRONG_DISTRIBUTION
#             else:
#                 return SmartMoneySignal.DISTRIBUTION
#         else:
#             return SmartMoneySignal.NEUTRAL

#     def _calculate_unified_signal_confidence(self, metrics: Dict[str, float]) -> float:
#         "Calculate unified signal confidence combining both systems"

#         confidence_factors = []

        # Current system confidence factors
#         volume_ratio = metrics.get('volume_ratio_short', 1.0)
#         unusual_volume = metrics.get('unusual_volume', False)
#         if unusual_volume:
#             confidence_factors.append(min(1.0, volume_ratio / 3.0))

#         institutional_flow = metrics.get('institutional_flow', 0.0)
#         if institutional_flow > 0.1:
#             confidence_factors.append(min(1.0, institutional_flow * 2))

#         volume_price_corr = abs(metrics.get('volume_price_correlation', 0.0))
#         if volume_price_corr > 0.3:
#             confidence_factors.append(min(1.0, volume_price_corr))

        # September 2025 confidence factors
#         smart_money_index = metrics.get('smart_money_index', 0.5)
#         confidence_factors.append(abs(smart_money_index - 0.5) * 2)  # Distance from neutral

#         confidence_factors.append(metrics.get('confidence', 0.5))  # Sept 2025 confidence

        # ML confidence
#         if metrics.get('ml_confidence_score'):
#             confidence_factors.append(metrics.get('ml_confidence_score', 0.0))

        # Anomaly confidence
#         anomaly_score = metrics.get('anomaly_score', 0.0)
#         if metrics.get('unusual_activity', False):
#             confidence_factors.append(anomaly_score)

#         if confidence_factors:
#             return np.mean(confidence_factors)
#         else:
#             return 0.5

#     def _check_enhanced_alerts(self, metrics: SmartMoneyMetrics, ml_signal: Optional[SmartMoneyMLSignal] = None):
#         "Check for enhanced smart money alerts"

        # Volume spike alert (enhanced)
#         if metrics.volume_ratio > self.alert_thresholds['volume_spike']:
# alert = SmartMoneyAlert(
#                 alert_type="volume_spike",
#                 severity="high",
#                 message=f"Unusual volume spike detected: {metrics.volume_ratio:.2f}x average",
#                 symbol=metrics.symbol,
#                 timestamp=metrics.timestamp,
#                 metrics={'volume_ratio': metrics.volume_ratio},
#                 threshold=self.alert_thresholds['volume_spike'],
#                 actual_value=metrics.volume_ratio,
#                 institutional_bias=metrics.institutional_bias,
#                 ml_enhanced=self.config.enable_ml_enhancement,
# )
#             self.alerts.append(alert)

        # Smart money index alert (September 2025)
#         if metrics.smart_money_index > self.alert_thresholds['smart_money_index']:
# alert = SmartMoneyAlert(
#                 alert_type="high_smart_money_index",
#                 severity="medium",
#                 message=f"High smart money index detected: {metrics.smart_money_index:.2f}",
#                 symbol=metrics.symbol,
#                 timestamp=metrics.timestamp,
#                 metrics={'smart_money_index': metrics.smart_money_index},
#                 threshold=self.alert_thresholds['smart_money_index'],
#                 actual_value=metrics.smart_money_index,
#                 institutional_bias=metrics.institutional_bias,
#                 order_flow_type=metrics.order_flow_type,
#                 ml_enhanced=self.config.enable_ml_enhancement,
# )
#             self.alerts.append(alert)

        # Institutional activity alert (enhanced)
#         if metrics.institutional_flow > self.alert_thresholds['institutional_flow']:
# alert = SmartMoneyAlert(
#                 alert_type="institutional_activity",
#                 severity="medium",
#                 message=f"High institutional activity detected: {metrics.institutional_flow:.2%}",
#                 symbol=metrics.symbol,
#                 timestamp=metrics.timestamp,
#                 metrics={'institutional_flow': metrics.institutional_flow},
#                 threshold=self.alert_thresholds['institutional_flow'],
#                 actual_value=metrics.institutional_flow,
#                 institutional_bias=metrics.institutional_bias,
#                 activity_level=metrics.activity_level,
#                 ml_enhanced=self.config.enable_ml_enhancement,
# )
#             self.alerts.append(alert)

        # Anomaly alert (enhanced)
#         if metrics.unusual_activity and metrics.anomaly_score > self.alert_thresholds['anomaly_score']:
# alert = SmartMoneyAlert(
#                 alert_type="anomaly_detected",
#                 severity="high",
#                 message=f"Unusual trading activity detected: anomaly score {metrics.anomaly_score:.2f}",
#                 symbol=metrics.symbol,
#                 timestamp=metrics.timestamp,
#                 metrics={'anomaly_score': metrics.anomaly_score},
#                 threshold=self.alert_thresholds['anomaly_score'],
#                 actual_value=metrics.anomaly_score,
#                 order_flow_type=metrics.order_flow_type,
#                 ml_enhanced=self.config.enable_ml_enhancement,
# )
#             self.alerts.append(alert)

    # API Compatibility Methods
#     def get_smart_money_signal(self, symbol: str) -> float:
# "Get current smart money signal for a symbol (API compatibility)""
#         if symbol in self.current_signals:
#             metrics = self.current_signals[symbol]

            # Convert signal to -1 to 1 scale
# signal_map = {
# SmartMoneySignal.STRONG_ACCUMULATION: 0.8,
# SmartMoneySignal.ACCUMULATION: 0.5,
# SmartMoneySignal.NEUTRAL: 0.0,
# SmartMoneySignal.DISTRIBUTION: -0.5,
# SmartMoneySignal.STRONG_DISTRIBUTION: -0.8,
# SmartMoneySignal.MANIPULATION: 0.0,
# }

#             base_signal = signal_map.get(metrics.smart_money_signal, 0.0)
#             weighted_signal = base_signal * metrics.signal_strength * metrics.signal_confidence

#             return max(-1.0, min(1.0, weighted_signal))

#         return 0.0

#     def get_smart_money_metrics(self, symbol: str) -> Optional[SmartMoneyMetrics]:
#         "Get comprehensive smart money metrics for a symbol"
#         return self.current_signals.get(symbol)

#     def get_recent_alerts(self, limit: int = 10) -> List[SmartMoneyAlert]:
#         "Get recent smart money alerts (enhanced)"
#         return list(self.alerts)[-limit:]

#     def get_analysis_summary(self) -> Dict[str, Any]:
#         "Get comprehensive analysis summary (enhanced)"
#         with self.lock:
# summary = {
# 'total_symbols_analyzed': len(self.current_signals),
# 'analysis_count': self.analysis_count,
# 'last_analysis': self.last_analysis.isoformat() if self.last_analysis else None,
# 'current_signals': {},
# 'alert_count': len(self.alerts),
# 'ml_enhanced': self.config.enable_ml_enhanced,
# 'sept2025_features': True,
# }

            # Summarize current signals
#             signal_counts = defaultdict(int)
#             bias_counts = defaultdict(int)
#             activity_counts = defaultdict(int)

#             for metrics in self.current_signals.values():
#                 signal_counts[metrics.smart_money_signal.value] += 1
#                 bias_counts[metrics.institutional_bias.value] += 1
#                 activity_counts[metrics.activity_level.value] += 1

#             summary['signal_distribution'] = dict(signal_counts)
#             summary['bias_distribution'] = dict(bias_counts)
#             summary['activity_distribution'] = dict(activity_counts)

            # Average metrics (enhanced)
#             if self.current_signals:
# avg_metrics = {
# 'avg_volume_ratio': np.mean([m.volume_ratio for m in self.current_signals.values()]),
# 'avg_signal_strength': np.mean([m.signal_strength for m in self.current_signals.values()]),
# 'avg_confidence': np.mean([m.signal_confidence for m in self.current_signals.values()]),
# 'avg_smart_money_index': np.mean([m.smart_money_index for m in self.current_signals.values()]),
# 'avg_institutional_flow': np.mean([m.institutional_flow for m in self.current_signals.values()]),
# 'avg_institutional_activity': np.mean([m.institutional_activity for m in self.current_signals.values()]),
# 'symbols_with_unusual_activity': sum(1 for m in self.current_signals.values() if m.unusual_activity),
# 'symbols_with_accumulation_phase': sum(1 for m in self.current_signals.values() if m.accumulation_phase),
# 'symbols_with_distribution_phase': sum(1 for m in self.current_signals.values() if m.distribution_phase),
# 'symbols_with_absorption_detected': sum(1 for m in self.current_signals.values() if m.absorption_detected),
# }
#                 summary['average_metrics'] = avg_metrics

#             return summary

#     def update_models(self):
#         "Update analysis models periodically (enhanced)"
#         try:
            # Clean up old data
#             self._cleanup_old_data()

            # Retrain ML models if enabled
#             if self.config.enable_ml_enhancement and SKLEARN_AVAILABLE:
#                 self._retrain_ml_models()

            # Update September 2025 models
#             self._update_sept2025_models()

#             self.logger.info("Enhanced smart money models updated")
#         except Exception as e:
#             self.logger.error(f"Error updating smart money models: {e}")

#     def _cleanup_old_data(self):
#         "Clean up old data (enhanced)"
#         cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)

        # Clean up current system data
#         for symbol in list(self.trade_data.keys()):
#             while (self.trade_data[symbol] and
#                     self.trade_data[symbol][0]['timestamp'] < cutoff_time):
#                 self.trade_data[symbol].popleft()

        # Clean up September 2025 data
#         for symbol in list(self.order_flow_data.keys()):
#             while (self.order_flow_data[symbol] and
#                     self.order_flow_data[symbol][0].timestamp < cutoff_time):
#                 self.order_flow_data[symbol].popleft()

#     def _retrain_ml_models(self):
#         "Retrain ML models (placeholder for future implementation)"
        # This would implement model retraining logic
#         pass

#     def _update_sept2025_models(self):
#         "Update September 2025 models (placeholder for future implementation)"
        # This would implement September 2025 model updates
#         pass

#     def get_ml_enhanced_signal(self, symbol: str) -> Optional[SmartMoneyMLSignal]:
#         "Get ML-enhanced smart money signal for a symbol"
#         if self.ml_processor and symbol in self.ml_processor.signal_history:
#             return list(self.ml_processor.signal_history[symbol])[-1]
#         return None

#     def update_ml_performance(self, symbol: str, actual_return: float, success: bool):
#         "Update ML performance with actual trading results"
#         if self.ml_processor:
#             ml_signal = self.get_ml_enhanced_signal(symbol)
#             if ml_signal:
#                 self.ml_processor.update_performance(symbol, ml_signal, actual_return, success)

#     def get_ml_performance_summary(self, symbol: str) -> Dict[str, Any]:
#         "Get ML performance summary for a symbol"
#         if self.ml_processor:
#             return self.ml_processor.get_performance_summary(symbol)
#         return {}

#     def get_enhanced_analysis_summary(self) -> Dict[str, Any]:
#         "Get comprehensive analysis summary including ML insights"
#         summary = self.get_analysis_summary()

        # Add ML-specific summary
#         if self.ml_processor:
# ml_summary = {
# 'ml_integration_enabled': True,
# 'ml_models_performance': {},
# 'ml_signal_count': sum(len(signals) for signals in self.ml_processor.signal_history.values()),
# 'ml_training_samples': sum(len(data) for data in self.ml_processor.training_data.values()),
# }

            # Add performance for each symbol
#             for symbol in self.current_signals.keys():
#                 ml_summary['ml_models_performance'][symbol] = self.get_ml_performance_summary(symbol)

#             summary['ml_integration'] = ml_summary
#         else:
#             summary['ml_integration'] = {'enabled': False}

#         return summary

#     def shutdown(self):
#         "Shutdown the enhanced smart money analysis engine"
#         if self.ml_processor:
#             self.logger.info("Shutting down ML processor...")
            # ML processor cleanup if needed

#         self.logger.info("Enhanced Smart Money Analysis Engine shutdown complete")


# Factory function for enhanced system
# def create_enhanced_smart_money_engine(
#     volume_threshold_multiplier: float = 2.0,
#     anomaly_contamination: float = 0.1,
#     enable_anomaly_detection: bool = True,
#     enable_ml_enhancement: bool = True,
#     lookback_period: int = 100,
#     large_order_threshold: float = 2.0,
# ) -> EnhancedSmartMoneyAnalysisEngine:
#     "Create enhanced smart money analysis engine with specified configuration"

# config = SmartMoneyConfig(
#         volume_threshold_multiplier=volume_threshold_multiplier,
#         anomaly_contamination=anomaly_contamination,
#         enable_anomaly_detection=enable_anomaly_detection,
#         enable_ml_enhancement=enable_ml_enhancement,
#         lookback_period=lookback_period,
#         large_order_threshold=large_order_threshold,
# )

#     return EnhancedSmartMoneyAnalysisEngine(config)


# Export all classes and functions
# __all__ = [
    # Enums
#     "TradingActivityType",
#     "SmartMoneySignal",
#     "SmartMoneyBias",
#     "InstitutionalActivity",
#     "OrderFlowType",
#     "LiquidityCondition",

    # Data classes
#     "SmartMoneyConfig",
#     "SmartMoneyMetrics",
#     "SmartMoneyAlert",
#     "OrderFlowData",

    # Main classes
#     "EnhancedSmartMoneyAnalysisEngine",

    # Factory functions
#     "create_enhanced_smart_money_engine",
# ]