"""Tests for core_trading.execution.smart_order_router (Phase 9.2).

Coverage targets
----------------
Existing router behaviour
* VenueConfig / VenueStats construction defaults.
* SmartOrderRouter.route_order -- selects highest-scoring eligible venue.
* eligibility filters -- disabled, unsupported instrument, min_fill_rate,
  max_latency, max_venues_to_evaluate cap.
* RoutingError raised when no eligible venue exists.
* update_venue_stats -- counters, derived metrics, unknown venue warning.
* get_venue_stats / get_all_stats / add_venue (dup error) / remove_venue.
* _score_venue legacy stats path (>=5 orders) and reason strings.

Phase 9.2 analytics + rationale
* AnalyticsConfig validation.
* VenueAnalytics smoothed fill probability (known Laplace values).
* latency rolling mean + percentile, window eviction.
* markout sign convention (positive = adverse) via record_markout and
  record_fill_markout (buy/sell).
* record_* validation errors.
* snapshot frozen + field correctness; to_venue_stats fold-in.
* router consumes analytics in scoring (fill prob + latency).
* decision-log rationale completeness, bounded size, decisions_to_frame export.
"""
from __future__ import annotations

import math
from dataclasses import FrozenInstanceError
from typing import Any

import pandas as pd
import pytest

from core_trading.execution.smart_order_router import (
    AnalyticsConfig,
    FillResult,
    RoutingConfig,
    RoutingDecision,
    RoutingError,
    RoutingRationale,
    SmartOrderRouter,
    VenueAnalytics,
    VenueAnalyticsSnapshot,
    VenueConfig,
    VenueScoreRecord,
    VenueStats,
)

_EPS = 1e-9


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


class _NullEventBus:
    """Minimal event-bus stand-in (the router never publishes in this path)."""


def _venue(
    venue_id: str = "V1",
    *,
    name: str | None = None,
    venue_type: str = "exchange",
    instruments: set[str] | None = None,
    commission_rate: float = 0.002,
    latency_ms: float = 10.0,
    fill_rate: float = 0.9,
    enabled: bool = True,
) -> VenueConfig:
    return VenueConfig(
        venue_id=venue_id,
        name=name or venue_id,
        venue_type=venue_type,
        supported_instruments=instruments if instruments is not None else {"AAPL"},
        commission_rate=commission_rate,
        latency_ms=latency_ms,
        fill_rate=fill_rate,
        enabled=enabled,
    )


def _order(
    instrument: str = "AAPL",
    quantity: float = 100.0,
    side: str = "buy",
    **extra: Any,
) -> dict[str, Any]:
    order: dict[str, Any] = {
        "instrument": instrument,
        "quantity": quantity,
        "side": side,
        "order_type": "limit",
    }
    order.update(extra)
    return order


def _router(*venues: VenueConfig, **kwargs: Any) -> SmartOrderRouter:
    return SmartOrderRouter(list(venues), _NullEventBus(), **kwargs)


# ---------------------------------------------------------------------------
# Data class defaults
# ---------------------------------------------------------------------------


class TestDataClasses:
    def test_venue_config_defaults(self) -> None:
        v = _venue()
        assert v.enabled is True
        assert v.supported_instruments == {"AAPL"}

    def test_venue_stats_defaults(self) -> None:
        s = VenueStats(venue_id="V1")
        assert s.total_orders == 0
        assert s.filled_orders == 0
        assert s.fill_rate == 0.0
        assert s.avg_latency_ms == 0.0
        assert s.last_fill_time is None


