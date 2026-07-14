"""Tests for core_trading.risk.circuit_breakers (Phase 7.8 DOD).

Coverage targets
----------------
* All BreakerState / BreakerType enum members.
* BreakerConfig validation (__post_init__).
* BreakerEvent field correctness.
* CircuitBreakerEngine: strategy update, portfolio update, intraday update,
  new_session, manual_reset, query helpers.

Simulation tests (explicit DOD items)
--------------------------------------
SIM-1  Strategy DD crosses 10% on a known bar -> PAUSED fires exactly there,
       not before.
SIM-2  Portfolio DD path crossing 15% then 25% -> DERISKED then HALTED at
       exact bars; HALTED sticky until manual_reset.
SIM-3  Intraday loss crossing 3% NAV -> HALT_NEW_ORDERS same session;
       auto-reset next session start.
SIM-4  Recovery: DD recovers above re-arm threshold but cooldown not elapsed
       -> still PAUSED; after cooldown -> NORMAL.
SIM-5  No false fires on a long flat / grinding-up equity curve.
SIM-6  Combined multi-breaker replay (all three active simultaneously)
       producing the full expected event sequence.

Boundary semantics
------------------
All thresholds use STRICT greater-than (>) for firing, STRICT less-than (<)
for re-arm.  Tests pin this at the exact threshold value to guard regressions.
"""
from __future__ import annotations

import pandas as pd
import pytest

from core_trading.risk.circuit_breakers import (
    DEFAULT_CONFIG,
    BreakerConfig,
    BreakerEvent,
    BreakerState,
    BreakerType,
    CircuitBreakerEngine,
)

# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------


def _ts(day: int) -> pd.Timestamp:
    """Return a deterministic timestamp for test day N (starting 2024-01-01)."""
    return pd.Timestamp("2024-01-01") + pd.Timedelta(days=day - 1)


# ---------------------------------------------------------------------------
# BreakerConfig validation
# ---------------------------------------------------------------------------


class TestBreakerConfig:
    def test_defaults_accepted(self) -> None:
        cfg = BreakerConfig()
        assert cfg.strategy_dd_threshold == 0.10
        assert cfg.strategy_rearm_pct == 0.05
        assert cfg.strategy_cooldown_sessions == 2
        assert cfg.portfolio_derisk_threshold == 0.15
        assert cfg.portfolio_halt_threshold == 0.25
        assert cfg.portfolio_derisk_factor == 0.50
        assert cfg.portfolio_rearm_pct == 0.05
        assert cfg.portfolio_cooldown_sessions == 3
        assert cfg.portfolio_halt_sticky is True
        assert cfg.daily_loss_threshold == 0.03

    @pytest.mark.parametrize(
        "field,value",
        [
            ("strategy_dd_threshold", 0.0),
            ("strategy_dd_threshold", -0.01),
            ("strategy_rearm_pct", 0.0),
            ("portfolio_derisk_threshold", 0.0),
            ("portfolio_halt_threshold", 0.0),
            ("portfolio_derisk_factor", 0.0),
            ("portfolio_rearm_pct", 0.0),
            ("daily_loss_threshold", 0.0),
        ],
    )
    def test_non_positive_raises(self, field: str, value: float) -> None:
        with pytest.raises(ValueError, match=field):
            BreakerConfig(**{field: value})  # type: ignore[arg-type]

    def test_halt_threshold_must_exceed_derisk_threshold(self) -> None:
        with pytest.raises(ValueError, match="portfolio_halt_threshold"):
            BreakerConfig(
                portfolio_derisk_threshold=0.20,
                portfolio_halt_threshold=0.15,
            )

    def test_halt_equal_to_derisk_raises(self) -> None:
        with pytest.raises(ValueError, match="portfolio_halt_threshold"):
            BreakerConfig(
                portfolio_derisk_threshold=0.20,
                portfolio_halt_threshold=0.20,
            )

    def test_negative_strategy_cooldown_raises(self) -> None:
        with pytest.raises(ValueError, match="strategy_cooldown_sessions"):
            BreakerConfig(strategy_cooldown_sessions=-1)

    def test_negative_portfolio_cooldown_raises(self) -> None:
        with pytest.raises(ValueError, match="portfolio_cooldown_sessions"):
            BreakerConfig(portfolio_cooldown_sessions=-1)

    def test_derisk_factor_must_be_in_open_unit_interval(self) -> None:
        with pytest.raises(ValueError, match="portfolio_derisk_factor"):
            BreakerConfig(portfolio_derisk_factor=1.0)
        with pytest.raises(ValueError, match="portfolio_derisk_factor"):
            BreakerConfig(portfolio_derisk_factor=0.0)

    def test_custom_config_round_trips(self) -> None:
        cfg = BreakerConfig(
            strategy_dd_threshold=0.08,
            portfolio_halt_sticky=False,
            strategy_cooldown_sessions=0,
        )
        assert cfg.strategy_dd_threshold == 0.08
        assert cfg.portfolio_halt_sticky is False
        assert cfg.strategy_cooldown_sessions == 0

    def test_default_config_singleton(self) -> None:
        assert DEFAULT_CONFIG.strategy_dd_threshold == 0.10


# ---------------------------------------------------------------------------
# BreakerState and BreakerType enums
# ---------------------------------------------------------------------------


