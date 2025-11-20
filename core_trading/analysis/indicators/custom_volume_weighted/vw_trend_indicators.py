from collections import deque
from typing import Optional, Tuple
import numpy as np
from nautilus_trader.model.data import Bar
# from .base_custom_vw_indicator import ()
"Volume-Weighted Trend Indicators."
# "
# This module implements 5 volume-weighted trend indicators:
# 1. VW ADX - Volume-weighted Average Directional Index
# 2. VW MACD Histogram - Volume-weighted MACD Histogram
# 3. VW Parabolic SAR - Volume-weighted Parabolic SAR
# 4. VW Aroon - Volume-weighted Aroon Oscillator
# 5. VW CCI - Volume-weighted Commodity Channel Index
# "
# All indicators follow the institutional-grade 5-pillar architecture."




#     BaseCustomVWIndicator,
#     CustomVWIndicatorConfig,
#     VWIndicatorType,
# )


# "

class VWADX(BaseCustomVWIndicator):""

# Volume-Weighted Average Directional Index.

# Enhanced ADX with volume weighting for improved trend strength
# measurement and directional movement analysis.

# Mathematical Formula:
# +DM = High[i] - High[i-1] (if positive, else 0)
# -DM = Low[i-1] - Low[i] (if positive, else 0)
#     TR = max(High-Low, abs(High-Close[i-1]), abs(Low-Close[i-1]))
# VW_+DI = 100 * EMA(+DM * Volume_Weight) / EMA(TR * Volume_Weight)
# VW_-DI = 100 * EMA(-DM * Volume_Weight) / EMA(TR * Volume_Weight)
#     VW_DX = 100 * abs(+DI - -DI) / (+DI + -DI)
# VW_ADX = EMA(VW_DX)"


#     def __init__(self, config: CustomVWIndicatorConfig):
#         super().__init__(config)
#         self.indicator_type = VWIndicatorType.TREND

#         self.alpha = 2.0 / (config.period + 1)

        # Previous values
#         self.prev_high = None
#         self.prev_low = None
#         self.prev_close = None

        # Volume weighting
#         self.volume_ema = None

        # Directional movement EMAs
#         self.plus_dm_ema = None
#         self.minus_dm_ema = None
#         self.tr_ema = None

        # ADX calculation
#         self.dx_ema = None
#         self.adx_values = deque(maxlen=config.period)

#         self.initialized = False

#     def _calculate_indicator_value(self, bar: Bar):
#         "Calculate Volume-Weighted ADX."
#         high = bar.high.as_double()
#         low = bar.low.as_double()
#         close = bar.close.as_double()
#         volume = bar.volume.as_double()

        # Initialize volume EMA
#         if self.volume_ema is None:
#             self.volume_ema = volume
#         else:
#             self.volume_ema = self.alpha * volume + (1 - self.alpha) * self.volume_ema

        # Calculate volume weight
#         if self.volume_ema > 0:
#             volume_weight = volume / self.volume_ema
#         else:
#             volume_weight = 1.0

        # Need previous values for calculation
#         if self.prev_high is None:
#             self.prev_high = high
#             self.prev_low = low
#             self.prev_close = close
#             return None

        # Calculate directional movements
#         plus_dm = max(high - self.prev_high, 0.0)
#         minus_dm = max(self.prev_low - low, 0.0)

        # Ensure only one directional movement is non-zero
#         if plus_dm > minus_dm:
#             minus_dm = 0.0
#         elif minus_dm > plus_dm:
#             plus_dm = 0.0
#         else:
#             plus_dm = minus_dm = 0.0

        # Calculate True Range
#         tr1 = high - low
#         tr2 = abs(high - self.prev_close)
#         tr3 = abs(low - self.prev_close)
#         true_range = max(tr1, tr2, tr3)

        # Apply volume weighting
