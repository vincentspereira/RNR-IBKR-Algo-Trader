from collections import deque
from typing import Dict, List, Optional, Tuple
import numpy as np
from nautilus_trader.model.data import Bar
from scipy import stats
# from .base_custom_vw_indicator import ()
"Volume-Weighted Statistical Indicators."
# "
# This module implements 4 volume-weighted statistical indicators:
# 1. VW Z-Score - Volume-weighted Z-Score for mean reversion
# 2. VW Correlation - Volume-weighted correlation analysis
# 3. VW Regression - Volume-weighted linear regression
# 4. VW Percentile Rank - Volume-weighted percentile ranking
# "
# All indicators follow the institutional-grade 5-pillar architecture."




#     BaseCustomVWIndicator,
#     CustomVWIndicatorConfig,
#     VWIndicatorType,
# )


# "

class VWZScore(BaseCustomVWIndicator):""

# Volume-Weighted Z-Score.

# Enhanced Z-Score calculation with volume weighting for improved
# mean reversion signal identification.

# Mathematical Formula:
#     VW_Mean = Σ(Price * Volume) / Σ(Volume)
# VW_StdDev = √(Σ(Volume * (Price - VW_Mean)²) / Σ(Volume))
# VW_Z_Score = (Current_Price - VW_Mean) / VW_StdDev"


#     def __init__(self, config: CustomVWIndicatorConfig):
#         super().__init__(config)
#         self.indicator_type = VWIndicatorType.STATISTICAL

        # Z-Score parameters"
#         self.price_type = getattr(""
#             config, "price_type", "close"
# )  # close, typical, weighted

        # Historical data
#         self.prices = deque(maxlen=config.period)
#         self.volumes = deque(maxlen=config.period)

        # Statistical values
#         self.vw_mean = None
#         self.vw_std_dev = None
#         self.z_score = None

        # Z-Score history for analysis
#         self.z_score_history = deque(maxlen=config.period)

        # Volume weighting
#         self.volume_ema = None
#         self.volume_alpha = 2.0 / (config.period + 1)

#     def _calculate_indicator_value(self, bar: Bar):
# "Calculate Volume-Weighted Z-Score.
        # Get price based on type"
#         if self.price_type == "typical":
# price = (
#                 bar.high.as_double() + bar.low.as_double() + bar.close.as_double()
# ) / 3.0"
#         elif self.price_type == "weighted":
# price = (
#                 bar.high.as_double() + bar.low.as_double() + 2 * bar.close.as_double()
# ) / 4.0
#         else:  # close
#             price = bar.close.as_double()

#         volume = bar.volume.as_double()

        # Store data
#         self.prices.append(price)
#         self.volumes.append(volume)

        # Initialize volume EMA
#         if self.volume_ema is None:
#             self.volume_ema = volume
#         else:
#             self.volume_ema = (
#                 self.volume_alpha * volume + (1 - self.volume_alpha) * self.volume_ema
# )

        # Need enough data
#         if len(self.prices) < self.config.period:
#             return None

        # Calculate volume-weighted mean
#         total_volume = sum(self.volumes)
#         if total_volume == 0:
#             return None

#         self.vw_mean = (
#             sum(p * v for p, v in zip(self.prices, self.volumes)) / total_volume
# )

        # Calculate volume-weighted standard deviation
# variance_sum = sum(
# v * (p - self.vw_mean) ** 2 for p, v in zip(self.prices, self.volumes)
# )
#         self.vw_std_dev = np.sqrt(variance_sum / total_volume)

        # Calculate Z-Score
#         if self.vw_std_dev != 0:
#             self.z_score = (price - self.vw_mean) / self.vw_std_dev
#         else:
#             self.z_score = 0.0

        # Store in history
#         self.z_score_history.append(self.z_score)

#         return self.z_score

#     def get_z_score_signal(self):
#         "Get Z-Score based signal."
#         if self.z_score is None:
#             return None

        # Standard Z-Score thresholds"
