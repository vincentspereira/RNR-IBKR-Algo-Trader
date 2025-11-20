import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np
import pandas as pd
from scipy import stats
#!/usr/bin/env python3

# Institutional-Grade RSI Mean Reversion Strategy Implementation

# This module implements a comprehensive RSI mean reversion strategy following
# the 5-Pillar Strategy Architecture with volume-weighted indicators and advanced
# statistical analysis for contrarian trading.

# Features:
# - Volume-weighted RSI calculations
# - Multi-timeframe RSI analysis
# - Statistical mean reversion detection
# - Dynamic overbought/oversold levels
# - Volume profile analysis
# - Market regime adaptation

# ""Author: Algorithmic Trading System"
# Version: 1.0.0
# Date: 15 October 2025"




# Import base strategy components
# try:
#     from infrastructure.config.master_config import get_config

#     from ..core.base_institutional_strategy import ()
#         BaseInstitutionalStrategy,
#         ExecutionOrder,
#         MarketRegime,
#         PerformanceMetrics,
#         RiskLevel,
#         RiskMetrics,
#         SignalData,
#         SignalType,
# StrategyState,)

#         StrategyConfig, IndicatorConfig, SignalConfig, RiskConfig,
#         RegimeConfig, ExecutionConfig, PerformanceConfig, BacktestConfig

# except ImportError:
    # Fallback for development:
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

#     @dataclass
#     class SignalData:
#         "signal_type: SignalType"
#         strength: float
#         confidence: float
#         timestamp: datetime
#         price: Decimal
#         volume: int = 0

class RSICondition(Enum):""
#     "RSI market conditions"
#     EXTREMELY_OVERSOLD = "extremely_oversold"  # RSI < 20""
#     OVERSOLD = "oversold"                      # RSI < 30""
#     NEUTRAL = "neutral"                        # 30 <= RSI <= 70""
#     OVERBOUGHT = "overbought"                  # RSI > 70""
#     EXTREMELY_OVERBOUGHT = "extremely_overbought"  # RSI > 80

class MeanReversionStrength(Enum):""
#     "Mean reversion signal strength"
#     VERY_WEAK = "very_weak"
#     WEAK = "weak"
#     MODERATE = "moderate"
#     STRONG = "strong"
#     VERY_STRONG = "very_strong"

# "

class VolumeProfile(Enum):""
#     "Volume profile analysis"
#     ACCUMULATION = "accumulation"      # High volume on dips""
#     DISTRIBUTION = "distribution"      # High volume on rallies""
#     NEUTRAL = "neutral"               # Normal volume pattern""
#     CLIMAX = "climax"                 # Extreme volume spike

# @dataclass
class RSIMeanReversionSignal:""
# "Enhanced RSI mean reversion signal":
#     signal_type: SignalType
#     strength: float
#     confidence: float
#     timestamp: datetime
#     price: Decimal
#     volume: int
#     rsi_value: float
#     vw_rsi_value: float
#     rsi_condition: RSICondition
#     mean_reversion_strength: MeanReversionStrength
#     volume_profile: VolumeProfile
#     statistical_significance: float  # P-value for mean reversion
#     price_deviation_from_mean: float  # Standard deviations from mean
#     volume_confirmation: bool
#     multi_timeframe_alignment: bool
#     expected_reversion_target: float
#     risk_reward_ratio: float
#     bollinger_position: float  # Position within Bollinger Bands

# @dataclass
class RSIMeanReversionConfig:""
# "Configuration for RSI Mean Reversion strategy":
    # RSI parameters
#     rsi_period: int = 14
#     rsi_oversold_level: float = 30.0
#     rsi_overbought_level: float = 70.0
#     rsi_extreme_oversold: float = 20.0
#     rsi_extreme_overbought: float = 80.0

    # Volume-weighted RSI parameters
#     use_volume_weighted_rsi: bool = True
#     volume_lookback_period: int = 20
#     volume_threshold_multiplier: float = 1.5

    # Mean reversion parameters
#     mean_lookback_period: int = 50
#     std_dev_threshold: float = 2.0  # Standard deviations for extreme moves
#     statistical_significance_threshold: float = 0.05  # P-value threshold

    # Multi-timeframe parameters
#     use_multi_timeframe: bool = True
#     higher_timeframe_multiplier: int = 4
#     lower_timeframe_multiplier: int = 0.25

    # Bollinger Bands parameters
#     bb_period: int = 20
#     bb_std_dev: float = 2.0

    # Risk management
#     max_position_size: float = 0.03  # 3% of account
#     stop_loss_atr_multiplier: float = 1.5
#     take_profit_atr_multiplier: float = 2.5
#     max_holding_period_hours: int = 48  # Maximum holding period

    # Volume analysis
#     volume_profile_lookback: int = 100
#     climax_volume_threshold: float = 3.0  # Volume spike threshold

    # Performance optimization
