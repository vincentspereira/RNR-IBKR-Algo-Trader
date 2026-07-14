# Cleanup Plan — State After 2026-05-21 Session

## What was done this session (22 files archived)

- **3 top-level adapter duplicates** archived to `.archive/2026-05-21_dead_adapters/top_level/`:
  - `core_trading/adapters/broker_adapter.py` (gutted duplicate ABC)
  - `core_trading/adapters/broker_factory.py` (gutted duplicate factory)
  - `core_trading/adapters/ibkr_adapter.py.fixed_attempt` (old backup)
- **19 shadow files** archived from `core_trading/adapters/brokers/` to `.archive/2026-05-21_dead_adapters/brokers/`:
  - 15 `.fixed_attempt` files (all of them)
  - 4 `.backup` files (alpaca, coinbase, interactive_brokers, websocket_streaming — these contain the original *working* pre-refactor code; see archive README)
- `.gitignore` updated to prevent future `.backup`, `.fixed_attempt`, `.old`, `.bak`, `.orig` shadow files from being committed.

## What still needs your decision

### Tier 1 — gutted broker adapters with no working alternative

These are still in `core_trading/adapters/brokers/` and **will fail to import** in their current state:

- `interactive_brokers.py` — gutted; we use `ibkr_adapter.py` instead → safe to delete
- `factory.py` — gutted broker factory; imports broken sibling modules → needs delete or rewrite
- `error_handling.py` — gutted; the restored `.backup` brokers depend on this → needs rewrite

And these are gutted with no working `.backup` to restore from:

- `binance.py`, `oanda.py`, `fxcm.py`, `trading212.py`

For these, you have three options each:
1. **Delete** — fastest path to a clean tree if you don't need multi-broker support now.
2. **Rewrite from scratch** — follow your global CLAUDE.md pattern (preserve logic, discard formatting).
3. **Leave as TODO markers** — explicitly document "Phase X: support Y broker".

### Tier 2 — restorable broker adapters

These have working `.backup` files in archive:

- `alpaca.py` (working `.backup` available)
- `coinbase.py` (working `.backup` available)
- `websocket_streaming.py` (working `.backup` available)

To restore any of them, see the recovery how-to in `.archive/2026-05-21_dead_adapters/README.md`.

Note: even after restoring, they import from the gutted `error_handling.py` and `security.py` in `brokers/`, so you'd also need to either restore or rewrite those.

### Tier 3 — the brokers/__init__.py situation

The current `core_trading/adapters/brokers/__init__.py` tries to import each broker module with `try/except: pass`. After the gutted files are deleted, this becomes dead code. Rewrite as a minimal `__init__.py` that imports only what exists.

## Recommended path forward (focused on paper trading)

User decision 2026-05-21: **keep all broker stubs as roadmap markers**. Don't delete; don't pre-emptively restore. Multi-broker support is a future-phase goal.

For paper trading via IBKR ASAP:

1. **Leave the gutted broker stubs in `core_trading/adapters/brokers/`** as roadmap signals — they document intent without affecting the IBKR loop (nothing imports them).
2. **`core_trading/adapters/ibkr_adapter.py` is the sole canonical broker** for this phase.
3. **Address the production blockers** in `PRODUCTION_PUNCH_LIST.md` — that's the critical path.

## Future broker roadmap (deferred — keep on file)

The user intends to add support for additional brokers in later phases. Capture here so we don't forget:

| Broker | Region / Asset | Status | Notes |
|--------|---------------|--------|-------|
| **IBKR** | Global, multi-asset | **Canonical (in progress)** | `core_trading/adapters/ibkr_adapter.py`. Focus of current work. |
| Alpaca | US equities + crypto | Stub gutted; `.backup` archived | Working pre-refactor code at `.archive/2026-05-21_dead_adapters/brokers/alpaca.py.backup`. Restore when needed. Apache-2.0 SDK (MAS-safe). |
| Coinbase | Crypto | Stub gutted; `.backup` archived | Same recovery path. Apache-2.0 SDK (MAS-safe). |
| Binance | Crypto | Stub gutted; no `.backup` | Rewrite from scratch using `python-binance` (MIT, MAS-safe). |
| OANDA | Forex/CFD | Stub gutted; no `.backup` | Rewrite using `oandapyV20` (MIT, MAS-safe). |
| FXCM | Forex/CFD | Stub gutted; no `.backup` | Rewrite using `fxcmpy` (license unclear — verify before MAS lift). |
| Trading212 | EU equities/CFD | Stub gutted; no `.backup` | No official API; uses reverse-engineered endpoints. Low priority. |
| Saxo | Multi-asset | Not started | Worth considering as IBKR alternative for European users (covered in `FINCEPT_TERMINAL_ASSESSMENT.md`). |
| Tradier | US options | Not started | Cheap options data; worth adding when options strategies mature. |

Sequencing when revisited: **Alpaca first** (working `.backup` exists, US equities, MAS-safe, complements IBKR for commission-free US trading). **Coinbase second** if crypto strategies emerge. Everything else as on-demand.

## Infrastructure swaps applied this session (2026-05-21)

- **Neo4j 5.25 Community (GPL-3.0)** → **ArcadeDB 24.11.1 (Apache-2.0)**. Multi-model graph + document DB. Code paths in `libs/database/neo4j/client.py` need rewriting to use ArcadeDB's HTTP API or `arcadedb-python` — tracked in HANDOVER.md.
- **Redis 7.4 (SSPL+RSALv2)** → **Valkey 8 (BSD-3-Clause)**. Wire-compatible; no Python client changes needed.
- **Grafana 10.2.3 (AGPL)** → **Grafana 9.5.21 (Apache-2.0)** (last permissive release).
- **Loki + Promtail** pinned at 2.9.10 (last Apache-2.0 patch).

Future infrastructure migration targets, deferred:
- Grafana 9.5.x → **Perses** (Apache-2.0, CNCF) once its dashboard library matures.
- Loki+Promtail → **Vector (MPL-2.0) shipping to existing ClickHouse** to remove a dedicated log store.
- Confluent CP-Kafka/Schema-Registry → **apache/kafka:3.9 + apicurio/apicurio-registry** before any commercial MAS deployment.
- `yfinance` → **Polygon / Tiingo / IEX Cloud / Finnhub** before any commercial MAS deployment.

## Verification commands

After any further cleanup:

```bash
cd "/home/vincentspereira/Projects/Trading/RNR-IBKR-Algo-Trader"

# Check nothing imports a deleted module
python -c "import core_trading.adapters.ibkr_adapter; print('OK')"
python -c "from core_trading.adapters.brokers import rate_limiting; print('OK')"

# Run the test suite if Python 3.12 + deps are installed
pytest tests/unit/ -q

# Make sure git diff doesn't accidentally include .env or secrets
git diff --stat
git status
```

## Not committed yet

I did not `git commit` any of these changes. You can review with `git status` and commit (or revert with `git restore --staged . && git checkout .`) at your discretion. The archive directory is excluded from git via `.gitignore`, so the archived files won't show up in `git status` as additions — they're effectively a local-disk safety net only.
