import asyncio
import hashlib
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import aiohttp
import numpy as np
import pandas as pd
import redis
import requests
import yaml
import yfinance as yf
from ib_insync import IB, Forex, Future, Option, Stock
from kafka import KafkaConsumer, KafkaProducer
from prometheus_client import Counter, Gauge, Histogram, start_http_server
#!/usr/bin/env python3

# Multi-Source Data Feed Manager with Complete Fallback Mechanism
# ""Institutional-Grade Data Feed Management for Algorithmic Trading System"

# This service implements a comprehensive data feed management system with:
# - Multi-source data feeds with automatic fallback
# - Asset-class specific fallback chains
# - Real-time monitoring and health checks
# - Data quality validation and anomaly detection
# - Kafka integration for event streaming
# - Compliance and audit logging"




# Configure logging"
# logging.basicConfig("
#     level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
# )
logger = logging.getLogger(__name__)


class DataSourceStatus(Enum):""
# "Data source status enumeration
# "
#     HEALTHY = "healthy"
#     DEGRADED = "degraded"
#     FAILED = "failed"
#     RECOVERING = "recovering"


# "

class AssetClass(Enum):""
# "Asset class enumeration
# "
#     STOCKS_ETFS = "stocks_etfs"
#     STOCK_FUTURES = "stock_futures"
#     STOCK_OPTIONS = "stock_options"
#     FOREX = "forex"
#     COMMODITIES = "commodities"
#     CRYPTOCURRENCY = "cryptocurrency"


# "

# @dataclass
class DataPoint:""
#     "Data point structure"

#     symbol: str
#     timestamp: datetime
#     price: float
#     volume: Optional[float] = None
#     bid: Optional[float] = None
#     ask: Optional[float] = None
#     source: Optional[str] = None
#     asset_class: Optional[str] = None
#     quality_score: float = 1.0
#     metadata: Optional[Dict] = None


# @dataclass
class DataSourceHealth:""
#     "Data source health metrics"

#     source_name: str
#     status: DataSourceStatus
#     latency_ms: float
#     error_rate: float
#     last_successful_request: datetime
#     consecutive_failures: int = 0
#     quality_score: float = 1.0


class CircuitBreaker:""
#     "Circuit breaker for data sources"

#     def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 300):
#         self.failure_threshold = failure_threshold
#         self.recovery_timeout = recovery_timeout
#         self.failure_count = 0
#         self.last_failure_time = None""
#         self.state = "closed"  # closed, open, half-open

#     def call(self, func, *args, **kwargs):
#         "Execute function with circuit breaker protection"
#         if self.state == "open":
#             if time.time() - self.last_failure_time > self.recovery_timeout:""
#                 self.state = "half-open"
#             else:""
#                 raise Exception("Circuit breaker is open")

#         try:
# result = func(*args, **kwargs)"
#             if self.state == "half-open":""
#                 self.state = "closed"
#                 self.failure_count = 0
#             return result
#         except Exception as e:
#             self.failure_count += 1
#             self.last_failure_time = time.time()

#             if self.failure_count >= self.failure_threshold:""
#                 self.state = "open"

#             raise e


class DataQualityValidator:""
#     "Data quality validation and anomaly detection"

#     def __init__(self, config: Dict):
#         self.config = config
#         self.price_history = {}
#         self.volume_history = {}

#     def validate_data_point(
# self, data_point: DataPoint
# ) -> Tuple[bool, float, List[str]]:"
#         "Validate data point and return quality score"
#         issues = []
#         quality_score = 1.0

        # Price range validation"
#         if data_point.price <= 0:""
#             issues.append("Invalid price: must be positive")
#             quality_score -= 0.3

        # Timestamp validation
#         now = datetime.now()
#         if data_point.timestamp > now + timedelta(minutes=5):""
#             issues.append("Future timestamp detected")
#             quality_score -= 0.2

        # Price spike detection
