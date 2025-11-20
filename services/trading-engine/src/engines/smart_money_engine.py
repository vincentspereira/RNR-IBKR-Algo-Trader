import logging
import math
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np
import pandas as pd
from scipy import stats
from scipy.signal import find_peaks

# Smart Money Analysis Engine

# Institutional-grade smart money flow detection and analysis system that:
# - Detects institutional trading patterns and large order flows
# - Identifies smart money entry and exit points
# - Analyzes volume patterns and price-volume relationships
# - Implements anomaly detection for unusual trading activity
# - Provides institutional pressure indicators
# - Tracks dark pool and block trade activities
# - Generates smart money-based trading signals

# Author: Vincent S. Pereira
# Version: 1.0.0




# try:
#     from sklearn.ensemble import IsolationForest
#     from sklearn.preprocessing import StandardScaler
#     SKLEARN_AVAILABLE = True
# except ImportError:
#     SKLEARN_AVAILABLE = False
#     logging.warning("scikit-learn not available. Smart money detection will be limited.")

logger = logging.getLogger(__name__)


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


# @dataclass
# class SmartMoneyConfig:
#     "Configuration for smart money analysis"

    # Detection parameters
#     volume_threshold_multiplier: float = 2.0  # Volume above average threshold
#     price_impact_threshold: float = 0.002  # 0.2% price impact
#     large_trade_threshold: float = 100000.0  # $100k trade size
#     anomaly_contamination: float = 0.1  # For anomaly detection

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


# @dataclass
# class SmartMoneyMetrics:
#     "Smart money flow metrics"

#     symbol: str
#     timestamp: datetime

    # Volume metrics
#     volume_ratio: float  # Current volume vs average
#     volume_trend: float  # Volume trend strength
#     unusual_volume: bool  # Unusual volume detected

    # Price impact metrics
#     price_impact: float  # Price change per volume unit
#     volume_price_correlation: float  # Correlation between volume and price
#     buying_pressure: float  # Net buying pressure
#     selling_pressure: float  # Net selling pressure

    # Institutional metrics
#     institutional_flow: float  # Estimated institutional flow
#     large_trade_ratio: float  # Ratio of large trades
#     dark_pool_activity: float  # Dark pool activity estimate

    # Anomaly metrics
#     anomaly_score: float  # Anomaly detection score
#     unusual_activity: bool  # Unusual activity detected

    # Signal metrics
#     smart_money_signal: SmartMoneySignal
#     signal_strength: float
#     signal_confidence: float


# @dataclass
# class SmartMoneyAlert:
#     "Smart money alert"

#     alert_type: str
#     severity: str  # 'low', 'medium', 'high', 'critical'
#     message: str
#     symbol: str
#     timestamp: datetime

    # Alert data
#     metrics: Dict[str, float]
#     threshold: float
#     actual_value: float


# class SmartMoneyAnalysisEngine:
#     "Institutional-Grade Smart Money Analysis Engine"

#     def __init__(self, config: SmartMoneyConfig = None):
#         self.config = config or SmartMoneyConfig()
#         self.logger = logger

        # Data storage
#         self.price_data: Dict[str, deque] = defaultdict(lambda: deque(maxlen=500))
#         self.volume_data: Dict[str, deque] = defaultdict(lambda: deque(maxlen=500))
#         self.trade_data: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
#         self.metrics_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=200))

        # Analysis components
#         self.current_signals: Dict[str, SmartMoneyMetrics] = {}

        # Anomaly detection models
#         self.anomaly_models: Dict[str, Any] = {}
#         self.scalers: Dict[str, Any] = {}

        # Alert system
#         self.alerts: deque = deque(maxlen=1000)
#         self.alert_thresholds = {
# 'volume_spike': self.config.volume_threshold_multiplier,
# 'price_impact': self.config.price_impact_threshold,
# 'anomaly_score': 0.7,
# }

        # Threading
#         self.lock = threading.Lock()

        # Statistics tracking
#         self.analysis_count = 0
#         self.last_analysis = None

