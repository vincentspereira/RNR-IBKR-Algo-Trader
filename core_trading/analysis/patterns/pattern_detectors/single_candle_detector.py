from .base_detector import BaseDetector
# "
# Detectors for single-candle patterns."



# "

# class Hammer(BaseDetector):
#     def __init__(self):
#         super().__init__(bar_count=1)

#     def detect(self, candles):
# "Detect Hammer pattern - bullish reversal with small body and long lower shadow.
#         if not candles or len(candles) < 1:""
#             return False, {"error": "Insufficient candles for Hammer detection"}
# "
#         candle = candles[-1]
#         try:
#             body = abs(candle.close - candle.open)
#             total_range = candle.high - candle.low
#             upper_shadow = candle.high - max(candle.open, candle.close)
#             lower_shadow = min(candle.open, candle.close) - candle.low
# "
#             if total_range == 0:""
#                 return False, {"error": "No price range"}
# "
            # Hammer criteria:
            # 1. Small body (< 30% of total range)
            # 2. Long lower shadow (> 60% of total range)
            # 3. Short upper shadow (< 10% of total range)
#             small_body = body / total_range < 0.3
#             long_lower_shadow = lower_shadow / total_range > 0.6
#             short_upper_shadow = upper_shadow / total_range < 0.1

#             is_hammer = small_body and long_lower_shadow and short_upper_shadow

# pattern_info = {"
# "pattern_type": "hammer","
# "body_ratio": body / total_range,"
# "lower_shadow_ratio": lower_shadow / total_range,"
# "upper_shadow_ratio": upper_shadow / total_range,"
# "confidence": 0.8 if is_hammer else 0.0,"
# "reversal_type": "bullish",
# }

#             return is_hammer, pattern_info

#         except Exception as e:""
#             return False, {"error": f"Hammer detection failed: {str(e)}"}


# class InvertedHammer(BaseDetector):
#     def __init__(self):
#         super().__init__(bar_count=1)

#     def detect(self, candles):
#         "Detect Inverted Hammer pattern - potential bullish reversal with small body and long upper shadow."
#         if not candles or len(candles) < 1:
#             return False, {
# "error": "Insufficient candles for Inverted Hammer detection"
# }

#         candle = candles[-1]
#         try:
#             body = abs(candle.close - candle.open)
#             total_range = candle.high - candle.low
#             upper_shadow = candle.high - max(candle.open, candle.close)
#             lower_shadow = min(candle.open, candle.close) - candle.low

#             if total_range == 0:""
#                 return False, {"error": "No price range"}

            # Inverted Hammer criteria:
            # 1. Small body (< 30% of total range)
            # 2. Long upper shadow (> 60% of total range)
            # 3. Short lower shadow (< 10% of total range)
#             small_body = body / total_range < 0.3
#             long_upper_shadow = upper_shadow / total_range > 0.6
#             short_lower_shadow = lower_shadow / total_range < 0.1

#             is_inverted_hammer = small_body and long_upper_shadow and short_lower_shadow

# pattern_info = {
# "pattern_type": "inverted_hammer","
# "body_ratio": body / total_range,"
# "upper_shadow_ratio": upper_shadow / total_range,"
# "lower_shadow_ratio": lower_shadow / total_range,"
# "confidence": 0.7 if is_inverted_hammer else 0.0,"
# "reversal_type": "potential_bullish",
# }

#             return is_inverted_hammer, pattern_info

#         except Exception as e:""
#             return False, {"error": f"Inverted Hammer detection failed: {str(e)}"}


# class ShootingStar(BaseDetector):
#     def __init__(self):
#         super().__init__(bar_count=1)

#     def detect(self, candles):
# "Detect Shooting Star pattern - bearish reversal with small body and long upper shadow.
#         if not candles or len(candles) < 1:""
#             return False, {"error": "Insufficient candles for Shooting Star detection"}
# "
#         candle = candles[-1]
#         try:
#             body = abs(candle.close - candle.open)
#             total_range = candle.high - candle.low
#             upper_shadow = candle.high - max(candle.open, candle.close)
#             lower_shadow = min(candle.open, candle.close) - candle.low
# "
#             if total_range == 0:""
#                 return False, {"error": "No price range"}
# "
            # Shooting Star criteria:
            # 1. Small body (< 30% of total range)
            # 2. Long upper shadow (> 60% of total range)
            # 3. Short lower shadow (< 10% of total range)
            # 4. Body should be in lower part of range
