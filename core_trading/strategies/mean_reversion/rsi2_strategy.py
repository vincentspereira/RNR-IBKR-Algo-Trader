"""RSI(2) Strategy - Classic 2-period RSI mean reversion with SMA trend filter."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class RSI2Signal(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class RSI2Config:
    rsi_period: int = 2
    sma_period: int = 200
    oversold_threshold: float = 10.0
    overbought_threshold: float = 90.0


@dataclass
class RSI2Result:
    signal: RSI2Signal
    rsi_value: float
    sma_value: float
    strength: float
    confidence: float
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


class RSI2Strategy:
    """RSI(2) mean reversion strategy with SMA trend filter.

    Buys when RSI(2) < oversold and price > SMA (uptrend pullback).
    Sells when RSI(2) > overbought and price < SMA (downtrend rally).
    """

    def __init__(self, config: Optional[RSI2Config] = None):
        self.config = config or RSI2Config()
        self.logger = logging.getLogger(self.__class__.__name__)

    def _calculate_rsi(self, prices: pd.Series) -> pd.Series:
        """Calculate RSI with exponential moving averages."""
        delta = prices.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1.0 / self.config.rsi_period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1.0 / self.config.rsi_period, adjust=False).mean()
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def generate_signals(self, data: pd.DataFrame) -> List[RSI2Result]:
        """Generate RSI(2) mean reversion signals."""
        min_required = max(self.config.rsi_period + 1, self.config.sma_period)
        if len(data) < min_required:
            return []

        close = data["close"]
        rsi = self._calculate_rsi(close)
        sma = close.rolling(window=self.config.sma_period).mean()

        curr_rsi = float(rsi.iloc[-1])
        curr_price = float(close.iloc[-1])
        curr_sma = float(sma.iloc[-1])

        if np.isnan(curr_rsi) or np.isnan(curr_sma):
            return []

        signals = []

        # Oversold in uptrend -> BUY
        if curr_rsi < self.config.oversold_threshold and curr_price > curr_sma:
            strength = min((self.config.oversold_threshold - curr_rsi) / self.config.oversold_threshold, 1.0)
            signals.append(RSI2Result(
                signal=RSI2Signal.BUY,
                rsi_value=curr_rsi,
                sma_value=curr_sma,
                strength=strength,
                confidence=min(strength * 1.2, 1.0),
                timestamp=datetime.now(timezone.utc),
                metadata={"condition": "oversold_in_uptrend"},
            ))

        # Overbought in downtrend -> SELL
        elif curr_rsi > self.config.overbought_threshold and curr_price < curr_sma:
            strength = min((curr_rsi - self.config.overbought_threshold) / (100 - self.config.overbought_threshold), 1.0)
            signals.append(RSI2Result(
                signal=RSI2Signal.SELL,
                rsi_value=curr_rsi,
                sma_value=curr_sma,
                strength=strength,
                confidence=min(strength * 1.2, 1.0),
                timestamp=datetime.now(timezone.utc),
                metadata={"condition": "overbought_in_downtrend"},
            ))

        return signals

    def get_current_values(self, data: pd.DataFrame) -> Dict[str, float]:
        """Return current RSI(2) and SMA values."""
        if len(data) < max(self.config.rsi_period + 1, self.config.sma_period):
            return {"rsi2": 0.0, "sma": 0.0}

        close = data["close"]
        rsi = self._calculate_rsi(close)
        sma = close.rolling(window=self.config.sma_period).mean()
        return {
            "rsi2": float(rsi.iloc[-1]) if not np.isnan(rsi.iloc[-1]) else 50.0,
            "sma": float(sma.iloc[-1]) if not np.isnan(sma.iloc[-1]) else 0.0,
        }
