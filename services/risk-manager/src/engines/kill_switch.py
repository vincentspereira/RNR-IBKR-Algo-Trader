"""Emergency Kill Switch for all trading activity.

Provides immediate shutdown capability:
- Cancels all open orders
- Closes all open positions via market orders
- Publishes critical risk alert event
- Requires manual confirmation to deactivate
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class KillSwitchState(Enum):
    """Kill switch operational state."""
    INACTIVE = "inactive"
    ACTIVATING = "activating"
    ACTIVE = "active"
    DEACTIVATING = "deactivating"


class KillSwitch:
    """Emergency stop for all trading activity.

    Usage:
        ks = KillSwitch(broker_adapter=adapter, event_bus=bus)
        await ks.activate("Daily loss limit exceeded")
        # ... all orders cancelled, positions closed
        await ks.deactivate()
    """

    def __init__(self, broker_adapter: Any = None, event_bus: Any = None):
        self._broker = broker_adapter
        self._event_bus = event_bus
        self._state = KillSwitchState.INACTIVE
        self._reason: Optional[str] = None
        self._activated_at: Optional[datetime] = None
        self._activation_log: List[Dict[str, Any]] = []

    @property
    def is_active(self) -> bool:
        return self._state == KillSwitchState.ACTIVE

    @property
    def state(self) -> KillSwitchState:
        return self._state

    @property
    def reason(self) -> Optional[str]:
        return self._reason

    @property
    def activated_at(self) -> Optional[datetime]:
        return self._activated_at

    async def activate(self, reason: str) -> Dict[str, Any]:
        """Activate kill switch: cancel all orders, close all positions.

        Args:
            reason: Human-readable reason for activation.

        Returns:
            Summary of actions taken.
        """
        if self._state == KillSwitchState.ACTIVE:
            logger.warning("Kill switch already active: %s", self._reason)
            return {"status": "already_active", "reason": self._reason}

        self._state = KillSwitchState.ACTIVATING
        self._reason = reason
        self._activated_at = datetime.now(timezone.utc)

        logger.critical("KILL SWITCH ACTIVATED: %s", reason)

        summary: Dict[str, Any] = {
            "reason": reason,
            "activated_at": self._activated_at.isoformat(),
            "orders_cancelled": 0,
            "positions_closed": 0,
            "errors": [],
        }

        # Step 1: Cancel all open orders
        orders_cancelled, order_errors = await self._cancel_all_orders()
        summary["orders_cancelled"] = orders_cancelled
        summary["errors"].extend(order_errors)

        # Step 2: Close all open positions
        positions_closed, position_errors = await self._close_all_positions()
        summary["positions_closed"] = positions_closed
        summary["errors"].extend(position_errors)

        # Step 3: Publish critical event
        await self._publish_emergency_event(reason, summary)

        self._state = KillSwitchState.ACTIVE
        self._activation_log.append(summary)

        logger.critical(
            "Kill switch activation complete: %d orders cancelled, %d positions closed",
            orders_cancelled, positions_closed,
        )

        return summary

    async def _cancel_all_orders(self) -> tuple:
        """Cancel all open orders via broker adapter."""
        cancelled = 0
        errors: List[str] = []

        if not self._broker:
            logger.warning("No broker adapter - cannot cancel orders")
            return cancelled, errors

        try:
            # Get open orders - broker adapter should expose this
            orders = await self._broker.get_open_orders() if hasattr(self._broker, "get_open_orders") else []

            for order in orders:
                order_id = order.get("order_id", order.get("id", ""))
                if not order_id:
                    continue
                try:
                    await self._broker.cancel_order(order_id)
                    cancelled += 1
                    logger.info("Cancelled order: %s", order_id)
                except Exception as e:
                    error_msg = f"Failed to cancel order {order_id}: {e}"
                    errors.append(error_msg)
                    logger.error(error_msg)

        except Exception as e:
            errors.append(f"Failed to retrieve open orders: {e}")
            logger.error("Failed to retrieve open orders: %s", e)

        return cancelled, errors

    async def _close_all_positions(self) -> tuple:
        """Close all open positions via market orders."""
        closed = 0
        errors: List[str] = []

        if not self._broker:
            logger.warning("No broker adapter - cannot close positions")
            return closed, errors

        try:
            positions = await self._broker.get_positions()

            for pos in positions:
                symbol = pos.get("symbol", pos.get("instrument", ""))
                quantity = float(pos.get("quantity", pos.get("position", 0)))

                if not symbol or quantity == 0:
                    continue

                try:
                    # Close position with opposing market order
                    closing_side = "sell" if quantity > 0 else "buy"
                    order_data = {
                        "symbol": symbol,
                        "side": closing_side,
                        "order_type": "market",
                        "quantity": abs(quantity),
                    }
                    result = await self._broker.place_order(order_data)

                    if result.get("status") in ("submitted", "accepted", "filled"):
                        closed += 1
                        logger.info(
                            "Closing position: %s %s %d",
                            symbol, closing_side, abs(quantity),
                        )
                    else:
                        errors.append(
                            f"Failed to close {symbol}: {result.get('reason', 'unknown error')}"
                        )

                except Exception as e:
                    error_msg = f"Failed to close position {symbol}: {e}"
                    errors.append(error_msg)
                    logger.error(error_msg)

        except Exception as e:
            errors.append(f"Failed to retrieve positions: {e}")
            logger.error("Failed to retrieve positions: %s", e)

        return closed, errors

    async def _publish_emergency_event(self, reason: str, summary: Dict[str, Any]):
        """Publish critical risk alert event."""
        if not self._event_bus:
            logger.warning("No event bus - cannot publish kill switch event")
            return

        try:
            # Use Event type from risk_engine module
            from .risk_engine import Event, EventPriority, EventType

            await self._event_bus.publish(Event(
                type=EventType.RISK_ALERT,
                data={
                    "action": "kill_switch_activated",
                    "reason": reason,
                    "summary": summary,
                },
                priority=EventPriority.CRITICAL,
                source="kill_switch",
            ))
        except Exception as e:
            logger.error("Failed to publish kill switch event: %s", e)

    async def deactivate(self, confirmation: str = "") -> bool:
        """Deactivate kill switch. Requires explicit confirmation.

        Args:
            confirmation: Must be "CONFIRM_DEACTIVATE" to proceed.

        Returns:
            True if deactivated successfully.
        """
        if self._state != KillSwitchState.ACTIVE:
            logger.warning("Kill switch is not active")
            return False

        if confirmation != "CONFIRM_DEACTIVATE":
            logger.warning("Kill switch deactivation requires confirmation string")
            return False

        self._state = KillSwitchState.DEACTIVATING

        logger.info(
            "Kill switch deactivated (was active since %s, reason: %s)",
            self._activated_at, self._reason,
        )

        # Publish deactivation event
        if self._event_bus:
            try:
                from .risk_engine import Event, EventPriority, EventType

                await self._event_bus.publish(Event(
                    type=EventType.RISK_ALERT,
                    data={
                        "action": "kill_switch_deactivated",
                        "previous_reason": self._reason,
                    },
                    priority=EventPriority.HIGH,
                    source="kill_switch",
                ))
            except Exception as e:
                logger.error("Failed to publish deactivation event: %s", e)

        self._state = KillSwitchState.INACTIVE
        self._reason = None
        self._activated_at = None

        return True

    def get_status(self) -> Dict[str, Any]:
        """Get current kill switch status."""
        return {
            "state": self._state.value,
            "is_active": self.is_active,
            "reason": self._reason,
            "activated_at": self._activated_at.isoformat() if self._activated_at else None,
            "activation_count": len(self._activation_log),
        }

    def get_activation_history(self) -> List[Dict[str, Any]]:
        """Get history of kill switch activations."""
        return self._activation_log.copy()
