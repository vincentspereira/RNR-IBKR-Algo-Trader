import yfinance as yf
from datetime import datetime
from typing import Any, Dict
import asyncio
from ..feed_handler import FeedHandler

class YahooFinanceProvider(FeedHandler):
    """Yahoo Finance data provider."""
    
    async def get_historical_data(self, symbol: str, start_date: datetime, end_date: datetime, interval: str = "1d") -> Any:
        # yfinance is synchronous, so we wrap it in a thread execution if needed, 
        # but for simplicity in this step we call it directly. 
        # In production, use run_in_executor.
        ticker = yf.Ticker(symbol)
        df = await asyncio.to_thread(ticker.history, start=start_date, end=end_date, interval=interval)
        return df

    async def get_realtime_quote(self, symbol: str) -> Dict[str, Any]:
        ticker = yf.Ticker(symbol)
        # Fetching info can be slow, so we offload it
        info = await asyncio.to_thread(lambda: ticker.info)
        return {
            "symbol": symbol,
            "price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "volume": info.get("volume"),
            "timestamp": datetime.now().isoformat(),
            "source": "yahoo"
        }
