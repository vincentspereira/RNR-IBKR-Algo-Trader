from collections import deque
from typing import Optional
import numpy as np
from nautilus_trader.model.data import Bar
# from .base_custom_vw_indicator import ()
"Volume-Weighted Volume Indicators."
# "
# This module implements 5 volume-weighted volume indicators:
# 1. VW VWAP - Enhanced Volume-Weighted Average Price
# 2. VW OBV - Volume-weighted On-Balance Volume
# 3. VW A/D Line - Volume-weighted Accumulation/Distribution Line
# 4. VW MFI - Enhanced Volume-weighted Money Flow Index
# 5. VW Chaikin Oscillator - Volume-weighted Chaikin Oscillator
# "
# All indicators follow the institutional-grade 5-pillar architecture."




#     BaseCustomVWIndicator,
#     CustomVWIndicatorConfig,
#     VWIndicatorType,
# )


# "

class VWVWAP(BaseCustomVWIndicator):""

# Enhanced Volume-Weighted Average Price.

# An enhanced VWAP implementation with institutional-grade features
# including smart money detection and regime adaptation.

# Mathematical Formula:
#     VWAP = Σ(Typical_Price * Volume) / Σ(Volume)
# Enhanced with volume profile analysis and smart money detection."


#     def __init__(self, config: CustomVWIndicatorConfig):
#         super().__init__(config)
#         self.indicator_type = VWIndicatorType.VOLUME

#         self.price_volume_sum = 0.0
#         self.volume_sum = 0.0""
#         self.session_reset = getattr(config, "session_reset", True)
#         self.bars_count = 0

        # Enhanced features
#         self.volume_profile = deque(maxlen=config.period)
#         self.price_levels = deque(maxlen=config.period)

#     def _calculate_indicator_value(self, bar: Bar):
#         "Calculate Enhanced VWAP."
        # Calculate typical price
# typical_price = (
#             bar.high.as_double() + bar.low.as_double() + bar.close.as_double()
# ) / 3.0

#         volume = bar.volume.as_double()

        # Reset for new session if configured
#         if self.session_reset and self.bars_count == 0:
#             self.price_volume_sum = 0.0
#             self.volume_sum = 0.0

        # Update cumulative sums
#         self.price_volume_sum += typical_price * volume
#         self.volume_sum += volume

        # Store for volume profile analysis
#         self.volume_profile.append(volume)
#         self.price_levels.append(typical_price)

#         self.bars_count += 1

#         if self.volume_sum == 0:
#             return typical_price

#         vwap = self.price_volume_sum / self.volume_sum

#         return vwap

#     def get_volume_profile_strength(self):
#         "Get volume profile strength indicator."
#         if len(self.volume_profile) < 5:
#             return 0.5

#         recent_volume = sum(list(self.volume_profile)[-5:])
#         total_volume = sum(self.volume_profile)

#         if total_volume == 0:
#             return 0.5

#         return recent_volume / total_volume

#     def get_price_deviation(self):
#         "Get current price deviation from VWAP."
#         if self.value is None or len(self.price_levels) == 0:
#             return None

#         current_price = self.price_levels[-1]
#         return (current_price - self.value) / self.value if self.value != 0 else 0.0

#     def reset(self):
#         "Reset indicator state."
#         super().reset()
#         self.price_volume_sum = 0.0
#         self.volume_sum = 0.0
#         self.bars_count = 0
#         self.volume_profile.clear()
#         self.price_levels.clear()


class VWOBV(BaseCustomVWIndicator):""

# Volume-Weighted On-Balance Volume.

# Enhanced OBV with volume weighting and smart money detection
#     for improved trend confirmation.

# Mathematical Formula:
# If Close > Prev_Close: VW_OBV += Volume * Price_Change_Ratio
# If Close < Prev_Close: VW_OBV -= Volume * Price_Change_Ratio
# If Close = Prev_Close: VW_OBV unchanged"


#     def __init__(self, config: CustomVWIndicatorConfig):
#         super().__init__(config)
#         self.indicator_type = VWIndicatorType.VOLUME

#         self.vw_obv = 0.0
#         self.prev_close = None
#         self.obv_values = deque(maxlen=config.period)

