"""Augmented institutional strategy with pillar-score-based signal generation.

Extends BaseInstitutionalStrategy with a 5-pillar scoring framework:
1. Signal pillar   -- raw signal quality
2. Risk pillar     -- risk-adjusted confidence
3. Regime pillar   -- market regime alignment
4. Execution pillar -- execution feasibility
5. Performance pillar -- historical performance factor
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from .base_institutional_strategy import (
    BaseInstitutionalStrategy,
    InstitutionalConfig,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class AugmentedConfig:
    """Configuration for AugmentedBaseInstitutionalStrategy.

    Intentionally a standalone dataclass so it works even when
    InstitutionalConfig is mocked during testing.
    """

    name: str = "AugmentedInstitutionalStrategy"
    symbol: str = ""
    max_position_pct: float = 0.02
    stop_loss_pct: float = 0.02
    take_profit_pct: float = 0.04
    signal_threshold: float = 0.5
    sma_period: int = 20
    atr_period: int = 14
    lookback: int = 60
    pillar_weights: Dict[str, float] = field(default_factory=lambda: {
        "signal": 0.30,
        "risk": 0.25,
        "regime": 0.20,
        "execution": 0.15,
        "performance": 0.10,
    })


# ---------------------------------------------------------------------------
# Pillar score container
# ---------------------------------------------------------------------------


@dataclass
class PillarScores:
    """Scores for each pillar, all in [0, 1]."""

    signal: float = 0.0
    risk: float = 0.0
    regime: float = 0.0
    execution: float = 0.0
    performance: float = 0.0

    def weighted_score(self, weights: Optional[Dict[str, float]] = None) -> float:
        """Return weighted aggregate of all pillars."""
        w = weights or {
            "signal": 0.30,
            "risk": 0.25,
            "regime": 0.20,
            "execution": 0.15,
            "performance": 0.10,
        }
        total = (
            w.get("signal", 0) * self.signal
            + w.get("risk", 0) * self.risk
            + w.get("regime", 0) * self.regime
            + w.get("execution", 0) * self.execution
            + w.get("performance", 0) * self.performance
        )
        return min(max(total, 0.0), 1.0)

    def to_dict(self) -> Dict[str, float]:
        return {
            "signal": self.signal,
            "risk": self.risk,
            "regime": self.regime,
            "execution": self.execution,
            "performance": self.performance,
            "composite": self.weighted_score(),
        }


# ---------------------------------------------------------------------------
# Augmented signal
# ---------------------------------------------------------------------------


@dataclass
class AugmentedSignal:
    """Signal enriched with pillar scores."""

    direction: str  # "buy", "sell", "hold"
    confidence: float  # composite pillar score [0, 1]
    strength: float  # signal magnitude [0, 1]
    pillars: PillarScores = field(default_factory=PillarScores)
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------


class AugmentedBaseInstitutionalStrategy(BaseInstitutionalStrategy):
    """Institutional strategy augmented with 5-pillar scoring.

    Overrides the abstract methods from BaseInstitutionalStrategy and adds
    ``generate_augmented_signals`` which returns AugmentedSignal objects
    with pillar scores.
    """

    def __init__(self, config: Optional[AugmentedConfig] = None):
        self._aug_config = config or AugmentedConfig()
        # Set attributes that the real BaseInstitutionalStrategy would set
        self.config = self._aug_config
        self._position = 0
        self._entry_price: Optional[float] = None
        self._entry_time = None
        self._performance_history: List[float] = []

    # -- Methods that would be inherited from real BaseInstitutionalStrategy --

    def is_in_position(self) -> bool:
        """Check if strategy has an open position."""
        return self._position != 0

    def reset(self) -> None:
        """Reset strategy state."""
        self._position = 0
        self._entry_price = None
        self._entry_time = None
        self._performance_history = []

    # -- BaseInstitutionalStrategy abstract method implementations -----------

    def generate_signals(self, data: pd.DataFrame) -> List[Dict[str, Any]]:
        """Generate standard signals (dict form) from OHLCV data.

        Returns empty list when data is insufficient.
        """
        augmented = self.generate_augmented_signals(data)
        results: List[Dict[str, Any]] = []
        for sig in augmented:
            results.append({
                "direction": sig.direction,
                "confidence": sig.confidence,
                "strength": sig.strength,
                "pillars": sig.pillars.to_dict(),
                "metadata": sig.metadata,
            })
        return results

    def calculate_position_size(self, account_value: float, price: float) -> float:
        """Calculate position size using pillar-adjusted sizing."""
        if price <= 0 or account_value <= 0:
            return 0.0
        max_pct = self.config.max_position_pct
        # Use composite confidence to scale position
        if self._performance_history:
            recent_perf = np.mean(self._performance_history[-20:])
            scale = min(recent_perf + 0.5, 1.0)
        else:
            scale = 1.0
        return account_value * max_pct * scale / price

    # -- Augmented signal generation -----------------------------------------

    def generate_augmented_signals(self, data: pd.DataFrame) -> List[AugmentedSignal]:
        """Generate augmented signals with pillar scores.

        Args:
            data: OHLCV DataFrame.

        Returns:
            List of AugmentedSignal (at most one signal per call).
            Empty list when data is insufficient.
        """
        min_rows = max(self._aug_config.sma_period, self._aug_config.atr_period, 2)
        if len(data) < min_rows:
            return []

        close = data["close"]

        # ----- Compute pillar scores -----
        pillars = self.calculate_pillar_scores(data)

        composite = pillars.weighted_score(self._aug_config.pillar_weights)

        # ----- Determine direction -----
        # Use short-term momentum as the raw direction indicator
        momentum = self._compute_momentum(data)
        if composite >= self._aug_config.signal_threshold:
            if momentum > 0:
                direction = "buy"
            elif momentum < 0:
                direction = "sell"
            else:
                direction = "hold"
        else:
            direction = "hold"

        strength = min(abs(momentum) * composite, 1.0)

        # Track performance
        self._performance_history.append(composite)
        if len(self._performance_history) > 200:
            self._performance_history = self._performance_history[-200:]

        signal = AugmentedSignal(
            direction=direction,
            confidence=composite,
            strength=strength,
            pillars=pillars,
            metadata={"momentum": momentum},
        )
        return [signal]

    def calculate_pillar_scores(self, data: pd.DataFrame) -> PillarScores:
        """Calculate the five pillar scores from OHLCV data.

        Each score is in [0, 1].

        Args:
            data: OHLCV DataFrame.

        Returns:
            PillarScores instance.
        """
        close = data["close"]
        sma_period = self._aug_config.sma_period

        # 1. Signal pillar -- how far price deviates from SMA (normalised)
        sma = close.rolling(sma_period).mean()
        if len(sma.dropna()) == 0:
            sig_score = 0.5
        else:
            current_sma = sma.iloc[-1]
            if pd.isna(current_sma) or current_sma == 0:
                sig_score = 0.5
            else:
                deviation = abs(close.iloc[-1] - current_sma) / current_sma
                sig_score = min(deviation * 10, 1.0)

        # 2. Risk pillar -- inverse of normalised ATR (lower vol = higher score)
        risk_score = self._compute_risk_score(data)

        # 3. Regime pillar -- simple trend alignment
        regime_score = self._compute_regime_score(data)

        # 4. Execution pillar -- volume confirms signal
        exec_score = self._compute_execution_score(data)

        # 5. Performance pillar -- recent performance
        if self._performance_history:
            perf_score = np.mean(self._performance_history[-20:])
        else:
            perf_score = 0.5

        return PillarScores(
            signal=sig_score,
            risk=risk_score,
            regime=regime_score,
            execution=exec_score,
            performance=perf_score,
        )

    def get_current_values(self, data: pd.DataFrame) -> Dict[str, Any]:
        """Return current indicator values for display.

        Returns empty dict when data is insufficient.
        """
        min_rows = max(self._aug_config.sma_period, 2)
        if len(data) < min_rows:
            return {}

        pillars = self.calculate_pillar_scores(data)
        values = pillars.to_dict()
        values["momentum"] = self._compute_momentum(data)
        values["position"] = self._position
        return values

    # -- private helpers -----------------------------------------------------

    @staticmethod
    def _compute_momentum(data: pd.DataFrame, period: int = 10) -> float:
        """Simple rate-of-change momentum."""
        close = data["close"]
        if len(close) < period + 1:
            return 0.0
        roc = (close.iloc[-1] - close.iloc[-period - 1]) / close.iloc[-period - 1]
        return float(np.clip(roc, -1.0, 1.0))

    def _compute_risk_score(self, data: pd.DataFrame) -> float:
        """Risk pillar: higher when volatility is low."""
        close = data["close"]
        atr_period = self._aug_config.atr_period
        if len(close) < atr_period + 1:
            return 0.5

        # Simple ATR approximation using close returns std
        returns = close.pct_change().dropna()
        if len(returns) < atr_period:
            return 0.5
        vol = returns.tail(atr_period).std()
        if pd.isna(vol):
            return 0.5
        # Lower vol -> higher score; 0.02 (2% daily vol) maps to ~0.7
        return float(min(1.0, max(0.0, 1.0 - vol * 20)))

    def _compute_regime_score(self, data: pd.DataFrame) -> float:
        """Regime pillar: alignment between short and long trend."""
        close = data["close"]
        sma_short = close.rolling(10).mean()
        sma_long = close.rolling(self._aug_config.sma_period).mean()

        if len(sma_short.dropna()) == 0 or len(sma_long.dropna()) == 0:
            return 0.5

        short_val = sma_short.iloc[-1]
        long_val = sma_long.iloc[-1]

        if pd.isna(short_val) or pd.isna(long_val) or long_val == 0:
            return 0.5

        # Aligned (same direction) -> higher score
        pct_diff = (short_val - long_val) / long_val
        return float(min(1.0, max(0.0, 0.5 + pct_diff * 10)))

    @staticmethod
    def _compute_execution_score(data: pd.DataFrame) -> float:
        """Execution pillar: volume health."""
        if "volume" not in data.columns:
            return 0.5
        volume = data["volume"]
        if len(volume) < 20:
            return 0.5

        avg_vol = volume.tail(20).mean()
        current_vol = volume.iloc[-1]
        if avg_vol == 0:
            return 0.5

        vol_ratio = current_vol / avg_vol
        # Healthy volume (around 1x average) -> high score
        if vol_ratio <= 0:
            return 0.1
        return float(min(1.0, max(0.1, 1.0 - abs(vol_ratio - 1.0) * 0.5)))
