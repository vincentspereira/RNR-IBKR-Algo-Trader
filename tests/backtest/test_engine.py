"""Tests for core_trading.backtest.engine.

The headline guarantee -- vectorised and event-driven modes agree under a
frictionless cost model -- is in :class:`TestModeAgreement`. Determinism
(byte-identical replay) is in :class:`TestDeterminism`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core_trading.backtest.engine import BacktestConfig, BacktestEngine, WeightStrategy


def _const_weights(panel: pd.DataFrame, w: float = 0.5) -> pd.DataFrame:
    syms = list(panel.index.get_level_values("symbol").unique())
    idx = pd.DatetimeIndex(panel.index.get_level_values("timestamp").unique()).sort_values()
    return pd.DataFrame(w, index=idx, columns=syms)


class TestPanelValidation:
    def test_requires_multiindex(self) -> None:
        flat = pd.DataFrame(
            {"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1.0]}
        )
        eng = BacktestEngine()
        with pytest.raises(ValueError, match="MultiIndex"):
            eng.run_vectorised(flat, WeightStrategy(pd.DataFrame()))

    def test_index_names(self, panel: pd.DataFrame) -> None:
        bad = panel.copy()
        bad.index = bad.index.set_names(["sym", "ts"])
        with pytest.raises(ValueError, match="index names"):
            BacktestEngine().run_vectorised(bad, WeightStrategy(pd.DataFrame()))

    def test_missing_columns(self, panel: pd.DataFrame) -> None:
        bad = panel.drop(columns=["volume"])
        with pytest.raises(ValueError, match="missing required columns"):
            BacktestEngine().run_vectorised(bad, WeightStrategy(pd.DataFrame()))


class TestModeAgreement:
    def test_constant_weights_agree(self, panel: pd.DataFrame) -> None:
        strat = WeightStrategy(_const_weights(panel, 0.5))
        eng = BacktestEngine(BacktestConfig(cost_model_name="zero", max_participation_rate=1.0))
        rv = eng.run(panel, strat, mode="vectorised")
        re = eng.run(panel, strat, mode="event_driven")
        rel = float((rv.equity - re.equity).abs().div(re.equity).max())
        assert rel < 1e-4  # master plan: agree within 1bp/day

    def test_long_short_weights_agree(self, panel: pd.DataFrame) -> None:
        w = _const_weights(panel, 0.0)
        w["AAA"] = 0.6
        w["BBB"] = -0.4
        eng = BacktestEngine(BacktestConfig(cost_model_name="zero", max_participation_rate=1.0))
        rv = eng.run(panel, WeightStrategy(w), mode="vectorised")
        re = eng.run(panel, WeightStrategy(w), mode="event_driven")
        rel = float((rv.equity - re.equity).abs().div(re.equity).max())
        assert rel < 1e-4

    def test_time_varying_weights_agree(self, panel: pd.DataFrame) -> None:
        rng = np.random.default_rng(0)
        base = _const_weights(panel, 0.0)
        w = pd.DataFrame(
            rng.uniform(-0.3, 0.3, size=base.shape), index=base.index, columns=base.columns
        )
        eng = BacktestEngine(BacktestConfig(cost_model_name="zero", max_participation_rate=1.0))
        rv = eng.run(panel, WeightStrategy(w), mode="vectorised")
        re = eng.run(panel, WeightStrategy(w), mode="event_driven")
        rel = float((rv.equity - re.equity).abs().div(re.equity).max())
        assert rel < 1e-4


class TestDeterminism:
    def test_replay_byte_identical(self, panel: pd.DataFrame) -> None:
        strat = WeightStrategy(_const_weights(panel, 0.4))
        eng = BacktestEngine(BacktestConfig(cost_model_name="ibkr", max_participation_rate=1.0))
        r1 = eng.run(panel, strat, mode="event_driven")
        r2 = eng.run(panel, strat, mode="event_driven")
        assert r1.fingerprint() == r2.fingerprint()
        pd.testing.assert_series_equal(r1.equity, r2.equity)

    def test_different_inputs_differ(self, panel: pd.DataFrame) -> None:
        eng = BacktestEngine(BacktestConfig(cost_model_name="zero"))
        r1 = eng.run(panel, WeightStrategy(_const_weights(panel, 0.4)), mode="vectorised")
        r2 = eng.run(panel, WeightStrategy(_const_weights(panel, 0.5)), mode="vectorised")
        assert r1.fingerprint() != r2.fingerprint()


class TestCosts:
    def test_costs_reduce_returns(self, panel: pd.DataFrame) -> None:
        strat = WeightStrategy(_const_weights(panel, 0.5))
        free = BacktestEngine(BacktestConfig(cost_model_name="zero", max_participation_rate=1.0))
        costed = BacktestEngine(BacktestConfig(cost_model_name="ibkr", max_participation_rate=1.0))
        rf = free.run(panel, strat, mode="event_driven")
        rc = costed.run(panel, strat, mode="event_driven")
        assert rc.total_costs > 0
        assert rc.equity.iloc[-1] < rf.equity.iloc[-1]


class TestBehaviour:
    def test_buy_and_hold_tracks_asset(self, panel: pd.DataFrame) -> None:
        # 100% in AAA, 0 in BBB
        w = _const_weights(panel, 0.0)
        w["AAA"] = 1.0
        eng = BacktestEngine(BacktestConfig(cost_model_name="zero", max_participation_rate=1.0))
        res = eng.run(panel, WeightStrategy(w), mode="vectorised")
        close = panel.xs("AAA", level="symbol")["close"]
        asset_total = close.iloc[-1] / close.iloc[0] - 1.0
        strat_total = res.equity.iloc[-1] / res.initial_cash - 1.0
        assert strat_total == pytest.approx(asset_total, rel=1e-6)

    def test_weights_forward_filled(self, panel: pd.DataFrame) -> None:
        idx = pd.DatetimeIndex(panel.index.get_level_values("timestamp").unique()).sort_values()
        syms = list(panel.index.get_level_values("symbol").unique())
        sparse = pd.DataFrame(0.0, index=[idx[0]], columns=syms)
        sparse.loc[idx[0], "AAA"] = 0.5
        eng = BacktestEngine(BacktestConfig(cost_model_name="zero"))
        res = eng.run(panel, WeightStrategy(sparse), mode="vectorised")
        # weight held forward for the whole timeline
        assert res.weights["AAA"].iloc[-1] == pytest.approx(0.5)

    def test_integer_shares(self, panel: pd.DataFrame) -> None:
        strat = WeightStrategy(_const_weights(panel, 0.3))
        cfg = BacktestConfig(
            cost_model_name="zero", allow_fractional_shares=False, max_participation_rate=1.0
        )
        res = BacktestEngine(cfg).run(panel, strat, mode="event_driven")
        for t in res.trades:
            assert t.quantity == pytest.approx(round(t.quantity))

    def test_skips_symbol_with_missing_prices(self, panel: pd.DataFrame) -> None:
        # BBB only quotes from the 50th bar; earlier bars have NaN close and
        # must be skipped rather than sized.
        idx = pd.DatetimeIndex(panel.index.get_level_values("timestamp").unique()).sort_values()
        bbb = panel.xs("BBB", level="symbol").copy()
        bbb_late = bbb.iloc[50:]
        bbb_late.index = pd.MultiIndex.from_product(
            [["BBB"], bbb_late.index], names=["symbol", "timestamp"]
        )
        aaa = panel.loc[panel.index.get_level_values("symbol") == "AAA"]
        merged = pd.concat([aaa, bbb_late]).sort_index()
        w = pd.DataFrame(0.5, index=idx, columns=["AAA", "BBB"])
        res = BacktestEngine(
            BacktestConfig(cost_model_name="zero", max_participation_rate=1.0)
        ).run(merged, WeightStrategy(w), mode="event_driven")
        assert res.equity.size == len(idx)

    def test_partial_liquidity_limits_position(self, panel: pd.DataFrame) -> None:
        strat = WeightStrategy(_const_weights(panel, 0.5))
        cfg = BacktestConfig(cost_model_name="zero", max_participation_rate=0.0001)
        res = BacktestEngine(cfg).run(panel, strat, mode="event_driven")
        # severe liquidity cap -> equity barely moves from initial early on
        assert res.equity.iloc[0] == pytest.approx(res.initial_cash, rel=1e-3)


class TestDispatch:
    def test_unknown_mode(self, panel: pd.DataFrame) -> None:
        with pytest.raises(ValueError, match="unknown mode"):
            BacktestEngine().run(panel, WeightStrategy(_const_weights(panel)), mode="turbo")

    def test_weight_strategy_returns_frame(self, panel: pd.DataFrame) -> None:
        w = _const_weights(panel)
        assert WeightStrategy(w).generate_weights(panel) is w

    def test_non_frame_weights_rejected(self, panel: pd.DataFrame) -> None:
        class _Bad:
            def generate_weights(self, prices: pd.DataFrame) -> pd.DataFrame:  # noqa: ARG002
                return "not a frame"  # type: ignore[return-value]

        with pytest.raises(TypeError, match="must return a DataFrame"):
            BacktestEngine().run_vectorised(panel, _Bad())
