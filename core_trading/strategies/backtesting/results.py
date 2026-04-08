"""Backtest results module with handler architecture."""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class BacktestResults:
    """Backtest results using modular handler architecture."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.logger = logger
        self._trades: List[Dict[str, Any]] = []
        self._equity_curve: List[float] = []
        self._metrics: Dict[str, float] = {}

    def process_request(self, request: Any) -> Dict[str, Any]:
        """Process request using appropriate handlers."""
        self.logger.info(f"Processing request with {self.__class__.__name__}")
        return {"status": "processed", "class": self.__class__.__name__}

    def get_status(self) -> Dict[str, Any]:
        """Get status from all handlers."""
        return {
            "main_class": self.__class__.__name__,
            "trades_count": len(self._trades),
            "metrics": self._metrics,
        }

    def add_trade(self, trade: Dict[str, Any]) -> None:
        """Record a trade result."""
        self._trades.append(trade)

    def add_equity_point(self, value: float) -> None:
        """Add a point to the equity curve."""
        self._equity_curve.append(value)

    def set_metrics(self, metrics: Dict[str, float]) -> None:
        """Set performance metrics."""
        self._metrics = metrics

    @property
    def trades(self) -> List[Dict[str, Any]]:
        return self._trades

    @property
    def equity_curve(self) -> List[float]:
        return self._equity_curve

    @property
    def metrics(self) -> Dict[str, float]:
        return self._metrics

    def summary(self) -> Dict[str, Any]:
        """Return a summary of backtest results."""
        return {
            "total_trades": len(self._trades),
            "metrics": self._metrics,
            "final_equity": self._equity_curve[-1] if self._equity_curve else 0.0,
        }