#         if self.z_score > 2.0:""
#             return "EXTREMELY_OVERBOUGHT"
#         elif self.z_score > 1.5:""
#             return "OVERBOUGHT"
#         elif self.z_score > 0.5:""
#             return "SLIGHTLY_OVERBOUGHT"
#         elif self.z_score < -2.0:""
#             return "EXTREMELY_OVERSOLD"
#         elif self.z_score < -1.5:""
#             return "OVERSOLD"
#         elif self.z_score < -0.5:""
#             return "SLIGHTLY_OVERSOLD"
#         else:""
#             return "NEUTRAL"

#     def get_mean_reversion_probability(self):
#         "Get probability of mean reversion based on Z-Score."
#         if self.z_score is None:
#             return None

        # Use normal distribution CDF to estimate probability
        # Higher absolute Z-Score = higher probability of reversion
#         abs_z = abs(self.z_score)

#         if abs_z > 3.0:
#             return 0.95
#         elif abs_z > 2.5:
#             return 0.85
#         elif abs_z > 2.0:
#             return 0.75
#         elif abs_z > 1.5:
#             return 0.60
#         elif abs_z > 1.0:
#             return 0.40
#         else:
#             return 0.20

#     def get_z_score_trend(self):
#         "Get Z-Score trend direction."
#         if len(self.z_score_history) < 3:
#             return None

#         recent_scores = list(self.z_score_history)[-3:]

#         if recent_scores[-1] > recent_scores[-2] > recent_scores[-3]:""
#             return "INCREASING"
#         elif recent_scores[-1] < recent_scores[-2] < recent_scores[-3]:""
#             return "DECREASING"
#         else:""
#             return "SIDEWAYS"

#     def reset(self):
#         "Reset indicator state."
#         super().reset()
#         self.prices.clear()
#         self.volumes.clear()
#         self.vw_mean = None
#         self.vw_std_dev = None
#         self.z_score = None
#         self.z_score_history.clear()
#         self.volume_ema = None


class VWCorrelation(BaseCustomVWIndicator):""

# Volume-Weighted Correlation.

# Enhanced correlation analysis with volume weighting for improved
# relationship identification between price and volume or other metrics.

# Mathematical Formula:
# VW_Correlation = Σ(Volume * (X - X̄) * (Y - Ȳ)) /
# √(Σ(Volume * (X - X̄)²) * Σ(Volume * (Y - Ȳ)²))"


#     def __init__(self, config: CustomVWIndicatorConfig):
#         super().__init__(config)
#         self.indicator_type = VWIndicatorType.STATISTICAL

        # Correlation parameters"
#         self.correlation_type = getattr(config, "correlation_type", "price_volume")
        # Options: 'price_volume', 'price_returns', 'volume_returns'

        # Historical data
#         self.x_values = deque(maxlen=config.period)
#         self.y_values = deque(maxlen=config.period)
#         self.volumes = deque(maxlen=config.period)

        # Previous values for returns calculation
#         self.prev_price = None
#         self.prev_volume = None

        # Correlation values
#         self.correlation = None
#         self.correlation_history = deque(maxlen=config.period)

        # Volume weighting
#         self.volume_ema = None
#         self.volume_alpha = 2.0 / (config.period + 1)

#     def _calculate_indicator_value(self, bar: Bar):
#         "Calculate Volume-Weighted Correlation."
#         price = bar.close.as_double()
#         volume = bar.volume.as_double()

        # Initialize volume EMA
#         if self.volume_ema is None:
#             self.volume_ema = volume
#         else:
#             self.volume_ema = (
#                 self.volume_alpha * volume + (1 - self.volume_alpha) * self.volume_ema
# )

        # Prepare X and Y values based on correlation type
#         x_val, y_val = self._get_correlation_values(bar)

#         if x_val is None or y_val is None:
#             return None

        # Store data
#         self.x_values.append(x_val)
#         self.y_values.append(y_val)
#         self.volumes.append(volume)

        # Need enough data
#         if len(self.x_values) < self.config.period:
#             return None

        # Calculate volume-weighted correlation
