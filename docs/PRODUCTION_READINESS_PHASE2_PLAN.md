# IBKR Algo Trader - Phase 2: 100% Production Readiness Plan

**Date:** April 7, 2026
**Based on:** Comprehensive verification of all Phase 0-6 deliverables
**Current State:** ~85% production ready, 76% test coverage, 256 tests passing
**Target:** 100% production ready, 92%+ test coverage

---

## Current Baseline

| Metric | Value |
|--------|-------|
| Python files | 284 |
| Production code | 112,736 lines |
| Test code | 6,117 lines |
| Tests | 256 passing, 0 failures |
| Line coverage | 76% |
| Strategy files | 135 (13 categories) |
| Data feed files | 14 |
| Adapter files | 20 |

### Coverage Gaps (Modules Below 70%)

| Module | Current | Missing Lines |
|--------|---------|---------------|
| `libs/messaging/producers/kafka_producer.py` | 5% | 42 |
| `libs/common/errors/handlers.py` | 15% | 35 |
| `libs/common/monitoring/metrics.py` | 26% | 43 |
| `libs/common/logging/logger.py` | 31% | 34 |
| `libs/database/qdrant/client.py` | 31% | 34 |
| `core_trading/adapters/ibkr_adapter.py` | 47% | 171 |
| `libs/common/monitoring/health.py` | 48% | 23 |
| `libs/database/postgres/client.py` | 58% | 22 |
| `services/risk-manager/src/engines/risk_engine.py` | 58% | 303 |
| `services/trading-engine/src/engines/execution_engine.py` | 61% | 163 |
| `libs/database/clickhouse/client.py` | 65% | 18 |
| `libs/common/events/serializers.py` | 71% | 5 |
| `core_trading/adapters/base.py` | 70% | 46 |

### Untested Code (0% coverage, no dedicated test files)

- **135 strategy files** across 13 categories (momentum, mean reversion, arbitrage, ML, backtesting, scalping, pair trading, volatility breakout, volume weighted, advanced technical, multi-factor, regime-based, seasonal)
- **14 data feed files** (ibkr_data_feed, timeseries_store, cache, normalizer, rate_limiting)
- **Reconnection manager** (`core_trading/adapters/reconnection.py`)
- **Order persistence** (`services/trading-engine/src/persistence/order_store.py`)
- **Smart money engine** and **enhanced smart money engine**
- **Position sizing, fundamental analysis, quant library**

---

## PHASE 7: Test Coverage Push (76% -> 92%+)

**Goal:** Bring all core infrastructure modules to 90%+ coverage.

### Task 7.1: Expand Kafka Producer Tests
**File:** `tests/unit/test_libraries.py` (extend) or create `tests/unit/test_kafka_producer.py`
**Target:** `libs/messaging/producers/kafka_producer.py` (5% -> 90%+)

Test cases:
- `test_producer_initialization_with_config`
- `test_producer_connect_success`
- `test_producer_connect_failure_raises`
- `test_produce_message_success`
- `test_produce_message_with_key`
- `test_produce_message_with_headers`
- `test_produce_message_serialization`
- `test_produce_message_delivery_report_success`
- `test_produce_message_delivery_report_failure`
- `test_producer_flush`
- `test_producer_close`
- `test_producer_retry_on_broker_error`
- `test_producer_compression_config`

### Task 7.2: Test Error Handlers
**File:** Create `tests/unit/test_error_handlers.py`
**Target:** `libs/common/errors/handlers.py` (15% -> 90%+)

Test cases:
- `test_global_error_handler_sync_function`
- `test_global_error_handler_async_function`
- `test_error_handler_logs_exception`
- `test_error_handler_returns_error_response`
- `test_error_handler_retry_on_transient_error`
- `test_error_handler_no_retry_on_permanent_error`
- `test_circuit_breaker_error_integration`
- `test_error_handler_custom_fallback`

### Task 7.3: Test Monitoring Metrics
**File:** Create `tests/unit/test_monitoring_metrics.py`
**Target:** `libs/common/monitoring/metrics.py` (26% -> 90%+)

Test cases:
- `test_metrics_collector_initialization`
- `test_record_counter`
- `test_record_gauge`
- `test_record_histogram`
- `test_get_all_metrics`
- `test_metrics_reset`
- `test_prometheus_format_export`
- `test_metrics_labels_and_tags`
- `test_timer_context_manager`
- `test_metrics_aggregation`

### Task 7.4: Test Logger Module
**File:** Create `tests/unit/test_logger.py`
**Target:** `libs/common/logging/logger.py` (31% -> 90%+)

Test cases:
- `test_logger_initialization`
- `test_structured_logging_json_output`
- `test_logger_with_context`
- `test_logger_log_levels`
- `test_logger_correlation_id`
- `test_logger_bind_extra_fields`
- `test_logger_file_handler_rotation`
- `test_logger_exception_logging`

### Task 7.5: Test Qdrant Client
**File:** Extend `tests/unit/test_database.py`
**Target:** `libs/database/qdrant/client.py` (31% -> 90%+)

Test cases:
- `test_qdrant_connect`
- `test_qdrant_create_collection`
- `test_qdrant_upsert_vectors`
- `test_qdrant_search_similar`
- `test_qdrant_delete_vectors`
- `test_qdrant_get_by_id`
- `test_qdrant_health_check`
- `test_qdrant_batch_operations`
- `test_qdrant_connection_failure_fallback`
- `test_qdrant_filter_search`

### Task 7.6: Test IBKR Adapter (Deep Coverage)
**File:** Extend `tests/unit/test_ibkr_adapter.py`
**Target:** `core_trading/adapters/ibkr_adapter.py` (47% -> 90%+)

