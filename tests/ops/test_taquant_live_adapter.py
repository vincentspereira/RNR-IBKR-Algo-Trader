"""Unit tests for the TAQuant live-runner adapter."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core_trading.ops.taquant_live_adapter import (
    CLOSE_ONLY_PRIMARIES,
    TAQuantRunnerConfig,
    TAQuantRunnerStrategy,
)
from core_trading.strategies.ta_quant import (
    TAQuantConfig,
    TAQuantStrategy,
    build_ta_quant_grid,
)
from core_trading.strategies.ta_quant.primaries import (
    DonchianBreakoutConfig,
    RSIDipConfig,
)


def _close_frame(n: int = 320, symbols: tuple[str, ...] = ("AAA", "BBB")) -> pd.DataFrame:
    """Trending closes with periodic dips so rsi_dip actually fires."""
    idx = pd.bdate_range("2024-01-02", periods=n)
    rng = np.random.default_rng(7)
    data = {}
    for k, sym in enumerate(symbols):
        # Strong uptrend with shallow two-day dips: the entry needs BOTH
        # RSI(2) < 15 (consecutive down days) AND close above the SMA-200,
        # so the dip must not knock the price below its own trend.
        drift = 0.0020 + 0.0002 * k
        r = rng.normal(drift, 0.005, n)
        r[60::37] = -0.012
        r[61::37] = -0.012
        data[sym] = 100.0 * np.cumprod(1.0 + r)
    return pd.DataFrame(data, index=idx)


def _rsi_config() -> TAQuantConfig:
    grid = dict(build_ta_quant_grid())
    return grid["rsi2t15_trend200"]


class TestConstruction:
    def test_rejects_high_low_primary(self) -> None:
        cfg = TAQuantConfig(
            primary="donchian_breakout", primary_config=DonchianBreakoutConfig()
        )
        with pytest.raises(ValueError, match="high/low"):
            TAQuantRunnerStrategy(cfg)

    def test_accepts_all_close_only_primaries(self) -> None:
        assert {"rsi_dip", "ma_cross", "macd_trend", "bollinger_fade"} == set(
            CLOSE_ONLY_PRIMARIES
        )

    def test_formation_window_exposed_for_runner(self) -> None:
        s = TAQuantRunnerStrategy(_rsi_config(), formation_window=252)
        assert s.config.formation_window == 252

    def test_bad_formation_window(self) -> None:
        with pytest.raises(ValueError, match="formation_window"):
            TAQuantRunnerConfig(formation_window=0)


class TestGenerateWeights:
    def test_shape_and_columns_match_input(self) -> None:
        closes = _close_frame()
        s = TAQuantRunnerStrategy(_rsi_config())
        w = s.generate_weights(closes)
        assert list(w.columns) == list(closes.columns)
        assert w.index.equals(closes.index)
        assert not w.isna().any().any()

    def test_matches_inner_strategy_on_close_only_panel(self) -> None:
        """Adapter output is bit-identical to TAQuantStrategy on the same data."""
        closes = _close_frame()
        adapter = TAQuantRunnerStrategy(_rsi_config())
        w_adapter = adapter.generate_weights(closes)

        inner = TAQuantStrategy(_rsi_config())
        panel = TAQuantRunnerStrategy._close_only_panel(closes)
        w_inner = inner.generate_weights(panel).reindex(columns=closes.columns)
        pd.testing.assert_frame_equal(w_adapter, w_inner.fillna(0.0))

    def test_long_only_and_gross_capped(self) -> None:
        closes = _close_frame()
        s = TAQuantRunnerStrategy(_rsi_config())
        w = s.generate_weights(closes)
        assert (w >= 0.0).all().all()  # rsi2t15 is long-only
        assert (w.abs().sum(axis=1) <= 1.0 + 1e-9).all()

    def test_dips_actually_generate_positions(self) -> None:
        closes = _close_frame()
        s = TAQuantRunnerStrategy(_rsi_config())
        w = s.generate_weights(closes)
        assert float(w.abs().sum().sum()) > 0.0, "no signal fired on dip-seeded data"

    def test_works_with_volt_overlay_config(self) -> None:
        grid = dict(build_ta_quant_grid())
        s = TAQuantRunnerStrategy(grid["rsi2t10_trend200_volt10"])
        w = s.generate_weights(_close_frame())
        # vol targeting may lever up to 2x
        assert (w.abs().sum(axis=1) <= 2.0 + 1e-9).all()

    def test_single_symbol_frame(self) -> None:
        closes = _close_frame(symbols=("ONLY",))
        s = TAQuantRunnerStrategy(
            TAQuantConfig(
                primary="rsi_dip",
                primary_config=RSIDipConfig(rsi_window=2, lower_thresh=15.0),
            )
        )
        w = s.generate_weights(closes)
        assert list(w.columns) == ["ONLY"]
