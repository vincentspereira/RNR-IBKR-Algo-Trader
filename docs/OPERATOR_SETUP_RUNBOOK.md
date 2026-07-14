# Operator Setup Runbook -- Bring-Up to Paper Trading

**Last updated:** 2026-06-09
**Audience:** the operator (Vincent), taking the system from "code complete" to
"running, monitored, and paper trading on IBKR".

This is the **single runnable checklist** for the operational steps that code
cannot do for you: rotate credentials, run Docker, ingest data, verify the
dashboard, connect TWS, schedule the daily jobs, and rehearse the kill switch.
Every command is copy-pasteable bash from the repo root. All CLI output
is plain ASCII (terminal-portable).

> Scope note. This runbook gets the *infrastructure and plumbing* live. It does
> NOT pick a strategy. As of 2026-06-09 there is no validated paper-trading
> occupant (the pairs pilot was REJECTED; the rsi2/trend candidate is pending
> survivorship-bias-free validation -- see `docs/STRATEGY_SWEEP_2026-06.md` and
> the go/no-go memo). Sections 1-7 are safe to do now; Section 8 (start the
> 90-day clock) waits on a strategy clearing the gate.

Time budget: ~2-4 focused hours for sections 0-6, then the data backfill runs
unattended (~30-60 min), then the 90-day paper clock is wall-clock.

---

## 0. Prerequisites

| Requirement | Why | Check |
| --- | --- | --- |
| Docker Desktop running | ClickHouse + Grafana + Prometheus | `docker info` |
| Python 3.12 venv at `.venv` | every CLI command below | `.venv/bin/python --version` |
| IBKR TWS (paper login), API enabled, port 7497 | broker connectivity | TWS running, "Enable ActiveX and Socket Clients" on |
| Git clean working tree | so you can `git diff` your config changes | `git status` |

