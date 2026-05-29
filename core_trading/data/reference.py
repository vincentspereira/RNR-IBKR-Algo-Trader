"""Reference data: sector classification and symbol-change tracking (Phase 1.5).

Provides the slow-moving descriptive data that signals and risk models need:

* **Sector / industry classification** (GICS-style) with effective dates, so a
  backtest can ask "what sector was this symbol in on date X?" -- important
  because classifications change (reclassifications, GICS revisions).
* **Symbol-change tracking** (ticker renames, e.g. FB -> META) so historical
  data keyed by the old ticker reconciles with the current one.

Built-in data ships as a static snapshot for the starter universes. The API is
date-aware so that vintage classification data (paid vendors, or scraped GICS
history) can be layered in later without changing call sites.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class SectorAssignment:
    """A symbol's sector/industry over a date range."""

    symbol: str
    sector: str
    industry: str
    effective_from: date
    effective_to: date | None = None

    def covers(self, as_of: date) -> bool:
        if as_of < self.effective_from:
            return False
        return not (self.effective_to is not None and as_of >= self.effective_to)


@dataclass(frozen=True, slots=True)
class SymbolChange:
    """A ticker rename event."""

    old_symbol: str
    new_symbol: str
    change_date: date
    reason: str = "rename"


class ReferenceData:
    """In-memory reference-data store with date-aware lookups."""

    def __init__(
        self,
        sectors: list[SectorAssignment] | None = None,
        symbol_changes: list[SymbolChange] | None = None,
    ) -> None:
        self._sectors = list(sectors or [])
        self._symbol_changes = list(symbol_changes or [])

    def add_sector(self, assignment: SectorAssignment) -> None:
        self._sectors.append(assignment)

    def add_symbol_change(self, change: SymbolChange) -> None:
        self._symbol_changes.append(change)

    def sector_of(self, symbol: str, as_of: date | None = None) -> str | None:
        """Return the GICS sector for ``symbol`` effective on ``as_of`` (default: latest)."""
        candidates = [s for s in self._sectors if s.symbol == symbol]
        if not candidates:
            return None
        if as_of is None:
            return max(candidates, key=lambda s: s.effective_from).sector
        for s in candidates:
            if s.covers(as_of):
                return s.sector
        return None

    def industry_of(self, symbol: str, as_of: date | None = None) -> str | None:
        candidates = [s for s in self._sectors if s.symbol == symbol]
        if not candidates:
            return None
        if as_of is None:
            return max(candidates, key=lambda s: s.effective_from).industry
        for s in candidates:
            if s.covers(as_of):
                return s.industry
        return None

    def symbols_in_sector(self, sector: str, as_of: date | None = None) -> tuple[str, ...]:
        out = {
            s.symbol
            for s in self._sectors
            if s.sector == sector and (as_of is None or s.covers(as_of))
        }
        return tuple(sorted(out))

    def resolve_current_symbol(self, symbol: str) -> str:
        """Follow rename chain to the current ticker (e.g. FB -> META)."""
        current = symbol
        changed = True
        seen = {current}
        while changed:
            changed = False
            for ch in self._symbol_changes:
                if ch.old_symbol == current and ch.new_symbol not in seen:
                    current = ch.new_symbol
                    seen.add(current)
                    changed = True
        return current

    def historical_symbols(self, current_symbol: str) -> tuple[str, ...]:
        """Return all prior tickers that resolve to ``current_symbol``."""
        out: set[str] = set()
        for ch in self._symbol_changes:
            if self.resolve_current_symbol(ch.old_symbol) == current_symbol:
                out.add(ch.old_symbol)
        return tuple(sorted(out))


# ---------------------------------------------------------------------------
# Built-in starter data (static snapshot 2026-05-28)
# ---------------------------------------------------------------------------

