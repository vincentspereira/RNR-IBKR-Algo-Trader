"""Multi-Account Manager for trading across multiple IBKR accounts.

Provides account registration, order submission, broadcast allocation,
aggregate position/P&L tracking, and health monitoring across accounts.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class AccountStatus(Enum):
    """Status of a trading account connection."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    ERROR = "error"
    DISCONNECTED = "disconnected"


@dataclass
class OrderRequest:
    """Simple order request."""

    symbol: str
    side: str  # "buy" or "sell"
    quantity: float
    order_type: str = "market"
    price: Optional[float] = None
    strategy_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OrderResult:
    """Result of an order submission."""

    order_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    account_id: str = ""
    symbol: str = ""
    side: str = ""
    quantity: float = 0.0
    status: str = "submitted"  # submitted, rejected, failed
    error_message: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class Position:
    """Position in a single account."""

    symbol: str
    quantity: float
    avg_cost: float
    market_price: float = 0.0
    unrealized_pnl: float = 0.0

    @property
    def market_value(self) -> float:
        """Current market value of this position."""
        return self.quantity * self.market_price


@dataclass
class AccountInfo:
    """Account information."""

    account_id: str
    equity: float = 0.0
    cash: float = 0.0
    buying_power: float = 0.0
    positions: Dict[str, Position] = field(default_factory=dict)
    status: AccountStatus = AccountStatus.ACTIVE

    @property
    def total_position_value(self) -> float:
        """Total market value of all positions in this account."""
        return sum(p.market_value for p in self.positions.values())


@dataclass
class AggregatePosition:
    """Combined position across multiple accounts."""

    symbol: str
    total_quantity: float
    weighted_avg_cost: float
    total_market_value: float
    total_unrealized_pnl: float
    account_breakdown: Dict[str, float] = field(default_factory=dict)  # account_id -> quantity


@dataclass
class AggregatePnL:
    """Combined P&L across all accounts."""

    total_equity: float
    total_unrealized_pnl: float
    total_realized_pnl: float
    total_market_value: float
    account_count: int
    account_breakdown: Dict[str, float] = field(default_factory=dict)  # account_id -> unrealized_pnl


@dataclass
class HealthStatus:
    """Health status of an account connection."""

    account_id: str
    status: AccountStatus
    last_heartbeat: Optional[datetime] = None
    latency_ms: float = 0.0
    error_message: str = ""


class MockAdapter:
    """Mock broker adapter for testing."""

    async def place_order(self, order: Dict) -> Dict:
        """Submit a mock order."""
        return {"status": "submitted", "order_id": uuid.uuid4().hex[:12]}

    async def cancel_order(self, order_id: str) -> Dict:
        """Cancel a mock order."""
        return {"status": "cancelled"}

    async def get_positions(self) -> List[Dict]:
        """Return empty positions list."""
        return []

    async def get_account_info(self) -> Dict:
        """Return default account info."""
        return {"equity": 100000.0, "cash": 50000.0, "buying_power": 200000.0}

    async def health_check(self) -> bool:
        """Return healthy status."""
        return True


class AccountContext:
    """Context for a single trading account."""

    def __init__(self, account_id: str, adapter=None):
        self.account_id = account_id
        self._adapter = adapter or MockAdapter()
        self._status = AccountStatus.ACTIVE
        self._orders: Dict[str, OrderResult] = {}
        self._info: Optional[AccountInfo] = None
        self._logger = logging.getLogger(__name__)

    @property
    def status(self) -> AccountStatus:
        """Current status of this account."""
        return self._status

    @property
    def adapter(self):
        """The broker adapter for this account."""
        return self._adapter

    async def get_info(self) -> AccountInfo:
        """Get account information from adapter."""
        try:
            data = await self._adapter.get_account_info()
            positions_data = await self._adapter.get_positions()
            positions = {}
            for p in positions_data:
                pos = Position(
                    symbol=p.get("symbol", ""),
                    quantity=float(p.get("quantity", 0)),
                    avg_cost=float(p.get("avg_cost", 0)),
                    market_price=float(p.get("market_price", 0)),
                    unrealized_pnl=float(p.get("unrealized_pnl", 0)),
                )
                positions[pos.symbol] = pos

            self._info = AccountInfo(
                account_id=self.account_id,
                equity=float(data.get("equity", 0)),
                cash=float(data.get("cash", 0)),
                buying_power=float(data.get("buying_power", 0)),
                positions=positions,
                status=self._status,
            )
            return self._info
        except Exception as e:
            self._logger.error(f"Failed to get info for account {self.account_id}: {e}")
            self._status = AccountStatus.ERROR
            raise

    async def submit_order(self, order: OrderRequest) -> OrderResult:
        """Submit an order through this account's adapter."""
        try:
            result = await self._adapter.place_order({
                "symbol": order.symbol,
                "side": order.side,
                "quantity": order.quantity,
                "order_type": order.order_type,
                "price": order.price,
            })
            order_result = OrderResult(
                account_id=self.account_id,
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                status=result.get("status", "submitted"),
            )
            self._orders[order_result.order_id] = order_result
            return order_result
        except Exception as e:
            return OrderResult(
                account_id=self.account_id,
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                status="failed",
                error_message=str(e),
            )

    async def health_check(self) -> HealthStatus:
        """Check health of this account's connection."""
        try:
            is_healthy = await self._adapter.health_check()
            status = AccountStatus.ACTIVE if is_healthy else AccountStatus.DISCONNECTED
            self._status = status
            return HealthStatus(
                account_id=self.account_id,
                status=status,
                last_heartbeat=datetime.now(timezone.utc),
            )
        except Exception as e:
            self._status = AccountStatus.ERROR
            return HealthStatus(
                account_id=self.account_id,
                status=AccountStatus.ERROR,
                error_message=str(e),
            )


