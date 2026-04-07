"""Vortex Indicator Strategy - Uses VI+ and VI- crossovers for trend detection."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class VortexSignal(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class VortexResult:
    signal: VortexSignal
    vi_plus: float
    vi_minus: float
    strength: float
    confidence: float
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class VortexConfig:
    period: int = 14


class VortexIndicatorStrategy:
    """Vortex Indicator strategy detecting trend direction via VI+/VI- crossovers."""

    def __init__(self, config: Optional[VortexConfig] = None):
        self.config = config or VortexConfig()
        self.logger = logging.getLogger(self.__class__.__name__)

    def _calculate_vortex(self, data: pd.DataFrame) -> Dict[str, pd.Series]:
        """Calculate Vortex Indicator components."""
        high = data["high"]
        low = data["low"]
        close = data["close"]
        period = self.config.period

        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        tr_sum = tr.rolling(window=period).sum()

        vm_plus = abs(high - low.shift(1))
        vm_plus_sum = vm_plus.rolling(window=period).sum()

        vm_minus = abs(low - high.shift(1))
        vm_minus_sum = vm_minus.rolling(window=period).sum()

        vi_plus = vm_plus_sum / tr_sum
        vi_minus = vm_minus_sum / tr_sum

        return {"vi_plus": vi_plus, "vi_minus": vi_minus}

    def generate_signals(self, data: pd.DataFrame) -> List[VortexResult]:
        """Generate Vortex Indicator trading signals."""
        if len(data) < self.config.period + 1:
            return []

        vortex = self._calculate_vortex(data)
        signals = []

        prev_plus = float(vortex["vi_plus"].iloc[-2])
        prev_minus = float(vortex["vi_minus"].iloc[-2])
        curr_plus = float(vortex["vi_plus"].iloc[-1])
        curr_minus = float(vortex["vi_minus"].iloc[-1])

        if np.isnan(curr_plus) or np.isnan(curr_minus):
            return []

        # Bullish crossover: VI+ crosses above VI-
        if prev_plus <= prev_minus and curr_plus > curr_minus:
            strength = min(abs(curr_plus - curr_minus) / (curr_plus + 1e-10), 1.0)
            signals.append(VortexResult(
                signal=VortexSignal.BUY,
                vi_plus=curr_plus,
                vi_minus=curr_minus,
                strength=strength,
                confidence=min(strength * 1.2, 1.0),
                timestamp=datetime.now(timezone.utc),
                metadata={"crossover": "bullish"},
            ))

        # Bearish crossover: VI- crosses above VI+
        elif prev_minus <= prev_plus and curr_minus > curr_plus:
            strength = min(abs(curr_minus - curr_plus) / (curr_minus + 1e-10), 1.0)
            signals.append(VortexResult(
                signal=VortexSignal.SELL,
                vi_plus=curr_plus,
                vi_minus=curr_minus,
                strength=strength,
                confidence=min(strength * 1.2, 1.0),
                timestamp=datetime.now(timezone.utc),
                metadata={"crossover": "bearish"},
            ))

        return signals

    def get_current_values(self, data: pd.DataFrame) -> Dict[str, float]:
        """Return current Vortex Indicator values."""
        if len(data) < self.config.period:
            return {"vi_plus": 0.0, "vi_minus": 0.0}

        vortex = self._calculate_vortex(data)
        vi_plus = vortex["vi_plus"].iloc[-1]
        vi_minus = vortex["vi_minus"].iloc[-1]
        return {
            "vi_plus": float(vi_plus) if not np.isnan(vi_plus) else 0.0,
            "vi_minus": float(vi_minus) if not np.isnan(vi_minus) else 0.0,
        }
