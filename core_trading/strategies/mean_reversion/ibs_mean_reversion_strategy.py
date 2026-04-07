"""IBS (Internal Bar Strength) Mean Reversion Strategy - Uses IBS indicator for intraday mean reversion."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class IBSSignal(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class IBSConfig:
    oversold_threshold: float = 0.2
    overbought_threshold: float = 0.8
    sma_period: int = 20


@dataclass
class IBSResult:
    signal: IBSSignal
    ibs_value: float
    strength: float
    confidence: float
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


class IBSMeanReversionStrategy:
    """Internal Bar Strength mean reversion strategy.

    IBS = (Close - Low) / (High - Low)
    Measures where the close is relative to the bar's range.
    Low IBS = price closed near the bar's low (oversold).
    High IBS = price closed near the bar's high (overbought).
    """

    def __init__(self, config: Optional[IBSConfig] = None):
        self.config = config or IBSConfig()
        self.logger = logging.getLogger(self.__class__.__name__)

    def _calculate_ibs(self, data: pd.DataFrame) -> pd.Series:
        """Calculate Internal Bar Strength."""
        high = data["high"]
        low = data["low"]
        close = data["close"]
        return (close - low) / (high - low + 1e-10)

    def generate_signals(self, data: pd.DataFrame) -> List[IBSResult]:
        """Generate IBS mean reversion signals."""
        if len(data) < 2:
            return []

        ibs = self._calculate_ibs(data)
        curr_ibs = float(ibs.iloc[-1])

        if np.isnan(curr_ibs):
            return []

        signals = []

        # IBS below oversold -> BUY (price closed near bar's low, expect bounce)
        if curr_ibs < self.config.oversold_threshold:
            strength = min((self.config.oversold_threshold - curr_ibs) / self.config.oversold_threshold, 1.0)
            signals.append(IBSResult(
                signal=IBSSignal.BUY,
                ibs_value=curr_ibs,
                strength=strength,
                confidence=min(strength * 1.2, 1.0),
                timestamp=datetime.now(timezone.utc),
                metadata={"condition": "ibs_oversold"},
            ))

        # IBS above overbought -> SELL (price closed near bar's high, expect reversal)
        elif curr_ibs > self.config.overbought_threshold:
            strength = min((curr_ibs - self.config.overbought_threshold) / (1.0 - self.config.overbought_threshold), 1.0)
            signals.append(IBSResult(
                signal=IBSSignal.SELL,
                ibs_value=curr_ibs,
                strength=strength,
                confidence=min(strength * 1.2, 1.0),
                timestamp=datetime.now(timezone.utc),
                metadata={"condition": "ibs_overbought"},
            ))

        return signals

    def get_current_values(self, data: pd.DataFrame) -> Dict[str, float]:
        """Return current IBS value."""
        if len(data) < 1:
            return {"ibs": 0.5}

        ibs = self._calculate_ibs(data)
        val = ibs.iloc[-1]
        return {"ibs": float(val) if not np.isnan(val) else 0.5}