#     min_reversion_probability: float = 0.65  # Minimum probability for signal
#     correlation_threshold: float = 0.3  # Price-volume correlation threshold
#     volatility_adjustment: bool = True

class RSIMeanReversionStrategy(BaseInstitutionalStrategy):""

# Institutional-Grade RSI Mean Reversion Strategy

# Implements sophisticated mean reversion trading with:
# - Volume-weighted RSI calculations
# - Statistical significance testing
# - Multi-timeframe analysis
# - Volume profile analysis
# - Dynamic overbought/oversold levels
# - Market regime adaptation"


#     def __init__(self, config: RSIMeanReversionConfig):
#         "Initialize RSI mean reversion strategy"
#         super().__init__()
#         self.config = config
#         self.logger = logging.getLogger(self.__class__.__name__)

        # Strategy state
#         self.state = StrategyState.INACTIVE
#         self.current_signals: List[RSIMeanReversionSignal] = []
#         self.active_positions: Dict[str, Dict] = {}

        # Technical indicators
#         self.rsi_values: List[float] = []
#         self.vw_rsi_values: List[float] = []
#         self.bb_upper: List[float] = []
#         self.bb_lower: List[float] = []
#         self.bb_middle: List[float] = []

        # Statistical analysis
#         self.price_mean: Optional[float] = None
#         self.price_std: Optional[float] = None
#         self.reversion_probabilities: List[float] = []

        # Multi-timeframe data
#         self.higher_tf_rsi: Optional[float] = None
#         self.lower_tf_rsi: Optional[float] = None

        # Performance tracking
#         self.reversion_accuracy: List[bool] = []
#         self.mean_reversion_times: List[float] = []
#         self.statistical_performance: List[float] = []
# "
#         self.logger.info(f"RSI Mean Reversion strategy initialized with RSI period: {config.rsi_period}")

    # Pillar 1: Signal Generation"
#     def generate_signals(self, market_data: pd.DataFrame):

# Generate RSI mean reversion signals with statistical analysis

# Args:
# market_data: Market data with OHLCV

# Returns:
# List of RSI mean reversion signals with statistical validation"

#         try:
#             if len(market_data) < max(self.config.rsi_period, self.config.mean_lookback_period):
#                 return []

#             signals = []

            # Calculate RSI indicators
#             rsi = self._calculate_rsi(market_data)
#             vw_rsi = self._calculate_volume_weighted_rsi(market_data) if self.config.use_volume_weighted_rsi else rsi

            # Calculate Bollinger Bands
#             bb_upper, bb_middle, bb_lower = self._calculate_bollinger_bands(market_data)

            # Store for later use
#             self.rsi_values = rsi.tolist()
#             self.vw_rsi_values = vw_rsi.tolist()
#             self.bb_upper = bb_upper.tolist()
#             self.bb_middle = bb_middle.tolist()
#             self.bb_lower = bb_lower.tolist()

            # Statistical analysis
#             self._update_statistical_metrics(market_data)

            # Detect mean reversion opportunities
#             reversion_signals = self._detect_mean_reversion_signals(market_data, rsi, vw_rsi, bb_upper, bb_middle, bb_lower)

#             for signal_data in reversion_signals:
                # Volume profile analysis
#                 volume_profile = self._analyze_volume_profile(market_data)

                # Multi-timeframe confirmation
#                 mtf_alignment = self._check_multi_timeframe_alignment(signal_data['signal_type'])

                # Statistical significance test
#                 statistical_significance = self._calculate_statistical_significance(market_data, signal_data)
# '
                # Create enhanced signal'
# current_price = Decimal(str(market_data['close'].iloc[-1]))'
#                 current_volume = market_data['volume'].iloc[-1]
# '
# signal = RSIMeanReversionSignal('
# signal_type=signal_data['signal_type'],)
#                     strength=self._calculate_signal_strength(signal_data, volume_profile, statistical_significance),
#                     confidence=self._calculate_confidence(signal_data, mtf_alignment, statistical_significance),
#                     timestamp=datetime.now(),
#                     price=current_price,
#                     volume=int(current_volume),
# rsi_value=rsi.iloc[-1],'
# vw_rsi_value=vw_rsi.iloc[-1],'
# rsi_condition=signal_data['rsi_condition'],'
#                     mean_reversion_strength=signal_data['reversion_strength'],
#                     volume_profile=volume_profile,
#                     statistical_significance=statistical_significance,
#                     price_deviation_from_mean=self._calculate_price_deviation(market_data),
#                     volume_confirmation=self._check_volume_confirmation(market_data),
#                     multi_timeframe_alignment=mtf_alignment,
#                     expected_reversion_target=self._calculate_reversion_target(market_data, signal_data),
#                     risk_reward_ratio=self._calculate_risk_reward_ratio(market_data, signal_data),
#                     bollinger_position=self._calculate_bollinger_position(market_data, bb_upper, bb_middle, bb_lower)


