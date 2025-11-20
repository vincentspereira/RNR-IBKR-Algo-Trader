from collections import deque
from typing import Optional
import numpy as np
from nautilus_trader.model.data import Bar
# from .base_custom_vw_indicator import ()
"Volume-Weighted Simple Moving Average Variants."
# "
# This module implements 5 variants of Volume-Weighted Simple Moving Averages:
# 1. VW SMA (Close) - Standard volume-weighted SMA using closing prices
# 2. VW SMA (High) - Volume-weighted SMA using high prices
# 3. VW SMA (Low) - Volume-weighted SMA using low prices
# 4. VW SMA (Typical Price) - Volume-weighted SMA using (H+L+C)/3
# 5. VW SMA (Weighted Price) - Volume-weighted SMA using (H+L+2*C)/4
# "
# All indicators follow the institutional-grade 5-pillar architecture."




#     BaseCustomVWIndicator,
#     CustomVWIndicatorConfig,
#     VWIndicatorType,
# )


# "

class VWSMAClose(BaseCustomVWIndicator):""

# Volume-Weighted Simple Moving Average using closing prices.

# This is the standard VW SMA implementation that weights closing prices
# by their corresponding trading volumes, providing a more accurate
# representation of the average price paid by market participants.

# Mathematical Formula:
# VW_SMA = Σ(Close_i × Volume_i) / Σ(Volume_i)"


#     def __init__(self, config: CustomVWIndicatorConfig):
#         super().__init__(config)
#         self.indicator_type = VWIndicatorType.MOVING_AVERAGE
#         self.price_volume_sum = deque(maxlen=config.period)
#         self.volume_sum = deque(maxlen=config.period)

#     def _calculate_indicator_value(self, bar: Bar):
#         "Calculate VW SMA using closing prices."
#         close_price = bar.close.as_double()
#         volume = bar.volume.as_double()

        # Store price*volume and volume
#         self.price_volume_sum.append(close_price * volume)
#         self.volume_sum.append(volume)

        # Need at least period data points
#         if len(self.price_volume_sum) < self.config.period:
#             return None

        # Calculate volume-weighted average
#         total_price_volume = sum(self.price_volume_sum)
#         total_volume = sum(self.volume_sum)

#         if total_volume > 0:
#             return total_price_volume / total_volume
#         else:
            # Fallback to simple average if no volume
#             return sum(self.price_data[-self.config.period :]) / self.config.period

#     def reset(self):
#         "Reset indicator state."
#         super().reset()
#         self.price_volume_sum.clear()
#         self.volume_sum.clear()


class VWSMAHigh(BaseCustomVWIndicator):""

# Volume-Weighted Simple Moving Average using high prices.

# Uses the high price of each bar weighted by volume, useful for
# identifying resistance levels and upside momentum with volume confirmation.

# Mathematical Formula:
# VW_SMA_High = Σ(High_i × Volume_i) / Σ(Volume_i)"


#     def __init__(self, config: CustomVWIndicatorConfig):
#         super().__init__(config)
#         self.indicator_type = VWIndicatorType.MOVING_AVERAGE
#         self.price_volume_sum = deque(maxlen=config.period)
#         self.volume_sum = deque(maxlen=config.period)

#     def _calculate_indicator_value(self, bar: Bar):
#         "Calculate VW SMA using high prices."
#         high_price = bar.high.as_double()
#         volume = bar.volume.as_double()

        # Store price*volume and volume
#         self.price_volume_sum.append(high_price * volume)
#         self.volume_sum.append(volume)

        # Need at least period data points
#         if len(self.price_volume_sum) < self.config.period:
#             return None

        # Calculate volume-weighted average
#         total_price_volume = sum(self.price_volume_sum)
#         total_volume = sum(self.volume_sum)

#         if total_volume > 0:
#             return total_price_volume / total_volume
#         else:
            # Fallback to simple average if no volume
# recent_highs = [
# bar.high.as_double() for bar in self.price_data[-self.config.period :]
# ]
#             return sum(recent_highs) / len(recent_highs) if recent_highs else high_price

#     def reset(self):
#         "Reset indicator state."
#         super().reset()
#         self.price_volume_sum.clear()
#         self.volume_sum.clear()


class VWSMALow(BaseCustomVWIndicator):""

# Volume-Weighted Simple Moving Average using low prices.

# Uses the low price of each bar weighted by volume, useful for
# identifying support levels and downside pressure with volume confirmation.

# Mathematical Formula:
# VW_SMA_Low = Σ(Low_i × Volume_i) / Σ(Volume_i)"


#     def __init__(self, config: CustomVWIndicatorConfig):
#         super().__init__(config)
#         self.indicator_type = VWIndicatorType.MOVING_AVERAGE
#         self.price_volume_sum = deque(maxlen=config.period)
#         self.volume_sum = deque(maxlen=config.period)

#     def _calculate_indicator_value(self, bar: Bar):
#         "Calculate VW SMA using low prices."
#         low_price = bar.low.as_double()
#         volume = bar.volume.as_double()

        # Store price*volume and volume
#         self.price_volume_sum.append(low_price * volume)
#         self.volume_sum.append(volume)

        # Need at least period data points
#         if len(self.price_volume_sum) < self.config.period:
#             return None

        # Calculate volume-weighted average
#         total_price_volume = sum(self.price_volume_sum)
#         total_volume = sum(self.volume_sum)

#         if total_volume > 0:
#             return total_price_volume / total_volume
#         else:
            # Fallback to simple average if no volume
