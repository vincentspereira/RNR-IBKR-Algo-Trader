# Broker Adapters

> **TL;DR:** The only real broker in this directory tree is
> `core_trading/adapters/ibkr_adapter.py` (located one level above this
> directory). Everything inside this `brokers/` subpackage -- except
> `rate_limiting.py` -- is a roadmap marker.

## What lives where

### Real, working implementations

| Module | Purpose |
|---|---|
| `../ibkr_adapter.py` | Canonical IBKR broker adapter (`IBKRAdapter`). Used for paper and live trading. |
| `rate_limiting.py` | Token bucket / sliding window / circuit breaker. Imported by `core_trading/data_feeds/ibkr_data_feed.py`. |

### Roadmap markers (not implemented)

All of these raise `NotImplementedError` on use. Each docstring records the
planned SDK, license, asset classes, and priority. The canonical priority
list lives in the `project-broker-roadmap` memory and in
`PRODUCTION_PUNCH_LIST.md`.

| Module | Planned scope |
|---|---|
| `alpaca.py` | US equities + crypto via `alpaca-py` (Apache-2.0). HIGH priority. |
| `binance.py` | Crypto spot + futures via `python-binance` (MIT). MEDIUM. |
| `coinbase.py` | Crypto via `coinbase-advanced-py` (Apache-2.0). MEDIUM. |
| `oanda.py` | Forex/CFD via `oandapyV20` (MIT). LOW. |
| `fxcm.py` | Forex/CFD via `fxcmpy` (license unclear). LOW. |
| `trading212.py` | EU equities/CFD; no official API. LOWEST. |
| `interactive_brokers.py` | Historical duplicate of canonical adapter. Use `core_trading.adapters.ibkr_adapter.IBKRAdapter` instead. |
| `factory.py` | Multi-broker dispatch. Unnecessary while IBKR is the only canonical broker. |
| `error_handling.py` | Shared error-handling layer. |
| `config_validation.py` | Shared config-validation layer. |
| `health_monitoring.py` | Shared health-monitoring layer. |
| `security.py` | Shared auth/credential layer. |
| `websocket_streaming.py` | Shared WebSocket streaming layer. |

## Why are the roadmap markers kept here?

Two reasons:

1. **Honest signalling of intent.** The user has explicitly opted to keep
   these stubs as roadmap markers rather than delete them, so the directory
   tree reflects the planned multi-broker scope rather than just the
   currently-shipped scope.
2. **Loud failures.** Each stub raises `NotImplementedError` rather than
   silently doing nothing. Anything that accidentally imports and uses one
   will fail noisily at the point of misuse.

If the placeholders are causing confusion, they can all be archived to
`.archive/<date>_dead_adapters/` with no impact on the IBKR loop.

## Reviving a placeholder

When a real implementation is needed:

1. Check the matching `.archive/2026-05-21_dead_adapters/brokers/<name>.py.backup`
   for the pre-refactor working code if one exists (alpaca, coinbase,
   interactive_brokers, websocket_streaming).
2. Validate the SDK license against the MAS licensing roadmap (see
   `project-license-decisions` memory).
3. Replace the stub in-place; do not introduce parallel files.
4. Wire into `ExecutionEngine` via the `broker_adapter` constructor argument
   (the same pattern `IBKRAdapter` uses today).
