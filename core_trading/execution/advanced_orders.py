"""Advanced Order Types for institutional-grade trading.

Provides TrailingStopOrder, BracketOrder, OCOOrder, OTOOrder, and IcebergOrder
implementations with full state tracking and validation.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class AdvancedOrderState:
    """State tracking for advanced orders."""
    status: str = "pending"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    trigger_price: float | None = None
    fill_price: float | None = None
    fill_quantity: float = 0.0
    error_message: str | None = None


class TrailingStopOrder:
    """Trailing stop order that follows price by a percentage or fixed amount.

    For a SELL trailing stop: triggers when price falls below (high_water_mark - trail).
    For a BUY trailing stop: triggers when price rises above (low_water_mark + trail).
    """

    def __init__(
        self,
        symbol: str,
        quantity: float,
        side: str,
        trail_type: str = "percentage",
        trail_amount: float = 0.05,
        event_bus: Any = None,
    ):
        self.order_id = uuid.uuid4().hex[:12]
        self.symbol = symbol
        self.quantity = quantity
        self.side = side
        self.trail_type = trail_type
        self.trail_amount = trail_amount
        self._state = AdvancedOrderState()
        self._high_water_mark: float | None = None
        self._low_water_mark: float | None = None
        self._event_bus = event_bus
        self._logger = logging.getLogger(__name__)

    def update_price(self, current_price: float) -> bool:
        """Update with new market price. Returns True if triggered."""
        if self._state.status in ("filled", "cancelled"):
            return False

        if self._high_water_mark is None or current_price > self._high_water_mark:
            self._high_water_mark = current_price
        if self._low_water_mark is None or current_price < self._low_water_mark:
            self._low_water_mark = current_price

        if self.side == "sell":
            trigger = self._calculate_trigger_price(self._high_water_mark)
            self._state.trigger_price = trigger
            if current_price <= trigger:
                self._state.status = "triggered"
                self._state.fill_price = current_price
                self._state.fill_quantity = self.quantity
                self._state.updated_at = datetime.now(UTC)
                return True
        else:  # buy
            trigger = self._calculate_trigger_price(self._low_water_mark)
            self._state.trigger_price = trigger
            if current_price >= trigger:
                self._state.status = "triggered"
                self._state.fill_price = current_price
                self._state.fill_quantity = self.quantity
                self._state.updated_at = datetime.now(UTC)
                return True

        self._state.updated_at = datetime.now(UTC)
        return False

    def _calculate_trigger_price(self, reference_price: float) -> float:
        """Calculate the trigger price based on trail type and amount."""
        if self.trail_type == "percentage":
            offset = reference_price * self.trail_amount
        else:
            offset = self.trail_amount

        if self.side == "sell":
            return reference_price - offset
        return reference_price + offset

    def get_trigger_price(self) -> float | None:
        """Get current trigger price."""
        if self._high_water_mark is not None and self.side == "sell":
            return self._calculate_trigger_price(self._high_water_mark)
        if self._low_water_mark is not None and self.side == "buy":
            return self._calculate_trigger_price(self._low_water_mark)
        return None

    def get_high_water_mark(self) -> float | None:
        return self._high_water_mark

    def get_low_water_mark(self) -> float | None:
        return self._low_water_mark

    @property
    def status(self) -> str:
        return self._state.status

    def cancel(self) -> bool:
        if self._state.status in ("triggered", "filled"):
            return False
        self._state.status = "cancelled"
        self._state.updated_at = datetime.now(UTC)
        return True


class BracketOrder:
    """Entry + take-profit + stop-loss as a single unit.

    When the entry order fills, the take-profit and stop-loss orders are
    automatically placed. When either TP or SL fills, the other is cancelled.
    """

    def __init__(
        self,
        symbol: str,
        quantity: float,
        side: str,
        entry_price: float,
        take_profit_price: float,
        stop_loss_price: float,
        event_bus: Any = None,
    ):
        self.order_id = uuid.uuid4().hex[:12]
        self.symbol = symbol
        self.quantity = quantity
        self.side = side
        self.entry_price = entry_price
        self.take_profit_price = take_profit_price
        self.stop_loss_price = stop_loss_price
        self._state = AdvancedOrderState()
        self._entry_status: str = "pending"
        self._tp_status: str = "pending"
        self._sl_status: str = "pending"
        self._event_bus = event_bus
        self._logger = logging.getLogger(__name__)

    def process_fill(self, fill_price: float, fill_quantity: float, order_type: str) -> str:
        """Process a fill for one of the bracket legs.

        Returns the action to take: "place_tp_sl", "cancel_sl", "cancel_tp", "none".
        """
        if order_type == "entry":
            self._entry_status = "filled"
            self._state.fill_price = fill_price
            self._state.fill_quantity = fill_quantity
            self._tp_status = "active"
            self._sl_status = "active"
            self._state.updated_at = datetime.now(UTC)
            return "place_tp_sl"

        if order_type == "take_profit":
            self._tp_status = "filled"
            self._sl_status = "cancelled"
            self._state.status = "completed"
            self._state.updated_at = datetime.now(UTC)
            return "cancel_sl"

        if order_type == "stop_loss":
            self._sl_status = "filled"
            self._tp_status = "cancelled"
            self._state.status = "completed"
            self._state.updated_at = datetime.now(UTC)
            return "cancel_tp"

        return "none"

    def validate(self) -> tuple[bool, str]:
        """Validate bracket order parameters."""
        if self.quantity <= 0:
            return False, "Quantity must be positive"

        if self.side == "buy":
            if self.take_profit_price <= self.entry_price:
                return False, "Take-profit must be above entry for buy bracket"
            if self.stop_loss_price >= self.entry_price:
                return False, "Stop-loss must be below entry for buy bracket"
        else:
            if self.take_profit_price >= self.entry_price:
                return False, "Take-profit must be below entry for sell bracket"
            if self.stop_loss_price <= self.entry_price:
                return False, "Stop-loss must be above entry for sell bracket"

        return True, "Valid"

    @property
    def status(self) -> str:
        if self._entry_status == "pending":
            return "pending"
        if self._tp_status == "filled" or self._sl_status == "filled":
            return "completed"
        if self._entry_status == "filled":
            return "active"
        return "pending"

    @property
    def entry_status(self) -> str:
        return self._entry_status

    @property
    def tp_status(self) -> str:
        return self._tp_status

    @property
    def sl_status(self) -> str:
        return self._sl_status

    def cancel(self) -> bool:
        self._entry_status = "cancelled"
        self._tp_status = "cancelled"
        self._sl_status = "cancelled"
        self._state.status = "cancelled"
        self._state.updated_at = datetime.now(UTC)
        return True


class OCOOrder:
    """One-Cancels-Other: two orders, first fill cancels the other."""

    def __init__(
        self,
        symbol: str,
        quantity: float,
        order_a_side: str,
        order_a_price: float,
        order_b_side: str,
        order_b_price: float,
        event_bus: Any = None,
    ):
        self.order_id = uuid.uuid4().hex[:12]
        self.symbol = symbol
        self.quantity = quantity
        self.order_a_side = order_a_side
        self.order_a_price = order_a_price
        self.order_b_side = order_b_side
        self.order_b_price = order_b_price
        self._state = AdvancedOrderState()
        self._order_a_status: str = "pending"
        self._order_b_status: str = "pending"
        self._filled_order: str | None = None
        self._event_bus = event_bus
        self._logger = logging.getLogger(__name__)

    def process_fill(self, order_leg: str, fill_price: float, fill_quantity: float) -> str:
        """Process a fill on one leg. Returns the other leg to cancel ("a" or "b" or "none")."""
        if self._filled_order is not None:
            return "none"

        if order_leg == "a":
            self._order_a_status = "filled"
            self._order_b_status = "cancelled"
            self._filled_order = "a"
            self._state.fill_price = fill_price
            self._state.fill_quantity = fill_quantity
            self._state.updated_at = datetime.now(UTC)
            return "b"
        if order_leg == "b":
            self._order_b_status = "filled"
            self._order_a_status = "cancelled"
            self._filled_order = "b"
            self._state.fill_price = fill_price
            self._state.fill_quantity = fill_quantity
            self._state.updated_at = datetime.now(UTC)
            return "a"

        return "none"

    @property
    def status(self) -> str:
        if self._filled_order is not None:
            return "completed"
        if self._order_a_status == "cancelled" and self._order_b_status == "cancelled":
            return "cancelled"
        return "pending"

    @property
    def filled_order(self) -> str | None:
        return self._filled_order

    def cancel(self) -> bool:
        if self._filled_order is not None:
            return False
        self._order_a_status = "cancelled"
        self._order_b_status = "cancelled"
        self._state.status = "cancelled"
        self._state.updated_at = datetime.now(UTC)
        return True


class OTOOrder:
    """One-Triggers-Other: parent fill triggers child order."""

    def __init__(
        self,
        symbol: str,
        quantity: float,
        parent_side: str,
        parent_price: float,
        child_side: str,
        child_price: float,
        child_quantity: float | None = None,
        event_bus: Any = None,
    ):
        self.order_id = uuid.uuid4().hex[:12]
        self.symbol = symbol
        self.quantity = quantity
        self.parent_side = parent_side
        self.parent_price = parent_price
        self.child_side = child_side
        self.child_price = child_price
        self.child_quantity = child_quantity or quantity
        self._state = AdvancedOrderState()
        self._parent_status: str = "pending"
        self._child_status: str = "pending"
        self._event_bus = event_bus
        self._logger = logging.getLogger(__name__)

    def process_parent_fill(self, fill_price: float, fill_quantity: float) -> bool:
        """Process parent order fill. Returns True if child should be placed."""
        if self._parent_status != "pending":
            return False
        self._parent_status = "filled"
        self._child_status = "active"
        self._state.fill_price = fill_price
        self._state.fill_quantity = fill_quantity
        self._state.updated_at = datetime.now(UTC)
        return True

    def process_child_fill(
        self,
        fill_price: float,  # noqa: ARG002 - kept for signature symmetry with process_parent_fill
        fill_quantity: float,  # noqa: ARG002 - kept for signature symmetry with process_parent_fill
    ) -> None:
        """Process child order fill."""
        self._child_status = "filled"
        self._state.updated_at = datetime.now(UTC)

    @property
    def status(self) -> str:
        if self._state.status == "cancelled":
            return "cancelled"
        if self._child_status == "filled":
            return "completed"
        if self._parent_status == "filled":
            return "active"
        return "pending"

    def cancel(self) -> bool:
        if self._child_status == "filled":
            return False
        if self._parent_status == "filled":
            self._child_status = "cancelled"
        else:
            self._parent_status = "cancelled"
            self._child_status = "cancelled"
        self._state.status = "cancelled"
        self._state.updated_at = datetime.now(UTC)
        return True


class IcebergOrder:
    """Large order with only a visible portion shown to the market.

    When the visible portion fills, a new slice is automatically shown.
    """

    def __init__(
        self,
        symbol: str,
        total_quantity: float,
        side: str,
        visible_quantity: float,
        price: float | None = None,
        event_bus: Any = None,
    ):
        self.order_id = uuid.uuid4().hex[:12]
        self.symbol = symbol
        self.total_quantity = total_quantity
        self.side = side
        self.visible_quantity = visible_quantity
        self.price = price
        self._state = AdvancedOrderState()
        self._filled_quantity: float = 0.0
        self._remaining_quantity: float = total_quantity
        self._current_visible: float = min(visible_quantity, total_quantity)
        self._slice_count: int = 0
        self._fills: list[dict[str, Any]] = []
        self._event_bus = event_bus
        self._logger = logging.getLogger(__name__)

    def process_fill(self, fill_quantity: float, fill_price: float) -> tuple[float, bool]:
        """Process a fill of the visible portion.

        Returns (next_visible_quantity, is_complete).
        """
        actual_fill = min(fill_quantity, self._current_visible, self._remaining_quantity)
        self._filled_quantity += actual_fill
        self._remaining_quantity -= actual_fill
        self._slice_count += 1

        self._fills.append({
            "slice": self._slice_count,
            "quantity": actual_fill,
            "price": fill_price,
            "timestamp": datetime.now(UTC).isoformat(),
        })

        is_complete = self._remaining_quantity <= 0
        if is_complete:
            self._current_visible = 0.0
            self._state.status = "completed"
        else:
            self._current_visible = min(self.visible_quantity, self._remaining_quantity)
            self._state.status = "active"

        self._state.fill_quantity = self._filled_quantity
        self._state.updated_at = datetime.now(UTC)
        return (self._current_visible, is_complete)

    def get_next_slice(self) -> float:
        """Get the next visible quantity to show."""
        if self._remaining_quantity <= 0:
            return 0.0
        return min(self.visible_quantity, self._remaining_quantity)

    @property
    def remaining_quantity(self) -> float:
        return self._remaining_quantity

    @property
    def filled_quantity(self) -> float:
        return self._filled_quantity

    @property
    def slice_count(self) -> int:
        return self._slice_count

    @property
    def status(self) -> str:
        if self._state.status == "completed":
            return "completed"
        if self._state.status == "cancelled":
            return "cancelled"
        if self._filled_quantity > 0:
            return "active"
        return "pending"

    def cancel(self) -> bool:
        if self._remaining_quantity <= 0:
            return False
        self._state.status = "cancelled"
        self._state.updated_at = datetime.now(UTC)
        return True

    def get_fill_history(self) -> list[dict[str, Any]]:
        """Get history of all fills."""
        return list(self._fills)