#         if data_point.symbol in self.price_history:
#             recent_prices = self.price_history[data_point.symbol][-10:]
#             if recent_prices:
#                 avg_price = np.mean(recent_prices)
#                 price_change = abs(data_point.price - avg_price) / avg_price
# "
#                 if price_change > self.config.get("price_spike_threshold", 0.1):""
#                     issues.append(f"Price spike detected: {price_change:.2%}")
#                     quality_score -= 0.1

        # Volume spike detection
#         if data_point.volume and data_point.symbol in self.volume_history:
#             recent_volumes = self.volume_history[data_point.symbol][-10:]
#             if recent_volumes:
#                 avg_volume = np.mean(recent_volumes)
#                 if avg_volume > 0:
#                     volume_ratio = data_point.volume / avg_volume
# "
#                     if volume_ratio > self.config.get("volume_spike_threshold", 5.0):""
#                         issues.append(f"Volume spike detected: {volume_ratio:.1f}x")
#                         quality_score -= 0.1

        # Update history
#         if data_point.symbol not in self.price_history:
#             self.price_history[data_point.symbol] = []
#         self.price_history[data_point.symbol].append(data_point.price)

#         if data_point.volume:
#             if data_point.symbol not in self.volume_history:
#                 self.volume_history[data_point.symbol] = []
#             self.volume_history[data_point.symbol].append(data_point.volume)

        # Keep only recent history
#         for symbol in self.price_history:
#             self.price_history[symbol] = self.price_history[symbol][-100:]
#         for symbol in self.volume_history:
#             self.volume_history[symbol] = self.volume_history[symbol][-100:]
# "
#         is_valid = quality_score >= self.config.get("quality_threshold", 0.95)
#         return is_valid, max(0.0, quality_score), issues


class DataSourceAdapter:""
#     "Base class for data source adapters"

#     def __init__(self, name: str, config: Dict):
#         self.name = name
#         self.config = config
#         self.circuit_breaker = CircuitBreaker(""
# failure_threshold=config.get("failure_threshold", 5),"
#             recovery_timeout=config.get("recovery_timeout", 300),
# )
#         self.session = None

#     async def initialize(self):
# "Initialize the data source adapter
#         self.session = aiohttp.ClientSession(""
#             timeout=aiohttp.ClientTimeout(total=self.config.get("timeout_seconds", 30))
# )

# "

#     async def cleanup(self):
#         "Cleanup resources"
#         if self.session:
#             await self.session.close()

#     async def get_data(
# self, symbol: str, asset_class: AssetClass
# ) -> Optional[DataPoint]:"
#         "Get data for a symbol - to be implemented by subclasses"
#         raise NotImplementedError

#     async def health_check(self):
#         "Perform health check - to be implemented by subclasses"
#         raise NotImplementedError


class YahooFinanceAdapter(DataSourceAdapter):""
#     "Yahoo Finance data source adapter"

#     async def get_data(
# self, symbol: str, asset_class: AssetClass
# ) -> Optional[DataPoint]:"
#         "Get data from Yahoo Finance"
#         try:
#             start_time = time.time()

            # Use yfinance library
#             ticker = yf.Ticker(symbol)
# info = ticker.info"
#             hist = ticker.history(period="1d", interval="1m")

#             if hist.empty:
#                 return None

#             latest = hist.iloc[-1]

# data_point = DataPoint(
#                 symbol=symbol,
# timestamp=datetime.now(),"
# price=float(latest["Close"]),"
#                 volume=float(latest["Volume"]) if "Volume" in latest else None,
#                 source=self.name,
#                 asset_class=asset_class.value,
# metadata={
# "open": float(latest["Open"]),"
# "high": float(latest["High"]),"
# "low": float(latest["Low"]),"
# "latency_ms": (time.time() - start_time) * 1000,
# },
# )

#             return data_point

#         except Exception as e:""
#             logger.error(f"Yahoo Finance error for {symbol}: {e}")
#             return None

#     async def health_check(self):
#         "Perform health check"
#         try:
#             start_time = time.time()

            # Test with a common symbol"
#             ticker = yf.Ticker("AAPL")
#             info = ticker.info

#             latency_ms = (time.time() - start_time) * 1000

