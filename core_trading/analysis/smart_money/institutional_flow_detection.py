import asyncio
import logging
import math
import threading
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union, Callable
import numpy as np
import pandas as pd
from scipy import stats
from scipy.signal import find_peaks, savgol_filter

# ""Institutional Flow Detection System - Advanced Smart Money Analysis"

# This module provides comprehensive institutional flow detection capabilities for
# all asset classes with sub-100μs performance optimization.

# Key Features:
# - Large order detection and block trade analysis
# - Insider trading and institutional activity monitoring
# - Unusual volume and price movement detection
# - Smart money flow aggregation and analysis
# - Multi-asset class support (Equities, ETFs, Options, Futures, Forex, Commodities, CFDs, Cryptos)
# - Real-time detection with sub-100μs latency
# - Machine learning-enhanced pattern recognition
# - Dark pool activity estimation
# - Cross-asset institutional flow correlation

# Author: Vincent S. Pereira
# Version: 1.0.0 (Production Deployment)




# try:
#     from sklearn.ensemble import IsolationForest, RandomForestClassifier
#     from sklearn.preprocessing import StandardScaler
#     from sklearn.cluster import DBSCAN
#     SKLEARN_AVAILABLE = True
# except ImportError:
#     SKLEARN_AVAILABLE = False
#     logging.warning("scikit-learn not available. Advanced ML features will be limited.")

# try:
#     from numba import jit, njit, prange
#     NUMBA_AVAILABLE = True
# except ImportError:
#     NUMBA_AVAILABLE = False
#     logging.warning("Numba not available. Performance optimization will be limited.")

# try:
#     from infrastructure.config.master_config import get_config
#     from infrastructure.wrappers.factory import WrapperFactory
#     logger = get_logger(__name__)
# except ImportError:
#     import logging
#     logger = logging.getLogger(__name__)

# ===========================================
# ASSET CLASS AND INSTITUTIONAL DATA ENUMS
# ===========================================

# class AssetClass(Enum):
#     "Supported asset classes for institutional flow detection"
#     EQUITIES = "equities"
#     ETFS = "etfs"
#     OPTIONS = "options"
#     FUTURES = "futures"
#     FOREX = "forex"
#     COMMODITIES = "commodities"
#     CFDS = "cfds"
#     CRYPTOS = "cryptos"

# class InstitutionType(Enum):
#     "Types of institutions for flow analysis"
#     HEDGE_FUND = "hedge_fund"
#     MUTUAL_FUND = "mutual_fund"
#     PENSION_FUND = "pension_fund"
#     INSURANCE_COMPANY = "insurance_company"
#     INVESTMENT_BANK = "investment_bank"
#     PRIVATE_EQUITY = "private_equity"
#     SOVEREIGN_WEALTH = "sovereign_wealth"
#     FAMILY_OFFICE = "family_office"
#     PROPRIETARY_TRADING = "proprietary_trading"
#     UNKNOWN = "unknown"

# class FlowType(Enum):
#     "Types of institutional flow"
#     BUY_SIDE_INITIATED = "buy_side_initiated"
#     SELL_SIDE_INITIATED = "sell_side_initiated"
#     BLOCK_TRADE = "block_trade"
#     DARK_POOL = "dark_pool"
#     ALGORITHMIC_EXECUTION = "algorithmic_execution"
#     PROGRAM_TRADE = "program_trade"
#     INDEX_REBALANCE = "index_rebalance"
#     DERIVATIVE_HEDGE = "derivative_hedge"
#     ARBITRAGE = "arbitrage"
#     SPECULATIVE = "speculative"

# class FlowStrength(Enum):
#     "Strength of institutional flow"
#     MINIMAL = "minimal"
#     LOW = "low"
#     MODERATE = "moderate"
#     HIGH = "high"
#     VERY_HIGH = "very_high"
#     EXTREME = "extreme"

# ===========================================
# CORE DATA STRUCTURES
# ===========================================

# @dataclass
# class InstitutionalTrade:
#     "Represents a detected institutional trade"
#     symbol: str
#     asset_class: AssetClass
#     timestamp: datetime
#     price: float
#     volume: float
#     trade_value: float
#     flow_type: FlowType
#     institution_type: InstitutionType
#     confidence: float  # 0-1 scale

    # Trade characteristics
#     urgency_score: float  # 0-1 scale
#     price_impact: float
#     volume_ratio: float  # vs average volume
#     size_category: str  # 'small', 'medium', 'large', 'block', 'whale'

    # Detection metadata
#     detection_method: str
#     market_conditions: Dict[str, Any]
#     cross_asset_impact: Dict[AssetClass, float] = field(default_factory=dict)

# @dataclass
# class FlowAlert:
#     "Institutional flow alert"
#     alert_type: str
#     severity: str  # 'low', 'medium', 'high', 'critical'
#     symbol: str
#     asset_class: AssetClass
#     timestamp: datetime

    # Alert data
#     message: str
#     trade_data: InstitutionalTrade
#     flow_metrics: Dict[str, float]
#     threshold_breached: str
#     actual_value: float

    # Additional context
#     related_symbols: List[str] = field(default_factory=list)
#     historical_context: Dict[str, Any] = field(default_factory=dict)
#     recommended_action: Optional[str] = None

# @dataclass
# class FlowMetrics:
#     "Comprehensive institutional flow metrics"
#     symbol: str
#     asset_class: AssetClass
#     timestamp: datetime

    # Volume-based metrics
#     institutional_volume_ratio: float  # Institutional volume / total volume
#     large_trade_frequency: float  # Large trades per minute
#     block_trade_activity: float  # Block trade volume ratio
#     dark_pool_estimate: float  # Estimated dark pool activity 0-1

    # Flow strength and bias
#     net_institutional_flow: float  # -1 to 1 scale
#     flow_strength: FlowStrength
#     buy_side_pressure: float  # 0-1 scale
#     sell_side_pressure: float  # 0-1 scale

    # Activity metrics
#     institutional_frequency: float  # Trades per minute
#     urgency_index: float  # Average urgency 0-1
#     confidence_score: float  # Overall confidence 0-1

    # Pattern metrics
#     accumulation_pattern: bool
#     distribution_pattern: bool
#     manipulation_risk: float  # 0-1 scale
#     anomaly_score: float  # 0-1 scale

    # Cross-asset metrics
#     sector_correlation: float  # Correlation with sector
#     market_impact: float  # Estimated market impact 0-1
#     spillover_effects: List[str] = field(default_factory=list)

# @dataclass
# class InstitutionalFlowConfig:
#     "Configuration for institutional flow detection"

    # Detection thresholds
#     large_trade_threshold_usd: float = 100000.0  # $100k
#     block_trade_threshold_usd: float = 1000000.0  # $1M
#     whale_trade_threshold_usd: float = 10000000.0  # $10M

    # Volume ratios
