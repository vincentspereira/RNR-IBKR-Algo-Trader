"""Tests for core_trading.execution.tca (Phase 9.4 Transaction Cost Analysis).

Covers, with hand-computed known-value examples:
* TCAConfig validation + defaults.
* arrival_slippage_bps / vwap_slippage_bps: sign convention + bps scaling.
* implementation_shortfall: Perold decomposition incl. opportunity cost.
* attribute_cost: the four-component-plus-fees == total_is identity.
* markouts: alignment rules (nearest at-or-after, EOD, beyond-data NaN).
* compute_fill_tca + build_daily_tca_report: per-symbol + portfolio stats,
  column validation, worst-fills ordering.
* render_report: ASCII-only + golden substrings.
* main(): --demo smoke + --output write + missing-flag SystemExit.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from core_trading.execution.tca import (
    REQUIRED_FILL_COLUMNS,
    DailyTCAReport,
    FillTCA,
    TCAConfig,
    arrival_slippage_bps,
    attribute_cost,
    build_daily_tca_report,
    compute_fill_tca,
    implementation_shortfall,
    main,
    markouts,
    render_report,
    vwap_slippage_bps,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_fills() -> pd.DataFrame:
    """A small deterministic fills frame with two symbols, both sides."""
    base = pd.Timestamp("2026-06-05 14:30:00")
    rows = [
        {
            "order_id": "O1",
            "symbol": "AAPL",
            "side": "buy",
            "quantity": 100.0,
            "filled_quantity": 100.0,
            "decision_price": 100.0,
            "arrival_price": 100.0,
            "avg_fill_price": 100.10,
            "mid_at_fill": 100.05,
            "half_spread": 0.05,
            "fill_time": base,
            "close_price": 100.0,
            "fees": 0.5,
        },
        {
            "order_id": "O2",
            "symbol": "MSFT",
            "side": "sell",
            "quantity": 200.0,
            "filled_quantity": 150.0,
            "decision_price": 50.0,
            "arrival_price": 49.98,
            "avg_fill_price": 49.95,
            "mid_at_fill": 49.97,
            "half_spread": 0.02,
            "fill_time": base + pd.Timedelta(minutes=10),
            "close_price": 49.90,
            "fees": 1.0,
        },
    ]
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# TCAConfig
# ---------------------------------------------------------------------------


def test_config_defaults_valid() -> None:
    cfg = TCAConfig()
    labels = [h[0] for h in cfg.horizons]
    assert labels == ["1s", "10s", "1m", "5m", "1h", "EOD"]
    assert cfg.bps_scale == 1e4
    assert cfg.worst_n == 5


def test_config_rejects_empty_horizons() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        TCAConfig(horizons=())


def test_config_rejects_duplicate_labels() -> None:
    with pytest.raises(ValueError, match="unique"):
        TCAConfig(horizons=(("1s", 1.0), ("1s", 2.0)))


def test_config_rejects_nonpositive_seconds() -> None:
    with pytest.raises(ValueError, match="positive or None"):
        TCAConfig(horizons=(("bad", -1.0),))


def test_config_rejects_bad_bps_scale() -> None:
    with pytest.raises(ValueError, match="bps_scale"):
        TCAConfig(bps_scale=0.0)


def test_config_rejects_bad_worst_n() -> None:
    with pytest.raises(ValueError, match="worst_n"):
        TCAConfig(worst_n=0)


# ---------------------------------------------------------------------------
# Slippage primitives -- hand-computed
# ---------------------------------------------------------------------------


def test_arrival_slippage_buy_above_is_positive_cost() -> None:
    # Buy filled at 100.10 vs arrival 100.00 -> +10 bps cost.
    assert arrival_slippage_bps(100.10, 100.0, 1) == pytest.approx(10.0)


def test_arrival_slippage_buy_below_is_improvement() -> None:
    # Buy filled below arrival -> negative cost (price improvement).
    assert arrival_slippage_bps(99.90, 100.0, 1) == pytest.approx(-10.0)


def test_arrival_slippage_sell_below_is_positive_cost() -> None:
    # Sell filled at 99.90 vs arrival 100.00 -> +10 bps cost (sold cheap).
    assert arrival_slippage_bps(99.90, 100.0, -1) == pytest.approx(10.0)


def test_arrival_slippage_nonpositive_arrival_is_nan() -> None:
    assert np.isnan(arrival_slippage_bps(100.0, 0.0, 1))


def test_vwap_slippage_buy_above_vwap_is_cost() -> None:
    # Buy at 100.20 vs VWAP 100.00 -> +20 bps.
    assert vwap_slippage_bps(100.20, 100.0, 1) == pytest.approx(20.0)


def test_vwap_slippage_nan_vwap_propagates() -> None:
    assert np.isnan(vwap_slippage_bps(100.0, float("nan"), 1))
    assert np.isnan(vwap_slippage_bps(100.0, -1.0, 1))


# ---------------------------------------------------------------------------
# Implementation shortfall -- hand-computed
# ---------------------------------------------------------------------------


def test_implementation_shortfall_full_fill() -> None:
    # Buy 100 @ 100.10 vs decision 100.00, fully filled, fees 0.5.
    # execution = +1 * (100.10 - 100.00) * 100 = 10.0
    # opportunity = 0 (nothing unfilled)
    # total = 10.0 + 0 + 0.5 = 10.5
    res = implementation_shortfall(
        side=1,
        quantity=100.0,
        filled_quantity=100.0,
        decision_price=100.0,
        avg_fill_price=100.10,
        close_price=100.0,
        fees=0.5,
    )
    assert res["execution_cost"] == pytest.approx(10.0)
    assert res["opportunity_cost"] == pytest.approx(0.0)
    assert res["total_is"] == pytest.approx(10.5)


def test_implementation_shortfall_partial_fill_opportunity() -> None:
    # Buy 100 intended, only 60 filled @ 101 vs decision 100; close 102.
    # execution = (101 - 100) * 60 = 60
    # opportunity = (102 - 100) * 40 = 80  (price ran away on the 40 unfilled)
    # total = 60 + 80 + 0 = 140
    res = implementation_shortfall(
        side=1,
        quantity=100.0,
        filled_quantity=60.0,
        decision_price=100.0,
        avg_fill_price=101.0,
        close_price=102.0,
        fees=0.0,
    )
    assert res["execution_cost"] == pytest.approx(60.0)
    assert res["opportunity_cost"] == pytest.approx(80.0)
    assert res["total_is"] == pytest.approx(140.0)


def test_implementation_shortfall_sell_side_sign() -> None:
    # Sell 100 @ 99 vs decision 100: execution = -1*(99-100)*100 = +100 cost.
    res = implementation_shortfall(
        side=-1,
        quantity=100.0,
        filled_quantity=100.0,
        decision_price=100.0,
        avg_fill_price=99.0,
        close_price=100.0,
        fees=0.0,
    )
    assert res["execution_cost"] == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# Attribution identity
# ---------------------------------------------------------------------------


def test_attribution_identity_components_sum_to_total() -> None:
    # Hand example: buy 100 intended, 80 filled.
    # decision=100, arrival=100.2, mid_fill=100.5, avg_fill=100.6, close=101.
    # timing = (100.2-100.0)*80 = 16
    # impact = (100.5-100.2)*80 = 24
    # spread = (100.6-100.5)*80 = 8
    # opportunity = (101-100)*20 = 20
    # fees = 2
    # total = 16+24+8+20+2 = 70
    attr = attribute_cost(
        side=1,
        quantity=100.0,
        filled_quantity=80.0,
        decision_price=100.0,
        arrival_price=100.2,
        avg_fill_price=100.6,
        mid_at_fill=100.5,
        half_spread=0.1,
        close_price=101.0,
        fees=2.0,
    )
    assert attr["timing"] == pytest.approx(16.0)
    assert attr["impact"] == pytest.approx(24.0)
    assert attr["spread"] == pytest.approx(8.0)
    assert attr["opportunity"] == pytest.approx(20.0)
    assert attr["fees"] == pytest.approx(2.0)
    assert attr["total_is"] == pytest.approx(70.0)
    # The decomposition identity.
    summed = (
        attr["spread"]
        + attr["impact"]
        + attr["timing"]
        + attr["opportunity"]
        + attr["fees"]
    )
    assert summed == pytest.approx(attr["total_is"])


def test_attribution_identity_matches_implementation_shortfall() -> None:
    # attribute_cost total must equal implementation_shortfall total for the
    # same inputs (execution = spread + impact + timing).
    kw = dict(
        side=-1,
        quantity=300.0,
        filled_quantity=210.0,
        decision_price=80.0,
        avg_fill_price=79.6,
        close_price=79.0,
        fees=3.5,
    )
    is_res = implementation_shortfall(**kw)  # type: ignore[arg-type]
    attr = attribute_cost(
        arrival_price=79.9,
        mid_at_fill=79.7,
        half_spread=0.1,
        **kw,  # type: ignore[arg-type]
    )
    assert attr["total_is"] == pytest.approx(is_res["total_is"])
    # execution leg reconstructed from the three components.
    exec_from_attr = attr["spread"] + attr["impact"] + attr["timing"]
    assert exec_from_attr == pytest.approx(is_res["execution_cost"])


def test_attribution_quoted_half_spread_reported() -> None:
    attr = attribute_cost(
        side=1,
        quantity=100.0,
        filled_quantity=100.0,
        decision_price=100.0,
        arrival_price=100.0,
        avg_fill_price=100.05,
        mid_at_fill=100.0,
        half_spread=0.05,
        close_price=100.0,
        fees=0.0,
    )
    assert attr["quoted_half_spread_usd"] == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# Markouts -- alignment rules
# ---------------------------------------------------------------------------


def _markout_prices() -> pd.Series:
    # 1-second grid: 100.0, 100.1, 100.2, ... for 10 seconds, then a gap.
    idx = pd.date_range("2026-06-05 10:00:00", periods=11, freq="1s")
    vals = 100.0 + 0.1 * np.arange(11)
    return pd.Series(vals, index=idx)


def test_markout_nearest_at_or_after() -> None:
    prices = _markout_prices()
    fills = pd.DataFrame(
        [
            {
                "side": "buy",
                "avg_fill_price": 100.0,
                "fill_time": pd.Timestamp("2026-06-05 10:00:00"),
            }
        ]
    )
    out = markouts(fills, prices, (("1s", 1.0), ("10s", 10.0)))
    # p0 = 100.0; at +1s price = 100.1 -> (100.1-100)/100*1e4 = 10 bps.
    assert out.iloc[0]["1s"] == pytest.approx(10.0)
    # at +10s price = 101.0 -> (101-100)/100*1e4 = 100 bps.
    assert out.iloc[0]["10s"] == pytest.approx(100.0)


def test_markout_sell_sign() -> None:
    prices = _markout_prices()
    fills = pd.DataFrame(
        [
            {
                "side": "sell",
                "avg_fill_price": 100.0,
                "fill_time": pd.Timestamp("2026-06-05 10:00:00"),
            }
        ]
    )
    out = markouts(fills, prices, (("1s", 1.0),))
    # sell, price rose -> favourable, so negative cost.
    assert out.iloc[0]["1s"] == pytest.approx(-10.0)


def test_markout_beyond_data_is_nan() -> None:
    prices = _markout_prices()  # spans 10s
    fills = pd.DataFrame(
        [
            {
                "side": "buy",
                "avg_fill_price": 100.0,
                "fill_time": pd.Timestamp("2026-06-05 10:00:05"),
            }
        ]
    )
    # +1h is far beyond the 10-second series -> nan.
    out = markouts(fills, prices, (("1h", 3600.0),))
    assert np.isnan(out.iloc[0]["1h"])


def test_markout_at_or_after_picks_forward_tick() -> None:
    # fill at a timestamp with no exact +secs match -> nearest forward.
    idx = pd.to_datetime(
        [
            "2026-06-05 10:00:00",
            "2026-06-05 10:00:03",  # only tick after +1s target (10:00:01)
        ]
    )
    prices = pd.Series([100.0, 105.0], index=idx)
    fills = pd.DataFrame(
        [
            {
                "side": "buy",
                "avg_fill_price": 100.0,
                "fill_time": pd.Timestamp("2026-06-05 10:00:00"),
            }
        ]
    )
    out = markouts(fills, prices, (("1s", 1.0),))
    # target 10:00:01, nearest at-or-after is 10:00:03 = 105 -> +500 bps.
    assert out.iloc[0]["1s"] == pytest.approx(500.0)


def test_markout_eod_uses_last_price_of_day() -> None:
    idx = pd.to_datetime(
        [
            "2026-06-05 10:00:00",
            "2026-06-05 15:59:00",
            "2026-06-06 09:30:00",  # next day, must be excluded
        ]
    )
    prices = pd.Series([100.0, 110.0, 200.0], index=idx)
    fills = pd.DataFrame(
        [
            {
                "side": "buy",
                "avg_fill_price": 100.0,
                "fill_time": pd.Timestamp("2026-06-05 10:00:00"),
            }
        ]
    )
    out = markouts(fills, prices, (("EOD", None),))
    # last price on 2026-06-05 is 110 -> +1000 bps (not 200 from next day).
    assert out.iloc[0]["EOD"] == pytest.approx(1000.0)


def test_markout_eod_missing_day_is_nan() -> None:
    idx = pd.to_datetime(["2026-06-04 10:00:00"])
    prices = pd.Series([100.0], index=idx)
    fills = pd.DataFrame(
        [
            {
                "side": "buy",
                "avg_fill_price": 100.0,
                "fill_time": pd.Timestamp("2026-06-05 10:00:00"),
            }
        ]
    )
    out = markouts(fills, prices, (("EOD", None),))
    assert np.isnan(out.iloc[0]["EOD"])


def test_markout_invalid_side_raises() -> None:
    prices = _markout_prices()
    fills = pd.DataFrame(
        [
            {
                "side": "hold",
                "avg_fill_price": 100.0,
                "fill_time": pd.Timestamp("2026-06-05 10:00:00"),
            }
        ]
    )
    with pytest.raises(ValueError, match="Unrecognised side"):
        markouts(fills, prices, (("1s", 1.0),))


def test_markout_empty_prices_all_nan() -> None:
    prices = pd.Series([], index=pd.DatetimeIndex([]), dtype=float)
    fills = pd.DataFrame(
        [
            {
                "side": "buy",
                "avg_fill_price": 100.0,
                "fill_time": pd.Timestamp("2026-06-05 10:00:00"),
            }
        ]
    )
    out = markouts(fills, prices, (("1s", 1.0),))
    assert np.isnan(out.iloc[0]["1s"])


def test_markout_nonpositive_p0_skipped() -> None:
    prices = _markout_prices()
    fills = pd.DataFrame(
        [
            {
                "side": "buy",
                "avg_fill_price": 0.0,
                "fill_time": pd.Timestamp("2026-06-05 10:00:00"),
            }
        ]
    )
    out = markouts(fills, prices, (("1s", 1.0),))
    assert np.isnan(out.iloc[0]["1s"])


def test_markout_requires_columns() -> None:
    prices = _markout_prices()
    with pytest.raises(ValueError, match="missing required column"):
        markouts(pd.DataFrame({"side": ["buy"]}), prices, (("1s", 1.0),))


def test_markout_requires_datetime_index() -> None:
    prices = pd.Series([100.0, 101.0], index=[0, 1])
    fills = _make_fills()
    with pytest.raises(ValueError, match="DatetimeIndex"):
        markouts(fills, prices)


def test_markout_requires_monotonic_index() -> None:
    idx = pd.to_datetime(["2026-06-05 10:00:01", "2026-06-05 10:00:00"])
    prices = pd.Series([100.0, 101.0], index=idx)
    fills = _make_fills()
    with pytest.raises(ValueError, match="monotonic"):
        markouts(fills, prices)


# ---------------------------------------------------------------------------
# compute_fill_tca
# ---------------------------------------------------------------------------


def test_compute_fill_tca_buy_row() -> None:
    fills = _make_fills()
    tca = compute_fill_tca(fills.iloc[0], interval_vwap=100.0)
    assert tca.order_id == "O1"
    assert tca.symbol == "AAPL"
    assert tca.side == 1
    assert tca.fill_rate == pytest.approx(1.0)
    # arrival == avg? arrival 100.0, avg 100.10 -> +10 bps.
    assert tca.arrival_slippage_bps == pytest.approx(10.0)
    # vwap 100.0 vs avg 100.10 -> +10 bps.
    assert tca.vwap_slippage_bps == pytest.approx(10.0)
    # identity holds for the per-order USD numbers.
    summed = (
        tca.spread_usd
        + tca.impact_usd
        + tca.timing_usd
        + tca.opportunity_usd
        + tca.fees_usd
    )
    assert summed == pytest.approx(tca.is_usd)


def test_compute_fill_tca_vwap_nan_when_not_given() -> None:
    fills = _make_fills()
    tca = compute_fill_tca(fills.iloc[0])
    assert np.isnan(tca.vwap_slippage_bps)


def test_compute_fill_tca_zero_quantity_fill_rate() -> None:
    fills = _make_fills()
    row = fills.iloc[0].copy()
    row["quantity"] = 0.0
    tca = compute_fill_tca(row)
    assert tca.fill_rate == 0.0
    assert np.isnan(tca.is_bps)


# ---------------------------------------------------------------------------
# build_daily_tca_report
# ---------------------------------------------------------------------------


def test_build_report_validates_columns() -> None:
    bad = pd.DataFrame({"order_id": ["O1"], "symbol": ["AAPL"]})
    with pytest.raises(ValueError, match="missing required column"):
        build_daily_tca_report(bad)


def test_build_report_missing_names_listed() -> None:
    bad = _make_fills().drop(columns=["fees", "close_price"])
    with pytest.raises(ValueError) as exc:
        build_daily_tca_report(bad)
    msg = str(exc.value)
    assert "fees" in msg
    assert "close_price" in msg


def test_build_report_structure() -> None:
    fills = _make_fills()
    report = build_daily_tca_report(fills, generated_at="2026-06-05T00:00:00Z")
    assert isinstance(report, DailyTCAReport)
    assert len(report.fills) == 2
    assert set(report.per_symbol) == {"AAPL", "MSFT"}
    assert report.portfolio["n_orders"] == 2.0
    assert report.portfolio["n_symbols"] == 2.0
    assert report.generated_at == "2026-06-05T00:00:00Z"


def test_build_report_per_symbol_total_cost() -> None:
    fills = _make_fills()
    report = build_daily_tca_report(fills)
    # AAPL single order is_usd: execution (100.10-100)*100=10 + fees 0.5 = 10.5
    aapl = report.per_symbol["AAPL"]
    assert aapl["n_orders"] == 1.0
    assert aapl["total_is_usd"] == pytest.approx(10.5)


def test_build_report_with_markouts() -> None:
    fills = _make_fills()
    idx = pd.date_range("2026-06-05 14:30:00", periods=120, freq="1min")
    prices = pd.Series(100.0 + 0.01 * np.arange(120), index=idx)
    report = build_daily_tca_report(fills, prices=prices)
    # each fill carries a markout dict with all horizon labels.
    for f in report.fills:
        assert set(f.markout_bps) == {"1s", "10s", "1m", "5m", "1h", "EOD"}


def test_build_report_worst_fills_ordering() -> None:
    fills = _make_fills()
    report = build_daily_tca_report(fills, config=TCAConfig(worst_n=1))
    assert len(report.worst_fills) == 1
    # worst by is_usd descending.
    all_is = sorted((f.is_usd for f in report.fills), reverse=True)
    assert report.worst_fills[0].is_usd == pytest.approx(all_is[0])


def test_build_report_with_interval_vwaps() -> None:
    fills = _make_fills()
    report = build_daily_tca_report(fills, interval_vwaps={"O1": 100.0})
    o1 = next(f for f in report.fills if f.order_id == "O1")
    assert o1.vwap_slippage_bps == pytest.approx(10.0)
    o2 = next(f for f in report.fills if f.order_id == "O2")
    assert np.isnan(o2.vwap_slippage_bps)


# ---------------------------------------------------------------------------
# Renderer -- ASCII + golden substrings
# ---------------------------------------------------------------------------


def test_render_report_is_ascii_only() -> None:
    fills = _make_fills()
    report = build_daily_tca_report(fills, generated_at="2026-06-05T00:00:00Z")
    text = render_report(report)
    assert all(ord(ch) < 128 for ch in text)


def test_render_report_golden_substrings() -> None:
    fills = _make_fills()
    report = build_daily_tca_report(fills, generated_at="2026-06-05T00:00:00Z")
    text = render_report(report)
    assert "# Daily TCA Report" in text
    assert "## Portfolio Summary" in text
    assert "## Per-Symbol TCA" in text
    assert "## Worst Fills" in text
    assert "AAPL" in text
    assert "MSFT" in text
    assert "2026-06-05T00:00:00Z" in text


def test_render_report_handles_empty_summary() -> None:
    # An empty (but column-valid) fills frame renders without error.
    empty = _make_fills().iloc[0:0]
    report = build_daily_tca_report(empty, generated_at="2026-06-05T00:00:00Z")
    text = render_report(report)
    assert "Orders            : 0" in text


# ---------------------------------------------------------------------------
# CLI main()
# ---------------------------------------------------------------------------


def test_main_demo_smoke(capsys: pytest.CaptureFixture[str]) -> None:
    main(["--demo"])
    out = capsys.readouterr().out
    assert "# Daily TCA Report" in out
    assert all(ord(ch) < 128 for ch in out)


def test_main_demo_output_writes_file(tmp_path: Path) -> None:
    target = tmp_path / "tca.md"
    main(["--demo", "--output", str(target)])
    assert target.exists()
    content = target.read_text(encoding="utf-8")
    assert "# Daily TCA Report" in content


def test_main_requires_demo_flag() -> None:
    with pytest.raises(SystemExit):
        main([])


def test_required_columns_constant() -> None:
    # Guard the documented input contract.
    for col in ("order_id", "symbol", "side", "avg_fill_price", "fees"):
        assert col in REQUIRED_FILL_COLUMNS


def test_fill_tca_is_frozen() -> None:
    fills = _make_fills()
    tca = compute_fill_tca(fills.iloc[0])
    assert isinstance(tca, FillTCA)
    with pytest.raises((AttributeError, Exception)):
        tca.is_usd = 0.0  # type: ignore[misc]
