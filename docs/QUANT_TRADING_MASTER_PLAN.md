# Quantitative Trading System — Master Implementation Plan

**Author:** Vincent S. Pereira
**Date:** 2026-05-27
**Repo:** IBKR Algo Trader (personal use)
**Status:** Planning — supersedes prior strategy-roadmap fragments
**Scope:** Convert the current paper-trading skeleton into a genuinely quantitative system covering data, research, signal generation, portfolio construction, risk, money management, execution, backtesting, paper trading, and live trading.

---

## 0. Executive Summary

### Objective

Build a quantitative trading system that operates the way institutional quant desks and quantitative hedge funds operate: evidence-driven, statistically rigorous, risk-first, and multi-strategy. The system should be able to research new signals, validate them with statistical robustness, paper-trade them under realistic conditions, and graduate winners into small-capital live trading with continuous monitoring.

### Production-Readiness Commitment (binding)

This plan is **not a roadmap of partial milestones**. The terminal deliverable is a system that is **complete in all aspects and production-ready** such that:

1. **The moment the build completes, paper trading begins.** No additional "finishing work," no "we'll come back to this later," no half-implemented modules in the runtime path. Paper trading is the immediate next action after the final integration test passes.
2. **Live trading begins immediately after the paper trading promotion criteria are met** (§11.3). The system is already production-ready; the paper-to-live transition is a capital-allocation decision, not a code-completion decision.
3. **Every component required for production trading is fully implemented before any code is merged.** Data ingestion, signal generation, portfolio construction, risk management, money management, execution, monitoring, alerting, reconciliation, kill switches, audit trails, runbooks — all present, all tested, all proven in integration.
4. **No commented-out code, no stubs, no placeholders, no "TODO: implement later" anywhere in the trading path.** See §10 No-Stubs Policy.
5. **Operational dependencies exist on day 1 of paper trading**, not bolted on later: monitoring dashboards live, alerts wired to a real channel (email/SMS/Slack), daily ops checklist defined and rehearsed, broker reconciliation working, tax-lot accounting in place, disaster recovery tested.

The plan's phases are **build sequence**, not a list of "phases that may or may not happen." Every phase ships to a production-ready bar. The paper-trading and live-trading phases (11 and 12) are not "if we get there" — they are the deliverable.

If something is in scope per this plan, it ships at production quality before paper trading begins. If something is not needed for production trading, it is explicitly marked deferred (the only example: certain broker adapters per §10.2). There is no middle ground.

### Honest Current State (Reality Check)

Before committing to a plan, a sober audit of what actually exists:

| Module                                                            | Reported State (per dir tree)      | Actual State (per inspection)                                                                                                        |
| ----------------------------------------------------------------- | ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `regime_aware_adaptive_strategies.py` (1466 lines)                | "HMM regime detection implemented" | **82% commented out** — file parses because lines are `#`-prefixed; no working HMM                                                   |
| `pairs_trading_strategies.py` (1028 lines)                        | "Cointegration pairs implemented"  | **85% commented out** — has a `.fixed_attempt` sibling, confirming prior failed repair                                               |
| `institutional_pairs_trading_strategy.py` (1289 lines)            | "Institutional pairs strategy"     | **79% commented out**                                                                                                                |
| `arbitrage/multi_factor_models.py` (1079 lines)                   | "Multi-factor models"              | **85% commented out**                                                                                                                |
| `multi_factor/multi_factor_models.py` (1610 lines)                | "Optimized multi-factor"           | **80% commented out**                                                                                                                |
| `machine_learning/reinforcement_learning.py` (1064 lines)         | "RL strategies"                    | **77% commented out**                                                                                                                |
| `machine_learning/feature_engineering.py` (1142 lines)            | "Feature engineering"              | **84% commented out**                                                                                                                |
| `arbitrage/volatility_arbitrage.py` (881 lines)                   | "Vol arb"                          | **85% commented out**                                                                                                                |
| `scalping/statistical_arbitrage_scalping_strategy.py` (963 lines) | "Stat arb scalping"                | **80% commented out**                                                                                                                |
| `machine_learning/supervised_strategies.py`                       | "Supervised ML strategies"         | **57 lines, 63% commented** — effectively empty                                                                                      |
| `engines/portfolio_engine.py`                                     | "Portfolio engine"                 | Has `.fixed_attempt` sibling — damaged                                                                                               |
| `pyproject.toml` quant libraries                                  | implied present                    | **None pinned** — no `statsmodels`, `arch`, `hmmlearn`, `cvxpy`, `PyPortfolioOpt`, `scikit-learn`, `xgboost`, `lightgbm`, `filterpy` |
| Top-level `risk/`, `portfolio/`, `research/` packages             | implied present                    | **Do not exist** — risk/portfolio logic is scattered across `services/risk-manager`, `strategies/utils`, and `engines/`              |
| Python version                                                    | `^3.11` in pyproject               | System has 3.14 (too new) and 3.12 not installed (per session memory)                                                                |

### Verdict

The quant layer **does not really exist**. What exists is a directory of named files containing mostly commented-out code, alongside a paper-trading and broker-adapter skeleton that is largely functional. The right framing for this plan is therefore not "extend the quant system" but **"build the quant system, using the existing file names as a structural inventory of what the original design intended."**

**Wider audit:** The damage is not confined to the quant subdirectories. A repo-wide scan found:

- **123 Python files ≥50% commented** in the active tree (most at 97–99%), totaling **80,244 lines** of effectively dead code
- **188 `.fixed_attempt` files** outside `.archive/` (cruft from prior repair attempts)
- **38 `.backup` files** outside `.archive/`
- **55+ files** with `TODO`/`FIXME`/`STUB`/`placeholder` markers
- Significant duplication between `core_trading/engines/` and `services/trading-engine/src/engines/` — same code, two locations

The damage spans: strategy implementations (99 files), engines (12 files), data feeds (10 files), and parts of services and libs. This warrants a dedicated remediation phase (**Phase 0.5**, below) running in parallel with the quant build.

### Strategic Approach

1. **Rewrite-from-scratch as default policy.** Per the user's global CLAUDE.md, files that are >50% commented or have `.fixed_attempt` siblings should be rewritten cleanly, not repaired. This applies repo-wide — not just quant files. Audit count: 123 files, ~80K lines (see Phase 0.5).
2. **No stubs, no placeholders, no `NotImplementedError` — REPO-WIDE.** Every function ships either with a working implementation or it does not ship at all. A directory of empty class definitions is worse than no directory. The single documented exception is broker adapters for brokers the operator does not currently trade (see Phase 0.5.E and §10.2 No-Stubs Policy).
3. **One vertical first, then horizontal expansion.** Phases 1–4 take pairs-trading end-to-end (data → signal → portfolio → risk → execution → paper → live monitoring) before broadening into the full signal library.
4. **Test-first for math.** Every statistical model gets unit tests against textbook examples *before* it touches production data.
5. **Personal-use scope.** Per session memory: this repo is personal. The MAS commercial product stays clean of AGPL/GPL code from here.
6. **Repo-wide remediation is parallel work, not a blocker.** Phase 0.5 begins in Week 1 alongside Phase 0 and runs in parallel with Phases 1–5. Live trading does not begin until Phase 0.5 DOD is met.

### Realistic Timeline

For one engineer working part-to-full-time:

- **Phase 0 (Foundation):** 1–2 weeks
- **Phase 0.5 (Repo-wide remediation):** 6–10 weeks running in parallel; ~856 engineering hours
- **Phase 1 (Data):** 4–8 weeks
- **Phase 2–3 (Research framework + Backtest engine):** 6–8 weeks
- **Phase 4 (Pilot pairs-trading vertical, end-to-end paper):** 4–6 weeks
- **Phases 5–9 (Full signal library, portfolio, risk, money, execution):** 8–12 months
- **Phase 10 (Continuous testing):** ongoing, never "complete"
- **Phase 11 (Paper trading per strategy):** minimum 90 calendar days
- **Phase 12 (Live trading with small capital):** 6+ months before scaling

**Honest end-to-end:** 18–24 months from today to "trading multiple uncorrelated quantitative strategies with risk-managed leverage." Anything faster compromises one of: code quality, statistical rigor, paper-validation period, or risk controls.

### Profitability Disclosure

The plan is designed to **maximize the probability** of profitability, not guarantee it. Even institutional quant funds with millions of dollars of research budget have failure rates of 50%+ on new strategies. Median retail quant strategies are unprofitable after costs. This document optimizes for: (a) not losing money to overfitting, (b) catching strategy decay early, (c) sizing positions so survival precedes profit. If you internalize one principle from this plan, it is: **risk management is what makes quant trading work, not signal quality.**

---

## 1. Foundational Principles

### How quant funds actually think

1. **Evidence beats opinion.** Every claim — "this signal predicts returns," "this filter improves Sharpe" — is a hypothesis tested against out-of-sample data with statistical rigor.
2. **Risk management precedes alpha generation.** The first question is not "how do I make money?" but "how do I not lose money?" Position sizing, stop-loss logic, and portfolio limits matter more than signal quality.
3. **Multiple uncorrelated strategies beat one good one.** A portfolio of 10 strategies each with Sharpe 0.5 and correlation 0.2 beats one strategy with Sharpe 1.0 and correlation 1.0 to itself.
4. **Costs eat alpha for breakfast.** Slippage, commissions, market impact, financing costs, and taxes are the difference between a great backtest and a losing live strategy.
5. **Capacity matters.** A signal that works on $100K may not work on $10M. Liquidity, market impact, and crowding all constrain capacity.
6. **Backtest the way you trade.** If you cannot fill the exact orders the backtest assumes, the backtest is fiction.
7. **All models are wrong, some are useful.** Calibrate expectations: even the best model will have drawdowns. Plan for them.

### The Five Tortures of Backtesting (de Prado)

A backtest passes the five tortures only if:

1. It is **out-of-sample** (never trained or tuned on the test data)
2. It is **statistically robust** (Sharpe > 1.0 after deflating for selection bias)
3. It is **regime-invariant** (works across bull, bear, sideways, crisis periods)
4. It survives **realistic costs** (slippage, market impact, commissions, taxes)
5. It is **economically rational** (you can explain *why* it works in terms of market structure or behavioral inefficiency)

Any strategy that does not pass all five never goes live.

### Personal-use guardrails (your specific situation)

- Single-operator system; no team to monitor 24/7
- Use brokers (IBKR) with paper-trading infrastructure; never test on live first
- Conservative capital allocation; do not scale a strategy that has run < 90 days paper
- All trading logic is auditable: every order has a model attribution and a reason code
- Kill switch is non-negotiable: a single command pauses all activity

---

## 2. System Architecture

```
+----------------------------------------------------------+
|                    Research Layer                         |
|  (Jupyter notebooks, papermill pipelines, feature store)  |
+----------------------------------------------------------+
                          |
                          v
+----------------------------------------------------------+
|                  Signal Generation Layer                  |
|  (statistical models, ML models, microstructure signals)  |
+----------------------------------------------------------+
                          |
                          v
+----------------------------------------------------------+
|              Portfolio Construction Layer                 |
|   (allocator: MVO, Black-Litterman, HRP, Risk Parity)     |
+----------------------------------------------------------+
                          |
                          v
+----------------------------------------------------------+
|                   Risk Management Layer                   |
|  (pre-trade checks, VaR, CVaR, stress tests, limits)      |
+----------------------------------------------------------+
                          |
                          v
+----------------------------------------------------------+
|                     Execution Layer                       |
|     (TWAP/VWAP/IS/AC, smart router, broker adapters)      |
+----------------------------------------------------------+
                          |
                          v
+----------------------------------------------------------+
|                   Broker (IBKR, paper/live)               |
+----------------------------------------------------------+
                          ^
                          |
+----------------------------------------------------------+
|         Operations / Monitoring / Attribution             |
|  (PnL attribution, signal decay, Sharpe deflation, alerts)|
+----------------------------------------------------------+
```

### Layered Module Plan (new top-level packages)

The existing `core_trading/` directory is the right home. Proposed additions:

```
core_trading/
  data/                  # NEW — historical + live data lake
  research/              # NEW — notebook templates, feature store, stat tests
  signals/               # NEW — signal generation library (replaces parts of strategies/)
  portfolio/             # NEW — portfolio construction (replaces engines/portfolio_engine.py)
  risk/                  # NEW — risk models (VaR, GARCH, stress)
  money/                 # NEW — position sizing, Kelly, vol targeting
  execution/             # EXISTS — extend with IS, AC, TCA
  backtest/              # NEW — clean backtest engine (replaces strategies/backtesting/)
  strategies/            # EXISTS — refactored to use signals/ + portfolio/ + risk/
  adapters/              # EXISTS — broker adapters (IBKR canonical)
  ops/                   # NEW — monitoring, attribution, alerting hooks
```

All new modules ship with:

- 100% pure Python (no commented-out blocks)
- Type hints on all public functions
- Docstrings with mathematical references
- Unit tests with textbook validation
- Integration tests with synthetic and real data
- Performance benchmarks where latency matters

---

## 3. The Phased Plan

### Phase 0 — Foundation (PREREQUISITE)

**Duration:** 1–2 weeks
**Status:** must complete before any quant work

#### Objectives

Eliminate environmental drift, dependency disagreements, and missing libraries that would otherwise corrupt every downstream test.

#### Tasks