Test cases:
- `test_connect_with_retry_backoff`
- `test_connect_failure_all_retries_exhausted`
- `test_disconnect_cleanup`
- `test_place_market_order_equity`
- `test_place_limit_order_equity`
- `test_place_stop_order`
- `test_place_option_order`
- `test_place_future_order`
- `test_place_forex_order`
- `test_cancel_order_success`
- `test_cancel_order_not_found`
- `test_get_order_status_pending`
- `test_get_order_status_filled`
- `test_get_positions_multiple`
- `test_get_positions_empty`
- `test_get_account_info`
- `test_get_portfolio_value`
- `test_subscribe_market_data`
- `test_get_historical_data_daily`
- `test_get_historical_data_hourly`
- `test_risk_limit_max_position_size`
- `test_risk_limit_daily_loss_limit`
- `test_risk_limit_max_daily_trades`
- `test_risk_limit_max_concurrent_positions`
- `test_risk_limit_ai_confidence_threshold`
- `test_reconnect_on_disconnect`
- `test_heartbeat_monitoring`
- `test_multi_asset_contract_creation`

### Task 7.7: Test Monitoring Health
**File:** Create `tests/unit/test_monitoring_health.py`
**Target:** `libs/common/monitoring/health.py` (48% -> 90%+)

Test cases:
- `test_health_check_register_component`
- `test_health_check_all_healthy`
- `test_health_check_component_down`
- `test_health_check_timeout`
- `test_health_status_response_format`
- `test_health_check_liveness`
- `test_health_check_readiness`

### Task 7.8: Test PostgreSQL Client
**File:** Extend `tests/unit/test_database.py`
**Target:** `libs/database/postgres/client.py` (58% -> 90%+)

Test cases:
- `test_postgres_connect`
- `test_postgres_execute_query`
- `test_postgres_execute_with_params`
- `test_postgres_insert_and_fetch`
- `test_postgres_transaction_commit`
- `test_postgres_transaction_rollback`
- `test_postgres_connection_pool`
- `test_postgres_health_check`
- `test_postgres_query_timeout`

### Task 7.9: Test Risk Engine (Deep Coverage)
**File:** Extend `tests/unit/test_risk_engine.py`
**Target:** `services/risk-manager/src/engines/risk_engine.py` (58% -> 90%+)

Test cases:
- `test_pre_trade_check_approves_valid_order`
- `test_pre_trade_check_rejects_over_position_limit`
- `test_pre_trade_check_rejects_over_concentration`
- `test_pre_trade_check_rejects_daily_loss_limit`
- `test_pre_trade_check_rejects_daily_trade_limit`
- `test_pre_trade_check_rejects_margin_insufficient`
- `test_pre_trade_check_rejects_order_size_limit`
- `test_var_historical_calculation`
- `test_var_parametric_calculation`
- `test_var_monte_carlo_calculation`
- `test_var_cornish_fisher_calculation`
- `test_portfolio_risk_aggregation`
- `test_correlation_matrix_calculation`
- `test_marginal_var_calculation`
- `test_diversification_ratio`
- `test_concentration_index`
- `test_risk_check_result_enum`
- `test_risk_metric_types`
- `test_risk_engine_with_real_broker_data`
- `test_risk_engine_handles_missing_data`
- `test_risk_engine_handles_zero_equity`
- `test_risk_engine_warns_high_portfolio_risk`

### Task 7.10: Test Execution Engine (Deep Coverage)
**File:** Extend `tests/unit/test_order_state_machine.py` or create `tests/unit/test_execution_engine.py`
**Target:** `services/trading-engine/src/engines/execution_engine.py` (61% -> 90%+)

Test cases:
- `test_submit_order_success`
- `test_submit_order_risk_rejected`
- `test_submit_order_circuit_breaker_open`
- `test_cancel_order_success`
- `test_cancel_order_not_found`
- `test_handle_partial_fill`
- `test_handle_full_fill`
- `test_handle_fill_updates_position`
- `test_reconcile_positions_on_startup`
- `test_get_active_orders`
- `test_get_order_by_id`
- `test_order_state_transitions_all_valid`
- `test_order_state_transition_invalid_raises`
- `test_terminal_state_immutable`
- `test_execution_engine_emits_event_on_fill`
- `test_execution_engine_emits_event_on_cancel`
- `test_execution_engine_emits_event_on_reject`
- `test_execution_engine_concurrent_orders`
- `test_execution_engine_order_not_found_raises`

### Task 7.11: Test ClickHouse Client
**File:** Extend `tests/unit/test_database.py`
**Target:** `libs/database/clickhouse/client.py` (65% -> 90%+)

Test cases:
- `test_clickhouse_connect`
- `test_clickhouse_execute_query`
- `test_clickhouse_insert_batch`
- `test_clickhouse_health_check`
- `test_clickhouse_query_timeout`
- `test_clickhouse_connection_failure`

### Task 7.12: Test Remaining Coverage Gaps
**Target:** Bring all remaining modules above 90%

| File | Current | Tests Needed |
|------|---------|--------------|
| `core_trading/adapters/base.py` | 70% | Abstract method enforcement, connection_context, metrics |
| `libs/common/events/serializers.py` | 71% | Serialize/deserialize event payloads |
| `libs/database/redis/client.py` | 82% | Pub/sub, TTL, batch operations |
| `services/risk-manager/src/engines/kill_switch.py` | 86% | Activate/deactivate edge cases, concurrent activation |
| `services/ai-assistant/src/main.py` | 64% | Deep coverage of LLM, embeddings, knowledge store, event handlers |
| `tests/conftest.py` | 92% | Fixture coverage |

### Task 7.13: Test Data Feed Modules
**File:** Create `tests/unit/test_data_feeds.py`

