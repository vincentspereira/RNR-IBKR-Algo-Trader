"""Tests for core_trading.money.capital_allocation (Phase 8.3)."""
from __future__ import annotations

from dataclasses import FrozenInstanceError

import numpy as np
import pandas as pd
import pytest

from core_trading.money.capital_allocation import (
    DEFAULT_LIFECYCLE_CONFIG,
    LifecycleAction,
    LifecycleConfig,
    LifecycleDecision,
    StrategyRecord,
    StrategyStage,
    allocate_live_capital,
    evaluate_lifecycle,
)
from core_trading.portfolio.strategy_allocator import (
    StrategyAllocatorConfig,
    allocate_strategies,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _record(
    *,
    strategy_id: str = "alpha",
    stage: StrategyStage = StrategyStage.PAPER,
    capital: float = 0.0,
    days_at_stage: int = 0,
    clean_days: int = 0,
    paper_sharpe: float | None = None,
    live_sharpe: float | None = None,
    reference_sharpe: float | None = None,
    live_sharpe_negative_days: int = 0,
    incident_count: int = 0,
) -> StrategyRecord:
    """Build a StrategyRecord with sensible defaults for tests."""
    return StrategyRecord(
        strategy_id=strategy_id,
        stage=stage,
        capital=capital,
        days_at_stage=days_at_stage,
        clean_days=clean_days,
        paper_sharpe=paper_sharpe,
        live_sharpe=live_sharpe,
        reference_sharpe=reference_sharpe,
        live_sharpe_negative_days=live_sharpe_negative_days,
        incident_count=incident_count,
    )


# ---------------------------------------------------------------------------
# LifecycleConfig validation
# ---------------------------------------------------------------------------


def test_default_config_singleton_is_valid() -> None:
    assert isinstance(DEFAULT_LIFECYCLE_CONFIG, LifecycleConfig)
    assert DEFAULT_LIFECYCLE_CONFIG.initial_live_capital == 5_000.0
    assert DEFAULT_LIFECYCLE_CONFIG.min_clean_days == 30


@pytest.mark.parametrize(
    "kwargs",
    [
        {"initial_live_capital": 0.0},
        {"initial_live_capital": -1.0},
        {"min_clean_days": 0},
        {"max_sharpe_shortfall": -0.01},
        {"max_sharpe_shortfall": 1.01},
        {"decommission_live_sharpe_days": 0},
        {"paper_degradation_limit": -0.1},
        {"paper_degradation_limit": 1.1},
        {"scale_step_factor": 1.0},
        {"scale_step_factor": 0.5},
        {"max_strategy_capital": 100.0},  # below initial_live_capital default
    ],
)
def test_config_rejects_bad_params(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        LifecycleConfig(**kwargs)


def test_config_accepts_boundary_values() -> None:
    cfg = LifecycleConfig(
        max_sharpe_shortfall=0.0,
        paper_degradation_limit=1.0,
        max_strategy_capital=5_000.0,
    )
    assert cfg.max_sharpe_shortfall == 0.0
    assert cfg.paper_degradation_limit == 1.0


# ---------------------------------------------------------------------------
# StrategyRecord validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"capital": -1.0},
        {"days_at_stage": -1},
        {"clean_days": -1},
        {"clean_days": 5, "days_at_stage": 4},
        {"live_sharpe_negative_days": -1},
        {"incident_count": -1},
    ],
)
def test_record_rejects_bad_invariants(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        _record(**kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# evaluate_lifecycle: stage transitions
# ---------------------------------------------------------------------------


def test_research_always_holds() -> None:
    rec = _record(stage=StrategyStage.RESEARCH, days_at_stage=999)
    decision = evaluate_lifecycle(rec)
    assert decision.action is LifecycleAction.HOLD
    assert decision.to_stage is StrategyStage.RESEARCH
    assert decision.trigger == "research_hold"


def test_decommissioned_is_terminal() -> None:
    rec = _record(stage=StrategyStage.DECOMMISSIONED)
    decision = evaluate_lifecycle(rec)
    assert decision.action is LifecycleAction.HOLD
    assert decision.trigger == "terminal"


def test_paper_promotes_when_clean_and_healthy() -> None:
    rec = _record(
        stage=StrategyStage.PAPER,
        days_at_stage=40,
        clean_days=35,
        paper_sharpe=1.0,
        reference_sharpe=1.2,
    )
    decision = evaluate_lifecycle(rec)
    assert decision.action is LifecycleAction.PROMOTE
    assert decision.to_stage is StrategyStage.SMALL_LIVE
    assert decision.target_capital == DEFAULT_LIFECYCLE_CONFIG.initial_live_capital
    assert decision.trigger == "paper_promotion"


def test_paper_holds_when_not_enough_clean_days() -> None:
    rec = _record(
        stage=StrategyStage.PAPER,
        days_at_stage=40,
        clean_days=10,
        paper_sharpe=1.0,
        reference_sharpe=1.0,
    )
    decision = evaluate_lifecycle(rec)
    assert decision.action is LifecycleAction.HOLD
    assert decision.trigger == "paper_clean_days"
    assert decision.observed == 10.0
    assert decision.limit == 30.0


def test_paper_promotes_when_no_positive_reference() -> None:
    # No reference Sharpe -> degradation gate is vacuously satisfied.
    rec = _record(
        stage=StrategyStage.PAPER,
        days_at_stage=40,
        clean_days=35,
        paper_sharpe=0.5,
        reference_sharpe=None,
    )
    decision = evaluate_lifecycle(rec)
    assert decision.action is LifecycleAction.PROMOTE


def test_paper_holds_in_band_between_promotion_and_decommission() -> None:
    # Default config: decommission floor = (1 - 0.50) * ref = 0.50 * ref;
    # promotion floor = 0.80 * ref.  A paper Sharpe in [0.50*ref, 0.80*ref)
    # is too weak to promote but not weak enough to retire -> HOLD.
    # reference 1.0 -> decommission floor 0.50, promotion floor 0.80.
    rec = _record(
        stage=StrategyStage.PAPER,
        clean_days=35,
        days_at_stage=40,
        paper_sharpe=0.6,  # 0.50 <= 0.6 < 0.80 -> band
        reference_sharpe=1.0,
    )
    decision = evaluate_lifecycle(rec)
    assert decision.action is LifecycleAction.HOLD
    assert decision.trigger == "paper_sharpe_weak"
    assert decision.observed == pytest.approx(0.6)
    assert decision.limit == pytest.approx(0.8)


def test_config_rejects_promotion_ratio_below_decommission_floor() -> None:
    # promotion_min_ratio 0.10 < 1 - paper_degradation_limit (0.50) -> reject.
    with pytest.raises(ValueError, match="paper_promotion_min_ratio"):
        LifecycleConfig(paper_promotion_min_ratio=0.10, paper_degradation_limit=0.50)


def test_config_rejects_promotion_ratio_out_of_range() -> None:
    with pytest.raises(ValueError, match="paper_promotion_min_ratio"):
        LifecycleConfig(paper_promotion_min_ratio=1.5)


# ---------------------------------------------------------------------------
# Decommission triggers
# ---------------------------------------------------------------------------


def test_decommission_on_persistent_negative_live_sharpe() -> None:
    rec = _record(
        stage=StrategyStage.SCALED_LIVE,
        capital=40_000.0,
        days_at_stage=80,
        clean_days=80,
        paper_sharpe=1.0,
        live_sharpe=-0.2,
        reference_sharpe=1.0,
        live_sharpe_negative_days=65,
    )
    decision = evaluate_lifecycle(rec)
    assert decision.action is LifecycleAction.DECOMMISSION
    assert decision.to_stage is StrategyStage.DECOMMISSIONED
    assert decision.target_capital == 0.0
    assert decision.trigger == "live_sharpe_negative"
    assert decision.observed == 65.0
    assert decision.limit == 60.0


def test_decommission_on_paper_degradation() -> None:
    rec = _record(
        stage=StrategyStage.PAPER,
        clean_days=35,
        days_at_stage=40,
        paper_sharpe=0.3,
        reference_sharpe=1.0,  # floor = 0.5; 0.3 < 0.5 -> decommission
    )
    decision = evaluate_lifecycle(rec)
    assert decision.action is LifecycleAction.DECOMMISSION
    assert decision.trigger == "paper_degradation"
    assert decision.observed == pytest.approx(0.7)


def test_decommission_priority_over_scale() -> None:
    # Would otherwise scale, but negative-live-sharpe trigger wins.
    rec = _record(
        stage=StrategyStage.SMALL_LIVE,
        capital=5_000.0,
        clean_days=40,
        days_at_stage=40,
        paper_sharpe=1.0,
        live_sharpe=0.9,
        reference_sharpe=1.0,
        live_sharpe_negative_days=70,
    )
    decision = evaluate_lifecycle(rec)
    assert decision.action is LifecycleAction.DECOMMISSION


def test_paper_degradation_not_triggered_without_reference() -> None:
    rec = _record(
        stage=StrategyStage.SMALL_LIVE,
        capital=5_000.0,
        clean_days=40,
        days_at_stage=40,
        paper_sharpe=0.01,
        live_sharpe=0.9,
        reference_sharpe=None,
        live_sharpe_negative_days=0,
    )
    decision = evaluate_lifecycle(rec)
    # No reference -> no degradation decommission; scales instead.
    assert decision.action is LifecycleAction.SCALE_UP


# ---------------------------------------------------------------------------
# Scaling gates
# ---------------------------------------------------------------------------


def test_small_live_scales_when_shortfall_ok() -> None:
    rec = _record(
        stage=StrategyStage.SMALL_LIVE,
        capital=5_000.0,
        clean_days=40,
        days_at_stage=40,
        paper_sharpe=1.0,
        live_sharpe=0.8,  # shortfall 0.2 <= 0.30
        reference_sharpe=1.0,
    )
    decision = evaluate_lifecycle(rec)
    assert decision.action is LifecycleAction.SCALE_UP
    assert decision.to_stage is StrategyStage.SCALED_LIVE
    assert decision.target_capital == 10_000.0  # 5000 * 2.0
    assert decision.trigger == "sharpe_shortfall_ok"


def test_small_live_holds_when_shortfall_too_big() -> None:
    rec = _record(
        stage=StrategyStage.SMALL_LIVE,
        capital=5_000.0,
        clean_days=40,
        days_at_stage=40,
        paper_sharpe=1.0,
        live_sharpe=0.5,  # shortfall 0.5 > 0.30
        reference_sharpe=1.0,
    )
    decision = evaluate_lifecycle(rec)
    assert decision.action is LifecycleAction.HOLD
    assert decision.trigger == "sharpe_shortfall"
    assert decision.observed == pytest.approx(0.5)


def test_small_live_holds_when_not_enough_clean_days() -> None:
    rec = _record(
        stage=StrategyStage.SMALL_LIVE,
        capital=5_000.0,
        clean_days=10,
        days_at_stage=40,
        paper_sharpe=1.0,
        live_sharpe=1.0,
        reference_sharpe=1.0,
    )
    decision = evaluate_lifecycle(rec)
    assert decision.action is LifecycleAction.HOLD
    assert decision.trigger == "scale_clean_days"


def test_small_live_holds_when_sharpe_undefined() -> None:
    rec = _record(
        stage=StrategyStage.SMALL_LIVE,
        capital=5_000.0,
        clean_days=40,
        days_at_stage=40,
        paper_sharpe=0.0,  # non-positive paper -> ratio undefined
        live_sharpe=0.5,
        reference_sharpe=None,
    )
    decision = evaluate_lifecycle(rec)
    assert decision.action is LifecycleAction.HOLD
    assert decision.trigger == "sharpe_undefined"


def test_scaled_live_grows_capital() -> None:
    rec = _record(
        stage=StrategyStage.SCALED_LIVE,
        capital=10_000.0,
        clean_days=40,
        days_at_stage=40,
        paper_sharpe=1.0,
        live_sharpe=0.9,
        reference_sharpe=1.0,
    )
    decision = evaluate_lifecycle(rec)
    assert decision.action is LifecycleAction.SCALE_UP
    assert decision.to_stage is StrategyStage.SCALED_LIVE
    assert decision.target_capital == 20_000.0


def test_scaled_live_caps_at_max_capital() -> None:
    rec = _record(
        stage=StrategyStage.SCALED_LIVE,
        capital=60_000.0,
        clean_days=40,
        days_at_stage=40,
        paper_sharpe=1.0,
        live_sharpe=1.0,
        reference_sharpe=1.0,
    )
    decision = evaluate_lifecycle(rec)
    # 60000 * 2 = 120000 capped at 100000.
    assert decision.target_capital == 100_000.0


def test_scaled_live_holds_at_ceiling() -> None:
    rec = _record(
        stage=StrategyStage.SCALED_LIVE,
        capital=100_000.0,
        clean_days=40,
        days_at_stage=40,
        paper_sharpe=1.0,
        live_sharpe=1.0,
        reference_sharpe=1.0,
    )
    decision = evaluate_lifecycle(rec)
    assert decision.action is LifecycleAction.HOLD
    assert decision.trigger == "max_capital"


def test_scaled_live_holds_when_clean_days_short() -> None:
    rec = _record(
        stage=StrategyStage.SCALED_LIVE,
        capital=20_000.0,
        clean_days=5,
        days_at_stage=40,
        paper_sharpe=1.0,
        live_sharpe=1.0,
        reference_sharpe=1.0,
    )
    decision = evaluate_lifecycle(rec)
    assert decision.action is LifecycleAction.HOLD
    assert decision.trigger == "scale_clean_days"


def test_scaled_live_holds_when_shortfall_undefined() -> None:
    rec = _record(
        stage=StrategyStage.SCALED_LIVE,
        capital=20_000.0,
        clean_days=40,
        days_at_stage=40,
        paper_sharpe=1.0,
        live_sharpe=None,  # undefined shortfall
        reference_sharpe=None,
    )
    decision = evaluate_lifecycle(rec)
    assert decision.action is LifecycleAction.HOLD
    assert decision.trigger == "sharpe_undefined"


def test_live_sharpe_exceeds_paper_no_shortfall() -> None:
    rec = _record(
        stage=StrategyStage.SMALL_LIVE,
        capital=5_000.0,
        clean_days=40,
        days_at_stage=40,
        paper_sharpe=1.0,
        live_sharpe=1.5,  # shortfall negative -> well within limit
        reference_sharpe=1.0,
    )
    decision = evaluate_lifecycle(rec)
    assert decision.action is LifecycleAction.SCALE_UP


# ---------------------------------------------------------------------------
# allocate_live_capital
# ---------------------------------------------------------------------------


def test_allocate_basic_stage_caps() -> None:
    records = [
        _record(strategy_id="research", stage=StrategyStage.RESEARCH),
        _record(strategy_id="paper", stage=StrategyStage.PAPER),
        _record(
            strategy_id="small",
            stage=StrategyStage.SMALL_LIVE,
            capital=5_000.0,
        ),
        _record(
            strategy_id="scaled",
            stage=StrategyStage.SCALED_LIVE,
            capital=40_000.0,
        ),
        _record(
            strategy_id="dead",
            stage=StrategyStage.DECOMMISSIONED,
        ),
    ]
    weights = {
        "research": 0.2,
        "paper": 0.2,
        "small": 0.2,
        "scaled": 0.3,
        "dead": 0.1,
    }
    out = allocate_live_capital(records, weights, total_capital=100_000.0)
    assert out["research"] == 0.0
    assert out["paper"] == 0.0
    assert out["small"] == 5_000.0  # flat, ignores weight
    assert out["scaled"] == 30_000.0  # 0.3 * 100000
    assert out["dead"] == 0.0


def test_allocate_scaled_capped_at_max() -> None:
    records = [
        _record(
            strategy_id="big",
            stage=StrategyStage.SCALED_LIVE,
            capital=10_000.0,
        ),
    ]
    out = allocate_live_capital(
        records, {"big": 0.9}, total_capital=1_000_000.0
    )
    # 0.9 * 1,000,000 = 900,000 capped at 100,000.
    assert out["big"] == 100_000.0


def test_allocate_small_live_capped_at_max_capital() -> None:
    # A SMALL_LIVE record with absurd capital is still capped.
    cfg = LifecycleConfig(max_strategy_capital=50_000.0)
    records = [
        _record(
            strategy_id="small",
            stage=StrategyStage.SMALL_LIVE,
            capital=80_000.0,
        ),
    ]
    out = allocate_live_capital(
        records, {"small": 0.5}, total_capital=100_000.0, config=cfg
    )
    assert out["small"] == 50_000.0


def test_allocate_missing_weight_treated_as_zero() -> None:
    records = [
        _record(
            strategy_id="scaled",
            stage=StrategyStage.SCALED_LIVE,
            capital=10_000.0,
        ),
        _record(
            strategy_id="small",
            stage=StrategyStage.SMALL_LIVE,
            capital=5_000.0,
        ),
    ]
    # No weights at all -> scaled gets 0, small still gets flat capital.
    out = allocate_live_capital(records, {}, total_capital=100_000.0)
    assert out["scaled"] == 0.0
    assert out["small"] == 5_000.0


def test_allocate_rejects_non_positive_total() -> None:
    with pytest.raises(ValueError, match="total_capital"):
        allocate_live_capital([], {}, total_capital=0.0)


def test_allocate_rejects_duplicate_ids() -> None:
    records = [
        _record(strategy_id="dup", stage=StrategyStage.SCALED_LIVE),
        _record(strategy_id="dup", stage=StrategyStage.SCALED_LIVE),
    ]
    with pytest.raises(ValueError, match="duplicate"):
        allocate_live_capital(records, {}, total_capital=100.0)


def test_allocate_rejects_unmatched_weight_key() -> None:
    records = [_record(strategy_id="known", stage=StrategyStage.SCALED_LIVE)]
    with pytest.raises(ValueError, match="no matching"):
        allocate_live_capital(
            records, {"ghost": 0.5}, total_capital=100.0
        )


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.1])
def test_allocate_rejects_bad_weight_values(bad: float) -> None:
    records = [_record(strategy_id="s", stage=StrategyStage.SCALED_LIVE)]
    with pytest.raises(ValueError):
        allocate_live_capital(records, {"s": bad}, total_capital=100.0)


