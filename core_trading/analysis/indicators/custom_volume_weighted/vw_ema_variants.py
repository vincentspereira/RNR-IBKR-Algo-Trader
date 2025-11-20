from collections import deque
from typing import Optional
import numpy as np
from nautilus_trader.model.data import Bar
# from .base_custom_vw_indicator import ()
"Volume-Weighted Exponential Moving Average Variants."
# "
# This module implements 5 variants of Volume-Weighted Exponential Moving Averages:
# 1. VW EMA (Close) - Standard volume-weighted EMA using closing prices
# 2. VW EMA (High) - Volume-weighted EMA using high prices
# 3. VW EMA (Low) - Volume-weighted EMA using low prices
# 4. VW EMA (Typical Price) - Volume-weighted EMA using (H+L+C)/3
# 5. VW EMA (Weighted Price) - Volume-weighted EMA using (H+L+2*C)/4
# "
# All indicators follow the institutional-grade 5-pillar architecture."




#     BaseCustomVWIndicator,
#     CustomVWIndicatorConfig,
#     VWIndicatorType,
# )


# "

class VWEMAClose(BaseCustomVWIndicator):""

# Volume-Weighted Exponential Moving Average using closing prices.

# This indicator combines the responsiveness of EMA with volume weighting,
# giving more weight to recent prices while considering volume significance.

# Mathematical Formula:
#     Alpha = 2 / (period + 1)
# VW_Price = (Close × Volume) / Volume_EMA
# VW_EMA = Alpha × VW_Price + (1 - Alpha) × Previous_VW_EMA"


#     def __init__(self, config: CustomVWIndicatorConfig):
#         super().__init__(config)
#         self.indicator_type = VWIndicatorType.MOVING_AVERAGE
#         self.alpha = 2.0 / (config.period + 1)
#         self.volume_ema = None
#         self.vw_ema = None
#         self.initialized = False

#     def _calculate_indicator_value(self, bar: Bar):
#         "Calculate VW EMA using closing prices."
#         close_price = bar.close.as_double()
#         volume = bar.volume.as_double()

        # Initialize on first bar
#         if not self.initialized:
#             self.volume_ema = volume
#             self.vw_ema = close_price
#             self.initialized = True
#             return self.vw_ema

        # Update volume EMA
#         self.volume_ema = self.alpha * volume + (1 - self.alpha) * self.volume_ema

        # Calculate volume-weighted price
#         if self.volume_ema > 0:
#             vw_price = (close_price * volume) / self.volume_ema
#         else:
#             vw_price = close_price

        # Update VW EMA
#         self.vw_ema = self.alpha * vw_price + (1 - self.alpha) * self.vw_ema

#         return self.vw_ema

#     def reset(self):
#         "Reset indicator state."
#         super().reset()
#         self.volume_ema = None
#         self.vw_ema = None
#         self.initialized = False


class VWEMAHigh(BaseCustomVWIndicator):""

# Volume-Weighted Exponential Moving Average using high prices.

# Uses high prices with volume weighting and exponential smoothing,
# excellent for tracking resistance levels with volume confirmation.

# Mathematical Formula:
#     Alpha = 2 / (period + 1)
# VW_Price = (High × Volume) / Volume_EMA
# VW_EMA_High = Alpha × VW_Price + (1 - Alpha) × Previous_VW_EMA_High"


#     def __init__(self, config: CustomVWIndicatorConfig):
#         super().__init__(config)
#         self.indicator_type = VWIndicatorType.MOVING_AVERAGE
#         self.alpha = 2.0 / (config.period + 1)
#         self.volume_ema = None
#         self.vw_ema = None
#         self.initialized = False

#     def _calculate_indicator_value(self, bar: Bar):
#         "Calculate VW EMA using high prices."
#         high_price = bar.high.as_double()
#         volume = bar.volume.as_double()

        # Initialize on first bar
#         if not self.initialized:
#             self.volume_ema = volume
#             self.vw_ema = high_price
#             self.initialized = True
#             return self.vw_ema

        # Update volume EMA