Test cases:
- `test_ibkr_data_feed_subscribe_ticker`
- `test_ibkr_data_feed_subscribe_level2`
- `test_ibkr_data_feed_get_historical_bars`
- `test_ibkr_data_feed_unsubscribe`
- `test_ibkr_data_feed_rate_limiting`
- `test_ibkr_data_feed_contract_creation`
- `test_timeseries_store_store_bars`
- `test_timeseries_store_get_bars`
- `test_timeseries_store_store_tick`
- `test_timeseries_store_graceful_fallback`
- `test_market_data_cache_get_quote`
- `test_market_data_cache_set_quote_ttl`
- `test_market_data_cache_in_memory_fallback`
- `test_data_normalizer_ibkr_quote`
- `test_data_normalizer_generic_quote`
- `test_data_normalizer_batch`

### Task 7.14: Test Reconnection Manager
**File:** Create `tests/unit/test_reconnection.py`

Test cases:
- `test_retry_succeeds_first_attempt`
- `test_retry_succeeds_after_failures`
- `test_retry_exponential_backoff_delays`
- `test_retry_max_attempts_exhausted`
- `test_retry_jitter_applied`
- `test_retry_custom_config`
- `test_retry_cancelled`

### Task 7.15: Test Order Store (Persistence)
**File:** Create `tests/unit/test_order_store.py`

Test cases:
- `test_save_order_new`
- `test_save_order_update_existing`
- `test_get_order_by_id`
- `test_get_active_orders`
- `test_get_active_orders_excludes_terminal`
- `test_update_order_status`
- `test_update_order_fill`
- `test_reconcile_on_startup_match`
- `test_reconcile_on_startup_discrepancy`
- `test_reconcile_on_startup_orphaned_db_order`

### Task 7.16: Verify Phase 7 Coverage Target
**Validation:**
```bash
pytest tests/ --cov --cov-report=term-missing --cov-fail-under=92
```

**Expected result:** 92%+ overall coverage, no module below 85%.

---

## PHASE 8: Advanced Features

**Goal:** Implement the high-value institutional features from the audit.

### Task 8.1: Smart Order Router (SOR)
**File:** Create `core_trading/execution/smart_order_router.py`

Implementation:
```python
class SmartOrderRouter:
    """Route orders to optimal venue based on fill probability, latency, and cost."""

    def __init__(self, venues: List[VenueConfig], event_bus: EventBus):
        self._venues = venues
        self._event_bus = event_bus
        self._venue_stats: Dict[str, VenueStats] = {}

    async def route_order(self, order: Order) -> RoutingDecision:
        """Select best venue for order execution."""
        candidates = await self._evaluate_venues(order)
        best = self._select_optimal(candidates)
        return RoutingDecision(
            venue=best.venue,
            estimated_fill_rate=best.fill_probability,
            estimated_cost=best.total_cost,
            estimated_latency_ms=best.avg_latency_ms,
            reason=best.selection_reason
        )

    async def _evaluate_venues(self, order: Order) -> List[VenueScore]:
        """Score each venue for this order."""
        # Factors: fill probability, latency, commission, spread, market impact

    def update_venue_stats(self, venue: str, fill_result: FillResult):
        """Track venue performance for future routing decisions."""
```

**Test file:** `tests/unit/test_smart_order_router.py`

### Task 8.2: TWAP/VWAP Execution Algorithms
**File:** Create `core_trading/execution/algo_orders.py`

Implementation:
```python
class TWAPExecutor:
    """Time-Weighted Average Price execution."""

    def __init__(self, execution_engine, event_bus):
        self._engine = execution_engine
        self._event_bus = event_bus

    async def execute_twap(self, order: Order, duration_minutes: int,
                           slices: int = 10) -> AlgoOrderResult:
        """Split order into equal slices over time window."""
        slice_size = order.quantity / slices
        interval = (duration_minutes * 60) / slices
        results = []
        for i in range(slices):
            slice_order = Order(
                symbol=order.symbol,
                side=order.side,
                order_type=OrderType.MARKET,
                quantity=slice_size,
                strategy_id=f"twap_{order.id}"
            )
            result = await self._engine.submit_order(slice_order)
            results.append(result)
            if i < slices - 1:
                await asyncio.sleep(interval)
        return AlgoOrderResult(parent_order=order, slices=results)

class VWAPExecutor:
    """Volume-Weighted Average Price execution."""

    async def execute_vwap(self, order: Order, volume_profile: VolumeProfile,
                           duration_minutes: int) -> AlgoOrderResult:
        """Split order proportional to expected volume profile."""
        # Calculate slice sizes based on volume curve
        # Execute slices at volume-weighted intervals
```

**Test file:** `tests/unit/test_algo_orders.py`

### Task 8.3: Advanced Order Types
**File:** Create `core_trading/execution/advanced_orders.py`

Implementation:
```python
class TrailingStopOrder:
    """Trailing stop order that follows price by a percentage or fixed amount."""

class BracketOrder:
    """Entry + take-profit + stop-loss as a single unit."""

class OCOOrder:
    """One-Cancels-Other: two orders, first fill cancels the other."""

class OTOOrder:
    """One-Triggers-Other: parent fill triggers child order."""

class IcebergOrder:
    """Large order with only a visible portion shown to the market."""
```

**Test file:** `tests/unit/test_advanced_orders.py`

### Task 8.4: Real-Time P&L Tracking with Greeks
**File:** Create `core_trading/analytics/pnl_tracker.py`

