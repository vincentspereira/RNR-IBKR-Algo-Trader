"""Comprehensive unit tests for OrderStore (PostgreSQL persistence).

All external dependencies (PostgreSQL, broker adapter) are fully mocked.
Tests cover:
- Save (insert and update paths)
- Retrieval by ID, active status, and symbol
- Status and fill updates
- Startup reconciliation with various broker state scenarios
- Order-to-dict normalization
"""

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.engines.execution_engine import (
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
)
from src.persistence.order_store import OrderStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_order(**overrides):
    """Create a valid Order with sensible defaults."""
    defaults = dict(
        instrument="AAPL",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=100,
        price=150.0,
    )
    defaults.update(overrides)
    return Order(**defaults)


class _InMemorySession:
    """In-memory mock of SQLAlchemy async session.

    Routes execute() calls based on the text clause content, matching
    the actual SQL patterns used in OrderStore.
    """

    def __init__(self):
        self._rows = {}  # order_id -> dict

    @asynccontextmanager
    async def session(self):
        yield self

    def _has(self, sql_text, pattern):
        """Case-insensitive substring match on SQL text."""
        return pattern.lower() in sql_text.lower()

    async def execute(self, stmt, params=None):
        sql_text = str(stmt)

        # --- SELECT by order_id ---
        if self._has(sql_text, "SELECT") and self._has(sql_text, "WHERE order_id"):
            order_id = params.get("order_id") if params else None
            row = self._rows.get(order_id)
            result = MagicMock()
            result.first.return_value = row
            mapping = MagicMock()
            mapping.first.return_value = row
            mapping.all.return_value = [row] if row else []
            result.mappings.return_value = mapping
            return result

        # --- SELECT active orders (by STATUS IN ...) ---
        if self._has(sql_text, "SELECT") and self._has(sql_text, "STATUS IN"):
            active = [
                v for v in self._rows.values()
                if v.get("status", "").upper()
                in ("PENDING", "SUBMITTED", "PARTIALLY_FILLED")
            ]
            result = MagicMock()
            mapping = MagicMock()
            mapping.all.return_value = active
            result.mappings.return_value = mapping
            return result

        # --- SELECT by symbol ---
        if self._has(sql_text, "SELECT") and self._has(sql_text, "WHERE symbol"):
            symbol = params.get("symbol") if params else None
            matched = [v for v in self._rows.values() if v.get("symbol") == symbol]
            result = MagicMock()
            mapping = MagicMock()
            mapping.all.return_value = matched
            result.mappings.return_value = mapping
            return result

        # --- INSERT ---
        if self._has(sql_text, "INSERT"):
            order_id = params.get("order_id") if params else None
            if order_id:
                self._rows[order_id] = dict(params)
            return MagicMock()

        # --- UPDATE ---
        if self._has(sql_text, "UPDATE"):
            order_id = params.get("order_id") if params else None
            if order_id:
                if order_id in self._rows:
                    self._rows[order_id].update(params)
                else:
                    self._rows[order_id] = dict(params)
            return MagicMock()

        return MagicMock()


class _InMemoryDB:
    """Mock PostgreSQL client backed by an in-memory session."""

    def __init__(self):
        self._session = _InMemorySession()

    def session(self):
        return self._session.session()


def _make_store_with_db():
    """Create an OrderStore backed by an in-memory mock database."""
    db = _InMemoryDB()
    store = OrderStore(postgres_client=db)
    return store, db


class _MockBrokerAdapter:
    """Mock broker adapter for reconciliation tests."""

    def __init__(self):
        self._order_statuses = {}

    def set_order_status(self, broker_order_id, status_data):
        self._order_statuses[broker_order_id] = status_data

    async def get_order_status(self, broker_order_id):
        return self._order_statuses.get(broker_order_id, {"status": "unknown"})

    async def cancel_order(self, order_id):
        pass

    async def get_positions(self):
        return []


# ---------------------------------------------------------------------------
# Tests: Save Order
# ---------------------------------------------------------------------------

