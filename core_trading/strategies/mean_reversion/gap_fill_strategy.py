"""Gap Fill Strategy - Trades gaps that are expected to fill based on mean reversion."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class GapSignal(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class GapConfig:
    min_gap_pct: float = 0.5
    max_gap_pct: float = 5.0
    lookback_period: int = 20


@dataclass
class GapResult:
    signal: GapSignal
    gap_size: float
    gap_direction: str
    strength: float
    confidence: float
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


class GapFillStrategy:
    """Gap fill mean reversion strategy.

    Detects opening gaps and trades in the opposite direction,
    expecting the gap to be filled (price reverts to prior close).
    """

    def __init__(self, config: Optional[GapConfig] = None):
        self.config = config or GapConfig()
        self.logger = logging.getLogger(self.__class__.__name__)

    def generate_signals(self, data: pd.DataFrame) -> List[GapResult]:
        """Generate gap fill signals."""
        if len(data) < 2:
            return []

        close = data["close"]
        open_price = data["open"]

        prev_close = float(close.iloc[-2])
        curr_open = float(open_price.iloc[-1])
        curr_close = float(close.iloc[-1])

        # Calculate gap size as percentage
        gap_pct = ((curr_open - prev_close) / prev_close) * 100

        # Check if gap is within our tradeable range
        if abs(gap_pct) < self.config.min_gap_pct or abs(gap_pct) > self.config.max_gap_pct:
            return []

        # Check if gap has already filled (price moved past prev close)
        gap_filled = (gap_pct > 0 and curr_close <= prev_close) or \
                     (gap_pct < 0 and curr_close >= prev_close)

        if gap_filled:
            return []

        signals = []

        # Gap down -> expect fill -> BUY
        if gap_pct < 0:
            strength = min(abs(gap_pct) / self.config.max_gap_pct, 1.0)
            signals.append(GapResult(
                signal=GapSignal.BUY,
                gap_size=gap_pct,
                gap_direction="down",
                strength=strength,
                confidence=min(strength * 1.1, 1.0),
                timestamp=datetime.now(timezone.utc),
                metadata={"prev_close": prev_close, "target": prev_close},
            ))

        # Gap up -> expect fill -> SELL
        elif gap_pct > 0:
            strength = min(gap_pct / self.config.max_gap_pct, 1.0)
            signals.append(GapResult(
                signal=GapSignal.SELL,
                gap_size=gap_pct,
                gap_direction="up",
                strength=strength,
                confidence=min(strength * 1.1, 1.0),
                timestamp=datetime.now(timezone.utc),
                metadata={"prev_close": prev_close, "target": prev_close},
            ))

        return signals

    def get_current_values(self, data: pd.DataFrame) -> Dict[str, float]:
        """Return current gap information."""
        if len(data) < 2:
            return {"gap_pct": 0.0}

        prev_close = float(data["close"].iloc[-2])
        curr_open = float(data["open"].iloc[-1])
        gap_pct = ((curr_open - prev_close) / prev_close) * 100
        return {"gap_pct": gap_pct}