#                 signals.append(signal)

            # Filter signals by quality and statistical significance
#             filtered_signals = self._filter_signals(signals)

#             self.current_signals = filtered_signals
#             return filtered_signals

#         except Exception as e:""
#             self.logger.error(f"Error generating RSI mean reversion signals: {e}")
#             return []

#     def _calculate_rsi(self, data: pd.DataFrame):
# "Calculate traditional RSI"'
#         try:''
#             prices = data['close']
#             delta = prices.diff()

#             gains = delta.where(delta > 0, 0)
#             losses = -delta.where(delta < 0, 0)

#             avg_gains = gains.rolling(window=self.config.rsi_period).mean()
#             avg_losses = losses.rolling(window=self.config.rsi_period).mean()

#             rs = avg_gains / avg_losses
#             rsi = 100 - (100 / (1 + rs))

#             return rsi.fillna(50)  # Fill NaN with neutral RSI

#         except Exception as e:""
#             self.logger.error(f"Error calculating RSI: {e}")
#             return pd.Series([50] * len(data), index=data.index)

#     def _calculate_volume_weighted_rsi(self, data: pd.DataFrame):
# "Calculate Volume-Weighted RSI"'
#         try:''
# prices = data['close']'
#             volumes = data['volume']

            # Calculate volume-weighted price changes
#             price_changes = prices.diff()
#             volume_weights = volumes / volumes.rolling(self.config.volume_lookback_period).mean()

            # Separate gains and losses with volume weighting
#             weighted_gains = (price_changes * volume_weights).where(price_changes > 0, 0)
#             weighted_losses = (-price_changes * volume_weights).where(price_changes < 0, 0)

            # Calculate average gains and losses
#             avg_weighted_gains = weighted_gains.rolling(self.config.rsi_period).mean()
#             avg_weighted_losses = weighted_losses.rolling(self.config.rsi_period).mean()

            # Calculate volume-weighted RSI
#             rs = avg_weighted_gains / avg_weighted_losses
#             vw_rsi = 100 - (100 / (1 + rs))

#             return vw_rsi.fillna(50)

#         except Exception as e:""
#             self.logger.error(f"Error calculating volume-weighted RSI: {e}")
#             return self._calculate_rsi(data)

#     def _calculate_bollinger_bands(self, data: pd.DataFrame):
# "Calculate Bollinger Bands"'
#         try:''
#             prices = data['close']

#             middle = prices.rolling(self.config.bb_period).mean()
#             std = prices.rolling(self.config.bb_period).std()

#             upper = middle + (std * self.config.bb_std_dev)
#             lower = middle - (std * self.config.bb_std_dev)

#             return upper, middle, lower

#         except Exception as e:"''
#             self.logger.error(f"Error calculating Bollinger Bands: {e}")
#             prices = data['close']
#             return prices, prices, prices

#     def _update_statistical_metrics(self, data: pd.DataFrame):
#         "Update statistical metrics for mean reversion analysis"
#         try:''
#             if len(data) >= self.config.mean_lookback_period:''
#                 recent_prices = data['close'].iloc[-self.config.mean_lookback_period:]
#                 self.price_mean = recent_prices.mean()
#                 self.price_std = recent_prices.std()

#         except Exception as e:""
#             self.logger.error(f"Error updating statistical metrics: {e}")

#     def _detect_mean_reversion_signals(self, data: pd.DataFrame, rsi: pd.Series, vw_rsi: pd.Series,)
# bb_upper: pd.Series, bb_middle: pd.Series, bb_lower: pd.Series -> List[Dict]:"
#         "Detect mean reversion opportunities"
#         signals = []

#         try:
# current_rsi = rsi.iloc[-1]'
# current_vw_rsi = vw_rsi.iloc[-1]'
#             current_price = data['close'].iloc[-1]

            # Determine RSI condition
#             rsi_condition = self._classify_rsi_condition(current_rsi)

            # Check for oversold mean reversion (buy signal)'
#             if self._check_oversold_reversion(current_rsi, current_vw_rsi, current_price, bb_lower.iloc[-1]):''
# reversion_strength = self._calculate_reversion_strength(data, 'buy')'
# signals.append({'
# 'signal_type': SignalType.BUY,'
# 'rsi_condition': rsi_condition,'
# 'reversion_strength': reversion_strength,'
# 'trigger_price': current_price}
# )

            # Check for overbought mean reversion (sell signal)'
#             elif self._check_overbought_reversion(current_rsi, current_vw_rsi, current_price, bb_upper.iloc[-1]):''
# reversion_strength = self._calculate_reversion_strength(data, 'sell')'
# signals.append({'
# 'signal_type': SignalType.SELL,'
# 'rsi_condition': rsi_condition,'
# 'reversion_strength': reversion_strength,'
# 'trigger_price': current_price}
# )

