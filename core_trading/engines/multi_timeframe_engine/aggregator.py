import asyncio
import json
import logging
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union
import numpy as np
import pandas as pd
from database.data_access_layer import DataAccessLayer
from nautilus_trader.model.data.bar import Bar
from nautilus_trader.model.enums import BarType
from nautilus_trader.model.identifiers import InstrumentId
from scipy import stats
from sklearn.cluster import DBSCAN
from sklearn.preprocessing import StandardScaler
from infrastructure.config.master_config import get_config
from shared.utils.utils.logging_utils import get_logger
"Enhanced Multi-Timeframe Data Aggregator for NautilusTrader"
# "
# Advanced multi-timeframe aggregation with institutional-grade features:
# - Efficient aggregation across multiple timeframes
# - Smart money flow integration and tracking
# - Volume-weighted indicators and analysis
# - Cross-timeframe validation and alignment
# - Institutional flow analysis and detection
# - Memory management and performance optimization
# - Real-time monitoring and metrics
# - Free data source integration (Yahoo Finance, Alpha Vantage)
# - Advanced aggregation methods (VWAP, TWAP, Volume Profile)
# - Timeframe alignment validation
# - Error handling and recovery"




# NautilusTrader imports

# Project imports

# Configure logging
logger = get_logger(__name__)


class TimeFrame(str, Enum):""
# "Supported timeframes for multi-timeframe analysis
# "
#     SECOND_1 = "1s"
#     SECOND_5 = "5s"
#     SECOND_10 = "10s"
#     SECOND_15 = "15s"
#     SECOND_30 = "30s"
#     MINUTE_1 = "1m"
#     MINUTE_2 = "2m"
#     MINUTE_3 = "3m"
#     MINUTE_5 = "5m"
#     MINUTE_10 = "10m"
#     MINUTE_15 = "15m"
#     MINUTE_30 = "30m"
#     HOUR_1 = "1h"
#     HOUR_2 = "2h"
#     HOUR_4 = "4h"
#     HOUR_6 = "6h"
#     HOUR_8 = "8h"
#     HOUR_12 = "12h"
#     DAY_1 = "1d"
#     WEEK_1 = "1w"
#     MONTH_1 = "1M"


# "

class SmartMoneySignal(str, Enum):""
# "Smart money flow signals
# "
#     ACCUMULATION = "accumulation"
#     DISTRIBUTION = "distribution"
#     ROTATION = "rotation"
#     BREAKOUT = "breakout"
#     REVERSAL = "reversal"
#     CONTINUATION = "continuation"
#     NEUTRAL = "neutral"


# "

# @dataclass
class SmartMoneyMetrics:""
#     "Smart money flow metrics for institutional analysis"

#     institutional_flow_ratio: float = 0.0  # -1.0 to 1.0
#     large_order_imbalance: float = 0.0
#     volume_weighted_pressure: float = 0.0
#     dark_pool_activity_score: float = 0.0
#     retail_vs_institutional_ratio: float = 0.0
#     order_flow_toxicity: float = 0.0
#     liquidity_provision_score: float = 0.0
#     market_impact_coefficient: float = 0.0
#     timestamp: datetime = field(default_factory=datetime.now)


# @dataclass
class MultiTimeframeBar:""
#     "Enhanced bar with multi-timeframe and smart money data"

    # Basic OHLCV data
#     symbol: str
#     timestamp: datetime
#     timeframe: TimeFrame
#     open: float
#     high: float
#     low: float
#     close: float
#     volume: int

    # Smart money metrics
#     smart_money_metrics: SmartMoneyMetrics = field(default_factory=SmartMoneyMetrics)
#     smart_money_signal: SmartMoneySignal = SmartMoneySignal.NEUTRAL

    # Technical indicators (volume-weighted)
