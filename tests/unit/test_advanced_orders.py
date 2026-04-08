"""Tests for advanced order types."""

import pytest

from core_trading.execution.advanced_orders import (
    AdvancedOrderState,
    BracketOrder,
    IcebergOrder,
    OCOOrder,
    OTOOrder,
    TrailingStopOrder,
)


# ---------------------------------------------------------------------------
# TrailingStopOrder Tests
# ---------------------------------------------------------------------------


class TestTrailingStopOrder:
    def test_creation_percentage_trail(self):
        order = TrailingStopOrder(
            symbol="AAPL", quantity=100, side="sell",
            trail_type="percentage", trail_amount=0.05,
        )
        assert order.symbol == "AAPL"
        assert order.quantity == 100
        assert order.side == "sell"
        assert order.trail_type == "percentage"
        assert order.trail_amount == 0.05
        assert order.status == "pending"

    def test_creation_fixed_trail(self):
        order = TrailingStopOrder(
            symbol="AAPL", quantity=100, side="sell",
            trail_type="fixed", trail_amount=2.50,
        )
        assert order.trail_type == "fixed"
        assert order.trail_amount == 2.50

    def test_sell_trailing_stop_follows_high(self):
        order = TrailingStopOrder(
            symbol="AAPL", quantity=100, side="sell",
            trail_type="percentage", trail_amount=0.05,
        )
        order.update_price(100.0)
        assert order.get_high_water_mark() == 100.0

        order.update_price(105.0)
        assert order.get_high_water_mark() == 105.0
        assert order.status == "pending"

        order.update_price(103.0)
        assert order.get_high_water_mark() == 105.0
        assert order.status == "pending"

    def test_sell_trailing_stop_triggers(self):
        order = TrailingStopOrder(
            symbol="AAPL", quantity=100, side="sell",
            trail_type="percentage", trail_amount=0.10,
        )
        order.update_price(100.0)
        triggered = order.update_price(89.0)  # 10% drop from 100
        assert triggered is True
        assert order.status == "triggered"

    def test_buy_trailing_stop_follows_low(self):
        order = TrailingStopOrder(
            symbol="AAPL", quantity=100, side="buy",
            trail_type="percentage", trail_amount=0.05,
        )
        order.update_price(100.0)
        assert order.get_low_water_mark() == 100.0

        order.update_price(95.0)
        assert order.get_low_water_mark() == 95.0
        assert order.status == "pending"

        order.update_price(97.0)
        assert order.get_low_water_mark() == 95.0
        assert order.status == "pending"

    def test_buy_trailing_stop_triggers(self):
        order = TrailingStopOrder(
            symbol="AAPL", quantity=100, side="buy",
            trail_type="percentage", trail_amount=0.10,
        )
        order.update_price(100.0)
        triggered = order.update_price(110.5)  # > 100 * (1 + 0.10) = 110
        assert triggered is True
        assert order.status == "triggered"

    def test_trailing_stop_high_water_mark(self):
        order = TrailingStopOrder(
            symbol="AAPL", quantity=100, side="sell",
            trail_type="fixed", trail_amount=5.0,
        )
        order.update_price(100.0)
        order.update_price(110.0)
        order.update_price(108.0)
        assert order.get_high_water_mark() == 110.0

    def test_trailing_stop_low_water_mark(self):
        order = TrailingStopOrder(
            symbol="AAPL", quantity=100, side="buy",
            trail_type="fixed", trail_amount=5.0,
        )
        order.update_price(100.0)
        order.update_price(90.0)
        order.update_price(95.0)
        assert order.get_low_water_mark() == 90.0

    def test_trailing_stop_trigger_price_percentage(self):
        order = TrailingStopOrder(
            symbol="AAPL", quantity=100, side="sell",
            trail_type="percentage", trail_amount=0.05,
        )
        order.update_price(100.0)
        trigger = order.get_trigger_price()
        assert trigger == pytest.approx(95.0)

    def test_trailing_stop_trigger_price_fixed(self):
        order = TrailingStopOrder(
            symbol="AAPL", quantity=100, side="sell",
            trail_type="fixed", trail_amount=3.0,
        )
        order.update_price(100.0)
        trigger = order.get_trigger_price()
        assert trigger == pytest.approx(97.0)

    def test_trailing_stop_cancel(self):
        order = TrailingStopOrder(
            symbol="AAPL", quantity=100, side="sell",
            trail_type="percentage", trail_amount=0.05,
        )
        assert order.cancel() is True
        assert order.status == "cancelled"

    def test_trailing_stop_no_trigger_flat_price(self):
        order = TrailingStopOrder(
            symbol="AAPL", quantity=100, side="sell",
            trail_type="percentage", trail_amount=0.10,
        )
        for _ in range(10):
            triggered = order.update_price(100.0)
            assert triggered is False
        assert order.status == "pending"