#             return signals

#         except Exception as e:""
#             self.logger.error(f"Error detecting mean reversion signals: {e}")
#             return []

#     def _classify_rsi_condition(self, rsi_value: float):
#         "Classify RSI condition"
#         if rsi_value < self.config.rsi_extreme_oversold:
#             return RSICondition.EXTREMELY_OVERSOLD
#         elif rsi_value < self.config.rsi_oversold_level:
#             return RSICondition.OVERSOLD
#         elif rsi_value > self.config.rsi_extreme_overbought:
#             return RSICondition.EXTREMELY_OVERBOUGHT
#         elif rsi_value > self.config.rsi_overbought_level:
#             return RSICondition.OVERBOUGHT
#         else:
#             return RSICondition.NEUTRAL

#     def _check_oversold_reversion(self, rsi: float, vw_rsi: float, price: float, bb_lower: float):
#         "Check for oversold mean reversion opportunity"
#         try:
            # RSI oversold condition
#             rsi_oversold = rsi < self.config.rsi_oversold_level
#             vw_rsi_oversold = vw_rsi < self.config.rsi_oversold_level

            # Price near Bollinger Band lower
#             near_bb_lower = price <= bb_lower * 1.02  # Within 2% of lower band

            # Statistical deviation check
#             if self.price_mean and self.price_std:
#                 price_deviation = (self.price_mean - price) / self.price_std
#                 extreme_deviation = price_deviation > self.config.std_dev_threshold
#             else:
#                 extreme_deviation = False

#             return (rsi_oversold or vw_rsi_oversold) and (near_bb_lower or extreme_deviation)

#         except Exception as e:""
#             self.logger.error(f"Error checking oversold reversion: {e}")
#             return False

#     def _check_overbought_reversion(self, rsi: float, vw_rsi: float, price: float, bb_upper: float):
#         "Check for overbought mean reversion opportunity"
#         try:
            # RSI overbought condition
#             rsi_overbought = rsi > self.config.rsi_overbought_level
#             vw_rsi_overbought = vw_rsi > self.config.rsi_overbought_level

            # Price near Bollinger Band upper
#             near_bb_upper = price >= bb_upper * 0.98  # Within 2% of upper band

            # Statistical deviation check
#             if self.price_mean and self.price_std:
#                 price_deviation = (price - self.price_mean) / self.price_std
#                 extreme_deviation = price_deviation > self.config.std_dev_threshold
#             else:
#                 extreme_deviation = False

#             return (rsi_overbought or vw_rsi_overbought) and (near_bb_upper or extreme_deviation)

#         except Exception as e:""
#             self.logger.error(f"Error checking overbought reversion: {e}")
#             return False

#     def _calculate_reversion_strength(self, data: pd.DataFrame, signal_type: str):
#         "Calculate mean reversion strength"
#         try:''
            # Price momentum (contrarian indicator)'
#             momentum = (data['close'].iloc[-1] - data['close'].iloc[-5]) / data['close'].iloc[-5]
# '
            # Volume confirmation'
#             volume_ratio = data['volume'].iloc[-1] / data['volume'].rolling(20).mean().iloc[-1]

            # Statistical deviation'
#             if self.price_mean and self.price_std:''
#                 deviation = abs(data['close'].iloc[-1] - self.price_mean) / self.price_std
#             else:
#                 deviation = 1.0

            # Combine factors
#             strength_score = abs(momentum) * 0.3 + (volume_ratio - 1.0) * 0.3 + deviation * 0.4

            # Classify strength
#             if strength_score > 3.0:
#                 return MeanReversionStrength.VERY_STRONG
#             elif strength_score > 2.0:
#                 return MeanReversionStrength.STRONG
#             elif strength_score > 1.5:
#                 return MeanReversionStrength.MODERATE
#             elif strength_score > 1.0:
#                 return MeanReversionStrength.WEAK
#             else:
#                 return MeanReversionStrength.VERY_WEAK

#         except Exception as e:""
#             self.logger.error(f"Error calculating reversion strength: {e}")
#             return MeanReversionStrength.MODERATE

#     def _analyze_volume_profile(self, data: pd.DataFrame):
#         "Analyze volume profile for mean reversion context"
#         try:
#             if len(data) < self.config.volume_profile_lookback:
#                 return VolumeProfile.NEUTRAL

#             recent_data = data.iloc[-self.config.volume_profile_lookback:]
# '
            # Calculate volume statistics'
# avg_volume = recent_data['volume'].mean()'
#             current_volume = data['volume'].iloc[-1]
#             volume_ratio = current_volume / avg_volume
# '
            # Price trend analysis'
#             price_trend = (data['close'].iloc[-1] - data['close'].iloc[-10]) / data['close'].iloc[-10]

            # Classify volume profile