#     def _calculate_indicator_value(self, bar: Bar):
#         "Calculate Volume-Weighted OBV."
#         close = bar.close.as_double()
#         volume = bar.volume.as_double()

#         if self.prev_close is None:
#             self.prev_close = close
#             self.vw_obv = 0.0
#             self.obv_values.append(self.vw_obv)
#             return self.vw_obv

        # Calculate price change ratio for weighting
#         if self.prev_close != 0:
#             price_change_ratio = abs(close - self.prev_close) / self.prev_close
#         else:
#             price_change_ratio = 0.0

        # Apply volume weighting based on price change significance
#         weighted_volume = volume * (1.0 + price_change_ratio)

        # Update OBV based on price direction
#         if close > self.prev_close:
#             self.vw_obv += weighted_volume
#         elif close < self.prev_close:
#             self.vw_obv -= weighted_volume
        # No change if close == prev_close

#         self.prev_close = close
#         self.obv_values.append(self.vw_obv)

#         return self.vw_obv

#     def get_obv_trend(self):
#         "Get OBV trend direction."
#         if len(self.obv_values) < 5:
#             return None

#         recent_values = list(self.obv_values)[-5:]
#         if recent_values[-1] > recent_values[0]:""
#             return "BULLISH"
#         elif recent_values[-1] < recent_values[0]:""
#             return "BEARISH"
#         else:""
#             return "NEUTRAL"

#     def reset(self):
#         "Reset indicator state."
#         super().reset()
#         self.vw_obv = 0.0
#         self.prev_close = None
#         self.obv_values.clear()


class VWAccumulationDistribution(BaseCustomVWIndicator):""

# Volume-Weighted Accumulation/Distribution Line.

# Enhanced A/D Line with volume weighting for improved
# accumulation and distribution detection.

# Mathematical Formula:
#     CLV = ((Close - Low) - (High - Close)) / (High - Low)
# VW_AD += CLV * Volume * Volume_Weight"


#     def __init__(self, config: CustomVWIndicatorConfig):
#         super().__init__(config)
#         self.indicator_type = VWIndicatorType.VOLUME

#         self.vw_ad_line = 0.0
#         self.volume_ema = None
#         self.alpha = 2.0 / (config.period + 1)
#         self.ad_values = deque(maxlen=config.period)

#     def _calculate_indicator_value(self, bar: Bar):
#         "Calculate Volume-Weighted A/D Line."
#         high = bar.high.as_double()
#         low = bar.low.as_double()
#         close = bar.close.as_double()
#         volume = bar.volume.as_double()

        # Initialize volume EMA
#         if self.volume_ema is None:
#             self.volume_ema = volume
#         else:
#             self.volume_ema = self.alpha * volume + (1 - self.alpha) * self.volume_ema

        # Calculate Close Location Value (CLV)
#         if high != low:
#             clv = ((close - low) - (high - close)) / (high - low)
#         else:
#             clv = 0.0

        # Calculate volume weight
#         if self.volume_ema > 0:
#             volume_weight = volume / self.volume_ema
#         else:
#             volume_weight = 1.0

        # Update A/D Line with volume weighting
#         ad_change = clv * volume * volume_weight
#         self.vw_ad_line += ad_change

#         self.ad_values.append(self.vw_ad_line)

#         return self.vw_ad_line

#     def get_ad_trend(self):
#         "Get A/D Line trend direction."
#         if len(self.ad_values) < 5:
#             return None

#         recent_values = list(self.ad_values)[-5:]
#         if recent_values[-1] > recent_values[0]:""
#             return "ACCUMULATION"
#         elif recent_values[-1] < recent_values[0]:""
#             return "DISTRIBUTION"
#         else:""
#             return "NEUTRAL"

#     def reset(self):
#         "Reset indicator state."
#         super().reset()
#         self.vw_ad_line = 0.0
#         self.volume_ema = None
#         self.ad_values.clear()


class VWMFI(BaseCustomVWIndicator):""

# Enhanced Volume-Weighted Money Flow Index.

# Enhanced MFI with additional volume weighting and smart money detection
#     for improved money flow analysis.