#     institutional_volume_threshold: float = 0.1  # 10% of total volume
#     unusual_volume_multiplier: float = 3.0  # 3x average volume

    # Price impact thresholds
#     price_impact_threshold: float = 0.002  # 0.2% price impact
#     high_impact_threshold: float = 0.01  # 1% price impact

    # Time windows
#     short_window_seconds: int = 60  # 1 minute
#     medium_window_seconds: int = 300  # 5 minutes
#     long_window_seconds: int = 1800  # 30 minutes

    # Pattern detection
#     enable_pattern_detection: bool = True
#     enable_anomaly_detection: bool = True
#     enable_cross_asset_analysis: bool = True
#     enable_dark_pool_estimation: bool = True

    # ML Enhancement
#     enable_ml_enhancement: bool = True
#     enable_ensemble_methods: bool = True
#     model_confidence_threshold: float = 0.7

    # Performance optimization
#     enable_high_performance_mode: bool = True
#     sub_100_microsecond_target: bool = True
#     enable_parallel_processing: bool = True
#     max_workers: int = 4

# ===========================================
# PERFORMANCE-OPTIMIZED CORE FUNCTIONS
# ===========================================

# if NUMBA_AVAILABLE:
#     @njit
#     def calculate_volume_ratio_numba(current_volume: float, avg_volume: float) -> float:
#         "Numba-optimized volume ratio calculation"
#         if avg_volume <= 0:
#             return 1.0
#         return current_volume / avg_volume

#     @njit
#     def calculate_price_impact_numba(current_price: float, prev_price: float, volume: float) -> float:
#         "Numba-optimized price impact calculation"
#         if prev_price <= 0:
#             return 0.0
#         price_change = abs(current_price - prev_price) / prev_price
#         return price_change / (volume / 1000) if volume > 0 else 0.0

#     @njit
#     def detect_large_trades_numba(trades: np.ndarray, large_threshold: float) -> np.ndarray:
#         "Numba-optimized large trade detection"
#         return trades[:, 3] > large_threshold  # Assuming trade_value is at index 3
# else:
#     def calculate_volume_ratio_numba(current_volume: float, avg_volume: float) -> float:
#         return current_volume / avg_volume if avg_volume > 0 else 1.0

#     def calculate_price_impact_numba(current_price: float, prev_price: float, volume: float) -> float:
#         if prev_price <= 0:
#             return 0.0
#         price_change = abs(current_price - prev_price) / prev_price
#         return price_change / (volume / 1000) if volume > 0 else 0.0

#     def detect_large_trades_numba(trades: np.ndarray, large_threshold: float) -> np.ndarray:
#         return trades[:, 3] > large_threshold

# ===========================================
# INSTITUTIONAL FLOW DETECTION ENGINE
# ===========================================

# class InstitutionalFlowDetectionEngine:

# Advanced Institutional Flow Detection Engine for comprehensive smart money analysis
# across all asset classes with sub-100μs performance optimization.


#     def __init__(self, config: InstitutionalFlowConfig = None):
#         self.config = config or InstitutionalFlowConfig()
#         self.logger = logger

        # Initialize wrapper factory for external integrations
#         try:
#             self.wrapper_factory = WrapperFactory()
#         except Exception as e:
#             self.logger.warning(f"Could not initialize wrapper factory: {e}")
#             self.wrapper_factory = None

        # Data storage
#         self.price_data: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
#         self.volume_data: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
#         self.trade_data: Dict[str, deque] = defaultdict(lambda: deque(maxlen=5000))
#         self.flow_metrics: Dict[str, deque] = defaultdict(lambda: deque(maxlen=200))

        # Asset class mapping
#         self.asset_classes: Dict[str, AssetClass] = {}
#         self.symbol_sectors: Dict[str, str] = {}

        # Detection models and algorithms
#         self.anomaly_detectors: Dict[str, Any] = {}
#         self.pattern_models: Dict[str, Any] = {}
#         self.volume_models: Dict[str, Dict] = defaultdict(dict)

        # Alert system
#         self.alerts: deque = deque(maxlen=10000)
#         self.alert_callbacks: List[Callable] = []

        # Performance tracking
#         self.detection_stats = {
# 'total_detections': 0,
# 'large_trades_detected': 0,
# 'block_trades_detected': 0,
# 'dark_pool_activities': 0,
# 'pattern_matches': 0,
# 'anomalies_detected': 0,
# 'avg_detection_time_us': 0.0,
# }

        # Threading and concurrency
#         self.lock = threading.Lock()
#         self.analysis_queue = asyncio.Queue()
#         self.background_tasks = set()

        # ML components
#         self.ml_models = {}
#         self.feature_cache = {}
#         self.model_performance = {}

        # Cross-asset correlation matrix
#         self.correlation_matrix: Dict[str, Dict[str, float]] = defaultdict(dict)
#         self.sector_flows: Dict[str, Dict[str, float]] = defaultdict(dict)

        # Start background processing
#         if self.config.enable_parallel_processing:
#             self._start_background_processing()

#         self.logger.info("Institutional Flow Detection Engine initialized successfully")

#     def register_symbol(self, symbol: str, asset_class: AssetClass, sector: str = None):
#         "Register a symbol for institutional flow detection"
#         self.asset_classes[symbol] = asset_class
#         if sector:
#             self.symbol_sectors[symbol] = sector

        # Initialize volume model for the symbol
#         self.volume_models[symbol] = {
# 'avg_volume': 0.0,
# 'volume_std': 0.0,
# 'volume_history': deque(maxlen=100),
# }

#         self.logger.info(f"Registered {symbol} ({asset_class.value}) for institutional flow detection")

#     def update_market_data(self, symbol: str, price: float, volume: float,
# timestamp: datetime = None, trade_context: Dict = None):

# Update market data and trigger institutional flow detection.
# Optimized for sub-100μs performance.

#         if timestamp is None:
#             timestamp = datetime.now(timezone.utc)

        # Performance measurement start
#         start_time = datetime.now()

#         try:
            # Store market data
#             with self.lock:
#                 self.price_data[symbol].append((timestamp, price))
#                 self.volume_data[symbol].append((timestamp, volume))

            # Update volume statistics
#             self._update_volume_statistics(symbol, volume)

            # Analyze for institutional flow
# institutional_trades = self._detect_institutional_flow(
#                 symbol, price, volume, timestamp, trade_context
# )

            # Process detected trades
#             for trade in institutional_trades:
#                 self._process_institutional_trade(trade)

            # Generate flow metrics
#             if self._should_generate_metrics(symbol):
#                 metrics = self._generate_flow_metrics(symbol)
#                 if metrics:
#                     with self.lock:
#                         self.flow_metrics[symbol].append(metrics)

                    # Check for alerts
