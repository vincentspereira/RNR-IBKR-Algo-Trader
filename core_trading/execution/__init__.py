"""Execution layer (master plan Phase 9, extending Phase 4).

Provides execution-algorithm scheduling and live executors, market
impact models, transaction cost analysis, adverse-selection
monitoring, smart order routing, and the order lifecycle / broker
reconciliation machinery.

Package contents
----------------
:mod:`core_trading.execution.algo_orders` -- async TWAP / VWAP executors
:mod:`core_trading.execution.advanced_orders` -- trailing stop, bracket,
    OCO, OTO, iceberg order state machines
:mod:`core_trading.execution.pairs_execution` -- Phase 4 atomic
    both-legs-or-none pairs execution with TWAP slicing
:mod:`core_trading.execution.exec_algorithms` -- Phase 9.1 schedule
    generators: Almgren-Chriss closed-form implementation-shortfall
    trajectories, efficient frontier, POV, arrival price, adaptive
    liquidity-seeking, iceberg clip helper
:mod:`core_trading.execution.smart_order_router` -- Phase 9.2 smart
    order router with venue analytics (smoothed fill probability,
    latency, post-fill markout) and TCA-ready routing rationale log
:mod:`core_trading.execution.impact_models` -- Phase 9.3 market impact:
    Almgren-Chriss square-root, Obizhaeva-Wang resilience decay,
    Kissell-Glantz I-Star, and fills-based calibration
:mod:`core_trading.execution.tca` -- Phase 9.4 transaction cost
    analysis: arrival / VWAP slippage, Perold implementation
    shortfall, markouts, cost attribution, daily ASCII report + CLI
:mod:`core_trading.execution.adverse_selection` -- Phase 9.5 VPIN
    (bulk volume classification) toxicity, markout drift detection,
    auto-pause monitor (closes the Phase 5 VPIN deferral)
:mod:`core_trading.execution.lifecycle` -- Phase 9.6 order state
    machine (NEW -> ACK -> PARTIAL -> FILLED / CANCELLED / REJECTED)
    with audit trail, duplicate-event dedup, and daily broker
    reconciliation with mismatch classification and alert hooks

Conventions
-----------
* Costs / slippage / markouts are side-signed so positive = cost or
  adverse move to the trader (repo-wide positive-loss convention).
* Schedule generators are pure and deterministic; executors own I/O.
"""

from .adverse_selection import (
    DEFAULT_CONFIG as DEFAULT_ADVERSE_SELECTION_CONFIG,
)
from .adverse_selection import (
    AdverseSelectionConfig,
    DriftVerdict,
    ExecutionToxicityMonitor,
    MonitorState,
    ToxicityEvent,
    ToxicityVerdict,
    TriggerType,
    bulk_volume_classify,
    markout_drift,
    toxicity_check,
    volume_buckets,
    vpin,
)
from .algo_orders import (
    AlgoConfig,
    AlgoOrder,
    AlgoOrderResult,
    SliceResult,
    TWAPExecutor,
    VolumeProfile,
    VWAPExecutor,
)
from .exec_algorithms import (
    ACParams,
    ACSchedule,
    ac_trajectory,
    adaptive_liquidity_schedule,
    arrival_price_schedule,
    efficient_frontier,
    iceberg_clip_sizes,
    pov_schedule,
    validate_schedule,
)
from .impact_models import (
    ACParams as ImpactACParams,
)
from .impact_models import (
    CalibrationResult,
    IStarParams,
    OWParams,
    ac_permanent_impact,
    ac_schedule_cost,
    ac_slice_cost,
    ac_temporary_impact,
    calibrate_impact,
    expected_cost_bps,
    istar_impact,
    kissell_glantz_cost,
    ow_impact_path,
    ow_schedule_cost,
)
from .lifecycle import (
    BROKER_FILL_COLUMNS,
    DEFAULT_RECON_CONFIG,
    INTERNAL_FILL_COLUMNS,
    AckEvent,
    AuditRecord,
    CancelEvent,
    FillEvent,
    IllegalTransitionError,
    LifecycleTracker,
    Mismatch,
    MismatchClass,
    OrderEvent,
    OrderLifecycle,
    OrderState,
    OverfillError,
    ReconciliationAlert,
    ReconciliationConfig,
    ReconciliationReport,
    RejectEvent,
    reconcile,
    render_reconciliation,
    run_daily_reconciliation,
)
from .pairs_execution import (
    DeterministicFillModel,
    ExecutionConfig,
    FillModel,
    Leg,
    LegFill,
    PairExecutionResult,
    PairExecutor,
    PairOrder,
    twap_schedule,
)
from .smart_order_router import (
    AnalyticsConfig,
    RoutingConfig,
    RoutingDecision,
    RoutingRationale,
    SmartOrderRouter,
    VenueAnalytics,
    VenueAnalyticsSnapshot,
    VenueConfig,
    VenueScore,
    VenueScoreRecord,
    VenueStats,
)
from .tca import (
    REQUIRED_FILL_COLUMNS,
    DailyTCAReport,
    FillTCA,
    TCAConfig,
    arrival_slippage_bps,
    attribute_cost,
    build_daily_tca_report,
    compute_fill_tca,
    implementation_shortfall,
    markouts,
    render_report,
    vwap_slippage_bps,
)

