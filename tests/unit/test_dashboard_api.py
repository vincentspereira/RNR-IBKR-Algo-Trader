"""Unit tests for the Dashboard API.

Tests cover:
- API endpoint responses (portfolio, positions, orders, strategies, risk, P&L, health)
- Order submission and kill switch enforcement
- Kill switch lifecycle (activate/deactivate/status)
- Audit trail and compliance endpoints
- WebSocket connectivity
- MockDataProvider data shape
- Pydantic model validation
"""

import sys
import os
from typing import Dict, List

import pytest

# ---------------------------------------------------------------------------
# Ensure the dashboard src module is importable
# ---------------------------------------------------------------------------
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_dashboard_src = os.path.join(_project_root, "services", "dashboard", "src")
if _dashboard_src not in sys.path:
    sys.path.insert(0, _dashboard_src)

from api import (
    AuditEntryResponse,
    ComplianceStatusResponse,
    DashboardAPI,
    HealthResponse,
    KillSwitchRequest,
    MockDataProvider,
    OrderRequest,
    OrderResponse,
    PnLResponse,
    PortfolioResponse,
    PositionResponse,
    RiskResponse,
    StrategyResponse,
)

from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_provider():
    return MockDataProvider()


@pytest.fixture
def api():
    return DashboardAPI()


@pytest.fixture
def app(api):
    return api.create_app()


@pytest.fixture
def client(app):
    return TestClient(app)


# ===========================================================================
# TestDashboardAPI
# ===========================================================================

