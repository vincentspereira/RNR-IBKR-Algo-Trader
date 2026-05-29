"""Tests for core_trading.backtest.execution."""
from __future__ import annotations

import pandas as pd
import pytest

from core_trading.backtest.costs import get_cost_model
from core_trading.backtest.execution import Bar, ExecutionConfig, ExecutionSimulator
from core_trading.backtest.orders import Order, OrderStatus, OrderType, Side

TS = pd.Timestamp("2022-03-01", tz="UTC")


def _bar(o: float, h: float, low: float, c: float, v: float = 1e6, **kw: float) -> Bar:
    return Bar(TS, o, h, low, c, v, **kw)


@pytest.fixture
def sim() -> ExecutionSimulator:
    return ExecutionSimulator(get_cost_model("zero"))


class TestBar:
    def test_typical_and_ohlc(self) -> None:
        b = _bar(10, 12, 9, 11)
        assert b.typical_price == pytest.approx((12 + 9 + 11) / 3)
        assert b.ohlc_average == pytest.approx((10 + 12 + 9 + 11) / 4)

    def test_inconsistent_ohlc_rejected(self) -> None:
        with pytest.raises(ValueError, match="inconsistent OHLC"):
            _bar(10, 9, 8, 8)  # high < open


class TestMarket:
    def test_market_fills_at_open_by_default(self, sim: ExecutionSimulator) -> None:
        order = Order("1", "AAA", Side.BUY, 100)
        res = sim.execute(order, _bar(10, 12, 9, 11))
        assert res.status is OrderStatus.FILLED
        assert res.fill is not None
        assert res.fill.price == pytest.approx(10.0)

    def test_market_fill_at_close(self) -> None:
        sim = ExecutionSimulator(get_cost_model("zero"), ExecutionConfig(market_fill_price="close"))
        res = sim.execute(Order("1", "AAA", Side.BUY, 100), _bar(10, 12, 9, 11))
        assert res.fill is not None
        assert res.fill.price == pytest.approx(11.0)


class TestLimit:
    def test_buy_limit_fills_when_crossed(self, sim: ExecutionSimulator) -> None:
        order = Order("1", "AAA", Side.BUY, 100, OrderType.LIMIT, limit_price=9.5)
        res = sim.execute(order, _bar(10, 11, 9, 10))  # low 9 <= 9.5
        assert res.fill is not None
        assert res.fill.price == pytest.approx(9.5)  # capped at limit, open above

    def test_buy_limit_no_fill(self, sim: ExecutionSimulator) -> None:
        order = Order("1", "AAA", Side.BUY, 100, OrderType.LIMIT, limit_price=8.0)
        res = sim.execute(order, _bar(10, 11, 9, 10))  # low 9 > 8
        assert res.status is OrderStatus.PENDING
        assert res.fill is None

    def test_sell_limit_fills(self, sim: ExecutionSimulator) -> None:
        order = Order("1", "AAA", Side.SELL, 100, OrderType.LIMIT, limit_price=10.5)
        res = sim.execute(order, _bar(10, 11, 9, 10))  # high 11 >= 10.5
        assert res.fill is not None
        assert res.fill.price == pytest.approx(10.5)


class TestStop:
    def test_buy_stop_triggers_on_high(self, sim: ExecutionSimulator) -> None:
        order = Order("1", "AAA", Side.BUY, 100, OrderType.STOP, stop_price=10.5)
        res = sim.execute(order, _bar(10, 11, 9, 10))  # high 11 >= 10.5
        assert res.fill is not None
        assert res.fill.price == pytest.approx(10.5)

    def test_buy_stop_no_trigger(self, sim: ExecutionSimulator) -> None:
        order = Order("1", "AAA", Side.BUY, 100, OrderType.STOP, stop_price=12.0)
        res = sim.execute(order, _bar(10, 11, 9, 10))
        assert res.fill is None

    def test_sell_stop_triggers_on_low(self, sim: ExecutionSimulator) -> None:
        order = Order("1", "AAA", Side.SELL, 100, OrderType.STOP, stop_price=9.5)
        res = sim.execute(order, _bar(10, 11, 9, 10))  # low 9 <= 9.5
        assert res.fill is not None
        assert res.fill.price == pytest.approx(9.5)

    def test_gap_through_stop_fills_at_open(self, sim: ExecutionSimulator) -> None:
        order = Order("1", "AAA", Side.BUY, 100, OrderType.STOP, stop_price=10.5)
        res = sim.execute(order, _bar(11, 12, 10.6, 11.5))  # opens above stop
        assert res.fill is not None
        assert res.fill.price == pytest.approx(11.0)  # max(open, stop)


class TestStopLimit:
    def test_fills_within_limit(self, sim: ExecutionSimulator) -> None:
        order = Order(
            "1", "AAA", Side.BUY, 100, OrderType.STOP_LIMIT, limit_price=11.0, stop_price=10.5
        )
        res = sim.execute(order, _bar(10, 11, 9, 10.5))  # triggers, fill 10.5 <= 11
        assert res.fill is not None

    def test_no_fill_when_not_triggered(self, sim: ExecutionSimulator) -> None:
        order = Order(
            "1", "AAA", Side.BUY, 100, OrderType.STOP_LIMIT, limit_price=13.0, stop_price=12.0
        )
        assert sim.execute(order, _bar(10, 11, 9, 10)).fill is None  # high 11 < stop 12

    def test_sell_stop_limit_fills(self, sim: ExecutionSimulator) -> None:
        order = Order(
            "1", "AAA", Side.SELL, 100, OrderType.STOP_LIMIT, limit_price=9.0, stop_price=9.5
        )
        res = sim.execute(order, _bar(10, 11, 9, 9.4))  # low 9 <= stop 9.5, fill 9.5 >= limit 9
        assert res.fill is not None

    def test_no_fill_when_past_limit(self, sim: ExecutionSimulator) -> None:
        order = Order(
            "1", "AAA", Side.BUY, 100, OrderType.STOP_LIMIT, limit_price=10.6, stop_price=10.5
        )
        res = sim.execute(order, _bar(11, 12, 10.7, 11.5))  # gaps to 11 > limit 10.6
        assert res.fill is None


