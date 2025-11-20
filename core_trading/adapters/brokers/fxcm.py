import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urljoin
import aiohttp
# from ..base import ()
"FXCM Broker Adapter"
# "
# This module provides a comprehensive adapter for FXCM forex broker integration,
# supporting forex, CFD, and commodity trading. The adapter implements the BaseBrokerAdapter
# interface and provides functionality for order management, position tracking,
# and account monitoring.
# "
# Features:
# - Forex, CFD, and commodity trading support
# - Real-time order execution and status updates
# - Position and portfolio management
# - Market data integration
# - Risk management and compliance checks
# - Major and minor currency pairs support
# - Order types (market, entry, stop, limit)
# - Event-driven architecture with Kafka integration"




#     AdapterConfig,
#     AdapterType,
#     BaseBrokerAdapter,
#     ConnectionStatus,
#     HealthCheck,
# )

# FXCM REST API imports (would be installed via pip install fxcmpy)
# try:
#     import fxcmpy

#     FXCM_AVAILABLE = True
# except ImportError:
# FXCM_AVAILABLE = False"
# ""logging.warning("FXCM API not available. Install with: pip install fxcmpy")""


class FXCMOrderType(Enum):""
# "FXCM order types
# "
#     MARKET = "AtMarket"
#     ENTRY = "Entry"
#     STOP = "Stop"
#     LIMIT = "Limit"


# "

class FXCMOrderSide(Enum):""
# "FXCM order sides
# "
#     BUY = "B"
#     SELL = "S"


# "

class FXCMTimeInForce(Enum):""
# "FXCM time in force options
# "
#     GTC = "GTC"  # Good Till Cancelled""
#     IOC = "IOC"  # Immediate or Cancel""
#     FOK = "FOK"  # Fill or Kill""
#     DAY = "DAY"  # Day order


# "

# @dataclass
class FXCMConfig(AdapterConfig):""
# "FXCM-specific configuration
# "
# access_token: str = "
#     server: str = "demo"  # "demo" or "real"
# log_level: str = "error
# log_file: Optional[str] = None"
#     base_url: str = "https://api-fxpractice.oanda.com"  # Demo URL""
#     live_base_url: str = "https://api-fxtrade.oanda.com"  # Live URL
# max_orders_per_minute: int = 100"
#     default_currency: str = "USD"

# "

#     def __post_init__(self):
# super().__post_init__()"
#         if self.server == "real":
#             self.base_url = self.live_base_url


class FXCMAdapter(BaseBrokerAdapter):""
#     "FXCM broker adapter implementation"

#     def __init__(self, config: FXCMConfig):
#         super().__init__(config)
#         self.config: FXCMConfig = config
#         self._session: Optional[aiohttp.ClientSession] = None
#         self._fxcm_connection = None
#         self._headers = {""
# "Authorization": f"Bearer {config.access_token}","
# "Content-Type": "application/json",
# }
#         self._account_info: Dict[str, Any] = {}
#         self._positions: List[Dict[str, Any]] = []
#         self._orders: Dict[str, Dict[str, Any]] = {}
#         self._instruments: Dict[str, Dict[str, Any]] = {}

#     async def connect(self):
# "Establish connection to FXCM API""
#         try:
#             self._set_status(ConnectionStatus.CONNECTING)

#             if not FXCM_AVAILABLE:""
#                 self.logger.error("FXCM API library not available")
#                 self._set_status(ConnectionStatus.ERROR)
#                 return False

            # Create FXCM connection
#             self._fxcm_connection = fxcmpy.fxcmpy(
#                 access_token=self.config.access_token,
#                 log_level=self.config.log_level,
#                 server=self.config.server,
#                 log_file=self.config.log_file,
# )

            # Create HTTP session for additional API calls
#             self._session = aiohttp.ClientSession(
#                 headers=self._headers,
# timeout=aiohttp.ClientTimeout(
#                     total=self.config.timeout.total_seconds()
# ),
# )

            # Test connection by getting account info
#             if self._fxcm_connection.is_connected():
#                 account_info = await self._get_account_info_sync()
#                 if account_info:
#                     self._account_info = account_info

                    # Load available instruments
#                     await self._load_instruments()

