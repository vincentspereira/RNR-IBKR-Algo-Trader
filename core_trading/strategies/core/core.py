"""Core component extracted from BaseInstitutionalStrategy."""

import logging
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


class MarketRegime(Enum):
    BULL_MARKET = "BULL_MARKET"
    BEAR_MARKET = "BEAR_MARKET"
    SIDEWAYS_MARKET = "SIDEWAYS_MARKET"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"


class SignalType(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class Core:
    """Core component providing signal generation, risk management, and execution."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self._signals: List[Dict[str, Any]] = []
        self._positions: Dict[str, Dict[str, Any]] = {}
        self._regime = MarketRegime.SIDEWAYS_MARKET
        self._equity = self.config.get("initial_capital", 100000.0)
        self._running = False

    def generate_signals(self, data: Optional[Any] = None) -> List[Dict[str, Any]]:
        """Generate trading signals from market data."""
        return self._signals

    def update_signals(self, signals: List[Dict[str, Any]]) -> None:
        """Update the signal list."""
        self._signals = signals

    def get_signal_strength(self, signal: Optional[Dict[str, Any]] = None) -> float:
        """Get the strength of the latest signal."""
        if not self._signals:
            return 0.0
        return self._signals[-1].get("strength", 0.0)

    def get_signal_confidence(self, signal: Optional[Dict[str, Any]] = None) -> float:
        """Get confidence of the latest signal."""
        if not self._signals:
            return 0.0
        return self._signals[-1].get("confidence", 0.0)

    def calculate_position_size(
        self, equity: float, risk_pct: float, entry_price: float, stop_price: float
    ) -> float:
        """Calculate position size based on risk parameters."""
        risk_amount = equity * (risk_pct / 100)
        risk_per_share = abs(entry_price - stop_price)
        if risk_per_share <= 0:
            return 0.0
        return risk_amount / risk_per_share

    def calculate_stop_loss(self, entry_price: float, atr: float, multiplier: float = 2.0, direction: str = "long") -> float:
        """Calculate stop loss price."""
        if direction == "long":
            return entry_price - atr * multiplier
        return entry_price + atr * multiplier

    def calculate_take_profit(self, entry_price: float, atr: float, multiplier: float = 3.0, direction: str = "long") -> float:
        """Calculate take profit price."""
        if direction == "long":
            return entry_price + atr * multiplier
        return entry_price - atr * multiplier

    def update_risk_metrics(self, positions: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
        """Update and return risk metrics."""
        pos = positions or self._positions
        return {
            "total_positions": len(pos),
            "equity": self._equity,
        }

    def detect_market_regime(self, prices: Optional[np.ndarray] = None) -> MarketRegime:
        """Detect current market regime from price data."""
        if prices is None or len(prices) < 2:
            return self._regime
        returns = np.diff(prices) / prices[:-1]
        volatility = float(np.std(returns))
        trend = float((prices[-1] - prices[0]) / prices[0])

        if volatility > 0.03:
            self._regime = MarketRegime.HIGH_VOLATILITY
        elif volatility < 0.01:
            self._regime = MarketRegime.LOW_VOLATILITY
        elif trend > 0.1:
            self._regime = MarketRegime.BULL_MARKET
        elif trend < -0.1:
            self._regime = MarketRegime.BEAR_MARKET
        else:
            self._regime = MarketRegime.SIDEWAYS_MARKET
        return self._regime

    def adapt_to_regime(self, regime: MarketRegime) -> Dict[str, Any]:
        """Adapt strategy parameters based on market regime."""
        adaptations = {
            MarketRegime.BULL_MARKET: {"position_multiplier": 1.2, "stop_multiplier": 2.0},
            MarketRegime.BEAR_MARKET: {"position_multiplier": 0.5, "stop_multiplier": 1.5},
            MarketRegime.HIGH_VOLATILITY: {"position_multiplier": 0.3, "stop_multiplier": 3.0},
            MarketRegime.LOW_VOLATILITY: {"position_multiplier": 1.0, "stop_multiplier": 1.5},
            MarketRegime.SIDEWAYS_MARKET: {"position_multiplier": 0.8, "stop_multiplier": 2.0},
        }
        return adaptations.get(regime, {"position_multiplier": 1.0, "stop_multiplier": 2.0})

    def get_regime_alignment_score(self, signal_type: SignalType) -> float:
        """Score how well a signal aligns with current regime."""
        alignment = {
            (SignalType.BUY, MarketRegime.BULL_MARKET): 0.9,
            (SignalType.BUY, MarketRegime.BEAR_MARKET): 0.2,
            (SignalType.SELL, MarketRegime.BEAR_MARKET): 0.9,
            (SignalType.SELL, MarketRegime.BULL_MARKET): 0.2,
            (SignalType.HOLD, MarketRegime.SIDEWAYS_MARKET): 0.8,
        }
        return alignment.get((signal_type, self._regime), 0.5)

    def create_order(self, symbol: str, side: str, quantity: float, price: Optional[float] = None) -> Dict[str, Any]:
        """Create an order."""
        return {
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "price": price,
            "timestamp": datetime.now().isoformat(),
            "status": "created",
        }

    def execute_order(self, order: Dict[str, Any]) -> Dict[str, Any]:
        """Execute an order."""
        order["status"] = "submitted"
        return order

    def check_exit_conditions(self, position: Dict[str, Any], current_price: float) -> bool:
        """Check if exit conditions are met for a position."""
        entry = position.get("entry_price", 0)
        stop = position.get("stop_loss", 0)
        tp = position.get("take_profit", float("inf"))
        side = position.get("side", "long")

        if side == "long":
            return current_price <= stop or current_price >= tp
        return current_price >= stop or current_price <= tp

    def update_performance_metrics(self, trades: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Update and return performance metrics."""
        if not trades:
            return {"total_trades": 0, "win_rate": 0.0, "total_pnl": 0.0}
        wins = sum(1 for t in trades if t.get("pnl", 0) > 0)
        total_pnl = sum(t.get("pnl", 0) for t in trades)
        return {
            "total_trades": len(trades),
            "win_rate": wins / len(trades),
            "total_pnl": total_pnl,
        }

    def calculate_current_equity(self) -> float:
        """Return current equity."""
        return self._equity

    def _is_winning_trade(self, entry: float, exit_price: float, side: str) -> bool:
        """Check if a trade is profitable."""
        if side == "long":
            return exit_price > entry
        return exit_price < entry

    def _is_losing_trade(self, entry: float, exit_price: float, side: str) -> bool:
        """Check if a trade is a loss."""
        return not self._is_winning_trade(entry, exit_price, side)

    def _calculate_trade_pnl(self, entry: float, exit_price: float, quantity: float, side: str) -> float:
        """Calculate PnL for a trade."""
        if side == "long":
            return (exit_price - entry) * quantity
        return (entry - exit_price) * quantity

    def get_current_price(self, symbol: str) -> Optional[float]:
        """Get current price for a symbol."""
        pos = self._positions.get(symbol, {})
        return pos.get("current_price")

    def update_market_data(self, symbol: str, price: float) -> None:
        """Update market data for a symbol."""
        if symbol not in self._positions:
            self._positions[symbol] = {}
        self._positions[symbol]["current_price"] = price

    def start_strategy(self) -> None:
        """Start the strategy."""
        self._running = True

    def stop_strategy(self) -> None:
        """Stop the strategy."""
        self._running = False

    def pause_strategy(self) -> None:
        """Pause the strategy."""
        self._running = False

    def resume_strategy(self) -> None:
        """Resume the strategy."""
        self._running = True

    def get_strategy_status(self) -> Dict[str, Any]:
        """Get strategy status."""
        return {
            "running": self._running,
            "regime": self._regime.value,
            "equity": self._equity,
            "positions": len(self._positions),
        }

    def run_strategy_cycle(self) -> Dict[str, Any]:
        """Run a single strategy cycle."""
        return self.get_strategy_status()

    def get_status(self) -> Dict[str, Any]:
        """Get component status."""
        return {"status": "active", "type": "core", "running": self._running}
