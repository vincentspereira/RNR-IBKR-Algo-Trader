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
| Damaged `strategies/backtesting/` (13 modules) | 13 | Archived NOT_WORTH literal rewrite (`.archive/2026-05-29_backtesting/`) — **rewritten** into `core_trading/backtest/` Phase 3 (209 tests, ~100% cov, mypy strict); metric set preserved |
| Legacy strategy skeletons (execution/utils/pairs/arbitrage/ML/advanced-technical/classical) + 10 orphaned tests | 68 | Archived 2026-06-05 (`.archive/2026-06-05_strategy_retirement/`) — replacement phases 4/5/7/8/9 ALL shipped; see "Strategy retirement sweep" section below |

## Remaining damaged files (91) — phase-deferred rewrites

These stay in the active tree until their phase rewrites them clean (per
ARCHIVING_POLICY "phase-deferred rewrites: left in place until their phase").
They are 80–99% commented skeletons with no working logic; rewriting them now —
before the Phase 2 feature store and Phase 3 backtest engine exist — would
produce untested code, violating the tested-end-to-end principle. The archived/
commented source is the logic reference for each rewrite.

### → Phase 3 (Backtest Engine v2) — 11 files — DONE (2026-05-29)
`strategies/backtesting/` : `__init__`, `backtest_engine`, `config`, `core`,
`integration`, `metrics`, `performance_analyzer`, `portfolio_simulator`,
`report_generator`, `risk_analyzer`, `visualization` (+ `data_manager`, `results`)
**Replacement home:** `core_trading/backtest/` (new, per Appendix A). **DONE** —
rewritten and archived to `.archive/2026-05-29_backtesting/`. See master plan
Phase 3 DOD (all items checked).

### → Phase 4 (Pairs-trading pilot) — 10 files — DONE (2026-06-05)
`strategies/pair_trading/` : `__init__`, `convergence_strategy`,
`correlation_analysis`, `divergence_strategy`,
`institutional_pairs_trading_strategy`, `pair_selection`, `pairs_strategies`,
`pairs_trading_strategies`, `performance_analytics`, `risk_management`
**Replacement home:** Phase 4 pairs vertical, shipped as
`core_trading/strategies/pairs_trading.py` (116 tests). **DONE** — whole dir
archived to `.archive/2026-06-05_strategy_retirement/core_trading/strategies/pair_trading/`.

### → Phase 5 (Signal library) — PARTIALLY DONE (2026-06-05)
Phase 5 signal library has shipped (~1500 tests). The superseded/weak-evidence
skeletons were archived 2026-06-05 to
`.archive/2026-06-05_strategy_retirement/`; unique-logic files were KEPT in the
active tree for later clean extraction.
- `strategies/arbitrage/` : `arbitrage_strategies`, `multi_factor_models` + root
  `arbitrage.py` → **ARCHIVED** (superseded by Phase 5 stat-arb).
  **KEPT for extraction:** `index_arbitrage.py`, `volatility_arbitrage.py`.
- `strategies/multi_factor/` : `multi_factor_models` → **ARCHIVED**.
  **KEPT for extraction:** `optimized_multi_factor_models.py`.
- `strategies/regime_based/regime_aware_adaptive_strategies` → **ARCHIVED** (dir removed).
- `strategies/scalping/news_based_scalping_strategy` → **ARCHIVED** (news feed out of data scope).
  **KEPT for extraction:** `scalping_strategy`, `order_flow_scalping_strategy`,
  `high_frequency_scalping_strategy`, `statistical_arbitrage_scalping_strategy`.
- `strategies/machine_learning/` : `ml_trading_strategies`, `supervised_strategies`,
  `model_manager` + root `ml_strategies.py` → **ARCHIVED**.
  **KEPT for extraction:** `feature_engineering`, `reinforcement_learning`
  (+ working `clustering_strategies`, `rl_strategy`).
- `strategies/advanced_technical/` (whole dir: harmonic, geometric, elliott,
  fibonacci, gann, `__init__`) → **ARCHIVED** weak-evidence per §6.1 (dropped, not rewritten).
