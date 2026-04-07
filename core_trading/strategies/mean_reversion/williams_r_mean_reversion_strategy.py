"""Williams %R Mean Reversion Strategy - Uses Williams %R for overbought/oversold signals."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class WilliamsRSignal(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class WilliamsRConfig:
    period: int = 14
    oversold: float = -80.0
    overbought: float = -20.0


@dataclass
class WilliamsRResult:
    signal: WilliamsRSignal
    williams_r: float
    strength: float
    confidence: float
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


class WilliamsRMeanReversionStrategy:
    """Williams %R mean reversion strategy.

    Williams %R ranges from -100 (oversold) to 0 (overbought).
    Buys when %R crosses above oversold level from below.
    Sells when %R crosses below overbought level from above.
    """

    def __init__(self, config: Optional[WilliamsRConfig] = None):
        self.config = config or WilliamsRConfig()
        self.logger = logging.getLogger(self.__class__.__name__)

    def _calculate_williams_r(self, data: pd.DataFrame) -> pd.Series:
        """Calculate Williams %R."""
        high = data["high"]
        low = data["low"]
        close = data["close"]

        highest_high = high.rolling(window=self.config.period).max()
        lowest_low = low.rolling(window=self.config.period).min()

        wr = -100 * (highest_high - close) / (highest_high - lowest_low + 1e-10)
        return wr

    def generate_signals(self, data: pd.DataFrame) -> List[WilliamsRResult]:
        """Generate Williams %R mean reversion signals."""
        if len(data) < self.config.period + 1:
            return []

        wr = self._calculate_williams_r(data)
        curr_wr = float(wr.iloc[-1])
        prev_wr = float(wr.iloc[-2])

        if np.isnan(curr_wr) or np.isnan(prev_wr):
            return []

        signals = []

        # Crosses above oversold level from below -> BUY
        if prev_wr < self.config.oversold and curr_wr >= self.config.oversold:
            strength = min(abs(curr_wr - self.config.oversold) / abs(self.config.oversold), 1.0)
            signals.append(WilliamsRResult(
                signal=WilliamsRSignal.BUY,
                williams_r=curr_wr,
                strength=strength,
                confidence=min(strength * 1.2, 1.0),
                timestamp=datetime.now(timezone.utc),
                metadata={"crossover": "oversold_exit"},
            ))

        # Crosses below overbought level from above -> SELL
        elif prev_wr > self.config.overbought and curr_wr <= self.config.overbought:
            strength = min(abs(self.config.overbought - curr_wr) / abs(self.config.overbought + 100), 1.0)
            signals.append(WilliamsRResult(
                signal=WilliamsRSignal.SELL,
                williams_r=curr_wr,
                strength=strength,
                confidence=min(strength * 1.2, 1.0),
                timestamp=datetime.now(timezone.utc),
                metadata={"crossover": "overbought_exit"},
            ))

        return signals

    def get_current_values(self, data: pd.DataFrame) -> Dict[str, float]:
        """Return current Williams %R value."""
        if len(data) < self.config.period:
            return {"williams_r": -50.0}

        wr = self._calculate_williams_r(data)
        val = wr.iloc[-1]
        return {"williams_r": float(val) if not np.isnan(val) else -50.0}
