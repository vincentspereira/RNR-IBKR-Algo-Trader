"""Smart Order Router for optimal venue selection.

Provides intelligent order routing by evaluating trading venues based on
fill probability, execution latency, and commission cost. Venues are scored
using a weighted composite metric and the highest-scoring venue is selected
for each order.

Key components:
- VenueConfig: Describes a trading venue's capabilities and cost profile
- VenueStats: Tracks rolling performance statistics per venue
- VenueScore: Composite evaluation result for a single venue
- RoutingDecision: Final routing choice with rationale and timestamp
- RoutingConfig: Tunable weights and thresholds for the scoring algorithm
- FillResult: Records the outcome of an executed fill for stats tracking
- SmartOrderRouter: Main routing engine with venue management and scoring
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class VenueConfig:
    """Configuration for a trading venue.

    Attributes:
        venue_id: Unique identifier for the venue.
        name: Human-readable venue name.
        venue_type: Category of venue (e.g. "exchange", "dark_pool", "ecn").
        supported_instruments: Set of instrument symbols this venue handles.
        commission_rate: Commission as a fraction of trade value (e.g. 0.005).
        latency_ms: Average round-trip latency in milliseconds.
        fill_rate: Historical fill probability (0.0 to 1.0).
        enabled: Whether the venue is active for routing.
    """

    venue_id: str
    name: str
    venue_type: str
    supported_instruments: Set[str]
    commission_rate: float
    latency_ms: float
    fill_rate: float
    enabled: bool = True


@dataclass
class VenueStats:
    """Rolling performance statistics for a venue.

    Attributes:
        venue_id: Unique venue identifier.
        total_orders: Total number of orders routed to this venue.
        filled_orders: Number of orders that were filled.
        total_latency_ms: Cumulative latency for all fills in milliseconds.
        total_commission: Cumulative commission paid in dollars.
        last_fill_time: Timestamp of the most recent fill, or None.
        fill_rate: Calculated fill rate (filled_orders / total_orders).
        avg_latency_ms: Calculated average latency in milliseconds.
    """

    venue_id: str
    total_orders: int = 0
    filled_orders: int = 0
    total_latency_ms: float = 0.0
    total_commission: float = 0.0
    last_fill_time: Optional[datetime] = None
    fill_rate: float = 0.0
    avg_latency_ms: float = 0.0


@dataclass
class VenueScore:
    """Evaluation result for a single venue against an order.

    Attributes:
        venue: The venue configuration that was scored.
        score: Composite weighted score (higher is better).
        fill_probability: Estimated probability of a successful fill.
        estimated_cost: Estimated commission cost for the order.
        avg_latency_ms: Expected average latency in milliseconds.
        selection_reason: Human-readable explanation of the score.
    """

    venue: VenueConfig
    score: float
    fill_probability: float
    estimated_cost: float
    avg_latency_ms: float
    selection_reason: str


@dataclass
class RoutingDecision:
    """Final routing decision for an order.

    Attributes:
        venue: The selected venue configuration.
        estimated_fill_rate: Expected fill probability at this venue.
        estimated_cost: Expected commission cost.
        estimated_latency_ms: Expected latency in milliseconds.
        reason: Human-readable rationale for this routing choice.
        timestamp: When the routing decision was made (UTC).
    """

    venue: VenueConfig
    estimated_fill_rate: float
    estimated_cost: float
    estimated_latency_ms: float
    reason: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class RoutingConfig:
    """Tunable configuration for the smart order routing algorithm.

    Attributes:
        max_venues_to_evaluate: Maximum number of venues to score per order.
        min_fill_rate: Minimum fill rate a venue must have to be eligible.
        max_latency_ms: Maximum acceptable latency in milliseconds.
        cost_weight: Weight applied to the cost component of the score.
        speed_weight: Weight applied to the speed (latency) component.
        fill_weight: Weight applied to the fill probability component.
    """

    max_venues_to_evaluate: int = 10
    min_fill_rate: float = 0.5
    max_latency_ms: float = 500.0
    cost_weight: float = 0.3
    speed_weight: float = 0.3
    fill_weight: float = 0.4


@dataclass
class FillResult:
    """Outcome of a fill attempt, used to update venue statistics.

    Attributes:
        venue_id: The venue where the fill was attempted.
        success: Whether the fill was successful.
        fill_price: Execution price per unit.
        fill_quantity: Number of units filled.
        latency_ms: Observed round-trip latency in milliseconds.
        commission: Commission charged for this fill.
        timestamp: When the fill result was recorded (UTC).
    """

    venue_id: str
    success: bool
    fill_price: float
    fill_quantity: float
    latency_ms: float
    commission: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class RoutingError(Exception):
    """Raised when no eligible venue can be found for an order."""


# ---------------------------------------------------------------------------
# Smart Order Router
# ---------------------------------------------------------------------------


class SmartOrderRouter:
    """Route orders to the optimal venue based on fill probability, latency, and cost.

    The router maintains a registry of venues with their capabilities and
    tracks real-time performance statistics. For each order, it evaluates
    eligible venues using a weighted composite score and selects the one
    most likely to deliver the best execution quality.
    """

    def __init__(
        self,
        venues: List[VenueConfig],
        event_bus: Any,
        config: Optional[RoutingConfig] = None,
    ):
        self._venues: Dict[str, VenueConfig] = {v.venue_id: v for v in venues}
        self._event_bus = event_bus
        self._config = config or RoutingConfig()
        self._venue_stats: Dict[str, VenueStats] = {}

        # Initialize stats for every venue provided at construction time.
        for venue in venues:
            self._venue_stats[venue.venue_id] = VenueStats(venue_id=venue.venue_id)

        logger.info(
            "SmartOrderRouter initialized with %d venue(s), config: %s",
            len(self._venues),
            self._config,
        )

    # -------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------

    async def route_order(self, order: Dict[str, Any]) -> RoutingDecision:
        """Select the best venue for order execution.

        Args:
            order: Dict-like object with keys ``instrument``, ``quantity``,
                ``side``, and ``order_type``.

        Returns:
            A RoutingDecision identifying the selected venue.

        Raises:
            RoutingError: If no eligible venue is available for the order.
        """
        scores = await self._evaluate_venues(order)

        if not scores:
            raise RoutingError(
                f"No eligible venue found for instrument "
                f"'{order.get('instrument', '<unknown>')}'"
            )

        best = self._select_optimal(scores)

        decision = RoutingDecision(
            venue=best.venue,
            estimated_fill_rate=best.fill_probability,
            estimated_cost=best.estimated_cost,
            estimated_latency_ms=best.avg_latency_ms,
            reason=best.selection_reason,
        )

        logger.info(
            "Routing order for '%s' to venue '%s' (score=%.4f): %s",
            order.get("instrument", "<unknown>"),
            best.venue.venue_id,
            best.score,
            best.selection_reason,
        )
        return decision

    async def _evaluate_venues(self, order: Dict[str, Any]) -> List[VenueScore]:
        """Score each eligible venue for this order.

        A venue is eligible when it is enabled, supports the order's instrument,
        and meets the minimum fill rate and maximum latency thresholds from
        the routing configuration.

        Returns:
            A list of VenueScore objects, one per eligible venue.
        """
        instrument = order.get("instrument", "")
        quantity = order.get("quantity", 0.0)

        eligible = self._get_eligible_venues(instrument)
        scores: List[VenueScore] = []

        for venue in eligible:
            score = self._score_venue(venue, quantity)
            scores.append(score)

        return scores

    def _select_optimal(self, scores: List[VenueScore]) -> VenueScore:
        """Select the venue with the highest composite score.

        Args:
            scores: Non-empty list of scored venues.

        Returns:
            The VenueScore with the highest ``score`` value.

        Raises:
            RoutingError: If ``scores`` is empty.
        """
        if not scores:
            raise RoutingError("Cannot select optimal venue from an empty score list.")

        return max(scores, key=lambda s: s.score)

    def update_venue_stats(self, venue_id: str, result: FillResult) -> None:
        """Track venue performance for future routing decisions.

        Incrementally updates order count, fill count, cumulative latency,
        commission, and derived averages.

        Args:
            venue_id: Identifier of the venue to update.
            result: The FillResult describing the outcome.
        """
        stats = self._venue_stats.get(venue_id)
        if stats is None:
            logger.warning("update_venue_stats called for unknown venue '%s'", venue_id)
            return

        stats.total_orders += 1

        if result.success:
            stats.filled_orders += 1
            stats.total_latency_ms += result.latency_ms
            stats.total_commission += result.commission
            stats.last_fill_time = result.timestamp

        # Recalculate derived metrics.
        if stats.total_orders > 0:
            stats.fill_rate = stats.filled_orders / stats.total_orders

        if stats.filled_orders > 0:
            stats.avg_latency_ms = stats.total_latency_ms / stats.filled_orders

        logger.debug(
            "Updated stats for venue '%s': fill_rate=%.2f, avg_latency=%.1fms",
            venue_id,
            stats.fill_rate,
            stats.avg_latency_ms,
        )

    def get_venue_stats(self, venue_id: str) -> Optional[VenueStats]:
        """Get performance statistics for a specific venue.

        Args:
            venue_id: Identifier of the venue.

        Returns:
            VenueStats if the venue is known, otherwise None.
        """
        return self._venue_stats.get(venue_id)

    def get_all_stats(self) -> Dict[str, VenueStats]:
        """Get performance statistics for all tracked venues.

        Returns:
            Mapping of venue_id to VenueStats.
        """
        return dict(self._venue_stats)

    def add_venue(self, venue: VenueConfig) -> None:
        """Add a new venue to the router.

        If a venue with the same ``venue_id`` already exists, a
        ``ValueError`` is raised.

        Args:
            venue: The VenueConfig to register.

        Raises:
            ValueError: If the venue_id is already registered.
        """
        if venue.venue_id in self._venues:
            raise ValueError(
                f"Venue '{venue.venue_id}' already exists in the router."
            )

        self._venues[venue.venue_id] = venue
        self._venue_stats[venue.venue_id] = VenueStats(venue_id=venue.venue_id)
        logger.info("Added venue '%s' (%s)", venue.venue_id, venue.name)

    def remove_venue(self, venue_id: str) -> None:
        """Remove a venue from the router.

        Silently ignores unknown venue IDs so callers do not need to check
        existence beforehand.

        Args:
            venue_id: Identifier of the venue to remove.
        """
        venue = self._venues.pop(venue_id, None)
        self._venue_stats.pop(venue_id, None)

        if venue is not None:
            logger.info("Removed venue '%s' (%s)", venue_id, venue.name)

    # -------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------

    def _get_eligible_venues(self, instrument: str) -> List[VenueConfig]:
        """Return venues that are enabled, support the instrument, and meet thresholds."""
        eligible: List[VenueConfig] = []

        for venue in self._venues.values():
            if not venue.enabled:
                continue

            if instrument not in venue.supported_instruments:
                continue

            # Apply minimum fill-rate and maximum latency filters from config.
            if venue.fill_rate < self._config.min_fill_rate:
                continue

            if venue.latency_ms > self._config.max_latency_ms:
                continue

            eligible.append(venue)

            if len(eligible) >= self._config.max_venues_to_evaluate:
                break

        return eligible

    def _score_venue(self, venue: VenueConfig, quantity: float) -> VenueScore:
        """Compute a composite score for a single venue.

        The score is a weighted combination of three normalized components:
          - Fill probability (higher is better)
          - Inverse latency (lower latency is better, so we invert)
          - Inverse cost (lower cost is better, so we invert)

        Each component is normalized to the [0, 1] range so that the weights
        sum to 1.0 and the final score also falls in [0, 1].
        """
        # Use observed fill_rate from stats if we have enough data,
        # otherwise fall back to the venue's configured fill_rate.
        stats = self._venue_stats.get(venue.venue_id)
        fill_probability = venue.fill_rate
        if stats and stats.total_orders >= 5:
            fill_probability = stats.fill_rate

        estimated_cost = venue.commission_rate * quantity
        avg_latency = venue.latency_ms
        if stats and stats.filled_orders > 0:
            avg_latency = stats.avg_latency_ms

        # Normalize latency to [0, 1] where 1 = best (0ms).
        latency_norm = min(avg_latency / self._config.max_latency_ms, 1.0)

        # Normalize cost using an absolute reference so that different commission
        # rates produce meaningfully different scores. We use 1% as the reference
        # maximum commission rate (0.01) applied to the order quantity. Venues
        # with commission rates below 1% score better (lower cost_norm).
        max_cost_reference = 0.01 * quantity
        cost_norm = min(estimated_cost / max_cost_reference, 1.0) if max_cost_reference > 0 else 0.0

        score = (
            self._config.fill_weight * fill_probability
            + self._config.speed_weight * (1.0 - latency_norm)
            + self._config.cost_weight * (1.0 - cost_norm)
        )

        # Build a human-readable reason.
        reasons: List[str] = []
        if fill_probability >= 0.9:
            reasons.append("high fill probability")
        elif fill_probability >= 0.7:
            reasons.append("moderate fill probability")
        else:
            reasons.append("low fill probability")

        if avg_latency <= 5.0:
            reasons.append("very low latency")
        elif avg_latency <= 50.0:
            reasons.append("low latency")
        else:
            reasons.append("higher latency")

        if venue.commission_rate <= 0.003:
            reasons.append("low cost")
        elif venue.commission_rate <= 0.007:
            reasons.append("moderate cost")
        else:
            reasons.append("higher cost")

        selection_reason = f"{venue.name}: {', '.join(reasons)}"

        return VenueScore(
            venue=venue,
            score=score,
            fill_probability=fill_probability,
            estimated_cost=estimated_cost,
            avg_latency_ms=avg_latency,
            selection_reason=selection_reason,
        )
