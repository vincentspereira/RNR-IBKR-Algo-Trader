"""MACD Crossover Strategy - Moving Average Convergence Divergence signal generation."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class MACDSignal(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class MACDResult:
    signal: MACDSignal
    macd_line: float
    signal_line: float
    histogram: float
    strength: float
    confidence: float
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MACDConfig:
    fast_period: int = 12
    slow_period: int = 26
    signal_period: int = 9
    histogram_threshold: float = 0.0
    min_confidence: float = 0.3
    volume_confirmation: bool = True
    volume_threshold: float = 1.2


class MACDCrossoverStrategy:
    """MACD crossover strategy generating BUY/SELL signals on line crossovers."""

    def __init__(self, config: Optional[MACDConfig] = None):
        self.config = config or MACDConfig()
        self.logger = logging.getLogger(self.__class__.__name__)

    def calculate(self, data: pd.DataFrame) -> List[MACDResult]:
        """Calculate MACD signals from OHLCV data.

        Args:
            data: DataFrame with 'close' (and optionally 'volume') columns.

        Returns:
            List of MACDResult signals for each crossover detected.
        """
        if len(data) < self.config.slow_period + self.config.signal_period:
            self.logger.warning("Insufficient data for MACD calculation")
            return []

        close = data["close"]
        volumes = data.get("volume", pd.Series(np.ones(len(data)), index=data.index))

        # Calculate EMA fast and slow
        ema_fast = close.ewm(span=self.config.fast_period, adjust=False).mean()
        ema_slow = close.ewm(span=self.config.slow_period, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=self.config.signal_period, adjust=False).mean()
        histogram = macd_line - signal_line

        signals = []

        # Detect crossovers in the last row
        if len(histogram) < 2:
            return []

        prev_hist = histogram.iloc[-2]
        curr_hist = histogram.iloc[-1]
        curr_macd = macd_line.iloc[-1]
        curr_signal = signal_line.iloc[-1]

        # Volume confirmation
        vol_confirmed = True
        if self.config.volume_confirmation and len(volumes) >= 20:
            avg_vol = volumes.rolling(20).mean().iloc[-1]
            if avg_vol > 0:
                vol_confirmed = volumes.iloc[-1] >= avg_vol * self.config.volume_threshold

        # Bullish crossover: histogram crosses above zero
        if prev_hist <= 0 and curr_hist > 0:
            strength = min(abs(curr_hist) / (close.iloc[-1] * 0.01 + 1e-10), 1.0)
            confidence = strength * (1.2 if vol_confirmed else 0.8)
            confidence = min(confidence, 1.0)

            signals.append(MACDResult(
                signal=MACDSignal.BUY,
                macd_line=float(curr_macd),
                signal_line=float(curr_signal),
                histogram=float(curr_hist),
                strength=strength,
                confidence=confidence,
                timestamp=datetime.now(timezone.utc),
                metadata={"crossover": "bullish", "volume_confirmed": vol_confirmed},
            ))

        # Bearish crossover: histogram crosses below zero
        elif prev_hist >= 0 and curr_hist < 0:
            strength = min(abs(curr_hist) / (close.iloc[-1] * 0.01 + 1e-10), 1.0)
            confidence = strength * (1.2 if vol_confirmed else 0.8)
            confidence = min(confidence, 1.0)

            signals.append(MACDResult(
                signal=MACDSignal.SELL,
                macd_line=float(curr_macd),
                signal_line=float(curr_signal),
                histogram=float(curr_hist),
                strength=strength,
                confidence=confidence,
                timestamp=datetime.now(timezone.utc),
                metadata={"crossover": "bearish", "volume_confirmed": vol_confirmed},
            ))

        return signals

    def generate_signals(self, data: pd.DataFrame) -> List[MACDResult]:
        """Generate MACD crossover signals (standard interface)."""
        return self.calculate(data)

    def get_current_values(self, data: pd.DataFrame) -> Dict[str, float]:
        """Return current MACD, signal, and histogram values."""
        if len(data) < self.config.slow_period + self.config.signal_period:
            return {"macd": 0.0, "signal": 0.0, "histogram": 0.0}

        close = data["close"]
        ema_fast = close.ewm(span=self.config.fast_period, adjust=False).mean()
        ema_slow = close.ewm(span=self.config.slow_period, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=self.config.signal_period, adjust=False).mean()

        return {
            "macd": float(macd_line.iloc[-1]),
            "signal": float(signal_line.iloc[-1]),
            "histogram": float((macd_line - signal_line).iloc[-1]),
        }
