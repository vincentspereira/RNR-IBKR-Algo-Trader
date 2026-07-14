# RNR-IBKR-Algo-Trader - Production Readiness Implementation Plan

**Date:** April 6, 2026
**Based on:** Comprehensive Production Readiness Audit
**Current State:** ~15-20% production ready
**Target:** 85%+ production ready

---

## How to Use This Plan

This plan is structured as step-by-step instructions for Claude Code. Each phase has numbered tasks with specific files to modify, patterns to follow, and verification steps. Execute phases sequentially. Within each phase, tasks marked [PARALLEL] can be done simultaneously.

---

## PHASE 0: Clean Up the Codebase (Pre-requisite)

### Why
50 handler-stub directories (249 files) and dual adapter architectures create confusion. Remove dead weight before building.

### Task 0.1: Delete all empty handler stub directories
**Instruction for Claude Code:**
```
Delete ALL directories matching *_handlers recursively, EXCEPT those inside core_trading/adapters/brokers/ (those are part of the old adapter structure we'll handle separately).

These 50 directories contain 249+ files that are all identical stubs returning {"status": "handled"} with zero business logic.

Directories to delete (example pattern):
- core_trading/brokers/*adapter_handlers/
- core_trading/strategies/*_handlers/
- core_trading/strategies/momentum/*_handlers/
- core_trading/strategies/mean_reversion/*_handlers/
- core_trading/strategies/architecture/pillars/*_handlers/
- core_trading/strategies/backtesting/*_handlers/
- core_trading/strategies/core/*_handlers/
- core_trading/strategies/machine_learning/*_handlers/
- core_trading/strategies/utils/*_handlers/
- core_trading/strategies/seasonal/*_handlers/
- core_trading/strategies/volatility_breakout/*_handlers/
- core_trading/strategies/volume_weighted/*_handlers/
- core_trading/data_feeds/*_handlers/
- core_trading/adapters/brokers/alpacaadapter_handlers/

Command: find . -type d -name "*_handlers" -exec rm -rf {} +
```
**Verify:** `find . -type d -name "*_handlers" | wc -l` should return 0.

### Task 0.2: Delete the new-structure broker adapter skeletons
**Why:** `core_trading/brokers/` contains 9 adapter files (~58 lines each) and their handler dirs. All are empty stubs. The real code is in `core_trading/adapters/brokers/`.

```
Delete entire directory: core_trading/brokers/
Keep: core_trading/adapters/brokers/ (old structure with real code)
```
**Verify:** `ls core_trading/brokers/` should fail (directory gone).

### Task 0.3: Rewrite `core_trading/adapters/base.py` from scratch
**Why:** The file is 487 lines but 100% commented out. All classes (ConnectionStatus, AdapterConfig, BaseAdapter, BaseBrokerAdapter, BaseDataFeedAdapter, BaseDatabaseAdapter) are defined with `class Foo:""` syntax and body commented out. This is a COMPLETE REWRITE following the "Code Restoration Pattern" from CLAUDE.md.

**Steps:**
1. Read the entire file to understand the intended logic
2. Write a clean version with proper Python:
   - `ConnectionStatus` enum with DISCONNECTED, CONNECTING, CONNECTED, RECONNECTING, ERROR, MAINTENANCE
   - `AdapterType` enum with BROKER, DATA_FEED, DATABASE
   - `AdapterConfig` dataclass with all fields from comments
   - `HealthCheck` dataclass
   - `BaseAdapter` ABC with connect(), disconnect(), health_check(), reconnect(), register_callback(), _emit_event(), _update_metrics(), _set_status(), connection_context()
   - `BaseBrokerAdapter(BaseAdapter)` ABC with place_order(), cancel_order(), get_order_status(), get_positions(), get_account_info(), get_portfolio_value()
   - `BaseDataFeedAdapter(BaseAdapter)` ABC with subscribe_real_time(), get_historical_data(), get_quote(), search_symbols()
   - `BaseDatabaseAdapter(BaseAdapter)` ABC with execute_query(), insert_data(), update_data(), delete_data(), create_table()
3. Use 4-space indentation, proper docstrings, type hints
4. Verify: `python -m py_compile core_trading/adapters/base.py`

### Task 0.4: Consolidate adapter structure
After Task 0.2, the single adapter structure is `core_trading/adapters/`. Verify these files exist and are the canonical source:
- `core_trading/adapters/base.py` (rewritten in 0.3)
- `core_trading/adapters/broker_adapter.py`
- `core_trading/adapters/broker_factory.py`
- `core_trading/adapters/ibkr_adapter.py`
- `core_trading/adapters/interactive_brokers.py`
- `core_trading/adapters/fix_client.py`
- `core_trading/adapters/brokers/` (old structure with real implementations)