#                     self._set_status(ConnectionStatus.CONNECTED)""
#                     self.logger.info(f"Connected to FXCM {self.config.server} server")
#                     return True

#             self._set_status(ConnectionStatus.ERROR)
#             return False

#         except Exception as e:""
#             self.logger.error(f"Failed to connect to FXCM: {e}")
#             self._set_status(ConnectionStatus.ERROR)
#             return False

#     async def disconnect(self):
# "Disconnect from FXCM API""
#         try:
#             if self._fxcm_connection:
#                 self._fxcm_connection.close()
#                 self._fxcm_connection = None

#             if self._session:
#                 await self._session.close()
#                 self._session = None

#             self._set_status(ConnectionStatus.DISCONNECTED)""
#             self.logger.info("Disconnected from FXCM")
#             return True

#         except Exception as e:""
#             self.logger.error(f"Error during disconnect: {e}")
#             return False

#     async def health_check(self):
#         "Perform health check"
#         start_time = datetime.now()

#         try:
#             if self._fxcm_connection and self._fxcm_connection.is_connected():
                # Simple check by getting server time or account info
#                 account_info = await self._get_account_info_sync()

#                 if account_info:
#                     latency = (datetime.now() - start_time).total_seconds() * 1000
#                     return HealthCheck(
#                         status=ConnectionStatus.CONNECTED,
#                         timestamp=datetime.now(),
# latency_ms=latency,"
#                         metadata={"server": self.config.server},
# )

#             return HealthCheck(
#                 status=ConnectionStatus.ERROR,
# timestamp=datetime.now(),"
#                 error_message="Connection not available",
# )

#         except Exception as e:
#             return HealthCheck(
#                 status=ConnectionStatus.ERROR,
#                 timestamp=datetime.now(),
#                 error_message=str(e),
# )

#     async def place_order(self, order_data: Dict[str, Any]):
#         "Place a trading order"
#         try:
            # Validate required fields"
#             required_fields = ["symbol", "quantity", "order_type", "side"]
#             for field in required_fields:
#                 if field not in order_data:""
#                     raise ValueError(f"Missing required field: {field}")

#             if not self._fxcm_connection or not self._fxcm_connection.is_connected():""
#                 raise Exception("Not connected to FXCM")

            # Prepare order parameters"
# symbol = order_data["symbol"]"
#             amount = int(order_data["quantity"])  # FXCM uses lot sizes""
#             is_buy = order_data["side"].upper() == "BUY"
#             order_type = order_data["order_type"].upper()
# "
            # Place order based on type"
#             if order_type == "MARKET":
                # Market order
# result = await self._execute_sync(
#                     self._fxcm_connection.create_market_buy_order
#                     if is_buy
# else self._fxcm_connection.create_market_sell_order,
#                     symbol,
#                     amount,
# )"
#             elif order_type in ["ENTRY", "LIMIT"]:
                # Entry/Limit order"
#                 if "price" not in order_data:""
#                     raise ValueError("Price required for entry/limit orders")
# "
#                 rate = float(order_data["price"])
# result = await self._execute_sync(
#                     self._fxcm_connection.create_entry_order,
#                     symbol,
#                     is_buy,
#                     amount,
#                     rate,
# )"
#             elif order_type == "STOP":
                # Stop order"
#                 if "stop_price" not in order_data:""
#                     raise ValueError("Stop price required for stop orders")
# "
#                 rate = float(order_data["stop_price"])
# result = await self._execute_sync(
#                     self._fxcm_connection.create_entry_order,
#                     symbol,
#                     is_buy,
#                     amount,
#                     rate,
#                     is_stop=True,
# )
#             else:""
#                 raise ValueError(f"Unsupported order type: {order_type}")

#             if result:
#                 order_id = str(result)
#                 self._orders[order_id] = {
# "id": order_id,"
# "status": "PENDING","
# "symbol": symbol,"
# "quantity": amount,"
# "side": order_data["side"],"
# "order_type": order_type,"
# "timestamp": datetime.now().isoformat(),
# }

#                 return {
# "success": True,"
# "order_id": order_id,"
# "status": "PENDING","
# "message": "Order placed successfully",
# }
#             else:""
#                 return {"success": False, "error": "Failed to place order"}