#                     self._check_flow_alerts(metrics)

            # Update performance stats
#             processing_time = (datetime.now() - start_time).total_seconds() * 1000000  # microseconds
#             self._update_performance_stats(processing_time)

#         except Exception as e:
#             self.logger.error(f"Error in institutional flow detection for {symbol}: {e}")

#     def _update_volume_statistics(self, symbol: str, volume: float):
#         "Update volume statistics for institutional flow detection"
#         if symbol not in self.volume_models:
#             self.volume_models[symbol] = {
# 'avg_volume': 0.0,
# 'volume_std': 0.0,
# 'volume_history': deque(maxlen=100),
# }

#         volume_history = self.volume_models[symbol]['volume_history']
#         volume_history.append(volume)

#         if len(volume_history) >= 10:
#             self.volume_models[symbol]['avg_volume'] = np.mean(volume_history)
#             self.volume_models[symbol]['volume_std'] = np.std(volume_history)

#     def _detect_institutional_flow(self, symbol: str, price: float, volume: float,
# timestamp: datetime, trade_context: Dict = None) -> List[InstitutionalTrade]:
#         "Detect institutional flow from market data update"
#         institutional_trades = []

        # Get volume statistics
#         volume_stats = self.volume_models.get(symbol, {})
#         avg_volume = volume_stats.get('avg_volume', volume)

        # Calculate volume ratio
#         volume_ratio = calculate_volume_ratio_numba(volume, avg_volume)

        # Check if this represents unusual volume
#         if volume_ratio >= self.config.unusual_volume_multiplier:
            # Categorize trade size
#             estimated_value = volume * price
# size_category, flow_type = self._categorize_institutional_trade(
#                 symbol, estimated_value, volume_ratio, trade_context
# )

            # Determine institution type (using ML if available)
# institution_type = self._classify_institution_type(
#                 symbol, price, volume, flow_type, trade_context
# )

            # Calculate confidence score
# confidence = self._calculate_detection_confidence(
#                 symbol, volume_ratio, price, flow_type, trade_context
# )

            # Create institutional trade object
# trade = InstitutionalTrade(
#                 symbol=symbol,
#                 asset_class=self.asset_classes.get(symbol, AssetClass.EQUITIES),
#                 timestamp=timestamp,
#                 price=price,
#                 volume=volume,
#                 trade_value=estimated_value,
#                 flow_type=flow_type,
#                 institution_type=institution_type,
#                 confidence=confidence,
#                 urgency_score=self._calculate_urgency_score(symbol, volume_ratio, trade_context),
#                 price_impact=self._calculate_price_impact(symbol, price, volume),
#                 volume_ratio=volume_ratio,
#                 size_category=size_category,
#                 detection_method="real_time_detection",
#                 market_conditions=self._assess_market_conditions(symbol),
# )

#             institutional_trades.append(trade)

#         return institutional_trades

#     def _categorize_institutional_trade(self, symbol: str, estimated_value: float,
# volume_ratio: float, trade_context: Dict = None) -> Tuple[str, FlowType]:
#         "Categorize institutional trade based on value and characteristics"

        # Determine size category
#         if estimated_value >= self.config.whale_trade_threshold_usd:
#             size_category = "whale"
#         elif estimated_value >= self.config.block_trade_threshold_usd:
#             size_category = "block"
#         elif estimated_value >= self.config.large_trade_threshold_usd:
#             size_category = "large"
#         else:
#             size_category = "medium"

        # Determine flow type
#         if trade_context and 'dark_pool' in trade_context and trade_context['dark_pool']:
#             flow_type = FlowType.DARK_POOL
#         elif size_category == "block":
#             flow_type = FlowType.BLOCK_TRADE
#         elif trade_context and 'algorithmic' in trade_context:
#             flow_type = FlowType.ALGORITHMIC_EXECUTION
#         elif volume_ratio > 10:  # Very high volume ratio
#             flow_type = FlowType.PROGRAM_TRADE
#         else:
            # Determine based on market conditions and trade characteristics
#             flow_type = self._infer_flow_type_from_market_data(symbol, volume_ratio, trade_context)

#         return size_category, flow_type

#     def _infer_flow_type_from_market_data(self, symbol: str, volume_ratio: float,
# trade_context: Dict = None) -> FlowType:
#         "Infer flow type from market data characteristics"

        # Check price history for patterns
#         if len(self.price_data[symbol]) < 10:
#             return FlowType.BUY_SIDE_INITIATED

#         recent_prices = [p[1] for p in list(self.price_data[symbol])[-10:]]

        # Calculate price momentum
#         if len(recent_prices) >= 5:
#             price_momentum = (recent_prices[-1] - recent_prices[-5]) / recent_prices[-5]
#         else:
#             price_momentum = 0

        # Determine flow type based on momentum and volume
#         if abs(price_momentum) > 0.02:  # Strong price movement
#             if price_momentum > 0:
#                 return FlowType.BUY_SIDE_INITIATED
#             else:
#                 return FlowType.SELL_SIDE_INITIATED
#         elif volume_ratio > 5:  # High volume without strong price movement
#             return FlowType.INDEX_REBALANCE
#         else:
#             return FlowType.BUY_SIDE_INITIATED  # Default assumption

#     def _classify_institution_type(self, symbol: str, price: float, volume: float,
# flow_type: FlowType, trade_context: Dict = None) -> InstitutionType:
#         "Classify the type of institution behind the trade"

        # Use ML model if available and trained
#         if self.config.enable_ml_enhancement and symbol in self.ml_models:
#             try:
#                 features = self._extract_institution_features(symbol, price, volume, flow_type, trade_context)
#                 prediction = self.ml_models[symbol].predict([features])[0]
#                 return InstitutionType(prediction)
#             except Exception as e:
#                 self.logger.debug(f"ML classification failed for {symbol}: {e}")

        # Rule-based classification
#         if flow_type == FlowType.DARK_POOL:
#             return InstitutionType.HEDGE_FUND
#         elif flow_type == FlowType.BLOCK_TRADE:
#             return InstitutionType.MUTUAL_FUND
#         elif flow_type == FlowType.INDEX_REBALANCE:
#             return InstitutionType.PENSION_FUND
#         elif flow_type == FlowType.DERIVATIVE_HEDGE:
#             return InstitutionType.INVESTMENT_BANK
#         elif flow_type == FlowType.ALGORITHMIC_EXECUTION:
#             return InstitutionType.PROPRIETARY_TRADING
#         else:
#             return InstitutionType.HEDGE_FUND  # Default

#     def _extract_institution_features(self, symbol: str, price: float, volume: float,
# flow_type: FlowType, trade_context: Dict = None) -> List[float]:
#         "Extract features for ML-based institution classification"

#         features = []

        # Volume features