class TestDashboardAPI:
    """Tests for the main DashboardAPI endpoints."""

    # --- App creation --------------------------------------------------

    def test_create_app(self, api, app):
        """create_app should return a FastAPI application."""
        from fastapi import FastAPI
        assert isinstance(app, FastAPI)
        assert app.title == "RNR-IBKR-Algo-Trader Dashboard"

    # --- GET endpoints -------------------------------------------------

    def test_get_portfolio(self, client):
        response = client.get("/api/v1/portfolio")
        assert response.status_code == 200
        data = response.json()
        assert data["total_value"] == 1000000.0
        assert data["total_pnl"] == 15000.0
        assert data["daily_pnl"] == 2500.0
        assert data["position_count"] == 5
        assert data["cash"] == 250000.0

    def test_get_positions(self, client):
        response = client.get("/api/v1/positions")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["symbol"] == "AAPL"
        assert data[1]["symbol"] == "MSFT"

    def test_get_orders(self, client):
        response = client.get("/api/v1/orders")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["order_id"] == "ord001"
        assert data[0]["symbol"] == "AAPL"
        assert data[0]["status"] == "filled"

    def test_get_strategies(self, client):
        response = client.get("/api/v1/strategies")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["strategy_id"] == "strat001"
        assert data[0]["name"] == "MACD Crossover"
        assert data[0]["status"] == "active"

    def test_get_risk(self, client):
        response = client.get("/api/v1/risk")
        assert response.status_code == 200
        data = response.json()
        assert data["overall_risk_level"] == "medium"
        assert data["var_95"] == -15000.0
        assert data["max_drawdown"] == -25000.0
        assert data["circuit_breaker_state"] == "closed"
        assert data["active_alerts"] == []

    def test_get_pnl(self, client):
        response = client.get("/api/v1/pnl")
        assert response.status_code == 200
        data = response.json()
        assert data["total_unrealized"] == 10000.0
        assert data["total_realized"] == 5000.0
        assert data["daily_pnl"] == 2500.0
        assert len(data["positions"]) == 1

    def test_get_health(self, client):
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "broker" in data["components"]
        assert data["components"]["broker"] == "connected"
        assert data["uptime_seconds"] == 86400.0

    # --- POST / DELETE endpoints ----------------------------------------

    def test_submit_order(self, client):
        payload = {"symbol": "TSLA", "side": "buy", "quantity": 50}
        response = client.post("/api/v1/orders", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "submitted"
        assert "order_id" in data
        assert data["symbol"] == "TSLA"
        assert data["side"] == "buy"
        assert data["quantity"] == 50

    def test_submit_order_kill_switch_active(self, client, api):
        """Orders should be rejected when the kill switch is active."""
        api._kill_switch_active = True
        payload = {"symbol": "TSLA", "side": "buy", "quantity": 50}
        response = client.post("/api/v1/orders", json=payload)
        assert response.status_code == 403
        assert "Kill switch" in response.json()["detail"]

    def test_activate_kill_switch_without_confirm(self, client):
        """Activating kill switch without confirm should return 400."""
        payload = {"confirm": False, "reason": "test"}
        response = client.post("/api/v1/kill-switch", json=payload)
        assert response.status_code == 400
        assert "confirmation" in response.json()["detail"].lower()

    def test_activate_kill_switch_with_confirm(self, client, api):
        """Activating kill switch with confirm should succeed."""
        payload = {"confirm": True, "reason": "emergency stop"}
        response = client.post("/api/v1/kill-switch", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "activated"
        assert "timestamp" in data
        assert api.kill_switch_active is True

    def test_deactivate_kill_switch(self, client, api):
        """Deactivating kill switch should reset the flag."""
        api._kill_switch_active = True
        response = client.delete("/api/v1/kill-switch")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "deactivated"
        assert api.kill_switch_active is False

    def test_kill_switch_status(self, client):
        """Kill switch status endpoint should reflect current state."""
        response = client.get("/api/v1/kill-switch/status")
        assert response.status_code == 200
        data = response.json()
        assert data["active"] is False

    # --- Audit and compliance -------------------------------------------

    def test_get_recent_audit(self, client):
        response = client.get("/api/v1/audit/recent")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["record_id"] == "rec001"
        assert data[0]["action"] == "order_filled"

    def test_get_recent_audit_custom_limit(self, client):
        response = client.get("/api/v1/audit/recent?limit=50")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_get_compliance_status(self, client):
        response = client.get("/api/v1/compliance/status")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "compliant"
        assert data["violations"] == []
        assert data["last_check"] is not None

    # --- Stats ----------------------------------------------------------

    def test_get_stats(self, client):
        response = client.get("/api/v1/stats")
        assert response.status_code == 200
        data = response.json()
        assert "websocket_connections" in data
        assert "kill_switch_active" in data
        assert "uptime_seconds" in data
        assert data["kill_switch_active"] is False

    # --- WebSocket ------------------------------------------------------

    def test_websocket_connect_and_ping(self, client):
        """WebSocket connection should accept and echo messages."""
        with client.websocket_connect("/ws/v1/live") as ws:
            ws.send_text("hello")
            data = ws.receive_json()
            assert data["type"] == "ping"
            assert data["data"] == "hello"

    # --- Lifecycle ------------------------------------------------------

    def test_kill_switch_blocks_orders(self, client, api):
        """Full lifecycle: activate kill switch, verify orders blocked."""
        # Activate
        response = client.post("/api/v1/kill-switch", json={"confirm": True, "reason": "test"})
        assert response.status_code == 200
        assert api.kill_switch_active is True

        # Try to submit order - should be blocked
        payload = {"symbol": "AAPL", "side": "sell", "quantity": 10}
        response = client.post("/api/v1/orders", json=payload)
        assert response.status_code == 403

    def test_kill_switch_lifecycle(self, client, api):
        """Full lifecycle: activate, check status, deactivate, submit order."""
        # Initially not active
        response = client.get("/api/v1/kill-switch/status")
        assert response.json()["active"] is False

        # Activate
        response = client.post("/api/v1/kill-switch", json={"confirm": True, "reason": "test"})
        assert response.status_code == 200
        assert api.kill_switch_active is True

        # Check status reflects activation
        response = client.get("/api/v1/kill-switch/status")
        assert response.json()["active"] is True

        # Deactivate
        response = client.delete("/api/v1/kill-switch")
        assert response.status_code == 200
        assert api.kill_switch_active is False

        # Now orders should go through
        payload = {"symbol": "GOOGL", "side": "buy", "quantity": 25}
        response = client.post("/api/v1/orders", json=payload)
        assert response.status_code == 200
        assert response.json()["status"] == "submitted"


# ===========================================================================
# TestMockDataProvider
# ===========================================================================

class TestMockDataProvider:
    """Tests for the MockDataProvider to verify data shapes."""

    def test_get_portfolio(self, mock_provider):
        result = mock_provider.get_portfolio()
        assert isinstance(result, dict)
        assert "total_value" in result
        assert "total_pnl" in result
        assert "daily_pnl" in result
        assert "position_count" in result
        assert "cash" in result

    def test_get_positions(self, mock_provider):
        result = mock_provider.get_positions()
        assert isinstance(result, list)
        assert len(result) >= 1
        for pos in result:
            assert "symbol" in pos
            assert "quantity" in pos
            assert "avg_cost" in pos
            assert "market_price" in pos
            assert "unrealized_pnl" in pos
            assert "pnl_pct" in pos

    def test_get_orders(self, mock_provider):
        result = mock_provider.get_orders()
        assert isinstance(result, list)
        assert len(result) >= 1
        for order in result:
            assert "order_id" in order
            assert "symbol" in order
            assert "side" in order
            assert "order_type" in order
            assert "quantity" in order
            assert "status" in order

    def test_get_strategies(self, mock_provider):
        result = mock_provider.get_strategies()
        assert isinstance(result, list)
        assert len(result) >= 1
        for strat in result:
            assert "strategy_id" in strat
            assert "name" in strat
            assert "status" in strat

    def test_get_risk(self, mock_provider):
        result = mock_provider.get_risk()
        assert isinstance(result, dict)
        assert "overall_risk_level" in result
        assert "var_95" in result
        assert "max_drawdown" in result
        assert "circuit_breaker_state" in result
        assert "active_alerts" in result

    def test_get_pnl(self, mock_provider):
        result = mock_provider.get_pnl()
        assert isinstance(result, dict)
        assert "total_unrealized" in result
        assert "total_realized" in result
        assert "daily_pnl" in result
        assert "positions" in result

    def test_get_health(self, mock_provider):
        result = mock_provider.get_health()
        assert isinstance(result, dict)
        assert result["status"] == "healthy"
        assert "components" in result
        assert "uptime_seconds" in result

    def test_get_compliance_status(self, mock_provider):
        result = mock_provider.get_compliance_status()
        assert isinstance(result, dict)
        assert result["status"] == "compliant"
        assert "violations" in result
        assert "last_check" in result

    def test_get_audit_recent(self, mock_provider):
        result = mock_provider.get_audit_recent(limit=10)
        assert isinstance(result, list)
        assert len(result) >= 1
        for entry in result:
            assert "record_id" in entry
            assert "timestamp" in entry
            assert "action" in entry
            assert "actor" in entry
            assert "details" in entry


# ===========================================================================
# TestPydanticModels
# ===========================================================================

class TestPydanticModels:
    """Tests for Pydantic request/response model validation."""

    def test_order_request(self):
        req = OrderRequest(symbol="AAPL", side="buy", quantity=100)
        assert req.symbol == "AAPL"
        assert req.side == "buy"
        assert req.quantity == 100
        assert req.order_type == "market"
        assert req.price is None
        assert req.strategy_id is None

    def test_order_request_with_price(self):
        req = OrderRequest(symbol="AAPL", side="sell", quantity=50, order_type="limit", price=175.0)
        assert req.order_type == "limit"
        assert req.price == 175.0

    def test_kill_switch_request(self):
        req = KillSwitchRequest(confirm=True, reason="emergency")
        assert req.confirm is True
        assert req.reason == "emergency"

    def test_position_response(self):
        resp = PositionResponse(
            symbol="AAPL", quantity=100, avg_cost=150.0,
            market_price=155.0, unrealized_pnl=500.0, pnl_pct=3.33,
        )
        assert resp.symbol == "AAPL"
        assert resp.pnl_pct == 3.33

    def test_health_response(self):
        resp = HealthResponse(
            status="healthy",
            components={"broker": "connected"},
            uptime_seconds=3600.0,
        )
        assert resp.status == "healthy"
        assert resp.components["broker"] == "connected"
        assert resp.uptime_seconds == 3600.0
