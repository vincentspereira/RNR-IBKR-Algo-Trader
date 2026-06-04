"""Historical bar ingestion CLI (Phase 1 operator entry point).

The one-command path from "empty ClickHouse" to "validated 5-year daily bar
history": resolve a symbol list (explicit or from a built-in universe), fetch
bars from a vendor adapter, run the Phase 1.8 quality gate, and persist the
frame through :class:`~core_trading.data.storage.BarStore`.

Usage (see docs/PHASE1_OPERATOR_RUNBOOK.md for the full runbook)::

    # 5 years of daily bars for the S&P 100, validated and stored
    python -m core_trading.data.ingest --universe SP100 --years 5

    # explicit symbols, dry run (fetch + validate, no storage)
    python -m core_trading.data.ingest --symbols AAPL,MSFT --years 2 --dry-run

    # IBKR as the vendor (requires a running TWS / Gateway)
    python -m core_trading.data.ingest --universe SP100 --source ibkr

Exit codes: ``0`` success; ``1`` the quality gate failed at the configured
``--fail-on`` level; ``2`` the fetch returned no rows.

Design notes:

* The CLI is a thin shell over :func:`build_request` / :func:`make_source` /
  :func:`run_ingest`, each independently unit-testable without a network or a
  ClickHouse server.
* Storage degrades gracefully: with no ClickHouse client,
  :class:`~core_trading.data.storage.BarStore` runs in no-op mode and the CLI
  reports ``stored 0 rows`` -- fetch and validation still execute, so the
  command doubles as a vendor smoke test.
* All output is ASCII (Windows cp1252 console).
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta

from core_trading.data.bars import BarRequest, BarResolution, BarSource, utc_now
from core_trading.data.quality import QualityReport, validate_bar_frame
from core_trading.data.storage import BarStore, get_bar_store
from core_trading.data.universe import get_universe

__all__ = [
    "IngestResult",
    "build_request",
    "make_source",
    "run_ingest",
    "main",
]


_RESOLUTION_SECONDS: dict[BarResolution, int] = {
    BarResolution.MINUTE_1: 60,
    BarResolution.MINUTE_5: 300,
    BarResolution.MINUTE_15: 900,
    BarResolution.MINUTE_30: 1_800,
    BarResolution.HOUR_1: 3_600,
    BarResolution.HOUR_4: 14_400,
    BarResolution.DAY_1: 86_400,
    BarResolution.WEEK_1: 604_800,
    BarResolution.MONTH_1: 2_592_000,
}
"""Nominal bar duration used for the time-gap quality check."""


@dataclass(frozen=True, slots=True)
class IngestResult:
    """Outcome of one ingestion run."""

    rows_fetched: int
    rows_stored: int
    report: QualityReport

    def failed(self, fail_on: str) -> bool:
        """Whether the quality gate fails at the given level.

        ``fail_on="error"`` fails only on error-severity issues;
        ``fail_on="warn"`` fails on warnings too.
        """
        if fail_on not in {"error", "warn"}:
            raise ValueError("fail_on must be 'error' or 'warn'")
        if self.report.has_errors:
            return True
        return fail_on == "warn" and self.report.has_warnings


def build_request(
    *,
    symbols: tuple[str, ...] | None = None,
    universe: str | None = None,
    years: float = 5.0,
    resolution: BarResolution = BarResolution.DAY_1,
    end: datetime | None = None,
) -> BarRequest:
    """Build the :class:`BarRequest` for an ingestion run.

    Exactly one of ``symbols`` / ``universe`` must be provided. ``years`` is
    converted to a calendar window ending at ``end`` (default: now, UTC).
    """
    if (symbols is None) == (universe is None):
        raise ValueError("provide exactly one of symbols= or universe=")
    if years <= 0:
        raise ValueError("years must be > 0")

    if universe is not None:
        resolved = get_universe(universe).current_symbols()
        if not resolved:
            raise ValueError(f"universe {universe!r} resolved to no symbols")
    else:
        resolved = tuple(s.strip().upper() for s in (symbols or ()) if s.strip())
        if not resolved:
            raise ValueError("symbols= contained no non-empty entries")

    end_ts = end if end is not None else utc_now()
    start_ts = end_ts - timedelta(days=years * 365.25)
    return BarRequest(symbols=resolved, resolution=resolution, start=start_ts, end=end_ts)


def make_source(name: str) -> BarSource:
    """Instantiate a vendor adapter by name (``yfinance`` or ``ibkr``).

    Imports are deferred so the CLI works in environments missing one vendor's
    dependency stack.
    """
    key = name.strip().lower()
    if key == "yfinance":
        from core_trading.data.sources.yfinance_source import YFinanceBarSource

        return YFinanceBarSource()
    if key == "ibkr":
        from core_trading.data.sources.ibkr_source import IBKRBarSource

        return IBKRBarSource()
    raise ValueError(f"unknown source {name!r}; expected 'yfinance' or 'ibkr'")


def run_ingest(
    source: BarSource,
    request: BarRequest,
    store: BarStore | None = None,
    *,
    dry_run: bool = False,
) -> IngestResult:
    """Fetch, validate, and (unless ``dry_run``) persist bars.

    Validation always runs; storage is skipped on ``dry_run`` or when the
    fetched frame is empty. ``store=None`` uses the process-wide singleton.
    """
    df = asyncio.run(source.fetch_bars(request))
    report = validate_bar_frame(
        df,
        source.capabilities.name,
        expected_resolution_seconds=_RESOLUTION_SECONDS.get(request.resolution),
    )

    rows_stored = 0
    if not dry_run and not df.empty:
        target = store if store is not None else get_bar_store()
        rows_stored = target.store_bars(df, request.resolution)

    return IngestResult(rows_fetched=len(df), rows_stored=rows_stored, report=report)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m core_trading.data.ingest",
        description="Fetch, validate, and store historical OHLCV bars.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--universe",
        help="Built-in universe name (e.g. SP100, NDX, NIFTY50).",
    )
    group.add_argument(
        "--symbols",
        help="Comma-separated explicit symbol list (e.g. AAPL,MSFT).",
    )
    parser.add_argument(
        "--years",
        type=float,
        default=5.0,
        help="History window in calendar years (default: 5).",
    )
    parser.add_argument(
        "--resolution",
        default=BarResolution.DAY_1.value,
        choices=sorted(r.value for r in _RESOLUTION_SECONDS),
        help="Bar resolution (default: 1d).",
    )
    parser.add_argument(
        "--source",
        default="yfinance",
        choices=["yfinance", "ibkr"],
        help="Vendor adapter (default: yfinance; ibkr needs a running TWS).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and validate only; do not write to storage.",
    )
    parser.add_argument(
        "--fail-on",
        default="error",
        choices=["error", "warn"],
        help="Quality-gate severity that fails the run (default: error).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    args = _build_parser().parse_args(argv)

    request = build_request(
        symbols=tuple(args.symbols.split(",")) if args.symbols else None,
        universe=args.universe,
        years=args.years,
        resolution=BarResolution(args.resolution),
    )
    source = make_source(args.source)

    print(
        f"[ingest] {len(request.symbols)} symbols, {args.resolution} bars, "
        f"{request.start.date()} -> {request.end.date()}, source={args.source}"
    )
    result = run_ingest(source, request, dry_run=args.dry_run)

    print(result.report.summary())
    for issue in result.report.issues:
        print(f"[{issue.severity.upper()}] {issue.category} {issue.symbol or '-'}: {issue.detail}")
    print(f"[ingest] fetched {result.rows_fetched} rows, stored {result.rows_stored} rows")

    if result.rows_fetched == 0:
        print("[ingest] FAIL: fetch returned no rows")
        return 2
    if result.failed(args.fail_on):
        print(f"[ingest] FAIL: quality gate at --fail-on={args.fail_on}")
        return 1
    print("[ingest] OK")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via main() in tests
    raise SystemExit(main())
