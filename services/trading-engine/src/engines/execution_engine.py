"""Execution Engine for institutional-grade order management.

Provides order routing, execution algorithms (VWAP, TWAP), slippage modeling,
smart order routing, fill management, and execution analytics.

Key components:
- Order state machine with validated transitions
- ExecutionEngine with dependency injection
- No random fills - all fills come from broker adapter callbacks
"""

import asyncio
import logging
import math
import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

from ..core.event_system import Event, EventBus, EventPriority, EventType, get_event_bus
from ..core.fault_tolerance import CircuitBreaker, HealthMonitor
from ..core.interfaces import MarketRegime, RiskLevel, SignalStrength


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"
    ICEBERG = "iceberg"
    HIDDEN = "hidden"
    PEGGED = "pegged"
    BRACKET = "bracket"


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ExecutionAlgorithm(Enum):
    MARKET = "market"
    VWAP = "vwap"
    TWAP = "twap"
    POV = "pov"
    IS = "implementation_shortfall"
    ICEBERG = "iceberg"
    SNIPER = "sniper"
    GUERRILLA = "guerrilla"


class VenueType(Enum):
    EXCHANGE = "exchange"
    DARK_POOL = "dark_pool"
    ECN = "ecn"
    MARKET_MAKER = "market_maker"
    CROSSING_NETWORK = "crossing_network"


class ExecutionQuality(Enum):
    EXCELLENT = "excellent"
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Venue:
    """Trading venue configuration."""
    venue_id: str
    name: str
    venue_type: VenueType
    supported_instruments: Set[str]
    supported_order_types: Set[OrderType]
    min_order_size: float
    max_order_size: float
    tick_size: float
    commission_rate: float
    latency_ms: float
    fill_rate: float
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Order:
    """Order representation."""
    order_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    client_order_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    instrument: str = ""
    side: OrderSide = OrderSide.BUY
    order_type: OrderType = OrderType.MARKET
    quantity: float = 0.0
    price: Optional[float] = None
    stop_price: Optional[float] = None
    time_in_force: str = "DAY"
    execution_algorithm: ExecutionAlgorithm = ExecutionAlgorithm.MARKET
    venue_id: Optional[str] = None
    strategy_id: Optional[str] = None
    parent_order_id: Optional[str] = None
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: float = 0.0
    remaining_quantity: float = 0.0
    average_fill_price: float = 0.0
    commission: float = 0.0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)
    broker_order_id: Optional[str] = None
    error_message: Optional[str] = None

    def __post_init__(self):
        self.remaining_quantity = self.quantity


@dataclass
class Fill:
    """Order fill representation."""
    fill_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    order_id: str = ""
    instrument: str = ""
    side: OrderSide = OrderSide.BUY
    quantity: float = 0.0
    price: float = 0.0
    venue_id: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    commission: float = 0.0
    fees: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionReport:
    """Execution performance report."""
    order_id: str
    instrument: str
    side: OrderSide
    total_quantity: float
    filled_quantity: float
    average_fill_price: float
    benchmark_price: float
    slippage: float
    market_impact: float
    timing_cost: float
    commission: float
    total_cost: float
    execution_quality: ExecutionQuality
    venues_used: List[str]
    execution_time_ms: float
    fill_rate: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SlippageModel:
    """Slippage estimation model."""
    instrument: str
    linear_coefficient: float = 0.001
    square_root_coefficient: float = 0.01
    fixed_cost: float = 0.0001
    volatility_adjustment: float = 1.0
    volume_adjustment: float = 1.0
    spread_adjustment: float = 1.0
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Order State Machine
# ---------------------------------------------------------------------------

