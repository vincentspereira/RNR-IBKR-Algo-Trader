"""Capital allocation across strategies and the strategy lifecycle (Phase 8.3).

This module governs *how much real money* each strategy is allowed to run,
layered on top of the Phase 6 multi-strategy allocator
(:func:`core_trading.portfolio.strategy_allocator.allocate_strategies`).  The
allocator answers "what is the risk-optimal split across strategies?"; this
module answers "which strategies have *earned* live capital, and how much may
they hold given where they are in their lifecycle?".

Strategy lifecycle
-------------------
Every strategy progresses through an explicit, irreversible-forward ladder::

    RESEARCH  ->  PAPER  ->  SMALL_LIVE  ->  SCALED_LIVE
                                    \\           /
                                     -> DECOMMISSIONED (terminal)

* ``RESEARCH``       -- backtest / signal-development only; zero live capital.
* ``PAPER``          -- forward paper trading; zero live capital.  A strategy
  is promoted to ``SMALL_LIVE`` only after it has accrued enough clean paper
  days and its paper Sharpe has not degraded materially from the research-era
  reference Sharpe.
* ``SMALL_LIVE``     -- a fixed, small live allocation (``initial_live_capital``,
  default 5,000) is granted *regardless of backtest quality*.  The point of
  this stage is to surface execution / microstructure / data issues that paper
  trading hides, with a loss that is affordable.
* ``SCALED_LIVE``    -- the strategy has proven that its LIVE Sharpe tracks its
  paper Sharpe (within ``max_sharpe_shortfall``) over a clean window
  (``min_clean_days``); capital is scaled up multiplicatively
  (``scale_step_factor``) up to ``max_strategy_capital`` and the Phase 6
  allocator weight is allowed to size it.
* ``DECOMMISSIONED`` -- terminal.  Reached when live Sharpe stays negative for
  ``decommission_live_sharpe_days``, or paper Sharpe degrades beyond
  ``paper_degradation_limit`` of the research reference.  Zero live capital.

Design principles (shared with the rest of the money layer)
-----------------------------------------------------------
* Pure functions only -- :func:`evaluate_lifecycle` and
  :func:`allocate_live_capital` read their inputs and return typed results; no
  wall-clock reads, no I/O, no mutation of the input records.
* Machine-readable decisions -- :class:`LifecycleDecision` names which trigger
  fired and reports the observed value against the configured limit so the
  caller can log / alert deterministically.
* Conventions match Phase 7: Sharpe inputs are per-bar (annualisation is the
  caller's choice and is scale-free at the default-zero thresholds).

References
----------
* Bailey, D. & Lopez de Prado, M. (2014). "The Deflated Sharpe Ratio."
  Journal of Portfolio Management, 40(5).  (Live-vs-backtest degradation is
  the expected failure mode of over-fit strategies; small-live capital and the
  shortfall gate are the practical defence.)
* Chan, E. (2013). "Algorithmic Trading: Winning Strategies and Their
  Rationale."  Wiley.  (Incremental capital deployment / paper-to-live ramp.)
"""
from __future__ import annotations

import enum
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

__all__ = [
    "StrategyStage",
    "LifecycleAction",
    "LifecycleConfig",
    "StrategyRecord",
    "LifecycleDecision",
    "evaluate_lifecycle",
    "allocate_live_capital",
    "DEFAULT_LIFECYCLE_CONFIG",
]


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class StrategyStage(enum.StrEnum):
    """Lifecycle stage of a strategy (see module docstring).

    RESEARCH
        Backtest / development only; no live capital.
    PAPER
        Forward paper trading; no live capital.
    SMALL_LIVE
        Fixed small live allocation to surface execution issues.
    SCALED_LIVE
        Proven live; allocator-sized up to ``max_strategy_capital``.
    DECOMMISSIONED
        Terminal; retired strategy, no live capital.
    """

    RESEARCH = "RESEARCH"
    PAPER = "PAPER"
    SMALL_LIVE = "SMALL_LIVE"
    SCALED_LIVE = "SCALED_LIVE"
    DECOMMISSIONED = "DECOMMISSIONED"


