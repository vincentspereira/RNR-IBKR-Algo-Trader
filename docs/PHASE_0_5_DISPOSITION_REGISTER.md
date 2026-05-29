# Phase 0.5 Disposition Register

**Date:** 2026-05-29
**Authority:** `docs/ARCHIVING_POLICY.md`
**Purpose:** Document the disposition of every damaged file found in the
repo-wide audit, so none is silently ignored. Per the archiving policy, a
damaged file is either (a) rewritten-then-archived, (b) archived as
NOT_WORTH_REWRITING, or (c) **left in place pending rewrite in its target
phase** (phase-deferred). This register tracks category (c) — the files that
remain in the active tree on purpose.

---

## Completed this session (archived or rewritten)

| Item | Count | Disposition |
|---|---:|---|
| `.fixed_attempt` / `.backup` cruft | 226 | Archived (`.archive/2026-05-28_remediation/cruft/`) |
| Damaged engines (smart-money, ai-signal, portfolio, etc.) | 10 | Archived; rewrite refs for Phases 5/6 |
| Misplaced pillar extracts | 6 | Archived; canonical pillars already exist |
| `libs/common/events/serializers.py` | 1 | **Rewritten** (working Avro impl, tested) |
| Damaged `data_feeds/` (7 modules + 3 tests) | 10 | Archived NOT_WORTH_REWRITING — **rewritten** into `core_trading/data/` (160 tests, 98% cov) |
| `engines/multi_timeframe_engine/` | 3 | Archived NOT_WORTH_REWRITING (rebuild in Phase 2 feature store) |
| `adapters/fix_client.py` | 1 | Archived NOT_WORTH_REWRITING (IBKR uses native API) |

## Remaining damaged files (91) — phase-deferred rewrites

These stay in the active tree until their phase rewrites them clean (per
ARCHIVING_POLICY "phase-deferred rewrites: left in place until their phase").
They are 80–99% commented skeletons with no working logic; rewriting them now —
before the Phase 2 feature store and Phase 3 backtest engine exist — would
produce untested code, violating the tested-end-to-end principle. The archived/
commented source is the logic reference for each rewrite.

### → Phase 3 (Backtest Engine v2) — 11 files
`strategies/backtesting/` : `__init__`, `backtest_engine`, `config`, `core`,
`integration`, `metrics`, `performance_analyzer`, `portfolio_simulator`,
`report_generator`, `risk_analyzer`, `visualization`
**Replacement home:** `core_trading/backtest/` (new, per Appendix A).

### → Phase 4 (Pairs-trading pilot) — 10 files
`strategies/pair_trading/` : `__init__`, `convergence_strategy`,
`correlation_analysis`, `divergence_strategy`,
`institutional_pairs_trading_strategy`, `pair_selection`, `pairs_strategies`,
`pairs_trading_strategies`, `performance_analytics`, `risk_management`
**Replacement home:** `core_trading/signals/pairs/` + `core_trading/strategies/pairs_trading_v2.py`.
**Note:** `pair_selection.py` flagged REWRITE by audit — it is the first file
rebuilt in Phase 4.

### → Phase 5 (Signal library) — 49 files
- `strategies/arbitrage/` (5) + `arbitrage.py` → `signals/` stat-arb
- `strategies/multi_factor/` (2) → `signals/factors/`
- `strategies/regime_based/` (1) → `signals/regimes/hmm.py`
- `strategies/scalping/` (5) → `signals/microstructure/`
- `strategies/machine_learning/` (6) + `ml_strategies.py` → `signals/ml/`
- `strategies/advanced_technical/` (6): harmonic/geometric → `signals/`; elliott/fibonacci/gann are weak-evidence (see §6.1) and may be dropped
- `strategies/volatility_breakout/` (8), `volume_weighted/` (7), `breakout/` (1),
  `seasonal/` (1), `multi_asset/` (1), `risk_adaptive_strategies.py` (1) →
  `strategies/classical/` (rewrite 5–8 representatives, archive rest per plan C.2)
- `strategies/tests/test_integration.py`, `tests/unit/test_quant.py` → rebuilt with their modules

### → Phase 7/8/9 (Risk / Money / Execution) — 19 files
- `strategies/execution/` (9): `position_sizing`, `stop_loss_strategies`,
  `execution_optimization`, `execution_intent_utils`, `backtesting/`,
  `live_trading/`, `validation/` → `core_trading/money/` + `core_trading/execution/`
- `strategies/utils/` (10): `risk_utils`, `risk_management_utils`,
  `risk_management_enhancements` → `core_trading/risk/`;
  `portfolio_level_features` → Phase 2 feature store;
  `technical_utils`, `signal_processing` → `signals/`;
  `performance_tracker` → `ops/attribution`; `common_functions`,
  `strategy_utilities`, `logging_config` → consolidate/drop

### → Phase 4/5 (examples) — 3 files
`strategies/examples/` (2), `strategies/integration/brokers/ib_trading_strategy.py`
→ one canonical worked example per pattern, rebuilt after Phase 4 ships.

---

## Status summary

| Phase | Status |
|---|---|
| **Phase 0 — Foundation** | ✅ COMPLETE (Python 3.12, deps, single requirements source, notebooks, MLflow/seed, CI gates) |
| **Phase 0.5 — Remediation** | ✅ Structurally complete: all cruft, engines, pillars, data_feeds, fix_client handled. 91 strategy files are **phase-deferred rewrites** (this register), per policy. |
| **Phase 1 — Data** | ✅ COMPLETE (universe, bars, corporate actions, fundamentals, macro, quality, storage, reference, sources: yfinance/IBKR/FRED/EDGAR; 160 tests @ 98% cov) |
| **Phase 2 — Research Framework** | ✅ COMPLETE 2026-05-29 (feature store [63 features], stat-test toolkit, purged/CPCV/walk-forward CV, Deflated Sharpe/PBO/reality-check/SPA + OOS lockbox, 9 notebook templates; 172 tests @ 99% cov, 0 warnings/0 skips) |

The full-repo no-stubs hook still reports ~177 violations; these are exactly the
91 phase-deferred strategy files (and their markers) catalogued above. The CI
**quant-layer gate** scopes the strict no-stubs + 90%-coverage + zero-warning
checks to the completed layers (`core_trading/data`, `core_trading/research`),
which are green. As each future phase rewrites its files, this register and the
violation count shrink to zero.
