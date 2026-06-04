"""Tests for core_trading.portfolio.rebalance (Phase 6.7).

Covers:
* Config validation of every parameter bound (turnover budget 0 allowed).
* drift_weights: hand-computed buy-and-hold drift, the no-move identity,
  the degenerate long-short book, and the validation battery.
* The trigger decision matrix: calendar / threshold / hybrid, each in
  due and not-due states, with the reason strings ("calendar",
  "threshold", "both", "none").
* Turnover budgeting: exact proportional scaling, the full-trade path,
  budget larger than desired, budget zero (decision fires, nothing
  trades), and self-financing preservation (trades sum to zero between
  fully-invested books).
* Input validation and the frozen result DTO.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest

from core_trading.portfolio.rebalance import (
    RebalanceConfig,
    RebalanceDecision,
    drift_weights,
    rebalance_decision,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _series(values: list[float], names: list[str] | None = None) -> pd.Series:
    idx = names if names is not None else [f"A{i:02d}" for i in range(len(values))]
    return pd.Series(np.asarray(values, dtype=float), index=idx)


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


class TestConfigValidation:
    def test_defaults_are_valid(self) -> None:
        cfg = RebalanceConfig()
        assert cfg.trigger == "hybrid"
        assert cfg.calendar_period == 21
        assert cfg.threshold == 0.05
        assert cfg.turnover_budget is None

    def test_bad_trigger(self) -> None:
        with pytest.raises(ValueError, match="trigger"):
            RebalanceConfig(trigger="daily")

    def test_bad_calendar_period(self) -> None:
        with pytest.raises(ValueError, match="calendar_period"):
            RebalanceConfig(calendar_period=0)

    @pytest.mark.parametrize("t", [0.0, -0.05, float("nan")])
    def test_bad_threshold(self, t: float) -> None:
        with pytest.raises(ValueError, match="threshold"):
            RebalanceConfig(threshold=t)

    @pytest.mark.parametrize("b", [-0.1, float("nan"), float("inf")])
    def test_bad_turnover_budget(self, b: float) -> None:
        with pytest.raises(ValueError, match="turnover_budget"):
            RebalanceConfig(turnover_budget=b)

    def test_zero_turnover_budget_allowed(self) -> None:
        assert RebalanceConfig(turnover_budget=0.0).turnover_budget == 0.0


# ---------------------------------------------------------------------------
# drift_weights
# ---------------------------------------------------------------------------


class TestDriftWeights:
    def test_hand_computed(self) -> None:
        drifted = drift_weights(_series([0.5, 0.5]), _series([0.1, -0.1]))
        np.testing.assert_allclose(drifted.to_numpy(), [0.55, 0.45], atol=1e-15)

    def test_zero_returns_identity(self) -> None:
        weights = _series([0.3, 0.7])
        drifted = drift_weights(weights, _series([0.0, 0.0]))
        np.testing.assert_allclose(drifted.to_numpy(), weights.to_numpy(), atol=1e-15)

    def test_long_short_drift(self) -> None:
        # 130/30 book: winners grow the long side's share.
        drifted = drift_weights(_series([1.3, -0.3]), _series([0.1, 0.0]))
        total = 1.3 * 1.1 - 0.3
        np.testing.assert_allclose(
            drifted.to_numpy(), [1.43 / total, -0.3 / total], atol=1e-15
        )

    def test_degenerate_book_raises(self) -> None:
        with pytest.raises(ValueError, match="undefined"):
            drift_weights(_series([1.0, -1.0]), _series([0.0, 0.0]))

    def test_misaligned_raises(self) -> None:
        with pytest.raises(ValueError, match="period_returns index"):
            drift_weights(
                _series([0.5, 0.5]), _series([0.1, 0.1], names=["B", "A"])
            )

    def test_nan_weights_raise(self) -> None:
        with pytest.raises(ValueError, match="weights contain"):
            drift_weights(_series([np.nan, 0.5]), _series([0.0, 0.0]))

    def test_nan_returns_raise(self) -> None:
        with pytest.raises(ValueError, match="period_returns contain"):
            drift_weights(_series([0.5, 0.5]), _series([np.nan, 0.0]))

    def test_total_loss_raises(self) -> None:
        with pytest.raises(ValueError, match="-100%"):
            drift_weights(_series([0.5, 0.5]), _series([-1.0, 0.0]))


# ---------------------------------------------------------------------------
# Trigger decision matrix
# ---------------------------------------------------------------------------


class TestTriggerMatrix:
    _CURRENT = _series([0.5, 0.5])
    _NEAR = _series([0.51, 0.49])  # drift 0.02
    _FAR = _series([0.8, 0.2])  # drift 0.60

    def test_calendar_due_fires_even_with_zero_drift(self) -> None:
        decision = rebalance_decision(
            self._CURRENT,
            self._CURRENT,
            bars_since_rebalance=21,
            config=RebalanceConfig(trigger="calendar"),
        )
        assert decision.should_rebalance is True
        assert decision.reason == "calendar"
        assert decision.drift == 0.0

    def test_calendar_not_due_ignores_huge_drift(self) -> None:
        decision = rebalance_decision(
            self._CURRENT,
            self._FAR,
            bars_since_rebalance=20,
            config=RebalanceConfig(trigger="calendar"),
        )
        assert decision.should_rebalance is False
        assert decision.reason == "none"
        assert decision.drift == pytest.approx(0.6, abs=1e-15)
        assert float(decision.trades.abs().sum()) == 0.0
        pd.testing.assert_series_equal(decision.new_weights, self._CURRENT)

    def test_threshold_fires_on_drift(self) -> None:
        decision = rebalance_decision(
            self._CURRENT,
            self._FAR,
            bars_since_rebalance=0,
            config=RebalanceConfig(trigger="threshold", threshold=0.05),
        )
        assert decision.should_rebalance is True
        assert decision.reason == "threshold"

    def test_threshold_quiet_below_drift(self) -> None:
        decision = rebalance_decision(
            self._CURRENT,
            self._NEAR,
            bars_since_rebalance=1000,
            config=RebalanceConfig(trigger="threshold", threshold=0.05),
        )
        assert decision.should_rebalance is False
        assert decision.reason == "none"

    def test_hybrid_calendar_only(self) -> None:
        decision = rebalance_decision(
            self._CURRENT,
            self._NEAR,
            bars_since_rebalance=21,
            config=RebalanceConfig(trigger="hybrid", threshold=0.05),
        )
        assert decision.should_rebalance is True
        assert decision.reason == "calendar"

    def test_hybrid_threshold_only(self) -> None:
        decision = rebalance_decision(
            self._CURRENT,
            self._FAR,
            bars_since_rebalance=3,
            config=RebalanceConfig(trigger="hybrid", threshold=0.05),
        )
        assert decision.should_rebalance is True
        assert decision.reason == "threshold"

    def test_hybrid_both(self) -> None:
        decision = rebalance_decision(
            self._CURRENT,
            self._FAR,
            bars_since_rebalance=21,
            config=RebalanceConfig(trigger="hybrid", threshold=0.05),
        )
        assert decision.should_rebalance is True
        assert decision.reason == "both"

    def test_hybrid_neither(self) -> None:
        decision = rebalance_decision(
            self._CURRENT,
            self._NEAR,
            bars_since_rebalance=3,
            config=RebalanceConfig(trigger="hybrid", threshold=0.05),
        )
        assert decision.should_rebalance is False
        assert decision.reason == "none"

    def test_threshold_boundary_inclusive(self) -> None:
        decision = rebalance_decision(
            self._CURRENT,
            self._NEAR,  # drift exactly 0.02
            bars_since_rebalance=0,
            config=RebalanceConfig(trigger="threshold", threshold=0.02),
        )
        assert decision.should_rebalance is True

    def test_calendar_boundary_inclusive(self) -> None:
        decision = rebalance_decision(
            self._CURRENT,
            self._CURRENT,
            bars_since_rebalance=5,
            config=RebalanceConfig(trigger="calendar", calendar_period=5),
        )
        assert decision.should_rebalance is True


# ---------------------------------------------------------------------------
# Turnover budgeting
# ---------------------------------------------------------------------------


class TestTurnoverBudget:
    def test_full_trade_without_budget(self) -> None:
        current = _series([0.5, 0.5])
        target = _series([0.8, 0.2])
        decision = rebalance_decision(
            current,
            target,
            bars_since_rebalance=21,
            config=RebalanceConfig(trigger="calendar"),
        )
        pd.testing.assert_series_equal(decision.new_weights, target)
        assert decision.turnover == pytest.approx(0.6, abs=1e-15)

    def test_proportional_scaling(self) -> None:
        current = _series([0.5, 0.5])
        target = _series([0.8, 0.2])
        decision = rebalance_decision(
            current,
            target,
            bars_since_rebalance=21,
            config=RebalanceConfig(trigger="calendar", turnover_budget=0.3),
        )
        np.testing.assert_allclose(
            decision.trades.to_numpy(), [0.15, -0.15], atol=1e-15
        )
        np.testing.assert_allclose(
            decision.new_weights.to_numpy(), [0.65, 0.35], atol=1e-15
        )
        assert decision.turnover == pytest.approx(0.3, abs=1e-15)
        # Self-financing: both books fully invested -> trades net to zero.
        assert float(decision.trades.sum()) == pytest.approx(0.0, abs=1e-15)

    def test_budget_larger_than_desired_trades_fully(self) -> None:
        current = _series([0.5, 0.5])
        target = _series([0.6, 0.4])
        decision = rebalance_decision(
            current,
            target,
            bars_since_rebalance=21,
            config=RebalanceConfig(trigger="calendar", turnover_budget=5.0),
        )
        pd.testing.assert_series_equal(decision.new_weights, target)

    def test_zero_budget_fires_but_does_not_trade(self) -> None:
        current = _series([0.5, 0.5])
        target = _series([0.8, 0.2])
        decision = rebalance_decision(
            current,
            target,
            bars_since_rebalance=21,
            config=RebalanceConfig(trigger="calendar", turnover_budget=0.0),
        )
        assert decision.should_rebalance is True
        assert decision.turnover == 0.0
        pd.testing.assert_series_equal(decision.new_weights, current)

    def test_already_at_target_trades_nothing(self) -> None:
        current = _series([0.5, 0.5])
        decision = rebalance_decision(
            current,
            current,
            bars_since_rebalance=21,
            config=RebalanceConfig(trigger="calendar", turnover_budget=0.5),
        )
        assert decision.should_rebalance is True
        assert decision.turnover == 0.0


# ---------------------------------------------------------------------------
# Input validation and DTO
# ---------------------------------------------------------------------------


class TestValidationAndDTO:
    def test_misaligned_target_raises(self) -> None:
        with pytest.raises(ValueError, match="target index"):
            rebalance_decision(
                _series([0.5, 0.5]),
                _series([0.5, 0.5], names=["B", "A"]),
                bars_since_rebalance=0,
            )

    def test_nan_current_raises(self) -> None:
        with pytest.raises(ValueError, match="current weights"):
            rebalance_decision(
                _series([np.nan, 0.5]), _series([0.5, 0.5]), bars_since_rebalance=0
            )

    def test_nan_target_raises(self) -> None:
        with pytest.raises(ValueError, match="target weights"):
            rebalance_decision(
                _series([0.5, 0.5]), _series([np.nan, 0.5]), bars_since_rebalance=0
            )

    def test_negative_bars_raises(self) -> None:
        with pytest.raises(ValueError, match="bars_since_rebalance"):
            rebalance_decision(
                _series([0.5, 0.5]), _series([0.5, 0.5]), bars_since_rebalance=-1
            )

    def test_frozen_and_equality(self) -> None:
        decision = rebalance_decision(
            _series([0.5, 0.5]), _series([0.5, 0.5]), bars_since_rebalance=0
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            decision.reason = "other"  # type: ignore[misc]
        other = RebalanceDecision(
            should_rebalance=False,
            reason="none",
            drift=0.0,
            trades=_series([1.0, -1.0]),
            new_weights=_series([9.0, 9.0]),
            turnover=0.0,
        )
        assert decision == other  # Series fields excluded from equality