#         vw_plus_dm = plus_dm * volume_weight
#         vw_minus_dm = minus_dm * volume_weight
#         vw_tr = true_range * volume_weight

        # Initialize EMAs
#         if not self.initialized:
#             self.plus_dm_ema = vw_plus_dm
#             self.minus_dm_ema = vw_minus_dm
#             self.tr_ema = vw_tr
#             self.initialized = True

#             self.prev_high = high
#             self.prev_low = low
#             self.prev_close = close
#             return None

        # Update EMAs
#         self.plus_dm_ema = self.alpha * vw_plus_dm + (1 - self.alpha) * self.plus_dm_ema
#         self.minus_dm_ema = (
#             self.alpha * vw_minus_dm + (1 - self.alpha) * self.minus_dm_ema
# )
#         self.tr_ema = self.alpha * vw_tr + (1 - self.alpha) * self.tr_ema

        # Calculate Directional Indicators
#         if self.tr_ema == 0:
#             plus_di = minus_di = 0.0
#         else:
#             plus_di = 100.0 * self.plus_dm_ema / self.tr_ema
#             minus_di = 100.0 * self.minus_dm_ema / self.tr_ema

        # Calculate DX
#         di_sum = plus_di + minus_di
#         if di_sum == 0:
#             dx = 0.0
#         else:
#             dx = 100.0 * abs(plus_di - minus_di) / di_sum

        # Calculate ADX
#         if self.dx_ema is None:
#             self.dx_ema = dx
#             adx = dx
#         else:
#             self.dx_ema = self.alpha * dx + (1 - self.alpha) * self.dx_ema
#             adx = self.dx_ema

#         self.adx_values.append(adx)

        # Update previous values
#         self.prev_high = high
#         self.prev_low = low
#         self.prev_close = close

#         return adx

#     def get_trend_strength(self):
#         "Get trend strength based on ADX value."
#         if self.value is None:
#             return None

#         if self.value > 50:""
#             return "VERY_STRONG"
#         elif self.value > 25:""
#             return "STRONG"
#         elif self.value > 20:""
#             return "MODERATE"
#         else:""
#             return "WEAK"

#     def get_directional_indicators(self):
#         "Get current +DI and -DI values."
#         if not self.initialized or self.tr_ema == 0:
#             return None

#         plus_di = 100.0 * self.plus_dm_ema / self.tr_ema
#         minus_di = 100.0 * self.minus_dm_ema / self.tr_ema

#         return plus_di, minus_di

#     def reset(self):
#         "Reset indicator state."
#         super().reset()
#         self.prev_high = None
#         self.prev_low = None
#         self.prev_close = None
#         self.volume_ema = None
#         self.plus_dm_ema = None
#         self.minus_dm_ema = None
#         self.tr_ema = None
#         self.dx_ema = None
#         self.adx_values.clear()
#         self.initialized = False


class VWMACDHistogram(BaseCustomVWIndicator):""

# Volume-Weighted MACD Histogram.

# Enhanced MACD Histogram with volume weighting for improved
# momentum divergence detection.

# Mathematical Formula:
#     VW_EMA_Fast = EMA_Fast(Close * Volume_Weight)
#     VW_EMA_Slow = EMA_Slow(Close * Volume_Weight)
#     VW_MACD = VW_EMA_Fast - VW_EMA_Slow
#     VW_Signal = EMA_Signal(VW_MACD)
# VW_Histogram = VW_MACD - VW_Signal"


#     def __init__(self, config: CustomVWIndicatorConfig):
#         super().__init__(config)
#         self.indicator_type = VWIndicatorType.TREND

        # MACD parameters"
#         self.fast_period = getattr(config, "fast_period", 12)""
#         self.slow_period = getattr(config, "slow_period", 26)""
#         self.signal_period = getattr(config, "signal_period", 9)

        # EMA alphas
