"""RSI(2) Mean Reversion Strategy - Enhanced RSI(2) with regime detection."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class RSI2MRSignal(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class MarketRegime(Enum):
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    MEAN_REVERTING = "mean_reverting"
    VOLATILE = "volatile"
    UNKNOWN = "unknown"


@dataclass
class RSI2MRConfig:
    rsi_period: int = 2
    sma_period: int = 200
    oversold: float = 10.0
    overbought: float = 90.0
    regime_lookback: int = 50


@dataclass
class RSI2MRResult:
    signal: RSI2MRSignal
    rsi_value: float
    regime: MarketRegime
    strength: float
    confidence: float
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


class RSI2MeanReversionStrategy:
    """Enhanced RSI(2) mean reversion strategy with regime detection.

    Adapts thresholds based on detected market regime:
    - Mean-reverting regime: standard thresholds
    - Trending regime: tighter thresholds
    - Volatile regime: wider thresholds
    """

    def __init__(self, config: Optional[RSI2MRConfig] = None):
        self.config = config or RSI2MRConfig()
        self.logger = logging.getLogger(self.__class__.__name__)

    def _calculate_rsi(self, prices: pd.Series, period: int) -> pd.Series:
        """Calculate RSI."""
        delta = prices.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _detect_regime(self, data: pd.DataFrame) -> MarketRegime:
        """Detect market regime based on price action."""
        if len(data) < self.config.regime_lookback:
            return MarketRegime.UNKNOWN

        close = data["close"].iloc[-self.config.regime_lookback:]
        returns = close.pct_change().dropna()

        if len(returns) < 10:
            return MarketRegime.UNKNOWN

        volatility = float(returns.std()) * np.sqrt(252)
        trend = float((close.iloc[-1] - close.iloc[0]) / close.iloc[0])
        sma20 = close.rolling(20).mean()
        sma50 = close.rolling(min(50, len(close))).mean()

        if volatility > 0.30:
            return MarketRegime.VOLATILE
        elif abs(trend) > 0.10 and len(sma20.dropna()) > 1 and len(sma50.dropna()) > 1:
            if sma20.iloc[-1] > sma50.iloc[-1]:
                return MarketRegime.TRENDING_UP
            else:
                return MarketRegime.TRENDING_DOWN
        else:
            return MarketRegime.MEAN_REVERTING

    def _get_regime_thresholds(self, regime: MarketRegime):
        """Get adjusted oversold/overbought thresholds based on regime."""
        oversold = self.config.oversold
        overbought = self.config.overbought

        if regime == MarketRegime.VOLATILE:
            oversold = max(5.0, oversold - 5.0)
            overbought = min(95.0, overbought + 5.0)
        elif regime in (MarketRegime.TRENDING_UP, MarketRegime.TRENDING_DOWN):
            oversold = min(15.0, oversold + 3.0)
            overbought = max(85.0, overbought - 3.0)

        return oversold, overbought

    def generate_signals(self, data: pd.DataFrame) -> List[RSI2MRResult]:
        """Generate RSI(2) mean reversion signals with regime adaptation."""
        min_required = max(self.config.rsi_period + 1, self.config.sma_period)
        if len(data) < min_required:
            return []

        close = data["close"]
        rsi = self._calculate_rsi(close, self.config.rsi_period)
        sma = close.rolling(window=self.config.sma_period).mean()
        regime = self._detect_regime(data)
        oversold, overbought = self._get_regime_thresholds(regime)

        curr_rsi = float(rsi.iloc[-1])
        curr_price = float(close.iloc[-1])
        curr_sma = float(sma.iloc[-1])

        if np.isnan(curr_rsi) or np.isnan(curr_sma):
            return []

        signals = []

        if curr_rsi < oversold and curr_price > curr_sma:
            strength = min((oversold - curr_rsi) / oversold, 1.0)
            confidence = strength * 1.2
            if regime == MarketRegime.MEAN_REVERTING:
                confidence *= 1.1
            elif regime == MarketRegime.VOLATILE:
                confidence *= 0.8

            signals.append(RSI2MRResult(
                signal=RSI2MRSignal.BUY,
                rsi_value=curr_rsi,
                regime=regime,
                strength=min(strength, 1.0),
                confidence=min(confidence, 1.0),
                timestamp=datetime.now(timezone.utc),
                metadata={"condition": "oversold_uptrend", "oversold_threshold": oversold},
            ))

        elif curr_rsi > overbought and curr_price < curr_sma:
            strength = min((curr_rsi - overbought) / (100 - overbought), 1.0)
            confidence = strength * 1.2
            if regime == MarketRegime.MEAN_REVERTING:
                confidence *= 1.1
            elif regime == MarketRegime.VOLATILE:
                confidence *= 0.8

            signals.append(RSI2MRResult(
                signal=RSI2MRSignal.SELL,
                rsi_value=curr_rsi,
                regime=regime,
                strength=min(strength, 1.0),
                confidence=min(confidence, 1.0),
                timestamp=datetime.now(timezone.utc),
                metadata={"condition": "overbought_downtrend", "overbought_threshold": overbought},
            ))

        return signals

    def get_current_values(self, data: pd.DataFrame) -> Dict[str, float]:
        """Return current RSI(2) and regime information."""
        if len(data) < self.config.rsi_period + 1:
            return {"rsi2": 50.0}

        rsi = self._calculate_rsi(data["close"], self.config.rsi_period)
        val = rsi.iloc[-1]
        regime = self._detect_regime(data)
        return {
            "rsi2": float(val) if not np.isnan(val) else 50.0,
            "regime": regime.value,
        }