# ---------------------------------------------------------------------------
# Router construction + analytics wiring
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_initializes_stats_and_analytics(self) -> None:
        r = _router(_venue("A"), _venue("B"))
        assert r.get_venue_stats("A") is not None
        assert r.get_venue_analytics("A") is not None
        assert r.get_venue_analytics("B") is not None
        assert set(r.get_all_stats().keys()) == {"A", "B"}

    def test_decision_log_size_validation(self) -> None:
        with pytest.raises(ValueError):
            _router(_venue("A"), decision_log_size=0)

    def test_custom_analytics_config_applied(self) -> None:
        cfg = AnalyticsConfig(latency_percentile=50.0)
        r = _router(_venue("A"), analytics_config=cfg)
        analytics = r.get_venue_analytics("A")
        assert analytics is not None
        assert analytics.config.latency_percentile == 50.0


# ---------------------------------------------------------------------------
# Routing logic (existing behaviour)
# ---------------------------------------------------------------------------


class TestRouting:
    async def test_routes_to_best_venue(self) -> None:
        # Cheap + fast + high fill should beat expensive + slow.
        good = _venue("GOOD", commission_rate=0.001, latency_ms=5.0, fill_rate=0.99)
        bad = _venue("BAD", commission_rate=0.009, latency_ms=400.0, fill_rate=0.6)
        r = _router(good, bad)
        decision = await r.route_order(_order())
        assert isinstance(decision, RoutingDecision)
        assert decision.venue.venue_id == "GOOD"
        assert decision.estimated_fill_rate == pytest.approx(0.99)

    async def test_no_eligible_venue_raises(self) -> None:
        r = _router(_venue("A", instruments={"MSFT"}))
        with pytest.raises(RoutingError):
            await r.route_order(_order(instrument="AAPL"))

    async def test_disabled_venue_excluded(self) -> None:
        r = _router(_venue("OFF", enabled=False))
        with pytest.raises(RoutingError):
            await r.route_order(_order())

    async def test_min_fill_rate_filter(self) -> None:
        cfg = RoutingConfig(min_fill_rate=0.8)
        r = _router(_venue("LOW", fill_rate=0.6), config=cfg)
        with pytest.raises(RoutingError):
            await r.route_order(_order())

    async def test_max_latency_filter(self) -> None:
        cfg = RoutingConfig(max_latency_ms=100.0)
        r = _router(_venue("SLOW", latency_ms=200.0), config=cfg)
        with pytest.raises(RoutingError):
            await r.route_order(_order())

    async def test_max_venues_to_evaluate_cap(self) -> None:
        cfg = RoutingConfig(max_venues_to_evaluate=2)
        venues = [_venue(f"V{i}") for i in range(5)]
        r = _router(*venues, config=cfg)
        scores = await r._evaluate_venues(_order())
        assert len(scores) == 2

    async def test_select_optimal_empty_raises(self) -> None:
        r = _router(_venue("A"))
        with pytest.raises(RoutingError):
            r._select_optimal([])


# ---------------------------------------------------------------------------
# Scoring / reason strings (existing)
# ---------------------------------------------------------------------------


class TestScoring:
    def test_reason_string_buckets(self) -> None:
        r = _router(_venue("A", fill_rate=0.95, latency_ms=3.0, commission_rate=0.002))
        score = r._score_venue(r._venues["A"], 100.0)
        assert "high fill probability" in score.selection_reason
        assert "very low latency" in score.selection_reason
        assert "low cost" in score.selection_reason

    def test_reason_string_moderate_buckets(self) -> None:
        r = _router(_venue("A", fill_rate=0.75, latency_ms=30.0, commission_rate=0.005))
        score = r._score_venue(r._venues["A"], 100.0)
        assert "moderate fill probability" in score.selection_reason
        assert "low latency" in score.selection_reason
        assert "moderate cost" in score.selection_reason

    def test_reason_string_low_buckets(self) -> None:
        r = _router(_venue("A", fill_rate=0.4, latency_ms=200.0, commission_rate=0.009))
        score = r._score_venue(r._venues["A"], 100.0)
        assert "low fill probability" in score.selection_reason
        assert "higher latency" in score.selection_reason
        assert "higher cost" in score.selection_reason

    def test_zero_quantity_cost_norm(self) -> None:
        r = _router(_venue("A"))
        score = r._score_venue(r._venues["A"], 0.0)
        # No division by zero; estimated cost is zero.
        assert score.estimated_cost == 0.0
        assert math.isfinite(score.score)