# ---------------------------------------------------------------------------
# BracketOrder Tests
# ---------------------------------------------------------------------------


class TestBracketOrder:
    def test_creation_buy_bracket(self):
        bracket = BracketOrder(
            symbol="AAPL", quantity=100, side="buy",
            entry_price=150.0, take_profit_price=160.0, stop_loss_price=140.0,
        )
        assert bracket.symbol == "AAPL"
        assert bracket.quantity == 100
        assert bracket.entry_price == 150.0
        assert bracket.take_profit_price == 160.0
        assert bracket.stop_loss_price == 140.0
        assert bracket.status == "pending"

    def test_creation_sell_bracket(self):
        bracket = BracketOrder(
            symbol="AAPL", quantity=100, side="sell",
            entry_price=150.0, take_profit_price=140.0, stop_loss_price=160.0,
        )
        assert bracket.status == "pending"

    def test_validate_buy_bracket_valid(self):
        bracket = BracketOrder(
            symbol="AAPL", quantity=100, side="buy",
            entry_price=150.0, take_profit_price=160.0, stop_loss_price=140.0,
        )
        valid, msg = bracket.validate()
        assert valid is True
        assert msg == "Valid"

    def test_validate_buy_bracket_invalid_tp(self):
        bracket = BracketOrder(
            symbol="AAPL", quantity=100, side="buy",
            entry_price=150.0, take_profit_price=145.0, stop_loss_price=140.0,
        )
        valid, msg = bracket.validate()
        assert valid is False
        assert "take-profit" in msg.lower()

    def test_validate_buy_bracket_invalid_sl(self):
        bracket = BracketOrder(
            symbol="AAPL", quantity=100, side="buy",
            entry_price=150.0, take_profit_price=160.0, stop_loss_price=155.0,
        )
        valid, msg = bracket.validate()
        assert valid is False
        assert "stop-loss" in msg.lower()

    def test_validate_sell_bracket_valid(self):
        bracket = BracketOrder(
            symbol="AAPL", quantity=100, side="sell",
            entry_price=150.0, take_profit_price=140.0, stop_loss_price=160.0,
        )
        valid, msg = bracket.validate()
        assert valid is True

    def test_process_entry_fill(self):
        bracket = BracketOrder(
            symbol="AAPL", quantity=100, side="buy",
            entry_price=150.0, take_profit_price=160.0, stop_loss_price=140.0,
        )
        action = bracket.process_fill(150.0, 100, "entry")
        assert action == "place_tp_sl"
        assert bracket.entry_status == "filled"
        assert bracket.tp_status == "active"
        assert bracket.sl_status == "active"
        assert bracket.status == "active"

    def test_process_tp_fill_cancels_sl(self):
        bracket = BracketOrder(
            symbol="AAPL", quantity=100, side="buy",
            entry_price=150.0, take_profit_price=160.0, stop_loss_price=140.0,
        )
        bracket.process_fill(150.0, 100, "entry")
        action = bracket.process_fill(160.0, 100, "take_profit")
        assert action == "cancel_sl"
        assert bracket.tp_status == "filled"
        assert bracket.sl_status == "cancelled"
        assert bracket.status == "completed"

    def test_process_sl_fill_cancels_tp(self):
        bracket = BracketOrder(
            symbol="AAPL", quantity=100, side="buy",
            entry_price=150.0, take_profit_price=160.0, stop_loss_price=140.0,
        )
        bracket.process_fill(150.0, 100, "entry")
        action = bracket.process_fill(140.0, 100, "stop_loss")
        assert action == "cancel_tp"
        assert bracket.sl_status == "filled"
        assert bracket.tp_status == "cancelled"
        assert bracket.status == "completed"

    def test_cancel_all_legs(self):
        bracket = BracketOrder(
            symbol="AAPL", quantity=100, side="buy",
            entry_price=150.0, take_profit_price=160.0, stop_loss_price=140.0,
        )
        bracket.cancel()
        assert bracket.entry_status == "cancelled"
        assert bracket.tp_status == "cancelled"
        assert bracket.sl_status == "cancelled"

    def test_status_transitions(self):
        bracket = BracketOrder(
            symbol="AAPL", quantity=100, side="buy",
            entry_price=150.0, take_profit_price=160.0, stop_loss_price=140.0,
        )
        assert bracket.status == "pending"
        bracket.process_fill(150.0, 100, "entry")
        assert bracket.status == "active"
        bracket.process_fill(160.0, 100, "take_profit")
        assert bracket.status == "completed"

    def test_process_unknown_order_type_returns_none(self):
        bracket = BracketOrder(
            symbol="AAPL", quantity=100, side="buy",
            entry_price=150.0, take_profit_price=160.0, stop_loss_price=140.0,
        )
        action = bracket.process_fill(100.0, 100, "unknown")
        assert action == "none"


