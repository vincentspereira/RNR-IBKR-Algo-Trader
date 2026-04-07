"""Bollinger Bands Mean Reversion Strategy - Uses Bollinger Bands for mean reversion trading."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class BBSignal(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class BBConfig:
    period: int = 20
    std_dev: float = 2.0
    oversold_threshold: float = 0.0
    overbought_threshold: float = 100.0


@dataclass
class BBResult:
    signal: BBSignal
    bb_value: float
    lower_band: float
    upper_band: float
    strength: float
    confidence: float
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


class BollingerBandsMeanReversionStrategy:
    """Bollinger Bands mean reversion strategy trading band extremes."""

    def __init__(self, config: Optional[BBConfig] = None):
        self.config = config or BBConfig()
        self.logger = logging.getLogger(self.__class__.__name__)

    def _calculate_bollinger_bands(self, data: pd.DataFrame) -> Dict[str, pd.Series]:
        """Calculate Bollinger Bands."""
        close = data["close"]
        sma = close.rolling(window=self.config.period).mean()
        std = close.rolling(window=self.config.period).std()
        upper = sma + (std * self.config.std_dev)
        lower = sma - (std * self.config.std_dev)
        bb_value = (close - lower) / (upper - lower) * 100
        return {"sma": sma, "upper": upper, "lower": lower, "bb_value": bb_value}

    def generate_signals(self, data: pd.DataFrame) -> List[BBResult]:
        """Generate Bollinger Bands mean reversion signals."""
        if len(data) < self.config.period + 1:
            return []

        bb = self._calculate_bollinger_bands(data)
        close = data["close"]

        curr_bb = float(bb["bb_value"].iloc[-1])
        prev_bb = float(bb["bb_value"].iloc[-2])
        curr_price = float(close.iloc[-1])
        curr_lower = float(bb["lower"].iloc[-1])
        curr_upper = float(bb["upper"].iloc[-1])

        if np.isnan(curr_bb) or np.isnan(prev_bb):
            return []

        signals = []

        # Price touches/crosses below lower band then moves up -> BUY
        if prev_bb <= 0 and curr_bb > 0:
            strength = min(abs(curr_lower - curr_price) / (curr_price + 1e-10) * 20, 1.0)
            signals.append(BBResult(
                signal=BBSignal.BUY,
                bb_value=curr_bb,
                lower_band=curr_lower,
                upper_band=curr_upper,
                strength=strength,
                confidence=min(strength * 1.2, 1.0),
                timestamp=datetime.now(timezone.utc),
                metadata={"reversal": "oversold_bounce"},
            ))

        # Price touches/crosses above upper band then moves down -> SELL
        elif prev_bb >= 100 and curr_bb < 100:
            strength = min(abs(curr_upper - curr_price) / (curr_price + 1e-10) * 20, 1.0)
            signals.append(BBResult(
                signal=BBSignal.SELL,
                bb_value=curr_bb,
                lower_band=curr_lower,
                upper_band=curr_upper,
                strength=strength,
                confidence=min(strength * 1.2, 1.0),
                timestamp=datetime.now(timezone.utc),
                metadata={"reversal": "overbought_rejection"},
            ))

        return signals

    def get_current_values(self, data: pd.DataFrame) -> Dict[str, float]:
        """Return current Bollinger Bands values."""
        if len(data) < self.config.period:
            return {}
        bb = self._calculate_bollinger_bands(data)
        return {
            "bb_value": float(bb["bb_value"].iloc[-1]),
            "upper_band": float(bb["upper"].iloc[-1]),
            "lower_band": float(bb["lower"].iloc[-1]),
            "sma": float(bb["sma"].iloc[-1]),
        }
