"""Shared pytest fixtures for strategy tests."""

import sys
import os
import types
import builtins
from unittest.mock import MagicMock
import numpy as np
import pandas as pd
import pytest

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


# ---------------------------------------------------------------------------
# Mock external dependencies that are not always installed
# ---------------------------------------------------------------------------

def _ensure_mock(name, attrs=None):
    """Insert a mock module into sys.modules if it does not already exist."""
    if name not in sys.modules:
        mod = types.ModuleType(name)
        if attrs:
            for k, v in attrs.items():
                setattr(mod, k, v)
        sys.modules[name] = mod
    return sys.modules[name]


def _mock_handler_pkg(handler_fqn, class_name_stem):
    """Create a mock handler package with sub-modules that export the expected names.

    The strategy files do: from .xxx_handlers.base_handler import XxxBaseHandler
    So each handler sub-module needs to have the right name as an attribute.
    """
    _ensure_mock(handler_fqn)
    for h, suffix in [
        ("base_handler", "BaseHandler"),
        ("main_handler", "MainHandler"),
        ("config_handler", "ConfigHandler"),
        ("state_handler", "StateHandler"),
        ("validation_handler", "ValidationHandler"),
    ]:
        mod = _ensure_mock(f"{handler_fqn}.{h}")
        attr_name = f"{class_name_stem}{suffix}"
        if not hasattr(mod, attr_name):
            setattr(mod, attr_name, MagicMock())


# --- Mock talib (C extension, optional) ---
_mock_talib = _ensure_mock("talib")
for _fn in [
    "SMA", "EMA", "WMA", "RSI", "MACD", "BBANDS", "ATR", "ADX", "CCI",
    "STOCH", "STOCHRSI", "WILLR", "ROC", "MOM", "TRIX", "OBV", "AD",
    "ADOSC", "MFI", "TRANGE", "T3", "DEMA", "TEMA", "KAMA", "MA",
    "LINEARREG", "LINEARREG_SLOPE", "TSF", "STDDEV", "VAR", "CORREL",
    "BETA", "TSR", "MIN", "MAX", "MININDEX", "MAXINDEX", "MINMAX",
    "MINMAXINDEX", "SUM", "DIV", "MULT", "SUB", "ADD", "CEIL", "FLOOR",
    "ROUND", "LOG10", "LN", "EXP", "SQRT", "AVGPRICE", "MEDPRICE",
    "TYPPRICE", "WCLPRICE", "AVGDEV", "BOP", "CDLDOJI", "CDLHAMMER",
    "CDLENGULFING", "CDLMORNINGSTAR", "CDLEVENINGSTAR", "HT_DCPERIOD",
    "HT_DCPHASE", "HT_PHASOR", "HT_SINE", "HT_TRENDMODE", "MA_TYPE",
]:
    if not hasattr(_mock_talib, _fn):
        setattr(_mock_talib, _fn, MagicMock())

