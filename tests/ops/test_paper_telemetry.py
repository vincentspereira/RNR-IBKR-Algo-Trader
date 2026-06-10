"""Unit tests for core_trading.ops.paper_telemetry."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core_trading.ops.paper_telemetry import (
    book_telemetry,
    discover_books,
    summarise_books,
)


def _write_book(
    root: Path,
    *,
    equities: list[float],
    base: float = 25_000.0,
    halted: bool = False,
    incidents: list[str] | None = None,
    skipped_days: int = 1,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    state = {
        "started": "2026-06-10",
        "formation_anchor": "2025-06-10",
        "cash": 1234.56,
        "positions": {"AAPL": 6, "VZ": 39},
        "halted": halted,
        "halt_reason": "test halt" if halted else None,
        "last_run_date": "2026-06-13",
        "incidents": incidents or [],
        "resolved_incidents": [],
    }
    (root / "state.json").write_text(json.dumps(state), encoding="utf-8")

    records = []
    prev = base
    for i, eq in enumerate(equities):
        records.append(
            {
                "date": f"2026-06-{10 + i:02d}",
                "status": "TRADED",
                "equity": eq,
                "daily_return": eq / prev - 1.0,
                "gross_leverage": 0.85,
                "orders": [
                    {"symbol": "AAPL", "side": "buy", "quantity": 6, "order_type": "market"}
                ],
                "fills": [],
                "violations": [],
                "promotion": {"eligible": False, "n_days": i + 1},
                "dry_run": False,
            }
        )
        prev = eq
    for j in range(skipped_days):
        records.append(
            {"date": f"2026-06-{20 + j:02d}", "status": "SKIPPED", "reason": "weekend"}
        )
    (root / "ledger.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )
    (root / "fills.jsonl").write_text(
        json.dumps({"date": "2026-06-10", "symbol": "AAPL", "side": "buy", "quantity": 6})
        + "\n",
        encoding="utf-8",
    )
    return root


class TestBookTelemetry:
    def test_loads_equity_and_returns(self, tmp_path: Path) -> None:
        book = _write_book(tmp_path / "slotA", equities=[25_100.0, 25_300.0, 25_000.0])
        t = book_telemetry(book, lane="taquant_paper", name="slotA")
        assert t.n_traded == 3
        assert t.n_skipped == 1
        assert list(t.equity) == [25_100.0, 25_300.0, 25_000.0]
        assert t.daily_returns.size == 3
        # peak 25300 -> trough 25000
        assert t.max_drawdown == pytest.approx(25_000.0 / 25_300.0 - 1.0)
        assert t.total_return == pytest.approx(0.0, abs=1e-9)  # back to base

    def test_to_json_is_jsonable_and_complete(self, tmp_path: Path) -> None:
        book = _write_book(
            tmp_path / "slotB", equities=[25_500.0], halted=True, incidents=["boom"]
        )
        payload = book_telemetry(book).to_json()
        json.dumps(payload)  # must be JSON-safe
        assert payload["halted"] is True
        assert payload["open_incidents"] == ["boom"]
        assert payload["positions"] == {"AAPL": 6, "VZ": 39}
        assert payload["equity_values"] == [25_500.0]
        assert payload["recent_orders"][0]["symbol"] == "AAPL"
        assert payload["recent_fills"][0]["quantity"] == 6

    def test_empty_book(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        (empty / "state.json").write_text("{}", encoding="utf-8")
        t = book_telemetry(empty)
        assert t.n_traded == 0
        assert t.paper_sharpe == 0.0
        assert t.max_drawdown == 0.0
        json.dumps(t.to_json())


class TestDiscoverAndSummarise:
    def test_discovers_lane_layouts(self, tmp_path: Path) -> None:
        logs = tmp_path / "logs"
        _write_book(logs / "taquant_paper" / "slot1", equities=[25_100.0])
        _write_book(logs / "taquant_paper" / "slot2", equities=[24_900.0])
        _write_book(logs / "pairs_paper", equities=[10_000.0])  # flat book layout
        books = discover_books(logs)
        keys = [(lane, name) for lane, name, _ in books]
        assert ("taquant_paper", "slot1") in keys
        assert ("taquant_paper", "slot2") in keys
        assert ("pairs_paper", "pairs_paper") in keys

    def test_summary_aggregates(self, tmp_path: Path) -> None:
        logs = tmp_path / "logs"
        _write_book(logs / "taquant_paper" / "slot1", equities=[25_100.0])
        _write_book(
            logs / "taquant_paper" / "slot2",
            equities=[24_900.0],
            halted=True,
            incidents=["x", "y"],
        )
        summary = summarise_books(logs)
        json.dumps(summary)
        assert summary["n_books"] == 2
        assert summary["any_halted"] is True
        assert summary["open_incidents"] == 2
        assert summary["total_marked_equity"] == pytest.approx(50_000.0)

    def test_missing_root_is_empty(self, tmp_path: Path) -> None:
        summary = summarise_books(tmp_path / "nope")
        assert summary["n_books"] == 0
        assert summary["books"] == []