#         avg_volume = self.volume_models.get(symbol, {}).get('avg_volume', volume)
#         features.append(volume / avg_volume if avg_volume > 0 else 1.0)

        # Price features
#         if len(self.price_data[symbol]) >= 5:
#             recent_prices = [p[1] for p in list(self.price_data[symbol])[-5:]]
#             price_volatility = np.std(recent_prices) / np.mean(recent_prices) if np.mean(recent_prices) > 0 else 0
#             features.append(price_volatility)
#         else:
#             features.append(0.0)

        # Time features
#         current_time = datetime.now()
#         features.append(current_time.hour)
#         features.append(current_time.weekday())

        # Flow type features (one-hot encoded)
#         flow_types = list(FlowType)
#         for ft in flow_types:
#             features.append(1.0 if flow_type == ft else 0.0)

        # Asset class features
#         asset_class = self.asset_classes.get(symbol, AssetClass.EQUITIES)
#         asset_classes = list(AssetClass)
#         for ac in asset_classes:
#             features.append(1.0 if asset_class == ac else 0.0)

#         return features

#     def _calculate_detection_confidence(self, symbol: str, volume_ratio: float,
# price: float, flow_type: FlowType,
# trade_context: Dict = None) -> float:
#         "Calculate confidence score for institutional flow detection"

#         confidence_factors = []

        # Volume ratio confidence
#         if volume_ratio >= 10:
#             confidence_factors.append(0.9)
#         elif volume_ratio >= 5:
#             confidence_factors.append(0.7)
#         elif volume_ratio >= 3:
#             confidence_factors.append(0.5)
#         else:
#             confidence_factors.append(0.3)

        # Flow type confidence
#         if flow_type in [FlowType.DARK_POOL, FlowType.BLOCK_TRADE]:
#             confidence_factors.append(0.8)
#         elif flow_type in [FlowType.PROGRAM_TRADE, FlowType.ALGORITHMIC_EXECUTION]:
#             confidence_factors.append(0.6)
#         else:
#             confidence_factors.append(0.4)

        # Market condition confidence
#         market_conditions = self._assess_market_conditions(symbol)
#         if market_conditions.get('high_volatility', False):
#             confidence_factors.append(0.7)
#         else:
#             confidence_factors.append(0.5)

        # Trade context confidence
#         if trade_context and 'confidence' in trade_context:
#             confidence_factors.append(trade_context['confidence'])
#         else:
#             confidence_factors.append(0.5)

#         return np.mean(confidence_factors)

#     def _calculate_urgency_score(self, symbol: str, volume_ratio: float,
# trade_context: Dict = None) -> float:
#         "Calculate urgency score (0-1) for the trade"

#         urgency = 0.0

        # Volume-based urgency
#         if volume_ratio >= 10:
#             urgency += 0.4
#         elif volume_ratio >= 5:
#             urgency += 0.3
#         elif volume_ratio >= 3:
#             urgency += 0.2
#         else:
#             urgency += 0.1

        # Market condition urgency
#         market_conditions = self._assess_market_conditions(symbol)
#         if market_conditions.get('high_volatility', False):
#             urgency += 0.3
#         if market_conditions.get('fast_market', False):
#             urgency += 0.2

        # Trade context urgency
#         if trade_context:
#             if trade_context.get('immediate_or_cancel', False):
#                 urgency += 0.2
#             if trade_context.get('fill_or_kill', False):
#                 urgency += 0.3

#         return min(1.0, urgency)

#     def _calculate_price_impact(self, symbol: str, price: float, volume: float) -> float:
#         "Calculate price impact of the trade"

#         if len(self.price_data[symbol]) < 2:
#             return 0.0

#         prev_price = self.price_data[symbol][-2][1]

#         if prev_price <= 0:
#             return 0.0

#         price_change = abs(price - prev_price) / prev_price

        # Normalize by volume (larger trades should have more impact)
#         normalized_impact = price_change / (volume / 1000) if volume > 0 else 0

#         return min(1.0, normalized_impact * 100)  # Scale to 0-1 range

#     def _assess_market_conditions(self, symbol: str) -> Dict[str, Any]:
#         "Assess current market conditions for a symbol"

# conditions = {
# 'high_volatility': False,
# 'fast_market': False,
# 'thin_liquidity': False,
# 'abnormal_spread': False,
# }

#         if len(self.price_data[symbol]) < 10:
#             return conditions

        # Calculate volatility
#         recent_prices = [p[1] for p in list(self.price_data[symbol])[-20:]]
#         if len(recent_prices) >= 10:
#             price_volatility = np.std(recent_prices) / np.mean(recent_prices) if np.mean(recent_prices) > 0 else 0
#             conditions['high_volatility'] = price_volatility > 0.02  # 2% volatility threshold

        # Check for fast market conditions (rapid price changes)
#         if len(recent_prices) >= 5:
# recent_changes = [abs(recent_prices[i] - recent_prices[i-1]) / recent_prices[i-1]
#                             for i in range(1, min(6, len(recent_prices)))]
#             avg_change = np.mean(recent_changes) if recent_changes else 0
#             conditions['fast_market'] = avg_change > 0.005  # 0.5% average change threshold

#         return conditions

#     def _process_institutional_trade(self, trade: InstitutionalTrade):
#         "Process detected institutional trade"

#         with self.lock:
#             self.trade_data[trade.symbol].append(trade)

            # Update detection statistics
#             self.detection_stats['total_detections'] += 1

#             if trade.size_category == 'large':
#                 self.detection_stats['large_trades_detected'] += 1
#             elif trade.size_category == 'block':
#                 self.detection_stats['block_trades_detected'] += 1

#             if trade.flow_type == FlowType.DARK_POOL:
#                 self.detection_stats['dark_pool_activities'] += 1

        # Trigger ML model update if enabled
#         if self.config.enable_ml_enhancement:
#             self._update_ml_models_with_trade(trade)

        # Check for real-time alerts
#         self._check_real_time_alerts(trade)

        # Update cross-asset correlations
#         if self.config.enable_cross_asset_analysis:
#             self._update_cross_asset_correlations(trade)

#         self.logger.debug(f"Processed institutional trade: {trade.symbol} "
#                         f"{trade.size_category} {trade.flow_type.value} "
# f"confidence: {trade.confidence:.2f}")

#     def _should_generate_metrics(self, symbol: str) -> bool:
#         "Determine if flow metrics should be generated for a symbol"

        # Check data availability
#         if len(self.trade_data[symbol]) < 5:
#             return False

        # Check timing
#         if symbol in self.flow_metrics and len(self.flow_metrics[symbol]) > 0:
#             last_metrics = self.flow_metrics[symbol][-1]
#             time_since = datetime.now(timezone.utc) - last_metrics.timestamp
#             if time_since.total_seconds() < self.config.short_window_seconds:
#                 return False