# --- Mock nautilus_trader and sub-packages ---
# IMPORTANT: Define sub-modules WITH their attrs first, then plain parent stubs.
# _ensure_mock skips attrs when module already exists, so we must create
# the leaf modules with attrs BEFORE any plain stub creates them empty.
_ensure_mock("nautilus_trader")
_ensure_mock("nautilus_trader.model")
# nautilus_trader.model.data needs Bar attribute for stop_loss_strategies.py
# Also needs __path__ to act as a package for sub-module imports.
_nt_data = _ensure_mock("nautilus_trader.model.data", {"Bar": MagicMock()})
_nt_data.__path__ = []
_nt_data.__package__ = "nautilus_trader.model.data"
_ensure_mock("nautilus_trader.trading")
_ensure_mock("nautilus_trader.core")
_ensure_mock("nautilus_trader.core.datetime")
_ensure_mock("nautilus_trader.backtest")
_ensure_mock("nautilus_trader.backtest.data")
_ensure_mock("nautilus_trader.backtest.data.providers")
_ensure_mock("nautilus_trader.backtest.engine")
_bar_mod = _ensure_mock("nautilus_trader.model.data.bar", {"Bar": MagicMock()})
_tick_mod = _ensure_mock("nautilus_trader.model.data.tick", {"QuoteTick": MagicMock(), "TradeTick": MagicMock()})
_ev_ord = _ensure_mock("nautilus_trader.model.events.order", {"OrderFilled": MagicMock()})
_ev_pos = _ensure_mock("nautilus_trader.model.events.position", {"PositionClosed": MagicMock(), "PositionOpened": MagicMock()})
_ids_mod = _ensure_mock("nautilus_trader.model.identifiers", {"InstrumentId": MagicMock(), "StrategyId": MagicMock()})
_inst_mod = _ensure_mock("nautilus_trader.model.instruments", {"Instrument": MagicMock()})
_enum_mod = _ensure_mock("nautilus_trader.model.enums", {
    "OrderSide": MagicMock(),
    "OrderType": MagicMock(),
    "PositionSide": MagicMock(),
    "TimeInForce": MagicMock(),
    "TriggerType": MagicMock(),
    "LiquidationAction": MagicMock(),
})
_ev_mod = _ensure_mock("nautilus_trader.model.events")
_strat_mod = _ensure_mock("nautilus_trader.strategy", {"Strategy": type("Strategy", (), {})})
# nautilus_trader.model must be a package so sub-modules (orders, etc.) can be found
sys.modules["nautilus_trader.model"].__path__ = []
sys.modules["nautilus_trader.model"].__package__ = "nautilus_trader.model"
_ensure_mock("nautilus_trader.model.orders", {"MarketOrder": MagicMock(), "LimitOrder": MagicMock()})
_nte = _ensure_mock("nautilus_trader_engine")
_nte.__path__ = [os.path.join(_project_root, "core_trading", "nautilus_trader_engine")] if os.path.isdir(os.path.join(_project_root, "core_trading", "nautilus_trader_engine")) else []
_ensure_mock("nautilus_trader_engine.rl")
_rl_env = _ensure_mock("nautilus_trader_engine.rl.environment", {"NautilusTradingEnv": MagicMock()})
_ensure_mock("nautilus_trader_engine.analysis")
_ensure_mock("nautilus_trader_engine.analysis.indicators")
_ci = _ensure_mock("nautilus_trader_engine.analysis.indicators.consolidated_indicators", {"ConsolidatedIndicators": MagicMock()})
_ensure_mock("nautilus_trader_engine.strategies")
_nte_strat = _ensure_mock("nautilus_trader_engine.strategies.base_strategy", {"BaseStrategy": type("BaseStrategy", (), {})})
# nautilus_trader_engine.strategies.execution must be a package with __path__
# so that sub-modules (backtesting, live_trading, validation) can be imported.
_nte_exec = _ensure_mock("nautilus_trader_engine.strategies.execution")
_nte_exec.__path__ = ["_mock_execution_pkg"]
_nte_exec.__package__ = "nautilus_trader_engine.strategies.execution"
_ensure_mock("nautilus_trader_engine.strategies.execution.base_strategy", {"BaseStrategy": type("BaseStrategy", (), {})})
_ensure_mock("nautilus_trader_engine.strategies.execution.backtesting", {"BacktestingEngine": MagicMock(), "ExecutionPipeline": MagicMock()})
_ensure_mock("nautilus_trader_engine.strategies.execution.live_trading", {"RuntimeEngine": MagicMock(), "PerformanceMonitor": MagicMock()})
_ensure_mock("nautilus_trader_engine.strategies.execution.validation", {"StrategyValidator": MagicMock()})
# Also make .execution itself importable as a name with ExecutionPipeline
_nte_exec.ExecutionPipeline = MagicMock()

# --- Mock stable_baselines3 ---
_ensure_mock("stable_baselines3")
_ensure_mock("stable_baselines3.common")
_ensure_mock("stable_baselines3.common.base_class", {"BaseAlgorithm": MagicMock()})

# --- Mock torch / torch.nn (reinforcement_learning.py references nn.Module at class level) ---
_nn_mod = _ensure_mock("torch")
_ensure_mock("torch.nn")
# Create a real class so `class Foo(nn.Module)` works at definition time
_nn_mod = sys.modules["torch.nn"]
_nn_mod.Module = type("Module", (), {})
_nn_mod.functional = MagicMock()
_nn_mod.Linear = type("Linear", (), {})
_nn_mod.ReLU = type("ReLU", (), {})
_nn_mod.Dropout = type("Dropout", (), {})
_nn_mod.Sequential = type("Sequential", (), {})
_ensure_mock("torch.optim")
_ensure_mock("torch.distributions")
sys.modules["torch"].nn = _nn_mod
# reinforcement_learning.py references `nn.Module` as a bare name at class definition time.
# Inject into builtins so it's available globally.
builtins.nn = _nn_mod

