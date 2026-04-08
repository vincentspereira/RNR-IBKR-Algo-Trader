"""Strategy Factory Module.

Provides factory classes for creating and configuring different types
of trading strategies. Serves as a centralized creation point.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Type, Union

logger = logging.getLogger(__name__)


class StrategyType(Enum):
    PAIRS_TRADING = "pairs_trading"
    MOMENTUM = "momentum"
    MEAN_REVERSION = "mean_reversion"
    CONVERGENCE = "convergence"
    DIVERGENCE = "divergence"
    ADAPTIVE = "adaptive"
    VOLATILITY_BREAKOUT = "volatility_breakout"
    SCALPING = "scalping"
    ML_BASED = "ml_based"
    MULTI_FACTOR = "multi_factor"
    SEASONAL = "seasonal"
    ARBITRAGE = "arbitrage"


class SignalStrength(Enum):
    WEAK = 1
    MODERATE = 2
    STRONG = 3
    VERY_STRONG = 4


class PositionType(Enum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


@dataclass
class TradingSignal:
    """Trading signal with metadata."""
    symbol: str
    direction: str
    strength: SignalStrength = SignalStrength.MODERATE
    confidence: float = 0.5
    timestamp: Optional[str] = None
    price: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Position:
    """Trading position."""
    symbol: str
    position_type: PositionType = PositionType.FLAT
    quantity: float = 0.0
    entry_price: Optional[float] = None
    current_price: Optional[float] = None


class StrategyConfig:
    """Base configuration for strategies."""

    def __init__(self, strategy_type: Optional[str] = None, **kwargs):
        self.strategy_type = strategy_type
        self.params = kwargs

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration parameter."""
        return self.params.get(key, default)

    def update(self, **kwargs) -> None:
        """Update configuration parameters."""
        self.params.update(kwargs)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {"strategy_type": self.strategy_type, **self.params}


class BaseStrategyFactory(ABC):
    """Abstract base factory for strategy creation."""

    @abstractmethod
    def create_strategy(self, config: Optional[StrategyConfig] = None) -> Any:
        """Create a strategy instance."""
        ...

    @abstractmethod
    def get_strategy_type(self) -> StrategyType:
        """Return the strategy type this factory creates."""
        ...

    def validate_config(self, config: StrategyConfig) -> bool:
        """Validate configuration parameters."""
        return True

    def get_default_config(self) -> StrategyConfig:
        """Get default configuration."""
        return StrategyConfig(strategy_type=self.get_strategy_type().value)


class MomentumStrategyFactory(BaseStrategyFactory):
    """Factory for momentum strategies."""

    def get_strategy_type(self) -> StrategyType:
        return StrategyType.MOMENTUM

    def create_strategy(self, config: Optional[StrategyConfig] = None) -> Dict[str, Any]:
        """Create a momentum strategy."""
        cfg = config or self.get_default_config()
        return {
            "type": "momentum",
            "config": cfg.to_dict(),
            "strategy_type": self.get_strategy_type().value,
        }


class MeanReversionStrategyFactory(BaseStrategyFactory):
    """Factory for mean reversion strategies."""

    def get_strategy_type(self) -> StrategyType:
        return StrategyType.MEAN_REVERSION

    def create_strategy(self, config: Optional[StrategyConfig] = None) -> Dict[str, Any]:
        cfg = config or self.get_default_config()
        return {
            "type": "mean_reversion",
            "config": cfg.to_dict(),
            "strategy_type": self.get_strategy_type().value,
        }


class PairsTradingStrategyFactory(BaseStrategyFactory):
    """Factory for pairs trading strategies."""

    def get_strategy_type(self) -> StrategyType:
        return StrategyType.PAIRS_TRADING

    def create_strategy(self, config: Optional[StrategyConfig] = None) -> Dict[str, Any]:
        cfg = config or self.get_default_config()
        return {
            "type": "pairs_trading",
            "config": cfg.to_dict(),
            "strategy_type": self.get_strategy_type().value,
        }


class StrategyFactoryManager:
    """Central registry for strategy factories."""

    def __init__(self):
        self._factories: Dict[StrategyType, BaseStrategyFactory] = {}

    def register_factory(self, factory: BaseStrategyFactory) -> None:
        """Register a strategy factory."""
        self._factories[factory.get_strategy_type()] = factory

    def unregister_factory(self, strategy_type: StrategyType) -> None:
        """Unregister a strategy factory."""
        self._factories.pop(strategy_type, None)

    def create_strategy(
        self,
        strategy_type: StrategyType,
        config: Optional[StrategyConfig] = None,
    ) -> Any:
        """Create a strategy by type."""
        factory = self._factories.get(strategy_type)
        if factory is None:
            raise ValueError(f"No factory registered for strategy type: {strategy_type}")
        return factory.create_strategy(config)

    def get_registered_types(self) -> List[StrategyType]:
        """Get all registered strategy types."""
        return list(self._factories.keys())

    def has_factory(self, strategy_type: StrategyType) -> bool:
        """Check if a factory is registered."""
        return strategy_type in self._factories

    def create_from_config(self, config: StrategyConfig) -> Any:
        """Create a strategy from a config object."""
        stype = StrategyType(config.strategy_type) if config.strategy_type else None
        if stype is None:
            raise ValueError("Config must specify strategy_type")
        return self.create_strategy(stype, config)


def create_default_factory_manager() -> StrategyFactoryManager:
    """Create a factory manager with all default factories registered."""
    manager = StrategyFactoryManager()
    manager.register_factory(MomentumStrategyFactory())
    manager.register_factory(MeanReversionStrategyFactory())
    manager.register_factory(PairsTradingStrategyFactory())
    return manager
