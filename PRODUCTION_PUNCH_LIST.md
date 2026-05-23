# Production Readiness Punch List

**Generated:** 2026-05-21
**Target:** Paper Trading via IBKR Paper Account (port 7497)

## 1. Executive Verdict

**NOT ready for paper trading today.** There is no runnable entrypoint that wires `IBKRAdapter` to the `ExecutionEngine`. The trading-engine `main.py` has two TODO comments where those connections should be made and does neither. Even if you started TWS and ran the service, orders would never reach IBKR.

The core components individually are solid. The minimum work to reach a functional paper trading loop is approximately **8-11 focused hours**: one wiring/bootstrap file, fill callback registration, two small bug fixes, deletion of broken stubs, and credential hygiene.

## 2. URGENT — Security Issue (do this first)

**Real IBKR paper trading credentials exist in three places, with different exposure levels:**

| File | Exposure | What it contains |
|------|----------|------------------|
| `.env` (lines 69-71) | Gitignored, on local disk only | Real `IBKR_USERNAME`, `IBKR_PASSWORD`, `IBKR_ACCOUNT_ID` |
| `core_trading/adapters/ibkr_adapter.py:101` | **Committed to git history** | Real account ID as hardcoded fallback default |
| `core_trading/adapters/ibkr_adapter.py.fixed_attempt` | **Committed to git history** | Same hardcoded account ID (old backup file should not be tracked at all) |
| `tests/conftest.py:73` | **Committed to git history** | Real account ID as test fixture value |

**Action required immediately:**

1. **Rotate the IBKR paper trading password** via IBKR Client Portal. The cleartext value sat in `.env` and has been read by tooling.
2. **Remove the hardcoded account ID** from all three tracked source files. Default to `None` and raise `ValueError` if not set via env.
3. **Delete `ibkr_adapter.py.fixed_attempt`** and remove it from git tracking. Any `.fixed_attempt` / `.old` / `.bak` files should be in `.gitignore`.
4. **Decide on git history rewrite.** Since this is a private repo for personal use, a `git filter-repo` rewrite is optional but recommended hygiene. If you ever publish this repo, it is mandatory.

Note: a paper trading account ID alone is not a credential — without the password it cannot be used to trade. But the password is in `.env` cleartext and the username is identifiable. Rotate.

## 3. Critical Blockers (in fix order)

### B1 — IBKR Adapter: Silent Simulation Fallback

**Severity:** Blocker
**Files:** `core_trading/adapters/ibkr_adapter.py:23-28, 153-157, 343-357`

When `ib_insync` is not installed, the adapter silently switches to simulation mode and reports `CONNECTED`. Every order "succeeds" without touching IBKR. This is the worst kind of bug: a broker that lies.

```python
# ibkr_adapter.py:153-157
if not IBKR_AVAILABLE:
    logger.info("IBKR integration not available - using simulation mode")
    self._set_status(ConnectionStatus.CONNECTED)  # reports CONNECTED with no connection
    return True
```

**Fix:** Replace silent simulation with `raise RuntimeError("ib_insync not installed — cannot connect to IBKR")`. Force install of `ib_insync>=0.9.86` (currently absent from `pyproject.toml`).

**Effort:** 2-4 hours

### B2 — Event Bus: `await` Against Sync Method

**Severity:** Blocker (causes `TypeError` on engine startup)
**Files:** `services/trading-engine/src/core/event_system.py:80`, `services/trading-engine/src/engines/execution_engine.py:495`

`EventBus.subscribe()` is synchronous but `ExecutionEngine.initialize()` awaits it. In Python 3.10+ this raises `TypeError`; in older Python it silently returns `None` and the `ORDER` handler is never registered.

**Fix:** Remove `await` from `execution_engine.py:495`.

**Effort:** 5 minutes

### B3 — Execution Engine: Zero Wiring to IBKR Adapter

**Severity:** Blocker
**Files:** `services/trading-engine/src/main.py:15-26`

```python
# main.py:15
execution_engine = ExecutionEngine()   # broker_adapter=None — orders never reach IBKR
# main.py:21
# TODO: Connect to Kafka
# main.py:24
# TODO: Connect to IBKR
```

When `broker_adapter` is `None`, `execution_engine.py:592` skips the broker call entirely. Orders state-machine to `SUBMITTED` then sit there forever.

**Fix:** Rewrite `main.py` to instantiate `IBKRAdapter` from env, connect, pass to `ExecutionEngine`. Sketch:

```python
import asyncio, os
from core_trading.adapters.ibkr_adapter import IBKRAdapter
from services.trading_engine.src.engines.execution_engine import ExecutionEngine
from services.trading_engine.src.core.event_system import get_event_bus

async def main():
    event_bus = get_event_bus()
    ibkr = IBKRAdapter(
        host=os.getenv("IBKR_HOST", "127.0.0.1"),
        port=int(os.getenv("IBKR_PORT", "7497")),
        client_id=int(os.getenv("IBKR_CLIENT_ID", "1")),
        account_id=os.environ["IBKR_ACCOUNT_ID"],  # required; no fallback
        paper_trading=os.getenv("IBKR_TRADING_MODE", "paper") == "paper",
    )
    if not await ibkr.connect():
        raise RuntimeError("IBKR connection failed")

    engine = ExecutionEngine(broker_adapter=ibkr, event_bus=event_bus)
    await engine.initialize()

    if ibkr.ib:
        ibkr.ib.execDetailsEvent += lambda trade, fill: asyncio.create_task(
            engine.handle_fill(str(fill.execution.orderId),
                               fill.execution.shares,
                               fill.execution.price)
        )

    await ibkr.start_heartbeat()
    while True:
        await asyncio.sleep(1)
```

**Effort:** 4-6 hours

### B4 — Duplicate Adapter Architecture [RESOLVED 2026-05-23]

**Severity:** Critical (import errors, developer confusion)

**Original state:**

| Canonical (keep) | Broken duplicate |
|---|---|
| `core_trading/adapters/ibkr_adapter.py` (634 lines, real ib_insync) | `core_trading/adapters/brokers/interactive_brokers.py` (58 lines, syntax error) |
| `core_trading/adapters/base.py` (284 lines, real ABCs) | `core_trading/adapters/broker_adapter.py` (60 lines, all commented out) |
| `core_trading/adapters/brokers/factory.py` | `core_trading/adapters/broker_factory.py` (177 lines, all commented out) |

Plus the 7 sibling gutted broker stubs (alpaca, binance, coinbase, oanda, fxcm, trading212, websocket_streaming) — see SKELETON_INVENTORY.md.

**Resolution:**

- Top-level duplicates (`broker_adapter.py`, `broker_factory.py`, `ibkr_adapter.py.fixed_attempt`) were archived in commit `d5ecaf5` (2026-05-21) under `.archive/2026-05-21_dead_adapters/top_level/`.
- The 7 sibling broker stubs and 5 broken helper modules under `core_trading/adapters/brokers/` were rewritten as honest ~25-line roadmap-marker modules. Each raises `NotImplementedError` on instantiation and documents the planned SDK, license, asset classes, and priority. Per user decision (see `project-broker-roadmap` memory), the stubs are kept in-place rather than archived so the directory tree reflects planned multi-broker scope.
- The try/except spaghetti in `brokers/__init__.py` (which silently swallowed every ImportError) was replaced with a clean package docstring.
- `brokers/README.md` was rewritten to remove the "Production Ready" claims and reflect actual status.

**What remains importable** from `core_trading.adapters.brokers`:
- `rate_limiting` (real implementation, used by `core_trading/data_feeds/ibkr_data_feed.py`)
- The roadmap-marker classes (instantiation raises NotImplementedError)

**Effort spent:** ~1 hour

### B5 — IBKR Fill Callback Not Wired

**Severity:** Critical
**Files:** `core_trading/adapters/ibkr_adapter.py:214-220`, `services/trading-engine/src/engines/execution_engine.py:652`

`_register_ib_callbacks()` only registers `disconnectedEvent` and `errorEvent`. Missing:

- `execDetailsEvent` — fill confirmations
- `orderStatusEvent` — CANCELLED / REJECTED transitions

Without these, orders state-machine to `SUBMITTED` and stay there. Positions never get marked filled. PnL is wrong. You can't close because the engine thinks you have no position.

**Fix:** Add to `_register_ib_callbacks()`:

```python
self.ib.execDetailsEvent += self._on_exec_details
self.ib.orderStatusEvent += self._on_order_status
```

Implement `_on_exec_details(trade, fill)` and `_on_order_status(trade)` to route to `ExecutionEngine.handle_fill()` and the state machine respectively.

**Effort:** 2-3 hours

### B6 — IBKR_PORT Constructor Argument Ignored

**Severity:** High
**File:** `core_trading/adapters/ibkr_adapter.py:161`

```python
# ibkr_adapter.py:161 — wrong
port = 7497 if self.paper_trading else 7496
```

The `port` arg passed to `__init__` is stored in `self.port` but the connect path hardcodes 7497/7496 based on `paper_trading`. The `IBKR_PORT` env var and constructor argument are both silently ignored.

**Fix:** Replace line 161 with `port = self.port`.

**Effort:** 5 minutes

## 4. Path to Paper Trading — Minimum Viable Loop

Goal: connect → place 1-share AAPL paper order → see fill → close position.

| # | Step | Effort |
|---|------|--------|
| 1 | Rotate IBKR password, remove hardcoded account ID from 3 files | 1h |
| 2 | Install `ib_insync>=0.9.86`, remove silent simulation fallback | 30min |
| 3 | Fix `await subscribe` `TypeError` | 5min |
| 4 | Delete broken stub adapters (B4) | 1h |
| 5 | Fix `IBKR_PORT` constructor honoring (B6) | 5min |
| 6 | Write bootstrap `main.py` (B3) | 4-6h |
| 7 | Wire `execDetailsEvent` and `orderStatusEvent` (B5) | 2-3h |
| 8 | Smoke test: launch IB Gateway in paper mode, run engine, submit 1-share AAPL order, watch state → FILLED | 1h |