# ---------------------------------------------------------------------------
# OCOOrder Tests
# ---------------------------------------------------------------------------


class TestOCOOrder:
    def test_creation(self):
        oco = OCOOrder(
            symbol="AAPL", quantity=100,
            order_a_side="buy", order_a_price=150.0,
            order_b_side="sell", order_b_price=140.0,
        )
        assert oco.symbol == "AAPL"
        assert oco.quantity == 100
        assert oco.order_a_price == 150.0
        assert oco.order_b_price == 140.0
        assert oco.status == "pending"

    def test_process_fill_a_cancels_b(self):
        oco = OCOOrder(
            symbol="AAPL", quantity=100,
            order_a_side="buy", order_a_price=150.0,
            order_b_side="sell", order_b_price=140.0,
        )
        cancel_leg = oco.process_fill("a", 150.0, 100)
        assert cancel_leg == "b"
        assert oco.status == "completed"

    def test_process_fill_b_cancels_a(self):
        oco = OCOOrder(
            symbol="AAPL", quantity=100,
            order_a_side="buy", order_a_price=150.0,
            order_b_side="sell", order_b_price=140.0,
        )
        cancel_leg = oco.process_fill("b", 140.0, 100)
        assert cancel_leg == "a"
        assert oco.status == "completed"

    def test_process_fill_already_completed(self):
        oco = OCOOrder(
            symbol="AAPL", quantity=100,
            order_a_side="buy", order_a_price=150.0,
            order_b_side="sell", order_b_price=140.0,
        )
        oco.process_fill("a", 150.0, 100)
        cancel_leg = oco.process_fill("b", 140.0, 100)
        assert cancel_leg == "none"

    def test_status_pending(self):
        oco = OCOOrder(
            symbol="AAPL", quantity=100,
            order_a_side="buy", order_a_price=150.0,
            order_b_side="sell", order_b_price=140.0,
        )
        assert oco.status == "pending"

    def test_status_completed_after_fill(self):
        oco = OCOOrder(
            symbol="AAPL", quantity=100,
            order_a_side="buy", order_a_price=150.0,
            order_b_side="sell", order_b_price=140.0,
        )
        oco.process_fill("a", 150.0, 100)
        assert oco.status == "completed"

    def test_cancel(self):
        oco = OCOOrder(
            symbol="AAPL", quantity=100,
            order_a_side="buy", order_a_price=150.0,
            order_b_side="sell", order_b_price=140.0,
        )
        assert oco.cancel() is True
        assert oco.status == "cancelled"

    def test_cancel_after_fill_returns_false(self):
        oco = OCOOrder(
            symbol="AAPL", quantity=100,
            order_a_side="buy", order_a_price=150.0,
            order_b_side="sell", order_b_price=140.0,
        )
        oco.process_fill("a", 150.0, 100)
        assert oco.cancel() is False

    def test_filled_order_tracking(self):
        oco = OCOOrder(
            symbol="AAPL", quantity=100,
            order_a_side="buy", order_a_price=150.0,
            order_b_side="sell", order_b_price=140.0,
        )
        assert oco.filled_order is None
        oco.process_fill("a", 150.0, 100)
        assert oco.filled_order == "a"


# ---------------------------------------------------------------------------
# OTOOrder Tests
# ---------------------------------------------------------------------------