#         self.logger.info("Smart Money Analysis Engine initialized")

#     def update_market_data(self, symbol: str, price: float, volume: float, timestamp: datetime):
#         "Update market data for analysis"

#         with self.lock:
            # Store data
#             self.price_data[symbol].append((timestamp, price))
#             self.volume_data[symbol].append((timestamp, volume))

            # Simulate trade data (in real implementation, this would come from trade feeds)
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

        # Trigger analysis
#         if self._should_analyze(symbol):
#             self._analyze_symbol(symbol)

#     def _should_analyze(self, symbol: str) -> bool:
#         "Determine if analysis should be run"

        # Check data availability
#         if len(self.price_data[symbol]) < self.config.short_window:
#             return False

        # Check timing
#         if self.last_analysis:
#             time_since = datetime.now(timezone.utc) - self.last_analysis
#             if time_since.total_seconds() < 60:  # At least 1 minute between analyses
#                 return False

#         return True

#     def _analyze_symbol(self, symbol: str):
#         "Analyze smart money flow for a symbol"

#         try:
            # Prepare data
#             prices = [p[1] for p in list(self.price_data[symbol])[-self.config.long_window:]]
#             volumes = [v[1] for v in list(self.volume_data[symbol])[-self.config.long_window:]]

#             if len(prices) < self.config.short_window:
#                 return

#             timestamp = self.price_data[symbol][-1][0]

            # 1. Volume Analysis
#             volume_metrics = self._analyze_volume_patterns(symbol, prices, volumes)

            # 2. Price Impact Analysis
#             price_impact_metrics = self._analyze_price_impact(symbol, prices, volumes)

            # 3. Institutional Flow Analysis
#             institutional_metrics = self._analyze_institutional_flow(symbol)

            # 4. Anomaly Detection
#             anomaly_metrics = self._detect_anomalies(symbol, prices, volumes)

            # 5. Generate Smart Money Signal
# signal_metrics = self._generate_smart_money_signal(
#                 symbol, timestamp, volume_metrics, price_impact_metrics,
#                 institutional_metrics, anomaly_metrics
# )

            # Store results
#             with self.lock:
#                 self.current_signals[symbol] = signal_metrics
#                 self.metrics_history[symbol].append(signal_metrics)
#                 self.analysis_count += 1
#                 self.last_analysis = datetime.now(timezone.utc)

            # Check for alerts
#             self._check_smart_money_alerts(signal_metrics)

#             self.logger.debug(f"Smart money analysis completed for {symbol}")

#         except Exception as e:
#             self.logger.error(f"Error analyzing smart money for {symbol}: {e}")

#     def _analyze_volume_patterns(self, symbol: str, prices: List[float], volumes: List[float]) -> Dict[str, float]:
#         "Analyze volume patterns"

#         if len(volumes) < self.config.short_window:
#             return {}

#         current_volume = volumes[-1]
#         avg_volume_short = np.mean(volumes[-self.config.short_window:])
#         avg_volume_medium = np.mean(volumes[-self.config.medium_window:])
#         avg_volume_long = np.mean(volumes[-self.config.long_window:]) if len(volumes) >= self.config.long_window else avg_volume_medium

        # Volume ratios
#         volume_ratio_short = current_volume / avg_volume_short if avg_volume_short > 0 else 1.0
#         volume_ratio_medium = current_volume / avg_volume_medium if avg_volume_medium > 0 else 1.0
#         volume_ratio_long = current_volume / avg_volume_long if avg_volume_long > 0 else 1.0

        # Volume trend
#         volume_trend = np.corrcoef(range(len(volumes[-self.config.medium_window:])), volumes[-self.config.medium_window:])[0, 1]
#         volume_trend = 0 if np.isnan(volume_trend) else volume_trend

        # Volume acceleration
#         if len(volumes) >= 3:
#             volume_acceleration = (volumes[-1] - volumes[-3]) / 2
#         else:
#             volume_acceleration = 0

        # Unusual volume detection
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
#         "Analyze price impact of volume"

