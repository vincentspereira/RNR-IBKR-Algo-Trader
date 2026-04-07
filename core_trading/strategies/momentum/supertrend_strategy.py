"""Supertrend Strategy - Trend-following based on ATR and Supertrend indicator."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class SupertrendSignal(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class SupertrendResult:
    signal: SupertrendSignal
    supertrend_value: float
    current_price: float
    trend_direction: int  # 1 = uptrend, -1 = downtrend
    strength: float
    confidence: float
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SupertrendConfig:
    atr_period: int = 10
    multiplier: float = 3.0
    min_confidence: float = 0.3


class SupertrendStrategy:
    """Supertrend strategy generating signals on trend direction changes."""

    def __init__(self, config: Optional[SupertrendConfig] = None):
        self.config = config or SupertrendConfig()
        self.logger = logging.getLogger(self.__class__.__name__)

    @staticmethod
    def _calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
        """Calculate Average True Range."""
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return true_range.rolling(period).mean()

    def calculate_supertrend(self, data: pd.DataFrame) -> pd.DataFrame:
        """Calculate Supertrend indicator for the entire dataset.

        Returns DataFrame with columns: 'supertrend', 'direction', 'upper_band', 'lower_band'
        """
        period = self.config.atr_period
        mult = self.config.multiplier

        if len(data) < period + 1:
            return pd.DataFrame(index=data.index)

        high = data["high"]
        low = data["low"]
        close = data["close"]
        atr = self._calculate_atr(high, low, close, period)

        hl2 = (high + low) / 2.0
        upper_band = hl2 + mult * atr
        lower_band = hl2 - mult * atr

        supertrend = pd.Series(np.nan, index=data.index)
        direction = pd.Series(1, index=data.index, dtype=int)

        # Initialize first valid row
        first_valid = atr.first_valid_index()
        if first_valid is None:
            return pd.DataFrame(index=data.index)

        start_idx = data.index.get_loc(first_valid)
        supertrend.iloc[start_idx] = upper_band.iloc[start_idx]
        direction.iloc[start_idx] = -1

        for i in range(start_idx + 1, len(data)):
            # Adjust bands: lower band can only rise, upper band can only fall
            if lower_band.iloc[i] > lower_band.iloc[i - 1] or close.iloc[i - 1] < lower_band.iloc[i - 1]:
                curr_lower = lower_band.iloc[i]
            else:
                curr_lower = lower_band.iloc[i - 1]

            if upper_band.iloc[i] < upper_band.iloc[i - 1] or close.iloc[i - 1] > upper_band.iloc[i - 1]:
                curr_upper = upper_band.iloc[i]
            else:
                curr_upper = upper_band.iloc[i - 1]

            # Determine direction
            if direction.iloc[i - 1] == 1:  # Was uptrend
                if close.iloc[i] < curr_lower:
                    direction.iloc[i] = -1
                    supertrend.iloc[i] = curr_upper
                else:
                    direction.iloc[i] = 1
                    supertrend.iloc[i] = curr_lower
            else:  # Was downtrend
                if close.iloc[i] > curr_upper:
                    direction.iloc[i] = 1
                    supertrend.iloc[i] = curr_lower
                else:
                    direction.iloc[i] = -1
                    supertrend.iloc[i] = curr_upper

            upper_band.iloc[i] = curr_upper
            lower_band.iloc[i] = curr_lower

        return pd.DataFrame({
            "supertrend": supertrend,
            "direction": direction,
            "upper_band": upper_band,
            "lower_band": lower_band,
        }, index=data.index)

    def calculate(self, data: pd.DataFrame) -> List[SupertrendResult]:
        """Calculate Supertrend signals from OHLCV data."""
        if len(data) < self.config.atr_period + 2:
            self.logger.warning("Insufficient data for Supertrend calculation")
            return []

        st = self.calculate_supertrend(data)
        if st.empty or len(st) < 2:
            return []

        signals = []
        prev_dir = st["direction"].iloc[-2]
        curr_dir = st["direction"].iloc[-1]
        curr_st = st["supertrend"].iloc[-1]
        curr_price = data["close"].iloc[-1]

        if np.isnan(curr_st):
            return []

        # Trend reversal detected
        if prev_dir != curr_dir:
            signal_type = SupertrendSignal.BUY if curr_dir == 1 else SupertrendSignal.SELL
            distance = abs(curr_price - curr_st) / curr_price
            strength = min(distance * 10, 1.0)
            confidence = strength

            signals.append(SupertrendResult(
                signal=signal_type,
                supertrend_value=float(curr_st),
                current_price=float(curr_price),
                trend_direction=int(curr_dir),
                strength=strength,
                confidence=confidence,
                timestamp=datetime.now(timezone.utc),
                metadata={"reversal": True, "prev_direction": int(prev_dir)},
            ))

        return signals

    def generate_signals(self, data: pd.DataFrame) -> List[SupertrendResult]:
        """Generate Supertrend signals (standard interface)."""
        return self.calculate(data)

    def get_current_values(self, data: pd.DataFrame) -> Dict[str, Any]:
        """Return current Supertrend values."""
        st = self.calculate_supertrend(data)
        if st.empty:
            return {"supertrend": 0.0, "direction": 0}

        return {
            "supertrend": float(st["supertrend"].iloc[-1]),
            "direction": int(st["direction"].iloc[-1]),
            "upper_band": float(st["upper_band"].iloc[-1]),
            "lower_band": float(st["lower_band"].iloc[-1]),
        }