#         self.correlation = self._calculate_vw_correlation()

        # Store in history
#         if self.correlation is not None:
#             self.correlation_history.append(self.correlation)

#         return self.correlation

#     def _get_correlation_values(
# self, bar: Bar
# ) -> Tuple[Optional[float], Optional[float]]:"
#         "Get X and Y values based on correlation type."
#         price = bar.close.as_double()
#         volume = bar.volume.as_double()
# "
#         if self.correlation_type == "price_volume":
#             return price, volume
# "
#         elif self.correlation_type == "price_returns":
#             if self.prev_price is None:
#                 self.prev_price = price
#                 return None, None

#             price_return = (price - self.prev_price) / self.prev_price
#             self.prev_price = price
#             return price_return, volume
# "
#         elif self.correlation_type == "volume_returns":
#             if self.prev_price is None or self.prev_volume is None:
#                 self.prev_price = price
#                 self.prev_volume = volume
#                 return None, None

#             price_return = (price - self.prev_price) / self.prev_price
# volume_return = (
#                 (volume - self.prev_volume) / self.prev_volume
#                 if self.prev_volume != 0
# else 0
# )

#             self.prev_price = price
#             self.prev_volume = volume
#             return price_return, volume_return

#         return None, None

#     def _calculate_vw_correlation(self):
#         "Calculate volume-weighted correlation coefficient."
#         if len(self.x_values) < 2:
#             return None

#         x_vals = list(self.x_values)
#         y_vals = list(self.y_values)
#         volumes = list(self.volumes)

        # Calculate volume-weighted means
#         total_volume = sum(volumes)
#         if total_volume == 0:
#             return None

#         x_mean = sum(x * v for x, v in zip(x_vals, volumes)) / total_volume
#         y_mean = sum(y * v for y, v in zip(y_vals, volumes)) / total_volume

        # Calculate volume-weighted covariance and variances
# covariance = sum(
# v * (x - x_mean) * (y - y_mean) for x, y, v in zip(x_vals, y_vals, volumes)
# )
#         x_variance = sum(v * (x - x_mean) ** 2 for x, v in zip(x_vals, volumes))
#         y_variance = sum(v * (y - y_mean) ** 2 for y, v in zip(y_vals, volumes))

        # Calculate correlation
#         denominator = np.sqrt(x_variance * y_variance)
#         if denominator == 0:
#             return 0.0

#         correlation = covariance / denominator

        # Ensure correlation is within [-1, 1]
#         return max(-1.0, min(1.0, correlation))

#     def get_correlation_strength(self):
#         "Get correlation strength classification."
#         if self.correlation is None:
#             return None

#         abs_corr = abs(self.correlation)

#         if abs_corr >= 0.8:""
#             return "VERY_STRONG"
#         elif abs_corr >= 0.6:""
#             return "STRONG"
#         elif abs_corr >= 0.4:""
#             return "MODERATE"
#         elif abs_corr >= 0.2:""
#             return "WEAK"
#         else:""
#             return "VERY_WEAK"

#     def get_correlation_direction(self):
#         "Get correlation direction."
#         if self.correlation is None:
#             return None

#         if self.correlation > 0.1:""
#             return "POSITIVE"
#         elif self.correlation < -0.1:""
#             return "NEGATIVE"
#         else:""
#             return "NEUTRAL"

#     def get_correlation_stability(self):
#         "Get correlation stability over time."
#         if len(self.correlation_history) < 10:
#             return None

#         recent_correlations = list(self.correlation_history)[-10:]
#         correlation_std = np.std(recent_correlations)

#         if correlation_std < 0.1:""
#             return "VERY_STABLE"
#         elif correlation_std < 0.2:""
#             return "STABLE"
#         elif correlation_std < 0.3:""
#             return "MODERATE"
#         else:""
#             return "UNSTABLE"

#     def reset(self):
#         "Reset indicator state."
#         super().reset()
#         self.x_values.clear()
#         self.y_values.clear()
#         self.volumes.clear()
#         self.prev_price = None
#         self.prev_volume = None
#         self.correlation = None
#         self.correlation_history.clear()
#         self.volume_ema = None


