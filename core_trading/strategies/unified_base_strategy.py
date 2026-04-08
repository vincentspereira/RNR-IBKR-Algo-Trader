"""Unified Base Strategy Implementation.

Consolidates strategy interfaces into a single cohesive base class that can
work both independently and with NautilusTrader.
"""

import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Union

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class SignalType(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    CLOSE_LONG = "close_long"
    CLOSE_SHORT = "close_short"


class StrategyStatus(Enum):
    INITIALIZED = "initialized"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"
    PAUSED = "paused"
    DEGRADED = "degraded"


class PositionSide(Enum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class StrategyType(Enum):
    MOMENTUM = "momentum"
    MEAN_REVERSION = "mean_reversion"
    ARBITRAGE = "arbitrage"
    MACHINE_LEARNING = "machine_learning"
    MULTI_ASSET = "multi_asset"
    VOLATILITY = "volatility"
    PAIRS_TRADING = "pairs_trading"
    STATISTICAL_ARBITRAGE = "statistical_arbitrage"
    MARKET_MAKING = "market_making"
    NEWS_BASED = "news_based"


class PositionSizing(Enum):
    FIXED = "fixed"
    PERCENT_RISK = "percent_risk"
    VOLATILITY_ADJUSTED = "volatility_adjusted"
    KELLY_CRITERION = "kelly_criterion"
    OPTIMAL_F = "optimal_f"
    EQUAL_WEIGHT = "equal_weight"
    RISK_PARITY = "risk_parity"


@dataclass
class Signal:
    """Trading signal with metadata."""
    signal_type: SignalType = SignalType.HOLD
    timestamp: Optional[datetime] = None
    symbol: str = ""
    price: float = 0.0
    quantity: Optional[float] = None
    confidence: float = 1.0
    strength: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    order_type: OrderType = OrderType.MARKET
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)
        if not 0 <= self.confidence <= 1:
            raise ValueError("Confidence must be between 0 and 1")
        if not 0 <= self.strength <= 1:
            raise ValueError("Strength must be between 0 and 1")


@dataclass
class UnifiedPosition:
    """Represents a trading position with P&L tracking."""
    symbol: str = ""
    side: PositionSide = PositionSide.FLAT
    quantity: float = 0.0
    entry_price: float = 0.0
    entry_time: Optional[datetime] = None
    current_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0

    def update_price(self, price: float) -> None:
        """Update current price and unrealized PnL."""
        self.current_price = price
        if self.side == PositionSide.LONG:
            self.unrealized_pnl = (price - self.entry_price) * self.quantity
        elif self.side == PositionSide.SHORT:
            self.unrealized_pnl = (self.entry_price - price) * self.quantity

    @property
    def pnl_pct(self) -> float:
        """Return PnL as percentage."""
        if self.entry_price == 0:
            return 0.0
        if self.side == PositionSide.LONG:
            return (self.current_price or 0) / self.entry_price - 1
        elif self.side == PositionSide.SHORT:
            return self.entry_price / (self.current_price or 1) - 1
        return 0.0


@dataclass
class StrategyConfig:
    """Unified strategy configuration."""
    name: str = "UnifiedStrategy"
    strategy_type: StrategyType = StrategyType.MOMENTUM
    symbols: List[str] = field(default_factory=lambda: ["SPY"])
    initial_capital: float = 100000.0
    position_sizing: PositionSizing = PositionSizing.PERCENT_RISK
    max_position_size: float = 0.1
    risk_per_trade: float = 0.02
    stop_loss_pct: float = 0.05
    take_profit_pct: float = 0.10
    parameters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PerformanceMetrics:
    """Strategy performance metrics."""
    total_return: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0
    profit_factor: float = 0.0
    avg_trade: float = 0.0


class UnifiedBaseStrategy(ABC):
    """Unified base class for all trading strategies."""

    def __init__(self, config: Optional[StrategyConfig] = None):
        self.config = config or StrategyConfig()
        self._status = StrategyStatus.INITIALIZED
        self._positions: Dict[str, UnifiedPosition] = {}
        self._signals: List[Signal] = []
        self._trade_history: List[Dict[str, Any]] = []
        self._equity_curve: List[float] = [self.config.initial_capital]
        self._strategy_id = uuid.uuid4().hex[:8]
        logger.info(f"Strategy {self.config.name} initialized (id={self._strategy_id})")

    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> List[Signal]:
        """Generate trading signals from market data."""
        ...

    def start(self) -> None:
        """Start the strategy."""
        self._status = StrategyStatus.RUNNING
        logger.info(f"Strategy {self.config.name} started")

    def stop(self) -> None:
        """Stop the strategy."""
        self._status = StrategyStatus.STOPPED
        logger.info(f"Strategy {self.config.name} stopped")

    def pause(self) -> None:
        """Pause the strategy."""
        self._status = StrategyStatus.PAUSED
        logger.info(f"Strategy {self.config.name} paused")

    def resume(self) -> None:
        """Resume the strategy."""
        self._status = StrategyStatus.RUNNING
        logger.info(f"Strategy {self.config.name} resumed")

    @property
    def status(self) -> StrategyStatus:
        return self._status

    @property
    def is_running(self) -> bool:
        return self._status == StrategyStatus.RUNNING

    def get_position(self, symbol: str) -> Optional[UnifiedPosition]:
        """Get current position for a symbol."""
        return self._positions.get(symbol)

    def get_all_positions(self) -> Dict[str, UnifiedPosition]:
        """Get all current positions."""
        return dict(self._positions)

    def update_position_price(self, symbol: str, price: float) -> None:
        """Update position price."""
        pos = self._positions.get(symbol)
        if pos:
            pos.update_price(price)

    def calculate_position_size(self, equity: float, price: float) -> float:
        """Calculate position size based on configuration."""
        method = self.config.position_sizing
        if method == PositionSizing.FIXED:
            return self.config.parameters.get("fixed_size", 100)
        elif method == PositionSizing.PERCENT_RISK:
            risk_amount = equity * self.config.risk_per_trade
            return risk_amount / (price * self.config.stop_loss_pct)
        elif method == PositionSizing.EQUAL_WEIGHT:
            n_symbols = max(len(self.config.symbols), 1)
            return equity / (n_symbols * price)
        return 0.0

    def calculate_stop_loss(self, entry_price: float, side: PositionSide) -> float:
        """Calculate stop loss price."""
        if side == PositionSide.LONG:
            return entry_price * (1 - self.config.stop_loss_pct)
        return entry_price * (1 + self.config.stop_loss_pct)

    def calculate_take_profit(self, entry_price: float, side: PositionSide) -> float:
        """Calculate take profit price."""
        if side == PositionSide.LONG:
            return entry_price * (1 + self.config.take_profit_pct)
        return entry_price * (1 - self.config.take_profit_pct)

    def get_performance_metrics(self) -> PerformanceMetrics:
        """Calculate and return performance metrics."""
        trades = self._trade_history
        if not trades:
            return PerformanceMetrics()

        wins = [t for t in trades if t.get("pnl", 0) > 0]
        losses = [t for t in trades if t.get("pnl", 0) < 0]
        total_pnl = sum(t.get("pnl", 0) for t in trades)
        gross_profit = sum(t.get("pnl", 0) for t in wins)
        gross_loss = abs(sum(t.get("pnl", 0) for t in losses))

        equity = np.array(self._equity_curve)
        if len(equity) > 1:
            returns = np.diff(equity) / equity[:-1]
            sharpe = float(np.mean(returns) / (np.std(returns) + 1e-10) * np.sqrt(252)) if np.std(returns) > 0 else 0.0
            peak = np.maximum.accumulate(equity)
            max_dd = float(np.min((equity - peak) / peak))
        else:
            sharpe = 0.0
            max_dd = 0.0

        return PerformanceMetrics(
            total_return=total_pnl / self.config.initial_capital if self.config.initial_capital > 0 else 0.0,
            sharpe_ratio=sharpe,
            max_drawdown=max_dd,
            win_rate=len(wins) / len(trades) if trades else 0.0,
            total_trades=len(trades),
            profit_factor=gross_profit / gross_loss if gross_loss > 0 else float("inf"),
            avg_trade=total_pnl / len(trades) if trades else 0.0,
        )

    def get_status_summary(self) -> Dict[str, Any]:
        """Get comprehensive strategy status."""
        return {
            "name": self.config.name,
            "id": self._strategy_id,
            "status": self._status.value,
            "strategy_type": self.config.strategy_type.value,
            "positions": len(self._positions),
            "total_trades": len(self._trade_history),
            "equity": self._equity_curve[-1] if self._equity_curve else self.config.initial_capital,
        }
