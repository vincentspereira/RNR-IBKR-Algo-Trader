"""Unit tests for core_trading.data.fundamentals."""
from __future__ import annotations

from datetime import date

import pytest

from core_trading.data.fundamentals import (
    FundamentalRecord,
    FundamentalRequest,
    FundamentalSource,
    StatementType,
)


class TestFundamentalRecord:
    def test_minimal_record(self) -> None:
        r = FundamentalRecord(
            symbol="AAPL",
            statement=StatementType.INCOME,
            metric="revenue",
            value=100_000_000.0,
            period_end=date(2026, 3, 31),
            filing_date=date(2026, 5, 1),
            fiscal_period="Q1 2026",
        )
        assert r.symbol == "AAPL"

    def test_filing_before_period_rejected(self) -> None:
        with pytest.raises(ValueError, match="filing_date"):
            FundamentalRecord(
                symbol="AAPL",
                statement=StatementType.INCOME,
                metric="revenue",
                value=1.0,
                period_end=date(2026, 5, 1),
                filing_date=date(2026, 3, 1),
                fiscal_period="Q1",
            )


class TestFundamentalRequest:
    def test_minimal_request(self) -> None:
        r = FundamentalRequest(
            symbols=("AAPL",),
            statements=(StatementType.INCOME,),
            start_period=date(2024, 1, 1),
            end_period=date(2026, 1, 1),
        )
        assert r.symbols == ("AAPL",)

    def test_empty_symbols_rejected(self) -> None:
        with pytest.raises(ValueError, match="symbols"):
            FundamentalRequest(
                symbols=(),
                statements=(StatementType.INCOME,),
                start_period=date(2024, 1, 1),
                end_period=date(2026, 1, 1),
            )

    def test_empty_statements_rejected(self) -> None:
        with pytest.raises(ValueError, match="statements"):
            FundamentalRequest(
                symbols=("AAPL",),
                statements=(),
                start_period=date(2024, 1, 1),
                end_period=date(2026, 1, 1),
            )

    def test_inverted_period_rejected(self) -> None:
        with pytest.raises(ValueError, match="start_period"):
            FundamentalRequest(
                symbols=("AAPL",),
                statements=(StatementType.INCOME,),
                start_period=date(2026, 1, 1),
                end_period=date(2024, 1, 1),
            )


class TestRecordsToDataframe:
    def test_empty_records(self) -> None:
        df = FundamentalSource.records_to_dataframe([])
        assert df.empty
        assert "symbol" in df.columns
        assert "filing_date" in df.columns

    def test_records_round_trip(self) -> None:
        records = [
            FundamentalRecord(
                symbol="AAPL",
                statement=StatementType.INCOME,
                metric="revenue",
                value=100.0,
                period_end=date(2026, 3, 31),
                filing_date=date(2026, 5, 1),
                fiscal_period="Q1 2026",
                source="test",
            ),
            FundamentalRecord(
                symbol="AAPL",
                statement=StatementType.BALANCE_SHEET,
                metric="total_assets",
                value=1000.0,
                period_end=date(2026, 3, 31),
                filing_date=date(2026, 5, 1),
                fiscal_period="Q1 2026",
                source="test",
            ),
        ]
        df = FundamentalSource.records_to_dataframe(records)
        assert len(df) == 2
        assert set(df["statement"].unique()) == {"income", "balance_sheet"}