# --- Mock infrastructure.config ---
_ensure_mock("infrastructure")
_ensure_mock("infrastructure.config")
_mc = _ensure_mock("infrastructure.config.master_config")
_mc.get_config = MagicMock(return_value={})

# --- Mock statsmodels ---
_ensure_mock("statsmodels")
_ensure_mock("statsmodels.regression")
_sm_ols = _ensure_mock("statsmodels.regression.linear_model", {"OLS": MagicMock()})
_ensure_mock("statsmodels.tsa")
_sm_stat = _ensure_mock("statsmodels.tsa.stattools", {
    "adfuller": MagicMock(), "coint": MagicMock(), "kpss": MagicMock(),
})
_ensure_mock("statsmodels.tsa.vector_ar")
_ensure_mock("statsmodels.tsa.vector_ar.vecm", {"coint_johansen": MagicMock()})

# --- Mock matplotlib ---
_ensure_mock("matplotlib")
_ensure_mock("matplotlib.pyplot")
_ensure_mock("matplotlib.dates")
_mpl_patches = _ensure_mock("matplotlib.patches", {"Rectangle": MagicMock()})
_ensure_mock("seaborn")

# --- Mock plotly ---
_ensure_mock("plotly")
_ensure_mock("plotly.express")
_ensure_mock("plotly.graph_objects")
_ensure_mock("plotly.offline")
_ensure_mock("plotly.subplots", {"make_subplots": MagicMock()})

# --- Mock core_trading.indicators ---
_ci2 = _ensure_mock("core_trading.indicators", {"ConsolidatedIndicators": MagicMock()})
_ci3 = _ensure_mock("core_trading.indicators.consolidated_indicators", {"ConsolidatedIndicators": MagicMock()})

# --- Mock shared.utils ---
_ensure_mock("shared")
_ensure_mock("shared.utils")
_ensure_mock("shared.utils.models")
_ensure_mock("shared.utils.models.agent_models", {"AgentType": MagicMock()})
_su = _ensure_mock("shared.utils.utils", {"get_logger": MagicMock(return_value=MagicMock())})

# --- Mock core_trading.core sub-modules ---
_ensure_mock("core_trading.core")
# core_trading.core must be a package so sub-modules can be imported
_core_mod = sys.modules["core_trading.core"]
_core_mod.__path__ = [os.path.join(_project_root, "core_trading", "core")]
_core_mod.__package__ = "core_trading.core"
_ensure_mock("core_trading.core.data_types", {"MarketData": MagicMock(), "Position": MagicMock(), "Signal": MagicMock()})
_ensure_mock("core_trading.core.events", {"OrderEvent": MagicMock(), "SignalEvent": MagicMock()})
_ensure_mock("core_trading.core.portfolio_management", {"PortfolioManager": MagicMock()})
_ensure_mock("core_trading.core.risk_management", {"RiskManager": MagicMock()})
_ensure_mock("core_trading.core.signal_generator", {"SignalGenerator": MagicMock()})
_ensure_mock("core_trading.core.augmented_base_institutional_strategy", {"SignalType": MagicMock()})

# --- Mock core_trading.strategies base modules ---
_ensure_mock("core_trading.strategies.base_strategy", {"BaseStrategy": MagicMock(), "StrategyConfig": MagicMock()})
_ensure_mock("core_trading.strategies.utils")
_eiu = _ensure_mock("core_trading.strategies.utils.execution_intent_utils", {
    "ExecutionConstraints": MagicMock(), "ExecutionIntentUtils": MagicMock(),
})
_rmu = _ensure_mock("core_trading.strategies.utils.risk_management_utils", {
    "RiskManagementUtils": MagicMock(),
})
_ensure_mock("core_trading.strategies.core")
_core_strat_mod = sys.modules["core_trading.strategies.core"]
_core_strat_mod.__path__ = [os.path.join(_project_root, "core_trading", "strategies", "core")]
_core_strat_mod.__package__ = "core_trading.strategies.core"
_ensure_mock("core_trading.strategies.core.base_institutional_strategy", {
    "BaseInstitutionalStrategy": type("BaseInstitutionalStrategy", (), {
        "__init__": lambda self, config=None: None,
    }),
    "InstitutionalConfig": type("InstitutionalConfig", (), {
        "__init__": lambda self, **kwargs: None,
    }),
})

