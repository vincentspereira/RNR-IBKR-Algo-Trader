"""Tests for core_trading.backtest.portfolio."""
from __future__ import annotations

import pandas as pd
import pytest

from core_trading.backtest.costs import BorrowModel, LotMethod
from core_trading.backtest.orders import Fill, Side
from core_trading.backtest.portfolio import Portfolio, Position

T0 = pd.Timestamp("2022-01-03", tz="UTC")
T1 = pd.Timestamp("2022-01-04", tz="UTC")
T2 = pd.Timestamp("2022-01-05", tz="UTC")


def _fill(side: Side, qty: float, price: float, ts: pd.Timestamp, **kw: float) -> Fill:
    return Fill("o", "AAA", side, qty, price, ts, **kw)


class TestPosition:
    def test_flat_defaults(self) -> None:
        p = Position("AAA")
        assert p.is_flat
        assert p.direction == 0
        assert p.avg_price == 0.0
        assert p.unrealised_pnl(100.0) == 0.0

    def test_long_unrealised(self) -> None:
        pf = Portfolio(100000)
        pf.apply_fill(_fill(Side.BUY, 100, 50.0, T0))
        pos = pf.position("AAA")
        assert pos.is_long
        assert pos.direction == 1
        assert pos.unrealised_pnl(55.0) == pytest.approx(500.0)

    def test_short_unrealised(self) -> None:
        pf = Portfolio(100000)
        pf.apply_fill(_fill(Side.SELL, 100, 50.0, T0))
        pos = pf.position("AAA")
        assert pos.is_short
        assert pos.direction == -1
        # short profits when price falls
        assert pos.unrealised_pnl(45.0) == pytest.approx(500.0)


class TestPortfolioBasics:
    def test_initial_cash(self) -> None:
        pf = Portfolio(100000)
        assert pf.cash == 100000
        assert pf.equity({}) == 100000

    def test_bad_initial_cash(self) -> None:
        with pytest.raises(ValueError):
            Portfolio(0)

    def test_buy_reduces_cash_and_opens_long(self) -> None:
        pf = Portfolio(100000)
        pf.apply_fill(_fill(Side.BUY, 100, 50.0, T0, commission=1.0))
        assert pf.cash == pytest.approx(100000 - 5000 - 1.0)
        pos = pf.position("AAA")
        assert pos.quantity == 100
        assert pos.avg_price == pytest.approx(50.0)
        assert pf.equity({"AAA": 50.0}) == pytest.approx(100000 - 1.0)


class TestRealisedPnl:
    def test_long_round_trip(self) -> None:
        pf = Portfolio(100000)
        pf.apply_fill(_fill(Side.BUY, 100, 50.0, T0))
        trades = pf.apply_fill(_fill(Side.SELL, 100, 60.0, T1))
        assert len(trades) == 1
        t = trades[0]
        assert t.direction == 1
        assert t.pnl == pytest.approx(1000.0)  # (60-50)*100
        assert pf.position("AAA").is_flat
        assert pf.realised_pnl == pytest.approx(1000.0)

    def test_short_round_trip(self) -> None:
        pf = Portfolio(100000)
        pf.apply_fill(_fill(Side.SELL, 100, 60.0, T0))
        assert pf.position("AAA").quantity == -100
        trades = pf.apply_fill(_fill(Side.BUY, 100, 50.0, T1))
        assert len(trades) == 1
        # short: entry 60, cover 50 -> profit (60-50)*100
        assert trades[0].direction == -1
        assert trades[0].pnl == pytest.approx(1000.0)

    def test_partial_close(self) -> None:
        pf = Portfolio(100000)
        pf.apply_fill(_fill(Side.BUY, 100, 50.0, T0))
        trades = pf.apply_fill(_fill(Side.SELL, 40, 55.0, T1))
        assert trades[0].quantity == pytest.approx(40)
        assert trades[0].pnl == pytest.approx(200.0)  # (55-50)*40
        assert pf.position("AAA").quantity == pytest.approx(60)

    def test_add_to_position_averages(self) -> None:
        pf = Portfolio(100000)
        pf.apply_fill(_fill(Side.BUY, 100, 10.0, T0))
        pf.apply_fill(_fill(Side.BUY, 100, 20.0, T1))
        assert pf.position("AAA").avg_price == pytest.approx(15.0)
        assert pf.position("AAA").quantity == 200

    def test_flip_long_to_short(self) -> None:
        pf = Portfolio(100000)
        pf.apply_fill(_fill(Side.BUY, 100, 50.0, T0))
        trades = pf.apply_fill(_fill(Side.SELL, 150, 60.0, T1))
        # closes 100 long (+1000 pnl), opens 50 short
        assert trades[0].quantity == pytest.approx(100)
        assert trades[0].pnl == pytest.approx(1000.0)
        pos = pf.position("AAA")
        assert pos.quantity == pytest.approx(-50)
        assert pos.avg_price == pytest.approx(60.0)

    def test_cost_apportioned_to_closed_fraction(self) -> None:
        pf = Portfolio(100000)
        pf.apply_fill(_fill(Side.BUY, 100, 50.0, T0))
        trades = pf.apply_fill(_fill(Side.SELL, 50, 60.0, T1, commission=10.0))
        # only the closing fill's cost (10) applies, fully (closed==fill qty)
        assert trades[0].costs == pytest.approx(10.0)
        assert trades[0].pnl == pytest.approx(500.0 - 10.0)