#         self.fast_alpha = 2.0 / (self.fast_period + 1)
#         self.slow_alpha = 2.0 / (self.slow_period + 1)
#         self.signal_alpha = 2.0 / (self.signal_period + 1)
#         self.volume_alpha = 2.0 / (config.period + 1)

        # Volume weighting
#         self.volume_ema = None

        # MACD EMAs
#         self.fast_ema = None
#         self.slow_ema = None
#         self.signal_ema = None

        # Historical values
#         self.macd_values = deque(maxlen=config.period)
#         self.histogram_values = deque(maxlen=config.period)

#         self.initialized = False

#     def _calculate_indicator_value(self, bar: Bar):
#         "Calculate Volume-Weighted MACD Histogram."
#         close = bar.close.as_double()
#         volume = bar.volume.as_double()

        # Initialize volume EMA
#         if self.volume_ema is None:
#             self.volume_ema = volume
#         else:
#             self.volume_ema = (
#                 self.volume_alpha * volume + (1 - self.volume_alpha) * self.volume_ema
# )

        # Calculate volume weight
#         if self.volume_ema > 0:
#             volume_weight = volume / self.volume_ema
#         else:
#             volume_weight = 1.0

        # Volume-weighted close
#         vw_close = close * volume_weight

        # Initialize EMAs
#         if not self.initialized:
#             self.fast_ema = vw_close
#             self.slow_ema = vw_close
#             self.initialized = True
#             return None

        # Update EMAs
#         self.fast_ema = (
#             self.fast_alpha * vw_close + (1 - self.fast_alpha) * self.fast_ema
# )
#         self.slow_ema = (
#             self.slow_alpha * vw_close + (1 - self.slow_alpha) * self.slow_ema
# )

        # Calculate MACD
#         macd = self.fast_ema - self.slow_ema
#         self.macd_values.append(macd)

        # Initialize signal EMA
#         if self.signal_ema is None:
#             self.signal_ema = macd
#             histogram = 0.0
#         else:
#             self.signal_ema = (
#                 self.signal_alpha * macd + (1 - self.signal_alpha) * self.signal_ema
# )
#             histogram = macd - self.signal_ema

#         self.histogram_values.append(histogram)

#         return histogram

#     def get_macd_components(self):
#         "Get MACD, Signal, and Histogram values."
#         if not self.initialized or self.signal_ema is None:
#             return None

#         macd = self.fast_ema - self.slow_ema
#         signal = self.signal_ema
#         histogram = self.value if self.value is not None else 0.0

#         return macd, signal, histogram

#     def get_divergence_signal(self):
#         "Detect bullish/bearish divergence."
#         if len(self.histogram_values) < 10:
#             return None

#         recent_hist = list(self.histogram_values)[-5:]
#         prev_hist = list(self.histogram_values)[-10:-5]

        # Check for bullish divergence (histogram making higher lows)"
#         if min(recent_hist) > min(prev_hist) and all(h < 0 for h in recent_hist):""
#             return "BULLISH_DIVERGENCE"

        # Check for bearish divergence (histogram making lower highs)"
#         if max(recent_hist) < max(prev_hist) and all(h > 0 for h in recent_hist):""
#             return "BEARISH_DIVERGENCE"
# "
#         return "NO_DIVERGENCE"

#     def reset(self):
#         "Reset indicator state."
#         super().reset()
#         self.volume_ema = None
#         self.fast_ema = None
#         self.slow_ema = None
#         self.signal_ema = None
#         self.macd_values.clear()
#         self.histogram_values.clear()
#         self.initialized = False


class VWParabolicSAR(BaseCustomVWIndicator):""

# Volume-Weighted Parabolic SAR.

# Enhanced Parabolic SAR with volume weighting for improved
# trend reversal detection.

# Mathematical Formula:
#     SAR[i] = SAR[i-1] + AF * (EP - SAR[i-1])
# Enhanced with volume-weighted acceleration factor adjustments."


