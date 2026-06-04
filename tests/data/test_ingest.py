"""Tests for core_trading.data.ingest (Phase 1 ingestion CLI).

All tests run offline: the vendor source is a fake BarSource yielding a
synthetic frame, and storage is either a recording fake or the no-op BarStore.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pandas as pd
import pytest

from core_trading.data.bars import (
    Bar,
    BarRequest,
    BarResolution,
    BarSource,
    BarSourceCapabilities,
)
from core_trading.data.ingest import (
    _RESOLUTION_SECONDS,
    IngestResult,
    build_request,
    main,
    make_source,
    run_ingest,
)
from core_trading.data.quality import QualityReport
from core_trading.data.storage import BarStore

# ---------------------------------------------------------------------------
# Fixtures / fakes
# ---------------------------------------------------------------------------


def _make_frame(symbols: tuple[str, ...] = ("AAPL", "MSFT"), n: int = 10) -> pd.DataFrame:
    """A clean synthetic bar frame in the standard (symbol, timestamp) shape."""
    bars = []
    for symbol in symbols:
        base = 100.0 if symbol == "AAPL" else 200.0
        for i in range(n):
            ts = datetime(2024, 1, 1, tzinfo=UTC) + pd.Timedelta(days=i)
            close = base + i
            bars.append(
                Bar(
                    symbol=symbol,
                    timestamp=ts,
                    resolution=BarResolution.DAY_1,
                    open=close - 0.5,
                    high=close + 1.0,
                    low=close - 1.0,
                    close=close,
                    volume=1_000.0 + i,
                    source="fake",
                )
            )
    return BarSource.bars_to_dataframe(bars)


class FakeSource(BarSource):
    """A BarSource returning a pre-built frame, recording the request."""

    def __init__(self, frame: pd.DataFrame) -> None:
        self._frame = frame
        self.last_request: BarRequest | None = None

    @property
    def capabilities(self) -> BarSourceCapabilities:
        return BarSourceCapabilities(
            name="fake",
            supports_resolutions=frozenset({BarResolution.DAY_1}),
            supports_extended_hours=False,
            supports_adjusted=False,
            supports_unadjusted=True,
            max_history_days=None,
            rate_limit_per_minute=None,
            requires_api_key=False,
        )

    async def fetch_bars(self, request: BarRequest) -> pd.DataFrame:
        self.last_request = request
        return self._frame

    async def stream_bars(self, _request: BarRequest) -> AsyncIterator[Bar]:
        raise NotImplementedError  # not used by the ingest path
        yield  # pragma: no cover

    def __repr__(self) -> str:  # aid debugging on assertion failures
        return f"FakeSource(rows={len(self._frame)})"


class RecordingStore(BarStore):
    """A BarStore that records store_bars calls instead of touching ClickHouse."""

    def __init__(self) -> None:
        super().__init__(client=None)
        self.calls: list[tuple[int, BarResolution]] = []

    def store_bars(self, df: pd.DataFrame, resolution: BarResolution) -> int:
        self.calls.append((len(df), resolution))
        return len(df)


# ---------------------------------------------------------------------------
# build_request
# ---------------------------------------------------------------------------


class TestBuildRequest:
    def test_explicit_symbols(self) -> None:
        req = build_request(symbols=("aapl", " msft "), years=2.0)
        assert req.symbols == ("AAPL", "MSFT")
        assert req.resolution is BarResolution.DAY_1
        span_days = (req.end - req.start).days
        assert 728 <= span_days <= 732

    def test_universe_resolution(self) -> None:
        req = build_request(universe="SP100", years=1.0)
        assert "AAPL" in req.symbols
        assert len(req.symbols) >= 90

    def test_explicit_end(self) -> None:
        end = datetime(2025, 6, 1, tzinfo=UTC)
        req = build_request(symbols=("AAPL",), years=1.0, end=end)
        assert req.end == end
        assert req.start.year == 2024

    def test_both_symbols_and_universe_raises(self) -> None:
        with pytest.raises(ValueError, match="exactly one"):
            build_request(symbols=("AAPL",), universe="SP100")

    def test_neither_raises(self) -> None:
        with pytest.raises(ValueError, match="exactly one"):
            build_request()

    def test_nonpositive_years_raises(self) -> None:
        with pytest.raises(ValueError, match="years"):
            build_request(symbols=("AAPL",), years=0.0)

    def test_unknown_universe_raises(self) -> None:
        with pytest.raises(KeyError, match="Unknown universe"):
            build_request(universe="NOPE")

    def test_empty_universe_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from datetime import date

        from core_trading.data.universe import Universe

        empty = Universe(
            name="EMPTY",
            description="no members",
            snapshot_date=date(2026, 1, 1),
            is_vintage=False,
            memberships=(),
        )
        monkeypatch.setattr("core_trading.data.ingest.get_universe", lambda _name: empty)
        with pytest.raises(ValueError, match="resolved to no symbols"):
            build_request(universe="EMPTY")

    def test_blank_symbols_raise(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            build_request(symbols=("", "  "))


# ---------------------------------------------------------------------------
# make_source
# ---------------------------------------------------------------------------


class TestMakeSource:
    def test_yfinance(self) -> None:
        src = make_source("yfinance")
        assert src.capabilities.name == "yfinance"

    def test_ibkr(self) -> None:
        src = make_source(" IBKR ")
        assert src.capabilities.name == "ibkr"

    def test_unknown_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown source"):
            make_source("bloomberg")


# ---------------------------------------------------------------------------
# run_ingest
# ---------------------------------------------------------------------------


def _request() -> BarRequest:
    return build_request(symbols=("AAPL", "MSFT"), years=1.0)


class TestRunIngest:
    def test_fetch_validate_store(self) -> None:
        source = FakeSource(_make_frame())
        store = RecordingStore()
        result = run_ingest(source, _request(), store)

        assert result.rows_fetched == 20
        assert result.rows_stored == 20
        assert store.calls == [(20, BarResolution.DAY_1)]
        assert not result.report.has_errors
        assert source.last_request is not None

    def test_dry_run_skips_store(self) -> None:
        source = FakeSource(_make_frame())
        store = RecordingStore()
        result = run_ingest(source, _request(), store, dry_run=True)

        assert result.rows_fetched == 20
        assert result.rows_stored == 0
        assert store.calls == []

    def test_empty_fetch_skips_store(self) -> None:
        source = FakeSource(BarSource.bars_to_dataframe([]))
        store = RecordingStore()
        result = run_ingest(source, _request(), store)

        assert result.rows_fetched == 0
        assert result.rows_stored == 0
        assert store.calls == []
        assert result.report.has_warnings  # "empty" warning from the validator

    def test_default_store_is_noop_offline(self) -> None:
        # No store argument: falls back to the singleton, which has no client
        # in the test environment and stores 0 rows.
        source = FakeSource(_make_frame())
        result = run_ingest(source, _request())
        assert result.rows_fetched == 20
        assert result.rows_stored == 0

    def test_quality_gap_check_receives_resolution(self) -> None:
        assert BarResolution.DAY_1 in _RESOLUTION_SECONDS
        source = FakeSource(_make_frame())
        result = run_ingest(source, _request(), RecordingStore())
        # Clean daily synthetic data: no gap issues at 1d nominal resolution.
        assert all(i.category != "time_gap" for i in result.report.issues)


# ---------------------------------------------------------------------------
# IngestResult.failed
# ---------------------------------------------------------------------------


def _result_with(severity: str | None) -> IngestResult:
    report = QualityReport(source="fake", n_rows=1, n_symbols=1)
    if severity is not None:
        from core_trading.data.quality import QualityIssue

        report.issues.append(QualityIssue(severity, "test", None, "detail"))
    return IngestResult(rows_fetched=1, rows_stored=1, report=report)


class TestFailed:
    def test_clean_passes_both_levels(self) -> None:
        res = _result_with(None)
        assert not res.failed("error")
        assert not res.failed("warn")

    def test_error_fails_both_levels(self) -> None:
        res = _result_with("error")
        assert res.failed("error")
        assert res.failed("warn")

    def test_warn_fails_only_warn_level(self) -> None:
        res = _result_with("warn")
        assert not res.failed("error")
        assert res.failed("warn")

    def test_invalid_level_raises(self) -> None:
        with pytest.raises(ValueError, match="fail_on"):
            _result_with(None).failed("info")


# ---------------------------------------------------------------------------
# main() CLI
# ---------------------------------------------------------------------------


class TestMain:
    def _patch_source(self, monkeypatch: pytest.MonkeyPatch, frame: pd.DataFrame) -> FakeSource:
        source = FakeSource(frame)
        monkeypatch.setattr("core_trading.data.ingest.make_source", lambda _name: source)
        return source

    def test_ok_run(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        self._patch_source(monkeypatch, _make_frame())
        code = main(["--symbols", "AAPL,MSFT", "--years", "1", "--dry-run"])
        out = capsys.readouterr().out
        assert code == 0
        assert "[ingest] OK" in out
        assert "fetched 20 rows, stored 0 rows" in out

    def test_empty_fetch_exits_2(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._patch_source(monkeypatch, BarSource.bars_to_dataframe([]))
        code = main(["--symbols", "AAPL", "--dry-run"])
        out = capsys.readouterr().out
        assert code == 2
        assert "no rows" in out

    def test_quality_failure_exits_1(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # An empty frame produces a warn-severity "empty" issue, but exits 2
        # first; to hit exit 1 we need rows plus a warning at --fail-on=warn.
        frame = _make_frame(symbols=("AAPL",), n=300)
        # Plant a >10-sigma single-bar price spike to trigger the warn issue.
        ts = frame.index.get_level_values("timestamp")[150]
        frame.loc[("AAPL", ts), "close"] = 10_000.0
        self._patch_source(monkeypatch, frame)
        code = main(["--symbols", "AAPL", "--dry-run", "--fail-on", "warn"])
        out = capsys.readouterr().out
        assert code == 1
        assert "quality gate" in out
        assert "[WARN]" in out

    def test_universe_argument(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        self._patch_source(monkeypatch, _make_frame())
        code = main(["--universe", "SP100", "--years", "1", "--dry-run"])
        out = capsys.readouterr().out
        assert code == 0
        assert "symbols, 1d bars" in out

    def test_mutually_exclusive_args(self) -> None:
        with pytest.raises(SystemExit):
            main(["--symbols", "AAPL", "--universe", "SP100"])

    def test_requires_symbols_or_universe(self) -> None:
        with pytest.raises(SystemExit):
            main([])
