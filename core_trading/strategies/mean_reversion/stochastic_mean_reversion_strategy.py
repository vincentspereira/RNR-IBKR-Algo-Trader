"""Stochastic Mean Reversion Strategy - Uses Stochastic Oscillator for mean reversion signals."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class StochasticSignal(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class StochasticConfig:
    k_period: int = 14
    d_period: int = 3
    oversold: float = 20.0
    overbought: float = 80.0


@dataclass
class StochasticResult:
    signal: StochasticSignal
    k_value: float
    d_value: float
    strength: float
    confidence: float
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


class StochasticMeanReversionStrategy:
    """Stochastic Oscillator mean reversion strategy.

    Buys when %K crosses above %D in oversold zone.
    Sells when %K crosses below %D in overbought zone.
    """

    def __init__(self, config: Optional[StochasticConfig] = None):
        self.config = config or StochasticConfig()
        self.logger = logging.getLogger(self.__class__.__name__)

    def _calculate_stochastic(self, data: pd.DataFrame) -> Dict[str, pd.Series]:
        """Calculate Stochastic Oscillator %K and %D."""
        high = data["high"]
        low = data["low"]
        close = data["close"]

        lowest_low = low.rolling(window=self.config.k_period).min()
        highest_high = high.rolling(window=self.config.k_period).max()

        k = 100 * (close - lowest_low) / (highest_high - lowest_low + 1e-10)
        d = k.rolling(window=self.config.d_period).mean()

        return {"k": k, "d": d}

    def generate_signals(self, data: pd.DataFrame) -> List[StochasticResult]:
        """Generate Stochastic mean reversion signals."""
        if len(data) < self.config.k_period + self.config.d_period:
            return []

        stoch = self._calculate_stochastic(data)
        curr_k = float(stoch["k"].iloc[-1])
        prev_k = float(stoch["k"].iloc[-2])
        curr_d = float(stoch["d"].iloc[-1])
        prev_d = float(stoch["d"].iloc[-2])

        if np.isnan(curr_k) or np.isnan(curr_d):
            return []

        signals = []

        # Bullish crossover in oversold zone -> BUY
        if prev_k <= prev_d and curr_k > curr_d and curr_k < self.config.oversold:
            strength = min((self.config.oversold - curr_k) / self.config.oversold, 1.0)
            signals.append(StochasticResult(
                signal=StochasticSignal.BUY,
                k_value=curr_k,
                d_value=curr_d,
                strength=strength,
                confidence=min(strength * 1.2, 1.0),
                timestamp=datetime.now(timezone.utc),
                metadata={"crossover": "bullish_oversold"},
            ))

        # Bearish crossover in overbought zone -> SELL
        elif prev_k >= prev_d and curr_k < curr_d and curr_k > self.config.overbought:
            strength = min((curr_k - self.config.overbought) / (100 - self.config.overbought), 1.0)
            signals.append(StochasticResult(
                signal=StochasticSignal.SELL,
                k_value=curr_k,
                d_value=curr_d,
                strength=strength,
                confidence=min(strength * 1.2, 1.0),
                timestamp=datetime.now(timezone.utc),
                metadata={"crossover": "bearish_overbought"},
            ))

        return signals

    def get_current_values(self, data: pd.DataFrame) -> Dict[str, float]:
        """Return current Stochastic values."""
        if len(data) < self.config.k_period:
            return {"k": 50.0, "d": 50.0}

        stoch = self._calculate_stochastic(data)
        k = stoch["k"].iloc[-1]
        d = stoch["d"].iloc[-1]
        return {
            "k": float(k) if not np.isnan(k) else 50.0,
            "d": float(d) if not np.isnan(d) else 50.0,
        }