class TestOTOOrder:
    def test_creation(self):
        oto = OTOOrder(
            symbol="AAPL", quantity=100,
            parent_side="buy", parent_price=150.0,
            child_side="sell", child_price=160.0,
        )
        assert oto.symbol == "AAPL"
        assert oto.quantity == 100
        assert oto.parent_side == "buy"
        assert oto.child_side == "sell"
        assert oto.status == "pending"

    def test_process_parent_fill_triggers_child(self):
        oto = OTOOrder(
            symbol="AAPL", quantity=100,
            parent_side="buy", parent_price=150.0,
            child_side="sell", child_price=160.0,
        )
        result = oto.process_parent_fill(150.0, 100)
        assert result is True
        assert oto.status == "active"

    def test_process_child_fill(self):
        oto = OTOOrder(
            symbol="AAPL", quantity=100,
            parent_side="buy", parent_price=150.0,
            child_side="sell", child_price=160.0,
        )
        oto.process_parent_fill(150.0, 100)
        oto.process_child_fill(160.0, 100)
        assert oto.status == "completed"

    def test_child_quantity_default(self):
        oto = OTOOrder(
            symbol="AAPL", quantity=100,
            parent_side="buy", parent_price=150.0,
            child_side="sell", child_price=160.0,
        )
        assert oto.child_quantity == 100

    def test_child_quantity_custom(self):
        oto = OTOOrder(
            symbol="AAPL", quantity=100,
            parent_side="buy", parent_price=150.0,
            child_side="sell", child_price=160.0,
            child_quantity=50,
        )
        assert oto.child_quantity == 50

    def test_cancel_before_parent_fill(self):
        oto = OTOOrder(
            symbol="AAPL", quantity=100,
            parent_side="buy", parent_price=150.0,
            child_side="sell", child_price=160.0,
        )
        result = oto.cancel()
        assert result is True
        assert oto.status == "cancelled"

    def test_cancel_after_parent_fill(self):
        oto = OTOOrder(
            symbol="AAPL", quantity=100,
            parent_side="buy", parent_price=150.0,
            child_side="sell", child_price=160.0,
        )
        oto.process_parent_fill(150.0, 100)
        result = oto.cancel()
        assert result is True

    def test_status_transitions(self):
        oto = OTOOrder(
            symbol="AAPL", quantity=100,
            parent_side="buy", parent_price=150.0,
            child_side="sell", child_price=160.0,
        )
        assert oto.status == "pending"
        oto.process_parent_fill(150.0, 100)
        assert oto.status == "active"
        oto.process_child_fill(160.0, 100)
        assert oto.status == "completed"

    def test_process_parent_fill_twice_returns_false(self):
        oto = OTOOrder(
            symbol="AAPL", quantity=100,
            parent_side="buy", parent_price=150.0,
            child_side="sell", child_price=160.0,
        )
        oto.process_parent_fill(150.0, 100)
        result = oto.process_parent_fill(155.0, 100)
        assert result is False

    def test_cancel_after_child_filled_returns_false(self):
        oto = OTOOrder(
            symbol="AAPL", quantity=100,
            parent_side="buy", parent_price=150.0,
            child_side="sell", child_price=160.0,
        )
        oto.process_parent_fill(150.0, 100)
        oto.process_child_fill(160.0, 100)
        result = oto.cancel()
        assert result is False


# ---------------------------------------------------------------------------
# IcebergOrder Tests
# ---------------------------------------------------------------------------


