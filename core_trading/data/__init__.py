"""Phase 1 data infrastructure.

Implements the data layer described in
:doc:`docs/QUANT_TRADING_MASTER_PLAN.md` Phase 1. Built free-vendor-first per
:doc:`docs/FREE_DATA_VENDORS.md`; paid vendors are revisited only before
live-trading capital allocation.

Sub-modules:

* :mod:`core_trading.data.universe` -- universe construction (survivorship-bias aware)
* :mod:`core_trading.data.bars` -- OHLCV bar data abstraction
* :mod:`core_trading.data.corporate_actions` -- splits, dividends
* :mod:`core_trading.data.fundamentals` -- point-in-time fundamentals
* :mod:`core_trading.data.alternative` -- news, options flow, sentiment scaffolding
* :mod:`core_trading.data.quality` -- cross-source validation, gap/spike detection
* :mod:`core_trading.data.sources` -- per-vendor adapters (yfinance, IBKR, FRED, EDGAR, ...)
"""

from core_trading.data.bars import Bar, BarRequest, BarResolution, BarSource
from core_trading.data.corporate_actions import (
    CorporateAction,
    CorporateActionSource,
    CorporateActionType,
    adjustment_factors,
    apply_adjustments,
    total_return_index,
)
from core_trading.data.fundamentals import (
    FundamentalRecord,
    FundamentalRequest,
    FundamentalSource,
    StatementType,
)
from core_trading.data.macro import MacroSeries, MacroSource
from core_trading.data.reference import (
    ReferenceData,
    SectorAssignment,
    SymbolChange,
    build_starter_reference,
)
from core_trading.data.storage import BarStore, CachingBarSource, get_bar_store
from core_trading.data.universe import Universe, UniverseMembership

__all__ = [
    "Bar",
    "BarRequest",
    "BarResolution",
    "BarSource",
    "CorporateAction",
    "CorporateActionSource",
    "CorporateActionType",
    "adjustment_factors",
    "apply_adjustments",
    "total_return_index",
    "FundamentalRecord",
    "FundamentalRequest",
    "FundamentalSource",
    "StatementType",
    "MacroSeries",
    "MacroSource",
    "ReferenceData",
    "SectorAssignment",
    "SymbolChange",
    "build_starter_reference",
    "BarStore",
    "CachingBarSource",
    "get_bar_store",
    "Universe",
    "UniverseMembership",
]
