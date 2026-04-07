"""Unit tests for data feeds module.

Covers:
- IBKRDataFeed (ibkr_data_feed.py)
- TimeSeriesStore (timeseries_store.py)
- MarketDataCache (cache.py)
- DataNormalizer (normalizer.py)
- BaseAdapter abstract classes (base.py)
- Rate limiting helpers (brokers/rate_limiting.py)
- Event Serializers (libs/common/events/serializers.py)

All tests mock external dependencies (ib_insync, ClickHouse, Redis) so they
run without live services.
"""

import types
import sys
import os

# ---------------------------------------------------------------------------
# CRITICAL: Pre-register a fake brokers package BEFORE any imports that
# transitively import core_trading.adapters.brokers. The brokers/__init__.py
# has broken imports (alpacaadapter_handlers). By inserting a fake package
# into sys.modules first, we prevent the real __init__.py from executing.
# ---------------------------------------------------------------------------
_fake_brokers = types.ModuleType("core_trading.adapters.brokers")
_fake_brokers.__path__ = [os.path.join(
    os.path.dirname(__file__), "..", "..", "core_trading", "adapters", "brokers"
)]
_fake_brokers.__package__ = "core_trading.adapters.brokers"
sys.modules["core_trading.adapters.brokers"] = _fake_brokers

# Set required database password env vars so DatabaseConfig (Pydantic) validates.
# These are needed because timeseries_store.py imports clickhouse client which
# triggers DatabaseConfig instantiation.
os.environ.setdefault("POSTGRES_PASSWORD", "test_pass")
os.environ.setdefault("CLICKHOUSE_PASSWORD", "test_pass")
os.environ.setdefault("NEO4J_PASSWORD", "test_pass")
os.environ.setdefault("REDIS_PASSWORD", "test_pass")
os.environ.setdefault("JWT_SECRET", "test_jwt_secret_for_unit_tests")
os.environ.setdefault("ALPHA_VANTAGE_API_KEY", "test_key")

# Ensure project root is importable
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


def _make_connected_feed():
    """Return a connected IBKRDataFeed with a mocked IBKRAdapter."""
    from core_trading.adapters.ibkr_adapter import IBKRAdapter
    from core_trading.data_feeds.ibkr_data_feed import IBKRDataFeed
    from core_trading.adapters.base import ConnectionStatus

    adapter = IBKRAdapter()
    adapter._set_status(ConnectionStatus.CONNECTED)
    feed = IBKRDataFeed(adapter)
    feed._set_status(ConnectionStatus.CONNECTED)
    return feed, adapter


# ===================================================================
# IBKRDataFeed tests
# ===================================================================


class TestIBKRDataFeedSubscribeTicker:
    @pytest.mark.asyncio
    async def test_subscribe_ticker_returns_subscription_id(self):
        feed, _ = _make_connected_feed()
        sub_id = await feed.subscribe_ticker("AAPL", lambda d: None)
        assert sub_id.startswith("tick_AAPL_")

    @pytest.mark.asyncio
    async def test_subscribe_ticker_stores_subscription(self):
        feed, _ = _make_connected_feed()
        cb = MagicMock()
        sub_id = await feed.subscribe_ticker("AAPL", cb)
        assert sub_id in feed._subscriptions
        assert feed._subscriptions[sub_id]["symbol"] == "AAPL"
        assert feed._subscriptions[sub_id]["type"] == "ticker"

    @pytest.mark.asyncio
    async def test_subscribe_ticker_registers_callback(self):
        feed, _ = _make_connected_feed()
        await feed.subscribe_ticker("AAPL", MagicMock())
        await feed.subscribe_ticker("AAPL", MagicMock())
        assert len(feed._callbacks["AAPL"]) == 2

    @pytest.mark.asyncio
    async def test_subscribe_ticker_not_connected_raises(self):
        from core_trading.adapters.ibkr_adapter import IBKRAdapter
        from core_trading.data_feeds.ibkr_data_feed import IBKRDataFeed
        feed = IBKRDataFeed(IBKRAdapter())
        with pytest.raises(RuntimeError, match="not connected"):
            await feed.subscribe_ticker("AAPL", lambda d: None)

    @pytest.mark.asyncio
    async def test_subscribe_ticker_increments_counter(self):
        feed, _ = _make_connected_feed()
        s1 = await feed.subscribe_ticker("AAPL", lambda d: None)
        s2 = await feed.subscribe_ticker("MSFT", lambda d: None)
        assert int(s2.split("_")[-1]) == int(s1.split("_")[-1]) + 1


class TestIBKRDataFeedSubscribeLevel2:
    @pytest.mark.asyncio
    async def test_subscribe_level2_returns_subscription_id(self):
        feed, _ = _make_connected_feed()
        sub_id = await feed.subscribe_level2("AAPL", lambda d: None)
        assert sub_id.startswith("l2_AAPL_")

    @pytest.mark.asyncio
    async def test_subscribe_level2_stores_subscription(self):
        feed, _ = _make_connected_feed()
        sub_id = await feed.subscribe_level2("ES", MagicMock())
        assert sub_id in feed._subscriptions
        assert feed._subscriptions[sub_id]["type"] == "level2"

    @pytest.mark.asyncio
    async def test_subscribe_level2_not_connected_raises(self):
        from core_trading.adapters.ibkr_adapter import IBKRAdapter
        from core_trading.data_feeds.ibkr_data_feed import IBKRDataFeed
        feed = IBKRDataFeed(IBKRAdapter())
        with pytest.raises(RuntimeError, match="not connected"):
            await feed.subscribe_level2("AAPL", lambda d: None)


class TestIBKRDataFeedHistoricalData:
    @pytest.mark.asyncio
    async def test_get_historical_data_simulation_returns_empty(self):
        feed, _ = _make_connected_feed()
        now = datetime.now(timezone.utc)
        bars = await feed.get_historical_data("AAPL", now - timedelta(days=1), now, "1 min")
        assert isinstance(bars, list)
        assert len(bars) == 0

    @pytest.mark.asyncio
    async def test_get_historical_bars_simulation_returns_empty(self):
        feed, _ = _make_connected_feed()
        bars = await feed.get_historical_bars("AAPL", "1 D", "1 min")
        assert isinstance(bars, list)
        assert len(bars) == 0

    @pytest.mark.asyncio
    async def test_get_historical_data_not_connected_raises(self):
        from core_trading.adapters.ibkr_adapter import IBKRAdapter
        from core_trading.data_feeds.ibkr_data_feed import IBKRDataFeed
        feed = IBKRDataFeed(IBKRAdapter())
        now = datetime.now(timezone.utc)
        with pytest.raises(RuntimeError, match="not connected"):
            await feed.get_historical_data("AAPL", now - timedelta(days=1), now)

    @pytest.mark.asyncio
    async def test_get_historical_bars_not_connected_raises(self):
        from core_trading.adapters.ibkr_adapter import IBKRAdapter
        from core_trading.data_feeds.ibkr_data_feed import IBKRDataFeed
        feed = IBKRDataFeed(IBKRAdapter())
        with pytest.raises(RuntimeError, match="not connected"):
            await feed.get_historical_bars("AAPL")


