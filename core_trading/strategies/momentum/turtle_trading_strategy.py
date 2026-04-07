"""Turtle Trading Strategy - Classic Donchian Channel breakout system."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class TurtleSignal(Enum):
    BUY = "buy"
    SELL = "sell"
    EXIT_LONG = "exit_long"
    EXIT_SHORT = "exit_short"
    HOLD = "hold"


@dataclass
class TurtleResult:
    signal: TurtleSignal
    channel_high: float
    channel_low: float
    atr: float
    strength: float
    confidence: float
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TurtleConfig:
    entry_period: int = 20
    exit_period: int = 10
    atr_period: int = 20


class TurtleTradingStrategy:
    """Turtle Trading strategy using Donchian Channel breakouts with ATR-based position sizing."""

    def __init__(self, config: Optional[TurtleConfig] = None):
        self.config = config or TurtleConfig()
        self.logger = logging.getLogger(self.__class__.__name__)
        self._position = 0  # 0=flat, 1=long, -1=short

    def _calculate_atr(self, data: pd.DataFrame) -> pd.Series:
        """Calculate Average True Range."""
        high = data["high"]
        low = data["low"]
        close = data["close"]
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.rolling(window=self.config.atr_period).mean()

    def generate_signals(self, data: pd.DataFrame) -> List[TurtleResult]:
        """Generate Turtle Trading signals based on Donchian Channel breakouts."""
        min_required = self.config.entry_period + 1
        if len(data) < min_required:
            return []

        high = data["high"]
        low = data["low"]
        close = data["close"]

        # Entry channel: highest high and lowest low over entry period (excluding current bar)
        channel_high = float(high.iloc[-(self.config.entry_period + 1):-1].max())
        channel_low = float(low.iloc[-(self.config.entry_period + 1):-1].min())

        # Exit channel: highest high and lowest low over exit period (excluding current bar)
        exit_high = float(high.iloc[-(self.config.exit_period + 1):-1].max())
        exit_low = float(low.iloc[-(self.config.exit_period + 1):-1].min())

        curr_price = float(close.iloc[-1])
        curr_atr = float(self._calculate_atr(data).iloc[-1])

        if np.isnan(curr_atr):
            curr_atr = 0.01

        signals = []

        if self._position == 0:
            # Entry signals
            if curr_price > channel_high:
                strength = min((curr_price - channel_high) / (curr_atr + 1e-10), 1.0)
                self._position = 1
                signals.append(TurtleResult(
                    signal=TurtleSignal.BUY,
                    channel_high=channel_high,
                    channel_low=channel_low,
                    atr=curr_atr,
                    strength=strength,
                    confidence=min(strength * 1.1, 1.0),
                    timestamp=datetime.now(timezone.utc),
                    metadata={"entry": "long_breakout"},
                ))
            elif curr_price < channel_low:
                strength = min((channel_low - curr_price) / (curr_atr + 1e-10), 1.0)
                self._position = -1
                signals.append(TurtleResult(
                    signal=TurtleSignal.SELL,
                    channel_high=channel_high,
                    channel_low=channel_low,
                    atr=curr_atr,
                    strength=strength,
                    confidence=min(strength * 1.1, 1.0),
                    timestamp=datetime.now(timezone.utc),
                    metadata={"entry": "short_breakout"},
                ))

        elif self._position == 1:
            # Exit long if price drops below exit channel low
            if curr_price < exit_low:
                self._position = 0
                signals.append(TurtleResult(
                    signal=TurtleSignal.EXIT_LONG,
                    channel_high=exit_high,
                    channel_low=exit_low,
                    atr=curr_atr,
                    strength=0.5,
                    confidence=0.8,
                    timestamp=datetime.now(timezone.utc),
                    metadata={"exit": "long_exit"},
                ))

        elif self._position == -1:
            # Exit short if price rises above exit channel high
            if curr_price > exit_high:
                self._position = 0
                signals.append(TurtleResult(
                    signal=TurtleSignal.EXIT_SHORT,
                    channel_high=exit_high,
                    channel_low=exit_low,
                    atr=curr_atr,
                    strength=0.5,
                    confidence=0.8,
                    timestamp=datetime.now(timezone.utc),
                    metadata={"exit": "short_exit"},
                ))

        return signals

    def reset_position(self):
        """Reset position state to flat."""
        self._position = 0

    def get_current_values(self, data: pd.DataFrame) -> Dict[str, float]:
        """Return current channel values and ATR."""
        if len(data) < self.config.entry_period:
            return {"channel_high": 0.0, "channel_low": 0.0, "atr": 0.0}

        high = data["high"]
        low = data["low"]
        atr = self._calculate_atr(data)

        return {
            "channel_high": float(high.iloc[-self.config.entry_period:].max()),
            "channel_low": float(low.iloc[-self.config.entry_period:].min()),
            "atr": float(atr.iloc[-1]) if not np.isnan(atr.iloc[-1]) else 0.0,
        }