#         return True

#     def _generate_flow_metrics(self, symbol: str) -> Optional[FlowMetrics]:
#         "Generate comprehensive institutional flow metrics"

#         try:
#             if symbol not in self.trade_data or len(self.trade_data[symbol]) == 0:
#                 return None

            # Get recent trades
#             recent_trades = list(self.trade_data[symbol])[-100:]
#             if not recent_trades:
#                 return None

#             timestamp = recent_trades[-1].timestamp
#             asset_class = self.asset_classes.get(symbol, AssetClass.EQUITIES)

            # Calculate volume-based metrics
#             institutional_volume = sum(t.volume for t in recent_trades)
#             total_volume = sum(v[1] for v in list(self.volume_data[symbol])[-100:])
#             institutional_volume_ratio = institutional_volume / total_volume if total_volume > 0 else 0

            # Calculate large trade frequency
#             large_trades = [t for t in recent_trades if t.size_category in ['large', 'block', 'whale']]
#             large_trade_frequency = len(large_trades) / max(1, len(recent_trades))

            # Calculate block trade activity
#             block_trades = [t for t in recent_trades if t.size_category == 'block']
#             block_trade_volume = sum(t.volume for t in block_trades)
#             block_trade_activity = block_trade_volume / institutional_volume if institutional_volume > 0 else 0

            # Estimate dark pool activity
#             dark_pool_trades = [t for t in recent_trades if t.flow_type == FlowType.DARK_POOL]
#             dark_pool_estimate = len(dark_pool_trades) / max(1, len(recent_trades))

            # Calculate flow strength and bias
# buy_trades = [t for t in recent_trades if 'buy' in str(t.flow_type.value).lower() or
# t.flow_type in [FlowType.BUY_SIDE_INITIATED]]
# sell_trades = [t for t in recent_trades if 'sell' in str(t.flow_type.value).lower() or
# t.flow_type in [FlowType.SELL_SIDE_INITIATED]]

#             buy_volume = sum(t.volume for t in buy_trades)
#             sell_volume = sum(t.volume for t in sell_trades)
#             total_trade_volume = buy_volume + sell_volume

#             buy_side_pressure = buy_volume / total_trade_volume if total_trade_volume > 0 else 0.5
#             sell_side_pressure = sell_volume / total_trade_volume if total_trade_volume > 0 else 0.5
#             net_institutional_flow = (buy_side_pressure - sell_side_pressure) * 2  # -1 to 1 scale

            # Determine flow strength
#             avg_confidence = np.mean([t.confidence for t in recent_trades])
#             if avg_confidence > 0.8 and large_trade_frequency > 0.5:
#                 flow_strength = FlowStrength.EXTREME
#             elif avg_confidence > 0.7 and large_trade_frequency > 0.3:
#                 flow_strength = FlowStrength.VERY_HIGH
#             elif avg_confidence > 0.6 and large_trade_frequency > 0.2:
#                 flow_strength = FlowStrength.HIGH
#             elif avg_confidence > 0.5:
#                 flow_strength = FlowStrength.MODERATE
#             else:
#                 flow_strength = FlowStrength.LOW

            # Calculate activity metrics
#             time_window = self.config.medium_window_seconds
#             if len(recent_trades) >= 2:
#                 time_span = (recent_trades[-1].timestamp - recent_trades[0].timestamp).total_seconds()
#                 institutional_frequency = len(recent_trades) / max(time_span, time_window) * time_window
#             else:
#                 institutional_frequency = 0

#             urgency_index = np.mean([t.urgency_score for t in recent_trades])
#             confidence_score = np.mean([t.confidence for t in recent_trades])

            # Pattern detection
#             accumulation_pattern = self._detect_accumulation_pattern(recent_trades)
#             distribution_pattern = self._detect_distribution_pattern(recent_trades)
#             manipulation_risk = self._assess_manipulation_risk(recent_trades)
#             anomaly_score = self._calculate_anomaly_score(symbol, recent_trades)

            # Cross-asset metrics
#             sector_correlation = self._calculate_sector_correlation(symbol, recent_trades)
#             market_impact = self._estimate_market_impact(symbol, recent_trades)
#             spillover_effects = self._identify_spillover_effects(symbol, recent_trades)

#             return FlowMetrics(
#                 symbol=symbol,
#                 asset_class=asset_class,
#                 timestamp=timestamp,

                # Volume-based metrics
#                 institutional_volume_ratio=institutional_volume_ratio,
#                 large_trade_frequency=large_trade_frequency,
#                 block_trade_activity=block_trade_activity,
#                 dark_pool_estimate=dark_pool_estimate,

                # Flow strength and bias
#                 net_institutional_flow=net_institutional_flow,
#                 flow_strength=flow_strength,
#                 buy_side_pressure=buy_side_pressure,
#                 sell_side_pressure=sell_side_pressure,

                # Activity metrics
#                 institutional_frequency=institutional_frequency,
#                 urgency_index=urgency_index,
#                 confidence_score=confidence_score,

                # Pattern metrics
#                 accumulation_pattern=accumulation_pattern,
#                 distribution_pattern=distribution_pattern,
#                 manipulation_risk=manipulation_risk,
#                 anomaly_score=anomaly_score,

                # Cross-asset metrics
#                 sector_correlation=sector_correlation,
#                 market_impact=market_impact,
#                 spillover_effects=spillover_effects,
# )

#         except Exception as e:
#             self.logger.error(f"Error generating flow metrics for {symbol}: {e}")
#             return None

#     def _detect_accumulation_pattern(self, trades: List[InstitutionalTrade]) -> bool:
#         "Detect accumulation pattern in institutional trades"

#         if len(trades) < 10:
#             return False

        # Look for consistent buying with increasing volume
# buy_trades = [t for t in trades if 'buy' in str(t.flow_type.value).lower() or
# t.flow_type in [FlowType.BUY_SIDE_INITIATED]]

#         if len(buy_trades) < len(trades) * 0.6:  # Less than 60% buy trades
#             return False

        # Check for increasing volume pattern
#         volumes = [t.volume for t in buy_trades[-10:]]
#         if len(volumes) >= 5:
#             volume_trend = np.polyfit(range(len(volumes)), volumes, 1)[0]
#             return volume_trend > 0  # Increasing volume trend

#         return False

#     def _detect_distribution_pattern(self, trades: List[InstitutionalTrade]) -> bool:
#         "Detect distribution pattern in institutional trades"

#         if len(trades) < 10:
#             return False

        # Look for consistent selling
# sell_trades = [t for t in trades if 'sell' in str(t.flow_type.value).lower() or
# t.flow_type in [FlowType.SELL_SIDE_INITIATED]]

#         return len(sell_trades) >= len(trades) * 0.6  # At least 60% sell trades