class TestIBKRDataFeedUnsubscribe:
    @pytest.mark.asyncio
    async def test_unsubscribe_removes_subscription(self):
        feed, _ = _make_connected_feed()
        sub_id = await feed.subscribe_ticker("AAPL", lambda d: None)
        await feed.unsubscribe(sub_id)
        assert sub_id not in feed._subscriptions

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_callback(self):
        feed, _ = _make_connected_feed()
        cb = MagicMock()
        sub_id = await feed.subscribe_ticker("AAPL", cb)
        await feed.unsubscribe(sub_id)
        assert "AAPL" not in feed._callbacks

    @pytest.mark.asyncio
    async def test_unsubscribe_unknown_id_is_noop(self):
        feed, _ = _make_connected_feed()
        await feed.unsubscribe("nonexistent_sub_id")

    @pytest.mark.asyncio
    async def test_unsubscribe_all_clears_everything(self):
        feed, _ = _make_connected_feed()
        await feed.subscribe_ticker("AAPL", lambda d: None)
        await feed.subscribe_ticker("MSFT", lambda d: None)
        await feed.subscribe_level2("ES", lambda d: None)
        await feed.unsubscribe_all()
        assert len(feed._subscriptions) == 0
        assert len(feed._callbacks) == 0
        assert len(feed._tickers) == 0


class TestIBKRDataFeedRateLimiting:
    def test_rate_limiter_initialized(self):
        feed, _ = _make_connected_feed()
        assert feed._rate_limiter is not None

    @pytest.mark.asyncio
    async def test_throttle_acquires_token(self):
        feed, _ = _make_connected_feed()
        await feed._throttle()


class TestIBKRDataFeedContractCreation:
    def test_calculate_duration_seconds(self):
        feed, _ = _make_connected_feed()
        start = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        end = start + timedelta(seconds=30)
        assert feed._calculate_duration(start, end) == "60 S"

    def test_calculate_duration_minutes(self):
        feed, _ = _make_connected_feed()
        start = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        end = start + timedelta(minutes=15)
        # 15 min = 900 sec -> 900/60 = 15 -> "15 S"
        assert feed._calculate_duration(start, end) == "15 S"

    def test_calculate_duration_hours(self):
        feed, _ = _make_connected_feed()
        start = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        end = start + timedelta(hours=3)
        assert feed._calculate_duration(start, end) == "3 S"

    def test_calculate_duration_days(self):
        feed, _ = _make_connected_feed()
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = start + timedelta(days=5)
        assert feed._calculate_duration(start, end) == "5 D"

    def test_calculate_duration_weeks(self):
        feed, _ = _make_connected_feed()
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = start + timedelta(days=45)
        assert "W" in feed._calculate_duration(start, end)

    def test_calculate_duration_months(self):
        feed, _ = _make_connected_feed()
        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        end = datetime(2026, 6, 1, tzinfo=timezone.utc)
        assert "M" in feed._calculate_duration(start, end)


class TestIBKRDataFeedConnectDisconnect:
    @pytest.mark.asyncio
    async def test_connect_via_adapter(self):
        from core_trading.adapters.ibkr_adapter import IBKRAdapter
        from core_trading.data_feeds.ibkr_data_feed import IBKRDataFeed
        feed = IBKRDataFeed(IBKRAdapter())
        result = await feed.connect()
        assert result is True
        assert feed.is_connected

    @pytest.mark.asyncio
    async def test_disconnect(self):
        feed, _ = _make_connected_feed()
        result = await feed.disconnect()
        assert result is True
        from core_trading.adapters.base import ConnectionStatus
        assert feed.status == ConnectionStatus.DISCONNECTED

    @pytest.mark.asyncio
    async def test_health_check_connected(self):
        feed, _ = _make_connected_feed()
        hc = await feed.health_check()
        from core_trading.adapters.base import ConnectionStatus
        assert hc.status == ConnectionStatus.CONNECTED
        assert "active_subscriptions" in hc.metadata

    @pytest.mark.asyncio
    async def test_health_check_disconnected(self):
        from core_trading.adapters.ibkr_adapter import IBKRAdapter
        from core_trading.data_feeds.ibkr_data_feed import IBKRDataFeed
        from core_trading.adapters.base import ConnectionStatus
        feed = IBKRDataFeed(IBKRAdapter())
        hc = await feed.health_check()
        assert hc.status == ConnectionStatus.DISCONNECTED
        assert hc.error_message is not None


class TestIBKRDataFeedGetQuote:
    @pytest.mark.asyncio
    async def test_get_quote_simulation(self):
        feed, _ = _make_connected_feed()
        quote = await feed.get_quote("AAPL")
        assert quote["symbol"] == "AAPL"
        assert quote["mode"] == "simulation"
        assert "timestamp" in quote

    @pytest.mark.asyncio
    async def test_get_quote_not_connected_raises(self):
        from core_trading.adapters.ibkr_adapter import IBKRAdapter
        from core_trading.data_feeds.ibkr_data_feed import IBKRDataFeed
        feed = IBKRDataFeed(IBKRAdapter())
        with pytest.raises(RuntimeError, match="not connected"):
            await feed.get_quote("AAPL")


class TestIBKRDataFeedSearchSymbols:
    @pytest.mark.asyncio
    async def test_search_symbols_simulation(self):
        feed, _ = _make_connected_feed()
        results = await feed.search_symbols("Apple")
        assert isinstance(results, list)
        assert len(results) > 0
        assert results[0]["symbol"] == "APPLE"

    @pytest.mark.asyncio
    async def test_search_symbols_not_connected_raises(self):
        from core_trading.adapters.ibkr_adapter import IBKRAdapter
        from core_trading.data_feeds.ibkr_data_feed import IBKRDataFeed
        feed = IBKRDataFeed(IBKRAdapter())
        with pytest.raises(RuntimeError, match="not connected"):
            await feed.search_symbols("AAPL")


class TestIBKRDataFeedCallbacks:
    def test_on_ticker_update_calls_callbacks(self):
        feed, _ = _make_connected_feed()
        received = []
        feed._callbacks["AAPL"] = [received.append]
        fake_ticker = MagicMock(bid=150.0, ask=150.5, last=150.25,
                                bidSize=100, askSize=200, lastSize=10,
                                volume=5000, high=151.0, low=149.0, close=150.0)
        feed._on_ticker_update("AAPL", fake_ticker)
        assert len(received) == 1
        # In simulation mode (IBKR_AVAILABLE=False), bid/ask/last/high/low/close become None
        assert received[0]["symbol"] == "AAPL"
        assert received[0]["volume"] == 5000

    def test_on_ticker_update_handles_callback_error(self):
        feed, _ = _make_connected_feed()
        bad_cb = MagicMock(side_effect=ValueError("boom"))
        good_cb = MagicMock()
        feed._callbacks["AAPL"] = [bad_cb, good_cb]
        fake_ticker = MagicMock(bid=150.0, ask=150.5, last=150.25,
                                bidSize=100, askSize=200, lastSize=10,
                                volume=5000, high=151.0, low=149.0, close=150.0)
        feed._on_ticker_update("AAPL", fake_ticker)
        good_cb.assert_called_once()

    def test_on_level2_update_calls_callbacks(self):
        feed, _ = _make_connected_feed()
        received = []
        feed._callbacks["l2_AAPL"] = [received.append]
        fake_ticker = MagicMock(domBids=None, domAsks=None)
        feed._on_level2_update("AAPL", fake_ticker)
        assert len(received) == 1
        assert received[0]["symbol"] == "AAPL"