class LifecycleAction(enum.StrEnum):
    """The action recommended by :func:`evaluate_lifecycle`.

    HOLD
        Stay at the current stage; no change.
    PROMOTE
        Advance one stage (PAPER -> SMALL_LIVE).
    SCALE_UP
        Increase live capital (SMALL_LIVE -> SCALED_LIVE, or grow an
        already-scaled allocation by ``scale_step_factor``).
    DECOMMISSION
        Retire the strategy to the terminal ``DECOMMISSIONED`` stage.
    """

    HOLD = "HOLD"
    PROMOTE = "PROMOTE"
    SCALE_UP = "SCALE_UP"
    DECOMMISSION = "DECOMMISSION"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LifecycleConfig:
    """Immutable lifecycle-transition thresholds.

    Attributes
    ----------
    initial_live_capital:
        Fixed small live capital granted on promotion to ``SMALL_LIVE``,
        in account currency.  Deliberately FLAT regardless of backtest
        quality -- the small-live stage exists to discover execution issues
        with an affordable loss, not to size by conviction.  Default 5,000.
    min_clean_days:
        Minimum number of consecutive incident-free days at the current
        stage before a time-based scaling step is allowed.  Default 30.
    max_sharpe_shortfall:
        Maximum fractional shortfall of LIVE Sharpe below PAPER Sharpe that
        still permits scaling, in ``[0, 1]``.  A value of ``0.30`` means the
        live Sharpe must be at least ``0.70 * paper_sharpe`` to scale up.
        Default 0.30.
    decommission_live_sharpe_days:
        Number of days for which the trailing live Sharpe may remain below
        zero before the strategy is decommissioned.  Default 60.
    paper_degradation_limit:
        Maximum fractional degradation of PAPER Sharpe relative to the
        research-era reference Sharpe before decommission, in ``[0, 1]``.
        ``0.50`` means a paper Sharpe that falls below half the reference
        triggers retirement.  Default 0.50.
    paper_promotion_min_ratio:
        Minimum ratio of PAPER Sharpe to the research reference Sharpe
        required to PROMOTE to small live, in ``[0, 1]``.  Distinct from
        (and stricter than) the decommission floor: a paper Sharpe in the
        band ``[(1 - paper_degradation_limit), paper_promotion_min_ratio)``
        of the reference is too weak to promote but not weak enough to
        retire -- the strategy simply HOLDs in paper.  Must be
        ``>= 1 - paper_degradation_limit`` so the band is well-formed.
        Default 0.80.
    scale_step_factor:
        Multiplicative capital step on each ``SCALE_UP`` (e.g. ``2.0``
        doubles the allocation).  Must be ``> 1``.  Default 2.0.
    max_strategy_capital:
        Hard ceiling on any single strategy's live capital, in account
        currency.  Default 100,000.
    """

    initial_live_capital: float = 5_000.0
    min_clean_days: int = 30
    max_sharpe_shortfall: float = 0.30
    decommission_live_sharpe_days: int = 60
    paper_degradation_limit: float = 0.50
    paper_promotion_min_ratio: float = 0.80
    scale_step_factor: float = 2.0
    max_strategy_capital: float = 100_000.0

    def __post_init__(self) -> None:
        """Validate parameter consistency."""
        if self.initial_live_capital <= 0:
            raise ValueError(
                f"initial_live_capital must be positive; "
                f"got {self.initial_live_capital}"
            )
        if self.min_clean_days < 1:
            raise ValueError(
                f"min_clean_days must be >= 1; got {self.min_clean_days}"
            )
        if not 0.0 <= self.max_sharpe_shortfall <= 1.0:
            raise ValueError(
                f"max_sharpe_shortfall must be in [0, 1]; "
                f"got {self.max_sharpe_shortfall}"
            )
        if self.decommission_live_sharpe_days < 1:
            raise ValueError(
                f"decommission_live_sharpe_days must be >= 1; "
                f"got {self.decommission_live_sharpe_days}"
            )
        if not 0.0 <= self.paper_degradation_limit <= 1.0:
            raise ValueError(
                f"paper_degradation_limit must be in [0, 1]; "
                f"got {self.paper_degradation_limit}"
            )
        if not 0.0 <= self.paper_promotion_min_ratio <= 1.0:
            raise ValueError(
                f"paper_promotion_min_ratio must be in [0, 1]; "
                f"got {self.paper_promotion_min_ratio}"
            )
        if self.paper_promotion_min_ratio < 1.0 - self.paper_degradation_limit:
            raise ValueError(
                f"paper_promotion_min_ratio ({self.paper_promotion_min_ratio}) "
                f"must be >= 1 - paper_degradation_limit "
                f"({1.0 - self.paper_degradation_limit})"
            )
        if self.scale_step_factor <= 1.0:
            raise ValueError(
                f"scale_step_factor must be > 1; got {self.scale_step_factor}"
            )
        if self.max_strategy_capital < self.initial_live_capital:
            raise ValueError(
                f"max_strategy_capital ({self.max_strategy_capital}) must be "
                f">= initial_live_capital ({self.initial_live_capital})"
            )


