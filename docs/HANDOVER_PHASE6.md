# Phase 6 Kickoff -- Session Handover Brief

**Date:** 2026-06-04
**Repo:** `/home/vincentspereira/Projects/Trading/RNR-IBKR-Algo-Trader` (git: origin = vincentspereira/RNR-IBKR-Algo-Trader, branch master)
**HEAD at handover:** `0ee0bbb`

---

## 1. Where the project stands

| Phase | Status |
| ----- | ------ |
| 0 / 0.5 | Complete / substantially complete (7/9 DOD; residual violations sequenced into later phases) |
| 1 data layer | CODE-COMPLETE, OPERATOR-GATED. Ingest CLI (`python -m core_trading.data.ingest`), quality gate, Grafana dashboard all shipped; remaining DOD items are manual ops (Docker, TWS, paid Norgate decision) per `docs/PHASE1_OPERATOR_RUNBOOK.md`. NOT a Phase 6 blocker. |
| 2 research framework | COMPLETE |
| 3 backtest engine | COMPLETE (`core_trading/backtest/`, vectorised + event-driven modes) |
| 4 pairs vertical | CODE-COMPLETE (paper/live gated on wall-clock + TWS smoke test) |
| 5 alpha factory | SUBSTANTIALLY COMPLETE (2026-06-04). All data-feasible sub-phases shipped across 7 batches, ~1,500 tests, 100% coverage per module. Deferred (data-blocked, none gate Phase 6): OBI/VPIN, news sentiment, options flow, DCC-GARCH. |
| 6 portfolio construction | **READY TO START** -- certification in `docs/QUANT_TRADING_MASTER_PLAN.md` ("Phase 6 readiness certification"). |

## 2. The Phase 6 mission (master plan section "Phase 6 -- Portfolio Construction Layer")

Build `core_trading/portfolio/` with these modules:

- **6.1 `mvo.py`** -- Markowitz with realistic constraints (long-only, gross leverage, sector caps, turnover); robust covariance (Ledoit-Wolf, OAS); robust means (never raw sample mean).
- **6.2 `black_litterman.py`** -- equilibrium + views; Omega confidence controls signal injection.
- **6.3 `hrp.py`** -- de Prado Hierarchical Risk Parity (cluster on correlation distance; no matrix inversion).
- **6.4 `risk_parity.py`** -- equal risk contribution, levered to target vol.
- **6.5 `robust_opt.py`** -- Michaud resampling, worst-case CVaR, DRO.
- **6.6 `strategy_allocator.py`** -- capital across strategies (equal-weight / risk parity / Bayesian live-performance update; decommission rule: live Sharpe < 0 for 60 days -> halve).
- **6.7 `rebalance.py`** -- threshold / calendar / hybrid triggers, turnover budget.

**Phase 6 DOD:** each optimiser produces valid weights for a 20-asset universe in < 1 s; sensitivity tests (small input perturbation -> small weight change, the matrix-inversion-instability check); a cross-method comparison report (MVO vs HRP vs RP, same universe); multi-strategy allocator integrated with the Phase 4 pairs strategy.

**Available building blocks:** covariance/factor structure from `core_trading/signals/factors/` (PCA, Barra); vol estimators from `signals/volatility/garch.py` + `signals/microstructure/hf_vol.py`; signal weights in standard shapes from the Phase 5 adapters; backtest + deflated-Sharpe gate via `core_trading/research/signal_evaluation.py` (`evaluate_signal`, `price_panel_from_frame`); `cvxpy` already pinned. Read `core_trading/signals/factors/momentum.py` + its tests as the style template for panel-shaped numerics.

## 3. Per-module quality bar (non-negotiable, same as Phase 5)