class MultiAccountManager:
    """Trade across multiple IBKR accounts simultaneously.

    Provides registration, order routing, broadcast allocation,
    and aggregate position/P&L tracking across accounts.
    """

    def __init__(self, event_bus=None):
        self._accounts: Dict[str, AccountContext] = {}
        self._event_bus = event_bus
        self._logger = logging.getLogger(__name__)

    async def register_account(self, account_id: str, adapter=None) -> None:
        """Register a trading account with its own adapter."""
        if account_id in self._accounts:
            raise ValueError(f"Account {account_id} already registered")
        context = AccountContext(account_id, adapter)
        self._accounts[account_id] = context
        self._logger.info(f"Registered account: {account_id}")

    def unregister_account(self, account_id: str) -> bool:
        """Unregister an account.

        Returns True if the account was found and removed, False otherwise.
        """
        return self._accounts.pop(account_id, None) is not None

    def get_account(self, account_id: str) -> Optional[AccountContext]:
        """Get an account context by ID."""
        return self._accounts.get(account_id)

    def get_account_ids(self) -> List[str]:
        """Get all registered account IDs."""
        return list(self._accounts.keys())

    async def submit_order(self, account_id: str, order: OrderRequest) -> OrderResult:
        """Submit order to a specific account."""
        context = self._accounts.get(account_id)
        if not context:
            return OrderResult(
                account_id=account_id,
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                status="rejected",
                error_message=f"Account {account_id} not found",
            )
        if context.status != AccountStatus.ACTIVE:
            return OrderResult(
                account_id=account_id,
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                status="rejected",
                error_message=f"Account {account_id} is {context.status.value}",
            )
        return await context.submit_order(order)

    async def broadcast_order(
        self, order: OrderRequest, allocation: Dict[str, float]
    ) -> Dict[str, OrderResult]:
        """Submit same order across multiple accounts with quantity allocation.

        Args:
            order: The order request template.
            allocation: Mapping of account_id to quantity for each account.

        Returns:
            Mapping of account_id to OrderResult for each account.
        """
        results = {}
        for account_id, quantity in allocation.items():
            account_order = OrderRequest(
                symbol=order.symbol,
                side=order.side,
                quantity=quantity,
                order_type=order.order_type,
                price=order.price,
                strategy_id=order.strategy_id,
                metadata={**order.metadata, "parent_broadcast": True},
            )
            results[account_id] = await self.submit_order(account_id, account_order)
        return results

    async def get_aggregate_positions(self) -> Dict[str, AggregatePosition]:
        """Get combined positions across all accounts."""
        all_positions: Dict[str, Dict[str, Position]] = {}  # symbol -> {account_id: Position}

        for account_id, context in self._accounts.items():
            try:
                info = await context.get_info()
                for symbol, position in info.positions.items():
                    if symbol not in all_positions:
                        all_positions[symbol] = {}
                    all_positions[symbol][account_id] = position
            except Exception as e:
                self._logger.warning(
                    f"Failed to get positions for account {account_id}: {e}"
                )

        aggregate = {}
        for symbol, account_positions in all_positions.items():
            total_qty = sum(p.quantity for p in account_positions.values())
            total_mv = sum(p.market_value for p in account_positions.values())
            total_pnl = sum(p.unrealized_pnl for p in account_positions.values())
            weighted_avg = (
                sum(p.avg_cost * p.quantity for p in account_positions.values()) / total_qty
                if total_qty > 0
                else 0.0
            )
            breakdown = {aid: p.quantity for aid, p in account_positions.items()}

            aggregate[symbol] = AggregatePosition(
                symbol=symbol,
                total_quantity=total_qty,
                weighted_avg_cost=weighted_avg,
                total_market_value=total_mv,
                total_unrealized_pnl=total_pnl,
                account_breakdown=breakdown,
            )

        return aggregate

    async def get_aggregate_pnl(self) -> AggregatePnL:
        """Get combined P&L across all accounts."""
        total_equity = 0.0
        total_unrealized = 0.0
        total_mv = 0.0
        breakdown: Dict[str, float] = {}

        for account_id, context in self._accounts.items():
            try:
                info = await context.get_info()
                total_equity += info.equity
                account_pnl = sum(p.unrealized_pnl for p in info.positions.values())
                total_unrealized += account_pnl
                total_mv += info.total_position_value
                breakdown[account_id] = account_pnl
            except Exception as e:
                self._logger.warning(
                    f"Failed to get P&L for account {account_id}: {e}"
                )

        return AggregatePnL(
            total_equity=total_equity,
            total_unrealized_pnl=total_unrealized,
            total_realized_pnl=0.0,  # Would need trade history for this
            total_market_value=total_mv,
            account_count=len(self._accounts),
            account_breakdown=breakdown,
        )

    async def health_check_all(self) -> Dict[str, HealthStatus]:
        """Check connectivity for all accounts."""
        results = {}
        for account_id, context in self._accounts.items():
            results[account_id] = await context.health_check()
        return results