# Module-level singleton default (satisfies ruff B008 -- no call in defaults).
DEFAULT_LIFECYCLE_CONFIG = LifecycleConfig()


# ---------------------------------------------------------------------------
# Records and decisions
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StrategyRecord:
    """Immutable snapshot of one strategy's lifecycle state.

    All Sharpe inputs are per-bar (matching the Phase 6 allocator and the
    Phase 7 risk layer).  ``None`` marks a Sharpe that is not yet observable
    at the current stage (e.g. a paper strategy has no ``live_sharpe``).

    Attributes
    ----------
    strategy_id:
        Stable identifier; must match the Phase 6 allocator column name.
    stage:
        Current :class:`StrategyStage`.
    capital:
        Current live capital held by the strategy, in account currency.
        Zero for RESEARCH / PAPER / DECOMMISSIONED.
    days_at_stage:
        Calendar days the strategy has spent at the current stage.
    clean_days:
        Consecutive incident-free days at the current stage
        (``clean_days <= days_at_stage``).  Reset to 0 whenever an incident
        occurs (see :attr:`incident_count`).
    paper_sharpe:
        Trailing paper-trading Sharpe (per bar); ``None`` before paper.
    live_sharpe:
        Trailing live Sharpe (per bar); ``None`` before going live.
    reference_sharpe:
        Research-era (backtest) Sharpe used as the degradation baseline.
    live_sharpe_negative_days:
        Number of trailing days for which live Sharpe has been below zero.
    incident_count:
        Count of operational incidents recorded at the current stage; purely
        informational for the decision (clean-day tracking drives scaling).
    """

    strategy_id: str
    stage: StrategyStage
    capital: float
    days_at_stage: int
    clean_days: int
    paper_sharpe: float | None
    live_sharpe: float | None
    reference_sharpe: float | None
    live_sharpe_negative_days: int
    incident_count: int

    def __post_init__(self) -> None:
        """Validate non-negativity invariants."""
        if self.capital < 0:
            raise ValueError(f"capital must be >= 0; got {self.capital}")
        if self.days_at_stage < 0:
            raise ValueError(
                f"days_at_stage must be >= 0; got {self.days_at_stage}"
            )
        if self.clean_days < 0:
            raise ValueError(f"clean_days must be >= 0; got {self.clean_days}")
        if self.clean_days > self.days_at_stage:
            raise ValueError(
                f"clean_days ({self.clean_days}) cannot exceed "
                f"days_at_stage ({self.days_at_stage})"
            )
        if self.live_sharpe_negative_days < 0:
            raise ValueError(
                f"live_sharpe_negative_days must be >= 0; "
                f"got {self.live_sharpe_negative_days}"
            )
        if self.incident_count < 0:
            raise ValueError(
                f"incident_count must be >= 0; got {self.incident_count}"
            )


@dataclass(frozen=True, slots=True)
class LifecycleDecision:
    """Machine-readable outcome of :func:`evaluate_lifecycle`.

    Attributes
    ----------
    strategy_id:
        The evaluated strategy.
    action:
        The recommended :class:`LifecycleAction`.
    from_stage:
        The strategy's stage at evaluation time.
    to_stage:
        The stage the action would move the strategy to (equals
        ``from_stage`` when ``action`` is ``HOLD``).
    target_capital:
        Live capital implied by the action.  For ``HOLD`` this is the
        record's current capital; for ``PROMOTE`` it is
        ``initial_live_capital``; for ``SCALE_UP`` it is the stepped capital
        capped at ``max_strategy_capital``; for ``DECOMMISSION`` it is 0.
    trigger:
        Short ASCII tag naming the rule that fired (e.g.
        ``"paper_promotion"``, ``"sharpe_shortfall_ok"``,
        ``"live_sharpe_negative"``, ``"paper_degradation"``, ``"hold"``).
    observed:
        The observed metric value that drove the decision (e.g. the live
        Sharpe, the clean-day count, or the degradation fraction).
    limit:
        The configured limit the observed value was compared against.
    reason:
        Human-readable ASCII sentence describing the decision.
    """

    strategy_id: str
    action: LifecycleAction
    from_stage: StrategyStage
    to_stage: StrategyStage
    target_capital: float
    trigger: str
    observed: float
    limit: float
    reason: str


