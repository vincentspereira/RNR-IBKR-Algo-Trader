"""Telemetry over paper-trading ledgers -- the data layer for dashboards.

Every paper book (the daily TAQuant slots, the pairs pilot, the intraday
experimental lane) persists the same three files via
:class:`~core_trading.ops.pairs_live_runner.LedgerStore`: ``state.json``,
``ledger.jsonl``, ``fills.jsonl``. This module reads those files into plain
data structures consumed by the static HTML report
(``tools/paper_report.py``) and the live operator dashboard
(``tools/dashboard_server.py``). It never writes anything.

A "book" here is one directory containing the three files. ``discover_books``
walks the conventional roots (``logs/taquant_paper/<slot>``,
``logs/intraday_paper/<slot>``, ``logs/pairs_paper``) so new slots appear in
dashboards automatically.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from core_trading.ops.pairs_live_runner import LedgerStore, RunnerState

__all__ = [
    "BookTelemetry",
    "book_telemetry",
    "discover_books",
    "summarise_books",
]

# Conventional lane roots relative to the repo's logs/ directory. A lane root
# either IS a book (pairs_paper) or contains one subdirectory per slot.
_LANE_DIRS = ("taquant_paper", "intraday_paper", "pairs_paper")


@dataclass(slots=True)
class BookTelemetry:
    """Everything a dashboard needs to render one paper book."""

    name: str
    lane: str
    root: str
    state: RunnerState
    equity: pd.Series  # equity marks of TRADED days (oldest first)
    daily_returns: pd.Series  # realised daily returns of TRADED days
    n_records: int
    n_traded: int
    n_skipped: int
    last_record: dict[str, Any] = field(default_factory=dict)
    recent_orders: list[dict[str, Any]] = field(default_factory=list)
    recent_fills: list[dict[str, Any]] = field(default_factory=list)

    @property
    def total_return(self) -> float:
        if self.equity.empty:
            return 0.0
        base = float(self.equity.iloc[0]) / (1.0 + float(self.daily_returns.iloc[0])) \
            if not self.daily_returns.empty else float(self.equity.iloc[0])
        if base <= 0:
            return 0.0
        return float(self.equity.iloc[-1]) / base - 1.0

    @property
    def max_drawdown(self) -> float:
        """Peak-to-trough drawdown of the equity marks, as a NEGATIVE fraction."""
        if self.equity.size < 2:
            return 0.0
        running_max = self.equity.cummax()
        dd = self.equity / running_max - 1.0
        return float(dd.min())

    @property
    def paper_sharpe(self) -> float:
        r = self.daily_returns
        if r.size < 2 or float(r.std(ddof=1)) == 0.0:
            return 0.0
        return float(r.mean() / r.std(ddof=1) * math.sqrt(252.0))

    def to_json(self) -> dict[str, Any]:
        """JSON-safe dict for the dashboard API and the static report."""
        return {
            "name": self.name,
            "lane": self.lane,
            "root": self.root,
            "started": self.state.started,
            "halted": self.state.halted,
            "halt_reason": self.state.halt_reason,
            "last_run_date": self.state.last_run_date,
            "cash": round(self.state.cash, 2),
            "positions": dict(sorted(self.state.positions.items())),
            "n_positions": len(self.state.positions),
            "open_incidents": list(self.state.incidents),
            "n_records": self.n_records,
            "n_traded": self.n_traded,
            "n_skipped": self.n_skipped,
            "equity_dates": [d.strftime("%Y-%m-%d") for d in self.equity.index],
            "equity_values": [round(float(v), 2) for v in self.equity],
            "daily_returns": [float(v) for v in self.daily_returns],
            "total_return": round(self.total_return, 6),
            "max_drawdown": round(self.max_drawdown, 6),
            "paper_sharpe": round(self.paper_sharpe, 4),
            "last_record": self.last_record,
            "recent_orders": self.recent_orders,
            "recent_fills": self.recent_fills,
            "promotion": self.last_record.get("promotion", {}),
            "gross_leverage": self.last_record.get("gross_leverage", 0.0),
            "last_status": self.last_record.get("status", ""),
            "last_reason": self.last_record.get("reason", ""),
        }


def _is_book_dir(path: Path) -> bool:
    return (path / "ledger.jsonl").exists() or (path / "state.json").exists()


def discover_books(logs_root: Path) -> list[tuple[str, str, Path]]:
    """Find paper books under ``logs_root``.

    Returns ``(lane, book_name, book_dir)`` triples, lanes in the
    conventional order, slots alphabetical within a lane.
    """
    books: list[tuple[str, str, Path]] = []
    for lane in _LANE_DIRS:
        lane_dir = logs_root / lane
        if not lane_dir.is_dir():
            continue
        if _is_book_dir(lane_dir):
            books.append((lane, lane, lane_dir))
            continue
        for sub in sorted(p for p in lane_dir.iterdir() if p.is_dir()):
            if _is_book_dir(sub):
                books.append((lane, sub.name, sub))
    return books


def _read_jsonl_tail(path: Path, limit: int) -> list[dict[str, Any]]:
    if not path.exists() or limit <= 0:
        return []
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return [json.loads(ln) for ln in lines[-limit:]]


def book_telemetry(
    book_dir: Path, *, lane: str = "", name: str = "", recent: int = 20
) -> BookTelemetry:
    """Load one book directory into a :class:`BookTelemetry`."""
    store = LedgerStore(Path(book_dir))
    state = store.load_state()
    records = store.ledger_records()
    traded = [r for r in records if r.get("status") == "TRADED" and not r.get("dry_run")]
    skipped = [r for r in records if r.get("status") == "SKIPPED"]

    equity = store.equity_series()
    if not traded:
        daily = pd.Series(dtype=float)
    else:
        daily = pd.Series(
            [float(r.get("daily_return", 0.0)) for r in traded],
            index=pd.to_datetime([r["date"] for r in traded]),
        )

    last_record = records[-1] if records else {}
    recent_orders: list[dict[str, Any]] = []
    for r in reversed(traded):
        for order in r.get("orders", []):
            recent_orders.append({"date": r["date"], **order})
            if len(recent_orders) >= recent:
                break
        if len(recent_orders) >= recent:
            break

    return BookTelemetry(
        name=name or Path(book_dir).name,
        lane=lane or Path(book_dir).parent.name,
        root=str(book_dir),
        state=state,
        equity=equity,
        daily_returns=daily,
        n_records=len(records),
        n_traded=len(traded),
        n_skipped=len(skipped),
        last_record=last_record,
        recent_orders=recent_orders,
        recent_fills=_read_jsonl_tail(store.fills_path, recent),
    )


def summarise_books(logs_root: Path, *, recent: int = 20) -> dict[str, Any]:
    """One JSON-safe payload describing every paper book under ``logs_root``."""
    books = [
        book_telemetry(path, lane=lane, name=name, recent=recent).to_json()
        for lane, name, path in discover_books(logs_root)
    ]
    total_equity = sum(
        b["equity_values"][-1] for b in books if b["equity_values"]
    )
    return {
        "generated_utc": pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M:%SZ"),
        "n_books": len(books),
        "total_marked_equity": round(float(total_equity), 2),
        "any_halted": any(b["halted"] for b in books),
        "open_incidents": sum(len(b["open_incidents"]) for b in books),
        "books": books,
    }