1. Mathematical reference cited in the module docstring.
2. Textbook / parameter-recovery tests on synthetic data with known truth (e.g. HRP must recover de Prado's worked example; risk parity must produce equal risk contributions to tolerance; MVO with shrinkage must beat raw-sample-cov MVO out of sample on a synthetic panel).
3. 100% coverage on new modules; `-W error` clean.
4. ruff clean + mypy strict clean (run in PACKAGE mode: `mypy -p core_trading.portfolio` -- file-path mode false-errors with "source file found twice") + `tools/check_no_stubs.py` clean.
5. ASCII-only everywhere (terminal-portable -- no Unicode in code, output, or commits).
6. One coherent batch = one commit (`git commit -F <tempfile>`, trailers: `Authored By: Vincent S. Pereira <vincentspereira@outlook.com>` then `Co-Authored-By: Claude ...`), then ALWAYS `git push origin master`. NEVER push to upstream. Never commit `graphify-out/`.

## 4. Toolchain recipes and traps (cost hours if ignored)

- **Python:** ALWAYS `.venv/bin/python` (3.12). PATH python is 3.14 and breaks deps.
- **Test recipe** (root `tests/conftest.py` is a flaky landmine -- numpy double-load + torch DLL crash; skip it for self-contained unit tests):
  `.venv/bin/python -c "import numpy; import sys, pytest; sys.exit(pytest.main(['tests/portfolio','--noconftest','-W','error','-W','ignore:unclosed event loop:ResourceWarning','-W','ignore:unclosed <socket.socket:ResourceWarning','--cov=core_trading.portfolio.<mod>','--cov-report=term-missing','-q','-p','no:cacheprovider']))"`
  The two extra `-W` ignores MUST come after `-W error` (pytest-asyncio 0.21 leaks event loops; ini filters cannot override command-line -W).
- **If anything imports torch in tests:** pre-import it too (`import numpy; import torch; ...`) or c10.dll fatally crashes on Windows.
- **mypy on big packages is slow** (~4 min) -- use a generous timeout.
- Do NOT run black/isort (configured but not enforced; they churn committed files). ruff is the import-sort source of truth.
- Keep clean quant tests OUT of `tests/strategies/` (its conftest mocks statsmodels/torch into sys.modules).
- Parallel-coverage runs: set `COVERAGE_FILE=.coverage.<name>` per run to avoid collisions.
- The post-commit graphify hook prints a ">10000 nodes too large for HTML viz" message -- expected, not a failure.
- Parallel subagent pattern that works: one `claude-aiml-engineer` agent per coherent module, told to read the style template and NOT touch shared `__init__.py` (you wire it); agents never commit; INDEPENDENTLY RE-VERIFY everything they report (a prior agent died mid-task reporting nothing while leaving 4 failing tests and a real sign bug on disk).

## 5. Sensible batch plan for Phase 6

- Batch 1: estimators foundation -- `covariance.py` (Ledoit-Wolf / OAS shrinkage, factor-model covariance from PCA/Barra) since every optimiser consumes it. (Master plan folds this into 6.1; a separate module keeps it testable.)
- Batch 2: 6.1 MVO + 6.4 risk parity (both cvxpy/scipy-based, share constraint plumbing).
- Batch 3: 6.3 HRP + 6.2 Black-Litterman.
- Batch 4: 6.5 robust opt.
- Batch 5: 6.6 strategy allocator + 6.7 rebalancing + the DOD cross-method comparison report + pairs-strategy integration.

## 6. Out of scope for the Phase 6 session

- Live/paper trading operations (TWS smoke test, Docker bring-up) -- operator items in `docs/PHASE1_OPERATOR_RUNBOOK.md` / `HANDOVER.md`.
- The Phase 5 deferred items (OBI/VPIN, news, options flow, DCC-GARCH) -- data-blocked.
- Buying data (Norgate etc.) -- user decision.

## 7. Key references

- `docs/QUANT_TRADING_MASTER_PLAN.md` -- the plan; Phase 6 spec + readiness certification; Phase 5 closing status.
- `core_trading/research/signal_evaluation.py` -- the backtest + deflated-Sharpe gate.
- `core_trading/signals/factors/` -- panel-shaped numerics style template + covariance inputs.
- `docs/PHASE1_OPERATOR_RUNBOOK.md` -- data-layer ops (not needed for synthetic-panel Phase 6 work).