class OrderStateMachine:
    """Validated order state transitions.

    PENDING -> SUBMITTED, CANCELLED
    SUBMITTED -> PARTIALLY_FILLED, FILLED, CANCELLED, REJECTED, EXPIRED
    PARTIALLY_FILLED -> PARTIALLY_FILLED, FILLED, CANCELLED
    FILLED -> (terminal)
    CANCELLED -> (terminal)
    REJECTED -> (terminal)
    EXPIRED -> (terminal)
    """

    VALID_TRANSITIONS: Dict[OrderStatus, Set[OrderStatus]] = {
        OrderStatus.PENDING: {OrderStatus.SUBMITTED, OrderStatus.CANCELLED},
        OrderStatus.SUBMITTED: {
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        },
        OrderStatus.PARTIALLY_FILLED: {
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
        },
        OrderStatus.FILLED: set(),
        OrderStatus.CANCELLED: set(),
        OrderStatus.REJECTED: set(),
        OrderStatus.EXPIRED: set(),
    }

    TERMINAL_STATES = {
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
    }

    def __init__(self, event_bus: Optional[EventBus] = None):
        self._event_bus = event_bus
        self._logger = logging.getLogger(__name__)

    def transition(self, order: Order, new_status: OrderStatus) -> None:
        """Validate and execute a state transition."""
        current = order.status
        allowed = self.VALID_TRANSITIONS.get(current, set())

        if new_status not in allowed:
            raise ValueError(
                f"Invalid order state transition: {current.value} -> {new_status.value} "
                f"(order_id={order.order_id})"
            )

        old_status = current
        order.status = new_status
        order.updated_at = datetime.now(timezone.utc)

        self._logger.info(
            f"Order {order.order_id}: {old_status.value} -> {new_status.value}"
        )

        if self._event_bus:
            event = Event(
                type=EventType.ORDER,
                data={
                    "order_id": order.order_id,
                    "old_status": old_status.value,
                    "new_status": new_status.value,
                },
                priority=EventPriority.HIGH,
                source="order_state_machine",
            )
            asyncio.create_task(self._event_bus.publish(event))

    def is_terminal(self, status: OrderStatus) -> bool:
        return status in self.TERMINAL_STATES


# ---------------------------------------------------------------------------
# Execution Algorithm Base
# ---------------------------------------------------------------------------

class ExecutionAlgorithmBase(ABC):
    """Base class for execution algorithms."""

    def __init__(self, name: str):
        self.name = name
        self.parameters: Dict[str, Any] = {}

    @abstractmethod
    async def execute(self, order: Order, market_data: Dict[str, Any]) -> List[Order]:
        """Execute the order using the algorithm, returning child orders."""
        raise NotImplementedError

    @abstractmethod
    def estimate_execution_time(self, order: Order, market_data: Dict[str, Any]) -> float:
        """Estimate execution time in seconds."""
        raise NotImplementedError

    @abstractmethod
    def estimate_market_impact(self, order: Order, market_data: Dict[str, Any]) -> float:
        """Estimate market impact as percentage of order value."""
        raise NotImplementedError


