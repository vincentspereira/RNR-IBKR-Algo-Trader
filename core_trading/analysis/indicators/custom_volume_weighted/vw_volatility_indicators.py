from collections import deque
from typing import Optional, Tuple
import numpy as np
from nautilus_trader.model.data import Bar
# from .base_custom_vw_indicator import ()
"Volume-Weighted Volatility Indicators."
# "
# This module implements 5 volume-weighted volatility indicators:
# 1. VW ATR - Volume-weighted Average True Range
# 2. VW Bollinger Bands - Volume-weighted Bollinger Bands
# 3. VW Keltner Channels - Volume-weighted Keltner Channels
# 4. VW Standard Deviation - Volume-weighted Standard Deviation
# 5. VW Volatility Index - Volume-weighted Volatility Index
# "
# All indicators follow the institutional-grade 5-pillar architecture."




#     BaseCustomVWIndicator,
#     CustomVWIndicatorConfig,
#     VWIndicatorType,
# )


# "

class VWATR(BaseCustomVWIndicator):""

# Volume-Weighted Average True Range.

# Applies volume weighting to ATR calculation for enhanced
# volatility measurement with volume confirmation.

# Mathematical Formula:
# TR = max(High - Low, |High - Prev_Close|, |Low - Prev_Close|)
#     VW_TR = TR * Volume
# VW_ATR = SMA(VW_TR) / SMA(Volume)"


#     def __init__(self, config: CustomVWIndicatorConfig):
#         super().__init__(config)
#         self.indicator_type = VWIndicatorType.VOLATILITY

#         self.vw_true_ranges = deque(maxlen=config.period)
#         self.volumes = deque(maxlen=config.period)
#         self.prev_close = None

#     def _calculate_indicator_value(self, bar: Bar):
#         "Calculate Volume-Weighted ATR."
#         high = bar.high.as_double()
#         low = bar.low.as_double()
#         close = bar.close.as_double()
#         volume = bar.volume.as_double()

        # Calculate True Range
#         if self.prev_close is None:
#             true_range = high - low
#         else:
# true_range = max(
#                 high - low, abs(high - self.prev_close), abs(low - self.prev_close)
# )

#         self.prev_close = close

        # Calculate volume-weighted true range
#         vw_true_range = true_range * volume

#         self.vw_true_ranges.append(vw_true_range)
#         self.volumes.append(volume)

        # Need enough data points
#         if len(self.vw_true_ranges) < self.config.period:
#             return None

        # Calculate VW ATR
#         total_vw_tr = sum(self.vw_true_ranges)
#         total_volume = sum(self.volumes)

#         if total_volume == 0:
#             return true_range  # Fallback to regular TR

#         vw_atr = total_vw_tr / total_volume

#         return vw_atr

#     def reset(self):
#         "Reset indicator state."
#         super().reset()
#         self.vw_true_ranges.clear()
#         self.volumes.clear()
#         self.prev_close = None


class VWBollingerBands(BaseCustomVWIndicator):""

# Volume-Weighted Bollinger Bands.

# Applies volume weighting to Bollinger Bands calculation for enhanced
# volatility bands with volume confirmation.

# Mathematical Formula:
#     VW_SMA = Σ(Price * Volume) / Σ(Volume)
# VW_StdDev = sqrt(Σ((Price - VW_SMA)² * Volume) / Σ(Volume))
#     Upper_Band = VW_SMA + (multiplier * VW_StdDev)
# Lower_Band = VW_SMA - (multiplier * VW_StdDev)"


#     def __init__(self, config: CustomVWIndicatorConfig):
#         super().__init__(config)
#         self.indicator_type = VWIndicatorType.VOLATILITY
# "
#         self.multiplier = getattr(config, "multiplier", 2.0)
#         self.prices = deque(maxlen=config.period)
#         self.volumes = deque(maxlen=config.period)

#         self.upper_band = None
#         self.lower_band = None
#         self.middle_band = None

#     def _calculate_indicator_value(self, bar: Bar):
#         "Calculate Volume-Weighted Bollinger Bands middle line."
#         price = bar.close.as_double()
#         volume = bar.volume.as_double()