# ---------------------------------------------------------------------------
# Lifecycle evaluation
# ---------------------------------------------------------------------------


def _decommission_check(
    record: StrategyRecord, config: LifecycleConfig
) -> LifecycleDecision | None:
    """Return a DECOMMISSION decision if any retirement trigger fired.

    Two triggers, checked in order:

    1. Live Sharpe has stayed below zero for at least
       ``decommission_live_sharpe_days`` (only meaningful once live).
    2. Paper Sharpe has degraded below ``(1 - paper_degradation_limit)`` of
       the research reference Sharpe (only meaningful with a positive
       reference and an observed paper Sharpe).

    Returns ``None`` when neither trigger applies.
    """
    is_live = record.stage in (StrategyStage.SMALL_LIVE, StrategyStage.SCALED_LIVE)
    if is_live and (
        record.live_sharpe_negative_days >= config.decommission_live_sharpe_days
    ):
        return LifecycleDecision(
            strategy_id=record.strategy_id,
            action=LifecycleAction.DECOMMISSION,
            from_stage=record.stage,
            to_stage=StrategyStage.DECOMMISSIONED,
            target_capital=0.0,
            trigger="live_sharpe_negative",
            observed=float(record.live_sharpe_negative_days),
            limit=float(config.decommission_live_sharpe_days),
            reason=(
                f"live Sharpe below zero for "
                f"{record.live_sharpe_negative_days} days "
                f">= {config.decommission_live_sharpe_days}; decommission"
            ),
        )
    if (
        record.reference_sharpe is not None
        and record.reference_sharpe > 0.0
        and record.paper_sharpe is not None
    ):
        floor = (1.0 - config.paper_degradation_limit) * record.reference_sharpe
        if record.paper_sharpe < floor:
            degradation = 1.0 - (record.paper_sharpe / record.reference_sharpe)
            return LifecycleDecision(
                strategy_id=record.strategy_id,
                action=LifecycleAction.DECOMMISSION,
                from_stage=record.stage,
                to_stage=StrategyStage.DECOMMISSIONED,
                target_capital=0.0,
                trigger="paper_degradation",
                observed=float(degradation),
                limit=float(config.paper_degradation_limit),
                reason=(
                    f"paper Sharpe degraded {degradation:.3f} "
                    f"> {config.paper_degradation_limit} of reference "
                    f"{record.reference_sharpe:.3f}; decommission"
                ),
            )
    return None


def _hold(
    record: StrategyRecord,
    trigger: str,
    observed: float,
    limit: float,
    reason: str,
) -> LifecycleDecision:
    """Build a HOLD decision keeping the record at its current stage."""
    return LifecycleDecision(
        strategy_id=record.strategy_id,
        action=LifecycleAction.HOLD,
        from_stage=record.stage,
        to_stage=record.stage,
        target_capital=record.capital,
        trigger=trigger,
        observed=observed,
        limit=limit,
        reason=reason,
    )