# GICS sectors for a subset of the SP100 starter universe. Not exhaustive --
# enough to exercise sector-neutral pairs selection and sector-cap risk checks
# in the Phase 4 pilot. Extend or replace with a vendor feed before scaling.
_STARTER_SECTORS: dict[str, tuple[str, str]] = {
    "AAPL": ("Information Technology", "Technology Hardware"),
    "MSFT": ("Information Technology", "Software"),
    "NVDA": ("Information Technology", "Semiconductors"),
    "AVGO": ("Information Technology", "Semiconductors"),
    "ORCL": ("Information Technology", "Software"),
    "CRM": ("Information Technology", "Software"),
    "ADBE": ("Information Technology", "Software"),
    "GOOGL": ("Communication Services", "Interactive Media"),
    "GOOG": ("Communication Services", "Interactive Media"),
    "META": ("Communication Services", "Interactive Media"),
    "NFLX": ("Communication Services", "Entertainment"),
    "DIS": ("Communication Services", "Entertainment"),
    "T": ("Communication Services", "Telecom"),
    "VZ": ("Communication Services", "Telecom"),
    "AMZN": ("Consumer Discretionary", "Internet Retail"),
    "TSLA": ("Consumer Discretionary", "Automobiles"),
    "HD": ("Consumer Discretionary", "Home Improvement Retail"),
    "MCD": ("Consumer Discretionary", "Restaurants"),
    "NKE": ("Consumer Discretionary", "Apparel"),
    "LOW": ("Consumer Discretionary", "Home Improvement Retail"),
    "JPM": ("Financials", "Banks"),
    "BAC": ("Financials", "Banks"),
    "WFC": ("Financials", "Banks"),
    "GS": ("Financials", "Capital Markets"),
    "MS": ("Financials", "Capital Markets"),
    "C": ("Financials", "Banks"),
    "BLK": ("Financials", "Asset Management"),
    "AXP": ("Financials", "Consumer Finance"),
    "V": ("Financials", "Payments"),
    "MA": ("Financials", "Payments"),
    "JNJ": ("Health Care", "Pharmaceuticals"),
    "UNH": ("Health Care", "Managed Care"),
    "LLY": ("Health Care", "Pharmaceuticals"),
    "PFE": ("Health Care", "Pharmaceuticals"),
    "MRK": ("Health Care", "Pharmaceuticals"),
    "ABBV": ("Health Care", "Biotechnology"),
    "TMO": ("Health Care", "Life Sciences Tools"),
    "ABT": ("Health Care", "Health Care Equipment"),
    "XOM": ("Energy", "Integrated Oil & Gas"),
    "CVX": ("Energy", "Integrated Oil & Gas"),
    "COP": ("Energy", "Oil & Gas E&P"),
    "PG": ("Consumer Staples", "Household Products"),
    "KO": ("Consumer Staples", "Beverages"),
    "PEP": ("Consumer Staples", "Beverages"),
    "WMT": ("Consumer Staples", "Food Retail"),
    "COST": ("Consumer Staples", "Food Retail"),
    "CAT": ("Industrials", "Machinery"),
    "BA": ("Industrials", "Aerospace & Defense"),
    "HON": ("Industrials", "Industrial Conglomerates"),
    "UPS": ("Industrials", "Air Freight & Logistics"),
    "GE": ("Industrials", "Industrial Conglomerates"),
    "LIN": ("Materials", "Industrial Gases"),
    "NEE": ("Utilities", "Electric Utilities"),
    "DUK": ("Utilities", "Electric Utilities"),
    "SO": ("Utilities", "Electric Utilities"),
    "AMT": ("Real Estate", "REITs"),
    "SPG": ("Real Estate", "REITs"),
}

_STARTER_SYMBOL_CHANGES: list[SymbolChange] = [
    SymbolChange(old_symbol="FB", new_symbol="META", change_date=date(2022, 6, 9)),
    SymbolChange(old_symbol="GOOG_OLD", new_symbol="GOOGL", change_date=date(2014, 4, 3)),
]

_SNAPSHOT_DATE = date(2026, 5, 28)


def build_starter_reference() -> ReferenceData:
    """Return a :class:`ReferenceData` populated with the built-in starter data."""
    sectors = [
        SectorAssignment(
            symbol=sym,
            sector=sector,
            industry=industry,
            effective_from=date(2000, 1, 1),
        )
        for sym, (sector, industry) in _STARTER_SECTORS.items()
    ]
    return ReferenceData(sectors=sectors, symbol_changes=list(_STARTER_SYMBOL_CHANGES))
