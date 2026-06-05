"""Tests for core_trading.risk.liquidity (Phase 7.10).

Covers:
* LiquidityConfig: validation errors fire for out-of-range inputs.
* days_to_liquidate: exact hand-computed examples; schedule sums to position;
  zero-ADV flag fires; NaN ADV flag fires; zero position DTL = 0;
  weighted-avg with two assets; portfolio infinite when any asset is infinite.
* liquidity_adjusted_var: BDSS formula exact; LVaR >= VaR invariant;
  k monotonicity; endogenous addon only fires above participation cap;
  sqrt-scaling: 4x size gives 2x impact per share;
  spread-multiplier monotonicity.
* stress_liquidity: 3x multiplier triples exogenous addon exactly;
  capital evaporation two-asset hand-computed match; nav > 0 guard;
  stressed_lvar = VaR + stressed_exog + endogenous_addon.
* render_liquidity_stress_markdown: ASCII-only (ord < 128);
  every asset row present; required section headers present.
* Validation: empty positions, nav <= 0, var < 0, missing positions.
"""
from __future__ import annotations

import math

import pandas as pd
import pytest

from core_trading.risk.liquidity import (
    LiquidityConfig,
    LiquidityStressReport,
    days_to_liquidate,
    liquidity_adjusted_var,
    render_liquidity_stress_markdown,
    stress_liquidity,
)
from core_trading.risk.var import VaRResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_var(var: float = 1000.0) -> VaRResult:
    return VaRResult(
        var=var,
        method="parametric",
        confidence=0.95,
        horizon=1,
        alpha=0.05,
    )


# ---------------------------------------------------------------------------
# LiquidityConfig validation
# ---------------------------------------------------------------------------


class TestLiquidityConfig:
    def test_defaults_valid(self) -> None:
        cfg = LiquidityConfig()
        assert cfg.participation_cap == 0.10
        assert cfg.bdss_k == 3.0
        assert cfg.impact_coeff == 0.1
        assert cfg.spread_stress_multiplier == 3.0

    def test_participation_cap_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="participation_cap"):
            LiquidityConfig(participation_cap=0.0)

    def test_participation_cap_above_one_raises(self) -> None:
        with pytest.raises(ValueError, match="participation_cap"):
            LiquidityConfig(participation_cap=1.1)

    def test_participation_cap_one_ok(self) -> None:
        cfg = LiquidityConfig(participation_cap=1.0)
        assert cfg.participation_cap == 1.0

    def test_bdss_k_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="bdss_k"):
            LiquidityConfig(bdss_k=0.0)

    def test_bdss_k_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="bdss_k"):
            LiquidityConfig(bdss_k=-1.0)

    def test_impact_coeff_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="impact_coeff"):
            LiquidityConfig(impact_coeff=0.0)

    def test_spread_stress_multiplier_below_one_raises(self) -> None:
        with pytest.raises(ValueError, match="spread_stress_multiplier"):
            LiquidityConfig(spread_stress_multiplier=0.9)

    def test_spread_stress_multiplier_one_ok(self) -> None:
        cfg = LiquidityConfig(spread_stress_multiplier=1.0)
        assert cfg.spread_stress_multiplier == 1.0


# ---------------------------------------------------------------------------
# days_to_liquidate -- hand-computed exact examples
# ---------------------------------------------------------------------------


