"""Unit tests for the trading-engine bootstrap (src/main.py).

Covers the production-hardening wiring added so that order persistence and
crash recovery are actually engaged at startup, plus the live-trading and
mode/port guards. All external dependencies (PostgreSQL, broker) are mocked.

Mode-by-mode contract for order persistence:
- live  : persistence MANDATORY -- refuse to start if the DB is unreachable.
- paper : persistence optional -- warn and continue if the DB is unreachable.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
import src.main as main

# ---------------------------------------------------------------------------
# Fakes for the PostgreSQL client used by _connect_order_store
# ---------------------------------------------------------------------------

class _FakeSession:
    def __init__(self, execute_exc=None):
        self._execute_exc = execute_exc

    async def execute(self, *_args, **_kwargs):
        if self._execute_exc is not None:
            raise self._execute_exc
        return MagicMock()


class _FakeClient:
    """Mimics PostgreSQLClient.session() as an async context manager."""

    def __init__(self, *, session_exc=None, execute_exc=None):
        self._session_exc = session_exc
        self._execute_exc = execute_exc

    @asynccontextmanager
    async def session(self):
        if self._session_exc is not None:
            raise self._session_exc
        yield _FakeSession(self._execute_exc)


def _patch_pg_client(monkeypatch, client_or_exc):
    """Patch libs.database.postgres.client.get_postgres_client."""
    if isinstance(client_or_exc, Exception):
        def _factory():
            raise client_or_exc
    else:
        def _factory():
            return client_or_exc
    monkeypatch.setattr(
        "libs.database.postgres.client.get_postgres_client", _factory, raising=True
    )


# ---------------------------------------------------------------------------
# _connect_order_store
# ---------------------------------------------------------------------------

class TestConnectOrderStore:
    @pytest.mark.asyncio
    async def test_client_unavailable_returns_none(self, monkeypatch):
        _patch_pg_client(monkeypatch, RuntimeError("no config"))
        assert await main._connect_order_store() is None

    @pytest.mark.asyncio
    async def test_probe_failure_returns_none(self, monkeypatch):
        _patch_pg_client(monkeypatch, _FakeClient(execute_exc=OSError("conn refused")))
        assert await main._connect_order_store() is None

    @pytest.mark.asyncio
    async def test_session_failure_returns_none(self, monkeypatch):
        _patch_pg_client(monkeypatch, _FakeClient(session_exc=OSError("pool exhausted")))
        assert await main._connect_order_store() is None

    @pytest.mark.asyncio
    async def test_success_returns_order_store(self, monkeypatch):
        _patch_pg_client(monkeypatch, _FakeClient())
        store = await main._connect_order_store()
        assert isinstance(store, main.OrderStore)


# ---------------------------------------------------------------------------
# _build_order_store -- mode-dependent policy
# ---------------------------------------------------------------------------

class TestBuildOrderStorePolicy:
    @pytest.mark.asyncio
    async def test_paper_explicitly_disabled_returns_none(self, monkeypatch):
        monkeypatch.setenv("FEATURE_ORDER_PERSISTENCE_ENABLED", "false")
        # _connect must not even be called when explicitly disabled.
        sentinel = AsyncMock(side_effect=AssertionError("should not connect"))
        monkeypatch.setattr(main, "_connect_order_store", sentinel)
        assert await main._build_order_store(paper_trading=True) is None

    @pytest.mark.asyncio
    async def test_live_explicitly_disabled_raises(self, monkeypatch):
        monkeypatch.setenv("FEATURE_ORDER_PERSISTENCE_ENABLED", "false")
        with pytest.raises(RuntimeError, match="requires order persistence"):
            await main._build_order_store(paper_trading=False)

    @pytest.mark.asyncio
    async def test_paper_db_unreachable_returns_none(self, monkeypatch):
        monkeypatch.delenv("FEATURE_ORDER_PERSISTENCE_ENABLED", raising=False)
        monkeypatch.setattr(main, "_connect_order_store", AsyncMock(return_value=None))
        assert await main._build_order_store(paper_trading=True) is None

    @pytest.mark.asyncio
    async def test_live_db_unreachable_raises(self, monkeypatch):
        monkeypatch.delenv("FEATURE_ORDER_PERSISTENCE_ENABLED", raising=False)
        monkeypatch.setattr(main, "_connect_order_store", AsyncMock(return_value=None))
        with pytest.raises(RuntimeError, match="requires order persistence"):
            await main._build_order_store(paper_trading=False)

    @pytest.mark.asyncio
    async def test_paper_db_available_returns_store(self, monkeypatch):
        monkeypatch.delenv("FEATURE_ORDER_PERSISTENCE_ENABLED", raising=False)
        store = MagicMock()
        monkeypatch.setattr(main, "_connect_order_store", AsyncMock(return_value=store))
        assert await main._build_order_store(paper_trading=True) is store

    @pytest.mark.asyncio
    async def test_live_db_available_returns_store(self, monkeypatch):
        monkeypatch.setenv("FEATURE_ORDER_PERSISTENCE_ENABLED", "true")
        store = MagicMock()
        monkeypatch.setattr(main, "_connect_order_store", AsyncMock(return_value=store))
        assert await main._build_order_store(paper_trading=False) is store


# ---------------------------------------------------------------------------
# _read_env -- live-trading and mode/port guards
# ---------------------------------------------------------------------------

def _clear_ibkr_env(monkeypatch):
    for var in (
        "IBKR_HOST", "IBKR_PORT", "IBKR_CLIENT_ID", "IBKR_ACCOUNT_ID",
        "IBKR_TRADING_MODE", "FEATURE_LIVE_TRADING_ENABLED",
    ):
        monkeypatch.delenv(var, raising=False)


class TestReadEnvGuards:
    def test_valid_paper_defaults(self, monkeypatch):
        _clear_ibkr_env(monkeypatch)
        monkeypatch.setenv("IBKR_ACCOUNT_ID", "DU123456")
        cfg = main._read_env()
        assert cfg["paper_trading"] is True
        assert cfg["port"] == 7497

    def test_missing_account_id_raises(self, monkeypatch):
        _clear_ibkr_env(monkeypatch)
        with pytest.raises(ValueError, match="IBKR_ACCOUNT_ID"):
            main._read_env()

    def test_invalid_mode_raises(self, monkeypatch):
        _clear_ibkr_env(monkeypatch)
        monkeypatch.setenv("IBKR_ACCOUNT_ID", "DU123456")
        monkeypatch.setenv("IBKR_TRADING_MODE", "sim")
        with pytest.raises(ValueError, match="IBKR_TRADING_MODE"):
            main._read_env()

    def test_paper_on_live_port_raises(self, monkeypatch):
        _clear_ibkr_env(monkeypatch)
        monkeypatch.setenv("IBKR_ACCOUNT_ID", "DU123456")
        monkeypatch.setenv("IBKR_TRADING_MODE", "paper")
        monkeypatch.setenv("IBKR_PORT", "7496")
        with pytest.raises(ValueError, match="7496"):
            main._read_env()

    def test_live_on_paper_port_raises(self, monkeypatch):
        _clear_ibkr_env(monkeypatch)
        monkeypatch.setenv("IBKR_ACCOUNT_ID", "U123456")
        monkeypatch.setenv("IBKR_TRADING_MODE", "live")
        monkeypatch.setenv("FEATURE_LIVE_TRADING_ENABLED", "true")
        monkeypatch.setenv("IBKR_PORT", "7497")
        with pytest.raises(ValueError, match="7497"):
            main._read_env()

    def test_live_without_feature_flag_raises(self, monkeypatch):
        _clear_ibkr_env(monkeypatch)
        monkeypatch.setenv("IBKR_ACCOUNT_ID", "U123456")
        monkeypatch.setenv("IBKR_TRADING_MODE", "live")
        monkeypatch.setenv("IBKR_PORT", "7496")
        with pytest.raises(ValueError, match="FEATURE_LIVE_TRADING_ENABLED"):
            main._read_env()

    def test_valid_live_with_flag_and_port(self, monkeypatch):
        _clear_ibkr_env(monkeypatch)
        monkeypatch.setenv("IBKR_ACCOUNT_ID", "U123456")
        monkeypatch.setenv("IBKR_TRADING_MODE", "live")
        monkeypatch.setenv("FEATURE_LIVE_TRADING_ENABLED", "true")
        monkeypatch.setenv("IBKR_PORT", "7496")
        cfg = main._read_env()
        assert cfg["paper_trading"] is False
        assert cfg["port"] == 7496