class TestEnums:
    def test_all_states_present(self) -> None:
        names = {s.value for s in BreakerState}
        assert "NORMAL" in names
        assert "PAUSED" in names
        assert "DERISKED" in names
        assert "HALTED" in names
        assert "HALT_NEW_ORDERS" in names

    def test_all_types_present(self) -> None:
        names = {t.value for t in BreakerType}
        assert "STRATEGY" in names
        assert "PORTFOLIO" in names
        assert "DAILY_LOSS" in names


# ---------------------------------------------------------------------------
# BreakerEvent structure
# ---------------------------------------------------------------------------


class TestBreakerEvent:
    def test_event_fields_accessible(self) -> None:
        ts = _ts(1)
        evt = BreakerEvent(
            timestamp=ts,
            breaker=BreakerType.STRATEGY,
            strategy_id="alpha",
            from_state=BreakerState.NORMAL,
            to_state=BreakerState.PAUSED,
            metric=0.11,
            threshold=0.10,
            message="test event",
        )
        assert evt.timestamp == ts
        assert evt.breaker == BreakerType.STRATEGY
        assert evt.strategy_id == "alpha"
        assert evt.from_state == BreakerState.NORMAL
        assert evt.to_state == BreakerState.PAUSED
        assert evt.metric == pytest.approx(0.11)
        assert evt.threshold == pytest.approx(0.10)
        assert "test event" in evt.message

    def test_event_is_immutable(self) -> None:
        evt = BreakerEvent(
            timestamp=_ts(1),
            breaker=BreakerType.PORTFOLIO,
            strategy_id=None,
            from_state=BreakerState.NORMAL,
            to_state=BreakerState.HALTED,
            metric=0.26,
            threshold=0.25,
            message="halt",
        )
        with pytest.raises((AttributeError, TypeError)):
            evt.metric = 0.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Engine: basic query helpers and initial state
# ---------------------------------------------------------------------------


class TestEngineInitialState:
    def test_unknown_strategy_is_normal(self) -> None:
        eng = CircuitBreakerEngine()
        assert eng.strategy_state("new_strat") == BreakerState.NORMAL

    def test_portfolio_state_initially_normal(self) -> None:
        eng = CircuitBreakerEngine()
        assert eng.portfolio_state == BreakerState.NORMAL

    def test_daily_state_initially_normal(self) -> None:
        eng = CircuitBreakerEngine()
        assert eng.daily_state == BreakerState.NORMAL

    def test_exposure_factor_normal(self) -> None:
        eng = CircuitBreakerEngine()
        assert eng.portfolio_exposure_factor == pytest.approx(1.0)

    def test_can_place_new_orders_initially_true(self) -> None:
        eng = CircuitBreakerEngine()
        assert eng.can_place_new_orders() is True

    def test_events_list_initially_empty(self) -> None:
        eng = CircuitBreakerEngine()
        assert eng.events == []


# ---------------------------------------------------------------------------
# Engine: strategy update -- invalid input
# ---------------------------------------------------------------------------


class TestStrategyUpdateValidation:
    def test_zero_equity_raises(self) -> None:
        eng = CircuitBreakerEngine()
        with pytest.raises(ValueError, match="equity must be > 0"):
            eng.update("s", _ts(1), equity=0.0)

    def test_negative_equity_raises(self) -> None:
        eng = CircuitBreakerEngine()
        with pytest.raises(ValueError, match="equity must be > 0"):
            eng.update("s", _ts(1), equity=-50.0)


# ---------------------------------------------------------------------------
# Engine: portfolio update -- invalid input
# ---------------------------------------------------------------------------


class TestPortfolioUpdateValidation:
    def test_zero_equity_raises(self) -> None:
        eng = CircuitBreakerEngine()
        with pytest.raises(ValueError, match="Portfolio equity must be > 0"):
            eng.update_portfolio(_ts(1), equity=0.0)

    def test_negative_equity_raises(self) -> None:
        eng = CircuitBreakerEngine()
        with pytest.raises(ValueError, match="Portfolio equity must be > 0"):
            eng.update_portfolio(_ts(1), equity=-1.0)


# ---------------------------------------------------------------------------
# Engine: intraday update -- invalid input
# ---------------------------------------------------------------------------


class TestIntradayUpdateValidation:
    def test_zero_nav_raises(self) -> None:
        eng = CircuitBreakerEngine()
        with pytest.raises(ValueError, match="current_nav must be > 0"):
            eng.update_intraday(_ts(1), current_nav=0.0)

    def test_negative_nav_raises(self) -> None:
        eng = CircuitBreakerEngine()
        with pytest.raises(ValueError, match="current_nav must be > 0"):
            eng.update_intraday(_ts(1), current_nav=-10.0)


# ---------------------------------------------------------------------------
# Engine: strategy -- boundary semantics
# ---------------------------------------------------------------------------


class TestStrategyBoundary:
    """Pin strict > semantics at exact threshold."""

    def test_exactly_at_threshold_does_not_fire(self) -> None:
        """DD == 0.10 must NOT fire (strict >)."""
        cfg = BreakerConfig(strategy_dd_threshold=0.10, strategy_cooldown_sessions=0)
        eng = CircuitBreakerEngine(cfg)
        # peak = 100, equity = 90 -> DD = 10.0% exactly
        eng.update("s", _ts(1), equity=100.0)
        evts = eng.update("s", _ts(2), equity=90.0)
        assert evts == []
        assert eng.strategy_state("s") == BreakerState.NORMAL

    def test_one_tick_above_threshold_fires(self) -> None:
        """DD = 0.1001 must fire."""
        cfg = BreakerConfig(strategy_dd_threshold=0.10, strategy_cooldown_sessions=0)
        eng = CircuitBreakerEngine(cfg)
        eng.update("s", _ts(1), equity=100.0)
        evts = eng.update("s", _ts(2), equity=89.99)
        assert len(evts) == 1
        assert evts[0].to_state == BreakerState.PAUSED
        assert eng.strategy_state("s") == BreakerState.PAUSED


