"""Tests for core_trading.strategies.ta_quant.strategy.

Coverage:
- Weight frame shape/index/columns match the price panel.
- Gross sum of absolute weights <= gross_cap + tolerance on every bar.
- long_short_demean makes row sums ~0 on active bars.
- End-to-end run through BacktestEngine produces finite returns.
- Diagnostics attributes populated after generate_weights.
- OverlaySpec and TAQuantConfig validation.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core_trading.backtest.engine import BacktestConfig, BacktestEngine
from core_trading.research.signal_evaluation import price_panel_from_frame
from core_trading.strategies.ta_quant.primaries import (
    BollingerFadeConfig,
    DonchianBreakoutConfig,
    KeltnerSqueezeConfig,
    MACDTrendConfig,
    MACrossConfig,
    RSIDipConfig,
)
from core_trading.strategies.ta_quant.strategy import (
    OverlaySpec,
    TAQuantConfig,
    TAQuantStrategy,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SYMS = ["AAPL", "MSFT", "GOOG"]
_N = 300


def _make_panel(n: int = _N, seed: int = 55) -> pd.DataFrame:
    """Build a minimal (symbol, timestamp) MultiIndex OHLCV panel."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2019-01-01", periods=n, freq="B")
    records = []
    for sym in _SYMS:
        close = 100.0 + np.cumsum(rng.normal(0, 0.5, n))
        close = np.clip(close, 1.0, None)
        high = close + rng.uniform(0.1, 1.0, n)
        low = close - rng.uniform(0.1, 1.0, n)
        low = np.clip(low, 0.01, None)
        open_ = low + rng.uniform(0.0, 1.0, n) * (high - low)
        volume = rng.integers(500_000, 5_000_000, n).astype(float)
        df = pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
            index=idx,
        )
        df.index.name = "timestamp"
        df["symbol"] = sym
        records.append(df.reset_index().set_index(["symbol", "timestamp"]))
    return pd.concat(records).sort_index()


# ---------------------------------------------------------------------------
# OverlaySpec validation
# ---------------------------------------------------------------------------


class TestOverlaySpec:
    def test_invalid_name_raises(self) -> None:
        with pytest.raises(ValueError, match="not recognised"):
            OverlaySpec("bad_overlay_name")

    def test_valid_names_accepted(self) -> None:
        for name in ("vol_regime", "trend_regime", "vol_target"):
            spec = OverlaySpec(name)
            assert spec.name == name

    def test_build_returns_correct_type(self) -> None:
        from core_trading.strategies.ta_quant.overlays import (
            TrendRegimeGate,
            VolRegimeGate,
            VolTargetScaler,
        )

        assert isinstance(OverlaySpec("vol_regime").build(), VolRegimeGate)
        assert isinstance(OverlaySpec("trend_regime").build(), TrendRegimeGate)
        assert isinstance(OverlaySpec("vol_target").build(), VolTargetScaler)


# ---------------------------------------------------------------------------
# TAQuantConfig validation
# ---------------------------------------------------------------------------


class TestTAQuantConfig:
    def test_invalid_primary_raises(self) -> None:
        with pytest.raises(ValueError, match="not recognised"):
            TAQuantConfig(primary="foobar")

    def test_zero_gross_cap_raises(self) -> None:
        with pytest.raises(ValueError, match="gross_cap"):
            TAQuantConfig(primary="ma_cross", gross_cap=0.0)

    def test_valid_config_constructs(self) -> None:
        cfg = TAQuantConfig(
            primary="donchian_breakout",
            primary_config=DonchianBreakoutConfig(channel_window=20),
            overlay_specs=(OverlaySpec("trend_regime"),),
            gross_cap=1.0,
            long_short_demean=False,
        )
        assert cfg.primary == "donchian_breakout"


# ---------------------------------------------------------------------------
# TAQuantStrategy -- weight frame contract
# ---------------------------------------------------------------------------