#     def __init__(self, config: CustomVWIndicatorConfig):
#         super().__init__(config)
#         self.indicator_type = VWIndicatorType.TREND

        # Parabolic SAR parameters"
#         self.af_start = getattr(config, "af_start", 0.02)""
#         self.af_increment = getattr(config, "af_increment", 0.02)""
#         self.af_max = getattr(config, "af_max", 0.20)

        # Current state
#         self.sar = None
#         self.trend = None  # 1 for uptrend, -1 for downtrend
#         self.af = self.af_start
#         self.ep = None  # Extreme Point

        # Volume weighting
#         self.volume_ema = None
#         self.volume_alpha = 2.0 / (config.period + 1)

        # Historical values
#         self.sar_values = deque(maxlen=config.period)
#         self.trend_changes = deque(maxlen=10)

#         self.initialized = False

#     def _calculate_indicator_value(self, bar: Bar):
#         "Calculate Volume-Weighted Parabolic SAR."
#         high = bar.high.as_double()
#         low = bar.low.as_double()
#         close = bar.close.as_double()
#         volume = bar.volume.as_double()

        # Initialize volume EMA
#         if self.volume_ema is None:
#             self.volume_ema = volume
#         else:
#             self.volume_ema = (
#                 self.volume_alpha * volume + (1 - self.volume_alpha) * self.volume_ema
# )

        # Calculate volume weight
#         if self.volume_ema > 0:
#             volume_weight = volume / self.volume_ema
#         else:
#             volume_weight = 1.0

        # Initialize on first bar
#         if not self.initialized:
#             self.sar = low
#             self.trend = 1  # Start with uptrend
#             self.ep = high
#             self.af = self.af_start
#             self.initialized = True
#             self.sar_values.append(self.sar)
#             return self.sar

        # Calculate new SAR
#         new_sar = self.sar + self.af * (self.ep - self.sar)

        # Volume-weighted AF adjustment
#         volume_factor = min(2.0, max(0.5, volume_weight))
#         adjusted_af = self.af * volume_factor

        # Check for trend reversal
#         if self.trend == 1:  # Uptrend
            # Check if price breaks below SAR
#             if low <= new_sar:
                # Trend reversal to downtrend
#                 self.trend = -1
#                 self.sar = self.ep  # SAR becomes the previous EP
#                 self.ep = low
#                 self.af = self.af_start
#                 self.trend_changes.append(-1)
#             else:
                # Continue uptrend
#                 self.sar = new_sar
                # Update EP and AF if new high
#                 if high > self.ep:
#                     self.ep = high
#                     self.af = min(self.af + self.af_increment, self.af_max)

                # Ensure SAR doesn't go above previous two lows
#                 self.sar = min(self.sar, low)

#         else:  # Downtrend
            # Check if price breaks above SAR
#             if high >= new_sar:
                # Trend reversal to uptrend
#                 self.trend = 1
#                 self.sar = self.ep  # SAR becomes the previous EP
#                 self.ep = high
#                 self.af = self.af_start
#                 self.trend_changes.append(1)
#             else:
                # Continue downtrend
#                 self.sar = new_sar
                # Update EP and AF if new low
#                 if low < self.ep:
#                     self.ep = low
#                     self.af = min(self.af + self.af_increment, self.af_max)''
# '
                # Ensure SAR doesn't go below previous two highs
#                 self.sar = max(self.sar, high)

#         self.sar_values.append(self.sar)

#         return self.sar

#     def get_trend_direction(self):
#         "Get current trend direction."
#         if self.trend is None:
#             return None
# "
#         return "UPTREND" if self.trend == 1 else "DOWNTREND"

#     def get_reversal_strength(self):
#         "Get strength of recent trend reversals."
#         if len(self.trend_changes) < 3:
#             return None

#         recent_changes = len(self.trend_changes)
#         if recent_changes >= 5:""
#             return "HIGH_VOLATILITY"
#         elif recent_changes >= 3:""
#             return "MODERATE_VOLATILITY"
#         else:""
#             return "LOW_VOLATILITY"