Implementation:
```python
class PnLTracker:
    """Real-time mark-to-market P&L tracking with Greeks for options."""

    def __init__(self, broker_adapter, event_bus):
        self._broker = broker_adapter
        self._event_bus = event_bus
        self._positions: Dict[str, PositionPnL] = {}

    async def update_pnl(self):
        """Recalculate P&L for all positions."""
        positions = await self._broker.get_positions()
        for pos in positions:
            market_price = await self._broker.get_quote(pos.symbol)
            self._positions[pos.symbol] = PositionPnL(
                symbol=pos.symbol,
                quantity=pos.quantity,
                avg_cost=pos.avg_cost,
                market_price=market_price.last,
                unrealized_pnl=(market_price.last - pos.avg_cost) * pos.quantity,
                realized_pnl=pos.realized_pnl,
                pnl_pct=((market_price.last - pos.avg_cost) / pos.avg_cost) * 100,
            )

    async def calculate_greeks(self, symbol: str) -> Greeks:
        """Calculate Delta, Gamma, Theta, Vega for options positions."""
        # Use Black-Scholes model for European options
        # Use binomial model for American options

    async def get_portfolio_summary(self) -> PortfolioPnL:
        """Aggregate P&L across all positions."""
```

**Test file:** `tests/unit/test_pnl_tracker.py`

### Task 8.5: Scenario / Stress-Test Engine
**File:** Create `core_trading/analytics/scenario_engine.py`

Implementation:
```python
class ScenarioEngine:
    """What-if analysis with custom stress test scenarios."""

    PREDEFINED_SCENARIOS = {
        "2008_financial_crisis": {"sp500_drop": -0.37, "vol_spike": 3.5, "correlation": 0.95},
        "covid_crash_2020": {"sp500_drop": -0.34, "vol_spike": 4.0, "recovery_days": 23},
        "flash_crash": {"sp500_drop": -0.09, "duration_minutes": 36},
        "interest_rate_shock": {"rate_increase_bps": 200, "bond_impact": -0.10},
        "sector_rotation": {"tech_drop": -0.20, "value_rise": 0.15},
    }

    async def run_scenario(self, scenario_name: str, portfolio: Portfolio) -> StressTestResult:
        """Apply predefined scenario to current portfolio."""

    async def run_custom_scenario(self, shocks: Dict[str, float], portfolio: Portfolio) -> StressTestResult:
        """Apply custom shocks (symbol -> pct_change) to portfolio."""

    async def run_monte_carlo_stress(self, portfolio: Portfolio, n_simulations: int = 10000) -> StressTestResult:
        """Monte Carlo stress test with correlated asset moves."""
```

**Test file:** `tests/unit/test_scenario_engine.py`

### Task 8.6: Compliance Engine
**File:** Create `services/compliance/src/compliance_engine.py`

Implementation:
```python
class ComplianceEngine:
    """Automated compliance checking for trading activities."""

    async def check_pattern_day_trader(self, account_id: str) -> PDTStatus:
        """Check Pattern Day Trader status (4+ day trades in 5 business days)."""

    async def check_wash_sale(self, symbol: str, account_id: str) -> WashSaleResult:
        """Detect wash sale violations (buy same/similar within 30 days of loss)."""

    async def check_reg_t_margin(self, account_id: str) -> MarginStatus:
        """Verify Reg T margin requirements."""

    async def check_position_concentration(self, account_id: str) -> ConcentrationReport:
        """Check if any single position exceeds concentration limits."""

    async def generate_audit_record(self, action: str, details: Dict) -> AuditRecord:
        """Create immutable audit trail entry."""

    async def generate_daily_report(self, account_id: str) -> ComplianceReport:
        """Generate end-of-day compliance report."""
```

**Test file:** `tests/unit/test_compliance_engine.py`

### Task 8.7: Immutable Audit Trail
**File:** Create `services/compliance/src/audit_trail.py`

Implementation:
```python
class AuditTrail:
    """Immutable, append-only log of every trading decision and action."""

    async def record(self, action: str, actor: str, details: Dict[str, Any],
                     metadata: Optional[Dict] = None) -> AuditRecord:
        """Record an immutable audit entry."""
        record = AuditRecord(
            id=uuid.uuid4().hex,
            timestamp=datetime.now(timezone.utc),
            action=action,
            actor=actor,
            details=details,
            metadata=metadata or {},
            checksum=self._compute_checksum(action, details),
            previous_hash=self._get_last_hash()
        )
        await self._store.persist(record)
        return record

    async def verify_integrity(self) -> IntegrityReport:
        """Verify the chain of audit records has not been tampered with."""
        # Walk the hash chain, verify each record's previous_hash

    async def query(self, filters: AuditFilter) -> List[AuditRecord]:
        """Query audit records by time range, action type, actor, symbol."""
```

**Test file:** `tests/unit/test_audit_trail.py`

### Task 8.8: Web Dashboard (API + Frontend)
**File:** Create `services/dashboard/` service

Backend API (`services/dashboard/src/api.py`):
```python
class DashboardAPI:
    """REST API for the trading dashboard."""

    # GET /api/v1/portfolio - Portfolio summary with P&L
    # GET /api/v1/positions - Current positions with unrealized P&L
    # GET /api/v1/orders - Active and recent orders
    # GET /api/v1/strategies - Strategy status and performance
    # GET /api/v1/risk - Risk metrics and alerts
    # GET /api/v1/pnl - P&L over time (daily, weekly, monthly)
    # GET /api/v1/health - System health check
    # POST /api/v1/orders - Submit manual order
    # POST /api/v1/kill-switch - Activate emergency stop
    # GET /api/v1/audit/recent - Recent audit trail entries
    # GET /api/v1/compliance/status - Current compliance status
    # WS /ws/v1/live - WebSocket for real-time updates (positions, P&L, orders)
```

Frontend (`services/dashboard/src/frontend/`):
- Portfolio overview with real-time P&L
- Position table with Greeks (for options)
- Order blotter with status tracking
- Strategy performance charts
- Risk heat map
- Compliance status panel
- Kill switch button (with confirmation)

**Test file:** `tests/unit/test_dashboard_api.py`

### Task 8.9: Notification Service
**File:** Create `services/notifications/src/notification_service.py`