# ---------------------------------------------------------------------------
# Engine: portfolio -- boundary semantics
# ---------------------------------------------------------------------------


class TestPortfolioBoundary:
    def test_exactly_at_derisk_threshold_does_not_fire(self) -> None:
        """DD == 0.15 must NOT fire DERISKED (strict >)."""
        cfg = BreakerConfig(
            portfolio_derisk_threshold=0.15,
            portfolio_halt_threshold=0.25,
        )
        eng = CircuitBreakerEngine(cfg)
        eng.update_portfolio(_ts(1), equity=100.0)
        evts = eng.update_portfolio(_ts(2), equity=85.0)
        assert evts == []
        assert eng.portfolio_state == BreakerState.NORMAL

    def test_one_tick_above_derisk_fires(self) -> None:
        cfg = BreakerConfig(
            portfolio_derisk_threshold=0.15,
            portfolio_halt_threshold=0.25,
        )
        eng = CircuitBreakerEngine(cfg)
        eng.update_portfolio(_ts(1), equity=100.0)
        evts = eng.update_portfolio(_ts(2), equity=84.99)
        assert len(evts) == 1
        assert evts[0].to_state == BreakerState.DERISKED

    def test_exactly_at_halt_threshold_does_not_fire(self) -> None:
        cfg = BreakerConfig(
            portfolio_derisk_threshold=0.15,
            portfolio_halt_threshold=0.25,
        )
        eng = CircuitBreakerEngine(cfg)
        eng.update_portfolio(_ts(1), equity=100.0)
        evts = eng.update_portfolio(_ts(2), equity=75.0)
        # DD = 25.0% exactly -- should only DERISKED, not HALTED.
        assert len(evts) == 1
        assert evts[0].to_state == BreakerState.DERISKED

    def test_one_tick_above_halt_fires_halt(self) -> None:
        cfg = BreakerConfig(
            portfolio_derisk_threshold=0.15,
            portfolio_halt_threshold=0.25,
        )
        eng = CircuitBreakerEngine(cfg)
        eng.update_portfolio(_ts(1), equity=100.0)
        evts = eng.update_portfolio(_ts(2), equity=74.99)
        assert len(evts) == 1
        assert evts[0].to_state == BreakerState.HALTED


# ---------------------------------------------------------------------------
# Engine: intraday -- boundary semantics
# ---------------------------------------------------------------------------


class TestIntradayBoundary:
    def test_exactly_at_threshold_does_not_fire(self) -> None:
        cfg = BreakerConfig(daily_loss_threshold=0.03)
        eng = CircuitBreakerEngine(cfg)
        eng.new_session(_ts(1), session_open_nav=100.0)
        # loss = 3.0% exactly -> should NOT fire
        evts = eng.update_intraday(_ts(1), current_nav=97.0)
        assert evts == []
        assert eng.daily_state == BreakerState.NORMAL

    def test_one_tick_above_threshold_fires(self) -> None:
        cfg = BreakerConfig(daily_loss_threshold=0.03)
        eng = CircuitBreakerEngine(cfg)
        eng.new_session(_ts(1), session_open_nav=100.0)
        evts = eng.update_intraday(_ts(1), current_nav=96.99)
        assert len(evts) == 1
        assert evts[0].to_state == BreakerState.HALT_NEW_ORDERS


# ---------------------------------------------------------------------------
# SIM-1: Strategy DD crosses 10% on a known bar -> PAUSED fires exactly there
# ---------------------------------------------------------------------------


class TestSim1StrategyDdFires:
    """SIM-1 -- Strategy drawdown exceeds 10%, fires at exact bar."""

    def test_pauses_at_correct_bar(self) -> None:
        cfg = BreakerConfig(
            strategy_dd_threshold=0.10,
            strategy_cooldown_sessions=0,
        )
        eng = CircuitBreakerEngine(cfg)

        # Bar 1: establish peak at 100.
        evts_1 = eng.update("strat_A", _ts(1), equity=100.0)
        assert evts_1 == []
        assert eng.strategy_state("strat_A") == BreakerState.NORMAL

        # Bar 2: equity 95 -> DD = 5% -- should NOT fire.
        evts_2 = eng.update("strat_A", _ts(2), equity=95.0)
        assert evts_2 == []
        assert eng.strategy_state("strat_A") == BreakerState.NORMAL

        # Bar 3: equity 91 -> DD = 9% -- should NOT fire (< 10%).
        evts_3 = eng.update("strat_A", _ts(3), equity=91.0)
        assert evts_3 == []
        assert eng.strategy_state("strat_A") == BreakerState.NORMAL

        # Bar 4: equity 89 -> DD = 11% -- PAUSED fires HERE.
        evts_4 = eng.update("strat_A", _ts(4), equity=89.0)
        assert len(evts_4) == 1
        evt = evts_4[0]
        assert evt.from_state == BreakerState.NORMAL
        assert evt.to_state == BreakerState.PAUSED
        assert evt.breaker == BreakerType.STRATEGY
        assert evt.strategy_id == "strat_A"
        assert evt.timestamp == _ts(4)
        assert evt.metric == pytest.approx(0.11)
        assert evt.threshold == pytest.approx(0.10)
        assert eng.strategy_state("strat_A") == BreakerState.PAUSED

        # Bar 5: further decline -- no NEW event (already PAUSED).
        evts_5 = eng.update("strat_A", _ts(5), equity=85.0)
        assert evts_5 == []
        assert eng.strategy_state("strat_A") == BreakerState.PAUSED

        # Event log should have exactly one event.
        assert len(eng.events) == 1


