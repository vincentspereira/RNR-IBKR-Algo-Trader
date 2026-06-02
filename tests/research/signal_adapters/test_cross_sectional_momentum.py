"""Tests for the cross-sectional momentum adapter (Phase 5 DOD, multi-asset).

Covers:
* momentum_score_panel -- shape, warmup NaN, and the CRITICAL look-ahead-free
  truncation-invariance check (signal at bar t unchanged by appending future
  bars), for both raw and risk-adjusted score paths.
* momentum_weights -- dollar-neutrality (each active row sums to ~0), leg
  membership, and quantile validation.
* momentum_grid -- length, keys, float coercion.
* build_momentum_weight_fn -- multi-column weight panel shape and the positional
  reindex onto the panel timestamps.
* price_panel_from_frame -- wide-to-long panel construction and validation.
* evaluate_signal via the gate: a panel with genuine cross-sectional momentum
  PROMOTES (with vectorised/event-driven mode agreement); independent random
  walks ARCHIVE.

The momentum fixture uses block-persistent per-asset drift, which produces a
deliberately strong (idealized) signal: the test asserts the gate's accept/reject
behaviour and look-ahead-freeness, not a realistic Sharpe magnitude.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from core_trading.research.signal_adapters.cross_sectional_momentum import (
    build_momentum_weight_fn,
    momentum_grid,
    momentum_score_panel,
    momentum_weights,
)
from core_trading.research.signal_evaluation import (
    evaluate_signal,
    price_panel_from_frame,
)
from core_trading.signals.factors.momentum import MomentumConfig

# ---------------------------------------------------------------------------
# Shared price-panel builders
# ---------------------------------------------------------------------------

_MOM_SEED = 7
_RW_SEED = 123
_N_ASSETS = 14
_CFG = MomentumConfig(lookback=126, skip=5, vol_window=40)


def _momentum_panel(
    n: int = 1500,
    n_assets: int = _N_ASSETS,
    *,
    block: int = 350,
    drift_sigma: float = 0.004,
    noise: float = 0.012,
    seed: int = _MOM_SEED,
) -> pd.DataFrame:
    """Wide price panel with block-persistent per-asset drift.

    Every ``block`` bars each asset draws a fresh persistent drift; within a
    block the cross-sectional ranking persists, so past winners keep winning and
    a momentum long/short has a genuine edge.
    """
    rng = np.random.default_rng(seed)
    rets = np.empty((n, n_assets), dtype=float)
    t = 0
    while t < n:
        end = min(t + block, n)
        drift = rng.normal(0.0, drift_sigma, size=n_assets)
        rets[t:end] = drift + rng.normal(0.0, noise, size=(end - t, n_assets))
        t = end
    prices = 100.0 * np.exp(np.cumsum(rets, axis=0))
    cols = [f"A{i:02d}" for i in range(n_assets)]
    idx = pd.date_range("2015-01-02", periods=n, freq="B")
    return pd.DataFrame(prices, index=idx, columns=cols)


def _random_walk_panel(
    n: int = 1500,
    n_assets: int = _N_ASSETS,
    *,
    noise: float = 0.01,
    seed: int = _RW_SEED,
) -> pd.DataFrame:
    """Independent driftless Gaussian random walks -- no cross-sectional edge."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0, noise, size=(n, n_assets))
    prices = 100.0 * np.exp(np.cumsum(rets, axis=0))
    cols = [f"A{i:02d}" for i in range(n_assets)]
    idx = pd.date_range("2015-01-02", periods=n, freq="B")
    return pd.DataFrame(prices, index=idx, columns=cols)


# ---------------------------------------------------------------------------
# momentum_score_panel
# ---------------------------------------------------------------------------


class TestMomentumScorePanel:
    def test_shape_and_columns(self) -> None:
        prices = _momentum_panel(n=400)
        z = momentum_score_panel(prices, _CFG)
        assert z.shape == prices.shape
        assert list(z.columns) == list(prices.columns)

    def test_warmup_nans(self) -> None:
        prices = _momentum_panel(n=400)
        z = momentum_score_panel(prices, _CFG)
        # Rows before the lookback window cannot have a score.
        assert z.iloc[: _CFG.lookback].isna().all().all()

    def test_has_finite_values_after_warmup(self) -> None:
        prices = _momentum_panel(n=600)
        z = momentum_score_panel(prices, _CFG)
        assert np.isfinite(z.to_numpy()).any()

    def test_raw_vs_risk_adjusted_differ(self) -> None:
        prices = _momentum_panel(n=600)
        z_raw = momentum_score_panel(prices, _CFG, risk_adjusted=False)
        z_adj = momentum_score_panel(prices, _CFG, risk_adjusted=True)
        # They should not be identical (vol-scaling changes the ranking scale).
        assert not np.allclose(
            np.nan_to_num(z_raw.to_numpy()), np.nan_to_num(z_adj.to_numpy())
        )

    @pytest.mark.parametrize("risk_adjusted", [False, True])
    def test_look_ahead_free_truncation_invariance(self, risk_adjusted: bool) -> None:
        """Score at bar t must not change when future bars are appended.

        The definitive look-ahead-free check: scores on the full panel and on a
        prefix of length k must agree at every shared bar (where both finite),
        with identical NaN masks. Leaking future data (e.g. cross-sectional
        scaling that peeks ahead) would break this.
        """
        full = _momentum_panel(n=700)
        k = 480
        prefix = full.iloc[:k]

        z_full = momentum_score_panel(full, _CFG, risk_adjusted=risk_adjusted).iloc[:k].to_numpy()
        z_pref = momentum_score_panel(prefix, _CFG, risk_adjusted=risk_adjusted).to_numpy()

        np.testing.assert_array_equal(
            np.isnan(z_full), np.isnan(z_pref),
            err_msg="NaN mask differs between full and truncated panels",
        )
        both_finite = np.isfinite(z_full) & np.isfinite(z_pref)
        np.testing.assert_allclose(
            z_full[both_finite], z_pref[both_finite],
            rtol=1e-10, atol=1e-12,
            err_msg="score values differ at shared bars -- look-ahead contamination",
        )