#             return DataSourceHealth(
#                 source_name=self.name,
#                 status=DataSourceStatus.HEALTHY,
#                 latency_ms=latency_ms,
#                 error_rate=0.0,
#                 last_successful_request=datetime.now(),
# )

#         except Exception as e:""
#             logger.error(f"Yahoo Finance health check failed: {e}")
#             return DataSourceHealth(
#                 source_name=self.name,
# status=DataSourceStatus.FAILED,"
#                 latency_ms=float("inf"),
#                 error_rate=1.0,
#                 last_successful_request=datetime.now(),
# )


class InteractiveBrokersAdapter(DataSourceAdapter):""
#     "Interactive Brokers data source adapter"

#     def __init__(self, name: str, config: Dict):
#         "super().__init__(name, config)"
#         self.ib = IB()
#         self.connected = False

#     async def initialize(self):
#         "Initialize IB connection"
#         await super().initialize()
#         try:""
#             self.ib.connect("127.0.0.1", 7497, clientId=1)  # Paper trading port
#             self.connected = True""
#             logger.info("Connected to Interactive Brokers")
#         except Exception as e:""
#             logger.error(f"Failed to connect to Interactive Brokers: {e}")
#             self.connected = False

#     async def get_data(
# self, symbol: str, asset_class: AssetClass
# ) -> Optional[DataPoint]:"
#         "Get data from Interactive Brokers"
#         if not self.connected:
#             return None

#         try:
#             start_time = time.time()

            # Create contract based on asset class"
#             if asset_class == AssetClass.STOCKS_ETFS:""
#                 contract = Stock(symbol, "SMART", "USD")
#             elif asset_class == AssetClass.FOREX:
                # Assume symbol format like 'EURUSD'
#                 base, quote = symbol[:3], symbol[3:]
#                 contract = Forex(base + quote)
#             else:
                # Default to stock"
#                 contract = Stock(symbol, "SMART", "USD")

            # Get market data
#             self.ib.qualifyContracts(contract)
#             ticker = self.ib.reqMktData(contract)

            # Wait for data
#             await asyncio.sleep(1)

#             if ticker.last and ticker.last > 0:
# data_point = DataPoint(
#                     symbol=symbol,
#                     timestamp=datetime.now(),
#                     price=float(ticker.last),
#                     volume=float(ticker.volume) if ticker.volume else None,
#                     bid=float(ticker.bid) if ticker.bid else None,
#                     ask=float(ticker.ask) if ticker.ask else None,
#                     source=self.name,
# asset_class=asset_class.value,"
#                     metadata={"latency_ms": (time.time() - start_time) * 1000},
# )

#                 return data_point

#             return None

#         except Exception as e:""
#             logger.error(f"Interactive Brokers error for {symbol}: {e}")
#             return None

#     async def health_check(self):
#         "Perform health check"
#         try:
#             if not self.connected:
#                 return DataSourceHealth(
#                     source_name=self.name,
# status=DataSourceStatus.FAILED,"
#                     latency_ms=float("inf"),
#                     error_rate=1.0,
#                     last_successful_request=datetime.now(),
# )

#             start_time = time.time()

            # Test connection
#             accounts = self.ib.managedAccounts()

#             latency_ms = (time.time() - start_time) * 1000

#             return DataSourceHealth(
#                 source_name=self.name,
#                 status=DataSourceStatus.HEALTHY,
#                 latency_ms=latency_ms,
#                 error_rate=0.0,
#                 last_successful_request=datetime.now(),
# )

#         except Exception as e:""
#             logger.error(f"Interactive Brokers health check failed: {e}")
#             return DataSourceHealth(
#                 source_name=self.name,
# status=DataSourceStatus.FAILED,"
#                 latency_ms=float("inf"),
#                 error_rate=1.0,
#                 last_successful_request=datetime.now(),
# )


class DataFeedManager:""
#     "Main data feed manager with fallback mechanism"

#     def __init__(self, config_path: str):
#         self.config = self._load_config(config_path)
#         self.adapters = {}
#         self.health_status = {}
#         self.quality_validator = DataQualityValidator(""
#             self.config.get("data_quality", {})
# )

        # Kafka integration