def evaluate_lifecycle(
    record: StrategyRecord,
    *,
    config: LifecycleConfig = DEFAULT_LIFECYCLE_CONFIG,
) -> LifecycleDecision:
    """Decide the next lifecycle action for one strategy.

    Pure function: reads ``record`` and ``config`` and returns a
    :class:`LifecycleDecision`.  Decommission triggers are evaluated FIRST
    (a failing strategy is retired before it can be promoted or scaled).

    Promotion / scaling rules
    -------------------------
    * ``RESEARCH``        -> always ``HOLD`` (promotion out of research is a
      human / data decision, not modelled here).
    * ``PAPER``           -> ``PROMOTE`` to ``SMALL_LIVE`` when the strategy
      has at least ``min_clean_days`` clean days AND a non-degraded paper
      Sharpe; otherwise ``HOLD``.
    * ``SMALL_LIVE``      -> ``SCALE_UP`` to ``SCALED_LIVE`` when it has at
      least ``min_clean_days`` clean days AND its live Sharpe is within
      ``max_sharpe_shortfall`` of its paper Sharpe; otherwise ``HOLD``.
    * ``SCALED_LIVE``     -> ``SCALE_UP`` (grow by ``scale_step_factor`` up to
      ``max_strategy_capital``) under the same clean-day + shortfall gate,
      but only while capital remains below ``max_strategy_capital``;
      otherwise ``HOLD``.
    * ``DECOMMISSIONED``  -> always ``HOLD`` (terminal).

    Parameters
    ----------
    record:
        The strategy snapshot to evaluate.
    config:
        Lifecycle thresholds; defaults to :data:`DEFAULT_LIFECYCLE_CONFIG`.

    Returns
    -------
    LifecycleDecision
    """
    # Decommission always wins.
    decommission = _decommission_check(record, config)
    if decommission is not None:
        return decommission

    if record.stage is StrategyStage.RESEARCH:
        return _hold(
            record,
            trigger="research_hold",
            observed=float(record.days_at_stage),
            limit=0.0,
            reason="research stage; promotion to paper is a manual decision",
        )

    if record.stage is StrategyStage.DECOMMISSIONED:
        return _hold(
            record,
            trigger="terminal",
            observed=0.0,
            limit=0.0,
            reason="decommissioned is terminal; no further action",
        )

    if record.stage is StrategyStage.PAPER:
        return _evaluate_paper(record, config)

    if record.stage is StrategyStage.SMALL_LIVE:
        return _evaluate_small_live(record, config)

    # SCALED_LIVE
    return _evaluate_scaled_live(record, config)


def _paper_strong_enough_to_promote(
    record: StrategyRecord, config: LifecycleConfig
) -> bool:
    """True when paper Sharpe clears the (strict) promotion floor.

    The promotion floor is ``paper_promotion_min_ratio * reference_sharpe`` --
    stricter than the decommission floor ``(1 - paper_degradation_limit) *
    reference_sharpe``.  A paper Sharpe in the band between the two is too weak
    to promote but not weak enough to retire, so the strategy HOLDs in paper.

    With no positive reference Sharpe there is nothing to compare against, so
    the gate is treated as satisfied (the clean-day gate still applies).
    """
    if (
        record.reference_sharpe is None
        or record.reference_sharpe <= 0.0
        or record.paper_sharpe is None
    ):
        return True
    floor = config.paper_promotion_min_ratio * record.reference_sharpe
    return record.paper_sharpe >= floor


def _evaluate_paper(
    record: StrategyRecord, config: LifecycleConfig
) -> LifecycleDecision:
    """PAPER -> SMALL_LIVE promotion gate."""
    if record.clean_days < config.min_clean_days:
        return _hold(
            record,
            trigger="paper_clean_days",
            observed=float(record.clean_days),
            limit=float(config.min_clean_days),
            reason=(
                f"paper clean days {record.clean_days} "
                f"< {config.min_clean_days}; hold"
            ),
        )
    if not _paper_strong_enough_to_promote(record, config):
        # Paper Sharpe is in the band between the decommission floor and the
        # (stricter) promotion floor: too weak to promote, not weak enough to
        # retire -- hold in paper.
        return _hold(
            record,
            trigger="paper_sharpe_weak",
            observed=float(record.paper_sharpe or 0.0),
            limit=float(
                config.paper_promotion_min_ratio * (record.reference_sharpe or 0.0)
            ),
            reason="paper Sharpe below promotion floor; hold",
        )
    return LifecycleDecision(
        strategy_id=record.strategy_id,
        action=LifecycleAction.PROMOTE,
        from_stage=StrategyStage.PAPER,
        to_stage=StrategyStage.SMALL_LIVE,
        target_capital=config.initial_live_capital,
        trigger="paper_promotion",
        observed=float(record.clean_days),
        limit=float(config.min_clean_days),
        reason=(
            f"paper clean days {record.clean_days} "
            f">= {config.min_clean_days} and Sharpe healthy; "
            f"promote to small live at {config.initial_live_capital}"
        ),
    )