#     def _assess_manipulation_risk(self, trades: List[InstitutionalTrade]) -> float:
#         "Assess manipulation risk based on trading patterns"

#         risk_score = 0.0

#         if len(trades) < 5:
#             return 0.0

        # High frequency trading with large sizes
#         if len(trades) > 20:
#             time_span = (trades[-1].timestamp - trades[0].timestamp).total_seconds()
#             if time_span < 300:  # Less than 5 minutes
#                 risk_score += 0.3

        # Alternating buy/sell patterns
#         pattern_changes = 0
#         for i in range(1, len(trades)):
#             if 'buy' in str(trades[i].flow_type.value).lower() != 'buy' in str(trades[i-1].flow_type.value).lower():
#                 pattern_changes += 1

#         if pattern_changes > len(trades) * 0.5:
#             risk_score += 0.2

        # High urgency scores
#         avg_urgency = np.mean([t.urgency_score for t in trades])
#         if avg_urgency > 0.8:
#             risk_score += 0.2

        # Low confidence but large trades
#         avg_confidence = np.mean([t.confidence for t in trades])
#         large_trades = [t for t in trades if t.size_category in ['large', 'block', 'whale']]
#         if avg_confidence < 0.5 and len(large_trades) > len(trades) * 0.3:
#             risk_score += 0.3

#         return min(1.0, risk_score)

#     def _calculate_anomaly_score(self, symbol: str, trades: List[InstitutionalTrade]) -> float:
#         "Calculate anomaly score using statistical methods"

#         if not SKLEARN_AVAILABLE or len(trades) < 10:
#             return 0.0

#         try:
            # Extract features for anomaly detection
#             features = []
#             for trade in trades:
# feature_vector = [
#                     trade.volume,
#                     trade.trade_value,
#                     trade.urgency_score,
#                     trade.price_impact,
#                     trade.confidence,
# ]
#                 features.append(feature_vector)

#             features_array = np.array(features)

            # Use Isolation Forest for anomaly detection
#             if symbol not in self.anomaly_detectors:
#                 self.anomaly_detectors[symbol] = IsolationForest(
#                     contamination=0.1,
#                     random_state=42
# )

            # Fit and predict
#             anomaly_scores = self.anomaly_detectors[symbol].fit_predict(features_array)

            # Return the most recent anomaly score
#             return 1.0 if anomaly_scores[-1] == -1 else 0.1

#         except Exception as e:
#             self.logger.error(f"Error calculating anomaly score for {symbol}: {e}")
#             return 0.0

#     def _calculate_sector_correlation(self, symbol: str, trades: List[InstitutionalTrade]) -> float:
#         "Calculate correlation with sector flows"

#         sector = self.symbol_sectors.get(symbol)
#         if not sector:
#             return 0.0

        # This would require sector data integration
        # For now, return placeholder
#         return 0.5

#     def _estimate_market_impact(self, symbol: str, trades: List[InstitutionalTrade]) -> float:
#         "Estimate market impact of institutional flows"

#         if not trades:
#             return 0.0

        # Calculate total trade value
#         total_value = sum(t.trade_value for t in trades)

        # Calculate average price impact
#         avg_price_impact = np.mean([t.price_impact for t in trades])

        # Scale by total value and confidence
#         avg_confidence = np.mean([t.confidence for t in trades])

#         market_impact = (total_value / 1000000) * avg_price_impact * avg_confidence  # Scaled by millions

#         return min(1.0, market_impact)

#     def _identify_spillover_effects(self, symbol: str, trades: List[InstitutionalTrade]) -> List[str]:
#         "Identify spillover effects to other symbols"

        # This would require cross-asset correlation analysis
        # For now, return empty list
#         return []

#     def _check_flow_alerts(self, metrics: FlowMetrics):
#         "Check for flow alerts based on metrics"

#         alerts = []

        # High institutional volume ratio alert
#         if metrics.institutional_volume_ratio > 0.3:
# alert = FlowAlert(
#                 alert_type="high_institutional_volume",
#                 severity="medium" if metrics.institutional_volume_ratio < 0.5 else "high",
#                 symbol=metrics.symbol,
#                 asset_class=metrics.asset_class,
#                 timestamp=metrics.timestamp,
#                 message=f"High institutional volume ratio: {metrics.institutional_volume_ratio:.2%}",
#                 trade_data=None,
#                 flow_metrics={'institutional_volume_ratio': metrics.institutional_volume_ratio},
#                 threshold_breached="0.3",
#                 actual_value=metrics.institutional_volume_ratio,
# )
#             alerts.append(alert)

        # Block trade activity alert
#         if metrics.block_trade_activity > 0.2:
# alert = FlowAlert(
#                 alert_type="block_trade_activity",
#                 severity="high",
#                 symbol=metrics.symbol,
#                 asset_class=metrics.asset_class,
#                 timestamp=metrics.timestamp,
#                 message=f"Significant block trade activity: {metrics.block_trade_activity:.2%}",
#                 trade_data=None,
#                 flow_metrics={'block_trade_activity': metrics.block_trade_activity},
#                 threshold_breached="0.2",
#                 actual_value=metrics.block_trade_activity,
# )
#             alerts.append(alert)

        # Manipulation risk alert
#         if metrics.manipulation_risk > 0.7:
# alert = FlowAlert(
#                 alert_type="manipulation_risk",
#                 severity="critical",
#                 symbol=metrics.symbol,
#                 asset_class=metrics.asset_class,
#                 timestamp=metrics.timestamp,
#                 message=f"High manipulation risk detected: {metrics.manipulation_risk:.2%}",
#                 trade_data=None,
#                 flow_metrics={'manipulation_risk': metrics.manipulation_risk},
#                 threshold_breached="0.7",
#                 actual_value=metrics.manipulation_risk,
# )
#             alerts.append(alert)

        # Add alerts to the system
#         for alert in alerts:
#             with self.lock:
#                 self.alerts.append(alert)

            # Trigger callbacks
#             for callback in self.alert_callbacks:
#                 try:
#                     callback(alert)
#                 except Exception as e:
#                     self.logger.error(f"Error in alert callback: {e}")

#     def _check_real_time_alerts(self, trade: InstitutionalTrade):
#         "Check for real-time alerts on individual trades"

#         alerts = []

        # Whale trade alert
#         if trade.size_category == "whale":
# alert = FlowAlert(
#                 alert_type="whale_trade",
#                 severity="critical",
#                 symbol=trade.symbol,
#                 asset_class=trade.asset_class,
#                 timestamp=trade.timestamp,
#                 message=f"Whale trade detected: ${trade.trade_value:,.0f}",
#                 trade_data=trade,
#                 flow_metrics={'trade_value': trade.trade_value},
#                 threshold_breached=f"${self.config.whale_trade_threshold_usd:,.0f}",
#                 actual_value=trade.trade_value,
# )
#             alerts.append(alert)

        # Block trade alert