class TestDaysToLiquidate:
    def test_hand_computed_exact(self) -> None:
        result = days_to_liquidate(
            positions={"AAPL": 1_000_000},
            adv={"AAPL": 2_000_000},
            config=LiquidityConfig(participation_cap=0.10),
        )
        r = result.asset_results[0]
        assert r.asset == "AAPL"
        assert r.daily_tradeable == pytest.approx(200_000.0)
        assert r.days_to_liquidate == 5.0
        assert result.weighted_avg_dtl == 5.0
        assert result.max_dtl == 5.0
        assert result.flagged_assets == []

    def test_schedule_sums_to_position(self) -> None:
        result = days_to_liquidate(
            positions={"SPY": 750_000},
            adv={"SPY": 1_000_000},
            config=LiquidityConfig(participation_cap=0.10),
        )
        r = result.asset_results[0]
        assert r.days_to_liquidate == 8.0
        assert sum(r.schedule.shares_per_day) == pytest.approx(750_000.0)

    def test_schedule_length_matches_dtl(self) -> None:
        result = days_to_liquidate(
            positions={"X": 300_000},
            adv={"X": 1_000_000},
            config=LiquidityConfig(participation_cap=0.10),
        )
        r = result.asset_results[0]
        assert r.days_to_liquidate == 3.0
        assert len(r.schedule.shares_per_day) == 3

    def test_exact_multiple_no_residual(self) -> None:
        result = days_to_liquidate(
            positions={"Y": 200_000},
            adv={"Y": 1_000_000},
            config=LiquidityConfig(participation_cap=0.10),
        )
        r = result.asset_results[0]
        assert r.days_to_liquidate == 2.0
        assert len(r.schedule.shares_per_day) == 2
        assert r.schedule.shares_per_day[0] == pytest.approx(100_000.0)
        assert r.schedule.shares_per_day[1] == pytest.approx(100_000.0)

    def test_zero_position_dtl_zero(self) -> None:
        result = days_to_liquidate(
            positions={"FLAT": 0.0},
            adv={"FLAT": 500_000},
        )
        r = result.asset_results[0]
        assert r.days_to_liquidate == 0.0
        assert r.zero_adv_flag is False
        assert r.schedule.shares_per_day == []

    def test_zero_adv_flag_fires(self) -> None:
        result = days_to_liquidate(
            positions={"ILLIQUID": 100_000},
            adv={"ILLIQUID": 0.0},
        )
        r = result.asset_results[0]
        assert r.zero_adv_flag is True
        assert r.days_to_liquidate == math.inf
        assert r.schedule.shares_per_day == []
        assert "ILLIQUID" in result.flagged_assets

    def test_nan_adv_flag_fires(self) -> None:
        result = days_to_liquidate(
            positions={"NAN_ASSET": 50_000},
            adv={"NAN_ASSET": float("nan")},
        )
        r = result.asset_results[0]
        assert r.zero_adv_flag is True
        assert r.days_to_liquidate == math.inf
        assert "NAN_ASSET" in result.flagged_assets

    def test_missing_adv_key_treated_as_nan(self) -> None:
        result = days_to_liquidate(
            positions={"GHOST": 10_000},
            adv={},
        )
        r = result.asset_results[0]
        assert r.zero_adv_flag is True
        assert math.isinf(r.days_to_liquidate)

    def test_portfolio_infinite_when_any_asset_flagged(self) -> None:
        result = days_to_liquidate(
            positions={"A": 100_000, "B": 50_000},
            adv={"A": 0.0, "B": 500_000},
        )
        assert math.isinf(result.weighted_avg_dtl)
        assert math.isinf(result.max_dtl)

    def test_weighted_avg_two_assets(self) -> None:
        result = days_to_liquidate(
            positions={"A": 1_000_000, "B": 500_000},
            adv={"A": 2_000_000, "B": 1_000_000},
            config=LiquidityConfig(participation_cap=0.10),
        )
        assert result.weighted_avg_dtl == pytest.approx(5.0)

    def test_weighted_avg_two_assets_different_dtl(self) -> None:
        result = days_to_liquidate(
            positions={"A": 1000.0, "B": 200.0},
            adv={"A": 1000.0, "B": 1000.0},
            config=LiquidityConfig(participation_cap=0.10),
        )
        expected_wavg = (1000.0 * 10.0 + 200.0 * 2.0) / 1200.0
        assert result.weighted_avg_dtl == pytest.approx(expected_wavg)

    def test_negative_position_abs_value_used(self) -> None:
        result = days_to_liquidate(
            positions={"SHORT": -1_000_000},
            adv={"SHORT": 2_000_000},
            config=LiquidityConfig(participation_cap=0.10),
        )
        r = result.asset_results[0]
        assert r.position_shares == pytest.approx(1_000_000.0)
        assert r.days_to_liquidate == 5.0

    def test_empty_positions_raises(self) -> None:
        with pytest.raises(ValueError, match="positions"):
            days_to_liquidate(positions={}, adv={})


