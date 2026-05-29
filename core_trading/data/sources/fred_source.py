"""FRED macro data adapter via ``fredapi``.

FRED (Federal Reserve Economic Data) is the standard free source for U.S.
macro time series: rates, CPI, unemployment, money supply, exchange rates,
VIX, and roughly 800k other series.

Per :doc:`docs/FREE_DATA_VENDORS.md`:

* Requires a free API key from https://fred.stlouisfed.org/docs/api/api_key.html
* Rate limit: 120 calls/minute (generous)
* Vintage / point-in-time data is available via separate FRED ALFRED endpoints;
  this adapter uses the latest revisions only. For series that are heavily
  revised (e.g. real GDP), a future vintage-aware extension is on the roadmap.

The key is read from ``FRED_API_KEY`` in the environment. If absent the
adapter raises :class:`RuntimeError` on first use; signing up is free.
"""
from __future__ import annotations

import asyncio
import os
from datetime import date

import pandas as pd
from fredapi import Fred

from core_trading.data.macro import MacroFrequency, MacroSeries, MacroSource

_FREQ_MAP: dict[str, MacroFrequency] = {
    "D": MacroFrequency.DAILY,
    "W": MacroFrequency.WEEKLY,
    "M": MacroFrequency.MONTHLY,
    "Q": MacroFrequency.QUARTERLY,
    "A": MacroFrequency.ANNUAL,
}


class FredMacroSource(MacroSource):
    """Macro data via FRED.

    Parameters
    ----------
    api_key:
        FRED API key. If ``None`` (the default) the adapter reads
        ``FRED_API_KEY`` from the environment.
    """

    _NAME = "fred"

    def __init__(self, api_key: str | None = None) -> None:
        key = api_key if api_key is not None else os.environ.get("FRED_API_KEY")
        if not key:
            raise RuntimeError(
                "FRED API key required. Either pass api_key= or set FRED_API_KEY "
                "in the environment. Sign up free at "
                "https://fred.stlouisfed.org/docs/api/api_key.html"
            )
        self._fred = Fred(api_key=key)

    @property
    def name(self) -> str:
        return self._NAME

    async def fetch_series(
        self,
        series_id: str,
        start: date | None = None,
        end: date | None = None,
    ) -> MacroSeries:
        def _fetch() -> tuple[pd.Series, dict[str, str]]:
            values = self._fred.get_series(
                series_id,
                observation_start=start,
                observation_end=end,
            )
            info = self._fred.get_series_info(series_id)
            info_dict = info.to_dict() if hasattr(info, "to_dict") else dict(info)
            return values, info_dict

        values, info = await asyncio.to_thread(_fetch)
        if not isinstance(values.index, pd.DatetimeIndex):
            values.index = pd.to_datetime(values.index)
        values = values.sort_index()
        values.name = series_id

        freq_code = (info.get("frequency_short") or "D").strip().upper()
        frequency = _FREQ_MAP.get(freq_code[0], MacroFrequency.DAILY)
        title = str(info.get("title") or series_id)
        units = str(info.get("units_short") or info.get("units") or "")

        return MacroSeries(
            series_id=series_id,
            title=title,
            frequency=frequency,
            units=units,
            source=self._NAME,
            values=values,
        )

    async def search(self, query: str, limit: int = 20) -> pd.DataFrame:
        def _search() -> pd.DataFrame:
            results = self._fred.search(query, limit=limit)
            if results is None or len(results) == 0:
                return pd.DataFrame(columns=["series_id", "title", "frequency", "units"])
            cols = ["id", "title", "frequency_short", "units_short"]
            available = [c for c in cols if c in results.columns]
            df = results[available].rename(
                columns={
                    "id": "series_id",
                    "frequency_short": "frequency",
                    "units_short": "units",
                }
            )
            return df.reset_index(drop=True)

        return await asyncio.to_thread(_search)


COMMON_SERIES: dict[str, str] = {
    "VIX": "VIXCLS",
    "10Y_YIELD": "DGS10",
    "2Y_YIELD": "DGS2",
    "FED_FUNDS": "DFF",
    "CPI_HEADLINE": "CPIAUCSL",
    "CPI_CORE": "CPILFESL",
    "UNEMPLOYMENT": "UNRATE",
    "M2": "M2SL",
    "DOLLAR_INDEX": "DTWEXBGS",
    "OIL_WTI": "DCOILWTICO",
    "TERM_SPREAD_10_2": "T10Y2Y",
    "TED_SPREAD": "TEDRATE",
    "FINANCIAL_STRESS": "STLFSI3",
}


def fred_series_id(alias: str) -> str:
    """Translate a friendly alias to its FRED series id.

    Example: ``fred_series_id("VIX") -> "VIXCLS"``.
    """
    key = alias.upper()
    if key in COMMON_SERIES:
        return COMMON_SERIES[key]
    return alias
