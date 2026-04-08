"""Comprehensive unit tests for the SmartOrderRouter.

Covers:
- Initialization with venues and configuration
- Order routing and venue selection
- Venue eligibility filtering (disabled, unsupported instruments)
- Composite scoring with configurable weights
- Venue statistics tracking and incremental updates
- Venue management (add, remove, duplicate handling)
- Error conditions (no eligible venues, empty score list)
- Timestamp generation on routing decisions
"""

import sys
import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Ensure the project root is on sys.path so core_trading is importable.
# ---------------------------------------------------------------------------
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from core_trading.execution.smart_order_router import (
    FillResult,
    RoutingConfig,
    RoutingDecision,
    RoutingError,
    SmartOrderRouter,
    VenueConfig,
    VenueScore,
    VenueStats,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_venues():
    """Three sample venues: NYSE, NASDAQ, and a dark pool."""
    return [
        VenueConfig(
            venue_id="NYSE",
            name="New York Stock Exchange",
            venue_type="exchange",
            supported_instruments={"AAPL", "MSFT", "GOOG"},
            commission_rate=0.005,
            latency_ms=5.0,
            fill_rate=0.95,
        ),
        VenueConfig(
            venue_id="NASDAQ",
            name="NASDAQ",
            venue_type="exchange",
            supported_instruments={"AAPL", "MSFT", "TSLA"},
            commission_rate=0.004,
            latency_ms=3.0,
            fill_rate=0.97,
        ),
        VenueConfig(
            venue_id="DARK_POOL",
            name="Institutional Dark Pool",
            venue_type="dark_pool",
            supported_instruments={"AAPL", "MSFT", "GOOG", "TSLA"},
            commission_rate=0.002,
            latency_ms=10.0,
            fill_rate=0.85,
        ),
    ]


@pytest.fixture
def mock_event_bus():
    """Simple mock event bus with a publish method."""
    bus = MagicMock()
    bus.publish = AsyncMock()
    return bus


@pytest.fixture
def router(sample_venues, mock_event_bus):
    """SmartOrderRouter initialized with sample venues and a mock event bus."""
    return SmartOrderRouter(venues=sample_venues, event_bus=mock_event_bus)


@pytest.fixture
def sample_order():
    """A sample market order dict for AAPL."""
    return {
        "instrument": "AAPL",
        "quantity": 100,
        "side": "buy",
        "order_type": "market",
    }


# ---------------------------------------------------------------------------
# Initialization tests
# ---------------------------------------------------------------------------


class TestSmartOrderRouter:
    """Tests for the SmartOrderRouter class."""

    def test_initialization_with_venues(self, router, sample_venues):
        """Router should register all venues provided at construction."""
        assert len(router._venues) == 3
        venue_ids = set(router._venues.keys())
        expected_ids = {v.venue_id for v in sample_venues}
        assert venue_ids == expected_ids

    def test_initialization_with_default_config(self, mock_event_bus):
        """Router should use RoutingConfig defaults when none is provided."""
        r = SmartOrderRouter(venues=[], event_bus=mock_event_bus)
        assert r._config.cost_weight == 0.3
        assert r._config.speed_weight == 0.3
        assert r._config.fill_weight == 0.4
        assert r._config.max_venues_to_evaluate == 10
        assert r._config.min_fill_rate == 0.5
        assert r._config.max_latency_ms == 500.0

    def test_initialization_with_custom_config(self, mock_event_bus):
        """Router should apply a custom RoutingConfig when one is given."""
        config = RoutingConfig(
            max_venues_to_evaluate=5,
            min_fill_rate=0.8,
            max_latency_ms=200.0,
            cost_weight=0.2,
            speed_weight=0.3,
            fill_weight=0.5,
        )
        r = SmartOrderRouter(venues=[], event_bus=mock_event_bus, config=config)
        assert r._config.max_venues_to_evaluate == 5
        assert r._config.min_fill_rate == 0.8
        assert r._config.max_latency_ms == 200.0
        assert r._config.cost_weight == 0.2
        assert r._config.fill_weight == 0.5

    def test_initialization_creates_stats_for_each_venue(
        self, router, sample_venues
    ):
        """Router should initialize empty VenueStats for every venue."""
        for v in sample_venues:
            stats = router.get_venue_stats(v.venue_id)
            assert stats is not None
            assert stats.total_orders == 0
            assert stats.filled_orders == 0


# ---------------------------------------------------------------------------
# Routing tests
# ---------------------------------------------------------------------------


class TestRouting:
    """Tests for the route_order flow."""

    @pytest.mark.asyncio
    async def test_route_order_selects_best_venue(self, router, sample_order):
        """route_order should return a RoutingDecision with the best venue."""
        decision = await router.route_order(sample_order)
        assert isinstance(decision, RoutingDecision)
        assert decision.venue.venue_id in {"NYSE", "NASDAQ", "DARK_POOL"}
        # With default weights (fill=0.4, speed=0.3, cost=0.3), DARK_POOL
        # has the lowest commission (0.002) giving it the best composite score
        # despite slightly lower fill rate and higher latency.
        assert decision.venue.venue_id == "DARK_POOL"

    @pytest.mark.asyncio
    async def test_route_order_excludes_disabled_venues(
        self, sample_venues, mock_event_bus
    ):
        """Disabled venues must not appear in routing decisions."""
        for v in sample_venues:
            if v.venue_id == "NASDAQ":
                v.enabled = False

        router = SmartOrderRouter(venues=sample_venues, event_bus=mock_event_bus)
        order = {"instrument": "AAPL", "quantity": 100, "side": "buy", "order_type": "market"}
        decision = await router.route_order(order)
        assert decision.venue.venue_id != "NASDAQ"

    @pytest.mark.asyncio
    async def test_route_order_excludes_unsupported_instruments(
        self, router
    ):
        """Venues that do not support the order's instrument are excluded."""
        # TSLA is only on NASDAQ and DARK_POOL.
        order = {"instrument": "TSLA", "quantity": 50, "side": "buy", "order_type": "limit"}
        decision = await router.route_order(order)
        assert decision.venue.venue_id in {"NASDAQ", "DARK_POOL"}

    @pytest.mark.asyncio
    async def test_route_order_no_eligible_venues_raises(self, router):
        """RoutingError should be raised when no venue supports the instrument."""
        order = {"instrument": "OBSCURE_PENNY_STOCK", "quantity": 100, "side": "buy", "order_type": "market"}
        with pytest.raises(RoutingError, match="No eligible venue"):
            await router.route_order(order)


# ---------------------------------------------------------------------------
# Venue evaluation tests
# ---------------------------------------------------------------------------


class TestVenueEvaluation:
    """Tests for _evaluate_venues and scoring."""

    @pytest.mark.asyncio
    async def test_evaluate_venues_returns_scores(self, router, sample_order):
        """_evaluate_venues should return a VenueScore per eligible venue."""
        scores = await router._evaluate_venues(sample_order)
        assert len(scores) == 3  # All three venues support AAPL
        for s in scores:
            assert isinstance(s, VenueScore)

    @pytest.mark.asyncio
    async def test_evaluate_venues_scores_include_fill_probability(
        self, router, sample_order
    ):
        """Each VenueScore should contain a fill_probability > 0."""
        scores = await router._evaluate_venues(sample_order)
        for s in scores:
            assert s.fill_probability > 0.0

    @pytest.mark.asyncio
    async def test_evaluate_venues_scores_include_cost_estimate(
        self, router, sample_order
    ):
        """Each VenueScore should have an estimated_cost based on commission."""
        scores = await router._evaluate_venues(sample_order)
        for s in scores:
            assert s.estimated_cost > 0.0
            # Cost = commission_rate * quantity
            expected = s.venue.commission_rate * sample_order["quantity"]
            assert abs(s.estimated_cost - expected) < 1e-9

    @pytest.mark.asyncio
    async def test_evaluate_venues_scores_include_latency_estimate(
        self, router, sample_order
    ):
        """Each VenueScore should report the venue's latency."""
        scores = await router._evaluate_venues(sample_order)
        for s in scores:
            assert s.avg_latency_ms > 0.0


# ---------------------------------------------------------------------------
# Optimal selection tests
# ---------------------------------------------------------------------------


class TestOptimalSelection:
    """Tests for _select_optimal."""

    def test_select_optimal_chooses_highest_score(self, router, sample_venues):
        """_select_optimal should pick the VenueScore with the highest score."""
        venue_a = sample_venues[0]
        venue_b = sample_venues[1]

        scores = [
            VenueScore(
                venue=venue_a, score=0.75,
                fill_probability=0.9, estimated_cost=0.5,
                avg_latency_ms=5.0, selection_reason="A",
            ),
            VenueScore(
                venue=venue_b, score=0.90,
                fill_probability=0.97, estimated_cost=0.4,
                avg_latency_ms=3.0, selection_reason="B",
            ),
        ]
        best = router._select_optimal(scores)
        assert best.venue.venue_id == venue_b.venue_id
        assert best.score == 0.90

    def test_select_optimal_empty_list_raises(self, router):
        """_select_optimal must raise RoutingError when given an empty list."""
        with pytest.raises(RoutingError, match="empty score list"):
            router._select_optimal([])


# ---------------------------------------------------------------------------
# Venue statistics tests
# ---------------------------------------------------------------------------


class TestVenueStats:
    """Tests for update_venue_stats and stats retrieval."""

    def test_update_venue_stats_success_fill(self, router):
        """A successful fill should increment filled_orders and update totals."""
        result = FillResult(
            venue_id="NYSE",
            success=True,
            fill_price=150.0,
            fill_quantity=100,
            latency_ms=5.0,
            commission=0.75,
        )
        router.update_venue_stats("NYSE", result)

        stats = router.get_venue_stats("NYSE")
        assert stats is not None
        assert stats.total_orders == 1
        assert stats.filled_orders == 1
        assert stats.total_latency_ms == 5.0
        assert stats.total_commission == 0.75
        assert stats.fill_rate == 1.0
        assert stats.avg_latency_ms == 5.0

    def test_update_venue_stats_failed_fill(self, router):
        """A failed fill should increment total_orders but not filled_orders."""
        result = FillResult(
            venue_id="NYSE",
            success=False,
            fill_price=0.0,
            fill_quantity=0,
            latency_ms=3.0,
            commission=0.0,
        )
        router.update_venue_stats("NYSE", result)

        stats = router.get_venue_stats("NYSE")
        assert stats is not None
        assert stats.total_orders == 1
        assert stats.filled_orders == 0
        assert stats.fill_rate == 0.0

    def test_update_venue_stats_updates_fill_rate(self, router):
        """Fill rate should be recalculated after each update."""
        # One success.
        router.update_venue_stats("NYSE", FillResult(
            venue_id="NYSE", success=True,
            fill_price=150.0, fill_quantity=100,
            latency_ms=5.0, commission=0.75,
        ))
        stats = router.get_venue_stats("NYSE")
        assert stats.fill_rate == 1.0

        # One failure.
        router.update_venue_stats("NYSE", FillResult(
            venue_id="NYSE", success=False,
            fill_price=0.0, fill_quantity=0,
            latency_ms=0.0, commission=0.0,
        ))
        stats = router.get_venue_stats("NYSE")
        assert stats.fill_rate == pytest.approx(0.5)

    def test_update_venue_stats_updates_avg_latency(self, router):
        """Average latency should be recalculated from cumulative totals."""
        router.update_venue_stats("NYSE", FillResult(
            venue_id="NYSE", success=True,
            fill_price=150.0, fill_quantity=100,
            latency_ms=4.0, commission=0.5,
        ))
        router.update_venue_stats("NYSE", FillResult(
            venue_id="NYSE", success=True,
            fill_price=151.0, fill_quantity=100,
            latency_ms=6.0, commission=0.5,
        ))

        stats = router.get_venue_stats("NYSE")
        assert stats.avg_latency_ms == pytest.approx(5.0)

    def test_get_venue_stats_existing(self, router):
        """get_venue_stats should return stats for a known venue."""
        stats = router.get_venue_stats("NASDAQ")
        assert stats is not None
        assert stats.venue_id == "NASDAQ"

    def test_get_venue_stats_nonexistent_returns_none(self, router):
        """get_venue_stats should return None for an unknown venue."""
        stats = router.get_venue_stats("UNKNOWN")
        assert stats is None

    def test_get_all_stats(self, router):
        """get_all_stats should return stats for every registered venue."""
        all_stats = router.get_all_stats()
        assert len(all_stats) == 3
        assert "NYSE" in all_stats
        assert "NASDAQ" in all_stats
        assert "DARK_POOL" in all_stats

    def test_update_venue_stats_unknown_venue_is_noop(self, router):
        """Updating stats for an unknown venue should log a warning and not crash."""
        result = FillResult(
            venue_id="NONEXISTENT", success=True,
            fill_price=100.0, fill_quantity=10,
            latency_ms=1.0, commission=0.1,
        )
        # Should not raise.
        router.update_venue_stats("NONEXISTENT", result)
        assert router.get_venue_stats("NONEXISTENT") is None


# ---------------------------------------------------------------------------
# Venue management tests
# ---------------------------------------------------------------------------


class TestVenueManagement:
    """Tests for add_venue and remove_venue."""

    def test_add_venue(self, router):
        """add_venue should register a new venue and create its stats."""
        new_venue = VenueConfig(
            venue_id="BATS",
            name="BATS Global Markets",
            venue_type="exchange",
            supported_instruments={"AAPL", "MSFT"},
            commission_rate=0.003,
            latency_ms=2.0,
            fill_rate=0.94,
        )
        router.add_venue(new_venue)

        assert "BATS" in router._venues
        stats = router.get_venue_stats("BATS")
        assert stats is not None
        assert stats.venue_id == "BATS"

    def test_add_venue_already_exists(self, router):
        """add_venue should raise ValueError if venue_id already registered."""
        duplicate = VenueConfig(
            venue_id="NYSE",
            name="Duplicate NYSE",
            venue_type="exchange",
            supported_instruments={"AAPL"},
            commission_rate=0.01,
            latency_ms=10.0,
            fill_rate=0.8,
        )
        with pytest.raises(ValueError, match="already exists"):
            router.add_venue(duplicate)

    def test_remove_venue(self, router):
        """remove_venue should delete the venue and its stats."""
        router.remove_venue("DARK_POOL")
        assert "DARK_POOL" not in router._venues
        assert router.get_venue_stats("DARK_POOL") is None

    def test_remove_venue_nonexistent(self, router):
        """remove_venue should silently ignore unknown venue IDs."""
        # Should not raise.
        router.remove_venue("UNKNOWN_VENUE")
        assert len(router._venues) == 3


# ---------------------------------------------------------------------------
# Timestamp and weight tests
# ---------------------------------------------------------------------------


class TestRoutingDecisionDetails:
    """Tests for routing decision metadata and weight application."""

    @pytest.mark.asyncio
    async def test_routing_decision_has_timestamp(self, router, sample_order):
        """Every RoutingDecision should carry a UTC timestamp."""
        decision = await router.route_order(sample_order)
        assert isinstance(decision.timestamp, datetime)
        assert decision.timestamp.tzinfo is not None

    @pytest.mark.asyncio
    async def test_venue_score_weights_respected(
        self, mock_event_bus
    ):
        """The configured weights should directly influence the composite score."""
        config = RoutingConfig(
            cost_weight=0.5,
            speed_weight=0.3,
            fill_weight=0.2,
            min_fill_rate=0.0,
            max_latency_ms=1000.0,
        )
        venues = [
            VenueConfig(
                venue_id="LOW_COST",
                name="Low Cost Venue",
                venue_type="exchange",
                supported_instruments={"AAPL"},
                commission_rate=0.001,
                latency_ms=50.0,
                fill_rate=0.80,
            ),
            VenueConfig(
                venue_id="HIGH_FILL",
                name="High Fill Venue",
                venue_type="exchange",
                supported_instruments={"AAPL"},
                commission_rate=0.010,
                latency_ms=50.0,
                fill_rate=0.99,
            ),
        ]
        router = SmartOrderRouter(venues=venues, event_bus=mock_event_bus, config=config)

        order = {"instrument": "AAPL", "quantity": 100, "side": "buy", "order_type": "market"}
        decision = await router.route_order(order)

        # With cost_weight=0.5, the low-cost venue should win despite
        # having a lower fill rate.
        assert decision.venue.venue_id == "LOW_COST"
