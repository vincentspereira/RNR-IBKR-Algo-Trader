"""Gate-wiring (DOD) tests for the classical strategy adapters.

The Definition-of-Done for any new strategy: it runs through the real
:func:`~core_trading.research.signal_evaluation.evaluate_signal` deflated-Sharpe
gate, a synthetic series engineered for the rule PROMOTES, and a random walk
ARCHIVES.

Covers both adapters:
* classical_breakout: squeeze->volume-backed-expansion path PROMOTES; RW ARCHIVES.
* classical_vw_trend: persistent-trend path PROMOTES; RW ARCHIVES.
Plus ohlcv_panel construction/validation and grid shape.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core_trading.research.signal_adapters.classical_breakout import (
    breakout_grid,
    build_breakout_weight_fn,
    evaluate_breakout,
    ohlcv_panel,
)
from core_trading.research.signal_adapters.classical_vw_trend import (
    build_vw_trend_weight_fn,
    evaluate_vw_trend,
    vw_trend_grid,
)

_PROMOTE_SEED = 20260605
_RW_SEED = 42


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _vol_regime_ohlcv(n: int = 1600, seed: int = _PROMOTE_SEED) -> pd.DataFrame:
    """Squeeze then directional volume-backed expansion -> breakout edge."""
    rng = np.random.default_rng(seed)
    rets = np.zeros(n, dtype=float)
    vol = np.full(n, 1.0, dtype=float)
    t = 0
    squeeze_len, expand_len = 60, 40
    sign = 1.0
    while t < n:
        s_end = min(t + squeeze_len, n)
        rets[t:s_end] = rng.normal(0.0, 0.002, s_end - t)
        vol[t:s_end] = 1.0
        t = s_end
        if t >= n:
            break
        e_end = min(t + expand_len, n)
        rets[t:e_end] = sign * 0.012 + rng.normal(0.0, 0.004, e_end - t)
        vol[t:e_end] = 3.5
        sign = -sign
        t = e_end
    close = 100.0 * np.exp(np.cumsum(rets))
    volume = np.abs(1_000_000.0 * vol * (1.0 + rng.normal(0.0, 0.05, n)))
    high = close * (1.0 + np.abs(rng.normal(0.0, 0.001, n)))
    low = close * (1.0 - np.abs(rng.normal(0.0, 0.001, n)))
    return pd.DataFrame({"high": high, "low": low, "close": close, "volume": volume})


def _trend_ohlcv(n: int = 1600, seed: int = _PROMOTE_SEED) -> pd.DataFrame:
    """Persistent sign-flipping trend -> VW-trend edge."""
    rng = np.random.default_rng(seed)
    seg = 200
    drift = 0.006
    rets = np.empty(n, dtype=float)
    t = 0
    while t < n:
        end = min(t + seg, n)
        sign = 1.0 if (t // seg) % 2 == 0 else -1.0
        rets[t:end] = sign * drift + rng.normal(0.0, 0.008, end - t)
        t = end
    close = 100.0 * np.exp(np.cumsum(rets))
    volume = np.abs(1_000_000.0 * (1.0 + rng.normal(0.0, 0.2, n)))
    high = close * (1.0 + np.abs(rng.normal(0.0, 0.002, n)))
    low = close * (1.0 - np.abs(rng.normal(0.0, 0.002, n)))
    return pd.DataFrame({"high": high, "low": low, "close": close, "volume": volume})


def _rw_ohlcv(n: int = 1600, seed: int = _RW_SEED) -> pd.DataFrame:
    """Driftless Gaussian random walk: no edge for either rule."""
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, n)))
    volume = np.abs(1_000_000.0 * (1.0 + rng.normal(0.0, 0.3, n)))
    high = close * (1.0 + np.abs(rng.normal(0.0, 0.002, n)))
    low = close * (1.0 - np.abs(rng.normal(0.0, 0.002, n)))
    return pd.DataFrame({"high": high, "low": low, "close": close, "volume": volume})


# ---------------------------------------------------------------------------
# ohlcv_panel
# ---------------------------------------------------------------------------


class TestOhlcvPanel:
    def test_shape_and_columns(self) -> None:
        df = _rw_ohlcv(n=100)
        panel = ohlcv_panel(df, symbol="SIM")
        assert set(panel.columns) == {"open", "high", "low", "close", "volume"}
        assert panel.index.names == ["symbol", "timestamp"]
        assert len(panel) == 100

    def test_open_equals_close(self) -> None:
        df = _rw_ohlcv(n=100)
        panel = ohlcv_panel(df)
        np.testing.assert_array_equal(panel["open"].to_numpy(), panel["close"].to_numpy())

    def test_preserves_high_low_volume(self) -> None:
        df = _rw_ohlcv(n=100)
        panel = ohlcv_panel(df, symbol="SIM")
        frame = panel.xs("SIM", level="symbol")
        np.testing.assert_array_equal(frame["high"].to_numpy(), df["high"].to_numpy())
        np.testing.assert_array_equal(frame["volume"].to_numpy(), df["volume"].to_numpy())

    def test_datetime_index_passthrough(self) -> None:
        df = _rw_ohlcv(n=50)
        df.index = pd.date_range("2021-01-01", periods=50, tz="UTC")
        panel = ohlcv_panel(df)
        ts = panel.index.get_level_values("timestamp")
        assert ts[0] == pd.Timestamp("2021-01-01", tz="UTC")

    def test_missing_column_raises(self) -> None:
        df = pd.DataFrame({"close": [1.0, 2.0], "volume": [1.0, 1.0]})
        with pytest.raises(ValueError, match="missing required columns"):
            ohlcv_panel(df)

    def test_too_few_rows_raises(self) -> None:
        df = _rw_ohlcv(n=100).iloc[:1]
        with pytest.raises(ValueError, match="at least 2 rows"):
            ohlcv_panel(df)

    def test_nonpositive_price_raises(self) -> None:
        df = _rw_ohlcv(n=10)
        df.iloc[3, df.columns.get_loc("close")] = -1.0
        with pytest.raises(ValueError, match="finite and strictly positive"):
            ohlcv_panel(df)


# ---------------------------------------------------------------------------
# Grids
# ---------------------------------------------------------------------------


class TestGrids:
    def test_breakout_grid_default(self) -> None:
        g = breakout_grid()
        assert len(g) == 6
        for cfg in g:
            assert "squeeze_q" in cfg and "vol_k" in cfg

    def test_breakout_grid_custom(self) -> None:
        g = breakout_grid(squeeze_qs=(0.3,), vol_ks=(1.0, 2.0))
        assert len(g) == 2

    def test_vw_trend_grid_default(self) -> None:
        g = vw_trend_grid()
        assert len(g) == 4
        for cfg in g:
            assert "adx_strong" in cfg and "adx_medium" in cfg
            assert cfg["adx_medium"] <= cfg["adx_strong"]

    def test_vw_trend_grid_custom(self) -> None:
        g = vw_trend_grid(thresholds=((25.0, 20.0), (30.0, 25.0)))
        assert len(g) == 2


# ---------------------------------------------------------------------------
# Weight-fn shape
# ---------------------------------------------------------------------------


class TestWeightFns:
    def test_breakout_weight_shape(self) -> None:
        df = _vol_regime_ohlcv(n=400)
        panel = ohlcv_panel(df, symbol="SIM")
        fn = build_breakout_weight_fn(symbol="SIM")
        w = fn(panel, {"squeeze_q": 0.3, "vol_k": 1.5})
        assert isinstance(w, pd.DataFrame)
        assert "SIM" in w.columns
        assert len(w) == len(df)
        assert set(np.unique(w["SIM"].to_numpy())).issubset({-1.0, 0.0, 1.0})

    def test_breakout_weight_uses_defaults_when_keys_absent(self) -> None:
        df = _vol_regime_ohlcv(n=400)
        panel = ohlcv_panel(df, symbol="SIM")
        fn = build_breakout_weight_fn(symbol="SIM")
        w = fn(panel, {})  # empty params -> base config
        assert len(w) == len(df)

    def test_vw_trend_weight_shape(self) -> None:
        df = _trend_ohlcv(n=400)
        panel = ohlcv_panel(df, symbol="SIM")
        fn = build_vw_trend_weight_fn(symbol="SIM")
        w = fn(panel, {"adx_strong": 25.0, "adx_medium": 20.0})
        assert "SIM" in w.columns
        assert len(w) == len(df)
        assert set(np.unique(w["SIM"].to_numpy())).issubset({-1.0, 0.0, 1.0})

    def test_vw_trend_weight_uses_defaults_when_keys_absent(self) -> None:
        df = _trend_ohlcv(n=400)
        panel = ohlcv_panel(df, symbol="SIM")
        fn = build_vw_trend_weight_fn(symbol="SIM")
        w = fn(panel, {})
        assert len(w) == len(df)


# ---------------------------------------------------------------------------
# Gate: breakout
# ---------------------------------------------------------------------------


class TestBreakoutGate:
    def test_promotes_engineered_path(self) -> None:
        df = _vol_regime_ohlcv(n=1600, seed=_PROMOTE_SEED)
        ev = evaluate_breakout(df)
        assert ev.is_promoted, (
            f"Expected PROMOTE; deflated={ev.deflated}, "
            f"sharpe={ev.observed_sharpe_annualised:.3f}"
        )
        assert ev.deflated is not None
        assert ev.deflated.is_significant
        assert ev.n_trials == 6
        assert ev.modes_agree

    def test_archives_random_walk(self) -> None:
        df = _rw_ohlcv(n=1600, seed=_RW_SEED)
        ev = evaluate_breakout(df)
        assert ev.verdict == "ARCHIVE", (
            f"Expected ARCHIVE; deflated={ev.deflated}, "
            f"sharpe={ev.observed_sharpe_annualised:.3f}"
        )

    def test_memo_present(self) -> None:
        df = _vol_regime_ohlcv(n=800)
        ev = evaluate_breakout(df)
        assert isinstance(ev.memo, str) and len(ev.memo) > 0


# ---------------------------------------------------------------------------
# Gate: VW trend
# ---------------------------------------------------------------------------


class TestVWTrendGate:
    def test_promotes_engineered_path(self) -> None:
        df = _trend_ohlcv(n=1600, seed=_PROMOTE_SEED)
        ev = evaluate_vw_trend(df)
        assert ev.is_promoted, (
            f"Expected PROMOTE; deflated={ev.deflated}, "
            f"sharpe={ev.observed_sharpe_annualised:.3f}"
        )
        assert ev.deflated is not None
        assert ev.deflated.is_significant
        assert ev.n_trials == 4
        assert ev.modes_agree

    def test_archives_random_walk(self) -> None:
        df = _rw_ohlcv(n=1600, seed=_RW_SEED)
        ev = evaluate_vw_trend(df)
        assert ev.verdict == "ARCHIVE", (
            f"Expected ARCHIVE; deflated={ev.deflated}, "
            f"sharpe={ev.observed_sharpe_annualised:.3f}"
        )

    def test_signal_name_propagates(self) -> None:
        df = _trend_ohlcv(n=800)
        ev = evaluate_vw_trend(df, signal_name="custom-name")
        assert ev.signal_name == "custom-name"
