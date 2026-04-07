"""Augmented MA Crossover Strategy - Enhanced moving average crossover with volume weighting."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class AugMACrossSignal(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class AugMACrossResult:
    signal: AugMACrossSignal
    fast_ma: float
    slow_ma: float
    spread_pct: float
    volume_ratio: float
    strength: float
    confidence: float
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AugMACrossConfig:
    fast_period: int = 10
    slow_period: int = 30
    ma_type: str = "ema"  # "sma" or "ema"
    use_volume_weighting: bool = True
    min_spread_pct: float = 0.1
    volume_threshold: float = 1.2


class AugmentedMACrossoverStrategy:
    """Augmented MA crossover with volume weighting and spread confirmation."""

    def __init__(self, config: Optional[AugMACrossConfig] = None):
        self.config = config or AugMACrossConfig()
        self.logger = logging.getLogger(self.__class__.__name__)

    def _calculate_ma(self, prices: pd.Series, period: int) -> pd.Series:
        """Calculate moving average based on config type."""
        if self.config.ma_type == "ema":
            return prices.ewm(span=period, adjust=False).mean()
        return prices.rolling(window=period).mean()

    def _calculate_vwma(self, prices: pd.Series, volumes: pd.Series, period: int) -> pd.Series:
        """Calculate volume-weighted moving average."""
        return (prices * volumes).rolling(window=period).sum() / volumes.rolling(window=period).sum()

    def generate_signals(self, data: pd.DataFrame) -> List[AugMACrossResult]:
        """Generate augmented MA crossover signals."""
        min_period = max(self.config.fast_period, self.config.slow_period) + 1
        if len(data) < min_period:
            return []

        close = data["close"]
        volumes = data.get("volume", pd.Series(np.ones(len(data)), index=data.index))

        # Calculate fast and slow MAs
        if self.config.use_volume_weighting:
            fast_ma = self._calculate_vwma(close, volumes, self.config.fast_period)
            slow_ma = self._calculate_vwma(close, volumes, self.config.slow_period)
        else:
            fast_ma = self._calculate_ma(close, self.config.fast_period)
            slow_ma = self._calculate_ma(close, self.config.slow_period)

        # Volume ratio
        avg_vol = volumes.rolling(20).mean()
        volume_ratio = volumes.iloc[-1] / avg_vol.iloc[-1] if avg_vol.iloc[-1] > 0 else 1.0

        # Current and previous MA values
        curr_fast = float(fast_ma.iloc[-1])
        curr_slow = float(slow_ma.iloc[-1])
        prev_fast = float(fast_ma.iloc[-2])
        prev_slow = float(slow_ma.iloc[-2])

        if np.isnan(curr_fast) or np.isnan(curr_slow):
            return []

        spread_pct = abs(curr_fast - curr_slow) / curr_slow * 100

        signals = []

        # Golden cross: fast crosses above slow
        if prev_fast <= prev_slow and curr_fast > curr_slow:
            if spread_pct >= self.config.min_spread_pct:
                strength = min(spread_pct / 2.0, 1.0)
                vol_confirmed = volume_ratio >= self.config.volume_threshold
                confidence = strength * (1.2 if vol_confirmed else 0.8)
                confidence = min(confidence, 1.0)

                signals.append(AugMACrossResult(
                    signal=AugMACrossSignal.BUY,
                    fast_ma=curr_fast,
                    slow_ma=curr_slow,
                    spread_pct=spread_pct,
                    volume_ratio=volume_ratio,
                    strength=strength,
                    confidence=confidence,
                    timestamp=datetime.now(timezone.utc),
                    metadata={"crossover": "golden_cross", "volume_confirmed": vol_confirmed},
                ))

        # Death cross: fast crosses below slow
        elif prev_fast >= prev_slow and curr_fast < curr_slow:
            if spread_pct >= self.config.min_spread_pct:
                strength = min(spread_pct / 2.0, 1.0)
                vol_confirmed = volume_ratio >= self.config.volume_threshold
                confidence = strength * (1.2 if vol_confirmed else 0.8)
                confidence = min(confidence, 1.0)

                signals.append(AugMACrossResult(
                    signal=AugMACrossSignal.SELL,
                    fast_ma=curr_fast,
                    slow_ma=curr_slow,
                    spread_pct=spread_pct,
                    volume_ratio=volume_ratio,
                    strength=strength,
                    confidence=confidence,
                    timestamp=datetime.now(timezone.utc),
                    metadata={"crossover": "death_cross", "volume_confirmed": vol_confirmed},
                ))

        return signals

    def get_current_values(self, data: pd.DataFrame) -> Dict[str, float]:
        """Return current MA values."""
        if len(data) < max(self.config.fast_period, self.config.slow_period):
            return {"fast_ma": 0.0, "slow_ma": 0.0, "spread": 0.0}

        close = data["close"]
        fast_ma = self._calculate_ma(close, self.config.fast_period)
        slow_ma = self._calculate_ma(close, self.config.slow_period)
        return {
            "fast_ma": float(fast_ma.iloc[-1]),
            "slow_ma": float(slow_ma.iloc[-1]),
            "spread": float(abs(fast_ma.iloc[-1] - slow_ma.iloc[-1]) / slow_ma.iloc[-1] * 100),
        }