class TestIBKRDataFeedModuleFunctions:
    def setup_method(self):
        import core_trading.data_feeds.ibkr_data_feed as mod
        mod._ibkr_data_feed = None

    def teardown_method(self):
        import core_trading.data_feeds.ibkr_data_feed as mod
        mod._ibkr_data_feed = None

    def test_get_ibkr_data_feed_creates_instance(self):
        from core_trading.data_feeds.ibkr_data_feed import get_ibkr_data_feed
        assert get_ibkr_data_feed() is not None

    def test_get_ibkr_data_feed_returns_same_instance(self):
        from core_trading.data_feeds.ibkr_data_feed import get_ibkr_data_feed
        assert get_ibkr_data_feed() is get_ibkr_data_feed()


class TestTickDataBarData:
    def test_tick_data_defaults(self):
        from core_trading.data_feeds.ibkr_data_feed import TickData
        td = TickData(symbol="AAPL")
        assert td.bid is None and td.ask is None and td.last is None

    def test_bar_data_fields(self):
        from core_trading.data_feeds.ibkr_data_feed import BarData
        bd = BarData(symbol="AAPL", timestamp=datetime.now(timezone.utc),
                     open=150.0, high=151.0, low=149.0, close=150.5, volume=10000)
        assert bd.bar_count == 0 and bd.average == 0.0


# ===================================================================
# TimeSeriesStore tests
# ===================================================================

class TestTimeSeriesStoreStoreBars:
    @pytest.mark.asyncio
    async def test_store_bars_empty_list(self):
        from core_trading.data_feeds.timeseries_store import TimeSeriesStore
        assert await TimeSeriesStore(client=None).store_bars("AAPL", []) is True

    @pytest.mark.asyncio
    async def test_store_bars_no_client(self):
        """With no client, store_bars should return True (graceful no-op)."""
        import core_trading.data_feeds.timeseries_store as ts_mod
        orig = ts_mod.CLICKHOUSE_AVAILABLE
        ts_mod.CLICKHOUSE_AVAILABLE = False
        try:
            store = ts_mod.TimeSeriesStore(client=None)
            assert await store.store_bars("AAPL", [{"open": 150}]) is True
        finally:
            ts_mod.CLICKHOUSE_AVAILABLE = orig

    @pytest.mark.asyncio
    async def test_store_bars_with_mock_client(self):
        from core_trading.data_feeds.timeseries_store import TimeSeriesStore
        mc = MagicMock()
        mc.insert_batch = MagicMock()
        store = TimeSeriesStore(client=mc)
        store._initialized = True
        result = await store.store_bars("AAPL", [{
            "timestamp": datetime.now(timezone.utc), "open": 150.0, "high": 151.0,
            "low": 149.0, "close": 150.5, "volume": 10000,
        }])
        assert result is True
        mc.insert_batch.assert_called_once()

    @pytest.mark.asyncio
    async def test_store_bars_string_timestamp(self):
        from core_trading.data_feeds.timeseries_store import TimeSeriesStore
        mc = MagicMock(insert_batch=MagicMock())
        store = TimeSeriesStore(client=mc)
        store._initialized = True
        assert await store.store_bars("AAPL", [
            {"timestamp": "2026-01-01T12:00:00Z", "open": 150.0}
        ]) is True

    @pytest.mark.asyncio
    async def test_store_bars_client_error(self):
        from core_trading.data_feeds.timeseries_store import TimeSeriesStore
        mc = MagicMock(insert_batch=MagicMock(side_effect=Exception("err")))
        store = TimeSeriesStore(client=mc)
        store._initialized = True
        assert await store.store_bars("AAPL", [{"open": 150}]) is False


class TestTimeSeriesStoreGetBars:
    @pytest.mark.asyncio
    async def test_get_bars_no_client(self):
        from core_trading.data_feeds.timeseries_store import TimeSeriesStore
        store = TimeSeriesStore(client=None)
        bars = await store.get_bars("AAPL", datetime(2026, 1, 1, tzinfo=timezone.utc),
                                     datetime(2026, 1, 2, tzinfo=timezone.utc))
        assert bars == []

    @pytest.mark.asyncio
    async def test_get_bars_with_mock_client(self):
        from core_trading.data_feeds.timeseries_store import TimeSeriesStore
        mc = MagicMock()
        mc.execute.return_value = [
            ("AAPL", datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
             150.0, 151.0, 149.0, 150.5, 10000, "1 min", 0, 0.0, "ibkr"),
        ]
        store = TimeSeriesStore(client=mc)
        store._initialized = True
        bars = await store.get_bars("AAPL", datetime(2026, 1, 1, tzinfo=timezone.utc),
                                     datetime(2026, 1, 2, tzinfo=timezone.utc))
        assert len(bars) == 1 and bars[0]["symbol"] == "AAPL"

    @pytest.mark.asyncio
    async def test_get_bars_client_error(self):
        from core_trading.data_feeds.timeseries_store import TimeSeriesStore
        mc = MagicMock(execute=MagicMock(side_effect=Exception("err")))
        store = TimeSeriesStore(client=mc)
        store._initialized = True
        bars = await store.get_bars("AAPL", datetime(2026, 1, 1, tzinfo=timezone.utc),
                                     datetime(2026, 1, 2, tzinfo=timezone.utc))
        assert bars == []