# ---------------------------------------------------------------------------
# update_venue_stats (existing) -- also feeds analytics
# ---------------------------------------------------------------------------


class TestUpdateVenueStats:
    def _fill(self, success: bool, latency: float = 20.0) -> FillResult:
        return FillResult(
            venue_id="A",
            success=success,
            fill_price=100.0,
            fill_quantity=10.0,
            latency_ms=latency,
            commission=0.5,
        )

    def test_successful_fill_updates_counters(self) -> None:
        r = _router(_venue("A"))
        r.update_venue_stats("A", self._fill(True, latency=30.0))
        stats = r.get_venue_stats("A")
        assert stats is not None
        assert stats.total_orders == 1
        assert stats.filled_orders == 1
        assert stats.fill_rate == pytest.approx(1.0)
        assert stats.avg_latency_ms == pytest.approx(30.0)
        assert stats.last_fill_time is not None

    def test_failed_fill_counts_order_only(self) -> None:
        r = _router(_venue("A"))
        r.update_venue_stats("A", self._fill(False))
        stats = r.get_venue_stats("A")
        assert stats is not None
        assert stats.total_orders == 1
        assert stats.filled_orders == 0
        assert stats.fill_rate == pytest.approx(0.0)

    def test_unknown_venue_is_noop(self) -> None:
        r = _router(_venue("A"))
        r.update_venue_stats("ZZZ", self._fill(True))  # no raise
        assert r.get_venue_stats("ZZZ") is None

    def test_mirrors_into_analytics(self) -> None:
        r = _router(_venue("A"))
        r.update_venue_stats("A", self._fill(True, latency=40.0))
        r.update_venue_stats("A", self._fill(False))
        analytics = r.get_venue_analytics("A")
        assert analytics is not None
        snap = analytics.snapshot()
        assert snap.attempts == 2
        assert snap.fills == 1
        assert snap.latency_count == 1
        assert snap.mean_latency_ms == pytest.approx(40.0)


# ---------------------------------------------------------------------------
# add_venue / remove_venue
# ---------------------------------------------------------------------------


class TestVenueManagement:
    def test_add_venue(self) -> None:
        r = _router(_venue("A"))
        r.add_venue(_venue("B"))
        assert r.get_venue_stats("B") is not None
        assert r.get_venue_analytics("B") is not None

    def test_add_duplicate_raises(self) -> None:
        r = _router(_venue("A"))
        with pytest.raises(ValueError):
            r.add_venue(_venue("A"))

    def test_remove_venue(self) -> None:
        r = _router(_venue("A"))
        r.remove_venue("A")
        assert r.get_venue_stats("A") is None
        assert r.get_venue_analytics("A") is None

    def test_remove_unknown_is_noop(self) -> None:
        r = _router(_venue("A"))
        r.remove_venue("ZZZ")  # no raise


# ---------------------------------------------------------------------------
# AnalyticsConfig validation
# ---------------------------------------------------------------------------


class TestAnalyticsConfig:
    def test_defaults(self) -> None:
        cfg = AnalyticsConfig()
        assert cfg.fill_prior_alpha == 1.0
        assert cfg.fill_prior_beta == 1.0
        assert cfg.latency_percentile == 95.0

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"fill_prior_alpha": -1.0},
            {"fill_prior_beta": -1.0},
            {"latency_window": 0},
            {"latency_percentile": -1.0},
            {"latency_percentile": 101.0},
            {"markout_window": 0},
        ],
    )
    def test_invalid_raises(self, kwargs: dict[str, Any]) -> None:
        with pytest.raises(ValueError):
            AnalyticsConfig(**kwargs)