# ---------------------------------------------------------------------------
# SIM-2: Portfolio DD -> DERISKED then HALTED; HALTED sticky until manual_reset
# ---------------------------------------------------------------------------


class TestSim2PortfolioGraduatedHalt:
    """SIM-2 -- Graduated portfolio halt sequence."""

    def test_derisk_then_halt_then_manual_reset(self) -> None:
        cfg = BreakerConfig(
            portfolio_derisk_threshold=0.15,
            portfolio_halt_threshold=0.25,
            portfolio_cooldown_sessions=0,
            portfolio_halt_sticky=True,
        )
        eng = CircuitBreakerEngine(cfg)

        # Establish peak at 1000.
        eng.update_portfolio(_ts(1), equity=1000.0)
        assert eng.portfolio_state == BreakerState.NORMAL
        assert eng.portfolio_exposure_factor == pytest.approx(1.0)

        # DD = 16% -> DERISKED fires here.
        evts_derisk = eng.update_portfolio(_ts(2), equity=840.0)
        assert len(evts_derisk) == 1
        assert evts_derisk[0].to_state == BreakerState.DERISKED
        assert evts_derisk[0].from_state == BreakerState.NORMAL
        assert evts_derisk[0].timestamp == _ts(2)
        assert eng.portfolio_state == BreakerState.DERISKED
        assert eng.portfolio_exposure_factor == pytest.approx(0.50)

        # DD = 18% -- stays DERISKED, no new event.
        evts_stay = eng.update_portfolio(_ts(3), equity=820.0)
        assert evts_stay == []
        assert eng.portfolio_state == BreakerState.DERISKED

        # DD = 26% -> HALTED fires here (DERISKED -> HALTED).
        evts_halt = eng.update_portfolio(_ts(4), equity=740.0)
        assert len(evts_halt) == 1
        assert evts_halt[0].from_state == BreakerState.DERISKED
        assert evts_halt[0].to_state == BreakerState.HALTED
        assert evts_halt[0].timestamp == _ts(4)
        assert eng.portfolio_state == BreakerState.HALTED
        assert eng.portfolio_exposure_factor == pytest.approx(0.0)

        # NAV recovers -- sticky HALT: still HALTED.
        evts_recover = eng.update_portfolio(_ts(5), equity=990.0)
        assert evts_recover == []
        assert eng.portfolio_state == BreakerState.HALTED

        # manual_reset None when not halted -- smoke test.
        eng2 = CircuitBreakerEngine(cfg)
        assert eng2.manual_reset(_ts(1)) is None

        # manual_reset clears HALT.
        reset_evt = eng.manual_reset(_ts(6), operator="risk_officer")
        assert reset_evt is not None
        assert reset_evt.from_state == BreakerState.HALTED
        assert reset_evt.to_state == BreakerState.NORMAL
        assert eng.portfolio_state == BreakerState.NORMAL
        assert eng.portfolio_exposure_factor == pytest.approx(1.0)

        # Audit log: derisk + halt + manual_reset = 3 events.
        assert len(eng.events) == 3

    def test_normal_to_halted_directly_when_skipping_derisk(self) -> None:
        """If first observation is already a 26% DD, go NORMAL -> HALTED."""
        cfg = BreakerConfig(
            portfolio_derisk_threshold=0.15,
            portfolio_halt_threshold=0.25,
            portfolio_halt_sticky=True,
        )
        eng = CircuitBreakerEngine(cfg)
        eng.update_portfolio(_ts(1), equity=1000.0)
        evts = eng.update_portfolio(_ts(2), equity=740.0)
        assert len(evts) == 1
        assert evts[0].from_state == BreakerState.NORMAL
        assert evts[0].to_state == BreakerState.HALTED


# ---------------------------------------------------------------------------
# SIM-3: Intraday loss -> HALT_NEW_ORDERS; auto-reset next session
# ---------------------------------------------------------------------------