class TestSaveOrder:
    """Tests for OrderStore.save_order."""

    @pytest.mark.asyncio
    async def test_save_order_new(self):
        store, db = _make_store_with_db()
        order = _make_order()

        result = await store.save_order(order)

        assert result is True
        assert order.order_id in db._session._rows

    @pytest.mark.asyncio
    async def test_save_order_update_existing(self):
        store, db = _make_store_with_db()
        order = _make_order()

        # First save inserts
        await store.save_order(order)
        assert len(db._session._rows) == 1

        # Second save updates (row found by SELECT)
        order.quantity = 200
        result = await store.save_order(order)

        assert result is True
        assert db._session._rows[order.order_id]["quantity"] == 200.0

    @pytest.mark.asyncio
    async def test_save_order_no_db_client(self):
        """When no database client is available, save_order returns False."""
        store = OrderStore(postgres_client=None)
        # Mock the module-level _get_postgres_client to return None
        with patch("src.persistence.order_store._get_postgres_client", return_value=None):
            result = await store.save_order(_make_order())
            assert result is False

    @pytest.mark.asyncio
    async def test_save_order_from_dict(self):
        store, db = _make_store_with_db()
        order_dict = {
            "order_id": "test-dict-001",
            "symbol": "AAPL",
            "side": "buy",
            "order_type": "limit",
            "quantity": 50,
            "price": 155.0,
            "status": "pending",
        }

        result = await store.save_order(order_dict)
        assert result is True

    @pytest.mark.asyncio
    async def test_save_order_handles_exception(self):
        """When session raises an exception, save_order returns False."""
        store = OrderStore(postgres_client=None)
        # Create a mock client whose session raises
        mock_client = MagicMock()
        mock_client.session.side_effect = Exception("connection lost")
        store._client = mock_client

        result = await store.save_order(_make_order())
        assert result is False


# ---------------------------------------------------------------------------
# Tests: Get Order
# ---------------------------------------------------------------------------

class TestGetOrder:
    """Tests for OrderStore.get_order."""

    @pytest.mark.asyncio
    async def test_get_order_by_id(self):
        store, db = _make_store_with_db()
        order = _make_order()
        await store.save_order(order)

        retrieved = await store.get_order(order.order_id)

        assert retrieved is not None
        assert retrieved["order_id"] == order.order_id

    @pytest.mark.asyncio
    async def test_get_order_not_found(self):
        store, _ = _make_store_with_db()

        result = await store.get_order("nonexistent_id")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_order_no_db_client(self):
        store = OrderStore(postgres_client=None)
        with patch("src.persistence.order_store._get_postgres_client", return_value=None):
            result = await store.get_order("any_id")
            assert result is None


# ---------------------------------------------------------------------------
# Tests: Get Active Orders
# ---------------------------------------------------------------------------

class TestGetActiveOrders:
    """Tests for OrderStore.get_active_orders."""

    @pytest.mark.asyncio
    async def test_get_active_orders(self):
        store, db = _make_store_with_db()

        # Insert an active order via save
        active_order = _make_order()
        active_order.status = OrderStatus.SUBMITTED
        await store.save_order(active_order)

        results = await store.get_active_orders()
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_get_active_orders_excludes_terminal(self):
        store, db = _make_store_with_db()

        # Insert orders directly into in-memory store
        db._session._rows["filled-1"] = {
            "order_id": "filled-1",
            "symbol": "AAPL",
            "status": "FILLED",
        }
        db._session._rows["cancelled-1"] = {
            "order_id": "cancelled-1",
            "symbol": "MSFT",
            "status": "CANCELLED",
        }
        db._session._rows["active-1"] = {
            "order_id": "active-1",
            "symbol": "GOOG",
            "status": "SUBMITTED",
        }

        results = await store.get_active_orders()
        order_ids = [r["order_id"] for r in results]
        assert "active-1" in order_ids
        assert "filled-1" not in order_ids
        assert "cancelled-1" not in order_ids

    @pytest.mark.asyncio
    async def test_get_active_orders_no_db_client(self):
        store = OrderStore(postgres_client=None)
        with patch("src.persistence.order_store._get_postgres_client", return_value=None):
            result = await store.get_active_orders()
            assert result == []


# ---------------------------------------------------------------------------
# Tests: Get Orders By Symbol
# ---------------------------------------------------------------------------

class TestGetOrdersBySymbol:
    """Tests for OrderStore.get_orders_by_symbol."""

    @pytest.mark.asyncio
    async def test_get_orders_by_symbol(self):
        store, db = _make_store_with_db()

        db._session._rows["ord-aapl"] = {
            "order_id": "ord-aapl",
            "symbol": "AAPL",
            "status": "SUBMITTED",
        }
        db._session._rows["ord-msft"] = {
            "order_id": "ord-msft",
            "symbol": "MSFT",
            "status": "PENDING",
        }

        aapl_orders = await store.get_orders_by_symbol("AAPL")
        assert len(aapl_orders) == 1
        assert aapl_orders[0]["order_id"] == "ord-aapl"

    @pytest.mark.asyncio
    async def test_get_orders_by_symbol_empty(self):
        store, _ = _make_store_with_db()

        result = await store.get_orders_by_symbol("TSLA")
        assert result == []