Implementation:
```python
class NotificationService:
    """Multi-channel alerting for critical trading events."""

    async def send_alert(self, alert: Alert):
        """Send alert via configured channels."""
        # Channels: email, SMS (Twilio), webhook (Slack/Discord), push

    # Alert types:
    # - Kill switch activated
    # - Circuit breaker tripped
    # - Daily loss limit approaching
    # - Position size limit reached
    # - Order rejected by risk engine
    # - Broker connection lost
    # - Strategy signal generated
    # - Large fill received
    # - Compliance violation detected
    # - System health degraded
```

**Test file:** `tests/unit/test_notification_service.py`

### Task 8.10: Multi-Account Support
**File:** Create `core_trading/accounts/multi_account_manager.py`

Implementation:
```python
class MultiAccountManager:
    """Trade across multiple IBKR accounts simultaneously."""

    def __init__(self, event_bus: EventBus):
        self._accounts: Dict[str, AccountContext] = {}
        self._event_bus = event_bus

    async def register_account(self, account_id: str, adapter: IBKRAdapter) -> None:
        """Register a trading account with its own adapter."""

    async def submit_order(self, account_id: str, order: Order) -> str:
        """Submit order to specific account."""

    async def broadcast_order(self, order: Order, allocation: Dict[str, float]) -> Dict[str, str]:
        """Submit same order across multiple accounts with quantity allocation."""

    async def get_aggregate_positions(self) -> Dict[str, AggregatePosition]:
        """Get combined positions across all accounts."""

    async def get_aggregate_pnl(self) -> AggregatePnL:
        """Get combined P&L across all accounts."""

    async def health_check_all(self) -> Dict[str, HealthStatus]:
        """Check connectivity for all accounts."""
```

**Test file:** `tests/unit/test_multi_account.py`

---

## PHASE 9: Comprehensive Strategy Testing

**Goal:** Achieve 90%+ coverage on all 135 strategy files across 13 categories.

### Task 9.1: Strategy Test Infrastructure
**File:** Create `tests/strategies/conftest.py`

```python
@pytest.fixture
def sample_ohlcv_data():
    """Generate realistic OHLCV data for strategy testing."""
    # 1 year of daily bars for AAPL with realistic returns

@pytest.fixture
def sample_tick_data():
    """Generate realistic tick data."""

@pytest.fixture
def strategy_config():
    """Default strategy configuration."""
```

### Task 9.2: Test Momentum Strategies (13 files)
**File:** Create `tests/strategies/test_momentum.py`

Test each strategy:
- ADX trend following
- Augmented MA crossover
- Augmented momentum
- Coppock curve
- Dual momentum
- Ichimoku cloud
- MACD crossover
- OBV trend
- Parabolic SAR
- ROC momentum
- Supertrend
- Turtle trading
- Vortex indicator

For each strategy test:
```python
def test_<strategy>_generates_buy_signal(self):
    """Verify buy signal on bullish data."""

def test_<strategy>_generates_sell_signal(self):
    """Verify sell signal on bearish data."""

def test_<strategy>_generates_no_signal_flat(self):
    """Verify no signal on flat data."""

def test_<strategy>_handles_insufficient_data(self):
    """Verify graceful handling of insufficient data."""

def test_<strategy>_confidence_range(self):
    """Verify confidence score is 0-1."""
```

### Task 9.3: Test Mean Reversion Strategies (13 files)
**File:** Create `tests/strategies/test_mean_reversion.py`

Test each strategy with the same pattern as momentum.

### Task 9.4: Test Volatility Breakout Strategies (7 files)
**File:** Create `tests/strategies/test_volatility_breakout.py`

### Task 9.5: Test Volume Weighted Strategies (6 files)
**File:** Create `tests/strategies/test_volume_weighted.py`

### Task 9.6: Test Pair Trading Strategies (10 files)
**File:** Create `tests/strategies/test_pair_trading.py`

Additional test cases for pairs:
- `test_cointegration_detection`
- `test_spread_calculation`
- `test_z_score_signal_generation`
- `test_hedge_ratio_computation`

### Task 9.7: Test Scalping Strategies (5 files)
**File:** Create `tests/strategies/test_scalping.py`

### Task 9.8: Test Advanced Technical Strategies (5 files)
**File:** Create `tests/strategies/test_advanced_technical.py`

Test cases for:
- Elliott Wave strategies
- Fibonacci strategies
- Gann strategies
- Harmonic patterns
- Geometric analysis

### Task 9.9: Test Remaining Strategy Categories
**File:** Create individual test files for:

| Category | Files | Test File |
|----------|-------|-----------|
| Arbitrage | 4 | `tests/strategies/test_arbitrage.py` |
| Backtesting | 12 | `tests/strategies/test_backtesting.py` |
| Machine Learning | 7 | `tests/strategies/test_ml_strategies.py` |
| Execution | 8 | `tests/strategies/test_execution.py` |
| Multi-asset | 1 | (in test_momentum.py or standalone) |
| Multi-factor | 2 | `tests/strategies/test_multi_factor.py` |
| Regime-based | 1 | `tests/strategies/test_regime.py` |
| Seasonal | 1 | (in test_momentum.py or standalone) |
| Breakout | 1 | (in test_volatility_breakout.py) |

### Task 9.10: Verify Phase 9 Coverage
```bash
pytest tests/strategies/ --cov=core_trading/strategies --cov-report=term-missing --cov-fail-under=90
```

---

## PHASE 10: Production Hardening

**Goal:** Security, reliability, and operational readiness.

### Task 10.1: Security Hardening

1. **Secrets Management**
   - Move all credentials to HashiCorp Vault or AWS Secrets Manager
   - Remove any hardcoded credentials from codebase
   - Add `.env` validation on startup (fail fast if missing required secrets)

2. **TLS/SSL for Inter-Service Communication**
   - Add TLS to all Kafka connections
   - Add TLS to PostgreSQL, ClickHouse, Redis connections
   - Add mTLS between microservices
   - Update `docker-compose.yml` with certificate volumes

