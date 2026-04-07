"""MA Crossover VWMA Strategy - Volume-Weighted Moving Average crossover for mean reversion."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class VWMASignal(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class VWMAConfig:
    fast_period: int = 10
    slow_period: int = 30


@dataclass
class VWMAResult:
    signal: VWMASignal
    fast_vwma: float
    slow_vwma: float
    strength: float
    confidence: float
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


class MovingAverageCrossoverVWMAStrategy:
    """Volume-Weighted Moving Average crossover strategy.

    Buys when fast VWMA crosses above slow VWMA.
    Sells when fast VWMA crosses below slow VWMA.
    """

    def __init__(self, config: Optional[VWMAConfig] = None):
        self.config = config or VWMAConfig()
        self.logger = logging.getLogger(self.__class__.__name__)

    def _calculate_vwma(self, prices: pd.Series, volumes: pd.Series, period: int) -> pd.Series:
        """Calculate Volume-Weighted Moving Average."""
        pv = prices * volumes
        pv_sum = pv.rolling(window=period, min_periods=period).sum()
        vol_sum = volumes.rolling(window=period, min_periods=period).sum()
        return pv_sum / (vol_sum + 1e-10)

    def generate_signals(self, data: pd.DataFrame) -> List[VWMAResult]:
        """Generate VWMA crossover signals."""
        min_required = self.config.slow_period + 1
        if len(data) < min_required:
            return []

        close = data["close"]
        volume = data["volume"]

        typical_price = (data["high"] + data["low"] + close) / 3
        fast_vwma = self._calculate_vwma(typical_price, volume, self.config.fast_period)
        slow_vwma = self._calculate_vwma(typical_price, volume, self.config.slow_period)

        curr_fast = float(fast_vwma.iloc[-1])
        prev_fast = float(fast_vwma.iloc[-2])
        curr_slow = float(slow_vwma.iloc[-1])
        prev_slow = float(slow_vwma.iloc[-2])

        if np.isnan(curr_fast) or np.isnan(curr_slow):
            return []

        signals = []

        # Bullish crossover: fast crosses above slow
        if prev_fast <= prev_slow and curr_fast > curr_slow:
            spread = (curr_fast - curr_slow) / (curr_slow + 1e-10)
            strength = min(abs(spread) * 20, 1.0)
            signals.append(VWMAResult(
                signal=VWMASignal.BUY,
                fast_vwma=curr_fast,
                slow_vwma=curr_slow,
                strength=strength,
                confidence=min(strength * 1.1, 1.0),
                timestamp=datetime.now(timezone.utc),
                metadata={"crossover": "bullish"},
            ))

        # Bearish crossover: fast crosses below slow
        elif prev_fast >= prev_slow and curr_fast < curr_slow:
            spread = (curr_slow - curr_fast) / (curr_slow + 1e-10)
            strength = min(abs(spread) * 20, 1.0)
            signals.append(VWMAResult(
                signal=VWMASignal.SELL,
                fast_vwma=curr_fast,
                slow_vwma=curr_slow,
                strength=strength,
                confidence=min(strength * 1.1, 1.0),
                timestamp=datetime.now(timezone.utc),
                metadata={"crossover": "bearish"},
            ))

        return signals

    def get_current_values(self, data: pd.DataFrame) -> Dict[str, float]:
        """Return current VWMA values."""
        if len(data) < self.config.slow_period:
            return {"fast_vwma": 0.0, "slow_vwma": 0.0}

        close = data["close"]
        volume = data["volume"]
        typical_price = (data["high"] + data["low"] + close) / 3

        fast_vwma = self._calculate_vwma(typical_price, volume, self.config.fast_period)
        slow_vwma = self._calculate_vwma(typical_price, volume, self.config.slow_period)

        fast = fast_vwma.iloc[-1]
        slow = slow_vwma.iloc[-1]
        return {
            "fast_vwma": float(fast) if not np.isnan(fast) else 0.0,
            "slow_vwma": float(slow) if not np.isnan(slow) else 0.0,
        }