#     vwap: float = 0.0
#     vw_sma_20: float = 0.0
#     vw_ema_20: float = 0.0
#     vw_rsi_14: float = 50.0
#     vw_macd_signal: float = 0.0
#     vw_mfi_14: float = 50.0

    # Multi-timeframe alignment"
#     higher_tf_trend: str = "neutral"  # bullish, bearish, neutral""
#     lower_tf_momentum: str = "neutral"
#     cross_tf_confirmation: bool = False

    # Volume profile data
#     poc_price: float = 0.0  # Point of Control
#     value_area_high: float = 0.0
#     value_area_low: float = 0.0

    # Order flow data
#     buy_volume: int = 0
#     sell_volume: int = 0
#     neutral_volume: int = 0
#     large_trade_count: int = 0

    # Metadata
#     data_quality_score: float = 1.0
#     latency_ms: float = 0.0


# @dataclass
class AggregationMetrics:""
#     "Performance metrics for aggregation operations"

#     total_bars_processed: int = 0
#     aggregation_latency_ms: float = 0.0
#     memory_usage_mb: float = 0.0
#     error_count: int = 0
#     last_update_time: Optional[datetime] = None
#     smart_money_signals_generated: int = 0
#     cross_timeframe_confirmations: int = 0
#     institutional_flow_detections: int = 0


class DataProvider(ABC):""
#     "Abstract base class for data providers"

#     @abstractmethod
#     def fetch_historical_data(
# self, symbol: str, timeframe: str, start_date: datetime, end_date: datetime
# ) -> pd.DataFrame:"
# "Fetch historical data for a symbol and timeframe
# raise NotImplementedError("
#             "Subclasses must implement fetch_historical_data method"
# )

# "

#     @abstractmethod
#     def fetch_real_time_data(self, symbol: str):
# "Fetch real-time data for a symbol
# raise NotImplementedError("
#             "Subclasses must implement fetch_real_time_data method"
# )


# "

class YahooFinanceProvider(DataProvider):""
#     "Data provider for Yahoo Finance (free tier)"

#     def fetch_historical_data(
# self, symbol: str, timeframe: str, start_date: datetime, end_date: datetime
# ) -> pd.DataFrame:"
#         "Fetch historical data from Yahoo Finance"
#         try:
#             import yfinance as yf

#             ticker = yf.Ticker(symbol)
#             data = ticker.history(start=start_date, end=end_date, interval=timeframe)

            # Convert to our format
# df = pd.DataFrame(
# {"
# "open": data["Open"],"
# "high": data["High"],"
# "low": data["Low"],"
# "close": data["Close"],"
# "volume": data["Volume"],
# }
# )

#             return df.dropna()

#         except Exception as e:""
#             logging.error(f"Error fetching Yahoo Finance data for {symbol}: {e}")
#             return pd.DataFrame()

#     def fetch_real_time_data(self, symbol: str):
#         "Fetch real-time data from Yahoo Finance"
        # Implementation would use yfinance for real-time data
        # For now, return None as Yahoo Finance has limitations for real-time
#         return None


class AlphaVantageProvider(DataProvider):""
#     "Data provider for Alpha Vantage (free tier)"

#     def __init__(self, api_key: str):
#         self.api_key = api_key

#     def fetch_historical_data(
# self, symbol: str, timeframe: str, start_date: datetime, end_date: datetime
# ) -> pd.DataFrame:"
#         "Fetch historical data from Alpha Vantage"
#         try:
#             from alpha_vantage.timeseries import TimeSeries
# "
#             ts = TimeSeries(key=self.api_key, output_format="pandas")
# "
#             if timeframe == "1D":""
# data, _ = ts.get_daily(symbol=symbol, outputsize="full")"
#             elif timeframe == "1H":
# data, _ = ts.get_intraday("
# symbol=symbol, interval="60min", outputsize="full"
# )
#             else:
                # For other timeframes, we'll need to resample"
# data, _ = ts.get_intraday("
# symbol=symbol, interval="1min", outputsize="full"
# )

            # Convert to our format
