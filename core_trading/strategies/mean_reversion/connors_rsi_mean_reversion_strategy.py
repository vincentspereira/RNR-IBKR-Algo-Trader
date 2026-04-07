"""Connors RSI Mean Reversion Strategy - Uses Connors RSI (CRSI) for mean reversion signals."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class CRSISignal(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class CRSIConfig:
    rsi_period: int = 3
    streak_period: int = 2
    roc_period: int = 100
    oversold_threshold: float = 15.0
    overbought_threshold: float = 85.0


@dataclass
class CRSIResult:
    signal: CRSISignal
    crsi_value: float
    rsi_component: float
    streak_component: float
    strength: float
    confidence: float
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


class ConnorsRSIMeanReversionStrategy:
    """Connors RSI mean reversion strategy.

    CRSI = (RSI + Streak RSI + Percent Rank) / 3
    Buys when CRSI < oversold, sells when CRSI > overbought.
    """

    def __init__(self, config: Optional[CRSIConfig] = None):
        self.config = config or CRSIConfig()
        self.logger = logging.getLogger(self.__class__.__name__)

    def _calculate_rsi(self, prices: pd.Series, period: int) -> pd.Series:
        """Calculate RSI component."""
        delta = prices.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _calculate_streak(self, prices: pd.Series) -> pd.Series:
        """Calculate price streak (consecutive up/down days)."""
        changes = prices.diff()
        streak = pd.Series(0, index=prices.index, dtype=float)

        for i in range(1, len(prices)):
            if changes.iloc[i] > 0:
                streak.iloc[i] = streak.iloc[i - 1] + 1 if streak.iloc[i - 1] > 0 else 1
            elif changes.iloc[i] < 0:
                streak.iloc[i] = streak.iloc[i - 1] - 1 if streak.iloc[i - 1] < 0 else -1
            else:
                streak.iloc[i] = 0

        return streak

    def _calculate_connors_rsi(self, data: pd.DataFrame) -> Dict[str, pd.Series]:
        """Calculate Connors RSI components and composite."""
        close = data["close"]

        # Component 1: Standard RSI
        rsi = self._calculate_rsi(close, self.config.rsi_period)

        # Component 2: Streak RSI
        streak = self._calculate_streak(close)
        streak_rsi = self._calculate_rsi(streak, self.config.streak_period)

        # Component 3: Percent rank of rate-of-change
        roc = close.pct_change(self.config.roc_period) * 100
        percent_rank = roc.rolling(window=self.config.roc_period).apply(
            lambda x: pd.Series(x).rank(pct=True).iloc[-1] * 100, raw=False
        )

        # Connors RSI composite
        crsi = (rsi + streak_rsi + percent_rank) / 3

        return {"crsi": crsi, "rsi": rsi, "streak_rsi": streak_rsi}

    def generate_signals(self, data: pd.DataFrame) -> List[CRSIResult]:
        """Generate Connors RSI mean reversion signals."""
        min_required = max(self.config.rsi_period + 1, self.config.roc_period)
        if len(data) < min_required:
            return []

        result = self._calculate_connors_rsi(data)
        curr_crsi = float(result["crsi"].iloc[-1])
        prev_crsi = float(result["crsi"].iloc[-2])

        if np.isnan(curr_crsi) or np.isnan(prev_crsi):
            return []

        curr_rsi = float(result["rsi"].iloc[-1])
        curr_streak = float(result["streak_rsi"].iloc[-1])

        signals = []

        # CRSI crosses below oversold threshold -> BUY
        if curr_crsi < self.config.oversold_threshold:
            strength = min((self.config.oversold_threshold - curr_crsi) / self.config.oversold_threshold, 1.0)
            signals.append(CRSIResult(
                signal=CRSISignal.BUY,
                crsi_value=curr_crsi,
                rsi_component=curr_rsi,
                streak_component=curr_streak,
                strength=strength,
                confidence=min(strength * 1.2, 1.0),
                timestamp=datetime.now(timezone.utc),
                metadata={"condition": "oversold"},
            ))

        # CRSI crosses above overbought threshold -> SELL
        elif curr_crsi > self.config.overbought_threshold:
            strength = min((curr_crsi - self.config.overbought_threshold) / (100 - self.config.overbought_threshold), 1.0)
            signals.append(CRSIResult(
                signal=CRSISignal.SELL,
                crsi_value=curr_crsi,
                rsi_component=curr_rsi,
                streak_component=curr_streak,
                strength=strength,
                confidence=min(strength * 1.2, 1.0),
                timestamp=datetime.now(timezone.utc),
                metadata={"condition": "overbought"},
            ))

        return signals

    def get_current_values(self, data: pd.DataFrame) -> Dict[str, float]:
        """Return current Connors RSI values."""
        if len(data) < max(self.config.rsi_period + 1, self.config.roc_period):
            return {"crsi": 50.0}

        result = self._calculate_connors_rsi(data)
        crsi = result["crsi"].iloc[-1]
        return {"crsi": float(crsi) if not np.isnan(crsi) else 50.0}