#         if len(prices) < self.config.short_window or len(volumes) < self.config.short_window:
#             return {}

        # Calculate price changes
#         price_changes = np.diff(prices)

        # Align price changes with volumes
#         aligned_volumes = volumes[1:]  # Shift to align with price changes

#         if len(aligned_volumes) < self.config.short_window:
#             return {}

        # Price impact per volume unit
#         recent_period = min(self.config.short_window, len(price_changes))
#         price_impacts = price_changes[-recent_period:] / aligned_volumes[-recent_period:]
#         price_impact = np.mean(price_impacts) if len(price_impacts) > 0 else 0

        # Volume-price correlation
# volume_price_corr = np.corrcoef(aligned_volumes[-self.config.medium_window:],
# price_changes[-self.config.medium_window:])[0, 1]
#         volume_price_corr = 0 if np.isnan(volume_price_corr) else volume_price_corr

        # Buying/selling pressure (based on volume and price direction)
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
#         "Analyze institutional flow patterns"

#         if symbol not in self.trade_data or len(self.trade_data[symbol]) < 10:
#             return {}

#         recent_trades = list(self.trade_data[symbol])[-100:]

        # Categorize trades
#         institutional_trades = [t for t in recent_trades if t['type'] == TradingActivityType.INSTITUTIONAL]
#         large_trades = [t for t in recent_trades if t['value'] > self.config.large_trade_threshold]

        # Calculate institutional flow
#         institutional_volume = sum(t['volume'] for t in institutional_trades)
#         institutional_value = sum(t['value'] for t in institutional_trades)

#         total_volume = sum(t['volume'] for t in recent_trades)
#         total_value = sum(t['value'] for t in recent_trades)

#         institutional_flow_ratio = institutional_volume / total_volume if total_volume > 0 else 0
#         large_trade_ratio = len(large_trades) / len(recent_trades) if recent_trades else 0

        # Dark pool activity estimate (simplified)
#         dark_pool_activity = self._estimate_dark_pool_activity(recent_trades)

        # Block trade detection
#         block_trades = [t for t in recent_trades if t['value'] > self.config.large_trade_threshold * 5]
#         block_trade_activity = len(block_trades) / len(recent_trades) if recent_trades else 0

#         return {
# 'institutional_flow': institutional_flow_ratio,
# 'large_trade_ratio': large_trade_ratio,
# 'dark_pool_activity': dark_pool_activity,
# 'block_trade_activity': block_trade_activity,
# 'avg_institutional_size': np.mean([t['value'] for t in institutional_trades]) if institutional_trades else 0,
# }

#     def _estimate_dark_pool_activity(self, trades: List[Dict]) -> float:
#         "Estimate dark pool activity (simplified heuristic)"

        # Heuristic: Large trades with minimal price impact might be dark pool trades
#         if len(trades) < 10:
#             return 0.0

#         large_trades = [t for t in trades if t['value'] > self.config.large_trade_threshold]

#         if not large_trades:
#             return 0.0

        # Calculate average price impact for large trades
#         price_impacts = []
#         for i, trade in enumerate(large_trades[1:], 1):
#             prev_price = large_trades[i-1]['price']
#             price_change = abs(trade['price'] - prev_price) / prev_price
#             price_impacts.append(price_change)

#         avg_price_impact = np.mean(price_impacts) if price_impacts else 0

        # Low price impact suggests dark pool activity
#         dark_pool_estimate = max(0, (0.01 - avg_price_impact) / 0.01)  # Normalize

#         return min(1.0, dark_pool_estimate)

#     def _detect_anomalies(self, symbol: str, prices: List[float], volumes: List[float]) -> Dict[str, float]:
#         "Detect anomalies in trading patterns"

#         if not SKLEARN_AVAILABLE:
#             return {'anomaly_score': 0.0, 'unusual_activity': False}

#         if len(prices) < self.config.medium_window:
#             return {'anomaly_score': 0.0, 'unusual_activity': False}

#         try:
            # Prepare features for anomaly detection
#             features = self._extract_anomaly_features(prices, volumes)