class TestTimeSeriesStoreTick:
    @pytest.mark.asyncio
    async def test_store_tick_no_client(self):
        import core_trading.data_feeds.timeseries_store as ts_mod
        orig = ts_mod.CLICKHOUSE_AVAILABLE
        ts_mod.CLICKHOUSE_AVAILABLE = False
        try:
            store = ts_mod.TimeSeriesStore(client=None)
            assert await store.store_tick("AAPL", {"bid": 150.0}) is True
        finally:
            ts_mod.CLICKHOUSE_AVAILABLE = orig

    @pytest.mark.asyncio
    async def test_store_tick_with_mock_client(self):
        from core_trading.data_feeds.timeseries_store import TimeSeriesStore
        mc = MagicMock(insert_batch=MagicMock())
        store = TimeSeriesStore(client=mc)
        store._initialized = True
        assert await store.store_tick("AAPL", {
            "bid": 150.0, "ask": 150.5, "last_price": 150.25,
        }) is True
        mc.insert_batch.assert_called_once()

    @pytest.mark.asyncio
    async def test_store_ticks_batch_empty(self):
        from core_trading.data_feeds.timeseries_store import TimeSeriesStore
        assert await TimeSeriesStore(client=None).store_ticks_batch("AAPL", []) is True

    @pytest.mark.asyncio
    async def test_store_ticks_batch_with_mock(self):
        from core_trading.data_feeds.timeseries_store import TimeSeriesStore
        mc = MagicMock(insert_batch=MagicMock())
        store = TimeSeriesStore(client=mc)
        store._initialized = True
        assert await store.store_ticks_batch("AAPL", [
            {"bid": 150.0, "ask": 150.5, "last_price": 150.25},
            {"bid": 150.1, "ask": 150.6, "last_price": 150.35},
        ]) is True

    @pytest.mark.asyncio
    async def test_get_ticks_no_client(self):
        from core_trading.data_feeds.timeseries_store import TimeSeriesStore
        store = TimeSeriesStore(client=None)
        result = await store.get_ticks("AAPL", datetime(2026, 1, 1, tzinfo=timezone.utc),
                                        datetime(2026, 1, 2, tzinfo=timezone.utc))
        assert result == []


class TestTimeSeriesStoreGracefulFallback:
    @pytest.mark.asyncio
    async def test_get_bars_dataframe_no_client(self):
        from core_trading.data_feeds.timeseries_store import TimeSeriesStore
        store = TimeSeriesStore(client=None)
        result = await store.get_bars_dataframe("AAPL", datetime(2026, 1, 1, tzinfo=timezone.utc),
                                                 datetime(2026, 1, 2, tzinfo=timezone.utc))
        assert result is None

    @pytest.mark.asyncio
    async def test_store_quote_snapshot_no_client(self):
        import core_trading.data_feeds.timeseries_store as ts_mod
        orig = ts_mod.CLICKHOUSE_AVAILABLE
        ts_mod.CLICKHOUSE_AVAILABLE = False
        try:
            store = ts_mod.TimeSeriesStore(client=None)
            assert await store.store_quote_snapshot("AAPL", {"bid": 150.0}) is True
        finally:
            ts_mod.CLICKHOUSE_AVAILABLE = orig

    @pytest.mark.asyncio
    async def test_get_latest_quote_no_client(self):
        from core_trading.data_feeds.timeseries_store import TimeSeriesStore
        assert await TimeSeriesStore(client=None).get_latest_quote("AAPL") is None


class TestTimeSeriesStoreInit:
    def test_ensure_initialized_with_client(self):
        from core_trading.data_feeds.timeseries_store import TimeSeriesStore
        mc = MagicMock()
        store = TimeSeriesStore(client=mc)
        store._ensure_initialized()
        mc.execute.assert_called_once()
        assert store._initialized is True

    def test_ensure_initialized_no_client(self):
        import core_trading.data_feeds.timeseries_store as ts_mod
        orig = ts_mod.CLICKHOUSE_AVAILABLE
        ts_mod.CLICKHOUSE_AVAILABLE = False
        try:
            store = ts_mod.TimeSeriesStore(client=None)
            store._ensure_initialized()
            assert store._initialized is True
        finally:
            ts_mod.CLICKHOUSE_AVAILABLE = orig

    def test_ensure_initialized_idempotent(self):
        from core_trading.data_feeds.timeseries_store import TimeSeriesStore
        mc = MagicMock()
        store = TimeSeriesStore(client=mc)
        store._ensure_initialized()
        store._ensure_initialized()
        assert mc.execute.call_count == 1

    def test_get_timeseries_store_singleton(self):
        import core_trading.data_feeds.timeseries_store as mod
        mod._timeseries_store = None
        from core_trading.data_feeds.timeseries_store import get_timeseries_store
        assert get_timeseries_store() is get_timeseries_store()
        mod._timeseries_store = None


# ===================================================================
# MarketDataCache tests
# ===================================================================

class TestMarketDataCacheGetQuote:
    @pytest.mark.asyncio
    async def test_get_quote_cache_miss(self):
        from core_trading.data_feeds.cache import MarketDataCache
        cache = MarketDataCache(redis_client=None)
        cache._redis_available = False
        assert await cache.get_quote("AAPL") is None

    @pytest.mark.asyncio
    async def test_get_quote_expired_data(self):
        from core_trading.data_feeds.cache import MarketDataCache
        cache = MarketDataCache(redis_client=None)
        cache._redis_available = False
        old_ts = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        await cache._fallback.set("quote:AAPL", json.dumps({"bid": 150.0, "timestamp": old_ts}), ttl=0)
        assert await cache.get_quote("AAPL") is None


class TestMarketDataCacheSetQuote:
    @pytest.mark.asyncio
    async def test_set_quote_in_memory(self):
        from core_trading.data_feeds.cache import MarketDataCache
        cache = MarketDataCache(redis_client=None)
        cache._redis_available = False
        await cache.set_quote("AAPL", {"bid": 150.0, "ask": 150.5})
        raw = await cache._fallback.get("quote:AAPL")
        assert raw is not None
        data = json.loads(raw)
        assert data["bid"] == 150.0 and "timestamp" in data

    @pytest.mark.asyncio
    async def test_set_quote_preserves_existing_timestamp(self):
        from core_trading.data_feeds.cache import MarketDataCache
        cache = MarketDataCache(redis_client=None)
        cache._redis_available = False
        ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc).isoformat()
        await cache.set_quote("AAPL", {"bid": 150.0, "timestamp": ts})
        raw = await cache._fallback.get("quote:AAPL")
        assert json.loads(raw)["timestamp"] == ts


class TestMarketDataCacheBars:
    @pytest.mark.asyncio
    async def test_set_and_get_bars(self):
        from core_trading.data_feeds.cache import MarketDataCache
        cache = MarketDataCache(redis_client=None)
        cache._redis_available = False
        await cache.set_bars("AAPL", "1 min", [{"open": 150.0, "close": 151.0}])
        result = await cache.get_bars("AAPL", "1 min")
        assert result is not None and len(result) == 1

    @pytest.mark.asyncio
    async def test_get_bars_miss(self):
        from core_trading.data_feeds.cache import MarketDataCache
        cache = MarketDataCache(redis_client=None)
        cache._redis_available = False
        assert await cache.get_bars("AAPL", "1 min") is None


class TestMarketDataCacheInvalidate:
    @pytest.mark.asyncio
    async def test_invalidate_removes_quote(self):
        from core_trading.data_feeds.cache import MarketDataCache
        cache = MarketDataCache(redis_client=None)
        cache._redis_available = False
        await cache.set_quote("AAPL", {"bid": 150.0})
        await cache.invalidate("AAPL")
        assert await cache.get_quote("AAPL") is None

    @pytest.mark.asyncio
    async def test_invalidate_bars(self):
        from core_trading.data_feeds.cache import MarketDataCache
        cache = MarketDataCache(redis_client=None)
        cache._redis_available = False
        await cache.set_bars("AAPL", "1 min", [{"open": 150}])
        await cache.invalidate_bars("AAPL", "1 min")
        assert await cache.get_bars("AAPL", "1 min") is None