#         self.prices.append(price)
#         self.volumes.append(volume)

        # Need enough data points
#         if len(self.prices) < self.config.period:
#             return None

        # Calculate volume-weighted SMA (middle band)
#         total_price_volume = sum(p * v for p, v in zip(self.prices, self.volumes))
#         total_volume = sum(self.volumes)

#         if total_volume == 0:
#             self.middle_band = sum(self.prices) / len(self.prices)
#         else:
#             self.middle_band = total_price_volume / total_volume

        # Calculate volume-weighted standard deviation
#         if total_volume == 0:
# variance = sum((p - self.middle_band) ** 2 for p in self.prices) / len(
#                 self.prices
# )
#         else:
# variance = (
# sum(
#                     ((p - self.middle_band) ** 2) * v
#                     for p, v in zip(self.prices, self.volumes)
# )
# / total_volume
# )

#         vw_std_dev = np.sqrt(variance)

        # Calculate bands
#         self.upper_band = self.middle_band + (self.multiplier * vw_std_dev)
#         self.lower_band = self.middle_band - (self.multiplier * vw_std_dev)

#         return self.middle_band

#     def get_upper_band(self):
#         "Get the upper Bollinger Band."
#         return self.upper_band

#     def get_lower_band(self):
#         "Get the lower Bollinger Band."
#         return self.lower_band

#     def get_bandwidth(self):
#         "Get the Bollinger Band width."
#         if (
#             self.upper_band is None
# or self.lower_band is None
# or self.middle_band is None
# ):
#             return None
#         if self.middle_band == 0:
#             return None
#         return (self.upper_band - self.lower_band) / self.middle_band

#     def reset(self):
#         "Reset indicator state."
#         super().reset()
#         self.prices.clear()
#         self.volumes.clear()
#         self.upper_band = None
#         self.lower_band = None
#         self.middle_band = None


class VWKeltnerChannels(BaseCustomVWIndicator):""

# Volume-Weighted Keltner Channels.

# Applies volume weighting to Keltner Channels calculation for enhanced
# volatility channels with volume confirmation.

# Mathematical Formula:
# VW_EMA = Volume-weighted EMA of price
# VW_ATR = Volume-weighted ATR
#     Upper_Channel = VW_EMA + (multiplier * VW_ATR)
# Lower_Channel = VW_EMA - (multiplier * VW_ATR)"


#     def __init__(self, config: CustomVWIndicatorConfig):
#         super().__init__(config)
#         self.indicator_type = VWIndicatorType.VOLATILITY
# "
#         self.multiplier = getattr(config, "multiplier", 2.0)""
#         self.atr_period = getattr(config, "atr_period", config.period)

        # EMA calculation
#         self.alpha = 2.0 / (config.period + 1)
#         self.vw_ema = None
#         self.volume_ema = None

        # ATR calculation
#         self.vw_true_ranges = deque(maxlen=self.atr_period)
#         self.atr_volumes = deque(maxlen=self.atr_period)
#         self.prev_close = None

#         self.upper_channel = None
#         self.lower_channel = None
#         self.initialized = False

#     def _calculate_indicator_value(self, bar: Bar):
#         "Calculate Volume-Weighted Keltner Channels middle line."
#         price = bar.close.as_double()
#         high = bar.high.as_double()
#         low = bar.low.as_double()
#         volume = bar.volume.as_double()

        # Initialize on first bar
#         if not self.initialized:
#             self.vw_ema = price
#             self.volume_ema = volume
#             self.prev_close = price
#             self.initialized = True
#             return self.vw_ema

        # Update volume EMA
#         self.volume_ema = self.alpha * volume + (1 - self.alpha) * self.volume_ema

        # Calculate volume-weighted price
#         if self.volume_ema > 0:
#             vw_price = (price * volume) / self.volume_ema
#         else:
#             vw_price = price

        # Update VW EMA
#         self.vw_ema = self.alpha * vw_price + (1 - self.alpha) * self.vw_ema

        # Calculate True Range for ATR
# true_range = max(
#             high - low, abs(high - self.prev_close), abs(low - self.prev_close)
# )