class TestExposureAndLeverage:
    def test_gross_net_exposure(self) -> None:
        pf = Portfolio(100000)
        pf.apply_fill(Fill("o", "AAA", Side.BUY, 100, 50.0, T0))
        pf.apply_fill(Fill("o", "BBB", Side.SELL, 100, 40.0, T0))
        prices = {"AAA": 50.0, "BBB": 40.0}
        assert pf.gross_exposure(prices) == pytest.approx(5000 + 4000)
        assert pf.net_exposure(prices) == pytest.approx(5000 - 4000)

    def test_leverage(self) -> None:
        pf = Portfolio(10000)
        pf.apply_fill(Fill("o", "AAA", Side.BUY, 1000, 50.0, T0))  # $50k on $10k
        lev = pf.leverage({"AAA": 50.0})
        assert lev == pytest.approx(50000 / pf.equity({"AAA": 50.0}))

    def test_leverage_infinite_when_wiped(self) -> None:
        pf = Portfolio(1000)
        # take cash deeply negative so equity <= 0
        pf.cash = -1.0
        assert pf.leverage({}) == float("inf")


class TestCarry:
    def test_borrow_cost_on_short(self) -> None:
        pf = Portfolio(100000, borrow_model=BorrowModel(default_annual_rate=0.0365))
        pf.apply_fill(_fill(Side.SELL, 100, 100.0, T0))  # short $10k
        charge = pf.accrue_carry({"AAA": 100.0}, days=1)
        assert charge == pytest.approx(10000 * 0.0365 / 365)
        assert pf.total_borrow_cost == pytest.approx(charge)

    def test_financing_on_margin_debit(self) -> None:
        pf = Portfolio(10000, borrow_model=BorrowModel(financing_annual_rate=0.0365))
        pf.apply_fill(_fill(Side.BUY, 1000, 50.0, T0))  # spends 50k -> cash negative
        assert pf.cash < 0
        charge = pf.accrue_carry({"AAA": 50.0}, days=1)
        assert charge > 0

    def test_no_carry_when_flat(self) -> None:
        pf = Portfolio(100000, borrow_model=BorrowModel(default_annual_rate=0.05))
        assert pf.accrue_carry({"AAA": 100.0}) == 0.0


class TestRecording:
    def test_equity_series(self) -> None:
        pf = Portfolio(100000)
        pf.apply_fill(_fill(Side.BUY, 100, 50.0, T0))
        pf.record(T0, {"AAA": 50.0})
        pf.record(T1, {"AAA": 55.0})
        s = pf.equity_series()
        assert list(s.index) == [T0, T1]
        assert s.iloc[1] == pytest.approx(pf.cash + 100 * 55.0)

    def test_empty_equity_series(self) -> None:
        assert Portfolio(100000).equity_series().empty

    def test_position_history_records_open_positions(self) -> None:
        pf = Portfolio(100000)
        pf.apply_fill(_fill(Side.BUY, 100, 50.0, T0))
        pf.record(T0, {"AAA": 50.0})
        assert pf.position_history[0][1] == "AAA"
        assert pf.position_history[0][2] == 100

    def test_lot_method_propagates(self) -> None:
        pf = Portfolio(100000, lot_method=LotMethod.LIFO)
        pf.apply_fill(_fill(Side.BUY, 100, 10.0, T0))
        assert pf.position("AAA").lot_method is LotMethod.LIFO
