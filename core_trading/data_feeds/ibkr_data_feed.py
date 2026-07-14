"""IBKR Real-Time Market Data Feed.

Provides real-time and historical market data via Interactive Brokers TWS/Gateway.
Built on top of the IBKRAdapter's connection management.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import structlog

try:
    from ib_insync import IB, Contract, Stock, Option, Future, Forex, util
    IBKR_AVAILABLE = True
except ImportError:
    IBKR_AVAILABLE = False
    logging.warning(
        "ib_insync not available - IBKR data feed CANNOT provide live market data; "
        "connect() will raise. Install with: pip install ib_insync>=0.9.86"
    )

from core_trading.adapters.base import (
    AdapterConfig,
    AdapterType,
    BaseDataFeedAdapter,
    ConnectionStatus,
    HealthCheck,
)
from core_trading.adapters.ibkr_adapter import IBKRAdapter, AssetClass
from core_trading.adapters.brokers.rate_limiting import (
    RateLimiter,
    RateLimitConfig,
    RateLimitStrategy,
)

logger = structlog.get_logger(__name__)


@dataclass
class TickData:
    """Single tick data point."""
    symbol: str
    bid: Optional[float] = None
    ask: Optional[float] = None
    last: Optional[float] = None
    bid_size: Optional[float] = None
    ask_size: Optional[float] = None
    last_size: Optional[float] = None
    volume: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class BarData:
    """OHLCV bar data."""
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    bar_count: int = 0
    average: float = 0.0


class IBKRDataFeed(BaseDataFeedAdapter):
    """Real-time market data via IBKR TWS/Gateway.

    Provides:
    - Real-time ticker subscriptions (bid/ask/last/volume)
    - Level 2 order book data
    - Historical OHLCV bars
    - Tick-by-tick data
    """

    def __init__(self, ibkr_adapter: IBKRAdapter):
        config = AdapterConfig(
            name="ibkr_data_feed",
            adapter_type=AdapterType.DATA_FEED,
            auto_reconnect=True,
            max_reconnect_attempts=10,
        )
        super().__init__(config)

        self._adapter = ibkr_adapter
        self._ib: Optional[IB] = None
        self._subscriptions: Dict[str, Dict[str, Any]] = {}
        self._tickers: Dict[str, Any] = {}
        self._callbacks: Dict[str, List[Callable]] = {}
        self._subscription_counter = 0

        # Rate limiter: IBKR allows ~45 requests/second for market data
        self._rate_limiter = RateLimiter(RateLimitConfig(
            requests_per_second=45.0,
            burst_capacity=50,
            strategy=RateLimitStrategy.TOKEN_BUCKET,
        ))

    @property
    def ib(self) -> Optional[IB]:
        """Get IB instance from adapter."""
        if IBKR_AVAILABLE and self._adapter.ib:
            return self._adapter.ib
        return None

    async def _throttle(self):
        """Wait for rate limiter to allow a request."""
        await self._rate_limiter.acquire()

    async def connect(self) -> bool:
        """Connect via the IBKR adapter."""
        # Defense in depth: never allow a "connected" data feed without ib_insync.
        # The broker adapter enforces the same rule; we re-check here so a missing
        # ib_insync fails loudly at the data-feed boundary instead of silently
        # yielding empty market data.
        if not IBKR_AVAILABLE:
            raise RuntimeError(
                "ib_insync is not installed - IBKR data feed cannot provide live "
                "market data. Install with: pip install ib_insync>=0.9.86"
            )
        if not self._adapter.is_connected:
            success = await self._adapter.connect()
            if not success:
                return False

        self._ib = self.ib
        self._set_status(ConnectionStatus.CONNECTED)
        logger.info("ibkr_data_feed_connected")
        return True

    async def disconnect(self) -> bool:
        """Unsubscribe from all feeds and disconnect."""
        await self.unsubscribe_all()
        self._set_status(ConnectionStatus.DISCONNECTED)
        logger.info("ibkr_data_feed_disconnected")
        return True

    async def health_check(self) -> HealthCheck:
        """Check if the data feed is healthy."""
        if self._adapter.is_connected:
            return HealthCheck(
                status=ConnectionStatus.CONNECTED,
                timestamp=datetime.now(timezone.utc),
                metadata={
                    "active_subscriptions": len(self._subscriptions),
                    "mode": "simulation" if not IBKR_AVAILABLE else "live",
                },
            )
        return HealthCheck(
            status=ConnectionStatus.DISCONNECTED,
            timestamp=datetime.now(timezone.utc),
            error_message="IBKR adapter not connected",
        )

    async def subscribe_real_time(self, symbols: List[str]):
        """Subscribe to real-time market data for given symbols.

        Returns an async generator yielding tick data dicts.
        """
        queue: asyncio.Queue = asyncio.Queue()

        for symbol in symbols:
            await self.subscribe_ticker(symbol, lambda data, q=queue: q.put_nowait(data))

        while self.is_connected:
            try:
                data = await asyncio.wait_for(queue.get(), timeout=1.0)
                yield data
            except asyncio.TimeoutError:
                continue

    async def subscribe_ticker(self, symbol: str, callback: Callable) -> str:
        """Subscribe to real-time ticker updates.

        Args:
            symbol: Symbol to subscribe to (e.g. 'AAPL', 'ES', 'EURUSD')
            callback: Callable receiving TickData on each update

        Returns:
            Subscription ID string
        """
        if not self.is_connected:
            raise RuntimeError("Data feed not connected")

        self._subscription_counter += 1
        sub_id = f"tick_{symbol}_{self._subscription_counter}"

        if symbol not in self._callbacks:
            self._callbacks[symbol] = []
        self._callbacks[symbol].append(callback)

        if IBKR_AVAILABLE and self.ib:
            await self._throttle()
            contract = self._adapter._create_contract(symbol)
            ticker = self.ib.reqMktData(contract, "", False, False)
            ticker.updateEvent += lambda t, s=symbol: self._on_ticker_update(s, t)
            self._tickers[symbol] = ticker
            logger.info("ticker_subscribed", symbol=symbol, sub_id=sub_id)
        else:
            logger.info("ticker_subscribed_simulation", symbol=symbol, sub_id=sub_id)

        self._subscriptions[sub_id] = {
            "symbol": symbol,
            "type": "ticker",
            "callback": callback,
            "created_at": datetime.now(timezone.utc),
        }

        return sub_id

    async def subscribe_level2(self, symbol: str, callback: Callable) -> str:
        """Subscribe to Level 2 (order book) data.

        Args:
            symbol: Symbol to subscribe to
            callback: Callable receiving order book data dict

        Returns:
            Subscription ID string
        """
        if not self.is_connected:
            raise RuntimeError("Data feed not connected")

        await self._throttle()

        self._subscription_counter += 1
        sub_id = f"l2_{symbol}_{self._subscription_counter}"

        if f"l2_{symbol}" not in self._callbacks:
            self._callbacks[f"l2_{symbol}"] = []
        self._callbacks[f"l2_{symbol}"].append(callback)

        if IBKR_AVAILABLE and self.ib:
            contract = self._adapter._create_contract(symbol)
            ticker = self.ib.reqMktData(contract, "", False, False)
            ticker.updateEvent += lambda t, s=symbol: self._on_level2_update(s, t)
            self._tickers[f"l2_{symbol}"] = ticker
            logger.info("level2_subscribed", symbol=symbol, sub_id=sub_id)
        else:
            logger.info("level2_subscribed_simulation", symbol=symbol, sub_id=sub_id)

        self._subscriptions[sub_id] = {
            "symbol": symbol,
            "type": "level2",
            "callback": callback,
            "created_at": datetime.now(timezone.utc),
        }

        return sub_id

    async def get_historical_data(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        timeframe: str = "1 min",
    ) -> List[Dict[str, Any]]:
        """Get historical market data bars.

        Args:
            symbol: Symbol to query
            start_date: Start of date range
            end_date: End of date range
            timeframe: Bar size ('1 sec', '5 secs', '10 secs', '15 secs',
                       '30 secs', '1 min', '2 mins', '3 mins', '5 mins',
                       '10 mins', '15 mins', '20 mins', '30 mins',
                       '1 hour', '2 hours', '3 hours', '4 hours',
                       '8 hours', '1 day', '1 week', '1 month')

        Returns:
            List of bar dicts with keys: date, open, high, low, close, volume
        """
        if not self.is_connected:
            raise RuntimeError("Data feed not connected")

        await self._throttle()
        duration = self._calculate_duration(start_date, end_date)

        if not IBKR_AVAILABLE or not self.ib:
            logger.info("historical_data_simulation", symbol=symbol, timeframe=timeframe)
            return []

        try:
            contract = self._adapter._create_contract(symbol)
            bars = await self.ib.reqHistoricalDataAsync(
                contract,
                endDateTime=end_date,
                durationStr=duration,
                barSizeSetting=timeframe,
                whatToShow="TRADES",
                useRTH=True,
            )

            result = []
            for bar in bars:
                bar_time = bar.date
                if bar_time.tzinfo is None:
                    bar_time = bar_time.replace(tzinfo=timezone.utc)

                if start_date <= bar_time <= end_date:
                    result.append({
                        "date": str(bar.date),
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "volume": bar.volume,
                        "bar_count": bar.barCount,
                        "average": bar.average,
                    })

            logger.info(
                "historical_data_retrieved",
                symbol=symbol,
                bars=len(result),
                timeframe=timeframe,
            )
            return result

        except Exception as e:
            logger.error("historical_data_error", symbol=symbol, error=str(e))
            return []

    async def get_historical_bars(
        self,
        symbol: str,
        duration: str = "1 D",
        bar_size: str = "1 min",
    ) -> List[BarData]:
        """Get historical OHLCV data as BarData objects.

        Args:
            symbol: Symbol to query
            duration: IBKR duration string ('60 S', '30 D', '13 W', '6 M', '10 Y')
            bar_size: Bar size ('1 min', '5 mins', '1 hour', '1 day', etc.)

        Returns:
            List of BarData objects
        """
        if not self.is_connected:
            raise RuntimeError("Data feed not connected")

        if not IBKR_AVAILABLE or not self.ib:
            logger.info("historical_bars_simulation", symbol=symbol)
            return []

        await self._throttle()

        try:
            contract = self._adapter._create_contract(symbol)
            bars = await self.ib.reqHistoricalDataAsync(
                contract,
                endDateTime="",
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow="TRADES",
                useRTH=True,
            )

            result = []
            for bar in bars:
                result.append(BarData(
                    symbol=symbol,
                    timestamp=bar.date if hasattr(bar.date, 'tzinfo') else datetime.now(timezone.utc),
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                    bar_count=bar.barCount,
                    average=bar.average,
                ))

            logger.info(
                "historical_bars_retrieved",
                symbol=symbol,
                bars=len(result),
                bar_size=bar_size,
            )
            return result

        except Exception as e:
            logger.error("historical_bars_error", symbol=symbol, error=str(e))
            return []

    async def get_quote(self, symbol: str) -> Dict[str, Any]:
        """Get current quote for a symbol.

        Args:
            symbol: Symbol to quote

        Returns:
            Dict with bid, ask, last, volume, timestamp
        """
        if not self.is_connected:
            raise RuntimeError("Data feed not connected")

        await self._throttle()

        if IBKR_AVAILABLE and self.ib:
            contract = self._adapter._create_contract(symbol)
            ticker = self.ib.reqMktData(contract, "", False, False)
            await asyncio.sleep(0.5)  # Wait for initial data

            return {
                "symbol": symbol,
                "bid": ticker.bid if util.isFinite(ticker.bid) else None,
                "ask": ticker.ask if util.isFinite(ticker.ask) else None,
                "last": ticker.last if util.isFinite(ticker.last) else None,
                "bid_size": ticker.bidSize,
                "ask_size": ticker.askSize,
                "last_size": ticker.lastSize,
                "volume": ticker.volume,
                "high": ticker.high if util.isFinite(ticker.high) else None,
                "low": ticker.low if util.isFinite(ticker.low) else None,
                "close": ticker.close if util.isFinite(ticker.close) else None,
                "timestamp": datetime.now(timezone.utc),
            }

        return {
            "symbol": symbol,
            "bid": None,
            "ask": None,
            "last": None,
            "volume": None,
            "timestamp": datetime.now(timezone.utc),
            "mode": "simulation",
        }

    async def search_symbols(self, query: str) -> List[Dict[str, Any]]:
        """Search for symbols matching query.

        Args:
            query: Search string (e.g. 'Apple', 'AAPL', 'S&P 500')

        Returns:
            List of symbol info dicts
        """
        if not self.is_connected:
            raise RuntimeError("Data feed not connected")

        if not IBKR_AVAILABLE or not self.ib:
            return [{"symbol": query.upper(), "name": query, "exchange": "SMART"}]

        await self._throttle()

        try:
            results = self.ib.reqSymbols(query)
            return [
                {
                    "symbol": r.symbol,
                    "name": r.name if hasattr(r, 'name') else r.symbol,
                    "exchange": r.exchange,
                    "sec_type": r.secType,
                    "con_id": r.conId,
                }
                for r in results[:20]
            ]
        except Exception as e:
            logger.error("symbol_search_error", query=query, error=str(e))
            return []

    async def unsubscribe(self, subscription_id: str):
        """Cancel a market data subscription.

        Args:
            subscription_id: The subscription ID returned by subscribe_ticker/level2
        """
        sub = self._subscriptions.pop(subscription_id, None)
        if not sub:
            logger.warning("subscription_not_found", sub_id=subscription_id)
            return

        symbol = sub["symbol"]
        sub_type = sub["type"]
        callback = sub["callback"]

        key = f"{sub_type}_{symbol}" if sub_type == "level2" else symbol
        if key in self._callbacks:
            self._callbacks[key] = [cb for cb in self._callbacks[key] if cb != callback]
            if not self._callbacks[key]:
                del self._callbacks[key]

                # Cancel the market data request if no more subscribers
                ticker_key = f"l2_{symbol}" if sub_type == "level2" else symbol
                if ticker_key in self._tickers and IBKR_AVAILABLE and self.ib:
                    ticker = self._tickers.pop(ticker_key)
                    self.ib.cancelMktData(ticker.contract)

        logger.info("unsubscribed", sub_id=subscription_id, symbol=symbol)

    async def unsubscribe_all(self):
        """Cancel all active subscriptions."""
        sub_ids = list(self._subscriptions.keys())
        for sub_id in sub_ids:
            await self.unsubscribe(sub_id)

        # Cancel any remaining tickers
        if IBKR_AVAILABLE and self.ib:
            for key, ticker in list(self._tickers.items()):
                try:
                    self.ib.cancelMktData(ticker.contract)
                except Exception as e:
                    logger.warning("cancel_mkt_data_error", key=key, error=str(e))
        self._tickers.clear()
        self._callbacks.clear()

        logger.info("all_subscriptions_cancelled")

    @staticmethod
    def _finite_or_none(value):
        """Return ``value`` if it is a finite number, else ``None``.

        IBKR reports NaN for unset ticker fields. ``ib_insync.util`` historically
        exposed ``isFinite`` but it was removed; we use ``math.isfinite`` which is
        the stable, version-independent equivalent.
        """
        import math

        try:
            if value is None:
                return None
            return value if math.isfinite(float(value)) else None
        except (TypeError, ValueError):
            return None

    def _on_ticker_update(self, symbol: str, ticker):
        """Handle incoming ticker update from IBKR."""
        f = self._finite_or_none
        data = {
            "symbol": symbol,
            "bid": f(ticker.bid),
            "ask": f(ticker.ask),
            "last": f(ticker.last),
            "bid_size": ticker.bidSize,
            "ask_size": ticker.askSize,
            "last_size": ticker.lastSize,
            "volume": ticker.volume,
            "high": f(ticker.high),
            "low": f(ticker.low),
            "close": f(ticker.close),
            "timestamp": datetime.now(timezone.utc),
        }

        for callback in self._callbacks.get(symbol, []):
            try:
                callback(data)
            except Exception as e:
                logger.error("ticker_callback_error", symbol=symbol, error=str(e))

    def _on_level2_update(self, symbol: str, ticker):
        """Handle Level 2 order book update."""
        data = {
            "symbol": symbol,
            "timestamp": datetime.now(timezone.utc),
        }

        if IBKR_AVAILABLE and hasattr(ticker, 'domBids') and ticker.domBids:
            data["bids"] = [
                {"price": row.price, "size": row.size}
                for row in ticker.domBids[:10]
            ]
        if IBKR_AVAILABLE and hasattr(ticker, 'domAsks') and ticker.domAsks:
            data["asks"] = [
                {"price": row.price, "size": row.size}
                for row in ticker.domAsks[:10]
            ]

        key = f"l2_{symbol}"
        for callback in self._callbacks.get(key, []):
            try:
                callback(data)
            except Exception as e:
                logger.error("level2_callback_error", symbol=symbol, error=str(e))

    def _calculate_duration(self, start_date: datetime, end_date: datetime) -> str:
        """Calculate IBKR duration string from date range."""
        delta = end_date - start_date
        total_seconds = delta.total_seconds()

        if total_seconds <= 60:
            return "60 S"
        elif total_seconds <= 3600:
            return f"{int(total_seconds / 60)} S"
        elif total_seconds <= 86400:
            return f"{max(1, int(total_seconds / 3600))} S"
        elif total_seconds <= 86400 * 30:
            return f"{max(1, int(total_seconds / 86400))} D"
        elif total_seconds <= 86400 * 365:
            return f"{max(1, int(total_seconds / (86400 * 7)))} W"
        else:
            return f"{max(1, int(total_seconds / (86400 * 30)))} M"


# Singleton
_ibkr_data_feed: Optional[IBKRDataFeed] = None


def get_ibkr_data_feed(adapter: Optional[IBKRAdapter] = None) -> IBKRDataFeed:
    """Get the global IBKR data feed instance."""
    global _ibkr_data_feed
    if _ibkr_data_feed is None:
        from core_trading.adapters.ibkr_adapter import get_ibkr_adapter
        _ibkr_data_feed = IBKRDataFeed(adapter or get_ibkr_adapter())
    return _ibkr_data_feed