# df = pd.DataFrame(
# {
# "open": data["1. open"],"
# "high": data["2. high"],"
# "low": data["3. low"],"
# "close": data["4. close"],"
# "volume": data["5. volume"],
# }
# )

            # Filter by date range
#             df.index = pd.to_datetime(df.index)
#             df = df[(df.index >= start_date) & (df.index <= end_date)]

#             return df.dropna()

#         except Exception as e:""
#             logging.error(f"Error fetching Alpha Vantage data for {symbol}: {e}")
#             return pd.DataFrame()

#     def fetch_real_time_data(self, symbol: str):
#         "Fetch real-time data from Alpha Vantage"
        # Implementation would use Alpha Vantage real-time API
#         return None


class BinanceProvider(DataProvider):""
#     "Data provider for Binance (crypto data)"

#     def fetch_historical_data(
# self, symbol: str, timeframe: str, start_date: datetime, end_date: datetime
# ) -> pd.DataFrame:"
#         "Fetch historical data from Binance"
#         try:
#             from binance.client import Client

            # Note: Requires Binance API keys"
#             client = Client(api_key=", api_secret=")  # Would need actual keys

            # Convert timeframe to Binance format
#             binance_interval = self._convert_timeframe(timeframe)

# klines = client.get_historical_klines(
#                 symbol,
# binance_interval,"
# start_date.strftime("%d %b, %Y"),"
#                 end_date.strftime("%d %b, %Y"),
# )

            # Convert to DataFrame
# df = pd.DataFrame(
#                 klines,
# columns=["
# "timestamp","
# "open","
# "high","
# "low","
# "close","
# "volume","
# "close_time","
# "quote_asset_volume","
# "number_of_trades","
# "taker_buy_base_asset_volume","
# "taker_buy_quote_asset_volume","
#                     "ignore",
# ],
# )
# "
# df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")"
#             df.set_index("timestamp", inplace=True)

            # Convert string columns to numeric"
#             for col in ["open", "high", "low", "close", "volume"]:""
#                 df[col] = pd.to_numeric(df[col], errors="coerce")
# "
#             return df[["open", "high", "low", "close", "volume"]].dropna()

#         except Exception as e:""
#             logging.error(f"Error fetching Binance data for {symbol}: {e}")
#             return pd.DataFrame()

#     def fetch_real_time_data(self, symbol: str):
#         "Fetch real-time data from Binance WebSocket"
        # Implementation would use Binance WebSocket streams
#         return None

#     def _convert_timeframe(self, timeframe: str):
# "Convert standard timeframe to Binance interval
# mapping = {"
# "1m": "1m","
# "5m": "5m","
# "15m": "15m","
# "30m": "30m","
# "1h": "1h","
# "4h": "4h","
# "1d": "1d","
# "1w": "1w","
# "1M": "1M",
# }
#         return mapping.get(timeframe, "1h")


class TimeframeAlignment:""
#     "Validates and manages timeframe alignment for institutional-grade analysis"

# VALID_TIMEFRAMES = {"
# "1s": 1,"
# "5s": 5,"
# "10s": 10,"
# "15s": 15,"
# "30s": 30,"
# "1m": 60,"
# "2m": 120,"
# "3m": 180,"
# "5m": 300,"
# "10m": 600,"
# "15m": 900,"
# "30m": 1800,"
# "1h": 3600,"
# "2h": 7200,"
# "4h": 14400,"
# "6h": 21600,"
# "8h": 28800,"
# "12h": 43200,"
# "1d": 86400,"
# "1w": 604800,"
# "1M": 2592000,
# }

#     @classmethod
#     def validate_alignment(cls, base_tf: str, higher_tfs: List[str]):
#         "Validate that higher timeframes are proper multiples of base timeframe"
#         if base_tf not in cls.VALID_TIMEFRAMES:
#             return False

#         base_seconds = cls.VALID_TIMEFRAMES[base_tf]

