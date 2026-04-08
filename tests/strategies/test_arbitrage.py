"""Tests for arbitrage strategy files."""
import pytest


# ---------------------------------------------------------------------------
# Top-level arbitrage.py (skeleton with handlers)
# ---------------------------------------------------------------------------


class TestArbitrageStrategy:
    """Top-level arbitrage.py is a skeleton with handler architecture."""

    def test_import(self):
        from core_trading.strategies.arbitrage import ArbitrageStrategy
        assert ArbitrageStrategy is not None

    def test_class_instantiation(self):
        from core_trading.strategies.arbitrage import ArbitrageStrategy
        strategy = ArbitrageStrategy()
        assert strategy is not None

    def test_class_name(self):
        from core_trading.strategies.arbitrage import ArbitrageStrategy
        assert ArbitrageStrategy.__name__ == "ArbitrageStrategy"


# ---------------------------------------------------------------------------
# arbitrage/index_arbitrage.py (skeleton with enums and classes)
# ---------------------------------------------------------------------------


class TestIndexArbitrage:
    """index_arbitrage.py defines enums and skeleton classes."""

    def test_import_enums(self):
        from core_trading.strategies.arbitrage.index_arbitrage import (
            IndexArbitrageType,
        )
        assert IndexArbitrageType is not None

    def test_index_arbitrage_type_is_enum(self):
        from core_trading.strategies.arbitrage.index_arbitrage import IndexArbitrageType
        assert hasattr(IndexArbitrageType, "__members__")

    def test_dataclasses_exist(self):
        from core_trading.strategies.arbitrage.index_arbitrage import (
            BasketComponent,
            ArbitrageOpportunity,
            IndexArbitrageAnalyzer,
        )
        assert BasketComponent is not None
        assert ArbitrageOpportunity is not None
        assert IndexArbitrageAnalyzer is not None


# ---------------------------------------------------------------------------
# arbitrage/volatility_arbitrage.py (skeleton with enums and classes)
# ---------------------------------------------------------------------------


class TestVolatilityArbitrage:
    """volatility_arbitrage.py defines enums and skeleton classes."""

    def test_import_enums(self):
        from core_trading.strategies.arbitrage.volatility_arbitrage import (
            VolatilityArbitrageType,
        )
        assert VolatilityArbitrageType is not None

    def test_volatility_arbitrage_type_is_enum(self):
        from core_trading.strategies.arbitrage.volatility_arbitrage import VolatilityArbitrageType
        assert hasattr(VolatilityArbitrageType, "__members__")

    def test_dataclasses_exist(self):
        from core_trading.strategies.arbitrage.volatility_arbitrage import (
            VolatilitySurface,
            VolatilityOpportunity,
            VolatilityAnalyzer,
        )
        assert VolatilitySurface is not None
        assert VolatilityOpportunity is not None
        assert VolatilityAnalyzer is not None


# ---------------------------------------------------------------------------
# arbitrage/multi_factor_models.py (skeleton with enums and classes)
# ---------------------------------------------------------------------------


class TestArbitrageMultiFactorModels:
    """multi_factor_models.py under arbitrage defines enums and skeleton classes."""

    def test_import_enums(self):
        from core_trading.strategies.arbitrage.multi_factor_models import (
            FactorType,
        )
        assert FactorType is not None

    def test_factor_type_is_enum(self):
        from core_trading.strategies.arbitrage.multi_factor_models import FactorType
        assert hasattr(FactorType, "__members__")

    def test_dataclasses_exist(self):
        from core_trading.strategies.arbitrage.multi_factor_models import (
            FactorExposure,
            FactorModel,
            FactorAnalyzer,
        )
        assert FactorExposure is not None
        assert FactorModel is not None
        assert FactorAnalyzer is not None


# ---------------------------------------------------------------------------
# arbitrage/arbitrage_strategies.py (skeleton with enums and classes)
# ---------------------------------------------------------------------------


class TestArbitrageStrategies:
    """arbitrage_strategies.py defines enums and skeleton classes."""

    def test_import_enums(self):
        from core_trading.strategies.arbitrage.arbitrage_strategies import (
            ArbitrageSignal,
            ArbitrageType,
            ArbitrageRegime,
        )
        assert ArbitrageSignal is not None
        assert ArbitrageType is not None
        assert ArbitrageRegime is not None

    def test_arbitrage_signal_is_enum(self):
        from core_trading.strategies.arbitrage.arbitrage_strategies import ArbitrageSignal
        assert hasattr(ArbitrageSignal, "__members__")

    def test_arbitrage_type_is_enum(self):
        from core_trading.strategies.arbitrage.arbitrage_strategies import ArbitrageType
        assert hasattr(ArbitrageType, "__members__")

    def test_arbitrage_regime_is_enum(self):
        from core_trading.strategies.arbitrage.arbitrage_strategies import ArbitrageRegime
        assert hasattr(ArbitrageRegime, "__members__")

    def test_dataclasses_exist(self):
        from core_trading.strategies.arbitrage.arbitrage_strategies import (
            ArbitrageConfig,
        )
        assert ArbitrageConfig is not None
