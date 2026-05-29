"""Point-in-time fundamental data abstraction.

Defines :class:`FundamentalRecord` and the :class:`FundamentalSource` interface
that EDGAR / Sharadar / yfinance-fundamentals adapters implement.

Per master plan Phase 1.4: a fundamental record is **point-in-time correct**
only if it carries both a ``period_end`` (the fiscal-period this number
describes) and a ``filing_date`` (the date the issuer actually disclosed it
publicly). Backtests use ``filing_date`` as the as-of cut: data is allowed in
the model only after it was filed.

Restated values are tracked via :attr:`revision_id` so a vendor that pushes
"latest" instead of "as-reported" can still be reconciled.
"""
from __future__ import annotations

import abc
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import Enum

import pandas as pd


class StatementType(str, Enum):
    """Standard financial statement classification."""

    INCOME = "income"
    BALANCE_SHEET = "balance_sheet"
    CASH_FLOW = "cash_flow"
    KEY_RATIO = "key_ratio"


@dataclass(frozen=True, slots=True)
class FundamentalRecord:
    """One numeric fundamental fact disclosed by an issuer.

    A complete 10-Q or 10-K expands into many records (revenue, COGS, total
    assets, etc.). Each record is a single number with full attribution so
    backtests can ask "what was X on date Y?" without leakage.
    """

    symbol: str
    statement: StatementType
    metric: str
    value: float
    period_end: date
    filing_date: date
    fiscal_period: str
    revision_id: int = 0
    source: str = ""

    def __post_init__(self) -> None:
        if self.period_end > self.filing_date:
            raise ValueError(
                f"FundamentalRecord.filing_date ({self.filing_date}) cannot precede "
                f"period_end ({self.period_end}) for {self.symbol}/{self.metric}"
            )


@dataclass(frozen=True, slots=True)
class FundamentalRequest:
    """Query descriptor for fundamentals."""

    symbols: tuple[str, ...]
    statements: tuple[StatementType, ...]
    start_period: date
    end_period: date
    as_of: date | None = None

    def __post_init__(self) -> None:
        if not self.symbols:
            raise ValueError("FundamentalRequest.symbols cannot be empty")
        if not self.statements:
            raise ValueError("FundamentalRequest.statements cannot be empty")
        if self.start_period >= self.end_period:
            raise ValueError("FundamentalRequest.start_period must precede end_period")


class FundamentalSource(abc.ABC):
    """Abstract base for fundamental-data adapters."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Adapter identifier; used as ``FundamentalRecord.source``."""

    @property
    @abc.abstractmethod
    def is_point_in_time(self) -> bool:
        """``True`` if this source reports as-filed values with filing dates.

        Adapters wrapping yfinance return ``False`` here because Yahoo returns
        restated values without filing-date attribution. Adapters wrapping
        EDGAR or Sharadar return ``True``.
        """

    @abc.abstractmethod
    async def fetch(self, request: FundamentalRequest) -> Sequence[FundamentalRecord]:
        """Fetch fundamental records matching ``request``.

        Adapters MUST respect ``request.as_of`` when set: records with
        ``filing_date > as_of`` are excluded. Sources that cannot honour this
        constraint (i.e. ``is_point_in_time == False``) MUST raise
        :class:`RuntimeError` when ``as_of`` is provided.
        """

    @staticmethod
    def records_to_dataframe(records: Sequence[FundamentalRecord]) -> pd.DataFrame:
        """Convert a sequence of records to a tidy DataFrame for analysis."""
        if not records:
            return pd.DataFrame(
                columns=[
                    "symbol",
                    "statement",
                    "metric",
                    "value",
                    "period_end",
                    "filing_date",
                    "fiscal_period",
                    "revision_id",
                    "source",
                ]
            )
        return pd.DataFrame(
            [
                {
                    "symbol": r.symbol,
                    "statement": r.statement.value,
                    "metric": r.metric,
                    "value": r.value,
                    "period_end": r.period_end,
                    "filing_date": r.filing_date,
                    "fiscal_period": r.fiscal_period,
                    "revision_id": r.revision_id,
                    "source": r.source,
                }
                for r in records
            ]
        )