#     def reset(self):
#         "Reset indicator state."
#         super().reset()
#         self.sar = None
#         self.trend = None
#         self.af = self.af_start
#         self.ep = None
#         self.volume_ema = None
#         self.sar_values.clear()
#         self.trend_changes.clear()
#         self.initialized = False


class VWAroon(BaseCustomVWIndicator):""

# Volume-Weighted Aroon Oscillator.

# Enhanced Aroon with volume weighting for improved trend
# identification and momentum analysis.

# Mathematical Formula:
#     Aroon_Up = ((period - periods_since_highest_high) / period) * 100
#     Aroon_Down = ((period - periods_since_lowest_low) / period) * 100
#     VW_Aroon = Aroon_Up - Aroon_Down
# Enhanced with volume-weighted high/low significance."


#     def __init__(self, config: CustomVWIndicatorConfig):
#         super().__init__(config)
#         self.indicator_type = VWIndicatorType.TREND

        # Historical data
#         self.highs = deque(maxlen=config.period)
#         self.lows = deque(maxlen=config.period)
#         self.volumes = deque(maxlen=config.period)

        # Volume weighting
#         self.volume_ema = None
#         self.volume_alpha = 2.0 / (config.period + 1)

        # Aroon values
#         self.aroon_up_values = deque(maxlen=config.period)
#         self.aroon_down_values = deque(maxlen=config.period)
#         self.aroon_oscillator_values = deque(maxlen=config.period)

#     def _calculate_indicator_value(self, bar: Bar):
#         "Calculate Volume-Weighted Aroon Oscillator."
#         high = bar.high.as_double()
#         low = bar.low.as_double()
#         volume = bar.volume.as_double()

        # Store values
#         self.highs.append(high)
#         self.lows.append(low)
#         self.volumes.append(volume)

        # Initialize volume EMA
#         if self.volume_ema is None:
#             self.volume_ema = volume
#         else:
#             self.volume_ema = (
#                 self.volume_alpha * volume + (1 - self.volume_alpha) * self.volume_ema
# )

        # Need enough data
#         if len(self.highs) < self.config.period:
#             return None

        # Find volume-weighted highest high and lowest low"
# max_high = -float("inf")"
#         min_low = float("inf")
#         max_high_idx = 0
#         min_low_idx = 0

#         highs_list = list(self.highs)
#         lows_list = list(self.lows)
#         volumes_list = list(self.volumes)

#         for i in range(len(highs_list)):
            # Volume weight for significance
# volume_weight = (
#                 volumes_list[i] / self.volume_ema if self.volume_ema > 0 else 1.0
# )

            # Weighted high and low
#             weighted_high = highs_list[i] * (1.0 + volume_weight * 0.1)
#             weighted_low = lows_list[i] * (1.0 - volume_weight * 0.1)

#             if weighted_high > max_high:
#                 max_high = weighted_high
#                 max_high_idx = i

#             if weighted_low < min_low:
#                 min_low = weighted_low
#                 min_low_idx = i

        # Calculate periods since highest high and lowest low
#         periods_since_high = len(highs_list) - 1 - max_high_idx
#         periods_since_low = len(lows_list) - 1 - min_low_idx

        # Calculate Aroon Up and Aroon Down
# aroon_up = (
#             (self.config.period - periods_since_high) / self.config.period
# ) * 100.0
# aroon_down = (
#             (self.config.period - periods_since_low) / self.config.period
# ) * 100.0

        # Calculate Aroon Oscillator
#         aroon_oscillator = aroon_up - aroon_down

        # Store values
#         self.aroon_up_values.append(aroon_up)
#         self.aroon_down_values.append(aroon_down)
#         self.aroon_oscillator_values.append(aroon_oscillator)

#         return aroon_oscillator

