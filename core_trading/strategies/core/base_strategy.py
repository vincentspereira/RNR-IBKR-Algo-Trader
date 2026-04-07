"""Base strategy class and types for the trading system."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

import pandas as pd


class SignalType(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    EXIT_LONG = "exit_long"
    EXIT_SHORT = "exit_short"


class PositionSide(Enum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


@dataclass
class Signal:
    """Trading signal."""
    signal_type: SignalType
    symbol: str = ""
    price: float = 0.0
    quantity: float = 1.0
    strength: float = 0.0
    confidence: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StrategyConfig:
    """Base strategy configuration."""
    name: str = "BaseStrategy"
    symbol: str = ""
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Position:
    """Trading position."""
    symbol: str
    side: PositionSide = PositionSide.FLAT
    quantity: float = 0.0
    entry_price: float = 0.0
    entry_time: Optional[datetime] = None


def create_signal(
    signal_type: SignalType,
    symbol: str = "",
    price: float = 0.0,
    quantity: float = 1.0,
    strength: float = 0.0,
    confidence: float = 0.0,
    metadata: Optional[Dict[str, Any]] = None,
) -> Signal:
    """Factory function to create a Signal."""
    return Signal(
        signal_type=signal_type,
        symbol=symbol,
        price=price,
        quantity=quantity,
        strength=strength,
        confidence=confidence,
        metadata=metadata or {},
    )


def validate_ohlcv_data(data: pd.DataFrame) -> bool:
    """Validate that DataFrame has required OHLCV columns."""
    required = {"open", "high", "low", "close", "volume"}
    return required.issubset(data.columns) and len(data) > 0


class BaseStrategy(ABC):
    """Abstract base class for all trading strategies."""

    def __init__(self, config: Optional[StrategyConfig] = None):
        self.config = config or StrategyConfig()

    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> List[Signal]:
        """Generate trading signals from market data."""
        ...

    def get_current_values(self, data: pd.DataFrame) -> Dict[str, float]:
        """Return current indicator values."""
        return {}
