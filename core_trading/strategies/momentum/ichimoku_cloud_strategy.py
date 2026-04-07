"""Ichimoku Cloud Strategy - Uses Ichimoku Kinko Hyo indicator for trend identification."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class IchimokuSignal(Enum):
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    STRONG_SELL = "strong_sell"


@dataclass
class IchimokuResult:
    signal: IchimokuSignal
    tenkan_sen: float
    kijun_sen: float
    senkou_span_a: float
    senkou_span_b: float
    chikou_span: float
    strength: float
    confidence: float
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class IchimokuConfig:
    tenkan_period: int = 9
    kijun_period: int = 26
    senkou_b_period: int = 52
    displacement: int = 26


class IchimokuCloudStrategy:
    """Ichimoku Cloud strategy with multi-signal confirmation."""

    def __init__(self, config: Optional[IchimokuConfig] = None):
        self.config = config or IchimokuConfig()
        self.logger = logging.getLogger(self.__class__.__name__)

    def _calculate_ichimoku(self, data: pd.DataFrame) -> Dict[str, pd.Series]:
        """Calculate all Ichimoku components."""
        high = data["high"]
        low = data["low"]
        close = data["close"]

        # Tenkan-sen (Conversion Line): (highest high + lowest low) / 2 over tenkan_period
        tenkan_high = high.rolling(window=self.config.tenkan_period).max()
        tenkan_low = low.rolling(window=self.config.tenkan_period).min()
        tenkan_sen = (tenkan_high + tenkan_low) / 2

        # Kijun-sen (Base Line): (highest high + lowest low) / 2 over kijun_period
        kijun_high = high.rolling(window=self.config.kijun_period).max()
        kijun_low = low.rolling(window=self.config.kijun_period).min()
        kijun_sen = (kijun_high + kijun_low) / 2

        # Senkou Span A (Leading Span A): (Tenkan + Kijun) / 2, displaced forward
        senkou_span_a = ((tenkan_sen + kijun_sen) / 2).shift(self.config.displacement)

        # Senkou Span B (Leading Span B): (highest high + lowest low) / 2 over senkou_b_period, displaced
        senkou_high = high.rolling(window=self.config.senkou_b_period).max()
        senkou_low = low.rolling(window=self.config.senkou_b_period).min()
        senkou_span_b = ((senkou_high + senkou_low) / 2).shift(self.config.displacement)

        # Chikou Span (Lagging Span): close displaced backward
        chikou_span = close.shift(-self.config.displacement)

        return {
            "tenkan_sen": tenkan_sen,
            "kijun_sen": kijun_sen,
            "senkou_span_a": senkou_span_a,
            "senkou_span_b": senkou_span_b,
            "chikou_span": chikou_span,
        }

    def generate_signals(self, data: pd.DataFrame) -> List[IchimokuResult]:
        """Generate Ichimoku trading signals."""
        min_required = self.config.senkou_b_period + self.config.displacement
        if len(data) < min_required:
            return []

        indicators = self._calculate_ichimoku(data)
        close = data["close"]

        signals = []
        idx = -1 - self.config.displacement
        if abs(idx) >= len(data):
            return []

        price = float(close.iloc[idx])
        tenkan = float(indicators["tenkan_sen"].iloc[idx])
        kijun = float(indicators["kijun_sen"].iloc[idx])
        span_a = float(indicators["senkou_span_a"].iloc[idx])
        span_b = float(indicators["senkou_span_b"].iloc[idx])

        if np.isnan(span_a) or np.isnan(span_b):
            return []

        # Cloud color (green = span_a > span_b, red = span_b > span_a)
        cloud_bullish = span_a > span_b
        cloud_top = max(span_a, span_b)
        cloud_bottom = min(span_a, span_b)

        # TK cross
        tk_bullish = tenkan > kijun

        # Price vs cloud
        above_cloud = price > cloud_top
        below_cloud = price < cloud_bottom
        in_cloud = not above_cloud and not below_cloud

        # Signal determination
        signal = IchimokuSignal.HOLD
        strength = 0.0

        if above_cloud and tk_bullish and cloud_bullish:
            signal = IchimokuSignal.STRONG_BUY
            strength = min(abs(price - cloud_top) / (cloud_top + 1e-10) * 10, 1.0)
        elif above_cloud and tk_bullish:
            signal = IchimokuSignal.BUY
            strength = 0.5
        elif below_cloud and not tk_bullish and not cloud_bullish:
            signal = IchimokuSignal.STRONG_SELL
            strength = min(abs(cloud_bottom - price) / (price + 1e-10) * 10, 1.0)
        elif below_cloud and not tk_bullish:
            signal = IchimokuSignal.SELL
            strength = 0.5
        elif in_cloud:
            signal = IchimokuSignal.HOLD
            strength = 0.2

        confidence = min(strength * 1.2, 1.0)

        signals.append(IchimokuResult(
            signal=signal,
            tenkan_sen=tenkan,
            kijun_sen=kijun,
            senkou_span_a=span_a,
            senkou_span_b=span_b,
            chikou_span=float(close.iloc[idx]),
            strength=strength,
            confidence=confidence,
            timestamp=datetime.now(timezone.utc),
            metadata={
                "above_cloud": above_cloud,
                "below_cloud": below_cloud,
                "cloud_bullish": cloud_bullish,
                "tk_cross_bullish": tk_bullish,
            },
        ))

        return signals

    def get_current_values(self, data: pd.DataFrame) -> Dict[str, float]:
        """Return current Ichimoku indicator values."""
        if len(data) < self.config.senkou_b_period:
            return {k: 0.0 for k in ["tenkan", "kijun", "span_a", "span_b"]}

        indicators = self._calculate_ichimoku(data)
        idx = -1
        return {
            "tenkan": float(indicators["tenkan_sen"].iloc[idx]),
            "kijun": float(indicators["kijun_sen"].iloc[idx]),
            "span_a": float(indicators["senkou_span_a"].iloc[idx]) if not np.isnan(indicators["senkou_span_a"].iloc[idx]) else 0.0,
            "span_b": float(indicators["senkou_span_b"].iloc[idx]) if not np.isnan(indicators["senkou_span_b"].iloc[idx]) else 0.0,
        }