# ---------------------------------------------------------------------------
# liquidity_adjusted_var -- BDSS and Almgren formulas
# ---------------------------------------------------------------------------


class TestLiquidityAdjustedVar:
    def test_bdss_formula_exact(self) -> None:
        var = _make_var(1000.0)
        result = liquidity_adjusted_var(
            var_result=var,
            positions={"A": 1000.0},
            position_values={"A": 100_000.0},
            spreads_mean={"A": 0.001},
            spreads_std={"A": 0.0005},
            config=LiquidityConfig(bdss_k=3.0),
        )
        expected_exog = 0.5 * (0.001 + 3.0 * 0.0005) * 100_000.0
        assert result.exogenous_addon == pytest.approx(expected_exog)
        assert result.var == pytest.approx(1000.0)
        assert result.lvar == pytest.approx(1000.0 + expected_exog)
        assert result.endogenous_addon == pytest.approx(0.0)

    def test_lvar_geq_var(self) -> None:
        var = _make_var(500.0)
        result = liquidity_adjusted_var(
            var_result=var,
            positions={"X": 200.0},
            position_values={"X": 20_000.0},
            spreads_mean={"X": 0.002},
            spreads_std={"X": 0.001},
        )
        assert result.lvar >= result.var

    def test_lvar_zero_spread(self) -> None:
        var = _make_var(750.0)
        result = liquidity_adjusted_var(
            var_result=var,
            positions={"Z": 100.0},
            position_values={"Z": 10_000.0},
            spreads_mean={"Z": 0.0},
            spreads_std={"Z": 0.0},
        )
        assert result.exogenous_addon == pytest.approx(0.0)
        assert result.lvar == pytest.approx(750.0)

    def test_k_monotonicity(self) -> None:
        var = _make_var(1000.0)
        common = dict(
            positions={"A": 500.0},
            position_values={"A": 50_000.0},
            spreads_mean={"A": 0.001},
            spreads_std={"A": 0.0005},
        )
        r1 = liquidity_adjusted_var(var_result=var, config=LiquidityConfig(bdss_k=1.0), **common)
        r2 = liquidity_adjusted_var(var_result=var, config=LiquidityConfig(bdss_k=3.0), **common)
        r3 = liquidity_adjusted_var(var_result=var, config=LiquidityConfig(bdss_k=5.0), **common)
        assert r1.lvar < r2.lvar < r3.lvar

    def test_endogenous_addon_zero_below_cap(self) -> None:
        var = _make_var(1000.0)
        result = liquidity_adjusted_var(
            var_result=var,
            positions={"A": 100.0},
            position_values={"A": 10_000.0},
            spreads_mean={"A": 0.0},
            spreads_std={"A": 0.0},
            adv={"A": 10_000.0},
            asset_vols={"A": 0.02},
            config=LiquidityConfig(participation_cap=0.10),
        )
        assert result.endogenous_addon == pytest.approx(0.0)
        assert result.per_asset_endogenous["A"] == pytest.approx(0.0)

    def test_endogenous_addon_fires_above_cap(self) -> None:
        var = _make_var(1000.0)
        cfg = LiquidityConfig(participation_cap=0.10, impact_coeff=0.1)
        result = liquidity_adjusted_var(
            var_result=var,
            positions={"A": 2000.0},
            position_values={"A": 200_000.0},
            spreads_mean={"A": 0.0},
            spreads_std={"A": 0.0},
            adv={"A": 10_000.0},
            asset_vols={"A": 0.02},
            config=cfg,
        )
        expected_endo = 0.1 * 0.02 * math.sqrt(2000.0 / 10_000.0) * 2000.0
        assert result.endogenous_addon == pytest.approx(expected_endo)
        assert result.per_asset_endogenous["A"] == pytest.approx(expected_endo)

    def test_endogenous_sqrt_scaling(self) -> None:
        var = _make_var(0.0)
        cfg = LiquidityConfig(participation_cap=0.01, impact_coeff=0.1)
        r1 = liquidity_adjusted_var(
            var_result=var,
            positions={"A": 1000.0},
            position_values={"A": 100_000.0},
            spreads_mean={"A": 0.0},
            spreads_std={"A": 0.0},
            adv={"A": 10_000.0},
            asset_vols={"A": 0.02},
            config=cfg,
        )
        r4 = liquidity_adjusted_var(
            var_result=var,
            positions={"A": 4000.0},
            position_values={"A": 400_000.0},
            spreads_mean={"A": 0.0},
            spreads_std={"A": 0.0},
            adv={"A": 10_000.0},
            asset_vols={"A": 0.02},
            config=cfg,
        )
        ips1 = r1.endogenous_addon / 1000.0
        ips4 = r4.endogenous_addon / 4000.0
        assert ips4 == pytest.approx(2.0 * ips1, rel=1e-9)

    def test_spread_multiplier_monotonicity(self) -> None:
        var = _make_var(1000.0)
        common_pos = dict(
            positions={"A": 500.0},
            position_values={"A": 50_000.0},
        )
        r1 = liquidity_adjusted_var(
            var_result=var,
            spreads_mean={"A": 0.001},
            spreads_std={"A": 0.0005},
            config=LiquidityConfig(bdss_k=3.0),
            **common_pos,
        )
        r3 = liquidity_adjusted_var(
            var_result=var,
            spreads_mean={"A": 0.003},
            spreads_std={"A": 0.0015},
            config=LiquidityConfig(bdss_k=3.0),
            **common_pos,
        )
        assert r3.exogenous_addon == pytest.approx(3.0 * r1.exogenous_addon)
        assert r3.lvar > r1.lvar

    def test_empty_positions_raises(self) -> None:
        with pytest.raises(ValueError, match="positions"):
            liquidity_adjusted_var(
                var_result=_make_var(),
                positions={},
                position_values={},
                spreads_mean={},
                spreads_std={},
            )

    def test_negative_var_raises(self) -> None:
        with pytest.raises(ValueError, match="var_result.var"):
            liquidity_adjusted_var(
                var_result=_make_var(-100.0),
                positions={"A": 100.0},
                position_values={"A": 10_000.0},
                spreads_mean={"A": 0.001},
                spreads_std={"A": 0.0005},
            )

    def test_no_adv_no_endogenous(self) -> None:
        var = _make_var(200.0)
        result = liquidity_adjusted_var(
            var_result=var,
            positions={"A": 5000.0},
            position_values={"A": 50_000.0},
            spreads_mean={"A": 0.0},
            spreads_std={"A": 0.0},
            adv=None,
            asset_vols={"A": 0.02},
        )
        assert result.endogenous_addon == pytest.approx(0.0)

    def test_two_asset_exogenous_sum(self) -> None:
        var = _make_var(500.0)
        result = liquidity_adjusted_var(
            var_result=var,
            positions={"A": 100.0, "B": 200.0},
            position_values={"A": 10_000.0, "B": 20_000.0},
            spreads_mean={"A": 0.001, "B": 0.002},
            spreads_std={"A": 0.0005, "B": 0.001},
            config=LiquidityConfig(bdss_k=3.0),
        )
        expected_sum = sum(result.per_asset_exogenous.values())
        assert result.exogenous_addon == pytest.approx(expected_sum)


