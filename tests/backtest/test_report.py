"""Tests for core_trading.backtest.report."""
from __future__ import annotations

import json

import pandas as pd
import pytest

from core_trading.backtest.engine import BacktestConfig, BacktestEngine, WeightStrategy
from core_trading.backtest.report import BacktestReport


def _const_weights(panel: pd.DataFrame, w: float = 0.5) -> pd.DataFrame:
    syms = list(panel.index.get_level_values("symbol").unique())
    idx = pd.DatetimeIndex(panel.index.get_level_values("timestamp").unique()).sort_values()
    return pd.DataFrame(w, index=idx, columns=syms)


@pytest.fixture
def report(panel: pd.DataFrame) -> BacktestReport:
    strat = WeightStrategy(_const_weights(panel, 0.5))
    eng = BacktestEngine(BacktestConfig(cost_model_name="ibkr", max_participation_rate=1.0))
    result = eng.run(panel, strat, mode="event_driven")
    return BacktestReport.from_result(result)


class TestTimeSeries:
    def test_equity_curve(self, report: BacktestReport) -> None:
        assert isinstance(report.equity_curve, pd.Series)
        assert report.equity_curve.size > 0

    def test_daily_pnl(self, report: BacktestReport) -> None:
        pnl = report.daily_pnl()
        assert pnl.name == "pnl"
        assert pnl.iloc[0] == pytest.approx(0.0)

    def test_drawdown_nonpositive(self, report: BacktestReport) -> None:
        assert (report.drawdown() <= 1e-9).all()

    def test_position_weights(self, report: BacktestReport) -> None:
        w = report.position_weights()
        assert "AAA" in w.columns


class TestTradeLedger:
    def test_ledger_has_trades(self, report: BacktestReport) -> None:
        ledger = report.trade_ledger()
        assert not ledger.empty
        assert {"symbol", "pnl", "entry_price", "exit_price"} <= set(ledger.columns)

    def test_empty_ledger_columns(self, panel: pd.DataFrame) -> None:
        # zero weights -> no trades
        strat = WeightStrategy(_const_weights(panel, 0.0))
        eng = BacktestEngine(BacktestConfig(cost_model_name="zero"))
        rep = BacktestReport.from_result(eng.run(panel, strat, mode="event_driven"))
        ledger = rep.trade_ledger()
        assert ledger.empty
        assert "pnl" in ledger.columns

    def test_attribution_by_symbol(self, report: BacktestReport) -> None:
        attrib = report.attribution()
        ledger = report.trade_ledger()
        for sym in ledger["symbol"].unique():
            assert attrib[sym] == pytest.approx(ledger[ledger["symbol"] == sym]["pnl"].sum())


class TestJson:
    def test_to_dict_structure(self, report: BacktestReport) -> None:
        d = report.to_dict()
        for k in ("mode", "final_equity", "metrics", "equity_curve", "fingerprint", "attribution"):
            assert k in d
        assert "timestamps" in d["equity_curve"]
        assert len(d["equity_curve"]["timestamps"]) == len(d["equity_curve"]["values"])

    def test_to_json_is_valid_and_sorted(self, report: BacktestReport) -> None:
        text = report.to_json()
        parsed = json.loads(text)
        assert parsed["mode"] == "event_driven"
        # deterministic: same content twice
        assert report.to_json() == text

    def test_save_json(self, report: BacktestReport, tmp_path) -> None:
        path = report.save_json(tmp_path / "bt.json")
        assert path.exists()
        reloaded = json.loads(path.read_text(encoding="utf-8"))
        assert reloaded["n_trades"] == report.metrics.n_trades

    def test_metrics_in_json(self, report: BacktestReport) -> None:
        d = report.to_dict()
        assert "sharpe" in d["metrics"]
        assert d["metrics"]["n_trades"] == float(report.metrics.n_trades)


class TestPdf:
    def test_save_pdf(self, report: BacktestReport, tmp_path) -> None:
        path = report.save_pdf(tmp_path / "tearsheet.pdf")
        assert path.exists()
        assert path.stat().st_size > 0
