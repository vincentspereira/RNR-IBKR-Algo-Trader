"""Unit tests for the Circuit Breaker and Health Monitor."""

import time
import pytest

from src.core.fault_tolerance import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
    HealthMonitor,
)


class TestCircuitBreakerState:
    """Tests for circuit breaker state transitions."""

    def test_initial_state_is_closed(self):
        cb = CircuitBreaker(name="test")
        assert cb.state == CircuitState.CLOSED

    def test_allow_request_when_closed(self):
        cb = CircuitBreaker()
        assert cb.allow_request() is True

    def test_allow_request_when_open(self):
        cb = CircuitBreaker()
        cb._state = CircuitState.OPEN
        assert cb.allow_request() is False


class TestCircuitBreakerOpenOnFailures:
    """Tests that circuit breaker opens after threshold failures."""

    def test_opens_after_threshold_failures(self):
        config = CircuitBreakerConfig(failure_threshold=3)
        cb = CircuitBreaker(name="test", config=config)

        for _ in range(3):
            cb.record_failure()

        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False

    def test_does_not_open_below_threshold(self):
        config = CircuitBreakerConfig(failure_threshold=5)
        cb = CircuitBreaker(name="test", config=config)

        for _ in range(4):
            cb.record_failure()

        assert cb.state == CircuitState.CLOSED

    def test_failure_count_with_sliding_window(self):
        config = CircuitBreakerConfig(
            failure_threshold=3,
            window_seconds=0.1,
        )
        cb = CircuitBreaker(name="test", config=config)

        # Record 2 failures, wait for them to expire
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.15)

        # These old failures should be cleaned up by the sliding window
        cb.record_failure()
        assert cb._failure_count == 1
        assert cb.state == CircuitState.CLOSED


class TestCircuitBreakerHalfOpen:
    """Tests for half-open state after recovery timeout."""

    def test_half_open_after_recovery_timeout(self):
        config = CircuitBreakerConfig(
            failure_threshold=1,
            recovery_timeout=0.1,
        )
        cb = CircuitBreaker(name="test", config=config)

        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

    def test_allow_limited_requests_in_half_open(self):
        config = CircuitBreakerConfig(
            failure_threshold=1,
            recovery_timeout=0.1,
            half_open_max_calls=2,
        )
        cb = CircuitBreaker(name="test", config=config)

        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

        assert cb.allow_request() is True
        assert cb.allow_request() is True
        assert cb.allow_request() is False  # exceeded half_open_max_calls

    def test_failure_in_half_open_returns_to_open(self):
        config = CircuitBreakerConfig(
            failure_threshold=1,
            recovery_timeout=0.1,
        )
        cb = CircuitBreaker(name="test", config=config)

        cb.record_failure()
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_failure()
        assert cb.state == CircuitState.OPEN


class TestCircuitBreakerRecovery:
    """Tests for recovery from half-open back to closed."""

    def test_closes_after_success_threshold_in_half_open(self):
        config = CircuitBreakerConfig(
            failure_threshold=1,
            recovery_timeout=0.1,
            success_threshold=2,
        )
        cb = CircuitBreaker(name="test", config=config)

        cb.record_failure()
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_success()
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_success_in_closed_reduces_failure_count(self):
        cb = CircuitBreaker(name="test", config=CircuitBreakerConfig())
        cb._failure_count = 3
        cb.record_success()
        assert cb._failure_count == 2


class TestHealthMonitor:
    """Tests for the HealthMonitor component registry."""

    @pytest.mark.asyncio
    async def test_register_and_check_healthy_component(self):
        monitor = HealthMonitor()
        monitor.register_component("broker", lambda: True)
        result = await monitor.check_health("broker")
        assert result["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_check_unhealthy_component(self):
        monitor = HealthMonitor()
        monitor.register_component("broker", lambda: False)
        result = await monitor.check_health("broker")
        assert result["status"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_check_error_component(self):
        monitor = HealthMonitor()
        monitor.register_component("broker", lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        result = await monitor.check_health("broker")
        assert result["status"] == "error"
        assert "fail" in result["error"]

    @pytest.mark.asyncio
    async def test_check_all_components(self):
        monitor = HealthMonitor()
        monitor.register_component("a", lambda: True)
        monitor.register_component("b", lambda: False)
        results = await monitor.check_health()
        assert "a" in results
        assert "b" in results
        assert results["a"]["status"] == "healthy"
        assert results["b"]["status"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_check_unknown_component(self):
        monitor = HealthMonitor()
        result = await monitor.check_health("nonexistent")
        assert result["status"] == "unknown"

    @pytest.mark.asyncio
    async def test_async_health_check_fn(self):
        monitor = HealthMonitor()

        async def async_check():
            return True

        monitor.register_component("broker", async_check)
        result = await monitor.check_health("broker")
        assert result["status"] == "healthy"

    def test_get_circuit_breaker_for_component(self):
        monitor = HealthMonitor()
        monitor.register_component("broker", lambda: True)
        cb = monitor.get_circuit_breaker("broker")
        assert isinstance(cb, CircuitBreaker)

    def test_get_circuit_breaker_unknown_component(self):
        monitor = HealthMonitor()
        cb = monitor.get_circuit_breaker("unknown")
        assert isinstance(cb, CircuitBreaker)
