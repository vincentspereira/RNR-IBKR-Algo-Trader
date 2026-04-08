"""Modular Strategy Components for Nautilus Trader Engine.

Provides reusable building blocks for creating complex trading strategies.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class ComponentType(Enum):
    ENTRY_SIGNAL = "entry_signal"
    EXIT_SIGNAL = "exit_signal"
    FILTER = "filter"
    RISK_MANAGER = "risk_manager"
    POSITION_SIZER = "position_sizer"
    EXECUTION_HANDLER = "execution_handler"


class SignalStrength(Enum):
    WEAK = 1
    MODERATE = 2
    STRONG = 3
    VERY_STRONG = 4


class SignalDirection(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class Signal:
    """Trading signal with metadata."""
    symbol: str = ""
    direction: str = "hold"
    strength: SignalStrength = SignalStrength.MODERATE
    confidence: float = 0.5
    timestamp: Optional[datetime] = None
    price: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


@dataclass
class ComponentResult:
    """Result from a component processing."""
    component_name: str
    component_type: ComponentType
    success: bool = True
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


class StrategyComponent(ABC):
    """Base class for strategy components."""

    def __init__(self, name: str, component_type: ComponentType, enabled: bool = True, weight: float = 1.0, **kwargs):
        self.name = name
        self.component_type = component_type
        self.enabled = enabled
        self.weight = weight
        self.parameters: Dict[str, Any] = kwargs

    @abstractmethod
    def process(self, data: pd.DataFrame, context: Optional[Dict[str, Any]] = None) -> Optional[Any]:
        """Process data and return result."""
        ...

    def validate_parameters(self) -> List[str]:
        """Validate component parameters."""
        return []

    def get_info(self) -> Dict[str, Any]:
        """Get component info."""
        return {
            "name": self.name,
            "type": self.component_type.value,
            "enabled": self.enabled,
            "weight": self.weight,
        }


class EntrySignalComponent(StrategyComponent):
    """Component for generating entry signals."""

    def __init__(self, name: str, threshold: float = 0.6, **kwargs):
        super().__init__(name, ComponentType.ENTRY_SIGNAL, **kwargs)
        self.threshold = threshold

    def process(self, data: pd.DataFrame, context: Optional[Dict[str, Any]] = None) -> Optional[Signal]:
        """Generate entry signal from data."""
        return self.generate_entry_signal(data, context or {})

    @abstractmethod
    def generate_entry_signal(self, data: pd.DataFrame, context: Dict[str, Any]) -> Optional[Signal]:
        """Override to implement entry logic."""
        ...


class ExitSignalComponent(StrategyComponent):
    """Component for generating exit signals."""

    def __init__(self, name: str, profit_threshold: float = 0.02, loss_threshold: float = -0.015, **kwargs):
        super().__init__(name, ComponentType.EXIT_SIGNAL, **kwargs)
        self.profit_threshold = profit_threshold
        self.loss_threshold = loss_threshold

    def process(self, data: pd.DataFrame, context: Optional[Dict[str, Any]] = None) -> Optional[Signal]:
        return self.generate_exit_signal(data, context or {})

    @abstractmethod
    def generate_exit_signal(self, data: pd.DataFrame, context: Dict[str, Any]) -> Optional[Signal]:
        """Override to implement exit logic."""
        ...


class FilterComponent(StrategyComponent):
    """Component for filtering signals."""

    def __init__(self, name: str, **kwargs):
        super().__init__(name, ComponentType.FILTER, **kwargs)

    def process(self, data: pd.DataFrame, context: Optional[Dict[str, Any]] = None) -> bool:
        """Return True if the filter passes."""
        return self.should_trade(data, context or {})

    @abstractmethod
    def should_trade(self, data: pd.DataFrame, context: Dict[str, Any]) -> bool:
        """Override to implement filter logic."""
        ...


class RiskManagerComponent(StrategyComponent):
    """Component for managing risk."""

    def __init__(self, name: str, max_position_size: float = 0.1, max_drawdown: float = 0.15, **kwargs):
        super().__init__(name, ComponentType.RISK_MANAGER, **kwargs)
        self.max_position_size = max_position_size
        self.max_drawdown = max_drawdown

    def process(self, data: pd.DataFrame, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Evaluate risk for the current state."""
        return self.evaluate_risk(data, context or {})

    @abstractmethod
    def evaluate_risk(self, data: pd.DataFrame, context: Dict[str, Any]) -> Dict[str, Any]:
        """Override to implement risk evaluation."""
        ...