#         for tf in higher_tfs:
#             if tf not in cls.VALID_TIMEFRAMES:
#                 return False
#             tf_seconds = cls.VALID_TIMEFRAMES[tf]
#             if tf_seconds <= base_seconds or tf_seconds % base_seconds != 0:
#                 return False

#         return True

#     @classmethod
#     def get_alignment_ratio(cls, base_tf: str, target_tf: str):
#         "Get the ratio between timeframes for proper aggregation"
#         return cls.VALID_TIMEFRAMES[target_tf] // cls.VALID_TIMEFRAMES[base_tf]


class AdvancedAggregationMethods:""
#     "Advanced aggregation methods for institutional-grade analysis"

#     @staticmethod
#     def volume_weighted_price(df: pd.DataFrame):
#         "Calculate volume-weighted average price"
#         if df.empty or df["volume"].sum() == 0:""
#             return df["close"].iloc[-1] if not df.empty else 0.0""
#         return (df["close"] * df["volume"]).sum() / df["volume"].sum()

#     @staticmethod
#     def time_weighted_price(df: pd.DataFrame):
#         "Calculate time-weighted average price"
#         if df.empty:
#             return 0.0""
#         return df["close"].mean()

#     @staticmethod
#     def institutional_bar_metrics(df: pd.DataFrame):
#         "Calculate institutional-grade bar metrics"
#         if df.empty:
#             return {}

#         return {
# "vwap": AdvancedAggregationMethods.volume_weighted_price(df),"
# "twap": AdvancedAggregationMethods.time_weighted_price(df),"
# "volume_profile_poc": df.loc[df["volume"].idxmax(), "close"]
#             if not df.empty
# else 0.0,"
# "price_range": df["high"].max() - df["low"].min(),"
# "volume_imbalance": (df["volume"] * (df["close"] - df["open"])).sum(),"
# "tick_count": len(df),"
# "uptick_ratio": len(df[df["close"] > df["open"]]) / len(df)
#             if len(df) > 0
# else 0.0,
# }


class MultiTimeframeAggregator:""

# Enhanced multi-timeframe aggregator with institutional-grade features

# Supports:
# - Multiple data providers (Yahoo Finance, Alpha Vantage, Binance)
# - Timeframe alignment validation
# - Advanced aggregation methods (VWAP, TWAP, Volume Profile)
# - Efficient memory management
# - Performance monitoring
# - Error handling and recovery
# - Real-time data integration
# - Institutional-grade bar metrics"


#     def __init__(
#         self,
# base_timeframe: str,
# higher_timeframes: List[str],
#         max_buffer_size: int = 10000,
#         data_provider: Optional[DataProvider] = None,
#         enable_advanced_metrics: bool = True,
#         validate_alignment: bool = True,
# ):"

# Initialize the multi-timeframe aggregator
# '
# Args:'
# base_timeframe: Base timeframe (e.g., '1m', '5m')
# higher_timeframes: List of higher timeframes to aggregate to
# max_buffer_size: Maximum number of bars to keep in memory
# data_provider: Data provider for fetching historical data
# enable_advanced_metrics: Enable institutional-grade metrics calculation
# validate_alignment: Validate timeframe alignment on initialization"

        # Validate timeframe alignment if requested
#         if validate_alignment and not TimeframeAlignment.validate_alignment(
#             base_timeframe, higher_timeframes
# ):
# raise ValueError("
#                 f"Invalid timeframe alignment: {base_timeframe} -> {higher_timeframes}"
# )

#         self.base_timeframe = base_timeframe
#         self.higher_timeframes = higher_timeframes
#         self.max_buffer_size = max_buffer_size
#         self.data_provider = data_provider
#         self.enable_advanced_metrics = enable_advanced_metrics

        # Initialize data storage
#         self._data = {}
#         self._advanced_metrics = {}
#         self._initialize_data_stores()

        # Performance monitoring
