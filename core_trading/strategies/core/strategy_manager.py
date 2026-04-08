"""Strategy Manager Module.

Provides a unified interface for managing all trading strategies across
the algorithmic trading system.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


class StrategyStatus(Enum):
    CREATED = "created"
    INITIALIZING = "initializing"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"


class StrategyPriority(Enum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class StrategyInfo:
    """Information about a registered strategy."""
    name: str
    strategy_type: str
    status: StrategyStatus = StrategyStatus.CREATED
    priority: StrategyPriority = StrategyPriority.MEDIUM
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_run: Optional[str] = None
    config: Dict[str, Any] = field(default_factory=dict)
    metrics: Dict[str, Any] = field(default_factory=dict)
    error_count: int = 0


@dataclass
class StrategyResult:
    """Result from a strategy execution."""
    strategy_name: str
    signals: List[Dict[str, Any]] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    success: bool = True
    error: Optional[str] = None


class StrategyManager:
    """Central manager for all trading strategies."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self._strategies: Dict[str, StrategyInfo] = {}
        self._strategy_instances: Dict[str, Any] = {}
        self._callbacks: Dict[str, List[Callable]] = defaultdict(list)
        self._running = False
        logger.info("StrategyManager initialized")

    def register_strategy(
        self,
        name: str,
        strategy_type: str,
        instance: Any = None,
        config: Optional[Dict[str, Any]] = None,
        priority: StrategyPriority = StrategyPriority.MEDIUM,
    ) -> StrategyInfo:
        """Register a new strategy."""
        info = StrategyInfo(
            name=name,
            strategy_type=strategy_type,
            config=config or {},
            priority=priority,
        )
        self._strategies[name] = info
        if instance is not None:
            self._strategy_instances[name] = instance
        logger.info(f"Registered strategy: {name} ({strategy_type})")
        return info

    def unregister_strategy(self, name: str) -> bool:
        """Remove a registered strategy."""
        if name in self._strategies:
            del self._strategies[name]
            self._strategy_instances.pop(name, None)
            logger.info(f"Unregistered strategy: {name}")
            return True
        return False

    def get_strategy(self, name: str) -> Optional[StrategyInfo]:
        """Get strategy info by name."""
        return self._strategies.get(name)

    def get_strategy_instance(self, name: str) -> Any:
        """Get strategy instance by name."""
        return self._strategy_instances.get(name)

    def list_strategies(self, status: Optional[StrategyStatus] = None) -> List[StrategyInfo]:
        """List all registered strategies, optionally filtered by status."""
        strategies = list(self._strategies.values())
        if status is not None:
            strategies = [s for s in strategies if s.status == status]
        return strategies

    def start_strategy(self, name: str) -> bool:
        """Start a registered strategy."""
        info = self._strategies.get(name)
        if info is None:
            logger.error(f"Strategy not found: {name}")
            return False
        info.status = StrategyStatus.RUNNING
        info.last_run = datetime.now().isoformat()
        logger.info(f"Started strategy: {name}")
        return True

    def stop_strategy(self, name: str) -> bool:
        """Stop a running strategy."""
        info = self._strategies.get(name)
        if info is None:
            return False
        info.status = StrategyStatus.STOPPED
        logger.info(f"Stopped strategy: {name}")
        return True

    def pause_strategy(self, name: str) -> bool:
        """Pause a running strategy."""
        info = self._strategies.get(name)
        if info is None:
            return False
        info.status = StrategyStatus.PAUSED
        logger.info(f"Paused strategy: {name}")
        return True

    def resume_strategy(self, name: str) -> bool:
        """Resume a paused strategy."""
        info = self._strategies.get(name)
        if info is None:
            return False
        info.status = StrategyStatus.RUNNING
        logger.info(f"Resumed strategy: {name}")
        return True

    def start_all(self) -> int:
        """Start all registered strategies."""
        count = 0
        for name in self._strategies:
            if self.start_strategy(name):
                count += 1
        self._running = True
        return count

    def stop_all(self) -> int:
        """Stop all running strategies."""
        count = 0
        for name, info in self._strategies.items():
            if info.status == StrategyStatus.RUNNING:
                self.stop_strategy(name)
                count += 1
        self._running = False
        return count

    def execute_strategy(self, name: str, data: Any = None) -> StrategyResult:
        """Execute a single strategy."""
        info = self._strategies.get(name)
        if info is None:
            return StrategyResult(strategy_name=name, success=False, error="Strategy not found")

        instance = self._strategy_instances.get(name)
        if instance is None:
            return StrategyResult(strategy_name=name, success=False, error="No instance registered")

        try:
            if hasattr(instance, "generate_signals"):
                signals = instance.generate_signals(data)
            else:
                signals = []

            info.last_run = datetime.now().isoformat()
            info.status = StrategyStatus.RUNNING
            return StrategyResult(strategy_name=name, signals=signals)
        except Exception as e:
            info.status = StrategyStatus.ERROR
            info.error_count += 1
            logger.error(f"Error executing strategy {name}: {e}")
            return StrategyResult(strategy_name=name, success=False, error=str(e))

    def update_metrics(self, name: str, metrics: Dict[str, Any]) -> bool:
        """Update metrics for a strategy."""
        info = self._strategies.get(name)
        if info is None:
            return False
        info.metrics.update(metrics)
        return True

    def get_metrics(self, name: str) -> Dict[str, Any]:
        """Get metrics for a strategy."""
        info = self._strategies.get(name)
        return info.metrics if info else {}

    def register_callback(self, event_type: str, callback: Callable) -> None:
        """Register a callback for events."""
        self._callbacks[event_type].append(callback)

    def emit_event(self, event_type: str, data: Any = None) -> None:
        """Emit an event to registered callbacks."""
        for callback in self._callbacks.get(event_type, []):
            try:
                callback(data)
            except Exception as e:
                logger.error(f"Callback error for {event_type}: {e}")

    def get_status(self) -> Dict[str, Any]:
        """Get overall manager status."""
        strategies = list(self._strategies.values())
        return {
            "running": self._running,
            "total_strategies": len(strategies),
            "active_strategies": sum(1 for s in strategies if s.status == StrategyStatus.RUNNING),
            "paused_strategies": sum(1 for s in strategies if s.status == StrategyStatus.PAUSED),
            "error_strategies": sum(1 for s in strategies if s.status == StrategyStatus.ERROR),
            "strategy_types": list(set(s.strategy_type for s in strategies)),
        }

    def health_check(self) -> Dict[str, bool]:
        """Check health of all strategies."""
        result = {}
        for name, info in self._strategies.items():
            result[name] = info.status in (StrategyStatus.RUNNING, StrategyStatus.PAUSED)
        return result