__all__ = [
    # algo executors (legacy + Phase 4)
    "AlgoConfig",
    "AlgoOrder",
    "AlgoOrderResult",
    "SliceResult",
    "TWAPExecutor",
    "VWAPExecutor",
    "VolumeProfile",
    # pairs execution (Phase 4.7)
    "Leg",
    "PairOrder",
    "LegFill",
    "PairExecutionResult",
    "FillModel",
    "DeterministicFillModel",
    "ExecutionConfig",
    "twap_schedule",
    "PairExecutor",
    # schedule generators (9.1)
    "ACParams",
    "ACSchedule",
    "ac_trajectory",
    "efficient_frontier",
    "pov_schedule",
    "arrival_price_schedule",
    "adaptive_liquidity_schedule",
    "iceberg_clip_sizes",
    "validate_schedule",
    # smart order router + venue analytics (9.2)
    "VenueConfig",
    "VenueStats",
    "VenueScore",
    "RoutingDecision",
    "RoutingConfig",
    "SmartOrderRouter",
    "AnalyticsConfig",
    "VenueAnalytics",
    "VenueAnalyticsSnapshot",
    "VenueScoreRecord",
    "RoutingRationale",
    # impact models (9.3)
    "ImpactACParams",
    "OWParams",
    "IStarParams",
    "CalibrationResult",
    "ac_temporary_impact",
    "ac_permanent_impact",
    "ac_slice_cost",
    "ac_schedule_cost",
    "ow_impact_path",
    "ow_schedule_cost",
    "istar_impact",
    "kissell_glantz_cost",
    "calibrate_impact",
    "expected_cost_bps",
    # TCA (9.4)
    "TCAConfig",
    "FillTCA",
    "DailyTCAReport",
    "REQUIRED_FILL_COLUMNS",
    "arrival_slippage_bps",
    "vwap_slippage_bps",
    "implementation_shortfall",
    "attribute_cost",
    "markouts",
    "compute_fill_tca",
    "build_daily_tca_report",
    "render_report",
    # adverse selection (9.5)
    "AdverseSelectionConfig",
    "DEFAULT_ADVERSE_SELECTION_CONFIG",
    "MonitorState",
    "TriggerType",
    "ToxicityVerdict",
    "DriftVerdict",
    "ToxicityEvent",
    "bulk_volume_classify",
    "volume_buckets",
    "vpin",
    "toxicity_check",
    "markout_drift",
    "ExecutionToxicityMonitor",
    # lifecycle + reconciliation (9.6)
    "OrderState",
    "AckEvent",
    "FillEvent",
    "CancelEvent",
    "RejectEvent",
    "OrderEvent",
    "AuditRecord",
    "OrderLifecycle",
    "LifecycleTracker",
    "IllegalTransitionError",
    "OverfillError",
    "MismatchClass",
    "ReconciliationConfig",
    "Mismatch",
    "ReconciliationReport",
    "ReconciliationAlert",
    "reconcile",
    "run_daily_reconciliation",
    "render_reconciliation",
    "DEFAULT_RECON_CONFIG",
    "INTERNAL_FILL_COLUMNS",
    "BROKER_FILL_COLUMNS",
]