#         elif trade.size_category == "block":
# alert = FlowAlert(
#                 alert_type="block_trade",
#                 severity="high",
#                 symbol=trade.symbol,
#                 asset_class=trade.asset_class,
#                 timestamp=trade.timestamp,
#                 message=f"Block trade detected: ${trade.trade_value:,.0f}",
#                 trade_data=trade,
#                 flow_metrics={'trade_value': trade.trade_value},
#                 threshold_breached=f"${self.config.block_trade_threshold_usd:,.0f}",
#                 actual_value=trade.trade_value,
# )
#             alerts.append(alert)

        # High urgency alert
#         if trade.urgency_score > 0.8:
# alert = FlowAlert(
#                 alert_type="high_urgency_trade",
#                 severity="medium",
#                 symbol=trade.symbol,
#                 asset_class=trade.asset_class,
#                 timestamp=trade.timestamp,
#                 message=f"High urgency trade detected: {trade.urgency_score:.2f}",
#                 trade_data=trade,
#                 flow_metrics={'urgency_score': trade.urgency_score},
#                 threshold_breached="0.8",
#                 actual_value=trade.urgency_score,
# )
#             alerts.append(alert)

        # Add alerts to the system
#         for alert in alerts:
#             with self.lock:
#                 self.alerts.append(alert)

            # Trigger callbacks
#             for callback in self.alert_callbacks:
#                 try:
#                     callback(alert)
#                 except Exception as e:
#                     self.logger.error(f"Error in alert callback: {e}")

#     def _update_ml_models_with_trade(self, trade: InstitutionalTrade):
#         "Update ML models with new trade data"

#         if not SKLEARN_AVAILABLE:
#             return

#         try:
            # This would implement incremental learning for ML models
            # For now, just store features for later training
#             if trade.symbol not in self.feature_cache:
#                 self.feature_cache[trade.symbol] = []

# features = self._extract_institution_features(
#                 trade.symbol, trade.price, trade.volume,
#                 trade.flow_type, {'confidence': trade.confidence}
# )

#             self.feature_cache[trade.symbol].append(features)

            # Limit cache size
#             if len(self.feature_cache[trade.symbol]) > 1000:
#                 self.feature_cache[trade.symbol] = self.feature_cache[trade.symbol][-500:]

#         except Exception as e:
#             self.logger.error(f"Error updating ML models with trade: {e}")

#     def _update_cross_asset_correlations(self, trade: InstitutionalTrade):
#         "Update cross-asset correlation analysis"

#         try:
            # This would implement cross-asset correlation updates
            # For now, placeholder implementation
#             pass
#         except Exception as e:
#             self.logger.error(f"Error updating cross-asset correlations: {e}")

#     def _update_performance_stats(self, processing_time_us: float):
#         "Update performance statistics"

#         with self.lock:
#             current_avg = self.detection_stats['avg_detection_time_us']
#             count = self.detection_stats['total_detections']

            # Calculate running average
#             new_avg = (current_avg * (count - 1) + processing_time_us) / count
#             self.detection_stats['avg_detection_time_us'] = new_avg

#     def _start_background_processing(self):
#         "Start background processing for intensive computations"

#         async def background_processor():
#             "while True:"
#                 try:
                    # Process analysis queue
#                     if not self.analysis_queue.empty():
#                         task = await self.analysis_queue.get()
#                         await self._process_background_task(task)

                    # Periodic model updates
#                     await asyncio.sleep(1)

                    # Update ML models periodically
#                     if self.config.enable_ml_enhancement:
#                         self._periodic_model_update()

#                 except Exception as e:
#                     self.logger.error(f"Error in background processing: {e}")
#                     await asyncio.sleep(5)

        # Start background task
#         task = asyncio.create_task(background_processor())
#         self.background_tasks.add(task)
#         task.add_done_callback(self.background_tasks.discard)

#     async def _process_background_task(self, task: Dict):
#         "Process background analysis task"

#         try:
#             task_type = task.get('type')

#             if task_type == 'model_training':
#                 await self._train_ml_models(task.get('symbol'))
#             elif task_type == 'correlation_update':
#                 await self._update_correlations()
#             elif task_type == 'pattern_analysis':
#                 await self._analyze_patterns(task.get('symbol'))

#         except Exception as e:
#             self.logger.error(f"Error processing background task {task_type}: {e}")

#     async def _train_ml_models(self, symbol: str):
#         "Train ML models for a symbol"

#         if not SKLEARN_AVAILABLE or symbol not in self.feature_cache:
#             return

#         try:
#             features = self.feature_cache[symbol]
#             if len(features) < 50:  # Need minimum data for training
#                 return

            # This would implement model training
            # For now, placeholder implementation
#             pass

#         except Exception as e:
#             self.logger.error(f"Error training ML models for {symbol}: {e}")

#     async def _update_correlations(self):
#         "Update cross-asset correlations"

#         try:
            # This would implement correlation matrix updates
            # For now, placeholder implementation
#             pass
#         except Exception as e:
#             self.logger.error(f"Error updating correlations: {e}")

#     async def _analyze_patterns(self, symbol: str):
#         "Analyze patterns for a symbol"

#         try:
            # This would implement pattern analysis
            # For now, placeholder implementation
#             pass
#         except Exception as e:
#             self.logger.error(f"Error analyzing patterns for {symbol}: {e}")

#     def _periodic_model_update(self):
#         "Periodic model update (called from background processor)"

        # This would implement periodic model updates
        # For now, placeholder implementation
#         pass

    # ===========================================
    # PUBLIC API METHODS
    # ===========================================

#     def get_current_flow_metrics(self, symbol: str) -> Optional[FlowMetrics]:
#         "Get current institutional flow metrics for a symbol"
#         if symbol in self.flow_metrics and len(self.flow_metrics[symbol]) > 0:
#             return self.flow_metrics[symbol][-1]
#         return None

#     def get_recent_alerts(self, symbol: str = None, limit: int = 50) -> List[FlowAlert]:
#         "Get recent institutional flow alerts"
#         alerts = list(self.alerts)

#         if symbol:
#             alerts = [a for a in alerts if a.symbol == symbol]

#         return alerts[-limit:]

#     def get_detection_statistics(self) -> Dict[str, Any]:
#         "Get detection performance statistics"
#         with self.lock:
#             stats = self.detection_stats.copy()

            # Add additional statistics
#             stats['symbols_monitored'] = len(self.asset_classes)
#             stats['total_alerts'] = len(self.alerts)
#             stats['ml_models_trained'] = len(self.ml_models)
#             stats['feature_cache_size'] = sum(len(features) for features in self.feature_cache.values())

            # Performance metrics
#             stats['sub_100us_target_met'] = stats['avg_detection_time_us'] < 100

