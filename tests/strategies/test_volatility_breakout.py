"""Tests for volatility breakout strategy files."""
import sys
import types
import pytest


# ---------------------------------------------------------------------------
# Many sub-modules under volatility_breakout fail because __init__.py
# references an undefined DEFAULT_VOLATILITY_CONFIG. We bypass __init__
# by using importlib to load individual modules directly.
# ---------------------------------------------------------------------------

def _import_submodule(module_name, file_path):
    """Import a submodule without triggering the package __init__.py."""
    import importlib.util
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    # Set __package__ so relative imports work if needed
    mod.__package__ = module_name.rsplit(".", 1)[0]
    spec.loader.exec_module(mod)
    return mod


_PKG = "core_trading.strategies.volatility_breakout"
_ROOT = "C:/Users/vince/Projects/Trading/IBKR - Algo Trader/core_trading/strategies/volatility_breakout"


class TestATRBreakoutStrategy:
    """ATRBreakoutStrategy is a skeleton; test import and class existence."""

    def test_import(self):
        from core_trading.strategies.volatility_breakout.atr_breakout_strategy import (
            ATRBreakoutStrategy,
        )
        assert ATRBreakoutStrategy is not None

    def test_class_instantiation(self):
        from core_trading.strategies.volatility_breakout.atr_breakout_strategy import (
            ATRBreakoutStrategy,
        )
        strategy = ATRBreakoutStrategy()
        assert strategy is not None


class TestVolatilityBreakoutCore:
    """Core module in volatility_breakout is a skeleton."""

    def test_import(self):
        from core_trading.strategies.volatility_breakout.core import Core
        assert Core is not None

    def test_class_instantiation(self):
        from core_trading.strategies.volatility_breakout.core import Core
        obj = Core()
        assert obj is not None


class TestDonchianBreakoutStrategy:
    """DonchianBreakoutStrategy is a skeleton."""

    def test_import(self):
        from core_trading.strategies.volatility_breakout.donchian_breakout_strategy import (
            DonchianBreakoutStrategy,
        )
        assert DonchianBreakoutStrategy is not None

    def test_class_instantiation(self):
        from core_trading.strategies.volatility_breakout.donchian_breakout_strategy import (
            DonchianBreakoutStrategy,
        )
        strategy = DonchianBreakoutStrategy()
        assert strategy is not None


class TestRangeBreakoutStrategies:
    """range_breakout_strategies is a skeleton with enums."""

    def test_import(self):
        import core_trading.strategies.volatility_breakout.range_breakout_strategies as mod
        assert mod is not None


class TestVolatilityBreakoutStrategy:
    """volatility_breakout_strategy.py is a skeleton."""

    def test_import(self):
        import core_trading.strategies.volatility_breakout.volatility_breakout_strategy as mod
        assert mod is not None


class TestVolatilityExpansionStrategies:
    """volatility_expansion_strategies is a skeleton."""

    def test_import(self):
        import core_trading.strategies.volatility_breakout.volatility_expansion_strategies as mod
        assert mod is not None


# ---------------------------------------------------------------------------
# Working file -- BollingerSqueezeStrategy
# ---------------------------------------------------------------------------


class TestBollingerSqueezeStrategy:
    """BollingerSqueezeStrategy is a skeleton with handler imports."""

    def test_import(self):
        from core_trading.strategies.volatility_breakout.bollinger_squeeze_strategy import (
            BollingerSqueezeStrategy,
        )
        assert BollingerSqueezeStrategy is not None

    def test_class_instantiation(self):
        from core_trading.strategies.volatility_breakout.bollinger_squeeze_strategy import (
            BollingerSqueezeStrategy,
        )
        strategy = BollingerSqueezeStrategy()
        assert strategy is not None

    def test_class_name(self):
        from core_trading.strategies.volatility_breakout.bollinger_squeeze_strategy import (
            BollingerSqueezeStrategy,
        )
        assert BollingerSqueezeStrategy.__name__ == "BollingerSqueezeStrategy"


# ---------------------------------------------------------------------------
# Breakout directory skeleton
# ---------------------------------------------------------------------------


class TestBollingerBandBreakoutStrategy:
    """breakout/bollinger_band_breakout_strategy.py is a skeleton."""

    def test_import(self):
        import core_trading.strategies.breakout.bollinger_band_breakout_strategy as mod
        assert mod is not None
