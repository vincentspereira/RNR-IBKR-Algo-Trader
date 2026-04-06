"""Order Persistence with PostgreSQL.

Provides crash-recoverable order storage using the existing
`trading.orders` table defined in infrastructure/postgres/init/04-create-trading-tables.sql.

Uses the PostgreSQLClient from libs/database/postgres/client.py.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)

# Lazy import to avoid hard dependency at module load
_postgres_client = None


def _get_postgres_client():
    """Lazily initialize the PostgreSQL client."""
    global _postgres_client
    if _postgres_client is None:
        try:
            from libs.database.postgres.client import get_postgres_client
            _postgres_client = get_postgres_client()
        except Exception as e:
            logger.warning("PostgreSQL client not available: %s", e)
    return _postgres_client


class OrderStore:
    """Persist orders to PostgreSQL for crash recovery.

    Maps to the existing `trading.orders` table schema.
    """

    def __init__(self, postgres_client=None):
        self._client = postgres_client

    @property
    def _db(self):
        if self._client:
            return self._client
        return _get_postgres_client()

    async def save_order(self, order: Any) -> bool:
        """Insert or update an order in the database.

        Args:
            order: Order object (dataclass or dict). Supports both the
                   execution_engine.Order dataclass and plain dicts.

        Returns:
            True if saved successfully.
        """
        db = self._db
        if not db:
            logger.warning("No database client - order not persisted")
            return False

        try:
            data = self._order_to_dict(order)

            async with db.session() as session:
                # Check if order already exists
                existing = await session.execute(
                    text("SELECT order_id FROM trading.orders WHERE order_id = :order_id"),
                    {"order_id": data["order_id"]},
                )
                row = existing.first()

                if row:
                    # Update existing order
                    await session.execute(
                        text("""
                            UPDATE trading.orders SET
                                symbol = :symbol,
                                order_type = :order_type,
                                side = :side,
                                quantity = :quantity,
                                price = :price,
                                limit_price = :limit_price,
                                stop_price = :stop_price,
                                status = :status,
                                broker_order_id = :broker_order_id,
                                filled_quantity = :filled_quantity,
                                avg_fill_price = :avg_fill_price,
                                commission = :commission,
                                time_in_force = :time_in_force,
                                strategy_id = :strategy_id,
                                updated_at = NOW()
                            WHERE order_id = :order_id
                        """),
                        data,
                    )
                else:
                    # Insert new order
                    await session.execute(
                        text("""
                            INSERT INTO trading.orders (
                                order_id, strategy_id, symbol, order_type, side,
                                quantity, price, limit_price, stop_price, status,
                                broker_order_id, filled_quantity, avg_fill_price,
                                commission, time_in_force, created_at, updated_at, metadata
                            ) VALUES (
                                :order_id, :strategy_id, :symbol, :order_type, :side,
                                :quantity, :price, :limit_price, :stop_price, :status,
                                :broker_order_id, :filled_quantity, :avg_fill_price,
                                :commission, :time_in_force, NOW(), NOW(), :metadata
                            )
                        """),
                        data,
                    )

            logger.debug("Order saved: %s", data["order_id"])
            return True

        except Exception as e:
            logger.error("Failed to save order %s: %s", getattr(order, "order_id", "unknown"), e)
            return False

    async def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve order by ID.

        Returns:
            Order data as dict, or None if not found.
        """
        db = self._db
        if not db:
            return None

        try:
            async with db.session() as session:
                result = await session.execute(
                    text("""
                        SELECT
                            order_id, strategy_id, symbol, order_type, side,
                            quantity, price, limit_price, stop_price, status,
                            broker_order_id, filled_quantity, avg_fill_price,
                            commission, time_in_force, created_at, updated_at, metadata
                        FROM trading.orders
                        WHERE order_id = :order_id
                    """),
                    {"order_id": order_id},
                )
                row = result.mappings().first()
                if row:
                    return dict(row)
            return None
        except Exception as e:
            logger.error("Failed to get order %s: %s", order_id, e)
            return None

    async def get_active_orders(self) -> List[Dict[str, Any]]:
        """Get all non-terminal orders (pending, submitted, partially_filled).

        Returns:
            List of order dicts.
        """
        db = self._db
        if not db:
            return []

        try:
            async with db.session() as session:
                result = await session.execute(
                    text("""
                        SELECT
                            order_id, strategy_id, symbol, order_type, side,
                            quantity, price, limit_price, stop_price, status,
                            broker_order_id, filled_quantity, avg_fill_price,
                            commission, time_in_force, created_at, updated_at, metadata
                        FROM trading.orders
                        WHERE status IN ('PENDING', 'SUBMITTED', 'PARTIALLY_FILLED')
                        ORDER BY created_at ASC
                    """),
                )
                return [dict(row) for row in result.mappings().all()]
        except Exception as e:
            logger.error("Failed to get active orders: %s", e)
            return []

    async def get_orders_by_symbol(self, symbol: str) -> List[Dict[str, Any]]:
        """Get all orders for a symbol."""
        db = self._db
        if not db:
            return []

        try:
            async with db.session() as session:
                result = await session.execute(
                    text("""
                        SELECT
                            order_id, strategy_id, symbol, order_type, side,
                            quantity, price, limit_price, stop_price, status,
                            broker_order_id, filled_quantity, avg_fill_price,
                            commission, time_in_force, created_at, updated_at, metadata
                        FROM trading.orders
                        WHERE symbol = :symbol
                        ORDER BY created_at DESC
                    """),
                    {"symbol": symbol},
                )
                return [dict(row) for row in result.mappings().all()]
        except Exception as e:
            logger.error("Failed to get orders for %s: %s", symbol, e)
            return []

    async def update_order_status(
        self,
        order_id: str,
        status: str,
        filled_quantity: Optional[float] = None,
        avg_fill_price: Optional[float] = None,
        commission: Optional[float] = None,
        error_message: Optional[str] = None,
    ) -> bool:
        """Update order status and fill info.

        Returns:
            True if updated successfully.
        """
        db = self._db
        if not db:
            return False

        try:
            updates = ["status = :status", "updated_at = NOW()"]

            params: Dict[str, Any] = {"order_id": order_id, "status": status.upper()}

            if filled_quantity is not None:
                updates.append("filled_quantity = :filled_quantity")
                params["filled_quantity"] = filled_quantity

            if avg_fill_price is not None:
                updates.append("avg_fill_price = :avg_fill_price")
                params["avg_fill_price"] = avg_fill_price

            if commission is not None:
                updates.append("commission = :commission")
                params["commission"] = commission

            if status.upper() == "SUBMITTED":
                updates.append("submitted_at = NOW()")
            elif status.upper() == "FILLED":
                updates.append("filled_at = NOW()")
            elif status.upper() in ("CANCELLED",):
                updates.append("cancelled_at = NOW()")

            async with db.session() as session:
                await session.execute(
                    text(f"UPDATE trading.orders SET {', '.join(updates)} WHERE order_id = :order_id"),
                    params,
                )

            return True
        except Exception as e:
            logger.error("Failed to update order %s status: %s", order_id, e)
            return False

    async def reconcile_on_startup(self, broker_adapter: Any) -> Dict[str, Any]:
        """Compare DB orders with broker state on startup and resolve discrepancies.

        Args:
            broker_adapter: The broker adapter to query for current order/position state.

        Returns:
            Reconciliation summary.
        """
        summary: Dict[str, Any] = {
            "db_active_orders": 0,
            "broker_active_orders": 0,
            "reconciled": 0,
            "cancelled_in_db": 0,
            "errors": [],
        }

        db = self._db
        if not db or not broker_adapter:
            logger.warning("Cannot reconcile - missing database client or broker adapter")
            return summary

        try:
            # 1. Get active orders from DB
            db_orders = await self.get_active_orders()
            summary["db_active_orders"] = len(db_orders)

            if not db_orders:
                logger.info("No active orders in DB to reconcile")
                return summary

            # 2. Get broker order statuses
            for db_order in db_orders:
                order_id = db_order.get("order_id")
                broker_order_id = db_order.get("broker_order_id")

                if not broker_order_id:
                    # No broker order ID — order was never submitted, mark as cancelled
                    await self.update_order_status(order_id, "CANCELLED")
                    summary["cancelled_in_db"] += 1
                    logger.info("Reconciled: cancelled unsubmitted order %s", order_id)
                    continue

                try:
                    broker_status = await broker_adapter.get_order_status(broker_order_id)
                    broker_state = broker_status.get("status", "unknown").upper()

                    # Map broker status to our status
                    if broker_state in ("FILLED", "COMPLETE"):
                        await self.update_order_status(
                            order_id,
                            "FILLED",
                            filled_quantity=broker_status.get("filled_quantity"),
                            avg_fill_price=broker_status.get("avg_fill_price"),
                            commission=broker_status.get("commission"),
                        )
                        summary["reconciled"] += 1
                    elif broker_state in ("CANCELLED", "CANCELED"):
                        await self.update_order_status(order_id, "CANCELLED")
                        summary["cancelled_in_db"] += 1
                    elif broker_state in ("REJECTED",):
                        await self.update_order_status(order_id, "REJECTED")
                        summary["cancelled_in_db"] += 1
                    elif broker_state in ("PARTIAL", "PARTIALLY_FILLED"):
                        await self.update_order_status(
                            order_id,
                            "PARTIALLY_FILLED",
                            filled_quantity=broker_status.get("filled_quantity"),
                            avg_fill_price=broker_status.get("avg_fill_price"),
                        )
                        summary["reconciled"] += 1
                    else:
                        # Still active at broker — keep as-is
                        summary["reconciled"] += 1

                except Exception as e:
                    error_msg = f"Failed to reconcile order {order_id}: {e}"
                    summary["errors"].append(error_msg)
                    logger.error(error_msg)

            logger.info(
                "Reconciliation complete: %d DB orders, %d reconciled, %d cancelled",
                summary["db_active_orders"], summary["reconciled"], summary["cancelled_in_db"],
            )

        except Exception as e:
            summary["errors"].append(f"Reconciliation failed: {e}")
            logger.error("Order reconciliation failed: %s", e)

        return summary

    def _order_to_dict(self, order: Any) -> Dict[str, Any]:
        """Convert an Order object (dataclass or dict) to a DB-compatible dict."""
        if isinstance(order, dict):
            data = order.copy()
        else:
            data = {}
            for attr in (
                "order_id", "strategy_id", "instrument", "symbol",
                "order_type", "side", "quantity", "price",
                "stop_price", "status", "broker_order_id",
                "filled_quantity", "average_fill_price", "avg_fill_price",
                "commission", "time_in_force", "metadata",
                "limit_price",
            ):
                val = getattr(order, attr, None)
                if val is not None:
                    data[attr] = val

        # Normalize field names to match DB schema
        result: Dict[str, Any] = {
            "order_id": str(data.get("order_id", data.get("id", ""))),
            "strategy_id": data.get("strategy_id"),
            "symbol": data.get("symbol", data.get("instrument", "")),
            "order_type": str(data.get("order_type", "MARKET")).replace("OrderType.", "").upper(),
            "side": str(data.get("side", "BUY")).replace("OrderSide.", "").upper(),
            "quantity": float(data.get("quantity", 0)),
            "price": data.get("price"),
            "limit_price": data.get("limit_price", data.get("price")),
            "stop_price": data.get("stop_price"),
            "status": str(data.get("status", "PENDING")).replace("OrderStatus.", "").upper(),
            "broker_order_id": data.get("broker_order_id"),
            "filled_quantity": float(data.get("filled_quantity", 0)),
            "avg_fill_price": data.get("avg_fill_price", data.get("average_fill_price")),
            "commission": float(data.get("commission", 0)),
            "time_in_force": data.get("time_in_force", "DAY"),
            "metadata": data.get("metadata", {}),
        }

        return result