#             if len(features) < 10:
#                 return {'anomaly_score': 0.0, 'unusual_activity': False}

            # Initialize or update anomaly model
#             if symbol not in self.anomaly_models:
#                 self.anomaly_models[symbol] = IsolationForest(
#                     contamination=self.config.anomaly_contamination,
#                     random_state=42
# )
#                 self.scalers[symbol] = StandardScaler()

            # Scale features
#             features_scaled = self.scalers[symbol].fit_transform(features)

            # Detect anomalies
#             anomaly_scores = self.anomaly_models[symbol].fit_predict(features_scaled)
#             current_score = anomaly_scores[-1]  # Latest data point

            # Convert to 0-1 scale (higher = more anomalous)
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
#         "Extract features for anomaly detection"

#         features = []

        # Use sliding window to extract features
#         window_size = min(20, len(prices) // 2)

#         for i in range(window_size, len(prices)):
#             window_prices = prices[i-window_size:i]
#             window_volumes = volumes[i-window_size:i]

            # Price features
#             price_return = (window_prices[-1] - window_prices[0]) / window_prices[0] if window_prices[0] != 0 else 0
#             price_volatility = np.std(window_prices) / np.mean(window_prices) if np.mean(window_prices) > 0 else 0
#             price_trend = np.corrcoef(range(len(window_prices)), window_prices)[0, 1] if len(window_prices) > 1 else 0

            # Volume features
#             volume_mean = np.mean(window_volumes)
#             volume_std = np.std(window_volumes)
#             volume_trend = np.corrcoef(range(len(window_volumes)), window_volumes)[0, 1] if len(window_volumes) > 1 else 0

            # Price-volume features
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

#     def _generate_smart_money_signal(self, symbol: str, timestamp: datetime,
# volume_metrics: Dict, price_impact_metrics: Dict,
# institutional_metrics: Dict, anomaly_metrics: Dict) -> SmartMoneyMetrics:
#         "Generate smart money signal"

        # Combine all metrics
#         combined_metrics = {**volume_metrics, **price_impact_metrics, **institutional_metrics, **anomaly_metrics}

        # Calculate signal strength
#         signal_strength = self._calculate_signal_strength(combined_metrics)

        # Determine signal type
#         smart_money_signal = self._determine_smart_money_signal(signal_strength, combined_metrics)

        # Calculate confidence
#         confidence = self._calculate_signal_confidence(combined_metrics)

#         return SmartMoneyMetrics(
#             symbol=symbol,
#             timestamp=timestamp,

            # Volume metrics
#             volume_ratio=volume_metrics.get('volume_ratio_short', 1.0),
#             volume_trend=volume_metrics.get('volume_trend', 0.0),
#             unusual_volume=volume_metrics.get('unusual_volume', False),

            # Price impact metrics
#             price_impact=price_impact_metrics.get('price_impact', 0.0),
#             volume_price_correlation=price_impact_metrics.get('volume_price_correlation', 0.0),
#             buying_pressure=price_impact_metrics.get('buying_pressure', 0.5),
#             selling_pressure=price_impact_metrics.get('selling_pressure', 0.5),

            # Institutional metrics
#             institutional_flow=institutional_metrics.get('institutional_flow', 0.0),
#             large_trade_ratio=institutional_metrics.get('large_trade_ratio', 0.0),
#             dark_pool_activity=institutional_metrics.get('dark_pool_activity', 0.0),

            # Anomaly metrics
#             anomaly_score=anomaly_metrics.get('anomaly_score', 0.0),
#             unusual_activity=anomaly_metrics.get('unusual_activity', False),

            # Signal metrics
#             smart_money_signal=smart_money_signal,
#             signal_strength=abs(signal_strength),
#             signal_confidence=confidence,
# )

#     def _calculate_signal_strength(self, metrics: Dict[str, float]) -> float:
#         "Calculate smart money signal strength"

#         strength = 0.0

        # Volume contribution