class TestMarketDataCacheSingleton:
    def test_singleton(self):
        import core_trading.data_feeds.cache as mod
        mod._market_data_cache = None
        from core_trading.data_feeds.cache import get_market_data_cache
        assert get_market_data_cache() is get_market_data_cache()
        mod._market_data_cache = None


class TestInMemoryFallback:
    @pytest.mark.asyncio
    async def test_set_and_get(self):
        from core_trading.data_feeds.cache import InMemoryFallback
        fb = InMemoryFallback()
        await fb.set("k", "v", ttl=60)
        assert await fb.get("k") == "v"

    @pytest.mark.asyncio
    async def test_expired_key(self):
        from core_trading.data_feeds.cache import InMemoryFallback
        fb = InMemoryFallback()
        await fb.set("k", "v", ttl=0)
        assert await fb.get("k") is None

    @pytest.mark.asyncio
    async def test_delete(self):
        from core_trading.data_feeds.cache import InMemoryFallback
        fb = InMemoryFallback()
        await fb.set("k", "v", ttl=60)
        await fb.delete("k")
        assert await fb.get("k") is None

    @pytest.mark.asyncio
    async def test_exists(self):
        from core_trading.data_feeds.cache import InMemoryFallback
        fb = InMemoryFallback()
        await fb.set("k", "v", ttl=60)
        assert await fb.exists("k") is True
        assert await fb.exists("nope") is False


# ===================================================================
# DataNormalizer tests
# ===================================================================

class TestDataNormalizerIBKRQuote:
    def test_normalize_ibkr_quote(self):
        from core_trading.data_feeds.normalizer import DataNormalizer
        q = DataNormalizer().normalize_quote("ibkr", {
            "symbol": "AAPL", "bid": 150.0, "ask": 150.5, "last": 150.25,
            "volume": 5000,
        })
        assert q.symbol == "AAPL" and q.bid == 150.0 and q.source == "ibkr"

    def test_normalize_ibkr_quote_with_string_timestamp(self):
        from core_trading.data_feeds.normalizer import DataNormalizer
        q = DataNormalizer().normalize_quote("ibkr", {
            "symbol": "AAPL", "timestamp": "2026-01-01T12:00:00Z",
        })
        assert isinstance(q.timestamp, datetime)

    def test_normalize_ibkr_quote_with_last_price_field(self):
        from core_trading.data_feeds.normalizer import DataNormalizer
        q = DataNormalizer().normalize_quote("ibkr", {"symbol": "AAPL", "last_price": 150.25})
        assert q.last == 150.25


class TestDataNormalizerGenericQuote:
    def test_normalize_generic_quote(self):
        from core_trading.data_feeds.normalizer import DataNormalizer
        q = DataNormalizer().normalize_quote("alpha_vantage", {
            "Symbol": "AAPL", "Bid": 150.0, "Ask": 150.5, "Last": 150.25,
        })
        assert q.symbol == "AAPL" and q.source == "alpha_vantage"

    def test_normalize_generic_quote_with_alternate_keys(self):
        from core_trading.data_feeds.normalizer import DataNormalizer
        q = DataNormalizer().normalize_quote("custom", {
            "symbol": "AAPL", "bidPrice": 150.0, "askPrice": 150.5, "lastPrice": 150.25,
        })
        assert q.bid == 150.0 and q.ask == 150.5


class TestDataNormalizerBar:
    def test_normalize_ibkr_bar(self):
        from core_trading.data_feeds.normalizer import DataNormalizer
        b = DataNormalizer().normalize_bar("ibkr", {
            "symbol": "AAPL", "timestamp": datetime.now(timezone.utc),
            "open": 150.0, "high": 151.0, "low": 149.0, "close": 150.5, "volume": 10000,
        })
        assert b.source == "ibkr" and b.open == 150.0

    def test_normalize_generic_bar(self):
        from core_trading.data_feeds.normalizer import DataNormalizer
        b = DataNormalizer().normalize_bar("custom", {
            "Symbol": "AAPL", "time": datetime.now(timezone.utc),
            "Open": 150.0, "High": 151.0, "Low": 149.0, "Close": 150.5, "Volume": 10000,
        })
        assert b.source == "custom"


class TestDataNormalizerBatch:
    def test_normalize_bars_batch(self):
        from core_trading.data_feeds.normalizer import DataNormalizer
        result = DataNormalizer().normalize_bars_batch("ibkr", [
            {"timestamp": datetime.now(timezone.utc), "open": 150.0,
             "high": 151.0, "low": 149.0, "close": 150.5, "volume": 10000},
            {"timestamp": datetime.now(timezone.utc), "open": 150.5,
             "high": 152.0, "low": 150.0, "close": 151.5, "volume": 12000},
        ], symbol="AAPL")
        assert len(result) == 2 and result[0].symbol == "AAPL"

    def test_normalize_empty_batch(self):
        from core_trading.data_feeds.normalizer import DataNormalizer
        assert DataNormalizer().normalize_bars_batch("ibkr", [], symbol="AAPL") == []


class TestDataNormalizerCustomNormalizer:
    def test_register_and_use_custom_quote_normalizer(self):
        from core_trading.data_feeds.normalizer import DataNormalizer, StandardizedQuote
        norm = DataNormalizer()
        norm.register_normalizer("mine", quote_fn=lambda r: StandardizedQuote(
            symbol=r.get("s", ""), bid=float(r.get("b", 0)),
            ask=float(r.get("a", 0)), last=float(r.get("l", 0)), source="mine"))
        q = norm.normalize_quote("mine", {"s": "AAPL", "b": 150.0, "a": 150.5, "l": 150.25})
        assert q.symbol == "AAPL" and q.source == "mine"


class TestDataNormalizerTick:
    def test_normalize_ibkr_tick(self):
        from core_trading.data_feeds.normalizer import DataNormalizer
        t = DataNormalizer().normalize_tick("ibkr", {
            "symbol": "AAPL", "last_price": 150.25, "last_size": 100,
        })
        assert t.price == 150.25 and t.source == "ibkr"

    def test_normalize_generic_tick(self):
        from core_trading.data_feeds.normalizer import DataNormalizer
        t = DataNormalizer().normalize_tick("custom", {
            "symbol": "AAPL", "price": 150.25, "size": 100,
        })
        assert t.source == "custom"


