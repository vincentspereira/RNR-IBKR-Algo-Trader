"""Tests for core_trading.money.sizing (Phase 4.4).

All assertions are derived from closed-form textbook formulae so they can be
verified by hand.  No fixed-seed RNG is required because we construct returns
series with exact known statistics.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from core_trading.money.sizing import (
    PositionSize,
    SizingConfig,
    fractional_kelly,
    scale_to_budget,
    size_position,
    vol_target_weight,
)

# ---------------------------------------------------------------------------
# SizingConfig validation
# ---------------------------------------------------------------------------


class TestSizingConfigValidation:
    """SizingConfig.__post_init__ enforces valid parameter ranges."""

    def test_defaults_are_valid(self) -> None:
        cfg = SizingConfig()
        assert cfg.kelly_fraction == 0.25
        assert cfg.target_vol == 0.10
        assert cfg.per_position_cap == 0.02
        assert cfg.periods_per_year == 252

    def test_kelly_fraction_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="kelly_fraction"):
            SizingConfig(kelly_fraction=0.0)

    def test_kelly_fraction_above_one_raises(self) -> None:
        with pytest.raises(ValueError, match="kelly_fraction"):
            SizingConfig(kelly_fraction=1.01)

    def test_kelly_fraction_exactly_one_is_valid(self) -> None:
        cfg = SizingConfig(kelly_fraction=1.0)
        assert cfg.kelly_fraction == 1.0

    def test_target_vol_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="target_vol"):
            SizingConfig(target_vol=0.0)

    def test_target_vol_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="target_vol"):
            SizingConfig(target_vol=-0.05)

    def test_per_position_cap_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="per_position_cap"):
            SizingConfig(per_position_cap=0.0)

    def test_per_position_cap_above_one_raises(self) -> None:
        with pytest.raises(ValueError, match="per_position_cap"):
            SizingConfig(per_position_cap=1.1)

    def test_periods_per_year_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="periods_per_year"):
            SizingConfig(periods_per_year=0)

    def test_frozen(self) -> None:
        from dataclasses import FrozenInstanceError

        cfg = SizingConfig()
        with pytest.raises(FrozenInstanceError):
            cfg.kelly_fraction = 0.5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# fractional_kelly
# ---------------------------------------------------------------------------


class TestFractionalKelly:
    """Textbook: f* = mu / sigma^2; fractional = kelly_fraction * f*."""

    def test_quarter_kelly_textbook(self) -> None:
        # mu=0.001, sigma=0.02
        # full Kelly = 0.001 / (0.02**2) = 0.001 / 0.0004 = 2.5
        # quarter Kelly = 0.25 * 2.5 = 0.625
        result = fractional_kelly(0.001, 0.02, kelly_fraction=0.25)
        assert result == pytest.approx(0.625, rel=1e-9)

    def test_full_kelly(self) -> None:
        result = fractional_kelly(0.001, 0.02, kelly_fraction=1.0)
        assert result == pytest.approx(2.5, rel=1e-9)

    def test_half_kelly(self) -> None:
        result = fractional_kelly(0.001, 0.02, kelly_fraction=0.5)
        assert result == pytest.approx(1.25, rel=1e-9)

    def test_sigma_zero_returns_zero(self) -> None:
        assert fractional_kelly(0.001, 0.0) == 0.0

    def test_sigma_negative_returns_zero(self) -> None:
        assert fractional_kelly(0.001, -0.01) == 0.0

    def test_negative_mu_negative_kelly(self) -> None:
        # Negative edge -> negative Kelly (short signal)
        result = fractional_kelly(-0.001, 0.02, kelly_fraction=0.25)
        assert result == pytest.approx(-0.625, rel=1e-9)

    def test_mu_zero_returns_zero(self) -> None:
        assert fractional_kelly(0.0, 0.02) == 0.0

    def test_default_kelly_fraction(self) -> None:
        # Default is 0.25 (quarter-Kelly)
        result = fractional_kelly(0.001, 0.02)
        assert result == pytest.approx(0.625, rel=1e-9)


# ---------------------------------------------------------------------------
# vol_target_weight
# ---------------------------------------------------------------------------


def _returns_with_known_annualised_vol(
    target_annualised_vol: float,
    n: int = 1000,
    periods_per_year: int = 252,
) -> np.ndarray:
    """Build a deterministic returns array whose annualised vol is exactly reproducible.

    For an alternating +c / -c series of even length n, mean = 0 and
    std(ddof=1) = c * sqrt(n / (n-1)).  Setting c = per_period_vol *
    sqrt((n-1) / n) therefore yields std(ddof=1) == per_period_vol exactly
    (up to float rounding).
    """
    assert n % 2 == 0, "n must be even"
    per_period_vol = target_annualised_vol / math.sqrt(periods_per_year)
    # Solve for c such that std(ddof=1) of the alternating series equals per_period_vol.
    c = per_period_vol * math.sqrt((n - 1) / n)
    base = np.full(n, c)
    base[::2] *= -1
    actual = float(np.std(base, ddof=1))
    assert actual == pytest.approx(per_period_vol, rel=1e-9)
    return base


class TestVolTargetWeight:
    """vol_target_weight = target_vol / annualised_realised_vol."""

    def test_textbook_half_weight(self) -> None:
        # annualised vol = 0.20, target = 0.10 => weight = 0.5
        returns = _returns_with_known_annualised_vol(0.20, n=1000)
        result = vol_target_weight(returns, target_vol=0.10, periods_per_year=252)
        assert result == pytest.approx(0.5, rel=1e-6)

    def test_matching_vol_gives_weight_one(self) -> None:
        # annualised vol = 0.10, target = 0.10 => weight = 1.0
        returns = _returns_with_known_annualised_vol(0.10, n=1000)
        result = vol_target_weight(returns, target_vol=0.10, periods_per_year=252)
        assert result == pytest.approx(1.0, rel=1e-6)

    def test_low_realised_vol_gives_weight_above_one(self) -> None:
        # annualised vol = 0.05, target = 0.10 => weight = 2.0
        returns = _returns_with_known_annualised_vol(0.05, n=1000)
        result = vol_target_weight(returns, target_vol=0.10, periods_per_year=252)
        assert result == pytest.approx(2.0, rel=1e-6)

    def test_empty_returns_gives_zero(self) -> None:
        assert vol_target_weight([]) == 0.0

    def test_single_observation_gives_zero(self) -> None:
        assert vol_target_weight([0.01]) == 0.0

    def test_constant_returns_gives_zero(self) -> None:
        # std == 0 => return 0.0
        assert vol_target_weight([0.01, 0.01, 0.01, 0.01]) == 0.0

    def test_all_nan_gives_zero(self) -> None:
        assert vol_target_weight([float("nan"), float("nan")]) == 0.0

    def test_two_observations_valid(self) -> None:
        # Two finite observations are sufficient.
        result = vol_target_weight([0.01, -0.01], target_vol=0.10, periods_per_year=252)
        assert result > 0.0

    def test_pandas_series_accepted(self) -> None:
        returns = pd.Series(_returns_with_known_annualised_vol(0.20, n=500))
        result = vol_target_weight(returns, target_vol=0.10, periods_per_year=252)
        assert result == pytest.approx(0.5, rel=1e-6)

    def test_weekly_periods_per_year(self) -> None:
        returns = _returns_with_known_annualised_vol(0.20, n=500, periods_per_year=52)
        result = vol_target_weight(returns, target_vol=0.10, periods_per_year=52)
        assert result == pytest.approx(0.5, rel=1e-6)


# ---------------------------------------------------------------------------
# size_position
# ---------------------------------------------------------------------------


def _large_edge_returns() -> np.ndarray:
    """Returns series with realised annualised vol = 0.20 (weight = 0.5 at target 0.10)."""
    return _returns_with_known_annualised_vol(0.20, n=1000)


class TestSizePosition:
    """Integration tests for size_position."""

    def test_direction_zero_gives_zero(self) -> None:
        result = size_position(
            direction=0,
            mu=0.005,
            sigma=0.02,
            returns=_large_edge_returns(),
        )
        assert result.weight == 0.0
        assert result.kelly_weight == 0.0
        assert result.vol_target_weight == 0.0
        assert result.binding_constraint == "none"

    def test_per_position_cap_binds_when_smallest(self) -> None:
        # mu=0.001, sigma=0.02 => quarter-kelly = 0.625
        # returns annualised vol 0.20, target 0.10 => vt_weight = 0.5
        # per_position_cap = 0.02  -- smallest
        cfg = SizingConfig(
            kelly_fraction=0.25,
            target_vol=0.10,
            per_position_cap=0.02,
            periods_per_year=252,
            max_leverage=2.0,
        )
        result = size_position(
            direction=1,
            mu=0.001,
            sigma=0.02,
            returns=_large_edge_returns(),
            config=cfg,
        )
        assert result.weight == pytest.approx(0.02, rel=1e-9)
        assert result.binding_constraint == "per_position_cap"

    def test_vol_target_binds_when_smallest(self) -> None:
        # Make vol_target the binding constraint by setting a generous cap
        # and low expected edge.
        # mu=0.0001, sigma=0.02 => quarter-kelly = 0.0625
        # returns annualised vol 0.20, target 0.01 => vt_weight = 0.05
        # per_position_cap = 0.10  -- large
        # => min(0.0625, 0.05, 0.10) = 0.05 => vol_target binds
        cfg = SizingConfig(
            kelly_fraction=0.25,
            target_vol=0.01,
            per_position_cap=0.10,
            periods_per_year=252,
            max_leverage=2.0,
        )
        result = size_position(
            direction=1,
            mu=0.0001,
            sigma=0.02,
            returns=_large_edge_returns(),
            config=cfg,
        )
        assert result.binding_constraint == "vol_target"
        assert result.weight < 0.0625  # must be below Kelly

    def test_kelly_binds_when_smallest(self) -> None:
        # Make Kelly the binding constraint.
        # mu=0.0001, sigma=0.02 => quarter-kelly = 0.0625
        # returns annualised vol 0.20, target 0.20 => vt_weight = 1.0 (full)
        # per_position_cap = 0.50  -- very large
        # => min(0.0625, 1.0, 0.50) = 0.0625 => Kelly binds
        cfg = SizingConfig(
            kelly_fraction=0.25,
            target_vol=0.20,
            per_position_cap=0.50,
            periods_per_year=252,
            max_leverage=2.0,
        )
        result = size_position(
            direction=1,
            mu=0.0001,
            sigma=0.02,
            returns=_large_edge_returns(),
            config=cfg,
        )
        assert result.binding_constraint == "kelly"
        assert result.weight == pytest.approx(0.0625, rel=1e-6)

    def test_long_direction_positive_weight(self) -> None:
        result = size_position(
            direction=1,
            mu=0.001,
            sigma=0.02,
            returns=_large_edge_returns(),
        )
        assert result.weight > 0.0

    def test_short_direction_negative_weight(self) -> None:
        result = size_position(
            direction=-1,
            mu=0.001,
            sigma=0.02,
            returns=_large_edge_returns(),
        )
        assert result.weight < 0.0

    def test_long_and_short_symmetric_magnitude(self) -> None:
        long_result = size_position(
            direction=1,
            mu=0.001,
            sigma=0.02,
            returns=_large_edge_returns(),
        )
        short_result = size_position(
            direction=-1,
            mu=0.001,
            sigma=0.02,
            returns=_large_edge_returns(),
        )
        assert abs(long_result.weight) == pytest.approx(abs(short_result.weight), rel=1e-9)
        assert long_result.weight == pytest.approx(-short_result.weight, rel=1e-9)

    def test_invalid_direction_raises(self) -> None:
        with pytest.raises(ValueError, match="direction"):
            size_position(
                direction=2,  # type: ignore[arg-type]
                mu=0.001,
                sigma=0.02,
                returns=_large_edge_returns(),
            )

    def test_returns_dataclass_types(self) -> None:
        result = size_position(
            direction=1,
            mu=0.001,
            sigma=0.02,
            returns=_large_edge_returns(),
        )
        assert isinstance(result, PositionSize)
        assert isinstance(result.weight, float)
        assert isinstance(result.kelly_weight, float)
        assert isinstance(result.vol_target_weight, float)
        assert isinstance(result.binding_constraint, str)

    def test_binding_constraint_valid_values(self) -> None:
        valid = {"kelly", "vol_target", "per_position_cap", "none"}
        result = size_position(
            direction=1,
            mu=0.001,
            sigma=0.02,
            returns=_large_edge_returns(),
        )
        assert result.binding_constraint in valid

    def test_zero_sigma_direction_positive(self) -> None:
        # fractional_kelly returns 0 when sigma=0; vol_target may also
        # be 0 if returns empty.  Weight must be 0.
        result = size_position(
            direction=1,
            mu=0.001,
            sigma=0.0,
            returns=[],
        )
        assert result.weight == 0.0

    def test_max_leverage_clips_kelly(self) -> None:
        # mu=0.1, sigma=0.02 => full_kelly = 250, quarter_kelly = 62.5
        # max_leverage=0.5 should clip to 0.5 before the three-way min
        cfg = SizingConfig(
            kelly_fraction=0.25,
            target_vol=1.0,   # very high target -> large vt_weight
            per_position_cap=1.0,
            max_leverage=0.5,
        )
        result = size_position(
            direction=1,
            mu=0.1,
            sigma=0.02,
            returns=_large_edge_returns(),
            config=cfg,
        )
        assert result.weight <= 0.5

    def test_direction_sign_flows_regardless_of_kelly_sign(self) -> None:
        # Even if mu < 0 (negative Kelly), direction controls the sign
        cfg = SizingConfig(per_position_cap=1.0, target_vol=1.0, max_leverage=10.0)
        result = size_position(
            direction=-1,
            mu=-0.001,   # negative edge -> negative Kelly
            sigma=0.02,
            returns=_large_edge_returns(),
            config=cfg,
        )
        # weight should be negative (short) regardless of Kelly sign
        assert result.weight < 0.0


# ---------------------------------------------------------------------------
# scale_to_budget
# ---------------------------------------------------------------------------


class TestScaleToBudget:
    """scale_to_budget enforces a gross-exposure budget."""

    def test_over_budget_scales_down(self) -> None:
        # weights summing to 3.0 with budget 2.0 => scale by 2/3
        weights = {"A": 1.0, "B": 1.0, "C": 1.0}
        result = scale_to_budget(weights, gross_budget=2.0)
        assert sum(abs(v) for v in result.values()) == pytest.approx(2.0, rel=1e-9)
        expected_scale = 2.0 / 3.0
        for k, v in result.items():
            assert v == pytest.approx(weights[k] * expected_scale, rel=1e-9)

    def test_under_budget_unchanged(self) -> None:
        weights = {"A": 0.3, "B": -0.2}
        result = scale_to_budget(weights, gross_budget=1.0)
        assert result == {"A": 0.3, "B": -0.2}

    def test_exactly_at_budget_unchanged(self) -> None:
        weights = {"A": 0.5, "B": -0.5}
        result = scale_to_budget(weights, gross_budget=1.0)
        assert result["A"] == pytest.approx(0.5, rel=1e-9)
        assert result["B"] == pytest.approx(-0.5, rel=1e-9)

    def test_signs_preserved_after_scaling(self) -> None:
        weights = {"long": 2.0, "short": -1.0}
        result = scale_to_budget(weights, gross_budget=1.0)
        assert result["long"] > 0.0
        assert result["short"] < 0.0

    def test_relative_magnitudes_preserved(self) -> None:
        weights = {"A": 2.0, "B": 1.0}
        result = scale_to_budget(weights, gross_budget=1.0)
        # A should still be twice B after scaling
        assert result["A"] == pytest.approx(2.0 * result["B"], rel=1e-9)

    def test_empty_dict_returns_empty(self) -> None:
        assert scale_to_budget({}, gross_budget=1.0) == {}

    def test_invalid_budget_raises(self) -> None:
        with pytest.raises(ValueError, match="gross_budget"):
            scale_to_budget({"A": 0.5}, gross_budget=0.0)

    def test_negative_budget_raises(self) -> None:
        with pytest.raises(ValueError, match="gross_budget"):
            scale_to_budget({"A": 0.5}, gross_budget=-1.0)

    def test_returns_new_dict(self) -> None:
        original = {"A": 0.3}
        result = scale_to_budget(original, gross_budget=1.0)
        result["A"] = 999.0  # mutating result must not affect original
        assert original["A"] == 0.3

    def test_over_budget_exact_textbook(self) -> None:
        # weights = {A: 1.2, B: -0.8, C: 1.0} => gross = 3.0, budget = 2.0
        # scale = 2/3
        weights = {"A": 1.2, "B": -0.8, "C": 1.0}
        result = scale_to_budget(weights, gross_budget=2.0)
        scale = 2.0 / 3.0
        assert result["A"] == pytest.approx(1.2 * scale, rel=1e-9)
        assert result["B"] == pytest.approx(-0.8 * scale, rel=1e-9)
        assert result["C"] == pytest.approx(1.0 * scale, rel=1e-9)