class TestCloseOrders:
    def test_moc_fills_at_close(self, sim: ExecutionSimulator) -> None:
        res = sim.execute(Order("1", "AAA", Side.BUY, 100, OrderType.MOC), _bar(10, 12, 9, 11))
        assert res.fill is not None
        assert res.fill.price == pytest.approx(11.0)

    def test_loc_respects_limit(self, sim: ExecutionSimulator) -> None:
        buy = Order("1", "AAA", Side.BUY, 100, OrderType.LOC, limit_price=10.0)
        assert sim.execute(buy, _bar(10, 12, 9, 11)).fill is None  # close 11 > 10
        assert sim.execute(buy, _bar(10, 12, 9, 9.5)).fill is not None  # close 9.5 <= 10


class TestAlgo:
    def test_twap_at_ohlc_average(self, sim: ExecutionSimulator) -> None:
        order = Order("1", "AAA", Side.BUY, 100, OrderType.TWAP, n_slices=4)
        res = sim.execute(order, _bar(10, 12, 9, 11))
        assert res.fill is not None
        assert res.fill.price == pytest.approx((10 + 12 + 9 + 11) / 4)

    def test_vwap_at_typical_price(self, sim: ExecutionSimulator) -> None:
        order = Order("1", "AAA", Side.SELL, 100, OrderType.VWAP, n_slices=4)
        res = sim.execute(order, _bar(10, 12, 9, 11))
        assert res.fill is not None
        assert res.fill.price == pytest.approx((12 + 9 + 11) / 3)


class TestPartialFills:
    def test_partial_when_order_exceeds_liquidity(self) -> None:
        sim = ExecutionSimulator(
            get_cost_model("zero"), ExecutionConfig(max_participation_rate=0.1)
        )
        order = Order("1", "AAA", Side.BUY, 1000)
        res = sim.execute(order, _bar(10, 11, 9, 10, v=5000))  # 10% of 5000 = 500
        assert res.status is OrderStatus.PARTIALLY_FILLED
        assert res.fill is not None
        assert res.fill.quantity == pytest.approx(500)
        assert res.fill.is_partial
        assert res.remaining_quantity == pytest.approx(500)

    def test_no_liquidity_no_fill(self) -> None:
        sim = ExecutionSimulator(
            get_cost_model("zero"), ExecutionConfig(max_participation_rate=0.1)
        )
        res = sim.execute(Order("1", "AAA", Side.BUY, 100), _bar(10, 11, 9, 10, v=0))
        assert res.status is OrderStatus.PENDING

    def test_full_fill_ignores_liquidity_when_disabled(self) -> None:
        sim = ExecutionSimulator(get_cost_model("zero"), ExecutionConfig(allow_partial_fills=False))
        res = sim.execute(Order("1", "AAA", Side.BUY, 10_000), _bar(10, 11, 9, 10, v=100))
        assert res.status is OrderStatus.FILLED
        assert res.fill is not None
        assert res.fill.quantity == pytest.approx(10_000)


class TestConfigValidation:
    def test_bad_participation(self) -> None:
        with pytest.raises(ValueError):
            ExecutionConfig(max_participation_rate=0)
        with pytest.raises(ValueError):
            ExecutionConfig(max_participation_rate=1.5)

    def test_bad_market_fill_price(self) -> None:
        with pytest.raises(ValueError):
            ExecutionConfig(market_fill_price="vwap")


class TestSellSideNoFill:
    def test_sell_limit_no_fill(self, sim: ExecutionSimulator) -> None:
        order = Order("1", "AAA", Side.SELL, 100, OrderType.LIMIT, limit_price=12.0)
        assert sim.execute(order, _bar(10, 11, 9, 10)).fill is None  # high 11 < 12

    def test_sell_stop_no_trigger(self, sim: ExecutionSimulator) -> None:
        order = Order("1", "AAA", Side.SELL, 100, OrderType.STOP, stop_price=8.0)
        assert sim.execute(order, _bar(10, 11, 9, 10)).fill is None  # low 9 > 8

    def test_sell_stop_limit_past_limit(self, sim: ExecutionSimulator) -> None:
        order = Order(
            "1", "AAA", Side.SELL, 100, OrderType.STOP_LIMIT, limit_price=9.4, stop_price=9.5
        )
        # gaps down: opens below limit so cannot sell at/above limit
        assert sim.execute(order, _bar(9.0, 9.3, 8.0, 8.5)).fill is None

    def test_loc_sell_no_fill(self, sim: ExecutionSimulator) -> None:
        order = Order("1", "AAA", Side.SELL, 100, OrderType.LOC, limit_price=12.0)
        assert sim.execute(order, _bar(10, 11, 9, 10)).fill is None  # close 10 < 12


class TestCostsApplied:
    def test_impact_moves_buy_price_up(self) -> None:
        sim = ExecutionSimulator(get_cost_model("ibkr"))
        order = Order("1", "AAA", Side.BUY, 10_000)
        res = sim.execute(order, _bar(50, 51, 49, 50, v=1e6, adv=1e6, volatility=0.02))
        assert res.fill is not None
        assert res.fill.price > 50.0
        assert res.fill.impact_cost > 0
        assert res.fill.commission > 0