class VWRegression(BaseCustomVWIndicator):""

# Volume-Weighted Linear Regression.

# Enhanced linear regression with volume weighting for improved
# trend analysis and price prediction.

# Mathematical Formula:
# VW_Slope = Σ(Volume * (X - X̄) * (Y - Ȳ)) / Σ(Volume * (X - X̄)²)
#     VW_Intercept = Ȳ - VW_Slope * X̄
# VW_R_Squared = 1 - (SS_res / SS_tot)"


#     def __init__(self, config: CustomVWIndicatorConfig):
#         super().__init__(config)
#         self.indicator_type = VWIndicatorType.STATISTICAL

        # Regression parameters"
#         self.price_type = getattr(config, "price_type", "close")

        # Historical data
#         self.prices = deque(maxlen=config.period)
#         self.volumes = deque(maxlen=config.period)
#         self.time_indices = deque(maxlen=config.period)

        # Regression results
#         self.slope = None
#         self.intercept = None
#         self.r_squared = None
#         self.predicted_value = None

        # Regression history
#         self.regression_history = deque(maxlen=config.period)

        # Volume weighting
#         self.volume_ema = None
#         self.volume_alpha = 2.0 / (config.period + 1)

#         self.bar_count = 0

#     def _calculate_indicator_value(self, bar: Bar):
# "Calculate Volume-Weighted Linear Regression.
        # Get price based on type"
#         if self.price_type == "typical":
# price = (
#                 bar.high.as_double() + bar.low.as_double() + bar.close.as_double()
# ) / 3.0"
#         elif self.price_type == "weighted":
# price = (
#                 bar.high.as_double() + bar.low.as_double() + 2 * bar.close.as_double()
# ) / 4.0
#         else:  # close
#             price = bar.close.as_double()

#         volume = bar.volume.as_double()

        # Store data
#         self.prices.append(price)
#         self.volumes.append(volume)
#         self.time_indices.append(self.bar_count)

#         self.bar_count += 1

        # Initialize volume EMA
#         if self.volume_ema is None:
#             self.volume_ema = volume
#         else:
#             self.volume_ema = (
#                 self.volume_alpha * volume + (1 - self.volume_alpha) * self.volume_ema
# )

        # Need enough data
#         if len(self.prices) < max(3, self.config.period // 2):
#             return None

        # Calculate volume-weighted regression
#         self._calculate_vw_regression()

        # Calculate predicted value for current time
#         if self.slope is not None and self.intercept is not None:
#             self.predicted_value = self.slope * self.bar_count + self.intercept

        # Store regression data
#         if self.slope is not None:
# regression_data = {
# "slope": self.slope,"
# "intercept": self.intercept,"
# "r_squared": self.r_squared,"
# "predicted": self.predicted_value,"
# "actual": price,"
# "time": self.bar_count,
# }
#             self.regression_history.append(regression_data)

#         return self.predicted_value

#     def _calculate_vw_regression(self):
#         "Calculate volume-weighted linear regression."
#         if len(self.prices) < 2:
#             return

#         x_vals = list(self.time_indices)
#         y_vals = list(self.prices)
#         volumes = list(self.volumes)

        # Calculate volume-weighted means
#         total_volume = sum(volumes)
#         if total_volume == 0:
#             return

#         x_mean = sum(x * v for x, v in zip(x_vals, volumes)) / total_volume
#         y_mean = sum(y * v for y, v in zip(y_vals, volumes)) / total_volume

        # Calculate volume-weighted slope
# numerator = sum(
# v * (x - x_mean) * (y - y_mean) for x, y, v in zip(x_vals, y_vals, volumes)
# )
#         denominator = sum(v * (x - x_mean) ** 2 for x, v in zip(x_vals, volumes))

#         if denominator == 0:
#             self.slope = 0.0
#         else:
#             self.slope = numerator / denominator

        # Calculate intercept
