# Phase 4 -- Pairs-Trading Pilot Runbook

**Strategy:** Statistical arbitrage (cointegration pairs)
**Status:** Code-complete and integration-tested. Paper-trading and live phases
are operational milestones gated on elapsed calendar time and a live IBKR paper
account (see "What is pending" at the bottom).
**Owner:** Vincent S. Pereira (single operator)
**Scope:** Personal-use IBKR Algo Trader. Not for the MAS commercial product.

This runbook is the operating procedure for the Phase 4 pilot defined in
`docs/QUANT_TRADING_MASTER_PLAN.md` section 4. It documents the daily loop, the
monitoring records, the kill switch, and the promotion gates that move the
strategy from backtest -> paper -> small-capital live.

---

## 1. What ships in Phase 4 (code-complete)

| Plan section | Capability | Module |
| ------------ | ---------- | ------ |
| 4.1 | Pair selection (distance, Engle-Granger + Johansen cointegration, copula, Bonferroni correction, volume/sector filters) | `core_trading/signals/pairs/selection.py` |
| 4.2 | Spread modelling: static OLS hedge, Kalman dynamic hedge, Ornstein-Uhlenbeck fit, z-scores | `core_trading/signals/pairs/spread.py` |
| 4.3 | Signal state machine: entry / mean-reversion exit / stop-loss / time-stop | `core_trading/signals/pairs/signals.py` |
| 4.4 | Position sizing: fractional Kelly, volatility targeting, per-position cap | `core_trading/money/sizing.py` |
| 4.5 | Portfolio construction: inverse-variance allocation, leverage / sector caps, market-beta neutralisation | `core_trading/portfolio/pairs_portfolio.py` |
| 4.6 | Risk: pre-trade checks, spread-divergence alerts, daily VaR + drawdown circuit breakers | `core_trading/risk/pairs_risk.py` |
| 4.7 | Execution: atomic both-legs-or-none fills, TWAP slicing, implementation-shortfall tracking | `core_trading/execution/pairs_execution.py` |
| 4.8 | End-to-end strategy + robustness (CPCV, Deflated Sharpe, stress windows) | `core_trading/strategies/pairs_trading.py`, `tests/integration/test_pairs_pipeline.py` |
| 4.9 | Paper-trading harness: daily driver, risk gate, kill switch, monitoring, promotion gate | `core_trading/ops/pairs_paper_trading.py` |

The whole vertical is exercised end-to-end by
`tests/integration/test_pairs_pipeline.py`: it confirms the genuine cointegrated
pairs are found, no look-ahead exists, the vectorised and event-driven engine
modes agree, CPCV produces a Sharpe distribution, the Deflated Sharpe is
well-defined, the risk circuit breaker fires on a crash, and pair execution is
atomic.

---

## 2. Pre-flight (once, before paper trading starts)

1. **Backtest gate.** Run the strategy through the Phase 3 engine over >= 5 years
   of clean data (Phase 1 data layer). Record the backtest Sharpe -- it becomes
   `PaperConfig.backtest_sharpe`, the bar the paper run must track.
2. **Robustness gate (plan 4.8).** The strategy may begin paper trading only if:
   - CPCV distribution-of-Sharpe is positive in the large majority of paths
     (`core_trading.backtest.walkforward.cpcv_sharpe_distribution`).
   - Deflated Sharpe >= 1.0
     (`core_trading.research.overfitting.deflated_sharpe_ratio`), i.e. the result
     survives deflation for the number of trials.
   - The strategy is profitable (after costs) across the 2008, 2020-03 and 2022
     stress windows, or at minimum does not breach risk limits in them.
3. **Account.** IBKR **paper** account funded with the notional you intend to
   mirror in live trading. Never test on a live account first.
4. **Alerts.** Wire `DivergenceAlert` (severity "critical") and any `RiskCheck`
   failure to a real channel (email / SMS / Slack). A halted day must page you.
5. **Kill switch rehearsal.** Confirm `PairsPaperTrader` halts and records an
   incident when a limit is breached (covered by
   `tests/ops/test_pairs_paper_trading.py::TestKillSwitch`). Know the manual
   command to flatten all positions.

---

## 3. Daily operating loop (paper)

Run once per trading day after the close (or before the next open):

1. **Refresh data.** Pull the latest bars into the Phase 1 store; run the data
   quality report. Do not trade on quarantined data.