# --- Provide BaseInstitutionalStrategy as a builtin for scalping modules ---
builtins.BaseInstitutionalStrategy = builtins.BaseInstitutionalStrategy if hasattr(builtins, "BaseInstitutionalStrategy") else type("BaseInstitutionalStrategy", (), {})
# --- Provide BaseVWStrategy as a builtin for volume_weighted modules ---
# The VW sub-strategy files reference BaseVWStrategy at class definition time but have the import commented out.
builtins.BaseVWStrategy = builtins.BaseVWStrategy if hasattr(builtins, "BaseVWStrategy") else type("BaseVWStrategy", (), {})

# --- Mock pypfopt ---
_ensure_mock("pypfopt")
_ensure_mock("pypfopt.efficient_frontier")
_ensure_mock("pypfopt.expected_returns")
_ensure_mock("pypfopt.risk_models")
_ensure_mock("pypfopt.discrete_allocation")
_ensure_mock("pypfopt.objective_functions")

# ---------------------------------------------------------------------------
# Handler mocks for skeleton strategy files
# ---------------------------------------------------------------------------
_mock_handler_pkg("core_trading.strategies.volatility_breakout.bollingersqueezestrategy_handlers", "BollingerSqueezeStrategy")
_mock_handler_pkg("core_trading.strategies.arbitragestrategy_handlers", "ArbitrageStrategy")
_mock_handler_pkg("core_trading.strategies.volume_weighted.basevwstrategy_handlers", "BaseVWStrategy")
_mock_handler_pkg("core_trading.strategies.backtesting.backtestresults_handlers", "BacktestResults")
_mock_handler_pkg("core_trading.strategies.backtesting.performanceanalyzer_handlers", "PerformanceAnalyzer")
_mock_handler_pkg("core_trading.strategies.seasonal.turnaroundtuesdaystrategy_handlers", "TurnaroundTuesdayStrategy")
_mock_handler_pkg("core_trading.strategies.mlstrategy_handlers", "MLStrategy")
_mock_handler_pkg("core_trading.strategies.machine_learning.modelmonitor_handlers", "ModelMonitor")
_mock_handler_pkg("core_trading.strategies.machine_learning.basemlstrategy_handlers", "BaseMLStrategy")

# --- Patch volatility_breakout __init__ to define missing variable ---
# We need the actual package to be importable but the __init__.py has a NameError.
# Fix by pre-defining the variable in the module dict.
_vb_pkg_path = os.path.join(_project_root, "core_trading", "strategies", "volatility_breakout")
if os.path.isdir(_vb_pkg_path) and "core_trading.strategies.volatility_breakout" not in sys.modules:
    # Create a proper package module with __path__ so sub-modules can be imported
    import importlib
    _vb_mod = types.ModuleType("core_trading.strategies.volatility_breakout")
    _vb_mod.__path__ = [_vb_pkg_path]
    _vb_mod.__package__ = "core_trading.strategies.volatility_breakout"
    _vb_mod.DEFAULT_VOLATILITY_CONFIG = {}
    _vb_mod.__version__ = "0.1.0"
    sys.modules["core_trading.strategies.volatility_breakout"] = _vb_mod

# Ensure volatility_breakout sub-modules (utils, config) that ATR/Donchian import
_vb_utils = _ensure_mock("core_trading.strategies.volatility_breakout.utils", {"Utils": MagicMock()})
_vb_config = _ensure_mock("core_trading.strategies.volatility_breakout.config", {"Config": MagicMock()})

# Pre-create machine_learning package module to prevent __init__.py from running.
# The __init__.py tries to import create_rl_strategy which is commented out in reinforcement_learning.py.
_ml_pkg_path = os.path.join(_project_root, "core_trading", "strategies", "machine_learning")
if os.path.isdir(_ml_pkg_path) and "core_trading.strategies.machine_learning" not in sys.modules:
    _ml_mod = types.ModuleType("core_trading.strategies.machine_learning")
    _ml_mod.__path__ = [_ml_pkg_path]
    _ml_mod.__package__ = "core_trading.strategies.machine_learning"
    sys.modules["core_trading.strategies.machine_learning"] = _ml_mod

# Load the real clustering_strategies module (now has working implementations).
# The __init__.py tries to import from it, so we load from file to avoid the
# broken __init__.py while still getting the real classes.
_cs_file = os.path.join(_project_root, "core_trading", "strategies", "machine_learning", "clustering_strategies.py")
if os.path.isfile(_cs_file) and "core_trading.strategies.machine_learning.clustering_strategies" not in sys.modules:
    import importlib.util
    _cs_spec = importlib.util.spec_from_file_location(
        "core_trading.strategies.machine_learning.clustering_strategies", _cs_file
    )
    _cs_mod = importlib.util.module_from_spec(_cs_spec)
    sys.modules["core_trading.strategies.machine_learning.clustering_strategies"] = _cs_mod
    _cs_spec.loader.exec_module(_cs_mod)