#         self.intercept = y_mean - self.slope * x_mean

        # Calculate R-squared
#         self._calculate_r_squared(x_vals, y_vals, volumes, y_mean)

#     def _calculate_r_squared(
#         self,
# x_vals: List[float],
# y_vals: List[float],
# volumes: List[float],
# y_mean: float,
# ):"
#         "Calculate volume-weighted R-squared."
        # Calculate predicted values
#         y_pred = [self.slope * x + self.intercept for x in x_vals]

        # Calculate volume-weighted sum of squares
#         ss_res = sum(v * (y - pred) ** 2 for y, pred, v in zip(y_vals, y_pred, volumes))
#         ss_tot = sum(v * (y - y_mean) ** 2 for y, v in zip(y_vals, volumes))

#         if ss_tot == 0:
#             self.r_squared = 0.0
#         else:
#             self.r_squared = 1.0 - (ss_res / ss_tot)
            # Ensure R-squared is between 0 and 1
#             self.r_squared = max(0.0, min(1.0, self.r_squared))

#     def get_trend_direction(self):
#         "Get trend direction based on slope."
#         if self.slope is None:
#             return None

#         if self.slope > 0.001:""
#             return "UPTREND"
#         elif self.slope < -0.001:""
#             return "DOWNTREND"
#         else:""
#             return "SIDEWAYS"

#     def get_trend_strength(self):
#         "Get trend strength based on R-squared."
#         if self.r_squared is None:
#             return None

#         if self.r_squared >= 0.8:""
#             return "VERY_STRONG"
#         elif self.r_squared >= 0.6:""
#             return "STRONG"
#         elif self.r_squared >= 0.4:""
#             return "MODERATE"
#         elif self.r_squared >= 0.2:""
#             return "WEAK"
#         else:""
#             return "VERY_WEAK"

#     def get_price_deviation(self, current_price: float):
#         "Get deviation of current price from regression line."
#         if self.predicted_value is None:
#             return None

#         return (current_price - self.predicted_value) / self.predicted_value

#     def get_regression_channel(
# self, std_dev_multiplier: float = 2.0
# ) -> Optional[Tuple[float, float]]:"
#         "Get regression channel bounds."
#         if len(self.regression_history) < 10:
#             return None

        # Calculate standard deviation of residuals
#         residuals = []
#         for data in self.regression_history:""
#             if data["predicted"] is not None and data["actual"] is not None:""
#                 residuals.append(data["actual"] - data["predicted"])

#         if not residuals:
#             return None

#         residual_std = np.std(residuals)

#         if self.predicted_value is None:
#             return None

#         upper_bound = self.predicted_value + (std_dev_multiplier * residual_std)
#         lower_bound = self.predicted_value - (std_dev_multiplier * residual_std)

#         return upper_bound, lower_bound

#     def reset(self):
#         "Reset indicator state."
#         super().reset()
#         self.prices.clear()
#         self.volumes.clear()
#         self.time_indices.clear()
#         self.slope = None
#         self.intercept = None
#         self.r_squared = None
#         self.predicted_value = None
#         self.regression_history.clear()
#         self.volume_ema = None
#         self.bar_count = 0


class VWPercentileRank(BaseCustomVWIndicator):""

# Volume-Weighted Percentile Rank.

# Enhanced percentile ranking with volume weighting for improved
# relative position analysis within historical distribution.

# Mathematical Formula:
# VW_Percentile = (Σ(Volume_i) for all Price_i <= Current_Price) / Σ(Total_Volume)
# Where Volume_i is weighted by recency and significance"


#     def __init__(self, config: CustomVWIndicatorConfig):
#         super().__init__(config)
#         self.indicator_type = VWIndicatorType.STATISTICAL

        # Percentile parameters"
#         self.price_type = getattr(config, "price_type", "close")""
#         self.lookback_period = getattr(config, "lookback_period", config.period * 2)

        # Historical data
#         self.price_volume_pairs = deque(maxlen=self.lookback_period)

        # Percentile values
