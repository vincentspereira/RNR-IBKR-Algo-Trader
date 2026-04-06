"""Circuit Breaker and Health Monitor for fault tolerance.

Implements the standard circuit breaker pattern (CLOSED -> OPEN -> HALF_OPEN)
with sliding window failure counting and health monitoring for components.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    half_open_max_calls: int = 3
    success_threshold: int = 3
    window_seconds: float = 60.0


class CircuitBreaker:
    def __init__(self, name: str = "default", config: Optional[CircuitBreakerConfig] = None):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self._half_open_calls = 0
        self._failure_times: List[float] = []

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if self._last_failure_time and (
                time.time() - self._last_failure_time
            ) >= self.config.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                self._success_count = 0
                logger.info(f"circuit_breaker_half_open: {self.name}")
        return self._state

    def allow_request(self) -> bool:
        current_state = self.state
        if current_state == CircuitState.CLOSED:
            return True
        elif current_state == CircuitState.HALF_OPEN:
            if self._half_open_calls < self.config.half_open_max_calls:
                self._half_open_calls += 1
                return True
            return False
        else:
            return False

    def record_success(self):
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.config.success_threshold:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._failure_times.clear()
                logger.info(f"circuit_breaker_closed: {self.name}")
        elif self._state == CircuitState.CLOSED:
            self._failure_count = max(0, self._failure_count - 1)

    def record_failure(self, error: Optional[Exception] = None):
        now = time.time()
        self._failure_times.append(now)
        self._last_failure_time = now

        cutoff = now - self.config.window_seconds
        self._failure_times = [t for t in self._failure_times if t > cutoff]
        self._failure_count = len(self._failure_times)

        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.OPEN
            logger.warning(f"circuit_breaker_open_from_half_open: {self.name}")
        elif self._failure_count >= self.config.failure_threshold:
            self._state = CircuitState.OPEN
            logger.error(
                f"circuit_breaker_open: {self.name}, failures={self._failure_count}"
            )


class HealthMonitor:
    def __init__(self):
        self._components: Dict[str, Dict[str, Any]] = {}
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}

    def register_component(
        self,
        name: str,
        health_check_fn: Callable,
        circuit_config: Optional[CircuitBreakerConfig] = None,
    ):
        self._components[name] = {
            "check_fn": health_check_fn,
            "healthy": True,
            "last_check": None,
        }
        self._circuit_breakers[name] = CircuitBreaker(name=name, config=circuit_config)

    async def check_health(self, component: Optional[str] = None) -> Dict[str, Any]:
        if component:
            return await self._check_single(component)
        results = {}
        for name in self._components:
            results[name] = await self._check_single(name)
        return results

    async def _check_single(self, name: str) -> Dict[str, Any]:
        comp = self._components.get(name)
        if not comp:
            return {"status": "unknown", "error": f"Component {name} not registered"}
        try:
            result = comp["check_fn"]()
            if asyncio.iscoroutine(result):
                result = await result
            comp["healthy"] = bool(result)
            comp["last_check"] = time.time()
            return {
                "status": "healthy" if result else "unhealthy",
                "circuit": self._circuit_breakers[name].state.value,
            }
        except Exception as e:
            comp["healthy"] = False
            comp["last_check"] = time.time()
            return {
                "status": "error",
                "error": str(e),
                "circuit": self._circuit_breakers[name].state.value,
            }

    def get_circuit_breaker(self, name: str) -> CircuitBreaker:
        return self._circuit_breakers.get(name, CircuitBreaker(name=name))


_health_monitor: Optional[HealthMonitor] = None


def get_health_monitor() -> HealthMonitor:
    """Get the global health monitor singleton."""
    global _health_monitor
    if _health_monitor is None:
        _health_monitor = HealthMonitor()
    return _health_monitor