# ---------------------------------------------------------------------------
# VenueAnalytics: fill probability (Laplace smoothing)
# ---------------------------------------------------------------------------


class TestFillProbability:
    def test_empty_prior_is_half(self) -> None:
        a = VenueAnalytics("V")
        assert a.fill_probability() == pytest.approx(0.5)

    def test_single_lucky_fill_does_not_dominate(self) -> None:
        a = VenueAnalytics("V")
        a.record_attempt(filled=True)
        # (1 + 1) / (1 + 1 + 1) = 2/3, not 1.0
        assert a.fill_probability() == pytest.approx(2.0 / 3.0)

    def test_known_smoothed_value(self) -> None:
        a = VenueAnalytics("V")
        for _ in range(8):
            a.record_attempt(filled=True)
        for _ in range(2):
            a.record_attempt(filled=False)
        # (8 + 1) / (10 + 2) = 9/12 = 0.75
        assert a.fill_probability() == pytest.approx(0.75)

    def test_custom_prior(self) -> None:
        cfg = AnalyticsConfig(fill_prior_alpha=0.0, fill_prior_beta=0.0)
        a = VenueAnalytics("V", cfg)
        # No prior, no data -> denom 0 -> 0.0 guard
        assert a.fill_probability() == pytest.approx(0.0)
        a.record_attempt(filled=True)
        assert a.fill_probability() == pytest.approx(1.0)

    def test_record_fill_count_attempt(self) -> None:
        a = VenueAnalytics("V")
        a.record_fill(count_attempt=True)
        snap = a.snapshot()
        assert snap.attempts == 1
        assert snap.fills == 1

    def test_record_fill_without_attempt(self) -> None:
        a = VenueAnalytics("V")
        a.record_attempt()
        a.record_fill()
        snap = a.snapshot()
        assert snap.attempts == 1
        assert snap.fills == 1

    def test_raw_fill_rate(self) -> None:
        a = VenueAnalytics("V")
        a.record_attempt(filled=True)
        a.record_attempt(filled=False)
        assert a.snapshot().raw_fill_rate == pytest.approx(0.5)

    def test_raw_fill_rate_no_attempts(self) -> None:
        assert VenueAnalytics("V").snapshot().raw_fill_rate == 0.0


# ---------------------------------------------------------------------------
# VenueAnalytics: latency
# ---------------------------------------------------------------------------


class TestLatency:
    def test_empty_latency_is_zero(self) -> None:
        a = VenueAnalytics("V")
        assert a.mean_latency_ms() == 0.0
        assert a.latency_percentile_ms() == 0.0

    def test_mean_latency(self) -> None:
        a = VenueAnalytics("V")
        for v in (10.0, 20.0, 30.0):
            a.record_latency(v)
        assert a.mean_latency_ms() == pytest.approx(20.0)

    def test_percentile_known_value(self) -> None:
        cfg = AnalyticsConfig(latency_percentile=50.0)
        a = VenueAnalytics("V", cfg)
        for v in (10.0, 20.0, 30.0):
            a.record_latency(v)
        # median of {10,20,30} = 20
        assert a.latency_percentile_ms() == pytest.approx(20.0)

    def test_percentile_p95(self) -> None:
        a = VenueAnalytics("V")  # default p95
        for v in (10.0, 20.0, 30.0, 100.0):
            a.record_latency(v)
        # numpy linear-interp p95 over [10,20,30,100]
        import numpy as np

        expected = float(np.percentile([10.0, 20.0, 30.0, 100.0], 95.0))
        assert a.latency_percentile_ms() == pytest.approx(expected)

    def test_window_eviction(self) -> None:
        cfg = AnalyticsConfig(latency_window=3)
        a = VenueAnalytics("V", cfg)
        for v in (1.0, 2.0, 3.0, 4.0):
            a.record_latency(v)
        # only last 3 retained: mean of {2,3,4} = 3
        assert a.snapshot().latency_count == 3
        assert a.mean_latency_ms() == pytest.approx(3.0)

    def test_negative_latency_raises(self) -> None:
        with pytest.raises(ValueError):
            VenueAnalytics("V").record_latency(-1.0)

    def test_nonfinite_latency_raises(self) -> None:
        with pytest.raises(ValueError):
            VenueAnalytics("V").record_latency(float("inf"))