#         volume_ratio = metrics.get('volume_ratio_short', 1.0)
#         unusual_volume = metrics.get('unusual_volume', False)
#         volume_trend = metrics.get('volume_trend', 0.0)

#         if unusual_volume and volume_ratio > 1.5:
#             strength += 0.3 * (volume_ratio - 1.0) / volume_ratio
#         strength += 0.1 * max(0, volume_trend)

        # Price impact contribution
#         net_pressure = metrics.get('net_pressure', 0.0)
#         price_impact = metrics.get('price_impact', 0.0)

#         strength += 0.25 * net_pressure
#         if abs(price_impact) > 0.001:  # Significant price impact
#             strength += 0.15 * np.sign(price_impact)

        # Institutional flow contribution
#         institutional_flow = metrics.get('institutional_flow', 0.0)
#         large_trade_ratio = metrics.get('large_trade_ratio', 0.0)
#         dark_pool_activity = metrics.get('dark_pool_activity', 0.0)

#         strength += 0.2 * institutional_flow
#         strength += 0.1 * large_trade_ratio
#         strength += 0.05 * dark_pool_activity

        # Anomaly contribution
#         anomaly_score = metrics.get('anomaly_score', 0.0)
#         unusual_activity = metrics.get('unusual_activity', False)

#         if unusual_activity:
#             strength += 0.1 * anomaly_score

#         return max(-1.0, min(1.0, strength))

#     def _determine_smart_money_signal(self, strength: float, metrics: Dict[str, float]) -> SmartMoneySignal:
#         "Determine smart money signal type"

        # Check for manipulation patterns
#         unusual_activity = metrics.get('unusual_activity', False)
#         high_anomaly = metrics.get('anomaly_score', 0.0) > 0.8

#         if unusual_activity and high_anomaly:
#             return SmartMoneySignal.MANIPULATION

        # Determine accumulation/distribution
#         if strength > 0.6:
#             return SmartMoneySignal.STRONG_ACCUMULATION
#         elif strength > 0.3:
#             return SmartMoneySignal.ACCUMULATION
#         elif strength < -0.6:
#             return SmartMoneySignal.STRONG_DISTRIBUTION
#         elif strength < -0.3:
#             return SmartMoneySignal.DISTRIBUTION
#         else:
#             return SmartMoneySignal.NEUTRAL

#     def _calculate_signal_confidence(self, metrics: Dict[str, float]) -> float:
#         "Calculate signal confidence"

#         confidence_factors = []

        # Volume confidence
#         volume_ratio = metrics.get('volume_ratio_short', 1.0)
#         unusual_volume = metrics.get('unusual_volume', False)
#         if unusual_volume:
#             confidence_factors.append(min(1.0, volume_ratio / 3.0))

        # Institutional confidence
#         institutional_flow = metrics.get('institutional_flow', 0.0)
#         if institutional_flow > 0.1:
#             confidence_factors.append(min(1.0, institutional_flow * 2))

        # Price impact confidence
#         volume_price_corr = abs(metrics.get('volume_price_correlation', 0.0))
#         if volume_price_corr > 0.3:
#             confidence_factors.append(min(1.0, volume_price_corr))

        # Anomaly confidence
#         anomaly_score = metrics.get('anomaly_score', 0.0)
#         if metrics.get('unusual_activity', False):
#             confidence_factors.append(anomaly_score)

        # Overall confidence
#         if confidence_factors:
#             return np.mean(confidence_factors)
#         else:
#             return 0.5  # Default confidence

#     def _check_smart_money_alerts(self, metrics: SmartMoneyMetrics):
#         "Check for smart money alerts"

        # Volume spike alert
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
# )
#             self.alerts.append(alert)

        # Institutional activity alert
#         if metrics.institutional_flow > 0.3:
# alert = SmartMoneyAlert(
#                 alert_type="institutional_activity",
#                 severity="medium",
#                 message=f"High institutional activity detected: {metrics.institutional_flow:.2%}",
#                 symbol=metrics.symbol,
#                 timestamp=metrics.timestamp,
#                 metrics={'institutional_flow': metrics.institutional_flow},
#                 threshold=0.3,
#                 actual_value=metrics.institutional_flow,
# )
#             self.alerts.append(alert)

        # Anomaly alert
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
# )
#             self.alerts.append(alert)