# ---------------------------------------------------------------------------
# stress_liquidity
# ---------------------------------------------------------------------------


class TestStressLiquidity:
    def _base_inputs(self) -> dict:
        return dict(
            var_result=_make_var(1000.0),
            positions={"A": 1000.0, "B": 500.0},
            position_values={"A": 100_000.0, "B": 50_000.0},
            spreads_mean={"A": 0.001, "B": 0.002},
            spreads_std={"A": 0.0005, "B": 0.001},
            nav=200_000.0,
        )

    def test_3x_spread_multiplier_triples_exog_addon(self) -> None:
        inputs = self._base_inputs()
        base_report = stress_liquidity(
            **inputs,
            config=LiquidityConfig(spread_stress_multiplier=1.0),
        )
        stressed_report = stress_liquidity(
            **inputs,
            config=LiquidityConfig(spread_stress_multiplier=3.0),
        )
        assert stressed_report.stressed_exogenous_addon == pytest.approx(
            3.0 * base_report.stressed_exogenous_addon, rel=1e-9
        )

    def test_stressed_lvar_formula(self) -> None:
        inputs = self._base_inputs()
        report = stress_liquidity(**inputs)
        expected = (
            report.base_lvar.var
            + report.stressed_exogenous_addon
            + report.stressed_endogenous_addon
        )
        assert report.stressed_lvar == pytest.approx(expected)

    def test_capital_evaporation_two_asset_hand_computed(self) -> None:
        cfg = LiquidityConfig(bdss_k=3.0, spread_stress_multiplier=3.0)
        report = stress_liquidity(
            var_result=_make_var(1000.0),
            positions={"A": 1000.0, "B": 500.0},
            position_values={"A": 100_000.0, "B": 50_000.0},
            spreads_mean={"A": 0.001, "B": 0.002},
            spreads_std={"A": 0.0005, "B": 0.001},
            nav=200_000.0,
            config=cfg,
        )
        assert report.capital_evaporation_abs == pytest.approx(750.0, rel=1e-9)
        assert report.capital_evaporation_pct == pytest.approx(0.375, rel=1e-9)

    def test_capital_evaporation_with_impact(self) -> None:
        c = 0.1
        sigma_a = 0.02
        q_a = 2000.0
        adv_a = 10_000.0
        expected_impact = c * sigma_a * math.sqrt(q_a / adv_a) * q_a

        report = stress_liquidity(
            var_result=_make_var(0.0),
            positions={"A": q_a},
            position_values={"A": 200_000.0},
            spreads_mean={"A": 0.0},
            spreads_std={"A": 0.0},
            nav=1_000_000.0,
            adv={"A": adv_a},
            asset_vols={"A": sigma_a},
            config=LiquidityConfig(
                spread_stress_multiplier=1.0,
                impact_coeff=c,
                participation_cap=0.10,
            ),
        )
        assert report.per_asset_impact["A"] == pytest.approx(expected_impact)
        assert report.capital_evaporation_abs == pytest.approx(expected_impact)

    def test_stressed_lvar_geq_base_lvar(self) -> None:
        inputs = self._base_inputs()
        report = stress_liquidity(**inputs)
        assert report.stressed_lvar >= report.base_lvar.lvar

    def test_nav_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="nav"):
            stress_liquidity(
                var_result=_make_var(),
                positions={"A": 100.0},
                position_values={"A": 10_000.0},
                spreads_mean={"A": 0.001},
                spreads_std={"A": 0.0005},
                nav=0.0,
            )

    def test_nav_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="nav"):
            stress_liquidity(
                var_result=_make_var(),
                positions={"A": 100.0},
                position_values={"A": 10_000.0},
                spreads_mean={"A": 0.001},
                spreads_std={"A": 0.0005},
                nav=-1.0,
            )

    def test_empty_positions_raises(self) -> None:
        with pytest.raises(ValueError, match="positions"):
            stress_liquidity(
                var_result=_make_var(),
                positions={},
                position_values={},
                spreads_mean={},
                spreads_std={},
                nav=100_000.0,
            )

    def test_spread_multiplier_monotonicity(self) -> None:
        inputs = self._base_inputs()
        r1 = stress_liquidity(**inputs, config=LiquidityConfig(spread_stress_multiplier=1.0))
        r2 = stress_liquidity(**inputs, config=LiquidityConfig(spread_stress_multiplier=2.0))
        r3 = stress_liquidity(**inputs, config=LiquidityConfig(spread_stress_multiplier=5.0))
        assert r1.stressed_lvar <= r2.stressed_lvar <= r3.stressed_lvar
        assert r1.capital_evaporation_abs <= r2.capital_evaporation_abs <= r3.capital_evaporation_abs

    def test_generated_at_default_is_valid_iso(self) -> None:
        inputs = self._base_inputs()
        report = stress_liquidity(**inputs)
        pd.Timestamp(report.generated_at)

    def test_generated_at_override(self) -> None:
        inputs = self._base_inputs()
        ts = "2025-01-01T00:00:00Z"
        report = stress_liquidity(**inputs, generated_at=ts)
        assert report.generated_at == ts

    def test_asset_names_preserved(self) -> None:
        inputs = self._base_inputs()
        report = stress_liquidity(**inputs)
        assert set(report.asset_names) == {"A", "B"}


