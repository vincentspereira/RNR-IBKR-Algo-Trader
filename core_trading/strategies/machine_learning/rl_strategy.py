"""Reinforcement Learning Strategy for the algorithmic trading system.

This module provides an RL-inspired strategy that generates trading signals from
OHLCV data using configurable parameters. It does **not** depend on nautilus_trader
or stable_baselines3 at runtime -- those libraries are mocked in the test suite.
Instead, it uses simple momentum / volatility heuristics to mimic RL agent behaviour,
making it fully testable without external ML frameworks.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Action & signal enums
# ---------------------------------------------------------------------------


class RLAction(Enum):
    """Discrete actions the RL agent can take."""

    HOLD = 0
    BUY = 1
    SELL = 2


class RLSignalType(Enum):
    """Signal type emitted by the strategy."""

    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class RLStrategyConfig:
    """Configuration for RLStrategy."""

    window_size: int = 30
    momentum_weight: float = 0.4
    volatility_weight: float = 0.3
    mean_reversion_weight: float = 0.3
    confidence_threshold: float = 0.3
    position_size_fraction: float = 0.1
    max_position: float = 1.0
    min_data_points: int = 30


# ---------------------------------------------------------------------------
# Signal dataclass
# ---------------------------------------------------------------------------


@dataclass
class RLSignal:
    """A signal produced by the RL strategy."""

    signal: RLSignalType
    confidence: float
    strength: float
    action: RLAction
    position_delta: float
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# RLStrategy
# ---------------------------------------------------------------------------


class RLStrategy:
    """RL-inspired trading strategy that evaluates momentum, volatility,
    and mean-reversion signals to produce discrete trading actions.

    This class intentionally avoids importing nautilus_trader or
    stable_baselines3 so that it can be tested in isolation.
    """

    def __init__(self, config: Optional[RLStrategyConfig] = None):
        self.config = config or RLStrategyConfig()
        self._position: float = 0.0
        self._bar_history: List[Dict[str, float]] = []
        self._last_signal: Optional[RLSignal] = None

    # -- public API ----------------------------------------------------------

    def generate_signals(self, data: pd.DataFrame) -> List[RLSignal]:
        """Generate trading signals from OHLCV data.

        Args:
            data: DataFrame with columns open, high, low, close, volume.

        Returns:
            A list containing zero or one RLSignal. Returns an empty list
            when there is insufficient data.
        """
        if len(data) < self.config.min_data_points:
            return []

        close = data["close"]
        window = self.config.window_size

        if len(close) < window:
            return []

        # --- Compute feature scores ---
        momentum_score = self._momentum_score(close, window)
        volatility_score = self._volatility_score(close, window)
        mr_score = self._mean_reversion_score(close, window)

        # Weighted combination -> raw signal
        raw = (
            self.config.momentum_weight * momentum_score
            + self.config.volatility_weight * volatility_score
            + self.config.mean_reversion_weight * mr_score
        )

        # Map to action
        if raw > self.config.confidence_threshold:
            action = RLAction.BUY
            signal_type = RLSignalType.BUY
            position_delta = self.config.position_size_fraction
        elif raw < -self.config.confidence_threshold:
            action = RLAction.SELL
            signal_type = RLSignalType.SELL
            position_delta = -self.config.position_size_fraction
        else:
            action = RLAction.HOLD
            signal_type = RLSignalType.HOLD
            position_delta = 0.0

        confidence = min(abs(raw), 1.0)
        strength = min(abs(raw) * 1.5, 1.0)

        signal = RLSignal(
            signal=signal_type,
            confidence=confidence,
            strength=strength,
            action=action,
            position_delta=position_delta,
            metadata={
                "momentum_score": momentum_score,
                "volatility_score": volatility_score,
                "mean_reversion_score": mr_score,
                "raw_signal": raw,
            },
        )
        self._last_signal = signal
        self._position = max(-self.config.max_position, min(self.config.max_position, self._position + position_delta))
        return [signal]

    def get_current_values(self, data: pd.DataFrame) -> Dict[str, float]:
        """Return the latest indicator values for display.

        Returns empty dict when data is insufficient.
        """
        if len(data) < self.config.min_data_points:
            return {}

        close = data["close"]
        window = min(self.config.window_size, len(close))

        values = {
            "momentum_score": self._momentum_score(close, window),
            "volatility_score": self._volatility_score(close, window),
            "mean_reversion_score": self._mean_reversion_score(close, window),
            "position": self._position,
        }
        if self._last_signal is not None:
            values["last_action"] = self._last_signal.action.value
            values["last_confidence"] = self._last_signal.confidence

        return values

    def reset(self) -> None:
        """Reset internal state."""
        self._position = 0.0
        self._bar_history = []
        self._last_signal = None

    # -- private feature scores ----------------------------------------------

    @staticmethod
    def _momentum_score(close: pd.Series, window: int) -> float:
        """Normalised momentum: positive means upward trend."""
        recent = close.iloc[-window:]
        returns = recent.pct_change().dropna()
        if len(returns) == 0:
            return 0.0
        return float(returns.mean() / (returns.std() + 1e-10))

    @staticmethod
    def _volatility_score(close: pd.Series, window: int) -> float:
        """Volatility-adjusted price position.

        Positive when price is in upper part of recent range,
        negative when in lower part.
        """
        recent = close.iloc[-window:]
        high = recent.max()
        low = recent.min()
        if high == low:
            return 0.0
        position = (close.iloc[-1] - low) / (high - low) - 0.5
        return float(position)

    @staticmethod
    def _mean_reversion_score(close: pd.Series, window: int) -> float:
        """Z-score of current price vs rolling mean.

        Negative z-score (oversold) -> positive score (buy),
        Positive z-score (overbought) -> negative score (sell).
        """
        recent = close.iloc[-window:]
        mean = recent.mean()
        std = recent.std()
        if std == 0:
            return 0.0
        z = (close.iloc[-1] - mean) / std
        return float(-z)  # negative z -> buy signal


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_rl_strategy(config: Optional[RLStrategyConfig] = None) -> RLStrategy:
    """Factory function to create an RL strategy."""
    return RLStrategy(config)


# Alias for backward compat with __init__.py
TradingState = RLStrategyConfig