# recent_lows = [
# bar.low.as_double() for bar in self.price_data[-self.config.period :]
# ]
#             return sum(recent_lows) / len(recent_lows) if recent_lows else low_price

#     def reset(self):
#         "Reset indicator state."
#         super().reset()
#         self.price_volume_sum.clear()
#         self.volume_sum.clear()


class VWSMATypical(BaseCustomVWIndicator):""

# Volume-Weighted Simple Moving Average using typical price (HLC/3).

# Uses the typical price (High + Low + Close) / 3 weighted by volume,
# providing a balanced view of the average price action with volume emphasis.

# Mathematical Formula:
#     Typical_Price = (High + Low + Close) / 3
# VW_SMA_Typical = Σ(Typical_Price_i × Volume_i) / Σ(Volume_i)"


#     def __init__(self, config: CustomVWIndicatorConfig):
#         super().__init__(config)
#         self.indicator_type = VWIndicatorType.MOVING_AVERAGE
#         self.price_volume_sum = deque(maxlen=config.period)
#         self.volume_sum = deque(maxlen=config.period)

#     def _calculate_indicator_value(self, bar: Bar):
#         "Calculate VW SMA using typical price."
        # Calculate typical price (HLC/3)
# typical_price = (
#             bar.high.as_double() + bar.low.as_double() + bar.close.as_double()
# ) / 3.0

#         volume = bar.volume.as_double()

        # Store price*volume and volume
#         self.price_volume_sum.append(typical_price * volume)
#         self.volume_sum.append(volume)

        # Need at least period data points
#         if len(self.price_volume_sum) < self.config.period:
#             return None

        # Calculate volume-weighted average
#         total_price_volume = sum(self.price_volume_sum)
#         total_volume = sum(self.volume_sum)

#         if total_volume > 0:
#             return total_price_volume / total_volume
#         else:
            # Fallback to simple average if no volume
#             return typical_price

#     def reset(self):
#         "Reset indicator state."
#         super().reset()
#         self.price_volume_sum.clear()
#         self.volume_sum.clear()


class VWSMAWeighted(BaseCustomVWIndicator):""

# Volume-Weighted Simple Moving Average using weighted price (HLCC/4).

# Uses the weighted price (High + Low + Close + Close) / 4 weighted by volume,
# giving extra emphasis to the closing price while maintaining volume weighting.

# Mathematical Formula:
#     Weighted_Price = (High + Low + 2*Close) / 4
# VW_SMA_Weighted = Σ(Weighted_Price_i × Volume_i) / Σ(Volume_i)"


#     def __init__(self, config: CustomVWIndicatorConfig):
#         super().__init__(config)
#         self.indicator_type = VWIndicatorType.MOVING_AVERAGE
#         self.price_volume_sum = deque(maxlen=config.period)
#         self.volume_sum = deque(maxlen=config.period)

#     def _calculate_indicator_value(self, bar: Bar):
#         "Calculate VW SMA using weighted price."
        # Calculate weighted price (HLCC/4)
# weighted_price = (
#             bar.high.as_double() + bar.low.as_double() + 2 * bar.close.as_double()
# ) / 4.0

#         volume = bar.volume.as_double()

        # Store price*volume and volume
#         self.price_volume_sum.append(weighted_price * volume)
#         self.volume_sum.append(volume)

        # Need at least period data points
#         if len(self.price_volume_sum) < self.config.period:
#             return None

        # Calculate volume-weighted average
#         total_price_volume = sum(self.price_volume_sum)
#         total_volume = sum(self.volume_sum)

#         if total_volume > 0:
#             return total_price_volume / total_volume
#         else:
            # Fallback to simple average if no volume
#             return weighted_price

#     def reset(self):
#         "Reset indicator state."
#         super().reset()
#         self.price_volume_sum.clear()
#         self.volume_sum.clear()


# Configuration factory functions for easy setup
# def create_vw_sma_close_config(
# period: int = 20, instrument_id=None, bar_type=None, **kwargs
# ) -> CustomVWIndicatorConfig:"
#     "Create configuration for VW SMA Close indicator."
#     return CustomVWIndicatorConfig(
# period=period, instrument_id=instrument_id, bar_type=bar_type, **kwargs
# )


# def create_vw_sma_high_config(
# period: int = 20, instrument_id=None, bar_type=None, **kwargs
# ) -> CustomVWIndicatorConfig:"
#     "Create configuration for VW SMA High indicator."
#     return CustomVWIndicatorConfig(
# period=period, instrument_id=instrument_id, bar_type=bar_type, **kwargs
# )


# def create_vw_sma_low_config(
# period: int = 20, instrument_id=None, bar_type=None, **kwargs
# ) -> CustomVWIndicatorConfig:"
#     "Create configuration for VW SMA Low indicator."
#     return CustomVWIndicatorConfig(
# period=period, instrument_id=instrument_id, bar_type=bar_type, **kwargs
# )


# def create_vw_sma_typical_config(
# period: int = 20, instrument_id=None, bar_type=None, **kwargs
# ) -> CustomVWIndicatorConfig:"
#     "Create configuration for VW SMA Typical indicator."
#     return CustomVWIndicatorConfig(
# period=period, instrument_id=instrument_id, bar_type=bar_type, **kwargs
# )


# def create_vw_sma_weighted_config(
# period: int = 20, instrument_id=None, bar_type=None, **kwargs
# ) -> CustomVWIndicatorConfig:"
#     "Create configuration for VW SMA Weighted indicator."
#     return CustomVWIndicatorConfig(
# period=period, instrument_id=instrument_id, bar_type=bar_type, **kwargs
# )
# "