class PositionSizerComponent(StrategyComponent):
    """Component for calculating position sizes."""

    def __init__(self, name: str, default_size: float = 100.0, **kwargs):
        super().__init__(name, ComponentType.POSITION_SIZER, **kwargs)
        self.default_size = default_size

    def process(self, data: pd.DataFrame, context: Optional[Dict[str, Any]] = None) -> float:
        """Calculate position size."""
        return self.calculate_size(data, context or {})

    @abstractmethod
    def calculate_size(self, data: pd.DataFrame, context: Dict[str, Any]) -> float:
        """Override to implement position sizing."""
        ...


class ExecutionHandlerComponent(StrategyComponent):
    """Component for handling order execution."""

    def __init__(self, name: str, **kwargs):
        super().__init__(name, ComponentType.EXECUTION_HANDLER, **kwargs)

    def process(self, data: pd.DataFrame, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self.execute(data, context or {})

    @abstractmethod
    def execute(self, data: pd.DataFrame, context: Dict[str, Any]) -> Dict[str, Any]:
        """Override to implement execution logic."""
        ...


class ModularStrategy:
    """Strategy composed of modular components."""

    def __init__(self, name: str = "ModularStrategy"):
        self.name = name
        self._components: Dict[str, StrategyComponent] = {}
        self._entry_components: List[EntrySignalComponent] = []
        self._exit_components: List[ExitSignalComponent] = []
        self._filters: List[FilterComponent] = []
        self._risk_managers: List[RiskManagerComponent] = []
        self._position_sizers: List[PositionSizerComponent] = []

    def add_component(self, component: StrategyComponent) -> None:
        """Add a component to the strategy."""
        self._components[component.name] = component
        if isinstance(component, EntrySignalComponent):
            self._entry_components.append(component)
        elif isinstance(component, ExitSignalComponent):
            self._exit_components.append(component)
        elif isinstance(component, FilterComponent):
            self._filters.append(component)
        elif isinstance(component, RiskManagerComponent):
            self._risk_managers.append(component)
        elif isinstance(component, PositionSizerComponent):
            self._position_sizers.append(component)

    def remove_component(self, name: str) -> bool:
        """Remove a component by name."""
        comp = self._components.pop(name, None)
        if comp is None:
            return False
        for lst in [self._entry_components, self._exit_components,
                    self._filters, self._risk_managers, self._position_sizers]:
            if comp in lst:
                lst.remove(comp)
        return True

    def get_component(self, name: str) -> Optional[StrategyComponent]:
        """Get a component by name."""
        return self._components.get(name)

    def process_filters(self, data: pd.DataFrame, context: Optional[Dict[str, Any]] = None) -> bool:
        """Run all filter components. Returns True if all pass."""
        for f in self._filters:
            if not f.process(data, context):
                return False
        return True

    def generate_entries(self, data: pd.DataFrame, context: Optional[Dict[str, Any]] = None) -> List[Signal]:
        """Generate entry signals from all entry components."""
        signals = []
        for comp in self._entry_components:
            if comp.enabled:
                sig = comp.process(data, context)
                if sig is not None:
                    signals.append(sig)
        return signals

    def generate_exits(self, data: pd.DataFrame, context: Optional[Dict[str, Any]] = None) -> List[Signal]:
        """Generate exit signals from all exit components."""
        signals = []
        for comp in self._exit_components:
            if comp.enabled:
                sig = comp.process(data, context)
                if sig is not None:
                    signals.append(sig)
        return signals

    def get_status(self) -> Dict[str, Any]:
        """Get strategy status with component info."""
        return {
            "name": self.name,
            "components": {n: c.get_info() for n, c in self._components.items()},
            "entry_components": len(self._entry_components),
            "exit_components": len(self._exit_components),
            "filters": len(self._filters),
        }
