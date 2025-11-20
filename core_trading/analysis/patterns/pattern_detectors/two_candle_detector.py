import logging
from .base_detector import BaseDetector
# "
# Detectors for two-candle patterns."



logger = logging.getLogger(__name__)


# "

class Engulfing(BaseDetector):
    def __init__(self):
        super().__init__(bar_count=2)

    def detect(self, candles):
        # Logic for Engulfing detection"
        logger.debug("Engulfing pattern detection not yet implemented")


class TweezerTop(BaseDetector):
    def __init__(self):
        super().__init__(bar_count=2)

    def detect(self, candles):
        # Logic for Tweezer Top detection"
        logger.debug("Tweezer Top pattern detection not yet implemented")


class TweezerBottom(BaseDetector):
    def __init__(self):
        super().__init__(bar_count=2)

    def detect(self, candles):
        # Logic for Tweezer Bottom detection"
        logger.debug("Tweezer Bottom pattern detection not yet implemented")
# "