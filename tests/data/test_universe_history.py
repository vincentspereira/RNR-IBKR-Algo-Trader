"""Unit tests for core_trading.data.universe_history (PIT S&P 500 loader)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from core_trading.data.universe_history import (
    DEFAULT_SP500_PIT_CSV,
    load_sp500_pit,
)


def _write_csv(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "members.csv"
    p.write_text(text, encoding="utf-8")
    return p


class TestLoadSyntheticCsv:
    def test_membership_windows(self, tmp_path: Path) -> None:
        p = _write_csv(
            tmp_path,
            "ticker,start_date,end_date\n"
            "AAA,2000-01-01,2010-01-01\n"
            "BBB,2005-01-01,\n"
            "AAA,2015-01-01,\n",
        )
        u = load_sp500_pit(p)
        assert u.is_vintage is True
        assert u.members_on(date(1999, 12, 31)) == ()
        assert u.members_on(date(2004, 6, 1)) == ("AAA",)
        assert u.members_on(date(2007, 6, 1)) == ("AAA", "BBB")
        # AAA removed 2010-01-01 (exclusive of the removal date itself)
        assert u.members_on(date(2012, 6, 1)) == ("BBB",)
        # AAA second spell
        assert u.members_on(date(2016, 6, 1)) == ("AAA", "BBB")

    def test_yahoo_symbol_translation(self, tmp_path: Path) -> None:
        p = _write_csv(
            tmp_path,
            "ticker,start_date,end_date\nBRK.B,2010-02-16,\n",
        )
        assert load_sp500_pit(p).members_on(date(2020, 1, 1)) == ("BRK-B",)
        assert load_sp500_pit(p, yahoo_symbols=False).members_on(date(2020, 1, 1)) == (
            "BRK.B",
        )

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="PIT membership CSV"):
            load_sp500_pit(tmp_path / "nope.csv")

    def test_bad_header_raises(self, tmp_path: Path) -> None:
        p = _write_csv(tmp_path, "symbol,from,to\nAAA,2000-01-01,\n")
        with pytest.raises(ValueError, match="must have columns"):
            load_sp500_pit(p)

    def test_inverted_dates_raise(self, tmp_path: Path) -> None:
        p = _write_csv(
            tmp_path, "ticker,start_date,end_date\nAAA,2010-01-01,2005-01-01\n"
        )
        with pytest.raises(ValueError, match="end_date"):
            load_sp500_pit(p)

    def test_empty_rows_raise(self, tmp_path: Path) -> None:
        p = _write_csv(tmp_path, "ticker,start_date,end_date\n")
        with pytest.raises(ValueError, match="no membership rows"):
            load_sp500_pit(p)


@pytest.mark.skipif(
    not DEFAULT_SP500_PIT_CSV.exists(), reason="checked-in dataset missing"
)
class TestCheckedInDataset:
    def test_loads_and_is_plausible(self) -> None:
        u = load_sp500_pit()
        assert u.is_vintage is True
        # ~500 members on any post-2001 business day
        for d in (date(2005, 1, 3), date(2015, 1, 2), date(2025, 1, 2)):
            n = len(u.members_on(d))
            assert 480 <= n <= 520, f"{d}: {n} members"

    def test_known_history_facts(self) -> None:
        u = load_sp500_pit()
        # Lehman (dataset uses its final OTC symbol LEHMQ) was a member in
        # 2007, gone by 2009.
        assert "LEHMQ" in u.members_on(date(2007, 6, 1))
        assert "LEHMQ" not in u.members_on(date(2009, 6, 1))
        # TSLA joined late 2020: not a member in 2015.
        assert "TSLA" not in u.members_on(date(2015, 6, 1))
        assert "TSLA" in u.members_on(date(2022, 6, 1))
        # Yahoo dash convention applied.
        assert "BRK-B" in u.members_on(date(2020, 1, 2))
