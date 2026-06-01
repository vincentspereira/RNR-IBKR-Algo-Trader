"""Tests for core_trading.research.signal_adapters.forecast.

Covers:
* forecast_signal_series -- look-ahead-free truncation invariance (mandatory),
  warmup NaN, finiteness, validation guards.
* forecast_positions -- {-1, 0, 1} range, NaN-to-0 path, entry guards.
* build_forecast_weight_fn -- smoke test (imports cleanly, returns callable).
* forecast_grid -- length and key structure.
* Gate accepts a genuinely autocorrelated series (PROMOTE with significant DSR).
* Gate archives i.i.d. Gaussian noise (ARCHIVE verdict).

Runtime budget
--------------
Rolling SARIMAX fits are slow.  Series length is capped at ~1200 bars with
lookback=250 and refit_every=20, giving approx (1200-250)/20 = 47 fits.  The
entire module must complete in under 90 seconds.

Data design
-----------
PROMOTE test: AR(1) returns with phi=0.45 and small noise, 1200 bars.  High
autocorrelation at moderate length gives the ARIMA(1,0,0) model a genuine
predictive edge, which the deflated Sharpe should clearly exceed 0.95.
ARCHIVE test: i.i.d. Gaussian returns (phi=0), same length, fixed seed.  No
autocorrelation; the gate should archive.

Warning filters
---------------
statsmodels SARIMAX may emit a convergence warning on short windows or poorly
conditioned AR(1) problems with near-zero coefficients.  Those third-party
warnings are suppressed at their source -- inside
:func:`~core_trading.research.signal_adapters.forecast.forecast_signal_series`,
around the ``fit_arima`` call -- so this module needs no warning plumbing and
runs clean under ``-W error``.
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
import pytest

from core_trading.research.signal_adapters.forecast import (
    build_forecast_weight_fn,
    forecast_grid,
    forecast_positions,
    forecast_signal_series,
)
from core_trading.research.signal_evaluation import (
    evaluate_signal,
    price_panel_from_series,
)

# ---------------------------------------------------------------------------
# Shared constants and helpers
# ---------------------------------------------------------------------------

_N = 1200        # series length -- keeps total test time under ~90 s
_LOOKBACK = 250  # must be < _N
_REFIT = 20      # one fit per 20 bars -> ~47 fits total per series

_PROMOTE_SEED = 42
_ARCHIVE_SEED = 99


def _ar1_prices(phi: float, sigma: float, n: int, seed: int) -> pd.Series:
    """Positive price series generated from AR(1) returns.

    r_t = phi * r_{t-1} + sigma * eps_t,  eps_t ~ N(0,1)
    price_t = 100 * exp(cumsum(r))

    Parameters
    ----------
    phi:
        AR(1) coefficient; phi > 0 gives positive autocorrelation (momentum).
    sigma:
        Innovation standard deviation.
    n:
        Number of price observations (returns have length n-1).
    seed:
        RNG seed for reproducibility.
    """
    rng = np.random.default_rng(seed)
    eps = rng.standard_normal(n)
    r = np.empty(n, dtype=float)
    r[0] = eps[0] * sigma
    for t in range(1, n):
        r[t] = phi * r[t - 1] + sigma * eps[t]
    prices = 100.0 * np.exp(np.cumsum(r))
    return pd.Series(prices)


def _iid_prices(n: int, seed: int) -> pd.Series:
    """Positive price series from i.i.d. Gaussian returns (no autocorrelation)."""
    rng = np.random.default_rng(seed)
    r = rng.standard_normal(n) * 0.01
    prices = 100.0 * np.exp(np.cumsum(r))
    return pd.Series(prices)


def _run_gate(close: pd.Series, name: str) -> object:
    """Run the full evaluation gate on a price series using default settings."""
    panel = price_panel_from_series(close, symbol="SIM")
    px = panel.xs("SIM", level="symbol")["close"]
    rule = build_forecast_weight_fn(
        px, symbol="SIM", lookback=_LOOKBACK, refit_every=_REFIT
    )
    grid = forecast_grid()
    return evaluate_signal(panel, rule, grid, signal_name=name)


# ---------------------------------------------------------------------------
# forecast_signal_series -- look-ahead-free truncation invariance (CRITICAL)
# ---------------------------------------------------------------------------


class TestForecastSignalSeriesLookAheadFree:
    def test_truncation_invariance(self) -> None:
        """The signal at every index < k must be identical when computed on the
        full series and on the prefix close.iloc[:k].

        This is the canonical test for look-ahead-freedom.  The refit schedule
        is deterministic from bar 0, so both computations see exactly the same
        windows and refits for bars 0..k-1.
        """
        close = _ar1_prices(phi=0.35, sigma=0.01, n=_N, seed=_PROMOTE_SEED)
        full_sig = forecast_signal_series(
            close, lookback=_LOOKBACK, refit_every=_REFIT
        )
        # Pick a mid-point well after warmup
        k = _LOOKBACK + 200
        trunc_sig = forecast_signal_series(
            close.iloc[:k], lookback=_LOOKBACK, refit_every=_REFIT
        )
        np.testing.assert_array_equal(
            full_sig["signal"].iloc[:k].isna().to_numpy(),
            trunc_sig["signal"].isna().to_numpy(),
            err_msg="NaN mask differs between full and truncated series",
        )
        # For finite values, the standardised signal must match exactly.
        full_vals = full_sig["signal"].iloc[:k].to_numpy()
        trunc_vals = trunc_sig["signal"].to_numpy()
        mask = np.isfinite(full_vals) & np.isfinite(trunc_vals)
        if mask.any():
            np.testing.assert_allclose(
                full_vals[mask],
                trunc_vals[mask],
                rtol=1e-10,
                atol=1e-10,
                err_msg="Signal values differ at overlapping finite indices",
            )


# ---------------------------------------------------------------------------
# forecast_signal_series -- warmup, shape, finiteness
# ---------------------------------------------------------------------------


class TestForecastSignalSeries:
    def test_warmup_is_nan(self) -> None:
        """The first ``lookback`` values must be NaN (warmup period)."""
        close = _ar1_prices(phi=0.35, sigma=0.01, n=_N, seed=_PROMOTE_SEED)
        sig = forecast_signal_series(close, lookback=_LOOKBACK, refit_every=_REFIT)
        assert sig["signal"].iloc[:_LOOKBACK].isna().all()

    def test_finite_after_warmup(self) -> None:
        """At least some values after warmup must be finite."""
        close = _ar1_prices(phi=0.35, sigma=0.01, n=_N, seed=_PROMOTE_SEED)
        sig = forecast_signal_series(close, lookback=_LOOKBACK, refit_every=_REFIT)
        post = sig["signal"].iloc[_LOOKBACK:]
        assert np.isfinite(post.to_numpy()).any()

    def test_shape_matches_close(self) -> None:
        """Output DataFrame must have the same index as the input close series."""
        close = _ar1_prices(phi=0.35, sigma=0.01, n=500, seed=_PROMOTE_SEED)
        sig = forecast_signal_series(close, lookback=150, refit_every=20)
        assert len(sig) == len(close)
        assert list(sig.columns) == ["signal"]

    def test_raises_lookback_too_small(self) -> None:
        close = _ar1_prices(phi=0.35, sigma=0.01, n=400, seed=0)
        with pytest.raises(ValueError, match="lookback must be >= 60"):
            forecast_signal_series(close, lookback=59)

    def test_raises_refit_every_zero(self) -> None:
        close = _ar1_prices(phi=0.35, sigma=0.01, n=400, seed=0)
        with pytest.raises(ValueError, match="refit_every must be >= 1"):
            forecast_signal_series(close, lookback=100, refit_every=0)

    def test_raises_refit_every_negative(self) -> None:
        close = _ar1_prices(phi=0.35, sigma=0.01, n=400, seed=0)
        with pytest.raises(ValueError, match="refit_every must be >= 1"):
            forecast_signal_series(close, lookback=100, refit_every=-5)

    def test_raises_ma_order(self) -> None:
        """A moving-average term (q > 0) is unsupported by the AR recursion."""
        close = _ar1_prices(phi=0.35, sigma=0.01, n=400, seed=0)
        with pytest.raises(ValueError, match="pure AR"):
            forecast_signal_series(close, order=(1, 0, 1), lookback=100)

    def test_raises_integrated_order(self) -> None:
        """A differencing term (d > 0) is unsupported by the AR recursion."""
        close = _ar1_prices(phi=0.35, sigma=0.01, n=400, seed=0)
        with pytest.raises(ValueError, match="pure AR"):
            forecast_signal_series(close, order=(1, 1, 0), lookback=100)

    def test_constant_prices_all_nan(self) -> None:
        """Constant prices produce zero log-returns, so trailing std is zero.

        The standardisation step divides by trailing_std, which is 0 for a
        constant series.  All signal values after warmup should be NaN (the
        ``trailing_std <= 0.0`` guard is taken).
        """
        n = 200
        close = pd.Series(np.full(n, 100.0))
        sig = forecast_signal_series(close, lookback=60, refit_every=20)
        # With zero returns, trailing_std is 0 -> signal stays NaN.
        assert sig["signal"].isna().all()

    def test_fit_always_fails_gives_all_nan(self) -> None:
        """Using an order that requires more observations than the lookback window
        causes fit_arima to always raise ValueError.  This exercises the
        ``except Exception: pass`` branch and the ``if not has_model: continue``
        guard.  When no model is ever fitted, the whole signal stays NaN.

        AR(60) with lookback=60 needs min_obs=62 > 60, so every fit call raises.
        """
        rng = np.random.default_rng(7)
        prices = 100.0 * np.exp(np.cumsum(rng.standard_normal(200) * 0.01))
        close = pd.Series(prices)
        sig = forecast_signal_series(close, order=(60, 0, 0), lookback=60, refit_every=1)
        # All fits fail -> has_model stays False -> all NaN.
        assert sig["signal"].isna().all()

    def test_nan_in_recent_returns_gives_nan_signal(self) -> None:
        """A NaN price inside the active region of the series causes the
        corresponding log-return to be NaN, which triggers the
        ``if not np.isfinite(recent_returns).all(): continue`` guard.

        The signal at the bar with a NaN price should remain NaN; surrounding
        bars should still produce finite signals (once the NaN is out of the
        recent-returns window).
        """
        rng = np.random.default_rng(13)
        prices = 100.0 * np.exp(np.cumsum(rng.standard_normal(400) * 0.01))
        # Insert a NaN deep into the series, well past the warmup.
        prices[300] = float("nan")
        close = pd.Series(prices)
        sig = forecast_signal_series(close, lookback=60, refit_every=20)
        # Bar 300 (and 301 which uses it as recent return) should be NaN.
        assert np.isnan(sig["signal"].iloc[300])
        # Some bars after the NaN window passes should be finite.
        assert sig["signal"].iloc[310:].notna().any()

    def test_non_finite_window_skips_refit(self) -> None:
        """A price series with an embedded NaN causes the window to contain NaN.

        The ``if np.isfinite(window).all()`` guard prevents the fit from being
        called on a window with NaN, so the series starts producing signals
        only after a clean window is available.
        """
        rng = np.random.default_rng(7)
        prices = 100.0 * np.exp(np.cumsum(rng.standard_normal(250) * 0.01))
        # Insert a NaN at index 100 (inside the first lookback window).
        prices_with_nan = prices.copy()
        prices_with_nan[100] = float("nan")
        close = pd.Series(prices_with_nan)
        # Should not raise; NaN windows are silently skipped.
        sig = forecast_signal_series(close, lookback=150, refit_every=20)
        assert isinstance(sig, pd.DataFrame)
        assert "signal" in sig.columns


# ---------------------------------------------------------------------------
# forecast_positions
# ---------------------------------------------------------------------------


class TestForecastPositions:
    def test_values_in_set(self) -> None:
        """All returned values must be in {-1.0, 0.0, 1.0}."""
        close = _ar1_prices(phi=0.35, sigma=0.01, n=_N, seed=_PROMOTE_SEED)
        sig = forecast_signal_series(close, lookback=_LOOKBACK, refit_every=_REFIT)
        pos = forecast_positions(sig["signal"])
        unique = set(np.unique(pos.to_numpy()))
        assert unique.issubset({-1.0, 0.0, 1.0})

    def test_long_on_positive_signal(self) -> None:
        """A signal above +entry gives position +1."""
        s = pd.Series([0.5, 1.0, 2.0])
        pos = forecast_positions(s, entry=0.25)
        assert (pos.to_numpy() == 1.0).all()

    def test_short_on_negative_signal(self) -> None:
        """A signal below -entry gives position -1."""
        s = pd.Series([-0.5, -1.0, -2.0])
        pos = forecast_positions(s, entry=0.25)
        assert (pos.to_numpy() == -1.0).all()

    def test_flat_within_band(self) -> None:
        """A signal within [-entry, +entry] gives position 0."""
        s = pd.Series([0.1, 0.0, -0.1])
        pos = forecast_positions(s, entry=0.25)
        assert (pos.to_numpy() == 0.0).all()

    def test_nan_signal_gives_flat(self) -> None:
        """NaN signal values must map to 0 (not raise and not propagate NaN)."""
        s = pd.Series([float("nan"), 1.0, float("nan")])
        pos = forecast_positions(s, entry=0.25)
        assert pos.iloc[0] == 0.0
        assert pos.iloc[1] == 1.0
        assert pos.iloc[2] == 0.0

    def test_raises_negative_entry(self) -> None:
        s = pd.Series([0.5, -0.5])
        with pytest.raises(ValueError, match="entry threshold must be >= 0"):
            forecast_positions(s, entry=-0.1)

    def test_index_preserved(self) -> None:
        """Output series must be indexed identically to the input signal."""
        idx = pd.date_range("2020-01-01", periods=5, freq="B")
        s = pd.Series([0.5, -0.5, 0.1, float("nan"), -0.3], index=idx)
        pos = forecast_positions(s, entry=0.25)
        pd.testing.assert_index_equal(pos.index, s.index)


# ---------------------------------------------------------------------------
# build_forecast_weight_fn
# ---------------------------------------------------------------------------


class TestBuildForecastWeightFn:
    def test_returns_callable(self) -> None:
        """The builder must return a callable."""
        close = _ar1_prices(phi=0.35, sigma=0.01, n=400, seed=0)
        rule = build_forecast_weight_fn(close, lookback=150, refit_every=20)
        assert callable(rule)

    def test_weight_frame_shape(self) -> None:
        """The weight frame must be (n_bars, 1) with the symbol as the column name."""
        close = _ar1_prices(phi=0.35, sigma=0.01, n=400, seed=0)
        panel = price_panel_from_series(close, symbol="SIM")
        px = panel.xs("SIM", level="symbol")["close"]
        rule = build_forecast_weight_fn(px, symbol="SIM", lookback=150, refit_every=20)
        weights = rule(panel, {"entry": 0.25})
        assert list(weights.columns) == ["SIM"]
        assert len(weights) == len(close)

    def test_weights_in_valid_range(self) -> None:
        """All weights must be in {-1.0, 0.0, 1.0}."""
        close = _ar1_prices(phi=0.35, sigma=0.01, n=400, seed=0)
        panel = price_panel_from_series(close, symbol="SIM")
        px = panel.xs("SIM", level="symbol")["close"]
        rule = build_forecast_weight_fn(px, symbol="SIM", lookback=150, refit_every=20)
        weights = rule(panel, {"entry": 0.0})
        unique = set(np.unique(weights["SIM"].to_numpy()))
        assert unique.issubset({-1.0, 0.0, 1.0})


# ---------------------------------------------------------------------------
# forecast_grid
# ---------------------------------------------------------------------------


class TestForecastGrid:
    def test_default_length(self) -> None:
        """Default grid must have >= 5 configurations."""
        grid = forecast_grid()
        assert len(grid) >= 5

    def test_key_structure(self) -> None:
        """Each configuration must have exactly one key: 'entry'."""
        for cfg in forecast_grid():
            assert set(cfg) == {"entry"}

    def test_custom_entries(self) -> None:
        grid = forecast_grid(entries=(0.0, 0.5, 1.0))
        assert len(grid) == 3
        assert [cfg["entry"] for cfg in grid] == [0.0, 0.5, 1.0]

    def test_floats(self) -> None:
        """All entry values must be float."""
        for cfg in forecast_grid():
            assert isinstance(cfg["entry"], float)


# ---------------------------------------------------------------------------
# Gate PROMOTES a genuinely predictable series
# ---------------------------------------------------------------------------


class TestGatePromotesGenuineEdge:
    def test_ar1_is_promoted(self) -> None:
        """AR(1) returns with phi=0.45 should clear the deflated-Sharpe gate.

        phi=0.45 gives strong positive autocorrelation that ARIMA(1,0,0) can
        exploit.  The signal is momentum-based: forecast predicts positive
        return -> go long.  With 1200 bars and low noise the DSR should clearly
        exceed 0.95.
        """
        t0 = time.monotonic()
        close = _ar1_prices(phi=0.45, sigma=0.008, n=_N, seed=_PROMOTE_SEED)
        ev = _run_gate(close, "ARIMA AR(1) momentum (genuine edge)")
        elapsed = time.monotonic() - t0
        print(f"\n[PROMOTE test] elapsed={elapsed:.1f}s")
        if ev.deflated is not None:
            print(
                f"  deflated_sharpe={ev.deflated.deflated_sharpe:.4f}  "
                f"n_obs={ev.deflated.n_obs}"
            )
        print(f"  verdict={ev.verdict}  observed_sharpe={ev.observed_sharpe_annualised:.4f}")
        assert ev.is_promoted, (
            f"Expected PROMOTE but got {ev.verdict}. "
            f"DSR={ev.deflated.deflated_sharpe if ev.deflated else 'n/a':.4f}. "
            "Consider raising phi or increasing _N."
        )
        assert ev.deflated is not None
        assert ev.deflated.is_significant, (
            f"Deflated Sharpe {ev.deflated.deflated_sharpe:.4f} did not exceed 0.95. "
            "Strengthen the autocorrelation."
        )

    def test_ar1_metadata(self) -> None:
        """The evaluation result must have correct structural metadata."""
        close = _ar1_prices(phi=0.45, sigma=0.008, n=_N, seed=_PROMOTE_SEED)
        ev = _run_gate(close, "ARIMA AR(1) momentum (genuine edge)")
        assert ev.n_trials == len(forecast_grid())
        assert set(ev.best_params) == {"entry"}
        assert ev.modes_agree
        assert "PROMOTE" in ev.memo
        assert ev.memo.isascii()


# ---------------------------------------------------------------------------
# Gate ARCHIVES unpredictable noise
# ---------------------------------------------------------------------------


class TestGateRejectsNoise:
    def test_iid_noise_is_archived(self) -> None:
        """i.i.d. Gaussian returns have no autocorrelation -- the gate must archive."""
        t0 = time.monotonic()
        close = _iid_prices(n=_N, seed=_ARCHIVE_SEED)
        ev = _run_gate(close, "ARIMA AR(1) momentum (i.i.d. noise)")
        elapsed = time.monotonic() - t0
        print(f"\n[ARCHIVE test] elapsed={elapsed:.1f}s")
        if ev.deflated is not None:
            print(f"  deflated_sharpe={ev.deflated.deflated_sharpe:.4f}")
        else:
            print("  deflated_sharpe=n/a (no active trades in best config)")
        print(f"  verdict={ev.verdict}")
        dsr_str = f"{ev.deflated.deflated_sharpe:.4f}" if ev.deflated is not None else "n/a"
        assert ev.verdict == "ARCHIVE", (
            f"Expected ARCHIVE but got {ev.verdict}. DSR={dsr_str}."
        )


# ---------------------------------------------------------------------------
# Module-level wall-clock timing (informational, printed to stdout)
# ---------------------------------------------------------------------------


class TestModuleRuntime:
    def test_runtime_budget(self) -> None:
        """Full gate runs (PROMOTE + ARCHIVE) must finish within ~90 s combined.

        This test re-runs both gate evaluations and fails if the combined wall
        clock exceeds the budget, so CI does not silently regress on runtime.
        """
        t0 = time.monotonic()
        promote_close = _ar1_prices(phi=0.45, sigma=0.008, n=_N, seed=_PROMOTE_SEED)
        _run_gate(promote_close, "budget-promote")
        archive_close = _iid_prices(n=_N, seed=_ARCHIVE_SEED)
        _run_gate(archive_close, "budget-archive")
        elapsed = time.monotonic() - t0
        print(f"\n[Runtime budget] combined elapsed={elapsed:.1f}s (budget=90s)")
        assert elapsed < 90.0, (
            f"Combined gate runs took {elapsed:.1f}s, exceeding 90s budget. "
            "Raise refit_every or shorten _N."
        )
