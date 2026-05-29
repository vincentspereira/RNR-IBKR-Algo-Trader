"""Tests for core_trading.backtest.costs."""
from __future__ import annotations

import math

import pytest

from core_trading.backtest.costs import (
    AlmgrenChrissImpact,
    BorrowModel,
    CommissionSchedule,
    CostModel,
    LotMethod,
    RegulatoryFees,
    SpreadVolumeSlippage,
    TaxLotBook,
    available_cost_models,
    get_cost_model,
    register_cost_model,
)
from core_trading.backtest.orders import Side


class TestCommissionSchedule:
    def test_per_share_with_minimum(self) -> None:
        sched = CommissionSchedule(per_share=0.005, minimum=1.0)
        assert sched.compute(100, 50.0) == pytest.approx(1.0)  # 0.50 -> floored to 1.0
        assert sched.compute(1000, 50.0) == pytest.approx(5.0)

    def test_percent_and_cap(self) -> None:
        sched = CommissionSchedule(per_share=0.0035, minimum=0.35, max_pct_of_notional=0.01)
        # 1 share at $1: 0.0035 -> min 0.35, but cap 1% of $1 = $0.01
        assert sched.compute(1, 1.0) == pytest.approx(0.01)

    def test_per_trade(self) -> None:
        assert CommissionSchedule(per_trade=2.0).compute(10, 5.0) == pytest.approx(2.0)

    def test_negative_rejected(self) -> None:
        with pytest.raises(ValueError):
            CommissionSchedule(per_share=-1)

    def test_bad_cap(self) -> None:
        with pytest.raises(ValueError):
            CommissionSchedule(max_pct_of_notional=0)


class TestRegulatoryFees:
    def test_buys_are_free(self) -> None:
        fees = RegulatoryFees(sec_fee_per_dollar=8e-6, finra_taf_per_share=0.000166)
        assert fees.compute(Side.BUY, 100, 10000) == 0.0

    def test_sell_charges_sec_and_taf(self) -> None:
        fees = RegulatoryFees(sec_fee_per_dollar=8e-6, finra_taf_per_share=0.000166)
        cost = fees.compute(Side.SELL, 100, 10000)
        assert cost == pytest.approx(8e-6 * 10000 + 0.000166 * 100)

    def test_taf_cap(self) -> None:
        fees = RegulatoryFees(finra_taf_per_share=1.0, finra_taf_cap=5.0)
        assert fees.compute(Side.SELL, 1000, 1000) == pytest.approx(5.0)

    def test_negative_rejected(self) -> None:
        with pytest.raises(ValueError):
            RegulatoryFees(sec_fee_per_dollar=-1)


class TestSlippage:
    def test_spread_only_when_no_volume(self) -> None:
        slip = SpreadVolumeSlippage(half_spread_bps=2.0, volume_coef_bps=10.0)
        # bar_volume 0 -> participation term 0
        cost = slip.cost_per_share(100.0, 50, 0.0)
        assert cost == pytest.approx(100.0 * 2.0 / 1e4)

    def test_participation_term(self) -> None:
        slip = SpreadVolumeSlippage(half_spread_bps=0.0, volume_coef_bps=100.0)
        # participation 0.1 -> 10 bps
        cost = slip.cost_per_share(100.0, 100, 1000.0)
        assert cost == pytest.approx(100.0 * (100.0 * 0.1) / 1e4)

    def test_negative_rejected(self) -> None:
        with pytest.raises(ValueError):
            SpreadVolumeSlippage(half_spread_bps=-1)


class TestImpact:
    def test_square_root_law(self) -> None:
        imp = AlmgrenChrissImpact(eta=0.5)
        cost = imp.cost_per_share(100.0, 1000, adv=10000, volatility=0.02)
        expected = 0.5 * 0.02 * 100.0 * math.sqrt(0.1)
        assert cost == pytest.approx(expected)

    def test_zero_adv_no_impact(self) -> None:
        assert AlmgrenChrissImpact(0.5).cost_per_share(100, 10, 0, 0.02) == 0.0

    def test_zero_eta_disables(self) -> None:
        assert AlmgrenChrissImpact(0.0).cost_per_share(100, 10, 1000, 0.02) == 0.0

    def test_negative_rejected(self) -> None:
        with pytest.raises(ValueError):
            AlmgrenChrissImpact(-1)


class TestBorrowModel:
    def test_default_and_per_symbol(self) -> None:
        b = BorrowModel(default_annual_rate=0.005, per_symbol={"GME": 0.5})
        assert b.annual_rate("AAPL") == 0.005
        assert b.annual_rate("GME") == 0.5

    def test_daily_borrow(self) -> None:
        b = BorrowModel(default_annual_rate=0.0365)
        # 0.0365/365 = 1e-4 per day
        assert b.daily_borrow_cost("X", 100000, 1) == pytest.approx(10.0)

    def test_no_cost_for_zero_value(self) -> None:
        assert BorrowModel().daily_borrow_cost("X", 0) == 0.0

    def test_financing(self) -> None:
        b = BorrowModel(financing_annual_rate=0.0365)
        assert b.daily_financing_cost(100000, 1) == pytest.approx(10.0)
        assert b.daily_financing_cost(0) == 0.0

    def test_negative_rejected(self) -> None:
        with pytest.raises(ValueError):
            BorrowModel(default_annual_rate=-1)


