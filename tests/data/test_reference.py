"""Tests for core_trading.data.reference."""
from __future__ import annotations

from datetime import date

from core_trading.data.reference import (
    ReferenceData,
    SectorAssignment,
    SymbolChange,
    build_starter_reference,
)


class TestSectorAssignment:
    def test_covers_lifetime(self) -> None:
        a = SectorAssignment("AAPL", "Tech", "Hardware", date(2000, 1, 1))
        assert a.covers(date(2026, 1, 1))
        assert not a.covers(date(1999, 1, 1))

    def test_covers_bounded(self) -> None:
        a = SectorAssignment("X", "S", "I", date(2010, 1, 1), date(2020, 1, 1))
        assert a.covers(date(2015, 1, 1))
        assert not a.covers(date(2020, 1, 1))
        assert not a.covers(date(2009, 1, 1))


class TestReferenceData:
    def test_sector_of_latest(self) -> None:
        ref = ReferenceData(
            sectors=[SectorAssignment("AAPL", "Tech", "Hardware", date(2000, 1, 1))]
        )
        assert ref.sector_of("AAPL") == "Tech"

    def test_sector_of_unknown(self) -> None:
        ref = ReferenceData()
        assert ref.sector_of("NOPE") is None

    def test_sector_of_as_of_reclassification(self) -> None:
        ref = ReferenceData(
            sectors=[
                SectorAssignment("X", "Old", "i", date(2000, 1, 1), date(2015, 1, 1)),
                SectorAssignment("X", "New", "i", date(2015, 1, 1)),
            ]
        )
        assert ref.sector_of("X", date(2010, 1, 1)) == "Old"
        assert ref.sector_of("X", date(2020, 1, 1)) == "New"

    def test_sector_of_as_of_no_match(self) -> None:
        ref = ReferenceData(
            sectors=[SectorAssignment("X", "S", "i", date(2015, 1, 1))]
        )
        assert ref.sector_of("X", date(2010, 1, 1)) is None

    def test_industry_of(self) -> None:
        ref = ReferenceData(
            sectors=[SectorAssignment("AAPL", "Tech", "Hardware", date(2000, 1, 1))]
        )
        assert ref.industry_of("AAPL") == "Hardware"
        assert ref.industry_of("NOPE") is None

    def test_industry_of_as_of(self) -> None:
        ref = ReferenceData(
            sectors=[
                SectorAssignment("X", "S", "old_ind", date(2000, 1, 1), date(2015, 1, 1)),
                SectorAssignment("X", "S", "new_ind", date(2015, 1, 1)),
            ]
        )
        assert ref.industry_of("X", date(2010, 1, 1)) == "old_ind"
        assert ref.industry_of("X", date(2010, 1, 1)) != ref.industry_of("X")

    def test_symbols_in_sector(self) -> None:
        ref = ReferenceData(
            sectors=[
                SectorAssignment("AAPL", "Tech", "i", date(2000, 1, 1)),
                SectorAssignment("MSFT", "Tech", "i", date(2000, 1, 1)),
                SectorAssignment("XOM", "Energy", "i", date(2000, 1, 1)),
            ]
        )
        assert ref.symbols_in_sector("Tech") == ("AAPL", "MSFT")

    def test_add_methods(self) -> None:
        ref = ReferenceData()
        ref.add_sector(SectorAssignment("AAPL", "Tech", "i", date(2000, 1, 1)))
        ref.add_symbol_change(SymbolChange("FB", "META", date(2022, 6, 9)))
        assert ref.sector_of("AAPL") == "Tech"
        assert ref.resolve_current_symbol("FB") == "META"


class TestSymbolChanges:
    def test_resolve_current(self) -> None:
        ref = ReferenceData(symbol_changes=[SymbolChange("FB", "META", date(2022, 6, 9))])
        assert ref.resolve_current_symbol("FB") == "META"
        assert ref.resolve_current_symbol("META") == "META"

    def test_resolve_unchanged(self) -> None:
        ref = ReferenceData()
        assert ref.resolve_current_symbol("AAPL") == "AAPL"

    def test_resolve_chain(self) -> None:
        ref = ReferenceData(
            symbol_changes=[
                SymbolChange("A", "B", date(2010, 1, 1)),
                SymbolChange("B", "C", date(2015, 1, 1)),
            ]
        )
        assert ref.resolve_current_symbol("A") == "C"

    def test_historical_symbols(self) -> None:
        ref = ReferenceData(
            symbol_changes=[
                SymbolChange("A", "B", date(2010, 1, 1)),
                SymbolChange("B", "C", date(2015, 1, 1)),
            ]
        )
        assert ref.historical_symbols("C") == ("A", "B")


class TestStarterReference:
    def test_builds(self) -> None:
        ref = build_starter_reference()
        assert ref.sector_of("AAPL") == "Information Technology"
        assert ref.sector_of("JPM") == "Financials"
        assert ref.sector_of("XOM") == "Energy"

    def test_fb_meta_rename(self) -> None:
        ref = build_starter_reference()
        assert ref.resolve_current_symbol("FB") == "META"

    def test_financials_sector_populated(self) -> None:
        ref = build_starter_reference()
        fins = ref.symbols_in_sector("Financials")
        assert "JPM" in fins
        assert "GS" in fins