Update `core_trading/adapters/__init__.py` to export the correct classes.

---

## PHASE 1: Make It Run (Critical Path)

### Task 1.1: Implement the Event Bus [CRITICAL]
**File:** `services/trading-engine/src/core/event_system.py`
**Current:** 35 lines, `publish()` and `subscribe()` both `pass`
**Impact:** Without this, NO component communication works.

**Rewrite the entire file with:**

```python
# Pattern to follow (Kafka-backed EventBus):
import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Awaitable
from dataclasses import dataclass, field
import structlog

logger = structlog.get_logger(__name__)

class EventPriority(Enum):
    LOW = auto()
    NORMAL = auto()
    HIGH = auto()
    CRITICAL = auto()

class EventType(Enum):
    MARKET_DATA = auto()
    SIGNAL = auto()
    ORDER = auto()
    FILL = auto()
    POSITION_UPDATE = auto()
    RISK_ALERT = auto()
    ERROR = auto()
    SYSTEM = auto()

@dataclass
class Event:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    type: EventType = EventType.SYSTEM
    data: Any = None
    priority: EventPriority = EventPriority.NORMAL
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = ""

class EventBus:
    def __init__(self):
        self._subscribers: Dict[EventType, List[Callable]] = defaultdict(list)
        self._global_subscribers: List[Callable] = []
        self._event_history: List[Event] = []
        self._max_history = 10000
        self._lock = asyncio.Lock()
        self._running = True

    async def publish(self, event: Event) -> None:
        """Publish event to all subscribers of that event type + global subscribers."""
        async with self._lock:
            self._event_history.append(event)
            if len(self._event_history) > self._max_history:
                self._event_history = self._event_history[-self._max_history:]

        subscribers = self._subscribers.get(event.type, []) + self._global_subscribers

        # Priority ordering: CRITICAL first, then HIGH, NORMAL, LOW
        tasks = []
        for callback in subscribers:
            try:
                result = callback(event)
                if asyncio.iscoroutine(result):
                    tasks.append(result)
            except Exception as e:
                logger.error("event_callback_error", error=str(e), event_type=event.type.name)

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def subscribe(self, event_type: EventType, callback: Callable[[Event], Awaitable[None]]):
        """Subscribe callback to specific event type."""
        self._subscribers[event_type].append(callback)
        logger.info("event_subscribed", event_type=event_type.name)

    def subscribe_all(self, callback: Callable[[Event], Awaitable[None]]):
        """Subscribe to ALL events."""
        self._global_subscribers.append(callback)

    def unsubscribe(self, event_type: EventType, callback: Callable):
        """Remove a callback subscription."""
        if event_type in self._subscribers:
            self._subscribers[event_type] = [
                cb for cb in self._subscribers[event_type] if cb != callback
            ]

    async def get_history(self, event_type: Optional[EventType] = None, limit: int = 100) -> List[Event]:
        """Get recent events, optionally filtered by type."""
        events = self._event_history
        if event_type:
            events = [e for e in events if e.type == event_type]
        return events[-limit:]

# Singleton
_event_bus: Optional[EventBus] = None

def get_event_bus() -> EventBus:
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus
```

**Verify:** `python -m py_compile services/trading-engine/src/core/event_system.py`

### Task 1.2: Implement Circuit Breakers and Fault Tolerance [CRITICAL]
**File:** `services/trading-engine/src/core/fault_tolerance.py`
**Current:** 21 lines, `allow_request()` always returns True
**Pattern:** Standard circuit breaker pattern (CLOSED -> OPEN -> HALF_OPEN)

**Rewrite the entire file with proper circuit breaker:**