#         self.kafka_producer = None
#         self.redis_client = None

        # Metrics"
#         self.request_counter = Counter(""
# "data_feed_requests_total","
# "Total data feed requests","
#             ["source", "asset_class"],
# )
#         self.latency_histogram = Histogram(""
#             "data_feed_latency_seconds", "Data feed latency", ["source"]
# )
#         self.error_counter = Counter(""
#             "data_feed_errors_total", "Total data feed errors", ["source", "error_type"]
# )
#         self.quality_gauge = Gauge(""
#             "data_feed_quality_score", "Data quality score", ["source"]
# )

        # Initialize adapters
#         self._initialize_adapters()

#     def _load_config(self, config_path: str):
#         "Load configuration from YAML file"
#         with open(config_path, "r") as f:
#             return yaml.safe_load(f)

#     def _initialize_adapters(self):
# "Initialize data source adapters
        # Yahoo Finance"
#         if "yahoo_finance" in self.config["data_sources"]:""
#             self.adapters["yahoo_finance"] = YahooFinanceAdapter(""
#                 "yahoo_finance", self.config["data_sources"]["yahoo_finance"]
# )
# "
        # Interactive Brokers"
#         if "interactive_brokers" in self.config["data_sources"]:""
#             self.adapters["interactive_brokers"] = InteractiveBrokersAdapter(""
# "interactive_brokers","
#                 self.config["data_sources"]["interactive_brokers"],
# )

        # Add more adapters as needed"
#         logger.info(f"Initialized {len(self.adapters)} data source adapters")

# "

#     async def initialize(self):
#         "Initialize the data feed manager"
        # Initialize adapters
#         for adapter in self.adapters.values():
#             await adapter.initialize()

        # Initialize Kafka producer"
#         if self.config.get("kafka_integration"):""
#             kafka_config = self.config["kafka_integration"]
#             self.kafka_producer = KafkaProducer(""
# bootstrap_servers=kafka_config["bootstrap_servers"],"
# value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),"
# **kafka_config.get("producer_config", {}),
# )

        # Initialize Redis"
#         if (""
#             self.config.get("performance", {})""
# .get("caching_strategy", {})"
# .get("redis_enabled")
# ):"
#             self.redis_client = redis.Redis(host="localhost", port=6379, db=0)

        # Start metrics server
#         start_http_server(8000)
# "
#         logger.info("Data feed manager initialized")

#     async def get_data(
# self, symbol: str, asset_class: AssetClass
# ) -> Optional[DataPoint]:"
# "Get data with fallback mechanism
        # Get fallback chain for asset class"
#         asset_config = self.config["asset_classes"].get(asset_class.value)
#         if not asset_config:""
#             logger.error(f"No configuration found for asset class: {asset_class.value}")
#             return None
# "
# fallback_chain = [asset_config["primary_source"]] + asset_config["
#             "fallback_chain"
# ]

        # Try each source in the fallback chain
#         for source_name in fallback_chain:
#             if source_name not in self.adapters:
#                 continue

#             adapter = self.adapters[source_name]

            # Check if source is healthy
#             health = self.health_status.get(source_name)
#             if health and health.status == DataSourceStatus.FAILED:
#                 continue

#             try:
                # Record request
#                 self.request_counter.labels(
#                     source=source_name, asset_class=asset_class.value
# ).inc()

#                 start_time = time.time()
#                 data_point = await adapter.get_data(symbol, asset_class)
#                 latency = time.time() - start_time

                # Record latency
#                 self.latency_histogram.labels(source=source_name).observe(latency)

#                 if data_point:
                    # Validate data quality
# (
#                         is_valid,
#                         quality_score,
#                         issues,
# ) = self.quality_validator.validate_data_point(data_point)
#                     data_point.quality_score = quality_score

                    # Record quality
#                     self.quality_gauge.labels(source=source_name).set(quality_score)

#                     if is_valid:
                        # Publish to Kafka
#                         await self._publish_data(data_point)

                        # Cache data
#                         await self._cache_data(data_point)

