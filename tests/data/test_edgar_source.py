"""Tests for the EDGAR fundamentals source (mocked HTTP)."""
from __future__ import annotations

from datetime import date

import pytest

from core_trading.data.fundamentals import FundamentalRequest, StatementType
from core_trading.data.sources.edgar_source import EdgarFundamentalSource


_TICKERS_JSON = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp"},
}

_FACTS_JSON = {
    "cik": 320193,
    "entityName": "Apple Inc.",
    "facts": {
        "us-gaap": {
            "Revenues": {
                "units": {
                    "USD": [
                        {
                            "end": "2025-12-31",
                            "val": 100_000_000,
                            "fy": 2025,
                            "fp": "Q4",
                            "filed": "2026-02-01",
                        },
                        {
                            "end": "2026-03-31",
                            "val": 110_000_000,
                            "fy": 2026,
                            "fp": "Q1",
                            "filed": "2026-05-01",
                        },
                    ]
                }
            },
            "Assets": {
                "units": {
                    "USD": [
                        {
                            "end": "2026-03-31",
                            "val": 500_000_000,
                            "fy": 2026,
                            "fp": "Q1",
                            "filed": "2026-05-01",
                        }
                    ]
                }
            },
        }
    },
}


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    """Minimal stand-in for httpx.AsyncClient that routes by URL."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def get(self, url: str, headers: dict | None = None) -> _FakeResponse:
        self.calls.append(url)
        if "company_tickers" in url:
            return _FakeResponse(_TICKERS_JSON)
        if "companyfacts" in url:
            return _FakeResponse(_FACTS_JSON)
        raise AssertionError(f"unexpected URL {url}")


@pytest.fixture
def edgar() -> EdgarFundamentalSource:
    return EdgarFundamentalSource(client=_FakeClient())


class TestMetadata:
    def test_name(self, edgar: EdgarFundamentalSource) -> None:
        assert edgar.name == "edgar"

    def test_is_point_in_time(self, edgar: EdgarFundamentalSource) -> None:
        assert edgar.is_point_in_time is True


class TestResolveCik:
    @pytest.mark.asyncio
    async def test_known_ticker(self, edgar: EdgarFundamentalSource) -> None:
        assert await edgar.resolve_cik("AAPL") == 320193

    @pytest.mark.asyncio
    async def test_case_insensitive(self, edgar: EdgarFundamentalSource) -> None:
        assert await edgar.resolve_cik("aapl") == 320193

    @pytest.mark.asyncio
    async def test_unknown_ticker_raises(self, edgar: EdgarFundamentalSource) -> None:
        with pytest.raises(KeyError, match="no SEC CIK"):
            await edgar.resolve_cik("NOTREAL")

    @pytest.mark.asyncio
    async def test_ticker_map_cached(self, edgar: EdgarFundamentalSource) -> None:
        await edgar.resolve_cik("AAPL")
        await edgar.resolve_cik("MSFT")
        tickers_calls = [c for c in edgar._client.calls if "company_tickers" in c]
        assert len(tickers_calls) == 1


class TestFetch:
    @pytest.mark.asyncio
    async def test_fetch_income_and_balance(self, edgar: EdgarFundamentalSource) -> None:
        req = FundamentalRequest(
            symbols=("AAPL",),
            statements=(StatementType.INCOME, StatementType.BALANCE_SHEET),
            start_period=date(2025, 1, 1),
            end_period=date(2026, 12, 31),
        )
        records = await edgar.fetch(req)
        metrics = {r.metric for r in records}
        assert "revenue" in metrics
        assert "total_assets" in metrics

    @pytest.mark.asyncio
    async def test_statement_filter(self, edgar: EdgarFundamentalSource) -> None:
        req = FundamentalRequest(
            symbols=("AAPL",),
            statements=(StatementType.BALANCE_SHEET,),
            start_period=date(2025, 1, 1),
            end_period=date(2026, 12, 31),
        )
        records = await edgar.fetch(req)
        assert all(r.statement == StatementType.BALANCE_SHEET for r in records)
        assert {r.metric for r in records} == {"total_assets"}

    @pytest.mark.asyncio
    async def test_period_window_filter(self, edgar: EdgarFundamentalSource) -> None:
        req = FundamentalRequest(
            symbols=("AAPL",),
            statements=(StatementType.INCOME,),
            start_period=date(2026, 1, 1),
            end_period=date(2026, 12, 31),
        )
        records = await edgar.fetch(req)
        # Only the 2026-Q1 revenue (period_end 2026-03-31) is in window.
        revenue = [r for r in records if r.metric == "revenue"]
        assert len(revenue) == 1
        assert revenue[0].period_end == date(2026, 3, 31)

    @pytest.mark.asyncio
    async def test_as_of_excludes_future_filings(self, edgar: EdgarFundamentalSource) -> None:
        req = FundamentalRequest(
            symbols=("AAPL",),
            statements=(StatementType.INCOME,),
            start_period=date(2025, 1, 1),
            end_period=date(2026, 12, 31),
            as_of=date(2026, 3, 1),
        )
        records = await edgar.fetch(req)
        # As of 2026-03-01, only the filing dated 2026-02-01 is known.
        revenue = [r for r in records if r.metric == "revenue"]
        assert len(revenue) == 1
        assert revenue[0].filing_date == date(2026, 2, 1)

    @pytest.mark.asyncio
    async def test_point_in_time_correctness(self, edgar: EdgarFundamentalSource) -> None:
        req = FundamentalRequest(
            symbols=("AAPL",),
            statements=(StatementType.INCOME,),
            start_period=date(2025, 1, 1),
            end_period=date(2026, 12, 31),
        )
        records = await edgar.fetch(req)
        for r in records:
            assert r.filing_date >= r.period_end
