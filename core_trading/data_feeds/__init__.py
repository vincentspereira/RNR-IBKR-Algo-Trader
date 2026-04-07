"""Data feeds package for the IBKR Algo Trader.

Provides real-time and historical market data via IBKR,
time-series storage via ClickHouse, Redis caching, and data normalization.
"""

from .ibkr_data_feed import IBKRDataFeed, get_ibkr_data_feed
from .timeseries_store import TimeSeriesStore, get_timeseries_store
from .cache import MarketDataCache, get_market_data_cache
from .normalizer import (
    DataNormalizer,
    StandardizedQuote,
    StandardizedBar,
    StandardizedTick,
    get_data_normalizer,
)

__all__ = [
    "IBKRDataFeed",
    "get_ibkr_data_feed",
    "TimeSeriesStore",
    "get_timeseries_store",
    "MarketDataCache",
    "get_market_data_cache",
    "DataNormalizer",
    "StandardizedQuote",
    "StandardizedBar",
    "StandardizedTick",
    "get_data_normalizer",
]
