# Phase 1 Operator Runbook -- Data Layer Bring-Up

**Last updated:** 2026-06-04
**Audience:** the operator (Vincent) bringing the Phase 1 data layer from
"code complete" to "live and validated". Every step here is manual by design:
these are the items that code cannot do for you (run Docker, log into TWS,
pay for data).

The Phase 1 *code* is complete and tested offline (adapters, storage, quality
gate, universe API, ingestion CLI). What remains is operational: running the
infrastructure and feeding it. This runbook is the checklist.

---

## 0. Prerequisites

| Requirement | Why | Check |
| --- | --- | --- |
| Docker Desktop running | ClickHouse + Grafana containers | `docker info` |
| Python 3.12 venv at `.venv` | all CLI commands below | `.venv/bin/python --version` |
| (optional) IBKR TWS or Gateway, paper login | IBKR bar source + cross-validation | TWS running, API enabled on port 7497 |

ASCII note: all CLI output is plain ASCII (terminal-portable).

---

## 1. Bring up storage + dashboards

```bash
# From the repo root. Starts ClickHouse, Prometheus, Grafana 9.5.x, etc.
docker compose up -d clickhouse grafana prometheus
docker ps   # all three should be healthy after ~30s
```

* Grafana: http://localhost:3001 (admin / $GRAFANA_ADMIN_PASSWORD, default `admin`).
* The **Data Quality -- Market Data Bars** dashboard is provisioned
  automatically from `infrastructure/grafana/dashboards/data-quality.json`.
  It will be empty until step 2 has run.
* ClickHouse schema: `infrastructure/clickhouse/init/01-create-market-data-tables.sql`
  runs on first container start; the ingestion path also creates the table on
  first write (`CREATE TABLE IF NOT EXISTS`), so ordering does not matter.

---

## 2. Ingest 5 years of daily bars (free source)

```bash
# Smoke test first: fetch + validate two symbols, do not store
.venv/bin/python -m core_trading.data.ingest --symbols AAPL,MSFT --years 1 --dry-run

# The real run: S&P 100, 5 years of daily bars, validated and stored
.venv/bin/python -m core_trading.data.ingest --universe SP100 --years 5
```

Exit codes: `0` OK; `1` quality gate failed (read the `[ERROR]`/`[WARN]`
lines); `2` the fetch returned nothing (vendor outage or symbology problem).

The quality gate is `core_trading/data/quality.py::validate_bar_frame` -- the
same checks the dashboard visualises: high < low, negative volume, duplicate
rows, all-zero closes, >10-sigma price spikes, timestamp gaps.

Re-running the command is **idempotent**: storage is a `ReplacingMergeTree`
keyed on `(symbol, resolution, timestamp)`, so overlapping windows do not
duplicate rows.

Other built-in universes: `NDX` (Nasdaq-100), `NIFTY50`.

---

## 3. Verify on the dashboard

Open Grafana -> **Data Quality -- Market Data Bars** and check:

1. **History span** stat is green (>= 1825 days).
2. **Structural violations** stat is 0 (green).
3. **Coverage** timeseries shows ~100 symbols on every trading day with no
   unexplained dips.
4. **Freshness** table: every symbol < 72h stale after a fresh run.

If a symbol is missing or short (see "Per-symbol bar counts"): yfinance
symbology differs occasionally (e.g. `BRK-B`); fix the symbol in
`core_trading/data/universe.py` or ingest it explicitly with `--symbols`.

---

## 4. IBKR cross-validation (optional but recommended)

With TWS running (paper account, API enabled, port 7497):

```bash
# Pull the same window from IBKR for a sample and store it
.venv/bin/python -m core_trading.data.ingest --symbols AAPL,MSFT,SPY --years 1 --source ibkr
```

* The bars land with `source='ibkr'` next to the yfinance rows -- the
  "Rows ingested per day by source" dashboard panel shows both.
* Programmatic comparison: `core_trading.data.quality.cross_source_compare`
  flags closes differing by more than 5 bps between the two sources.
* Connection settings come from `IBKR_HOST` / `IBKR_PORT` env vars
  (default `127.0.0.1:7497`). The data session uses client id 7, distinct
  from the trading adapter, so it can run alongside paper trading.

---

## 5. Daily top-up

After the initial backfill, a daily run keeps the store current:

```bash
.venv/bin/python -m core_trading.data.ingest --universe SP100 --years 0.1
```

(36 days re-fetched; idempotent storage dedups the overlap.) Schedule via
cron at ~23:00 UTC after the US close if desired.

---

## 6. Known limitations / the paid-data upgrade path

These are **data-cost decisions**, deliberately left to the operator:

| Gap | Impact | Fix | Cost |
| --- | --- | --- | --- |
| Survivorship bias: built-in universes are static snapshots (2026-05-28), no delisted names | Long-horizon cross-sectional backtests overstate returns | Norgate Data (full US vintage membership) via a `UniverseSource` adapter; Tiingo free tier covers some delisted US tickers | Norgate ~USD 300-500/yr; Tiingo free |
| yfinance is not point-in-time and occasionally restates | Research-grade only; cross-validate vs IBKR before trusting any anomaly | Keep IBKR as the verification source; promote IBKR or a paid vendor to primary before live | included w/ brokerage |
| No tick / L2 history | Microstructure signals (OBI, VPIN) stay deferred (see master plan 5.E) | IBKR tick-by-tick recording forward-only, or Polygon/Databento history | Polygon ~USD 200/mo |
| Macro (FRED) needs an API key | `fred_source` adapter idle until then | Free key at fred.stlouisfed.org, set `FRED_API_KEY` | free |

None of these block Phase 6 (portfolio construction research on daily bars).

---

## 7. Troubleshooting

* **`stored 0 rows` with ClickHouse running** -- the Python clickhouse client
  could not connect. Check `docker logs trading-clickhouse`, then
  `CLICKHOUSE_PASSWORD` env consistency between compose and your shell.
* **yfinance rate-limit / empty frames** -- transient; rerun. Persistent
  empties for one symbol = symbology drift; check the ticker on finance.yahoo.com.
* **IBKR `error 162` (pacing)** -- the adapter requests sequentially, but
  5 years x 100 symbols on IBKR will pace-limit; use yfinance for bulk
  history, IBKR for verification samples.
* **Grafana dashboard empty but data exists** -- check the ClickHouse
  datasource health in Grafana (Configuration -> Data sources). The
  provisioned datasource expects the `grafana-clickhouse-datasource` plugin
  (installed automatically via `GF_INSTALL_PLUGINS`).
* **TWS smoke test (paper trading gate)** -- see `HANDOVER.md` for the
  manual TWS setup + first paper order checklist.
