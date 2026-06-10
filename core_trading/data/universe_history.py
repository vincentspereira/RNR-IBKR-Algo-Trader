"""Point-in-time (vintage) universe loading from free membership datasets.

This module turns the free historical S&P 500 membership dataset
(``data/universe/sp500_ticker_start_end.csv``, MIT-licensed, from the
fja05680/sp500 GitHub project, base list via Andreas Clenow's *Trading
Evolved*) into a :class:`~core_trading.data.universe.Universe` with
``is_vintage=True``, so walk-forward research can ask "who was a member on
this date" instead of projecting today's constituents backwards.

What this does and does not fix
-------------------------------
* FIXES index-selection survivorship: names that were members at the time
  but were later demoted or delisted are included on the dates they were
  members, and today's late joiners (e.g. TSLA pre-2020) are excluded
  before they joined.
* Does NOT fix price-data survivorship on its own: free price vendors
  (yfinance) only carry data for symbols that still trade. Demoted-but-
  still-listed names ("fallen angels") are fully recoverable; acquired or
  bankrupt names mostly are not. The coverage gap must be measured
  (``tools/pit_coverage_probe.py``) and stress-tested rather than ignored.

Ticker conventions
------------------
The CSV uses dot class-share notation (``BRK.B``); Yahoo uses dashes
(``BRK-B``). ``load_sp500_pit(yahoo_symbols=True)`` (the default)
translates dots to dashes so the symbols feed straight into the yfinance
source.
"""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from core_trading.data.universe import Universe, UniverseMembership

__all__ = ["DEFAULT_SP500_PIT_CSV", "load_sp500_pit"]

DEFAULT_SP500_PIT_CSV = (
    Path(__file__).resolve().parents[2] / "data" / "universe" / "sp500_ticker_start_end.csv"
)


def _parse_date(text: str) -> date | None:
    text = text.strip()
    if not text:
        return None
    return date.fromisoformat(text)


def load_sp500_pit(
    csv_path: Path | str | None = None,
    *,
    yahoo_symbols: bool = True,
) -> Universe:
    """Load the point-in-time S&P 500 membership history.

    Parameters
    ----------
    csv_path:
        Membership CSV with columns ``ticker,start_date,end_date`` (empty
        ``end_date`` = still a member). Defaults to the checked-in dataset.
    yahoo_symbols:
        Translate dot class-share tickers to Yahoo's dash form
        (``BRK.B`` -> ``BRK-B``). Default ``True``.

    Returns
    -------
    Universe
        ``is_vintage=True``; ``members_on(d)`` returns the true membership
        on ``d``. The snapshot date is the latest membership-change date in
        the file, so ``current_symbols()`` returns the most recent list.

    Raises
    ------
    FileNotFoundError
        If the CSV is missing (the dataset is checked in; a missing file
        means a broken checkout, not an optional feature).
    ValueError
        On malformed rows -- membership data errors must fail loudly, not
        silently shrink the universe.
    """
    path = Path(csv_path) if csv_path is not None else DEFAULT_SP500_PIT_CSV
    if not path.exists():
        raise FileNotFoundError(
            f"PIT membership CSV not found: {path}. "
            "Re-download from https://github.com/fja05680/sp500 "
            "(sp500_ticker_start_end.csv, MIT licence)."
        )

    memberships: list[UniverseMembership] = []
    latest = date.min
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        required = {"ticker", "start_date", "end_date"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ValueError(
                f"{path} must have columns {sorted(required)}; got {reader.fieldnames}"
            )
        for row_no, row in enumerate(reader, start=2):
            symbol = row["ticker"].strip()
            if not symbol:
                raise ValueError(f"{path}:{row_no}: empty ticker")
            if yahoo_symbols:
                symbol = symbol.replace(".", "-")
            added = _parse_date(row["start_date"])
            if added is None:
                raise ValueError(f"{path}:{row_no}: missing start_date for {symbol}")
            removed = _parse_date(row["end_date"])
            if removed is not None and removed <= added:
                raise ValueError(
                    f"{path}:{row_no}: end_date {removed} <= start_date {added} for {symbol}"
                )
            memberships.append(
                UniverseMembership(symbol=symbol, added=added, removed=removed)
            )
            latest = max(latest, added, removed or added)

    if not memberships:
        raise ValueError(f"{path}: no membership rows")

    return Universe(
        name="SP500_PIT",
        description=(
            "S&P 500 point-in-time membership 1996+ (fja05680/sp500, MIT; "
            "base list via Clenow's Trading Evolved). Membership is vintage; "
            "price-data coverage for delisted names is NOT guaranteed."
        ),
        snapshot_date=latest,
        is_vintage=True,
        memberships=tuple(memberships),
    )