# ---------------------------------------------------------------------------
# momentum_weights
# ---------------------------------------------------------------------------


class TestMomentumWeights:
    def test_dollar_neutral_rows(self) -> None:
        prices = _momentum_panel(n=600)
        z = momentum_score_panel(prices, _CFG)
        w = momentum_weights(z, quantile=0.2)
        row_sums = w.sum(axis=1).to_numpy()
        # Every row is either all-zero (warmup / too few names) or dollar-neutral.
        assert np.allclose(row_sums, 0.0, atol=1e-9)

    def test_has_long_and_short_legs(self) -> None:
        prices = _momentum_panel(n=600)
        z = momentum_score_panel(prices, _CFG)
        w = momentum_weights(z, quantile=0.2).to_numpy()
        # At least one active bar with both a +ve and a -ve weight.
        active = w[np.any(w != 0.0, axis=1)]
        assert active.shape[0] > 0
        assert np.any(active > 0.0) and np.any(active < 0.0)

    def test_gross_exposure_two_on_active_rows(self) -> None:
        prices = _momentum_panel(n=600)
        z = momentum_score_panel(prices, _CFG)
        w = momentum_weights(z, quantile=0.2).to_numpy()
        gross = np.abs(w).sum(axis=1)
        active = gross[gross > 0.0]
        # Each active row longs +1 and shorts -1 -> gross 2.
        np.testing.assert_allclose(active, 2.0, atol=1e-9)

    def test_quantile_out_of_range_raises(self) -> None:
        prices = _momentum_panel(n=300)
        z = momentum_score_panel(prices, _CFG)
        with pytest.raises(ValueError, match="quantile"):
            momentum_weights(z, quantile=0.0)
        with pytest.raises(ValueError, match="quantile"):
            momentum_weights(z, quantile=1.0)


# ---------------------------------------------------------------------------
# momentum_grid
# ---------------------------------------------------------------------------


class TestMomentumGrid:
    def test_default_length(self) -> None:
        assert len(momentum_grid()) == 4

    def test_all_have_quantile_key(self) -> None:
        for cfg in momentum_grid():
            assert "quantile" in cfg
            assert isinstance(cfg["quantile"], float)

    def test_custom_quantiles(self) -> None:
        g = momentum_grid(quantiles=(0.1, 0.25))
        assert len(g) == 2
        assert g[0]["quantile"] == 0.1
        assert g[1]["quantile"] == 0.25

    def test_values_coerced_to_float(self) -> None:
        g = momentum_grid(quantiles=(0,))  # type: ignore[arg-type]
        # 0 is not a valid quantile, but the grid only constructs configs; the
        # coercion to float is what we assert here.
        assert type(g[0]["quantile"]) is float


# ---------------------------------------------------------------------------
# build_momentum_weight_fn
# ---------------------------------------------------------------------------


class TestBuildMomentumWeightFn:
    def test_returns_callable(self) -> None:
        prices = _momentum_panel(n=400)
        fn = build_momentum_weight_fn(prices, config=_CFG)
        assert callable(fn)

    def test_weight_frame_shape_and_columns(self) -> None:
        prices = _momentum_panel(n=400)
        panel = price_panel_from_frame(prices)
        fn = build_momentum_weight_fn(prices, config=_CFG)
        weights = fn(panel, {"quantile": 0.2})
        assert isinstance(weights, pd.DataFrame)
        assert set(weights.columns) == set(prices.columns)
        n_ts = panel.index.get_level_values("timestamp").nunique()
        assert len(weights) == n_ts

    def test_weights_reindexed_onto_panel_timestamps(self) -> None:
        prices = _momentum_panel(n=400)
        panel = price_panel_from_frame(prices)
        fn = build_momentum_weight_fn(prices, config=_CFG)
        weights = fn(panel, {"quantile": 0.2})
        ts_index = panel.index.get_level_values("timestamp").unique().sort_values()
        pd.testing.assert_index_equal(weights.index, ts_index)


