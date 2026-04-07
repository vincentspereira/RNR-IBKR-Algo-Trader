"""Overnight Reversal Strategy - Trades overnight gap reversals."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class OvernightSignal(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class OvernightConfig:
    min_gap_pct: float = 0.3
    reversal_bar_count: int = 3
    sma_period: int = 20


@dataclass
class OvernightResult:
    signal: OvernightSignal
    gap_pct: float
    reversal_strength: float
    strength: float
    confidence: float
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


class OvernightReversalStrategy:
    """Overnight reversal strategy.

    Detects overnight gaps and trades the reversal during the session.
    Gap down that reverses -> BUY. Gap up that reverses -> SELL.
    """

    def __init__(self, config: Optional[OvernightConfig] = None):
        self.config = config or OvernightConfig()
        self.logger = logging.getLogger(self.__class__.__name__)

    def generate_signals(self, data: pd.DataFrame) -> List[OvernightResult]:
        """Generate overnight reversal signals."""
        if len(data) < self.config.reversal_bar_count + 1:
            return []

        close = data["close"]
        open_price = data["open"]
        high = data["high"]
        low = data["low"]

        prev_close = float(close.iloc[-2])
        curr_open = float(open_price.iloc[-1])
        curr_close = float(close.iloc[-1])
        curr_high = float(high.iloc[-1])
        curr_low = float(low.iloc[-1])

        # Calculate overnight gap
        gap_pct = ((curr_open - prev_close) / prev_close) * 100

        if abs(gap_pct) < self.config.min_gap_pct:
            return []

        # Calculate intraday movement relative to gap
        intraday_range = curr_high - curr_low
        intraday_move = curr_close - curr_open

        signals = []

        # Gap down + intraday reversal (price moved up from open) -> BUY
        if gap_pct < 0 and curr_close > curr_open:
            reversal_strength = abs(intraday_move) / (intraday_range + 1e-10)
            strength = min(abs(gap_pct) / 2.0 * reversal_strength, 1.0)
            signals.append(OvernightResult(
                signal=OvernightSignal.BUY,
                gap_pct=gap_pct,
                reversal_strength=reversal_strength,
                strength=strength,
                confidence=min(strength * 1.2, 1.0),
                timestamp=datetime.now(timezone.utc),
                metadata={"gap_direction": "down", "reversed": True},
            ))

        # Gap up + intraday reversal (price moved down from open) -> SELL
        elif gap_pct > 0 and curr_close < curr_open:
            reversal_strength = abs(intraday_move) / (intraday_range + 1e-10)
            strength = min(abs(gap_pct) / 2.0 * reversal_strength, 1.0)
            signals.append(OvernightResult(
                signal=OvernightSignal.SELL,
                gap_pct=gap_pct,
                reversal_strength=reversal_strength,
                strength=strength,
                confidence=min(strength * 1.2, 1.0),
                timestamp=datetime.now(timezone.utc),
                metadata={"gap_direction": "up", "reversed": True},
            ))

        return signals

    def get_current_values(self, data: pd.DataFrame) -> Dict[str, float]:
        """Return current overnight gap values."""
        if len(data) < 2:
            return {"gap_pct": 0.0}

        prev_close = float(data["close"].iloc[-2])
        curr_open = float(data["open"].iloc[-1])
        gap_pct = ((curr_open - prev_close) / prev_close) * 100
        return {"gap_pct": gap_pct}
