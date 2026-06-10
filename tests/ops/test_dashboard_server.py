"""Tests for tools/dashboard_server.py using FastAPI's TestClient."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import dashboard_server  # noqa: E402


@pytest.fixture()
def logs_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    book = tmp_path / "taquant_paper" / "slotX"
    book.mkdir(parents=True)
    (book / "state.json").write_text(
        json.dumps({"started": "2026-06-10", "cash": 5.0, "positions": {}, "incidents": []}),
        encoding="utf-8",
    )
    (book / "ledger.jsonl").write_text(
        json.dumps(
            {
                "date": "2026-06-10",
                "status": "TRADED",
                "equity": 25_100.0,
                "daily_return": 0.004,
                "orders": [],
                "promotion": {"n_days": 1},
                "dry_run": False,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(dashboard_server, "LOGS_ROOT", tmp_path)
    return tmp_path


class TestDashboardServer:
    def test_index_serves_page(self) -> None:
        client = TestClient(dashboard_server.app)
        r = client.get("/")
        assert r.status_code == 200
        assert "Operator Dashboard" in r.text

    @pytest.mark.usefixtures("logs_root")
    def test_api_summary_shape(self) -> None:
        client = TestClient(dashboard_server.app)
        r = client.get("/api/summary")
        assert r.status_code == 200
        payload = r.json()
        for key in ("generated_utc", "n_books", "books", "any_halted", "open_incidents"):
            assert key in payload
        assert payload["n_books"] == 1
        assert payload["books"][0]["name"] == "slotX"
        assert payload["books"][0]["equity_values"] == [25_100.0]

    def test_docs_disabled(self) -> None:
        client = TestClient(dashboard_server.app)
        assert client.get("/docs").status_code == 404