def _sharpe_shortfall(record: StrategyRecord) -> float | None:
    """Fractional shortfall of live Sharpe below paper Sharpe.

    Returns ``None`` when the comparison is undefined (missing inputs, or a
    non-positive paper Sharpe, where a ratio is meaningless).  A negative
    return value means live Sharpe EXCEEDS paper Sharpe (no shortfall).
    """
    if (
        record.live_sharpe is None
        or record.paper_sharpe is None
        or record.paper_sharpe <= 0.0
    ):
        return None
    return 1.0 - (record.live_sharpe / record.paper_sharpe)


def _scale_gate(
    record: StrategyRecord, config: LifecycleConfig
) -> LifecycleDecision | None:
    """Shared clean-day + Sharpe-shortfall gate for scaling up.

    Returns a HOLD decision when the gate is not satisfied, else ``None``
    (caller proceeds to build the SCALE_UP decision).
    """
    if record.clean_days < config.min_clean_days:
        return _hold(
            record,
            trigger="scale_clean_days",
            observed=float(record.clean_days),
            limit=float(config.min_clean_days),
            reason=(
                f"clean days {record.clean_days} "
                f"< {config.min_clean_days}; hold"
            ),
        )
    shortfall = _sharpe_shortfall(record)
    if shortfall is None:
        return _hold(
            record,
            trigger="sharpe_undefined",
            observed=0.0,
            limit=float(config.max_sharpe_shortfall),
            reason="live/paper Sharpe comparison undefined; hold",
        )
    if shortfall > config.max_sharpe_shortfall:
        return _hold(
            record,
            trigger="sharpe_shortfall",
            observed=float(shortfall),
            limit=float(config.max_sharpe_shortfall),
            reason=(
                f"live Sharpe shortfall {shortfall:.3f} "
                f"> {config.max_sharpe_shortfall}; hold"
            ),
        )
    return None


def _evaluate_small_live(
    record: StrategyRecord, config: LifecycleConfig
) -> LifecycleDecision:
    """SMALL_LIVE -> SCALED_LIVE scaling gate."""
    gate = _scale_gate(record, config)
    if gate is not None:
        return gate
    target = min(
        record.capital * config.scale_step_factor, config.max_strategy_capital
    )
    shortfall = _sharpe_shortfall(record)
    return LifecycleDecision(
        strategy_id=record.strategy_id,
        action=LifecycleAction.SCALE_UP,
        from_stage=StrategyStage.SMALL_LIVE,
        to_stage=StrategyStage.SCALED_LIVE,
        target_capital=target,
        trigger="sharpe_shortfall_ok",
        observed=float(shortfall if shortfall is not None else 0.0),
        limit=float(config.max_sharpe_shortfall),
        reason=(
            f"clean days {record.clean_days} and live Sharpe within "
            f"{config.max_sharpe_shortfall} of paper; scale to {target}"
        ),
    )


def _evaluate_scaled_live(
    record: StrategyRecord, config: LifecycleConfig
) -> LifecycleDecision:
    """SCALED_LIVE growth gate (step capital up to the ceiling)."""
    if record.capital >= config.max_strategy_capital:
        return _hold(
            record,
            trigger="max_capital",
            observed=float(record.capital),
            limit=float(config.max_strategy_capital),
            reason=(
                f"capital {record.capital} at ceiling "
                f"{config.max_strategy_capital}; hold"
            ),
        )
    gate = _scale_gate(record, config)
    if gate is not None:
        return gate
    target = min(
        record.capital * config.scale_step_factor, config.max_strategy_capital
    )
    shortfall = _sharpe_shortfall(record)
    return LifecycleDecision(
        strategy_id=record.strategy_id,
        action=LifecycleAction.SCALE_UP,
        from_stage=StrategyStage.SCALED_LIVE,
        to_stage=StrategyStage.SCALED_LIVE,
        target_capital=target,
        trigger="sharpe_shortfall_ok",
        observed=float(shortfall if shortfall is not None else 0.0),
        limit=float(config.max_sharpe_shortfall),
        reason=(
            f"clean days {record.clean_days} and live Sharpe healthy; "
            f"grow capital to {target}"
        ),
    )


# ---------------------------------------------------------------------------
# Live-capital allocation (Phase 6 allocator tie-in -- Phase 8 DOD)
# ---------------------------------------------------------------------------