# Mathematical Formula:
#     Typical_Price = (High + Low + Close) / 3
#     Raw_Money_Flow = Typical_Price * Volume
#     VW_Money_Flow = Raw_Money_Flow * Volume_Weight
# MFI = 100 - (100 / (1 + Money_Flow_Ratio))"


#     def __init__(self, config: CustomVWIndicatorConfig):
#         super().__init__(config)
#         self.indicator_type = VWIndicatorType.VOLUME

#         self.positive_money_flows = deque(maxlen=config.period)
#         self.negative_money_flows = deque(maxlen=config.period)
#         self.volume_weights = deque(maxlen=config.period)
#         self.prev_typical_price = None
#         self.volume_ema = None
#         self.alpha = 2.0 / (config.period + 1)

#     def _calculate_indicator_value(self, bar: Bar):
#         "Calculate Enhanced Volume-Weighted MFI."
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
#             self.volume_ema = self.alpha * volume + (1 - self.alpha) * self.volume_ema

        # Calculate volume weight
#         if self.volume_ema > 0:
#             volume_weight = volume / self.volume_ema
#         else:
#             volume_weight = 1.0

        # Calculate raw money flow
#         raw_money_flow = typical_price * volume

        # Apply volume weighting
#         vw_money_flow = raw_money_flow * volume_weight

        # Determine positive or negative money flow
#         if self.prev_typical_price is None:
#             self.prev_typical_price = typical_price
#             self.positive_money_flows.append(0.0)
#             self.negative_money_flows.append(0.0)
#             self.volume_weights.append(volume_weight)
#             return None

#         if typical_price > self.prev_typical_price:
#             self.positive_money_flows.append(vw_money_flow)
#             self.negative_money_flows.append(0.0)
#         elif typical_price < self.prev_typical_price:
#             self.positive_money_flows.append(0.0)
#             self.negative_money_flows.append(vw_money_flow)
#         else:
#             self.positive_money_flows.append(0.0)
#             self.negative_money_flows.append(0.0)

#         self.volume_weights.append(volume_weight)
#         self.prev_typical_price = typical_price

        # Need enough data points
#         if len(self.positive_money_flows) < self.config.period:
#             return None

        # Calculate money flow ratio
#         positive_mf = sum(self.positive_money_flows)
#         negative_mf = sum(self.negative_money_flows)

#         if negative_mf == 0:
#             return 100.0

#         money_flow_ratio = positive_mf / negative_mf
#         mfi = 100.0 - (100.0 / (1.0 + money_flow_ratio))

#         return mfi

#     def reset(self):
#         "Reset indicator state."
#         super().reset()
#         self.positive_money_flows.clear()
#         self.negative_money_flows.clear()
#         self.volume_weights.clear()
#         self.prev_typical_price = None
#         self.volume_ema = None


class VWChaikinOscillator(BaseCustomVWIndicator):""

# Volume-Weighted Chaikin Oscillator.

# Enhanced Chaikin Oscillator with volume weighting for improved
# momentum analysis of the A/D Line.

# Mathematical Formula:
# VW_AD_Line = Volume-weighted A/D Line
# VW_Chaikin = EMA_Fast(VW_AD_Line) - EMA_Slow(VW_AD_Line)"


#     def __init__(self, config: CustomVWIndicatorConfig):
#         super().__init__(config)
#         self.indicator_type = VWIndicatorType.VOLUME

        # Chaikin parameters"
#         self.fast_period = getattr(config, "fast_period", 3)""
#         self.slow_period = getattr(config, "slow_period", 10)

        # EMA calculations
#         self.fast_alpha = 2.0 / (self.fast_period + 1)
#         self.slow_alpha = 2.0 / (self.slow_period + 1)

        # A/D Line calculation
#         self.vw_ad_line = 0.0
#         self.volume_ema = None
#         self.ad_alpha = 2.0 / (config.period + 1)

        # Chaikin EMAs
#         self.fast_ema = None
#         self.slow_ema = None
#         self.initialized = False