#     def get_aroon_components(self):
#         "Get Aroon Up and Aroon Down values."
#         if len(self.aroon_up_values) == 0 or len(self.aroon_down_values) == 0:
#             return None

#         return self.aroon_up_values[-1], self.aroon_down_values[-1]

#     def get_trend_signal(self):
#         "Get trend signal based on Aroon values."
#         components = self.get_aroon_components()
#         if components is None:
#             return None

#         aroon_up, aroon_down = components

#         if aroon_up > 70 and aroon_down < 30:""
#             return "STRONG_UPTREND"
#         elif aroon_down > 70 and aroon_up < 30:""
#             return "STRONG_DOWNTREND"
#         elif aroon_up > 50 and aroon_down < 50:""
#             return "UPTREND"
#         elif aroon_down > 50 and aroon_up < 50:""
#             return "DOWNTREND"
#         else:""
#             return "SIDEWAYS"

#     def reset(self):
#         "Reset indicator state."
#         super().reset()
#         self.highs.clear()
#         self.lows.clear()
#         self.volumes.clear()
#         self.volume_ema = None
#         self.aroon_up_values.clear()
#         self.aroon_down_values.clear()
#         self.aroon_oscillator_values.clear()


class VWCCI(BaseCustomVWIndicator):""

# Volume-Weighted Commodity Channel Index.

# Enhanced CCI with volume weighting for improved overbought/oversold
# detection and trend analysis.

# Mathematical Formula:
#     Typical_Price = (High + Low + Close) / 3
#     VW_SMA = SMA(Typical_Price * Volume_Weight)
#     Mean_Deviation = SMA(abs(Typical_Price - VW_SMA) * Volume_Weight)
# VW_CCI = (Typical_Price - VW_SMA) / (0.015 * Mean_Deviation)"


#     def __init__(self, config: CustomVWIndicatorConfig):
#         super().__init__(config)
#         self.indicator_type = VWIndicatorType.TREND

        # CCI constant"
#         self.cci_constant = getattr(config, "cci_constant", 0.015)

        # Historical data
#         self.typical_prices = deque(maxlen=config.period)
#         self.volume_weights = deque(maxlen=config.period)

        # Volume weighting
#         self.volume_ema = None
#         self.volume_alpha = 2.0 / (config.period + 1)

        # CCI values
#         self.cci_values = deque(maxlen=config.period)

#     def _calculate_indicator_value(self, bar: Bar):
#         "Calculate Volume-Weighted CCI."
#         high = bar.high.as_double()
#         low = bar.low.as_double()
#         close = bar.close.as_double()
#         volume = bar.volume.as_double()

        # Calculate typical price
#         typical_price = (high + low + close) / 3.0

        # Initialize volume EMA
#         if self.volume_ema is None:
#             self.volume_ema = volume
#         else:
#             self.volume_ema = (
#                 self.volume_alpha * volume + (1 - self.volume_alpha) * self.volume_ema
# )

        # Calculate volume weight
#         if self.volume_ema > 0:
#             volume_weight = volume / self.volume_ema
#         else:
#             volume_weight = 1.0

        # Store values
#         self.typical_prices.append(typical_price)
#         self.volume_weights.append(volume_weight)

        # Need enough data
#         if len(self.typical_prices) < self.config.period:
#             return None

        # Calculate volume-weighted SMA
# weighted_sum = sum(
# tp * vw for tp, vw in zip(self.typical_prices, self.volume_weights)
# )
#         weight_sum = sum(self.volume_weights)

#         if weight_sum == 0:
#             vw_sma = sum(self.typical_prices) / len(self.typical_prices)
#         else:
#             vw_sma = weighted_sum / weight_sum

        # Calculate volume-weighted mean deviation
#         deviations = []
#         for tp, vw in zip(self.typical_prices, self.volume_weights):
#             deviation = abs(tp - vw_sma) * vw
#             deviations.append(deviation)

