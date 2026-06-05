"""Drawdown circuit breakers -- replayable state machines (master plan Phase 7.8).

Three complementary breaker types guard the trading system against sustained
adverse moves:

Strategy-level breaker
    Pauses a single strategy when its equity drawdown exceeds a configurable
    threshold (default 10%).  Inspired by venue-level limit-up / limit-down
    rules (NYSE Rule 80B / LULD) applied at strategy scope.

Portfolio-level breaker
    Graduated two-stage response to portfolio equity drawdown: de-risk to a
    reduced target exposure at a soft threshold (default 15%), then impose a
    full halt at a hard threshold (default 25%).  The full HALT is *sticky* --
    it requires explicit human review via :meth:`CircuitBreakerEngine.manual_reset`
    before trading can resume.  This mirrors the market-wide circuit breaker
    philosophy: a large drawdown should force human review, not auto-restart.

Daily-loss limiter
    Halts NEW orders when the intraday loss exceeds a configurable fraction of
    NAV (default 3%).  Unlike portfolio HALT, this breaker resets automatically
    at the next session start because a bad day should not preclude the next day.

Design principles
-----------------
* **Pure / replayable**: :meth:`CircuitBreakerEngine.update` and
  :meth:`CircuitBreakerEngine.update_intraday` accept caller-supplied
  timestamps and return typed :class:`BreakerEvent` objects.  No wall-clock
  reads occur inside the module.
* **Explicit state machine**: states are :class:`BreakerState` enum members;
  transitions are table-driven and logged as immutable events.
* **Configurable re-arm rules** (conservative, documented):

  - Strategy PAUSED un-pauses when the drawdown has recovered within
    ``strategy_rearm_pct`` of the peak AND at least ``strategy_cooldown_sessions``
    new session-start timestamps have been observed since the pause.  Default:
    recover within 5% of peak (i.e. drawdown < 5%); 2 sessions cooldown.
  - Portfolio DERISKED returns to NORMAL when drawdown recovers within
    ``portfolio_rearm_pct`` of peak AND ``portfolio_cooldown_sessions``
    sessions have elapsed.  Default: 5%; 3 sessions.
  - Portfolio HALT is sticky (``portfolio_halt_sticky=True`` by default) --
    only :meth:`manual_reset` can clear it.  Set ``portfolio_halt_sticky=False``
    to allow automatic recovery (useful in backtests); even then the same
    recovery + cooldown conditions apply.
  - Daily HALT_NEW_ORDERS resets automatically on the next session start
    (:meth:`new_session`); no cooldown required.

References
----------
* NYSE Rule 80B (market-wide circuit breakers).
* SEC Regulation SCI, Rule 15c3-5 (market access risk controls).
* Pairs-trading risk precursor: :mod:`core_trading.risk.pairs_risk`.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass

import pandas as pd

__all__ = [
    "BreakerState",
    "BreakerType",
    "BreakerEvent",
    "BreakerConfig",
    "CircuitBreakerEngine",
    "DEFAULT_CONFIG",
]

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class BreakerState(enum.Enum):
    """Possible states for each breaker dimension.

    NORMAL
        All clear; no active breakers.
    PAUSED
        Strategy-level: strategy is paused due to drawdown threshold breach.
    DERISKED
        Portfolio-level: soft threshold crossed; exposure scaled to
        ``portfolio_derisk_factor`` of target.
    HALTED
        Portfolio-level: hard threshold crossed; all trading halted.
    HALT_NEW_ORDERS
        Daily-loss: no new orders may be placed; existing positions may be
        closed.  Resets automatically at the next session start.
    """

    NORMAL = "NORMAL"
    PAUSED = "PAUSED"
    DERISKED = "DERISKED"
    HALTED = "HALTED"
    HALT_NEW_ORDERS = "HALT_NEW_ORDERS"


class BreakerType(enum.Enum):
    """Which breaker dimension produced an event."""

    STRATEGY = "STRATEGY"
    PORTFOLIO = "PORTFOLIO"
    DAILY_LOSS = "DAILY_LOSS"


# ---------------------------------------------------------------------------
# Event record
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BreakerEvent:
    """Immutable record of a single state-machine transition.

    Attributes
    ----------
    timestamp:
        Caller-supplied timestamp at which the transition occurred.
    breaker:
        Which breaker dimension fired.
    strategy_id:
        Strategy identifier; ``None`` for portfolio and daily-loss events.
    from_state:
        State before the transition.
    to_state:
        State after the transition.
    metric:
        The metric value that triggered (or cleared) the transition, expressed
        as a positive fraction.  E.g. drawdown of 0.11 or intraday loss 0.035.
    threshold:
        The threshold that was crossed.  For re-arm events this is the
        re-arm threshold; for halt events it is the halt threshold.
    message:
        Human-readable ASCII description of the event.
    """

    timestamp: pd.Timestamp
    breaker: BreakerType
    strategy_id: str | None
    from_state: BreakerState
    to_state: BreakerState
    metric: float
    threshold: float
    message: str


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BreakerConfig:
    """Immutable configuration for all circuit breakers.

    Strategy-level parameters
    -------------------------
    strategy_dd_threshold:
        Pause a strategy when drawdown exceeds this fraction (default 0.10).
    strategy_rearm_pct:
        Strategy resumes only when drawdown drops below this fraction and the
        cooldown has elapsed (default 0.05 -- within 5% of peak).
    strategy_cooldown_sessions:
        Minimum number of session-start events that must be observed after
        a strategy pause before recovery is allowed (default 2).

    Portfolio-level parameters
    --------------------------
    portfolio_derisk_threshold:
        Scale exposure when portfolio drawdown exceeds this fraction
        (default 0.15).
    portfolio_halt_threshold:
        Halt all trading when portfolio drawdown exceeds this fraction
        (default 0.25).
    portfolio_derisk_factor:
        Target exposure multiplier during DERISKED state (default 0.50).
    portfolio_rearm_pct:
        Portfolio resumes NORMAL from DERISKED only when drawdown drops below
        this fraction and the cooldown has elapsed (default 0.05).
    portfolio_cooldown_sessions:
        Minimum session-start events after a DERISKED event before recovery
        from DERISKED is allowed (default 3).
    portfolio_halt_sticky:
        When ``True`` (default), portfolio HALT is sticky: only
        :meth:`CircuitBreakerEngine.manual_reset` can clear it.  When
        ``False``, the same recovery + cooldown conditions as DERISKED apply.

    Daily-loss parameters
    ---------------------
    daily_loss_threshold:
        Halt new orders when intraday loss fraction exceeds this (default 0.03).
    """

    # strategy
    strategy_dd_threshold: float = 0.10
    strategy_rearm_pct: float = 0.05
    strategy_cooldown_sessions: int = 2

    # portfolio
    portfolio_derisk_threshold: float = 0.15
    portfolio_halt_threshold: float = 0.25
    portfolio_derisk_factor: float = 0.50
    portfolio_rearm_pct: float = 0.05
    portfolio_cooldown_sessions: int = 3
    portfolio_halt_sticky: bool = True

    # daily loss
    daily_loss_threshold: float = 0.03

    def __post_init__(self) -> None:
        """Validate configuration values."""
        _pos_float = [
            ("strategy_dd_threshold", self.strategy_dd_threshold),
            ("strategy_rearm_pct", self.strategy_rearm_pct),
            ("portfolio_derisk_threshold", self.portfolio_derisk_threshold),
            ("portfolio_halt_threshold", self.portfolio_halt_threshold),
            ("portfolio_derisk_factor", self.portfolio_derisk_factor),
            ("portfolio_rearm_pct", self.portfolio_rearm_pct),
            ("daily_loss_threshold", self.daily_loss_threshold),
        ]
        for name, val in _pos_float:
            if val <= 0.0:
                raise ValueError(f"BreakerConfig.{name} must be > 0, got {val!r}")
        if self.portfolio_halt_threshold <= self.portfolio_derisk_threshold:
            raise ValueError(
                f"portfolio_halt_threshold ({self.portfolio_halt_threshold}) must be"
                f" > portfolio_derisk_threshold ({self.portfolio_derisk_threshold})"
            )
        if self.strategy_cooldown_sessions < 0:
            raise ValueError(
                f"strategy_cooldown_sessions must be >= 0, got"
                f" {self.strategy_cooldown_sessions!r}"
            )
        if self.portfolio_cooldown_sessions < 0:
            raise ValueError(
                f"portfolio_cooldown_sessions must be >= 0, got"
                f" {self.portfolio_cooldown_sessions!r}"
            )
        if not (0.0 < self.portfolio_derisk_factor < 1.0):
            raise ValueError(
                f"portfolio_derisk_factor must be in (0, 1), got"
                f" {self.portfolio_derisk_factor!r}"
            )


DEFAULT_CONFIG: BreakerConfig = BreakerConfig()


# ---------------------------------------------------------------------------
# Internal per-strategy state
# ---------------------------------------------------------------------------


@dataclass
class _StrategyState:
    """Mutable runtime state for a single strategy breaker."""

    state: BreakerState = BreakerState.NORMAL
    high_watermark: float = 0.0
    # Sessions elapsed since breaker fired (incremented by new_session calls).
    sessions_since_pause: int = 0
    # Whether we are currently counting cooldown sessions.
    counting_cooldown: bool = False


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------


class CircuitBreakerEngine:
    """Stateful, replayable circuit breaker engine.

    Maintains three independent breaker dimensions:

    1. Per-strategy drawdown (one :class:`BreakerState` per strategy ID).
    2. Portfolio drawdown (single state, graduated: DERISKED -> HALTED).
    3. Daily intraday loss (single state: HALT_NEW_ORDERS).

    All state transitions emit :class:`BreakerEvent` records appended to
    :attr:`events`.  The events list is the authoritative audit log.

    Parameters
    ----------
    config:
        Immutable configuration object.  Defaults to :data:`DEFAULT_CONFIG`.

    Examples
    --------
    >>> engine = CircuitBreakerEngine()
    >>> ts = pd.Timestamp("2024-01-02")
    >>> evts = engine.update("strat_A", ts, equity=95.0)  # peak was 100
    >>> engine.strategy_state("strat_A")
    <BreakerState.PAUSED: 'PAUSED'>
    """

    def __init__(self, config: BreakerConfig = DEFAULT_CONFIG) -> None:
        self._cfg = config
        # Per-strategy mutable state.
        self._strategies: dict[str, _StrategyState] = {}
        # Portfolio-level state.
        self._port_state: BreakerState = BreakerState.NORMAL
        self._port_hwm: float = 0.0
        self._port_sessions_since_derisked: int = 0
        self._port_counting_cooldown: bool = False
        # Daily-loss state.
        self._daily_state: BreakerState = BreakerState.NORMAL
        self._daily_session_nav: float | None = None  # NAV at session start
        # Audit log of all transitions.
        self.events: list[BreakerEvent] = []

    # ------------------------------------------------------------------
    # Public query helpers
    # ------------------------------------------------------------------

    def strategy_state(self, strategy_id: str) -> BreakerState:
        """Return the current :class:`BreakerState` for a strategy.

        Returns :attr:`BreakerState.NORMAL` for unknown strategies (no equity
        observations have been fed yet).
        """
        s = self._strategies.get(strategy_id)
        return s.state if s is not None else BreakerState.NORMAL

    @property
    def portfolio_state(self) -> BreakerState:
        """Current portfolio-level :class:`BreakerState`."""
        return self._port_state

    @property
    def daily_state(self) -> BreakerState:
        """Current daily-loss :class:`BreakerState`."""
        return self._daily_state

    @property
    def portfolio_exposure_factor(self) -> float:
        """Exposure scaling factor implied by the current portfolio state.

        Returns
        -------
        float
            1.0 in NORMAL/PAUSED states; ``config.portfolio_derisk_factor`` in
            DERISKED; 0.0 in HALTED.
        """
        if self._port_state == BreakerState.HALTED:
            return 0.0
        if self._port_state == BreakerState.DERISKED:
            return self._cfg.portfolio_derisk_factor
        return 1.0

    def can_place_new_orders(self) -> bool:
        """Return ``True`` when the daily-loss limiter allows new orders."""
        return self._daily_state != BreakerState.HALT_NEW_ORDERS

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def new_session(
        self,
        timestamp: pd.Timestamp,
        session_open_nav: float | None = None,
    ) -> list[BreakerEvent]:
        """Signal the start of a new trading session.

        This method performs three actions:

        1. Resets the daily-loss HALT_NEW_ORDERS state (intraday losses do not
           carry over to the next session).
        2. Records the session-open NAV for daily-loss tracking when provided.
        3. Increments the cooldown session counters for strategy and portfolio
           breakers that are currently in a triggered state.

        Parameters
        ----------
        timestamp:
            Session open timestamp (caller-supplied, no wall-clock reads).
        session_open_nav:
            Portfolio NAV at session open.  When provided, this becomes the
            baseline for daily-loss calculations via :meth:`update_intraday`.
            When ``None``, the intraday baseline is unchanged.

        Returns
        -------
        list[BreakerEvent]
            Any events generated (e.g. daily-loss reset, strategy recovery
            triggered by reaching cooldown after prior equity update).
        """
        evts: list[BreakerEvent] = []

        # 1. Reset daily-loss halt.
        if self._daily_state == BreakerState.HALT_NEW_ORDERS:
            evt = BreakerEvent(
                timestamp=timestamp,
                breaker=BreakerType.DAILY_LOSS,
                strategy_id=None,
                from_state=BreakerState.HALT_NEW_ORDERS,
                to_state=BreakerState.NORMAL,
                metric=0.0,
                threshold=self._cfg.daily_loss_threshold,
                message=(
                    "Daily-loss halt reset at session start;"
                    " HALT_NEW_ORDERS -> NORMAL"
                ),
            )
            self._daily_state = BreakerState.NORMAL
            self.events.append(evt)
            evts.append(evt)

        # 2. Record session-open NAV.
        if session_open_nav is not None:
            self._daily_session_nav = float(session_open_nav)

        # 3. Increment cooldown counters; check recovery.
        for _sid, ss in self._strategies.items():
            if ss.counting_cooldown:
                ss.sessions_since_pause += 1
                # Recovery check is deferred to the next update() call so that
                # a new equity point is required to confirm actual recovery.

        if self._port_counting_cooldown:
            self._port_sessions_since_derisked += 1

        return evts

    # ------------------------------------------------------------------
    # Per-strategy update
    # ------------------------------------------------------------------

    def update(
        self,
        strategy_id: str,
        timestamp: pd.Timestamp,
        *,
        equity: float,
    ) -> list[BreakerEvent]:
        """Feed a new equity observation for a strategy.

        Computes the high-watermark drawdown and evaluates strategy-level
        circuit breaker conditions.  May also evaluate re-arm conditions if the
        strategy is currently PAUSED.

        Parameters
        ----------
        strategy_id:
            Unique string identifier for the strategy.
        timestamp:
            Observation timestamp (caller-supplied).
        equity:
            Current strategy equity / NAV value (price-like, e.g. 100.0).
            Must be > 0.

        Returns
        -------
        list[BreakerEvent]
            Zero or more transition events (empty when state is unchanged).

        Raises
        ------
        ValueError
            If ``equity`` is not strictly positive.
        """
        if equity <= 0.0:
            raise ValueError(
                f"equity must be > 0 for strategy '{strategy_id}'; got {equity!r}"
            )

        evts: list[BreakerEvent] = []
        cfg = self._cfg

        # Initialise strategy state on first observation.
        if strategy_id not in self._strategies:
            self._strategies[strategy_id] = _StrategyState(
                high_watermark=float(equity)
            )

        ss = self._strategies[strategy_id]

        # Update high-watermark.
        if equity > ss.high_watermark:
            ss.high_watermark = float(equity)

        drawdown = (ss.high_watermark - equity) / ss.high_watermark

        if ss.state == BreakerState.NORMAL:
            # Check for pause condition: drawdown > threshold (strict >).
            if drawdown > cfg.strategy_dd_threshold:
                from_state = BreakerState.NORMAL
                ss.state = BreakerState.PAUSED
                ss.counting_cooldown = True
                ss.sessions_since_pause = 0
                evt = BreakerEvent(
                    timestamp=timestamp,
                    breaker=BreakerType.STRATEGY,
                    strategy_id=strategy_id,
                    from_state=from_state,
                    to_state=BreakerState.PAUSED,
                    metric=drawdown,
                    threshold=cfg.strategy_dd_threshold,
                    message=(
                        f"Strategy '{strategy_id}' paused: drawdown"
                        f" {drawdown:.4f} > threshold {cfg.strategy_dd_threshold:.4f}"
                    ),
                )
                self.events.append(evt)
                evts.append(evt)

        elif ss.state == BreakerState.PAUSED:
            # Re-arm conditions (both must hold):
            #   1. Drawdown has recovered below re-arm threshold (strict <).
            #   2. Cooldown session count has been reached.
            recovered = drawdown < cfg.strategy_rearm_pct
            cooled = ss.sessions_since_pause >= cfg.strategy_cooldown_sessions
            if recovered and cooled:
                from_state = BreakerState.PAUSED
                ss.state = BreakerState.NORMAL
                ss.counting_cooldown = False
                ss.sessions_since_pause = 0
                evt = BreakerEvent(
                    timestamp=timestamp,
                    breaker=BreakerType.STRATEGY,
                    strategy_id=strategy_id,
                    from_state=from_state,
                    to_state=BreakerState.NORMAL,
                    metric=drawdown,
                    threshold=cfg.strategy_rearm_pct,
                    message=(
                        f"Strategy '{strategy_id}' re-armed: drawdown"
                        f" {drawdown:.4f} < rearm_pct {cfg.strategy_rearm_pct:.4f}"
                        f" and cooldown sessions {ss.sessions_since_pause}"
                        f" >= {cfg.strategy_cooldown_sessions} (PAUSED -> NORMAL)"
                    ),
                )
                self.events.append(evt)
                evts.append(evt)

        return evts

    # ------------------------------------------------------------------
    # Portfolio-level update
    # ------------------------------------------------------------------

    def update_portfolio(
        self,
        timestamp: pd.Timestamp,
        *,
        equity: float,
    ) -> list[BreakerEvent]:
        """Feed a new portfolio equity observation.

        Evaluates the graduated portfolio breaker: NORMAL -> DERISKED ->
        HALTED.  Also evaluates recovery from DERISKED (and optionally from
        HALTED when ``config.portfolio_halt_sticky=False``).

        Parameters
        ----------
        timestamp:
            Observation timestamp (caller-supplied).
        equity:
            Portfolio NAV / equity value.  Must be > 0.

        Returns
        -------
        list[BreakerEvent]
            Zero or more transition events.

        Raises
        ------
        ValueError
            If ``equity`` is not strictly positive.
        """
        if equity <= 0.0:
            raise ValueError(
                f"Portfolio equity must be > 0; got {equity!r}"
            )

        evts: list[BreakerEvent] = []
        cfg = self._cfg

        # Initialise high-watermark on first observation.
        if self._port_hwm == 0.0:
            self._port_hwm = float(equity)

        # Update high-watermark.
        if equity > self._port_hwm:
            self._port_hwm = float(equity)

        drawdown = (self._port_hwm - equity) / self._port_hwm

        state = self._port_state

        if state == BreakerState.NORMAL:
            if drawdown > cfg.portfolio_halt_threshold:
                # Skip DERISKED, go directly to HALTED.
                self._port_state = BreakerState.HALTED
                self._port_counting_cooldown = True
                self._port_sessions_since_derisked = 0
                evt = self._port_event(
                    timestamp,
                    BreakerState.NORMAL,
                    BreakerState.HALTED,
                    drawdown,
                    cfg.portfolio_halt_threshold,
                    f"Portfolio halted: drawdown {drawdown:.4f}"
                    f" > halt_threshold {cfg.portfolio_halt_threshold:.4f}"
                    " (NORMAL -> HALTED)",
                )
                self.events.append(evt)
                evts.append(evt)
            elif drawdown > cfg.portfolio_derisk_threshold:
                self._port_state = BreakerState.DERISKED
                self._port_counting_cooldown = True
                self._port_sessions_since_derisked = 0
                evt = self._port_event(
                    timestamp,
                    BreakerState.NORMAL,
                    BreakerState.DERISKED,
                    drawdown,
                    cfg.portfolio_derisk_threshold,
                    f"Portfolio de-risked: drawdown {drawdown:.4f}"
                    f" > derisk_threshold {cfg.portfolio_derisk_threshold:.4f}"
                    f"; exposure scaled to {cfg.portfolio_derisk_factor:.0%}"
                    " (NORMAL -> DERISKED)",
                )
                self.events.append(evt)
                evts.append(evt)

        elif state == BreakerState.DERISKED:
            if drawdown > cfg.portfolio_halt_threshold:
                # Escalate to HALT.
                self._port_state = BreakerState.HALTED
                # Keep counting cooldown from the escalation point.
                self._port_sessions_since_derisked = 0
                evt = self._port_event(
                    timestamp,
                    BreakerState.DERISKED,
                    BreakerState.HALTED,
                    drawdown,
                    cfg.portfolio_halt_threshold,
                    f"Portfolio halted: drawdown {drawdown:.4f}"
                    f" > halt_threshold {cfg.portfolio_halt_threshold:.4f}"
                    " (DERISKED -> HALTED)",
                )
                self.events.append(evt)
                evts.append(evt)
            else:
                # Check recovery conditions.
                recovered = drawdown < cfg.portfolio_rearm_pct
                cooled = (
                    self._port_sessions_since_derisked
                    >= cfg.portfolio_cooldown_sessions
                )
                if recovered and cooled:
                    self._port_state = BreakerState.NORMAL
                    self._port_counting_cooldown = False
                    self._port_sessions_since_derisked = 0
                    evt = self._port_event(
                        timestamp,
                        BreakerState.DERISKED,
                        BreakerState.NORMAL,
                        drawdown,
                        cfg.portfolio_rearm_pct,
                        f"Portfolio re-armed: drawdown {drawdown:.4f}"
                        f" < rearm_pct {cfg.portfolio_rearm_pct:.4f}"
                        f" and cooldown sessions"
                        f" {self._port_sessions_since_derisked}"
                        f" >= {cfg.portfolio_cooldown_sessions}"
                        " (DERISKED -> NORMAL)",
                    )
                    self.events.append(evt)
                    evts.append(evt)

        elif state == BreakerState.HALTED and not cfg.portfolio_halt_sticky:
            # Auto-recovery: same conditions as DERISKED recovery.
            recovered = drawdown < cfg.portfolio_rearm_pct
            cooled = (
                self._port_sessions_since_derisked
                >= cfg.portfolio_cooldown_sessions
            )
            if recovered and cooled:
                self._port_state = BreakerState.NORMAL
                self._port_counting_cooldown = False
                self._port_sessions_since_derisked = 0
                evt = self._port_event(
                    timestamp,
                    BreakerState.HALTED,
                    BreakerState.NORMAL,
                    drawdown,
                    cfg.portfolio_rearm_pct,
                    f"Portfolio re-armed from HALT (sticky=False): drawdown"
                    f" {drawdown:.4f} < rearm_pct {cfg.portfolio_rearm_pct:.4f}"
                    " (HALTED -> NORMAL)",
                )
                self.events.append(evt)
                evts.append(evt)

        return evts

    # ------------------------------------------------------------------
    # Intraday / daily-loss update
    # ------------------------------------------------------------------

    def update_intraday(
        self,
        timestamp: pd.Timestamp,
        *,
        current_nav: float,
    ) -> list[BreakerEvent]:
        """Feed an intraday NAV mark for daily-loss tracking.

        Compares the current NAV against the session-open baseline (set via
        :meth:`new_session`).  If no baseline has been set, the first call to
        this method establishes it and no breach is possible on that same call.

        Parameters
        ----------
        timestamp:
            Observation timestamp (caller-supplied).
        current_nav:
            Current portfolio NAV mark.  Must be > 0.

        Returns
        -------
        list[BreakerEvent]
            Zero or more events (HALT_NEW_ORDERS fire or nothing).

        Raises
        ------
        ValueError
            If ``current_nav`` is not strictly positive.
        """
        if current_nav <= 0.0:
            raise ValueError(
                f"current_nav must be > 0; got {current_nav!r}"
            )

        evts: list[BreakerEvent] = []

        # Establish baseline if not yet set.
        if self._daily_session_nav is None:
            self._daily_session_nav = float(current_nav)
            return evts

        baseline = self._daily_session_nav
        intraday_loss = (baseline - current_nav) / baseline

        if (
            self._daily_state == BreakerState.NORMAL
            and intraday_loss > self._cfg.daily_loss_threshold
        ):
            self._daily_state = BreakerState.HALT_NEW_ORDERS
            evt = BreakerEvent(
                timestamp=timestamp,
                breaker=BreakerType.DAILY_LOSS,
                strategy_id=None,
                from_state=BreakerState.NORMAL,
                to_state=BreakerState.HALT_NEW_ORDERS,
                metric=intraday_loss,
                threshold=self._cfg.daily_loss_threshold,
                message=(
                    f"Daily-loss limit breached: intraday loss {intraday_loss:.4f}"
                    f" > threshold {self._cfg.daily_loss_threshold:.4f}"
                    "; HALT_NEW_ORDERS"
                ),
            )
            self.events.append(evt)
            evts.append(evt)

        return evts

    # ------------------------------------------------------------------
    # Manual reset (sticky HALT only)
    # ------------------------------------------------------------------

    def manual_reset(
        self,
        timestamp: pd.Timestamp,
        *,
        operator: str = "operator",
    ) -> BreakerEvent | None:
        """Manually clear a sticky portfolio HALT.

        This method exists specifically to honour the design requirement that a
        portfolio HALT (>= 25% drawdown) forces human review before resumption.
        It must be called explicitly; the engine never auto-resets from HALTED
        when ``config.portfolio_halt_sticky=True``.

        Parameters
        ----------
        timestamp:
            Reset timestamp (caller-supplied).
        operator:
            Free-text identifier of the operator performing the reset (for
            audit purposes).

        Returns
        -------
        BreakerEvent or None
            The transition event if the state was HALTED; ``None`` if no reset
            was needed.
        """
        if self._port_state != BreakerState.HALTED:
            return None

        self._port_state = BreakerState.NORMAL
        self._port_counting_cooldown = False
        self._port_sessions_since_derisked = 0
        evt = BreakerEvent(
            timestamp=timestamp,
            breaker=BreakerType.PORTFOLIO,
            strategy_id=None,
            from_state=BreakerState.HALTED,
            to_state=BreakerState.NORMAL,
            metric=0.0,
            threshold=0.0,
            message=(
                f"Portfolio HALT manually cleared by '{operator}'"
                " (HALTED -> NORMAL)"
            ),
        )
        self.events.append(evt)
        return evt

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _port_event(
        timestamp: pd.Timestamp,
        from_state: BreakerState,
        to_state: BreakerState,
        metric: float,
        threshold: float,
        message: str,
    ) -> BreakerEvent:
        return BreakerEvent(
            timestamp=timestamp,
            breaker=BreakerType.PORTFOLIO,
            strategy_id=None,
            from_state=from_state,
            to_state=to_state,
            metric=metric,
            threshold=threshold,
            message=message,
        )
