"""Tests for multi-factor strategy files (all skeletons with enums/classes)."""
import pytest


class TestMultiFactorModels:
    """multi_factor_models.py defines enums and skeleton classes."""

    def test_import_enums(self):
        from core_trading.strategies.multi_factor.multi_factor_models import (
            FactorSignal,
            FactorType,
            FactorModel,
            MarketRegime,
        )
        assert FactorSignal is not None
        assert FactorType is not None
        assert FactorModel is not None
        assert MarketRegime is not None

    def test_factor_signal_is_enum(self):
        from core_trading.strategies.multi_factor.multi_factor_models import FactorSignal
        assert hasattr(FactorSignal, "__members__")

    def test_factor_type_is_enum(self):
        from core_trading.strategies.multi_factor.multi_factor_models import FactorType
        assert hasattr(FactorType, "__members__")

    def test_factor_model_is_enum(self):
        from core_trading.strategies.multi_factor.multi_factor_models import FactorModel
        assert hasattr(FactorModel, "__members__")

    def test_market_regime_is_enum(self):
        from core_trading.strategies.multi_factor.multi_factor_models import MarketRegime
        assert hasattr(MarketRegime, "__members__")

    def test_dataclasses_exist(self):
        from core_trading.strategies.multi_factor.multi_factor_models import (
            FactorConfig,
            FactorExposure,
            FactorReturn,
            PortfolioMetrics,
            FactorModelResult,
        )
        assert FactorConfig is not None
        assert FactorExposure is not None
        assert FactorReturn is not None
        assert PortfolioMetrics is not None
        assert FactorModelResult is not None

    def test_main_classes_exist(self):
        from core_trading.strategies.multi_factor.multi_factor_models import (
            BaseFactorModel,
            FamaFrenchThreeFactorModel,
            MultiFactorTradingManager,
        )
        assert BaseFactorModel is not None
        assert FamaFrenchThreeFactorModel is not None
        assert MultiFactorTradingManager is not None


class TestOptimizedMultiFactorModels:
    """optimized_multi_factor_models.py defines skeleton classes."""

    def test_import(self):
        from core_trading.strategies.multi_factor.optimized_multi_factor_models import (
            BoundedCache,
            VectorizedMath,
            OptimizedFactorData,
            OptimizedBaseFactorModel,
            OptimizedFamaFrenchThreeFactorModel,
        )
        assert BoundedCache is not None
        assert VectorizedMath is not None
        assert OptimizedFactorData is not None
        assert OptimizedBaseFactorModel is not None
        assert OptimizedFamaFrenchThreeFactorModel is not None
