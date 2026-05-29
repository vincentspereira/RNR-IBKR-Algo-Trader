"""Tests for core_trading.backtest.orders."""
from __future__ import annotations

import pandas as pd
import pytest

from core_trading.backtest.orders import (
    Fill,
    LiquidityFlag,
    Order,
    OrderType,
    Side,
    TimeInForce,
    Trade,
)

TS = pd.Timestamp("2022-01-03", tz="UTC")


class TestSide:
    def test_sign(self) -> None:
        assert Side.BUY.sign == 1
        assert Side.SELL.sign == -1

    def test_opposite(self) -> None:
        assert Side.BUY.opposite is Side.SELL
        assert Side.SELL.opposite is Side.BUY


class TestOrderValidation:
    def test_market_order_minimal(self) -> None:
        o = Order("1", "AAPL", Side.BUY, 100)
        assert o.order_type is OrderType.MARKET
        assert o.signed_quantity == 100
        assert not o.is_algo

    def test_negative_quantity_rejected(self) -> None:
        with pytest.raises(ValueError, match="quantity must be > 0"):
            Order("1", "AAPL", Side.BUY, -5)

    def test_limit_requires_price(self) -> None:
        with pytest.raises(ValueError, match="requires a limit_price"):
            Order("1", "AAPL", Side.BUY, 1, OrderType.LIMIT)

    def test_stop_requires_stop_price(self) -> None:
        with pytest.raises(ValueError, match="requires a stop_price"):
            Order("1", "AAPL", Side.BUY, 1, OrderType.STOP)

    def test_stop_limit_requires_both(self) -> None:
        with pytest.raises(ValueError, match="requires a limit_price"):
            Order("1", "AAPL", Side.BUY, 1, OrderType.STOP_LIMIT, stop_price=10)

    def test_negative_limit_rejected(self) -> None:
        with pytest.raises(ValueError, match="limit_price must be > 0"):
            Order("1", "AAPL", Side.BUY, 1, OrderType.LIMIT, limit_price=-1)

    def test_negative_stop_rejected(self) -> None:
        with pytest.raises(ValueError, match="stop_price must be > 0"):
            Order("1", "AAPL", Side.SELL, 1, OrderType.STOP, stop_price=-1)

    def test_algo_needs_slices(self) -> None:
        with pytest.raises(ValueError, match="n_slices"):
            Order("1", "AAPL", Side.BUY, 100, OrderType.TWAP, n_slices=0)

    def test_algo_flag(self) -> None:
        assert Order("1", "AAPL", Side.BUY, 100, OrderType.VWAP, n_slices=5).is_algo
        assert Order("1", "AAPL", Side.BUY, 100, OrderType.TWAP, n_slices=3).is_algo

    def test_signed_quantity_sell(self) -> None:
        assert Order("1", "AAPL", Side.SELL, 50).signed_quantity == -50


class TestFill:
    def test_cash_flow_buy_is_negative(self) -> None:
        f = Fill("1", "AAPL", Side.BUY, 100, 10.0, TS, commission=1.0)
        # spend 100*10 + 1 commission
        assert f.cash_flow == pytest.approx(-1001.0)
        assert f.gross_value == pytest.approx(1000.0)
        assert f.total_cost == pytest.approx(1.0)

    def test_cash_flow_sell_is_positive(self) -> None:
        f = Fill("1", "AAPL", Side.SELL, 100, 10.0, TS, commission=1.0, fees=0.5)
        # receive 1000 minus 1.5 costs
        assert f.cash_flow == pytest.approx(998.5)
        assert f.signed_quantity == -100

    def test_invalid_quantity(self) -> None:
        with pytest.raises(ValueError, match="quantity must be > 0"):
            Fill("1", "AAPL", Side.BUY, 0, 10.0, TS)

    def test_invalid_price(self) -> None:
        with pytest.raises(ValueError, match="price must be > 0"):
            Fill("1", "AAPL", Side.BUY, 1, 0.0, TS)

    def test_liquidity_default_taker(self) -> None:
        assert Fill("1", "AAPL", Side.BUY, 1, 10.0, TS).liquidity is LiquidityFlag.TAKER


class TestTrade:
    def test_win_and_return(self) -> None:
        t = Trade("AAPL", 1, 100, TS, TS, 10.0, 12.0, pnl=200.0)
        assert t.is_win
        assert t.return_pct == pytest.approx(200.0 / 1000.0)

    def test_loss(self) -> None:
        t = Trade("AAPL", -1, 100, TS, TS, 10.0, 12.0, pnl=-200.0, costs=5.0)
        assert not t.is_win
        assert t.gross_pnl == pytest.approx(-195.0)

    def test_zero_notional_return(self) -> None:
        t = Trade("AAPL", 1, 100, TS, TS, 0.0, 0.0, pnl=0.0)
        assert t.return_pct == 0.0

    def test_bad_direction(self) -> None:
        with pytest.raises(ValueError, match="direction must be"):
            Trade("AAPL", 0, 100, TS, TS, 10.0, 12.0, pnl=0.0)

    def test_bad_quantity(self) -> None:
        with pytest.raises(ValueError, match="quantity must be > 0"):
            Trade("AAPL", 1, 0, TS, TS, 10.0, 12.0, pnl=0.0)


def test_time_in_force_values() -> None:
    assert TimeInForce.DAY.value == "day"
    assert {t.value for t in TimeInForce} == {
        "day",
        "good_till_cancel",
        "immediate_or_cancel",
        "fill_or_kill",
    }