#             if volume_ratio > self.config.climax_volume_threshold:
#                 return VolumeProfile.CLIMAX
#             elif volume_ratio > 1.5 and price_trend < -0.02:  # High volume on decline
#                 return VolumeProfile.ACCUMULATION
#             elif volume_ratio > 1.5 and price_trend > 0.02:   # High volume on advance
#                 return VolumeProfile.DISTRIBUTION
#             else:
#                 return VolumeProfile.NEUTRAL

#         except Exception as e:""
#             self.logger.error(f"Error analyzing volume profile: {e}")
#             return VolumeProfile.NEUTRAL

#     def _check_multi_timeframe_alignment(self, signal_type: SignalType):
#         "Check multi-timeframe RSI alignment"
#         try:
#             if not self.config.use_multi_timeframe:
#                 return True

            # Placeholder for multi-timeframe logic
            # In practice, this would analyze RSI on higher and lower timeframes
#             return True

#         except Exception as e:""
#             self.logger.error(f"Error checking multi-timeframe alignment: {e}")
#             return True

#     def _calculate_statistical_significance(self, data: pd.DataFrame, signal_data: Dict):
#         "Calculate statistical significance of mean reversion signal"
#         try:
#             if len(data) < 30:  # Need minimum sample size
#                 return 0.5
# '
            # Get recent price returns'
#             returns = data['close'].pct_change().dropna().iloc[-30:]

            # Test for mean reversion using t-test
            # H0: mean return = 0 (no mean reversion)
            # H1: mean return != 0 (mean reversion exists)
#             t_stat, p_value = stats.ttest_1samp(returns, 0)

            # Return 1 - p_value as significance (higher is more significant)
#             return max(0.0, min(1.0, 1.0 - p_value))

#         except Exception as e:""
#             self.logger.error(f"Error calculating statistical significance: {e}")
#             return 0.5

#     def _calculate_price_deviation(self, data: pd.DataFrame):
#         "Calculate price deviation from mean in standard deviations"
#         try:''
#             if self.price_mean and self.price_std and self.price_std > 0:''
#                 current_price = data['close'].iloc[-1]
#                 deviation = abs(current_price - self.price_mean) / self.price_std
#                 return float(deviation)
#             else:
#                 return 0.0

#         except Exception as e:""
#             self.logger.error(f"Error calculating price deviation: {e}")
#             return 0.0

#     def _check_volume_confirmation(self, data: pd.DataFrame):
# "Check if volume confirms the mean reversion signal"'
#         try:''
# current_volume = data['volume'].iloc[-1]'
#             avg_volume = data['volume'].rolling(20).mean().iloc[-1]

#             return current_volume >= avg_volume * self.config.volume_threshold_multiplier

#         except Exception as e:""
#             self.logger.error(f"Error checking volume confirmation: {e}")
#             return False

#     def _calculate_reversion_target(self, data: pd.DataFrame, signal_data: Dict):
#         "Calculate expected mean reversion target"
#         try:
#             if self.price_mean:
                # Target is the statistical mean
#                 return float(self.price_mean)
#             else:''
                # Fallback to moving average'
#                 return float(data['close'].rolling(20).mean().iloc[-1])

#         except Exception as e:"''
#             self.logger.error(f"Error calculating reversion target: {e}")
#             return float(data['close'].iloc[-1])

#     def _calculate_risk_reward_ratio(self, data: pd.DataFrame, signal_data: Dict):
# "Calculate risk-reward ratio for mean reversion trade"'
#         try:''
#             current_price = data['close'].iloc[-1]
#             target_price = self._calculate_reversion_target(data, signal_data)

            # Calculate ATR for stop loss
#             atr = self._calculate_atr(data, 14).iloc[-1]
#             stop_distance = atr * self.config.stop_loss_atr_multiplier

            # Calculate potential profit and loss
#             potential_profit = abs(target_price - current_price)
#             potential_loss = stop_distance

#             if potential_loss > 0:
#                 return float(potential_profit / potential_loss)
#             else:
#                 return 2.0  # Default ratio

#         except Exception as e:""
#             self.logger.error(f"Error calculating risk-reward ratio: {e}")
#             return 2.0

#     def _calculate_atr(self, data: pd.DataFrame, period: int):
# "Calculate Average True Range"'
#         try:''
# high_low = data['high'] - data['low']'
# high_close = abs(data['high'] - data['close'].shift())'
#             low_close = abs(data['low'] - data['close'].shift())

#             true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
#             return true_range.rolling(period).mean()

#         except Exception as e:""
#             self.logger.error(f"Error calculating ATR: {e}")
#             return pd.Series([0.02] * len(data), index=data.index)

#     def _calculate_bollinger_position(self, data: pd.DataFrame, bb_upper: pd.Series,)
# bb_middle: pd.Series, bb_lower: pd.Series -> float:"
# "Calculate position within Bollinger Bands (0 = lower band, 1 = upper band)"'
#         try:''
#             current_price = data['close'].iloc[-1]
#             upper = bb_upper.iloc[-1]
#             lower = bb_lower.iloc[-1]

