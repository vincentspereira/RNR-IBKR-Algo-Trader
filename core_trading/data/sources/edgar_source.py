"""SEC EDGAR point-in-time fundamentals adapter.

EDGAR is the gold-standard **free** source for point-in-time fundamentals
(master plan Phase 1.4): every filing carries a filing date, so a backtest can
ask "what was known on date Y?" without leakage.

This adapter uses the SEC ``companyfacts`` JSON API:
``https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json``

Key facts:

* **Free, official, no API key.** SEC only requires a descriptive
  ``User-Agent`` header identifying the requester (their fair-access policy).
* Rate limit: 10 requests/second. We stay well under that.
* The API returns XBRL facts keyed by taxonomy (us-gaap) and concept
  (Revenues, Assets, ...). Each fact carries ``end`` (period end), ``filed``
  (filing date), ``fy``/``fp`` (fiscal year/period), and ``val``.

The adapter maps a curated set of XBRL concepts to our metric names and
respects ``FundamentalRequest.as_of`` by dropping any fact with
``filed > as_of``.

Symbol -> CIK resolution uses the SEC ``company_tickers.json`` mapping, cached
on first use.

Network calls go through ``httpx`` (already a dependency). Unit tests mock the
HTTP layer so they run offline.
"""
from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import date
from typing import Any

import httpx

from core_trading.data.fundamentals import (
    FundamentalRecord,
    FundamentalRequest,
    FundamentalSource,
    StatementType,
)

_SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SEC_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

# Map XBRL us-gaap concepts to (our metric name, statement type).
_CONCEPT_MAP: dict[str, tuple[str, StatementType]] = {
    "Revenues": ("revenue", StatementType.INCOME),
    "RevenueFromContractWithCustomerExcludingAssessedTax": ("revenue", StatementType.INCOME),
    "CostOfRevenue": ("cost_of_revenue", StatementType.INCOME),
    "GrossProfit": ("gross_profit", StatementType.INCOME),
    "OperatingIncomeLoss": ("operating_income", StatementType.INCOME),
    "NetIncomeLoss": ("net_income", StatementType.INCOME),
    "EarningsPerShareDiluted": ("eps_diluted", StatementType.INCOME),
    "Assets": ("total_assets", StatementType.BALANCE_SHEET),
    "Liabilities": ("total_liabilities", StatementType.BALANCE_SHEET),
    "StockholdersEquity": ("stockholders_equity", StatementType.BALANCE_SHEET),
    "CashAndCashEquivalentsAtCarryingValue": ("cash", StatementType.BALANCE_SHEET),
    "NetCashProvidedByUsedInOperatingActivities": (
        "operating_cash_flow",
        StatementType.CASH_FLOW,
    ),
    "PaymentsToAcquirePropertyPlantAndEquipment": ("capex", StatementType.CASH_FLOW),
}

_DEFAULT_USER_AGENT = "IBKR-Algo-Trader research contact@example.com"


class EdgarFundamentalSource(FundamentalSource):
    """Point-in-time fundamentals via SEC EDGAR companyfacts.

    Parameters
    ----------
    user_agent:
        Descriptive User-Agent per SEC fair-access policy. Should identify you
        and include contact info.
    client:
        Optional pre-built ``httpx.AsyncClient`` (injected in tests). If
        ``None`` a client is created per request.
    """

    _NAME = "edgar"

    def __init__(
        self,
        user_agent: str = _DEFAULT_USER_AGENT,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._user_agent = user_agent
        self._client = client
        self._ticker_to_cik: dict[str, int] | None = None

    @property
    def name(self) -> str:
        return self._NAME

    @property
    def is_point_in_time(self) -> bool:
        return True

    def _headers(self) -> dict[str, str]:
        return {"User-Agent": self._user_agent, "Accept-Encoding": "gzip, deflate"}

    async def _get_json(self, url: str) -> Any:
        if self._client is not None:
            resp = await self._client.get(url, headers=self._headers())
            resp.raise_for_status()
            return resp.json()
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def _load_ticker_map(self) -> dict[str, int]:
        if self._ticker_to_cik is not None:
            return self._ticker_to_cik
        data = await self._get_json(_SEC_TICKERS_URL)
        mapping: dict[str, int] = {}
        # company_tickers.json is a dict of {"0": {"cik_str":..,"ticker":..}, ...}
        rows = data.values() if isinstance(data, dict) else data
        for row in rows:
            ticker = str(row["ticker"]).upper()
            mapping[ticker] = int(row["cik_str"])
        self._ticker_to_cik = mapping
        return mapping

    async def resolve_cik(self, symbol: str) -> int:
        """Resolve a ticker symbol to its SEC CIK number."""
        mapping = await self._load_ticker_map()
        key = symbol.upper()
        if key not in mapping:
            raise KeyError(f"no SEC CIK found for ticker {symbol!r}")
        return mapping[key]

    def _parse_facts(
        self,
        symbol: str,
        facts_json: dict[str, Any],
        request: FundamentalRequest,
    ) -> list[FundamentalRecord]:
        records: list[FundamentalRecord] = []
        wanted_statements = set(request.statements)
        us_gaap = facts_json.get("facts", {}).get("us-gaap", {})

        for concept, (metric, statement) in _CONCEPT_MAP.items():
            if statement not in wanted_statements:
                continue
            concept_block = us_gaap.get(concept)
            if not concept_block:
                continue
            for unit_entries in concept_block.get("units", {}).values():
                for entry in unit_entries:
                    end_str = entry.get("end")
                    filed_str = entry.get("filed")
                    val = entry.get("val")
                    if end_str is None or filed_str is None or val is None:
                        continue
                    period_end = date.fromisoformat(end_str)
                    filing_date = date.fromisoformat(filed_str)
                    if period_end < request.start_period or period_end > request.end_period:
                        continue
                    if request.as_of is not None and filing_date > request.as_of:
                        continue
                    fiscal_period = f"{entry.get('fp', '')} {entry.get('fy', '')}".strip()
                    records.append(
                        FundamentalRecord(
                            symbol=symbol,
                            statement=statement,
                            metric=metric,
                            value=float(val),
                            period_end=period_end,
                            filing_date=filing_date,
                            fiscal_period=fiscal_period or "unknown",
                            source=self._NAME,
                        )
                    )
        return records

    async def fetch(self, request: FundamentalRequest) -> Sequence[FundamentalRecord]:
        async def _fetch_one(symbol: str) -> list[FundamentalRecord]:
            cik = await self.resolve_cik(symbol)
            facts = await self._get_json(_SEC_FACTS_URL.format(cik=cik))
            return self._parse_facts(symbol, facts, request)

        results = await asyncio.gather(*[_fetch_one(s) for s in request.symbols])
        flat: list[FundamentalRecord] = []
        for r in results:
            flat.extend(r)
        return flat