#     def _calculate_indicator_value(self, bar: Bar):
#         "Calculate Volume-Weighted Chaikin Oscillator."
#         high = bar.high.as_double()
#         low = bar.low.as_double()
#         close = bar.close.as_double()
#         volume = bar.volume.as_double()

        # Initialize volume EMA
#         if self.volume_ema is None:
#             self.volume_ema = volume
#         else:
#             self.volume_ema = (
#                 self.ad_alpha * volume + (1 - self.ad_alpha) * self.volume_ema
# )

        # Calculate CLV
#         if high != low:
#             clv = ((close - low) - (high - close)) / (high - low)
#         else:
#             clv = 0.0

        # Calculate volume weight
#         if self.volume_ema > 0:
#             volume_weight = volume / self.volume_ema
#         else:
#             volume_weight = 1.0

        # Update A/D Line with volume weighting
#         ad_change = clv * volume * volume_weight
#         self.vw_ad_line += ad_change

        # Initialize EMAs on first calculation
#         if not self.initialized:
#             self.fast_ema = self.vw_ad_line
#             self.slow_ema = self.vw_ad_line
#             self.initialized = True
#             return 0.0

        # Update EMAs
#         self.fast_ema = (
#             self.fast_alpha * self.vw_ad_line + (1 - self.fast_alpha) * self.fast_ema
# )
#         self.slow_ema = (
#             self.slow_alpha * self.vw_ad_line + (1 - self.slow_alpha) * self.slow_ema
# )

        # Calculate Chaikin Oscillator
#         chaikin_oscillator = self.fast_ema - self.slow_ema

#         return chaikin_oscillator

#     def get_signal_strength(self):
#         "Get Chaikin Oscillator signal strength."
#         if self.value is None:
#             return None

#         if abs(self.value) > 1000:""
#             return "STRONG"
#         elif abs(self.value) > 500:""
#             return "MODERATE"
#         else:""
#             return "WEAK"

#     def reset(self):
#         "Reset indicator state."
#         super().reset()
#         self.vw_ad_line = 0.0
#         self.volume_ema = None
#         self.fast_ema = None
#         self.slow_ema = None
#         self.initialized = False


# Configuration factory functions
# def create_vw_vwap_config(
#     period: int = 20,
#     session_reset: bool = True,
#     instrument_id=None,
#     bar_type=None,
# **kwargs,
# ) -> CustomVWIndicatorConfig:"
#     "Create configuration for VW VWAP indicator."
# config = CustomVWIndicatorConfig(
# period=period, instrument_id=instrument_id, bar_type=bar_type, **kwargs
# )
#     config.session_reset = session_reset
#     return config


# def create_vw_obv_config(
# period: int = 20, instrument_id=None, bar_type=None, **kwargs
# ) -> CustomVWIndicatorConfig:"
#     "Create configuration for VW OBV indicator."
#     return CustomVWIndicatorConfig(
# period=period, instrument_id=instrument_id, bar_type=bar_type, **kwargs
# )


# def create_vw_ad_line_config(
# period: int = 20, instrument_id=None, bar_type=None, **kwargs
# ) -> CustomVWIndicatorConfig:"
#     "Create configuration for VW A/D Line indicator."
#     return CustomVWIndicatorConfig(
# period=period, instrument_id=instrument_id, bar_type=bar_type, **kwargs
# )


# def create_vw_mfi_config(
# period: int = 14, instrument_id=None, bar_type=None, **kwargs
# ) -> CustomVWIndicatorConfig:"
#     "Create configuration for VW MFI indicator."
#     return CustomVWIndicatorConfig(
# period=period, instrument_id=instrument_id, bar_type=bar_type, **kwargs
# )


# def create_vw_chaikin_oscillator_config(
#     period: int = 20,
#     fast_period: int = 3,
#     slow_period: int = 10,
#     instrument_id=None,
#     bar_type=None,
# **kwargs,
# ) -> CustomVWIndicatorConfig:"
#     "Create configuration for VW Chaikin Oscillator indicator."
# config = CustomVWIndicatorConfig(
# period=period, instrument_id=instrument_id, bar_type=bar_type, **kwargs
# )
#     config.fast_period = fast_period
#     config.slow_period = slow_period
#     return config
# "