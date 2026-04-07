"""OBV (On-Balance Volume) Trend Strategy - Uses OBV with moving average for trend confirmation."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class OBVSignal(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class OBVResult:
    signal: OBVSignal
    obv_value: float
    obv_ma: float
    price_trend: str
    strength: float
    confidence: float
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OBVConfig:
    ma_period: int = 20
    divergence_lookback: int = 20


class OBVTrendStrategy:
    """OBV trend strategy detecting price-OBV divergences and trend confirmations."""

    def __init__(self, config: Optional[OBVConfig] = None):
        self.config = config or OBVConfig()
        self.logger = logging.getLogger(self.__class__.__name__)

    def _calculate_obv(self, data: pd.DataFrame) -> pd.Series:
        """Calculate On-Balance Volume."""
        close = data["close"]
        volume = data["volume"]
        direction = np.sign(close.diff())
        direction.iloc[0] = 0
        return (direction * volume).cumsum()

    def generate_signals(self, data: pd.DataFrame) -> List[OBVResult]:
        """Generate OBV trend signals."""
        if len(data) < self.config.ma_period + 2:
            return []

        obv = self._calculate_obv(data)
        obv_ma = obv.rolling(window=self.config.ma_period).mean()
        close = data["close"]

        curr_obv = float(obv.iloc[-1])
        prev_obv = float(obv.iloc[-2])
        curr_obv_ma = float(obv_ma.iloc[-1])
        prev_obv_ma = float(obv_ma.iloc[-2])

        if np.isnan(curr_obv_ma) or np.isnan(prev_obv_ma):
            return []

        signals = []

        # OBV crosses above its MA - bullish
        if prev_obv <= prev_obv_ma and curr_obv > curr_obv_ma:
            price_trend_val = close.iloc[-1] - close.iloc[-self.config.divergence_lookback]
            obv_trend_val = obv.iloc[-1] - obv.iloc[-self.config.divergence_lookback]
            divergence = price_trend_val > 0 and obv_trend_val < 0

            strength = min(abs(curr_obv - curr_obv_ma) / (abs(curr_obv_ma) + 1), 1.0)
            confidence = min(strength * (1.3 if divergence else 1.0), 1.0)

            signals.append(OBVResult(
                signal=OBVSignal.BUY,
                obv_value=curr_obv,
                obv_ma=curr_obv_ma,
                price_trend="up" if price_trend_val > 0 else "down",
                strength=strength,
                confidence=confidence,
                timestamp=datetime.now(timezone.utc),
                metadata={"bullish_divergence": divergence},
            ))

        # OBV crosses below its MA - bearish
        elif prev_obv >= prev_obv_ma and curr_obv < curr_obv_ma:
            price_trend_val = close.iloc[-1] - close.iloc[-self.config.divergence_lookback]
            obv_trend_val = obv.iloc[-1] - obv.iloc[-self.config.divergence_lookback]
            divergence = price_trend_val < 0 and obv_trend_val > 0

            strength = min(abs(curr_obv_ma - curr_obv) / (abs(curr_obv_ma) + 1), 1.0)
            confidence = min(strength * (1.3 if divergence else 1.0), 1.0)

            signals.append(OBVResult(
                signal=OBVSignal.SELL,
                obv_value=curr_obv,
                obv_ma=curr_obv_ma,
                price_trend="down" if price_trend_val < 0 else "up",
                strength=strength,
                confidence=confidence,
                timestamp=datetime.now(timezone.utc),
                metadata={"bearish_divergence": divergence},
            ))

        return signals

    def get_current_values(self, data: pd.DataFrame) -> Dict[str, float]:
        """Return current OBV and its moving average."""
        if len(data) < self.config.ma_period:
            return {"obv": 0.0, "obv_ma": 0.0}

        obv = self._calculate_obv(data)
        obv_ma = obv.rolling(window=self.config.ma_period).mean()
        return {
            "obv": float(obv.iloc[-1]),
            "obv_ma": float(obv_ma.iloc[-1]),
        }