# ---------------------------------------------------------------------------
# Tests: Update Order Status
# ---------------------------------------------------------------------------

class TestUpdateOrderStatus:
    """Tests for OrderStore.update_order_status."""

    @pytest.mark.asyncio
    async def test_update_order_status(self):
        store, db = _make_store_with_db()
        order = _make_order()
        await store.save_order(order)

        result = await store.update_order_status(order.order_id, "SUBMITTED")
        assert result is True

    @pytest.mark.asyncio
    async def test_update_order_fill(self):
        store, db = _make_store_with_db()
        order = _make_order()
        await store.save_order(order)

        result = await store.update_order_status(
            order.order_id,
            "PARTIALLY_FILLED",
            filled_quantity=50,
            avg_fill_price=149.5,
        )
        assert result is True
        row = db._session._rows[order.order_id]
        assert row["filled_quantity"] == 50
        assert row["avg_fill_price"] == 149.5

    @pytest.mark.asyncio
    async def test_update_order_status_no_db_client(self):
        store = OrderStore(postgres_client=None)
        with patch("src.persistence.order_store._get_postgres_client", return_value=None):
            result = await store.update_order_status("x", "FILLED")
            assert result is False

    @pytest.mark.asyncio
    async def test_update_order_status_handles_exception(self):
        store = OrderStore(postgres_client=None)
        mock_client = MagicMock()
        mock_client.session.side_effect = Exception("connection lost")
        store._client = mock_client

        result = await store.update_order_status("x", "FILLED")
        assert result is False


# ---------------------------------------------------------------------------
# Tests: Reconcile On Startup
# ---------------------------------------------------------------------------

class TestReconcileOnStartup:
    """Tests for OrderStore.reconcile_on_startup."""

    @pytest.mark.asyncio
    async def test_reconcile_on_startup_match(self):
        """DB order matches broker status -- kept as-is."""
        store, db = _make_store_with_db()
        broker = _MockBrokerAdapter()

        db._session._rows["ord-1"] = {
            "order_id": "ord-1",
            "symbol": "AAPL",
            "status": "SUBMITTED",
            "broker_order_id": "BK-001",
        }
        broker.set_order_status("BK-001", {"status": "SUBMITTED"})

        summary = await store.reconcile_on_startup(broker)

        assert summary["db_active_orders"] == 1
        assert summary["reconciled"] == 1
        assert summary["cancelled_in_db"] == 0

    @pytest.mark.asyncio
    async def test_reconcile_on_startup_discrepancy(self):
        """DB says submitted but broker says filled -- DB updated."""
        store, db = _make_store_with_db()
        broker = _MockBrokerAdapter()

        db._session._rows["ord-2"] = {
            "order_id": "ord-2",
            "symbol": "MSFT",
            "status": "SUBMITTED",
            "broker_order_id": "BK-002",
        }
        broker.set_order_status("BK-002", {
            "status": "FILLED",
            "filled_quantity": 100,
            "avg_fill_price": 300.0,
            "commission": 1.5,
        })

        summary = await store.reconcile_on_startup(broker)

        assert summary["reconciled"] == 1
        row = db._session._rows.get("ord-2")
        assert row is not None
        assert row.get("status") == "FILLED"

    @pytest.mark.asyncio
    async def test_reconcile_on_startup_orphaned_db_order(self):
        """DB order with no broker_order_id -- cancelled in DB."""
        store, db = _make_store_with_db()
        broker = _MockBrokerAdapter()

        db._session._rows["ord-3"] = {
            "order_id": "ord-3",
            "symbol": "GOOG",
            "status": "PENDING",
            "broker_order_id": None,
        }

        summary = await store.reconcile_on_startup(broker)

        assert summary["cancelled_in_db"] == 1
        row = db._session._rows.get("ord-3")
        assert row is not None
        assert row.get("status") == "CANCELLED"

    @pytest.mark.asyncio
    async def test_reconcile_on_startup_broker_cancelled(self):
        """Broker says cancelled -- order cancelled in DB."""
        store, db = _make_store_with_db()
        broker = _MockBrokerAdapter()

        db._session._rows["ord-4"] = {
            "order_id": "ord-4",
            "symbol": "TSLA",
            "status": "SUBMITTED",
            "broker_order_id": "BK-004",
        }
        broker.set_order_status("BK-004", {"status": "CANCELLED"})

        summary = await store.reconcile_on_startup(broker)

        assert summary["cancelled_in_db"] == 1

    @pytest.mark.asyncio
    async def test_reconcile_on_startup_broker_rejected(self):
        """Broker says rejected -- order rejected in DB."""
        store, db = _make_store_with_db()
        broker = _MockBrokerAdapter()

        db._session._rows["ord-5"] = {
            "order_id": "ord-5",
            "symbol": "AMZN",
            "status": "SUBMITTED",
            "broker_order_id": "BK-005",
        }
        broker.set_order_status("BK-005", {"status": "REJECTED"})

        summary = await store.reconcile_on_startup(broker)

        assert summary["cancelled_in_db"] == 1

    @pytest.mark.asyncio
    async def test_reconcile_on_startup_broker_partial(self):
        """Broker says partially filled -- DB updated with fill data."""
        store, db = _make_store_with_db()
        broker = _MockBrokerAdapter()

        db._session._rows["ord-6"] = {
            "order_id": "ord-6",
            "symbol": "META",
            "status": "SUBMITTED",
            "broker_order_id": "BK-006",
        }
        broker.set_order_status("BK-006", {
            "status": "PARTIALLY_FILLED",
            "filled_quantity": 50,
            "avg_fill_price": 480.0,
        })

        summary = await store.reconcile_on_startup(broker)

        assert summary["reconciled"] == 1

    @pytest.mark.asyncio
    async def test_reconcile_on_startup_no_db_client(self):
        store = OrderStore(postgres_client=None)
        with patch("src.persistence.order_store._get_postgres_client", return_value=None):
            summary = await store.reconcile_on_startup(AsyncMock())
            assert summary["db_active_orders"] == 0

    @pytest.mark.asyncio
    async def test_reconcile_on_startup_no_broker_adapter(self):
        store, _ = _make_store_with_db()
        summary = await store.reconcile_on_startup(None)
        assert summary["db_active_orders"] == 0

    @pytest.mark.asyncio
    async def test_reconcile_on_startup_no_active_orders(self):
        store, _ = _make_store_with_db()
        broker = _MockBrokerAdapter()

        summary = await store.reconcile_on_startup(broker)

        assert summary["db_active_orders"] == 0
        assert summary["reconciled"] == 0

    @pytest.mark.asyncio
    async def test_reconcile_on_startup_broker_query_error(self):
        """Broker adapter throws during get_order_status -- error recorded."""
        store, db = _make_store_with_db()

        broker = AsyncMock()
        broker.get_order_status = AsyncMock(side_effect=Exception("timeout"))

        db._session._rows["ord-err"] = {
            "order_id": "ord-err",
            "symbol": "NVDA",
            "status": "SUBMITTED",
            "broker_order_id": "BK-ERR",
        }

        summary = await store.reconcile_on_startup(broker)

        assert len(summary["errors"]) == 1
        assert "ord-err" in summary["errors"][0]