```python
import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
import structlog

logger = structlog.get_logger(__name__)

class CircuitState(Enum):
    CLOSED = "closed"       # Normal operation
    OPEN = "open"           # Blocking requests
    HALF_OPEN = "half_open" # Testing if service recovered

@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5
    recovery_timeout: float = 60.0       # seconds
    half_open_max_calls: int = 3
    success_threshold: int = 3           # successes to close from half-open
    window_seconds: float = 60.0         # sliding window for failure counting

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
            if self._last_failure_time and (time.time() - self._last_failure_time) >= self.config.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                self._success_count = 0
                logger.info("circuit_breaker_half_open", name=self.name)
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
        else:  # OPEN
            return False

    def record_success(self):
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.config.success_threshold:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._failure_times.clear()
                logger.info("circuit_breaker_closed", name=self.name)
        elif self._state == CircuitState.CLOSED:
            self._failure_count = max(0, self._failure_count - 1)

    def record_failure(self, error: Optional[Exception] = None):
        now = time.time()
        self._failure_times.append(now)
        self._last_failure_time = now

        # Clean old failures outside window
        cutoff = now - self.config.window_seconds
        self._failure_times = [t for t in self._failure_times if t > cutoff]

        self._failure_count = len(self._failure_times)

        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.OPEN
            logger.warning("circuit_breaker_open_from_half_open", name=self.name)
        elif self._failure_count >= self.config.failure_threshold:
            self._state = CircuitState.OPEN
            logger.error("circuit_breaker_open", name=self.name, failures=self._failure_count)

class HealthMonitor:
    def __init__(self):
        self._components: Dict[str, Dict[str, Any]] = {}
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}

    def register_component(self, name: str, health_check_fn: Callable, circuit_config: Optional[CircuitBreakerConfig] = None):
        self._components[name] = {"check_fn": health_check_fn, "healthy": True, "last_check": None}
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
            return {"status": "healthy" if result else "unhealthy", "circuit": self._circuit_breakers[name].state.value}
        except Exception as e:
            comp["healthy"] = False
            comp["last_check"] = time.time()
            return {"status": "error", "error": str(e), "circuit": self._circuit_breakers[name].state.value}

    def get_circuit_breaker(self, name: str) -> CircuitBreaker:
        return self._circuit_breakers.get(name, CircuitBreaker(name=name))

# Singleton
_health_monitor: Optional[HealthMonitor] = None

def get_health_monitor() -> HealthMonitor:
    global _health_monitor
    if _health_monitor is None:
        _health_monitor = HealthMonitor()
    return _health_monitor
```

**Verify:** `python -m py_compile services/trading-engine/src/core/fault_tolerance.py`

### Task 1.3: Rewrite the IBKR Adapter [HIGHEST PRIORITY]
**Files:**
- `core_trading/adapters/ibkr_adapter.py` (99% commented out)
- `core_trading/adapters/interactive_brokers.py` (100% commented out)

**This is THE single most important task. Without IBKR connectivity, nothing trades.**

**Approach:** COMPLETE REWRITE (per CLAUDE.md Code Restoration Pattern). Do NOT attempt to uncomment.

**Step 1:** Read both files completely to extract the intended design from comments.

**Step 2:** Write a clean `core_trading/adapters/ibkr_adapter.py` that:

1. **Imports `ib_insync`** with graceful fallback:
```python
try:
    from ib_insync import IB, Stock, Option, Future, Forex, Contract, Order, Trade, util
    IBKR_AVAILABLE = True
except ImportError:
    IBKR_AVAILABLE = False
    logging.warning("ib_insync not available - IBKR adapter will be simulated")
```

2. **Implements `IBKRAdapter(BaseBrokerAdapter)`** with these methods:
   - `__init__(config)` — Initialize with host, port, client_id, account_id, paper_trading flag
   - `async connect()` — Connect to TWS/Gateway with retry logic
   - `async disconnect()` — Clean disconnect
   - `async health_check()` — Check connection alive via `ib.isConnected()`
   - `async place_order(order_data)` — Create Contract + Order, submit via `ib.placeOrder()`
   - `async cancel_order(order_id)` — Cancel via trade object lookup
   - `async get_order_status(order_id)` — Query order status from `ib.openOrders()` or `ib.trades()`
   - `async get_positions()` — Return `ib.positions()` as standardized dicts
   - `async get_account_info()` — Return `ib.accountValues()` as structured dict (balance, buying_power, etc.)
   - `async get_portfolio_value()` — Return total portfolio value
   - `async subscribe_market_data(symbol, callback)` — Real-time ticks via `ib.reqMktData()`
   - `async get_historical_data(symbol, duration, bar_size)` — Via `ib.reqHistoricalData()`

3. **Risk Limits (from original comments):**
   - max_position_size: $1,000
   - daily_loss_limit: 2%
   - max_daily_trades: 10
   - max_concurrent_positions: 5
   - stop_loss_mandatory: True
   - ai_confidence_threshold: 0.9

4. **Multi-asset support:**
   - `Stock(symbol, 'SMART', 'USD')`
   - `Option(symbol, expiry, strike, right, 'SMART', 'USD')`
   - `Future(symbol, exchange)`
   - `Forex(pair)`

5. **Connection management:**
   - Auto-reconnect with exponential backoff (5s, 10s, 20s, 40s, max 60s)
   - Heartbeat monitoring every 30s
   - Event callbacks for connection/disconnection/errors

**Step 3:** After writing, move `interactive_brokers.py` to `.archive/` since `ibkr_adapter.py` is now the single source.

