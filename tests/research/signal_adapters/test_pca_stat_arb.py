"""Tests for the PCA residual-reversion stat-arb adapter (Phase 5 DOD, multi-asset).

Covers:
* pca_sscore_panel -- shape, warmup NaN, the CRITICAL look-ahead-free
  truncation-invariance check, and validation guards.
* residual_reversion_weights -- dollar-neutrality and the reversion direction
  (longs the most negative s-score, shorts the most positive).
* pca_statarb_grid -- length, keys, float coercion.
* build_pca_statarb_weight_fn -- multi-column weight panel shape and the
  positional reindex onto the panel timestamps.
* evaluate_signal via the gate: a panel with common factor structure and
  mean-reverting (OU) idiosyncratic residuals PROMOTES (with vectorised/
  event-driven mode agreement); the same structure with random-walk residuals
  (no reversion to trade) ARCHIVES.

The fixture plants a common factor structure plus an idiosyncratic process; with
an OU idiosyncratic level the residual-reversion signal has a genuine edge, with
a random-walk idiosyncratic level it does not.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from core_trading.research.signal_adapters.pca_stat_arb import (
    build_pca_statarb_weight_fn,
    pca_sscore_panel,
    pca_statarb_grid,
    residual_reversion_weights,
)
from core_trading.research.signal_evaluation import (
    evaluate_signal,
    price_panel_from_frame,
)

# ---------------------------------------------------------------------------
# Shared price-panel builder
# ---------------------------------------------------------------------------

_PROMOTE_SEED = 7
_ARCHIVE_SEED = 47
_N_ASSETS = 15
_N_FACTORS = 3


def _factor_panel(
    n: int = 1600,
    n_assets: int = _N_ASSETS,
    k: int = _N_FACTORS,
    *,
    theta: float,
    idio_sigma: float = 0.02,
    factor_sigma: float = 0.012,
    seed: int,
) -> pd.DataFrame:
    """Common k-factor structure plus an idiosyncratic process.

    The idiosyncratic level X follows X[t] = (1-theta) X[t-1] + eta. With
    ``theta > 0`` it is mean-reverting (OU) -- the residual-reversion signal has
    an edge; with ``theta = 0`` it is a random walk -- no reversion to trade.
    """
    rng = np.random.default_rng(seed)
    f = rng.normal(0.0, factor_sigma, size=(n, k))
    b = rng.normal(0.0, 1.0, size=(n_assets, k))
    systematic = f @ b.T
    x = np.zeros((n, n_assets))
    for t in range(1, n):
        x[t] = (1.0 - theta) * x[t - 1] + rng.normal(0.0, idio_sigma, size=n_assets)
    idio_ret = np.empty_like(x)
    idio_ret[0] = 0.0
    idio_ret[1:] = x[1:] - x[:-1]
    total = systematic + idio_ret
    prices = 100.0 * np.exp(np.cumsum(total, axis=0))
    cols = [f"A{i:02d}" for i in range(n_assets)]
    idx = pd.date_range("2015-01-02", periods=n, freq="B")
    return pd.DataFrame(prices, index=idx, columns=cols)


# ---------------------------------------------------------------------------
# pca_sscore_panel
# ---------------------------------------------------------------------------


class TestPcaSscorePanel:
    def test_shape_and_columns(self) -> None:
        prices = _factor_panel(n=400, theta=0.08, seed=1)
        s = pca_sscore_panel(prices, n_factors=_N_FACTORS, lookback=60, refit_every=5)
        assert s.shape == prices.shape
        assert list(s.columns) == list(prices.columns)

    def test_warmup_nans(self) -> None:
        prices = _factor_panel(n=400, theta=0.08, seed=1)
        lookback = 60
        s = pca_sscore_panel(prices, n_factors=_N_FACTORS, lookback=lookback, refit_every=5)
        assert s.iloc[:lookback].isna().all().all()

    def test_finite_after_warmup(self) -> None:
        prices = _factor_panel(n=400, theta=0.08, seed=1)
        s = pca_sscore_panel(prices, n_factors=_N_FACTORS, lookback=60, refit_every=5)
        assert np.isfinite(s.to_numpy()).any()

    def test_look_ahead_free_truncation_invariance(self) -> None:
        """s-score at bar t must not change when future bars are appended."""
        full = _factor_panel(n=500, theta=0.08, seed=3)
        k = 360
        prefix = full.iloc[:k]
        lookback, refit_every = 60, 5

        s_full = pca_sscore_panel(
            full, n_factors=_N_FACTORS, lookback=lookback, refit_every=refit_every
        ).iloc[:k].to_numpy()
        s_pref = pca_sscore_panel(
            prefix, n_factors=_N_FACTORS, lookback=lookback, refit_every=refit_every
        ).to_numpy()

        np.testing.assert_array_equal(
            np.isnan(s_full), np.isnan(s_pref),
            err_msg="NaN mask differs between full and truncated panels",
        )
        both_finite = np.isfinite(s_full) & np.isfinite(s_pref)
        np.testing.assert_allclose(
            s_full[both_finite], s_pref[both_finite],
            rtol=1e-10, atol=1e-12,
            err_msg="s-score values differ at shared bars -- look-ahead contamination",
        )

    def test_incomplete_window_yields_nan(self) -> None:
        """A window containing NaN (missing data) produces a NaN s-score row.

        Injecting a NaN price makes the returns straddling it non-finite, so any
        refit window covering it falls to the NaN branch -- yielding more NaN
        post-warmup rows than the clean panel.
        """
        clean = _factor_panel(n=250, theta=0.08, seed=1)
        dirty = clean.copy()
        dirty.iloc[120, 0] = np.nan
        s_clean = pca_sscore_panel(clean, n_factors=_N_FACTORS, lookback=60, refit_every=5)
        s_dirty = pca_sscore_panel(dirty, n_factors=_N_FACTORS, lookback=60, refit_every=5)
        post = slice(70, 250)
        assert s_dirty.iloc[post].isna().sum().sum() > s_clean.iloc[post].isna().sum().sum()

    def test_lookback_too_small_raises(self) -> None:
        prices = _factor_panel(n=200, theta=0.08, seed=1)
        with pytest.raises(ValueError, match="lookback must be >= 2"):
            pca_sscore_panel(prices, n_factors=2, lookback=1)

    def test_refit_every_too_small_raises(self) -> None:
        prices = _factor_panel(n=200, theta=0.08, seed=1)
        with pytest.raises(ValueError, match="refit_every must be >= 1"):
            pca_sscore_panel(prices, n_factors=2, lookback=60, refit_every=0)

    def test_n_factors_too_small_raises(self) -> None:
        prices = _factor_panel(n=200, theta=0.08, seed=1)
        with pytest.raises(ValueError, match="n_factors must be >= 1"):
            pca_sscore_panel(prices, n_factors=0, lookback=60)


# ---------------------------------------------------------------------------
# residual_reversion_weights
# ---------------------------------------------------------------------------


class TestResidualReversionWeights:
    def _sscore_row(self, values: list[float]) -> pd.DataFrame:
        cols = [f"A{i}" for i in range(len(values))]
        return pd.DataFrame([values], columns=cols)

    def test_longs_lowest_shorts_highest(self) -> None:
        # 5 assets, quantile 0.2 -> one per leg: long the -2 (cheapest), short +2.
        s = self._sscore_row([-2.0, -1.0, 0.0, 1.0, 2.0])
        w = residual_reversion_weights(s, quantile=0.2)
        assert w.iloc[0, 0] == pytest.approx(1.0)   # s=-2 -> long
        assert w.iloc[0, 4] == pytest.approx(-1.0)  # s=+2 -> short

    def test_dollar_neutral_rows(self) -> None:
        prices = _factor_panel(n=500, theta=0.08, seed=2)
        s = pca_sscore_panel(prices, n_factors=_N_FACTORS, lookback=60, refit_every=5)
        w = residual_reversion_weights(s, quantile=0.2)
        assert np.allclose(w.sum(axis=1).to_numpy(), 0.0, atol=1e-9)

    def test_gross_exposure_two_on_active_rows(self) -> None:
        prices = _factor_panel(n=500, theta=0.08, seed=2)
        s = pca_sscore_panel(prices, n_factors=_N_FACTORS, lookback=60, refit_every=5)
        w = residual_reversion_weights(s, quantile=0.2).to_numpy()
        gross = np.abs(w).sum(axis=1)
        active = gross[gross > 0.0]
        np.testing.assert_allclose(active, 2.0, atol=1e-9)

    def test_quantile_out_of_range_raises(self) -> None:
        s = self._sscore_row([-1.0, 0.0, 1.0])
        with pytest.raises(ValueError, match="quantile"):
            residual_reversion_weights(s, quantile=0.0)


# ---------------------------------------------------------------------------
# pca_statarb_grid
# ---------------------------------------------------------------------------


class TestPcaStatArbGrid:
    def test_default_length(self) -> None:
        assert len(pca_statarb_grid()) == 4

    def test_all_have_quantile_key(self) -> None:
        for cfg in pca_statarb_grid():
            assert "quantile" in cfg
            assert isinstance(cfg["quantile"], float)

    def test_custom_quantiles(self) -> None:
        g = pca_statarb_grid(quantiles=(0.15, 0.35))
        assert len(g) == 2
        assert g[0]["quantile"] == 0.15

    def test_values_coerced_to_float(self) -> None:
        g = pca_statarb_grid(quantiles=(0,))  # type: ignore[arg-type]
        assert type(g[0]["quantile"]) is float


# ---------------------------------------------------------------------------
# build_pca_statarb_weight_fn
# ---------------------------------------------------------------------------


class TestBuildPcaStatArbWeightFn:
    def test_returns_callable(self) -> None:
        prices = _factor_panel(n=400, theta=0.08, seed=1)
        fn = build_pca_statarb_weight_fn(prices, n_factors=_N_FACTORS, lookback=60)
        assert callable(fn)

    def test_weight_frame_shape_and_columns(self) -> None:
        prices = _factor_panel(n=400, theta=0.08, seed=1)
        panel = price_panel_from_frame(prices)
        fn = build_pca_statarb_weight_fn(prices, n_factors=_N_FACTORS, lookback=60)
        weights = fn(panel, {"quantile": 0.2})
        assert isinstance(weights, pd.DataFrame)
        assert set(weights.columns) == set(prices.columns)
        n_ts = panel.index.get_level_values("timestamp").nunique()
        assert len(weights) == n_ts

    def test_weights_reindexed_onto_panel_timestamps(self) -> None:
        prices = _factor_panel(n=400, theta=0.08, seed=1)
        panel = price_panel_from_frame(prices)
        fn = build_pca_statarb_weight_fn(prices, n_factors=_N_FACTORS, lookback=60)
        weights = fn(panel, {"quantile": 0.2})
        ts_index = panel.index.get_level_values("timestamp").unique().sort_values()
        pd.testing.assert_index_equal(weights.index, ts_index)


# ---------------------------------------------------------------------------
# Evaluation gate: PROMOTE on mean-reverting idiosyncratic residuals
# ---------------------------------------------------------------------------


class TestEvalGatePromotion:
    def test_promotes_mean_reverting_residuals(self) -> None:
        prices = _factor_panel(theta=0.08, idio_sigma=0.02, seed=_PROMOTE_SEED)
        panel = price_panel_from_frame(prices)
        weight_fn = build_pca_statarb_weight_fn(
            prices, n_factors=_N_FACTORS, lookback=120, refit_every=5
        )
        ev = evaluate_signal(panel, weight_fn, pca_statarb_grid(), signal_name="pca-statarb")

        assert ev.verdict == "PROMOTE", (
            f"Expected PROMOTE, got {ev.verdict}. "
            f"deflated={ev.deflated}, sharpe={ev.observed_sharpe_annualised:.3f}"
        )
        assert ev.deflated is not None
        assert ev.deflated.is_significant
        assert ev.n_trials == 4

    def test_modes_agree(self) -> None:
        prices = _factor_panel(theta=0.08, idio_sigma=0.02, seed=_PROMOTE_SEED)
        panel = price_panel_from_frame(prices)
        weight_fn = build_pca_statarb_weight_fn(
            prices, n_factors=_N_FACTORS, lookback=120, refit_every=5
        )
        ev = evaluate_signal(panel, weight_fn, pca_statarb_grid(), signal_name="pca-statarb")
        assert ev.modes_agree


# ---------------------------------------------------------------------------
# Evaluation gate: ARCHIVE on random-walk idiosyncratic residuals
# ---------------------------------------------------------------------------


class TestEvalGateArchive:
    def test_archives_random_walk_residuals(self) -> None:
        prices = _factor_panel(theta=0.0, idio_sigma=0.02, seed=_ARCHIVE_SEED)
        panel = price_panel_from_frame(prices)
        weight_fn = build_pca_statarb_weight_fn(
            prices, n_factors=_N_FACTORS, lookback=120, refit_every=5
        )
        ev = evaluate_signal(panel, weight_fn, pca_statarb_grid(), signal_name="pca-noise")
        assert ev.verdict == "ARCHIVE", (
            f"Expected ARCHIVE, got {ev.verdict}. "
            f"deflated={ev.deflated}, sharpe={ev.observed_sharpe_annualised:.3f}"
        )


# ---------------------------------------------------------------------------
# SignalEvaluation structure
# ---------------------------------------------------------------------------


class TestSignalEvaluationStructure:
    def test_memo_present(self) -> None:
        prices = _factor_panel(n=500, theta=0.08, seed=1)
        panel = price_panel_from_frame(prices)
        weight_fn = build_pca_statarb_weight_fn(prices, n_factors=_N_FACTORS, lookback=60)
        ev = evaluate_signal(panel, weight_fn, pca_statarb_grid(), signal_name="pca")
        assert isinstance(ev.memo, str) and len(ev.memo) > 0

    def test_best_params_has_quantile(self) -> None:
        prices = _factor_panel(n=500, theta=0.08, seed=1)
        panel = price_panel_from_frame(prices)
        weight_fn = build_pca_statarb_weight_fn(prices, n_factors=_N_FACTORS, lookback=60)
        ev = evaluate_signal(panel, weight_fn, pca_statarb_grid(), signal_name="pca")
        assert "quantile" in ev.best_params

    def test_observed_sharpe_finite(self) -> None:
        prices = _factor_panel(n=500, theta=0.08, seed=1)
        panel = price_panel_from_frame(prices)
        weight_fn = build_pca_statarb_weight_fn(prices, n_factors=_N_FACTORS, lookback=60)
        ev = evaluate_signal(panel, weight_fn, pca_statarb_grid(), signal_name="pca")
        assert math.isfinite(ev.observed_sharpe_annualised)