3. **Network Security**
   - Docker network isolation (frontend, backend, data tiers)
   - IP whitelisting for IBKR Gateway access
   - Rate limiting on all API endpoints

4. **Dependency Security**
   - Pin all dependencies with hashes in `poetry.lock`
   - Add `pip-audit` or `safety` to CI pipeline
   - Weekly automated dependency update PRs (Dependabot/Renovate)

### Task 10.2: Reliability Enhancements

1. **Graceful Shutdown**
   - SIGTERM handler in every service
   - Drain in-flight orders before shutdown
   - Persist state to DB before exit
   - Close broker connections cleanly

2. **Startup Validation**
   - Verify all required services are reachable on startup
   - Validate configuration completeness
   - Pre-flight checks: DB schema version, Kafka topics exist, broker connectivity
   - Fail fast with clear error messages

3. **Data Durability**
   - Write-ahead log for all order state changes
   - PostgreSQL transaction guarantees for order persistence
   - ClickHouse data replication for market data
   - Redis persistence (AOF + RDB) for cache durability

4. **Disaster Recovery**
   - Automated backup schedule for PostgreSQL
   - ClickHouse backup via `clickhouse-backup`
   - Documented recovery runbook
   - Secondary broker failover capability

### Task 10.3: Observability

1. **Structured Logging Enhancement**
   - Correlation IDs across all services (X-Correlation-ID header)
   - Log aggregation via Loki with consistent labels
   - Sensitive data redaction (credentials, PII)
   - Log levels: ERROR for alerts, WARNING for degraded, INFO for audit

2. **Metrics Enhancement**
   - Latency histograms per order (submit to fill)
   - Strategy performance metrics (Sharpe, win rate, drawdown)
   - System resource metrics (CPU, memory, disk, network)
   - Business metrics (orders/minute, fills/minute, active strategies)
   - Grafana dashboards for each service

3. **Alerting Rules**
   - Create Prometheus alerting rules:
     - `BrokerDisconnected` - connection to IBKR lost
     - `CircuitBreakerOpen` - circuit breaker tripped
     - `HighErrorRate` - error rate > 5%
     - `DailyLossApproaching` - 80% of daily loss limit
     - `KillSwitchActivated` - emergency stop triggered
     - `LowDiskSpace` - disk > 85% full
     - `HighLatency` - order latency > 500ms
     - `StaleData` - no market data for > 30 seconds

### Task 10.4: Configuration Management

1. **Environment-Based Configuration**
   - Separate configs for dev, staging, production
   - Pydantic Settings with environment variable overrides
   - Config validation on startup (ranges, types, required fields)

2. **Feature Flags**
   - Toggle strategies on/off without redeployment
   - Toggle paper/live trading mode
   - Toggle advanced features (SOR, TWAP/VWAP)

### Task 10.5: Performance Optimization

1. **Latency Optimization**
   - Measure and optimize order submission latency
   - Use connection pooling for all database connections
   - Batch Kafka messages where possible
   - Async I/O everywhere (no blocking calls in hot paths)

2. **Memory Optimization**
   - Memory limits in Docker Compose for each service
   - Bounded data structures (ring buffers for tick data)
   - Periodic cleanup of stale cache entries

3. **Load Testing**
   - Create `tests/performance/test_load.py`
   - Simulate 100+ concurrent orders
   - Simulate 1000+ ticks/second market data
   - Verify system stability under sustained load
   - Measure p50, p95, p99 latencies

---

## PHASE 11: Integration Testing & Paper Trading

**Goal:** End-to-end verification with real infrastructure and paper trading.

### Task 11.1: Docker Compose Integration Tests
**File:** Create `tests/e2e/test_docker_integration.py`

```python
@pytest.mark.e2e
class TestDockerIntegration:
    """Tests that spin up actual Docker services."""

    async def test_all_services_start_healthy(self):
        """Verify all 15 Docker services start and report healthy."""

    async def test_postgres_schema_initialized(self):
        """Verify all SQL tables are created correctly."""

    async def test_kafka_topics_created(self):
        """Verify all 40+ Kafka topics exist."""

    async def test_grafana_dashboards_loaded(self):
        """Verify Grafana has expected dashboards."""
```

### Task 11.2: End-to-End Order Flow Test
**File:** Create `tests/e2e/test_e2e_order_flow.py`

```python
@pytest.mark.e2e
async def test_full_order_lifecycle_with_real_infra():
    """End-to-end test with real Kafka, PostgreSQL, Redis, ClickHouse."""
    # 1. Start all services via docker-compose
    # 2. Connect to IBKR paper trading
    # 3. Subscribe to market data for AAPL
    # 4. Wait for real-time tick
    # 5. Strategy generates signal
    # 6. Risk engine validates
    # 7. Execution engine submits order
    # 8. Order persisted to PostgreSQL
    # 9. Fill received and processed
    # 10. P&L updated
    # 11. Audit trail entry created
    # 12. Verify all events flowed through Kafka
```

### Task 11.3: Paper Trading Validation
**File:** Create `tests/e2e/test_paper_trading.py`

```python
@pytest.mark.paper_trading
class TestPaperTrading:
    """Tests against IBKR paper trading account."""

    async def test_connect_paper_account(self):
        """Connect to IBKR paper trading TWS/Gateway."""

    async def test_place_and_cancel_order(self):
        """Place a limit order and cancel it."""

    async def test_market_data_subscription(self):
        """Subscribe to real-time market data and receive ticks."""

    async def test_position_sync(self):
        """Verify position synchronization after manual fill."""

    async def test_account_info(self):
        """Retrieve account balances and buying power."""

    async def test_kill_switch_paper(self):
        """Activate kill switch and verify all orders cancelled."""

    async def test_circuit_breaker_under_failures(self):
        """Simulate failures and verify circuit breaker opens."""
```