#             small_body = body / total_range < 0.3
#             long_upper_shadow = upper_shadow / total_range > 0.6
#             short_lower_shadow = lower_shadow / total_range < 0.1
# body_in_lower_range = (
#                 min(candle.open, candle.close) - candle.low
# ) / total_range < 0.3

# is_shooting_star = (
#                 small_body
# and long_upper_shadow
# and short_lower_shadow
# and body_in_lower_range
# )

# pattern_info = {"
# "pattern_type": "shooting_star","
# "body_ratio": body / total_range,"
# "upper_shadow_ratio": upper_shadow / total_range,"
# "lower_shadow_ratio": lower_shadow / total_range,"
# "confidence": 0.8 if is_shooting_star else 0.0,"
# "reversal_type": "bearish",
# }

#             return is_shooting_star, pattern_info

#         except Exception as e:""
#             return False, {"error": f"Shooting Star detection failed: {str(e)}"}


# class Doji(BaseDetector):
#     def __init__(self):
#         super().__init__(bar_count=1)

#     def detect(self, candles):
# "Detect Doji pattern - indecision candle with very small body.
#         if not candles or len(candles) < 1:""
#             return False, {"error": "Insufficient candles for Doji detection"}
# "
#         candle = candles[-1]
#         try:
#             body = abs(candle.close - candle.open)
#             total_range = candle.high - candle.low
#             upper_shadow = candle.high - max(candle.open, candle.close)
#             lower_shadow = min(candle.open, candle.close) - candle.low
# "
#             if total_range == 0:""
#                 return True, {"pattern_type": "perfect_doji", "confidence": 1.0}
# "
            # Doji criteria: body is very small relative to total range (< 5%)
#             body_ratio = body / total_range
#             is_doji = body_ratio < 0.05
# "
            # Classify doji types"
# doji_type = "standard_doji
#             if upper_shadow > lower_shadow * 2:""
# doji_type = "dragonfly_doji
#             elif lower_shadow > upper_shadow * 2:""
# doji_type = "gravestone_doji
#             elif abs(upper_shadow - lower_shadow) / total_range < 0.1:""
#                 doji_type = "long_legged_doji"

# pattern_info = {
# "pattern_type": doji_type,"
# "body_ratio": body_ratio,"
# "upper_shadow_ratio": upper_shadow / total_range,"
# "lower_shadow_ratio": lower_shadow / total_range,"
# "confidence": 0.9 if is_doji else 0.0,"
# "signal_type": "indecision",
# }

#             return is_doji, pattern_info

#         except Exception as e:""
#             return False, {"error": f"Doji detection failed: {str(e)}"}


# class Marubozu(BaseDetector):
#     def __init__(self):
#         super().__init__(bar_count=1)

#     def detect(self, candles):
# "Detect Marubozu pattern - strong directional candle with little to no shadows.
#         if not candles or len(candles) < 1:""
#             return False, {"error": "Insufficient candles for Marubozu detection"}
# "
#         candle = candles[-1]
#         try:
#             body = abs(candle.close - candle.open)
#             total_range = candle.high - candle.low
#             upper_shadow = candle.high - max(candle.open, candle.close)
#             lower_shadow = min(candle.open, candle.close) - candle.low
# "
#             if total_range == 0:""
#                 return False, {"error": "No price range"}
# "
            # Marubozu criteria:
            # 1. Large body (> 85% of total range)
            # 2. Very small shadows (< 7.5% each)
#             body_ratio = body / total_range
#             upper_shadow_ratio = upper_shadow / total_range
#             lower_shadow_ratio = lower_shadow / total_range
# "
#             large_body = body_ratio > 0.85
#             small_shadows = upper_shadow_ratio < 0.075 and lower_shadow_ratio < 0.075
# "
#             is_marubozu = large_body and small_shadows
# "
            # Determine marubozu type"
# marubozu_type = ("
#                 "bullish_marubozu" if candle.close > candle.open else "bearish_marubozu"
# )
# "
# pattern_info = {"
# "pattern_type": marubozu_type,"
# "body_ratio": body_ratio,"
# "upper_shadow_ratio": upper_shadow_ratio,"
# "lower_shadow_ratio": lower_shadow_ratio,"
# "confidence": 0.9 if is_marubozu else 0.0,"
# "signal_type": "strong_directional",
# }

#             return is_marubozu, pattern_info

#         except Exception as e:""
#             return False, {"error": f"Marubozu detection failed: {str(e)}"}
# "