**Total: 9-12 hours** of focused work. One developer-day.

## 5. Path to Live Trading (after 90-day paper validation)

Do not skip paper validation.

1. **Kafka event bus.** `main.py:21` TODO. 43 topics documented, none wired. Required for multi-service production.
2. **PostgreSQL order persistence.** `OrderStore` in `persistence/order_store.py` exists. Wire by passing it into `ExecutionEngine`. Required for crash recovery — a process restart today loses all in-flight order state.
3. **Sector classification.** `risk_engine.py:1219` `_calculate_sector_exposures()` returns `{"Unclassified": 1.0}`. Concentration limits non-functional without real sector data.
4. **Keycloak auth.** ADR-014 documents it; not implemented. Required for any multi-user access.
5. **Live trading guard.** Enforce `FEATURE_LIVE_TRADING_ENABLED` flag check in the bootstrap, plus port-switch logic (7496 = live, 7497 = paper).
6. **Unique `IBKR_CLIENT_ID`** per simultaneous TWS connection.

## 6. Configuration Gaps

| Variable | In .env.example | Used in code | Status |
|----------|-----------------|--------------|--------|
| IBKR_HOST | ✅ | ✅ | OK |
| IBKR_PORT | ✅ | ❌ ignored (see B6) | Fix code |
| IBKR_CLIENT_ID | ❌ missing | defaults to 1 | Add to .env.example |
| IBKR_ACCOUNT_ID | ✅ | ✅ with hardcoded fallback | Remove fallback |
| IBKR_TRADING_MODE | ✅ | ❌ not read by code | Wire to bootstrap |
| IBKR_PAPER_MAX_POSITION_SIZE | ❌ | ✅ (`ibkr_adapter.py:132`) | Add to .env.example |
| IBKR_PAPER_MAX_DAILY_LOSS_PERCENTAGE | ❌ | ✅ (`ibkr_adapter.py:134`) | Add to .env.example |
| IBKR_PAPER_MAX_DAILY_TRADES | ❌ | ✅ (`ibkr_adapter.py:136`) | Add to .env.example |
| IBKR_MAX_CONCURRENT_POSITIONS | ❌ | ✅ (`ibkr_adapter.py:138`) | Add to .env.example |

## 7. What Actually Works (positives)

To balance: significant good work exists.

- **`core_trading/adapters/ibkr_adapter.py`** — the real IBKR integration is correct. Connect/disconnect, `placeOrder`, `cancelOrder`, `get_positions`, `accountValues`, historical data, market data subs, heartbeat loop, reconnect-with-backoff. Only needs fill callbacks + port-fix.
- **`core_trading/adapters/reconnection.py`** — clean exponential-backoff with jitter, callbacks. Ready to use.
- **`core_trading/adapters/base.py`** — complete, well-designed ABC hierarchy. Nothing broken.
- **`services/trading-engine/src/engines/execution_engine.py`** — `OrderStateMachine` (lines 197-273) is correct. `submit_order()`, `handle_fill()`, `reconcile_on_startup()` all well-structured. One-line `await` bug aside.
- **`services/trading-engine/src/core/event_system.py`** — `EventBus.publish()` correctly handles sync + async callbacks, gathers tasks with `return_exceptions=True`, trims history. The bug is in the caller, not here.
- **`services/risk-manager/src/engines/risk_engine.py`** — 8 pre-trade checks, VaR with 4 methods, real-time portfolio loop, alerts. Only stub is sector classification.
- **`core_trading/data_feeds/ibkr_data_feed.py`** — rate-limited (45 req/s token bucket), real-time tickers, L2 order book, historical bars. Ready.
- **`.env.example`** — covers all major variables with security warnings and paper-first guidance.
- **`services/trading-engine/src/persistence/order_store.py`** — PostgreSQL upsert, startup reconciliation. Ready.

## 8. Summary

| Blocker | Severity | Effort | Status |
|---------|----------|--------|--------|
| B1: Silent simulation fallback | Blocker | 2-4h | RESOLVED (commit `e21d891`) |
| B2: `await` against sync `subscribe` | Blocker | 5min | RESOLVED (commit `e21d891`) |
| B3: No adapter-to-engine wiring | Blocker | 4-6h | RESOLVED (commit `e21d891`) |
| B4: Broken stub files | Critical | 1h | RESOLVED (2026-05-23) |
| B5: Fill callback not wired | Critical | 2-3h | RESOLVED (commit `e21d891`) |
| B6: `IBKR_PORT` ignored | High | 5min | RESOLVED (commit `e21d891`) |
| Credential hygiene | Critical Security | 1h | RESOLVED (commit `dad70a9`) |

**Total minimum work for a working paper trading loop: 9-12 focused hours.**

The architecture is sound. The wiring is missing. The repo passed a documentation-level Level 3 audit but never had a runnable end-to-end trading loop. Fix the wiring and you have a real system.
