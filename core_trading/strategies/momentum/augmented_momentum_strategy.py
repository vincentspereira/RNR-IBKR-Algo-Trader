"""Augmented Momentum Strategy - Multi-factor momentum with trend and volume confirmation."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class AugMomentumSignal(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class AugMomentumConfig:
    lookback_period: int = 20
    roc_period: int = 10
    volume_ma_period: int = 20
    volume_threshold: float = 1.2


@dataclass
class AugMomentumResult:
    signal: AugMomentumSignal
    momentum_score: float
    trend_alignment: bool
    volume_confirmation: bool
    strength: float
    confidence: float
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


class AugmentedMomentumStrategy:
    """Augmented momentum strategy combining rate of change with trend and volume confirmation."""

    def __init__(self, config: Optional[AugMomentumConfig] = None):
        self.config = config or AugMomentumConfig()
        self.logger = logging.getLogger(self.__class__.__name__)

    def generate_signals(self, data: pd.DataFrame) -> List[AugMomentumResult]:
        """Generate augmented momentum signals."""
        min_required = max(self.config.lookback_period, self.config.roc_period, self.config.volume_ma_period) + 1
        if len(data) < min_required:
            return []

        close = data["close"]
        volume = data["volume"]

        # Rate of change
        roc = close.pct_change(periods=self.config.roc_period) * 100
        curr_roc = float(roc.iloc[-1])

        # Trend alignment: short MA vs long MA
        short_ma = close.rolling(window=self.config.lookback_period // 2).mean()
        long_ma = close.rolling(window=self.config.lookback_period).mean()
        trend_up = float(short_ma.iloc[-1]) > float(long_ma.iloc[-1])

        # Volume confirmation
        vol_ma = volume.rolling(window=self.config.volume_ma_period).mean()
        vol_confirmed = float(volume.iloc[-1]) > float(vol_ma.iloc[-1]) * self.config.volume_threshold

        if np.isnan(curr_roc):
            return []

        signals = []

        # Strong positive momentum with trend alignment -> BUY
        if curr_roc > 0 and trend_up:
            momentum_score = curr_roc
            strength = min(abs(curr_roc) / 10.0, 1.0)
            confidence = strength * (1.2 if vol_confirmed else 0.9)

            signals.append(AugMomentumResult(
                signal=AugMomentumSignal.BUY,
                momentum_score=momentum_score,
                trend_alignment=trend_up,
                volume_confirmation=vol_confirmed,
                strength=min(strength, 1.0),
                confidence=min(confidence, 1.0),
                timestamp=datetime.now(timezone.utc),
                metadata={"roc": curr_roc},
            ))

        # Strong negative momentum against trend -> SELL
        elif curr_roc < 0 and not trend_up:
            momentum_score = curr_roc
            strength = min(abs(curr_roc) / 10.0, 1.0)
            confidence = strength * (1.2 if vol_confirmed else 0.9)

            signals.append(AugMomentumResult(
                signal=AugMomentumSignal.SELL,
                momentum_score=momentum_score,
                trend_alignment=not trend_up,
                volume_confirmation=vol_confirmed,
                strength=min(strength, 1.0),
                confidence=min(confidence, 1.0),
                timestamp=datetime.now(timezone.utc),
                metadata={"roc": curr_roc},
            ))

        return signals

    def get_current_values(self, data: pd.DataFrame) -> Dict[str, float]:
        """Return current momentum values."""
        if len(data) < self.config.roc_period + 1:
            return {"roc": 0.0}

        roc = data["close"].pct_change(periods=self.config.roc_period) * 100
        val = roc.iloc[-1]
        return {"roc": float(val) if not np.isnan(val) else 0.0}