### Task 11.4: Strategy Backtesting Validation
**File:** Create `tests/e2e/test_strategy_backtesting.py`

```python
@pytest.mark.e2e
async def test_momentum_strategy_backtest():
    """Run backtest on historical data and verify results are reasonable."""
    # 1. Load 1 year of historical data
    # 2. Run MACD crossover strategy
    # 3. Verify Sharpe ratio > 0
    # 4. Verify max drawdown < 30%
    # 5. Verify total trades > 10
```

### Task 11.5: Chaos Engineering
**File:** Create `tests/chaos/test_resilience.py`

```python
@pytest.mark.chaos
class TestResilience:
    """Verify system recovers from failures."""

    async def test_broker_disconnect_recovery(self):
        """Kill broker connection, verify auto-reconnect."""

    async def test_kafka_broker_failure(self):
        """Stop Kafka broker, verify system queues and recovers."""

    async def test_postgres_failure(self):
        """Stop PostgreSQL, verify graceful degradation."""

    async def test_redis_failure(self):
        """Stop Redis, verify in-memory fallback works."""

    async def test_clickhouse_failure(self):
        """Stop ClickHouse, verify system continues without historical storage."""

    async def test_oom_recovery(self):
        """Simulate memory pressure, verify bounded behavior."""
```

---

## PHASE 12: Deployment & Go-Live

**Goal:** Final verification and production deployment readiness.

### Task 12.1: Deployment Pipeline

1. **CI/CD Enhancement**
   - Add staging environment to CI pipeline
   - Blue-green deployment strategy
   - Automated rollback on test failures
   - Deployment approval gate for production

2. **Docker Optimization**
   - Multi-stage builds for smaller images
   - Health checks on all containers
   - Resource limits (CPU, memory) for all services
   - Docker image vulnerability scanning (Trivy)

3. **Infrastructure as Code**
   - Terraform/Pulumi for cloud resources (if deploying to cloud)
   - Docker Compose for local/on-premise
   - Kubernetes manifests for scalable deployment (optional)

### Task 12.2: Documentation

1. **Operations Runbook** (`docs/operations-runbook.md`)
   - How to start/stop the system
   - How to monitor system health
   - How to activate/deactivate kill switch
   - How to add a new strategy
   - How to switch paper/live trading
   - Recovery procedures for common failures
   - Contact information for support

2. **API Documentation** (`docs/api-reference.md`)
   - All REST endpoints with request/response schemas
   - WebSocket protocol documentation
   - Authentication flow
   - Rate limits

3. **Architecture Documentation** (`docs/architecture.md`)
   - System architecture diagram
   - Service communication patterns
   - Data flow diagrams
   - Database schema documentation
   - Event/message schema documentation

### Task 12.3: Pre-Launch Checklist

- [ ] All 92%+ test coverage verified
- [ ] Paper trading for 2+ weeks with no unexpected behavior
- [ ] Security scan (bandit, pip-audit) with no high/critical findings
- [ ] Load test passed at expected throughput
- [ ] Chaos test passed (broker disconnect, DB failures)
- [ ] Backup and recovery tested
- [ ] Monitoring and alerting configured and tested
- [ ] Kill switch tested in paper environment
- [ ] Compliance engine validated
- [ ] Audit trail integrity verified
- [ ] All documentation reviewed and up-to-date
- [ ] Secrets management configured
- [ ] TLS/SSL enabled on all connections
- [ ] Graceful shutdown verified
- [ ] Disaster recovery plan documented and tested

---

## EXECUTION ORDER SUMMARY

```
Phase 7: Test Coverage Push (76% -> 92%+)
  7.1  Kafka producer tests                (5% -> 90%)
  7.2  Error handler tests                 (15% -> 90%)
  7.3  Monitoring metrics tests            (26% -> 90%)
  7.4  Logger tests                        (31% -> 90%)
  7.5  Qdrant client tests                 (31% -> 90%)
  7.6  IBKR adapter deep tests             (47% -> 90%)
  7.7  Health monitor tests                (48% -> 90%)
  7.8  PostgreSQL client tests             (58% -> 90%)
  7.9  Risk engine deep tests              (58% -> 90%)
  7.10 Execution engine deep tests         (61% -> 90%)
  7.11 ClickHouse client tests             (65% -> 90%)
  7.12 Remaining coverage gaps             (70-86% -> 90%)
  7.13 Data feed module tests              (0% -> 90%)
  7.14 Reconnection manager tests          (0% -> 90%)
  7.15 Order persistence tests             (0% -> 90%)
  7.16 Verify 92%+ coverage

Phase 8: Advanced Features
  8.1  Smart Order Router (SOR)
  8.2  TWAP/VWAP Execution Algorithms
  8.3  Advanced Order Types (Trailing Stop, Bracket, OCO, OTO, Iceberg)
  8.4  Real-Time P&L with Greeks
  8.5  Scenario / Stress-Test Engine
  8.6  Compliance Engine (PDT, Wash Sale, Reg T)
  8.7  Immutable Audit Trail
  8.8  Web Dashboard (API + Frontend)
  8.9  Notification Service
  8.10 Multi-Account Support

Phase 9: Strategy Testing (135 files)
  9.1  Strategy test infrastructure (conftest, fixtures)
  9.2  Momentum strategies (13 files)
  9.3  Mean reversion strategies (13 files)
  9.4  Volatility breakout strategies (7 files)
  9.5  Volume weighted strategies (6 files)
  9.6  Pair trading strategies (10 files)
  9.7  Scalping strategies (5 files)
  9.8  Advanced technical strategies (5 files)
  9.9  Remaining strategy categories (arbitrage, ML, backtesting, execution, etc.)
  9.10 Verify 90%+ strategy coverage

Phase 10: Production Hardening
  10.1 Security hardening (secrets, TLS, network, deps)
  10.2 Reliability (graceful shutdown, startup validation, durability, DR)
  10.3 Observability (logging, metrics, alerting)
  10.4 Configuration management
  10.5 Performance optimization and load testing

Phase 11: Integration Testing & Paper Trading
  11.1 Docker Compose integration tests
  11.2 End-to-end order flow with real infrastructure
  11.3 IBKR paper trading validation
  11.4 Strategy backtesting validation
  11.5 Chaos engineering tests

Phase 12: Deployment & Go-Live
  12.1 Deployment pipeline (CI/CD, Docker, IaC)
  12.2 Documentation (runbook, API, architecture)
  12.3 Pre-launch checklist verification
```

