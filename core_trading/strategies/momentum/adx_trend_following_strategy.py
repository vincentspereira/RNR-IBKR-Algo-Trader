"""ADX Trend Following Strategy - Uses Average Directional Index for trend strength."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class ADXSignal(Enum):
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    STRONG_SELL = "strong_sell"


@dataclass
class ADXResult:
    signal: ADXSignal
    adx: float
    plus_di: float
    minus_di: float
    strength: float
    confidence: float
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ADXConfig:
    period: int = 14
    adx_threshold: float = 25.0
    strong_trend_threshold: float = 50.0
    volume_confirmation: bool = True
    volume_threshold: float = 1.2


class ADXTrendFollowingStrategy:
    """ADX-based trend following strategy using directional movement."""

    def __init__(self, config: Optional[ADXConfig] = None):
        self.config = config or ADXConfig()
        self.logger = logging.getLogger(self.__class__.__name__)

    def _calculate_adx(self, data: pd.DataFrame) -> Dict[str, pd.Series]:
        """Calculate ADX, +DI, and -DI indicators."""
        period = self.config.period
        high = data["high"]
        low = data["low"]
        close = data["close"]

        # True Range
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # Directional Movement
        up_move = high - high.shift(1)
        down_move = low.shift(1) - low

        plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0), index=data.index)
        minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0), index=data.index)

        # Smoothed values using Wilder's smoothing
        atr = tr.ewm(alpha=1.0 / period, adjust=False).mean()
        plus_di = 100 * (plus_dm.ewm(alpha=1.0 / period, adjust=False).mean() / atr)
        minus_di = 100 * (minus_dm.ewm(alpha=1.0 / period, adjust=False).mean() / atr)

        # ADX
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10)
        adx = dx.ewm(alpha=1.0 / period, adjust=False).mean()

        return {"adx": adx, "plus_di": plus_di, "minus_di": minus_di, "atr": atr}

    def calculate(self, data: pd.DataFrame) -> List[ADXResult]:
        """Calculate ADX trend-following signals."""
        if len(data) < self.config.period * 3:
            self.logger.warning("Insufficient data for ADX calculation")
            return []

        indicators = self._calculate_adx(data)
        adx = indicators["adx"]
        plus_di = indicators["plus_di"]
        minus_di = indicators["minus_di"]

        signals = []

        curr_adx = adx.iloc[-1]
        curr_plus_di = plus_di.iloc[-1]
        curr_minus_di = minus_di.iloc[-1]
        prev_plus_di = plus_di.iloc[-2]
        prev_minus_di = minus_di.iloc[-2]

        if np.isnan(curr_adx):
            return []

        # Volume confirmation
        vol_confirmed = True
        if self.config.volume_confirmation and "volume" in data.columns and len(data) >= 20:
            avg_vol = data["volume"].rolling(20).mean().iloc[-1]
            if avg_vol > 0:
                vol_confirmed = data["volume"].iloc[-1] >= avg_vol * self.config.volume_threshold

        # Determine signal
        signal = ADXSignal.HOLD
        strength = curr_adx / 100.0

        if curr_adx >= self.config.adx_threshold:
            # +DI crosses above -DI -> bullish
            if prev_plus_di <= prev_minus_di and curr_plus_di > curr_minus_di:
                signal = ADXSignal.STRONG_BUY if curr_adx >= self.config.strong_trend_threshold else ADXSignal.BUY

            # -DI crosses above +DI -> bearish
            elif prev_minus_di <= prev_plus_di and curr_minus_di > curr_plus_di:
                signal = ADXSignal.STRONG_SELL if curr_adx >= self.config.strong_trend_threshold else ADXSignal.SELL

            # Trend continuation
            elif curr_plus_di > curr_minus_di:
                signal = ADXSignal.BUY if curr_adx >= self.config.strong_trend_threshold else ADXSignal.HOLD
            elif curr_minus_di > curr_plus_di:
                signal = ADXSignal.SELL if curr_adx >= self.config.strong_trend_threshold else ADXSignal.HOLD

        confidence = min(strength * (1.2 if vol_confirmed else 0.8), 1.0)

        signals.append(ADXResult(
            signal=signal,
            adx=float(curr_adx),
            plus_di=float(curr_plus_di),
            minus_di=float(curr_minus_di),
            strength=strength,
            confidence=confidence,
            timestamp=datetime.now(timezone.utc),
            metadata={"volume_confirmed": vol_confirmed},
        ))

        return signals

    def generate_signals(self, data: pd.DataFrame) -> List[ADXResult]:
        """Generate ADX trend-following signals (standard interface)."""
        return self.calculate(data)

    def get_current_values(self, data: pd.DataFrame) -> Dict[str, float]:
        """Return current ADX indicator values."""
        if len(data) < self.config.period * 3:
            return {"adx": 0.0, "plus_di": 0.0, "minus_di": 0.0}

        indicators = self._calculate_adx(data)
        return {
            "adx": float(indicators["adx"].iloc[-1]),
            "plus_di": float(indicators["plus_di"].iloc[-1]),
            "minus_di": float(indicators["minus_di"].iloc[-1]),
        }