class TestSim3IntradayDailyLoss:
    """SIM-3 -- Daily-loss halt fires and auto-resets next session."""

    def test_halt_new_orders_fires_and_resets(self) -> None:
        cfg = BreakerConfig(daily_loss_threshold=0.03)
        eng = CircuitBreakerEngine(cfg)

        # Open session at NAV = 1000.
        eng.new_session(_ts(1), session_open_nav=1000.0)
        assert eng.daily_state == BreakerState.NORMAL
        assert eng.can_place_new_orders() is True

        # Intraday: small loss 1% -- no breach.
        evts_ok = eng.update_intraday(_ts(1), current_nav=990.0)
        assert evts_ok == []
        assert eng.daily_state == BreakerState.NORMAL

        # Intraday: 3.1% loss -> HALT_NEW_ORDERS.
        evts_halt = eng.update_intraday(_ts(1), current_nav=969.0)
        assert len(evts_halt) == 1
        assert evts_halt[0].to_state == BreakerState.HALT_NEW_ORDERS
        assert evts_halt[0].breaker == BreakerType.DAILY_LOSS
        assert evts_halt[0].strategy_id is None
        assert eng.can_place_new_orders() is False

        # Further intraday decline -- already halted, no duplicate event.
        evts_extra = eng.update_intraday(_ts(1), current_nav=950.0)
        assert evts_extra == []
        assert eng.daily_state == BreakerState.HALT_NEW_ORDERS

        # Next session start: halt auto-resets.
        reset_evts = eng.new_session(_ts(2), session_open_nav=960.0)
        assert len(reset_evts) == 1
        reset_evt = reset_evts[0]
        assert reset_evt.from_state == BreakerState.HALT_NEW_ORDERS
        assert reset_evt.to_state == BreakerState.NORMAL
        assert eng.daily_state == BreakerState.NORMAL
        assert eng.can_place_new_orders() is True

    def test_no_baseline_on_first_call(self) -> None:
        """First update_intraday call without new_session sets baseline, no fire."""
        cfg = BreakerConfig(daily_loss_threshold=0.03)
        eng = CircuitBreakerEngine(cfg)
        # No new_session called -- baseline is None.
        evts = eng.update_intraday(_ts(1), current_nav=100.0)
        assert evts == []
        assert eng.daily_state == BreakerState.NORMAL

    def test_gain_intraday_never_fires(self) -> None:
        cfg = BreakerConfig(daily_loss_threshold=0.03)
        eng = CircuitBreakerEngine(cfg)
        eng.new_session(_ts(1), session_open_nav=1000.0)
        evts = eng.update_intraday(_ts(1), current_nav=1050.0)
        assert evts == []


# ---------------------------------------------------------------------------
# SIM-4: Recovery -- cooldown not elapsed -> still PAUSED; after cooldown -> NORMAL
# ---------------------------------------------------------------------------


class TestSim4RecoveryWithCooldown:
    """SIM-4 -- Strategy re-arm only fires after full cooldown."""

    def test_recovery_blocked_until_cooldown_elapsed(self) -> None:
        cfg = BreakerConfig(
            strategy_dd_threshold=0.10,
            strategy_rearm_pct=0.05,
            strategy_cooldown_sessions=2,
        )
        eng = CircuitBreakerEngine(cfg)

        # Establish peak at 100; drop to PAUSED.
        eng.update("s", _ts(1), equity=100.0)
        evts = eng.update("s", _ts(2), equity=88.0)  # DD = 12%
        assert len(evts) == 1
        assert eng.strategy_state("s") == BreakerState.PAUSED

        # Equity recovers to 97 (DD = 3% < rearm_pct=5%) -- but 0 sessions elapsed.
        evts_recover_too_early = eng.update("s", _ts(3), equity=97.0)
        assert evts_recover_too_early == []
        assert eng.strategy_state("s") == BreakerState.PAUSED

        # Session 1 starts.
        eng.new_session(_ts(4))
        # Equity still recovered (DD ~ 3%) -- only 1 session elapsed, need 2.
        evts_after_1 = eng.update("s", _ts(4), equity=97.0)
        assert evts_after_1 == []
        assert eng.strategy_state("s") == BreakerState.PAUSED

        # Session 2 starts (cooldown now 2 sessions elapsed).
        eng.new_session(_ts(5))
        # Now update with recovered equity: should fire NORMAL.
        evts_rearm = eng.update("s", _ts(5), equity=97.0)
        assert len(evts_rearm) == 1
        rearm_evt = evts_rearm[0]
        assert rearm_evt.from_state == BreakerState.PAUSED
        assert rearm_evt.to_state == BreakerState.NORMAL
        assert rearm_evt.breaker == BreakerType.STRATEGY
        assert eng.strategy_state("s") == BreakerState.NORMAL

    def test_no_rearm_if_dd_still_high_after_cooldown(self) -> None:
        """Cooldown elapsed but equity still below re-arm threshold -> PAUSED."""
        cfg = BreakerConfig(
            strategy_dd_threshold=0.10,
            strategy_rearm_pct=0.05,
            strategy_cooldown_sessions=1,
        )
        eng = CircuitBreakerEngine(cfg)
        eng.update("s", _ts(1), equity=100.0)
        eng.update("s", _ts(2), equity=85.0)  # PAUSED

        # Session passes.
        eng.new_session(_ts(3))
        # Equity at 90 -> DD = 10.0% == threshold but > rearm_pct=5% -> still PAUSED.
        evts = eng.update("s", _ts(3), equity=90.0)
        assert evts == []
        assert eng.strategy_state("s") == BreakerState.PAUSED

    def test_rearm_resets_cooldown_counter(self) -> None:
        """After successful re-arm, a new drop can PAUSED again cleanly."""
        cfg = BreakerConfig(
            strategy_dd_threshold=0.10,
            strategy_rearm_pct=0.05,
            strategy_cooldown_sessions=1,
        )
        eng = CircuitBreakerEngine(cfg)
        eng.update("s", _ts(1), equity=100.0)
        eng.update("s", _ts(2), equity=85.0)  # PAUSED (DD=15%)
        eng.new_session(_ts(3))
        # Equity recovers to 99 -> re-arms.
        evts_rearm = eng.update("s", _ts(3), equity=99.0)
        assert len(evts_rearm) == 1
        assert eng.strategy_state("s") == BreakerState.NORMAL

        # New peak at 110, then drop to 98 -> 10.9% DD -> PAUSED again.
        eng.update("s", _ts(4), equity=110.0)
        evts2 = eng.update("s", _ts(5), equity=98.0)
        assert len(evts2) == 1
        assert evts2[0].to_state == BreakerState.PAUSED


