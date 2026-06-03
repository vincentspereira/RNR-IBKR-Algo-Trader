"""Tests for the tree-ensemble ML directional signal adapter (Phase 5.D.1 DOD).

Two layers, matching the adapter's two distinct concerns:

* ``event_positions_to_weights`` -- the de Prado ``avgActiveSignals`` map from
  sparse event bet sizes to a dense held-position weight series. This is where the
  look-ahead discipline lives, so it gets exact, model-free assertions: a single
  held event, overlapping events averaged, the bounded net position, the
  off-calendar holding clip, the validation guards, and the CRITICAL causality
  check (appending a later event never changes an earlier bar's weight).
* the evaluation gate end-to-end -- a real ``RandomForestSignal`` out-of-fold on a
  regime-driven price (a feature that predicts the triple-barrier direction)
  PROMOTES with vectorised/event-driven mode agreement; the same pipeline on a
  driftless random walk with a noise feature ARCHIVES.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core_trading.research.signal_adapters.ml_tree_signal import (
    build_ml_signal_weight_fn,
    event_positions_to_weights,
    ml_signal_grid,
)
from core_trading.research.signal_evaluation import (
    evaluate_signal,
    price_panel_from_series,
)
from core_trading.signals.ml.labeling import (
    add_vertical_barrier,
    cusum_filter,
    daily_volatility,
    get_bins,
    triple_barrier_events,
)
from core_trading.signals.ml.trees import RandomForestSignal, TreeSignalConfig


def _bdays(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2020-01-01", periods=n, freq="B")


# ---------------------------------------------------------------------------
# event_positions_to_weights -- the avgActiveSignals map
# ---------------------------------------------------------------------------


class TestEventPositionsToWeights:
    def test_single_event_held_over_window(self) -> None:
        idx = _bdays(10)
        positions = pd.Series([0.7], index=[idx[2]])
        hold_until = pd.Series([idx[5]], index=[idx[2]])  # active on bars 2,3,4
        w = event_positions_to_weights(positions, hold_until, idx, symbol="SIM")
        col = w["SIM"].to_numpy()
        assert col[0] == 0.0 and col[1] == 0.0
        np.testing.assert_allclose(col[2:5], 0.7)
        assert col[5] == 0.0  # window is half-open [start, hold_until)

    def test_non_overlapping_events(self) -> None:
        idx = _bdays(12)
        positions = pd.Series([1.0, -1.0], index=[idx[1], idx[6]])
        hold_until = pd.Series([idx[4], idx[9]], index=[idx[1], idx[6]])
        w = event_positions_to_weights(positions, hold_until, idx)["SIM"].to_numpy()
        np.testing.assert_allclose(w[1:4], 1.0)
        np.testing.assert_allclose(w[4:6], 0.0)
        np.testing.assert_allclose(w[6:9], -1.0)

    def test_overlapping_events_are_averaged(self) -> None:
        idx = _bdays(10)
        # Two events both active on bars 3,4 -> mean(1.0, -0.5) = 0.25 there.
        positions = pd.Series([1.0, -0.5], index=[idx[1], idx[3]])
        hold_until = pd.Series([idx[5], idx[7]], index=[idx[1], idx[3]])
        w = event_positions_to_weights(positions, hold_until, idx)["SIM"].to_numpy()
        np.testing.assert_allclose(w[1:3], 1.0)        # only event 1 active
        np.testing.assert_allclose(w[3:5], 0.25)       # both active -> averaged
        np.testing.assert_allclose(w[5:7], -0.5)       # only event 2 active

    def test_net_position_bounded_by_one(self) -> None:
        idx = _bdays(20)
        rng = np.random.default_rng(0)
        starts = idx[[1, 3, 5, 7, 9]]
        positions = pd.Series(rng.uniform(-1.0, 1.0, 5), index=starts)
        hold_until = pd.Series([idx[12]] * 5, index=starts)  # all overlap heavily
        w = event_positions_to_weights(positions, hold_until, idx)["SIM"].to_numpy()
        assert np.all(np.abs(w) <= 1.0 + 1e-12)

    def test_holding_end_off_calendar_is_clipped(self) -> None:
        idx = _bdays(10)
        positions = pd.Series([0.5], index=[idx[7]])
        beyond = idx[-1] + pd.Timedelta(days=30)  # not in the calendar
        hold_until = pd.Series([beyond], index=[idx[7]])
        w = event_positions_to_weights(positions, hold_until, idx)["SIM"].to_numpy()
        np.testing.assert_allclose(w[7:], 0.5)  # held to the end of the calendar
        np.testing.assert_allclose(w[:7], 0.0)

    def test_causality_appending_later_event_does_not_change_earlier_bars(self) -> None:
        """The definitive look-ahead check for the held-position map."""
        idx = _bdays(20)
        early = pd.Series([0.8], index=[idx[2]])
        early_hold = pd.Series([idx[6]], index=[idx[2]])
        w_early = event_positions_to_weights(early, early_hold, idx)["SIM"].to_numpy()

        both = pd.Series([0.8, -0.9], index=[idx[2], idx[10]])
        both_hold = pd.Series([idx[6], idx[15]], index=[idx[2], idx[10]])
        w_both = event_positions_to_weights(both, both_hold, idx)["SIM"].to_numpy()

        # Bars before the later event (index 10) are byte-identical.
        np.testing.assert_array_equal(w_early[:10], w_both[:10])

    def test_mismatched_indices_raise(self) -> None:
        idx = _bdays(10)
        positions = pd.Series([1.0], index=[idx[1]])
        hold_until = pd.Series([idx[4]], index=[idx[2]])
        with pytest.raises(ValueError, match="share the same index"):
            event_positions_to_weights(positions, hold_until, idx)

    def test_event_start_absent_from_index_raises(self) -> None:
        idx = _bdays(10)
        stray = idx[-1] + pd.Timedelta(days=5)
        positions = pd.Series([1.0], index=[stray])
        hold_until = pd.Series([idx[4]], index=[stray])
        with pytest.raises(ValueError, match="event start must be present"):
            event_positions_to_weights(positions, hold_until, idx)

    def test_empty_holding_window_raises(self) -> None:
        idx = _bdays(10)
        positions = pd.Series([1.0], index=[idx[5]])
        hold_until = pd.Series([idx[5]], index=[idx[5]])  # ends at its own start
        with pytest.raises(ValueError, match="must end after its event start"):
            event_positions_to_weights(positions, hold_until, idx)


# ---------------------------------------------------------------------------
# ml_signal_grid
# ---------------------------------------------------------------------------


class TestMlSignalGrid:
    def test_default_length_and_keys(self) -> None:
        grid = ml_signal_grid()
        assert len(grid) == 4
        for cfg in grid:
            assert "min_size" in cfg
            assert isinstance(cfg["min_size"], float)

    def test_custom_floors(self) -> None:
        grid = ml_signal_grid(min_sizes=(0.0, 0.25))
        assert [c["min_size"] for c in grid] == [0.0, 0.25]

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one floor"):
            ml_signal_grid(min_sizes=())

    def test_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match=r"\[0, 1\)"):
            ml_signal_grid(min_sizes=(0.0, 1.0))


# ---------------------------------------------------------------------------
# build_ml_signal_weight_fn -- masking and panel reindex
# ---------------------------------------------------------------------------


class TestBuildMlSignalWeightFn:
    def _inputs(self) -> tuple[pd.Series, pd.Series, pd.DatetimeIndex]:
        idx = _bdays(12)
        positions = pd.Series([0.9, 0.05, -0.8], index=[idx[1], idx[4], idx[7]])
        hold_until = pd.Series([idx[3], idx[6], idx[9]], index=[idx[1], idx[4], idx[7]])
        return positions, hold_until, idx

    def test_min_size_drops_low_conviction_events(self) -> None:
        positions, hold_until, idx = self._inputs()
        fn = build_ml_signal_weight_fn(
            oof_positions=positions, hold_until=hold_until, index=idx
        )
        panel = price_panel_from_series(
            pd.Series(np.full(len(idx), 100.0), index=idx), symbol="SIM"
        )
        # min_size 0.1 drops the 0.05 event; its bars 4,5 become flat.
        w = fn(panel, {"min_size": 0.1})["SIM"].to_numpy()
        np.testing.assert_allclose(w[1:3], 0.9)
        np.testing.assert_allclose(w[4:6], 0.0)
        np.testing.assert_allclose(w[7:9], -0.8)
        # min_size 0.0 keeps it.
        w_all = fn(panel, {"min_size": 0.0})["SIM"].to_numpy()
        np.testing.assert_allclose(w_all[4:6], 0.05)

    def test_falls_back_to_index_when_panel_length_differs(self) -> None:
        positions, hold_until, idx = self._inputs()
        fn = build_ml_signal_weight_fn(
            oof_positions=positions, hold_until=hold_until, index=idx
        )
        # A panel with fewer timestamps than ``index`` -> the rule must fall back
        # to the original ``index`` (not the panel's), so events still align.
        short_idx = idx[:7]
        panel = price_panel_from_series(
            pd.Series(np.full(len(short_idx), 100.0), index=short_idx), symbol="SIM"
        )
        w = fn(panel, {"min_size": 0.0})
        pd.testing.assert_index_equal(w.index, idx)


# ---------------------------------------------------------------------------
# Evaluation gate end-to-end (real forest, out-of-fold)
# ---------------------------------------------------------------------------


def _regime_price(
    n: int, *, seed: int, mu: float, flip_p: float, noise: float
) -> tuple[pd.Series, pd.Series]:
    """Regime-driven price plus the (observable) regime feature.

    A hidden state ``s in {-1, +1}`` persists and flips with probability
    ``flip_p``; the per-bar return is ``mu * s + noise``. With ``mu > 0`` the
    regime predicts the triple-barrier direction (a learnable signal); with
    ``mu = 0`` the price is a random walk and the feature is uninformative.
    """
    rng = np.random.default_rng(seed)
    s = np.empty(n, dtype=float)
    s[0] = 1.0
    for t in range(1, n):
        s[t] = -s[t - 1] if rng.random() < flip_p else s[t - 1]
    rets = mu * s + rng.normal(0.0, noise, size=n)
    close = pd.Series(100.0 * np.exp(np.cumsum(rets)), index=_bdays(n), name="close")
    feature = pd.Series(s, index=close.index, name="regime")
    return close, feature


def _build_ml_weight_fn(
    close: pd.Series, feature: pd.Series, *, num_bars: int = 10
):
    """Run the full 5.D pipeline -> out-of-fold positions -> a weight rule."""
    target = daily_volatility(close, span=50)
    events_idx = cusum_filter(close, threshold=0.015)
    vbar = add_vertical_barrier(close, events_idx, num_bars=num_bars)
    tb = triple_barrier_events(
        close, events_idx, pt_sl=(1.5, 1.5), target=target, vertical_barrier=vbar
    )
    bins = get_bins(tb, close)
    y = bins["bin"]
    keep = y != 0.0
    y = y[keep].astype(int)
    x = feature.reindex(y.index).to_frame(name="regime")
    t1 = tb["t1"].reindex(y.index)
    hold_until = vbar.reindex(y.index).fillna(close.index[-1])

    model = RandomForestSignal(config=TreeSignalConfig(n_estimators=60, random_state=0))
    oof = model.oof_signal(x, y, t1=t1, n_splits=5)
    return build_ml_signal_weight_fn(
        oof_positions=oof, hold_until=hold_until, index=close.index
    )


class TestEvalGate:
    def test_promotes_regime_driven_signal(self) -> None:
        close, feature = _regime_price(1000, seed=11, mu=0.0015, flip_p=0.02, noise=0.006)
        panel = price_panel_from_series(close, symbol="SIM")
        weight_fn = _build_ml_weight_fn(close, feature)
        ev = evaluate_signal(panel, weight_fn, ml_signal_grid(), signal_name="ml-trees")
        assert ev.verdict == "PROMOTE", (
            f"Expected PROMOTE, got {ev.verdict}. deflated={ev.deflated}, "
            f"sharpe={ev.observed_sharpe_annualised:.3f}"
        )
        assert ev.deflated is not None and ev.deflated.is_significant
        assert ev.modes_agree
        assert ev.n_trials == 4

    def test_archives_random_walk_noise_feature(self) -> None:
        close, _ = _regime_price(1000, seed=23, mu=0.0, flip_p=0.02, noise=0.006)
        rng = np.random.default_rng(99)
        noise_feature = pd.Series(rng.normal(0.0, 1.0, len(close)), index=close.index)
        panel = price_panel_from_series(close, symbol="SIM")
        weight_fn = _build_ml_weight_fn(close, noise_feature)
        ev = evaluate_signal(panel, weight_fn, ml_signal_grid(), signal_name="ml-noise")
        assert ev.verdict == "ARCHIVE", (
            f"Expected ARCHIVE, got {ev.verdict}. deflated={ev.deflated}, "
            f"sharpe={ev.observed_sharpe_annualised:.3f}"
        )
