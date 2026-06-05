"""Tests for core_trading.money.turnover (Phase 8.5).

All assertions are hand-computed from the one-sided turnover convention
(``sum |dw| / 2``) and the cost-budget / edge-vs-cost inequalities, so they can
be verified without a reference implementation.  No RNG is needed; where a
DataFrame is constructed it has exact known weights.
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import numpy as np
import pandas as pd
import pytest

from core_trading.money.turnover import (
    TurnoverConfig,
    TurnoverDecision,
    check_turnover_budget,
    cost_budget_ok,
    cost_budget_ratio,
    edge_exceeds_cost,
    filter_trades_by_edge,
    monthly_turnover,
    realised_turnover,
    turnover_headroom,
)

# ---------------------------------------------------------------------------
# TurnoverConfig validation
# ---------------------------------------------------------------------------


class TestTurnoverConfigValidation:
    """TurnoverConfig.__post_init__ enforces valid parameter ranges."""

    def test_defaults_are_valid(self) -> None:
        cfg = TurnoverConfig()
        assert cfg.max_monthly_turnover == 2.0
        assert cfg.max_cost_alpha_ratio == 0.30
        assert cfg.min_edge_cost_multiple == 2.0
        assert cfg.periods_per_month == 21

    def test_max_monthly_turnover_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="max_monthly_turnover"):
            TurnoverConfig(max_monthly_turnover=-0.1)

    def test_max_monthly_turnover_nan_raises(self) -> None:
        with pytest.raises(ValueError, match="max_monthly_turnover"):
            TurnoverConfig(max_monthly_turnover=float("nan"))

    def test_max_monthly_turnover_zero_is_valid(self) -> None:
        cfg = TurnoverConfig(max_monthly_turnover=0.0)
        assert cfg.max_monthly_turnover == 0.0

    def test_cost_ratio_above_one_raises(self) -> None:
        with pytest.raises(ValueError, match="max_cost_alpha_ratio"):
            TurnoverConfig(max_cost_alpha_ratio=1.01)

    def test_cost_ratio_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="max_cost_alpha_ratio"):
            TurnoverConfig(max_cost_alpha_ratio=-0.01)

    def test_cost_ratio_boundaries_valid(self) -> None:
        assert TurnoverConfig(max_cost_alpha_ratio=0.0).max_cost_alpha_ratio == 0.0
        assert TurnoverConfig(max_cost_alpha_ratio=1.0).max_cost_alpha_ratio == 1.0

    def test_min_edge_multiple_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="min_edge_cost_multiple"):
            TurnoverConfig(min_edge_cost_multiple=0.0)

    def test_min_edge_multiple_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="min_edge_cost_multiple"):
            TurnoverConfig(min_edge_cost_multiple=-1.0)

    def test_min_edge_multiple_inf_raises(self) -> None:
        with pytest.raises(ValueError, match="min_edge_cost_multiple"):
            TurnoverConfig(min_edge_cost_multiple=float("inf"))

    def test_periods_per_month_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="periods_per_month"):
            TurnoverConfig(periods_per_month=0)

    def test_periods_per_month_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="periods_per_month"):
            TurnoverConfig(periods_per_month=-5)

    def test_frozen(self) -> None:
        cfg = TurnoverConfig()
        with pytest.raises(FrozenInstanceError):
            cfg.max_monthly_turnover = 3.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# realised_turnover
# ---------------------------------------------------------------------------


class TestRealisedTurnover:
    """One-sided turnover: sum |dw| / 2 per consecutive pair of rows."""

    def test_simple_two_row_known_value(self) -> None:
        # A: 0.5 -> 0.3 (|dw|=0.2); B: 0.5 -> 0.7 (|dw|=0.2)
        # L1 = 0.4, one-sided = 0.2
        wh = pd.DataFrame({"A": [0.5, 0.3], "B": [0.5, 0.7]})
        out = realised_turnover(wh)
        assert len(out) == 1
        assert out.iloc[0] == pytest.approx(0.2)

    def test_full_rotation_is_one(self) -> None:
        # Sell all of A (1.0 -> 0.0), buy all of B (0.0 -> 1.0).
        # L1 = 2.0, one-sided = 1.0 (one round-trip of NAV).
        wh = pd.DataFrame({"A": [1.0, 0.0], "B": [0.0, 1.0]})
        out = realised_turnover(wh)
        assert out.iloc[0] == pytest.approx(1.0)

    def test_nan_treated_as_zero_entering_asset(self) -> None:
        # Asset C enters at row 1 with weight 0.4 (NaN == 0 before).
        # A: 0.6 -> 0.6 (0); C: NaN(=0) -> 0.4 (0.4). L1 = 0.4, one-sided 0.2
        wh = pd.DataFrame({"A": [0.6, 0.6], "C": [np.nan, 0.4]})
        out = realised_turnover(wh)
        assert out.iloc[0] == pytest.approx(0.2)

    def test_nan_treated_as_zero_leaving_asset(self) -> None:
        # Asset B leaves at row 1 (0.3 -> NaN == 0). |dw| = 0.3, one-sided 0.15
        wh = pd.DataFrame({"A": [0.7, 0.7], "B": [0.3, np.nan]})
        out = realised_turnover(wh)
        assert out.iloc[0] == pytest.approx(0.15)

    def test_multi_period_index_preserved(self) -> None:
        idx = pd.date_range("2024-01-01", periods=3, freq="D")
        wh = pd.DataFrame(
            {"A": [0.5, 0.4, 0.4], "B": [0.5, 0.6, 0.5]}, index=idx
        )
        out = realised_turnover(wh)
        # period 1: A |0.1| + B |0.1| -> 0.2/2 = 0.1
        # period 2: A |0.0| + B |0.1| -> 0.1/2 = 0.05
        assert list(out.index) == list(idx[1:])
        assert out.iloc[0] == pytest.approx(0.1)
        assert out.iloc[1] == pytest.approx(0.05)

    def test_single_row_returns_empty(self) -> None:
        wh = pd.DataFrame({"A": [1.0]})
        out = realised_turnover(wh)
        assert out.empty

    def test_empty_returns_empty(self) -> None:
        wh = pd.DataFrame()
        out = realised_turnover(wh)
        assert out.empty


# ---------------------------------------------------------------------------
# monthly_turnover
# ---------------------------------------------------------------------------


class TestMonthlyTurnover:
    """Rolling sum of per-period turnover over periods_per_month."""

    def test_rolling_sum_window(self) -> None:
        # per-period turnovers will be [0.1, 0.1, 0.1, 0.1] across 5 rows.
        wh = pd.DataFrame(
            {
                "A": [0.5, 0.4, 0.3, 0.2, 0.1],
                "B": [0.5, 0.6, 0.7, 0.8, 0.9],
            }
        )
        out = monthly_turnover(wh, periods_per_month=2)
        # per-period each = 0.1; rolling-2 sum: [0.1, 0.2, 0.2, 0.2]
        assert out.iloc[0] == pytest.approx(0.1)
        assert out.iloc[1] == pytest.approx(0.2)
        assert out.iloc[2] == pytest.approx(0.2)
        assert out.iloc[3] == pytest.approx(0.2)

    def test_window_larger_than_history_sums_all(self) -> None:
        wh = pd.DataFrame({"A": [0.5, 0.4, 0.3], "B": [0.5, 0.6, 0.7]})
        out = monthly_turnover(wh, periods_per_month=21)
        # two per-period turnovers of 0.1 each, cumulative
        assert out.iloc[0] == pytest.approx(0.1)
        assert out.iloc[1] == pytest.approx(0.2)

    def test_single_row_empty(self) -> None:
        wh = pd.DataFrame({"A": [1.0]})
        assert monthly_turnover(wh).empty

    def test_invalid_periods_raises(self) -> None:
        wh = pd.DataFrame({"A": [1.0, 0.5], "B": [0.0, 0.5]})
        with pytest.raises(ValueError, match="periods_per_month"):
            monthly_turnover(wh, periods_per_month=0)


# ---------------------------------------------------------------------------
# turnover_headroom
# ---------------------------------------------------------------------------


class TestTurnoverHeadroom:
    """Headroom = cap - trailing (periods_per_month - 1) turnover, floored 0."""

    def test_no_history_full_headroom(self) -> None:
        wh = pd.DataFrame({"A": [1.0]})
        cfg = TurnoverConfig(max_monthly_turnover=2.0)
        assert turnover_headroom(wh, config=cfg) == pytest.approx(2.0)

    def test_partial_consumption(self) -> None:
        # 4 rows -> 3 per-period turnovers of 0.1 each = 0.3 over window
        # periods_per_month=4 -> window=3, used = 0.3, headroom = 2.0-0.3=1.7
        wh = pd.DataFrame(
            {
                "A": [0.5, 0.4, 0.3, 0.2],
                "B": [0.5, 0.6, 0.7, 0.8],
            }
        )
        cfg = TurnoverConfig(max_monthly_turnover=2.0, periods_per_month=4)
        assert turnover_headroom(wh, config=cfg) == pytest.approx(1.7)

    def test_window_truncates_old_turnover(self) -> None:
        # 5 rows -> 4 per-period turnovers of 0.1; window = periods-1 = 1
        # only the most recent 0.1 counts. headroom = 2.0 - 0.1 = 1.9
        wh = pd.DataFrame(
            {
                "A": [0.5, 0.4, 0.3, 0.2, 0.1],
                "B": [0.5, 0.6, 0.7, 0.8, 0.9],
            }
        )
        cfg = TurnoverConfig(max_monthly_turnover=2.0, periods_per_month=2)
        assert turnover_headroom(wh, config=cfg) == pytest.approx(1.9)

    def test_floor_at_zero_when_overspent(self) -> None:
        # one per-period turnover of 1.0; cap 0.5 -> headroom floored to 0
        wh = pd.DataFrame({"A": [1.0, 0.0], "B": [0.0, 1.0]})
        cfg = TurnoverConfig(max_monthly_turnover=0.5, periods_per_month=2)
        assert turnover_headroom(wh, config=cfg) == 0.0

    def test_periods_one_means_no_prior_window(self) -> None:
        # window = periods_per_month - 1 = 0 -> no prior turnover counts.
        wh = pd.DataFrame({"A": [1.0, 0.0], "B": [0.0, 1.0]})
        cfg = TurnoverConfig(max_monthly_turnover=2.0, periods_per_month=1)
        assert turnover_headroom(wh, config=cfg) == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# check_turnover_budget
# ---------------------------------------------------------------------------


class TestCheckTurnoverBudget:
    """Decision logic for proposed rebalances against the monthly cap."""

    def test_within_budget_allows_full_move(self) -> None:
        current = {"A": 0.5, "B": 0.5}
        proposed = {"A": 0.4, "B": 0.6}  # one-sided turnover = 0.1
        wh = pd.DataFrame({"A": [0.5], "B": [0.5]})
        cfg = TurnoverConfig(max_monthly_turnover=2.0)
        dec = check_turnover_budget(current, proposed, wh, config=cfg)
        assert isinstance(dec, TurnoverDecision)
        assert dec.allowed is True
        assert dec.reason == "within_budget"
        assert dec.proposed_turnover == pytest.approx(0.1)
        assert dec.used_budget == pytest.approx(0.0)
        assert dec.remaining_budget == pytest.approx(2.0)
        assert dec.scaled_weights["A"] == pytest.approx(0.4)
        assert dec.scaled_weights["B"] == pytest.approx(0.6)

    def test_no_trade_zero_turnover(self) -> None:
        current = {"A": 0.5, "B": 0.5}
        proposed = {"A": 0.5, "B": 0.5}
        wh = pd.DataFrame({"A": [0.5], "B": [0.5]})
        dec = check_turnover_budget(current, proposed, wh)
        assert dec.allowed is True
        assert dec.reason == "no_trade"
        assert dec.proposed_turnover == 0.0

    def test_no_budget_stays_put(self) -> None:
        # Consume the whole budget in history, then propose a move.
        # 2 rows: full rotation = 1.0 turnover; cap 1.0, periods=2 window=1.
        wh = pd.DataFrame({"A": [1.0, 0.0], "B": [0.0, 1.0]})
        cfg = TurnoverConfig(max_monthly_turnover=1.0, periods_per_month=2)
        current = {"A": 0.0, "B": 1.0}
        proposed = {"A": 1.0, "B": 0.0}
        dec = check_turnover_budget(current, proposed, wh, config=cfg)
        assert dec.allowed is False
        assert dec.reason == "no_budget"
        assert dec.remaining_budget == 0.0
        # stays at current
        assert dec.scaled_weights["A"] == pytest.approx(0.0)
        assert dec.scaled_weights["B"] == pytest.approx(1.0)

    def test_breach_scales_proportionally(self) -> None:
        # No history -> full budget. Cap 0.1; proposed move turnover 0.2.
        # scale = 0.1 / 0.2 = 0.5; move halfway from current to proposed.
        current = {"A": 0.5, "B": 0.5}
        proposed = {"A": 0.3, "B": 0.7}  # one-sided turnover = 0.2
        wh = pd.DataFrame({"A": [0.5], "B": [0.5]})
        cfg = TurnoverConfig(max_monthly_turnover=0.1)
        dec = check_turnover_budget(current, proposed, wh, config=cfg)
        assert dec.allowed is False
        assert dec.reason == "breach_scaled"
        assert dec.proposed_turnover == pytest.approx(0.2)
        assert dec.remaining_budget == pytest.approx(0.1)
        # halfway: A = 0.5 + (0.3-0.5)*0.5 = 0.4; B = 0.5 + (0.7-0.5)*0.5 = 0.6
        assert dec.scaled_weights["A"] == pytest.approx(0.4)
        assert dec.scaled_weights["B"] == pytest.approx(0.6)
        # and the scaled move consumes exactly the remaining budget
        scaled_turnover = (
            abs(dec.scaled_weights["A"] - current["A"])
            + abs(dec.scaled_weights["B"] - current["B"])
        ) / 2.0
        assert scaled_turnover == pytest.approx(0.1)

    def test_exactly_at_cap_is_allowed(self) -> None:
        # proposed turnover exactly equals remaining budget -> allowed.
        current = {"A": 0.5, "B": 0.5}
        proposed = {"A": 0.4, "B": 0.6}  # turnover 0.1
        wh = pd.DataFrame({"A": [0.5], "B": [0.5]})
        cfg = TurnoverConfig(max_monthly_turnover=0.1)
        dec = check_turnover_budget(current, proposed, wh, config=cfg)
        assert dec.allowed is True
        assert dec.reason == "within_budget"

    def test_asset_entering_handled(self) -> None:
        # New asset C in proposed only; current has no C (treated as 0).
        current = {"A": 1.0}
        proposed = {"A": 0.6, "C": 0.4}  # A:|0.4|, C:|0.4| -> one-sided 0.4
        wh = pd.DataFrame({"A": [1.0]})
        cfg = TurnoverConfig(max_monthly_turnover=2.0)
        dec = check_turnover_budget(current, proposed, wh, config=cfg)
        assert dec.proposed_turnover == pytest.approx(0.4)
        assert dec.scaled_weights["C"] == pytest.approx(0.4)
        assert dec.scaled_weights["A"] == pytest.approx(0.6)

    def test_used_budget_reduces_headroom(self) -> None:
        # History consumes 0.1 (window=1), cap 0.25 -> remaining 0.15.
        # propose turnover 0.2 > 0.15 -> breach, scale = 0.15/0.2 = 0.75.
        wh = pd.DataFrame({"A": [0.5, 0.4], "B": [0.5, 0.6]})  # last turn 0.1
        cfg = TurnoverConfig(max_monthly_turnover=0.25, periods_per_month=2)
        current = {"A": 0.4, "B": 0.6}
        proposed = {"A": 0.2, "B": 0.8}  # turnover 0.2
        dec = check_turnover_budget(current, proposed, wh, config=cfg)
        assert dec.used_budget == pytest.approx(0.1)
        assert dec.remaining_budget == pytest.approx(0.15)
        assert dec.reason == "breach_scaled"
        # A = 0.4 + (0.2-0.4)*0.75 = 0.25
        assert dec.scaled_weights["A"] == pytest.approx(0.25)

    def test_empty_history(self) -> None:
        current = {"A": 0.5, "B": 0.5}
        proposed = {"A": 0.4, "B": 0.6}
        dec = check_turnover_budget(current, proposed, pd.DataFrame())
        assert dec.used_budget == pytest.approx(0.0)
        assert dec.allowed is True


# ---------------------------------------------------------------------------
# cost_budget_ratio / cost_budget_ok
# ---------------------------------------------------------------------------


class TestCostBudget:
    """costs <= max_cost_alpha_ratio * gross_alpha."""

    def test_ratio_known_value(self) -> None:
        assert cost_budget_ratio(0.10, 0.02) == pytest.approx(0.2)

    def test_ratio_zero_alpha_zero_cost(self) -> None:
        assert cost_budget_ratio(0.0, 0.0) == 0.0

    def test_ratio_zero_alpha_positive_cost_is_inf(self) -> None:
        assert cost_budget_ratio(0.0, 0.01) == float("inf")

    def test_ratio_negative_alpha_is_inf(self) -> None:
        assert cost_budget_ratio(-0.05, 0.01) == float("inf")

    def test_ratio_negative_cost_raises(self) -> None:
        with pytest.raises(ValueError, match="expected_costs"):
            cost_budget_ratio(0.1, -0.01)

    def test_ok_within_budget(self) -> None:
        # ratio 0.2 <= 0.30 default
        assert cost_budget_ok(0.10, 0.02) is True

    def test_ok_exactly_at_budget(self) -> None:
        # ratio 0.30 == 0.30 -> allowed (<=)
        cfg = TurnoverConfig(max_cost_alpha_ratio=0.30)
        assert cost_budget_ok(0.10, 0.03, config=cfg) is True

    def test_ok_over_budget(self) -> None:
        # ratio 0.40 > 0.30
        assert cost_budget_ok(0.10, 0.04) is False

    def test_ok_zero_alpha_zero_cost_true(self) -> None:
        assert cost_budget_ok(0.0, 0.0) is True

    def test_ok_zero_alpha_positive_cost_false(self) -> None:
        assert cost_budget_ok(0.0, 0.001) is False

    def test_ok_custom_ratio(self) -> None:
        cfg = TurnoverConfig(max_cost_alpha_ratio=0.5)
        assert cost_budget_ok(0.10, 0.05, config=cfg) is True
        assert cost_budget_ok(0.10, 0.06, config=cfg) is False


# ---------------------------------------------------------------------------
# edge_exceeds_cost / filter_trades_by_edge
# ---------------------------------------------------------------------------


class TestEdgeExceedsCost:
    """edge > min_edge_cost_multiple * cost (default multiple = 2)."""

    def test_edge_beats_2x_cost(self) -> None:
        # edge 0.03 > 2 * 0.01 = 0.02
        assert edge_exceeds_cost(0.03, 0.01) is True

    def test_edge_below_2x_cost(self) -> None:
        assert edge_exceeds_cost(0.015, 0.01) is False

    def test_edge_exactly_2x_cost_excluded(self) -> None:
        # strict inequality: edge == 2*cost -> False
        assert edge_exceeds_cost(0.02, 0.01) is False

    def test_zero_cost_positive_edge_true(self) -> None:
        assert edge_exceeds_cost(0.001, 0.0) is True

    def test_zero_cost_zero_edge_false(self) -> None:
        # 0 > 0 is False
        assert edge_exceeds_cost(0.0, 0.0) is False

    def test_negative_cost_raises(self) -> None:
        with pytest.raises(ValueError, match="expected_cost"):
            edge_exceeds_cost(0.05, -0.01)

    def test_custom_multiple(self) -> None:
        cfg = TurnoverConfig(min_edge_cost_multiple=3.0)
        assert edge_exceeds_cost(0.04, 0.01, config=cfg) is True  # 0.04 > 0.03
        assert edge_exceeds_cost(0.03, 0.01, config=cfg) is False  # 0.03 !> 0.03


class TestFilterTradesByEdge:
    """Vectorised per-asset edge filter."""

    def test_known_mask(self) -> None:
        edges = pd.Series({"A": 0.03, "B": 0.015, "C": 0.05})
        costs = pd.Series({"A": 0.01, "B": 0.01, "C": 0.01})
        out = filter_trades_by_edge(edges, costs)
        # A: 0.03 > 0.02 True; B: 0.015 > 0.02 False; C: 0.05 > 0.02 True
        assert out["A"] is np.True_ or bool(out["A"]) is True
        assert bool(out["A"]) is True
        assert bool(out["B"]) is False
        assert bool(out["C"]) is True
        assert out.dtype == bool

    def test_index_preserved(self) -> None:
        edges = pd.Series({"X": 0.1, "Y": 0.0})
        costs = pd.Series({"X": 0.01, "Y": 0.01})
        out = filter_trades_by_edge(edges, costs)
        assert list(out.index) == ["X", "Y"]

    def test_misaligned_index_raises(self) -> None:
        edges = pd.Series({"A": 0.03, "B": 0.02})
        costs = pd.Series({"A": 0.01, "C": 0.01})
        with pytest.raises(ValueError, match="same index"):
            filter_trades_by_edge(edges, costs)

    def test_negative_cost_raises(self) -> None:
        edges = pd.Series({"A": 0.03})
        costs = pd.Series({"A": -0.01})
        with pytest.raises(ValueError, match="non-negative"):
            filter_trades_by_edge(edges, costs)

    def test_custom_multiple(self) -> None:
        edges = pd.Series({"A": 0.04, "B": 0.025})
        costs = pd.Series({"A": 0.01, "B": 0.01})
        cfg = TurnoverConfig(min_edge_cost_multiple=3.0)
        out = filter_trades_by_edge(edges, costs, config=cfg)
        # threshold 0.03: A 0.04 True; B 0.025 False
        assert bool(out["A"]) is True
        assert bool(out["B"]) is False
