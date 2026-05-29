"""Quick smoke test: download 30 days of daily bars for AAPL via yfinance.

Run with: .venv/Scripts/python.exe tools/smoke_yfinance.py
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from core_trading.data import BarRequest, BarResolution
from core_trading.data.sources.yfinance_source import YFinanceBarSource


async def main() -> None:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=30)
    request = BarRequest(
        symbols=("AAPL", "MSFT"),
        resolution=BarResolution.DAY_1,
        start=start,
        end=end,
    )
    source = YFinanceBarSource()
    df = await source.fetch_bars(request)
    print(f"Fetched {len(df)} rows for {df.index.get_level_values('symbol').nunique()} symbols")
    print()
    print(df.head())
    print()
    print(df.tail())


if __name__ == "__main__":
    asyncio.run(main())
