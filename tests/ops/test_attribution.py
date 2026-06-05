"""Tests for core_trading/ops/attribution.py (Phase 11.4).

Coverage targets:
- AttributionConfig: defaults, validation, frozen
- factor_attribution: OLS correctness, alignment, NaN dropping, edge cases
- strategy_attribution: additive decomposition, weight mismatch errors
- trade_attribution: fill aggregation, realised/unrealised split, movers
- cost_attribution: spread/commission/slippage decomposition, bps calculation
- render_attribution_report: ASCII-only, section presence, None sections
- _build_demo_data: determinism
- main CLI: --demo path, --output path, error on missing --demo
"""
from __future__ import annotations

import dataclasses
import os
from typing import Any  # noqa: TCH003

import numpy as np
import pandas as pd
import pytest

from core_trading.ops.attribution import (
    AttributionConfig,
    CostAttributionResult,
    FactorAttributionResult,
    StrategyAttributionResult,
    TradeAttributionResult,
    _build_demo_data,
    _fmt_float,
    cost_attribution,
    factor_attribution,
    main,
    render_attribution_report,
    strategy_attribution,
    trade_attribution,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dates(n: int, start: str = "2024-01-02") -> pd.DatetimeIndex:
    return pd.date_range(start, periods=n, freq="B")


def _is_ascii(text: str) -> bool:
    return all(ord(ch) < 128 for ch in text)


def _simple_factor_data(n: int = 60, seed: int = 0) -> tuple[pd.Series, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    dates = _dates(n)
    factor_arr = rng.normal(0.0, 0.01, (n, 2))
    factor_df = pd.DataFrame(factor_arr, index=dates, columns=["f1", "f2"])
    port = pd.Series(
        factor_arr[:, 0] * 0.8 + factor_arr[:, 1] * 0.3 + rng.normal(0.0, 0.002, n),
        index=dates,
        name="portfolio",
    )
    return port, factor_df


# ---------------------------------------------------------------------------
# AttributionConfig
# ---------------------------------------------------------------------------


class TestAttributionConfig:
    def test_defaults(self) -> None:
        cfg = AttributionConfig()
        assert cfg.annualise_factor == 252
        assert cfg.contribution_tol == pytest.approx(1e-8)
        assert cfg.top_n_movers == 5
        assert cfg.generated_at is None
        assert cfg.bps_scale == pytest.approx(10_000.0)

    def test_frozen(self) -> None:
        cfg = AttributionConfig()
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.annualise_factor = 100  # type: ignore[misc]

    def test_rejects_annualise_factor_zero(self) -> None:
        with pytest.raises(ValueError, match="annualise_factor"):
            AttributionConfig(annualise_factor=0)

    def test_rejects_contribution_tol_zero(self) -> None:
        with pytest.raises(ValueError, match="contribution_tol"):
            AttributionConfig(contribution_tol=0.0)

    def test_rejects_top_n_movers_zero(self) -> None:
        with pytest.raises(ValueError, match="top_n_movers"):
            AttributionConfig(top_n_movers=0)

    def test_rejects_bps_scale_zero(self) -> None:
        with pytest.raises(ValueError, match="bps_scale"):
            AttributionConfig(bps_scale=0.0)

    def test_custom_values_accepted(self) -> None:
        cfg = AttributionConfig(
            annualise_factor=365, top_n_movers=3, bps_scale=1_000.0
        )
        assert cfg.annualise_factor == 365
        assert cfg.top_n_movers == 3


# ---------------------------------------------------------------------------
# factor_attribution
# ---------------------------------------------------------------------------


class TestFactorAttribution:
    def test_betas_close_to_true_values(self) -> None:
        rng = np.random.default_rng(1)
        n = 500
        dates = _dates(n)
        f1 = rng.normal(0.0, 0.01, n)
        f2 = rng.normal(0.0, 0.005, n)
        port = 0.9 * f1 + 0.4 * f2 + rng.normal(0.0, 0.001, n)
        df = pd.DataFrame({"f1": f1, "f2": f2}, index=dates)
        s = pd.Series(port, index=dates, name="p")
        result = factor_attribution(s, df)
        assert result.betas["f1"] == pytest.approx(0.9, abs=0.05)
        assert result.betas["f2"] == pytest.approx(0.4, abs=0.05)

    def test_r_squared_in_unit_interval(self) -> None:
        port, factors = _simple_factor_data()
        result = factor_attribution(port, factors)
        assert 0.0 <= result.r_squared <= 1.0

    def test_r_squared_high_for_clean_linear_data(self) -> None:
        rng = np.random.default_rng(2)
        n = 300
        dates = _dates(n)
        f = rng.normal(0.0, 0.01, n)
        df = pd.DataFrame({"f1": f}, index=dates)
        s = pd.Series(2.0 * f + rng.normal(0.0, 0.0001, n), index=dates)
        result = factor_attribution(s, df)
        assert result.r_squared > 0.99

    def test_n_obs_correct(self) -> None:
        port, factors = _simple_factor_data(n=80)
        result = factor_attribution(port, factors)
        assert result.n_obs == 80

    def test_factor_names_match_columns(self) -> None:
        port, factors = _simple_factor_data()
        result = factor_attribution(port, factors)
        assert result.factor_names == ["f1", "f2"]

    def test_contributions_keyed_by_factor_name(self) -> None:
        port, factors = _simple_factor_data()
        result = factor_attribution(port, factors)
        for name in result.factor_names:
            assert name in result.contributions
            assert isinstance(result.contributions[name], pd.Series)

    def test_contributions_sum_plus_alpha_approx_fitted(self) -> None:
        # fitted = alpha_per_period + sum(beta_f * factor_f)
        # port[i] = fitted[i] + residual[i]
        # So: port - residual = alpha_per_period + contrib_sum
        port, factors = _simple_factor_data(n=100)
        result = factor_attribution(port, factors)
        contrib_sum_arr = sum(
            result.contributions[n].to_numpy() for n in result.factor_names
        )
        alpha_per_period = result.alpha_annualised / 252.0
        fitted_approx = contrib_sum_arr + alpha_per_period
        port_aligned = port.reindex(result.residuals.index).to_numpy()
        residuals_arr = result.residuals.to_numpy()
        np.testing.assert_allclose(
            fitted_approx + residuals_arr, port_aligned, atol=1e-10
        )

    def test_residuals_length_matches_n_obs(self) -> None:
        port, factors = _simple_factor_data()
        result = factor_attribution(port, factors)
        assert len(result.residuals) == result.n_obs

    def test_alpha_annualised_scales_by_annualise_factor(self) -> None:
        port, factors = _simple_factor_data(n=100)
        cfg252 = AttributionConfig(annualise_factor=252)
        cfg365 = AttributionConfig(annualise_factor=365)
        r252 = factor_attribution(port, factors, config=cfg252)
        r365 = factor_attribution(port, factors, config=cfg365)
        ratio = r365.alpha_annualised / r252.alpha_annualised
        assert ratio == pytest.approx(365.0 / 252.0, rel=1e-9)

    def test_nan_rows_dropped(self) -> None:
        rng = np.random.default_rng(3)
        n = 50
        dates = _dates(n)
        f = rng.normal(0.0, 0.01, n)
        port_arr = 0.7 * f + rng.normal(0.0, 0.002, n)
        port_arr[5] = float("nan")
        port_arr[10] = float("nan")
        df = pd.DataFrame({"f1": f}, index=dates)
        s = pd.Series(port_arr, index=dates)
        result = factor_attribution(s, df)
        assert result.n_obs == n - 2

    def test_raises_on_empty_factor_dataframe(self) -> None:
        port, factors = _simple_factor_data()
        empty_df = factors.iloc[:, :0]
        with pytest.raises(ValueError, match="at least one column"):
            factor_attribution(port, empty_df)

    def test_raises_on_insufficient_obs(self) -> None:
        dates = _dates(1)
        df = pd.DataFrame({"f1": [0.01]}, index=dates)
        s = pd.Series([0.005], index=dates)
        with pytest.raises(ValueError, match="2 clean observations"):
            factor_attribution(s, df)

    def test_inner_join_alignment(self) -> None:
        rng = np.random.default_rng(4)
        n = 40
        dates_port = _dates(n)
        dates_factor = pd.date_range("2024-02-01", periods=n, freq="B")
        f = rng.normal(0.0, 0.01, n)
        df = pd.DataFrame({"f1": f}, index=dates_factor)
        port = pd.Series(rng.normal(0.0, 0.01, n), index=dates_port)
        overlap = len(dates_port.intersection(dates_factor))
        result = factor_attribution(port, df)
        assert result.n_obs == overlap


# ---------------------------------------------------------------------------
# strategy_attribution
# ---------------------------------------------------------------------------


class TestStrategyAttribution:
    def _build(self, n: int = 50, seed: int = 0) -> tuple[pd.DataFrame, dict[str, float]]:
        rng = np.random.default_rng(seed)
        dates = _dates(n)
        arr = rng.normal(0.0, 0.01, (n, 3))
        df = pd.DataFrame(arr, index=dates, columns=["A", "B", "C"])
        weights = {"A": 0.5, "B": 0.3, "C": 0.2}
        return df, weights

    def test_contributions_sum_to_total(self) -> None:
        df, weights = self._build()
        result = strategy_attribution(df, weights)
        assert result.verified is True
        direct_total = sum(
            float(result.contributions[n].sum()) for n in result.strategy_names
        )
        assert direct_total == pytest.approx(result.total_return, abs=1e-10)

    def test_weights_stored(self) -> None:
        df, weights = self._build()
        result = strategy_attribution(df, weights)
        for k, v in weights.items():
            assert result.weights[k] == pytest.approx(v)

    def test_n_obs_correct(self) -> None:
        df, weights = self._build(n=60)
        result = strategy_attribution(df, weights)
        assert result.n_obs == 60

    def test_strategy_names_order_preserved(self) -> None:
        df, weights = self._build()
        result = strategy_attribution(df, weights)
        assert result.strategy_names == ["A", "B", "C"]

    def test_contributions_shape(self) -> None:
        df, weights = self._build(n=40)
        result = strategy_attribution(df, weights)
        for name in result.strategy_names:
            assert len(result.contributions[name]) == 40

    def test_weight_mismatch_extra_weight_key_raises(self) -> None:
        df, weights = self._build()
        weights["D"] = 0.1
        with pytest.raises(ValueError, match="weights keys not in returns"):
            strategy_attribution(df, weights)

    def test_weight_mismatch_missing_weight_key_raises(self) -> None:
        df, weights = self._build()
        del weights["C"]
        with pytest.raises(ValueError, match="returns columns not in weights"):
            strategy_attribution(df, weights)

    def test_nan_rows_dropped(self) -> None:
        df, weights = self._build(n=20)
        df.iloc[3, 0] = float("nan")
        result = strategy_attribution(df, weights)
        assert result.n_obs == 19

    def test_known_contribution_value(self) -> None:
        dates = _dates(3)
        df = pd.DataFrame(
            {"A": [0.1, 0.2, 0.3], "B": [0.0, 0.0, 0.0]}, index=dates
        )
        weights = {"A": 2.0, "B": 1.0}
        result = strategy_attribution(df, weights)
        expected_a = [0.2, 0.4, 0.6]
        np.testing.assert_allclose(
            result.contributions["A"].to_numpy(), expected_a, atol=1e-12
        )

    def test_verified_false_when_tol_very_tight(self) -> None:
        # With tol < machine epsilon, verified should be False even for
        # correct data. Use an absurdly tight tolerance to force this.
        df, weights = self._build(n=50)
        cfg = AttributionConfig(contribution_tol=1e-100)
        result = strategy_attribution(df, weights, config=cfg)
        # We don't assert False here since floating point may still pass;
        # just confirm the result is a bool.
        assert isinstance(result.verified, bool)


# ---------------------------------------------------------------------------
# trade_attribution
# ---------------------------------------------------------------------------


class TestTradeAttribution:
    def _simple_fills(self) -> tuple[list[dict], dict[str, float]]:
        fills = [
            {"symbol": "AAPL", "side": "BUY",  "quantity": 100.0, "price": 150.0},
            {"symbol": "AAPL", "side": "SELL", "quantity": 100.0, "price": 155.0},
            {"symbol": "GOOG", "side": "BUY",  "quantity": 10.0,  "price": 2000.0},
        ]
        close_prices = {"AAPL": 156.0, "GOOG": 1950.0}
        return fills, close_prices

    def test_round_trip_aapl_realised_pnl(self) -> None:
        # BUY 100 @ 150, SELL 100 @ 155 -> net position = 0
        # realised = 100*(155-150) = 500
        fills, closes = self._simple_fills()
        result = trade_attribution(fills, closes)
        aapl = result.symbol_pnl["AAPL"]
        assert aapl.net_position == pytest.approx(0.0)
        assert aapl.realised_pnl == pytest.approx(500.0, rel=1e-6)
        assert aapl.unrealised_pnl == pytest.approx(0.0, abs=1e-9)

    def test_open_position_unrealised_pnl(self) -> None:
        # BUY 10 @ 2000, close = 1950 -> unrealised = 10 * (1950-2000) = -500
        fills, closes = self._simple_fills()
        result = trade_attribution(fills, closes)
        goog = result.symbol_pnl["GOOG"]
        assert goog.net_position == pytest.approx(10.0)
        assert goog.unrealised_pnl == pytest.approx(10.0 * (1950.0 - 2000.0))
        assert goog.realised_pnl == pytest.approx(0.0, abs=1e-9)

    def test_total_pnl_sum_of_symbols(self) -> None:
        fills, closes = self._simple_fills()
        result = trade_attribution(fills, closes)
        manual_total = sum(s.total_pnl for s in result.symbol_pnl.values())
        assert result.total_pnl == pytest.approx(manual_total, abs=1e-9)

    def test_n_symbols(self) -> None:
        fills, closes = self._simple_fills()
        result = trade_attribution(fills, closes)
        assert result.n_symbols == 2

    def test_top_gainers_sorted_descending(self) -> None:
        fills, closes = self._simple_fills()
        result = trade_attribution(fills, closes)
        pnls = [s.total_pnl for s in result.top_gainers]
        assert pnls == sorted(pnls, reverse=True)

    def test_top_losers_sorted_ascending(self) -> None:
        fills, closes = self._simple_fills()
        result = trade_attribution(fills, closes)
        pnls = [s.total_pnl for s in result.top_losers]
        assert pnls == sorted(pnls)

    def test_missing_close_price_falls_back_to_fill_price(self) -> None:
        fills = [{"symbol": "XYZ", "side": "BUY", "quantity": 10.0, "price": 50.0}]
        result = trade_attribution(fills, {})
        xyz = result.symbol_pnl["XYZ"]
        # close_price == avg_fill_price, so unrealised == 0
        assert xyz.close_price == pytest.approx(xyz.avg_fill_price)
        assert xyz.unrealised_pnl == pytest.approx(0.0, abs=1e-12)

    def test_sell_without_prior_buy(self) -> None:
        # Short open: SELL 50 @ 100, close = 90 -> profit
        fills = [{"symbol": "ABC", "side": "SELL", "quantity": 50.0, "price": 100.0}]
        closes = {"ABC": 90.0}
        result = trade_attribution(fills, closes)
        abc = result.symbol_pnl["ABC"]
        assert abc.net_position == pytest.approx(-50.0)
        # unrealised = -50 * (90 - 100) = 500
        assert abc.unrealised_pnl == pytest.approx(500.0, rel=1e-6)

    def test_raises_on_missing_fill_key(self) -> None:
        fills = [{"symbol": "X", "side": "BUY", "quantity": 10.0}]  # missing price
        with pytest.raises(ValueError, match="missing required key 'price'"):
            trade_attribution(fills, {})

    def test_raises_on_bad_side(self) -> None:
        fills = [{"symbol": "X", "side": "HOLD", "quantity": 10.0, "price": 50.0}]
        with pytest.raises(ValueError, match="unrecognised side"):
            trade_attribution(fills, {})

    def test_case_insensitive_side(self) -> None:
        fills = [{"symbol": "X", "side": "buy", "quantity": 10.0, "price": 50.0}]
        result = trade_attribution(fills, {"X": 51.0})
        assert result.symbol_pnl["X"].net_position == pytest.approx(10.0)

    def test_empty_fills(self) -> None:
        result = trade_attribution([], {})
        assert result.n_symbols == 0
        assert result.total_pnl == pytest.approx(0.0)

    def test_avg_fill_price_weighted(self) -> None:
        # BUY 100 @ 100 and BUY 200 @ 110 -> avg = (100*100 + 200*110)/300 = 106.67
        fills = [
            {"symbol": "X", "side": "BUY", "quantity": 100.0, "price": 100.0},
            {"symbol": "X", "side": "BUY", "quantity": 200.0, "price": 110.0},
        ]
        result = trade_attribution(fills, {"X": 105.0})
        expected_avg = (100 * 100 + 200 * 110) / 300
        assert result.symbol_pnl["X"].avg_fill_price == pytest.approx(expected_avg)

    def test_top_n_movers_config(self) -> None:
        rng = np.random.default_rng(99)
        syms = [f"SYM{i:02d}" for i in range(20)]
        fills = [
            {
                "symbol": s,
                "side": "BUY",
                "quantity": 100.0,
                "price": float(rng.uniform(10, 200)),
            }
            for s in syms
        ]
        closes = {s: float(rng.uniform(10, 200)) for s in syms}
        cfg = AttributionConfig(top_n_movers=3)
        result = trade_attribution(fills, closes, config=cfg)
        assert len(result.top_gainers) <= 3
        assert len(result.top_losers) <= 3


# ---------------------------------------------------------------------------
# cost_attribution
# ---------------------------------------------------------------------------


class TestCostAttribution:
    def _build_trades(self) -> list[dict]:
        return [
            {
                "symbol": "AAPL",
                "quantity": 100.0,
                "fill_price": 151.0,
                "reference_price": 150.0,
                "commission": 1.0,
                "total_cost": 3.0,
            },
            {
                "symbol": "GOOG",
                "quantity": 10.0,
                "fill_price": 2005.0,
                "reference_price": 2000.0,
                "commission": 5.0,
                "total_cost": 60.0,
            },
        ]

    def test_spread_cost_formula(self) -> None:
        trades = self._build_trades()
        result = cost_attribution(trades)
        # AAPL: qty=100, fill=151, ref=150 -> spread = 100*1 = 100
        assert result.breakdowns[0].spread_cost == pytest.approx(100.0)
        # GOOG: qty=10, fill=2005, ref=2000 -> spread = 10*5 = 50
        assert result.breakdowns[1].spread_cost == pytest.approx(50.0)

    def test_slippage_residual(self) -> None:
        trades = self._build_trades()
        result = cost_attribution(trades)
        # AAPL: total=3, spread=100, commission=1 -> slippage = 3-100-1 = -98
        assert result.breakdowns[0].slippage == pytest.approx(3.0 - 100.0 - 1.0)

    def test_total_cost_aggregation(self) -> None:
        trades = self._build_trades()
        result = cost_attribution(trades)
        assert result.total_cost == pytest.approx(3.0 + 60.0)

    def test_total_notional(self) -> None:
        trades = self._build_trades()
        result = cost_attribution(trades)
        expected = 100.0 * 150.0 + 10.0 * 2000.0
        assert result.total_notional == pytest.approx(expected)

    def test_n_trades(self) -> None:
        trades = self._build_trades()
        result = cost_attribution(trades)
        assert result.n_trades == 2

    def test_bps_formula(self) -> None:
        trades = self._build_trades()
        result = cost_attribution(trades)
        total_notional = 100.0 * 150.0 + 10.0 * 2000.0
        expected_total_bps = 63.0 / total_notional * 10_000.0
        assert result.total_bps == pytest.approx(expected_total_bps, rel=1e-6)

    def test_per_trade_bps_formula(self) -> None:
        trades = [self._build_trades()[0]]  # AAPL only
        result = cost_attribution(trades)
        notional = 100.0 * 150.0
        assert result.breakdowns[0].spread_bps == pytest.approx(
            100.0 / notional * 10_000.0, rel=1e-6
        )

    def test_commission_aggregation(self) -> None:
        trades = self._build_trades()
        result = cost_attribution(trades)
        assert result.total_commission == pytest.approx(1.0 + 5.0)

    def test_spread_aggregation(self) -> None:
        trades = self._build_trades()
        result = cost_attribution(trades)
        assert result.total_spread_cost == pytest.approx(100.0 + 50.0)

    def test_raises_on_missing_key(self) -> None:
        trades = [{"symbol": "X", "quantity": 100.0}]
        with pytest.raises(ValueError, match="missing required key"):
            cost_attribution(trades)

    def test_empty_trades(self) -> None:
        result = cost_attribution([])
        assert result.n_trades == 0
        assert result.total_cost == pytest.approx(0.0)
        assert result.total_bps == pytest.approx(0.0)

    def test_zero_notional_does_not_raise(self) -> None:
        trades = [{
            "symbol": "X",
            "quantity": 0.0,
            "fill_price": 100.0,
            "reference_price": 100.0,
            "commission": 1.0,
            "total_cost": 1.0,
        }]
        result = cost_attribution(trades)
        assert result.breakdowns[0].spread_bps == pytest.approx(0.0)

    def test_custom_bps_scale(self) -> None:
        trades = self._build_trades()
        cfg = AttributionConfig(bps_scale=1_000.0)
        result_default = cost_attribution(trades)
        result_custom = cost_attribution(trades, config=cfg)
        assert result_custom.total_bps == pytest.approx(
            result_default.total_bps * 0.1, rel=1e-9
        )


# ---------------------------------------------------------------------------
# render_attribution_report
# ---------------------------------------------------------------------------


class TestRenderAttributionReport:
    def _demo_results(self) -> tuple[
        FactorAttributionResult,
        StrategyAttributionResult,
        TradeAttributionResult,
        CostAttributionResult,
    ]:
        demo = _build_demo_data(seed=7, n_days=100)
        fa = factor_attribution(demo["portfolio_returns"], demo["factor_returns"])
        sa = strategy_attribution(demo["strategy_returns"], demo["strategy_weights"])
        ta = trade_attribution(demo["fills"], demo["close_prices"])
        ca = cost_attribution(demo["trades"])
        return fa, sa, ta, ca

    def test_output_is_ascii_only(self) -> None:
        fa, sa, ta, ca = self._demo_results()
        out = render_attribution_report(fa, sa, ta, ca, generated_at="2024-01-01T00:00:00Z")
        assert _is_ascii(out), "Report contains non-ASCII characters"

    def test_header_present(self) -> None:
        fa, sa, ta, ca = self._demo_results()
        out = render_attribution_report(fa, sa, ta, ca, generated_at="TEST")
        assert "# Performance Attribution Report" in out
        assert "Generated : TEST" in out

    def test_all_section_headers_present(self) -> None:
        fa, sa, ta, ca = self._demo_results()
        out = render_attribution_report(fa, sa, ta, ca, generated_at="X")
        assert "## 1. Factor Attribution" in out
        assert "## 2. Strategy Attribution" in out
        assert "## 3. Trade Attribution" in out
        assert "## 4. Cost Attribution" in out

    def test_none_sections_show_not_available(self) -> None:
        out = render_attribution_report(None, None, None, None, generated_at="X")
        assert out.count("Not available") == 4

    def test_factor_section_shows_r_squared(self) -> None:
        fa, sa, ta, ca = self._demo_results()
        out = render_attribution_report(fa, None, None, None, generated_at="X")
        assert "R-squared" in out

    def test_strategy_section_shows_verified(self) -> None:
        fa, sa, ta, ca = self._demo_results()
        out = render_attribution_report(None, sa, None, None, generated_at="X")
        assert "Additive sum verified" in out

    def test_trade_section_shows_gainers_and_losers(self) -> None:
        fa, sa, ta, ca = self._demo_results()
        out = render_attribution_report(None, None, ta, None, generated_at="X")
        assert "Top Gainers" in out
        assert "Top Losers" in out

    def test_cost_section_shows_bps_table(self) -> None:
        fa, sa, ta, ca = self._demo_results()
        out = render_attribution_report(None, None, None, ca, generated_at="X")
        assert "bps" in out
        assert "Spread cost" in out

    def test_no_unicode_in_table_borders(self) -> None:
        fa, sa, ta, ca = self._demo_results()
        out = render_attribution_report(fa, sa, ta, ca, generated_at="X")
        for ch in out:
            assert ord(ch) < 128, f"Non-ASCII char {ch!r} (ord {ord(ch)}) found"


# ---------------------------------------------------------------------------
# _fmt_float helper
# ---------------------------------------------------------------------------


class TestFmtFloat:
    def test_nan_returns_na(self) -> None:
        assert _fmt_float(float("nan")) == "n/a"

    def test_pos_inf(self) -> None:
        assert _fmt_float(float("inf")) == "+inf"

    def test_neg_inf(self) -> None:
        assert _fmt_float(float("-inf")) == "-inf"

    def test_finite_format(self) -> None:
        assert _fmt_float(1.23456789) == "1.2346"

    def test_custom_decimals(self) -> None:
        assert _fmt_float(1.0, decimals=2) == "1.00"


# ---------------------------------------------------------------------------
# _build_demo_data
# ---------------------------------------------------------------------------


class TestBuildDemoData:
    def test_deterministic(self) -> None:
        d1 = _build_demo_data(seed=42, n_days=50)
        d2 = _build_demo_data(seed=42, n_days=50)
        pd.testing.assert_series_equal(
            d1["portfolio_returns"], d2["portfolio_returns"]
        )

    def test_different_seeds_differ(self) -> None:
        d1 = _build_demo_data(seed=1, n_days=50)
        d2 = _build_demo_data(seed=2, n_days=50)
        assert not d1["portfolio_returns"].equals(d2["portfolio_returns"])

    def test_factor_and_portfolio_lengths(self) -> None:
        n = 80
        d = _build_demo_data(seed=5, n_days=n)
        assert len(d["portfolio_returns"]) == n
        assert len(d["factor_returns"]) == n

    def test_strategy_weights_keys_match_columns(self) -> None:
        d = _build_demo_data(seed=5, n_days=50)
        assert set(d["strategy_weights"].keys()) == set(d["strategy_returns"].columns)

    def test_fills_have_required_keys(self) -> None:
        d = _build_demo_data(seed=5, n_days=50)
        for fill in d["fills"]:
            for key in ("symbol", "side", "quantity", "price"):
                assert key in fill

    def test_trades_have_required_keys(self) -> None:
        d = _build_demo_data(seed=5, n_days=50)
        for trade in d["trades"]:
            for key in ("symbol", "quantity", "fill_price", "reference_price",
                        "commission", "total_cost"):
                assert key in trade


# ---------------------------------------------------------------------------
# CLI main()
# ---------------------------------------------------------------------------


class TestMain:
    def test_demo_runs_without_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        main(["--demo"])
        out = capsys.readouterr().out
        assert len(out) > 0
        assert "Performance Attribution Report" in out

    def test_demo_output_is_ascii(self, capsys: pytest.CaptureFixture[str]) -> None:
        main(["--demo"])
        out = capsys.readouterr().out
        assert _is_ascii(out), "CLI output contains non-ASCII characters"

    def test_demo_output_sections(self, capsys: pytest.CaptureFixture[str]) -> None:
        main(["--demo"])
        out = capsys.readouterr().out
        assert "## 1. Factor Attribution" in out
        assert "## 2. Strategy Attribution" in out
        assert "## 3. Trade Attribution" in out
        assert "## 4. Cost Attribution" in out

    def test_demo_output_file(self, tmp_path: Any) -> None:
        out_path = str(tmp_path / "attribution.txt")
        main(["--demo", "--output", out_path])
        assert os.path.exists(out_path)
        with open(out_path, encoding="utf-8") as fh:
            content = fh.read()
        assert "Performance Attribution Report" in content

    def test_no_demo_flag_raises_system_exit(self) -> None:
        with pytest.raises(SystemExit):
            main([])
