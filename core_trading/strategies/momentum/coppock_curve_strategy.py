"""Coppock Curve Strategy - Uses Coppock Curve indicator for long-term buy/sell signals."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class CoppockSignal(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class CoppockConfig:
    roc_period_1: int = 14
    roc_period_2: int = 11
    wma_period: int = 10


@dataclass
class CoppockResult:
    signal: CoppockSignal
    coppock_value: float
    strength: float
    confidence: float
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


class CoppockCurveStrategy:
    """Coppock Curve strategy for long-term momentum signals.

    Originally designed for monthly charts to identify major bottoms.
    Buy when Coppock Curve crosses above zero from below.
    """

    def __init__(self, config: Optional[CoppockConfig] = None):
        self.config = config or CoppockConfig()
        self.logger = logging.getLogger(self.__class__.__name__)

    def _calculate_coppock(self, data: pd.DataFrame) -> pd.Series:
        """Calculate Coppock Curve."""
        close = data["close"]

        # Calculate two rates of change
        roc1 = close.pct_change(periods=self.config.roc_period_1) * 100
        roc2 = close.pct_change(periods=self.config.roc_period_2) * 100

        # Sum the ROCs
        roc_sum = roc1 + roc2

        # Apply weighted moving average
        coppock = roc_sum.rolling(window=self.config.wma_period).apply(
            lambda x: np.average(x, weights=np.arange(1, len(x) + 1)),
            raw=True,
        )

        return coppock

    def generate_signals(self, data: pd.DataFrame) -> List[CoppockResult]:
        """Generate Coppock Curve signals."""
        min_required = max(self.config.roc_period_1, self.config.roc_period_2) + self.config.wma_period + 1
        if len(data) < min_required:
            return []

        coppock = self._calculate_coppock(data)
        curr = float(coppock.iloc[-1])
        prev = float(coppock.iloc[-2])

        if np.isnan(curr) or np.isnan(prev):
            return []

        signals = []

        # Coppock crosses above zero -> BUY
        if prev <= 0 and curr > 0:
            strength = min(abs(curr) / (abs(prev) + abs(curr) + 1e-10), 1.0)
            signals.append(CoppockResult(
                signal=CoppockSignal.BUY,
                coppock_value=curr,
                strength=strength,
                confidence=min(strength * 1.2, 1.0),
                timestamp=datetime.now(timezone.utc),
                metadata={"crossover": "above_zero"},
            ))

        # Coppock crosses below zero -> SELL
        elif prev >= 0 and curr < 0:
            strength = min(abs(curr) / (abs(prev) + abs(curr) + 1e-10), 1.0)
            signals.append(CoppockResult(
                signal=CoppockSignal.SELL,
                coppock_value=curr,
                strength=strength,
                confidence=min(strength * 1.2, 1.0),
                timestamp=datetime.now(timezone.utc),
                metadata={"crossover": "below_zero"},
            ))

        return signals

    def get_current_values(self, data: pd.DataFrame) -> Dict[str, float]:
        """Return current Coppock Curve value."""
        min_required = max(self.config.roc_period_1, self.config.roc_period_2) + self.config.wma_period
        if len(data) < min_required:
            return {"coppock": 0.0}

        coppock = self._calculate_coppock(data)
        val = coppock.iloc[-1]
        return {"coppock": float(val) if not np.isnan(val) else 0.0}
