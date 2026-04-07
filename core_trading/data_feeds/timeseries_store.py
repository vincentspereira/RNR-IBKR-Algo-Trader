"""ClickHouse Time-Series Store for Market Data.

Provides storage and retrieval of OHLCV bars, tick data, and quotes
using ClickHouse as the time-series database backend.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

try:
    from libs.database.clickhouse.client import ClickHouseClient, get_clickhouse_client
    CLICKHOUSE_AVAILABLE = True
except ImportError:
    CLICKHOUSE_AVAILABLE = False
    logging.warning("ClickHouse client not available - timeseries store will be simulated")

logger = structlog.get_logger(__name__)


class TimeSeriesStore:
    """Store and retrieve market data from ClickHouse.

    Handles:
    - OHLCV bar storage and retrieval
    - Tick data storage
    - Quote snapshot storage
    - Automatic table creation verification
    """

    def __init__(self, client: Optional[ClickHouseClient] = None):
        self._client = client
        self._initialized = False

    @property
    def client(self) -> Optional[ClickHouseClient]:
        """Get or create ClickHouse client."""
        if self._client is None and CLICKHOUSE_AVAILABLE:
            self._client = get_clickhouse_client()
        return self._client

    def _ensure_initialized(self):
        """Ensure the database tables exist."""
        if self._initialized:
            return

        if self.client:
            try:
                self.client.execute("CREATE DATABASE IF NOT EXISTS market_data")
                self._initialized = True
                logger.info("timeseries_store_initialized")
            except Exception as e:
                logger.error("timeseries_store_init_error", error=str(e))
        else:
            self._initialized = True

    async def store_bars(self, symbol: str, bars: List[Dict[str, Any]]) -> bool:
        """Store OHLCV bars in ClickHouse.

        Args:
            symbol: Symbol identifier
            bars: List of bar dicts with keys:
                  timestamp, open, high, low, close, volume, timeframe

        Returns:
            True if successful
        """
        if not bars:
            return True

        self._ensure_initialized()

        if not self.client:
            logger.debug("store_bars_no_client", symbol=symbol, bars=len(bars))
            return True

        try:
            data = []
            for bar in bars:
                ts = bar.get("timestamp") or bar.get("date")
                if isinstance(ts, str):
                    ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                elif isinstance(ts, datetime):
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)

                data.append((
                    symbol,
                    ts,
                    float(bar.get("open", 0)),
                    float(bar.get("high", 0)),
                    float(bar.get("low", 0)),
                    float(bar.get("close", 0)),
                    float(bar.get("volume", 0)),
                    bar.get("timeframe", "1 min"),
                    int(bar.get("bar_count", 0)),
                    float(bar.get("average", 0)),
                    bar.get("source", "ibkr"),
                ))

            columns = [
                "symbol", "timestamp", "open", "high", "low", "close",
                "volume", "timeframe", "bar_count", "average", "source",
            ]
            self.client.insert_batch("market_data.bars", data, columns)
            logger.info("bars_stored", symbol=symbol, count=len(bars))
            return True

        except Exception as e:
            logger.error("store_bars_error", symbol=symbol, error=str(e))
            return False

    async def get_bars(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframe: str = "1 min",
    ) -> List[Dict[str, Any]]:
        """Query historical bars from ClickHouse.

        Args:
            symbol: Symbol to query
            start: Start datetime
            end: End datetime
            timeframe: Bar timeframe

        Returns:
            List of bar dicts
        """
        self._ensure_initialized()

        if not self.client:
            logger.debug("get_bars_no_client", symbol=symbol)
            return []

        try:
            query = """
                SELECT symbol, timestamp, open, high, low, close,
                       volume, timeframe, bar_count, average, source
                FROM market_data.bars
                WHERE symbol = %(symbol)s
                  AND timeframe = %(timeframe)s
                  AND timestamp >= %(start)s
                  AND timestamp <= %(end)s
                ORDER BY timestamp ASC
            """
            results = self.client.execute(query, {
                "symbol": symbol,
                "timeframe": timeframe,
                "start": start.strftime("%Y-%m-%d %H:%M:%S"),
                "end": end.strftime("%Y-%m-%d %H:%M:%S"),
            })

            bars = []
            for row in results:
                bars.append({
                    "symbol": row[0],
                    "timestamp": row[1],
                    "open": row[2],
                    "high": row[3],
                    "low": row[4],
                    "close": row[5],
                    "volume": row[6],
                    "timeframe": row[7],
                    "bar_count": row[8],
                    "average": row[9],
                    "source": row[10],
                })

            logger.info("bars_retrieved", symbol=symbol, count=len(bars))
            return bars

        except Exception as e:
            logger.error("get_bars_error", symbol=symbol, error=str(e))
            return []

    async def get_bars_dataframe(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframe: str = "1 min",
    ):
        """Query historical bars as a pandas DataFrame.

        Args:
            symbol: Symbol to query
            start: Start datetime
            end: End datetime
            timeframe: Bar timeframe

        Returns:
            pandas DataFrame or None if pandas unavailable
        """
        bars = await self.get_bars(symbol, start, end, timeframe)

        if not PANDAS_AVAILABLE or not bars:
            return None

        df = pd.DataFrame(bars)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df.set_index("timestamp", inplace=True)
        return df

    async def store_tick(self, symbol: str, tick: Dict[str, Any]) -> bool:
        """Store a single tick data point.

        Args:
            symbol: Symbol identifier
            tick: Dict with bid, ask, last_price, bid_size, ask_size, last_size, volume

        Returns:
            True if successful
        """
        self._ensure_initialized()

        if not self.client:
            return True

        try:
            ts = tick.get("timestamp", datetime.now(timezone.utc))
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))

            data = [(
                symbol,
                ts,
                float(tick.get("bid", 0)),
                float(tick.get("ask", 0)),
                float(tick.get("last_price", tick.get("last", 0))),
                float(tick.get("bid_size", 0)),
                float(tick.get("ask_size", 0)),
                float(tick.get("last_size", 0)),
                float(tick.get("volume", 0)),
                tick.get("source", "ibkr"),
            )]

            columns = [
                "symbol", "timestamp", "bid", "ask", "last_price",
                "bid_size", "ask_size", "last_size", "volume", "source",
            ]
            self.client.insert_batch("market_data.ticks", data, columns)
            return True

        except Exception as e:
            logger.error("store_tick_error", symbol=symbol, error=str(e))
            return False

    async def store_ticks_batch(self, symbol: str, ticks: List[Dict[str, Any]]) -> bool:
        """Store multiple tick data points.

        Args:
            symbol: Symbol identifier
            ticks: List of tick dicts

        Returns:
            True if successful
        """
        if not ticks:
            return True

        self._ensure_initialized()

        if not self.client:
            return True

        try:
            data = []
            for tick in ticks:
                ts = tick.get("timestamp", datetime.now(timezone.utc))
                if isinstance(ts, str):
                    ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))

                data.append((
                    symbol,
                    ts,
                    float(tick.get("bid", 0)),
                    float(tick.get("ask", 0)),
                    float(tick.get("last_price", tick.get("last", 0))),
                    float(tick.get("bid_size", 0)),
                    float(tick.get("ask_size", 0)),
                    float(tick.get("last_size", 0)),
                    float(tick.get("volume", 0)),
                    tick.get("source", "ibkr"),
                ))

            columns = [
                "symbol", "timestamp", "bid", "ask", "last_price",
                "bid_size", "ask_size", "last_size", "volume", "source",
            ]
            self.client.insert_batch("market_data.ticks", data, columns)
            logger.info("ticks_stored", symbol=symbol, count=len(ticks))
            return True

        except Exception as e:
            logger.error("store_ticks_batch_error", symbol=symbol, error=str(e))
            return False

    async def get_ticks(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        limit: int = 10000,
    ) -> List[Dict[str, Any]]:
        """Query tick data from ClickHouse.

        Args:
            symbol: Symbol to query
            start: Start datetime
            end: End datetime
            limit: Maximum number of ticks to return

        Returns:
            List of tick dicts
        """
        self._ensure_initialized()

        if not self.client:
            return []

        try:
            query = """
                SELECT symbol, timestamp, bid, ask, last_price,
                       bid_size, ask_size, last_size, volume, source
                FROM market_data.ticks
                WHERE symbol = %(symbol)s
                  AND timestamp >= %(start)s
                  AND timestamp <= %(end)s
                ORDER BY timestamp ASC
                LIMIT %(limit)s
            """
            results = self.client.execute(query, {
                "symbol": symbol,
                "start": start.strftime("%Y-%m-%d %H:%M:%S"),
                "end": end.strftime("%Y-%m-%d %H:%M:%S"),
                "limit": limit,
            })

            return [
                {
                    "symbol": row[0],
                    "timestamp": row[1],
                    "bid": row[2],
                    "ask": row[3],
                    "last_price": row[4],
                    "bid_size": row[5],
                    "ask_size": row[6],
                    "last_size": row[7],
                    "volume": row[8],
                    "source": row[9],
                }
                for row in results
            ]

        except Exception as e:
            logger.error("get_ticks_error", symbol=symbol, error=str(e))
            return []

    async def store_quote_snapshot(self, symbol: str, quote: Dict[str, Any]) -> bool:
        """Store latest quote snapshot (ReplacingMergeTree keeps only latest).

        Args:
            symbol: Symbol identifier
            quote: Quote dict with bid, ask, last_price, volume, etc.

        Returns:
            True if successful
        """
        self._ensure_initialized()

        if not self.client:
            return True

        try:
            ts = quote.get("timestamp", datetime.now(timezone.utc))
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))

            data = [(
                symbol,
                ts,
                float(quote.get("bid", 0)),
                float(quote.get("ask", 0)),
                float(quote.get("last_price", quote.get("last", 0))),
                float(quote.get("bid_size", 0)),
                float(quote.get("ask_size", 0)),
                float(quote.get("volume", 0)),
                float(quote.get("high", 0)),
                float(quote.get("low", 0)),
                float(quote.get("close", 0)),
                quote.get("source", "ibkr"),
            )]

            columns = [
                "symbol", "timestamp", "bid", "ask", "last_price",
                "bid_size", "ask_size", "volume", "high", "low",
                "close", "source",
            ]
            self.client.insert_batch("market_data.quotes", data, columns)
            return True

        except Exception as e:
            logger.error("store_quote_error", symbol=symbol, error=str(e))
            return False

    async def get_latest_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get latest quote snapshot for a symbol.

        Args:
            symbol: Symbol to query

        Returns:
            Quote dict or None
        """
        self._ensure_initialized()

        if not self.client:
            return None

        try:
            query = """
                SELECT symbol, timestamp, bid, ask, last_price,
                       bid_size, ask_size, volume, high, low, close, source
                FROM market_data.quotes
                FINAL
                WHERE symbol = %(symbol)s
            """
            results = self.client.execute(query, {"symbol": symbol})

            if results:
                row = results[0]
                return {
                    "symbol": row[0],
                    "timestamp": row[1],
                    "bid": row[2],
                    "ask": row[3],
                    "last_price": row[4],
                    "bid_size": row[5],
                    "ask_size": row[6],
                    "volume": row[7],
                    "high": row[8],
                    "low": row[9],
                    "close": row[10],
                    "source": row[11],
                }
            return None

        except Exception as e:
            logger.error("get_latest_quote_error", symbol=symbol, error=str(e))
            return None


# Singleton
_timeseries_store: Optional[TimeSeriesStore] = None


def get_timeseries_store() -> TimeSeriesStore:
    """Get the global TimeSeriesStore instance."""
    global _timeseries_store
    if _timeseries_store is None:
        _timeseries_store = TimeSeriesStore()
    return _timeseries_store
