"""Unit tests for core_trading.data.universe."""
from __future__ import annotations

from datetime import date

import pytest

from core_trading.data.universe import (
    BUILTIN_UNIVERSES,
    NASDAQ100,
    NIFTY50,
    SP100,
    Universe,
    UniverseMembership,
    get_universe,
)


class TestUniverseMembership:
    def test_lifetime_membership(self) -> None:
        m = UniverseMembership(symbol="AAPL", added=date(2020, 1, 1))
        assert m.is_member_on(date(2020, 1, 1))
        assert m.is_member_on(date(2030, 1, 1))
        assert not m.is_member_on(date(2019, 12, 31))

    def test_removed_excludes_after(self) -> None:
        m = UniverseMembership(
            symbol="LEHM", added=date(1990, 1, 1), removed=date(2008, 9, 15)
        )
        assert m.is_member_on(date(2008, 9, 14))
        assert not m.is_member_on(date(2008, 9, 15))
        assert not m.is_member_on(date(2010, 1, 1))


class TestBuiltinUniverses:
    def test_sp100_starter(self) -> None:
        assert SP100.name == "SP100"
        assert "AAPL" in SP100.current_symbols()
        assert "MSFT" in SP100.current_symbols()
        assert SP100.is_vintage is False

    def test_nasdaq_starter(self) -> None:
        assert "NVDA" in NASDAQ100.current_symbols()
        assert "META" in NASDAQ100.current_symbols()

    def test_nifty_starter(self) -> None:
        assert "RELIANCE.NS" in NIFTY50.current_symbols()
        assert "TCS.NS" in NIFTY50.current_symbols()

    def test_static_snapshot_returns_empty_before_snapshot_date(self) -> None:
        before = SP100.members_on(date(2026, 5, 27))
        assert before == ()

    def test_static_snapshot_returns_full_on_or_after_snapshot_date(self) -> None:
        on = SP100.members_on(SP100.snapshot_date)
        assert "AAPL" in on

    def test_get_universe_by_name(self) -> None:
        u = get_universe("SP100")
        assert u is SP100

    def test_get_universe_unknown_raises(self) -> None:
        with pytest.raises(KeyError, match="Unknown universe"):
            get_universe("NONEXISTENT")

    def test_builtin_registry_consistent(self) -> None:
        for name in ("SP100", "NDX", "NIFTY50"):
            u = BUILTIN_UNIVERSES[name]
            assert isinstance(u, Universe)
            assert u.current_symbols(), f"{name} has empty current symbols"
