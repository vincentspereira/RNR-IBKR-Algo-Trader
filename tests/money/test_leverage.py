"""Tests for core_trading.money.leverage (Phase 8.2).

All assertions are hand-computed from the documented proportional-scaling
rules so they can be verified without an RNG.  No network, no sleeps.
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from core_trading.money.leverage import (
    LeverageConfig,
    LeverageReport,
    apply_dynamic_delever,
    apply_leverage_limits,
    dynamic_delever_factor,
)

# ---------------------------------------------------------------------------
# LeverageConfig validation
# ---------------------------------------------------------------------------


class TestLeverageConfigValidation:
    """LeverageConfig.__post_init__ enforces valid parameter ranges."""

    def test_defaults_are_valid(self) -> None:
        cfg = LeverageConfig()
        assert cfg.max_gross == 2.0
        assert cfg.max_net == 1.0
        assert cfg.asset_class_caps == {}
        assert cfg.drawdown_delever_threshold == 0.10
        assert cfg.drawdown_delever_factor == 0.5
        assert cfg.high_vol_delever_factor == 0.5

    def test_max_gross_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="max_gross"):
            LeverageConfig(max_gross=0.0)

    def test_max_gross_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="max_gross"):
            LeverageConfig(max_gross=-1.0)

    def test_max_net_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="max_net"):
            LeverageConfig(max_net=0.0)

    def test_max_net_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="max_net"):
            LeverageConfig(max_net=-0.5)

    def test_asset_class_cap_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="asset_class"):
            LeverageConfig(asset_class_caps={"equity": 0.0})

    def test_asset_class_cap_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="asset_class"):
            LeverageConfig(asset_class_caps={"equity": -1.0})

    def test_asset_class_caps_valid(self) -> None:
        cfg = LeverageConfig(asset_class_caps={"equity": 1.0, "fx": 0.5})
        assert cfg.asset_class_caps["equity"] == 1.0
        assert cfg.asset_class_caps["fx"] == 0.5

    def test_drawdown_threshold_below_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="drawdown_delever_threshold"):
            LeverageConfig(drawdown_delever_threshold=-0.01)

    def test_drawdown_threshold_above_one_raises(self) -> None:
        with pytest.raises(ValueError, match="drawdown_delever_threshold"):
            LeverageConfig(drawdown_delever_threshold=1.5)

    def test_drawdown_threshold_zero_valid(self) -> None:
        cfg = LeverageConfig(drawdown_delever_threshold=0.0)
        assert cfg.drawdown_delever_threshold == 0.0

    def test_drawdown_factor_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="drawdown_delever_factor"):
            LeverageConfig(drawdown_delever_factor=0.0)

    def test_drawdown_factor_above_one_raises(self) -> None:
        with pytest.raises(ValueError, match="drawdown_delever_factor"):
            LeverageConfig(drawdown_delever_factor=1.5)

    def test_high_vol_factor_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="high_vol_delever_factor"):
            LeverageConfig(high_vol_delever_factor=0.0)

    def test_high_vol_factor_above_one_raises(self) -> None:
        with pytest.raises(ValueError, match="high_vol_delever_factor"):
            LeverageConfig(high_vol_delever_factor=1.1)

    def test_frozen(self) -> None:
        cfg = LeverageConfig()
        with pytest.raises(FrozenInstanceError):
            cfg.max_gross = 3.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# apply_leverage_limits -- gross cap
# ---------------------------------------------------------------------------


class TestGrossCap:
    """Gross cap scales the whole book proportionally."""

    def test_under_gross_unchanged(self) -> None:
        cfg = LeverageConfig(max_gross=2.0, max_net=10.0)
        weights = {"A": 0.5, "B": -0.5}
        report = apply_leverage_limits(weights, config=cfg)
        assert report.weights == {"A": 0.5, "B": -0.5}
        assert report.binding_constraints == []
        assert report.scale_factors == {}

    def test_over_gross_scales_down(self) -> None:
        # gross = 3.0, cap = 2.0 => factor 2/3.
        cfg = LeverageConfig(max_gross=2.0, max_net=10.0)
        weights = {"A": 1.5, "B": -1.5}
        report = apply_leverage_limits(weights, config=cfg)
        scale = 2.0 / 3.0
        assert report.weights["A"] == pytest.approx(1.5 * scale, rel=1e-12)
        assert report.weights["B"] == pytest.approx(-1.5 * scale, rel=1e-12)
        assert report.gross_after == pytest.approx(2.0, rel=1e-12)
        assert "gross" in report.binding_constraints
        assert report.scale_factors["gross"] == pytest.approx(scale, rel=1e-12)

    def test_exactly_at_gross_unchanged(self) -> None:
        cfg = LeverageConfig(max_gross=2.0, max_net=10.0)
        weights = {"A": 1.0, "B": -1.0}
        report = apply_leverage_limits(weights, config=cfg)
        assert report.binding_constraints == []
        assert report.weights == {"A": 1.0, "B": -1.0}

    def test_relative_sizes_preserved(self) -> None:
        cfg = LeverageConfig(max_gross=1.0, max_net=10.0)
        weights = {"A": 2.0, "B": 1.0}
        report = apply_leverage_limits(weights, config=cfg)
        assert report.weights["A"] == pytest.approx(
            2.0 * report.weights["B"], rel=1e-12
        )

    def test_gross_before_after_recorded(self) -> None:
        cfg = LeverageConfig(max_gross=2.0, max_net=10.0)
        weights = {"A": 2.0, "B": -1.0}
        report = apply_leverage_limits(weights, config=cfg)
        assert report.gross_before == pytest.approx(3.0, rel=1e-12)
        assert report.gross_after == pytest.approx(2.0, rel=1e-12)


# ---------------------------------------------------------------------------
# apply_leverage_limits -- net cap
# ---------------------------------------------------------------------------


class TestNetCap:
    """Net cap scales the whole book proportionally."""

    def test_under_net_unchanged(self) -> None:
        cfg = LeverageConfig(max_gross=10.0, max_net=1.0)
        weights = {"A": 0.5, "B": -0.5}  # net = 0
        report = apply_leverage_limits(weights, config=cfg)
        assert report.binding_constraints == []
        assert report.net_after == pytest.approx(0.0, abs=1e-15)

    def test_over_net_scales_down(self) -> None:
        # net = 2.0, cap = 1.0 => factor 0.5.
        cfg = LeverageConfig(max_gross=10.0, max_net=1.0)
        weights = {"A": 1.5, "B": 0.5}  # net = 2.0
        report = apply_leverage_limits(weights, config=cfg)
        assert report.weights["A"] == pytest.approx(0.75, rel=1e-12)
        assert report.weights["B"] == pytest.approx(0.25, rel=1e-12)
        assert report.net_after == pytest.approx(1.0, rel=1e-12)
        assert "net" in report.binding_constraints
        assert report.scale_factors["net"] == pytest.approx(0.5, rel=1e-12)

    def test_net_before_after_recorded(self) -> None:
        cfg = LeverageConfig(max_gross=10.0, max_net=1.0)
        weights = {"A": 1.5, "B": 0.5}
        report = apply_leverage_limits(weights, config=cfg)
        assert report.net_before == pytest.approx(2.0, rel=1e-12)
        assert report.net_after == pytest.approx(1.0, rel=1e-12)

    def test_short_dominant_net_scaled(self) -> None:
        # net = |-2.0| = 2.0 => factor 0.5; whole book scaled, signs kept.
        cfg = LeverageConfig(max_gross=10.0, max_net=1.0)
        weights = {"A": -1.5, "B": -0.5}
        report = apply_leverage_limits(weights, config=cfg)
        assert report.weights["A"] == pytest.approx(-0.75, rel=1e-12)
        assert report.weights["B"] == pytest.approx(-0.25, rel=1e-12)


class TestGrossThenNet:
    """Gross and net caps can both bind; gross is applied first."""

    def test_both_bind(self) -> None:
        # weights net=long-heavy: A=2.0, B=1.0 => gross 3, net 3.
        # gross cap 2.0 -> factor 2/3 -> A=1.333, B=0.667, gross 2, net 2.
        # net cap 1.0 -> factor 0.5 -> A=0.667, B=0.333, net 1, gross 1.
        cfg = LeverageConfig(max_gross=2.0, max_net=1.0)
        weights = {"A": 2.0, "B": 1.0}
        report = apply_leverage_limits(weights, config=cfg)
        assert "gross" in report.binding_constraints
        assert "net" in report.binding_constraints
        # gross applied before net in the binding list
        assert report.binding_constraints.index("gross") < (
            report.binding_constraints.index("net")
        )
        assert report.net_after == pytest.approx(1.0, rel=1e-12)
        # final weights: A = 2.0 * (2/3) * 0.5 = 0.6667
        assert report.weights["A"] == pytest.approx(2.0 * (2.0 / 3.0) * 0.5, rel=1e-12)


# ---------------------------------------------------------------------------
# apply_leverage_limits -- asset-class caps
# ---------------------------------------------------------------------------


class TestAssetClassCaps:
    """Per-class gross caps scale only the offending class members."""

    def test_class_cap_scales_only_members(self) -> None:
        # equity gross = 1.5 (> cap 1.0) => factor 2/3 on equity only.
        # fx gross = 0.5 (< cap) => untouched.
        cfg = LeverageConfig(
            max_gross=10.0,
            max_net=10.0,
            asset_class_caps={"equity": 1.0},
        )
        weights = {"AAPL": 1.0, "MSFT": 0.5, "EURUSD": 0.5}
        amap = {"AAPL": "equity", "MSFT": "equity", "EURUSD": "fx"}
        report = apply_leverage_limits(weights, config=cfg, asset_class_map=amap)
        scale = 1.0 / 1.5
        assert report.weights["AAPL"] == pytest.approx(1.0 * scale, rel=1e-12)
        assert report.weights["MSFT"] == pytest.approx(0.5 * scale, rel=1e-12)
        assert report.weights["EURUSD"] == pytest.approx(0.5, rel=1e-12)
        assert "asset_class:equity" in report.binding_constraints

    def test_class_under_cap_untouched(self) -> None:
        cfg = LeverageConfig(
            max_gross=10.0,
            max_net=10.0,
            asset_class_caps={"equity": 2.0},
        )
        weights = {"AAPL": 1.0, "MSFT": 0.5}
        amap = {"AAPL": "equity", "MSFT": "equity"}
        report = apply_leverage_limits(weights, config=cfg, asset_class_map=amap)
        assert report.binding_constraints == []
        assert report.weights == {"AAPL": 1.0, "MSFT": 0.5}

    def test_two_classes_both_capped(self) -> None:
        cfg = LeverageConfig(
            max_gross=10.0,
            max_net=10.0,
            asset_class_caps={"equity": 1.0, "fx": 0.4},
        )
        weights = {"AAPL": 1.5, "EURUSD": 0.8}
        amap = {"AAPL": "equity", "EURUSD": "fx"}
        report = apply_leverage_limits(weights, config=cfg, asset_class_map=amap)
        assert report.weights["AAPL"] == pytest.approx(1.0, rel=1e-12)
        assert report.weights["EURUSD"] == pytest.approx(0.4, rel=1e-12)
        # processed in sorted order: equity before fx
        assert report.binding_constraints == ["asset_class:equity", "asset_class:fx"]

    def test_missing_class_map_treats_as_unclassed(self) -> None:
        # asset_class_map is None but caps are set; no member matches the class
        # label, so the class has no members and nothing is scaled.
        cfg = LeverageConfig(
            max_gross=10.0,
            max_net=10.0,
            asset_class_caps={"equity": 0.1},
        )
        weights = {"AAPL": 1.0}
        report = apply_leverage_limits(weights, config=cfg)
        assert report.binding_constraints == []
        assert report.weights == {"AAPL": 1.0}

    def test_class_with_short_members(self) -> None:
        # class gross uses absolute values.
        cfg = LeverageConfig(
            max_gross=10.0,
            max_net=10.0,
            asset_class_caps={"equity": 1.0},
        )
        weights = {"AAPL": 1.0, "MSFT": -1.0}
        amap = {"AAPL": "equity", "MSFT": "equity"}
        report = apply_leverage_limits(weights, config=cfg, asset_class_map=amap)
        # class gross = 2.0 -> factor 0.5
        assert report.weights["AAPL"] == pytest.approx(0.5, rel=1e-12)
        assert report.weights["MSFT"] == pytest.approx(-0.5, rel=1e-12)


# ---------------------------------------------------------------------------
# apply_leverage_limits -- edge cases
# ---------------------------------------------------------------------------


class TestLeverageLimitsEdge:
    """Edge cases for apply_leverage_limits."""

    def test_empty_book(self) -> None:
        report = apply_leverage_limits({})
        assert report.weights == {}
        assert report.gross_before == 0.0
        assert report.gross_after == 0.0
        assert report.net_before == 0.0
        assert report.net_after == 0.0
        assert report.binding_constraints == []

    def test_all_zero_weights(self) -> None:
        cfg = LeverageConfig(max_gross=2.0, max_net=1.0)
        report = apply_leverage_limits({"A": 0.0, "B": 0.0}, config=cfg)
        assert report.binding_constraints == []
        assert report.weights == {"A": 0.0, "B": 0.0}

    def test_returns_leverage_report_type(self) -> None:
        report = apply_leverage_limits({"A": 0.5})
        assert isinstance(report, LeverageReport)
        assert isinstance(report.binding_constraints, list)

    def test_input_not_mutated(self) -> None:
        cfg = LeverageConfig(max_gross=1.0, max_net=10.0)
        original = {"A": 1.0, "B": 1.0}
        apply_leverage_limits(original, config=cfg)
        assert original == {"A": 1.0, "B": 1.0}

    def test_default_config_used(self) -> None:
        # Default max_gross=2.0; gross=3.0 should bind.
        report = apply_leverage_limits({"A": 2.0, "B": 1.0})
        assert "gross" in report.binding_constraints


# ---------------------------------------------------------------------------
# dynamic_delever_factor
# ---------------------------------------------------------------------------


class TestDynamicDeleverFactor:
    """Drawdown and high-vol triggers compound multiplicatively."""

    def test_no_trigger_returns_one(self) -> None:
        cfg = LeverageConfig()
        factor = dynamic_delever_factor(
            current_drawdown=0.05, vol_regime_high=False, config=cfg
        )
        assert factor == 1.0

    def test_drawdown_only(self) -> None:
        cfg = LeverageConfig(
            drawdown_delever_threshold=0.10, drawdown_delever_factor=0.5
        )
        factor = dynamic_delever_factor(
            current_drawdown=0.12, vol_regime_high=False, config=cfg
        )
        assert factor == pytest.approx(0.5, rel=1e-12)

    def test_drawdown_exactly_at_threshold_triggers(self) -> None:
        cfg = LeverageConfig(
            drawdown_delever_threshold=0.10, drawdown_delever_factor=0.5
        )
        factor = dynamic_delever_factor(
            current_drawdown=0.10, vol_regime_high=False, config=cfg
        )
        assert factor == pytest.approx(0.5, rel=1e-12)

    def test_high_vol_only(self) -> None:
        cfg = LeverageConfig(high_vol_delever_factor=0.5)
        factor = dynamic_delever_factor(
            current_drawdown=0.0, vol_regime_high=True, config=cfg
        )
        assert factor == pytest.approx(0.5, rel=1e-12)

    def test_both_triggers_compound(self) -> None:
        cfg = LeverageConfig(
            drawdown_delever_threshold=0.10,
            drawdown_delever_factor=0.5,
            high_vol_delever_factor=0.5,
        )
        factor = dynamic_delever_factor(
            current_drawdown=0.15, vol_regime_high=True, config=cfg
        )
        assert factor == pytest.approx(0.25, rel=1e-12)

    def test_asymmetric_factors_compound(self) -> None:
        cfg = LeverageConfig(
            drawdown_delever_threshold=0.10,
            drawdown_delever_factor=0.6,
            high_vol_delever_factor=0.4,
        )
        factor = dynamic_delever_factor(
            current_drawdown=0.20, vol_regime_high=True, config=cfg
        )
        assert factor == pytest.approx(0.6 * 0.4, rel=1e-12)

    def test_zero_drawdown_no_trigger(self) -> None:
        cfg = LeverageConfig(drawdown_delever_threshold=0.10)
        factor = dynamic_delever_factor(
            current_drawdown=0.0, vol_regime_high=False, config=cfg
        )
        assert factor == 1.0

    def test_negative_drawdown_raises(self) -> None:
        with pytest.raises(ValueError, match="current_drawdown"):
            dynamic_delever_factor(current_drawdown=-0.01, vol_regime_high=False)

    def test_default_config(self) -> None:
        # Defaults: threshold 0.10, factor 0.5.
        factor = dynamic_delever_factor(current_drawdown=0.11, vol_regime_high=False)
        assert factor == pytest.approx(0.5, rel=1e-12)

    def test_factor_in_unit_interval(self) -> None:
        cfg = LeverageConfig()
        factor = dynamic_delever_factor(
            current_drawdown=0.50, vol_regime_high=True, config=cfg
        )
        assert 0.0 < factor <= 1.0


# ---------------------------------------------------------------------------
# apply_dynamic_delever
# ---------------------------------------------------------------------------


class TestApplyDynamicDelever:
    """apply_dynamic_delever scales every weight by the factor."""

    def test_halve_exposure(self) -> None:
        result = apply_dynamic_delever({"A": 1.0, "B": -0.5}, 0.5)
        assert result["A"] == pytest.approx(0.5, rel=1e-12)
        assert result["B"] == pytest.approx(-0.25, rel=1e-12)

    def test_factor_one_unchanged(self) -> None:
        result = apply_dynamic_delever({"A": 1.0, "B": -0.5}, 1.0)
        assert result == {"A": 1.0, "B": -0.5}

    def test_factor_zero_flattens(self) -> None:
        result = apply_dynamic_delever({"A": 1.0, "B": -0.5}, 0.0)
        assert result == {"A": 0.0, "B": -0.0}

    def test_signs_preserved(self) -> None:
        result = apply_dynamic_delever({"long": 2.0, "short": -1.0}, 0.5)
        assert result["long"] > 0.0
        assert result["short"] < 0.0

    def test_empty_book(self) -> None:
        assert apply_dynamic_delever({}, 0.5) == {}

    def test_negative_factor_raises(self) -> None:
        with pytest.raises(ValueError, match="factor"):
            apply_dynamic_delever({"A": 1.0}, -0.1)

    def test_input_not_mutated(self) -> None:
        original = {"A": 1.0}
        apply_dynamic_delever(original, 0.5)
        assert original == {"A": 1.0}

    def test_integration_with_factor(self) -> None:
        # dynamic_delever_factor -> apply_dynamic_delever round trip.
        cfg = LeverageConfig(
            drawdown_delever_threshold=0.10,
            drawdown_delever_factor=0.5,
            high_vol_delever_factor=0.5,
        )
        factor = dynamic_delever_factor(
            current_drawdown=0.15, vol_regime_high=True, config=cfg
        )
        result = apply_dynamic_delever({"A": 1.0}, factor)
        assert result["A"] == pytest.approx(0.25, rel=1e-12)