#         self.metrics = AggregationMetrics()
#         self.logger = logging.getLogger(self.__class__.__name__)

        # Error recovery
#         self.last_error_time = None
#         self.error_backoff_seconds = 60

        # Aggregation methods
#         self.aggregation_methods = AdvancedAggregationMethods()

#         self.logger.info(""
#             f"Initialized MultiTimeframeAggregator: {base_timeframe} -> {higher_timeframes}"
# )

#     def _initialize_data_stores(self):
#         "Initialize data storage for all timeframes"
#         columns = ["open", "high", "low", "close", "volume", "timestamp"]
#         for tf in [self.base_timeframe] + self.higher_timeframes:
#             self._data[tf] = pd.DataFrame(columns=columns)""
#             self._data[tf] = self._data[tf].set_index("timestamp")

#     def update(self, bar: Bar):

# Update with new bar data

# Args:
# bar: New bar data

# Returns:
# True if update successful, False otherwise"

#         start_time = time.time()

#         try:
            # Update base timeframe data"
#             timestamp = pd.to_datetime(bar.ts_event, unit="ns")

# new_row = pd.DataFrame(
# [
# {
# "open": bar.open,"
# "high": bar.high,"
# "low": bar.low,"
# "close": bar.close,"
# "volume": bar.volume,
# }
# ],
#                 index=[timestamp],
# )

#             self._data[self.base_timeframe] = pd.concat(
# [self._data[self.base_timeframe], new_row]
# )

            # Maintain buffer size
#             if len(self._data[self.base_timeframe]) > self.max_buffer_size:
#                 self._data[self.base_timeframe] = self._data[self.base_timeframe].iloc[
# -self.max_buffer_size :
# ]

            # Resample to higher timeframes
#             self._resample_higher_timeframes()

            # Update metrics
#             self.metrics.total_bars_processed += 1
#             self.metrics.aggregation_latency_ms = (time.time() - start_time) * 1000
#             self.metrics.last_update_time = datetime.now()

#             return True

#         except Exception as e:""
#             self.logger.error(f"Error updating aggregator: {e}")
#             self.metrics.error_count += 1
#             self.last_error_time = datetime.now()
#             return False

#     def _resample_higher_timeframes(self):
#         "Resample base timeframe data to higher timeframes with advanced metrics"
#         base_data = self._data[self.base_timeframe]

#         if len(base_data) == 0:
#             return

#         for tf in self.higher_timeframes:
#             try:
                # Get alignment ratio for proper aggregation
# alignment_ratio = TimeframeAlignment.get_alignment_ratio(
#                     self.base_timeframe, tf
# )

                # Resample with proper OHLC aggregation
# resampled = (
#                     base_data.resample(tf)
# .agg(
# {
# "open": "first","
# "high": "max","
# "low": "min","
# "close": "last","
# "volume": "sum",
# }
# )
# .dropna()
# )

                # Calculate advanced metrics if enabled
#                 if self.enable_advanced_metrics and not resampled.empty:
                    # Group base data by resampled periods for advanced calculations
#                     grouped_base = base_data.groupby(pd.Grouper(freq=tf))

#                     advanced_metrics = []
#                     for period, group_data in grouped_base:
#                         if not group_data.empty:
# metrics = (
#                                 self.aggregation_methods.institutional_bar_metrics(
#                                     group_data
# )
# )"
#                             metrics["timestamp"] = period
#                             advanced_metrics.append(metrics)

#                     if advanced_metrics:
# metrics_df = pd.DataFrame(advanced_metrics)"
#                         metrics_df.set_index("timestamp", inplace=True)
#                         self._advanced_metrics[tf] = pd.concat(
# [self._advanced_metrics.get(tf, pd.DataFrame()), metrics_df]
# )
                        # Remove duplicates"
#                         self._advanced_metrics[tf] = self._advanced_metrics[tf][""
#                             ~self._advanced_metrics[tf].index.duplicated(keep="last")
# ]

                # Update higher timeframe data