- Classical: `volatility_breakout/{range_breakout,atr_breakout,donchian_breakout,bollinger_squeeze,core,__init__→stub}`,
  `volume_weighted/{vw_multi_factor,vw_breakout,vw_momentum,base_vw,__init__→stub}`,
  `breakout/` (whole), `seasonal/` (whole), `multi_asset/` (whole),
  `risk_adaptive_strategies.py` → **ARCHIVED** per plan C.2.
  **KEPT as rewrite-reference SOURCES (until chosen classical rewrites land):**
  `volatility_breakout/{volatility_breakout_strategy, volatility_expansion_strategies}`,
  `volume_weighted/{vw_trend_following_strategies, vw_mean_reversion_strategies}`.
- `strategies/tests/test_integration.py`, `tests/unit/test_quant.py` → still in tree (not part of this sweep).

### → Phase 7/8/9 (Risk / Money / Execution) — DONE (2026-06-05)
Phases 7 (risk), 8 (money), 9 (execution) have ALL shipped. The legacy skeletons
were archived 2026-06-05 to `.archive/2026-06-05_strategy_retirement/`.
- `strategies/execution/` (9, whole dir): `position_sizing`, `stop_loss_strategies`,
  `execution_optimization`, `execution_intent_utils`, `__init__`, `backtesting/`,
  `live_trading/`, `validation/` → **ARCHIVED** (superseded by `core_trading/execution/`
  + `core_trading/money/`).
- `strategies/utils/` : `risk_utils`, `risk_management_utils`, `performance_tracker`,
  `common_functions`, `strategy_utilities`, `technical_utils`, `logging_config`
  → **ARCHIVED** (superseded by `core_trading/risk/`, `core_trading/money/`, ops attribution).
  **KEPT for extraction:** `risk_management_enhancements`, `signal_processing`,
  `portfolio_level_features`. (`utils/` has no `__init__.py`; nothing to stub.)

### → Phase 4/5 (examples) — 3 files — DONE (2026-06-05)
`strategies/examples/` (`nautilus_integration_example`, `rsi2_backtest_example`),
`strategies/integration/brokers/ib_trading_strategy.py` → **ARCHIVED** 2026-06-05
(dirs removed). Canonical worked examples to be rebuilt per pattern post-Phase 4.

---

## Strategy retirement sweep — 2026-06-05

**Archive path:** `.archive/2026-06-05_strategy_retirement/` (gitignored; mirrors
original subpaths). Rationale: `.archive/2026-06-05_strategy_retirement/README.rationale.md`.

**Trigger:** Replacement phases 4/5/7/8/9 have ALL shipped, so the phase-deferred
skeletons catalogued above are now genuinely superseded and were archived.

**Archived: 58 source modules + 10 orphaned legacy tests = 68 files.**

**Orphaned tests archived** (imported now-archived modules; would ImportError at
collection): `tests/strategies/`
`test_advanced_technical` (25), `test_arbitrage` (17), `test_execution` (18),
`test_ml_strategies` (54), `test_multi_factor` (8), `test_pair_trading` (25),
`test_regime` (15), `test_scalping` (15), `test_volatility_breakout` (13),
`test_volume_weighted` (14) = 204 tests removed. The shared
`tests/strategies/conftest.py` was RETAINED (remaining tests — momentum,
mean_reversion, technical_indicators, augmented_base, backtesting — still need it).

**Retained-package `__init__.py` rewritten to honest stubs** (dir not emptied):
`arbitrage/`, `machine_learning/`, `volatility_breakout/`, `volume_weighted/`.

**KEEP-for-extraction** (unique logic, left in active tree): see Phase 5 / 7/8/9
sections above and the rationale file.

**Rewrite-reference SOURCES** (kept until classical rewrites land):
`volatility_breakout/{volatility_breakout_strategy, volatility_expansion_strategies}`,
`volume_weighted/{vw_trend_following_strategies, vw_mean_reversion_strategies}`.

**Safety:** No active-tree file (core_trading non-strategy, services, libs, tools,
tests excl. tests/strategies) imported any archived module — verified by grep
before removal. `import core_trading.strategies` still succeeds. No files were
refused. No-stubs violations dropped 135 → 28.

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