#         self.volume_ema = self.alpha * volume + (1 - self.alpha) * self.volume_ema

        # Calculate volume-weighted price
#         if self.volume_ema > 0:
#             vw_price = (high_price * volume) / self.volume_ema
#         else:
#             vw_price = high_price

        # Update VW EMA
#         self.vw_ema = self.alpha * vw_price + (1 - self.alpha) * self.vw_ema

#         return self.vw_ema

#     def reset(self):
#         "Reset indicator state."
#         super().reset()
#         self.volume_ema = None
#         self.vw_ema = None
#         self.initialized = False


class VWEMALow(BaseCustomVWIndicator):""

# Volume-Weighted Exponential Moving Average using low prices.

# Uses low prices with volume weighting and exponential smoothing,
# excellent for tracking support levels with volume confirmation.

# Mathematical Formula:
#     Alpha = 2 / (period + 1)
# VW_Price = (Low × Volume) / Volume_EMA
# VW_EMA_Low = Alpha × VW_Price + (1 - Alpha) × Previous_VW_EMA_Low"


#     def __init__(self, config: CustomVWIndicatorConfig):
#         super().__init__(config)
#         self.indicator_type = VWIndicatorType.MOVING_AVERAGE
#         self.alpha = 2.0 / (config.period + 1)
#         self.volume_ema = None
#         self.vw_ema = None
#         self.initialized = False

#     def _calculate_indicator_value(self, bar: Bar):
#         "Calculate VW EMA using low prices."
#         low_price = bar.low.as_double()
#         volume = bar.volume.as_double()

        # Initialize on first bar
#         if not self.initialized:
#             self.volume_ema = volume
#             self.vw_ema = low_price
#             self.initialized = True
#             return self.vw_ema

        # Update volume EMA
#         self.volume_ema = self.alpha * volume + (1 - self.alpha) * self.volume_ema

        # Calculate volume-weighted price
#         if self.volume_ema > 0:
#             vw_price = (low_price * volume) / self.volume_ema
#         else:
#             vw_price = low_price

        # Update VW EMA
#         self.vw_ema = self.alpha * vw_price + (1 - self.alpha) * self.vw_ema

#         return self.vw_ema

#     def reset(self):
#         "Reset indicator state."
#         super().reset()
#         self.volume_ema = None
#         self.vw_ema = None
#         self.initialized = False


class VWEMATypical(BaseCustomVWIndicator):""

# Volume-Weighted Exponential Moving Average using typical price (HLC/3).

# Uses typical price with volume weighting and exponential smoothing,
# providing a balanced and responsive trend indicator.

# Mathematical Formula:
#     Typical_Price = (High + Low + Close) / 3
#     Alpha = 2 / (period + 1)
# VW_Price = (Typical_Price × Volume) / Volume_EMA
# VW_EMA_Typical = Alpha × VW_Price + (1 - Alpha) × Previous_VW_EMA_Typical"


#     def __init__(self, config: CustomVWIndicatorConfig):
#         super().__init__(config)
#         self.indicator_type = VWIndicatorType.MOVING_AVERAGE
#         self.alpha = 2.0 / (config.period + 1)
#         self.volume_ema = None
#         self.vw_ema = None
#         self.initialized = False

#     def _calculate_indicator_value(self, bar: Bar):
#         "Calculate VW EMA using typical price."
        # Calculate typical price (HLC/3)
# typical_price = (
#             bar.high.as_double() + bar.low.as_double() + bar.close.as_double()
# ) / 3.0

#         volume = bar.volume.as_double()

        # Initialize on first bar
#         if not self.initialized:
#             self.volume_ema = volume
#             self.vw_ema = typical_price
#             self.initialized = True
#             return self.vw_ema

        # Update volume EMA
#         self.volume_ema = self.alpha * volume + (1 - self.alpha) * self.volume_ema

        # Calculate volume-weighted price
#         if self.volume_ema > 0:
#             vw_price = (typical_price * volume) / self.volume_ema
#         else:
#             vw_price = typical_price

        # Update VW EMA
#         self.vw_ema = self.alpha * vw_price + (1 - self.alpha) * self.vw_ema

