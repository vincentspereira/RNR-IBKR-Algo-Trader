# Operator Setup Runbook -- Bring-Up to Paper Trading

**Last updated:** 2026-06-09
**Audience:** the operator (Vincent), taking the system from "code complete" to
"running, monitored, and paper trading on IBKR".

This is the **single runnable checklist** for the operational steps that code
cannot do for you: rotate credentials, run Docker, ingest data, verify the
dashboard, connect TWS, schedule the daily jobs, and rehearse the kill switch.
Every command is copy-pasteable PowerShell from the repo root. All CLI output
is plain ASCII (Windows cp1252-safe).

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
| Python 3.12 venv at `.venv` | every CLI command below | `./.venv/Scripts/python.exe --version` |
| IBKR TWS (paper login), API enabled, port 7497 | broker connectivity | TWS running, "Enable ActiveX and Socket Clients" on |
| Git clean working tree | so you can `git diff` your config changes | `git status` |

If Python 3.12 is not the venv interpreter, stop and fix that first (system
Python is 3.14, too new for the pinned deps -- see memory
`project_python_deps_state.md`).

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

```powershell
# Create your private .env from the template (never commit it)
Copy-Item .env.example .env

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

```powershell
# Should return NOTHING. If it prints a real DU/U account id, stop and scrub it.
git grep -nE "DU[0-9]{6,}|U[0-9]{6,}" -- "*.py" | Select-String -NotMatch "DU_TEST_ACCOUNT"

# Confirm the no-stubs / hygiene gate is green
./.venv/Scripts/python.exe tools/check_no_stubs.py
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

```powershell
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

```powershell
# Smoke test: fetch + validate two symbols, store nothing
./.venv/Scripts/python.exe -m core_trading.data.ingest --symbols AAPL,MSFT --years 1 --dry-run

# Real backfill: S&P 100, 5 years daily, validated + stored (idempotent)
./.venv/Scripts/python.exe -m core_trading.data.ingest --universe SP100 --years 5
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

```powershell
# Cross-validate data: pull a sample from IBKR alongside the yfinance rows
./.venv/Scripts/python.exe -m core_trading.data.ingest --symbols AAPL,MSFT,SPY --years 1 --source ibkr
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

## 6. Schedule the daily jobs (Windows Task Scheduler)

Three unattended jobs. Run each command once interactively first to confirm it
works, then wrap in a Task Scheduler action (Program: the venv python; Arguments:
the `-m ...`/script path; Start in: the repo root).

```powershell
# 6.1 Daily data top-up (run ~23:00 UTC, after US close). 36 days re-fetched, dedup'd.
./.venv/Scripts/python.exe -m core_trading.data.ingest --universe SP100 --years 0.1

# 6.2 Daily risk report (VaR/ES + stress + liquidity)
./.venv/Scripts/python.exe -m core_trading.risk.daily_report --output logs/risk/risk_$(Get-Date -f yyyyMMdd).md

# 6.3 Daily TCA report (once trading; --demo proves the pipeline pre-trade)
./.venv/Scripts/python.exe -m core_trading.execution.tca --demo
```

A daily-reports Task Scheduler job already exists per memory
(`project_paper_trading_blockers.md`); confirm it points at the venv python and
the current repo path, and add 6.1/6.3 if missing. `tools/daily_ops.py` is the
pre-market/post-market ops driver (data freshness, connectivity, reconciliation).

### 6.4 TAQuant paper book -- the 90-day clock (REGISTERED 2026-06-10)

Task `IBKR-AlgoTrader TAQuant Paper Run` runs `tools/taquant_paper_run.py`
weekdays at 20:30 UK (~15:30 ET) and appends to
`logs/taquant_paper/<slot>/`. Three slots, separate ledgers, kill switches
and promotion gates (decision record
`docs/GO_NO_GO_RSI2_TREND_SURVIVORSHIP_2026-06-10.md`): `rsi2t15_trend200`
(SP100), `rsi2t10_trend200_volt10` (SP100, vol-targeted),
`rsi2t10_calm75` (ETF_CORE). TWS paper must be running and logged in at
20:30 UK or the day records as SKIPPED (stretches the calendar, never
corrupts the ledger).

```powershell
# daily ops
./.venv/Scripts/python.exe tools/taquant_paper_run.py --status
./.venv/Scripts/python.exe tools/taquant_paper_run.py --reset-halt --slot <slot>
Get-Content logs/taquant_paper/scheduler.log -Tail 50
```

Known symbol quirks (handled in `tools/pairs_paper_run.py`): BNY Mellon is
`BK` canonically/Yahoo but `BNY` at IBKR (alias map); WBA was delisted and
removed from the static SP100 list 2026-06-10.

---

## 7. Kill-switch drill

The kill switch is non-negotiable and must be rehearsed before any capital is at
risk. It lives in the pre-trade gate (`core_trading/risk/pretrade.py`) and the
paper-trading driver (`core_trading/ops/pairs_paper_trading.py`); the runner
exposes it operationally:

```powershell
# Halt: clear/raise via the runner's controls
./.venv/Scripts/python.exe tools/pairs_paper_run.py --status         # show ledger + halt state
./.venv/Scripts/python.exe tools/pairs_paper_run.py --reset-halt     # clear the kill switch after review
```

Drill monthly: trip the switch, confirm no new orders are admitted by the
pre-trade gate, then `--reset-halt` and confirm normal operation resumes.
Target latency from command to "no new orders" is < 5s (master plan §10.0).

---

## 8. Start the 90-day paper clock (GATED -- needs a validated strategy)

Do NOT start this until a strategy clears robustness validation on clean data.
As of 2026-06-09 the pairs pilot is REJECTED and rsi2/trend is pending Norgate
survivorship validation. When a strategy passes:

```powershell
# Dry run first: compute and print orders, place/persist nothing
./.venv/Scripts/python.exe tools/pairs_paper_run.py --dry-run

# Live paper run (places paper orders via TWS, persists the ledger)
./.venv/Scripts/python.exe tools/pairs_paper_run.py --equity 25000
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

```powershell
# pre-market: data fresh? broker up? positions reconciled?
./.venv/Scripts/python.exe tools/daily_ops.py
# intraday: monitor Grafana PnL/risk panels; trip kill switch on anomaly
# post-market: risk report + TCA + reconciliation auto-run via Task Scheduler
./.venv/Scripts/python.exe tools/pairs_paper_run.py --status
```