# ---------------------------------------------------------------------------
# render_liquidity_stress_markdown
# ---------------------------------------------------------------------------


class TestRenderLiquidityStressMarkdown:
    def _make_report(self) -> LiquidityStressReport:
        return stress_liquidity(
            var_result=_make_var(1000.0),
            positions={"AAPL": 500.0, "MSFT": 300.0},
            position_values={"AAPL": 50_000.0, "MSFT": 30_000.0},
            spreads_mean={"AAPL": 0.001, "MSFT": 0.0015},
            spreads_std={"AAPL": 0.0005, "MSFT": 0.0007},
            nav=200_000.0,
            generated_at="2025-01-15T09:30:00Z",
        )

    def test_ascii_only(self) -> None:
        report = self._make_report()
        md = render_liquidity_stress_markdown(report)
        for i, ch in enumerate(md):
            assert ord(ch) < 128, (
                f"Non-ASCII character {ch!r} (ord={ord(ch)}) at position {i}"
            )

    def test_contains_every_asset_row(self) -> None:
        report = self._make_report()
        md = render_liquidity_stress_markdown(report)
        assert "AAPL" in md
        assert "MSFT" in md

    def test_required_sections_present(self) -> None:
        report = self._make_report()
        md = render_liquidity_stress_markdown(report)
        assert "# Liquidity Stress Report" in md
        assert "## LVaR Summary" in md
        assert "## Per-Asset Breakdown" in md
        assert "## Capital Evaporation" in md
        assert "Generated:" in md
        assert "Spread stress multiplier:" in md
        assert "NAV:" in md

    def test_generated_at_in_output(self) -> None:
        report = self._make_report()
        md = render_liquidity_stress_markdown(report)
        assert "2025-01-15T09:30:00Z" in md

    def test_returns_string(self) -> None:
        report = self._make_report()
        md = render_liquidity_stress_markdown(report)
        assert isinstance(md, str)
        assert len(md) > 0

    def test_single_asset(self) -> None:
        report = stress_liquidity(
            var_result=_make_var(500.0),
            positions={"SPY": 1000.0},
            position_values={"SPY": 100_000.0},
            spreads_mean={"SPY": 0.0005},
            spreads_std={"SPY": 0.0002},
            nav=500_000.0,
            generated_at="2025-01-15T09:30:00Z",
        )
        md = render_liquidity_stress_markdown(report)
        assert "SPY" in md
        for ch in md:
            assert ord(ch) < 128


