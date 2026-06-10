"""Tests for tools/paper_report.py (HTML generation, no browser needed)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from paper_report import build_report_html, generate_report  # noqa: E402


def _book(root: Path, equities: list[float]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "state.json").write_text(
        json.dumps(
            {
                "started": "2026-06-10",
                "cash": 100.0,
                "positions": {"AAPL": 6},
                "halted": False,
                "incidents": [],
            }
        ),
        encoding="utf-8",
    )
    records = []
    prev = 25_000.0
    for i, eq in enumerate(equities):
        records.append(
            {
                "date": f"2026-06-{10 + i:02d}",
                "status": "TRADED",
                "equity": eq,
                "daily_return": eq / prev - 1.0,
                "orders": [],
                "promotion": {"n_days": i + 1},
                "dry_run": False,
            }
        )
        prev = eq
    (root / "ledger.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8"
    )


class TestBuildReport:
    def test_html_contains_data_and_escapes_script_close(self, tmp_path: Path) -> None:
        _book(tmp_path / "taquant_paper" / "slotA", [25_100.0, 25_200.0])
        out = generate_report(tmp_path, tmp_path / "report.html")
        html = out.read_text(encoding="utf-8")
        assert "slotA" in html
        assert "25100.0" in html
        assert "<!DOCTYPE html>" in html
        # data island must not be able to break out of its script tag
        payload_start = html.index('type="application/json">') + len(
            'type="application/json">'
        )
        payload = html[payload_start : html.index("</script>", payload_start)]
        assert "</" not in payload.replace("<\\/", "")

    def test_empty_logs_root_renders(self) -> None:
        html = build_report_html(
            {
                "generated_utc": "2026-06-10 00:00:00Z",
                "n_books": 0,
                "total_marked_equity": 0.0,
                "any_halted": False,
                "open_incidents": 0,
                "books": [],
            }
        )
        assert "Paper Trading Report" in html

    def test_output_dir_created(self, tmp_path: Path) -> None:
        out = generate_report(tmp_path / "nological", tmp_path / "deep" / "r.html")
        assert out.exists()
