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

If your goal is "paper trading via IBKR working ASAP", the cleanest plan is:

1. **Delete everything except IBKR in `core_trading/adapters/brokers/`** — keep only `__init__.py`, `rate_limiting.py` (verified intact), and possibly `health_monitoring.py`/`security.py`/`config_validation.py` (need to verify).
2. **Delete `core_trading/adapters/brokers/interactive_brokers.py`** — `core_trading/adapters/ibkr_adapter.py` is the canonical path.
3. **Reduce `brokers/__init__.py`** to: `# Broker utilities. Concrete brokers live one level up (ibkr_adapter.py).`
4. **Address the production blockers** in `PRODUCTION_PUNCH_LIST.md`.
5. **Add multi-broker support later** by restoring/rewriting individual adapters when needed, not pre-emptively.

## Verification commands

After any further cleanup:

```bash
cd "C:\Users\vince\Projects\Trading\IBKR - Algo Trader"

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