# ---------------------------------------------------------------------------
# VenueAnalytics: markout sign convention
# ---------------------------------------------------------------------------


class TestMarkout:
    def test_empty_markout_is_zero(self) -> None:
        assert VenueAnalytics("V").mean_markout() == 0.0

    def test_record_signed_markout(self) -> None:
        a = VenueAnalytics("V")
        a.record_markout(2.0)
        a.record_markout(4.0)
        assert a.mean_markout() == pytest.approx(3.0)

    def test_buy_price_up_is_favourable_negative(self) -> None:
        a = VenueAnalytics("V")
        m = a.record_fill_markout(side="buy", reference_price=100.0, future_price=101.0)
        assert m == pytest.approx(-1.0)  # favourable -> negative
        assert a.mean_markout() == pytest.approx(-1.0)

    def test_buy_price_down_is_adverse_positive(self) -> None:
        a = VenueAnalytics("V")
        m = a.record_fill_markout(side="buy", reference_price=100.0, future_price=99.0)
        assert m == pytest.approx(1.0)  # adverse -> positive

    def test_sell_price_up_is_adverse_positive(self) -> None:
        a = VenueAnalytics("V")
        m = a.record_fill_markout(side="sell", reference_price=100.0, future_price=101.0)
        assert m == pytest.approx(1.0)

    def test_sell_price_down_is_favourable_negative(self) -> None:
        a = VenueAnalytics("V")
        m = a.record_fill_markout(side="sell", reference_price=100.0, future_price=99.0)
        assert m == pytest.approx(-1.0)

    @pytest.mark.parametrize("side", ["b", "BUY", "Sell", "s"])
    def test_side_aliases(self, side: str) -> None:
        a = VenueAnalytics("V")
        a.record_fill_markout(side=side, reference_price=100.0, future_price=100.5)

    def test_bad_side_raises(self) -> None:
        with pytest.raises(ValueError):
            VenueAnalytics("V").record_fill_markout(
                side="hold", reference_price=1.0, future_price=2.0
            )

    def test_nonfinite_markout_raises(self) -> None:
        with pytest.raises(ValueError):
            VenueAnalytics("V").record_markout(float("nan"))

    def test_nonfinite_price_raises(self) -> None:
        with pytest.raises(ValueError):
            VenueAnalytics("V").record_fill_markout(
                side="buy", reference_price=float("inf"), future_price=1.0
            )

    def test_markout_window_eviction(self) -> None:
        cfg = AnalyticsConfig(markout_window=2)
        a = VenueAnalytics("V", cfg)
        a.record_markout(1.0)
        a.record_markout(2.0)
        a.record_markout(3.0)
        assert a.snapshot().markout_count == 2
        assert a.mean_markout() == pytest.approx(2.5)


# ---------------------------------------------------------------------------
# VenueAnalytics: snapshot + to_venue_stats
# ---------------------------------------------------------------------------