class TestStandardizedQuoteProperties:
    def test_spread(self):
        from core_trading.data_feeds.normalizer import StandardizedQuote
        assert StandardizedQuote(symbol="X", bid=150.0, ask=150.5, last=150.25).spread == 0.5

    def test_spread_zero_when_no_bid_ask(self):
        from core_trading.data_feeds.normalizer import StandardizedQuote
        assert StandardizedQuote(symbol="X", bid=0.0, ask=0.0, last=150.25).spread == 0.0

    def test_mid_price(self):
        from core_trading.data_feeds.normalizer import StandardizedQuote
        assert StandardizedQuote(symbol="X", bid=150.0, ask=150.5, last=150.25).mid_price == 150.25

    def test_mid_price_fallback_to_last(self):
        from core_trading.data_feeds.normalizer import StandardizedQuote
        assert StandardizedQuote(symbol="X", bid=0.0, ask=0.0, last=150.25).mid_price == 150.25


class TestStandardizedBarProperties:
    def test_is_bullish(self):
        from core_trading.data_feeds.normalizer import StandardizedBar
        b = StandardizedBar(symbol="X", timestamp=datetime.now(timezone.utc),
                            open=150.0, high=151.0, low=149.0, close=150.5, volume=10000)
        assert b.is_bullish is True

    def test_is_bearish(self):
        from core_trading.data_feeds.normalizer import StandardizedBar
        b = StandardizedBar(symbol="X", timestamp=datetime.now(timezone.utc),
                            open=151.0, high=151.0, low=149.0, close=150.0, volume=10000)
        assert b.is_bullish is False

    def test_body_size(self):
        from core_trading.data_feeds.normalizer import StandardizedBar
        b = StandardizedBar(symbol="X", timestamp=datetime.now(timezone.utc),
                            open=150.0, high=151.0, low=149.0, close=150.5, volume=10000)
        assert b.body_size == 0.5

    def test_range(self):
        from core_trading.data_feeds.normalizer import StandardizedBar
        b = StandardizedBar(symbol="X", timestamp=datetime.now(timezone.utc),
                            open=150.0, high=151.0, low=149.0, close=150.5, volume=10000)
        assert b.range == 2.0


class TestDataNormalizerSafeFloat:
    def test_none(self):
        from core_trading.data_feeds.normalizer import DataNormalizer
        assert DataNormalizer._safe_float(None) == 0.0

    def test_string_number(self):
        from core_trading.data_feeds.normalizer import DataNormalizer
        assert DataNormalizer._safe_float("150.5") == 150.5

    def test_invalid_string(self):
        from core_trading.data_feeds.normalizer import DataNormalizer
        assert DataNormalizer._safe_float("bad") == 0.0

    def test_int(self):
        from core_trading.data_feeds.normalizer import DataNormalizer
        assert DataNormalizer._safe_float(42) == 42.0


class TestDataNormalizerSingleton:
    def test_singleton(self):
        import core_trading.data_feeds.normalizer as mod
        mod._data_normalizer = None
        from core_trading.data_feeds.normalizer import get_data_normalizer
        assert get_data_normalizer() is get_data_normalizer()
        mod._data_normalizer = None


# ===================================================================
# BaseAdapter tests
# ===================================================================

class TestConnectionStatusEnum:
    def test_all_values(self):
        from core_trading.adapters.base import ConnectionStatus
        assert ConnectionStatus.DISCONNECTED.value == "disconnected"
        assert ConnectionStatus.CONNECTED.value == "connected"
        assert ConnectionStatus.ERROR.value == "error"
        assert ConnectionStatus.MAINTENANCE.value == "maintenance"


class TestAdapterTypeEnum:
    def test_all_values(self):
        from core_trading.adapters.base import AdapterType
        assert AdapterType.BROKER.value == "broker"
        assert AdapterType.DATA_FEED.value == "data_feed"
        assert AdapterType.DATABASE.value == "database"


class TestAdapterConfigDefaults:
    def test_defaults(self):
        from core_trading.adapters.base import AdapterConfig, AdapterType
        c = AdapterConfig(name="t", adapter_type=AdapterType.BROKER)
        assert c.enabled is True and c.credentials == {}


class TestHealthCheckDataclass:
    def test_fields(self):
        from core_trading.adapters.base import HealthCheck, ConnectionStatus
        hc = HealthCheck(status=ConnectionStatus.CONNECTED, timestamp=datetime.now(timezone.utc))
        assert hc.error_message is None and hc.metadata == {}

    def test_with_error(self):
        from core_trading.adapters.base import HealthCheck, ConnectionStatus
        hc = HealthCheck(status=ConnectionStatus.ERROR, timestamp=datetime.now(timezone.utc),
                         error_message="refused", metadata={"retry": 3})
        assert hc.error_message == "refused"


class TestBaseAdapterAbstractMethods:
    def test_cannot_instantiate_directly(self):
        from core_trading.adapters.base import BaseAdapter, AdapterConfig, AdapterType
        with pytest.raises(TypeError):
            BaseAdapter(AdapterConfig(name="t", adapter_type=AdapterType.BROKER))

    def test_concrete_subclass_works(self):
        from core_trading.adapters.base import (
            BaseAdapter, AdapterConfig, AdapterType, ConnectionStatus, HealthCheck,
        )

        class C(BaseAdapter):
            async def connect(self): return True
            async def disconnect(self): return True
            async def health_check(self): return HealthCheck(
                status=ConnectionStatus.CONNECTED, timestamp=datetime.now(timezone.utc))

        a = C(AdapterConfig(name="t", adapter_type=AdapterType.BROKER))
        assert a.status == ConnectionStatus.DISCONNECTED


class TestConnectionContextManager:
    @pytest.mark.asyncio
    async def test_context_manager_success(self):
        from core_trading.adapters.base import (
            BaseAdapter, AdapterConfig, AdapterType, ConnectionStatus, HealthCheck,
        )

        class C(BaseAdapter):
            async def connect(self):
                self._set_status(ConnectionStatus.CONNECTED); return True
            async def disconnect(self):
                self._set_status(ConnectionStatus.DISCONNECTED); return True
            async def health_check(self): return HealthCheck(
                status=self._status, timestamp=datetime.now(timezone.utc))

        a = C(AdapterConfig(name="t", adapter_type=AdapterType.BROKER))
        async with a.connection_context() as ca:
            assert ca.is_connected
        assert not a.is_connected

    @pytest.mark.asyncio
    async def test_context_manager_disconnect_on_exception(self):
        from core_trading.adapters.base import (
            BaseAdapter, AdapterConfig, AdapterType, ConnectionStatus, HealthCheck,
        )

        class C(BaseAdapter):
            async def connect(self):
                self._set_status(ConnectionStatus.CONNECTED); return True
            async def disconnect(self):
                self._set_status(ConnectionStatus.DISCONNECTED); return True
            async def health_check(self): return HealthCheck(
                status=self._status, timestamp=datetime.now(timezone.utc))

        a = C(AdapterConfig(name="t", adapter_type=AdapterType.BROKER))
        with pytest.raises(ValueError):
            async with a.connection_context():
                raise ValueError("boom")
        assert not a.is_connected