#         mean_deviation = sum(deviations) / weight_sum if weight_sum > 0 else 0.0

        # Calculate CCI
#         if mean_deviation == 0:
#             cci = 0.0
#         else:
#             cci = (typical_price - vw_sma) / (self.cci_constant * mean_deviation)

#         self.cci_values.append(cci)

#         return cci

#     def get_signal_level(self):
#         "Get CCI signal level."
#         if self.value is None:
#             return None

#         if self.value > 200:""
#             return "EXTREMELY_OVERBOUGHT"
#         elif self.value > 100:""
#             return "OVERBOUGHT"
#         elif self.value < -200:""
#             return "EXTREMELY_OVERSOLD"
#         elif self.value < -100:""
#             return "OVERSOLD"
#         else:""
#             return "NEUTRAL"

#     def get_trend_signal(self):
#         "Get trend signal based on CCI."
#         if len(self.cci_values) < 5:
#             return None

#         recent_values = list(self.cci_values)[-5:]

#         if all(v > 0 for v in recent_values) and recent_values[-1] > recent_values[0]:""
#             return "BULLISH"
#         elif all(v < 0 for v in recent_values) and recent_values[-1] < recent_values[0]:""
#             return "BEARISH"
#         else:""
#             return "NEUTRAL"

#     def reset(self):
#         "Reset indicator state."
#         super().reset()
#         self.typical_prices.clear()
#         self.volume_weights.clear()
#         self.volume_ema = None
#         self.cci_values.clear()


# Configuration factory functions
# def create_vw_adx_config(
# period: int = 14, instrument_id=None, bar_type=None, **kwargs
# ) -> CustomVWIndicatorConfig:"
#     "Create configuration for VW ADX indicator."
#     return CustomVWIndicatorConfig(
# period=period, instrument_id=instrument_id, bar_type=bar_type, **kwargs
# )


# def create_vw_macd_histogram_config(
#     period: int = 26,
#     fast_period: int = 12,
#     slow_period: int = 26,
#     signal_period: int = 9,
#     instrument_id=None,
#     bar_type=None,
# **kwargs,
# ) -> CustomVWIndicatorConfig:"
#     "Create configuration for VW MACD Histogram indicator."
# config = CustomVWIndicatorConfig(
# period=period, instrument_id=instrument_id, bar_type=bar_type, **kwargs
# )
#     config.fast_period = fast_period
#     config.slow_period = slow_period
#     config.signal_period = signal_period
#     return config


# def create_vw_parabolic_sar_config(
#     period: int = 20,
#     af_start: float = 0.02,
#     af_increment: float = 0.02,
#     af_max: float = 0.20,
#     instrument_id=None,
#     bar_type=None,
# **kwargs,
# ) -> CustomVWIndicatorConfig:"
#     "Create configuration for VW Parabolic SAR indicator."
# config = CustomVWIndicatorConfig(
# period=period, instrument_id=instrument_id, bar_type=bar_type, **kwargs
# )
#     config.af_start = af_start
#     config.af_increment = af_increment
#     config.af_max = af_max
#     return config


# def create_vw_aroon_config(
# period: int = 14, instrument_id=None, bar_type=None, **kwargs
# ) -> CustomVWIndicatorConfig:"
#     "Create configuration for VW Aroon indicator."
#     return CustomVWIndicatorConfig(
# period=period, instrument_id=instrument_id, bar_type=bar_type, **kwargs
# )


# def create_vw_cci_config(
#     period: int = 20,
#     cci_constant: float = 0.015,
#     instrument_id=None,
#     bar_type=None,
# **kwargs,
# ) -> CustomVWIndicatorConfig:"
#     "Create configuration for VW CCI indicator."
# config = CustomVWIndicatorConfig(
# period=period, instrument_id=instrument_id, bar_type=bar_type, **kwargs
# )
#     config.cci_constant = cci_constant
#     return config
# "'"'