class TestSnapshot:
    def test_snapshot_is_frozen(self) -> None:
        snap = VenueAnalytics("V").snapshot()
        assert isinstance(snap, VenueAnalyticsSnapshot)
        with pytest.raises(FrozenInstanceError):
            snap.attempts = 5  # type: ignore[misc]

    def test_venue_id_and_config_properties(self) -> None:
        cfg = AnalyticsConfig(latency_percentile=90.0)
        a = VenueAnalytics("VX", cfg)
        assert a.venue_id == "VX"
        assert a.config is cfg

    def test_snapshot_fields(self) -> None:
        a = VenueAnalytics("V")
        a.record_attempt(filled=True)
        a.record_latency(15.0)
        a.record_markout(2.0)
        snap = a.snapshot()
        assert snap.venue_id == "V"
        assert snap.attempts == 1
        assert snap.fills == 1
        assert snap.latency_count == 1
        assert snap.markout_count == 1
        assert snap.latency_percentile_q == 95.0
        assert snap.mean_markout == pytest.approx(2.0)

    def test_to_venue_stats_fresh(self) -> None:
        a = VenueAnalytics("V")
        for _ in range(8):
            a.record_attempt(filled=True)
        for _ in range(2):
            a.record_attempt(filled=False)
        a.record_latency(25.0)
        stats = a.to_venue_stats()
        assert isinstance(stats, VenueStats)
        assert stats.venue_id == "V"
        assert stats.total_orders == 10
        assert stats.filled_orders == 8
        assert stats.fill_rate == pytest.approx(0.75)  # smoothed
        assert stats.avg_latency_ms == pytest.approx(25.0)

    def test_to_venue_stats_preserves_base_commission(self) -> None:
        a = VenueAnalytics("V")
        a.record_attempt(filled=True)
        base = VenueStats(venue_id="V", total_commission=42.0)
        out = a.to_venue_stats(base)
        assert out is base
        assert out.total_commission == 42.0  # preserved
        assert out.total_orders == 1  # overwritten


# ---------------------------------------------------------------------------
# Router consumes analytics in scoring
# ---------------------------------------------------------------------------


class TestAnalyticsScoring:
    def test_scoring_uses_analytics_fill_prob(self) -> None:
        # Static config fill_rate is 0.9 but analytics drives it down.
        r = _router(_venue("A", fill_rate=0.9))
        analytics = r.get_venue_analytics("A")
        assert analytics is not None
        for _ in range(20):
            analytics.record_attempt(filled=False)
        score = r._score_venue(r._venues["A"], 100.0)
        # smoothed = 1/22, well below the static 0.9
        assert score.fill_probability < 0.1

    def test_scoring_uses_analytics_latency(self) -> None:
        r = _router(_venue("A", latency_ms=10.0))
        analytics = r.get_venue_analytics("A")
        assert analytics is not None
        analytics.record_attempt(filled=True)
        analytics.record_latency(300.0)
        score = r._score_venue(r._venues["A"], 100.0)
        assert score.avg_latency_ms == pytest.approx(300.0)

    def test_no_analytics_falls_back_to_static(self) -> None:
        r = _router(_venue("A", fill_rate=0.85))
        score = r._score_venue(r._venues["A"], 100.0)
        assert score.fill_probability == pytest.approx(0.85)

    def test_legacy_stats_path_when_no_analytics_for_venue(self) -> None:
        # Drive the legacy >=5 orders branch by removing the analytics entry.
        r = _router(_venue("A", fill_rate=0.9))
        r._analytics.pop("A")
        stats = r.get_venue_stats("A")
        assert stats is not None
        stats.total_orders = 10
        stats.filled_orders = 6
        stats.fill_rate = 0.6
        stats.avg_latency_ms = 50.0
        score = r._score_venue(r._venues["A"], 100.0)
        assert score.fill_probability == pytest.approx(0.6)
        assert score.avg_latency_ms == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# Decision log + rationale + DataFrame export
# ---------------------------------------------------------------------------