# ---------------------------------------------------------------------------
# Integration: full pipeline
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_full_pipeline_no_exceptions(self) -> None:
        positions = {"AAPL": 10_000.0, "MSFT": 5_000.0, "ILLIQUID": 2_000.0}
        adv = {"AAPL": 100_000.0, "MSFT": 50_000.0, "ILLIQUID": 0.0}

        dtl_result = days_to_liquidate(positions=positions, adv=adv)
        assert math.isinf(dtl_result.max_dtl)
        assert "ILLIQUID" in dtl_result.flagged_assets

        var_result = _make_var(5000.0)
        lvar = liquidity_adjusted_var(
            var_result=var_result,
            positions=positions,
            position_values={"AAPL": 1_000_000.0, "MSFT": 500_000.0, "ILLIQUID": 200_000.0},
            spreads_mean={"AAPL": 0.001, "MSFT": 0.0015, "ILLIQUID": 0.005},
            spreads_std={"AAPL": 0.0005, "MSFT": 0.0008, "ILLIQUID": 0.003},
            adv=adv,
            asset_vols={"AAPL": 0.015, "MSFT": 0.018, "ILLIQUID": 0.04},
        )
        assert lvar.lvar >= lvar.var

        stress_report = stress_liquidity(
            var_result=var_result,
            positions=positions,
            position_values={"AAPL": 1_000_000.0, "MSFT": 500_000.0, "ILLIQUID": 200_000.0},
            spreads_mean={"AAPL": 0.001, "MSFT": 0.0015, "ILLIQUID": 0.005},
            spreads_std={"AAPL": 0.0005, "MSFT": 0.0008, "ILLIQUID": 0.003},
            nav=2_000_000.0,
            adv=adv,
            asset_vols={"AAPL": 0.015, "MSFT": 0.018, "ILLIQUID": 0.04},
        )
        assert stress_report.stressed_lvar >= stress_report.base_lvar.var

        md = render_liquidity_stress_markdown(stress_report)
        for ch in md:
            assert ord(ch) < 128, f"Non-ASCII: {ch!r}"

    def test_per_asset_exogenous_keys_match_positions(self) -> None:
        var = _make_var(1000.0)
        positions = {"A": 100.0, "B": 200.0, "C": 300.0}
        result = liquidity_adjusted_var(
            var_result=var,
            positions=positions,
            position_values={"A": 10_000.0, "B": 20_000.0, "C": 30_000.0},
            spreads_mean={"A": 0.001, "B": 0.002, "C": 0.003},
            spreads_std={"A": 0.0005, "B": 0.001, "C": 0.0015},
        )
        assert set(result.per_asset_exogenous.keys()) == set(positions.keys())
        assert set(result.per_asset_endogenous.keys()) == set(positions.keys())

    def test_bdss_k_effect_on_exogenous_addon(self) -> None:
        var = _make_var(1000.0)
        common = dict(
            var_result=var,
            positions={"A": 1000.0},
            position_values={"A": 100_000.0},
            spreads_mean={"A": 0.0},
            spreads_std={"A": 0.001},
        )
        r1 = liquidity_adjusted_var(**common, config=LiquidityConfig(bdss_k=1.0))
        r2 = liquidity_adjusted_var(**common, config=LiquidityConfig(bdss_k=2.0))
        assert r2.exogenous_addon == pytest.approx(2.0 * r1.exogenous_addon)

    def test_lvar_result_method_field(self) -> None:
        var = _make_var(500.0)
        result = liquidity_adjusted_var(
            var_result=var,
            positions={"A": 100.0},
            position_values={"A": 10_000.0},
            spreads_mean={"A": 0.001},
            spreads_std={"A": 0.0005},
        )
        assert result.method == "lvar_bdss_almgren"