# Remediation Memo -- 2026-05-28 Session

**Author:** Vincent S. Pereira (with Claude)
**Status:** Investigation results + recommendations; no code-level deletion performed pending sign-off

---

## Context

Phase 0.5 of `docs/QUANT_TRADING_MASTER_PLAN.md` calls out duplication between
`services/trading-engine/src/engines/` and `core_trading/engines/`. This memo
documents what was found and recommends the canonical home for each component.

## Findings

| File | Location | Lines | Commented % | Verdict |
|---|---|---:|---:|---|
| `smart_money_engine.py` | `services/trading-engine/src/engines/` | 785 | 98% | Damaged shell -- DELETE |
| `execution_engine.py` | `services/trading-engine/src/engines/` | 944 | 5% | **Real code -- KEEP for now, audit later** |
| `smart_money_engine/core.py` | `core_trading/engines/` | 433 | 99% | Damaged shell -- ARCHIVE |
| `enhanced_smart_money_engine.py` | `core_trading/engines/` | 1545 | 99% | Damaged shell -- ARCHIVE |
| `ai_enhanced_signal_engine.py` | `core_trading/engines/` | 1379 | 99% | Damaged shell -- ARCHIVE (replaced by Phase 5 `signals/ml/`) |
| `parallel_processing_engine.py` | `core_trading/engines/` | 643 | 95% | Damaged shell -- ARCHIVE |
| `portfolio_engine.py` | `core_trading/engines/` | 970 | 97% | Damaged shell -- ARCHIVE (replaced by Phase 6 `portfolio/`) |
| `smart_money_performance_optimizer.py` | `core_trading/engines/` | 789 | 98% | Damaged shell -- ARCHIVE (premature optimisation) |
| `strategy_engine.py` | `core_trading/engines/` | 476 | 94% | Damaged shell -- ARCHIVE, rewrite as runtime orchestrator |

## Recommendations

### A. `services/` is for deployment, `core_trading/` is the library

Resolve the duplication once and for all with the rule:

- **`core_trading/`** is the canonical Python library. All trading logic
  (signals, portfolio, risk, money, execution, backtest) lives here.
- **`services/`** wraps `core_trading/` modules in deployable microservices
  (FastAPI HTTP, Kafka consumers, Prometheus exporters). Services contain
  glue code -- not domain logic.

Any future PR that puts domain logic inside `services/` instead of importing
from `core_trading/` should fail review.

### B. Smart Money Engine

Both the `services/` and `core_trading/` copies are damaged. There is no
"working version to merge from." The path forward:

1. **ARCHIVE both** to `.archive/2026-05-28_remediation/engines/` (preserving
   the commented-out source as a reference for future rewrite).
2. **REWRITE** as `core_trading/signals/smart_money/` per Phase 5 plan
   (a clean signal module, not a "smart money engine" superclass).
3. **Service-level integration** (if needed) becomes a thin FastAPI wrapper at
   `services/trading-engine/src/engines/smart_money_service.py` that imports
   from `core_trading/signals/smart_money/`.

### C. Execution Engine (the one real-code file)

`services/trading-engine/src/engines/execution_engine.py` is 944 lines of
**actual implementation** (only 5% commented). This violates the "services/ is
glue only" rule, but it is the only working execution path in the repo right now.

Recommendation:

1. **Keep as-is for the moment** -- do not break the only working execution
   layer while remediation is ongoing.
2. **Audit it in detail during Phase 9** (Execution Layer Extension). At that
   point, port the bulk of its logic into `core_trading/execution/` modules
   and leave only the FastAPI/Kafka wiring at the service level.
3. **Until then, mark it as a known architectural debt** in `ADRs/` so future
   readers understand the inversion.

### D. All other engines

Archive all of: `enhanced_smart_money_engine.py`, `ai_enhanced_signal_engine.py`,
`parallel_processing_engine.py`, `portfolio_engine.py`,
`smart_money_performance_optimizer.py`, `strategy_engine.py`.

Each gets a one-line rationale.md in the archive describing why and which Phase
will produce the replacement.

## What was done this session

1. Wrote `tools/check_no_stubs.py` and wired it into `.pre-commit-config.yaml`
   as the `no-stubs` local hook.
2. Established the 536-violation baseline (saved at
   `.archive/2026-05-28_remediation/no_stubs_baseline.txt`).
3. Archived 226 cruft files (`.fixed_attempt` + `.backup`) into
   `.archive/2026-05-28_remediation/cruft/`. Baseline dropped to **310
   violations**.
4. Updated `pyproject.toml`:
   - Python pin: `^3.11` -> `^3.12`
   - Added ~40 quant dependencies (statsmodels, arch, hmmlearn, filterpy,
     cvxpy, PyPortfolioOpt, scikit-learn, xgboost, lightgbm, polars, mlflow,
     jupyterlab, etc. -- full list per Phase 0.3)
   - Added ruff configuration
   - Updated black/mypy targets to `py312`
   - Added `hypothesis` for property-based testing
5. Wrote this memo documenting recommendations for the engines duplication
   (no code-level deletion performed; deletion requires explicit sign-off).

## Pending user actions

These items in Week 1 (§11 of master plan) require user input or environment
changes that cannot be performed inside this session:

| Item | Reason | Effort |
|---|---|---|
| Install Python 3.12 | System-level change | 30 min |
| `poetry install` from updated `pyproject.toml` | Requires Python 3.12 in venv | 15 min once 3.12 is installed |
| Pick fundamental-data vendor (Sharadar / SimFin / EDGAR) | Cost/scope decision | -- |
| Approve engines deletion plan (recommendations above) | Risk of breaking working execution path | -- |
| Audit existing IBKR adapter end-to-end with one paper trade | Needs IBKR account credentials | 2 hours |

## Current Phase 0.5 violation status

| Stage | Total violations |
|---|---:|
| Pre-remediation baseline | 536 |
| After cruft archival (this session) | 310 |
| Target by end of Phase 0.5 | 0 (excluding documented broker-roadmap exception) |

## Next steps

Once user confirms direction, the next high-leverage autonomous work items are:

1. **Rewrite `libs/common/errors/exceptions.py`** to address the 21 TODO markers
   and produce a clean exception hierarchy. (~6 hours)
2. **Rewrite `libs/common/events/serializers.py`** to remove the 2
   `NotImplementedError` raises and address 5 TODOs. (~4 hours)
3. **Begin Phase 0.5 Category A** -- rewrite the pillar architecture
   (`core_trading/strategies/architecture/pillars/*.py`). This is foundational
   for everything else; ~200 hours total. Start with `core.py` (defines the
   `Pillar` and `PillarScores` interfaces). (~16 hours for `core.py` alone)
4. **Archive the damaged engines** per recommendations above. (~2 hours)

All four items can proceed without user input; user sign-off on item 4
(archiving) is the only gating decision.