#         except Exception as e:""
#             self.logger.error(f"Error placing order: {e}")""
#             return {"success": False, "error": str(e)}

#     async def cancel_order(self, order_id: str):
#         "Cancel an existing order"
#         try:
#             if not self._fxcm_connection or not self._fxcm_connection.is_connected():
#                 return False

# result = await self._execute_sync(
#                 self._fxcm_connection.delete_order, order_id
# )

#             if result:
#                 if order_id in self._orders:""
#                     self._orders[order_id]["status"] = "CANCELLED"
#                 return True
#             return False

#         except Exception as e:""
#             self.logger.error(f"Error cancelling order {order_id}: {e}")
#             return False

#     async def get_order_status(self, order_id: str):
#         "Get status of an order"
#         try:
            # Check local cache first
#             if order_id in self._orders:
#                 local_order = self._orders[order_id]

                # Try to get updated status from API
#                 if self._fxcm_connection and self._fxcm_connection.is_connected():
# orders_df = await self._execute_sync(
#                         self._fxcm_connection.get_orders
# )

#                     if orders_df is not None and not orders_df.empty:
                        # Find order in dataframe
#                         order_row = orders_df[orders_df.index == int(order_id)]
#                         if not order_row.empty:
#                             order_info = order_row.iloc[0]
#                             self._orders[order_id].update(
# {
# "status": "ACTIVE"
#                                     if order_info.get("isEntryOrder", False)""
# else "FILLED","
# "amount": order_info.get("amountK", 0),"
# "rate": order_info.get("rate", 0),
# }
# )
# "
#                 return self._orders[order_id]
#             else:""
#                 return {"error": "Order not found"}

#         except Exception as e:""
#             self.logger.error(f"Error getting order status for {order_id}: {e}")""
#             return {"error": str(e)}

# "

#     async def get_positions(self):
#         "Get current positions"
#         try:
#             if not self._fxcm_connection or not self._fxcm_connection.is_connected():
#                 return []

# positions_df = await self._execute_sync(
#                 self._fxcm_connection.get_open_positions
# )

#             if positions_df is not None and not positions_df.empty:
#                 positions = []
#                 for idx, position in positions_df.iterrows():
# positions.append(
# {"
# "position_id": str(idx),"
# "symbol": position.get("currency", "),"
# "quantity": int(position.get("amountK", 0)),"
# "side": "BUY" if position.get("isBuy", False) else "SELL","
# "open_rate": float(position.get("open", 0)),"
# "close_rate": float(position.get("close", 0)),"
# "unrealized_pnl": float(position.get("grossPL", 0)),"
# "net_pnl": float(position.get("netPL", 0)),"
# "timestamp": position.get("
#                                 "time", datetime.now().isoformat()
# ),
# }
# )

#                 self._positions = positions
#                 return positions
#             else:
#                 return []

#         except Exception as e:""
#             self.logger.error(f"Error getting positions: {e}")
#             return []

#     async def get_account_info(self):
#         "Get account information"
#         try:
#             if not self._fxcm_connection or not self._fxcm_connection.is_connected():
#                 return self._account_info

#             account_info = await self._get_account_info_sync()
#             if account_info:
#                 self._account_info = account_info

#             return self._account_info

#         except Exception as e:""
#             self.logger.error(f"Error getting account info: {e}")
#             return self._account_info

#     async def get_portfolio_value(self):
#         "Get total portfolio value"
#         try:
# account_info = await self.get_account_info()"
#             equity = Decimal(str(account_info.get("equity", 0)))
#             return equity

#         except Exception as e:""
#             self.logger.error(f"Error calculating portfolio value: {e}")""
#             return Decimal("0")

#     async def _get_account_info_sync(self):
#         "Get account info synchronously"
#         try:
#             if not self._fxcm_connection:
#                 return {}

#             accounts_df = await self._execute_sync(self._fxcm_connection.get_accounts)

