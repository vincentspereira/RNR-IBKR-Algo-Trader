"""Dashboard REST API for the IBKR Algo Trader.

Provides endpoints for portfolio overview, positions, orders, strategies,
risk metrics, P&L, system health, audit trail, compliance, and manual order submission.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Pydantic models for request/response
# ---------------------------------------------------------------------------

class OrderRequest(BaseModel):
    symbol: str
    side: str
    quantity: float
    order_type: str = "market"
    price: Optional[float] = None
    strategy_id: Optional[str] = None


class KillSwitchRequest(BaseModel):
    confirm: bool = False
    reason: str = ""


class PositionResponse(BaseModel):
    symbol: str
    quantity: float
    avg_cost: float
    market_price: float
    unrealized_pnl: float
    pnl_pct: float


class OrderResponse(BaseModel):
    order_id: str
    symbol: str
    side: str
    order_type: str
    quantity: float
    status: str
    filled_quantity: float = 0.0
    average_fill_price: float = 0.0


class PortfolioResponse(BaseModel):
    total_value: float
    total_pnl: float
    daily_pnl: float
    position_count: int
    cash: float


class RiskResponse(BaseModel):
    overall_risk_level: str
    var_95: float
    max_drawdown: float
    circuit_breaker_state: str
    active_alerts: List[str] = []


class HealthResponse(BaseModel):
    status: str
    components: Dict[str, str]
    uptime_seconds: float = 0.0


class PnLResponse(BaseModel):
    total_unrealized: float
    total_realized: float
    daily_pnl: float
    positions: List[Dict[str, Any]] = []


class StrategyResponse(BaseModel):
    strategy_id: str
    name: str
    status: str
    pnl: float = 0.0
    positions: int = 0


class ComplianceStatusResponse(BaseModel):
    status: str
    violations: List[Dict[str, Any]] = []
    last_check: Optional[str] = None


class AuditEntryResponse(BaseModel):
    record_id: str
    timestamp: str
    action: str
    actor: str
    details: Dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Mock data provider
# ---------------------------------------------------------------------------

class MockDataProvider:
    """Provides mock data for the dashboard when real services are unavailable."""

    def get_portfolio(self) -> Dict:
        return {
            "total_value": 1000000.0,
            "total_pnl": 15000.0,
            "daily_pnl": 2500.0,
            "position_count": 5,
            "cash": 250000.0,
        }

    def get_positions(self) -> List[Dict]:
        return [
            {"symbol": "AAPL", "quantity": 100, "avg_cost": 150.0, "market_price": 155.0,
             "unrealized_pnl": 500.0, "pnl_pct": 3.33},
            {"symbol": "MSFT", "quantity": 50, "avg_cost": 300.0, "market_price": 310.0,
             "unrealized_pnl": 500.0, "pnl_pct": 1.67},
        ]

    def get_orders(self) -> List[Dict]:
        return [
            {"order_id": "ord001", "symbol": "AAPL", "side": "buy", "order_type": "market",
             "quantity": 100, "status": "filled", "filled_quantity": 100, "average_fill_price": 155.0},
        ]

    def get_strategies(self) -> List[Dict]:
        return [
            {"strategy_id": "strat001", "name": "MACD Crossover", "status": "active", "pnl": 5000.0, "positions": 3},
        ]

    def get_risk(self) -> Dict:
        return {
            "overall_risk_level": "medium",
            "var_95": -15000.0,
            "max_drawdown": -25000.0,
            "circuit_breaker_state": "closed",
            "active_alerts": [],
        }

    def get_pnl(self) -> Dict:
        return {
            "total_unrealized": 10000.0,
            "total_realized": 5000.0,
            "daily_pnl": 2500.0,
            "positions": [
                {"symbol": "AAPL", "unrealized_pnl": 500.0, "realized_pnl": 200.0},
            ],
        }

    def get_health(self) -> Dict:
        return {
            "status": "healthy",
            "components": {
                "broker": "connected",
                "database": "connected",
                "risk_engine": "healthy",
            },
            "uptime_seconds": 86400.0,
        }

    def get_compliance_status(self) -> Dict:
        return {"status": "compliant", "violations": [], "last_check": datetime.now(timezone.utc).isoformat()}

    def get_audit_recent(self, limit: int = 20) -> List[Dict]:
        return [
            {"record_id": "rec001", "timestamp": datetime.now(timezone.utc).isoformat(),
             "action": "order_filled", "actor": "execution_engine", "details": {"symbol": "AAPL"}},
        ]


# ---------------------------------------------------------------------------
# Dashboard API
# ---------------------------------------------------------------------------

class DashboardAPI:
    """REST API for the trading dashboard."""

    def __init__(self, data_provider=None, execution_engine=None, risk_engine=None,
                 compliance_engine=None, audit_trail=None, notification_service=None):
        self._data_provider = data_provider or MockDataProvider()
        self._execution_engine = execution_engine
        self._risk_engine = risk_engine
        self._compliance_engine = compliance_engine
        self._audit_trail = audit_trail
        self._notification_service = notification_service
        self._kill_switch_active = False
        self._connected_websockets: List[WebSocket] = []
        self._start_time = datetime.now(timezone.utc)
        self._logger = logging.getLogger(__name__)

    def create_app(self) -> FastAPI:
        """Create and configure the FastAPI application."""
        app = FastAPI(
            title="IBKR Algo Trader Dashboard",
            version="1.0.0",
            description="REST API for the trading dashboard",
        )
        self._register_routes(app)
        return app

    def _register_routes(self, app: FastAPI):
        """Register all API routes."""

        @app.get("/api/v1/portfolio", response_model=PortfolioResponse)
        async def get_portfolio():
            data = self._data_provider.get_portfolio()
            return PortfolioResponse(**data)

        @app.get("/api/v1/positions")
        async def get_positions():
            return self._data_provider.get_positions()

        @app.get("/api/v1/orders", response_model=List[OrderResponse])
        async def get_orders():
            data = self._data_provider.get_orders()
            return [OrderResponse(**o) for o in data]

        @app.get("/api/v1/strategies", response_model=List[StrategyResponse])
        async def get_strategies():
            data = self._data_provider.get_strategies()
            return [StrategyResponse(**s) for s in data]

        @app.get("/api/v1/risk", response_model=RiskResponse)
        async def get_risk():
            data = self._data_provider.get_risk()
            return RiskResponse(**data)

        @app.get("/api/v1/pnl", response_model=PnLResponse)
        async def get_pnl():
            data = self._data_provider.get_pnl()
            return PnLResponse(**data)

        @app.get("/api/v1/health", response_model=HealthResponse)
        async def get_health():
            data = self._data_provider.get_health()
            return HealthResponse(**data)

        @app.post("/api/v1/orders")
        async def submit_order(request: OrderRequest):
            if self._kill_switch_active:
                raise HTTPException(status_code=403, detail="Kill switch is active - no new orders allowed")
            order_id = uuid.uuid4().hex[:12]
            self._logger.info(f"Manual order submitted: {order_id} {request.symbol} {request.side} {request.quantity}")
            return {"order_id": order_id, "status": "submitted", **request.model_dump()}

        @app.post("/api/v1/kill-switch")
        async def activate_kill_switch(request: KillSwitchRequest):
            if not request.confirm:
                raise HTTPException(status_code=400, detail="Kill switch requires confirmation")
            self._kill_switch_active = True
            self._logger.warning(f"Kill switch activated: {request.reason}")
            return {"status": "activated", "timestamp": datetime.now(timezone.utc).isoformat()}

        @app.delete("/api/v1/kill-switch")
        async def deactivate_kill_switch():
            self._kill_switch_active = False
            self._logger.info("Kill switch deactivated")
            return {"status": "deactivated"}

        @app.get("/api/v1/kill-switch/status")
        async def get_kill_switch_status():
            return {"active": self._kill_switch_active}

        @app.get("/api/v1/audit/recent")
        async def get_recent_audit(limit: int = Query(default=20, ge=1, le=100)):
            return self._data_provider.get_audit_recent(limit)

        @app.get("/api/v1/compliance/status", response_model=ComplianceStatusResponse)
        async def get_compliance_status():
            data = self._data_provider.get_compliance_status()
            return ComplianceStatusResponse(**data)

        @app.websocket("/ws/v1/live")
        async def websocket_live(websocket: WebSocket):
            await websocket.accept()
            self._connected_websockets.append(websocket)
            try:
                while True:
                    data = await websocket.receive_text()
                    # Echo back for now - in production would push real-time updates
                    await websocket.send_json({"type": "ping", "data": data})
            except WebSocketDisconnect:
                self._connected_websockets.remove(websocket)
            except Exception:
                if websocket in self._connected_websockets:
                    self._connected_websockets.remove(websocket)

        @app.get("/api/v1/stats")
        async def get_stats():
            return {
                "websocket_connections": len(self._connected_websockets),
                "kill_switch_active": self._kill_switch_active,
                "uptime_seconds": (datetime.now(timezone.utc) - self._start_time).total_seconds(),
            }

    @property
    def kill_switch_active(self) -> bool:
        return self._kill_switch_active

    @property
    def connected_websockets(self) -> int:
        return len(self._connected_websockets)