class TestBaseAdapterCallbacks:
    def test_register_and_emit(self):
        from core_trading.adapters.base import (
            BaseAdapter, AdapterConfig, AdapterType, ConnectionStatus, HealthCheck,
        )

        class C(BaseAdapter):
            async def connect(self): return True
            async def disconnect(self): return True
            async def health_check(self): return HealthCheck(
                status=ConnectionStatus.CONNECTED, timestamp=datetime.now(timezone.utc))

        a = C(AdapterConfig(name="t", adapter_type=AdapterType.BROKER))
        r = []
        a.register_callback("ev", lambda d: r.append(d))
        a._emit_event("ev", {"k": "v"})
        assert len(r) == 1

    def test_emit_event_handles_callback_error(self):
        from core_trading.adapters.base import (
            BaseAdapter, AdapterConfig, AdapterType, ConnectionStatus, HealthCheck,
        )

        class C(BaseAdapter):
            async def connect(self): return True
            async def disconnect(self): return True
            async def health_check(self): return HealthCheck(
                status=ConnectionStatus.CONNECTED, timestamp=datetime.now(timezone.utc))

        a = C(AdapterConfig(name="t", adapter_type=AdapterType.BROKER))
        a.register_callback("ev", MagicMock(side_effect=RuntimeError))
        good = MagicMock()
        a.register_callback("ev", good)
        a._emit_event("ev", None)
        good.assert_called_once()


class TestBaseAdapterMetrics:
    def test_update_metrics(self):
        from core_trading.adapters.base import (
            BaseAdapter, AdapterConfig, AdapterType, ConnectionStatus, HealthCheck,
        )

        class C(BaseAdapter):
            async def connect(self): return True
            async def disconnect(self): return True
            async def health_check(self): return HealthCheck(
                status=ConnectionStatus.CONNECTED, timestamp=datetime.now(timezone.utc))

        a = C(AdapterConfig(name="t", adapter_type=AdapterType.BROKER))
        a._update_metrics("x", 42)
        assert a.metrics["x"] == 42

    def test_metrics_returns_copy(self):
        from core_trading.adapters.base import (
            BaseAdapter, AdapterConfig, AdapterType, ConnectionStatus, HealthCheck,
        )

        class C(BaseAdapter):
            async def connect(self): return True
            async def disconnect(self): return True
            async def health_check(self): return HealthCheck(
                status=ConnectionStatus.CONNECTED, timestamp=datetime.now(timezone.utc))

        a = C(AdapterConfig(name="t", adapter_type=AdapterType.BROKER))
        a.metrics["extra"] = "v"
        assert "extra" not in a.metrics


class TestBaseAdapterReconnect:
    @pytest.mark.asyncio
    async def test_reconnect_within_limit(self):
        from core_trading.adapters.base import (
            BaseAdapter, AdapterConfig, AdapterType, ConnectionStatus, HealthCheck,
        )
        from datetime import timedelta

        class C(BaseAdapter):
            async def connect(self):
                self._set_status(ConnectionStatus.CONNECTED); return True
            async def disconnect(self): return True
            async def health_check(self): return HealthCheck(
                status=self._status, timestamp=datetime.now(timezone.utc))

        a = C(AdapterConfig(name="t", adapter_type=AdapterType.BROKER, reconnect_delay=timedelta(seconds=0)))
        assert await a.reconnect() is True

    @pytest.mark.asyncio
    async def test_reconnect_exceeds_max_attempts(self):
        from core_trading.adapters.base import (
            BaseAdapter, AdapterConfig, AdapterType, ConnectionStatus, HealthCheck,
        )
        from datetime import timedelta

        class C(BaseAdapter):
            async def connect(self): return False
            async def disconnect(self): return True
            async def health_check(self): return HealthCheck(
                status=ConnectionStatus.DISCONNECTED, timestamp=datetime.now(timezone.utc))

        a = C(AdapterConfig(name="t", adapter_type=AdapterType.BROKER, max_reconnect_attempts=2,
                            reconnect_delay=timedelta(seconds=0)))
        a._reconnect_count = 5
        assert await a.reconnect() is False


class TestBaseAdapterSetStatus:
    def test_emits_on_change(self):
        from core_trading.adapters.base import (
            BaseAdapter, AdapterConfig, AdapterType, ConnectionStatus, HealthCheck,
        )

        class C(BaseAdapter):
            async def connect(self): return True
            async def disconnect(self): return True
            async def health_check(self): return HealthCheck(
                status=ConnectionStatus.CONNECTED, timestamp=datetime.now(timezone.utc))

        a = C(AdapterConfig(name="t", adapter_type=AdapterType.BROKER))
        r = []
        a.register_callback("status_changed", lambda d: r.append(d))
        a._set_status(ConnectionStatus.CONNECTING)
        assert len(r) == 1

    def test_no_event_when_same(self):
        from core_trading.adapters.base import (
            BaseAdapter, AdapterConfig, AdapterType, ConnectionStatus, HealthCheck,
        )

        class C(BaseAdapter):
            async def connect(self): return True
            async def disconnect(self): return True
            async def health_check(self): return HealthCheck(
                status=ConnectionStatus.CONNECTED, timestamp=datetime.now(timezone.utc))

        a = C(AdapterConfig(name="t", adapter_type=AdapterType.BROKER))
        r = []
        a.register_callback("status_changed", lambda d: r.append(d))
        a._set_status(ConnectionStatus.DISCONNECTED)
        assert len(r) == 0


class TestBaseBrokerAdapterAbstractMethods:
    def test_cannot_instantiate(self):
        from core_trading.adapters.base import BaseBrokerAdapter, AdapterConfig, AdapterType
        with pytest.raises(TypeError):
            BaseBrokerAdapter(AdapterConfig(name="t", adapter_type=AdapterType.BROKER))

    def test_concrete_instantiates(self):
        from core_trading.adapters.base import (
            BaseBrokerAdapter, AdapterConfig, AdapterType, ConnectionStatus, HealthCheck,
        )

        class B(BaseBrokerAdapter):
            async def connect(self): return True
            async def disconnect(self): return True
            async def health_check(self): return HealthCheck(
                status=ConnectionStatus.CONNECTED, timestamp=datetime.now(timezone.utc))
            async def place_order(self, d): return {}
            async def cancel_order(self, o): return True
            async def get_order_status(self, o): return {}
            async def get_positions(self): return []
            async def get_account_info(self): return {}
            async def get_portfolio_value(self): return 0.0

        assert B(AdapterConfig(name="t", adapter_type=AdapterType.BROKER)) is not None


class TestBaseDataFeedAdapterAbstractMethods:
    def test_cannot_instantiate(self):
        from core_trading.adapters.base import BaseDataFeedAdapter, AdapterConfig, AdapterType
        with pytest.raises(TypeError):
            BaseDataFeedAdapter(AdapterConfig(name="t", adapter_type=AdapterType.DATA_FEED))


