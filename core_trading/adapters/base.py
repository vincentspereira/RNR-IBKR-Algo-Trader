"""Abstract base classes for all adapter implementations.

This module defines the core interfaces that all adapters must implement,
ensuring consistency and interoperability across different broker, data feed,
and database implementations.
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Union


class ConnectionStatus(Enum):
    """Connection status enumeration."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"
    MAINTENANCE = "maintenance"


class AdapterType(Enum):
    """Adapter type enumeration."""
    BROKER = "broker"
    DATA_FEED = "data_feed"
    DATABASE = "database"


@dataclass
class AdapterConfig:
    """Base configuration for all adapters."""
    name: str
    adapter_type: AdapterType
    enabled: bool = True
    auto_reconnect: bool = True
    max_reconnect_attempts: int = 5
    reconnect_delay: timedelta = field(default_factory=lambda: timedelta(seconds=5))
    heartbeat_interval: timedelta = field(default_factory=lambda: timedelta(seconds=30))
    timeout: timedelta = field(default_factory=lambda: timedelta(seconds=10))
    rate_limit_requests_per_second: Optional[int] = None
    credentials: Dict[str, Any] = field(default_factory=dict)
    extra_config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HealthCheck:
    """Health check result."""
    status: ConnectionStatus
    timestamp: datetime
    latency_ms: Optional[float] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseAdapter(ABC):
    """Abstract base class for all adapters.

    Provides common functionality for connection management, health checks,
    error handling, and observability.
    """

    def __init__(self, config: AdapterConfig):
        self.config = config
        self.logger = logging.getLogger(
            f"{self.__class__.__module__}.{self.__class__.__name__}"
        )
        self._status = ConnectionStatus.DISCONNECTED
        self._last_heartbeat: Optional[datetime] = None
        self._reconnect_count = 0
        self._error_count = 0
        self._metrics: Dict[str, Any] = {}
        self._callbacks: Dict[str, List[Callable]] = {}

    @property
    def status(self) -> ConnectionStatus:
        """Get current connection status."""
        return self._status

    @property
    def is_connected(self) -> bool:
        """Check if adapter is connected."""
        return self._status == ConnectionStatus.CONNECTED

    @property
    def metrics(self) -> Dict[str, Any]:
        """Get adapter metrics."""
        return self._metrics.copy()

    @abstractmethod
    async def connect(self) -> bool:
        """Establish connection to the external service."""
        pass

    @abstractmethod
    async def disconnect(self) -> bool:
        """Disconnect from the external service."""
        pass

    @abstractmethod
    async def health_check(self) -> HealthCheck:
        """Perform health check."""
        pass

    async def reconnect(self) -> bool:
        """Attempt to reconnect to the service."""
        if self._reconnect_count >= self.config.max_reconnect_attempts:
            self.logger.error(
                f"Max reconnection attempts ({self.config.max_reconnect_attempts}) exceeded"
            )
            return False

        self._status = ConnectionStatus.RECONNECTING
        self._reconnect_count += 1

        self.logger.info(
            f"Attempting reconnection {self._reconnect_count}/{self.config.max_reconnect_attempts}"
        )

        await asyncio.sleep(self.config.reconnect_delay.total_seconds())

        success = await self.connect()
        if success:
            self._reconnect_count = 0
            self.logger.info("Reconnection successful")
        else:
            self.logger.warning(f"Reconnection attempt {self._reconnect_count} failed")

        return success

    def register_callback(self, event_type: str, callback: Callable):
        """Register callback for specific event type."""
        if event_type not in self._callbacks:
            self._callbacks[event_type] = []
        self._callbacks[event_type].append(callback)

    def _emit_event(self, event_type: str, data: Any = None):
        """Emit event to registered callbacks."""
        if event_type in self._callbacks:
            for callback in self._callbacks[event_type]:
                try:
                    callback(data)
                except Exception as e:
                    self.logger.error(f"Error in callback for {event_type}: {e}")

    def _update_metrics(self, key: str, value: Any):
        """Update adapter metrics."""
        self._metrics[key] = value
        self._metrics["last_updated"] = datetime.now()

    def _set_status(self, status: ConnectionStatus):
        """Set connection status and emit event."""
        old_status = self._status
        self._status = status

        if old_status != status:
            self.logger.info(
                f"Status changed from {old_status.value} to {status.value}"
            )
            self._emit_event(
                "status_changed", {"old_status": old_status, "new_status": status}
            )

    @asynccontextmanager
    async def connection_context(self):
        """Context manager for connection lifecycle."""
        try:
            await self.connect()
            yield self
        finally:
            await self.disconnect()


class BaseBrokerAdapter(BaseAdapter):
    """Abstract base class for broker adapters.

    Provides interface for order management, position tracking,
    and account information retrieval.
    """

    @abstractmethod
    async def place_order(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """Place a trading order."""
        pass

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an existing order."""
        pass

    @abstractmethod
    async def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """Get status of an order."""
        pass

    @abstractmethod
    async def get_positions(self) -> List[Dict[str, Any]]:
        """Get current positions."""
        pass

    @abstractmethod
    async def get_account_info(self) -> Dict[str, Any]:
        """Get account information."""
        pass

    @abstractmethod
    async def get_portfolio_value(self) -> float:
        """Get total portfolio value."""
        pass


class BaseDataFeedAdapter(BaseAdapter):
    """Abstract base class for data feed adapters.

    Provides interface for real-time and historical market data.
    """

    @abstractmethod
    async def subscribe_real_time(
        self, symbols: List[str]
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Subscribe to real-time market data."""
        pass

    @abstractmethod
    async def get_historical_data(
        self, symbol: str, start_date: datetime, end_date: datetime, timeframe: str
    ) -> List[Dict[str, Any]]:
        """Get historical market data."""
        pass

    @abstractmethod
    async def get_quote(self, symbol: str) -> Dict[str, Any]:
        """Get current quote for a symbol."""
        pass

    @abstractmethod
    async def search_symbols(self, query: str) -> List[Dict[str, Any]]:
        """Search for symbols matching query."""
        pass


class BaseDatabaseAdapter(BaseAdapter):
    """Abstract base class for database adapters.

    Provides interface for data storage and retrieval.
    """

    @abstractmethod
    async def execute_query(
        self, query: str, params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Execute a database query."""
        pass

    @abstractmethod
    async def insert_data(
        self, table: str, data: Union[Dict[str, Any], List[Dict[str, Any]]]
    ) -> bool:
        """Insert data into table."""
        pass

    @abstractmethod
    async def update_data(
        self, table: str, data: Dict[str, Any], where_clause: Dict[str, Any]
    ) -> bool:
        """Update data in table."""
        pass

    @abstractmethod
    async def delete_data(self, table: str, where_clause: Dict[str, Any]) -> bool:
        """Delete data from table."""
        pass

    @abstractmethod
    async def create_table(self, table_name: str, schema: Dict[str, str]) -> bool:
        """Create a new table."""
        pass