#             if upper > lower:
#                 position = (current_price - lower) / (upper - lower)
#                 return max(0.0, min(1.0, float(position)))
#             else:
#                 return 0.5  # Neutral position

#         except Exception as e:""
#             self.logger.error(f"Error calculating Bollinger position: {e}")
#             return 0.5

#     def _calculate_signal_strength(self, signal_data: Dict, volume_profile: VolumeProfile,)
# statistical_significance: float -> float:"
#         "Calculate signal strength based on multiple factors"
#         try:
#             base_strength = 0.5

            # Reversion strength bonus
# strength_multipliers = {
# MeanReversionStrength.VERY_STRONG: 1.5,
# MeanReversionStrength.STRONG: 1.3,
# MeanReversionStrength.MODERATE: 1.0,
# MeanReversionStrength.WEAK: 0.8,
# MeanReversionStrength.VERY_WEAK: 0.6}'
# '
#             base_strength *= strength_multipliers[signal_data['reversion_strength']]

            # Statistical significance bonus
#             base_strength += statistical_significance * 0.3

            # Volume profile bonus
#             if volume_profile in [VolumeProfile.ACCUMULATION, VolumeProfile.DISTRIBUTION]:
#                 base_strength += 0.15
#             elif volume_profile == VolumeProfile.CLIMAX:
#                 base_strength += 0.25

#             return min(base_strength, 1.0)

#         except Exception as e:""
#             self.logger.error(f"Error calculating signal strength: {e}")
#             return 0.5

#     def _calculate_confidence(self, signal_data: Dict, mtf_alignment: bool,)
# statistical_significance: float -> float:"
#         "Calculate signal confidence"
#         try:
#             base_confidence = 0.6

            # Statistical significance bonus
#             if statistical_significance > 0.7:
#                 base_confidence += 0.2
#             elif statistical_significance > 0.5:
#                 base_confidence += 0.1

            # Multi-timeframe alignment bonus
#             if mtf_alignment:
#                 base_confidence += 0.1
# '
            # Extreme RSI levels bonus'
#             rsi_condition = signal_data['rsi_condition']
#             if rsi_condition in [RSICondition.EXTREMELY_OVERSOLD, RSICondition.EXTREMELY_OVERBOUGHT]:
#                 base_confidence += 0.15

#             return min(base_confidence, 0.95)

#         except Exception as e:""
#             self.logger.error(f"Error calculating confidence: {e}")
#             return 0.6

#     def _filter_signals(self, signals: List[RSIMeanReversionSignal]):
#         "Filter signals based on quality criteria"
#         filtered = []

#         for signal in signals:
            # Minimum confidence threshold
#             if signal.confidence < 0.65:
#                 continue

            # Statistical significance threshold
#             if signal.statistical_significance < self.config.statistical_significance_threshold:
#                 continue

            # Minimum reversion strength
#             if signal.mean_reversion_strength == MeanReversionStrength.VERY_WEAK:
#                 continue

            # Risk-reward ratio check
#             if signal.risk_reward_ratio < 1.5:
#                 continue

            # Price deviation threshold
#             if signal.price_deviation_from_mean < 1.0:  # Less than 1 standard deviation
#                 continue

#             filtered.append(signal)

#         return filtered

    # Pillar 2: Risk Management"
#     def calculate_position_size(self, signal: RSIMeanReversionSignal, account_balance: Decimal):
#         "Calculate position size with mean reversion risk adjustment"
#         try:
            # Base position size
#             base_size = account_balance * Decimal(str(self.config.max_position_size))

            # Adjust for signal strength and confidence
#             strength_multiplier = Decimal(str(signal.strength * signal.confidence))
#             adjusted_size = base_size * strength_multiplier

            # Statistical significance adjustment
#             stat_multiplier = Decimal(str(signal.statistical_significance))
#             adjusted_size *= stat_multiplier

            # Mean reversion strength adjustment'
# strength_multipliers = {'
# MeanReversionStrength.VERY_STRONG: Decimal('1.3'),'
# MeanReversionStrength.STRONG: Decimal('1.1'),'
# MeanReversionStrength.MODERATE: Decimal('1.0'),'
# MeanReversionStrength.WEAK: Decimal('0.8'),'
# MeanReversionStrength.VERY_WEAK: Decimal('0.6')}

#             adjusted_size *= strength_multipliers[signal.mean_reversion_strength]

            # Volatility adjustment
#             if self.config.volatility_adjustment:
#                 volatility_factor = Decimal(str(max(0.5, 1.0 - signal.price_deviation_from_mean * 0.1)))
#                 adjusted_size *= volatility_factor
# '
            # Ensure limits'
