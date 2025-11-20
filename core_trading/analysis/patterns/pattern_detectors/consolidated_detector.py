from .five_candle_detector import MatHold
from .four_candle_detector import Hikkake
from .single_candle_detector import Doji, Hammer, InvertedHammer, Marubozu, ShootingStar
# from .three_candle_detector import ()
from .two_candle_detector import Engulfing, TweezerBottom, TweezerTop
# "
# Consolidated pattern detector."

#     AbandonedBaby,
#     EveningStar,
#     MorningStar,
#     ThreeBlackCrows,
#     ThreeInsideUpDown,
#     ThreeWhiteSoldiers,
# )


# "

# class ConsolidatedPatternDetector:
#     def __init__(self):
#         self.detectors = {
            # Single-candle patterns"
# "Hammer": Hammer(),"
# "InvertedHammer": InvertedHammer(),"
# "ShootingStar": ShootingStar(),"
# "Doji": Doji(),"
# "Marubozu": Marubozu(),
            # Two-candle patterns"
# "Engulfing": Engulfing(),"
# "TweezerTop": TweezerTop(),"
# "TweezerBottom": TweezerBottom(),
            # Three-candle patterns"
# "MorningStar": MorningStar(),"
# "EveningStar": EveningStar(),"
# "ThreeWhiteSoldiers": ThreeWhiteSoldiers(),"
# "ThreeBlackCrows": ThreeBlackCrows(),"
# "ThreeInsideUpDown": ThreeInsideUpDown(),"
# "AbandonedBaby": AbandonedBaby(),
            # Four-candle patterns"
# "Hikkake": Hikkake(),
            # Five-candle patterns"
# "MatHold": MatHold(),
# }

#     def detect(self, candles):

# Runs all registered pattern detectors on the given candles.

# :param candles: A list of candles to analyze.
# :return: A dictionary of detection results."

#         results = {}
#         for name, detector in self.detectors.items():
#             if len(candles) >= detector.bar_count:
#                 result = detector.detect(candles[-detector.bar_count :])
#                 if result and result[0]:
#                     results[name] = result[1]
#         return results
# "