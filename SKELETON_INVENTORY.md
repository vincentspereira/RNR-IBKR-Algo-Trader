# Skeleton / Incomplete Code Inventory

**Generated:** 2026-05-21
**Scope:** `core_trading/`, `services/`, `libs/`

## Summary Table

| Category | Count | Severity | Top Directory |
|----------|-------|----------|---|
| Gutted Files (commented-out bodies) | 13 | CRITICAL | `core_trading/adapters/brokers/` |
| `NotImplementedError` (non-ABC) | 11 | MEDIUM | `libs/common/events/` |
| Bare `pass` bodies | 30+ | LOW (most are ABCs) | `core_trading/adapters/base.py` |
| TODO/FIXME/XXX/HACK markers | 143 | HIGH | `core_trading/strategies/` (87) |
| Empty modules | ~5 | LOW | `libs/common/` |
| Skeleton classes (docstring only) | 15-20 | CRITICAL | `core_trading/adapters/brokers/` |

## 1. Gutted Files (Top 10)

All show the same automated-uncommenting damage your global CLAUDE.md describes. Per your rules, these should be **rewritten from scratch** preserving logic — not piecemeal repaired.

1. `core_trading/adapters/brokers/interactive_brokers.py:18` — `class InteractiveBrokersAdapter:` body entirely commented; references handler modules that may not exist.
2. `core_trading/adapters/brokers/alpaca.py:18` — identical pattern.
3. `core_trading/adapters/brokers/binance.py:18` — 514 commented lines.
4. `core_trading/adapters/brokers/coinbase.py:18` — blank class + handler scaffolding only.
5. `core_trading/adapters/brokers/oanda.py:18` — 529 commented lines.
6. `core_trading/adapters/brokers/fxcm.py:18` — 446 commented lines.
7. `core_trading/adapters/brokers/trading212.py:18` — 376 commented lines.
8. `core_trading/engines/smart_money_engine/core.py:9` — `class Core:` with 41 `# TODO: Implement extracted method logic` markers.
9. `core_trading/strategies/architecture/pillars/core.py:9` — `class Core:` with 27 of the same markers.
10. `core_trading/data_feeds/tests/test_pipeline_core.py:119` — security-gutted test methods (`# DANGEROUS: exec() removed`).

**Pattern:** 8 broker adapters in `core_trading/adapters/brokers/` share identical scaffolding — they were all refactored simultaneously and the refactor was not completed. The "working" IBKR adapter lives at `core_trading/adapters/ibkr_adapter.py`, not in `brokers/`.

## 2. NotImplementedError (intentional Phase 5 stubs)

- `libs/common/events/serializers.py:64` — `AvroSerializer.serialize()` — "will be implemented in Phase 5"
- `libs/common/events/serializers.py:78` — `AvroSerializer.deserialize()` — Phase 5
- Most others are commented out inside gutted code (don't actually raise).

## 3. Bare `pass` bodies — mostly acceptable

The 17 consecutive `pass` bodies in `core_trading/adapters/base.py:189-283` are abstract methods on `BaseBrokerAdapter` / `BaseDataFeedAdapter` — this is correct Python ABC style. Not a code-quality issue.

## 4. Top TODO Markers

Most concerning (production-relevant):

1. `services/trading-engine/src/main.py:20` — "TODO: Connect to Kafka"
2. `services/trading-engine/src/main.py:24` — "TODO: Connect to IBKR"
3. `libs/common/events/serializers.py:50` — "TODO: Initialize Schema Registry client"
4. `core_trading/data_feeds/tests/test_pipeline_core.py:119, 128, 141, 157` — "TODO: Replace with safe alternatives" (4 instances of removed `eval`/`exec`)
5. `core_trading/data_feeds/tests/test_enhanced_pipeline.py:123, 132, 145, 161` — Same security-gutting pattern (4 more)

Bulk TODO count by directory:
- `core_trading/engines/smart_money_engine/core.py` — 41 TODOs
- `core_trading/strategies/architecture/pillars/core.py` — 27 TODOs
- `core_trading/strategies/backtesting/core.py` — 30 TODOs
- `core_trading/strategies/volatility_breakout/core.py` — 26 TODOs

These four files alone account for 124 of the 143 total TODOs.

## 5. Key Conclusions

1. **Broker adapter refactoring is half-done.** All 8 broker adapters in `core_trading/adapters/brokers/` are gutted shells. The real, working IBKR adapter is `core_trading/adapters/ibkr_adapter.py`. The gutted files should be archived and deleted.

2. **"God class extraction" pattern incomplete.** Smart Money Engine and Architecture Pillars show ~70 TODO markers from an unfinished method-extraction refactor.

3. **Security-gutted tests.** 8 test methods had `eval()`/`exec()` removed with "TODO: Replace with safe alternatives" — tests cannot pass until these are rewritten using `ast.literal_eval()` or removed entirely.

4. **Phase 5 placeholders OK.** Avro serialization stubs are intentional and documented.

5. **No active runtime risk.** Most damage is in commented-out code that fails on import — services would refuse to start rather than execute broken logic. So nothing dangerous is *running*, but nothing useful is either.