# ---------------------------------------------------------------------------
# SIM-5: No false fires on flat/grinding-up equity curve
# ---------------------------------------------------------------------------


class TestSim5NoFalseFires:
    """SIM-5 -- Flat and monotonically rising curves produce zero events."""

    def test_flat_strategy_equity(self) -> None:
        eng = CircuitBreakerEngine()
        for day in range(1, 101):
            evts = eng.update("flat", _ts(day), equity=100.0)
            assert evts == [], f"False fire on day {day}"
        assert eng.strategy_state("flat") == BreakerState.NORMAL
        assert eng.events == []

    def test_monotonically_rising_strategy_equity(self) -> None:
        eng = CircuitBreakerEngine()
        for day in range(1, 101):
            evts = eng.update("bull", _ts(day), equity=100.0 + day * 0.5)
            assert evts == [], f"False fire on day {day}"
        assert eng.strategy_state("bull") == BreakerState.NORMAL
        assert eng.events == []

    def test_flat_portfolio(self) -> None:
        eng = CircuitBreakerEngine()
        for day in range(1, 101):
            evts = eng.update_portfolio(_ts(day), equity=1000.0)
            assert evts == [], f"False fire on day {day}"
        assert eng.portfolio_state == BreakerState.NORMAL
        assert eng.events == []

    def test_rising_portfolio(self) -> None:
        eng = CircuitBreakerEngine()
        for day in range(1, 101):
            evts = eng.update_portfolio(_ts(day), equity=1000.0 + day * 2.0)
            assert evts == [], f"False fire on day {day}"
        assert eng.portfolio_state == BreakerState.NORMAL
        assert eng.events == []

    def test_flat_intraday(self) -> None:
        eng = CircuitBreakerEngine()
        eng.new_session(_ts(1), session_open_nav=1000.0)
        for tick in range(1, 51):
            evts = eng.update_intraday(_ts(1), current_nav=1000.0)
            assert evts == [], f"False fire on tick {tick}"
        assert eng.daily_state == BreakerState.NORMAL

    def test_rising_intraday(self) -> None:
        eng = CircuitBreakerEngine()
        eng.new_session(_ts(1), session_open_nav=1000.0)
        for tick in range(1, 51):
            evts = eng.update_intraday(_ts(1), current_nav=1000.0 + tick)
            assert evts == [], f"False fire on tick {tick}"
        assert eng.daily_state == BreakerState.NORMAL

    def test_small_drawdown_below_all_thresholds(self) -> None:
        """Drawdown of 2% throughout (below all default thresholds)."""
        eng = CircuitBreakerEngine()
        for day in range(1, 51):
            eng.update("s", _ts(day), equity=100.0)
        eng.update("s", _ts(51), equity=98.1)  # DD = 1.9% -- below all thresholds
        assert eng.strategy_state("s") == BreakerState.NORMAL
        assert eng.events == []


# ---------------------------------------------------------------------------
# SIM-6: Combined multi-breaker replay
# ---------------------------------------------------------------------------


