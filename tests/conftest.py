"""Shared pytest fixtures for the RNR-IBKR-Algo-Trader test suite.

Import strategy:
- Project root is on sys.path for `core_trading` imports.
- `services/trading-engine` on sys.path lets us import as `src.core.*`,
  `src.engines.*` etc. with relative imports working correctly.
- `services/risk-manager` modules are loaded via importlib under unique names
  to avoid colliding with trading-engine's `engines` package.
"""

import asyncio
import importlib.util
import sys
import os
from unittest.mock import AsyncMock

import pytest

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _project_root)
sys.path.insert(0, os.path.join(_project_root, "services", "trading-engine"))

# Load risk-manager modules via importlib (unique names to avoid collisions)
_rm_engines = os.path.join(_project_root, "services", "risk-manager", "src", "engines")


def _load_module(name, path, package=None):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    if package:
        mod.__package__ = package
    spec.loader.exec_module(mod)
    return mod


_load_module("risk_engines", os.path.join(_rm_engines, "risk_engine.py"))
_load_module("kill_switch", os.path.join(_rm_engines, "kill_switch.py"))

# Load compliance module via importlib
_compliance_src = os.path.join(_project_root, "services", "compliance", "src")
_compliance_engine_path = os.path.join(_compliance_src, "compliance_engine.py")
if os.path.exists(_compliance_engine_path):
    _load_module("compliance_engine", _compliance_engine_path)

# Load ai-assistant module via importlib
_ai_src = os.path.join(_project_root, "services", "ai-assistant", "src")
_ai_main_path = os.path.join(_ai_src, "main.py")
if os.path.exists(_ai_main_path):
    _load_module("ai_assistant_main", _ai_main_path, package="src")


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
def _ensure_current_event_loop():
    """Guarantee a current event loop on the main thread for every test.

    Python 3.12 removed implicit event-loop creation in
    ``asyncio.get_event_loop()``. ib_insync's ``eventkit`` dependency calls
    ``get_event_loop()`` lazily; after pytest-asyncio tears down a test's loop,
    a subsequent (even synchronous) test that touches eventkit would otherwise
    hit ``RuntimeError: There is no current event loop``. This autouse fixture
    ensures a loop is always set, making the suite order-independent.

    The probe is wrapped in ``catch_warnings`` so the fixture itself does not
    emit the very DeprecationWarning it guards against, and any loop it creates
    is closed on teardown to avoid leaking a ResourceWarning.
    """
    import warnings

    created_loop = None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                raise RuntimeError("event loop is closed")
        except RuntimeError:
            created_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(created_loop)
    yield
    if created_loop is not None and not created_loop.is_running():
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            created_loop.close()


@pytest.fixture
def event_bus():
    from src.core.event_system import EventBus
    return EventBus()


@pytest.fixture
def mock_broker_adapter():
    adapter = AsyncMock()
    adapter.connect = AsyncMock(return_value=True)
    adapter.disconnect = AsyncMock(return_value=True)
    adapter.get_positions = AsyncMock(return_value=[])
    adapter.get_account_info = AsyncMock(return_value={
        "account_id": "DU_TEST_ACCOUNT",
        "balance": 100000.0,
        "buying_power": 200000.0,
        "net_liquidation": 100000.0,
        "currency": "USD",
    })
    adapter.get_portfolio_value = AsyncMock(return_value=100000.0)
    adapter.get_quote = AsyncMock(return_value={"last": 150.0, "bid": 149.99, "ask": 150.01})
    adapter.get_historical_data = AsyncMock(return_value=[])
    adapter.place_order = AsyncMock(return_value={
        "order_id": "1",
        "status": "submitted",
        "broker_order_id": "1001",
    })
    adapter.cancel_order = AsyncMock(return_value=True)
    adapter.get_order_status = AsyncMock(return_value={"status": "submitted"})
    adapter.get_open_orders = AsyncMock(return_value=[])
    return adapter


@pytest.fixture
def sample_order():
    from src.engines.execution_engine import Order, OrderSide, OrderType
    return Order(
        instrument="AAPL",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=100,
        price=150.0,
    )


@pytest.fixture
def sample_order_data():
    return {
        "symbol": "AAPL",
        "side": "buy",
        "quantity": 10,
        "order_type": "limit",
        "price": 150.0,
        "asset_class": "equities",
    }


@pytest.fixture
def risk_config():
    from risk_engines import RiskConfig
    return RiskConfig(
        max_position_size=10000.0,
        max_portfolio_var=5000.0,
        max_drawdown=0.05,
        max_leverage=3.0,
        max_sector_exposure=0.25,
        daily_loss_limit_pct=0.02,
        max_daily_trades=10,
        max_concurrent_positions=5,
        max_order_size=5000.0,
    )


@pytest.fixture
def risk_engine(mock_broker_adapter, event_bus, risk_config):
    from risk_engines import RiskEngine
    return RiskEngine(
        broker_adapter=mock_broker_adapter,
        event_bus=event_bus,
        config=risk_config,
    )


@pytest.fixture
def execution_engine(mock_broker_adapter, event_bus):
    from src.engines.execution_engine import ExecutionEngine
    return ExecutionEngine(
        broker_adapter=mock_broker_adapter,
        event_bus=event_bus,
        risk_engine=None,
        order_store=None,
    )


@pytest.fixture
def ai_config():
    if "ai_assistant_main" in sys.modules:
        from ai_assistant_main import AIConfig
        return AIConfig(
            llm_api_key="test-key",
            llm_model="gpt-4o-mini",
            qdrant_url="http://localhost:6333",
        )
    return None


@pytest.fixture
def ai_assistant(ai_config):
    if "ai_assistant_main" not in sys.modules:
        pytest.skip("AI assistant module not loaded")
    from ai_assistant_main import AIAssistantService
    return AIAssistantService(config=ai_config)