#             if accounts_df is not None and not accounts_df.empty:
#                 account = accounts_df.iloc[0]  # Get first account
#                 return {
# "account_id": str(account.name),"
# "currency": account.get("currency", self.config.default_currency),"
# "balance": float(account.get("balance", 0)),"
# "equity": float(account.get("equity", 0)),"
# "day_pnl": float(account.get("dayPL", 0)),"
# "gross_pnl": float(account.get("grossPL", 0)),"
# "margin_rate": float(account.get("mc", 0)),"
# "margin_call": account.get("mcDate", "),"
# "server": self.config.server,"
# "last_updated": datetime.now().isoformat(),
# }
#             else:
#                 return {}

#         except Exception as e:""
#             self.logger.error(f"Error getting account info: {e}")
#             return {}

#     async def _load_instruments(self):
#         "Load available trading instruments"
#         try:
#             if not self._fxcm_connection:
#                 return

# instruments_df = await self._execute_sync(
#                 self._fxcm_connection.get_instruments
# )

#             if instruments_df is not None and not instruments_df.empty:
#                 for idx, instrument in instruments_df.iterrows():""
# symbol = instrument.get("currency", ")
#                     self._instruments[symbol] = {""
# "symbol": symbol,"
# "pip_size": float(instrument.get("pipSize", 0.0001)),"
# "pip_cost": float(instrument.get("pipCost", 1)),"
# "min_quantity": int(instrument.get("minQuantity", 1)),"
# "max_quantity": int(instrument.get("maxQuantity", 50000)),"
# "tradeable": True,
# }
# "
#                 self.logger.info(f"Loaded {len(self._instruments)} instruments")

#         except Exception as e:""
#             self.logger.error(f"Error loading instruments: {e}")

#     async def _execute_sync(self, func, *args, **kwargs):
#         "Execute synchronous FXCM function in async context"
#         loop = asyncio.get_event_loop()
#         return await loop.run_in_executor(None, func, *args, **kwargs)

#     async def get_historical_data(""
# self, symbol: str, timeframe: str = "H1", periods: int = 100
# ) -> List[Dict[str, Any]]:"
#         "Get historical price data"
#         try:
#             if not self._fxcm_connection or not self._fxcm_connection.is_connected():
#                 return []

            # Get historical data
# data_df = await self._execute_sync(
#                 self._fxcm_connection.get_candles,
#                 symbol,
#                 period=timeframe,
#                 number=periods,
# )

#             if data_df is not None and not data_df.empty:
#                 historical_data = []
#                 for timestamp, row in data_df.iterrows():
# historical_data.append(
# {"
# "timestamp": timestamp.isoformat(),"
# "open": float(row.get("bidopen", 0)),"
# "high": float(row.get("bidhigh", 0)),"
# "low": float(row.get("bidlow", 0)),"
# "close": float(row.get("bidclose", 0)),"
# "volume": int(row.get("tickqty", 0)),
# }
# )
#                 return historical_data
#             else:
#                 return []

#         except Exception as e:""
#             self.logger.error(f"Error getting historical data for {symbol}: {e}")
#             return []

#     async def get_current_price(self, symbol: str):
#         "Get current bid/ask prices for a symbol"
#         try:
#             if not self._fxcm_connection or not self._fxcm_connection.is_connected():
#                 return {}

            # Get current prices
# prices_df = await self._execute_sync(
#                 self._fxcm_connection.get_prices, symbol
# )

#             if prices_df is not None and not prices_df.empty:
#                 latest_price = prices_df.iloc[-1]
#                 return {
# "symbol": symbol,"
# "bid": float(latest_price.get("Bid", 0)),"
# "ask": float(latest_price.get("Ask", 0)),"
# "spread": float(latest_price.get("Ask", 0))"
# - float(latest_price.get("Bid", 0)),"
# "timestamp": datetime.now().isoformat(),
# }
#             else:
#                 return {}

#         except Exception as e:""
#             self.logger.error(f"Error getting current price for {symbol}: {e}")
#             return {}

#     async def get_available_instruments(self):
#         "Get list of available trading instruments"
#         return list(self._instruments.values())

#     async def close_position(self, position_id: str):
#         "Close an open position"
#         try:
#             if not self._fxcm_connection or not self._fxcm_connection.is_connected():
#                 return False

# result = await self._execute_sync(
#                 self._fxcm_connection.close_position, position_id
# )

#             return result is not None

#         except Exception as e:""
#             self.logger.error(f"Error closing position {position_id}: {e}")
#             return False
# "