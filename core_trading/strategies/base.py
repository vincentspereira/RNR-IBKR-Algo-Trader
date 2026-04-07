"""Base strategy class providing common interface for all strategies."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


class SignalType(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class Signal:
    """Trading signal."""
    signal_type: SignalType
    symbol: str = ""
    price: float = 0.0
    strength: float = 0.0
    confidence: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StrategyConfig:
    """Base configuration for all strategies."""
    name: str = "BaseStrategy"
    symbol: str = ""
    params: Dict[str, Any] = field(default_factory=dict)


class BaseStrategy(ABC):
    """Abstract base class for all trading strategies."""

    def __init__(self, config: Optional[StrategyConfig] = None):
        self.config = config or StrategyConfig()
        self.logger = logging.getLogger(self.__class__.__name__)

    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> List[Signal]:
        """Generate trading signals from market data."""
        ...

    def get_current_values(self, data: pd.DataFrame) -> Dict[str, float]:
        """Return current indicator values."""
        return {}

    @staticmethod
    def validate_ohlcv_data(data: pd.DataFrame) -> bool:
        """Validate that data has required OHLCV columns."""
        required = {"open", "high", "low", "close", "volume"}
        return required.issubset(data.columns) and len(data) > 0