class TestTAQuantStrategyWeightFrame:
    def test_output_shape_and_index(self) -> None:
        panel = _make_panel()
        cfg = TAQuantConfig(primary="ma_cross")
        strat = TAQuantStrategy(cfg)
        weights = strat.generate_weights(panel)
        # Expected index: unique timestamps in panel.
        timestamps = panel.index.get_level_values("timestamp").unique().sort_values()
        assert list(weights.index) == list(timestamps)
        # Columns come from unstack("symbol") which sorts alphabetically.
        assert set(weights.columns) == set(_SYMS)
        assert len(weights.columns) == len(_SYMS)

    def test_no_nan_in_weights(self) -> None:
        panel = _make_panel()
        strat = TAQuantStrategy(TAQuantConfig(primary="ma_cross"))
        weights = strat.generate_weights(panel)
        assert not weights.isna().any().any(), "weight frame must be NaN-free"

    def test_gross_cap_respected(self) -> None:
        panel = _make_panel()
        gross_cap = 0.8
        cfg = TAQuantConfig(primary="ma_cross", gross_cap=gross_cap)
        strat = TAQuantStrategy(cfg)
        weights = strat.generate_weights(panel)
        gross = weights.abs().sum(axis=1)
        # Allow a small floating-point tolerance.
        assert (gross <= gross_cap + 1e-9).all(), f"gross exceeds cap {gross_cap}: {gross.max()}"

    def test_long_short_demean_row_sums_near_zero(self) -> None:
        panel = _make_panel()
        cfg = TAQuantConfig(
            primary="ma_cross",
            primary_config=MACrossConfig(fast_window=10, slow_window=50, long_only=False),
            long_short_demean=True,
        )
        strat = TAQuantStrategy(cfg)
        weights = strat.generate_weights(panel)
        # On active bars the row sum should be approximately 0.
        row_sums = weights.sum(axis=1)
        active = weights.abs().sum(axis=1) > 1e-9
        if active.any():
            max_abs_sum = float(row_sums[active].abs().max())
            assert max_abs_sum < 1e-9 + 0.01, (
                f"long_short_demean: active row sum {max_abs_sum:.6f} is too large"
            )

    def test_diagnostics_populated(self) -> None:
        panel = _make_panel()
        strat = TAQuantStrategy(TAQuantConfig(primary="ma_cross"))
        strat.generate_weights(panel)
        assert strat.last_positions is not None
        assert strat.last_active_count is not None
        assert len(strat.last_active_count) == len(
            panel.index.get_level_values("timestamp").unique()
        )

    @pytest.mark.parametrize(
        "primary_name,primary_cfg",
        [
            ("donchian_breakout", DonchianBreakoutConfig(channel_window=20)),
            ("ma_cross", MACrossConfig(fast_window=10, slow_window=50)),
            ("rsi_dip", RSIDipConfig(rsi_window=2, trend_window=50)),
            ("macd_trend", MACDTrendConfig(fast=8, slow=17, signal_period=5)),
            ("bollinger_fade", BollingerFadeConfig(window=20, min_bandwidth=0.001)),
            ("keltner_squeeze", KeltnerSqueezeConfig()),
        ],
    )
    def test_all_primaries_run_without_error(self, primary_name: str, primary_cfg: object) -> None:
        panel = _make_panel()
        cfg = TAQuantConfig(primary=primary_name, primary_config=primary_cfg)
        strat = TAQuantStrategy(cfg)
        weights = strat.generate_weights(panel)
        assert isinstance(weights, pd.DataFrame)
        assert not weights.isna().any().any()


# ---------------------------------------------------------------------------
# TAQuantStrategy -- end-to-end backtest
# ---------------------------------------------------------------------------


class TestTAQuantStrategyEndToEnd:
    def test_backtest_produces_finite_returns(self) -> None:
        panel = _make_panel()
        cfg = TAQuantConfig(
            primary="ma_cross",
            primary_config=MACrossConfig(fast_window=10, slow_window=30, long_only=False),
            overlay_specs=(OverlaySpec("trend_regime", {"trend_window": 50}),),
            gross_cap=1.0,
        )
        strat = TAQuantStrategy(cfg)
        engine = BacktestEngine(BacktestConfig(cost_model_name="zero"))
        result = engine.run(panel, strat, mode="vectorised")
        assert result.returns.isna().sum() == 0, "returns must be finite"
        assert np.isfinite(result.returns.to_numpy()).all()

    def test_backtest_with_vol_target_overlay(self) -> None:
        panel = _make_panel()
        cfg = TAQuantConfig(
            primary="donchian_breakout",
            primary_config=DonchianBreakoutConfig(channel_window=20),
            overlay_specs=(OverlaySpec("vol_target", {"target_vol": 0.15, "vol_window": 40}),),
            gross_cap=2.0,
        )
        strat = TAQuantStrategy(cfg)
        engine = BacktestEngine(BacktestConfig(cost_model_name="zero"))
        result = engine.run(panel, strat, mode="vectorised")
        assert np.isfinite(result.returns.to_numpy()).all()

    def test_backtest_equity_is_positive(self) -> None:
        panel = _make_panel()
        strat = TAQuantStrategy(TAQuantConfig(primary="rsi_dip"))
        engine = BacktestEngine(BacktestConfig(cost_model_name="zero"))
        result = engine.run(panel, strat, mode="vectorised")
        assert (result.equity > 0).all(), "equity should remain positive"

    def test_price_panel_from_frame_compatibility(self) -> None:
        """Verify price_panel_from_frame produces a panel the strategy accepts."""
        rng = np.random.default_rng(22)
        n = 200
        idx = pd.date_range("2020-01-01", periods=n, freq="B")
        close_wide = pd.DataFrame(
            {sym: 100.0 + np.cumsum(rng.normal(0, 0.5, n)) for sym in _SYMS},
            index=idx,
        )
        panel = price_panel_from_frame(close_wide)
        strat = TAQuantStrategy(TAQuantConfig(primary="ma_cross"))
        weights = strat.generate_weights(panel)
        assert weights.shape == (n, len(_SYMS))