**Step 4:** Verify:
```bash
python -m py_compile core_trading/adapters/ibkr_adapter.py
python -c "from core_trading.adapters.ibkr_adapter import IBKRAdapter; print('Import OK')"
```

### Task 1.4: Implement Order State Machine [CRITICAL]
**File:** `services/trading-engine/src/engines/execution_engine.py`
**Current:** 1,202 lines, 80% commented out, enums broken (`class OrderType(Enum):""`)
**Impact:** Orders get lost without a state machine.

**Approach:** COMPLETE REWRITE (1,200 lines of mostly broken code).

**Step 1:** Read the entire file to extract intended design from comments.

**Step 2:** Write clean file with:

1. **Clean Enums** (fix the `class X(Enum):""` syntax):
```python
class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"

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
```

2. **Order dataclass:**
```python
@dataclass
class Order:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    symbol: str = ""
    side: OrderSide = OrderSide.BUY
    order_type: OrderType = OrderType.MARKET
    quantity: float = 0.0
    filled_quantity: float = 0.0
    price: Optional[float] = None
    stop_price: Optional[float] = None
    status: OrderStatus = OrderStatus.PENDING
    strategy_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    broker_order_id: Optional[str] = None
    avg_fill_price: Optional[float] = None
    commission: float = 0.0
    error_message: Optional[str] = None
```

3. **OrderStateMachine** class:
   - Valid transitions map:
     ```
     PENDING -> SUBMITTED, CANCELLED
     SUBMITTED -> PARTIALLY_FILLED, FILLED, CANCELLED, REJECTED, EXPIRED
     PARTIALLY_FILLED -> PARTIALLY_FILLED, FILLED, CANCELLED
     FILLED -> (terminal)
     CANCELLED -> (terminal)
     REJECTED -> (terminal)
     EXPIRED -> (terminal)
     ```
   - `transition(order, new_status)` — validates transition, raises on invalid
   - Emits Event on every state change

4. **ExecutionEngine class:**
   - `__init__(broker_adapter, event_bus, risk_engine)` — inject dependencies
   - `async submit_order(order)` — validate via risk engine, submit to broker, track in state machine
   - `async cancel_order(order_id)` — cancel via broker, update state
   - `async handle_fill(order_id, fill_quantity, fill_price)` — process partial/full fills
   - `async reconcile_positions()` — sync positions with broker
   - `get_active_orders()` — return non-terminal orders
   - `get_order(order_id)` — return order by ID

5. **NO random fills.** All fills come from broker adapter callbacks.

**Step 3:** Verify: `python -m py_compile services/trading-engine/src/engines/execution_engine.py`

### Task 1.5: Add Reconnection Logic [IMPORTANT]
**File:** Part of `ibkr_adapter.py` (Task 1.3) and a shared utility.

Create `core_trading/adapters/reconnection.py`:
```python
class ReconnectionManager:
    """Exponential backoff reconnection with jitter."""
    def __init__(self, initial_delay=1.0, max_delay=60.0, max_attempts=None, jitter=True):
        ...

    async def execute_with_retry(self, connect_fn) -> bool:
        """Try connect_fn with exponential backoff."""
        attempt = 0
        while self.max_attempts is None or attempt < self.max_attempts:
            try:
                result = await connect_fn()
                if result:
                    return True
            except Exception as e:
                delay = min(self.initial_delay * (2 ** attempt), self.max_delay)
                if self.jitter:
                    delay *= (0.5 + random.random())
                logger.warning("reconnect_attempt", attempt=attempt, delay=delay, error=str(e))
                await asyncio.sleep(delay)
                attempt += 1
        return False
```

**Verify:** `python -m py_compile core_trading/adapters/reconnection.py`

---

## PHASE 2: Make It Safe (Risk and Reliability)

### Task 2.1: Wire Risk Engine to Real Data
**File:** `services/risk-manager/src/engines/risk_engine.py`
**Current:** Uses hardcoded values (position=0.0, price=100.0, equity=1,000,000.0)

**Changes:**
1. Add dependency injection for data sources:
```python
class RiskEngine:
    def __init__(self, broker_adapter: BaseBrokerAdapter, event_bus: EventBus, config: RiskConfig):
        self._broker = broker_adapter
        self._event_bus = event_bus
        ...
```

2. Replace ALL hardcoded data methods:
   - `_get_current_position(symbol)` -> `self._broker.get_positions()` then filter
   - `_get_current_price(symbol)` -> `self._broker.get_quote(symbol)`
   - `_get_historical_returns(symbol)` -> fetch from ClickHouse or broker historical data
   - `_get_total_equity()` -> `self._broker.get_account_info()` -> net_liquidation