# ---------------------------------------------------------------------------
# price_panel_from_frame
# ---------------------------------------------------------------------------


class TestPricePanelFromFrame:
    def test_panel_structure(self) -> None:
        prices = _momentum_panel(n=50, n_assets=3)
        panel = price_panel_from_frame(prices)
        assert list(panel.index.names) == ["symbol", "timestamp"]
        assert set(panel.columns) == {"open", "high", "low", "close", "volume"}
        assert len(panel) == 50 * 3
        # open == high == low == close for every row
        sub = panel[["open", "high", "low", "close"]].to_numpy()
        assert np.allclose(sub, sub[:, [0]])

    def test_synthesises_calendar_for_non_datetime_index(self) -> None:
        prices = _momentum_panel(n=20, n_assets=2).reset_index(drop=True)
        panel = price_panel_from_frame(prices)
        ts = panel.index.get_level_values("timestamp")
        assert isinstance(ts, pd.DatetimeIndex)

    def test_rejects_too_few_rows(self) -> None:
        prices = _momentum_panel(n=20).iloc[:1]
        with pytest.raises(ValueError, match="at least 2 timestamps"):
            price_panel_from_frame(prices)

    def test_rejects_no_columns(self) -> None:
        prices = _momentum_panel(n=20).iloc[:, :0]
        with pytest.raises(ValueError, match="at least 1 symbol"):
            price_panel_from_frame(prices)

    def test_rejects_non_positive(self) -> None:
        prices = _momentum_panel(n=20, n_assets=2).copy()
        prices.iloc[5, 0] = -1.0
        with pytest.raises(ValueError, match="finite and strictly positive"):
            price_panel_from_frame(prices)


# ---------------------------------------------------------------------------
# Evaluation gate: PROMOTE on genuine cross-sectional momentum
# ---------------------------------------------------------------------------


class TestEvalGatePromotion:
    def test_promotes_genuine_momentum(self) -> None:
        prices = _momentum_panel(seed=_MOM_SEED)
        panel = price_panel_from_frame(prices)
        weight_fn = build_momentum_weight_fn(prices, config=_CFG)
        ev = evaluate_signal(panel, weight_fn, momentum_grid(), signal_name="xsec-momentum")

        assert ev.verdict == "PROMOTE", (
            f"Expected PROMOTE, got {ev.verdict}. "
            f"deflated={ev.deflated}, sharpe={ev.observed_sharpe_annualised:.3f}"
        )
        assert ev.deflated is not None
        assert ev.deflated.is_significant
        assert ev.n_trials == 4

    def test_vectorised_event_driven_modes_agree(self) -> None:
        """The long/short flips exercise the event-driven engine; modes must agree."""
        prices = _momentum_panel(seed=_MOM_SEED)
        panel = price_panel_from_frame(prices)
        weight_fn = build_momentum_weight_fn(prices, config=_CFG)
        ev = evaluate_signal(panel, weight_fn, momentum_grid(), signal_name="xsec-momentum")
        assert ev.modes_agree, "vectorised and event-driven modes disagreed on the long/short"

    def test_best_params_has_quantile(self) -> None:
        prices = _momentum_panel(seed=_MOM_SEED)
        panel = price_panel_from_frame(prices)
        weight_fn = build_momentum_weight_fn(prices, config=_CFG)
        ev = evaluate_signal(panel, weight_fn, momentum_grid(), signal_name="xsec-momentum")
        assert "quantile" in ev.best_params


# ---------------------------------------------------------------------------
# Evaluation gate: ARCHIVE on independent random walks
# ---------------------------------------------------------------------------


class TestEvalGateArchive:
    def test_archives_random_walks(self) -> None:
        prices = _random_walk_panel(seed=_RW_SEED)
        panel = price_panel_from_frame(prices)
        weight_fn = build_momentum_weight_fn(prices, config=_CFG)
        ev = evaluate_signal(panel, weight_fn, momentum_grid(), signal_name="xsec-noise")
        assert ev.verdict == "ARCHIVE", (
            f"Expected ARCHIVE, got {ev.verdict}. "
            f"deflated={ev.deflated}, sharpe={ev.observed_sharpe_annualised:.3f}"
        )


# ---------------------------------------------------------------------------
# SignalEvaluation structure
# ---------------------------------------------------------------------------


class TestSignalEvaluationStructure:
    def test_memo_present(self) -> None:
        prices = _momentum_panel(n=500)
        panel = price_panel_from_frame(prices)
        weight_fn = build_momentum_weight_fn(prices, config=_CFG)
        ev = evaluate_signal(panel, weight_fn, momentum_grid(), signal_name="xsec")
        assert isinstance(ev.memo, str) and len(ev.memo) > 0

    def test_observed_sharpe_finite(self) -> None:
        prices = _momentum_panel(n=500)
        panel = price_panel_from_frame(prices)
        weight_fn = build_momentum_weight_fn(prices, config=_CFG)
        ev = evaluate_signal(panel, weight_fn, momentum_grid(), signal_name="xsec")
        assert math.isfinite(ev.observed_sharpe_annualised)