#             min_size = account_balance * Decimal('0.005')  # 0.5% minimum
#             max_size = account_balance * Decimal(str(self.config.max_position_size))

#             return max(min_size, min(adjusted_size, max_size))

#         except Exception as e:"''
#             self.logger.error(f"Error calculating position size: {e}")
#             return account_balance * Decimal('0.02')  # Default 2%

#     def calculate_stop_loss(self, signal: RSIMeanReversionSignal, atr: float):
#         "Calculate stop loss for mean reversion position"
#         try:
#             stop_distance = atr * self.config.stop_loss_atr_multiplier

#             if signal.signal_type == SignalType.BUY:
#                 return signal.price - Decimal(str(stop_distance))
#             else:
#                 return signal.price + Decimal(str(stop_distance))

#         except Exception as e:"''
#             self.logger.error(f"Error calculating stop loss: {e}")
#             return signal.price * Decimal('0.97')  # Default 3% stop

#     def calculate_take_profit(self, signal: RSIMeanReversionSignal):
#         "Calculate take profit based on reversion target"
#         try:
#             return Decimal(str(signal.expected_reversion_target))

#         except Exception as e:"''
#             self.logger.error(f"Error calculating take profit: {e}")
#             return signal.price * Decimal('1.02')  # Default 2% profit

    # Pillar 3: Market Regime Adaptation"
#     def detect_market_regime(self, market_data: pd.DataFrame):
#         "Detect market regime for mean reversion adaptation"
#         try:
#             if len(market_data) < 50:
#                 return MarketRegime.SIDEWAYS
# '
            # Volatility analysis'
# volatility = market_data['close'].rolling(20).std().iloc[-1] / market_data['close'].iloc[-1]'
#             avg_volatility = market_data['close'].rolling(50).std().mean() / market_data['close'].rolling(50).mean().iloc[-1]
# '
            # Trend analysis'
# short_ma = market_data['close'].rolling(10).mean().iloc[-1]'
#             long_ma = market_data['close'].rolling(50).mean().iloc[-1]
#             trend_strength = abs(short_ma - long_ma) / long_ma

            # RSI analysis
#             current_rsi = self.rsi_values[-1] if self.rsi_values else 50

            # Determine regime
#             if volatility > avg_volatility * 1.5:
#                 return MarketRegime.HIGH_VOLATILITY
#             elif trend_strength > 0.05 and current_rsi > 60:
#                 return MarketRegime.TRENDING_UP
#             elif trend_strength > 0.05 and current_rsi < 40:
#                 return MarketRegime.TRENDING_DOWN
#             elif volatility < avg_volatility * 0.7:
#                 return MarketRegime.LOW_VOLATILITY
#             else:
#                 return MarketRegime.SIDEWAYS

#         except Exception as e:""
#             self.logger.error(f"Error detecting market regime: {e}")
#             return MarketRegime.SIDEWAYS

#     def adapt_strategy_parameters(self, regime: MarketRegime):
#         "Adapt strategy parameters based on market regime"
#         try:
#             if regime == MarketRegime.HIGH_VOLATILITY:
                # More conservative in volatile markets
#                 self.config.rsi_oversold_level = 25.0
#                 self.config.rsi_overbought_level = 75.0
#                 self.config.std_dev_threshold = 2.5
#                 self.config.max_position_size *= 0.7

#             elif regime == MarketRegime.LOW_VOLATILITY:
                # More aggressive in calm markets
#                 self.config.rsi_oversold_level = 35.0
#                 self.config.rsi_overbought_level = 65.0
#                 self.config.std_dev_threshold = 1.5
#                 self.config.max_position_size *= 1.2

#             elif regime in [MarketRegime.TRENDING_UP, MarketRegime.TRENDING_DOWN]:
                # Adjust for trending markets (less mean reversion)
#                 self.config.statistical_significance_threshold = 0.1
#                 self.config.min_reversion_probability = 0.7

#             elif regime == MarketRegime.SIDEWAYS:
                # Optimal for mean reversion
#                 self.config.rsi_oversold_level = 30.0
#                 self.config.rsi_overbought_level = 70.0
#                 self.config.statistical_significance_threshold = 0.05
# "
#             self.logger.info(f"Adapted parameters for regime: {regime}")

#         except Exception as e:""
#             self.logger.error(f"Error adapting parameters: {e}")

    # Pillar 4: Execution Management"
#     def create_execution_order(self, signal: RSIMeanReversionSignal, position_size: Decimal):
#         "Create execution order for mean reversion signal"
#         try:
#             atr = 0.02  # Default ATR, should be calculated from market data
#             stop_loss = self.calculate_stop_loss(signal, atr)
#             take_profit = self.calculate_take_profit(signal)