3. Ensure VaR calculations still work (they're already production-grade math).

### Task 2.2: Implement Kill Switch
**File:** Create `services/risk-manager/src/engines/kill_switch.py`

```python
class KillSwitch:
    """Emergency stop for all trading activity."""

    def __init__(self, broker_adapter, event_bus):
        self._broker = broker_adapter
        self._event_bus = event_bus
        self._activated = False
        self._reason = None

    async def activate(self, reason: str):
        """Activate kill switch: cancel all orders, close all positions."""
        self._activated = True
        self._reason = reason

        # 1. Cancel all open orders
        orders = await self._broker.get_open_orders()
        for order in orders:
            await self._broker.cancel_order(order.id)

        # 2. Close all positions (market sell/buy)
        positions = await self._broker.get_positions()
        for pos in positions:
            closing_order = Order(
                symbol=pos.symbol,
                side=OrderSide.SELL if pos.quantity > 0 else OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=abs(pos.quantity)
            )
            await self._broker.place_order(closing_order)

        # 3. Publish emergency event
        await self._event_bus.publish(Event(
            type=EventType.RISK_ALERT,
            data={"action": "kill_switch", "reason": reason},
            priority=EventPriority.CRITICAL
        ))

    async def deactivate(self):
        """Deactivate kill switch (requires manual confirmation)."""
        self._activated = False
        self._reason = None

    @property
    def is_active(self) -> bool:
        return self._activated
```

### Task 2.3: Implement Pre-Trade Risk Checks
**File:** Part of risk_engine.py

Add method:
```python
async def pre_trade_check(self, order: Order) -> RiskCheckResult:
    """Block orders that violate risk limits."""
    checks = [
        self._check_position_limit(order),
        self._check_concentration_limit(order),
        self._check_daily_loss_limit(),
        self._check_daily_trade_limit(),
        self._check_margin_requirement(order),
        self._check_order_size_limit(order),
    ]
    failures = [c for c in checks if not c.passed]
    if failures:
        return RiskCheckResult.REJECTED, failures
    return RiskCheckResult.APPROVED, []
```

### Task 2.4: Implement Order Persistence
**File:** Create `services/trading-engine/src/persistence/order_store.py`

Use the production-ready PostgreSQL client (`libs/database/postgres/client.py`).

```python
class OrderStore:
    """Persist orders to PostgreSQL for crash recovery."""

    async def save_order(self, order: Order) -> bool:
        """Insert or update order in database."""

    async def get_order(self, order_id: str) -> Optional[Order]:
        """Retrieve order by ID."""

    async def get_active_orders(self) -> List[Order]:
        """Get all non-terminal orders."""

    async def reconcile_on_startup(self, broker_adapter) -> List[Order]:
        """Compare DB orders with broker state on startup, resolve discrepancies."""
```

**SQL Schema** (add to `infrastructure/postgres/init/`):
```sql
CREATE TABLE IF NOT EXISTS orders (
    id VARCHAR(64) PRIMARY KEY,
    symbol VARCHAR(32) NOT NULL,
    side VARCHAR(8) NOT NULL,
    order_type VARCHAR(16) NOT NULL,
    quantity DECIMAL(20,8) NOT NULL,
    filled_quantity DECIMAL(20,8) DEFAULT 0,
    price DECIMAL(20,8),
    stop_price DECIMAL(20,8),
    status VARCHAR(24) NOT NULL DEFAULT 'pending',
    strategy_id VARCHAR(64),
    broker_order_id VARCHAR(64),
    avg_fill_price DECIMAL(20,8),
    commission DECIMAL(20,8) DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_orders_symbol ON orders(symbol);
CREATE INDEX idx_orders_created ON orders(created_at);
```

### Task 2.5: Add Position Reconciliation on Startup
**File:** Part of `execution_engine.py` startup sequence.

```python
async def reconcile_on_startup(self):
    """Sync local state with broker on startup."""
    # 1. Load persisted orders from DB
    db_orders = await self.order_store.get_active_orders()

    # 2. Get broker positions
    broker_positions = await self.broker_adapter.get_positions()

    # 3. Compare and resolve discrepancies
    # 4. Update local state
    # 5. Emit reconciliation complete event
```

---

## PHASE 3: Make It Smart (Data and Strategies)

### Task 3.1: Implement IBKR Real-Time Market Data
**File:** Create `core_trading/data_feeds/ibkr_data_feed.py`

Uses the `ibkr_adapter.py` connection to subscribe to real-time market data:
```python
class IBKRDataFeed:
    """Real-time market data via IBKR TWS/Gateway."""

    async def subscribe_ticker(self, symbol: str, callback) -> str:
        """Subscribe to real-time ticker updates. Returns subscription ID."""
        contract = self._create_contract(symbol)
        ticker = self._ib.reqMktData(contract, '', False, False)
        ticker.updateEvent += callback
        return ticker

    async def subscribe_level2(self, symbol: str, callback) -> str:
        """Subscribe to Level 2 order book data."""

    async def get_historical_bars(self, symbol: str, duration: str, bar_size: str) -> pd.DataFrame:
        """Get historical OHLCV data via ib.reqHistoricalData()."""

    async def unsubscribe(self, subscription_id: str):
        """Cancel market data subscription."""

    def _create_contract(self, symbol: str) -> Contract:
        """Create IBKR contract from symbol string."""
```

### Task 3.2: Wire ClickHouse for Time-Series Storage
**File:** Create `core_trading/data_feeds/timeseries_store.py`

```python
class TimeSeriesStore:
    """Store and retrieve market data from ClickHouse."""

    async def store_bars(self, symbol: str, bars: List[Dict]):
        """Store OHLCV bars in ClickHouse."""

    async def get_bars(self, symbol: str, start: datetime, end: datetime, timeframe: str) -> pd.DataFrame:
        """Query historical bars."""

    async def store_tick(self, symbol: str, tick: Dict):
        """Store tick data."""
```

**ClickHouse table** (add to init scripts):
```sql
CREATE TABLE IF NOT EXISTS market_data.bars (
    symbol String,
    timestamp DateTime64(3),
    open Float64,
    high Float64,
    low Float64,
    close Float64,
    volume Float64,
    timeframe String
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(timestamp)
ORDER BY (symbol, timestamp);
```

### Task 3.3: Enable Redis Caching for Market Data
**File:** Create `core_trading/data_feeds/cache.py`

```python
class MarketDataCache:
    """Redis-backed cache for market data."""

    async def get_quote(self, symbol: str) -> Optional[Dict]:
        """Get cached quote if fresh (< 5 seconds old)."""

    async def set_quote(self, symbol: str, data: Dict, ttl: float = 5.0):
        """Cache quote with TTL."""

    async def get_bars(self, symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
        """Get cached bars."""

    async def set_bars(self, symbol: str, timeframe: str, data: pd.DataFrame, ttl: float = 60.0):
        """Cache bars with TTL."""
```

### Task 3.4: Build Data Normalization Layer
**File:** Create `core_trading/data_feeds/normalizer.py`

```python
class DataNormalizer:
    """Normalize data from different sources into standard format."""

    def normalize_quote(self, source: str, raw_data: Dict) -> StandardizedQuote:
        """Normalize quote from any source to standard format."""

    def normalize_bar(self, source: str, raw_data: Dict) -> StandardizedBar:
        """Normalize OHLCV bar from any source to standard format."""

    def normalize_tick(self, source: str, raw_data: Dict) -> StandardizedTick:
        """Normalize tick data from any source to standard format."""

@dataclass
class StandardizedQuote:
    symbol: str
    bid: float
    ask: float
    last: float
    bid_size: float
    ask_size: float
    volume: float
    timestamp: datetime
    source: str
```

### Task 3.5: Implement Rate Limiting Enforcement
**File:** `core_trading/adapters/brokers/rate_limiting.py` already has the implementation (token bucket, sliding window). Wire it up.

Add to each data feed adapter:
```python
from core_trading.adapters.brokers.rate_limiting import TokenBucketRateLimiter

class IBKRDataFeed:
    def __init__(self, ...):
        self._rate_limiter = TokenBucketRateLimiter(
            max_requests=45,  # IBKR limit
            time_window=1.0
        )

    async def _throttle(self):
        while not self._rate_limiter.allow():
            await asyncio.sleep(0.01)
```

---

## PHASE 4: Fix Strategy Handlers

### Task 4.1: Audit each strategy directory
For each strategy in `core_trading/strategies/`:
1. Read the main strategy file
2. If it delegates to empty handlers that were deleted in Phase 0, implement the actual logic inline
3. If the strategy has real logic (arbitrage, ML, backtesting), leave it alone

### Task 4.2: Implement Momentum Strategy Logic
**File:** `core_trading/strategies/momentum/` strategies

Each momentum strategy (MACD, RSI, Supertrend, etc.) should:
1. Calculate the relevant indicator
2. Generate BUY/SELL signals
3. Emit events via EventBus
4. Not delegate to external handlers

### Task 4.3: Implement Mean Reversion Strategy Logic
**File:** `core_trading/strategies/mean_reversion/` strategies

Same pattern as momentum - inline the actual indicator calculations and signal generation.

---

## PHASE 5: Testing and CI/CD

### Task 5.1: Create Test Infrastructure
**File:** `tests/conftest.py`

```python
import pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.fixture
def mock_broker_adapter():
    adapter = AsyncMock()
    adapter.connect.return_value = True
    adapter.disconnect.return_value = True
    adapter.get_positions.return_value = []
    adapter.get_account_info.return_value = {
        "balance": 100000.0,
        "buying_power": 200000.0,
        "net_liquidation": 100000.0
    }
    return adapter

@pytest.fixture
def event_bus():
    from services.trading_engine.src.core.event_system import EventBus
    return EventBus()

@pytest.fixture
def mock_order():
    from services.trading_engine.src.engines.execution_engine import Order, OrderSide, OrderType
    return Order(
        symbol="AAPL",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=100,
        price=150.0
    )
```

### Task 5.2: Write Unit Tests for Event Bus
**File:** `tests/unit/test_event_system.py`

Test cases:
- `test_publish_delivers_to_subscribers`
- `test_subscribe_multiple_callbacks`
- `test_unsubscribe_removes_callback`
- `test_priority_ordering`
- `test_global_subscriber_receives_all_events`
- `test_event_history`

### Task 5.3: Write Unit Tests for Circuit Breaker
**File:** `tests/unit/test_circuit_breaker.py`

Test cases:
- `test_initial_state_is_closed`
- `test_opens_after_threshold_failures`
- `test_half_open_after_recovery_timeout`
- `test_closes_after_success_threshold`
- `test_sliding_window_cleans_old_failures`

### Task 5.4: Write Unit Tests for IBKR Adapter
**File:** `tests/unit/test_ibkr_adapter.py`

Test cases (mock `ib_insync`):
- `test_connect_success`
- `test_connect_failure_retries`
- `test_place_market_order`
- `test_place_limit_order`
- `test_cancel_order`
- `test_get_positions`
- `test_get_account_info`
- `test_risk_limit_enforcement`

### Task 5.5: Write Unit Tests for Order State Machine
**File:** `tests/unit/test_order_state_machine.py`

Test cases:
- `test_valid_transitions`
- `test_invalid_transition_raises`
- `test_terminal_states`
- `test_partial_fill`

### Task 5.6: Write Unit Tests for Risk Engine
**File:** `tests/unit/test_risk_engine.py`

Test cases:
- `test_pre_trade_check_approves_valid_order`
- `test_pre_trade_check_rejects_over_position_limit`
- `test_pre_trade_check_rejects_over_daily_loss`
- `test_var_calculation`
- `test_kill_switch_cancels_all_orders`

### Task 5.7: Write Integration Tests
**File:** `tests/integration/test_order_lifecycle.py`

Test the full flow:
1. Strategy generates signal -> event bus
2. Risk engine validates -> approve
3. Execution engine submits to broker (mock)
4. Fill received -> state machine updates
5. Position updated in DB

### Task 5.8: Update CI/CD Pipeline
**File:** `.github/workflows/ci.yml`

Add:
```yaml
- name: Run tests
  run: pytest tests/ -v --cov --cov-report=xml

- name: Security scan
  run: bandit -r core_trading/ services/ libs/

- name: Type check
  run: mypy core_trading/ services/ --ignore-missing-imports

- name: Lint
  run: ruff check core_trading/ services/ libs/
```

---

## PHASE 6: AI Assistant Service

### Task 6.1: Rewrite AI Assistant
**File:** `services/ai-assistant/src/main.py`
**Current:** 22-line placeholder with infinite sleep loop

Implement:
```python
class AIAssistantService:
    """AI-powered trading assistant using LangGraph and vector store."""

    def __init__(self):
        self.event_bus = get_event_bus()
        self.vector_store = QdrantClient(...)  # Use libs/database/qdrant/client.py
        self.llm = ChatOpenAI(...)

    async def analyze_signal(self, signal: Dict) -> Dict:
        """AI analysis of trading signal."""

    async def assess_risk(self, context: Dict) -> Dict:
        """AI risk assessment."""

    async def answer_query(self, query: str) -> str:
        """Natural language trading queries."""
```

---

## EXECUTION ORDER SUMMARY

```
Phase 0 (Cleanup) - Day 1
  0.1 Delete handler stubs (249 files)
  0.2 Delete core_trading/brokers/ skeleton directory
  0.3 Rewrite core_trading/adapters/base.py
  0.4 Consolidate adapter structure

Phase 1 (Make It Run) - Days 2-5
  1.1 Implement EventBus                    [blocks everything]
  1.2 Implement Circuit Breakers
  1.3 Rewrite IBKR Adapter                  [blocks everything]
  1.4 Rewrite Execution Engine              [depends on 1.1, 1.3]
  1.5 Add Reconnection Logic                [depends on 1.3]

Phase 2 (Make It Safe) - Days 6-9
  2.1 Wire Risk Engine to real data         [depends on 1.3]
  2.2 Implement Kill Switch                 [depends on 1.1, 1.3]
  2.3 Implement Pre-Trade Risk Checks       [depends on 2.1]
  2.4 Implement Order Persistence           [depends on 1.4]
  2.5 Position Reconciliation               [depends on 1.3, 2.4]

Phase 3 (Make It Smart) - Days 10-13
  3.1 IBKR Real-Time Market Data            [depends on 1.3]
  3.2 ClickHouse Time-Series Store
  3.3 Redis Market Data Cache
  3.4 Data Normalization Layer
  3.5 Rate Limiting Enforcement

Phase 4 (Fix Strategies) - Days 14-16
  4.1 Audit strategy directories
  4.2 Implement Momentum strategies
  4.3 Implement Mean Reversion strategies

Phase 5 (Testing) - Days 17-20
  5.1-5.7 Write tests (parallel)
  5.8 Update CI/CD

Phase 6 (AI Service) - Days 21-22
  6.1 Rewrite AI Assistant
```

---

## KEY PRINCIPLES FOR CLAUDE CODE

1. **Always COMPLETE REWRITE damaged files** - never try to uncomment. Follow CLAUDE.md Code Restoration Pattern.
2. **Preserve the logic, discard the formatting** - read comments to understand intent, write clean Python.
3. **Use production-ready libs** - `libs/database/`, `libs/messaging/`, `libs/common/` are all good. Import and use them.
4. **Follow existing patterns** - look at `libs/messaging/producers/kafka_producer.py` or `libs/common/logging/logger.py` for code quality standards.
5. **Verify after every file** - run `python -m py_compile <file>` after each rewrite.
6. **No random fills** - all execution must go through real broker adapter.
7. **No hardcoded data** - risk engine gets real data from broker.
8. **Test everything** - write tests alongside implementation, not after.

---

## FILES TO CREATE (NEW)

| File | Purpose |
|------|---------|
| `core_trading/adapters/reconnection.py` | Exponential backoff reconnection |
| `core_trading/data_feeds/ibkr_data_feed.py` | Real-time market data via IBKR |
| `core_trading/data_feeds/timeseries_store.py` | ClickHouse time-series storage |
| `core_trading/data_feeds/cache.py` | Redis market data cache |
| `core_trading/data_feeds/normalizer.py` | Cross-source data normalization |
| `services/risk-manager/src/engines/kill_switch.py` | Emergency kill switch |
| `services/trading-engine/src/persistence/order_store.py` | PostgreSQL order persistence |
| `tests/conftest.py` | Test fixtures |
| `tests/unit/test_event_system.py` | Event bus tests |
| `tests/unit/test_circuit_breaker.py` | Circuit breaker tests |
| `tests/unit/test_ibkr_adapter.py` | IBKR adapter tests |
| `tests/unit/test_order_state_machine.py` | Order state machine tests |
| `tests/unit/test_risk_engine.py` | Risk engine tests |
| `tests/integration/test_order_lifecycle.py` | End-to-end order flow test |

## FILES TO REWRITE (COMPLETE)

| File | Reason | Lines |
|------|--------|-------|
| `core_trading/adapters/base.py` | 100% commented out | 487 |
| `core_trading/adapters/ibkr_adapter.py` | 99% commented out | ~300 |
| `services/trading-engine/src/core/event_system.py` | 100% stub | 35 |
| `services/trading-engine/src/core/fault_tolerance.py` | 100% stub | 21 |
| `services/trading-engine/src/engines/execution_engine.py` | 80% broken | 1,201 |
| `services/risk-manager/src/engines/risk_engine.py` | Hardcoded data | ~800 |
| `services/ai-assistant/src/main.py` | 22-line placeholder | 22 |

## DIRECTORIES TO DELETE

| Directory | Files | Reason |
|-----------|-------|--------|
| `core_trading/brokers/` (entire) | ~58 | Empty skeletons |
| All `*_handlers/` directories | ~249 | Empty stubs |

## FILES TO LEAVE ALONE (Production-Ready)

- Everything in `libs/` (database, messaging, common, fundamental)
- `core_trading/strategies/arbitrage/`
- `core_trading/strategies/machine_learning/`
- `core_trading/strategies/backtesting/backtest_engine.py`
- `core_trading/strategies/execution/position_sizing.py`
- `docker-compose.yml` and all `infrastructure/`
- `.pre-commit-config.yaml`