# ---------------------------------------------------------------------------
# Tests: Order-to-Dict Normalization
# ---------------------------------------------------------------------------

class TestOrderToDict:
    """Tests for OrderStore._order_to_dict normalization."""

    def test_order_to_dict_normalization(self):
        store = OrderStore()
        order = _make_order()
        result = store._order_to_dict(order)

        assert result["order_id"] == order.order_id
        assert result["symbol"] == "AAPL"
        assert result["quantity"] == 100.0
        assert result["price"] == 150.0
        # Enums normalized to uppercase strings without prefix
        assert result["order_type"] == "LIMIT"
        assert result["side"] == "BUY"
        assert result["status"] == "PENDING"

    def test_order_to_dict_from_dict_input(self):
        store = OrderStore()
        data = {
            "order_id": "dict-001",
            "symbol": "MSFT",
            "side": "sell",
            "order_type": "market",
            "quantity": 200,
            "price": None,
            "status": "submitted",
        }
        result = store._order_to_dict(data)

        assert result["order_id"] == "dict-001"
        assert result["symbol"] == "MSFT"
        assert result["quantity"] == 200.0

    def test_order_to_dict_handles_instrument_as_symbol(self):
        """The Order dataclass uses 'instrument'; _order_to_dict maps to 'symbol'."""
        store = OrderStore()
        order = _make_order(instrument="TSLA")
        result = store._order_to_dict(order)

        assert result["symbol"] == "TSLA"

    def test_order_to_dict_handles_avg_fill_price_aliases(self):
        """Both 'average_fill_price' and 'avg_fill_price' should work."""
        store = OrderStore()
        order = _make_order()
        order.average_fill_price = 148.5
        result = store._order_to_dict(order)

        assert result["avg_fill_price"] == 148.5

    def test_order_to_dict_defaults(self):
        store = OrderStore()
        order = Order()  # all defaults
        result = store._order_to_dict(order)

        assert result["time_in_force"] == "DAY"
        assert result["commission"] == 0.0
        assert result["filled_quantity"] == 0.0