def test_one_record_per_input() -> None:
    records = [
        _record(strategy_id=f"s{i}", stage=StrategyStage.SCALED_LIVE)
        for i in range(4)
    ]
    out = allocate_live_capital(records, {}, total_capital=100.0)
    assert sorted(out) == ["s0", "s1", "s2", "s3"]


# ---------------------------------------------------------------------------
# Phase 6 allocator integration (DOD tie-in)
# ---------------------------------------------------------------------------


def test_phase6_allocator_feeds_live_capital() -> None:
    """Real allocate_strategies output flows into allocate_live_capital.

    This is the Phase 8 DOD integration test: the Phase 6 multi-strategy
    allocator produces target weights from a live-returns panel, and those
    weights drive scaled-live capital while lifecycle caps zero out the
    non-live strategies.
    """
    rng = np.random.default_rng(20260605)
    n = 120
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    panel = pd.DataFrame(
        {
            "alpha": rng.normal(0.0008, 0.01, n),
            "beta": rng.normal(0.0006, 0.012, n),
            "gamma": rng.normal(0.0004, 0.008, n),
        },
        index=idx,
    )
    allocation = allocate_strategies(
        panel, StrategyAllocatorConfig(method="equal")
    )
    weights = dict(allocation.weights)
    assert set(weights) == {"alpha", "beta", "gamma"}
    assert pytest.approx(sum(weights.values()), abs=1e-9) == 1.0

    records = [
        _record(
            strategy_id="alpha",
            stage=StrategyStage.SCALED_LIVE,
            capital=20_000.0,
        ),
        _record(
            strategy_id="beta",
            stage=StrategyStage.SMALL_LIVE,
            capital=5_000.0,
        ),
        _record(strategy_id="gamma", stage=StrategyStage.PAPER),
    ]
    out = allocate_live_capital(records, weights, total_capital=90_000.0)

    # alpha (scaled) is sized by allocator weight (1/3) * 90,000 = 30,000.
    assert out["alpha"] == pytest.approx(weights["alpha"] * 90_000.0)
    # beta is flat small-live capital regardless of its allocator weight.
    assert out["beta"] == 5_000.0
    # gamma is paper -> zero live capital.
    assert out["gamma"] == 0.0


def test_decision_is_frozen_dataclass() -> None:
    rec = _record(stage=StrategyStage.RESEARCH)
    decision = evaluate_lifecycle(rec)
    assert isinstance(decision, LifecycleDecision)
    with pytest.raises(FrozenInstanceError):
        decision.action = LifecycleAction.PROMOTE  # type: ignore[misc]
