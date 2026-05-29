"""Macro time-series abstraction.

Defines :class:`MacroSeries` and the :class:`MacroSource` interface for FRED
and similar macro-data adapters. Macro series include interest rates, CPI,
unemployment, M2, VIX, USD index, term-structure points, and so on.

Per master plan Phase 1 / 5.F.5: macro signals feed regime detection and
factor models. The interface is intentionally simple -- macro series are
sparse, low-frequency, and the cost is in source choice, not in API design.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass
from datetime import date
from enum import Enum

import pandas as pd


class MacroFrequency(str, Enum):
    """Native publication frequency of a macro series."""

    DAILY = "D"
    WEEKLY = "W"
    MONTHLY = "M"
    QUARTERLY = "Q"
    ANNUAL = "A"


@dataclass(frozen=True, slots=True)
class MacroSeries:
    """Metadata + values for one macro series."""

    series_id: str
    title: str
    frequency: MacroFrequency
    units: str
    source: str
    values: pd.Series

    def __post_init__(self) -> None:
        if not isinstance(self.values, pd.Series):
            raise TypeError("MacroSeries.values must be a pandas Series")
        if not isinstance(self.values.index, pd.DatetimeIndex):
            raise ValueError("MacroSeries.values must be indexed by DatetimeIndex")

    def as_of(self, cutoff: date) -> pd.Series:
        """Return the slice of values published on or before ``cutoff``.

        For FRED-vintage-aware adapters this may eventually use the
        as-of-date series instead of the latest series; today it filters by
        index date (good enough for series that are not heavily revised, such
        as VIX or daily yields).
        """
        ts = pd.Timestamp(cutoff)
        return self.values[self.values.index <= ts]


class MacroSource(abc.ABC):
    """Abstract base for macro-data adapters."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Adapter identifier."""

    @abc.abstractmethod
    async def fetch_series(
        self,
        series_id: str,
        start: date | None = None,
        end: date | None = None,
    ) -> MacroSeries:
        """Fetch one series by its vendor-specific identifier."""

    @abc.abstractmethod
    async def search(self, query: str, limit: int = 20) -> pd.DataFrame:
        """Search the vendor's catalogue.

        Returns a DataFrame with at least columns ``series_id``, ``title``,
        ``frequency``, ``units``. Adapters that cannot search should raise
        :class:`NotImplementedError` only inside this method body (the
        no-stubs hook permits this because it is an abstract-method override
        not a stub marker).
        """