# Pre-create backtesting package module to prevent __init__.py from running.
# The __init__.py imports from .risk_analyzer which does `from .config import Config`
# but config.py only has BacktestConfig, not Config -- causing ImportError.
_bt_pkg_path = os.path.join(_project_root, "core_trading", "strategies", "backtesting")
if os.path.isdir(_bt_pkg_path) and "core_trading.strategies.backtesting" not in sys.modules:
    _bt_mod = types.ModuleType("core_trading.strategies.backtesting")
    _bt_mod.__path__ = [_bt_pkg_path]
    _bt_mod.__package__ = "core_trading.strategies.backtesting"
    sys.modules["core_trading.strategies.backtesting"] = _bt_mod

# Mock backtesting data_manager to provide create_data_manager
_dm = _ensure_mock("core_trading.strategies.backtesting.data_manager")
for _dm_attr in ["create_data_manager", "DataConfig", "MarketData", "DataSource",
                  "YahooFinanceSource", "MockDataSource", "DataManager"]:
    if not hasattr(_dm, _dm_attr):
        setattr(_dm, _dm_attr, MagicMock())

# Mock backtesting results to provide the names integration.py imports
_br_mod = _ensure_mock("core_trading.strategies.backtesting.results")
for _br_attr in ["BacktestResults", "PortfolioSnapshot", "Position", "Trade"]:
    if not hasattr(_br_mod, _br_attr):
        setattr(_br_mod, _br_attr, MagicMock())

# Mock backtesting utils -- risk_analyzer.py does `from .utils import Utils`
_ensure_mock("core_trading.strategies.backtesting.utils", {"Utils": MagicMock()})

# Mock backtesting config -- risk_analyzer.py does `from .config import Config` but
# the real config.py only has BacktestConfig, not Config.  Pre-load real file and add alias.
# Also needs to import from ...indicators.consolidated_indicators which we already mock.
_bt_config_path = os.path.join(_project_root, "core_trading", "strategies", "backtesting", "config.py")
if os.path.isfile(_bt_config_path) and "core_trading.strategies.backtesting.config" not in sys.modules:
    import importlib.util
    _bt_cfg_spec = importlib.util.spec_from_file_location(
        "core_trading.strategies.backtesting.config", _bt_config_path
    )
    _bt_cfg_mod = importlib.util.module_from_spec(_bt_cfg_spec)
    sys.modules["core_trading.strategies.backtesting.config"] = _bt_cfg_mod
    _bt_cfg_spec.loader.exec_module(_bt_cfg_mod)
    # Add Config alias for risk_analyzer.py compatibility
    if not hasattr(_bt_cfg_mod, "Config"):
        _bt_cfg_mod.Config = getattr(_bt_cfg_mod, "BacktestConfig", MagicMock())

# Mock backtesting core -- risk_analyzer.py does `from .core import Core`
_bt_core_path = os.path.join(_project_root, "core_trading", "strategies", "backtesting", "core.py")
if os.path.isfile(_bt_core_path) and "core_trading.strategies.backtesting.core" not in sys.modules:
    import importlib.util
    _bt_core_spec = importlib.util.spec_from_file_location(
        "core_trading.strategies.backtesting.core", _bt_core_path
    )
    _bt_core_mod = importlib.util.module_from_spec(_bt_core_spec)
    sys.modules["core_trading.strategies.backtesting.core"] = _bt_core_mod
    _bt_core_spec.loader.exec_module(_bt_core_mod)

# Pre-create execution package module to prevent broken __init__.py from running.
# The __init__.py has bare code referencing undefined 'strategy', 'data', 'config' variables.
_exec_pkg_path = os.path.join(_project_root, "core_trading", "strategies", "execution")
if os.path.isdir(_exec_pkg_path) and "core_trading.strategies.execution" not in sys.modules:
    _exec_mod = types.ModuleType("core_trading.strategies.execution")
    _exec_mod.__path__ = [_exec_pkg_path]
    _exec_mod.__package__ = "core_trading.strategies.execution"
    sys.modules["core_trading.strategies.execution"] = _exec_mod