#         self.percentile_rank = None
#         self.percentile_history = deque(maxlen=config.period)

        # Volume weighting
#         self.volume_ema = None
#         self.volume_alpha = 2.0 / (config.period + 1)

        # Recency weighting"
#         self.recency_factor = getattr(config, "recency_factor", 0.95)

#     def _calculate_indicator_value(self, bar: Bar):
# "Calculate Volume-Weighted Percentile Rank.
        # Get price based on type"
#         if self.price_type == "typical":
# price = (
#                 bar.high.as_double() + bar.low.as_double() + bar.close.as_double()
# ) / 3.0"
#         elif self.price_type == "weighted":
# price = (
#                 bar.high.as_double() + bar.low.as_double() + 2 * bar.close.as_double()
# ) / 4.0
#         else:  # close
#             price = bar.close.as_double()

#         volume = bar.volume.as_double()

        # Initialize volume EMA
#         if self.volume_ema is None:
#             self.volume_ema = volume
#         else:
#             self.volume_ema = (
#                 self.volume_alpha * volume + (1 - self.volume_ema) * self.volume_ema
# )

        # Store price-volume pair
#         self.price_volume_pairs.append((price, volume))

        # Need enough data
#         if len(self.price_volume_pairs) < max(10, self.config.period // 2):
#             return None

        # Calculate volume-weighted percentile rank
#         self.percentile_rank = self._calculate_vw_percentile_rank(price)

        # Store in history
#         if self.percentile_rank is not None:
#             self.percentile_history.append(self.percentile_rank)

#         return self.percentile_rank

#     def _calculate_vw_percentile_rank(self, current_price: float):
#         "Calculate volume-weighted percentile rank."
#         if len(self.price_volume_pairs) < 2:
#             return 0.5

        # Calculate recency weights
#         n = len(self.price_volume_pairs)
#         recency_weights = [self.recency_factor ** (n - i - 1) for i in range(n)]

        # Calculate volume weights
#         volume_weights = []
#         for _, volume in self.price_volume_pairs:
#             if self.volume_ema > 0:
#                 vol_weight = volume / self.volume_ema
#             else:
#                 vol_weight = 1.0
#             volume_weights.append(vol_weight)

        # Combine recency and volume weights
#         combined_weights = [r * v for r, v in zip(recency_weights, volume_weights)]

        # Calculate weighted percentile
#         total_weight_below = 0.0
#         total_weight = sum(combined_weights)

#         for i, (price, _) in enumerate(self.price_volume_pairs):
#             if price <= current_price:
#                 total_weight_below += combined_weights[i]

#         if total_weight == 0:
#             return 0.5

#         percentile = total_weight_below / total_weight

        # Ensure percentile is between 0 and 1
#         return max(0.0, min(1.0, percentile))

#     def get_percentile_signal(self):
#         "Get signal based on percentile rank."
#         if self.percentile_rank is None:
#             return None

#         if self.percentile_rank >= 0.95:""
#             return "EXTREMELY_HIGH"
#         elif self.percentile_rank >= 0.80:""
#             return "HIGH"
#         elif self.percentile_rank >= 0.60:""
#             return "ABOVE_AVERAGE"
#         elif self.percentile_rank <= 0.05:""
#             return "EXTREMELY_LOW"
#         elif self.percentile_rank <= 0.20:""
#             return "LOW"
#         elif self.percentile_rank <= 0.40:""
#             return "BELOW_AVERAGE"
#         else:""
#             return "AVERAGE"

#     def get_percentile_momentum(self):
#         "Get percentile momentum direction."
#         if len(self.percentile_history) < 3:
#             return None

#         recent_percentiles = list(self.percentile_history)[-3:]

#         if recent_percentiles[-1] > recent_percentiles[-2] > recent_percentiles[-3]:""
#             return "RISING"
#         elif recent_percentiles[-1] < recent_percentiles[-2] < recent_percentiles[-3]:""
#             return "FALLING"
#         else:""
#             return "SIDEWAYS"

