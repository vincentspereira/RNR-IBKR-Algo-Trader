"""Data Normalization Layer.

Normalizes market data from different sources (IBKR, Alpha Vantage, etc.)
into a standard format so downstream consumers don't need to know the source.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class StandardizedQuote:
    """Normalized quote data from any source."""
    symbol: str
    bid: float
    ask: float
    last: float
    bid_size: float = 0.0
    ask_size: float = 0.0
    volume: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = ""

    @property
    def spread(self) -> float:
        """Calculate bid-ask spread."""
        return self.ask - self.bid if self.bid and self.ask else 0.0

    @property
    def mid_price(self) -> float:
        """Calculate mid-price."""
        return (self.bid + self.ask) / 2 if self.bid and self.ask else self.last


@dataclass
class StandardizedBar:
    """Normalized OHLCV bar from any source."""
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    timeframe: str = "1 min"
    source: str = ""
    bar_count: int = 0
    average: float = 0.0

    @property
    def is_bullish(self) -> bool:
        return self.close >= self.open

    @property
    def body_size(self) -> float:
        return abs(self.close - self.open)

    @property
    def range(self) -> float:
        return self.high - self.low


@dataclass
class StandardizedTick:
    """Normalized tick data from any source."""
    symbol: str
    timestamp: datetime
    price: float
    size: float
    side: str = ""  # "buy" or "sell" if available
    source: str = ""
    bid: float = 0.0
    ask: float = 0.0
    bid_size: float = 0.0
    ask_size: float = 0.0


class DataNormalizer:
    """Normalize data from different sources into standard format.

    Supports:
    - IBKR (via ib_insync ticker/bar objects and raw dicts)
    - Generic dict-based sources
    - Extensible via registration of custom normalizers
    """

    def __init__(self):
        self._custom_normalizers: Dict[str, Dict[str, Any]] = {}

    def register_normalizer(
        self,
        source: str,
        quote_fn=None,
        bar_fn=None,
        tick_fn=None,
    ):
        """Register custom normalization functions for a source.

        Args:
            source: Source identifier
            quote_fn: Function(raw_data) -> StandardizedQuote
            bar_fn: Function(raw_data) -> StandardizedBar
            tick_fn: Function(raw_data) -> StandardizedTick
        """
        self._custom_normalizers[source] = {
            "quote": quote_fn,
            "bar": bar_fn,
            "tick": tick_fn,
        }
        logger.info("normalizer_registered", source=source)

    def normalize_quote(self, source: str, raw_data: Dict[str, Any]) -> StandardizedQuote:
        """Normalize quote data from any source.

        Args:
            source: Data source identifier ('ibkr', 'alpha_vantage', etc.)
            raw_data: Raw quote data dict

        Returns:
            StandardizedQuote
        """
        if source in self._custom_normalizers and self._custom_normalizers[source].get("quote"):
            return self._custom_normalizers[source]["quote"](raw_data)

        if source == "ibkr":
            return self._normalize_ibkr_quote(raw_data)

        return self._normalize_generic_quote(source, raw_data)

    def normalize_bar(self, source: str, raw_data: Dict[str, Any]) -> StandardizedBar:
        """Normalize OHLCV bar from any source.

        Args:
            source: Data source identifier
            raw_data: Raw bar data dict

        Returns:
            StandardizedBar
        """
        if source in self._custom_normalizers and self._custom_normalizers[source].get("bar"):
            return self._custom_normalizers[source]["bar"](raw_data)

        if source == "ibkr":
            return self._normalize_ibkr_bar(raw_data)

        return self._normalize_generic_bar(source, raw_data)

    def normalize_tick(self, source: str, raw_data: Dict[str, Any]) -> StandardizedTick:
        """Normalize tick data from any source.

        Args:
            source: Data source identifier
            raw_data: Raw tick data dict

        Returns:
            StandardizedTick
        """
        if source in self._custom_normalizers and self._custom_normalizers[source].get("tick"):
            return self._custom_normalizers[source]["tick"](raw_data)

        if source == "ibkr":
            return self._normalize_ibkr_tick(raw_data)

        return self._normalize_generic_tick(source, raw_data)

    def normalize_bars_batch(
        self, source: str, raw_bars: List[Dict[str, Any]], symbol: str = ""
    ) -> List[StandardizedBar]:
        """Normalize a batch of bars.

        Args:
            source: Data source identifier
            raw_bars: List of raw bar dicts
            symbol: Symbol to use if not in raw data

        Returns:
            List of StandardizedBar
        """
        return [
            self.normalize_bar(source, {**bar, "symbol": bar.get("symbol", symbol)})
            for bar in raw_bars
        ]

    def _normalize_ibkr_quote(self, raw: Dict[str, Any]) -> StandardizedQuote:
        """Normalize IBKR quote data."""
        ts = raw.get("timestamp")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        elif ts is None:
            ts = datetime.now(timezone.utc)

        return StandardizedQuote(
            symbol=raw.get("symbol", ""),
            bid=self._safe_float(raw.get("bid", 0)),
            ask=self._safe_float(raw.get("ask", 0)),
            last=self._safe_float(raw.get("last", raw.get("last_price", 0))),
            bid_size=self._safe_float(raw.get("bid_size", 0)),
            ask_size=self._safe_float(raw.get("ask_size", 0)),
            volume=self._safe_float(raw.get("volume", 0)),
            high=self._safe_float(raw.get("high", 0)),
            low=self._safe_float(raw.get("low", 0)),
            close=self._safe_float(raw.get("close", 0)),
            timestamp=ts,
            source="ibkr",
        )

    def _normalize_ibkr_bar(self, raw: Dict[str, Any]) -> StandardizedBar:
        """Normalize IBKR bar data."""
        ts = raw.get("timestamp") or raw.get("date")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        elif ts is None:
            ts = datetime.now(timezone.utc)

        return StandardizedBar(
            symbol=raw.get("symbol", ""),
            timestamp=ts,
            open=self._safe_float(raw.get("open", 0)),
            high=self._safe_float(raw.get("high", 0)),
            low=self._safe_float(raw.get("low", 0)),
            close=self._safe_float(raw.get("close", 0)),
            volume=self._safe_float(raw.get("volume", 0)),
            timeframe=raw.get("timeframe", "1 min"),
            source="ibkr",
            bar_count=int(raw.get("bar_count", 0)),
            average=self._safe_float(raw.get("average", 0)),
        )

    def _normalize_ibkr_tick(self, raw: Dict[str, Any]) -> StandardizedTick:
        """Normalize IBKR tick data."""
        ts = raw.get("timestamp")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        elif ts is None:
            ts = datetime.now(timezone.utc)

        return StandardizedTick(
            symbol=raw.get("symbol", ""),
            timestamp=ts,
            price=self._safe_float(raw.get("last_price", raw.get("last", raw.get("price", 0)))),
            size=self._safe_float(raw.get("last_size", raw.get("size", 0))),
            source="ibkr",
            bid=self._safe_float(raw.get("bid", 0)),
            ask=self._safe_float(raw.get("ask", 0)),
            bid_size=self._safe_float(raw.get("bid_size", 0)),
            ask_size=self._safe_float(raw.get("ask_size", 0)),
        )

    def _normalize_generic_quote(self, source: str, raw: Dict[str, Any]) -> StandardizedQuote:
        """Generic quote normalization for unknown sources.

        Tries common field names and falls back to 0.
        """
        ts = raw.get("timestamp")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        elif ts is None:
            ts = datetime.now(timezone.utc)

        return StandardizedQuote(
            symbol=raw.get("symbol", raw.get("Symbol", "")),
            bid=self._safe_float(raw.get("bid", raw.get("Bid", raw.get("bidPrice", 0)))),
            ask=self._safe_float(raw.get("ask", raw.get("Ask", raw.get("askPrice", 0)))),
            last=self._safe_float(raw.get("last", raw.get("Last", raw.get("lastPrice", raw.get("close", 0))))),
            bid_size=self._safe_float(raw.get("bid_size", raw.get("BidSize", 0))),
            ask_size=self._safe_float(raw.get("ask_size", raw.get("AskSize", 0))),
            volume=self._safe_float(raw.get("volume", raw.get("Volume", 0))),
            high=self._safe_float(raw.get("high", raw.get("High", 0))),
            low=self._safe_float(raw.get("low", raw.get("Low", 0))),
            close=self._safe_float(raw.get("close", raw.get("Close", 0))),
            timestamp=ts,
            source=source,
        )

    def _normalize_generic_bar(self, source: str, raw: Dict[str, Any]) -> StandardizedBar:
        """Generic bar normalization for unknown sources."""
        ts = raw.get("timestamp") or raw.get("date") or raw.get("time")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        elif ts is None:
            ts = datetime.now(timezone.utc)

        return StandardizedBar(
            symbol=raw.get("symbol", raw.get("Symbol", "")),
            timestamp=ts,
            open=self._safe_float(raw.get("open", raw.get("Open", 0))),
            high=self._safe_float(raw.get("high", raw.get("High", 0))),
            low=self._safe_float(raw.get("low", raw.get("Low", 0))),
            close=self._safe_float(raw.get("close", raw.get("Close", 0))),
            volume=self._safe_float(raw.get("volume", raw.get("Volume", 0))),
            timeframe=raw.get("timeframe", raw.get("interval", "1 min")),
            source=source,
        )

    def _normalize_generic_tick(self, source: str, raw: Dict[str, Any]) -> StandardizedTick:
        """Generic tick normalization for unknown sources."""
        ts = raw.get("timestamp") or raw.get("time")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        elif ts is None:
            ts = datetime.now(timezone.utc)

        return StandardizedTick(
            symbol=raw.get("symbol", raw.get("Symbol", "")),
            timestamp=ts,
            price=self._safe_float(raw.get("price", raw.get("last", raw.get("Price", 0)))),
            size=self._safe_float(raw.get("size", raw.get("Size", raw.get("quantity", 0)))),
            source=source,
        )

    @staticmethod
    def _safe_float(value) -> float:
        """Safely convert value to float, returning 0.0 for None/invalid."""
        if value is None:
            return 0.0
        try:
            return float(value)
        except (ValueError, TypeError):
            return 0.0


# Singleton
_data_normalizer: Optional[DataNormalizer] = None


def get_data_normalizer() -> DataNormalizer:
    """Get the global DataNormalizer instance."""
    global _data_normalizer
    if _data_normalizer is None:
        _data_normalizer = DataNormalizer()
    return _data_normalizer