# Mock the arbitrage __init__ -- it has a NameError with __all__
_arb_pkg_path = os.path.join(_project_root, "core_trading", "strategies", "arbitrage")
_arb_mod = sys.modules.get("core_trading.strategies.arbitrage")
if os.path.isdir(_arb_pkg_path):
    if _arb_mod is None:
        _arb_mod = types.ModuleType("core_trading.strategies.arbitrage")
        _arb_mod.__path__ = [_arb_pkg_path]
        _arb_mod.__package__ = "core_trading.strategies.arbitrage"
        sys.modules["core_trading.strategies.arbitrage"] = _arb_mod
    _arb_mod.__all__ = []
    # The test_arbitrage.py tries `from core_trading.strategies.arbitrage import ArbitrageStrategy`
    # but ArbitrageStrategy is in the FILE arbitrage.py, shadowed by this directory package.
    # We need to load the real file and set the class on the package module.
    _arb_file = os.path.join(_project_root, "core_trading", "strategies", "arbitrage.py")
    if os.path.isfile(_arb_file):
        import importlib.util
        _arb_spec = importlib.util.spec_from_file_location(
            "core_trading.strategies._arbitrage_file", _arb_file
        )
        _arb_file_mod = importlib.util.module_from_spec(_arb_spec)
        # Ensure handler mocks exist before loading the file
        sys.modules["core_trading.strategies._arbitrage_file"] = _arb_file_mod
        _arb_spec.loader.exec_module(_arb_file_mod)
        if hasattr(_arb_file_mod, "ArbitrageStrategy"):
            _arb_mod.ArbitrageStrategy = _arb_file_mod.ArbitrageStrategy

# Mock loguru
_ensure_mock("loguru", {"logger": MagicMock()})


# ---------------------------------------------------------------------------
# OHLCV fixture helpers
# ---------------------------------------------------------------------------

def _make_ohlcv(n_rows: int, trend: str = "flat", base_price: float = 150.0,
                volatility: float = 0.02, seed: int = 42) -> pd.DataFrame:
    """Generate realistic OHLCV data.

    Args:
        n_rows: Number of bars to generate.
        trend: "up" for bullish, "down" for bearish, "flat" for sideways.
        base_price: Starting price.
        volatility: Daily volatility (fraction).
        seed: Random seed for reproducibility.

    Returns:
        DataFrame with open, high, low, close, volume columns.
    """
    rng = np.random.default_rng(seed)

    if trend == "up":
        drift = 0.001
    elif trend == "down":
        drift = -0.001
    else:
        drift = 0.0

    returns = rng.normal(drift, volatility, n_rows)
    close = base_price * np.cumprod(1 + returns)

    intra_range = close * volatility * 0.3
    high = close + rng.uniform(0, 1, n_rows) * intra_range
    low = close - rng.uniform(0, 1, n_rows) * intra_range
    open_ = low + rng.uniform(0, 1, n_rows) * (high - low)
    volume = rng.integers(500_000, 5_000_000, n_rows).astype(float)

    return pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


@pytest.fixture
def bull_data_252():
    """1 year of bullish daily OHLCV data (252 trading days)."""
    return _make_ohlcv(252, trend="up", base_price=150.0, seed=1)


@pytest.fixture
def bear_data_252():
    """1 year of bearish daily OHLCV data."""
    return _make_ohlcv(252, trend="down", base_price=150.0, seed=2)


@pytest.fixture
def flat_data_252():
    """1 year of flat/sideways daily OHLCV data."""
    return _make_ohlcv(252, trend="flat", base_price=150.0, seed=3)


@pytest.fixture
def short_data():
    """Very short OHLCV data (insufficient for most strategies)."""
    return _make_ohlcv(5, trend="flat", base_price=150.0, seed=4)


@pytest.fixture
def bull_data_60():
    """60 bars of bullish data for shorter-period strategies."""
    return _make_ohlcv(60, trend="up", base_price=100.0, seed=5)


@pytest.fixture
def bear_data_60():
    """60 bars of bearish data for shorter-period strategies."""
    return _make_ohlcv(60, trend="down", base_price=100.0, seed=6)


@pytest.fixture
def flat_data_60():
    """60 bars of flat data for shorter-period strategies."""
    return _make_ohlcv(60, trend="flat", base_price=100.0, seed=7)


@pytest.fixture
def empty_data():
    """Empty DataFrame with correct columns but no rows."""
    return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