#                 self._data[tf] = pd.concat([self._data[tf], resampled])
#                 self._data[tf] = self._data[tf][""
#                     ~self._data[tf].index.duplicated(keep="last")
# ]

                # Maintain buffer size
#                 buffer_size = max(self.max_buffer_size // (alignment_ratio * 2), 100)
#                 if len(self._data[tf]) > buffer_size:
#                     self._data[tf] = self._data[tf].iloc[-buffer_size:]

                # Maintain advanced metrics buffer
#                 if self.enable_advanced_metrics and tf in self._advanced_metrics:
#                     if len(self._advanced_metrics[tf]) > buffer_size:
#                         self._advanced_metrics[tf] = self._advanced_metrics[tf].iloc[
# -buffer_size:
# ]

#             except Exception as e:""
#                 self.logger.error(f"Error resampling to {tf}: {e}")

#     def get_data(self, timeframe: str):
#         "Get data for specified timeframe"
#         return self._data.get(timeframe, pd.DataFrame())

#     def get_latest_bar(
# self, timeframe: str, include_advanced_metrics: bool = False
# ) -> Optional[Dict[str, Any]]:"
#         "Get latest bar for specified timeframe with optional advanced metrics"
#         data = self.get_data(timeframe)
#         if len(data) == 0:
#             return None

#         latest = data.iloc[-1]
# result = {"
# "timestamp": latest.name,"
# "open": latest["open"],"
# "high": latest["high"],"
# "low": latest["low"],"
# "close": latest["close"],"
# "volume": latest["volume"],
# }

        # Add advanced metrics if requested and available
#         if (
#             include_advanced_metrics
# and self.enable_advanced_metrics
# and timeframe in self._advanced_metrics
# ):
#             metrics_data = self._advanced_metrics[timeframe]
#             if not metrics_data.empty:
#                 latest_metrics = metrics_data.iloc[-1]
# result.update(
# {
# "vwap": latest_metrics.get("vwap", 0.0),"
# "twap": latest_metrics.get("twap", 0.0),"
# "volume_profile_poc": latest_metrics.get("
#                             "volume_profile_poc", 0.0
# ),"
# "price_range": latest_metrics.get("price_range", 0.0),"
# "volume_imbalance": latest_metrics.get("volume_imbalance", 0.0),"
# "tick_count": latest_metrics.get("tick_count", 0),"
# "uptick_ratio": latest_metrics.get("uptick_ratio", 0.0),
# }
# )

#         return result

#     def load_historical_data(
# self, symbol: str, start_date: datetime, end_date: datetime
# ) -> bool:"
#         "Load historical data using configured data provider"
#         if not self.data_provider:
#             self.logger.warning(""
#                 "No data provider configured for historical data loading"
# )
#             return False

#         try:
            # Load base timeframe data
# base_data = self.data_provider.fetch_historical_data(
#                 symbol, self.base_timeframe, start_date, end_date
# )

#             if len(base_data) > 0:
                # Convert index to timestamp if needed
#                 if not isinstance(base_data.index, pd.DatetimeIndex):
#                     base_data.index = pd.to_datetime(base_data.index)

                # Add timestamp column"
#                 base_data["timestamp"] = base_data.index

#                 self._data[self.base_timeframe] = pd.concat(
# [self._data[self.base_timeframe], base_data]
# ).drop_duplicates()

                # Resample higher timeframes
#                 self._resample_higher_timeframes()

#                 self.logger.info(""
#                     f"Loaded {len(base_data)} historical bars for {symbol}"
# )
#                 return True

#         except Exception as e:""
#             self.logger.error(f"Error loading historical data for {symbol}: {e}")

#         return False

#     def get_metrics(self):
#         "Get current performance metrics"
        # Update memory usage