---

## FILES TO CREATE (NEW)

| File | Purpose | Phase |
|------|---------|-------|
| `tests/unit/test_kafka_producer.py` | Kafka producer tests | 7 |
| `tests/unit/test_error_handlers.py` | Error handler tests | 7 |
| `tests/unit/test_monitoring_metrics.py` | Monitoring metrics tests | 7 |
| `tests/unit/test_logger.py` | Logger tests | 7 |
| `tests/unit/test_monitoring_health.py` | Health check tests | 7 |
| `tests/unit/test_data_feeds.py` | Data feed module tests | 7 |
| `tests/unit/test_reconnection.py` | Reconnection manager tests | 7 |
| `tests/unit/test_order_store.py` | Order persistence tests | 7 |
| `tests/unit/test_execution_engine.py` | Execution engine deep tests | 7 |
| `core_trading/execution/smart_order_router.py` | Smart Order Router | 8 |
| `core_trading/execution/algo_orders.py` | TWAP/VWAP execution | 8 |
| `core_trading/execution/advanced_orders.py` | Trailing stop, bracket, OCO, OTO, iceberg | 8 |
| `core_trading/analytics/pnl_tracker.py` | Real-time P&L with Greeks | 8 |
| `core_trading/analytics/scenario_engine.py` | Stress-test engine | 8 |
| `services/compliance/src/compliance_engine.py` | Compliance checking | 8 |
| `services/compliance/src/audit_trail.py` | Immutable audit trail | 8 |
| `services/dashboard/src/api.py` | Dashboard REST API | 8 |
| `services/notifications/src/notification_service.py` | Multi-channel alerts | 8 |
| `core_trading/accounts/multi_account_manager.py` | Multi-account trading | 8 |
| `tests/unit/test_smart_order_router.py` | SOR tests | 8 |
| `tests/unit/test_algo_orders.py` | TWAP/VWAP tests | 8 |
| `tests/unit/test_advanced_orders.py` | Advanced order tests | 8 |
| `tests/unit/test_pnl_tracker.py` | P&L tracker tests | 8 |
| `tests/unit/test_scenario_engine.py` | Scenario engine tests | 8 |
| `tests/unit/test_compliance_engine.py` | Compliance tests | 8 |
| `tests/unit/test_audit_trail.py` | Audit trail tests | 8 |
| `tests/unit/test_dashboard_api.py` | Dashboard API tests | 8 |
| `tests/unit/test_notification_service.py` | Notification tests | 8 |
| `tests/unit/test_multi_account.py` | Multi-account tests | 8 |
| `tests/strategies/conftest.py` | Strategy test fixtures | 9 |
| `tests/strategies/test_momentum.py` | Momentum strategy tests | 9 |
| `tests/strategies/test_mean_reversion.py` | Mean reversion strategy tests | 9 |
| `tests/strategies/test_volatility_breakout.py` | Volatility breakout tests | 9 |
| `tests/strategies/test_volume_weighted.py` | Volume weighted tests | 9 |
| `tests/strategies/test_pair_trading.py` | Pair trading tests | 9 |
| `tests/strategies/test_scalping.py` | Scalping strategy tests | 9 |
| `tests/strategies/test_advanced_technical.py` | Advanced technical tests | 9 |
| `tests/strategies/test_arbitrage.py` | Arbitrage strategy tests | 9 |
| `tests/strategies/test_backtesting.py` | Backtesting engine tests | 9 |
| `tests/strategies/test_ml_strategies.py` | ML strategy tests | 9 |
| `tests/strategies/test_execution.py` | Execution strategy tests | 9 |
| `tests/strategies/test_multi_factor.py` | Multi-factor tests | 9 |
| `tests/strategies/test_regime.py` | Regime-based tests | 9 |
| `tests/e2e/test_docker_integration.py` | Docker integration tests | 11 |
| `tests/e2e/test_e2e_order_flow.py` | Full order lifecycle test | 11 |
| `tests/e2e/test_paper_trading.py` | IBKR paper trading tests | 11 |
| `tests/e2e/test_strategy_backtesting.py` | Strategy backtest validation | 11 |
| `tests/chaos/test_resilience.py` | Chaos engineering tests | 11 |
| `tests/performance/test_load.py` | Load/performance tests | 10 |
| `docs/operations-runbook.md` | Operations documentation | 12 |
| `docs/api-reference.md` | API documentation | 12 |
| `docs/architecture.md` | Architecture documentation | 12 |

---

## KEY PRINCIPLES

1. **Test every new feature** - Each Phase 8 feature must have corresponding tests with 90%+ coverage.
2. **Never merge without CI passing** - All tests, linting, type checking, security scans green.
3. **Paper trade before live** - No feature goes live without paper trading validation.
4. **Fail safe, not fail open** - Default to blocking orders on any uncertainty.
5. **Audit everything** - Every order, signal, risk decision, and kill switch action is recorded.
6. **Measure before optimizing** - Profile before performance changes, verify after.
7. **Gradual rollout** - New features behind feature flags, paper trade first, then small live positions.
