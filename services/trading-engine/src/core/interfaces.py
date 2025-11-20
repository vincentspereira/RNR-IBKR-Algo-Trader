from enum import Enum, auto

class MarketRegime(Enum):
    BULLISH = auto()
    BEARISH = auto()
    SIDEWAYS = auto()
    VOLATILE = auto()

class RiskLevel(Enum):
    LOW = auto()
    MEDIUM = auto()
    HIGH = auto()
    CRITICAL = auto()

class SignalStrength(Enum):
    WEAK = auto()
    MODERATE = auto()
    STRONG = auto()