If Python 3.12 is not the venv interpreter, stop and fix that first.
On WSL2/Ubuntu the system Python is 3.12.3 (ideal). Recreate the venv with
`python3.12 -m venv .venv` (a Windows `.venv\Scripts\` venv is NOT portable
to Linux -- see memory `project_python_deps_state.md`).

---

## 1. Credential rotation and hygiene (DO THIS FIRST)

Background: on 2026-05-21 a real IBKR paper account ID was committed to git and
the paper password sat in `.env` cleartext (memory `project_credential_incident.md`).
The hardcoded ID was removed from source, but **the password must be rotated**
and a clean `.env` established before anything connects to IBKR.

### 1.1 Rotate the IBKR paper password

1. Log into IBKR Client Portal -> Settings -> User -> change the paper-trading
   password.
2. This invalidates the value that was previously in cleartext.

### 1.2 Establish a clean `.env`

```bash
# Create your private .env from the template (never commit it)
cp .env.example .env

# Confirm .env is gitignored (should print a match)
git check-ignore .env
```

Edit `.env` and set, at minimum, the live-trading-relevant block:

```
IBKR_USERNAME=<your paper username>
IBKR_PASSWORD=<the NEW rotated password>
IBKR_ACCOUNT_ID=<your DU... paper account id>
IBKR_TRADING_MODE=paper          # keep 'paper' until the 90-day gate is met
IBKR_HOST=127.0.0.1
IBKR_PORT=7497                    # 7497 paper, 7496 live
FEATURE_LIVE_TRADING_ENABLED=false   # flip to true only after the go-live gate
```

Also change every `ChangeMeInProduction123!` database password and set
`GRAFANA_ADMIN_PASSWORD` to something non-default.

### 1.3 Verify no secret is hardcoded in tracked source

```bash
# Should return NOTHING. If it prints a real DU/U account id, stop and scrub it.
git grep -nE "DU[0-9]{6,}|U[0-9]{6,}" -- "*.py" | grep -v "DU_TEST_ACCOUNT"

# Confirm the no-stubs / hygiene gate is green
.venv/bin/python tools/check_no_stubs.py
```

Expected: `[no_stubs] OK -- no violations detected`.

### 1.4 (Optional, recommended) Secrets manager

For a single-operator box, a gitignored `.env` with rotated values is the
practical baseline. If you later host this off-laptop, move IBKR + DB secrets
into a secrets manager (Vault / cloud) and load them as env vars at process
start -- never back into tracked files. This is the §4.2 production item from
the master plan; it is not required to begin paper trading on localhost.

---

## 2. Bring up storage + dashboards

```bash
# Starts ClickHouse, Grafana 9.5.x, Prometheus
docker compose up -d clickhouse grafana prometheus
docker ps    # all three healthy after ~30s
```

* Grafana: http://localhost:3001  (admin / $GRAFANA_ADMIN_PASSWORD)
* The **Data Quality -- Market Data Bars** dashboard auto-provisions from
  `infrastructure/grafana/dashboards/data-quality.json` (empty until step 3).
* ClickHouse schema auto-creates on first container start AND on first write
  (`CREATE TABLE IF NOT EXISTS`), so ordering does not matter.

Troubleshooting: if a container is unhealthy, `docker logs trading-clickhouse`
/ `docker logs <grafana container>`; check `CLICKHOUSE_PASSWORD` is consistent
between `.env` and your shell.

---

## 3. Ingest 5 years of daily bars (free source)

```bash
# Smoke test: fetch + validate two symbols, store nothing
.venv/bin/python -m core_trading.data.ingest --symbols AAPL,MSFT --years 1 --dry-run

# Real backfill: S&P 100, 5 years daily, validated + stored (idempotent)
.venv/bin/python -m core_trading.data.ingest --universe SP100 --years 5
```

Exit codes: `0` OK; `1` quality gate failed (read the `[ERROR]`/`[WARN]`
lines); `2` fetch returned nothing (vendor outage / symbology).

Storage is a `ReplacingMergeTree` keyed on `(symbol, resolution, timestamp)`,
so re-runs and overlapping windows never duplicate rows. Other built-in
universes: `NDX`, `NIFTY50`.

(Full detail and per-symbol troubleshooting: `docs/PHASE1_OPERATOR_RUNBOOK.md`.)

---

## 4. Verify on the dashboard

Open Grafana -> **Data Quality -- Market Data Bars**:

1. **History span** stat green (>= 1825 days).
2. **Structural violations** stat is 0 (green).
3. **Coverage** shows ~100 symbols every trading day, no unexplained dips.
4. **Freshness** table: every symbol < 72h stale after a fresh run.

The master plan's pre-paper gate (§10.0) wants this dashboard **green for 14
consecutive days** before trading. The daily top-up job (Section 6) keeps it
fresh so that clock can run.

---

## 5. IBKR TWS connectivity + paper smoke test

With TWS running (paper account, API enabled, port 7497):

```bash
# Cross-validate data: pull a sample from IBKR alongside the yfinance rows
.venv/bin/python -m core_trading.data.ingest --symbols AAPL,MSFT,SPY --years 1 --source ibkr
```

The data session uses client id 7, distinct from the trading adapter, so it can
run alongside paper trading. `core_trading.data.quality.cross_source_compare`
flags closes differing > 5 bps between sources.

**Order round-trip smoke test:** the AAPL paper round trip was validated
2026-06-05 (memory `project_paper_trading_blockers.md`). To re-confirm after any
adapter or TWS change, follow the TWS setup + first-paper-order checklist in
`HANDOVER.md`. A clean smoke test = adapter connects (no silent simulation
fallback), order acks, fills, and the position reconciles.

---

## 6. Schedule the daily jobs (cron)

Three unattended jobs. Run each command once interactively first to confirm it
works, then add each as a cron job (`crontab -e`) running the venv python from
the repo root, e.g. `0 23 * * 1-5 .venv/bin/python -m core_trading.data.ingest --universe SP100 --years 0.1`.

```bash
# 6.1 Daily data top-up (run ~23:00 UTC, after US close). 36 days re-fetched, dedup'd.
.venv/bin/python -m core_trading.data.ingest --universe SP100 --years 0.1

# 6.2 Daily risk report (VaR/ES + stress + liquidity)
.venv/bin/python -m core_trading.risk.daily_report --output logs/risk/risk_$(date +%Y%m%d).md

# 6.3 Daily TCA report (once trading; --demo proves the pipeline pre-trade)
.venv/bin/python -m core_trading.execution.tca --demo
```

A daily-reports cron job already exists per memory
(`project_paper_trading_blockers.md`); confirm it points at the venv python and the current repo path,
and add 6.1/6.3 if missing (the Windows Task Scheduler entries do not exist on
WSL2 -- recreate them as cron jobs). `tools/daily_ops.py` is the
pre-market/post-market ops driver (data freshness, connectivity, reconciliation).

### 6.4 TAQuant paper book -- the 90-day clock (REGISTERED 2026-06-10)

A cron job (formerly the Windows task `IBKR-AlgoTrader TAQuant Paper Run`) runs `tools/taquant_paper_run.py`
weekdays at 20:30 UK (~15:30 ET) and appends to
`logs/taquant_paper/<slot>/`. Two slots, separate ledgers, kill switches
and promotion gates (decision record
`docs/GO_NO_GO_RSI2_TREND_SURVIVORSHIP_2026-06-10.md`): `rsi2t15_trend200`
(SP100) and `rsi2t10_trend200_volt10` (SP100, vol-targeted). TWS paper must
be running and logged in at 20:30 UK or the day records as SKIPPED
(stretches the calendar, never corrupts the ledger).

The memo's third slot (`rsi2t10_calm75` on US ETFs) is **PARKED**: IBKR
rejects US-domiciled ETFs for UK retail accounts under PRIIPs ("no KID",
error 201 -- discovered via live paper rejections 2026-06-10). Restoring it
requires the UCITS port (see the task list); single stocks are unaffected.

```bash
# daily ops
.venv/bin/python tools/taquant_paper_run.py --status
.venv/bin/python tools/taquant_paper_run.py --reset-halt --slot <slot>
tail -n 50 logs/taquant_paper/scheduler.log
```

Known symbol quirks (handled in `tools/pairs_paper_run.py`): BNY Mellon is
`BK` canonically/Yahoo but `BNY` at IBKR (alias map); WBA was delisted and
removed from the static SP100 list 2026-06-10.

### 6.5 Dashboards (added 2026-06-10)

Two views over the same ledgers, both read-only:

```bash
# Live web dashboard (auto-refreshes every 5s; Ctrl+C to stop)
.venv/bin/python tools/dashboard_server.py     # -> http://127.0.0.1:8642

# Static HTML report (auto-regenerated after every live paper run)
xdg-open logs/paper_report.html
```

Both show every book (daily slots, intraday lane, pairs) automatically:
equity curve, total return, max drawdown, paper Sharpe, gross leverage,
positions, recent orders/fills, kill-switch state, incidents, and 90-day
promotion progress. The web dashboard never connects to TWS, so it can run
permanently without burning a client id.

### 6.6 Intraday experimental lane (added 2026-06-10)

`tools/intraday_paper_run.py` trades the same three rsi2 configs on signal
CHANGES during the session, using IBKR delayed quotes (free on paper, ~15
min behind), instead of waiting for the close. Separate ledgers under
`logs/intraday_paper/<slot>/`, smaller equity (10k/slot), order budget and
churn guard.

**This lane is an experiment, not the validated clock.** The research
result that justified paper trading is signal-on-close execution; this lane
exists to measure -- with data, after 90 days -- whether intraday execution
helps or hurts. Never read its results into the daily slots' promotion.

```bash
# one tick (smoke test), full session loop, status
.venv/bin/python tools/intraday_paper_run.py --once --slot rsi2t10_calm75
.venv/bin/python tools/intraday_paper_run.py            # loops until 15:55 ET
.venv/bin/python tools/intraday_paper_run.py --status
```

A cron job (weekdays 14:50 UK) starts the session loop; the process exits by
itself at 15:55 ET. (Recreate the Windows Task Scheduler entry as a cron job.)

### 6.7 Strategy lab (added 2026-06-10)

Author and evaluate your own strategies against the SAME validation bar the
production candidates cleared:

```bash
.venv/bin/python tools/strategy_lab.py list
.venv/bin/python tools/strategy_lab.py chart    --config rsi2t15_trend200 --universe etf
.venv/bin/python tools/strategy_lab.py backtest --config rsi2t15_trend200 --universe sp500pit
.venv/bin/python tools/strategy_lab.py backtest --custom examples/custom_strategy_example.py
```

`chart` writes an interactive HTML (prices + entry/exit markers + equity +
drawdown) to `logs/strategy_lab/`. `backtest` runs the full 2005+
walk-forward and the robustness battery, deflating against the saved trial
bank of the chosen universe (your idea is judged as the N+1-th trial).
Promotion path: PASS on `sp500pit` -> add a slot in
`tools/taquant_paper_run.py` -> 90-day paper gate -> live.

---

## 7. Kill-switch drill

The kill switch is non-negotiable and must be rehearsed before any capital is at
risk. It lives in the pre-trade gate (`core_trading/risk/pretrade.py`) and the
paper-trading driver (`core_trading/ops/pairs_paper_trading.py`); the runner
exposes it operationally:

```bash
# Halt: clear/raise via the runner's controls
.venv/bin/python tools/pairs_paper_run.py --status         # show ledger + halt state
.venv/bin/python tools/pairs_paper_run.py --reset-halt     # clear the kill switch after review
```

Drill monthly: trip the switch, confirm no new orders are admitted by the
pre-trade gate, then `--reset-halt` and confirm normal operation resumes.
Target latency from command to "no new orders" is < 5s (master plan §10.0).

---

## 8. Start the 90-day paper clock (GATED -- needs a validated strategy)

Do NOT start this until a strategy clears robustness validation on clean data.
As of 2026-06-09 the pairs pilot is REJECTED and rsi2/trend is pending Norgate
survivorship validation. When a strategy passes:

```bash
# Dry run first: compute and print orders, place/persist nothing
.venv/bin/python tools/pairs_paper_run.py --dry-run

# Live paper run (places paper orders via TWS, persists the ledger)
.venv/bin/python tools/pairs_paper_run.py --equity 25000
```

The runner is generic across strategies via the Strategy seam (the `pairs_`
prefix is historical). Schedule the live run daily alongside Section 6.

### Go-live gate (master plan §11.3 -- all must hold over 90 calendar days)

1. Realised Sharpe >= 0.6 x backtest Sharpe (within 1 SE)
2. Realised max drawdown <= 1.5 x backtest max drawdown
3. Trade count within +/-30% of backtest expectation
4. No unhandled exceptions in live monitoring
5. No risk-limit breaches
6. Average slippage <= assumed slippage in backtest
7. Postmortem document approved by you

Only when all 7 hold: set `IBKR_TRADING_MODE=live`, `IBKR_PORT=7496`,
`FEATURE_LIVE_TRADING_ENABLED=true`, start at $5K-10K (master plan §12.1), same
code path.

---

## 9. The one paid-data decision (do before trusting the strategy memo)

| Gap | Impact | Fix | Cost |
| --- | --- | --- | --- |
| Survivorship bias: built-in universes are static 2026-05-28 snapshots, no delisted names | Long-horizon cross-sectional backtests overstate returns -- this is exactly why every sweep verdict is an "upper bound" | Norgate Data (point-in-time US membership) via a `UniverseSource` adapter | ~USD 300-500/yr |
| No tick / L2 history | Microstructure signals (OBI, VPIN) stay deferred | IBKR tick recording (forward) or Polygon/Databento (history) | Polygon ~USD 200/mo |
| Macro (FRED) needs a key | `fred_source` idle | free key at fred.stlouisfed.org -> `FRED_API_KEY` | free |

Norgate is the single highest-leverage spend: it converts the strategy sweep
from "upper bound pending survivorship correction" into a decisive go/no-go.

---

## Quick reference -- daily operator loop (once paper trading)

```bash
# pre-market: data fresh? broker up? positions reconciled?
.venv/bin/python tools/daily_ops.py
# intraday: monitor Grafana PnL/risk panels; trip kill switch on anomaly
# post-market: risk report + TCA + reconciliation auto-run via cron
.venv/bin/python tools/pairs_paper_run.py --status
```
