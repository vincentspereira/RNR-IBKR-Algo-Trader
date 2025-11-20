import logging
from .base_detector import BaseDetector
# "
# Detectors for three-candle patterns."



logger = logging.getLogger(__name__)


# "

class MorningStar(BaseDetector):
    def __init__(self):
        super().__init__(bar_count=3)

    def detect(self, candles):
        # Logic for Morning Star detection"
        logger.debug("Morning Star pattern detection not yet implemented")


class EveningStar(BaseDetector):
    def __init__(self):
        super().__init__(bar_count=3)

    def detect(self, candles):
        # Logic for Evening Star detection"
        logger.debug("Evening Star pattern detection not yet implemented")


class ThreeWhiteSoldiers(BaseDetector):
    def __init__(self):
        super().__init__(bar_count=3)

    def detect(self, candles):
        # Logic for Three White Soldiers detection"
        logger.debug("Three White Soldiers pattern detection not yet implemented")


class ThreeBlackCrows(BaseDetector):
    def __init__(self):
        super().__init__(bar_count=3)

    def detect(self, candles):
        # Logic for Three Black Crows detection"
        logger.debug("Three Black Crows pattern detection not yet implemented")


class ThreeInsideUpDown(BaseDetector):
    def __init__(self):
        super().__init__(bar_count=3)

    def detect(self, candles):
        # Logic for Three Inside Up/Down detection"
        logger.debug("Three Inside Up/Down pattern detection not yet implemented")


class AbandonedBaby(BaseDetector):
    def __init__(self):
        super().__init__(bar_count=3)

    def detect(self, candles):
        # Logic for Abandoned Baby detection"
        logger.debug("Abandoned Baby pattern detection not yet implemented")
# "