# logger.debug("
#                             f"Successfully retrieved data for {symbol} from {source_name}"
# )
#                         return data_point
#                     else:
# logger.warning("
#                             f"Data quality issues for {symbol} from {source_name}: {issues}"
# )

#             except Exception as e:
                # Record error
#                 self.error_counter.labels(
#                     source=source_name, error_type=type(e).__name__
# ).inc()"
#                 logger.error(f"Error getting data for {symbol} from {source_name}: {e}")
#                 continue
# "
#         logger.error(f"Failed to get data for {symbol} from all sources")
#         return None

#     async def _publish_data(self, data_point: DataPoint):
#         "Publish data to Kafka"
#         if self.kafka_producer:
#             try:""
#                 topic = self.config["kafka_integration"]["topics"]["processed_data"]
#                 message = asdict(data_point)
#                 self.kafka_producer.send(topic, message)
#             except Exception as e:""
#                 logger.error(f"Failed to publish data to Kafka: {e}")

#     async def _cache_data(self, data_point: DataPoint):
#         "Cache data in Redis"
#         if self.redis_client:
#             try:""
#                 key = f"data:{data_point.symbol}:{data_point.asset_class}"
#                 value = json.dumps(asdict(data_point), default=str)
# ttl = ("
#                     self.config.get("performance", {})""
# .get("caching_strategy", {})"
# .get("cache_ttl", 60)
# )
#                 self.redis_client.setex(key, ttl, value)
#             except Exception as e:""
#                 logger.error(f"Failed to cache data: {e}")

#     async def health_check_all_sources(self):
#         "Perform health check on all data sources"
#         tasks = []
#         for name, adapter in self.adapters.items():
#             tasks.append(adapter.health_check())

#         results = await asyncio.gather(*tasks, return_exceptions=True)

#         for i, result in enumerate(results):
#             adapter_name = list(self.adapters.keys())[i]
#             if isinstance(result, Exception):""
#                 logger.error(f"Health check failed for {adapter_name}: {result}")
#                 self.health_status[adapter_name] = DataSourceHealth(
#                     source_name=adapter_name,
# status=DataSourceStatus.FAILED,"
#                     latency_ms=float("inf"),
#                     error_rate=1.0,
#                     last_successful_request=datetime.now(),
# )
#             else:
#                 self.health_status[adapter_name] = result
# "
#         logger.info(f"Health check completed for {len(self.adapters)} sources")

#     async def start_monitoring(self):
#         "Start continuous monitoring"
#         while True:
#             try:
#                 await self.health_check_all_sources()
# await asyncio.sleep("
#                     self.config.get("global_settings", {}).get(""
#                         "health_check_interval", 30
# )
# )
#             except Exception as e:""
#                 logger.error(f"Monitoring error: {e}")
#                 await asyncio.sleep(60)

#     async def cleanup(self):
#         "Cleanup resources"
#         for adapter in self.adapters.values():
#             await adapter.cleanup()

#         if self.kafka_producer:
#             self.kafka_producer.close()

#         if self.redis_client:
#             self.redis_client.close()
# "
#         logger.info("Data feed manager cleaned up")


# async def main():
#     "Main function for testing"
#     config_path = "data_feeds_config.yaml"

    # Initialize data feed manager
#     manager = DataFeedManager(config_path)
#     await manager.initialize()

#     try:
        # Start monitoring in background
#         monitoring_task = asyncio.create_task(manager.start_monitoring())

        # Test data retrieval"
#         symbols = ["AAPL", "GOOGL", "MSFT", "TSLA"]

#         while True:
#             for symbol in symbols:
#                 data_point = await manager.get_data(symbol, AssetClass.STOCKS_ETFS)
#                 if data_point:
# logger.info("
#                         f"Retrieved data for {symbol}: ${data_point.price:.2f} from {data_point.source}"
# )
#                 else:""
#                     logger.warning(f"Failed to retrieve data for {symbol}")

#             await asyncio.sleep(10)

#     except KeyboardInterrupt:""
#         logger.info("Shutting down...")
#     finally:
#         monitoring_task.cancel()
#         await manager.cleanup()

# "
# if __name__ == "__main__":
#     asyncio.run(main())
# "'"'