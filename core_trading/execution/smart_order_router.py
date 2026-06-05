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

Phase 9.2 venue-analytics extension
-----------------------------------
- VenueAnalytics: Deterministic, replayable per-venue rolling estimator that
  consumes observed attempts/fills/markouts and produces immutable
  ``VenueAnalyticsSnapshot`` records. Snapshots carry Laplace-smoothed fill
  probability, rolling mean/percentile latency, and side-signed post-fill
  markout (positive = adverse, consistent with the repo positive-loss
  convention). The router can fold a snapshot into a ``VenueStats`` instance so
  the existing scoring code transparently benefits from richer estimates.
- AnalyticsConfig: Tunable smoothing prior, latency percentile, and rolling
  window sizes for VenueAnalytics.
- RoutingRationale: Machine-readable record of a single routing decision
  (chosen venue, per-venue scores, the analytics inputs behind them, order
  ref, timestamp) captured for transaction-cost analysis (TCA). The router
  retains a bounded ``decision_log`` and exposes ``decisions_to_frame`` for
  export to a pandas DataFrame.
"""
from __future__ import annotations

import logging
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

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
    supported_instruments: set[str]
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
    last_fill_time: datetime | None = None
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
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


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
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# Phase 9.2: Venue analytics
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AnalyticsConfig:
    """Tunable configuration for the :class:`VenueAnalytics` estimator.

    Attributes
    ----------
    fill_prior_alpha:
        Laplace-smoothing pseudo-count of prior *successes*. The smoothed fill
        probability is ``(fills + alpha) / (attempts + alpha + beta)``. With the
        defaults (``alpha=1``, ``beta=1``) an unobserved venue is assigned a
        neutral prior of ``0.5`` and a single lucky fill yields ``2/3`` rather
        than ``1.0``, preventing a thin sample from dominating routing.
    fill_prior_beta:
        Laplace-smoothing pseudo-count of prior *failures* (see above).
    latency_window:
        Maximum number of most-recent latency observations retained for the
        rolling mean and percentile. Older observations are evicted FIFO.
    latency_percentile:
        Percentile (0..100) reported alongside the rolling mean latency, e.g.
        ``95.0`` for the p95 tail latency.
    markout_window:
        Maximum number of most-recent markout observations retained for the
        rolling mean side-signed markout.
    """

    fill_prior_alpha: float = 1.0
    fill_prior_beta: float = 1.0
    latency_window: int = 256
    latency_percentile: float = 95.0
    markout_window: int = 256

    def __post_init__(self) -> None:
        if self.fill_prior_alpha < 0.0:
            raise ValueError("fill_prior_alpha must be non-negative")
        if self.fill_prior_beta < 0.0:
            raise ValueError("fill_prior_beta must be non-negative")
        if self.latency_window < 1:
            raise ValueError("latency_window must be >= 1")
        if not 0.0 <= self.latency_percentile <= 100.0:
            raise ValueError("latency_percentile must be in [0, 100]")
        if self.markout_window < 1:
            raise ValueError("markout_window must be >= 1")


@dataclass(frozen=True, slots=True)
class VenueAnalyticsSnapshot:
    """Immutable snapshot of a venue's analytics-derived estimates.

    All fields are computed deterministically from the observations recorded so
    far, so replaying the same sequence of ``record_*`` calls always yields the
    same snapshot.

    Attributes
    ----------
    venue_id:
        Identifier of the venue this snapshot describes.
    attempts:
        Total number of routing attempts observed for the venue.
    fills:
        Total number of successful fills observed for the venue.
    fill_probability:
        Laplace-smoothed fill probability in ``[0, 1]`` (see
        :class:`AnalyticsConfig`).
    raw_fill_rate:
        Unsmoothed ``fills / attempts``; ``0.0`` when there are no attempts.
        Provided for diagnostics and TCA, not used for scoring.
    latency_count:
        Number of latency observations currently in the rolling window.
    mean_latency_ms:
        Rolling mean of observed ack/fill latencies in milliseconds; ``0.0``
        when no latency has been observed.
    latency_percentile:
        The configured percentile of observed latencies in milliseconds;
        ``0.0`` when no latency has been observed.
    latency_percentile_q:
        The percentile level (0..100) that ``latency_percentile`` reports.
    markout_count:
        Number of markout observations currently in the rolling window.
    mean_markout:
        Rolling mean side-signed post-fill markout. Positive values are
        adverse (consistent with the repo positive-loss convention); ``0.0``
        when no markout has been observed.
    """

    venue_id: str
    attempts: int
    fills: int
    fill_probability: float
    raw_fill_rate: float
    latency_count: int
    mean_latency_ms: float
    latency_percentile: float
    latency_percentile_q: float
    markout_count: int
    mean_markout: float


class VenueAnalytics:
    """Deterministic, replayable per-venue rolling analytics estimator.

    The estimator maintains, for a single venue:

    * a smoothed fill probability from attempt/fill counts (Laplace smoothing
      with a configurable prior so a thin sample cannot dominate),
    * a rolling mean and percentile of observed ack/fill latencies, and
    * a rolling mean side-signed post-fill markout.

    The object is mutated only through the ``record_*`` methods; accessors
    return frozen :class:`VenueAnalyticsSnapshot` instances. Given the same
    ordered sequence of ``record_*`` calls the estimator is fully deterministic
    and replayable, which makes it suitable for offline TCA replay.

    Sign conventions
    ----------------
    Markout is recorded side-signed so that *positive = adverse* (the repo
    positive-loss convention): for a buy, an upward post-fill price move is
    favourable and is recorded as a negative markout; for a sell the reverse.
    Callers either pass an already side-signed value or use
    :meth:`record_fill_markout` which applies the sign from the order side and
    a reference/future price pair.

    Parameters
    ----------
    venue_id:
        Identifier of the venue this estimator tracks.
    config:
        Optional :class:`AnalyticsConfig`; a default instance is used when
        omitted.
    """

    __slots__ = (
        "_venue_id",
        "_config",
        "_attempts",
        "_fills",
        "_latencies",
        "_markouts",
    )

    def __init__(
        self,
        venue_id: str,
        config: AnalyticsConfig | None = None,
    ) -> None:
        self._venue_id = venue_id
        self._config = config or AnalyticsConfig()
        self._attempts: int = 0
        self._fills: int = 0
        self._latencies: deque[float] = deque(maxlen=self._config.latency_window)
        self._markouts: deque[float] = deque(maxlen=self._config.markout_window)

    # -- accessors -----------------------------------------------------------

    @property
    def venue_id(self) -> str:
        """Identifier of the tracked venue."""
        return self._venue_id

    @property
    def config(self) -> AnalyticsConfig:
        """The analytics configuration in effect."""
        return self._config

    # -- recorders -----------------------------------------------------------

    def record_attempt(self, *, filled: bool = False) -> None:
        """Record a single routing attempt.

        Parameters
        ----------
        filled:
            When ``True`` the attempt is also counted as a fill, equivalent to
            following the attempt with :meth:`record_fill`. Defaults to
            ``False`` so callers may record the attempt and the fill outcome
            separately.
        """
        self._attempts += 1
        if filled:
            self._fills += 1

    def record_fill(self, *, count_attempt: bool = False) -> None:
        """Record a single successful fill.

        Parameters
        ----------
        count_attempt:
            When ``True`` the fill also increments the attempt count. Defaults
            to ``False`` because the typical flow records the attempt first
            (via :meth:`record_attempt`) and the fill outcome second.
        """
        if count_attempt:
            self._attempts += 1
        self._fills += 1

    def record_latency(self, latency_ms: float) -> None:
        """Record one observed ack/fill latency in milliseconds.

        Parameters
        ----------
        latency_ms:
            Observed latency; must be finite and non-negative.

        Raises
        ------
        ValueError
            If ``latency_ms`` is negative or non-finite.
        """
        if not np.isfinite(latency_ms):
            raise ValueError("latency_ms must be finite")
        if latency_ms < 0.0:
            raise ValueError("latency_ms must be non-negative")
        self._latencies.append(float(latency_ms))

    def record_markout(self, markout: float) -> None:
        """Record one already side-signed post-fill markout.

        Positive values are adverse (repo positive-loss convention).

        Parameters
        ----------
        markout:
            Side-signed markout; must be finite.

        Raises
        ------
        ValueError
            If ``markout`` is non-finite.
        """
        if not np.isfinite(markout):
            raise ValueError("markout must be finite")
        self._markouts.append(float(markout))

    def record_fill_markout(
        self,
        *,
        side: str,
        reference_price: float,
        future_price: float,
    ) -> float:
        """Record a markout from a price pair, applying the side sign.

        The signed markout is computed so that *positive = adverse*:

        * BUY: ``future_price - reference_price`` is favourable, so the markout
          is ``reference_price - future_price``.
        * SELL: the reverse, ``future_price - reference_price``.

        Parameters
        ----------
        side:
            Order side, ``"buy"``/``"b"`` or ``"sell"``/``"s"``
            (case-insensitive).
        reference_price:
            Fill (decision) price.
        future_price:
            Price at the markout horizon.

        Returns
        -------
        float
            The side-signed markout that was recorded.

        Raises
        ------
        ValueError
            If ``side`` is not recognised or a price is non-finite.
        """
        if not (np.isfinite(reference_price) and np.isfinite(future_price)):
            raise ValueError("prices must be finite")
        normalized = side.strip().lower()
        if normalized in ("buy", "b"):
            sign = -1.0
        elif normalized in ("sell", "s"):
            sign = 1.0
        else:
            raise ValueError(f"unrecognized side: {side!r}")
        markout = sign * (float(future_price) - float(reference_price))
        self._markouts.append(markout)
        return markout

    # -- derived estimates ---------------------------------------------------

    def fill_probability(self) -> float:
        """Return the Laplace-smoothed fill probability in ``[0, 1]``."""
        alpha = self._config.fill_prior_alpha
        beta = self._config.fill_prior_beta
        denom = self._attempts + alpha + beta
        if denom <= 0.0:
            return 0.0
        return (self._fills + alpha) / denom

    def mean_latency_ms(self) -> float:
        """Return the rolling mean latency in ms (``0.0`` if no observations)."""
        if not self._latencies:
            return 0.0
        return float(np.mean(self._latencies))

    def latency_percentile_ms(self) -> float:
        """Return the configured latency percentile in ms (``0.0`` if empty)."""
        if not self._latencies:
            return 0.0
        return float(
            np.percentile(
                np.asarray(self._latencies, dtype=float),
                self._config.latency_percentile,
            )
        )

    def mean_markout(self) -> float:
        """Return the rolling mean side-signed markout (``0.0`` if empty)."""
        if not self._markouts:
            return 0.0
        return float(np.mean(self._markouts))

    def snapshot(self) -> VenueAnalyticsSnapshot:
        """Return an immutable snapshot of the current estimates."""
        raw_fill_rate = (self._fills / self._attempts) if self._attempts > 0 else 0.0
        return VenueAnalyticsSnapshot(
            venue_id=self._venue_id,
            attempts=self._attempts,
            fills=self._fills,
            fill_probability=self.fill_probability(),
            raw_fill_rate=raw_fill_rate,
            latency_count=len(self._latencies),
            mean_latency_ms=self.mean_latency_ms(),
            latency_percentile=self.latency_percentile_ms(),
            latency_percentile_q=self._config.latency_percentile,
            markout_count=len(self._markouts),
            mean_markout=self.mean_markout(),
        )

    def to_venue_stats(self, base: VenueStats | None = None) -> VenueStats:
        """Fold the analytics estimates into a :class:`VenueStats` instance.

        This lets the existing scoring code consume analytics-derived estimates
        without duplicating fields: the returned stats carry the smoothed fill
        probability in ``fill_rate`` and the rolling mean latency in
        ``avg_latency_ms``.

        Parameters
        ----------
        base:
            Optional existing stats to update. When supplied its commission and
            timestamp fields are preserved; otherwise a fresh instance is
            created. The instance is updated in place and also returned.

        Returns
        -------
        VenueStats
            The updated stats instance.
        """
        stats = base if base is not None else VenueStats(venue_id=self._venue_id)
        stats.total_orders = self._attempts
        stats.filled_orders = self._fills
        stats.fill_rate = self.fill_probability()
        stats.avg_latency_ms = self.mean_latency_ms()
        return stats


# ---------------------------------------------------------------------------
# Phase 9.2: Routing rationale (TCA)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VenueScoreRecord:
    """Immutable per-venue score line captured for a routing decision.

    Attributes
    ----------
    venue_id:
        Identifier of the scored venue.
    score:
        Composite weighted score (higher is better).
    fill_probability:
        Fill probability used in scoring (analytics-derived when available).
    estimated_cost:
        Estimated commission cost for the order at this venue.
    avg_latency_ms:
        Latency used in scoring in milliseconds.
    mean_markout:
        Analytics rolling mean side-signed markout (``0.0`` when no analytics
        are wired for this venue).
    chosen:
        Whether this venue was the one selected for the order.
    """

    venue_id: str
    score: float
    fill_probability: float
    estimated_cost: float
    avg_latency_ms: float
    mean_markout: float
    chosen: bool


@dataclass(frozen=True, slots=True)
class RoutingRationale:
    """Machine-readable record of one routing decision for TCA.

    Attributes
    ----------
    order_ref:
        Caller-supplied order reference (``order['order_ref']`` or
        ``order['order_id']`` when present, else ``""``).
    instrument:
        Instrument symbol the order targeted.
    side:
        Order side as supplied (or ``""``).
    quantity:
        Order quantity.
    chosen_venue_id:
        Identifier of the selected venue.
    chosen_score:
        Composite score of the selected venue.
    venue_scores:
        Tuple of :class:`VenueScoreRecord`, one per evaluated venue, including
        the chosen one (flagged via ``chosen``).
    timestamp:
        When the decision was made (UTC).
    """

    order_ref: str
    instrument: str
    side: str
    quantity: float
    chosen_venue_id: str
    chosen_score: float
    venue_scores: tuple[VenueScoreRecord, ...]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


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
        venues: list[VenueConfig],
        event_bus: Any,
        config: RoutingConfig | None = None,
        *,
        analytics_config: AnalyticsConfig | None = None,
        decision_log_size: int = 1000,
    ):
        self._venues: dict[str, VenueConfig] = {v.venue_id: v for v in venues}
        self._event_bus = event_bus
        self._config = config or RoutingConfig()
        self._analytics_config = analytics_config or AnalyticsConfig()
        self._venue_stats: dict[str, VenueStats] = {}
        self._analytics: dict[str, VenueAnalytics] = {}

        if decision_log_size < 1:
            raise ValueError("decision_log_size must be >= 1")
        self._decision_log: deque[RoutingRationale] = deque(maxlen=decision_log_size)

        # Initialize stats and analytics for every venue provided at
        # construction time.
        for venue in venues:
            self._venue_stats[venue.venue_id] = VenueStats(venue_id=venue.venue_id)
            self._analytics[venue.venue_id] = VenueAnalytics(
                venue.venue_id, self._analytics_config
            )

        logger.info(
            "SmartOrderRouter initialized with %d venue(s), config: %s",
            len(self._venues),
            self._config,
        )

    # -------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------

    async def route_order(self, order: dict[str, Any]) -> RoutingDecision:
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

        # Capture a machine-readable rationale for TCA.
        self._record_rationale(order, scores, best)

        logger.info(
            "Routing order for '%s' to venue '%s' (score=%.4f): %s",
            order.get("instrument", "<unknown>"),
            best.venue.venue_id,
            best.score,
            best.selection_reason,
        )
        return decision

    def _record_rationale(
        self,
        order: dict[str, Any],
        scores: Sequence[VenueScore],
        best: VenueScore,
    ) -> None:
        """Append a :class:`RoutingRationale` for this decision to the log."""
        records: list[VenueScoreRecord] = []
        for score in scores:
            vid = score.venue.venue_id
            analytics = self._analytics.get(vid)
            mean_markout = analytics.mean_markout() if analytics is not None else 0.0
            records.append(
                VenueScoreRecord(
                    venue_id=vid,
                    score=score.score,
                    fill_probability=score.fill_probability,
                    estimated_cost=score.estimated_cost,
                    avg_latency_ms=score.avg_latency_ms,
                    mean_markout=mean_markout,
                    chosen=vid == best.venue.venue_id,
                )
            )

        order_ref = str(order.get("order_ref", order.get("order_id", "")))
        rationale = RoutingRationale(
            order_ref=order_ref,
            instrument=str(order.get("instrument", "")),
            side=str(order.get("side", "")),
            quantity=float(order.get("quantity", 0.0)),
            chosen_venue_id=best.venue.venue_id,
            chosen_score=best.score,
            venue_scores=tuple(records),
        )
        self._decision_log.append(rationale)

    async def _evaluate_venues(self, order: dict[str, Any]) -> list[VenueScore]:
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
        scores: list[VenueScore] = []

        for venue in eligible:
            score = self._score_venue(venue, quantity)
            scores.append(score)

        return scores

    def _select_optimal(self, scores: list[VenueScore]) -> VenueScore:
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

        # Mirror the observation into the analytics estimator so that smoothed
        # estimates and rolling latency stay in sync with the legacy counters.
        analytics = self._analytics.get(venue_id)
        if analytics is not None:
            analytics.record_attempt(filled=result.success)
            if result.success:
                analytics.record_latency(result.latency_ms)

        logger.debug(
            "Updated stats for venue '%s': fill_rate=%.2f, avg_latency=%.1fms",
            venue_id,
            stats.fill_rate,
            stats.avg_latency_ms,
        )

    def get_venue_stats(self, venue_id: str) -> VenueStats | None:
        """Get performance statistics for a specific venue.

        Args:
            venue_id: Identifier of the venue.

        Returns:
            VenueStats if the venue is known, otherwise None.
        """
        return self._venue_stats.get(venue_id)

    def get_all_stats(self) -> dict[str, VenueStats]:
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
        self._analytics[venue.venue_id] = VenueAnalytics(
            venue.venue_id, self._analytics_config
        )
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
        self._analytics.pop(venue_id, None)

        if venue is not None:
            logger.info("Removed venue '%s' (%s)", venue_id, venue.name)

    # -------------------------------------------------------------------
    # Phase 9.2: Analytics and decision-log access
    # -------------------------------------------------------------------

    def get_venue_analytics(self, venue_id: str) -> VenueAnalytics | None:
        """Return the :class:`VenueAnalytics` estimator for a venue.

        Args:
            venue_id: Identifier of the venue.

        Returns:
            The estimator if the venue is known, otherwise None.
        """
        return self._analytics.get(venue_id)

    def record_markout(
        self,
        venue_id: str,
        *,
        side: str,
        reference_price: float,
        future_price: float,
    ) -> float | None:
        """Record a post-fill markout observation for a venue.

        Convenience wrapper around
        :meth:`VenueAnalytics.record_fill_markout` (positive = adverse).

        Args:
            venue_id: Identifier of the venue.
            side: Order side (``"buy"``/``"sell"``).
            reference_price: Fill (decision) price.
            future_price: Price at the markout horizon.

        Returns:
            The side-signed markout recorded, or None if the venue is unknown.
        """
        analytics = self._analytics.get(venue_id)
        if analytics is None:
            logger.warning("record_markout called for unknown venue '%s'", venue_id)
            return None
        return analytics.record_fill_markout(
            side=side,
            reference_price=reference_price,
            future_price=future_price,
        )

    @property
    def decision_log(self) -> tuple[RoutingRationale, ...]:
        """Return the bounded routing-decision rationale log (oldest first)."""
        return tuple(self._decision_log)

    def decisions_to_frame(self) -> pd.DataFrame:
        """Export the decision log to a flat :class:`pandas.DataFrame` for TCA.

        The frame has one row per evaluated venue per decision. Columns:
        ``timestamp``, ``order_ref``, ``instrument``, ``side``, ``quantity``,
        ``chosen_venue_id``, ``chosen_score``, ``venue_id``, ``score``,
        ``fill_probability``, ``estimated_cost``, ``avg_latency_ms``,
        ``mean_markout``, ``chosen``.

        Returns:
            A DataFrame with the columns above; empty (with the correct
            columns) when no decisions have been logged.
        """
        columns = [
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
        ]
        rows: list[dict[str, Any]] = []
        for rationale in self._decision_log:
            for record in rationale.venue_scores:
                rows.append(
                    {
                        "timestamp": rationale.timestamp,
                        "order_ref": rationale.order_ref,
                        "instrument": rationale.instrument,
                        "side": rationale.side,
                        "quantity": rationale.quantity,
                        "chosen_venue_id": rationale.chosen_venue_id,
                        "chosen_score": rationale.chosen_score,
                        "venue_id": record.venue_id,
                        "score": record.score,
                        "fill_probability": record.fill_probability,
                        "estimated_cost": record.estimated_cost,
                        "avg_latency_ms": record.avg_latency_ms,
                        "mean_markout": record.mean_markout,
                        "chosen": record.chosen,
                    }
                )
        return pd.DataFrame(rows, columns=columns)

    # -------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------

    def _get_eligible_venues(self, instrument: str) -> list[VenueConfig]:
        """Return venues that are enabled, support the instrument, and meet thresholds."""
        eligible: list[VenueConfig] = []

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
        # Prefer analytics-derived estimates when the venue has any observed
        # attempts: VenueAnalytics applies Laplace smoothing so a thin sample
        # cannot dominate, and it folds its estimates into a VenueStats so the
        # rest of this method is unchanged. Fall back to the legacy stats path
        # (observed fill_rate once >=5 orders) and finally to the venue's
        # configured static fields.
        stats = self._venue_stats.get(venue.venue_id)
        analytics = self._analytics.get(venue.venue_id)

        fill_probability = venue.fill_rate
        avg_latency = venue.latency_ms

        if analytics is not None and analytics.snapshot().attempts > 0:
            snap = analytics.snapshot()
            fill_probability = snap.fill_probability
            if snap.latency_count > 0:
                avg_latency = snap.mean_latency_ms
        else:
            if stats and stats.total_orders >= 5:
                fill_probability = stats.fill_rate
            if stats and stats.filled_orders > 0:
                avg_latency = stats.avg_latency_ms

        estimated_cost = venue.commission_rate * quantity

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
        reasons: list[str] = []
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