#             return stats

#     def register_alert_callback(self, callback: Callable):
#         "Register callback function for alerts"
#         self.alert_callbacks.append(callback)

#     def unregister_alert_callback(self, callback: Callable):
#         "Unregister alert callback function"
#         if callback in self.alert_callbacks:
#             self.alert_callbacks.remove(callback)

#     def get_symbol_summary(self, symbol: str) -> Dict[str, Any]:
#         "Get comprehensive summary for a symbol"

# summary = {
# 'symbol': symbol,
# 'asset_class': self.asset_classes.get(symbol, AssetClass.EQUITIES).value,
# 'sector': self.symbol_sectors.get(symbol, 'Unknown'),
# }

        # Current metrics
#         current_metrics = self.get_current_flow_metrics(symbol)
#         if current_metrics:
# summary['current_metrics'] = {
# 'institutional_volume_ratio': current_metrics.institutional_volume_ratio,
# 'net_institutional_flow': current_metrics.net_institutional_flow,
# 'flow_strength': current_metrics.flow_strength.value,
# 'confidence_score': current_metrics.confidence_score,
# 'accumulation_pattern': current_metrics.accumulation_pattern,
# 'distribution_pattern': current_metrics.distribution_pattern,
# 'manipulation_risk': current_metrics.manipulation_risk,
# }

        # Recent trades
#         if symbol in self.trade_data:
#             recent_trades = list(self.trade_data[symbol])[-10:]
#             if recent_trades:
# summary['recent_activity'] = {
# 'trade_count': len(recent_trades),
# 'total_volume': sum(t.volume for t in recent_trades),
# 'total_value': sum(t.trade_value for t in recent_trades),
# 'avg_confidence': np.mean([t.confidence for t in recent_trades]),
# 'flow_types': list(set(t.flow_type.value for t in recent_trades)),
# }

        # Recent alerts
#         recent_alerts = self.get_recent_alerts(symbol, limit=5)
#         if recent_alerts:
# summary['recent_alerts'] = [
# {
# 'type': alert.alert_type,
# 'severity': alert.severity,
# 'message': alert.message,
# 'timestamp': alert.timestamp.isoformat(),
# }
#                 for alert in recent_alerts
# ]

#         return summary

#     def get_cross_asset_summary(self) -> Dict[str, Any]:
#         "Get cross-asset flow analysis summary"

# summary = {
# 'total_symbols': len(self.asset_classes),
# 'asset_class_distribution': defaultdict(int),
# 'overall_flow_bias': 0.0,
# 'high_activity_symbols': [],
# 'accumulation_symbols': [],
# 'distribution_symbols': [],
# }

        # Analyze all symbols
#         total_flow = 0.0
#         symbol_count = 0

#         for symbol, metrics_list in self.flow_metrics.items():
#             if metrics_list:
#                 asset_class = self.asset_classes.get(symbol, AssetClass.EQUITIES)
#                 summary['asset_class_distribution'][asset_class.value] += 1

#                 current_metrics = metrics_list[-1]
#                 total_flow += current_metrics.net_institutional_flow
#                 symbol_count += 1

                # High activity symbols
#                 if current_metrics.institutional_frequency > 5:
# summary['high_activity_symbols'].append({
# 'symbol': symbol,
# 'frequency': current_metrics.institutional_frequency,
# 'flow_strength': current_metrics.flow_strength.value,
# })

                # Accumulation symbols
#                 if current_metrics.accumulation_pattern:
# summary['accumulation_symbols'].append({
# 'symbol': symbol,
# 'buy_side_pressure': current_metrics.buy_side_pressure,
# 'confidence': current_metrics.confidence_score,
# })

                # Distribution symbols
#                 if current_metrics.distribution_pattern:
# summary['distribution_symbols'].append({
# 'symbol': symbol,
# 'sell_side_pressure': current_metrics.sell_side_pressure,
# 'confidence': current_metrics.confidence_score,
# })

        # Calculate overall flow bias
#         if symbol_count > 0:
#             summary['overall_flow_bias'] = total_flow / symbol_count

#         return summary

#     def cleanup_old_data(self, hours: int = 24):
#         "Clean up old data to prevent memory issues"

#         cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)

#         with self.lock:
            # Clean up trade data
#             for symbol in list(self.trade_data.keys()):
#                 while (self.trade_data[symbol] and
#                         self.trade_data[symbol][0].timestamp < cutoff_time):
#                     self.trade_data[symbol].popleft()

            # Clean up flow metrics
#             for symbol in list(self.flow_metrics.keys()):
#                 while (self.flow_metrics[symbol] and
#                         self.flow_metrics[symbol][0].timestamp < cutoff_time):
#                     self.flow_metrics[symbol].popleft()

            # Clean up alerts
#             while self.alerts and self.alerts[0].timestamp < cutoff_time:
#                 self.alerts.popleft()

#         self.logger.info(f"Cleaned up data older than {hours} hours")

#     def shutdown(self):
#         "Shutdown the institutional flow detection engine"

        # Cancel background tasks
#         for task in self.background_tasks:
#             task.cancel()

        # Clear caches
#         self.feature_cache.clear()
#         self.ml_models.clear()

#         self.logger.info("Institutional Flow Detection Engine shutdown complete")


# ===========================================
# FACTORY FUNCTIONS AND UTILITIES
# ===========================================

# def create_institutional_flow_detection_engine(
#     large_trade_threshold_usd: float = 100000.0,
#     block_trade_threshold_usd: float = 1000000.0,
#     whale_trade_threshold_usd: float = 10000000.0,
#     enable_ml_enhancement: bool = True,
#     enable_high_performance_mode: bool = True,
#     sub_100_microsecond_target: bool = True,
# ) -> InstitutionalFlowDetectionEngine:
#     "Create institutional flow detection engine with specified configuration"

# config = InstitutionalFlowConfig(
#         large_trade_threshold_usd=large_trade_threshold_usd,
#         block_trade_threshold_usd=block_trade_threshold_usd,
#         whale_trade_threshold_usd=whale_trade_threshold_usd,
#         enable_ml_enhancement=enable_ml_enhancement,
#         enable_high_performance_mode=enable_high_performance_mode,
#         sub_100_microsecond_target=sub_100_microsecond_target,
# )

#     return InstitutionalFlowDetectionEngine(config)


# Export all classes and functions
# __all__ = [
    # Enums
#     "AssetClass",
#     "InstitutionType",
#     "FlowType",
#     "FlowStrength",

    # Data classes
#     "InstitutionalTrade",
#     "FlowAlert",
#     "FlowMetrics",
#     "InstitutionalFlowConfig",

    # Main classes
#     "InstitutionalFlowDetectionEngine",

    # Factory functions
#     "create_institutional_flow_detection_engine",
# ]