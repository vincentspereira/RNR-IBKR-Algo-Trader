# Runtime State — RNR-IBKR-Algo-Trader

**Captured:** 2026-05-21
**Host:** Lenovo Legion 5 Pro 16ACH6H (Ryzen 7 5800H, 64 GB RAM, RTX 3060,
Windows 11 with WSL2/Ubuntu 24.04 as the dev environment, 1 TB SSD with 450 GB free)

## Current State (TL;DR)

**The system cannot be started today.** The repository is in a development state, not a runnable state:

- No virtual environment exists (`.venv`, `venv` both absent).
- No project dependencies are installed.
- No Poetry binary found on PATH.
- Docker is running but only with cognee containers — none of this project's services are up.
- TWS Gateway is not running on any standard IBKR port (7497/7496/4002/4001).
- The dependency baseline is inconsistent: `pyproject.toml` declares only foundational libs (Pydantic, FastAPI, DB drivers) while `requirements.txt` declares the full trading stack — they disagree.

## Detailed Observations

### Python

- System Python: **3.14.4** — too new for several pinned trading libs. As of 2026-05-21, `vectorbt`, `tensorflow`, `tf-keras`, `pmdarima`, `zipline-reloaded`, and some QuantLib bindings ship binary wheels for 3.11/3.12 but not yet 3.14. `pyproject.toml` declares `python = "^3.11"` (>= 3.11, < 4.0) which technically permits 3.14, but Poetry's resolver will fail when wheel coverage is missing.
- **Recommendation:** install Python **3.12** (not 3.11 — it's older, and 3.12 has the best wheel coverage right now). Use `pyenv-win` or `python.org` installer side-by-side with 3.14.
- No `poetry` executable found. Need `pip install poetry`.

### Dependency declaration conflict

| File | Declares trading stack? | Build system |
|------|------------------------|--------------|
| `pyproject.toml` | **No** — only Pydantic/FastAPI/DB/Kafka/Auth/Test libs | Poetry |
| `requirements.txt` | **Yes** — full stack (NautilusTrader, VectorBT, ib-insync, TA-Lib, FinRL, PyTorch, LangGraph, etc.) | pip |
| `services/trading-engine/requirements.txt` | `nautilus_trader`, `ib_insync` | pip per-service |
| `services/backtesting-engine/requirements.txt` | `nautilus_trader`, `vectorbt` | pip per-service |
| `services/ai-assistant/requirements.txt` | `langgraph` | pip per-service |
| `services/market-data/requirements.txt` | (need to check) | pip per-service |
| `core_trading/data_feeds/requirements.txt` | `nautilus_trader`, `quantlib` | pip per-service |

This is a real problem. `poetry install` would not give you a working trading environment because Poetry doesn't read `requirements.txt`. You'd need to install both — or unify them.

**Recommendation:** consolidate everything into Poetry groups so `poetry install --with trading` works. Or commit to pure pip and delete `pyproject.toml`'s lock. Pick one.

### Docker

- Engine running (Docker version 29.4.3).
- Running containers belong to cognee-mcp (Valkey, Postgres, Qdrant, Neo4j) — these are tooling, not this project's stack.
- This project's `docker-compose.yml` has not been brought up.
- No project Docker images built.

### IBKR connectivity

- No process listening on any of:
  - 7497 (TWS paper)
  - 7496 (TWS live)
  - 4002 (IB Gateway paper)
  - 4001 (IB Gateway live)
- You must install **either** TWS or **IB Gateway** (Gateway is lighter, recommended for headless/automated). Download from IBKR client portal.
- `.env` has `IBKR_TRADING_MODE=paper`, `IBKR_HOST=127.0.0.1`, `IBKR_PORT=7497` — port 7497 is correct for paper TWS (use 4002 if you choose Gateway instead).

### Configuration & secrets

- `.env` exists (250 lines, populated by you) and is correctly gitignored — verified with `git check-ignore` and `git ls-files`.
- `.env.example` exists (230 lines) — the structure is reasonable.
- Secrets sanity: `git ls-files .env` returned nothing — `.env` is not in git history. Good.
- Recommend you rotate any IBKR credentials in `.env` before doing anything else (since AI tooling has read this directory; the agents I dispatched have not been told to read `.env` but cipher-grade hygiene says rotate anyway).

## Hardware Verdict

Your laptop is **more than sufficient** for paper trading and small-account live trading on this stack:

| Resource | You Have | Paper Trading Needs | Full Stack Needs |
|----------|----------|---------------------|------------------|
| RAM | 64 GB | 8-16 GB | 32-48 GB |
| CPU | Ryzen 7 5800H, 8C/16T | 2-4 cores | 8+ cores |
| GPU | RTX 3060 6 GB (CUDA 11.8) | Not needed | Needed for ML training |
| Disk | 1 TB SSD, 450 GB free | 20 GB | 100-150 GB (databases grow) |

The **real risks** on a laptop are operational, not hardware:

1. **Power & sleep events** — WSL2 runs under the Windows host, which can still
   suspend during a live position. Mitigate on the WINDOWS side (not WSL):
   `powercfg /change standby-timeout-ac 0` in Windows PowerShell, and disable USB
   selective suspend. (Inside WSL itself, `systemd-notify --watchdog` cannot
   prevent host sleep.)
2. **Windows Update reboots** — schedule outside trading hours; set active hours.
3. **Network blips** — IBKR's API drops on routine WAN events. You need a working reconnection manager (the graphify hyperedge says it exists at `core_trading/connections/reconnection_manager.py` — to be verified).
4. **Single point of failure** — laptop dies = positions exposed without monitoring.

### Cost-minimal VPS plan (for later, NOT now)

Only consider VPS once you've completed 90 days of stable paper trading on the laptop. Then:

- **Cheapest option ($4-6/mo):** Hetzner CX22 (Falkenstein DE) — 2 vCPU, 4 GB RAM, 40 GB SSD, 20 TB egress. Latency to IBKR's Frankfurt gateway ~5 ms.
- **US East ($6/mo):** Hetzner Ashburn CPX11, or Contabo Cloud VPS S.
- **Premium ($10-15/mo):** Vultr High Frequency in NJ/Chicago — closer to IBKR's NYC/Chicago datacenters.

Run **only** the IBKR adapter + execution engine + risk gate + a thin journal on the VPS. Keep ClickHouse / Neo4j / ML training / dashboard on the laptop. Stream events between them over a Tailscale tunnel.

**Do not** run the full 28-microservice stack on a VPS. The whole stack assumes 32+ GB RAM and constant data ingestion; a $10/mo VPS will thrash.

## What Needs to Happen Before Paper Trading

In order, blocking items:

1. **Install Python 3.12** alongside 3.14, point Poetry at it (`poetry env use 3.12`).
2. **Unify dependency manifests** — single source of truth.
3. **Install dependencies** — expect ~1.5 GB of wheels; some (TA-Lib) need a C compiler or prebuilt wheel from `https://github.com/cgohlke/talib-build/releases`.
4. **Resolve the 4 critical blockers** (see PRODUCTION_PUNCH_LIST.md once that agent finishes).
5. **Install & run IB Gateway** in paper mode; enable API connections, set socket port to 4002 (or keep TWS on 7497).
6. **Verify** the minimal viable loop: connect → request quote → submit 1-share market order on AAPL → see fill → close position.

Until step 6 passes end-to-end, this system is **not** ready for paper trading.

## What's Actually Solid

To balance the negatives: significant good work exists.

- **Repository hygiene** (Level 3 audit): pre-commit hooks, CODEOWNERS, GitHub templates, CI workflow — all in place.
- **Architecture documentation**: 15 ADRs, 10 Mermaid diagrams, comprehensive README.
- **Shared libraries** (`libs/`): events, logging, tracing, feature flags, metrics — these look real and have tests.
- **Strategy framework** (`core_trading/strategies/`): the abstract base class and signal generation interfaces are well-designed.
- **Multi-account manager**: appears to be a complete, working module (graphify community 12).
- **Audit store**: immutable audit trail design is sound (graphify community 9).
- **Smart Order Router**: cohesion-0.08 module with clear venue scoring (graphify community 15).

The system is **architecturally mature but operationally incomplete**. That's a much better starting position than the reverse.