class VWAPAlgorithm(ExecutionAlgorithmBase):
    """Volume Weighted Average Price execution algorithm."""

    def __init__(self):
        super().__init__("VWAP")
        self.parameters = {
            "participation_rate": 0.1,
            "max_participation_rate": 0.3,
            "min_fill_size": 100,
            "urgency_factor": 1.0,
        }

    async def execute(self, order: Order, market_data: Dict[str, Any]) -> List[Order]:
        child_orders = []
        volume_profile = self._get_volume_profile(order.instrument, market_data)
        execution_horizon = self._calculate_execution_horizon()
        time_slices = self._create_time_slices(execution_horizon)

        remaining_quantity = order.quantity

        for i, time_slice in enumerate(time_slices):
            if remaining_quantity <= 0:
                break

            expected_volume = volume_profile.get(time_slice, 0)
            participation_rate = min(
                self.parameters["participation_rate"] * self.parameters["urgency_factor"],
                self.parameters["max_participation_rate"],
            )

            slice_quantity = min(
                expected_volume * participation_rate,
                remaining_quantity,
                self.parameters["min_fill_size"],
            )

            if slice_quantity > 0:
                child_order = Order(
                    order_id=f"{order.order_id}_slice_{i}",
                    client_order_id=f"{order.client_order_id}_slice_{i}",
                    instrument=order.instrument,
                    side=order.side,
                    order_type=OrderType.LIMIT,
                    quantity=slice_quantity,
                    price=self._calculate_limit_price(order, market_data, time_slice),
                    parent_order_id=order.order_id,
                    execution_algorithm=ExecutionAlgorithm.VWAP,
                    metadata={"time_slice": time_slice, "expected_volume": expected_volume},
                )
                child_orders.append(child_order)
                remaining_quantity -= slice_quantity

        return child_orders

    def estimate_execution_time(self, order: Order, market_data: Dict[str, Any]) -> float:
        daily_volume = market_data.get("daily_volume", 1000000)
        participation_rate = self.parameters["participation_rate"]
        expected_volume_participation = daily_volume * participation_rate
        execution_time_hours = (order.quantity / expected_volume_participation) * 6.5
        return max(execution_time_hours * 3600, 300)

    def estimate_market_impact(self, order: Order, market_data: Dict[str, Any]) -> float:
        daily_volume = market_data.get("daily_volume", 1000000)
        volatility = market_data.get("volatility", 0.02)
        volume_ratio = order.quantity / daily_volume
        impact = 0.1 * volatility * math.sqrt(volume_ratio)
        return min(impact, 0.005)

    def _get_volume_profile(self, instrument: str, market_data: Dict[str, Any]) -> Dict[str, float]:
        return {
            "09:30": 0.15, "10:00": 0.12, "10:30": 0.08,
            "11:00": 0.06, "11:30": 0.05, "12:00": 0.04,
            "12:30": 0.04, "13:00": 0.04, "13:30": 0.05,
            "14:00": 0.06, "14:30": 0.08, "15:00": 0.10,
            "15:30": 0.13,
        }

    def _calculate_execution_horizon(self) -> int:
        return 240

    def _create_time_slices(self, horizon_minutes: int) -> List[str]:
        slices = []
        current_time = datetime.now().replace(second=0, microsecond=0)
        for i in range(0, horizon_minutes, 30):
            slice_time = current_time + __import__("datetime").timedelta(minutes=i)
            slices.append(slice_time.strftime("%H:%M"))
        return slices

    def _calculate_limit_price(self, order: Order, market_data: Dict[str, Any], time_slice: str) -> float:
        current_price = market_data.get("current_price", 100.0)
        spread = market_data.get("spread", 0.01)
        if order.side == OrderSide.BUY:
            return current_price + spread * 0.3
        else:
            return current_price - spread * 0.3


class TWAPAlgorithm(ExecutionAlgorithmBase):
    """Time Weighted Average Price execution algorithm."""

    def __init__(self):
        super().__init__("TWAP")
        self.parameters = {
            "execution_horizon": 3600,
            "slice_interval": 300,
            "price_improvement_threshold": 0.001,
        }

    async def execute(self, order: Order, market_data: Dict[str, Any]) -> List[Order]:
        child_orders = []
        execution_horizon = self.parameters["execution_horizon"]
        slice_interval = self.parameters["slice_interval"]
        num_slices = execution_horizon // slice_interval
        slice_quantity = order.quantity / num_slices

        for i in range(num_slices):
            child_order = Order(
                order_id=f"{order.order_id}_twap_{i}",
                client_order_id=f"{order.client_order_id}_twap_{i}",
                instrument=order.instrument,
                side=order.side,
                order_type=OrderType.LIMIT,
                quantity=slice_quantity,
                price=self._calculate_twap_price(order, market_data),
                parent_order_id=order.order_id,
                execution_algorithm=ExecutionAlgorithm.TWAP,
                metadata={"slice_number": i, "total_slices": num_slices},
            )
            child_orders.append(child_order)

        return child_orders

    def estimate_execution_time(self, order: Order, market_data: Dict[str, Any]) -> float:
        return float(self.parameters["execution_horizon"])

    def estimate_market_impact(self, order: Order, market_data: Dict[str, Any]) -> float:
        volatility = market_data.get("volatility", 0.02)
        return 0.05 * volatility

    def _calculate_twap_price(self, order: Order, market_data: Dict[str, Any]) -> float:
        current_price = market_data.get("current_price", 100.0)
        spread = market_data.get("spread", 0.01)
        if order.side == OrderSide.BUY:
            return current_price + spread * 0.1
        else:
            return current_price - spread * 0.1


