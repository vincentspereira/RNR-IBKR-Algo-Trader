"""Base institutional strategy class with 5-pillar architecture support."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd


@dataclass
class InstitutionalConfig:
    """Configuration for institutional strategies."""
    name: str = "InstitutionalStrategy"
    symbol: str = ""
    max_position_pct: float = 0.02
    stop_loss_pct: float = 0.02
    take_profit_pct: float = 0.04
    params: Dict[str, Any] = field(default_factory=dict)


class BaseInstitutionalStrategy(ABC):
    """Base class for institutional-grade strategies.

    Provides framework for:
    - Signal generation with confirmation
    - Dynamic position sizing
    - Risk management integration
    - Performance tracking
    """

    def __init__(self, config: Optional[InstitutionalConfig] = None):
        self.config = config or InstitutionalConfig()
        self._position = 0  # 0=flat, 1=long, -1=short
        self._entry_price: Optional[float] = None
        self._entry_time: Optional[datetime] = None

    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> List[Dict[str, Any]]:
        """Generate trading signals from market data."""
        ...

    @abstractmethod
    def calculate_position_size(self, account_value: float, price: float) -> float:
        """Calculate position size based on risk parameters."""
        ...

    def get_stop_loss(self, entry_price: float, side: int) -> float:
        """Calculate stop loss price."""
        if side > 0:  # long
            return entry_price * (1 - self.config.stop_loss_pct)
        else:  # short
            return entry_price * (1 + self.config.stop_loss_pct)

    def get_take_profit(self, entry_price: float, side: int) -> float:
        """Calculate take profit price."""
        if side > 0:  # long
            return entry_price * (1 + self.config.take_profit_pct)
        else:  # short
            return entry_price * (1 - self.config.take_profit_pct)

    def is_in_position(self) -> bool:
        """Check if strategy has an open position."""
        return self._position != 0

    def reset(self):
        """Reset strategy state."""
        self._position = 0
        self._entry_price = None
        self._entry_time = None