0.1 **Python version lock-in**

- Install Python 3.12 (current 3.14 is too new; per memory `project_python_deps_state.md`)
- Document in `README.md` and `pyproject.toml`
- Update `pyproject.toml`: `python = "^3.12"`

0.2 **Dependency reconciliation**

- Merge `pyproject.toml` and `requirements.txt` into a single source of truth (`pyproject.toml`)
- Generate locked `poetry.lock` and pin
- Verify against the resolved infra swaps from commit `dad70a9` (Neo4j→ArcadeDB, Redis→Valkey, etc.)

0.3 **Quant library additions** (currently *none* present)

```toml
# Statistics & econometrics
statsmodels = "^0.14"          # ADF, KPSS, cointegration, ARIMA, OLS, GLS
arch = "^7.0"                  # GARCH family, EGARCH, GJR-GARCH, HAR-RV
pingouin = "^0.5"              # robust statistical tests
hmmlearn = "^0.3"              # Hidden Markov Models
filterpy = "^1.4"              # Kalman filters, particle filters
linearmodels = "^6.0"          # Fama-MacBeth, panel regressions

# Optimisation
cvxpy = "^1.5"                 # convex optimisation (MVO, HRP, robust opt)
PyPortfolioOpt = "^1.5"        # higher-level portfolio optimisation
scipy = "^1.13"

# Machine learning
scikit-learn = "^1.5"
xgboost = "^2.1"
lightgbm = "^4.5"
catboost = "^1.2"
torch = "^2.4"                 # if deep learning
pytorch-lightning = "^2.4"

# Reinforcement learning
stable-baselines3 = "^2.3"     # baseline RL algorithms
gymnasium = "^0.29"            # standard env API
finrl = "^0.3"                 # finance-RL framework (already referenced)

# Time series & feature engineering
ta-lib = "^0.4"                # technical indicators (C-backed, fast)
pandas-ta = "^0.3"             # pure-Python TA
tsfresh = "^0.20"              # automated time-series feature extraction
featuretools = "^1.31"

# NLP / alternative data
transformers = "^4.43"
sentence-transformers = "^3.0"
finbert = "*"                  # pretrained sentiment for finance

# Backtesting helpers (not the engine — we write our own)
vectorbt = "^0.26"             # vectorised research
empyrical = "^0.5"             # performance metrics
quantstats = "^0.0.62"

# Data utilities
arctic = "*"                   # high-performance time-series store (optional)
polars = "^1.5"                # fast DataFrame for large data
pyarrow = "^16.0"
```

0.4 **Research environment**

- Jupyter Lab + nbstripout pre-commit hook (strips outputs to keep diffs clean)
- Papermill for parameterised notebook execution
- `notebooks/research/` directory structure: `00_data_exploration/`, `01_feature_research/`, `02_signal_research/`, `03_portfolio_research/`, `04_risk_research/`

0.5 **Reproducibility infrastructure**

- Global random seed config
- Experiment tracking (MLflow or DVC) — every backtest gets a hash-tagged run
- Pinned dependency hashes in lockfile

0.6 **Continuous integration upgrade**

- `pytest` runs on every commit
- `mypy --strict` on all new code
- `ruff` for lint
- Coverage gate: 95% on new code

#### Definition of Done — Phase 0

- [ ] `python --version` reports 3.12.x on dev machine
- [ ] `poetry install` succeeds from a clean clone
- [ ] All quant libraries import in a fresh venv
- [ ] CI pipeline green on a "hello world" quant notebook
- [ ] No `.fixed_attempt` files left in the repo (delete or archive)

---

### Phase 0.5 — Repo-Wide Code Remediation (Cleanup of Damaged Code)

**Duration:** 6–10 weeks (can overlap with Phase 1 once triaged)
**Status:** PREREQUISITE for production trust; blocks live trading

The audit performed at planning time discovered the damage is not confined to quant code. The active tree contains:

- **80,244 lines of Python that are ≥50% commented out** across 123 files
- **188 `.fixed_attempt` files** outside the archive directory
- **38 `.backup` files** outside the archive directory
- **55+ files** with TODO/FIXME/STUB/placeholder markers

This is the same damage pattern (failed automated uncommenting per global CLAUDE.md) that affected `position_sizing.py`, propagated to most of `core_trading/`. The user's directive — **no commented code, no placeholders, no stubs anywhere in the system** — requires a structured remediation effort across the whole repo, not just the quant layer.

#### 0.5.0 Inventory and triage matrix

The audit produced this breakdown by directory:

| Area                       | Damaged Files | Damaged Lines | Strategy                                                                                  |
| -------------------------- | -------------:| -------------:| ----------------------------------------------------------------------------------------- |
| `core_trading/strategies/` | 99            | 66,007        | Mostly rewrite-from-scratch (architecture pillars, individual strategies); some delete    |
| `core_trading/engines/`    | 12            | 8,209         | Rewrite or delete (smart_money_engine, ai_enhanced_signal_engine)                         |
| `core_trading/data_feeds/` | 10            | 5,155         | Rewrite cleanly as Phase 1 data layer; delete duplicates                                  |
| `services/trading-engine/` | 1             | 785           | Duplicate of `core_trading/engines/smart_money_engine/`; pick one canonical, delete other |
| `core_trading/adapters/`   | 1             | 88            | Cleanup as part of Phase 0                                                                |

**Cruft to remove:** 188 `.fixed_attempt` + 38 `.backup` files (in active tree, not archive) = 226 files. These bloat the repo and confuse code search tools.

#### 0.5.1 Triage decision matrix

Every damaged file goes through one of four decisions:

| Decision    | When                                                                                                                                                      | Action                                                                                                                                 |
| ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| **REWRITE** | File represents a real capability the system needs                                                                                                        | Read the commented code to understand intent; rewrite cleanly using the global CLAUDE.md rewrite-from-scratch pattern; ship with tests |
| **REPLACE** | A clean version is being built elsewhere in this plan (e.g., quant signals)                                                                               | Archive the damaged file; point downstream imports at the new module                                                                   |
| **DELETE**  | Capability is duplicated, abandoned, or never made sense                                                                                                  | Archive to `.archive/2026-05-27_remediation/` with a brief rationale; remove from active tree                                          |
| **MERGE**   | Two damaged files implement the same capability (e.g., `core_trading/engines/smart_money_engine/` vs `services/trading-engine/.../smart_money_engine.py`) | Pick the canonical home; merge any unique logic; archive the loser                                                                     |

Per the global CLAUDE.md decision tree (≥500 lines + 3+ issue types ⇒ rewrite), every file in the 97–99%-commented bucket meets the rewrite threshold.

#### 0.5.2 Category-by-category remediation plan

##### Category A: Strategy "Architecture Pillars" (`core_trading/strategies/architecture/pillars/`)

These are intended as the abstract base layer that every strategy uses (signal generation, risk management, execution intent, performance analytics). They are all 97–99% commented out (`execution_intent.py` 3095 lines, `signal_generation.py` 1747 lines, `risk_management.py` 1800 lines). The graphify community report ("Augmented Institutional Strategy", "PillarScores", "PillarCoordinator") confirms this is intended as a core abstraction.

**Decision:** REWRITE — this is foundational. Replace with clean implementations:

- `pillars/signal_generation.py` → becomes the base for everything in `signals/` (Phase 5)
- `pillars/risk_management.py` → becomes the base for everything in `risk/` (Phase 7)
- `pillars/execution_intent.py` → becomes the base for everything in `execution/algorithms/` (Phase 9)
- `pillars/performance_analytics.py` → becomes the base for `ops/attribution.py` (Phase 12)
- `pillars/core.py` → defines the `Pillar` and `PillarScores` interface
- `coordinator/pillar_coordinator.py` → orchestrates pillars per strategy

Effort: ~200 hours. Outputs are reusable across all phases that follow.

##### Category B: Smart Money / Signal Engines (`core_trading/engines/`)

- `engines/smart_money_engine/core.py` (433 lines, 99% commented)
- `engines/enhanced_smart_money_engine.py` (1545 lines, 99% commented)
- `engines/ai_enhanced_signal_engine.py` (1379 lines, 99% commented)
- `engines/smart_money_performance_optimizer.py` (991 lines, 98% commented)
- `engines/multi_timeframe_engine/` (engines for multi-timeframe aggregation)
- `engines/portfolio_engine.py` (has `.fixed_attempt`)
- `engines/strategy_engine.py` (4 TODO markers, otherwise OK)
- `services/trading-engine/src/engines/smart_money_engine.py` (785 lines, 98% commented — **duplicate** of `core_trading/engines/smart_money_engine/`)

**Decision:**

