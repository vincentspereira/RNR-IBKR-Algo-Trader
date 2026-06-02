"""Phase 5 signal-evaluation adapters.

Each adapter wires an already-shipped signal module through the evaluation gate
in :mod:`core_trading.research.signal_evaluation`: it turns a fitted model into a
look-ahead-free target-weight rule plus a parameter grid, so the signal can be
run through the backtest engine and scored with the deflated Sharpe (the
per-signal Definition-of-Done items 3-5).

Every adapter follows the same shape as the Ornstein-Uhlenbeck mean-reversion
adapter that lives directly in
:mod:`core_trading.research.signal_evaluation`: compute the expensive
look-ahead-free signal path once in a ``build_*_weight_fn`` factory, then sweep a
cheap threshold grid so each configuration reuses the single computed series.

Adapters
--------
* :mod:`~core_trading.research.signal_adapters.trend` -- local-linear-trend
  (state-space stochastic slope) trend-following (single-asset).
* :mod:`~core_trading.research.signal_adapters.forecast` -- ARIMA one-step-ahead
  directional forecast (single-asset).
* :mod:`~core_trading.research.signal_adapters.cross_sectional_momentum` --
  cross-sectional momentum dollar-neutral long/short (multi-asset).
* :mod:`~core_trading.research.signal_adapters.pca_stat_arb` -- PCA
  residual-reversion (Avellaneda-Lee) dollar-neutral long/short (multi-asset).

The single-asset adapters compute the expensive look-ahead-free signal path once
in a ``build_*_weight_fn`` factory, then sweep a cheap threshold grid so each
configuration reuses the single computed series. The cross-sectional adapter
follows the same shape with a multi-asset weight panel and a swept long/short
quantile instead of a single-instrument threshold.

Like :mod:`core_trading.research.signal_evaluation`, these are intentionally not
re-exported from :mod:`core_trading.research`; import them from this subpackage
or by their submodule path.
"""
from __future__ import annotations

from core_trading.research.signal_adapters.cross_sectional_momentum import (
    build_momentum_weight_fn,
    momentum_grid,
    momentum_score_panel,
    momentum_weights,
)
from core_trading.research.signal_adapters.forecast import (
    build_forecast_weight_fn,
    forecast_grid,
    forecast_positions,
    forecast_signal_series,
)
from core_trading.research.signal_adapters.pca_stat_arb import (
    build_pca_statarb_weight_fn,
    pca_sscore_panel,
    pca_statarb_grid,
    residual_reversion_weights,
)
from core_trading.research.signal_adapters.trend import (
    build_trend_weight_fn,
    trend_grid,
    trend_positions,
    trend_slope_series,
)

__all__ = [
    # trend (local-linear-trend) adapter
    "trend_slope_series",
    "trend_positions",
    "build_trend_weight_fn",
    "trend_grid",
    # forecast (ARIMA) adapter
    "forecast_signal_series",
    "forecast_positions",
    "build_forecast_weight_fn",
    "forecast_grid",
    # cross-sectional momentum (multi-asset long/short) adapter
    "momentum_score_panel",
    "momentum_weights",
    "build_momentum_weight_fn",
    "momentum_grid",
    # PCA residual-reversion stat-arb (multi-asset long/short) adapter
    "pca_sscore_panel",
    "residual_reversion_weights",
    "build_pca_statarb_weight_fn",
    "pca_statarb_grid",
]