#         return self.vw_ema

#     def reset(self):
#         "Reset indicator state."
#         super().reset()
#         self.volume_ema = None
#         self.vw_ema = None
#         self.initialized = False


class VWEMAWeighted(BaseCustomVWIndicator):""

# Volume-Weighted Exponential Moving Average using weighted price (HLCC/4).

# Uses weighted price with volume weighting and exponential smoothing,
# emphasizing closing prices while maintaining responsiveness.

# Mathematical Formula:
#     Weighted_Price = (High + Low + 2*Close) / 4
#     Alpha = 2 / (period + 1)
# VW_Price = (Weighted_Price × Volume) / Volume_EMA
# VW_EMA_Weighted = Alpha × VW_Price + (1 - Alpha) × Previous_VW_EMA_Weighted"


#     def __init__(self, config: CustomVWIndicatorConfig):
#         super().__init__(config)
#         self.indicator_type = VWIndicatorType.MOVING_AVERAGE
#         self.alpha = 2.0 / (config.period + 1)
#         self.volume_ema = None
#         self.vw_ema = None
#         self.initialized = False

#     def _calculate_indicator_value(self, bar: Bar):
#         "Calculate VW EMA using weighted price."
        # Calculate weighted price (HLCC/4)
# weighted_price = (
#             bar.high.as_double() + bar.low.as_double() + 2 * bar.close.as_double()
# ) / 4.0

#         volume = bar.volume.as_double()

        # Initialize on first bar
#         if not self.initialized:
#             self.volume_ema = volume
#             self.vw_ema = weighted_price
#             self.initialized = True
#             return self.vw_ema

        # Update volume EMA
#         self.volume_ema = self.alpha * volume + (1 - self.alpha) * self.volume_ema

        # Calculate volume-weighted price
#         if self.volume_ema > 0:
#             vw_price = (weighted_price * volume) / self.volume_ema
#         else:
#             vw_price = weighted_price

        # Update VW EMA
#         self.vw_ema = self.alpha * vw_price + (1 - self.alpha) * self.vw_ema

#         return self.vw_ema

#     def reset(self):
#         "Reset indicator state."
#         super().reset()
#         self.volume_ema = None
#         self.vw_ema = None
#         self.initialized = False


# Configuration factory functions for easy setup
# def create_vw_ema_close_config(
# period: int = 20, instrument_id=None, bar_type=None, **kwargs
# ) -> CustomVWIndicatorConfig:"
#     "Create configuration for VW EMA Close indicator."
#     return CustomVWIndicatorConfig(
# period=period, instrument_id=instrument_id, bar_type=bar_type, **kwargs
# )


# def create_vw_ema_high_config(
# period: int = 20, instrument_id=None, bar_type=None, **kwargs
# ) -> CustomVWIndicatorConfig:"
#     "Create configuration for VW EMA High indicator."
#     return CustomVWIndicatorConfig(
# period=period, instrument_id=instrument_id, bar_type=bar_type, **kwargs
# )


# def create_vw_ema_low_config(
# period: int = 20, instrument_id=None, bar_type=None, **kwargs
# ) -> CustomVWIndicatorConfig:"
#     "Create configuration for VW EMA Low indicator."
#     return CustomVWIndicatorConfig(
# period=period, instrument_id=instrument_id, bar_type=bar_type, **kwargs
# )


# def create_vw_ema_typical_config(
# period: int = 20, instrument_id=None, bar_type=None, **kwargs
# ) -> CustomVWIndicatorConfig:"
#     "Create configuration for VW EMA Typical indicator."
#     return CustomVWIndicatorConfig(
# period=period, instrument_id=instrument_id, bar_type=bar_type, **kwargs
# )


# def create_vw_ema_weighted_config(
# period: int = 20, instrument_id=None, bar_type=None, **kwargs
# ) -> CustomVWIndicatorConfig:"
#     "Create configuration for VW EMA Weighted indicator."
#     return CustomVWIndicatorConfig(
# period=period, instrument_id=instrument_id, bar_type=bar_type, **kwargs
# )
# "