2. **Regenerate targets.** `PairsTradingStrategy.generate_weights(prices)` on the
   current universe. Selection and hedge ratios are fixed from the formation
   window; only the rolling z-score and signals update.
3. **Pre-trade risk gate.** `PairsRiskManager.pre_trade(target_weights)`. If it
   fails, DO NOT SEND. Investigate (usually a leverage or sector breach from a
   pair that has run).
4. **Execute.** For each pair whose target position changed, build a `PairOrder`
   and send it through `PairExecutor`. Both legs fill within the window or both
   cancel -- never carry a naked single leg overnight.
5. **Mark + monitor.** Append today's `DailySnapshot`: equity, daily return,
   gross leverage, active pairs, rolling Sharpe, drawdown, risk status.
6. **Circuit breakers.** `PairsRiskManager.daily_check(equity)` and `var_check`.
   A daily loss > 5% or a trailing-month drawdown > 10% halts trading and pages
   you (kill switch). A divergence z-score > 3.5 on any open pair is a critical
   alert -- consider closing that pair.

`PairsPaperTrader.run(prices)` automates steps 2-6 over historical data so the
loop is testable; in live paper trading the execution seam (`FillModel`) is the
IBKR paper adapter.

---

## 4. Monitoring (what to watch)

`PairsPaperTrader.monitoring_frame()` produces the daily record. Track:

- **Paper Sharpe vs backtest Sharpe.** Some decay is expected. The promotion
  floor is `backtest_sharpe - promotion_se_mult * SE(Sharpe)`.
- **Drawdown** against the 5% daily / 10% monthly limits.
- **Gross leverage** against the 2.0x cap (vol-targeted budget keeps it lower).
- **Active pairs** -- a collapse to zero for many days means the signal is dead;
  a spike means correlated entries (crowding risk).
- **Incidents** -- any kill-switch trip. A clean promotion requires zero
  unresolved incidents.

---

## 5. Promotion gates

### 5.1 Paper -> Live (plan 4.9 -> 4.10)

`PairsPaperTrader.evaluate_promotion()` returns `eligible=True` only when ALL of:

- **History:** >= `min_paper_days` active paper observations (plan mandates
  >= 90 calendar days).
- **Incidents:** zero unresolved kill-switch trips.
- **Performance:** paper Sharpe is no worse than `backtest_sharpe` minus
  `promotion_se_mult` standard errors. A paper Sharpe that exceeds the backtest
  is always acceptable.

Promotion is a capital-allocation decision, not a code change -- the system is
already production-ready.

### 5.2 Live sizing and scaling (plan 4.10)

- Initial capital: USD 5k-10k.
- Scaling rule: double capital after 30 days with no risk-limit breach, up to a
  predefined cap.
- Decay stop: if live Sharpe decays > 50% versus paper Sharpe, stop and
  postmortem.

---

## 6. Incident response

| Trigger | Automated action | Operator action |
| ------- | ---------------- | --------------- |
| Pre-trade limit breach | Day's orders blocked; incident recorded | Review the breaching pair; resize or drop it |
| Daily loss > 5% | Kill switch halts trading | Flatten if needed; investigate before resuming |
| Monthly drawdown > 10% | Kill switch halts trading | Full review; do not resume same day |
| Spread divergence z > 3.5 | Critical alert | Consider closing the pair (cointegration may have broken) |
| One execution leg fails | Both legs cancelled | Re-evaluate; do not leg in manually |

Resuming after a halt is a deliberate manual decision, never automatic.

---

## 7. What is pending (operationally gated, not code)

These cannot be completed in a build session; they require elapsed time and a
live account:

- **4.9 Paper trading:** the genuine >= 90 calendar-day paper run on the IBKR
  paper account. The harness, monitoring and promotion logic are code-complete
  and tested; the run itself is a wall-clock milestone.
- **4.10 Live trading:** begins only after the 4.9 promotion gate passes. It is a
  capital-allocation decision.
- **IBKR paper adapter wiring:** the `FillModel` seam in
  `core_trading/ops/pairs_paper_trading.py` is broker-agnostic and defaults to a
  deterministic simulator; connecting it to the live IBKR paper account is a thin
  adapter to implement when the paper run starts.

Until 4.9 and 4.10 complete, the Phase 4 Definition of Done in the master plan
remains open on those two checkboxes by design.
