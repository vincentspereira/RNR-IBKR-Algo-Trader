from abc import ABC, abstractmethod
# "
# Base class for pattern detectors."



# "

class BaseDetector(ABC):""
# "
# Abstract base class for all pattern detectors."


# "

#     def __init__(self, bar_count: int):
#         self.bar_count = bar_count

#     @abstractmethod
#     def detect(self, candles):

# Detects the pattern in the given candles.

# :param candles: A list of candles to analyze.
# :return: A tuple containing a boolean indicating if the pattern was detected,
# and a dictionary with pattern-specific information."

#         try:
            # Validate input"
#             if not candles:""
#                 return False, {"error": "No candles provided"}

#             if len(candles) < self.bar_count:
#                 return False, {
# "error": f"Insufficient candles: need {self.bar_count}, got {len(candles)}"
# }

            # Get the most recent candles for analysis
#             recent_candles = candles[-self.bar_count :]

            # Basic pattern detection logic - can be overridden by subclasses"
# pattern_info = {
# "candles_analyzed": len(recent_candles),"
# "bar_count_required": self.bar_count,"
# "timestamp": recent_candles[-1].timestamp"
#                 if hasattr(recent_candles[-1], "timestamp")
# else None,"
# "symbol": recent_candles[-1].symbol"
#                 if hasattr(recent_candles[-1], "symbol")
# else None,
# }

            # Analyze candle characteristics
# bullish_candles = sum(
# 1 for candle in recent_candles if self._is_bullish(candle)
# )
# bearish_candles = sum(
# 1 for candle in recent_candles if self._is_bearish(candle)
# )
#             doji_candles = sum(1 for candle in recent_candles if self._is_doji(candle))

            # Calculate average body size
#             body_sizes = [self._calculate_body(candle) for candle in recent_candles]
#             avg_body_size = sum(body_sizes) / len(body_sizes) if body_sizes else 0

            # Calculate price range
#             highs = [candle.high for candle in recent_candles]
#             lows = [candle.low for candle in recent_candles]
#             price_range = max(highs) - min(lows)

            # Calculate volatility (simplified)
#             closes = [candle.close for candle in recent_candles]
#             if len(closes) > 1:
# price_changes = [
#                     abs(closes[i] - closes[i - 1]) / closes[i - 1]
#                     for i in range(1, len(closes))
# ]
# volatility = (
#                     sum(price_changes) / len(price_changes) if price_changes else 0
# )
#             else:
#                 volatility = 0

            # Update pattern info with analysis
# pattern_info.update(
# {
# "bullish_candles": bullish_candles,"
# "bearish_candles": bearish_candles,"
# "doji_candles": doji_candles,"
# "avg_body_size": avg_body_size,"
# "price_range": price_range,"
# "volatility": volatility,"
# "trend_direction": "bullish
#                     if bullish_candles > bearish_candles""
# else "bearish
#                     if bearish_candles > bullish_candles""
# else "neutral",
# }
# )

            # Basic pattern detection - look for significant patterns
#             pattern_detected = False

            # Detect strong trending patterns
#             if self.bar_count >= 3:
                # Strong bullish trend
#                 if bullish_candles >= (self.bar_count * 0.7):
# pattern_detected = True"
#                     pattern_info["pattern_type"] = "strong_bullish_trend"
#                     pattern_info["confidence"] = bullish_candles / self.bar_count

                # Strong bearish trend
#                 elif bearish_candles >= (self.bar_count * 0.7):
# pattern_detected = True"
#                     pattern_info["pattern_type"] = "strong_bearish_trend"
#                     pattern_info["confidence"] = bearish_candles / self.bar_count

                # High volatility pattern
#                 elif volatility > 0.02:  # 2% average change
# pattern_detected = True"
#                     pattern_info["pattern_type"] = "high_volatility"
# pattern_info["confidence"] = min(
#                         volatility * 10, 1.0
# )  # Scale volatility to confidence

                # Consolidation pattern (many doji or small bodies)
#                 elif doji_candles >= (self.bar_count * 0.5) or avg_body_size < (
#                     price_range * 0.3
# ):
# pattern_detected = True"
#                     pattern_info["pattern_type"] = "consolidation"
# pattern_info["confidence"] = max(
#                         doji_candles / self.bar_count, 1 - (avg_body_size / price_range)
# )

            # Single candle patterns
#             elif self.bar_count == 1:
#                 current_candle = recent_candles[0]

                # Doji pattern
#                 if self._is_doji(current_candle):
# pattern_detected = True"
#                     pattern_info["pattern_type"] = "doji"
#                     pattern_info["confidence"] = 0.7

                # Long body candle
#                 elif (
#                     self._calculate_body(current_candle)
# > (current_candle.high - current_candle.low) * 0.7
# ):
#                     pattern_detected = True
#                     if self._is_bullish(current_candle):""
# pattern_info["pattern_type"] = "long_bullish_body
#                     else:""
#                         pattern_info["pattern_type"] = "long_bearish_body"
#                     pattern_info["confidence"] = 0.8
# "
            # Add strength and reliability metrics"
#             if pattern_detected:""
# pattern_info["strength"] = pattern_info.get("confidence", 0.5)"
# pattern_info["reliability"] = min(
#                     len(recent_candles) / self.bar_count, 1.0
# )
# "
                # Calculate support/resistance levels"
# pattern_info["support_level"] = min(lows)"
#                 pattern_info["resistance_level"] = max(highs)

                # Calculate pattern completion percentage"
#                 pattern_info["completion"] = 1.0  # Pattern is complete when detected

#             return pattern_detected, pattern_info

#         except Exception as e:""
#             return False, {"error": f"Pattern detection failed: {str(e)}"}

# "

#     def _calculate_body(self, candle):
#         "Calculates the size of the candle body."
#         return abs(candle.close - candle.open)

#     def _is_bullish(self, candle):
#         "Determines if a candle is bullish."
#         return candle.close > candle.open

#     def _is_bearish(self, candle):
#         "Determines if a candle is bearish."
#         return candle.close < candle.open

#     def _is_doji(self, candle, threshold=0.1):

# Determines if a candle is a doji (open and close are very close).

# :param candle: The candle to check.
# :param threshold: The threshold percentage for considering a doji (default 0.1%).
# :return: True if the candle is a doji, False otherwise."

#         try:
#             body_size = abs(candle.close - candle.open)
#             total_range = candle.high - candle.low

#             if total_range == 0:
#                 return True  # No price movement at all

            # Doji if body is less than threshold percentage of total range
#             return (body_size / total_range) <= threshold
#         except (AttributeError, ZeroDivisionError):
#             return False
# "