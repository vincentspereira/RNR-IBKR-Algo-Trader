# Broker Adapter Roadmap

**Status:** IBKR is the sole canonical broker. All other adapters are
**deliberately deferred roadmap markers**, not stubs in the misleading-code
sense -- each raises a clear, informative error directing the caller to
`IBKRAdapter`. This document satisfies the Phase 0.5 No-Stubs Policy exception
(master plan section 0.5, Category E): the markers are tracked here as deferred
work instead of masquerading as implemented code.

**Decision (2026-05-21, operator):** keep the non-IBKR adapters as roadmap
markers; do not pre-emptively restore or implement them. IBKR alone backs the
paper-trading and initial live phases. Implement another broker only when a
concrete use case demands it (e.g. "I want to trade crypto on Coinbase").

---

## Canonical broker

| Broker | Module | State |
| ------ | ------ | ----- |
| Interactive Brokers (IBKR) | `core_trading/adapters/ibkr_adapter.py` | Canonical. Backs Phase 4 paper trading and Phase 10+ live trading. |

## Deferred adapters (implement in this order, only when needed)

| # | Broker | Asset focus | Restore / build path | SDK license | Priority |
| - | ------ | ----------- | -------------------- | ----------- | -------- |
| 1 | Alpaca | US equities + crypto, commission-free | Working `.backup` at `.archive/2026-05-21_dead_adapters/brokers/alpaca.py.backup` | Apache-2.0 (MAS-safe) | HIGH -- complements IBKR for US equities |
| 2 | Coinbase | Crypto | Working `.backup` archived (same dir) | Apache-2.0 (MAS-safe) | MEDIUM -- if crypto strategies emerge |
| 3 | Binance | Crypto | Rewrite using `python-binance` | MIT | MEDIUM |
| 4 | OANDA | Forex / CFD | Rewrite using `oandapyV20` | MIT | LOW |
| 5 | Saxo | Multi-asset (Europe) | Not started | -- | LOW |
| 6 | Tradier | US options data | Not started | -- | LOW -- when options strategies mature |
| 7 | FXCM | Forex / CFD | `core_trading/adapters/brokers/fxcm.py` marker | Unclear -- verify before MAS lift | LOW |
| 8 | Trading212 | EU equities / CFD | `core_trading/adapters/brokers/trading212.py` marker | No official API (reverse-engineered) | LOWEST |

## Rules

- **Do not** start any non-IBKR adapter until the IBKR paper-trading loop is
  verified end-to-end (Phase 4.9 / Phase 11).
- When adding any non-IBKR broker, check the SDK license against the MAS
  commercial roadmap before lifting any code into that product. AGPL/GPL code
  from this repo must never enter MAS.
- The `core_trading/adapters/brokers/README.md` describes aspirational scope;
  **this file is the source of truth** for what is actually supported.

## Current marker modules (deferred, not implemented)

`core_trading/adapters/brokers/`: `alpaca.py`, `binance.py`, `coinbase.py`,
`fxcm.py`, `oanda.py`, `trading212.py`, `interactive_brokers.py` (legacy shim;
the canonical adapter is `core_trading/adapters/ibkr_adapter.py`). Each is an
informative roadmap marker, documented as deferred here per Phase 0.5.E.
