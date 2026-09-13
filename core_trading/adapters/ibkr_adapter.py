"""Interactive Brokers (IBKR) Adapter.

Comprehensive integration with Interactive Brokers for both paper and live
trading with enhanced risk management, multi-asset support, and conservative
configuration.

Features:
- Multi-asset class support (Equities, Options, Futures, Forex, Commodities, Cryptos)
- Conservative risk management with configurable limits
- Auto-reconnect with exponential backoff
- Event-driven callbacks for connection/disconnection/errors
"""

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional

try:
    from ib_insync import IB, Contract, Order, Stock, Option, Future, Forex, Trade, util
    IBKR_AVAILABLE = True
except ImportError:
    IB = None
    Contract = None
    Order = None
    Stock = None
    Option = None
    Future = None
    Forex = None
    Trade = None
    util = None
    IBKR_AVAILABLE = False

from .base import (
    AdapterConfig,
    AdapterType,
    BaseBrokerAdapter,
    ConnectionStatus,
    HealthCheck,
)

logger = logging.getLogger(__name__)


class AssetClass(Enum):
    EQUITIES = "equities"
    OPTIONS = "options"
    FUTURES = "futures"
    FOREX = "forex"
    COMMODITIES = "commodities"
    CRYPTOCURRENCIES = "cryptocurrencies"


@dataclass
class RiskLimits:
    """Conservative risk limits configuration."""
    max_position_size: float = 1000.0
    daily_loss_limit_percentage: float = 2.0
    max_daily_trades: int = 10
    max_concurrent_positions: int = 5
    stop_loss_mandatory: bool = True
    ai_confidence_threshold: float = 0.9


@dataclass
class PerformanceMetrics:
    """Performance tracking metrics."""
    order_latency_ms: float = 0.0
    connection_uptime: float = 0.0
    daily_trades: int = 0
    daily_pnl: float = 0.0
    data_quality_score: float = 1.0
    error_count: int = 0