#         self.prev_close = price

        # Calculate volume-weighted true range
#         vw_true_range = true_range * volume

#         self.vw_true_ranges.append(vw_true_range)
#         self.atr_volumes.append(volume)

        # Calculate VW ATR
#         if len(self.vw_true_ranges) >= self.atr_period:
#             total_vw_tr = sum(self.vw_true_ranges)
#             total_atr_volume = sum(self.atr_volumes)

#             if total_atr_volume > 0:
#                 vw_atr = total_vw_tr / total_atr_volume
#             else:
#                 vw_atr = true_range

            # Calculate channels
#             self.upper_channel = self.vw_ema + (self.multiplier * vw_atr)
#             self.lower_channel = self.vw_ema - (self.multiplier * vw_atr)

#         return self.vw_ema

#     def get_upper_channel(self):
#         "Get the upper Keltner Channel."
#         return self.upper_channel

#     def get_lower_channel(self):
#         "Get the lower Keltner Channel."
#         return self.lower_channel

#     def reset(self):
#         "Reset indicator state."
#         super().reset()
#         self.vw_ema = None
#         self.volume_ema = None
#         self.vw_true_ranges.clear()
#         self.atr_volumes.clear()
#         self.prev_close = None
#         self.upper_channel = None
#         self.lower_channel = None
#         self.initialized = False


class VWStandardDeviation(BaseCustomVWIndicator):""

# Volume-Weighted Standard Deviation.

# Calculates standard deviation with volume weighting for enhanced
# volatility measurement with volume confirmation.

# Mathematical Formula:
#     VW_Mean = Σ(Price * Volume) / Σ(Volume)
# VW_StdDev = sqrt(Σ((Price - VW_Mean)² * Volume) / Σ(Volume))"


#     def __init__(self, config: CustomVWIndicatorConfig):
#         super().__init__(config)
#         self.indicator_type = VWIndicatorType.VOLATILITY

#         self.prices = deque(maxlen=config.period)
#         self.volumes = deque(maxlen=config.period)

#     def _calculate_indicator_value(self, bar: Bar):
#         "Calculate Volume-Weighted Standard Deviation."
#         price = bar.close.as_double()
#         volume = bar.volume.as_double()

#         self.prices.append(price)
#         self.volumes.append(volume)

        # Need enough data points
#         if len(self.prices) < self.config.period:
#             return None

        # Calculate volume-weighted mean
#         total_price_volume = sum(p * v for p, v in zip(self.prices, self.volumes))
#         total_volume = sum(self.volumes)

#         if total_volume == 0:
            # Fallback to regular standard deviation
#             mean = sum(self.prices) / len(self.prices)
#             variance = sum((p - mean) ** 2 for p in self.prices) / len(self.prices)
#         else:
#             vw_mean = total_price_volume / total_volume

            # Calculate volume-weighted variance
# variance = (
#                 sum(((p - vw_mean) ** 2) * v for p, v in zip(self.prices, self.volumes))
# / total_volume
# )

#         vw_std_dev = np.sqrt(variance)

#         return vw_std_dev

#     def reset(self):
#         "Reset indicator state."
#         super().reset()
#         self.prices.clear()
#         self.volumes.clear()


class VWVolatilityIndex(BaseCustomVWIndicator):""

# Volume-Weighted Volatility Index.

# Custom volatility index that combines multiple volatility measures
#     with volume weighting for comprehensive volatility assessment.

# Mathematical Formula:
# VW_Returns = Volume-weighted returns
#     VW_ATR_Normalized = VW_ATR / VW_Price
# VW_Vol_Index = (VW_StdDev + VW_ATR_Normalized) / 2 * 100"


#     def __init__(self, config: CustomVWIndicatorConfig):
#         super().__init__(config)
#         self.indicator_type = VWIndicatorType.VOLATILITY

#         self.prices = deque(maxlen=config.period)
#         self.volumes = deque(maxlen=config.period)
#         self.vw_true_ranges = deque(maxlen=config.period)
#         self.prev_close = None