- `smart_money_engine/core.py` + `enhanced_smart_money_engine.py` → **MERGE into one canonical** `signals/smart_money/engine.py` that lives in the Phase 5 signal library structure. Smart money concepts (institutional order flow, dark pool activity, accumulation/distribution) become specific signal modules.
- `services/trading-engine/.../smart_money_engine.py` → **DELETE** (duplicate; the canonical version lives in `core_trading/`)
- `ai_enhanced_signal_engine.py` → **REPLACE** with the Phase 5 ML signal library (`signals/ml/`)
- `smart_money_performance_optimizer.py` → **DELETE** (premature optimisation of code that doesn't work yet; revisit when the canonical engine is profiled)
- `portfolio_engine.py` → **REWRITE** as `portfolio/portfolio.py` (Phase 6 home)
- `strategy_engine.py` → **REWRITE** addressing the 4 TODO markers; becomes the runtime that coordinates pillar execution
- `multi_timeframe_engine/` → review during Phase 1 (data); may become part of the feature store

Effort: ~250 hours.

##### Category C: Strategy Implementations (`core_trading/strategies/*.py`)

The 99 damaged strategy files break into:

**C.1 — Quant strategies (covered by Phase 5)**

- pair_trading/ (all 11 files), arbitrage/, multi_factor/, regime_based/, scalping/, advanced_technical/

**Decision:** REPLACE — These are already in the Phase 5 plan as new clean `signals/`/`strategies/` modules. Archive the damaged originals once the clean versions are in place. **Read the commented-out code first** to extract any non-obvious logic before archiving.

**C.2 — Conventional technical strategies (not in Phase 5)**

- `volatility_breakout/` (7 files, ~6500 lines combined): atr_breakout, bollinger_squeeze, donchian_breakout, range_breakout, volatility_expansion
- `breakout/bollinger_band_breakout_strategy.py` (1003 lines)
- `mean_reversion/` (5 files): bollinger_bands_mean_reversion, connors_rsi_mean_reversion (and .backup siblings)
- `momentum/` (multiple files)
- `seasonal/turnaround_tuesday_strategy.py`
- `volume_weighted/` (6 files, ~4000 lines): vw_trend, vw_breakout, vw_momentum, vw_mean_reversion, vw_multi_factor

**Decision:** REWRITE selectively. Conventional technicals are not core to the quant plan (per §6.1 of this document, technicals are *features* in larger models, not standalone strategies). But for personal use and for backtest comparisons, having clean implementations is useful. Plan:

- Pick **5–8 representative strategies** worth keeping (e.g., ATR breakout, Donchian, Bollinger squeeze, classic momentum, classic mean reversion)
- REWRITE those cleanly under `strategies/classical/` using the rebuilt pillar architecture
- ARCHIVE the rest

Effort: ~150 hours for the rewrites; archival is fast.

**C.3 — Execution-related strategy modules**

- `execution/position_sizing.py` (740 lines, 98% commented) — note: this is the file used as the "rewrite-from-scratch" example in global CLAUDE.md; presumably it was rewritten once already, then re-damaged
- `execution/stop_loss_strategies.py` (892 lines)
- `execution/execution_optimization.py` (1446 lines)
- `execution/backtesting/backtesting_engine.py`
- `execution/live_trading/runtime_engine.py`
- `execution/live_trading/performance_monitor.py`
- `execution/validation/strategy_validator.py`

**Decision:** REPLACE with Phase 8 (money management) and Phase 9 (execution) clean modules. The 1446-line `execution_optimization.py` likely contains useful logic worth extracting before archival — read first.

**C.4 — Utilities and helpers**

- `strategies/utils/risk_utils.py`, `risk_management_utils.py`, `risk_management_enhancements.py` (three overlapping risk helpers — REWRITE into single `risk/` module)
- `strategies/utils/portfolio_level_features.py` (1218 lines, 98% commented) — REPLACE with Phase 2 feature store
- `strategies/utils/technical_utils.py` (514 lines, 98% commented) — REWRITE as `signals/technical/` library (clean implementations of RSI, MACD, ATR, Bollinger, etc. — used as features, not signals)
- `strategies/utils/signal_processing.py` — REWRITE as `signals/filters/signal_processing.py` (smoothing, denoising, decimation)
- `strategies/utils/strategy_utilities.py` — review; likely DELETE or merge into a single `strategies/base.py`
- `strategies/utils/performance_tracker.py` — REPLACE with `ops/attribution.py`
- `strategies/utils/common_functions.py` — review; likely DELETE
- `strategies/utils/logging_config.py` — DELETE (use shared logging from `libs/common/`)

Effort: ~120 hours.

**C.5 — Pillar architecture & coordinator**

- `strategies/architecture/coordinator/pillar_coordinator.py` — REWRITE as Phase 0.5.A's coordinator
- `strategies/architecture/pillars/*.py` — covered above in Category A

**C.6 — Backtesting (`strategies/backtesting/`)**

- `backtesting/backtest_engine.py`, `core.py`, `metrics.py`, `performance_analyzer.py`, `portfolio_simulator.py`, `report_generator.py`, `risk_analyzer.py`, `visualization.py`, `config.py`, `integration.py` — **all damaged**

**Decision:** REPLACE — this is Phase 3 (Backtest Engine v2). Archive damaged versions; the rewrite lives in `core_trading/backtest/` (new home).

**C.7 — Examples and templates**

- `strategies/examples/rsi2_backtest_example.py` (97% commented)
- `strategies/examples/nautilus_integration_example.py`
- `strategies/templates/blockly_strategy_template.py`
- `strategies/integration/brokers/ib_trading_strategy.py`

**Decision:** Examples should demonstrate working strategies. REWRITE one canonical example per pattern (one mean-reversion, one momentum, one pairs) after Phase 4 ships. Archive the damaged versions now.

##### Category D: Data Feeds (`core_trading/data_feeds/`)

10 damaged files, 5155 lines, with many `.fixed_attempt` and `.backup` siblings:

- `enhanced_multi_source_pipeline.py`
- `multi_source_feed_manager.py`
- `enhanced_data_integration.py` (95% commented, 6 TODO markers)
- `alternative_data_integration.py`
- `institutional_data_feed_manager.py`
- `pipeline_integration.py` (98% commented)
- `tests/test_enhanced_pipeline.py`, `tests/test_pipeline_core.py`

**Decision:** REPLACE — All of this is subsumed by Phase 1 (Data Infrastructure). Archive the damaged versions; new clean modules live in `core_trading/data/` (new home). Read the commented code to inventory which data sources were intended (Alpha Vantage, Yahoo, Binance, etc.) — that informs the Phase 1 source adapter list.

Effort: covered by Phase 1.

##### Category E: Broker Adapters (`core_trading/adapters/brokers/`)

Per session memory `project_broker_roadmap.md`: IBKR is canonical now; Alpaca/Coinbase have working `.backup` archives; 5 others (Binance, FXCM, OANDA, Trading212, Interactive Brokers shim) need rewrite.

The active files (`alpaca.py`, `binance.py`, `coinbase.py`, `fxcm.py`, `oanda.py`, `trading212.py`, `interactive_brokers.py`, `factory.py`, `websocket_streaming.py`) are currently honest **roadmap markers** per commit `7d47926` — not damaged code, but explicit placeholders that raise informative errors.

**Decision:** These are intentional roadmap markers, not damaged code. They violate the "no placeholders" directive though. Options:

1. **Strict interpretation:** every adapter must be fully implemented before merge. Implement them in order: Alpaca (restore from `.backup`), Coinbase (restore from `.backup`), Binance, OANDA, FXCM, Trading212. Effort: 60–100 hours each = 360–600 hours total.
2. **Pragmatic interpretation:** roadmap markers are not stubs in the misleading-code sense — they raise clear errors saying "not implemented; use IBKRAdapter". Keep them but rename `BrokerAdapter._raise_roadmap_marker()` for clarity, and document them as **deferred** in a `BROKER_ROADMAP.md` rather than as stubs in code.

**Recommended:** Pragmatic interpretation, because no personal-use user needs 7 broker adapters. **Document this exception explicitly** in this plan (see §10.2 No-Stubs Policy below). Adapters get implemented only when there's a concrete use case (e.g., "I want to trade crypto on Coinbase").

##### Category F: Services (`services/*/`)

The microservices directory mirrors the trading system but in service form. Per the audit:

- `services/trading-engine/src/engines/smart_money_engine.py` (98% commented) — **duplicate of `core_trading/engines/smart_money_engine/`**, **DELETE**
- `services/trading-engine/src/main.py` (4% commented) — clean, OK
- `services/ai-assistant/src/main.py` (9% commented, 2 TODO markers) — review TODOs, address
- `services/market-data/src/feed_handler.py` (17 lines) — stub of a real implementation; REWRITE
- `services/risk-manager/`, `services/backtesting-engine/`, `services/compliance/`, `services/dashboard/`, `services/notifications/` — needs per-file inspection

**Decision:**

- **Strategic question first:** are services/ and core_trading/ supposed to coexist long-term, or is one the future and the other the past? The duplication suggests architectural drift. Resolve before remediation: **canonicalise on `core_trading/` as the library; services wrap it for deployment**. Delete any service-level reimplementation that duplicates `core_trading/` capabilities.
- Per-service audit and TODO resolution: ~60 hours.

##### Category G: Common Libraries (`libs/common/`)

- `libs/common/errors/exceptions.py` (0% commented, 21 TODO markers) — has stub exceptions; REWRITE with full exception hierarchy and clear semantics
- `libs/common/events/serializers.py` (5% commented, 5 TODO markers) — address TODOs
- Other `libs/` directories (`core`, `database`, `fundamental`, `messaging`, `quant`, `testing`) — per-file audit

**Decision:** Audit and TODO-cleanup pass. Effort: ~40 hours.

##### Category H: Cruft removal

- 188 `.fixed_attempt` files in active tree → **DELETE** (archived versions already exist for anything important)
- 38 `.backup` files in active tree → **REVIEW each one**, keep the ones the broker-roadmap memory specifically references (Alpaca, Coinbase, Interactive Brokers .backup are working implementations that may be restored); archive the rest to `.archive/2026-05-27_remediation/`
- Empty `__init__.py` files with 98% comments → REWRITE as proper package init files

Effort: ~8 hours.

#### 0.5.3 Remediation workflow (per file)

For each REWRITE-classified file:

1. **Read the commented-out source** to understand intent
2. **Identify the canonical home** in the new module structure (signals/, portfolio/, risk/, etc.)
3. **Find downstream callers** via `grep` to understand the interface
4. **Write the clean implementation** with proper docstrings, type hints, mathematical references
5. **Write unit tests** that cover the textbook behaviour
6. **Update imports** in callers
7. **Archive the damaged original** to `.archive/2026-05-27_remediation/<original-path>/`
8. **Run integration tests** to confirm no regression
9. **Update graphify** (`graphify update .`) to refresh the knowledge graph

For each REPLACE-classified file, steps 1, 2, 7, 8, 9 only.

For each DELETE-classified file, steps 7, 9 only, with a one-line `rationale.md` next to the archived copy.

#### 0.5.4 Effort total

| Category                                  | Decision                        | Effort (hours) |
| ----------------------------------------- | ------------------------------- | --------------:|
| A — Pillar architecture                   | REWRITE                         | 200            |
| B — Engines                               | REWRITE/MERGE/DELETE            | 250            |
| C.1 — Quant strategies                    | REPLACE (covered by Phase 5)    | 0 (Phase 5)    |
| C.2 — Classical strategies                | REWRITE 5–8 representatives     | 150            |
| C.3 — Execution-related                   | REPLACE (covered by Phases 8–9) | 0 (Phases 8–9) |
| C.4 — Utilities                           | REWRITE/CONSOLIDATE             | 120            |
| C.5 — Pillar coordinator                  | REWRITE                         | (part of A)    |
| C.6 — Backtesting                         | REPLACE (covered by Phase 3)    | 0 (Phase 3)    |
| C.7 — Examples                            | REWRITE 3 canonical             | 20             |
| D — Data feeds                            | REPLACE (covered by Phase 1)    | 0 (Phase 1)    |
| E — Broker adapters                       | DOCUMENT (pragmatic exception)  | 8              |
| F — Services                              | DEDUP + audit                   | 60             |
| G — Common libs                           | AUDIT + cleanup                 | 40             |
| H — Cruft removal                         | DELETE                          | 8              |
| **Total new effort (not double-counted)** |                                 | **856 hours**  |

That is ~5 calendar months at half-time, ~2.5 months at full-time. It is real work, but it eliminates 80K+ lines of misleading code from the repo.

#### 0.5.5 Sequencing

Phase 0.5 does not need to complete before any other phase begins. Sequencing recommendation:

- **Week 1 (in parallel with Phase 0):** Cruft removal (H) + duplicate deletion in services/ (F partial). Quick wins, low risk. ~16 hours.
- **Weeks 2–4:** Pillar rewrite (A) — foundational, blocks Phase 5 cleanly. ~200 hours.
- **Weeks 5–8:** Engines (B) and utilities (C.4) — needed for Phase 4 pilot. ~370 hours.
- **Weeks 9–12:** Classical strategies (C.2), examples (C.7), services/libs (F, G). ~270 hours.
- **As-they-arise:** REPLACE categories (C.1, C.3, C.6, D) happen automatically as Phases 1, 3, 5, 8, 9 ship.

#### 0.5.6 Definition of Done — Phase 0.5

- [ ] Zero `.fixed_attempt` files in the active tree (only inside `.archive/`)
- [ ] Zero `.backup` files in the active tree (only inside `.archive/`)
- [ ] All files in `core_trading/strategies/architecture/pillars/` have <5% commented lines and pass mypy --strict
- [ ] No duplicate implementations between `core_trading/` and `services/`
- [ ] All TODO/FIXME/XXX markers in non-broker code resolved or converted to GitHub issues with rationale
- [ ] Broker adapter roadmap markers documented as deferred (not as stubs) in `BROKER_ROADMAP.md`
- [ ] `libs/common/errors/exceptions.py` ships a complete exception hierarchy
- [ ] Graphify knowledge graph regenerated and committed
- [ ] No file in the active tree has >20% commented lines (a `# normal docstring` comment is fine, but commented-out *code* is not)

---

###  Phase 1 — Data Infrastructure

**Duration:** 4–8 weeks
**Status:** prerequisite for any backtest

The most expensive mistake in quant is starting with strategies before data. Garbage in, garbage out. Backtests on dirty data are worse than no backtests because they create false confidence.

#### Objectives

Build a survivorship-bias-free, corporate-action-adjusted, point-in-time correct data lake for equities (initially) covering ≥5 years of history.

#### 1.1 Universe construction

- Define the trading universe (e.g., S&P 1500 equities, plus India NSE if relevant)
- Maintain historical constituent membership (survivorship-bias-free): the universe on 2018-01-01 is what was *actually trading* on that date, including delisted names
- Source: IBKR historical, plus optionally Norgate Data (paid, gold standard for survivorship)

#### 1.2 Historical bar data

- 1-minute, 5-minute, 1-hour, 1-day bars for the universe
- Storage: ClickHouse (already present per ADR-003) — table per resolution, partition by symbol+month
- Schema: `(symbol, timestamp, open, high, low, close, volume, vwap, trade_count, source_id, ingestion_ts)`
- Validation: gap detection, spike detection, weekend/holiday handling

#### 1.3 Corporate actions

- Splits, dividends, mergers, spin-offs
- Maintain both **adjusted** and **unadjusted** price series; backtests use unadjusted prices and apply adjustments at trade time (the correct way; most retail systems use adjusted prices, which leaks information)
- Source: IBKR corporate action feed, validated against secondary source

#### 1.4 Fundamental data (point-in-time)

- Quarterly financial statements with **as-reported and as-of dates** (not restated)
- Key requirement: when backtesting on 2018-01-01, only use fundamental data published *before* that date
- Source options: Sharadar (paid), SimFin (free tier), or aggregate from SEC EDGAR
- Schema includes: report_date, period_end_date, revision_id

#### 1.5 Reference data

- Sector/industry classifications (GICS) with effective dates
- Index membership history
- Symbol changes / ticker renames
- Earnings announcement timestamps (precise)

#### 1.6 Alternative data (deferred to Phase 5, scaffolded now)

- News and sentiment (sources: Refinitiv, Benzinga, RSS)
- Options chain history (IBKR or CBOE DataShop)
- Insider transactions (SEC Form 4)
- Short interest (FINRA)
- Macro indicators (FRED)

#### 1.7 Live data feed

- IBKR market data subscription for the universe
- Tick-level capture to ClickHouse with sub-100ms write latency
- Quality monitoring: dropped ticks, stale quotes, crossed markets

#### 1.8 Data quality framework

- Daily integrity report: missing bars, price jumps > N sigma, volume anomalies
- Cross-source validation where possible (IBKR vs Yahoo for sanity)
- Automated quarantine of suspect data with manual review queue

#### Definition of Done — Phase 1

- [ ] 5+ years of clean OHLCV bars for the chosen universe
- [ ] Survivorship-bias-free universe with delisted names included
- [ ] Corporate actions integrated and validated
- [ ] Point-in-time fundamental data for ≥3 years
- [ ] Data quality dashboard live in Grafana
- [ ] Backtests can query historical state of the universe at any date

---

### Phase 2 — Research Framework

**Duration:** 3–4 weeks (parallel with Phase 1 tail)

A research framework that prevents look-ahead bias by construction, not by discipline. Look-ahead bias is the single most common cause of fake alpha.

#### 2.1 Feature store

- Centralised computation of all features (returns, volatility, technical indicators, fundamental ratios, factor exposures)
- Each feature has a "as-of" timestamp guaranteeing no future data
- Versioned: when a feature definition changes, old backtests can still recompute with the old definition

#### 2.2 Notebook → strategy template

Standardised research workflow:

1. `00_universe.ipynb` — confirm universe
2. `01_hypothesis.ipynb` — state the alpha hypothesis in plain English
3. `02_features.ipynb` — compute candidate features, plot distributions
4. `03_signal.ipynb` — build signal, in-sample only
5. `04_validation.ipynb` — purged k-fold cross-validation, walk-forward
6. `05_portfolio.ipynb` — combine signal with portfolio construction
7. `06_backtest.ipynb` — full backtest with costs
8. `07_robustness.ipynb` — Deflated Sharpe, PBO, bootstrap CIs
9. `08_promotion.ipynb` — paper-trading promotion or rejection memo

Each step gates the next. Code from notebooks promotes into `core_trading/signals/` only after step 09.

#### 2.3 Statistical test toolkit (`research/stat_tests.py`)

Cleanly implemented, unit-tested implementations of:

- **Stationarity:** Augmented Dickey-Fuller, KPSS, Phillips-Perron
- **Cointegration:** Engle-Granger, Johansen (with and without trend)
- **Hurst exponent** (long-memory detection)
- **Half-life of mean reversion** (Ornstein-Uhlenbeck estimation)
- **Variance ratio test** (Lo-MacKinlay)
- **Ljung-Box** (autocorrelation)
- **Jarque-Bera** (normality)
- **Volatility tests:** Engle ARCH-LM
- **Hansen's structural break test**
- **Multiple testing corrections:** Bonferroni, Holm, Benjamini-Hochberg

#### 2.4 Cross-validation framework

- **Purged k-fold CV** (de Prado): removes training samples whose labels overlap with test period
- **Combinatorial Purged CV (CPCV):** generates multiple backtest paths to estimate distribution of returns
- **Walk-forward analysis:** anchored and rolling windows
- **Embargo periods:** prevent information leakage at fold boundaries

#### 2.5 Anti-overfitting guardrails

- **Deflated Sharpe Ratio** (Bailey & de Prado): adjusts Sharpe for number of trials and skew/kurtosis
- **Probability of Backtest Overfitting (PBO):** estimates the chance the strategy was selected by luck
- **White's Reality Check / Hansen's SPA test:** test best strategy from a set
- **Out-of-sample lockbox:** the final 20% of history is touched only at the very end, exactly once

#### Definition of Done — Phase 2

- [x] Feature store live with ≥50 features — `core_trading/research/feature_store.py`: 63 versioned, look-ahead-free features; look-ahead guarantee unit-tested (`TestNoLookAhead`)
- [x] All 9 notebook templates working — `notebooks/research/strategy_template/00..08`; executed headlessly in CI (`quant-layer` smoke step)
- [x] Stat-test toolkit passes textbook validation — `core_trading/research/stat_tests.py`: ADF/KPSS/PP on known stationary vs unit-root series, Engle-Granger/Johansen on a constructed cointegrated pair, OU half-life vs analytic `ln2/κ`, etc. (`tests/research/test_stat_tests.py`)
- [x] CPCV implemented — `core_trading/research/cross_validation.py`: `CombinatorialPurgedCV` with purge + embargo, `n_paths = C(N-1, k-1)`; purge/embargo leakage verified structurally (`tests/research/test_cross_validation.py`)
- [x] Deflated Sharpe + PBO available — `core_trading/research/overfitting.py`: PSR, Deflated Sharpe (Bailey & de Prado), PBO via CSCV, White's Reality Check, Hansen's SPA, single-use out-of-sample lockbox; wired into `07_robustness.ipynb`

**Status: Phase 2 COMPLETE (2026-05-29).** 172 research tests pass under `-W error` (0 warnings, 0 skips), 99% coverage on `core_trading/research`. See §Phase 2 completion note below.

---

### Phase 3 — Backtest Engine v2 (Rewrite)

**Duration:** 4–6 weeks

The current `core_trading/strategies/backtesting/` directory is largely scaffolding with TODOs for vectorised backtest, Monte Carlo, and walk-forward (per graphify Community 7). We rewrite it.

#### 3.1 Architecture

Hybrid vectorised + event-driven engine:

- **Vectorised mode** for research speed (compute signals across full history in seconds using NumPy/Polars)
- **Event-driven mode** for realism (orders, fills, slippage, market impact, partial fills)
- A backtest run can switch modes; results must match within tolerance

#### 3.2 Realistic execution simulation

- **Slippage model:** linear-in-volume + spread component, calibrated per asset class
- **Market impact:** Almgren-Chriss square-root model for parent orders
- **Partial fills:** when order size exceeds available liquidity at touch
- **Order types:** Market, Limit, Stop, Stop-Limit, MOC, LOC, TWAP, VWAP (matching real broker capabilities)
- **Borrow costs** for shorts
- **Financing costs** for leveraged positions

#### 3.3 Multi-asset, multi-timeframe

- Equities, futures, options, FX, crypto (extensible via asset class registry)
- Mix timeframes (e.g., signal on daily, execution on 5-minute)
- Time-zone aware

#### 3.4 Monte Carlo simulation

- Resample trade sequences with replacement
- Block bootstrap (preserves autocorrelation)
- Synthetic price paths under fitted distributions
- Output: distribution of terminal wealth, max drawdown, Sharpe; not a single number

#### 3.5 Walk-forward optimisation

- Anchored: training window expands, test window rolls
- Rolling: both windows roll
- Parameter stability across folds (a strategy that needs different params each fold is overfit)

#### 3.6 Combinatorial Purged Cross-Validation

- Generates N test paths from K folds
- Returns a distribution of out-of-sample Sharpe ratios
- A single Sharpe number from a single train-test split is fiction

#### 3.7 Cost model registry

- Per-broker, per-asset commission schedules
- Exchange fees, regulatory fees
- Borrow rates by symbol (for shorts)
- Tax lot accounting (FIFO, LIFO, HIFO) — important for taxable accounts

#### 3.8 Reporting

- `BacktestReport` object containing: equity curve, trade ledger, daily PnL, position history, attribution
- Auto-generated PDF report (matplotlib or `quantstats`) with Sharpe, Sortino, Calmar, max DD, MAR, win rate, profit factor, turnover, capacity estimate
- Standardised JSON output for ML-pipeline ingestion

#### Definition of Done — Phase 3

- [x] Vectorised and event-driven modes agree on a reference strategy within 1bp/day
      (`tests/backtest/test_engine.py::TestModeAgreement` — agree to ~1e-15 on
      constant, long/short and time-varying weights, far inside 1bp/day)
- [x] All execution realism components implemented and unit-tested
      (`costs.py`: spread+volume slippage, Almgren-Chriss impact, commission
      registry, SEC/FINRA fees, borrow/financing, FIFO/LIFO/HIFO tax lots;
      `execution.py`: 8 order types + partial fills — `tests/backtest/test_costs.py`,
      `test_execution.py`)
- [x] CPCV produces distribution-of-Sharpe output
      (`walkforward.py::cpcv_sharpe_distribution`, reusing the Phase 2
      `research.cross_validation.CombinatorialPurgedCV` — `test_walkforward.py::TestCpcv`)
- [x] Backtest report generates without manual intervention
      (`report.py::BacktestReport` — equity/trade-ledger/daily-PnL/attribution,
      deterministic JSON + headless PDF tear sheet — `test_report.py`)
- [x] Replay test: re-run a backtest from saved snapshot, get byte-identical results
      (`BacktestResult.fingerprint()`; `test_engine.py::TestDeterminism`)

**Status: Phase 3 COMPLETE (2026-05-29).** Implementation in `core_trading/backtest/`
(orders, costs, execution, portfolio, metrics, engine, montecarlo, walkforward,
report). 209 tests, ~100% coverage, `-W error`, 0 skips / 0 warnings, mypy strict
clean. Also includes Monte Carlo (iid/block/gaussian) and walk-forward
optimisation with parameter-stability. Old `strategies/backtesting/` archived to
`.archive/2026-05-29_backtesting/` (damaged scaffolding; metric set preserved).

---

### Phase 4 — Pilot Vertical: Statistical Arbitrage (Pairs Trading)

**Duration:** 4–6 weeks
**Goal:** prove the entire stack end-to-end on one strategy

Pairs trading is the right pilot because: (a) it exercises stationarity tests, cointegration, Kalman filtering, and OU processes — all techniques you'll reuse; (b) it has clear entry/exit logic; (c) it's market-neutral, so capital at risk is smaller; (d) it's the most-scaffolded existing area.

#### 4.1 Pair selection (`signals/pairs/selection.py`)

- **Distance method:** sum of squared normalised price differences
- **Cointegration method:** Engle-Granger and Johansen tests across all pairs in sector
- **Copula method:** model joint distribution to find pairs with non-linear dependence
- Filter: minimum trading volume, sector match, share count comparable
- Multiple-testing correction (Bonferroni) on cointegration p-values

#### 4.2 Spread modelling (`signals/pairs/spread.py`)

- **Static hedge ratio:** OLS regression of price A on price B
- **Dynamic hedge ratio:** Kalman filter estimating time-varying beta
- **Spread as Ornstein-Uhlenbeck process:** estimate mean-reversion speed (κ), long-run mean (μ), volatility (σ)
- Half-life of mean reversion: `ln(2)/κ`; if > 30 days, reject the pair

#### 4.3 Signal generation (`signals/pairs/signals.py`)

- Z-score of spread vs OU long-run mean
- Entry: |z| > 2.0
- Exit: |z| < 0.5 or stop-loss at |z| > 4.0
- Time stop: exit after 3 × half-life regardless of z-score

#### 4.4 Position sizing (`money/sizing.py`)

- Fractional Kelly: `f* = μ/σ²` × kelly_fraction (typically 0.25)
- Volatility targeting: size to target 10% annualised vol per pair
- Per-pair cap: max 2% of portfolio NAV

#### 4.5 Portfolio construction (`portfolio/pairs_portfolio.py`)

- Allocate across all qualified pairs proportional to inverse spread variance
- Total gross leverage cap: 2.0x
- Sector exposure limit: 30% of NAV per sector
- Beta-neutralise overall portfolio against SPY

#### 4.6 Risk management (`risk/pairs_risk.py`)

- Pre-trade: position size check, correlation check, sector cap check
- Real-time: spread divergence alert (z-score > 3.5)
- Daily: VaR check, drawdown circuit breaker (5% daily, 10% monthly)

#### 4.7 Execution (`execution/pairs_execution.py`)

- Both legs filled within 60 seconds or both cancelled
- Use TWAP over 5 minutes for orders > 20% of bar volume
- Track execution shortfall per trade

#### 4.8 Backtest + robustness

- 5-year backtest with realistic costs
- CPCV with 10 folds, 4 test windows
- Deflated Sharpe ≥ 1.0 required to promote to paper
- Stress test: 2008, 2020-03, 2022 inflation regime

#### 4.9 Paper trading

- IBKR paper account
- 90+ calendar days minimum
- Daily monitoring: PnL, Sharpe vs backtest, drawdown
- Promotion gate to live: paper Sharpe within 1 SE of backtest Sharpe, no incidents

#### 4.10 Live trading (small capital)

- Initial capital: $5K–$10K
- Scaling rule: double capital after 30 days without breach of risk limits, up to defined cap
- Continuous monitoring with attribution

#### Definition of Done — Phase 4

- [x] Full pairs vertical implemented (4.1-4.8): selection, spread modelling,
      signal state machine, sizing, portfolio construction, risk, execution, and
      an end-to-end `PairsTradingStrategy` that drives the Phase 3 engine.
      Modules: `core_trading/signals/pairs/{selection,spread,signals}.py`,
      `core_trading/money/sizing.py`, `core_trading/portfolio/pairs_portfolio.py`,
      `core_trading/risk/pairs_risk.py`,
      `core_trading/execution/pairs_execution.py`,
      `core_trading/strategies/pairs_trading.py`.
- [x] Robustness wired through the Phase 3 engine (4.8): vectorised vs
      event-driven agreement, CPCV distribution-of-Sharpe
      (`walkforward.cpcv_sharpe_distribution`), Deflated Sharpe
      (`research.overfitting.deflated_sharpe_ratio`), and a stress-window check --
      all in `tests/integration/test_pairs_pipeline.py`. Selection is verified to
      find the genuine cointegrated pairs and let them dominate spurious ones.
- [x] Paper-trading harness (4.9 code): `core_trading/ops/pairs_paper_trading.py`
      -- risk-gated daily driver, kill switch with incident recording, daily
      monitoring frame, and the paper-to-live promotion gate (>= 90 days, zero
      incidents, paper Sharpe within a standard error of backtest Sharpe).
- [x] All new code passes coverage, type-check, lint gates: 396 Phase 4 tests
      pass; mypy strict clean; ruff clean; coverage 100% on
      sizing/portfolio/risk/signals/spread, 99% execution, 97% ops/strategy, 95%
      selection. No regressions in the 381 pre-existing backtest/research tests.
- [ ] End-to-end paper trading run completed for 90 days *(operationally gated --
      requires elapsed calendar time on a live IBKR paper account; harness is
      code-complete)*
- [ ] Live Sharpe within 50% of paper Sharpe (decay is expected; >50% decay = stop)
      *(operationally gated -- follows the 90-day paper run)*
- [ ] No risk-limit breaches over the 90-day paper period *(operationally gated)*
- [ ] Postmortem document: what worked, what surprised us, what to change for next
      strategy *(written at the end of the paper run)*

**Status: Phase 4 CODE-COMPLETE (2026-05-30).** The entire statistical-arbitrage
vertical is implemented, integration-tested end-to-end, and proven to drive the
Phase 3 backtest engine look-ahead-free with the two engine modes in agreement.
The remaining open checkboxes (90-day paper run, live sizing, postmortem) are
operational milestones gated on wall-clock time and a live IBKR paper account, not
code; the runnable harness and the operating procedure
(`docs/PHASE_4_PAIRS_RUNBOOK.md`) are in place to execute them. New packages:
`core_trading/signals/`, `core_trading/money/`, `core_trading/portfolio/`,
`core_trading/risk/`, `core_trading/ops/`, plus `pairs_execution.py` and the
`pairs_trading.py` pilot strategy.

---

### Phase 5 — Signal Generation Library (the Alpha Factory)

**Duration:** 6–12 months in parallel with Phases 6–9

This is the big one. The library of signals that drive everything. Build incrementally; one signal at a time, each going through the full Phase 2–4 pipeline before the next.

Sequence (priority order based on expected edge × ease):

#### 5.A — Time-series statistical models

5.A.1 **Hidden Markov regime detection** (`signals/regimes/hmm.py`)

- Replace the 82%-commented `regime_aware_adaptive_strategies.py`
- Two-state (bull/bear), three-state (bull/bear/sideways), four-state (add crisis)
- Features: returns, realised volatility, term structure
- Output: regime probabilities at each timestamp
- Strategy application: switch sub-strategies by regime

5.A.2 **Kalman filters** (`signals/filters/kalman.py`)

- Dynamic linear models with Gaussian noise
- Applications: time-varying beta (pairs hedge ratio), state-space mean reversion, latent factor extraction
- Validate against `filterpy` reference implementation

5.A.3 **State-space models** (`signals/filters/state_space.py`)

- Local level, local trend, BSM (basic structural model)
- Unobserved Components Models (UCM) for trend/cycle decomposition

5.A.4 **ARIMA / SARIMA / ARFIMA** (`signals/timeseries/arima.py`)

- Box-Jenkins methodology for short-term return forecasting
- Long-memory via ARFIMA (fractional differencing)
- de Prado's "fractional differencing" preserves memory while gaining stationarity

5.A.5 **GARCH family** (`signals/volatility/garch.py`)

- GARCH(1,1) baseline
- EGARCH (asymmetric)
- GJR-GARCH (leverage effect)
- HAR-RV (heterogeneous autoregressive realised volatility)
- DCC-GARCH for time-varying correlations

#### 5.B — Stochastic process models

5.B.1 **Ornstein-Uhlenbeck** (`signals/stochastic/ou.py`)

- Mean-reverting baseline for pairs and stat-arb
- MLE estimation of κ, μ, σ

5.B.2 **Jump-diffusion (Merton)** (`signals/stochastic/jump_diffusion.py`)

- Models large jumps (earnings, macro events)
- Used in options pricing and risk modelling

5.B.3 **Heston stochastic volatility** (`signals/stochastic/heston.py`)

- For options market making and vol arb

5.B.4 **Geometric Brownian Motion baseline** (`signals/stochastic/gbm.py`)

- Reference model; not for trading but for relative comparison

#### 5.C — Cross-sectional factor models

5.C.1 **Fama-French 3 / 5 / 6 factor** (`signals/factors/fama_french.py`)

- Market, SMB (size), HML (value), RMW (profitability), CMA (investment), UMD (momentum)
- Replace the 80–85%-commented `multi_factor_models.py` files
- Daily factor returns; cross-sectional regressions

5.C.2 **Barra-style risk factor model** (`signals/factors/barra.py`)

- Industry factors + style factors (size, value, growth, leverage, liquidity, volatility, momentum)
- Used for residual returns (alpha after factor exposure removed)

5.C.3 **PCA factor extraction** (`signals/factors/pca_factors.py`)

- Statistical factors (no economic priors)
- Useful for hedging unknown common exposures

5.C.4 **Cross-sectional momentum** (`signals/factors/momentum.py`)

- 12-1 month, 6-1 month, 3-1 month
- Risk-adjusted (volatility-scaled momentum)

5.C.5 **Quality / Value / Low-vol** (`signals/factors/style_factors.py`)

- Standard style premia, point-in-time correct

#### 5.D — Machine learning signals

5.D.1 **Tree ensembles** (`signals/ml/trees.py`)

- XGBoost, LightGBM, CatBoost for return prediction
- Cross-sectional ranking models (predict next-month return rank)
- SHAP feature importance for interpretability

5.D.2 **Random Forest with purged CV** (`signals/ml/random_forest.py`)

- Bagging baseline
- Out-of-bag error estimates

5.D.3 **Neural networks for time series** (`signals/ml/neural.py`)

- LSTM with attention
- Transformer (Informer, Autoformer) for long-horizon forecasting
- Temporal Fusion Transformer

5.D.4 **Reinforcement learning** (`signals/ml/rl/`)

- Replace the 77%-commented `reinforcement_learning.py`
- Discrete actions: long, flat, short
- Continuous actions: position size
- Algorithms: DQN, PPO, SAC, TD3
- Reward shaping critical: Sharpe-based, not raw return
- Use FinRL framework; validate against published environments

5.D.5 **Meta-labelling** (`signals/ml/meta_labelling.py`)

- de Prado's technique: ML model predicts whether to take a signal generated by a base strategy
- Improves precision; sacrifices recall

#### 5.E — Microstructure signals

5.E.1 **Order book imbalance** (`signals/microstructure/obi.py`)

- Bid volume vs ask volume at top N levels
- Predictive over 1–60 second horizons

5.E.2 **VPIN (Volume-Synchronised PIN)** (`signals/microstructure/vpin.py`)

- Easley-Lopez de Prado-O'Hara toxicity measure
- Pre-warning of adverse selection

5.E.3 **Kyle's Lambda** (`signals/microstructure/kyle_lambda.py`)

- Price impact per unit volume
- Liquidity proxy

5.E.4 **Spread decomposition** (`signals/microstructure/spread.py`)

- Roll's effective spread
- Glosten-Harris (adverse selection, order processing, inventory components)

5.E.5 **High-frequency volatility** (`signals/microstructure/hf_vol.py`)

- Realised volatility from tick data
- Realised kernels (Barndorff-Nielsen-Shephard) — noise-robust

#### 5.F — Alternative data signals (later phase)

5.F.1 **News sentiment** (`signals/alt_data/news_sentiment.py`)

- FinBERT or similar pretrained model
- Aggregate by symbol and time window
- Decay function (news decays fast)

5.F.2 **Earnings surprise** (`signals/alt_data/earnings.py`)

- Standardised Unexpected Earnings (SUE)
- Post-Earnings Announcement Drift (PEAD)

5.F.3 **Insider trading** (`signals/alt_data/insider.py`)

- SEC Form 4 data
- Cluster buys; magnitude relative to insider holdings

5.F.4 **Options flow** (`signals/alt_data/options_flow.py`)

- Put/call ratio, unusual options activity
- Implied volatility skew

5.F.5 **Macro indicators** (`signals/alt_data/macro.py`)

- VIX term structure
- Yield curve slope and shape
- TED spread, credit spreads
- Currency carry signals

#### Definition of Done — Phase 5

Each signal module:

- [ ] Mathematical reference cited in module docstring
- [ ] Unit tests pass against textbook examples (e.g., GARCH parameters recovered on simulated GARCH series)
- [ ] Backtest run completes in the standard framework
- [ ] Deflated Sharpe computed
- [ ] Either promoted to paper trading (Sharpe > threshold) or archived with rejection memo
- [ ] No `.fixed_attempt` siblings, no commented-out blocks

---

### Phase 6 — Portfolio Construction Layer

**Duration:** 2–3 months (overlaps Phase 5)

#### 6.1 Mean-variance optimisation (`portfolio/mvo.py`)

- Classical Markowitz
- With realistic constraints: long-only, gross leverage, sector caps, turnover
- Robust covariance: Ledoit-Wolf shrinkage, OAS
- Robust mean: Black-Litterman or Bayesian shrinkage
- **Never use raw sample mean as expected return — it's noisy garbage**

#### 6.2 Black-Litterman (`portfolio/black_litterman.py`)

- Combines market-implied equilibrium with user views
- Mathematically clean way to inject signals into allocation
- View confidence parameter (Ω) controls how much signals move from equilibrium

#### 6.3 Hierarchical Risk Parity (`portfolio/hrp.py`)

- de Prado's HRP
- Uses asset clustering on correlation distance
- More stable than MVO out of sample (no matrix inversion)

#### 6.4 Risk Parity (`portfolio/risk_parity.py`)

- Equal risk contribution
- Levered to target volatility
- Classic Bridgewater "All Weather" structure

#### 6.5 Robust optimisation (`portfolio/robust_opt.py`)

- Michaud resampling
- Worst-case CVaR
- Distributionally robust optimisation

#### 6.6 Multi-strategy allocator (`portfolio/strategy_allocator.py`)

- Allocate capital across active strategies
- Inputs: backtest Sharpe, live Sharpe, drawdown, capacity, correlation
- Methods: equal-weight, risk parity, Bayesian update with live performance
- Strategy decommissioning: live Sharpe < 0 for 60 days → reduce by 50%

#### 6.7 Rebalancing logic (`portfolio/rebalance.py`)

- Threshold-based (when drift > X%)
- Calendar-based (monthly, quarterly)
- Hybrid (calendar trigger with threshold override)
- Turnover budget: max N% portfolio turnover per period

#### Definition of Done — Phase 6

- [ ] Each optimiser produces valid weights for a 20-asset universe in < 1 second
- [ ] Sensitivity tests: small input changes produce small output changes (test for matrix-inversion instability)
- [ ] Cross-method comparison report: MVO vs HRP vs RP on same universe
- [ ] Multi-strategy allocator integrated with Phase 4 pairs strategy

---

### Phase 7 — Risk Management Layer

**Duration:** 2–3 months (overlaps Phase 5–6)

Risk management is what makes quant work, not signal quality. Treat this phase as load-bearing.

#### 7.1 Pre-trade risk checks (`risk/pretrade.py`)

- Position size vs liquidity (max 10% of 30-day average daily volume per order)
- Position size vs portfolio NAV (max 5% per single position)
- Aggregate exposure vs limits
- Margin sufficiency
- Restricted-list check (no insider-list symbols)
- Kill-switch check

#### 7.2 Position-level risk (`risk/position_risk.py`)

- Stop-loss (absolute, ATR-based, volatility-based)
- Trailing stops
- Position-level VaR contribution
- Greek exposure for options (delta, gamma, vega, theta)

#### 7.3 Portfolio-level VaR (`risk/var.py`)

- **Parametric VaR** (variance-covariance)
- **Historical VaR** (empirical quantile)
- **Monte Carlo VaR** (simulation from fitted distributions)
- Confidence levels: 95%, 99%
- Horizons: 1-day, 10-day
- Backtesting: Kupiec and Christoffersen tests (does realised loss frequency match VaR?)

#### 7.4 CVaR / Expected Shortfall (`risk/cvar.py`)

- Average loss in the worst (1-α)% of cases
- Coherent risk measure (VaR is not)
- Use CVaR for optimisation, VaR for reporting

#### 7.5 Stress testing (`risk/stress.py`)

- **Historical scenarios:** 2008 crisis, 2010 flash crash, 2015 Aug, 2018 Q4, 2020 COVID, 2022 inflation
- **Hypothetical scenarios:** ±10% equity shock, ±50bp rate shock, ±20% vol shock
- **Reverse stress test:** what scenario makes the portfolio lose X%?

#### 7.6 GARCH-based volatility forecasting (`risk/vol_forecast.py`)

- Replace constant historical-vol assumptions
- Symmetric and asymmetric models (GJR-GARCH for leverage)
- Multi-step-ahead forecasts
- Feeds into Phase 6 portfolio construction

#### 7.7 Tail risk and copulas (`risk/copulas.py`)

- Gaussian copula (baseline)
- Student-t copula (fat tails)
- Vine copulas (high-dimensional joint distributions)
- Tail dependence coefficients

#### 7.8 Drawdown circuit breakers (`risk/circuit_breakers.py`)

- Strategy-level: pause if drawdown > 10%
- Portfolio-level: de-risk to 50% if drawdown > 15%, halt at 25%
- Daily-loss limit: halt new orders if intraday loss > 3% of NAV
- All breakers tested via simulation before going live

#### 7.9 Correlation regime detection (`risk/correlation_regime.py`)

- Rolling correlation matrices
- Spectral analysis (largest eigenvalue = market mode)
- Alert when correlation structure shifts (crowding, crisis)

#### 7.10 Liquidity risk (`risk/liquidity.py`)

- Days-to-liquidate at X% of ADV without market impact
- Liquidity-adjusted VaR
- Stress liquidity: how much capital evaporates if spreads triple?

#### Definition of Done — Phase 7

- [ ] All risk modules implemented and tested
- [ ] VaR backtest (Kupiec) passes for the pilot strategy
- [ ] Stress test report auto-generated daily
- [ ] Circuit breakers fire correctly in simulation
- [ ] Pre-trade risk gate integrated with execution layer

---

### Phase 8 — Money Management Layer

**Duration:** 1–2 months (overlaps Phase 7)

#### 8.1 Position sizing (`money/sizing.py`)

- **Fixed fractional:** N% of NAV per trade
- **Fixed dollar:** $X per trade
- **Kelly Criterion (fractional):** `f* = (μ-r)/σ² × kelly_fraction` (use kelly_fraction = 0.25 to 0.5; full Kelly is too aggressive)
- **Volatility targeting:** size to hit a target portfolio volatility
- **Risk parity sizing:** equal risk contribution across positions
- **Optimal-f (Vince):** alternative to Kelly that's drawdown-aware

#### 8.2 Leverage management (`money/leverage.py`)

- Gross leverage limit (e.g., 2.0x)
- Net leverage limit (e.g., 1.0x for market-neutral)
- Per-asset-class leverage caps
- Dynamic delevering on drawdown (Volatility Targeting: lower leverage in high-vol regimes)

#### 8.3 Capital allocation across strategies (`money/capital_allocation.py`)

- Strategy lifecycle: research → paper → small live → scaled live
- Initial live capital: fixed small amount (e.g., $5K) regardless of backtest greatness
- Scaling triggers: time-based (30 days clean) AND performance-based (within X% of paper Sharpe)
- Decommissioning: live Sharpe < 0 for 60 days, or paper Sharpe degrades > 50%

#### 8.4 Drawdown-based de-risking (`money/drawdown_management.py`)

- Reduce exposure as drawdown deepens
- "Vol-of-vol" indicator: when vol is rising AND drawdown is growing, halve exposure
- Re-leverage rules: must hit prior equity high to return to full size

#### 8.5 Turnover and cost budget (`money/turnover.py`)

- Hard cap on monthly turnover per strategy (e.g., 200%)
- Cost budget: max 30% of expected gross alpha consumed by costs
- Trade only when expected edge > 2× expected cost

#### Definition of Done — Phase 8

- [ ] All sizing methods implemented and unit-tested with known examples
- [ ] Backtest comparison: same signal under different sizing methods
- [ ] Drawdown circuit logic verified in simulation
- [ ] Live capital allocation tied to Phase 6 multi-strategy allocator

---

### Phase 9 — Execution Layer (Extension of Existing)

**Duration:** 2–3 months

The existing `core_trading/strategies/execution/` plus the algorithmic order system (graphify Community 13) is partially built. We extend rather than rewrite.

#### 9.1 Algorithm catalogue (`execution/algorithms/`)

Existing (per graphify): TWAP, VWAP. Add:

- **Implementation Shortfall (Almgren-Chriss)** — optimal trade-off between market impact and price drift
- **Almgren-Chriss closed-form solver** — for risk-aversion-weighted execution
- **Iceberg** — already in Community 14
- **Adaptive Liquidity-seeking** — Sniper-style for illiquid names
- **Participation rate (POV)** — percentage of volume
- **Arrival price** — minimise vs decision price

#### 9.2 Smart order router (`execution/smart_router.py`)

Already exists (Community 15). Extend with:

- Venue analytics: fill probability, expected latency, post-fill markout
- Routing decision logged with rationale for TCA

#### 9.3 Market impact models (`execution/impact_models.py`)

- **Almgren-Chriss square-root** — temporary + permanent impact
- **Obizhaeva-Wang** — exponential decay impact
- **Kissel-Glantz I-Star** — empirical model
- Calibrate models on your own fills monthly

#### 9.4 Transaction Cost Analysis (`execution/tca.py`)

- Arrival price slippage
- VWAP slippage
- Implementation shortfall
- Markout analysis (1s, 10s, 1m, 5m, 1h, EOD)
- Attribution: spread cost, impact cost, timing cost, opportunity cost
- Daily TCA report

#### 9.5 Adverse selection monitoring (`execution/adverse_selection.py`)

- VPIN-based pre-trade toxicity check
- Markout drift detection
- Auto-pause execution when toxicity spikes

#### 9.6 Order lifecycle and reconciliation (`execution/lifecycle.py`)

- State machine: NEW → ACK → PARTIAL → FILLED / CANCELLED / REJECTED
- Reconcile internal records with broker fills daily
- Mismatch alerts go to Pager

#### Definition of Done — Phase 9

- [ ] All execution algorithms run in backtest and live
- [ ] TCA report auto-generated daily
- [ ] Market impact models calibrated on actual fills
- [ ] Reconciliation runs daily with zero unexplained mismatches

---

### Phase 10 — Continuous Testing Framework

**Duration:** ongoing, never "complete"

#### 10.1 Test pyramid

- **Unit tests:** every function, every model — 95%+ coverage on `signals/`, `portfolio/`, `risk/`, `money/`, `execution/`
- **Integration tests:** full backtest from data to report; full live flow against IBKR paper
- **Property tests:** Hypothesis-based, e.g., portfolio weights always sum to ≤ leverage limit
- **Regression tests:** save backtest hashes; alert if a code change moves results unexpectedly

#### 10.2 Statistical robustness tests (automated per strategy)

- Bootstrap confidence intervals on Sharpe
- Deflated Sharpe Ratio
- Probability of Backtest Overfitting
- White's Reality Check across the strategy set
- CPCV distribution

#### 10.3 Live-vs-backtest divergence

- Daily: compare live PnL to "shadow backtest" run on the same day's data
- Alert if divergence > 2 standard deviations of historical residuals
- Investigate every divergence

#### 10.4 Chaos testing

- Randomly inject: slow market data, broker disconnect, fill rejections, partial fills, duplicate fills
- System must degrade gracefully

#### 10.5 Performance benchmarks

- Backtest throughput: bars/second
- Live tick-to-order latency: μs measurements at p50, p99, p999
- Memory profiles under load

#### Definition of Done — Phase 10

Ongoing gates:

- [ ] Every PR ships green tests + coverage report
- [ ] Strategy promotion requires fresh statistical robustness report
- [ ] Daily ops dashboard shows live-vs-backtest divergence

---

### Phase 11 — Forward Testing & Paper Trading

**Duration:** minimum 90 days per strategy

#### 11.1 Paper trading infrastructure

- IBKR paper account (separate from live)
- Identical code path to live except for broker connection — no `if paper: ...` branches
- Real-time tick data (not delayed)
- Full execution simulation realism

#### 11.2 Daily monitoring

- PnL dashboard (cumulative, daily, intraday)
- Sharpe ratio rolling 30/60/90 day
- Drawdown vs backtest expectation
- Trade count vs backtest expectation
- Slippage attribution

#### 11.3 Promotion criteria to live

A strategy may go live (with small capital) only if **all** of the following hold over the 90-day paper period:

1. Realised Sharpe ≥ 0.6 × backtest Sharpe (within 1 SE)
2. Realised max drawdown ≤ 1.5 × backtest max drawdown
3. Trade count within ±30% of backtest expectation
4. No unhandled exceptions in live monitoring
5. No risk-limit breaches
6. Average slippage ≤ assumed slippage in backtest
7. Postmortem document approved by you (the operator)

If any criterion fails, the strategy returns to research with documented failure mode.

#### 11.4 Performance attribution (`ops/attribution.py`)

- Factor attribution: how much PnL came from market beta, value, momentum, etc.?
- Strategy attribution: per-strategy contribution to portfolio PnL
- Trade attribution: which trades drove the day's PnL?
- Cost attribution: spread, impact, timing, opportunity

#### Definition of Done — Phase 11

Per strategy:

- [ ] 90+ day paper run completed
- [ ] Promotion criteria evaluated and documented
- [ ] Decision (promote / reject / extend) signed off
- [ ] Attribution report archived

---

### Phase 12 — Live Trading

**Duration:** ongoing

#### 12.1 Initial deployment

- Tier 1 capital: $5K–$10K per strategy
- Conservative leverage: 1.0x gross, 1.0x net (or strategy-natural)
- Hard daily-loss limit: 2% of allocated capital

#### 12.2 Scaling rules

- **30-day clean:** double capital allocation
- **60-day clean:** double again
- **90-day clean and stable Sharpe:** consider strategic allocation
- "Clean" = no risk breaches, Sharpe within expected band, no incidents

#### 12.3 Incident response

- Runbooks for: broker disconnect, market data outage, execution errors, kill-switch firings, unusual fills
- Each incident triggers a postmortem document
- Recurring incidents trigger code-level remediation

#### 12.4 Daily operations

- Pre-market: data freshness check, broker connectivity check, capital reconciliation
- Intraday: real-time PnL, risk limit monitoring, alert triage
- Post-market: TCA report, performance attribution, audit trail review
- Weekly: live-vs-backtest divergence analysis
- Monthly: strategy review meeting (with yourself, formal)
- Quarterly: full system audit, capacity review, decommission/promote decisions

#### 12.5 Reconciliation and audit (`ops/reconciliation.py`)

- Broker positions vs internal positions: daily
- Broker fills vs internal fills: daily
- Cash balance reconciliation: daily
- Mismatches trigger pager immediately

#### 12.6 Tax and regulatory

- Tax lot accounting (FIFO / LIFO / HIFO selectable per account)
- Wash-sale tracking
- Year-end tax report
- Regulatory: pattern day trader rules (if US accounts < $25K)

#### 12.7 Documentation and audit trail

- Every order has: strategy_id, signal_id, model_version, reason_code
- Every parameter change has: who, when, why, prior_value
- 7-year retention (for personal records)

#### Definition of Done — Phase 12

Ongoing:

- [ ] Live and paper running side-by-side
- [ ] Daily ops checklist completed and archived
- [ ] No unreconciled positions at EOD
- [ ] Monthly performance report generated

---

### Phase 13 — Continuous Research & Improvement

**Duration:** ongoing, never ends

#### 13.1 Signal decay monitoring

- Track in-sample Sharpe vs rolling out-of-sample Sharpe per signal
- Alpha decay is real; expect it
- Retire signals when rolling Sharpe < 0 for 60 days

#### 13.2 Crowding analysis

- Are the same factors making everyone's portfolios at the same time?
- Use 13F filings, factor crowding indices, market-wide momentum
- Reduce exposure to crowded factors

#### 13.3 New strategy pipeline

- Quarterly research sprints
- Idea sources: academic papers (SSRN, JFE, JF, RFS), conference proceedings, your own observations
- Standard research workflow: hypothesis → backtest → paper → live

#### 13.4 Model retraining cadence

- ML models: retrain monthly with rolling 3-year window
- Statistical models (GARCH, HMM): re-estimate weekly
- Factor models: re-estimate monthly
- All retraining is automated; results logged

#### 13.5 Research backlog

- Maintained as a separate `RESEARCH_BACKLOG.md`
- Prioritised by: expected edge × ease of implementation
- Rejected ideas archived with reason (so we don't re-explore them)

---

## 4. Cross-Cutting Concerns

### 4.1 Logging and observability

- Structured logging (already present via `LoggerMixin`)
- ASCII-only output per global CLAUDE.md (no Unicode in logs)
- Metrics: Prometheus (already present per ADR-015)
- Dashboards: Grafana 10+ (per session memory `project_infra_swaps.md`)
- Log aggregation: Loki (pinned 2.9.x per memory)

### 4.2 Security

- IBKR credentials in environment variables, never in code (per memory `project_credential_incident.md`)
- Secrets manager (HashiCorp Vault or AWS Secrets Manager) for production
- Audit log for every parameter change
- Read-only roles for monitoring users

### 4.3 Disaster recovery

- Daily snapshot of ClickHouse and PostgreSQL
- Code in git with off-site backup (GitHub)
- Strategy state checkpointed every N minutes
- Restart-from-snapshot tested quarterly

### 4.4 Capacity planning

- Each strategy has an estimated capacity (max AUM before market impact erodes alpha)
- Capacity = function of average daily volume of universe, holding period, turnover
- Monitor: live position size vs capacity; alert at 50%, halt new allocation at 80%

### 4.5 Documentation

- Every module: docstring with mathematical reference
- Every strategy: design doc + research notebook archive + paper-trading postmortem
- ADRs (Architecture Decision Records) for every major design choice — extend existing `phase01_architecture_decision_records_*.md`
- Runbooks for every operational task

---

## 5. Things You May Have Missed (My Additions)

### 5.1 Data infrastructure FIRST, not last

The most expensive quant mistake is starting with strategies before data. Spend the first 2 months on Phase 1 (data) and you'll save 6 months later. Dirty data poisons every backtest you ever run on it.

### 5.2 Point-in-time data is non-negotiable

Using current fundamental data in a 2018 backtest is fraudulent. The standard convention in many libraries (yfinance, pandas-datareader) uses restated data; this leaks future information.

### 5.3 Multiple-testing correction

If you test 1000 strategies and pick the one with highest Sharpe, that Sharpe is a lie. Apply Bonferroni / Holm / Benjamini-Hochberg corrections to all in-sample selections.

### 5.4 Deflated Sharpe Ratio

After selection from a strategy set, Sharpe must be deflated by the expected maximum order statistic. Bailey & López de Prado (2014) formalised this. Without it, every "great backtest" is overstated.

### 5.5 Out-of-sample lockbox

Reserve the final 20% of history. Touch it once, at the very end. Do not iterate on it. If your strategy fails OOS, it fails — go back to research, don't tune.

### 5.6 Combinatorial Purged CV (CPCV)

Standard k-fold leaks information when labels overlap with neighbouring folds. de Prado's CPCV solves this and produces a distribution of OOS Sharpes (not a single number).

### 5.7 Transaction cost realism

Even good strategies die from costs. Assume conservative: 2-5 bps slippage on liquid US large-cap, 10-20 bps on small-cap, more on emerging markets. Use square-root market impact for large orders.

### 5.8 Crowding and regime change

Every factor decays. Every regime ends. Build monitoring that catches this before drawdowns force you to act in panic.

### 5.9 Latency budget

For HFT signals (microstructure, news), latency matters. Decision-to-order p99 latency must be measured. If it's > the alpha decay timescale, the signal is unusable.

### 5.10 Independent live monitoring

The live-monitoring system should not depend on the trading system to flag its own problems. Run monitoring on separate process / separate host. If trading code crashes, monitoring still alerts.

### 5.11 Independent kill switch

A single command halts all trading. Tested monthly. Mapped to a physical button if practical. (Already present in your code — graphify Community shows `KillSwitch` as a god node with 159 edges; keep it pristine.)

### 5.12 Behavioural risk (the operator's risk)

You are the highest-risk component. Plan for: revenge trading after a loss, anchor bias, overconfidence after a win. Mitigation:

- Hard rules > discretion
- Cooling-off periods after large losses or large wins
- Trading journal
- A second pair of eyes on major decisions (even if it's a friend or a hired advisor)

### 5.13 Capacity assumptions in backtest

If your backtest assumes you fill at the close, but in reality the close auction has 5x the spread of the prior minute, your backtest overstates returns. Always check: would your backtest fill survive 2x the real spread?

### 5.14 Survivorship bias is everywhere

Not just in stocks — in strategies you read in papers, in YouTube backtests, in factor publications. Discount everything in published research because what you're seeing has been selected for survival.

### 5.15 The "skin in the game" rule

Do not deploy capital to a strategy you would not deploy your own capital to. (This is your own capital, but the rule still applies recursively: do not allocate to a strategy you would not double-down on tomorrow.)

---

## 6. Things You Mentioned That Need Nuance or Correction

### 6.1 "Hedge funds don't use technical indicators"

Partially true. **Quant** funds (Renaissance, Citadel, Two Sigma, DE Shaw, Jane Street) do use price-derived features extensively — but as inputs to larger models, not as standalone signals. They don't trade "RSI < 30 → buy"; they include RSI as one of thousands of features in an XGBoost or neural model. **Discretionary hedge funds** (Bridgewater Pure Alpha, Citadel Wellington's discretionary book) use technical indicators too, just in combination with macro views.

The truth: technicals are inputs, not signals. Where you go wrong with technicals is using them as standalone systems with hand-tuned thresholds.

### 6.2 "Markov chains"

Markov chains are one technique among many. The full statistical-modelling toolkit includes:

- Markov chains (memoryless state transitions)
- **Hidden Markov Models** (states are latent, observations are conditional on states) — more useful in practice
- MCMC (Markov Chain Monte Carlo) for Bayesian inference — used in model estimation, not directly for trading
- Regime-switching models (Hamilton-style)
- State-space models (Kalman filter is a special case)

Pure Markov chains alone will not trade profitably. The plan above includes HMMs (Phase 5.A.1) as the main "Markov-flavoured" tool.

### 6.3 "Trade like a hedge fund profitably"

Realistic expectations:

- Top quant funds achieve net-of-fees Sharpe of 1.5–3.0 on multi-billion AUM (Medallion is the outlier at ~7)
- Median retail quant strategy is unprofitable after costs
- A single individual with disciplined process, good infrastructure, and conservative risk can achieve Sharpe 1.0–1.5 over the long run *if everything goes right*
- 50% of strategies you build will fail to graduate from paper trading. Plan for that. Failure is the default; success is the exception.

This plan optimises for the best chance of profitability. It does not guarantee it.

### 6.4 "Models like Markov chains, etc."

The full landscape is:

| Class                   | Examples                               | Trading use                                               |
| ----------------------- | -------------------------------------- | --------------------------------------------------------- |
| Time-series statistical | ARIMA, GARCH, HMM, Kalman, state-space | Mean reversion, regime detection, vol forecasting         |
| Stochastic processes    | OU, GBM, Heston, jump-diffusion        | Pairs trading, options pricing, vol arb                   |
| Cross-sectional         | Fama-French, Barra, PCA factors        | Factor investing, risk decomposition                      |
| Machine learning        | Trees, RF, GBM, NN, RL                 | Return prediction, meta-labelling, execution optimisation |
| Microstructure          | OBI, VPIN, Kyle's λ                    | HFT, market making, adverse selection                     |
| Optimisation            | MVO, Black-Litterman, HRP, CVaR        | Portfolio construction                                    |
| Risk                    | VaR, CVaR, copulas, stress             | Risk management                                           |
| Execution               | TWAP, VWAP, IS, Almgren-Chriss         | Trading mechanics                                         |

The plan above covers all of these in Phases 5–9.

---

## 7. Resource and Cost Estimates

### 7.1 Human time

Solo engineer, half-to-full time:

- Phase 0: 40–80 hours
- Phase 1: 160–320 hours
- Phase 2: 120–160 hours
- Phase 3: 160–240 hours
- Phase 4: 160–240 hours
- Phase 5 (all): 800–1600 hours (split across 6–12 months)
- Phase 6: 200–300 hours
- Phase 7: 200–300 hours
- Phase 8: 80–120 hours
- Phase 9: 200–300 hours
- Phase 10–13: ongoing, ~10–20 hours/week thereafter

**Total to baseline ("trading like a small hedge fund"):** 2500–4000 engineering hours = 18–24 calendar months at part-to-full time.

### 7.2 Infrastructure cost (laptop-first per existing strategy)

- IBKR account: free, paper or funded
- Market data subscriptions (IBKR bundles + supplementary): $100–$500/month
- Fundamental data (Sharadar or similar): $50–$200/month
- Compute: existing laptop sufficient for research; cloud burst for heavy ML if needed ($50–$200/month occasional)
- Backup / storage: $20–$50/month
- Tools (MLflow / W&B etc.): free tier OK to start

**Operational cost:** $200–$1000/month, scales with data subscriptions.

### 7.3 Capital

- Phase 4 live (pilot pairs): $5K–$10K to start
- Multi-strategy live (Phase 12+): scaling rules above; aim for $50K–$100K by month 18 if everything goes right
- Minimum reserve: 12 months of operating expenses + 100% of allocated trading capital (so a 100% drawdown does not threaten livelihood)

### 7.4 Knowledge investment

Mandatory reading (in order):

1. *Advances in Financial Machine Learning* — Marcos López de Prado (the bible)
2. *Active Portfolio Management* — Grinold & Kahn
3. *Quantitative Equity Investing* — Fabozzi
4. *Algorithmic Trading & DMA* — Barry Johnson
5. *Trading and Exchanges* — Larry Harris
6. *Options, Futures, and Other Derivatives* — Hull
7. *Analysis of Financial Time Series* — Tsay
8. *Machine Learning for Asset Managers* — López de Prado

Plus continuous reading of: SSRN finance papers, *Journal of Financial Economics*, *Review of Financial Studies*, *Journal of Finance*.

---

## 8. Risks and Failure Modes

### 8.1 Technical risks

- **Look-ahead bias:** mitigated by Phase 2 feature store with as-of timestamps
- **Survivorship bias:** mitigated by Phase 1 survivorship-bias-free universe
- **Overfitting:** mitigated by Phase 2 CPCV + Deflated Sharpe + OOS lockbox
- **Data quality:** mitigated by Phase 1 quality framework + cross-source validation
- **Software bugs in math:** mitigated by Phase 10 textbook unit tests + property tests

### 8.2 Market risks

- **Strategy decay:** mitigated by Phase 13 monitoring + retirement rules
- **Regime change:** mitigated by Phase 7 regime detection + Phase 8 drawdown circuits
- **Crowding:** mitigated by Phase 13 crowding analysis
- **Black swan events:** mitigated by Phase 7 stress tests + Phase 8 conservative sizing

### 8.3 Operational risks

- **Broker disconnect:** mitigated by Phase 12 runbook + retry logic
- **Data feed outage:** mitigated by multi-source ingestion + halt-on-bad-data policy
- **Code bugs in live:** mitigated by Phase 11 paper-first promotion + canary deployments
- **Operator error:** mitigated by hard rules + kill switch + cooling-off periods

### 8.4 Personal risks

- **Burnout:** budget rest, this is a marathon
- **Tunnel vision:** schedule periodic reality checks (do I still believe in this?)
- **Capital concentration:** never put more than 10–20% of net worth into one venture
- **Lifestyle creep on early winners:** treat early profits as luck until 12+ months of evidence

---

## 9. Governance and Decision Gates

Every promotion between phases requires a documented gate. No skipping.

### Gate 0 → 1: Environment ready

- All Phase 0 DOD items checked

### Gate 1 → 2: Data ready

- All Phase 1 DOD items checked
- Data quality dashboard green for 7 consecutive days

### Gate 2 → 3: Research framework ready

- All Phase 2 DOD items checked
- A "hello world" research notebook runs end-to-end

### Gate 3 → 4: Backtest engine ready

- All Phase 3 DOD items checked
- Vectorised and event-driven modes match within tolerance

### Gate 4 → Live (pilot): First strategy

- All Phase 4 DOD items checked
- 90+ days paper trading complete
- Promotion criteria from Phase 11.3 satisfied

### Gate per Strategy: Each new strategy must pass

- Statistical robustness (Deflated Sharpe ≥ 1.0)
- 90-day paper trading
- Postmortem document

### Gate per Quarter: Portfolio-level review

- Live PnL vs expectation
- Strategy correlations
- Capacity utilisation
- Decommission decisions

---

## 10. Definition of "Done" for the Whole System

"Done" means **production-ready end-to-end**. The system is built once, completely, with every required component implemented at production quality, and then paper trading begins immediately followed by live trading once paper criteria are met. There is no "Phase 14 — finish the bits we skipped." This is the deliverable bar:

### 10.0 Production-Readiness Checklist (pre-paper-trading gate)

Before paper trading begins on day 1, every item below must be green. No partial credit. No "we'll fix this in the first week of paper." This is the production-readiness contract.

**Code completeness:**

- [ ] Every module listed in Appendix A exists, parses, has full implementation (no commented-out blocks > 20% per file)
- [ ] Zero `.fixed_attempt`, `.backup`, or `.old` files in active tree
- [ ] Zero `NotImplementedError` outside `@abstractmethod`
- [ ] Zero `# TODO`, `# FIXME`, `# XXX`, `# HACK` outside GitHub-issue-linked exceptions
- [ ] Zero "placeholder" / "stub" / "skeleton" markers in code (broker-roadmap exception documented per §10.2)
- [ ] Phase 0.5 remediation complete (all 80K+ damaged lines resolved)

**Data infrastructure (Phase 1):**

- [ ] 5+ years of clean OHLCV bars for the trading universe in ClickHouse
- [ ] Survivorship-bias-free universe with delisted names
- [ ] Corporate actions integrated and validated
- [ ] Point-in-time fundamental data flowing
- [ ] Live data feed running with <100ms latency
- [ ] Data quality dashboard green for ≥ 14 consecutive days

**Research and backtest framework (Phases 2–3):**

- [ ] Feature store live, ≥ 50 features
- [ ] Statistical test toolkit validated against textbook examples
- [ ] Backtest engine (vectorised + event-driven) producing reproducible results
- [ ] CPCV + Deflated Sharpe + PBO computed automatically on every backtest
- [ ] OOS lockbox protocol documented and respected

**Strategy library (Phases 4–5):**

- [ ] Pilot pairs-trading strategy passing all robustness gates (Deflated Sharpe ≥ 1.0)
- [ ] At least one strategy per category (statistical, factor, ML) implemented and backtested
- [ ] All signals shipped to production have textbook-validated unit tests

**Portfolio, risk, money (Phases 6–8):**

- [ ] Multi-strategy allocator wired and rebalancing on schedule
- [ ] Pre-trade risk checks gating every order
- [ ] VaR + CVaR + stress tests running daily
- [ ] Position sizing methods (Kelly fractional, vol targeting) implemented and unit-tested
- [ ] Circuit breakers tested in simulation and verified to fire correctly
- [ ] GARCH volatility forecasts feeding portfolio construction

**Execution (Phase 9):**

- [ ] TWAP, VWAP, IS, Almgren-Chriss algorithms implemented and tested in backtest
- [ ] Smart order router live
- [ ] TCA report auto-generated daily
- [ ] Market impact models calibrated

**Testing (Phase 10):**

- [ ] ≥ 90% test coverage across `signals/`, `portfolio/`, `risk/`, `money/`, `execution/`
- [ ] Property tests for all invariants (e.g., weights sum ≤ leverage cap)
- [ ] Regression tests pinned (backtest hash equality)
- [ ] Chaos tests pass (broker disconnect, slow data, partial fills)
- [ ] CI green on every commit

**Operations (Phase 12):**

- [ ] Monitoring dashboards live in Grafana with relevant panels (PnL, positions, risk limits, latency, broker health)
- [ ] Alerting wired to a real channel (email/SMS/PagerDuty) and tested end-to-end with a fake alert
- [ ] Daily ops checklist defined and rehearsed at least 3 times
- [ ] Reconciliation (broker vs internal) runs daily without manual intervention
- [ ] Kill switch tested monthly (mapped to a single command, latency < 5s)
- [ ] Disaster recovery runbook executed end-to-end at least once
- [ ] Tax-lot accounting in place (FIFO / LIFO / HIFO selectable)
- [ ] Audit trail captures every order with strategy_id, signal_id, model_version, reason_code
- [ ] Backup of ClickHouse + PostgreSQL configured and restore tested

**Broker integration:**

- [ ] IBKR paper account fully integrated (orders, fills, positions, account info all reconciled)
- [ ] IBKR live account credentials prepared (rotated since 2026-05-21 incident — see `project_credential_incident.md`) and stored in secrets manager, never in code
- [ ] Broker disconnect runbook tested
- [ ] Pre-market connectivity check automated

**Documentation:**

- [ ] All ADRs current
- [ ] Runbooks for every operational task
- [ ] Strategy postmortem template ready for Phase 11 use
- [ ] `BROKER_ROADMAP.md` documents the deferred broker adapters

**Operator readiness (you):**

- [ ] You have read all 8 books listed in §7.4
- [ ] You can step away from the system for 24 hours and the system continues safely
- [ ] You can articulate, for each live strategy, why it works in plain English
- [ ] You have the capital reserve specified in §7.3

### 10.1 Paper Trading Readiness Gate

When all items in §10.0 are green, the system enters paper trading on the **immediately following trading day**. There is no "settling-in period," no "soft launch," no "we'll start when X is ready." Day 1 of paper trading runs the full production stack.

Paper trading runs continuously for ≥ 90 calendar days against the criteria in §11.3.

### 10.2 Live Trading Readiness Gate

When the 90-day paper period completes and all 7 promotion criteria in §11.3 are met, the system **transitions to live trading on the immediately following trading day** at the initial capital tier defined in §12.1. There is no second build phase between paper and live — same code path, same configuration, only the broker connection switches from paper to live.

### 10.3 The Whole-System DOD (restated)

The system is "done enough to trade like a small hedge fund" when:

- [ ] Phases 0–9 substantially complete (Phase 5 has at least 5 live strategies, others fully built)
- [ ] **Phase 0.5 complete: zero damaged code, zero stubs, zero placeholders (except documented broker-roadmap markers)**
- [ ] At least 3 uncorrelated strategies live, each with > 90 days paper history
- [ ] Multi-strategy allocator (Phase 6.6) live and dynamically rebalancing
- [ ] Full risk stack (Phase 7) gating every order
- [ ] TCA report (Phase 9.4) green for ≥ 30 days
- [ ] Daily ops checklist run without incident for ≥ 30 days
- [ ] Total system test coverage ≥ 90% across `signals/`, `portfolio/`, `risk/`, `money/`, `execution/`
- [ ] **Zero `.fixed_attempt` and zero `.backup` files anywhere in active tree**
- [ ] **Zero files with >20% commented-out code lines** (docstrings and prose comments fine)
- [ ] **Zero `NotImplementedError`, `pass # stub`, `# TODO`, `# FIXME`, `# XXX`, "placeholder" markers** outside the explicitly documented broker-roadmap exception
- [ ] All ADRs current
- [ ] Operator (you) can step away for 24 hours and the system continues safely

This is what "trading like a hedge fund" means in concrete, testable terms.

### 10.4 No-Stubs Policy (binding rule)

The following are **prohibited** in any merged file under the active tree:

1. **Commented-out code** — code prefixed with `#` that *was* code (not prose). If you don't need it, delete it. Git remembers.
2. **`pass`-only function bodies** — `pass` is allowed only when it actually means "no-op" (e.g., a sentinel class) and a docstring explains why.
3. **`raise NotImplementedError`** — except inside Abstract Base Class `@abstractmethod` definitions.
4. **`# TODO` / `# FIXME` / `# XXX` / `# HACK`** — every one of these must either be resolved before merge or converted to a GitHub issue with the issue number referenced in the code (e.g., `# See issue #142`).
5. **Words like "placeholder", "stub", "skeleton", "ROADMAP MARKER"** in code — these signal known-broken code shipping anyway.

### 10.5 Documented exception: broker-roadmap markers

Broker adapters for brokers the operator does not currently trade (Alpaca, Binance, Coinbase, FXCM, OANDA, Trading212) are permitted as roadmap markers because:

- They raise a clear `BrokerNotImplementedError` with a message directing users to the canonical adapter
- They serve as a declared interface contract that future implementations must honour
- Implementing 7 broker adapters for a single-operator personal-use system is wasteful effort
- They are documented as deferred in `BROKER_ROADMAP.md`, not hidden in code

This is the **only** exception. Adding new exceptions requires an ADR.

### 10.6 Enforcement

A pre-commit hook (`tools/check_no_stubs.py`) and a CI check fail the build if:

- Any merged Python file has > 20% commented code lines (excluding docstrings)
- Any merged Python file contains a forbidden marker outside the broker exception
- Any `.fixed_attempt` or `.backup` file appears outside `.archive/`

The check is configured in `.pre-commit-config.yaml` and `.github/workflows/lint.yml`.

---

## 11. Immediate Next Actions (Week 1)

If you accept this plan, the first week should be:

1. **Cruft removal pass.** Delete 188 `.fixed_attempt` files and 38 `.backup` files outside `.archive/`. Quick win. (2–4 hours)
2. **Resolve services/core_trading duplication.** Audit overlap between `services/trading-engine/src/engines/` and `core_trading/engines/`. Decide canonical home. Delete duplicates. (4–6 hours)
3. **Lock Python to 3.12.** Install, validate, document. (1–2 hours)
4. **Reconcile `pyproject.toml` + `requirements.txt`** into a single source of truth. Add the Phase 0.3 quant libraries. (2–4 hours)
5. **Install no-stubs pre-commit hook.** Use `tools/check_no_stubs.py` (write it). Configure to fail on violations. (3–4 hours)
6. **Archive the existing damaged quant code.** Move all 77–85%-commented files to `.archive/2026-05-27_remediation/` after the no-stubs hook is installed. (2–4 hours)
7. **Decide on data sources for Phase 1.** Pick fundamental data vendor (Sharadar, SimFin, EDGAR). Budget approved. (2 hours)
8. **Write the first research notebook template** (`00_universe.ipynb`) and run it against IBKR. Confirm round-trip data flow. (4–8 hours)
9. **Set up MLflow** (or DVC) for experiment tracking. (2–4 hours)
10. **Audit existing IBKR adapter** end-to-end with one trade in paper. (2 hours)

If those ten items complete cleanly, you're ready to begin Phase 1 in week 2 with Phase 0.5 running in parallel.

---

## 12. References and Further Reading

### Books

- López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley.
- López de Prado, M. (2020). *Machine Learning for Asset Managers*. Cambridge.
- Grinold, R., & Kahn, R. (1999). *Active Portfolio Management*. McGraw-Hill.
- Fabozzi, F., Focardi, S., & Kolm, P. (2010). *Quantitative Equity Investing*. Wiley.
- Johnson, B. (2010). *Algorithmic Trading & DMA*. 4Myeloma Press.
- Harris, L. (2002). *Trading and Exchanges*. Oxford.
- Tsay, R. (2010). *Analysis of Financial Time Series*. Wiley.
- Hull, J. (2018). *Options, Futures, and Other Derivatives*. Pearson.
- Cartea, Á., Jaimungal, S., & Penalva, J. (2015). *Algorithmic and High-Frequency Trading*. Cambridge.

### Key papers

- Bailey, D., & López de Prado, M. (2014). "The Deflated Sharpe Ratio."
- López de Prado, M. (2018). "The 10 Reasons Most Machine Learning Funds Fail."
- Almgren, R., & Chriss, N. (2001). "Optimal Execution of Portfolio Transactions."
- Fama, E., & French, K. (2015). "A Five-Factor Asset Pricing Model."
- Engle, R., & Granger, C. (1987). "Co-integration and Error Correction."

### Existing project documents to read in sequence

- `docs/Comprehensive Production Readiness Audit.md`
- `docs/PRODUCTION_READINESS_IMPLEMENTATION_PLAN.md`
- `docs/PRODUCTION_READINESS_PHASE2_PLAN.md`
- `docs/implementation_plan_v5.md`
- `PRODUCTION_PUNCH_LIST.md` (repo root)
- `LICENSES.md` (repo root)
- `HANDOVER.md` (repo root)

---

## 13. Change Log

| Date       | Author                                   | Change                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| ---------- | ---------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 2026-05-27 | Vincent S. Pereira (drafted with Claude) | Initial version                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| 2026-05-28 | Vincent S. Pereira (with Claude)         | Added Phase 0.5 (repo-wide code remediation) after audit found 80K+ lines of damaged code; added §10.4–10.6 No-Stubs Policy and enforcement; added production-readiness commitment in §0 and §10.0–10.2 (pre-paper-trading gate, paper-trading readiness gate, live-trading readiness gate) — the system must be complete and production-ready before paper trading begins, and live trading begins immediately after paper-trading criteria are met |

---

## Appendix A — Folder Structure (Target State)

```
core_trading/
  data/
    __init__.py
    universe.py
    bars.py
    corporate_actions.py
    fundamentals.py
    alternative.py
    quality.py
    sources/
      ibkr.py
      sharadar.py
      edgar.py
  research/
    __init__.py
    feature_store.py
    stat_tests.py
    cross_validation.py
    deflated_sharpe.py
    pbo.py
    notebooks/
      00_universe.ipynb
      01_hypothesis.ipynb
      ...
  signals/
    __init__.py
    base.py
    regimes/
      hmm.py
      threshold_models.py
    filters/
      kalman.py
      state_space.py
    timeseries/
      arima.py
      arfima.py
    volatility/
      garch.py
      egarch.py
      gjr_garch.py
      har_rv.py
    stochastic/
      ou.py
      heston.py
      jump_diffusion.py
      gbm.py
    factors/
      fama_french.py
      barra.py
      pca_factors.py
      momentum.py
      style_factors.py
    ml/
      trees.py
      random_forest.py
      neural.py
      meta_labelling.py
      rl/
        environments.py
        agents.py
    microstructure/
      obi.py
      vpin.py
      kyle_lambda.py
      spread.py
      hf_vol.py
    pairs/
      selection.py
      spread.py
      signals.py
    alt_data/
      news_sentiment.py
      earnings.py
      insider.py
      options_flow.py
      macro.py
  portfolio/
    __init__.py
    mvo.py
    black_litterman.py
    hrp.py
    risk_parity.py
    robust_opt.py
    strategy_allocator.py
    rebalance.py
  risk/
    __init__.py
    pretrade.py
    position_risk.py
    var.py
    cvar.py
    stress.py
    vol_forecast.py
    copulas.py
    circuit_breakers.py
    correlation_regime.py
    liquidity.py
  money/
    __init__.py
    sizing.py
    leverage.py
    capital_allocation.py
    drawdown_management.py
    turnover.py
  execution/
    __init__.py
    algorithms/
      twap.py
      vwap.py
      implementation_shortfall.py
      almgren_chriss.py
      iceberg.py
      adaptive.py
      pov.py
    smart_router.py
    impact_models.py
    tca.py
    adverse_selection.py
    lifecycle.py
  backtest/
    __init__.py
    engine.py
    vectorised.py
    event_driven.py
    execution_sim.py
    monte_carlo.py
    walk_forward.py
    cpcv.py
    cost_models.py
    report.py
  strategies/
    __init__.py
    base.py
    pairs_trading_v2.py
    # one file per live strategy; all use signals/, portfolio/, risk/, money/, execution/
  adapters/
    brokers/
      ibkr.py            # canonical
      # alpaca.py, coinbase.py — to be rewritten when needed
  ops/
    __init__.py
    monitoring.py
    attribution.py
    alerting.py
    reconciliation.py
    runbooks/
      broker_disconnect.md
      market_data_outage.md
      kill_switch.md
```

---

## Appendix B — Acronyms

| Acronym | Meaning                                                   |
| ------- | --------------------------------------------------------- |
| ADF     | Augmented Dickey-Fuller (stationarity test)               |
| AC      | Almgren-Chriss (optimal execution model)                  |
| ARCH    | Autoregressive Conditional Heteroskedasticity             |
| BSM     | Basic Structural Model                                    |
| CPCV    | Combinatorial Purged Cross-Validation                     |
| CVaR    | Conditional Value-at-Risk (Expected Shortfall)            |
| DCC     | Dynamic Conditional Correlation                           |
| GARCH   | Generalised Autoregressive Conditional Heteroskedasticity |
| GBM     | Geometric Brownian Motion / Gradient Boosting Machine     |
| HMM     | Hidden Markov Model                                       |
| HRP     | Hierarchical Risk Parity                                  |
| IS      | Implementation Shortfall                                  |
| MVO     | Mean-Variance Optimisation                                |
| OBI     | Order Book Imbalance                                      |
| OU      | Ornstein-Uhlenbeck                                        |
| PBO     | Probability of Backtest Overfitting                       |
| POV     | Percentage of Volume (execution algorithm)                |
| TCA     | Transaction Cost Analysis                                 |
| TWAP    | Time-Weighted Average Price                               |
| UMD     | Up-Minus-Down (momentum factor)                           |
| VaR     | Value-at-Risk                                             |
| VPIN    | Volume-Synchronised Probability of Informed Trading       |
| VWAP    | Volume-Weighted Average Price                             |

---

**End of plan. Version 1.0. 2026-05-27.**
