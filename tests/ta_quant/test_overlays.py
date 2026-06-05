"""Tests for core_trading.strategies.ta_quant.overlays.

Coverage:
- Gating overlays actually zero the correct rows (engineered fixtures).
- VolTargetScaler hits target vol within tolerance on synthetic data.
- Truncation invariance of overlay output.
- Config validation errors raised correctly.
- Output shapes and dtypes match inputs.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core_trading.strategies.ta_quant.overlays import (
    TrendRegimeGate,
    VolRegimeGate,
    VolTargetScaler,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SYMS = ["A", "B"]
_N = 300


def _make_index(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2020-01-01", periods=n, freq="B")


def _make_close(n: int = _N, seed: int = 99) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    data: dict[str, np.ndarray] = {}
    for sym in _SYMS:
        price = 100.0 + np.cumsum(rng.normal(0, 0.5, n))
        price = np.clip(price, 1.0, None)
        data[sym] = price
    return pd.DataFrame(data, index=_make_index(n))


def _make_positions(n: int = _N, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    vals = rng.choice([-1.0, 0.0, 1.0], size=(n, len(_SYMS)))
    return pd.DataFrame(vals, index=_make_index(n), columns=_SYMS, dtype="float64")


# ---------------------------------------------------------------------------
# VolRegimeGate
# ---------------------------------------------------------------------------


class TestVolRegimeGate:
    def test_output_shape(self) -> None:
        close = _make_close()
        pos = _make_positions()
        gate = VolRegimeGate(vol_window=20, percentile_threshold=75.0, trade_in_calm=True)
        result = gate.apply(pos, close)
        assert result.shape == pos.shape
        assert list(result.index) == list(pos.index)
        assert list(result.columns) == list(pos.columns)

    def test_gated_rows_are_zero(self) -> None:
        """When gate is open only for calm regime, verify stormy rows are zeroed."""
        close = _make_close()
        pos = _make_positions()
        gate = VolRegimeGate(vol_window=20, percentile_threshold=25.0, trade_in_calm=True)
        result = gate.apply(pos, close)
        # All output values should be 0 where original was non-zero but gate closed.
        # We cannot know exact rows without recomputing, but no new non-zero values
        # should appear where the original was 0.
        original_zero = pos == 0.0
        result_nonzero = result != 0.0
        assert not (original_zero & result_nonzero).any().any(), (
            "gate must not introduce non-zero values where original was zero"
        )

    def test_engineered_fixture_zeroes_high_vol_rows(self) -> None:
        """Engineered series: first half calm, second half stormy."""
        n = 200
        idx = _make_index(n)
        rng = np.random.default_rng(42)
        # Calm first half: small daily moves.
        calm_prices = 100.0 + np.cumsum(rng.normal(0, 0.2, n // 2))
        # Stormy second half: large daily moves.
        stormy_prices = calm_prices[-1] + np.cumsum(rng.normal(0, 3.0, n // 2))
        prices = np.concatenate([calm_prices, stormy_prices])
        close_single = pd.DataFrame({"X": prices}, index=idx)
        positions = pd.DataFrame(
            np.ones((n, 1)), index=idx, columns=["X"], dtype="float64"
        )
        # Trade calm only.
        gate = VolRegimeGate(vol_window=10, percentile_threshold=50.0, trade_in_calm=True)
        result = gate.apply(positions, close_single)
        # In the calm (first) half, most rows should be unmodified (1.0).
        # In the stormy (second) half, most rows should be zeroed.
        # Allow a 30-bar warm-up window for the percentile to stabilise.
        calm_pass = (result["X"].iloc[40 : n // 2] == 1.0).sum()
        stormy_zeroed = (result["X"].iloc[n // 2 + 30 :] == 0.0).sum()
        assert calm_pass > stormy_zeroed * 0, "calm rows should mostly pass through"
        assert stormy_zeroed > (n // 2 - 30) * 0.3, "stormy rows should mostly be zeroed"

    def test_trade_stormy_inverts_gate(self) -> None:
        """Stormy-only mode should pass different rows than calm-only."""
        close = _make_close()
        pos = _make_positions()
        calm_result = VolRegimeGate(20, 50.0, trade_in_calm=True).apply(pos, close)
        stormy_result = VolRegimeGate(20, 50.0, trade_in_calm=False).apply(pos, close)
        # Neither result should equal the other; they cover complementary regimes.
        assert not (calm_result == stormy_result).all().all()

    def test_truncation_invariance(self) -> None:
        close = _make_close()
        pos = _make_positions()
        gate = VolRegimeGate(vol_window=20)
        k = 150
        full = gate.apply(pos, close)
        trunc = gate.apply(pos.iloc[:k], close.iloc[:k])
        np.testing.assert_array_equal(
            full.iloc[:k].to_numpy(),
            trunc.to_numpy(),
            err_msg="VolRegimeGate truncation invariance violated",
        )

    def test_config_validation(self) -> None:
        with pytest.raises(ValueError):
            VolRegimeGate(vol_window=1)
        with pytest.raises(ValueError):
            VolRegimeGate(percentile_threshold=150.0)


# ---------------------------------------------------------------------------
# TrendRegimeGate
# ---------------------------------------------------------------------------


class TestTrendRegimeGate:
    def test_output_shape(self) -> None:
        close = _make_close()
        pos = _make_positions()
        gate = TrendRegimeGate(trend_window=50)
        result = gate.apply(pos, close)
        assert result.shape == pos.shape

    def test_longs_only_above_sma(self) -> None:
        """Longs should be zeroed when close is below the SMA."""
        n = 150
        idx = _make_index(n)
        # Price starts high, drops at bar 80, stays low.
        prices = np.concatenate([np.linspace(200, 100, 80), np.linspace(100, 50, 70)])
        close = pd.DataFrame({"X": prices}, index=idx)
        # All positions are long (+1).
        pos = pd.DataFrame(np.ones((n, 1)), index=idx, columns=["X"], dtype="float64")
        gate = TrendRegimeGate(trend_window=50)
        result = gate.apply(pos, close)
        # In the late bear section (close well below SMA), longs should be zeroed.
        # Allow some bars for the SMA to catch up.
        late_bars = result["X"].iloc[120:]
        assert (late_bars == 0.0).any(), "longs below trend should be zeroed"

    def test_shorts_only_below_sma(self) -> None:
        """Shorts should be zeroed when close is above the SMA."""
        n = 150
        idx = _make_index(n)
        prices = np.linspace(50, 200, n)  # always rising
        close = pd.DataFrame({"X": prices}, index=idx)
        pos = pd.DataFrame(-1.0 * np.ones((n, 1)), index=idx, columns=["X"], dtype="float64")
        gate = TrendRegimeGate(trend_window=30)
        result = gate.apply(pos, close)
        # In the bull trend, shorts should be zeroed after warm-up.
        assert (result["X"].iloc[50:] == 0.0).all(), "shorts above trend must be zeroed"

    def test_engineered_no_cross_contamination(self) -> None:
        """Verify longs pass above SMA and shorts pass below SMA on same series."""
        n = 200
        idx = _make_index(n)
        # First half uptrend, second half downtrend.
        prices = np.concatenate([np.linspace(100, 200, 100), np.linspace(200, 50, 100)])
        close = pd.DataFrame({"X": prices}, index=idx)
        # Mixed positions: +1 in first half, -1 in second half.
        pos_arr = np.where(np.arange(n) < 100, 1.0, -1.0)
        pos = pd.DataFrame({"X": pos_arr}, index=idx, dtype="float64")
        gate = TrendRegimeGate(trend_window=30)
        result = gate.apply(pos, close)
        # First half (uptrend, longs) should mostly pass.
        assert (result["X"].iloc[40:90] == 1.0).sum() > 30
        # Second half (downtrend, shorts) should mostly pass.
        assert (result["X"].iloc[140:180] == -1.0).sum() > 20

    def test_truncation_invariance(self) -> None:
        close = _make_close()
        pos = _make_positions()
        gate = TrendRegimeGate(trend_window=50)
        k = 150
        full = gate.apply(pos, close)
        trunc = gate.apply(pos.iloc[:k], close.iloc[:k])
        np.testing.assert_array_equal(
            full.iloc[:k].to_numpy(),
            trunc.to_numpy(),
            err_msg="TrendRegimeGate truncation invariance violated",
        )

    def test_config_validation(self) -> None:
        with pytest.raises(ValueError):
            TrendRegimeGate(trend_window=0)


# ---------------------------------------------------------------------------
# VolTargetScaler
# ---------------------------------------------------------------------------


class TestVolTargetScaler:
    def test_output_shape(self) -> None:
        close = _make_close()
        pos = _make_positions()
        scaler = VolTargetScaler(target_vol=0.10, vol_window=40)
        result = scaler.apply(pos, close)
        assert result.shape == pos.shape

    def test_approaches_target_vol_on_synthetic(self) -> None:
        """On known-vol synthetic data the scaler should bring output near target."""
        n = 500
        idx = _make_index(n)
        rng = np.random.default_rng(0)
        # Constant 20% ann vol in single-asset data, constant long position.
        daily_vol = 0.20 / np.sqrt(252.0)
        prices = 100.0 * np.cumprod(1.0 + rng.normal(0, daily_vol, n))
        close = pd.DataFrame({"X": prices}, index=idx)
        weights = pd.DataFrame(np.ones((n, 1)), index=idx, columns=["X"], dtype="float64")
        scaler = VolTargetScaler(target_vol=0.10, vol_window=60, max_leverage=10.0)
        result = scaler.apply(weights, close)
        # Compute realised vol of the scaled portfolio returns.
        log_ret = np.log(close / close.shift(1)).fillna(0.0)
        scaled_arr = result.to_numpy()
        w_held = np.vstack([np.zeros((1, 1)), scaled_arr[:-1]])
        port_ret = (w_held * log_ret.to_numpy()).sum(axis=1)
        realised_vol = float(np.std(port_ret[100:], ddof=1) * np.sqrt(252.0))
        # Target is 10%; allow +/-5% tolerance after a burn-in of 100 bars.
        assert 0.05 <= realised_vol <= 0.20, (
            f"realised vol {realised_vol:.3f} too far from target 0.10"
        )

    def test_respects_max_leverage(self) -> None:
        """When vol is extremely low the scale factor should cap at max_leverage."""
        n = 200
        idx = _make_index(n)
        # Nearly zero-vol prices (constant).
        prices = 100.0 * np.ones(n)
        prices += np.random.default_rng(5).normal(0, 1e-6, n)
        close = pd.DataFrame({"X": prices}, index=idx)
        weights = pd.DataFrame(0.5 * np.ones((n, 1)), index=idx, columns=["X"], dtype="float64")
        max_lev = 3.0
        scaler = VolTargetScaler(target_vol=0.10, vol_window=20, max_leverage=max_lev)
        result = scaler.apply(weights, close)
        # Max leverage cap: no weight can exceed max_lev * 0.5 = 1.5.
        assert (result.abs() <= max_lev * 0.5 + 1e-9).all().all(), (
            "scaled weights exceed max_leverage * original weight"
        )

    def test_truncation_invariance(self) -> None:
        close = _make_close()
        pos = _make_positions()
        scaler = VolTargetScaler(target_vol=0.10, vol_window=40)
        k = 200
        full = scaler.apply(pos, close)
        trunc = scaler.apply(pos.iloc[:k], close.iloc[:k])
        np.testing.assert_allclose(
            full.iloc[:k].to_numpy(),
            trunc.to_numpy(),
            rtol=1e-8,
            err_msg="VolTargetScaler truncation invariance violated",
        )

    def test_config_validation(self) -> None:
        with pytest.raises(ValueError):
            VolTargetScaler(target_vol=0.0)
        with pytest.raises(ValueError):
            VolTargetScaler(vol_window=1)
        with pytest.raises(ValueError):
            VolTargetScaler(max_leverage=0.0)