#     def _calculate_indicator_value(self, bar: Bar):
#         "Calculate Volume-Weighted Volatility Index."
#         high = bar.high.as_double()
#         low = bar.low.as_double()
#         close = bar.close.as_double()
#         volume = bar.volume.as_double()

#         self.prices.append(close)
#         self.volumes.append(volume)

        # Calculate True Range
#         if self.prev_close is None:
#             true_range = high - low
#         else:
# true_range = max(
#                 high - low, abs(high - self.prev_close), abs(low - self.prev_close)
# )

#         self.prev_close = close

        # Calculate volume-weighted true range
#         vw_true_range = true_range * volume
#         self.vw_true_ranges.append(vw_true_range)

        # Need enough data points
#         if len(self.prices) < self.config.period:
#             return None

        # Calculate volume-weighted mean price
#         total_price_volume = sum(p * v for p, v in zip(self.prices, self.volumes))
#         total_volume = sum(self.volumes)

#         if total_volume == 0:
#             return 0.0

#         vw_mean_price = total_price_volume / total_volume

        # Calculate volume-weighted standard deviation
# variance = (
# sum(
#                 ((p - vw_mean_price) ** 2) * v
#                 for p, v in zip(self.prices, self.volumes)
# )
# / total_volume
# )

#         vw_std_dev = np.sqrt(variance)

        # Calculate volume-weighted ATR
#         total_vw_tr = sum(self.vw_true_ranges)
#         vw_atr = total_vw_tr / total_volume

        # Normalize ATR by price
#         if vw_mean_price > 0:
#             vw_atr_normalized = vw_atr / vw_mean_price
#         else:
#             vw_atr_normalized = 0.0

        # Combine measures into volatility index
# vw_volatility_index = (
#             ((vw_std_dev / vw_mean_price) + vw_atr_normalized) / 2.0 * 100.0
# )

#         return vw_volatility_index

#     def reset(self):
#         "Reset indicator state."
#         super().reset()
#         self.prices.clear()
#         self.volumes.clear()
#         self.vw_true_ranges.clear()
#         self.prev_close = None


# Configuration factory functions
# def create_vw_atr_config(
# period: int = 14, instrument_id=None, bar_type=None, **kwargs
# ) -> CustomVWIndicatorConfig:"
#     "Create configuration for VW ATR indicator."
#     return CustomVWIndicatorConfig(
# period=period, instrument_id=instrument_id, bar_type=bar_type, **kwargs
# )


# def create_vw_bollinger_bands_config(
#     period: int = 20,
#     multiplier: float = 2.0,
#     instrument_id=None,
#     bar_type=None,
# **kwargs,
# ) -> CustomVWIndicatorConfig:"
#     "Create configuration for VW Bollinger Bands indicator."
# config = CustomVWIndicatorConfig(
# period=period, instrument_id=instrument_id, bar_type=bar_type, **kwargs
# )
#     config.multiplier = multiplier
#     return config


# def create_vw_keltner_channels_config(
#     period: int = 20,
#     atr_period: int = 14,
#     multiplier: float = 2.0,
#     instrument_id=None,
#     bar_type=None,
# **kwargs,
# ) -> CustomVWIndicatorConfig:"
#     "Create configuration for VW Keltner Channels indicator."
# config = CustomVWIndicatorConfig(
# period=period, instrument_id=instrument_id, bar_type=bar_type, **kwargs
# )
#     config.atr_period = atr_period
#     config.multiplier = multiplier
#     return config


# def create_vw_std_dev_config(
# period: int = 20, instrument_id=None, bar_type=None, **kwargs
# ) -> CustomVWIndicatorConfig:"
#     "Create configuration for VW Standard Deviation indicator."
#     return CustomVWIndicatorConfig(
# period=period, instrument_id=instrument_id, bar_type=bar_type, **kwargs
# )


# def create_vw_volatility_index_config(
# period: int = 20, instrument_id=None, bar_type=None, **kwargs
# ) -> CustomVWIndicatorConfig:"
#     "Create configuration for VW Volatility Index indicator."
#     return CustomVWIndicatorConfig(
# period=period, instrument_id=instrument_id, bar_type=bar_type, **kwargs
# )
# "