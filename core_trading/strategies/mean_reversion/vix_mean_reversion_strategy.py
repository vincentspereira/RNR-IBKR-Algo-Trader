"""VIX Mean Reversion Strategy - Uses volatility proxy (ATR-based) for mean reversion signals."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class VIXSignal(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class VIXConfig:
    atr_period: int = 14
    lookback_period: int = 20
    vol_spike_threshold: float = 1.5
    vol_calm_threshold: float = 0.7


@dataclass
class VIXResult:
    signal: VIXSignal
    vol_ratio: float
    atr_value: float
    strength: float
    confidence: float
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


class VIXMeanReversionStrategy:
    """VIX/volatility mean reversion strategy.

    Uses ATR as a volatility proxy. When volatility spikes, expect mean reversion
    (BUY after vol spike calms). When volatility is unusually low, expect expansion
    (caution/SELL signal).
    """

    def __init__(self, config: Optional[VIXConfig] = None):
        self.config = config or VIXConfig()
        self.logger = logging.getLogger(self.__class__.__name__)

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

    def generate_signals(self, data: pd.DataFrame) -> List[VIXResult]:
        """Generate VIX/volatility mean reversion signals."""
        min_required = self.config.atr_period + self.config.lookback_period
        if len(data) < min_required:
            return []

        atr = self._calculate_atr(data)
        if np.isnan(atr.iloc[-1]):
            return []

        curr_atr = float(atr.iloc[-1])
        avg_atr = float(atr.iloc[-self.config.lookback_period:].mean())
        vol_ratio = curr_atr / (avg_atr + 1e-10)

        close = data["close"]
        curr_price = float(close.iloc[-1])
        prev_price = float(close.iloc[-2])

        signals = []

        # Volatility spike followed by price stabilization -> BUY
        if vol_ratio > self.config.vol_spike_threshold and curr_price > prev_price:
            strength = min((vol_ratio - self.config.vol_spike_threshold) / self.config.vol_spike_threshold, 1.0)
            signals.append(VIXResult(
                signal=VIXSignal.BUY,
                vol_ratio=vol_ratio,
                atr_value=curr_atr,
                strength=strength,
                confidence=min(strength * 1.1, 1.0),
                timestamp=datetime.now(timezone.utc),
                metadata={"condition": "vol_spike_stabilizing"},
            ))

        # Very low volatility -> caution/SELL (expect expansion)
        elif vol_ratio < self.config.vol_calm_threshold:
            strength = min((self.config.vol_calm_threshold - vol_ratio) / self.config.vol_calm_threshold, 1.0)
            signals.append(VIXResult(
                signal=VIXSignal.SELL,
                vol_ratio=vol_ratio,
                atr_value=curr_atr,
                strength=strength,
                confidence=min(strength * 0.8, 1.0),
                timestamp=datetime.now(timezone.utc),
                metadata={"condition": "low_volatility_warning"},
            ))

        return signals

    def get_current_values(self, data: pd.DataFrame) -> Dict[str, float]:
        """Return current volatility proxy values."""
        if len(data) < self.config.atr_period:
            return {"atr": 0.0, "vol_ratio": 1.0}

        atr = self._calculate_atr(data)
        curr_atr = atr.iloc[-1]
        if np.isnan(curr_atr):
            return {"atr": 0.0, "vol_ratio": 1.0}

        lookback = min(self.config.lookback_period, len(atr.dropna()))
        if lookback < 2:
            return {"atr": float(curr_atr), "vol_ratio": 1.0}

        avg_atr = float(atr.iloc[-lookback:].mean())
        return {
            "atr": float(curr_atr),
            "vol_ratio": float(curr_atr) / (avg_atr + 1e-10),
        }
