"""Rate limiting and connection management for broker adapters.

Provides comprehensive rate limiting with multiple strategies:
- Token Bucket: Smooth rate limiting with burst capacity
- Sliding Window: Precise request counting over a time window
- Adaptive: Auto-adjusts rates based on error rates

Also includes connection pooling, circuit breaking, and health monitoring.
"""

import asyncio
import logging
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union

import structlog

logger = structlog.get_logger(__name__)


class RateLimitStrategy(Enum):
    """Rate limiting strategies."""
    TOKEN_BUCKET = "token_bucket"
    SLIDING_WINDOW = "sliding_window"
    FIXED_WINDOW = "fixed_window"
    ADAPTIVE = "adaptive"


class ConnectionState(Enum):
    """Connection states."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"
    THROTTLED = "throttled"


@dataclass
class RateLimitConfig:
    """Rate limiting configuration."""
    requests_per_second: float = 10.0
    requests_per_minute: float = 600.0
    requests_per_hour: float = 36000.0
    burst_capacity: int = 50
    strategy: RateLimitStrategy = RateLimitStrategy.TOKEN_BUCKET
    adaptive_factor: float = 0.8
    backoff_multiplier: float = 2.0
    max_backoff_seconds: float = 300.0
    enable_adaptive_limiting: bool = True


@dataclass
class ConnectionConfig:
    """Connection management configuration."""
    max_connections: int = 5
    connection_timeout: float = 30.0
    read_timeout: float = 60.0
    max_retries: int = 3
    retry_delay: float = 1.0
    exponential_backoff: bool = True
    keepalive_interval: float = 30.0
    health_check_interval: float = 60.0
    auto_reconnect: bool = True
    circuit_breaker_threshold: int = 5
    circuit_breaker_timeout: float = 60.0


@dataclass
class RequestMetrics:
    """Request metrics for monitoring."""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    rate_limited_requests: int = 0
    average_response_time: float = 0.0
    last_request_time: float = 0.0
    error_rate: float = 0.0
    current_rate: float = 0.0


class TokenBucket:
    """Token bucket rate limiter implementation.

    Allows bursts of requests up to capacity, then refills at a steady rate.
    """

    def __init__(self, capacity: int, refill_rate: float):
        self.capacity = capacity
        self.tokens = float(capacity)
        self.refill_rate = refill_rate
        self.last_refill = time.time()
        self._lock = threading.Lock()

    def consume(self, tokens: int = 1) -> bool:
        """Attempt to consume tokens from the bucket.

        Args:
            tokens: Number of tokens to consume

        Returns:
            True if tokens were available and consumed
        """
        with self._lock:
            now = time.time()
            elapsed = now - self.last_refill
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
            self.last_refill = now

            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False

    def wait_time(self, tokens: int = 1) -> float:
        """Calculate wait time for tokens to be available."""
        with self._lock:
            if self.tokens >= tokens:
                return 0.0
            needed = tokens - self.tokens
            return needed / self.refill_rate


class SlidingWindowRateLimiter:
    """Sliding window rate limiter implementation.

    Maintains a deque of request timestamps and counts requests within
    the window size.
    """

    def __init__(self, window_size: float, max_requests: int):
        self.window_size = window_size
        self.max_requests = max_requests
        self.requests: deque = deque()
        self._lock = threading.Lock()

    def is_allowed(self) -> bool:
        """Check if a request is allowed within the current window."""
        with self._lock:
            now = time.time()
            while self.requests and self.requests[0] <= now - self.window_size:
                self.requests.popleft()

            if len(self.requests) < self.max_requests:
                self.requests.append(now)
                return True
            return False

    def wait_time(self) -> float:
        """Calculate wait time until next request is allowed."""
        with self._lock:
            if len(self.requests) < self.max_requests:
                return 0.0
            oldest = self.requests[0]
            return max(0.0, oldest + self.window_size - time.time())


class AdaptiveRateLimiter:
    """Adaptive rate limiter that adjusts based on error rates.

    Reduces the request rate when error rates exceed 10% and gradually
    increases when error rates drop below 5%.
    """

    def __init__(self, config: RateLimitConfig):
        self.config = config
        self.base_rate = config.requests_per_second
        self.current_rate = self.base_rate
        self.token_bucket = TokenBucket(config.burst_capacity, self.current_rate)
        self.error_count = 0
        self.success_count = 0
        self.last_adjustment = time.time()
        self._lock = threading.Lock()

    def is_allowed(self) -> bool:
        """Check if request is allowed."""
        return self.token_bucket.consume()

    def record_success(self):
        """Record a successful request."""
        with self._lock:
            self.success_count += 1
            self._adjust_rate()

    def record_error(self):
        """Record a failed request."""
        with self._lock:
            self.error_count += 1
            self._adjust_rate()

    def _adjust_rate(self):
        """Adjust rate based on success/error ratio."""
        now = time.time()
        if now - self.last_adjustment < 10.0:
            return

        total = self.success_count + self.error_count
        if total < 10:
            return

        error_rate = self.error_count / total

        if error_rate > 0.1:
            self.current_rate *= self.config.adaptive_factor
            self.current_rate = max(1.0, self.current_rate)
            logger.warning(
                "rate_limiter_reducing_rate",
                error_rate=error_rate,
                new_rate=self.current_rate,
            )
        elif error_rate < 0.05:
            self.current_rate = min(self.base_rate, self.current_rate * 1.1)

        self.token_bucket.refill_rate = self.current_rate
        self.success_count = 0
        self.error_count = 0
        self.last_adjustment = now

    def wait_time(self) -> float:
        """Calculate wait time."""
        return self.token_bucket.wait_time()


class RateLimiter:
    """Main rate limiter class with multiple strategies.

    Supports token bucket, sliding window, and adaptive strategies.
    Tracks request metrics and provides async acquisition.
    """

    def __init__(self, config: RateLimitConfig):
        self.config = config
        self.metrics = RequestMetrics()
        self._lock = threading.Lock()

        if config.strategy == RateLimitStrategy.TOKEN_BUCKET:
            self.limiter = TokenBucket(config.burst_capacity, config.requests_per_second)
        elif config.strategy == RateLimitStrategy.SLIDING_WINDOW:
            self.limiter = SlidingWindowRateLimiter(1.0, int(config.requests_per_second))
        elif config.strategy == RateLimitStrategy.ADAPTIVE:
            self.limiter = AdaptiveRateLimiter(config)
        else:
            self.limiter = TokenBucket(config.burst_capacity, config.requests_per_second)

    async def acquire(self, tokens: int = 1) -> bool:
        """Acquire permission to make a request.

        If the request is not immediately allowed, waits for the required
        tokens to become available.

        Args:
            tokens: Number of tokens to acquire

        Returns:
            True when permission is granted
        """
        if hasattr(self.limiter, "is_allowed"):
            allowed = self.limiter.is_allowed()
        else:
            allowed = self.limiter.consume(tokens)

        if not allowed:
            wait = self.limiter.wait_time(tokens) if hasattr(self.limiter, "wait_time") else 1.0
            if wait > 0:
                await asyncio.sleep(wait)
                return await self.acquire(tokens)

        with self._lock:
            self.metrics.total_requests += 1
            self.metrics.last_request_time = time.time()

        return True

    def record_success(self, response_time: float = 0.0):
        """Record a successful request."""
        with self._lock:
            self.metrics.successful_requests += 1
            if response_time > 0:
                total = self.metrics.average_response_time * (self.metrics.successful_requests - 1)
                self.metrics.average_response_time = (total + response_time) / self.metrics.successful_requests

        if hasattr(self.limiter, "record_success"):
            self.limiter.record_success()

    def record_failure(self):
        """Record a failed request."""
        with self._lock:
            self.metrics.failed_requests += 1
            total = self.metrics.successful_requests + self.metrics.failed_requests
            self.metrics.error_rate = self.metrics.failed_requests / total if total > 0 else 0.0

        if hasattr(self.limiter, "record_error"):
            self.limiter.record_error()

    def record_rate_limit(self):
        """Record that a request was rate-limited."""
        with self._lock:
            self.metrics.rate_limited_requests += 1

    def get_metrics(self) -> RequestMetrics:
        """Get current rate limiter metrics."""
        with self._lock:
            return RequestMetrics(
                total_requests=self.metrics.total_requests,
                successful_requests=self.metrics.successful_requests,
                failed_requests=self.metrics.failed_requests,
                rate_limited_requests=self.metrics.rate_limited_requests,
                average_response_time=self.metrics.average_response_time,
                last_request_time=self.metrics.last_request_time,
                error_rate=self.metrics.error_rate,
                current_rate=getattr(self.limiter, "current_rate", self.config.requests_per_second),
            )


class CircuitBreaker:
    """Circuit breaker for connection management.

    States:
    - closed: Normal operation, requests pass through
    - open: Too many failures, requests blocked
    - half-open: Testing if service recovered
    """

    def __init__(self, failure_threshold: int = 5, timeout: float = 60.0):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure_time = 0.0
        self.state = "closed"
        self._lock = threading.Lock()

    def call(self, func: Callable, *args, **kwargs):
        """Execute function with circuit breaker protection.

        Raises:
            Exception: If circuit breaker is open or function fails
        """
        with self._lock:
            if self.state == "open":
                if time.time() - self.last_failure_time > self.timeout:
                    self.state = "half-open"
                else:
                    raise Exception("Circuit breaker is open")

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    async def call_async(self, func: Callable, *args, **kwargs):
        """Execute async function with circuit breaker protection."""
        with self._lock:
            if self.state == "open":
                if time.time() - self.last_failure_time > self.timeout:
                    self.state = "half-open"
                else:
                    raise Exception("Circuit breaker is open")

        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise

    def _on_success(self):
        """Handle successful call."""
        with self._lock:
            self.failure_count = 0
            self.state = "closed"

    def _on_failure(self):
        """Handle failed call."""
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.failure_count >= self.failure_threshold:
                self.state = "open"
                logger.warning(
                    "circuit_breaker_opened",
                    failures=self.failure_count,
                    threshold=self.failure_threshold,
                )


class ConnectionManager:
    """Advanced connection manager with pooling and health monitoring.

    Manages multiple named connections with individual:
    - Circuit breakers
    - Rate limiters
    - Health check loops
    - Reconnection logic
    """

    def __init__(self, config: ConnectionConfig):
        self.config = config
        self.connections: Dict[str, Any] = {}
        self.connection_states: Dict[str, ConnectionState] = {}
        self.connection_metrics: Dict[str, RequestMetrics] = defaultdict(RequestMetrics)
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
        self.rate_limiters: Dict[str, RateLimiter] = {}
        self._locks: Dict[str, threading.Lock] = defaultdict(threading.Lock)
        self._health_check_tasks: Dict[str, asyncio.Task] = {}

    def register_connection(
        self,
        connection_id: str,
        connection: Any,
        rate_limit_config: Optional[RateLimitConfig] = None,
    ):
        """Register a connection for management.

        Args:
            connection_id: Unique identifier for this connection
            connection: The connection object (must have .connect(), .disconnect())
            rate_limit_config: Optional rate limiting configuration
        """
        with self._locks[connection_id]:
            self.connections[connection_id] = connection
            self.connection_states[connection_id] = ConnectionState.DISCONNECTED

            self.circuit_breakers[connection_id] = CircuitBreaker(
                self.config.circuit_breaker_threshold,
                self.config.circuit_breaker_timeout,
            )

            if rate_limit_config:
                self.rate_limiters[connection_id] = RateLimiter(rate_limit_config)

        logger.info("connection_registered", connection_id=connection_id)

    async def get_connection(self, connection_id: str) -> Any:
        """Get a connection, connecting if necessary.

        Args:
            connection_id: Connection identifier

        Returns:
            The connection object or None
        """
        with self._locks[connection_id]:
            if connection_id not in self.connections:
                return None

            state = self.connection_states[connection_id]

            if state == ConnectionState.CONNECTED:
                return self.connections[connection_id]
            elif state == ConnectionState.DISCONNECTED:
                await self._connect(connection_id)
                return self.connections.get(connection_id)
            else:
                return None

    async def _connect(self, connection_id: str):
        """Connect with retry logic.

        Args:
            connection_id: Connection identifier
        """
        self.connection_states[connection_id] = ConnectionState.CONNECTING

        for attempt in range(self.config.max_retries):
            try:
                connection = self.connections[connection_id]

                if hasattr(connection, "connect"):
                    if asyncio.iscoroutinefunction(connection.connect):
                        await connection.connect()
                    else:
                        connection.connect()

                self.connection_states[connection_id] = ConnectionState.CONNECTED
                logger.info("connection_established", connection_id=connection_id)

                if connection_id not in self._health_check_tasks:
                    task = asyncio.create_task(self._health_check_loop(connection_id))
                    self._health_check_tasks[connection_id] = task

                return

            except Exception as e:
                logger.warning(
                    "connection_attempt_failed",
                    connection_id=connection_id,
                    attempt=attempt + 1,
                    error=str(e),
                )

                if attempt < self.config.max_retries - 1:
                    delay = self.config.retry_delay
                    if self.config.exponential_backoff:
                        delay *= 2 ** attempt
                    await asyncio.sleep(delay)

        self.connection_states[connection_id] = ConnectionState.ERROR
        logger.error(
            "connection_failed_all_attempts",
            connection_id=connection_id,
            attempts=self.config.max_retries,
        )

    async def _health_check_loop(self, connection_id: str):
        """Continuous health check loop for a connection."""
        while connection_id in self.connections:
            try:
                await asyncio.sleep(self.config.health_check_interval)

                if self.connection_states.get(connection_id) != ConnectionState.CONNECTED:
                    continue

                connection = self.connections.get(connection_id)
                if connection and hasattr(connection, "health_check"):
                    if asyncio.iscoroutinefunction(connection.health_check):
                        healthy = await connection.health_check()
                    else:
                        healthy = connection.health_check()

                    if not healthy:
                        logger.warning("health_check_failed", connection_id=connection_id)
                        if self.config.auto_reconnect:
                            await self._reconnect(connection_id)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("health_check_error", connection_id=connection_id, error=str(e))

    async def _reconnect(self, connection_id: str):
        """Reconnect a connection."""
        self.connection_states[connection_id] = ConnectionState.RECONNECTING
        await self._connect(connection_id)

    @asynccontextmanager
    async def rate_limited_request(self, connection_id: str):
        """Context manager for rate-limited requests.

        Automatically records success/failure for rate and circuit tracking.

        Args:
            connection_id: Connection identifier
        """
        if connection_id in self.rate_limiters:
            await self.rate_limiters[connection_id].acquire()

        start_time = time.time()
        try:
            yield
            response_time = time.time() - start_time
            if connection_id in self.rate_limiters:
                self.rate_limiters[connection_id].record_success(response_time)
        except Exception as e:
            if connection_id in self.rate_limiters:
                self.rate_limiters[connection_id].record_failure()
            raise

    def get_connection_metrics(self, connection_id: str) -> Optional[RequestMetrics]:
        """Get metrics for a specific connection."""
        if connection_id in self.rate_limiters:
            return self.rate_limiters[connection_id].get_metrics()
        return None

    def get_connection_state(self, connection_id: str) -> Optional[ConnectionState]:
        """Get current connection state."""
        return self.connection_states.get(connection_id)

    async def close_connection(self, connection_id: str):
        """Close and cleanup a connection.

        Args:
            connection_id: Connection identifier
        """
        with self._locks[connection_id]:
            if connection_id in self._health_check_tasks:
                self._health_check_tasks[connection_id].cancel()
                del self._health_check_tasks[connection_id]

            if connection_id in self.connections:
                connection = self.connections[connection_id]
                if hasattr(connection, "disconnect"):
                    if asyncio.iscoroutinefunction(connection.disconnect):
                        await connection.disconnect()
                    else:
                        connection.disconnect()
                del self.connections[connection_id]

            self.connection_states.pop(connection_id, None)
            self.circuit_breakers.pop(connection_id, None)
            self.rate_limiters.pop(connection_id, None)

        logger.info("connection_closed", connection_id=connection_id)

    async def close_all_connections(self):
        """Close all managed connections."""
        connection_ids = list(self.connections.keys())
        for connection_id in connection_ids:
            await self.close_connection(connection_id)


def rate_limited(limiter: RateLimiter):
    """Decorator to apply rate limiting to async functions.

    Args:
        limiter: RateLimiter instance to use

    Usage:
        @rate_limited(my_limiter)
        async def my_api_call():
            ...
    """
    def decorator(func):
        async def wrapper(*args, **kwargs):
            await limiter.acquire()
            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                response_time = time.time() - start_time
                limiter.record_success(response_time)
                return result
            except Exception as e:
                limiter.record_failure()
                raise

        return wrapper
    return decorator