class TestIcebergOrder:
    def test_creation(self):
        iceberg = IcebergOrder(
            symbol="AAPL", total_quantity=1000, side="buy",
            visible_quantity=100, price=150.0,
        )
        assert iceberg.symbol == "AAPL"
        assert iceberg.total_quantity == 1000
        assert iceberg.side == "buy"
        assert iceberg.visible_quantity == 100
        assert iceberg.price == 150.0
        assert iceberg.status == "pending"
        assert iceberg.remaining_quantity == 1000

    def test_process_fill_reveals_next_slice(self):
        iceberg = IcebergOrder(
            symbol="AAPL", total_quantity=1000, side="buy",
            visible_quantity=100,
        )
        next_visible, is_complete = iceberg.process_fill(100, 150.0)
        assert iceberg.filled_quantity == 100
        assert iceberg.remaining_quantity == 900
        assert is_complete is False
        assert iceberg.slice_count == 1
        assert next_visible == 100

    def test_process_fill_complete(self):
        iceberg = IcebergOrder(
            symbol="AAPL", total_quantity=100, side="buy",
            visible_quantity=50,
        )
        iceberg.process_fill(50, 150.0)
        next_visible, is_complete = iceberg.process_fill(50, 151.0)
        assert is_complete is True
        assert iceberg.filled_quantity == 100
        assert iceberg.remaining_quantity == 0
        assert next_visible == 0.0
        assert iceberg.status == "completed"

    def test_get_next_slice(self):
        iceberg = IcebergOrder(
            symbol="AAPL", total_quantity=1000, side="buy",
            visible_quantity=100,
        )
        assert iceberg.get_next_slice() == 100
        iceberg.process_fill(100, 150.0)
        assert iceberg.get_next_slice() == 100

    def test_remaining_quantity_tracking(self):
        iceberg = IcebergOrder(
            symbol="AAPL", total_quantity=500, side="buy",
            visible_quantity=100,
        )
        assert iceberg.remaining_quantity == 500
        iceberg.process_fill(100, 150.0)
        assert iceberg.remaining_quantity == 400
        iceberg.process_fill(100, 151.0)
        assert iceberg.remaining_quantity == 300

    def test_filled_quantity_tracking(self):
        iceberg = IcebergOrder(
            symbol="AAPL", total_quantity=500, side="buy",
            visible_quantity=100,
        )
        assert iceberg.filled_quantity == 0
        iceberg.process_fill(100, 150.0)
        assert iceberg.filled_quantity == 100
        iceberg.process_fill(100, 151.0)
        assert iceberg.filled_quantity == 200

    def test_slice_count(self):
        iceberg = IcebergOrder(
            symbol="AAPL", total_quantity=300, side="buy",
            visible_quantity=100,
        )
        assert iceberg.slice_count == 0
        iceberg.process_fill(100, 150.0)
        assert iceberg.slice_count == 1
        iceberg.process_fill(100, 151.0)
        assert iceberg.slice_count == 2

    def test_fill_history(self):
        iceberg = IcebergOrder(
            symbol="AAPL", total_quantity=200, side="buy",
            visible_quantity=100,
        )
        iceberg.process_fill(100, 150.0)
        iceberg.process_fill(100, 151.0)
        history = iceberg.get_fill_history()
        assert len(history) == 2
        assert history[0]["quantity"] == 100
        assert history[0]["price"] == 150.0
        assert history[1]["quantity"] == 100
        assert history[1]["price"] == 151.0

    def test_cancel(self):
        iceberg = IcebergOrder(
            symbol="AAPL", total_quantity=1000, side="buy",
            visible_quantity=100,
        )
        assert iceberg.cancel() is True
        assert iceberg.status == "cancelled"

    def test_cancel_after_complete_returns_false(self):
        iceberg = IcebergOrder(
            symbol="AAPL", total_quantity=100, side="buy",
            visible_quantity=100,
        )
        iceberg.process_fill(100, 150.0)
        assert iceberg.cancel() is False

    def test_iceberg_with_price(self):
        iceberg = IcebergOrder(
            symbol="AAPL", total_quantity=1000, side="buy",
            visible_quantity=100, price=155.0,
        )
        assert iceberg.price == 155.0

    def test_small_total_single_slice(self):
        iceberg = IcebergOrder(
            symbol="AAPL", total_quantity=50, side="buy",
            visible_quantity=100,
        )
        next_visible, is_complete = iceberg.process_fill(50, 150.0)
        assert is_complete is True
        assert iceberg.filled_quantity == 50
        assert iceberg.slice_count == 1

    def test_partial_fill_less_than_visible(self):
        iceberg = IcebergOrder(
            symbol="AAPL", total_quantity=500, side="buy",
            visible_quantity=100,
        )
        next_visible, is_complete = iceberg.process_fill(50, 150.0)
        assert iceberg.filled_quantity == 50
        assert iceberg.remaining_quantity == 450
        assert is_complete is False


# ---------------------------------------------------------------------------
# AdvancedOrderState Tests
# ---------------------------------------------------------------------------


class TestAdvancedOrderState:
    def test_default_state(self):
        state = AdvancedOrderState()
        assert state.status == "pending"
        assert state.trigger_price is None
        assert state.fill_price is None
        assert state.fill_quantity == 0.0
        assert state.error_message is None

    def test_custom_state(self):
        state = AdvancedOrderState(
            status="filled",
            fill_price=150.0,
            fill_quantity=100.0,
        )
        assert state.status == "filled"
        assert state.fill_price == 150.0
        assert state.fill_quantity == 100.0