# order = ExecutionOrder(
#                 signal_type=signal.signal_type,
#                 quantity=position_size,
#                 price=signal.price,
#                 stop_loss=stop_loss,
# take_profit=take_profit,'
# timestamp=signal.timestamp,'
# urgency='MEDIUM','
# execution_style='PATIENT',)'
#                 max_slippage=Decimal('0.002'),  # 0.2% max slippage''
#                 time_in_force='GTC'  # Good Till Cancelled


#             return order

#         except Exception as e:""
#             self.logger.error(f"Error creating execution order: {e}")
#             return None

    # Pillar 5: Performance Tracking"
#     def update_performance_metrics(self, trade_result: Dict[str, Any]):
#         "Update performance metrics for mean reversion strategy"
#         try:''
            # Track reversion accuracy'
#             was_profitable = trade_result.get('pnl', 0) > 0
#             self.reversion_accuracy.append(was_profitable)
# '
            # Track mean reversion time'
#             holding_time = trade_result.get('holding_time_hours', 24)
#             self.mean_reversion_times.append(holding_time)
# '
            # Track statistical performance'
#             statistical_score = trade_result.get('statistical_significance', 0.5)
#             self.statistical_performance.append(statistical_score)

            # Log performance metrics
#             if len(self.reversion_accuracy) % 10 == 0:  # Every 10 trades
#                 win_rate = np.mean(self.reversion_accuracy[-10:]) * 100
#                 avg_reversion_time = np.mean(self.mean_reversion_times[-10:])
#                 avg_statistical_score = np.mean(self.statistical_performance[-10:])

#                 self.logger.info(""
# f"Mean Reversion Performance - Win Rate: {win_rate:.1f}%,
# f"Avg Reversion Time: {avg_reversion_time:.1f}h,
# f"Statistical Score: {avg_statistical_score:.2f}")


#         except Exception as e:""
#             self.logger.error(f"Error updating performance metrics: {e}")

#     def get_strategy_status(self):
#         "Get current strategy status and performance"
#         try:''
#             return {''
# 'strategy_name': 'RSIMeanReversionStrategy','
# 'state': self.state.value,'
# 'rsi_period': self.config.rsi_period,'
# 'current_signals': len(self.current_signals),'
# 'active_positions': len(self.active_positions),'
# 'current_rsi': self.rsi_values[-1] if self.rsi_values else None,'
# 'current_vw_rsi': self.vw_rsi_values[-1] if self.vw_rsi_values else None,'
# 'price_mean': self.price_mean,'
# 'price_std': self.price_std,'
# 'win_rate_pct': np.mean(self.reversion_accuracy) * 100 if self.reversion_accuracy else 0,'
# 'avg_reversion_time_hours': np.mean(self.mean_reversion_times) if self.mean_reversion_times else 0,'
# 'avg_statistical_score': np.mean(self.statistical_performance) if self.statistical_performance else 0,'
# 'last_update': datetime.now().isoformat()}


#         except Exception as e:"''
#             self.logger.error(f"Error getting strategy status: {e}")
#             return {'error': str(e)}

# Example usage and configuration"
# def create_rsi_mean_reversion_config():
#     "Create a sample RSI mean reversion strategy configuration"
#     return RSIMeanReversionConfig(
#         rsi_period=14,
#         rsi_oversold_level=30.0,
#         rsi_overbought_level=70.0,
#         rsi_extreme_oversold=20.0,
#         rsi_extreme_overbought=80.0,
#         use_volume_weighted_rsi=True,
#         volume_lookback_period=20,
#         volume_threshold_multiplier=1.5,
#         mean_lookback_period=50,
#         std_dev_threshold=2.0,
#         statistical_significance_threshold=0.05,
#         use_multi_timeframe=True,
#         bb_period=20,
#         bb_std_dev=2.0,
#         max_position_size=0.03,
#         stop_loss_atr_multiplier=1.5,
#         take_profit_atr_multiplier=2.5,
#         max_holding_period_hours=48,
#         min_reversion_probability=0.65,
# volatility_adjustment=True)

# "
# if __name__ == "__main__":
    # Example usage:
#     config = create_rsi_mean_reversion_config()
#     strategy = RSIMeanReversionStrategy(config)

    # Sample market data'
# sample_data = pd.DataFrame({'
# 'timestamp': pd.date_range('2024-01-01', periods=100, freq='1H'),'
# 'open': np.random.randn(100).cumsum() + 100,'
# 'high': np.random.randn(100).cumsum() + 101,'
# 'low': np.random.randn(100).cumsum() + 99,'
# 'close': np.random.randn(100).cumsum() + 100,'
# 'volume': np.random.randint(10000, 100000, 100)}
# )

    # Generate signals"
# signals = strategy.generate_signals(sample_data)"
#     print(f"Generated {len(signals)} RSI mean reversion signals")

    # Get strategy status"
# status = strategy.get_strategy_status()"
# print(f"Strategy Status: {status}")"'
# "'"'