#     def get_mean_reversion_signal(self):
#         "Get mean reversion signal based on extreme percentiles."
#         if self.percentile_rank is None:
#             return None

#         if self.percentile_rank >= 0.90:""
#             return "STRONG_SELL_SIGNAL"
#         elif self.percentile_rank >= 0.80:""
#             return "SELL_SIGNAL"
#         elif self.percentile_rank <= 0.10:""
#             return "STRONG_BUY_SIGNAL"
#         elif self.percentile_rank <= 0.20:""
#             return "BUY_SIGNAL"
#         else:""
#             return "NO_SIGNAL"

#     def get_distribution_stats(self):
#         "Get distribution statistics."
#         if len(self.price_volume_pairs) < 10:
#             return None

#         prices = [pair[0] for pair in self.price_volume_pairs]
#         volumes = [pair[1] for pair in self.price_volume_pairs]

        # Calculate volume-weighted statistics
#         total_volume = sum(volumes)
#         if total_volume == 0:
#             return None

#         vw_mean = sum(p * v for p, v in zip(prices, volumes)) / total_volume
# vw_variance = (
#             sum(v * (p - vw_mean) ** 2 for p, v in zip(prices, volumes)) / total_volume
# )
#         vw_std = np.sqrt(vw_variance)

        # Calculate percentiles
#         sorted_prices = sorted(prices)
#         p25 = np.percentile(sorted_prices, 25)
#         p50 = np.percentile(sorted_prices, 50)
#         p75 = np.percentile(sorted_prices, 75)

#         return {
# "vw_mean": vw_mean,"
# "vw_std": vw_std,"
# "min": min(prices),"
# "max": max(prices),"
# "p25": p25,"
# "p50": p50,"
# "p75": p75,"
# "current_percentile": self.percentile_rank,
# }

#     def reset(self):
#         "Reset indicator state."
#         super().reset()
#         self.price_volume_pairs.clear()
#         self.percentile_rank = None
#         self.percentile_history.clear()
#         self.volume_ema = None


# Configuration factory functions
# def create_vw_z_score_config(
# period: int = 20,"
#     price_type: str = "close",
#     instrument_id=None,
#     bar_type=None,
# **kwargs,
# ) -> CustomVWIndicatorConfig:"
#     "Create configuration for VW Z-Score indicator."
# config = CustomVWIndicatorConfig(
# period=period, instrument_id=instrument_id, bar_type=bar_type, **kwargs
# )
#     config.price_type = price_type
#     return config


# def create_vw_correlation_config(
# period: int = 20,"
#     correlation_type: str = "price_volume",
#     instrument_id=None,
#     bar_type=None,
# **kwargs,
# ) -> CustomVWIndicatorConfig:"
#     "Create configuration for VW Correlation indicator."
# config = CustomVWIndicatorConfig(
# period=period, instrument_id=instrument_id, bar_type=bar_type, **kwargs
# )
#     config.correlation_type = correlation_type
#     return config


# def create_vw_regression_config(
# period: int = 20,"
#     price_type: str = "close",
#     instrument_id=None,
#     bar_type=None,
# **kwargs,
# ) -> CustomVWIndicatorConfig:"
#     "Create configuration for VW Regression indicator."
# config = CustomVWIndicatorConfig(
# period=period, instrument_id=instrument_id, bar_type=bar_type, **kwargs
# )
#     config.price_type = price_type
#     return config


# def create_vw_percentile_rank_config(
# period: int = 20,"
#     price_type: str = "close",
#     lookback_period: int = 40,
#     recency_factor: float = 0.95,
#     instrument_id=None,
#     bar_type=None,
# **kwargs,
# ) -> CustomVWIndicatorConfig:"
#     "Create configuration for VW Percentile Rank indicator."
# config = CustomVWIndicatorConfig(
# period=period, instrument_id=instrument_id, bar_type=bar_type, **kwargs
# )
#     config.price_type = price_type
#     config.lookback_period = lookback_period
#     config.recency_factor = recency_factor
#     return config
# "'"'