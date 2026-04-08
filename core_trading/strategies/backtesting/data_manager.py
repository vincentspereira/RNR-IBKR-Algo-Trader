"""Backtesting data manager for loading and managing historical market data."""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class DataSource(Enum):
    YAHOO_FINANCE = "yahoo_finance"
    IBKR = "ibkr"
    CSV = "csv"
    MOCK = "mock"
    DATABASE = "database"


class DataResolution(Enum):
    TICK = "tick"
    SECOND = "second"
    MINUTE = "minute"
    HOUR = "hour"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


@dataclass
class DataConfig:
    """Configuration for data sources."""
    source: DataSource = DataSource.MOCK
    resolution: DataResolution = DataResolution.DAILY
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    symbols: List[str] = field(default_factory=list)
    cache_enabled: bool = True
    cache_ttl_seconds: int = 3600
    rate_limit_per_minute: int = 60
    retry_count: int = 3


@dataclass
class MarketData:
    """Container for market data."""
    symbol: str
    timestamp: str
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0
    resolution: DataResolution = DataResolution.DAILY

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }


class YahooFinanceSource:
    """Data source for Yahoo Finance."""

    def __init__(self, config: Optional[DataConfig] = None):
        self.config = config or DataConfig(source=DataSource.YAHOO_FINANCE)

    def fetch(self, symbol: str, start_date: str, end_date: str, resolution: DataResolution = DataResolution.DAILY) -> pd.DataFrame:
        """Fetch data from Yahoo Finance."""
        logger.info(f"Fetching {symbol} data from {start_date} to {end_date}")
        try:
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            return ticker.history(start=start_date, end=end_date)
        except ImportError:
            logger.warning("yfinance not installed, returning empty DataFrame")
            return pd.DataFrame()


class MockDataSource:
    """Mock data source for testing."""

    def __init__(self, config: Optional[DataConfig] = None):
        self.config = config or DataConfig(source=DataSource.MOCK)
        self._data: Dict[str, List[MarketData]] = {}

    def fetch(self, symbol: str, start_date: str, end_date: str, resolution: DataResolution = DataResolution.DAILY) -> pd.DataFrame:
        """Generate mock data."""
        n = 252
        rng = np.random.default_rng(42)
        dates = pd.date_range(start=start_date or "2024-01-01", periods=n, freq="B")
        base = 100.0
        returns = rng.normal(0.0005, 0.02, n)
        close = base * np.cumprod(1 + returns)

        spread = close * 0.005
        high = close + rng.uniform(0, 1, n) * spread
        low = close - rng.uniform(0, 1, n) * spread
        open_ = low + rng.uniform(0, 1, n) * (high - low)
        volume = rng.integers(500_000, 5_000_000, n).astype(float)

        return pd.DataFrame({
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }, index=dates)

    def add_data(self, symbol: str, data: List[MarketData]) -> None:
        """Pre-load mock data."""
        self._data[symbol] = data


class DataManager:
    """Manager for loading and caching market data."""

    def __init__(self, config: Optional[DataConfig] = None):
        self.config = config or DataConfig()
        self._cache: Dict[str, pd.DataFrame] = {}
        self._sources: Dict[DataSource, Any] = {
            DataSource.MOCK: MockDataSource(self.config),
            DataSource.YAHOO_FINANCE: YahooFinanceSource(self.config),
        }
        logger.info("DataManager initialized")

    def get_data(
        self,
        symbol: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        resolution: Optional[DataResolution] = None,
    ) -> pd.DataFrame:
        """Fetch market data for a symbol."""
        cache_key = f"{symbol}_{start_date}_{end_date}"
        if self.config.cache_enabled and cache_key in self._cache:
            return self._cache[cache_key]

        source = self._sources.get(self.config.source)
        if source is None:
            logger.error(f"No data source configured: {self.config.source}")
            return pd.DataFrame()

        start = start_date or self.config.start_date or "2024-01-01"
        end = end_date or self.config.end_date or datetime.now().strftime("%Y-%m-%d")
        res = resolution or self.config.resolution

        data = source.fetch(symbol, start, end, res)

        if self.config.cache_enabled and not data.empty:
            self._cache[cache_key] = data

        return data

    def get_multiple(self, symbols: List[str], **kwargs) -> Dict[str, pd.DataFrame]:
        """Fetch data for multiple symbols."""
        return {sym: self.get_data(sym, **kwargs) for sym in symbols}

    def clear_cache(self) -> None:
        """Clear the data cache."""
        self._cache.clear()

    def register_source(self, source_type: DataSource, source: Any) -> None:
        """Register a custom data source."""
        self._sources[source_type] = source

    def get_status(self) -> Dict[str, Any]:
        """Get data manager status."""
        return {
            "source": self.config.source.value,
            "cache_size": len(self._cache),
            "registered_sources": [s.value for s in self._sources.keys()],
        }