def allocate_live_capital(
    records: Sequence[StrategyRecord],
    allocator_weights: Mapping[str, float],
    *,
    total_capital: float,
    config: LifecycleConfig = DEFAULT_LIFECYCLE_CONFIG,
) -> dict[str, float]:
    """Apply lifecycle caps to the Phase 6 allocator's target weights.

    Integration contract (Phase 8 Definition-of-Done tie-in)
    --------------------------------------------------------
    The Phase 6 multi-strategy allocator
    (:func:`core_trading.portfolio.strategy_allocator.allocate_strategies`)
    returns a :class:`~core_trading.portfolio.strategy_allocator.StrategyAllocation`
    whose ``weights`` field is a ``pd.Series`` of capital FRACTIONS that sum to
    1 across *all* strategies it knows about.  Those weights answer the
    risk-optimal question only; they do NOT know about lifecycle stage.  This
    function consumes ``allocation.weights`` (passed in as a plain
    ``Mapping[str, float]`` via ``dict(allocation.weights)`` so this module
    does not depend on pandas) and overlays the lifecycle caps:

    * ``RESEARCH`` / ``PAPER``     -> 0 live capital (not live yet).
    * ``SMALL_LIVE``               -> capped at the record's own ``capital``
      (the fixed ``initial_live_capital`` or whatever small amount it holds),
      IGNORING the allocator weight.  The small-live stage is intentionally
      flat-sized.
    * ``SCALED_LIVE``              -> ``weight * total_capital`` capped at
      ``max_strategy_capital``.  This is the only stage the allocator weight
      actually sizes.
    * ``DECOMMISSIONED``           -> 0 live capital.

    A strategy present in ``records`` but absent from ``allocator_weights`` is
    treated as having weight 0 (so SCALED_LIVE strategies the allocator
    dropped receive nothing; SMALL_LIVE strategies still get their flat
    capital because that stage ignores the weight).  Allocator keys with no
    matching record raise -- the caller must keep the two in sync.

    The returned dict is NOT renormalised: it is an *absolute* per-strategy
    live-capital map in account currency.  Total deployed live capital may be
    below ``total_capital`` (research / paper / decommissioned strategies and
    the ceilings hold money back) -- the residual is uninvested cash, which is
    the intended conservative behaviour.

    Parameters
    ----------
    records:
        Lifecycle snapshots, one per strategy.  Duplicate ``strategy_id``
        values raise.
    allocator_weights:
        Phase 6 target weights (``dict(StrategyAllocation.weights)``); values
        must be finite and non-negative.
    total_capital:
        Total live capital available to deploy, in account currency
        (``> 0``).
    config:
        Lifecycle thresholds; defaults to :data:`DEFAULT_LIFECYCLE_CONFIG`.

    Returns
    -------
    dict[str, float]
        Strategy id -> absolute live capital (in account currency), one entry
        per input record, each ``>= 0``.

    Raises
    ------
    ValueError
        On non-positive ``total_capital``, duplicate record ids, invalid
        weights, or an allocator key with no matching record.
    """
    if total_capital <= 0:
        raise ValueError(f"total_capital must be positive; got {total_capital}")

    ids = [r.strategy_id for r in records]
    if len(set(ids)) != len(ids):
        raise ValueError("records contain duplicate strategy_id values.")
    id_set = set(ids)

    for name, weight in allocator_weights.items():
        if name not in id_set:
            raise ValueError(
                f"allocator weight {name!r} has no matching strategy record."
            )
        if not _is_finite_nonneg(weight):
            raise ValueError(
                f"allocator weight for {name!r} must be finite and "
                f">= 0; got {weight}"
            )

    out: dict[str, float] = {}
    for record in records:
        weight = float(allocator_weights.get(record.strategy_id, 0.0))
        if record.stage in (
            StrategyStage.RESEARCH,
            StrategyStage.PAPER,
            StrategyStage.DECOMMISSIONED,
        ):
            out[record.strategy_id] = 0.0
        elif record.stage is StrategyStage.SMALL_LIVE:
            # Flat-sized: ignore allocator weight, cap at the record capital.
            out[record.strategy_id] = min(
                record.capital, config.max_strategy_capital
            )
        else:  # SCALED_LIVE
            out[record.strategy_id] = min(
                weight * total_capital, config.max_strategy_capital
            )
    return out


def _is_finite_nonneg(value: float) -> bool:
    """True when ``value`` is a finite, non-negative real number."""
    return (
        value == value  # NaN check
        and value not in (float("inf"), float("-inf"))
        and value >= 0.0
    )
