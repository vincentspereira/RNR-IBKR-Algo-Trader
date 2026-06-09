# Phase 0.5 gate closure -- legacy strategy archival (2026-06-09)

These 14 files were the residual high-comment-ratio (96-98% commented-out)
legacy strategy shells flagged by `tools/check_no_stubs.py`. They are the
last occupants of the master plan's Phase 0.5 triage buckets C.1 (quant
strategies superseded by `core_trading/signals/`), C.4 (utility helpers
superseded by `core_trading/{risk,research}/`), and the scalping / arbitrage
families whose clean replacements ship in `core_trading/signals/` and
`core_trading/strategies/classical/`.

Per the master plan (sections 0.5.2 / 0.5.6 and the Phase 10 retirement note),
the disposition for these was REPLACE/ARCHIVE once their replacement phases
shipped -- which they have (Phases 5-9 complete). They were verified to have
**zero active importers** in the active tree before archival (the only
internal references were comment lines and the `feature_engineering <-
reinforcement_learning` pair, archived together). The package `__init__.py`
files were already cleaned to avoid eager re-export, so removal is import-safe.

The commented-out source is preserved here and in git history for any future
"unique logic extraction" (the Phase 10 backlog: order-flow / latency
scalping signals, IV/RV vol arbitrage, index tracking, ML feature selection /
RL env, VW mean reversion). Extraction, if pursued, rebuilds cleanly under the
canonical module homes -- it does not un-archive these.

## Files archived

| Original path | Bucket | Clean replacement home |
| ------------- | ------ | ---------------------- |
| strategies/arbitrage/index_arbitrage.py | C.1 | (research backlog) |
| strategies/arbitrage/volatility_arbitrage.py | C.1 | signals/volatility, signals/stochastic/heston |
| strategies/machine_learning/feature_engineering.py | C.1 | signals/ml/feature_importance, research/feature_store |
| strategies/machine_learning/reinforcement_learning.py | C.1 | signals/ml/rl/ |
| strategies/multi_factor/optimized_multi_factor_models.py | C.1 | signals/factors/ |
| strategies/scalping/high_frequency_scalping_strategy.py | C.1 | (research backlog) |
| strategies/scalping/order_flow_scalping_strategy.py | C.1 | signals/microstructure/ |
| strategies/scalping/scalping_strategy.py | C.1 | (research backlog) |
| strategies/scalping/statistical_arbitrage_scalping_strategy.py | C.1 | signals/pairs, signals/factors/pca_factors |
| strategies/tests/test_integration.py | dead test | tests/integration/ |
| strategies/utils/portfolio_level_features.py | C.4 | research/feature_store |
| strategies/utils/risk_management_enhancements.py | C.4 | core_trading/risk/ |
| strategies/utils/signal_processing.py | C.4 | signals/filters/ |
| strategies/volume_weighted/vw_mean_reversion_strategies.py | C.1 | strategies/classical/volume_weighted_trend |