class TestSim6CombinedReplay:
    """SIM-6 -- All three breakers activate in one scenario; full event audit."""

    def test_combined_breaker_sequence(self) -> None:
        cfg = BreakerConfig(
            strategy_dd_threshold=0.10,
            strategy_rearm_pct=0.05,
            strategy_cooldown_sessions=1,
            portfolio_derisk_threshold=0.15,
            portfolio_halt_threshold=0.25,
            portfolio_derisk_factor=0.50,
            portfolio_cooldown_sessions=1,
            portfolio_halt_sticky=True,
            daily_loss_threshold=0.03,
        )
        eng = CircuitBreakerEngine(cfg)

        # --- Day 1: session open, establish peaks ---
        eng.new_session(_ts(1), session_open_nav=1000.0)
        eng.update("alpha", _ts(1), equity=100.0)
        eng.update_portfolio(_ts(1), equity=1000.0)
        assert eng.events == []

        # --- Day 1 intraday: 4% loss -> daily halt ---
        evts_d1_intra = eng.update_intraday(_ts(1), current_nav=960.0)
        assert len(evts_d1_intra) == 1
        assert evts_d1_intra[0].to_state == BreakerState.HALT_NEW_ORDERS
        assert eng.can_place_new_orders() is False

        # --- Day 2: new session -> daily resets; strategy drops 11% -> PAUSED ---
        eng.new_session(_ts(2), session_open_nav=980.0)
        assert eng.daily_state == BreakerState.NORMAL
        assert eng.can_place_new_orders() is True

        evts_strat = eng.update("alpha", _ts(2), equity=89.0)  # DD = 11%
        assert len(evts_strat) == 1
        assert evts_strat[0].to_state == BreakerState.PAUSED
        assert eng.strategy_state("alpha") == BreakerState.PAUSED

        # --- Day 2: portfolio drops 17% -> DERISKED ---
        evts_port = eng.update_portfolio(_ts(2), equity=830.0)
        assert len(evts_port) == 1
        assert evts_port[0].to_state == BreakerState.DERISKED
        assert eng.portfolio_state == BreakerState.DERISKED
        assert eng.portfolio_exposure_factor == pytest.approx(0.50)

        # --- Day 3: session starts; portfolio drops to 26% -> HALTED ---
        eng.new_session(_ts(3), session_open_nav=820.0)
        evts_halt = eng.update_portfolio(_ts(3), equity=740.0)  # DD = 26%
        assert len(evts_halt) == 1
        assert evts_halt[0].from_state == BreakerState.DERISKED
        assert evts_halt[0].to_state == BreakerState.HALTED
        assert eng.portfolio_state == BreakerState.HALTED
        assert eng.portfolio_exposure_factor == pytest.approx(0.0)

        # --- Day 3 intraday: daily halt fires again ---
        evts_d3_intra = eng.update_intraday(_ts(3), current_nav=795.0)
        assert len(evts_d3_intra) == 1
        assert evts_d3_intra[0].to_state == BreakerState.HALT_NEW_ORDERS

        # --- Day 4: session start resets daily halt; strategy recovers ---
        eng.new_session(_ts(4), session_open_nav=800.0)
        assert eng.daily_state == BreakerState.NORMAL

        # Strategy equity recovers to 96 (DD = 4% < rearm_pct=5%); 1 session elapsed.
        evts_rearm = eng.update("alpha", _ts(4), equity=96.0)
        assert len(evts_rearm) == 1
        assert evts_rearm[0].from_state == BreakerState.PAUSED
        assert evts_rearm[0].to_state == BreakerState.NORMAL
        assert eng.strategy_state("alpha") == BreakerState.NORMAL

        # Portfolio still HALTED (sticky).
        assert eng.portfolio_state == BreakerState.HALTED

        # --- Manual reset clears portfolio HALT ---
        reset = eng.manual_reset(_ts(4), operator="risk_team")
        assert reset is not None
        assert reset.to_state == BreakerState.NORMAL
        assert eng.portfolio_state == BreakerState.NORMAL

        # --- Verify full audit log ---
        # Expected events in order:
        # 1. daily halt day 1
        # 2. daily reset day 2 (new_session)
        # 3. strategy PAUSED day 2
        # 4. portfolio DERISKED day 2
        # 5. portfolio HALTED day 3
        # 6. daily halt day 3
        # 7. daily reset day 4 (new_session)
        # 8. strategy NORMAL (re-arm) day 4
        # 9. portfolio NORMAL (manual_reset) day 4
        event_transitions = [
            (e.from_state, e.to_state, e.breaker) for e in eng.events
        ]
        assert event_transitions[0] == (
            BreakerState.NORMAL, BreakerState.HALT_NEW_ORDERS, BreakerType.DAILY_LOSS
        )
        assert event_transitions[1] == (
            BreakerState.HALT_NEW_ORDERS, BreakerState.NORMAL, BreakerType.DAILY_LOSS
        )
        assert event_transitions[2] == (
            BreakerState.NORMAL, BreakerState.PAUSED, BreakerType.STRATEGY
        )
        assert event_transitions[3] == (
            BreakerState.NORMAL, BreakerState.DERISKED, BreakerType.PORTFOLIO
        )
        assert event_transitions[4] == (
            BreakerState.DERISKED, BreakerState.HALTED, BreakerType.PORTFOLIO
        )
        assert event_transitions[5] == (
            BreakerState.NORMAL, BreakerState.HALT_NEW_ORDERS, BreakerType.DAILY_LOSS
        )
        assert event_transitions[6] == (
            BreakerState.HALT_NEW_ORDERS, BreakerState.NORMAL, BreakerType.DAILY_LOSS
        )
        assert event_transitions[7] == (
            BreakerState.PAUSED, BreakerState.NORMAL, BreakerType.STRATEGY
        )
        assert event_transitions[8] == (
            BreakerState.HALTED, BreakerState.NORMAL, BreakerType.PORTFOLIO
        )
        assert len(eng.events) == 9