# ---------------------------------------------------------------------------
# Execution Engine
# ---------------------------------------------------------------------------

class ExecutionEngine:
    """Core execution engine for institutional-grade order management.

    Provides intelligent order routing, execution algorithms, slippage modeling,
    and comprehensive execution analytics.
    """

    def __init__(
        self,
        broker_adapter=None,
        event_bus: Optional[EventBus] = None,
        risk_engine=None,
        order_store=None,
    ):
        self._broker_adapter = broker_adapter
        self._event_bus = event_bus or get_event_bus()
        self._risk_engine = risk_engine
        self._order_store = order_store

        self._venues: Dict[str, Venue] = {}
        self._orders: Dict[str, Order] = {}
        self._fills: Dict[str, List[Fill]] = {}
        self._execution_reports: Dict[str, ExecutionReport] = {}
        self._slippage_models: Dict[str, SlippageModel] = {}
        self._algorithms: Dict[ExecutionAlgorithm, ExecutionAlgorithmBase] = {}
        self._state_machine = OrderStateMachine(event_bus=self._event_bus)
        self._health_monitor = HealthMonitor()
        self._circuit_breaker = CircuitBreaker()
        self._lock = threading.RLock()
        self._shutdown_event = asyncio.Event()
        self._execution_tasks: Dict[str, asyncio.Task] = {}

    async def initialize(self) -> bool:
        """Initialize the execution engine and reconcile state on startup."""
        try:
            self._algorithms[ExecutionAlgorithm.VWAP] = VWAPAlgorithm()
            self._algorithms[ExecutionAlgorithm.TWAP] = TWAPAlgorithm()
            self._load_default_venues()
            self._load_slippage_models()

            self._event_bus.subscribe(
                EventType.ORDER, self._handle_order_request
            )

            # Reconcile persisted orders with broker state on startup
            await self.reconcile_on_startup()

            logger.info("Execution engine initialized successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize execution engine: {e}")
            return False

    async def shutdown(self):
        """Shutdown the execution engine."""
        try:
            self._shutdown_event.set()
            for task in self._execution_tasks.values():
                task.cancel()
            if self._execution_tasks:
                await asyncio.gather(*self._execution_tasks.values(), return_exceptions=True)
            logger.info("Execution engine shutdown completed")
        except Exception as e:
            logger.error(f"Error during execution engine shutdown: {e}")

    def _load_default_venues(self):
        """Load default trading venues."""
        venues = [
            Venue(
                venue_id="NYSE",
                name="New York Stock Exchange",
                venue_type=VenueType.EXCHANGE,
                supported_instruments={"STOCKS", "ETF"},
                supported_order_types={OrderType.MARKET, OrderType.LIMIT, OrderType.STOP},
                min_order_size=1,
                max_order_size=1000000,
                tick_size=0.01,
                commission_rate=0.005,
                latency_ms=2.5,
                fill_rate=0.95,
            ),
            Venue(
                venue_id="NASDAQ",
                name="NASDAQ",
                venue_type=VenueType.EXCHANGE,
                supported_instruments={"STOCKS", "ETF"},
                supported_order_types={
                    OrderType.MARKET, OrderType.LIMIT, OrderType.STOP, OrderType.HIDDEN,
                },
                min_order_size=1,
                max_order_size=1000000,
                tick_size=0.01,
                commission_rate=0.005,
                latency_ms=2.0,
                fill_rate=0.96,
            ),
        ]
        for venue in venues:
            self._venues[venue.venue_id] = venue

    def _load_slippage_models(self):
        """Load default slippage model."""
        self._slippage_models["DEFAULT"] = SlippageModel(instrument="DEFAULT")

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    async def submit_order(self, order: Order) -> bool:
        """Submit an order for execution.

        Validates via risk engine, submits to broker, tracks in state machine.
        """
        try:
            if not self._validate_order(order):
                self._state_machine.transition(order, OrderStatus.REJECTED)
                return False

            # Pre-trade risk check
            if self._risk_engine:
                approved = await self._risk_engine.pre_trade_check(order)
                if not approved:
                    self._state_machine.transition(order, OrderStatus.REJECTED)
                    return False

            if not self._circuit_breaker.allow_request():
                logger.warning(f"Circuit breaker open - rejecting order {order.order_id}")
                self._state_machine.transition(order, OrderStatus.REJECTED)
                return False

            with self._lock:
                self._orders[order.order_id] = order
                self._fills[order.order_id] = []

            self._state_machine.transition(order, OrderStatus.SUBMITTED)

            # Submit to broker adapter
            if self._broker_adapter:
                result = await self._broker_adapter.place_order({
                    "symbol": order.instrument,
                    "side": order.side.value,
                    "quantity": order.quantity,
                    "order_type": order.order_type.value,
                    "price": order.price,
                    "stop_price": order.stop_price,
                })
                if result.get("status") == "rejected":
                    self._state_machine.transition(order, OrderStatus.REJECTED)
                    order.error_message = result.get("reason", "Rejected by broker")
                    return False
                order.broker_order_id = result.get("broker_order_id")

            # Persist order to database
            if self._order_store:
                try:
                    await self._order_store.save_order(order)
                except Exception as e:
                    logger.warning(f"Failed to persist order {order.order_id}: {e}")

            logger.info(
                f"Order submitted: {order.order_id} "
                f"({order.instrument} {order.side.value} {order.quantity})"
            )
            return True

        except Exception as e:
            self._circuit_breaker.record_failure()
            logger.error(f"Error submitting order {order.order_id}: {e}")
            return False

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an order."""
        try:
            with self._lock:
                order = self._orders.get(order_id)
                if not order:
                    return False

                if self._state_machine.is_terminal(order.status):
                    return False

            # Cancel at broker first
            if self._broker_adapter:
                await self._broker_adapter.cancel_order(order.broker_order_id or order_id)

            self._state_machine.transition(order, OrderStatus.CANCELLED)

            if order_id in self._execution_tasks:
                self._execution_tasks[order_id].cancel()

            logger.info(f"Order cancelled: {order_id}")
            return True

        except Exception as e:
            logger.error(f"Error cancelling order {order_id}: {e}")
            return False

    async def handle_fill(
        self,
        order_id: str,
        fill_quantity: float,
        fill_price: float,
    ) -> None:
        """Process a partial or full fill from broker adapter callback."""
        with self._lock:
            order = self._orders.get(order_id)
            if not order:
                logger.warning(f"Fill received for unknown order: {order_id}")
                return

        fill = Fill(
            order_id=order_id,
            instrument=order.instrument,
            side=order.side,
            quantity=fill_quantity,
            price=fill_price,
        )

        with self._lock:
            order.filled_quantity += fill_quantity
            order.remaining_quantity = order.quantity - order.filled_quantity

            # Weighted average fill price
            if order.filled_quantity > 0:
                old_total = order.average_fill_price * (order.filled_quantity - fill_quantity)
                order.average_fill_price = (old_total + fill_price * fill_quantity) / order.filled_quantity

            self._fills.setdefault(order_id, []).append(fill)

        # State transition
        if order.remaining_quantity <= 0:
            self._state_machine.transition(order, OrderStatus.FILLED)
        else:
            self._state_machine.transition(order, OrderStatus.PARTIALLY_FILLED)

        # Emit fill event
        await self._event_bus.publish(Event(
            type=EventType.FILL,
            data={"order_id": order_id, "fill_quantity": fill_quantity, "fill_price": fill_price},
            priority=EventPriority.HIGH,
            source="execution_engine",
        ))

        self._circuit_breaker.record_success()
        logger.info(
            f"Fill processed: {order_id} qty={fill_quantity} @ {fill_price} "
            f"(total filled: {order.filled_quantity}/{order.quantity})"
        )

    def _find_order_by_broker_id(self, broker_order_id: str) -> Optional["Order"]:
        """Return the local Order whose broker_order_id matches, else None."""
        with self._lock:
            for order in self._orders.values():
                if order.broker_order_id is not None and \
                        str(order.broker_order_id) == str(broker_order_id):
                    return order
        return None

    async def handle_fill_by_broker_id(
        self,
        broker_order_id: str,
        fill_quantity: float,
        fill_price: float,
    ) -> None:
        """Process a fill keyed by broker_order_id (e.g. IBKR execDetailsEvent)."""
        order = self._find_order_by_broker_id(broker_order_id)
        if order is None:
            logger.warning(
                f"Fill received for unknown broker_order_id={broker_order_id} "
                f"(local order map has {len(self._orders)} orders)"
            )
            return
        await self.handle_fill(order.order_id, fill_quantity, fill_price)

    async def handle_status_by_broker_id(
        self,
        broker_order_id: str,
        broker_status: str,
    ) -> None:
        """Process a broker status update keyed by broker_order_id.

        Maps ib_insync OrderStatus strings to OrderStateMachine transitions.
        Filled is handled by handle_fill_by_broker_id (via execDetailsEvent),
        so we only act on terminal cancel/reject/inactive transitions here.
        """
        status_norm = broker_status.lower()
        # ib_insync statuses: PendingSubmit, PreSubmitted, Submitted,
        # Filled, Cancelled, ApiCancelled, Inactive
        if status_norm in ("cancelled", "apicancelled"):
            new_status = OrderStatus.CANCELLED
        elif status_norm == "inactive":
            new_status = OrderStatus.REJECTED
        else:
            return  # informational only

        order = self._find_order_by_broker_id(broker_order_id)
        if order is None:
            return
        if self._state_machine.is_terminal(order.status):
            return
        try:
            self._state_machine.transition(order, new_status)
        except ValueError as e:
            logger.warning(
                f"Refused status transition for {order.order_id} "
                f"({order.status.value} -> {new_status.value}): {e}"
            )

    async def reconcile_positions(self) -> None:
        """Sync local state with broker positions."""
        if not self._broker_adapter:
            logger.warning("No broker adapter - cannot reconcile positions")
            return

        try:
            broker_positions = await self._broker_adapter.get_positions()
            logger.info(f"Reconciliation: broker reports {len(broker_positions)} positions")

            for pos in broker_positions:
                logger.info(
                    f"Position: {pos.get('symbol')} qty={pos.get('quantity')} "
                    f"avg_cost={pos.get('avg_cost')}"
                )

            await self._event_bus.publish(Event(
                type=EventType.SYSTEM,
                data={"action": "reconciliation_complete", "positions": len(broker_positions)},
                source="execution_engine",
            ))
        except Exception as e:
            logger.error(f"Position reconciliation failed: {e}")

    async def reconcile_on_startup(self) -> None:
        """Full startup reconciliation: sync persisted orders with broker, then sync positions.

        1. Load active orders from DB via OrderStore
        2. Reconcile each order with broker status
        3. Restore reconciled orders to local state
        4. Sync positions with broker
        """
        # Step 1: Reconcile persisted orders with broker
        if self._order_store and self._broker_adapter:
            try:
                summary = await self._order_store.reconcile_on_startup(self._broker_adapter)
                logger.info(
                    f"Order reconciliation: {summary.get('db_active_orders', 0)} DB orders, "
                    f"{summary.get('reconciled', 0)} reconciled, "
                    f"{summary.get('cancelled_in_db', 0)} cancelled"
                )

                # Reload reconciled active orders into local state
                active_db_orders = await self._order_store.get_active_orders()
                for db_order in active_db_orders:
                    order = Order(
                        order_id=db_order.get("order_id", ""),
                        instrument=db_order.get("symbol", ""),
                        side=OrderSide(db_order.get("side", "buy").lower()),
                        order_type=OrderType(db_order.get("order_type", "market").lower()),
                        quantity=float(db_order.get("quantity", 0)),
                        price=db_order.get("price"),
                        stop_price=db_order.get("stop_price"),
                        status=OrderStatus(db_order.get("status", "pending").lower()),
                        filled_quantity=float(db_order.get("filled_quantity", 0)),
                        average_fill_price=db_order.get("avg_fill_price", 0) or 0,
                        commission=float(db_order.get("commission", 0)),
                        broker_order_id=db_order.get("broker_order_id"),
                        strategy_id=str(db_order.get("strategy_id")) if db_order.get("strategy_id") else None,
                    )
                    order.remaining_quantity = order.quantity - order.filled_quantity
                    self._orders[order.order_id] = order
                    self._fills.setdefault(order.order_id, [])

                if active_db_orders:
                    logger.info(f"Restored {len(active_db_orders)} active orders from database")

            except Exception as e:
                logger.error(f"Order store reconciliation failed: {e}")

        # Step 2: Reconcile positions with broker
        await self.reconcile_positions()

        # Step 3: Emit reconciliation complete event
        await self._event_bus.publish(Event(
            type=EventType.SYSTEM,
            data={
                "action": "startup_reconciliation_complete",
                "active_orders": len(self.get_active_orders()),
                "has_order_store": self._order_store is not None,
            },
            source="execution_engine",
        ))

    def get_active_orders(self) -> List[Order]:
        """Return all non-terminal orders."""
        return [
            o for o in self._orders.values()
            if not self._state_machine.is_terminal(o.status)
        ]

    def get_order(self, order_id: str) -> Optional[Order]:
        """Return order by ID."""
        return self._orders.get(order_id)

    def get_orders(self, status: Optional[OrderStatus] = None) -> List[Order]:
        """Get orders, optionally filtered by status."""
        orders = list(self._orders.values())
        if status:
            orders = [o for o in orders if o.status == status]
        return orders

    def get_fills(self, order_id: str) -> List[Fill]:
        """Get fills for an order."""
        return self._fills.get(order_id, [])

    def get_execution_report(self, order_id: str) -> Optional[ExecutionReport]:
        """Get execution report for an order."""
        return self._execution_reports.get(order_id)

    def get_venues(self) -> List[Venue]:
        """Get all configured venues."""
        return list(self._venues.values())

    def add_venue(self, venue: Venue):
        """Add a trading venue."""
        with self._lock:
            self._venues[venue.venue_id] = venue
        logger.info(f"Added venue: {venue.name}")

    # -----------------------------------------------------------------------
    # Internal methods
    # -----------------------------------------------------------------------

    async def _handle_order_request(self, event: Event):
        """Handle order request events from event bus."""
        try:
            if isinstance(event.data, dict):
                order = Order(**event.data)
                await self.submit_order(order)
        except Exception as e:
            logger.error(f"Error handling order request: {e}")

    def _validate_order(self, order: Order) -> bool:
        """Validate order parameters."""
        if not order.instrument or order.quantity <= 0:
            return False
        if order.order_type in (OrderType.LIMIT, OrderType.STOP_LIMIT) and not order.price:
            return False
        if order.order_type in (OrderType.STOP, OrderType.STOP_LIMIT) and not order.stop_price:
            return False
        return True

    def _estimate_slippage(
        self, order: Order, market_data: Dict[str, Any], venue: Venue
    ) -> float:
        """Estimate slippage for order execution."""
        model = self._slippage_models.get(
            order.instrument, self._slippage_models.get("DEFAULT")
        )
        if not model:
            return 0.001

        daily_volume = market_data.get("daily_volume", 1000000)
        volatility = market_data.get("volatility", 0.02)
        spread = market_data.get("spread", 0.01)
        volume_ratio = order.quantity / daily_volume

        linear_impact = model.linear_coefficient * volume_ratio
        sqrt_impact = model.square_root_coefficient * math.sqrt(volume_ratio)
        total = linear_impact + sqrt_impact + model.fixed_cost
        total += volatility * model.volatility_adjustment
        total += spread * model.spread_adjustment

        return min(total, 0.01)


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_execution_engine: Optional[ExecutionEngine] = None


def get_execution_engine() -> ExecutionEngine:
    """Get the global execution engine instance."""
    global _execution_engine
    if _execution_engine is None:
        _execution_engine = ExecutionEngine()
    return _execution_engine