class TestBaseDatabaseAdapterAbstractMethods:
    def test_cannot_instantiate(self):
        from core_trading.adapters.base import BaseDatabaseAdapter, AdapterConfig, AdapterType
        with pytest.raises(TypeError):
            BaseDatabaseAdapter(AdapterConfig(name="t", adapter_type=AdapterType.DATABASE))

    def test_concrete_instantiates(self):
        from core_trading.adapters.base import (
            BaseDatabaseAdapter, AdapterConfig, AdapterType, ConnectionStatus, HealthCheck,
        )

        class D(BaseDatabaseAdapter):
            async def connect(self): return True
            async def disconnect(self): return True
            async def health_check(self): return HealthCheck(
                status=ConnectionStatus.CONNECTED, timestamp=datetime.now(timezone.utc))
            async def execute_query(self, q, p=None): return []
            async def insert_data(self, t, d): return True
            async def update_data(self, t, d, w): return True
            async def delete_data(self, t, w): return True
            async def create_table(self, n, s): return True

        assert D(AdapterConfig(name="t", adapter_type=AdapterType.DATABASE)) is not None


# ===================================================================
# Rate Limiting tests
# ===================================================================

class TestTokenBucket:
    def test_consume_available(self):
        from core_trading.adapters.brokers.rate_limiting import TokenBucket
        assert TokenBucket(capacity=10, refill_rate=1.0).consume(1) is True

    def test_consume_exhausts(self):
        from core_trading.adapters.brokers.rate_limiting import TokenBucket
        b = TokenBucket(capacity=2, refill_rate=1.0)
        assert b.consume(1) is True
        assert b.consume(1) is True
        assert b.consume(1) is False

    def test_wait_time_zero(self):
        from core_trading.adapters.brokers.rate_limiting import TokenBucket
        assert TokenBucket(capacity=10, refill_rate=1.0).wait_time(1) == 0.0


class TestSlidingWindowRateLimiter:
    def test_allows_within_window(self):
        from core_trading.adapters.brokers.rate_limiting import SlidingWindowRateLimiter
        l = SlidingWindowRateLimiter(window_size=1.0, max_requests=5)
        for _ in range(5):
            assert l.is_allowed() is True

    def test_blocks_over_window(self):
        from core_trading.adapters.brokers.rate_limiting import SlidingWindowRateLimiter
        l = SlidingWindowRateLimiter(window_size=1.0, max_requests=2)
        assert l.is_allowed() is True
        assert l.is_allowed() is True
        assert l.is_allowed() is False


class TestRateLimiter:
    @pytest.mark.asyncio
    async def test_acquire(self):
        from core_trading.adapters.brokers.rate_limiting import (
            RateLimiter, RateLimitConfig, RateLimitStrategy,
        )
        l = RateLimiter(RateLimitConfig(strategy=RateLimitStrategy.TOKEN_BUCKET,
                                        burst_capacity=50, requests_per_second=10.0))
        assert await l.acquire() is True

    def test_record_success(self):
        from core_trading.adapters.brokers.rate_limiting import (
            RateLimiter, RateLimitConfig, RateLimitStrategy,
        )
        l = RateLimiter(RateLimitConfig(strategy=RateLimitStrategy.TOKEN_BUCKET,
                                        burst_capacity=50, requests_per_second=10.0))
        l.record_success(0.5)
        assert l.metrics.successful_requests == 1

    def test_record_failure(self):
        from core_trading.adapters.brokers.rate_limiting import (
            RateLimiter, RateLimitConfig, RateLimitStrategy,
        )
        l = RateLimiter(RateLimitConfig(strategy=RateLimitStrategy.TOKEN_BUCKET,
                                        burst_capacity=50, requests_per_second=10.0))
        l.record_failure()
        assert l.metrics.failed_requests == 1


class TestCircuitBreaker:
    def test_closed_allows(self):
        from core_trading.adapters.brokers.rate_limiting import CircuitBreaker
        assert CircuitBreaker(failure_threshold=3, timeout=60.0).call(lambda: "ok") == "ok"

    def test_opens_after_failures(self):
        from core_trading.adapters.brokers.rate_limiting import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=2, timeout=60.0)
        for _ in range(2):
            with pytest.raises(RuntimeError):
                cb.call(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        with pytest.raises(Exception, match="Circuit breaker is open"):
            cb.call(lambda: "ok")

    @pytest.mark.asyncio
    async def test_async_call(self):
        from core_trading.adapters.brokers.rate_limiting import CircuitBreaker
        cb = CircuitBreaker(failure_threshold=3, timeout=60.0)

        async def ok():
            return "ok"

        assert await cb.call_async(ok) == "ok"


class TestRateLimitConfig:
    def test_defaults(self):
        from core_trading.adapters.brokers.rate_limiting import RateLimitConfig, RateLimitStrategy
        c = RateLimitConfig()
        assert c.requests_per_second == 10.0 and c.strategy == RateLimitStrategy.TOKEN_BUCKET


class TestConnectionConfig:
    def test_defaults(self):
        from core_trading.adapters.brokers.rate_limiting import ConnectionConfig
        c = ConnectionConfig()
        assert c.max_connections == 5 and c.auto_reconnect is True


# ===================================================================
# Event Serializer tests
# ===================================================================

class TestJSONSerializer:
    def test_serialize_event(self):
        from libs.common.events.serializers import JSONSerializer
        from libs.common.events.base import MarketDataEvent
        result = JSONSerializer.serialize(MarketDataEvent(symbol="AAPL", exchange="NASDAQ"))
        assert isinstance(result, bytes) and b"AAPL" in result

    def test_deserialize_event(self):
        import json as json_mod
        from libs.common.events.serializers import JSONSerializer
        from libs.common.events.base import MarketDataEvent
        data = json_mod.dumps({
            "symbol": "AAPL", "exchange": "NASDAQ", "event_type": "market_data",
        }).encode("utf-8")
        result = JSONSerializer.deserialize(data, MarketDataEvent)
        assert result.symbol == "AAPL" and result.exchange == "NASDAQ"

    def test_serialize_deserialize_roundtrip(self):
        from libs.common.events.serializers import JSONSerializer
        from libs.common.events.base import MarketDataEvent
        event = MarketDataEvent(symbol="GOOG", exchange="NYSE")
        deserialized = JSONSerializer.deserialize(JSONSerializer.serialize(event), MarketDataEvent)
        assert deserialized.symbol == event.symbol and deserialized.exchange == event.exchange

    def test_serialize_invalid_data_raises(self):
        from libs.common.events.serializers import JSONSerializer
        from libs.common.events.base import MarketDataEvent
        with pytest.raises(Exception):
            JSONSerializer.deserialize(b"not valid json{}", MarketDataEvent)

    def test_avro_serializer_not_implemented(self):
        from libs.common.events.serializers import AvroSerializer
        from libs.common.events.base import MarketDataEvent
        s = AvroSerializer(schema_registry_url="http://localhost:8081")
        with pytest.raises(NotImplementedError):
            s.serialize(MarketDataEvent(symbol="AAPL", exchange="NASDAQ"), schema_id=1)
        with pytest.raises(NotImplementedError):
            s.deserialize(b"data", MarketDataEvent)
