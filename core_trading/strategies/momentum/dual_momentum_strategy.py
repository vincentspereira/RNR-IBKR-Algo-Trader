"""Dual Momentum Strategy - Combines absolute and relative momentum."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class DualMomentumSignal(Enum):
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    STRONG_SELL = "strong_sell"


@dataclass
class DualMomentumResult:
    signal: DualMomentumSignal
    absolute_momentum: float
    relative_momentum: float
    combined_score: float
    strength: float
    confidence: float
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DualMomentumConfig:
    lookback_period: int = 12
    absolute_threshold: float = 0.0
    relative_weight: float = 0.4
    absolute_weight: float = 0.6


class DualMomentumStrategy:
    """Dual momentum combining absolute (time-series) and relative momentum."""

    def __init__(self, config: Optional[DualMomentumConfig] = None):
        self.config = config or DualMomentumConfig()
        self.logger = logging.getLogger(self.__class__.__name__)

    def generate_signals(
        self,
        data: pd.DataFrame,
        benchmark_data: Optional[pd.DataFrame] = None,
    ) -> List[DualMomentumResult]:
        """Generate dual momentum signals."""
        if len(data) < self.config.lookback_period:
            return []

        close = data["close"]

        # Absolute momentum: current price vs price N periods ago
        curr_price = float(close.iloc[-1])
        past_price = float(close.iloc[-self.config.lookback_period])
        absolute_momentum = (curr_price - past_price) / past_price

        # Relative momentum vs benchmark
        relative_momentum = 0.0
        if benchmark_data is not None and len(benchmark_data) >= self.config.lookback_period:
            bench_close = benchmark_data["close"]
            bench_curr = float(bench_close.iloc[-1])
            bench_past = float(bench_close.iloc[-self.config.lookback_period])
            bench_return = (bench_curr - bench_past) / bench_past
            relative_momentum = absolute_momentum - bench_return

        # Combined score
        combined_score = (
            self.config.absolute_weight * absolute_momentum
            + self.config.relative_weight * relative_momentum
        )

        # Signal determination
        threshold = self.config.absolute_threshold
        signal = DualMomentumSignal.HOLD

        if absolute_momentum > threshold and relative_momentum > 0:
            if combined_score > 0.05:
                signal = DualMomentumSignal.STRONG_BUY
            else:
                signal = DualMomentumSignal.BUY
        elif absolute_momentum < -threshold and relative_momentum < 0:
            if combined_score < -0.05:
                signal = DualMomentumSignal.STRONG_SELL
            else:
                signal = DualMomentumSignal.SELL

        strength = min(abs(combined_score) * 10, 1.0)
        confidence = min(strength * 1.1, 1.0)

        return [DualMomentumResult(
            signal=signal,
            absolute_momentum=absolute_momentum,
            relative_momentum=relative_momentum,
            combined_score=combined_score,
            strength=strength,
            confidence=confidence,
            timestamp=datetime.now(timezone.utc),
            metadata={
                "lookback_period": self.config.lookback_period,
                "has_benchmark": benchmark_data is not None,
            },
        )]

    def get_current_values(self, data: pd.DataFrame) -> Dict[str, float]:
        """Return current momentum values."""
        if len(data) < self.config.lookback_period:
            return {"absolute": 0.0, "combined": 0.0}

        close = data["close"]
        absolute = (close.iloc[-1] - close.iloc[-self.config.lookback_period]) / close.iloc[-self.config.lookback_period]
        return {"absolute": float(absolute), "combined": float(absolute)}