class IBKRAdapter(BaseBrokerAdapter):
    """Adapter for Interactive Brokers integration.

    Provides comprehensive methods for connecting to IBKR, submitting orders,
    managing trading modes (paper vs live), and implementing conservative
    risk management.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 7497,
        client_id: int = 1,
        account_id: Optional[str] = None,
        paper_trading: bool = True,
    ):
        config = AdapterConfig(
            name="ibkr",
            adapter_type=AdapterType.BROKER,
            auto_reconnect=True,
            max_reconnect_attempts=10,
            reconnect_delay=__import__("datetime").timedelta(seconds=5),
            heartbeat_interval=__import__("datetime").timedelta(seconds=30),
        )
        super().__init__(config)

        self.host = host
        self.port = port
        self.client_id = client_id
        self.account_id = account_id or os.getenv("IBKR_ACCOUNT_ID")
        if not self.account_id:
            raise ValueError(
                "IBKR_ACCOUNT_ID is required: pass account_id to IBKRAdapter() "
                "or set the IBKR_ACCOUNT_ID environment variable."
            )
        self.paper_trading = paper_trading
        self.ib: Optional[IB] = None

        # Conservative risk management
        self.risk_limits = self._load_risk_configuration()
        self.performance_metrics = PerformanceMetrics()
        self.connection_start_time: Optional[datetime] = None

        # Daily tracking
        self._daily_trades: List[Dict] = []
        self._daily_pnl = 0.0
        self._last_reset_date = datetime.now(timezone.utc).date()

        # Order tracking
        self._orders: Dict[str, Dict[str, Any]] = {}
        self._next_order_id = 1
        self._positions: Dict[str, Dict[str, Any]] = {}
        self._account_balance = 50000.0

        # Market data subscriptions
        self._market_data_callbacks: Dict[str, List[Callable]] = {}

        # Fill / order status routing (set by bootstrap via on_fill / on_order_status)
        self._fill_callback: Optional[Callable[[str, float, float], Awaitable[None]]] = None
        self._status_callback: Optional[Callable[[str, str], Awaitable[None]]] = None

        # Reconnection state
        self._reconnect_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None

    def _load_risk_configuration(self) -> RiskLimits:
        """Load conservative risk configuration from environment or defaults."""
        return RiskLimits(
            max_position_size=float(
                os.getenv("IBKR_PAPER_MAX_POSITION_SIZE", "1000.0")
            ),
            daily_loss_limit_percentage=float(
                os.getenv("IBKR_PAPER_MAX_DAILY_LOSS_PERCENTAGE", "2.0")
            ),
            max_daily_trades=int(os.getenv("IBKR_PAPER_MAX_DAILY_TRADES", "10")),
            max_concurrent_positions=int(
                os.getenv("IBKR_MAX_CONCURRENT_POSITIONS", "5")
            ),
            stop_loss_mandatory=(
                os.getenv("IBKR_STOP_LOSS_MANDATORY", "true").lower() == "true"
            ),
            ai_confidence_threshold=float(
                os.getenv("IBKR_AI_CONFIDENCE_THRESHOLD", "0.9")
            ),
        )

    async def connect(self) -> bool:
        """Connect to Interactive Brokers TWS/Gateway."""
        if not IBKR_AVAILABLE:
            self._set_status(ConnectionStatus.ERROR)
            raise RuntimeError(
                "ib_insync is not installed - cannot connect to IBKR. "
                "Install with: pip install ib_insync>=0.9.86"
            )

        self._set_status(ConnectionStatus.CONNECTING)

        try:
            self.ib = IB()
            await self.ib.connectAsync(self.host, self.port, clientId=self.client_id)
            self._set_status(ConnectionStatus.CONNECTED)
            self.connection_start_time = datetime.now(timezone.utc)
            self._register_ib_callbacks()
            logger.info(
                f"Connected to IBKR {'paper' if self.paper_trading else 'live'} "
                f"trading at {self.host}:{self.port} clientId={self.client_id}"
            )
            return True
        except Exception as e:
            self._set_status(ConnectionStatus.ERROR)
            logger.error(f"Failed to connect to IBKR at {self.host}:{self.port}: {e}")
            return False

    async def disconnect(self) -> bool:
        """Disconnect from Interactive Brokers."""
        try:
            if self._heartbeat_task:
                self._heartbeat_task.cancel()
            if self._reconnect_task:
                self._reconnect_task.cancel()

            if self.ib is not None and self.ib.isConnected():
                self.ib.disconnect()

            self._set_status(ConnectionStatus.DISCONNECTED)
            logger.info("Disconnected from IBKR")
            return True
        except Exception as e:
            logger.error(f"Error disconnecting from IBKR: {e}")
            return False

    async def health_check(self) -> HealthCheck:
        """Check connection health."""
        if self.ib is not None and self.ib.isConnected():
            return HealthCheck(
                status=ConnectionStatus.CONNECTED,
                timestamp=datetime.now(timezone.utc),
            )
        return HealthCheck(
            status=ConnectionStatus.DISCONNECTED,
            timestamp=datetime.now(timezone.utc),
            error_message="Not connected to IBKR",
        )

    def on_fill(
        self, callback: Callable[[str, float, float], Awaitable[None]]
    ) -> None:
        """Register a coroutine to handle fills. Signature: (broker_order_id, qty, price)."""
        self._fill_callback = callback

    def on_order_status(
        self, callback: Callable[[str, str], Awaitable[None]]
    ) -> None:
        """Register a coroutine to handle order status changes.

        Signature: (broker_order_id, ib_status). Statuses follow ib_insync
        OrderStatus.status: 'PendingSubmit', 'PreSubmitted', 'Submitted',
        'Filled', 'Cancelled', 'ApiCancelled', 'Inactive'.
        """
        self._status_callback = callback

    def _register_ib_callbacks(self):
        """Register IBKR event callbacks."""
        if self.ib is None:
            return

        self.ib.disconnectedEvent += self._on_disconnected
        self.ib.errorEvent += self._on_error
        self.ib.execDetailsEvent += self._on_exec_details
        self.ib.orderStatusEvent += self._on_order_status

    def _on_disconnected(self, *_args):
        """Handle IBKR disconnection."""
        self._set_status(ConnectionStatus.DISCONNECTED)
        self._emit_event("disconnected")
        logger.warning("IBKR connection lost")

    def _on_error(self, reqId, errorCode, errorString, contract):
        """Handle IBKR errors."""
        logger.error(f"IBKR error: code={errorCode}, msg={errorString}")
        self.performance_metrics.error_count += 1
        self._emit_event("error", {
            "code": errorCode,
            "message": errorString,
            "contract": str(contract) if contract else None,
        })

    def _on_exec_details(self, trade, fill):
        """Route IBKR execution-detail (fill) to the registered fill callback."""
        try:
            broker_order_id = str(fill.execution.orderId)
            qty = float(fill.execution.shares)
            price = float(fill.execution.price)
            logger.info(
                f"IBKR fill: broker_order_id={broker_order_id} qty={qty} price={price}"
            )
        except Exception as e:
            logger.error(f"Failed to parse IBKR exec details: {e}")
            return

        if self._fill_callback is None:
            logger.warning(
                f"IBKR fill received but no fill_callback registered "
                f"(broker_order_id={broker_order_id})"
            )
            return

        try:
            asyncio.create_task(self._fill_callback(broker_order_id, qty, price))
        except RuntimeError as e:
            logger.error(f"Cannot schedule fill callback (no running loop?): {e}")

    def _on_order_status(self, trade):
        """Route IBKR orderStatus updates to the registered status callback."""
        try:
            broker_order_id = str(trade.order.orderId)
            ib_status = str(trade.orderStatus.status)
        except Exception as e:
            logger.error(f"Failed to parse IBKR order status: {e}")
            return

        logger.debug(
            f"IBKR order status: broker_order_id={broker_order_id} status={ib_status}"
        )

        if self._status_callback is None:
            return

        try:
            asyncio.create_task(self._status_callback(broker_order_id, ib_status))
        except RuntimeError as e:
            logger.error(f"Cannot schedule status callback (no running loop?): {e}")

    async def _heartbeat_loop(self):
        """Monitor connection health periodically."""
        while self.is_connected:
            await asyncio.sleep(self.config.heartbeat_interval.total_seconds())
            try:
                if self.ib is not None and not self.ib.isConnected():
                    self._set_status(ConnectionStatus.DISCONNECTED)
                    logger.warning("IBKR heartbeat: connection lost")
                    self._emit_event("connection_lost")
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")

    def _create_contract(self, symbol: str, asset_class: AssetClass = AssetClass.EQUITIES, **kwargs) -> Any:
        """Create an IBKR Contract for the given symbol and asset class."""
        if asset_class == AssetClass.EQUITIES:
            return Stock(symbol, "SMART", "USD")
        elif asset_class == AssetClass.OPTIONS:
            return Option(
                symbol,
                kwargs.get("expiry", ""),
                kwargs.get("strike", 0),
                kwargs.get("right", "C"),
                "SMART",
                "USD",
            )
        elif asset_class == AssetClass.FUTURES:
            return Future(symbol, exchange=kwargs.get("exchange", "CME"))
        elif asset_class == AssetClass.FOREX:
            return Forex(symbol)
        elif asset_class == AssetClass.COMMODITIES:
            return Stock(symbol, "SMART", "USD")
        elif asset_class == AssetClass.CRYPTOCURRENCIES:
            return Stock(symbol, "PAXOS", "USD")
        else:
            return Stock(symbol, "SMART", "USD")

    def _check_risk_limits(self, order_data: Dict[str, Any]) -> bool:
        """Validate order against risk limits."""
        # Reset daily counters if new day
        today = datetime.now(timezone.utc).date()
        if today != self._last_reset_date:
            self._daily_trades.clear()
            self._daily_pnl = 0.0
            self._last_reset_date = today

        # Check daily trade limit
        if len(self._daily_trades) >= self.risk_limits.max_daily_trades:
            logger.warning("Risk limit: max daily trades exceeded")
            return False

        # Check position size. Fail closed: a market order without a price
        # estimate used to compute notional 0 and bypass this limit entirely
        # (VIN-40 F1). Reject instead of guessing a size.
        quantity = order_data.get("quantity", 0)
        price = order_data.get("price", 0) or order_data.get("stop_price", 0)
        if not price or price <= 0:
            logger.warning(
                "Risk limit: order lacks a positive price/stop_price estimate; "
                "cannot size position (rejecting)"
            )
            return False
        if quantity * price > self.risk_limits.max_position_size:
            logger.warning(
                f"Risk limit: position size {quantity * price} exceeds "
                f"max {self.risk_limits.max_position_size}"
            )
            return False

        # Check daily loss limit
        account_info = self._account_balance
        if account_info > 0:
            daily_loss_pct = abs(self._daily_pnl) / account_info * 100
            if daily_loss_pct >= self.risk_limits.daily_loss_limit_percentage:
                logger.warning("Risk limit: daily loss limit exceeded")
                return False

        # Check concurrent positions
        if len(self._positions) >= self.risk_limits.max_concurrent_positions:
            logger.warning("Risk limit: max concurrent positions exceeded")
            return False

        return True

    async def place_order(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """Place a trading order.

        Args:
            order_data: Dict with keys: symbol, side, quantity, order_type,
                       price (optional), stop_price (optional), asset_class (optional)

        Returns:
            Dict with order_id, status, and broker_order_id
        """
        if not self.is_connected:
            raise RuntimeError("Not connected to IBKR")

        if not self._check_risk_limits(order_data):
            return {
                "status": "rejected",
                "reason": "Risk limit violated",
                "order_id": None,
            }

        if self.ib is None:
            raise RuntimeError("IBKR adapter not connected; call connect() before placing orders")

        order_id = str(self._next_order_id)
        self._next_order_id += 1
        asset_class = order_data.get("asset_class", AssetClass.EQUITIES)
        if isinstance(asset_class, str):
            asset_class = AssetClass(asset_class)

        contract = self._create_contract(order_data["symbol"], asset_class)

        ib_order = Order()
        ib_order.action = "BUY" if order_data.get("side", "buy").lower() == "buy" else "SELL"
        ib_order.totalQuantity = order_data["quantity"]

        order_type = order_data.get("order_type", "market").lower()
        if order_type == "market":
            ib_order.orderType = "MKT"
        elif order_type == "limit":
            ib_order.orderType = "LMT"
            ib_order.lmtPrice = order_data.get("price", 0)
        elif order_type == "stop":
            ib_order.orderType = "STP"
            ib_order.auxPrice = order_data.get("stop_price", 0)
        elif order_type == "stop_limit":
            ib_order.orderType = "STP LMT"
            ib_order.lmtPrice = order_data.get("price", 0)
            ib_order.auxPrice = order_data.get("stop_price", 0)

        try:
            trade = self.ib.placeOrder(contract, ib_order)
            broker_order_id = str(trade.order.orderId)
            self._orders[order_id] = {
                "order_data": order_data,
                "status": "submitted",
                "timestamp": datetime.now(timezone.utc),
                "broker_order_id": broker_order_id,
                "trade": trade,
            }
            self._daily_trades.append(order_data)
            logger.info(f"IBKR order submitted: {order_id} -> broker {broker_order_id}")
            return {
                "order_id": order_id,
                "status": "submitted",
                "broker_order_id": broker_order_id,
            }
        except Exception as e:
            logger.error(f"Failed to place IBKR order: {e}")
            self._orders[order_id] = {
                "order_data": order_data,
                "status": "rejected",
                "timestamp": datetime.now(timezone.utc),
                "error": str(e),
            }
            return {
                "order_id": order_id,
                "status": "rejected",
                "reason": str(e),
            }

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an existing order."""
        if not self.is_connected:
            raise RuntimeError("Not connected to IBKR")

        order_record = self._orders.get(order_id)
        if not order_record:
            logger.warning(f"Order not found for cancellation: {order_id}")
            return False

        if self.ib is None:
            raise RuntimeError("IBKR adapter not connected; cannot cancel order")

        try:
            trade = order_record.get("trade")
            if trade:
                self.ib.cancelOrder(trade.order)
            order_record["status"] = "cancelled"
            logger.info(f"IBKR order cancelled: {order_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel IBKR order {order_id}: {e}")
            return False

    async def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """Get status of an order."""
        if not self.is_connected:
            raise RuntimeError("Not connected to IBKR")

        order_record = self._orders.get(order_id)
        if not order_record:
            return {"status": "unknown", "error": "Order not found"}

        try:
            trade = order_record.get("trade")
            if trade:
                # BrokerLike contract (core_trading/ops/pairs_live_runner.py):
                # consumers read ``filled_quantity`` and ``avg_fill_price``.
                # Emitting any other fill-quantity key leaves every consumer
                # parsing 0.0 fills and the position book never updating.
                return {
                    "status": trade.orderStatus.status.lower(),
                    "filled_quantity": trade.orderStatus.filled,
                    "avg_fill_price": trade.orderStatus.avgFillPrice,
                    "remaining": trade.orderStatus.remaining,
                }
            return {
                "status": order_record["status"],
                "filled_quantity": 0.0,
                "avg_fill_price": 0.0,
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    async def get_positions(self) -> List[Dict[str, Any]]:
        """Get current positions."""
        if not self.is_connected or self.ib is None:
            raise RuntimeError("Not connected to IBKR")

        try:
            positions = self.ib.positions()
            result = []
            for pos in positions:
                result.append({
                    "symbol": pos.contract.symbol,
                    "quantity": pos.position,
                    "avg_cost": pos.avgCost,
                    "contract": str(pos.contract),
                })
            return result
        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            return []

    async def get_account_info(self) -> Dict[str, Any]:
        """Get account information."""
        if not self.is_connected or self.ib is None:
            raise RuntimeError("Not connected to IBKR")

        try:
            account_values = {v.tag: v.value for v in self.ib.accountValues()}
            return {
                "account_id": self.account_id,
                "balance": float(account_values.get("TotalCashValue", 0)),
                "buying_power": float(account_values.get("BuyingPower", 0)),
                "net_liquidation": float(account_values.get("NetLiquidation", 0)),
                "currency": "USD",
                "raw": account_values,
            }
        except Exception as e:
            logger.error(f"Failed to get account info: {e}")
            return {"error": str(e)}

    async def get_portfolio_value(self) -> float:
        """Get total portfolio value."""
        info = await self.get_account_info()
        return float(info.get("net_liquidation", self._account_balance))

    async def subscribe_market_data(self, symbol: str, callback: Callable):
        """Subscribe to real-time market data for a symbol."""
        if not self.is_connected or self.ib is None:
            raise RuntimeError("Not connected to IBKR")

        if symbol not in self._market_data_callbacks:
            self._market_data_callbacks[symbol] = []
        self._market_data_callbacks[symbol].append(callback)

        contract = self._create_contract(symbol)
        ticker = self.ib.reqMktData(contract, "", False, False)
        ticker.updateEvent += lambda t: self._on_market_data(symbol, t)

        logger.info(f"Subscribed to market data: {symbol}")

    def _on_market_data(self, symbol: str, ticker):
        """Handle incoming market data."""
        data = {
            "symbol": symbol,
            "bid": ticker.bid if ticker.bid == ticker.bid else None,
            "ask": ticker.ask if ticker.ask == ticker.ask else None,
            "last": ticker.last if ticker.last == ticker.last else None,
            "volume": ticker.volume,
            "timestamp": datetime.now(timezone.utc),
        }
        for cb in self._market_data_callbacks.get(symbol, []):
            try:
                cb(data)
            except Exception as e:
                logger.error(f"Market data callback error for {symbol}: {e}")

    async def get_historical_data(
        self,
        symbol: str,
        duration: str = "1 D",
        bar_size: str = "1 min",
    ) -> List[Dict[str, Any]]:
        """Get historical OHLCV data via IBKR."""
        if not self.is_connected or self.ib is None:
            raise RuntimeError("Not connected to IBKR")

        try:
            contract = self._create_contract(symbol)
            bars = await self.ib.reqHistoricalDataAsync(
                contract,
                endDateTime="",
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow="TRADES",
                useRTH=True,
            )
            return [
                {
                    "date": str(bar.date),
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                }
                for bar in bars
            ]
        except Exception as e:
            logger.error(f"Failed to get historical data for {symbol}: {e}")
            return []

    async def start_heartbeat(self):
        """Start the heartbeat monitoring loop."""
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def reconnect_with_backoff(self) -> bool:
        """Reconnect with exponential backoff."""
        delays = [5, 10, 20, 40, 60]
        for attempt, delay in enumerate(delays):
            logger.info(f"Reconnect attempt {attempt + 1}/{len(delays)}, waiting {delay}s")
            await asyncio.sleep(delay)
            if await self.connect():
                return True
        logger.error("All reconnection attempts failed")
        return False


_ibkr_adapter: Optional[IBKRAdapter] = None


def get_ibkr_adapter() -> IBKRAdapter:
    """Get the global IBKR adapter instance."""
    global _ibkr_adapter
    if _ibkr_adapter is None:
        _ibkr_adapter = IBKRAdapter()
    return _ibkr_adapter


def initialize_ibkr_adapter(
    host: str = "127.0.0.1",
    port: int = 7497,
    client_id: int = 1,
    account_id: Optional[str] = None,
    paper_trading: bool = True,
) -> IBKRAdapter:
    """Initialize the global IBKR adapter instance."""
    global _ibkr_adapter
    _ibkr_adapter = IBKRAdapter(
        host=host,
        port=port,
        client_id=client_id,
        account_id=account_id,
        paper_trading=paper_trading,
    )
    return _ibkr_adapter