# ---------------------------------------------------------------------------
# Additional edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_multiple_strategies_independent(self) -> None:
        """Two strategies with separate drawdown paths stay independent."""
        cfg = BreakerConfig(
            strategy_dd_threshold=0.10,
            strategy_cooldown_sessions=0,
        )
        eng = CircuitBreakerEngine(cfg)
        eng.update("A", _ts(1), equity=100.0)
        eng.update("B", _ts(1), equity=100.0)

        # A drops 12% -> PAUSED.
        eng.update("A", _ts(2), equity=88.0)
        assert eng.strategy_state("A") == BreakerState.PAUSED

        # B stays flat.
        eng.update("B", _ts(2), equity=100.0)
        assert eng.strategy_state("B") == BreakerState.NORMAL

    def test_portfolio_high_watermark_tracks_correctly(self) -> None:
        """HWM updates on new highs; drawdown computed from highest seen."""
        eng = CircuitBreakerEngine()
        eng.update_portfolio(_ts(1), equity=100.0)
        eng.update_portfolio(_ts(2), equity=120.0)  # new HWM
        # DD from 120 to 102 = 15% -- triggers derisk.
        evts = eng.update_portfolio(_ts(3), equity=102.0 - 0.01)
        assert len(evts) == 1
        assert evts[0].to_state == BreakerState.DERISKED

    def test_strategy_hwm_updates_after_recovery(self) -> None:
        """After re-arm, HWM can be set to new high and breaker fires again."""
        cfg = BreakerConfig(
            strategy_dd_threshold=0.10,
            strategy_rearm_pct=0.05,
            strategy_cooldown_sessions=0,
        )
        eng = CircuitBreakerEngine(cfg)
        eng.update("s", _ts(1), equity=100.0)
        eng.update("s", _ts(2), equity=88.0)  # PAUSED
        # Recover.
        eng.update("s", _ts(3), equity=97.0)  # NORMAL (0 sessions cooldown)
        assert eng.strategy_state("s") == BreakerState.NORMAL

        # Push to new high 120; drop to 107 (DD = 10.8% from 120) -> PAUSED again.
        eng.update("s", _ts(4), equity=120.0)
        evts = eng.update("s", _ts(5), equity=107.0)
        assert len(evts) == 1
        assert evts[0].to_state == BreakerState.PAUSED

    def test_new_session_without_nav_does_not_change_intraday_baseline(self) -> None:
        """new_session without session_open_nav keeps previous baseline."""
        eng = CircuitBreakerEngine(BreakerConfig(daily_loss_threshold=0.03))
        eng.new_session(_ts(1), session_open_nav=1000.0)
        # Call new_session without nav -- baseline unchanged.
        eng.new_session(_ts(2))
        # Intraday loss vs 1000 baseline.
        evts = eng.update_intraday(_ts(2), current_nav=960.0)
        assert len(evts) == 1
        assert evts[0].to_state == BreakerState.HALT_NEW_ORDERS

    def test_portfolio_non_sticky_auto_recovers(self) -> None:
        """With portfolio_halt_sticky=False, HALTED recovers automatically."""
        cfg = BreakerConfig(
            portfolio_derisk_threshold=0.15,
            portfolio_halt_threshold=0.25,
            portfolio_rearm_pct=0.05,
            portfolio_cooldown_sessions=1,
            portfolio_halt_sticky=False,
        )
        eng = CircuitBreakerEngine(cfg)
        eng.update_portfolio(_ts(1), equity=1000.0)
        eng.update_portfolio(_ts(2), equity=740.0)  # DD = 26% -> HALTED
        assert eng.portfolio_state == BreakerState.HALTED

        # Equity recovers to 97 (DD = 3%); need 1 session first.
        evts_no_sess = eng.update_portfolio(_ts(3), equity=970.0)
        assert evts_no_sess == []
        assert eng.portfolio_state == BreakerState.HALTED

        # Session advances cooldown counter.
        eng.new_session(_ts(4))
        evts_recover = eng.update_portfolio(_ts(4), equity=970.0)
        assert len(evts_recover) == 1
        assert evts_recover[0].from_state == BreakerState.HALTED
        assert evts_recover[0].to_state == BreakerState.NORMAL

    def test_manual_reset_returns_none_when_not_halted(self) -> None:
        eng = CircuitBreakerEngine()
        assert eng.manual_reset(_ts(1)) is None

    def test_derisked_recovery_requires_both_conditions(self) -> None:
        """Verify that recovery from DERISKED needs BOTH drawdown < rearm AND cooldown."""
        cfg = BreakerConfig(
            portfolio_derisk_threshold=0.15,
            portfolio_halt_threshold=0.25,
            portfolio_rearm_pct=0.05,
            portfolio_cooldown_sessions=2,
            portfolio_halt_sticky=True,
        )
        eng = CircuitBreakerEngine(cfg)
        eng.update_portfolio(_ts(1), equity=1000.0)
        eng.update_portfolio(_ts(2), equity=840.0)  # DD=16% -> DERISKED
        assert eng.portfolio_state == BreakerState.DERISKED

        # Equity recovers but 0 sessions elapsed.
        evts = eng.update_portfolio(_ts(3), equity=980.0)  # DD=2%
        assert evts == []

        # 1 session elapsed (need 2).
        eng.new_session(_ts(4))
        evts = eng.update_portfolio(_ts(4), equity=980.0)
        assert evts == []

        # 2 sessions elapsed -- recovery fires.
        eng.new_session(_ts(5))
        evts = eng.update_portfolio(_ts(5), equity=980.0)
        assert len(evts) == 1
        assert evts[0].to_state == BreakerState.NORMAL

    def test_new_session_on_already_normal_daily_emits_no_event(self) -> None:
        eng = CircuitBreakerEngine()
        evts = eng.new_session(_ts(1), session_open_nav=1000.0)
        assert evts == []

    def test_event_message_is_ascii_only(self) -> None:
        """All event messages must be ASCII (terminal-portable safety)."""
        cfg = BreakerConfig(
            strategy_dd_threshold=0.10,
            portfolio_derisk_threshold=0.15,
            portfolio_halt_threshold=0.25,
            daily_loss_threshold=0.03,
            strategy_cooldown_sessions=0,
            portfolio_cooldown_sessions=0,
            portfolio_halt_sticky=True,
        )
        eng = CircuitBreakerEngine(cfg)
        eng.new_session(_ts(1), session_open_nav=1000.0)
        eng.update("s", _ts(1), equity=100.0)
        eng.update_portfolio(_ts(1), equity=1000.0)
        # Strategy pause
        eng.update("s", _ts(2), equity=85.0)
        # Portfolio derisk
        eng.update_portfolio(_ts(2), equity=840.0)
        # Portfolio halt
        eng.update_portfolio(_ts(3), equity=730.0)
        # Daily loss
        eng.update_intraday(_ts(3), current_nav=965.0)
        # Manual reset
        eng.manual_reset(_ts(4))

        for evt in eng.events:
            try:
                evt.message.encode("ascii")
            except UnicodeEncodeError as exc:
                raise AssertionError(
                    f"Non-ASCII character in event message: {evt.message!r}"
                ) from exc