#         total_memory = 0
#         for df in self._data.values():
#             total_memory += df.memory_usage(deep=True).sum()
#         self.metrics.memory_usage_mb = total_memory / (1024 * 1024)

#         return self.metrics

#     def get_advanced_metrics(self, timeframe: str):
#         "Get advanced metrics for specified timeframe"
#         return self._advanced_metrics.get(timeframe, pd.DataFrame())

#     def get_timeframe_analysis(self, symbol: str = None):
# "Get comprehensive timeframe analysis
# analysis = {"
# "base_timeframe": self.base_timeframe,"
# "higher_timeframes": self.higher_timeframes,"
# "alignment_valid": TimeframeAlignment.validate_alignment(
#                 self.base_timeframe, self.higher_timeframes
# ),"
# "data_availability": {},"
# "latest_bars": {},"
# "advanced_metrics_enabled": self.enable_advanced_metrics,
# }

        # Check data availability for each timeframe
#         for tf in [self.base_timeframe] + self.higher_timeframes:
# data = self.get_data(tf)"
# analysis["data_availability"][tf] = {
# "bars_count": len(data),"
# "has_data": not data.empty,"
# "latest_timestamp": data.index[-1] if not data.empty else None,"
# "earliest_timestamp": data.index[0] if not data.empty else None,
# }

            # Get latest bar with advanced metrics"
# latest_bar = self.get_latest_bar(tf, include_advanced_metrics=True)"
#             analysis["latest_bars"][tf] = latest_bar

#         return analysis

#     def get_cross_timeframe_signals(self):
# "Generate cross-timeframe trading signals
# signals = {"
# "timestamp": datetime.now(),"
# "base_timeframe": self.base_timeframe,"
# "signals": {},"
# "consensus": None,
# }
# "
#         trend_votes = []
# "
#         for tf in [self.base_timeframe] + self.higher_timeframes:
#             data = self.get_data(tf)
#             if len(data) < 2:
#                 continue
# "
            # Simple trend analysis"
# latest_close = data["close"].iloc[-1]"
# prev_close = data["close"].iloc[-2]"
#             trend = "bullish" if latest_close > prev_close else "bearish"
# "
            # Volume confirmation"
#             latest_volume = data["volume"].iloc[-1]
# avg_volume = ("
#                 data["volume"].tail(10).mean() if len(data) >= 10 else latest_volume
# )
#             volume_confirmation = latest_volume > avg_volume
# "
# signal = {"
# "trend": trend,"
# "volume_confirmation": volume_confirmation,"
# "strength": abs(latest_close - prev_close) / prev_close
#                 if prev_close != 0
# else 0,
# }

            # Add advanced metrics if available
#             if self.enable_advanced_metrics and tf in self._advanced_metrics:
#                 metrics_data = self._advanced_metrics[tf]
#                 if not metrics_data.empty:
#                     latest_metrics = metrics_data.iloc[-1]
# signal.update(
# {
# "vwap_position": "above"
#                             if latest_close > latest_metrics.get("vwap", latest_close)""
# else "below","
# "volume_imbalance": latest_metrics.get("
#                                 "volume_imbalance", 0
# ),"
# "uptick_ratio": latest_metrics.get("uptick_ratio", 0.5),
# }
# )
# "
# signals["signals"][tf] = signal"
#             trend_votes.append(1 if trend == "bullish" else -1)

        # Calculate consensus
#         if trend_votes:
#             consensus_score = sum(trend_votes) / len(trend_votes)
#             if consensus_score > 0.5:""
# signals["consensus"] = "bullish
#             elif consensus_score < -0.5:""
# signals["consensus"] = "bearish
#             else:""
#                 signals["consensus"] = "neutral"

#         return signals

#     def reset(self):
#         "Reset the aggregator to initial state"
#         self._initialize_data_stores()
#         self._advanced_metrics = {}
#         self.metrics = AggregationMetrics()""
#         self.logger.info("Aggregator reset to initial state")
# "'"'