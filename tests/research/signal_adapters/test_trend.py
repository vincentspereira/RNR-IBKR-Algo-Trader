"""Tests for core_trading.research.signal_adapters.trend (Phase 5 DOD adapter).

Covers:
* trend_slope_series -- warmup NaN, refit cadence, look-ahead-free invariance
  (CRITICAL: proves signal at bar t uses only data <= t).
* trend_positions -- deadband rule including NaN passthrough.
* build_trend_weight_fn -- weight shape / dtype, positional reindex.
* trend_grid -- length and key presence.
* evaluate_signal via the gate: genuine trend PROMOTES with significant
  deflated Sharpe; pure Gaussian random walk ARCHIVES.
* ValueError guards: lookback too small, refit_every < 1, deadband < 0.
* 100% line coverage of trend.py.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from core_trading.research.signal_adapters.trend import (
    build_trend_weight_fn,
    trend_grid,
    trend_positions,
    trend_slope_series,
)
from core_trading.research.signal_evaluation import (
    evaluate_signal,
    price_panel_from_series,
)

# ---------------------------------------------------------------------------
# Shared price builders
# ---------------------------------------------------------------------------

_TREND_SEED = 20260601
_RW_SEED = 99


def _trend_prices(n: int = 1400, seed: int = _TREND_SEED) -> pd.Series:
    """Piecewise-constant-drift price series with sign-flipping trends.

    Every ~200 bars the drift sign flips; Gaussian noise is modest relative
    to the drift so the trend-following rule has a genuine edge.
    """
    rng = np.random.default_rng(seed)
    segment_len = 200
    drift_mag = 0.006  # 0.6 % per bar -- strong, clear trend

    returns = np.empty(n, dtype=float)
    t = 0
    while t < n:
        end = min(t + segment_len, n)
        # Alternate sign each segment; start positive
        sign = 1.0 if (t // segment_len) % 2 == 0 else -1.0
        seg_returns = sign * drift_mag + rng.normal(0.0, 0.008, size=end - t)
        returns[t:end] = seg_returns
        t = end

    prices = 100.0 * np.exp(np.cumsum(returns))
    return pd.Series(prices)


def _random_walk_prices(n: int = 1400, seed: int = _RW_SEED) -> pd.Series:
    """Driftless Gaussian random walk in log-price (strictly positive)."""
    rng = np.random.default_rng(seed)
    log_returns = rng.normal(0.0, 0.01, size=n)
    prices = 100.0 * np.exp(np.cumsum(log_returns))
    return pd.Series(prices)


# ---------------------------------------------------------------------------
# trend_slope_series -- basic properties
# ---------------------------------------------------------------------------


class TestTrendSlopeSeries:
    def test_output_shape_and_columns(self) -> None:
        close = _trend_prices(n=300)
        df = trend_slope_series(close, lookback=50, refit_every=10)
        assert isinstance(df, pd.DataFrame)
        assert set(df.columns) >= {"raw_slope", "signal"}
        assert len(df) == len(close)

    def test_warmup_nans(self) -> None:
        """Bars before the first full window must be NaN."""
        lookback = 60
        close = _trend_prices(n=300)
        df = trend_slope_series(close, lookback=lookback, refit_every=10)
        # First (lookback - 1) bars are warmup; signal also needs >= 2 slopes
        assert df["signal"].iloc[: lookback - 1].isna().all()
        assert df["raw_slope"].iloc[: lookback - 1].isna().all()

    def test_valid_bars_have_finite_values(self) -> None:
        close = _trend_prices(n=300)
        df = trend_slope_series(close, lookback=50, refit_every=10)
        # After warmup + first slope we should have some finite values
        assert df["signal"].dropna().size > 0

    def test_index_preserved(self) -> None:
        close = _trend_prices(n=200)
        df = trend_slope_series(close, lookback=40, refit_every=10)
        pd.testing.assert_index_equal(df.index, close.index)

    # ------------------------------------------------------------------
    # CRITICAL: look-ahead-free truncation-invariance test
    # ------------------------------------------------------------------

    def test_look_ahead_free_truncation_invariance(self) -> None:
        """Signal at bar t must not change when future bars are appended.

        This is the definitive look-ahead-free check: compute the signal on
        the full series AND on a prefix of length k.  Every bar < k that is
        non-NaN in both series must match to float precision.

        If the implementation leaks future data (e.g. fitting on the whole
        series and slicing), the smoothed-state values change as more data
        is appended, and this test will catch the discrepancy.
        """
        close_full = _trend_prices(n=500)
        k = 320  # middle cut
        close_prefix = close_full.iloc[:k]

        lookback = 60
        refit_every = 10

        df_full = trend_slope_series(close_full, lookback=lookback, refit_every=refit_every)
        df_prefix = trend_slope_series(close_prefix, lookback=lookback, refit_every=refit_every)

        full_sig = df_full["signal"].iloc[:k].to_numpy()
        pref_sig = df_prefix["signal"].iloc[:k].to_numpy()

        # Where both are finite they must agree exactly (same computation).
        both_finite = np.isfinite(full_sig) & np.isfinite(pref_sig)
        full_nan = np.isnan(full_sig)
        pref_nan = np.isnan(pref_sig)

        # NaN positions must agree
        np.testing.assert_array_equal(
            full_nan,
            pref_nan,
            err_msg="NaN mask differs between full and truncated series",
        )
        # Non-NaN values must be identical to tight tolerance
        np.testing.assert_allclose(
            full_sig[both_finite],
            pref_sig[both_finite],
            rtol=1e-10,
            atol=1e-12,
            err_msg=(
                "signal values at shared bars differ between full and truncated "
                "series -- look-ahead contamination detected"
            ),
        )

    # ------------------------------------------------------------------
    # Validation errors
    # ------------------------------------------------------------------

    def test_lookback_too_small_raises(self) -> None:
        close = _trend_prices(n=200)
        with pytest.raises(ValueError, match="lookback must be >= 30"):
            trend_slope_series(close, lookback=29)

    def test_refit_every_zero_raises(self) -> None:
        close = _trend_prices(n=200)
        with pytest.raises(ValueError, match="refit_every must be >= 1"):
            trend_slope_series(close, lookback=40, refit_every=0)

    def test_refit_every_negative_raises(self) -> None:
        close = _trend_prices(n=200)
        with pytest.raises(ValueError, match="refit_every must be >= 1"):
            trend_slope_series(close, lookback=40, refit_every=-5)

    def test_lookback_exactly_30_allowed(self) -> None:
        close = _trend_prices(n=150)
        df = trend_slope_series(close, lookback=30, refit_every=5)
        assert len(df) == 150

    def test_refit_every_one_allowed(self) -> None:
        # refit_every=1 is expensive but valid; use tiny series
        close = _trend_prices(n=60)
        df = trend_slope_series(close, lookback=30, refit_every=1)
        assert len(df) == 60


# ---------------------------------------------------------------------------
# trend_positions
# ---------------------------------------------------------------------------


class TestTrendPositions:
    def _make_signal(self, values: list[float]) -> pd.Series:
        return pd.Series(values, dtype=float)

    def test_long_above_deadband(self) -> None:
        sig = self._make_signal([0.0, 0.6, 1.5])
        pos = trend_positions(sig, deadband=0.5)
        assert float(pos.iloc[1]) == 1.0
        assert float(pos.iloc[2]) == 1.0

    def test_short_below_deadband(self) -> None:
        sig = self._make_signal([-0.6, -1.5, 0.0])
        pos = trend_positions(sig, deadband=0.5)
        assert float(pos.iloc[0]) == -1.0
        assert float(pos.iloc[1]) == -1.0

    def test_flat_inside_deadband(self) -> None:
        sig = self._make_signal([-0.4, 0.0, 0.4])
        pos = trend_positions(sig, deadband=0.5)
        assert (pos == 0.0).all()

    def test_boundary_values_exactly_at_deadband_are_flat(self) -> None:
        # signal == deadband is not strictly greater, so position is flat
        sig = self._make_signal([0.5, -0.5])
        pos = trend_positions(sig, deadband=0.5)
        assert (pos == 0.0).all()

    def test_nan_signal_yields_zero_position(self) -> None:
        sig = self._make_signal([float("nan"), 2.0, float("nan")])
        pos = trend_positions(sig, deadband=0.5)
        assert float(pos.iloc[0]) == 0.0
        assert float(pos.iloc[2]) == 0.0
        assert float(pos.iloc[1]) == 1.0

    def test_deadband_zero_gives_threshold_at_zero(self) -> None:
        # With deadband=0, only exactly 0.0 is flat; any positive -> long
        sig = self._make_signal([0.01, -0.01, 0.0])
        pos = trend_positions(sig, deadband=0.0)
        assert float(pos.iloc[0]) == 1.0
        assert float(pos.iloc[1]) == -1.0
        assert float(pos.iloc[2]) == 0.0

    def test_output_values_in_allowed_set(self) -> None:
        rng = np.random.default_rng(42)
        sig = pd.Series(rng.standard_normal(500))
        pos = trend_positions(sig, deadband=0.5)
        assert set(pos.unique()).issubset({-1.0, 0.0, 1.0})

    def test_index_preserved(self) -> None:
        idx = pd.date_range("2020-01-01", periods=10)
        sig = pd.Series(np.linspace(-2.0, 2.0, 10), index=idx)
        pos = trend_positions(sig, deadband=0.5)
        pd.testing.assert_index_equal(pos.index, sig.index)

    def test_negative_deadband_raises(self) -> None:
        sig = self._make_signal([1.0, 0.0, -1.0])
        with pytest.raises(ValueError, match="deadband must be >= 0"):
            trend_positions(sig, deadband=-0.1)


# ---------------------------------------------------------------------------
# trend_grid
# ---------------------------------------------------------------------------


class TestTrendGrid:
    def test_default_length(self) -> None:
        g = trend_grid()
        assert len(g) == 5

    def test_all_have_deadband_key(self) -> None:
        for cfg in trend_grid():
            assert "deadband" in cfg
            assert isinstance(cfg["deadband"], float)

    def test_custom_deadbands(self) -> None:
        g = trend_grid(deadbands=(0.0, 1.0, 2.0))
        assert len(g) == 3
        assert g[0]["deadband"] == 0.0
        assert g[2]["deadband"] == 2.0

    def test_values_are_coerced_to_float(self) -> None:
        g = trend_grid(deadbands=(0, 1))  # type: ignore[arg-type]
        for cfg in g:
            assert type(cfg["deadband"]) is float


# ---------------------------------------------------------------------------
# build_trend_weight_fn
# ---------------------------------------------------------------------------


class TestBuildTrendWeightFn:
    def test_returns_callable(self) -> None:
        close = _trend_prices(n=300)
        fn = build_trend_weight_fn(close, lookback=60, refit_every=10)
        assert callable(fn)

    def test_weight_frame_shape(self) -> None:
        close = _trend_prices(n=300)
        panel = price_panel_from_series(close, symbol="SIM")
        fn = build_trend_weight_fn(close, symbol="SIM", lookback=60, refit_every=10)
        weights = fn(panel, {"deadband": 0.5})
        # Must be a single-column frame matching the panel's timestamp count
        assert isinstance(weights, pd.DataFrame)
        assert "SIM" in weights.columns
        sym_len = len(panel.xs("SIM", level="symbol"))
        assert len(weights) == sym_len

    def test_weights_in_allowed_set(self) -> None:
        close = _trend_prices(n=300)
        panel = price_panel_from_series(close, symbol="SIM")
        fn = build_trend_weight_fn(close, symbol="SIM", lookback=60, refit_every=10)
        weights = fn(panel, {"deadband": 0.5})
        assert set(weights["SIM"].unique()).issubset({-1.0, 0.0, 1.0})


# ---------------------------------------------------------------------------
# Evaluation gate: PROMOTE on genuine trend
# ---------------------------------------------------------------------------


class TestEvalGatePromotion:
    """A price series with persistent, sign-flipping trends must PROMOTE."""

    def test_promotes_genuine_trend(self) -> None:
        close = _trend_prices(n=1400, seed=_TREND_SEED)
        panel = price_panel_from_series(close, symbol="SIM")
        weight_fn = build_trend_weight_fn(close, symbol="SIM", lookback=150, refit_every=10)
        grid = trend_grid()

        ev = evaluate_signal(
            panel,
            weight_fn,
            grid,
            signal_name="trend-following",
        )

        assert ev.signal_name == "trend-following"
        assert ev.is_promoted, (
            f"Expected PROMOTE but got ARCHIVE. "
            f"deflated={ev.deflated}, sharpe={ev.observed_sharpe_annualised:.3f}"
        )
        assert ev.deflated is not None, "deflated should not be None for an active signal"
        assert ev.deflated.is_significant, (
            f"Deflated Sharpe {ev.deflated.deflated_sharpe:.4f} did not clear 0.95. "
            f"Strengthen the trend signal if this fails."
        )

    def test_promote_has_correct_verdict_string(self) -> None:
        close = _trend_prices(n=1400, seed=_TREND_SEED)
        panel = price_panel_from_series(close, symbol="SIM")
        weight_fn = build_trend_weight_fn(close, symbol="SIM", lookback=150, refit_every=10)
        ev = evaluate_signal(panel, weight_fn, trend_grid(), signal_name="trend-following")
        assert ev.verdict == "PROMOTE"
        assert ev.n_trials == 5


# ---------------------------------------------------------------------------
# Evaluation gate: ARCHIVE on pure noise
# ---------------------------------------------------------------------------


class TestEvalGateArchive:
    """A driftless Gaussian random walk has no trend-following edge."""

    def test_archives_random_walk(self) -> None:
        close = _random_walk_prices(n=1400, seed=_RW_SEED)
        panel = price_panel_from_series(close, symbol="SIM")
        weight_fn = build_trend_weight_fn(close, symbol="SIM", lookback=150, refit_every=10)
        grid = trend_grid()

        ev = evaluate_signal(
            panel,
            weight_fn,
            grid,
            signal_name="trend-following-noise",
        )

        assert ev.verdict == "ARCHIVE", (
            f"Expected ARCHIVE but got PROMOTE. "
            f"deflated={ev.deflated}, sharpe={ev.observed_sharpe_annualised:.3f}"
        )

    def test_archive_has_correct_verdict_string(self) -> None:
        close = _random_walk_prices(n=1400, seed=_RW_SEED)
        panel = price_panel_from_series(close, symbol="SIM")
        weight_fn = build_trend_weight_fn(close, symbol="SIM", lookback=150, refit_every=10)
        ev = evaluate_signal(panel, weight_fn, trend_grid(), signal_name="trend-following-noise")
        assert ev.verdict == "ARCHIVE"


# ---------------------------------------------------------------------------
# SignalEvaluation structural checks
# ---------------------------------------------------------------------------


class TestSignalEvaluationStructure:
    def test_eval_result_has_memo(self) -> None:
        close = _trend_prices(n=400)
        panel = price_panel_from_series(close, symbol="SIM")
        weight_fn = build_trend_weight_fn(close, symbol="SIM", lookback=60, refit_every=10)
        ev = evaluate_signal(panel, weight_fn, trend_grid(), signal_name="test")
        assert isinstance(ev.memo, str)
        assert len(ev.memo) > 0

    def test_eval_result_best_params_has_deadband(self) -> None:
        close = _trend_prices(n=400)
        panel = price_panel_from_series(close, symbol="SIM")
        weight_fn = build_trend_weight_fn(close, symbol="SIM", lookback=60, refit_every=10)
        ev = evaluate_signal(panel, weight_fn, trend_grid(), signal_name="test")
        assert "deadband" in ev.best_params

    def test_observed_sharpe_is_finite(self) -> None:
        close = _trend_prices(n=400)
        panel = price_panel_from_series(close, symbol="SIM")
        weight_fn = build_trend_weight_fn(close, symbol="SIM", lookback=60, refit_every=10)
        ev = evaluate_signal(panel, weight_fn, trend_grid(), signal_name="test")
        assert math.isfinite(ev.observed_sharpe_annualised)