class TestDecisionLog:
    async def test_rationale_recorded(self) -> None:
        good = _venue("GOOD", commission_rate=0.001, latency_ms=5.0, fill_rate=0.99)
        bad = _venue("BAD", commission_rate=0.008, latency_ms=300.0, fill_rate=0.6)
        r = _router(good, bad)
        await r.route_order(_order(order_ref="O-1"))
        log = r.decision_log
        assert len(log) == 1
        rationale = log[0]
        assert isinstance(rationale, RoutingRationale)
        assert rationale.order_ref == "O-1"
        assert rationale.instrument == "AAPL"
        assert rationale.side == "buy"
        assert rationale.quantity == pytest.approx(100.0)
        assert rationale.chosen_venue_id == "GOOD"
        # one record per evaluated venue
        assert len(rationale.venue_scores) == 2
        chosen = [s for s in rationale.venue_scores if s.chosen]
        assert len(chosen) == 1
        assert chosen[0].venue_id == "GOOD"

    async def test_rationale_record_fields(self) -> None:
        r = _router(_venue("A"))
        analytics = r.get_venue_analytics("A")
        assert analytics is not None
        analytics.record_markout(3.0)
        await r.route_order(_order())
        rec = r.decision_log[0].venue_scores[0]
        assert isinstance(rec, VenueScoreRecord)
        assert rec.venue_id == "A"
        assert rec.mean_markout == pytest.approx(3.0)
        assert math.isfinite(rec.score)
        assert math.isfinite(rec.fill_probability)

    async def test_order_ref_falls_back_to_order_id(self) -> None:
        r = _router(_venue("A"))
        await r.route_order(_order(order_id="OID-9"))
        assert r.decision_log[0].order_ref == "OID-9"

    async def test_order_ref_default_empty(self) -> None:
        r = _router(_venue("A"))
        await r.route_order(_order())
        assert r.decision_log[0].order_ref == ""

    async def test_decision_log_bounded(self) -> None:
        r = _router(_venue("A"), decision_log_size=3)
        for i in range(5):
            await r.route_order(_order(order_ref=f"O-{i}"))
        log = r.decision_log
        assert len(log) == 3
        # oldest evicted; newest retained (oldest-first ordering)
        assert [x.order_ref for x in log] == ["O-2", "O-3", "O-4"]

    async def test_decisions_to_frame(self) -> None:
        good = _venue("GOOD", commission_rate=0.001, latency_ms=5.0, fill_rate=0.99)
        bad = _venue("BAD", commission_rate=0.008, latency_ms=300.0, fill_rate=0.6)
        r = _router(good, bad)
        await r.route_order(_order(order_ref="O-1"))
        await r.route_order(_order(order_ref="O-2"))
        df = r.decisions_to_frame()
        assert isinstance(df, pd.DataFrame)
        # 2 decisions x 2 venues = 4 rows
        assert len(df) == 4
        expected_cols = {
            "timestamp",
            "order_ref",
            "instrument",
            "side",
            "quantity",
            "chosen_venue_id",
            "chosen_score",
            "venue_id",
            "score",
            "fill_probability",
            "estimated_cost",
            "avg_latency_ms",
            "mean_markout",
            "chosen",
        }
        assert set(df.columns) == expected_cols
        # exactly one chosen row per decision
        assert int(df["chosen"].sum()) == 2
        assert set(df["order_ref"]) == {"O-1", "O-2"}

    def test_decisions_to_frame_empty(self) -> None:
        r = _router(_venue("A"))
        df = r.decisions_to_frame()
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0
        assert "venue_id" in df.columns


# ---------------------------------------------------------------------------
# router.record_markout convenience wrapper
# ---------------------------------------------------------------------------


class TestRouterRecordMarkout:
    def test_record_markout_routes_to_analytics(self) -> None:
        r = _router(_venue("A"))
        m = r.record_markout(
            "A", side="sell", reference_price=100.0, future_price=101.0
        )
        assert m == pytest.approx(1.0)
        analytics = r.get_venue_analytics("A")
        assert analytics is not None
        assert analytics.mean_markout() == pytest.approx(1.0)

    def test_record_markout_unknown_venue_returns_none(self) -> None:
        r = _router(_venue("A"))
        assert (
            r.record_markout(
                "ZZZ", side="buy", reference_price=1.0, future_price=2.0
            )
            is None
        )