#     def get_smart_money_signal(self, symbol: str) -> float:
#         "Get current smart money signal for a symbol"

#         if symbol in self.current_signals:
#             metrics = self.current_signals[symbol]

            # Convert signal to -1 to 1 scale
# signal_map = {
# SmartMoneySignal.STRONG_ACCUMULATION: 0.8,
# SmartMoneySignal.ACCUMULATION: 0.5,
# SmartMoneySignal.NEUTRAL: 0.0,
# SmartMoneySignal.DISTRIBUTION: -0.5,
# SmartMoneySignal.STRONG_DISTRIBUTION: -0.8,
# SmartMoneySignal.MANIPULATION: 0.0,  # Neutral for manipulation
# }

#             base_signal = signal_map.get(metrics.smart_money_signal, 0.0)
#             weighted_signal = base_signal * metrics.signal_strength * metrics.signal_confidence

#             return max(-1.0, min(1.0, weighted_signal))

#         return 0.0

#     def get_recent_alerts(self, limit: int = 10) -> List[SmartMoneyAlert]:
#         "Get recent smart money alerts"
#         return list(self.alerts)[-limit:]

#     def get_analysis_summary(self) -> Dict[str, Any]:
#         "Get comprehensive analysis summary"

#         with self.lock:
# summary = {
# 'total_symbols_analyzed': len(self.current_signals),
# 'analysis_count': self.analysis_count,
# 'last_analysis': self.last_analysis.isoformat() if self.last_analysis else None,
# 'current_signals': {},
# 'alert_count': len(self.alerts),
# }

            # Summarize current signals
#             signal_counts = defaultdict(int)
#             for metrics in self.current_signals.values():
#                 signal_counts[metrics.smart_money_signal.value] += 1

#             summary['signal_distribution'] = dict(signal_counts)

            # Average metrics
#             if self.current_signals:
# avg_metrics = {
# 'avg_volume_ratio': np.mean([m.volume_ratio for m in self.current_signals.values()]),
# 'avg_signal_strength': np.mean([m.signal_strength for m in self.current_signals.values()]),
# 'avg_confidence': np.mean([m.signal_confidence for m in self.current_signals.values()]),
# 'avg_institutional_flow': np.mean([m.institutional_flow for m in self.current_signals.values()]),
# 'symbols_with_unusual_activity': sum(1 for m in self.current_signals.values() if m.unusual_activity),
# }
#                 summary['average_metrics'] = avg_metrics

#             return summary

#     def update_models(self):
#         "Update analysis models periodically"
#         try:
            # This would trigger model retraining with new data
            # For now, just clean up old data
#             self._cleanup_old_data()
#             self.logger.info("Smart money models updated")
#         except Exception as e:
#             self.logger.error(f"Error updating smart money models: {e}")

#     def _cleanup_old_data(self):
#         "Clean up old data"
#         cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)

        # Clean up old trade data
#         for symbol in list(self.trade_data.keys()):
#             while (self.trade_data[symbol] and
#                     self.trade_data[symbol][0]['timestamp'] < cutoff_time):
#                 self.trade_data[symbol].popleft()

#     def shutdown(self):
#         "Shutdown the smart money analysis engine"
#         self.logger.info("Smart Money Analysis Engine shutdown complete")


# Factory function
# def create_smart_money_engine(
#     volume_threshold_multiplier: float = 2.0,
#     anomaly_contamination: float = 0.1,
#     enable_anomaly_detection: bool = True,
# ) -> SmartMoneyAnalysisEngine:
#     "Create smart money analysis engine with specified configuration"

# config = SmartMoneyConfig(
#         volume_threshold_multiplier=volume_threshold_multiplier,
#         anomaly_contamination=anomaly_contamination,
#         enable_anomaly_detection=enable_anomaly_detection,
# )

#     return SmartMoneyAnalysisEngine(config)