class TestCostModel:
    def test_buy_fills_above_reference(self) -> None:
        cm = CostModel(
            slippage=SpreadVolumeSlippage(half_spread_bps=10.0, volume_coef_bps=0.0),
            impact=AlmgrenChrissImpact(0.0),
        )
        bd = cm.price_with_costs(Side.BUY, 100, 100.0)
        assert bd.fill_price > 100.0
        assert bd.slippage_cost == pytest.approx(100.0 * 10.0 / 1e4 * 100)

    def test_sell_fills_below_reference(self) -> None:
        cm = CostModel(slippage=SpreadVolumeSlippage(half_spread_bps=10.0, volume_coef_bps=0.0))
        bd = cm.price_with_costs(Side.SELL, 100, 100.0)
        assert bd.fill_price < 100.0

    def test_breakdown_totals(self) -> None:
        cm = get_cost_model("ibkr")
        bd = cm.price_with_costs(Side.SELL, 100, 50.0, bar_volume=1e6, adv=1e6, volatility=0.02)
        assert bd.total_cost == pytest.approx(bd.explicit_cost + bd.implicit_cost)
        assert bd.explicit_cost == pytest.approx(bd.commission + bd.fees)

    def test_bad_reference(self) -> None:
        with pytest.raises(ValueError):
            CostModel().price_with_costs(Side.BUY, 1, 0.0)

    def test_bad_quantity(self) -> None:
        with pytest.raises(ValueError):
            CostModel().price_with_costs(Side.BUY, 0, 10.0)

    def test_zero_model_is_frictionless(self) -> None:
        bd = get_cost_model("zero").price_with_costs(
            Side.BUY, 100, 50.0, bar_volume=1e6, adv=1e6, volatility=0.02
        )
        assert bd.total_cost == pytest.approx(0.0)
        assert bd.fill_price == pytest.approx(50.0)


class TestRegistry:
    def test_available(self) -> None:
        names = available_cost_models()
        assert {"ibkr", "ibkr_fixed", "zero", "commission_free"} <= set(names)

    def test_unknown_raises(self) -> None:
        with pytest.raises(KeyError):
            get_cost_model("nope")

    def test_register(self) -> None:
        register_cost_model("custom_test", lambda: CostModel())
        assert isinstance(get_cost_model("custom_test"), CostModel)

    def test_ibkr_fixed(self) -> None:
        cm = get_cost_model("ibkr_fixed")
        bd = cm.price_with_costs(Side.BUY, 1000, 50.0)
        assert bd.commission == pytest.approx(5.0)  # 0.005 * 1000

    def test_commission_free_has_fees_on_sell(self) -> None:
        cm = get_cost_model("commission_free")
        bd = cm.price_with_costs(Side.SELL, 100, 50.0)
        assert bd.commission == 0.0
        assert bd.fees > 0.0


class TestTaxLotBook:
    def test_fifo(self) -> None:
        book = TaxLotBook(LotMethod.FIFO)
        book.add(100, 10.0)
        book.add(100, 20.0)
        realised = book.reduce(150, 25.0)
        # FIFO: 100 @10 then 50 @20
        assert realised[0].cost_basis == pytest.approx(1000.0)
        assert realised[1].cost_basis == pytest.approx(1000.0)
        assert book.open_quantity == pytest.approx(50.0)

    def test_lifo(self) -> None:
        book = TaxLotBook(LotMethod.LIFO)
        book.add(100, 10.0)
        book.add(100, 20.0)
        realised = book.reduce(50, 25.0)
        assert realised[0].cost_basis == pytest.approx(50 * 20.0)

    def test_hifo(self) -> None:
        book = TaxLotBook(LotMethod.HIFO)
        book.add(100, 10.0)
        book.add(100, 30.0)
        book.add(100, 20.0)
        realised = book.reduce(50, 25.0)
        # highest cost (30) first
        assert realised[0].cost_basis == pytest.approx(50 * 30.0)

    def test_realised_pnl(self) -> None:
        book = TaxLotBook()
        book.add(100, 10.0)
        realised = book.reduce(100, 15.0)
        assert realised[0].pnl == pytest.approx(500.0)

    def test_overclose_rejected(self) -> None:
        book = TaxLotBook()
        book.add(10, 10.0)
        with pytest.raises(ValueError, match="cannot close"):
            book.reduce(20, 10.0)

    def test_bad_add(self) -> None:
        with pytest.raises(ValueError):
            TaxLotBook().add(-1, 10.0)
        with pytest.raises(ValueError):
            TaxLotBook().add(1, -10.0)

    def test_bad_reduce(self) -> None:
        with pytest.raises(ValueError):
            TaxLotBook().reduce(0, 10.0)

    def test_len(self) -> None:
        book = TaxLotBook()
        book.add(1, 1.0)
        book.add(1, 2.0)
        assert len(book) == 2
