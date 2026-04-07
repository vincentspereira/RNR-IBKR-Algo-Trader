"""ROC (Rate of Change) Momentum Strategy - Measures price momentum as percentage change."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class ROCSignal(Enum):
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    STRONG_SELL = "strong_sell"


@dataclass
class ROCResult:
    signal: ROCSignal
    roc_value: float
    strength: float
    confidence: float
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ROCConfig:
    period: int = 12
    overbought_threshold: float = 10.0
    oversold_threshold: float = -10.0
    strong_threshold: float = 20.0
    smoothing_period: int = 5


class ROCMomentumStrategy:
    """ROC momentum strategy using rate of change with overbought/oversold levels."""

    def __init__(self, config: Optional[ROCConfig] = None):
        self.config = config or ROCConfig()
        self.logger = logging.getLogger(self.__class__.__name__)

    def calculate(self, data: pd.DataFrame) -> List[ROCResult]:
        """Calculate ROC momentum signals from OHLCV data."""
        if len(data) < self.config.period + self.config.smoothing_period:
            self.logger.warning("Insufficient data for ROC calculation")
            return []

        close = data["close"]

        # Calculate Rate of Change
        roc = ((close - close.shift(self.config.period)) / close.shift(self.config.period)) * 100

        # Smooth ROC
        roc_smoothed = roc.rolling(self.config.smoothing_period).mean()

        curr_roc = roc_smoothed.iloc[-1]
        if np.isnan(curr_roc):
            return []

        # Determine signal
        signal = ROCSignal.HOLD
        strength = min(abs(curr_roc) / self.config.strong_threshold, 1.0)

        if curr_roc > self.config.strong_threshold:
            signal = ROCSignal.STRONG_BUY
        elif curr_roc > self.config.overbought_threshold:
            signal = ROCSignal.BUY
        elif curr_roc < -self.config.strong_threshold:
            signal = ROCSignal.STRONG_SELL
        elif curr_roc < self.config.oversold_threshold:
            signal = ROCSignal.SELL

        confidence = strength

        return [ROCResult(
            signal=signal,
            roc_value=float(curr_roc),
            strength=strength,
            confidence=confidence,
            timestamp=datetime.now(timezone.utc),
            metadata={"raw_roc": float(roc.iloc[-1]) if not np.isnan(roc.iloc[-1]) else 0.0},
        )]

    def generate_signals(self, data: pd.DataFrame) -> List[ROCResult]:
        """Generate ROC momentum signals (standard interface)."""
        return self.calculate(data)

    def get_current_values(self, data: pd.DataFrame) -> Dict[str, float]:
        """Return current ROC value."""
        if len(data) < self.config.period:
            return {"roc": 0.0}

        close = data["close"]
        roc = ((close.iloc[-1] - close.iloc[-self.config.period]) / close.iloc[-self.config.period]) * 100
        return {"roc": float(roc)}
