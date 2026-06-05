"""Tests for core_trading/ops/reconciliation.py (Phase 12.5 / 12.6).

Coverage targets:
- ReconciliationConfig: defaults, validation, frozen
- reconcile_positions: exact match, tolerance, mismatch, one-sided symbols
- reconcile_fills: order_id match, greedy match, unmatched, price bps
- reconcile_cash: clean, absolute tol, relative tol, mismatch
- build_reconciliation_report: CLEAN verdict, MISMATCH verdict, all_incidents
- WashSale: basic flag, 30-day window edge, partial replacement, pre-sale buy,
  no flag outside window, zero-loss sale skipped, multiple buys, all consumed
- render_reconciliation_report: ASCII-only, section presence, None sections
- _build_demo_data: smoke test
- main CLI: --demo path, --output path, error on missing --demo
"""
from __future__ import annotations

import dataclasses
import os
from datetime import date
from typing import Any

import pytest

from core_trading.ops.reconciliation import (
    BuyEvent,
    CashReconciliationResult,
    FillReconciliationResult,
    PositionReconciliationResult,
    ReconciliationConfig,
    ReconciliationReport,
    ReconciliationStatus,
    SaleEvent,
    _build_demo_data,
    _fmt_float,
    _fmt_opt_float,
    build_reconciliation_report,
    flag_wash_sales,
    main,
    reconcile_cash,
    reconcile_fills,
    reconcile_positions,
    render_reconciliation_report,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_ascii(text: str) -> bool:
    return all(ord(ch) < 128 for ch in text)


def _make_fill(
    symbol: str = "AAPL",
    side: str = "BUY",
    quantity: float = 10.0,
    price: float = 100.0,
    order_id: str | None = None,
) -> dict[str, Any]:
    d: dict[str, Any] = {
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "price": price,
    }
    if order_id is not None:
        d["order_id"] = order_id
    return d


# ---------------------------------------------------------------------------
# ReconciliationConfig tests
# ---------------------------------------------------------------------------


class TestReconciliationConfig:
    def test_defaults(self) -> None:
        cfg = ReconciliationConfig()
        assert cfg.position_qty_tol == 0.0
        assert cfg.fill_price_bps_tol == 0.5
        assert cfg.cash_abs_tol == 0.01
        assert cfg.cash_rel_tol == 1e-5
        assert cfg.generated_at is None
        assert cfg.bps_scale == 10_000.0

    def test_frozen(self) -> None:
        cfg = ReconciliationConfig()
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            cfg.position_qty_tol = 1.0  # type: ignore[misc]

    def test_negative_position_qty_tol_raises(self) -> None:
        with pytest.raises(ValueError, match="position_qty_tol"):
            ReconciliationConfig(position_qty_tol=-0.1)

    def test_negative_fill_price_bps_tol_raises(self) -> None:
        with pytest.raises(ValueError, match="fill_price_bps_tol"):
            ReconciliationConfig(fill_price_bps_tol=-1.0)

    def test_negative_cash_abs_tol_raises(self) -> None:
        with pytest.raises(ValueError, match="cash_abs_tol"):
            ReconciliationConfig(cash_abs_tol=-0.01)

    def test_negative_cash_rel_tol_raises(self) -> None:
        with pytest.raises(ValueError, match="cash_rel_tol"):
            ReconciliationConfig(cash_rel_tol=-1e-5)

    def test_zero_bps_scale_raises(self) -> None:
        with pytest.raises(ValueError, match="bps_scale"):
            ReconciliationConfig(bps_scale=0.0)

    def test_negative_bps_scale_raises(self) -> None:
        with pytest.raises(ValueError, match="bps_scale"):
            ReconciliationConfig(bps_scale=-1.0)

    def test_custom_values_accepted(self) -> None:
        cfg = ReconciliationConfig(
            position_qty_tol=0.5,
            fill_price_bps_tol=2.0,
            cash_abs_tol=5.0,
            cash_rel_tol=0.001,
            generated_at="2026-06-05T16:00:00Z",
            bps_scale=10_000.0,
        )
        assert cfg.position_qty_tol == 0.5
        assert cfg.fill_price_bps_tol == 2.0
        assert cfg.generated_at == "2026-06-05T16:00:00Z"


# ---------------------------------------------------------------------------
# Position reconciliation tests
# ---------------------------------------------------------------------------


class TestReconcilePositions:
    def test_exact_match_clean(self) -> None:
        result = reconcile_positions(
            {"AAPL": 100.0, "MSFT": 50.0},
            {"AAPL": 100.0, "MSFT": 50.0},
        )
        assert result.clean is True
        assert result.n_matched == 2
        assert result.n_mismatch == 0
        assert result.n_internal_only == 0
        assert result.n_broker_only == 0
        assert result.incidents == []

    def test_mismatch_detected(self) -> None:
        result = reconcile_positions(
            {"AAPL": 100.0},
            {"AAPL": 95.0},
        )
        assert result.clean is False
        assert result.n_mismatch == 1
        assert len(result.incidents) == 1
        assert "position mismatch AAPL" in result.incidents[0]
        assert "-5.0" in result.incidents[0] or "-5" in result.incidents[0]

    def test_internal_only_symbol(self) -> None:
        result = reconcile_positions(
            {"AAPL": 100.0, "GLD": 30.0},
            {"AAPL": 100.0},
        )
        assert result.n_internal_only == 1
        assert result.clean is False
        inc = " ".join(result.incidents)
        assert "internal-only" in inc
        assert "GLD" in inc

    def test_broker_only_symbol(self) -> None:
        result = reconcile_positions(
            {"AAPL": 100.0},
            {"AAPL": 100.0, "SPY": 10.0},
        )
        assert result.n_broker_only == 1
        assert result.clean is False
        inc = " ".join(result.incidents)
        assert "broker-only" in inc
        assert "SPY" in inc

    def test_quantity_tolerance_zero_no_match(self) -> None:
        result = reconcile_positions(
            {"AAPL": 100.0},
            {"AAPL": 100.1},
            config=ReconciliationConfig(position_qty_tol=0.0),
        )
        assert result.n_mismatch == 1

    def test_quantity_tolerance_covers_diff(self) -> None:
        result = reconcile_positions(
            {"AAPL": 100.0},
            {"AAPL": 100.1},
            config=ReconciliationConfig(position_qty_tol=0.5),
        )
        assert result.n_matched == 1
        assert result.clean is True
        assert result.incidents == []

    def test_run_date_in_incidents(self) -> None:
        result = reconcile_positions(
            {"AAPL": 100.0},
            {"AAPL": 90.0},
            run_date="2026-06-05",
        )
        assert result.incidents[0].startswith("2026-06-05:")

    def test_empty_both_sides(self) -> None:
        result = reconcile_positions({}, {})
        assert result.clean is True
        assert result.n_matched == 0
        assert result.records == []

    def test_records_include_diff_field(self) -> None:
        result = reconcile_positions({"AAPL": 100.0}, {"AAPL": 105.0})
        rec = result.records[0]
        assert rec.diff == pytest.approx(5.0)
        assert rec.matched is False

    def test_one_sided_records_have_none_diff(self) -> None:
        result = reconcile_positions({"AAPL": 100.0}, {})
        rec = result.records[0]
        assert rec.diff is None
        assert rec.broker_qty is None
        assert rec.internal_qty == 100.0

    def test_symbols_sorted_in_records(self) -> None:
        result = reconcile_positions(
            {"ZZZ": 1.0, "AAA": 2.0},
            {"ZZZ": 1.0, "AAA": 2.0},
        )
        assert [r.symbol for r in result.records] == ["AAA", "ZZZ"]

    def test_multiple_mismatches_and_one_sided(self) -> None:
        result = reconcile_positions(
            {"A": 10.0, "B": 20.0, "C": 5.0},
            {"A": 12.0, "B": 20.0, "D": 7.0},
        )
        assert result.n_mismatch == 1   # A
        assert result.n_matched == 1    # B
        assert result.n_internal_only == 1  # C
        assert result.n_broker_only == 1    # D
        assert result.clean is False


# ---------------------------------------------------------------------------
# Fill reconciliation tests
# ---------------------------------------------------------------------------


class TestReconcileFills:
    def test_order_id_match_clean(self) -> None:
        inf = [_make_fill(order_id="ORD-1", price=100.0)]
        bkf = [_make_fill(order_id="ORD-1", price=100.01)]
        cfg = ReconciliationConfig(fill_price_bps_tol=2.0)
        result = reconcile_fills(inf, bkf, config=cfg)
        assert result.n_matched == 1
        assert result.n_unmatched_internal == 0
        assert result.n_unmatched_broker == 0
        assert result.n_price_discrepancy == 0
        assert result.clean is True
        assert result.matches[0].match_key == "order_id"

    def test_greedy_match_by_sym_side_qty(self) -> None:
        inf = [_make_fill("MSFT", "SELL", 5.0, 415.0)]
        bkf = [_make_fill("MSFT", "SELL", 5.0, 415.02)]
        cfg = ReconciliationConfig(fill_price_bps_tol=2.0)
        result = reconcile_fills(inf, bkf, config=cfg)
        assert result.n_matched == 1
        assert result.matches[0].match_key == "greedy"
        assert result.clean is True

    def test_price_discrepancy_flagged(self) -> None:
        # 100 bps discrepancy (price 101 vs 100 = 1% = 100 bps)
        inf = [_make_fill(order_id="ORD-2", price=100.0)]
        bkf = [_make_fill(order_id="ORD-2", price=101.0)]
        cfg = ReconciliationConfig(fill_price_bps_tol=0.5)
        result = reconcile_fills(inf, bkf, config=cfg)
        assert result.n_matched == 1
        assert result.n_price_discrepancy == 1
        assert result.clean is False
        inc_text = " ".join(result.incidents)
        assert "price discrepancy" in inc_text

    def test_unmatched_internal(self) -> None:
        inf = [_make_fill("GLD", "BUY", 10.0, 190.0)]
        bkf: list[dict[str, Any]] = []
        result = reconcile_fills(inf, bkf)
        assert result.n_unmatched_internal == 1
        assert result.clean is False
        assert any("unmatched internal" in i for i in result.incidents)

    def test_unmatched_broker(self) -> None:
        inf: list[dict[str, Any]] = []
        bkf = [_make_fill("QQQ", "SELL", 3.0, 450.0)]
        result = reconcile_fills(inf, bkf)
        assert result.n_unmatched_broker == 1
        assert result.clean is False
        assert any("unmatched broker" in i for i in result.incidents)

    def test_empty_both_sides_clean(self) -> None:
        result = reconcile_fills([], [])
        assert result.clean is True
        assert result.n_matched == 0

    def test_order_id_takes_priority_over_greedy(self) -> None:
        # Two fills with same symbol/side/qty but different order_ids
        inf = [
            _make_fill("AAPL", "BUY", 10.0, 182.0, order_id="ORD-A"),
            _make_fill("AAPL", "BUY", 10.0, 182.0, order_id="ORD-B"),
        ]
        bkf = [
            _make_fill("AAPL", "BUY", 10.0, 182.1, order_id="ORD-A"),
            _make_fill("AAPL", "BUY", 10.0, 182.2, order_id="ORD-B"),
        ]
        cfg = ReconciliationConfig(fill_price_bps_tol=10.0)
        result = reconcile_fills(inf, bkf, config=cfg)
        assert result.n_matched == 2
        order_id_matches = [m for m in result.matches if m.match_key == "order_id"]
        assert len(order_id_matches) == 2

    def test_run_date_in_incidents(self) -> None:
        inf = [_make_fill("AAPL", "BUY", 10.0, 100.0)]
        bkf: list[dict[str, Any]] = []
        result = reconcile_fills(inf, bkf, run_date="2026-06-05")
        assert result.incidents[0].startswith("2026-06-05:")

    def test_multiple_fills_partial_match(self) -> None:
        inf = [
            _make_fill("AAPL", "BUY", 10.0, 182.0, order_id="X1"),
            _make_fill("MSFT", "SELL", 5.0, 415.0),  # greedy
            _make_fill("GLD", "BUY", 3.0, 190.0),     # no match
        ]
        bkf = [
            _make_fill("AAPL", "BUY", 10.0, 182.05, order_id="X1"),
            _make_fill("MSFT", "SELL", 5.0, 415.10),  # greedy
            _make_fill("QQQ", "BUY", 2.0, 450.0),     # unmatched broker
        ]
        cfg = ReconciliationConfig(fill_price_bps_tol=5.0)
        result = reconcile_fills(inf, bkf, config=cfg)
        assert result.n_matched == 2
        assert result.n_unmatched_internal == 1
        assert result.n_unmatched_broker == 1
        assert result.clean is False

    def test_price_bps_boundary_exact(self) -> None:
        # 0.5 bps tolerance; diff exactly 0.5 bps should pass
        internal_price = 100.0
        broker_price = 100.0 + (0.5 / 10_000) * 100.0  # exactly 0.5 bps
        inf = [_make_fill(order_id="OID", price=internal_price)]
        bkf = [_make_fill(order_id="OID", price=broker_price)]
        cfg = ReconciliationConfig(fill_price_bps_tol=0.5)
        result = reconcile_fills(inf, bkf, config=cfg)
        assert result.n_price_discrepancy == 0

    def test_fills_without_price_no_discrepancy(self) -> None:
        # Fills without price key should not trigger discrepancy
        inf = [{"symbol": "AAPL", "side": "BUY", "quantity": 10.0}]
        bkf = [{"symbol": "AAPL", "side": "BUY", "quantity": 10.0}]
        result = reconcile_fills(inf, bkf)
        assert result.n_price_discrepancy == 0
        assert result.n_matched == 1


# ---------------------------------------------------------------------------
# Cash reconciliation tests
# ---------------------------------------------------------------------------


class TestReconcileCash:
    def test_exact_match_clean(self) -> None:
        result = reconcile_cash(50_000.0, 50_000.0)
        assert result.clean is True
        assert result.diff == pytest.approx(0.0)
        assert result.incidents == []

    def test_within_abs_tolerance(self) -> None:
        result = reconcile_cash(50_000.0, 50_000.005)
        assert result.clean is True

    def test_outside_abs_tolerance(self) -> None:
        # diff = 0.05, abs_tol = 0.01, rel_tol = 0 -> mismatch
        cfg = ReconciliationConfig(cash_abs_tol=0.01, cash_rel_tol=0.0)
        result = reconcile_cash(50_000.0, 50_000.05, config=cfg)
        assert result.clean is False
        assert len(result.incidents) == 1
        assert "cash mismatch" in result.incidents[0]

    def test_within_rel_tolerance(self) -> None:
        # 1e-6 relative diff, rel tol = 1e-5
        cfg = ReconciliationConfig(cash_abs_tol=0.0, cash_rel_tol=1e-5)
        result = reconcile_cash(100_000.0, 100_000.1, config=cfg)
        # diff_rel = 0.1 / 100_000 = 1e-6, tol = 1e-5 * 100_000 = 1
        assert result.clean is True

    def test_diff_and_diff_abs_correct(self) -> None:
        result = reconcile_cash(50_000.0, 49_750.0)
        assert result.diff == pytest.approx(-250.0)
        assert result.diff_abs == pytest.approx(250.0)

    def test_diff_rel_correct(self) -> None:
        result = reconcile_cash(100.0, 101.0)
        # diff_rel = 1/101 ~= 0.0099
        assert result.diff_rel == pytest.approx(1.0 / 101.0, rel=1e-4)

    def test_zero_cash_both_sides(self) -> None:
        result = reconcile_cash(0.0, 0.0)
        assert result.clean is True
        assert result.diff_rel == 0.0

    def test_run_date_in_incident(self) -> None:
        result = reconcile_cash(100.0, 200.0, run_date="2026-06-05")
        assert result.incidents[0].startswith("2026-06-05:")

    def test_negative_cash_handled(self) -> None:
        # Negative cash can occur with margin; should still reconcile
        result = reconcile_cash(-5_000.0, -5_000.0)
        assert result.clean is True

    def test_large_discrepancy_mismatch(self) -> None:
        result = reconcile_cash(50_000.0, 49_000.0)
        assert result.clean is False
        assert result.diff == pytest.approx(-1_000.0)


# ---------------------------------------------------------------------------
# build_reconciliation_report tests
# ---------------------------------------------------------------------------


class TestBuildReconciliationReport:
    def _clean_position(self) -> PositionReconciliationResult:
        return reconcile_positions({"AAPL": 100.0}, {"AAPL": 100.0})

    def _clean_fills(self) -> FillReconciliationResult:
        return reconcile_fills(
            [_make_fill(order_id="O1")],
            [_make_fill(order_id="O1")],
        )

    def _clean_cash(self) -> CashReconciliationResult:
        return reconcile_cash(50_000.0, 50_000.0)

    def test_all_clean_produces_clean_status(self) -> None:
        report = build_reconciliation_report(
            position_result=self._clean_position(),
            fill_result=self._clean_fills(),
            cash_result=self._clean_cash(),
            generated_at="2026-06-05T16:00:00Z",
        )
        assert report.status == ReconciliationStatus.CLEAN
        assert report.all_incidents == []

    def test_position_mismatch_produces_mismatch_status(self) -> None:
        pos = reconcile_positions({"AAPL": 100.0}, {"AAPL": 90.0})
        report = build_reconciliation_report(position_result=pos)
        assert report.status == ReconciliationStatus.MISMATCH
        assert len(report.all_incidents) >= 1

    def test_cash_mismatch_produces_mismatch_status(self) -> None:
        cash = reconcile_cash(50_000.0, 40_000.0)
        report = build_reconciliation_report(cash_result=cash)
        assert report.status == ReconciliationStatus.MISMATCH

    def test_fill_mismatch_produces_mismatch_status(self) -> None:
        fills = reconcile_fills(
            [_make_fill("GLD", "BUY", 10.0, 190.0)],
            [],
        )
        report = build_reconciliation_report(fill_result=fills)
        assert report.status == ReconciliationStatus.MISMATCH

    def test_incidents_ordered_pos_fill_cash(self) -> None:
        pos = reconcile_positions({"A": 1.0}, {"A": 2.0}, run_date="D")
        fills = reconcile_fills([_make_fill("B", "BUY", 1.0, 100.0)], [],
                                run_date="D")
        cash = reconcile_cash(100.0, 200.0, run_date="D")
        report = build_reconciliation_report(
            position_result=pos, fill_result=fills, cash_result=cash
        )
        assert "position mismatch" in report.all_incidents[0]
        assert "unmatched internal" in report.all_incidents[1]
        assert "cash mismatch" in report.all_incidents[2]

    def test_no_sections_clean(self) -> None:
        report = build_reconciliation_report()
        assert report.status == ReconciliationStatus.CLEAN

    def test_dataclass_frozen(self) -> None:
        report = build_reconciliation_report()
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            report.status = "X"  # type: ignore[misc]

    def test_generated_at_preserved(self) -> None:
        report = build_reconciliation_report(generated_at="2026-01-01T00:00:00Z")
        assert report.generated_at == "2026-01-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Wash-sale tracking tests
# ---------------------------------------------------------------------------


class TestFlagWashSales:
    def test_basic_post_sale_buy_within_window(self) -> None:
        sale = SaleEvent("AAPL", date(2026, 1, 10), quantity=100.0,
                         loss_amount=500.0)
        buy = BuyEvent("AAPL", date(2026, 1, 15), quantity=100.0)  # 5 days after
        report = flag_wash_sales([sale], [buy])
        assert len(report.flags) == 1
        fl = report.flags[0]
        assert fl.sale is sale
        assert fl.buy is buy
        assert fl.replacement_ratio == pytest.approx(1.0)
        assert fl.disallowed_loss == pytest.approx(500.0)
        assert fl.days_apart == 5

    def test_basic_pre_sale_buy_within_window(self) -> None:
        sale = SaleEvent("AAPL", date(2026, 1, 10), quantity=50.0,
                         loss_amount=200.0)
        buy = BuyEvent("AAPL", date(2025, 12, 25), quantity=50.0)  # 16 days before
        report = flag_wash_sales([sale], [buy])
        assert len(report.flags) == 1
        assert report.flags[0].days_apart == -16

    def test_buy_exactly_30_days_after_flagged(self) -> None:
        sale = SaleEvent("MSFT", date(2026, 2, 1), quantity=10.0,
                         loss_amount=100.0)
        buy = BuyEvent("MSFT", date(2026, 3, 3), quantity=10.0)  # exactly 30 days
        report = flag_wash_sales([sale], [buy])
        assert len(report.flags) == 1

    def test_buy_31_days_after_not_flagged(self) -> None:
        sale = SaleEvent("MSFT", date(2026, 2, 1), quantity=10.0,
                         loss_amount=100.0)
        buy = BuyEvent("MSFT", date(2026, 3, 4), quantity=10.0)  # 31 days
        report = flag_wash_sales([sale], [buy])
        assert len(report.flags) == 0

    def test_buy_exactly_30_days_before_flagged(self) -> None:
        sale = SaleEvent("GLD", date(2026, 3, 1), quantity=20.0,
                         loss_amount=80.0)
        buy = BuyEvent("GLD", date(2026, 1, 30), quantity=20.0)  # exactly 30 before
        report = flag_wash_sales([sale], [buy])
        assert len(report.flags) == 1
        assert report.flags[0].days_apart == -30

    def test_buy_31_days_before_not_flagged(self) -> None:
        sale = SaleEvent("GLD", date(2026, 3, 1), quantity=20.0,
                         loss_amount=80.0)
        buy = BuyEvent("GLD", date(2026, 1, 29), quantity=20.0)  # 31 days before
        report = flag_wash_sales([sale], [buy])
        assert len(report.flags) == 0

    def test_partial_replacement(self) -> None:
        sale = SaleEvent("AAPL", date(2026, 1, 10), quantity=100.0,
                         loss_amount=400.0)
        buy = BuyEvent("AAPL", date(2026, 1, 20), quantity=40.0)  # 40% replacement
        report = flag_wash_sales([sale], [buy])
        assert len(report.flags) == 1
        fl = report.flags[0]
        assert fl.replacement_ratio == pytest.approx(0.4)
        assert fl.disallowed_loss == pytest.approx(160.0)

    def test_multiple_buys_collectively_replace(self) -> None:
        sale = SaleEvent("AAPL", date(2026, 1, 10), quantity=100.0,
                         loss_amount=500.0)
        buys = [
            BuyEvent("AAPL", date(2026, 1, 12), quantity=30.0),
            BuyEvent("AAPL", date(2026, 1, 20), quantity=50.0),
            BuyEvent("AAPL", date(2026, 1, 25), quantity=30.0),  # only 20 consumed
        ]
        report = flag_wash_sales([sale], buys)
        # First two fully match, third partially
        assert len(report.flags) == 3
        total_ratio = sum(f.replacement_ratio for f in report.flags)
        assert total_ratio == pytest.approx(1.0)
        assert report.total_disallowed_loss == pytest.approx(500.0)

    def test_zero_loss_sale_skipped(self) -> None:
        sale = SaleEvent("AAPL", date(2026, 1, 10), quantity=100.0,
                         loss_amount=0.0)
        buy = BuyEvent("AAPL", date(2026, 1, 15), quantity=100.0)
        report = flag_wash_sales([sale], [buy])
        assert len(report.flags) == 0
        assert report.n_sales_affected == 0

    def test_different_symbol_buy_not_flagged(self) -> None:
        sale = SaleEvent("AAPL", date(2026, 1, 10), quantity=100.0,
                         loss_amount=300.0)
        buy = BuyEvent("MSFT", date(2026, 1, 15), quantity=100.0)
        report = flag_wash_sales([sale], [buy])
        assert len(report.flags) == 0

    def test_n_sales_affected_counted_correctly(self) -> None:
        sales = [
            SaleEvent("AAPL", date(2026, 1, 10), 100.0, 200.0),
            SaleEvent("MSFT", date(2026, 1, 15), 50.0, 100.0),
        ]
        buys = [
            BuyEvent("AAPL", date(2026, 1, 20), 100.0),  # affects sale 0
            # no buy for MSFT
        ]
        report = flag_wash_sales(sales, buys)
        assert report.n_sales_affected == 1
        assert len(report.flags) == 1

    def test_total_disallowed_loss_sum(self) -> None:
        sales = [
            SaleEvent("AAPL", date(2026, 1, 10), 100.0, 200.0),
            SaleEvent("MSFT", date(2026, 1, 15), 50.0, 100.0),
        ]
        buys = [
            BuyEvent("AAPL", date(2026, 1, 20), 100.0),
            BuyEvent("MSFT", date(2026, 1, 20), 50.0),
        ]
        report = flag_wash_sales(sales, buys)
        assert report.total_disallowed_loss == pytest.approx(300.0)

    def test_buy_consumed_only_once(self) -> None:
        # One buy should not match two separate sales
        sales = [
            SaleEvent("AAPL", date(2026, 1, 5), 50.0, 100.0),
            SaleEvent("AAPL", date(2026, 1, 6), 50.0, 100.0),
        ]
        buys = [BuyEvent("AAPL", date(2026, 1, 10), 50.0)]
        report = flag_wash_sales(sales, buys)
        # Only the first (earliest) sale should match
        assert len(report.flags) == 1
        assert report.total_disallowed_loss == pytest.approx(100.0)

    def test_report_disclaimer_present(self) -> None:
        report = flag_wash_sales([], [])
        assert "NOT TAX ADVICE" in report.disclaimer
        assert "tax professional" in report.disclaimer.lower()

    def test_empty_inputs_no_flags(self) -> None:
        report = flag_wash_sales([], [])
        assert report.flags == []
        assert report.total_disallowed_loss == 0.0
        assert report.n_sales_affected == 0

    def test_flags_sorted_by_sale_date(self) -> None:
        sales = [
            SaleEvent("B", date(2026, 2, 1), 10.0, 50.0),
            SaleEvent("A", date(2026, 1, 1), 10.0, 50.0),
        ]
        buys = [
            BuyEvent("B", date(2026, 2, 5), 10.0),
            BuyEvent("A", date(2026, 1, 5), 10.0),
        ]
        report = flag_wash_sales(sales, buys)
        assert report.flags[0].sale.symbol == "A"
        assert report.flags[1].sale.symbol == "B"

    def test_replacement_ratio_capped_at_one(self) -> None:
        # Buy quantity > sold quantity
        sale = SaleEvent("AAPL", date(2026, 1, 10), 50.0, 200.0)
        buy = BuyEvent("AAPL", date(2026, 1, 15), 100.0)
        report = flag_wash_sales([sale], [buy])
        assert report.flags[0].replacement_ratio == pytest.approx(1.0)

    def test_same_day_buy_flagged(self) -> None:
        sale = SaleEvent("SPY", date(2026, 3, 15), 20.0, 30.0)
        buy = BuyEvent("SPY", date(2026, 3, 15), 20.0)
        report = flag_wash_sales([sale], [buy])
        assert len(report.flags) == 1
        assert report.flags[0].days_apart == 0
        assert "same day" in report.flags[0].note


# ---------------------------------------------------------------------------
# Render tests
# ---------------------------------------------------------------------------


class TestRenderReconciliationReport:
    def _clean_report(self) -> ReconciliationReport:
        pos = reconcile_positions({"AAPL": 100.0}, {"AAPL": 100.0})
        fills = reconcile_fills(
            [_make_fill(order_id="O1")], [_make_fill(order_id="O1")]
        )
        cash = reconcile_cash(50_000.0, 50_000.0)
        return build_reconciliation_report(
            position_result=pos, fill_result=fills, cash_result=cash,
            generated_at="2026-06-05T16:00:00Z",
        )

    def test_output_is_ascii(self) -> None:
        report = self._clean_report()
        text = render_reconciliation_report(report)
        assert _is_ascii(text), "Report contains non-ASCII characters"

    def test_clean_status_in_output(self) -> None:
        report = self._clean_report()
        text = render_reconciliation_report(report)
        assert "CLEAN" in text

    def test_mismatch_status_in_output(self) -> None:
        pos = reconcile_positions({"AAPL": 100.0}, {"AAPL": 90.0})
        report = build_reconciliation_report(position_result=pos)
        text = render_reconciliation_report(report)
        assert "MISMATCH" in text

    def test_generated_at_in_output(self) -> None:
        report = self._clean_report()
        text = render_reconciliation_report(report)
        assert "2026-06-05T16:00:00Z" in text

    def test_position_section_header(self) -> None:
        report = self._clean_report()
        text = render_reconciliation_report(report)
        assert "Position Reconciliation" in text

    def test_fill_section_header(self) -> None:
        report = self._clean_report()
        text = render_reconciliation_report(report)
        assert "Fill Reconciliation" in text

    def test_cash_section_header(self) -> None:
        report = self._clean_report()
        text = render_reconciliation_report(report)
        assert "Cash Reconciliation" in text

    def test_incident_section_header(self) -> None:
        report = self._clean_report()
        text = render_reconciliation_report(report)
        assert "Incidents" in text

    def test_wash_sale_section_header(self) -> None:
        report = self._clean_report()
        text = render_reconciliation_report(report)
        assert "Wash-Sale" in text

    def test_none_position_shows_not_available(self) -> None:
        report = build_reconciliation_report()
        text = render_reconciliation_report(report)
        assert "Not available: no position" in text

    def test_none_fills_shows_not_available(self) -> None:
        report = build_reconciliation_report()
        text = render_reconciliation_report(report)
        assert "Not available: no fill" in text

    def test_none_cash_shows_not_available(self) -> None:
        report = build_reconciliation_report()
        text = render_reconciliation_report(report)
        assert "Not available: no cash" in text

    def test_none_wash_report_shows_not_available(self) -> None:
        report = build_reconciliation_report()
        text = render_reconciliation_report(report, wash_report=None)
        assert "Not available: no wash-sale" in text

    def test_wash_sale_report_rendered(self) -> None:
        sale = SaleEvent("AAPL", date(2026, 1, 10), 100.0, 500.0)
        buy = BuyEvent("AAPL", date(2026, 1, 15), 100.0)
        wash = flag_wash_sales([sale], [buy])
        report = build_reconciliation_report()
        text = render_reconciliation_report(report, wash_report=wash)
        assert "AAPL" in text
        assert "NOT TAX ADVICE" in text or "INFORMATIONAL" in text

    def test_incidents_listed_in_output(self) -> None:
        pos = reconcile_positions({"AAPL": 100.0}, {"AAPL": 90.0},
                                  run_date="2026-06-05")
        report = build_reconciliation_report(position_result=pos)
        text = render_reconciliation_report(report)
        assert "position mismatch AAPL" in text

    def test_no_incidents_message(self) -> None:
        report = self._clean_report()
        text = render_reconciliation_report(report)
        assert "No incidents." in text

    def test_output_is_string(self) -> None:
        report = self._clean_report()
        text = render_reconciliation_report(report)
        assert isinstance(text, str)


# ---------------------------------------------------------------------------
# _fmt_float and _fmt_opt_float helpers
# ---------------------------------------------------------------------------


class TestFmtHelpers:
    def test_fmt_float_basic(self) -> None:
        assert _fmt_float(1.5, 2) == "1.50"

    def test_fmt_float_nan(self) -> None:
        assert _fmt_float(float("nan")) == "n/a"

    def test_fmt_float_inf(self) -> None:
        assert _fmt_float(float("inf")) == "+inf"
        assert _fmt_float(float("-inf")) == "-inf"

    def test_fmt_opt_float_none(self) -> None:
        assert _fmt_opt_float(None) == "n/a"

    def test_fmt_opt_float_value(self) -> None:
        assert _fmt_opt_float(3.14159, 2) == "3.14"


# ---------------------------------------------------------------------------
# Demo data + CLI tests
# ---------------------------------------------------------------------------


class TestDemoAndCLI:
    def test_build_demo_data_returns_expected_keys(self) -> None:
        demo = _build_demo_data()
        assert "clean" in demo
        assert "mismatch" in demo
        assert "wash_sales" in demo
        assert "wash_buys" in demo

    def test_demo_clean_scenario_is_clean(self) -> None:
        demo = _build_demo_data()
        s = demo["clean"]
        cfg = ReconciliationConfig(fill_price_bps_tol=2.0)
        pos = reconcile_positions(s["internal_pos"], s["broker_pos"], config=cfg)
        fills = reconcile_fills(s["int_fills"], s["brk_fills"], config=cfg)
        cash = reconcile_cash(s["int_cash"], s["brk_cash"], config=cfg)
        report = build_reconciliation_report(
            position_result=pos, fill_result=fills, cash_result=cash
        )
        assert report.status == ReconciliationStatus.CLEAN

    def test_demo_mismatch_scenario_is_mismatch(self) -> None:
        demo = _build_demo_data()
        s = demo["mismatch"]
        pos = reconcile_positions(s["internal_pos"], s["broker_pos"])
        fills = reconcile_fills(s["int_fills"], s["brk_fills"])
        cash = reconcile_cash(s["int_cash"], s["brk_cash"])
        report = build_reconciliation_report(
            position_result=pos, fill_result=fills, cash_result=cash
        )
        assert report.status == ReconciliationStatus.MISMATCH

    def test_main_demo_runs_without_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        main(["--demo"])
        captured = capsys.readouterr()
        assert "CLEAN SCENARIO" in captured.out
        assert "MISMATCH SCENARIO" in captured.out

    def test_main_demo_output_is_ascii(self, capsys: pytest.CaptureFixture[str]) -> None:
        main(["--demo"])
        captured = capsys.readouterr()
        assert _is_ascii(captured.out)

    def test_main_no_demo_exits_with_error(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code != 0

    def test_main_output_flag(self, tmp_path: Any) -> None:
        out_path = str(tmp_path / "recon_report.txt")
        main(["--demo", "--output", out_path])
        assert os.path.exists(out_path)
        with open(out_path, encoding="utf-8") as fh:
            content = fh.read()
        assert "CLEAN SCENARIO" in content
        assert _is_ascii(content)

    def test_demo_wash_sales_produces_flags(self) -> None:
        demo = _build_demo_data()
        report = flag_wash_sales(demo["wash_sales"], demo["wash_buys"])
        # At least one flag should be detected (AAPL buy 5 days after sale)
        assert report.n_sales_affected >= 1
        assert report.total_disallowed_loss > 0.0
