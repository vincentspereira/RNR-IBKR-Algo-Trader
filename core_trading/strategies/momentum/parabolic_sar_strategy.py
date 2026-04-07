"""Parabolic SAR Strategy - Uses Parabolic Stop and Reverse for trend following."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class SARSignal(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class SARResult:
    signal: SARSignal
    sar_value: float
    trend_direction: str
    strength: float
    confidence: float
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SARConfig:
    step: float = 0.02
    max_step: float = 0.20


class ParabolicSARStrategy:
    """Parabolic SAR strategy for trend following with stop-and-reverse signals."""

    def __init__(self, config: Optional[SARConfig] = None):
        self.config = config or SARConfig()
        self.logger = logging.getLogger(self.__class__.__name__)

    def _calculate_sar(self, data: pd.DataFrame) -> Dict[str, np.ndarray]:
        """Calculate Parabolic SAR values and trend direction."""
        high = data["high"].values.astype(float)
        low = data["low"].values.astype(float)
        n = len(high)

        sar = np.zeros(n)
        trend = np.ones(n)  # 1=uptrend, -1=downtrend
        af = self.config.step
        ep = high[0]

        sar[0] = low[0]
        trend[0] = 1

        for i in range(1, n):
            sar[i] = sar[i - 1] + af * (ep - sar[i - 1])

            if trend[i - 1] == 1:
                sar[i] = min(sar[i], low[i - 1])
                if i >= 2:
                    sar[i] = min(sar[i], low[i - 2])

                if low[i] < sar[i]:
                    trend[i] = -1
                    sar[i] = ep
                    ep = low[i]
                    af = self.config.step
                else:
                    trend[i] = 1
                    if high[i] > ep:
                        ep = high[i]
                        af = min(af + self.config.step, self.config.max_step)
            else:
                sar[i] = max(sar[i], high[i - 1])
                if i >= 2:
                    sar[i] = max(sar[i], high[i - 2])

                if high[i] > sar[i]:
                    trend[i] = 1
                    sar[i] = ep
                    ep = high[i]
                    af = self.config.step
                else:
                    trend[i] = -1
                    if low[i] < ep:
                        ep = low[i]
                        af = min(af + self.config.step, self.config.max_step)

        return {"sar": sar, "trend": trend}

    def generate_signals(self, data: pd.DataFrame) -> List[SARResult]:
        """Generate Parabolic SAR trading signals."""
        if len(data) < 3:
            return []

        result = self._calculate_sar(data)
        close = data["close"].values
        signals = []

        curr_trend = int(result["trend"][-1])
        prev_trend = int(result["trend"][-2])
        curr_sar = float(result["sar"][-1])
        curr_price = float(close[-1])

        # Trend reversal: downtrend -> uptrend (BUY)
        if prev_trend == -1 and curr_trend == 1:
            distance = abs(curr_price - curr_sar) / (curr_price + 1e-10)
            strength = min(distance * 20, 1.0)
            signals.append(SARResult(
                signal=SARSignal.BUY,
                sar_value=curr_sar,
                trend_direction="uptrend",
                strength=strength,
                confidence=min(strength * 1.2, 1.0),
                timestamp=datetime.now(timezone.utc),
                metadata={"reversal": True},
            ))

        # Trend reversal: uptrend -> downtrend (SELL)
        elif prev_trend == 1 and curr_trend == -1:
            distance = abs(curr_price - curr_sar) / (curr_price + 1e-10)
            strength = min(distance * 20, 1.0)
            signals.append(SARResult(
                signal=SARSignal.SELL,
                sar_value=curr_sar,
                trend_direction="downtrend",
                strength=strength,
                confidence=min(strength * 1.2, 1.0),
                timestamp=datetime.now(timezone.utc),
                metadata={"reversal": True},
            ))

        return signals

    def get_current_values(self, data: pd.DataFrame) -> Dict[str, float]:
        """Return current SAR value and trend direction."""
        if len(data) < 3:
            return {"sar": 0.0, "trend": 0}

        result = self._calculate_sar(data)
        return {
            "sar": float(result["sar"][-1]),
            "trend": float(result["trend"][-1]),
        }
