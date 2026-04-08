"""Tests for pair trading strategy files."""
import pytest
import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Working files -- pair_trading utilities
# ---------------------------------------------------------------------------


class TestCorrelationAnalysis:
    """Correlation analysis module defines enums and skeleton classes."""

    def test_import_enums(self):
        from core_trading.strategies.pair_trading.correlation_analysis import (
            CorrelationType,
            StationarityTest,
        )
        assert CorrelationType is not None
        assert StationarityTest is not None

    def test_correlation_type_is_enum(self):
        from core_trading.strategies.pair_trading.correlation_analysis import CorrelationType
        assert hasattr(CorrelationType, "__members__")

    def test_stationarity_test_is_enum(self):
        from core_trading.strategies.pair_trading.correlation_analysis import StationarityTest
        assert hasattr(StationarityTest, "__members__")

    def test_dataclasses_exist(self):
        from core_trading.strategies.pair_trading.correlation_analysis import (
            CorrelationResult,
            CointegrationResult,
            StationarityResult,
            SpreadAnalysis,
        )
        assert CorrelationResult is not None
        assert CointegrationResult is not None
        assert StationarityResult is not None
        assert SpreadAnalysis is not None

    def test_analyzer_classes_exist(self):
        from core_trading.strategies.pair_trading.correlation_analysis import (
            CorrelationAnalyzer,
            CointegrationTester,
            StationarityTester,
            SpreadAnalyzer,
            TimeSeriesAnalyzer,
        )
        assert CorrelationAnalyzer is not None
        assert CointegrationTester is not None
        assert StationarityTester is not None
        assert SpreadAnalyzer is not None
        assert TimeSeriesAnalyzer is not None


class TestPairSelection:
    """Pair selection module defines enums and skeleton classes."""

    def test_import_enums(self):
        from core_trading.strategies.pair_trading.pair_selection import (
            PairSelectionMethod,
            SectorFilter,
        )
        assert PairSelectionMethod is not None
        assert SectorFilter is not None

    def test_pair_selection_method_is_enum(self):
        from core_trading.strategies.pair_trading.pair_selection import PairSelectionMethod
        assert hasattr(PairSelectionMethod, "__members__")

    def test_sector_filter_is_enum(self):
        from core_trading.strategies.pair_trading.pair_selection import SectorFilter
        assert hasattr(SectorFilter, "__members__")

    def test_dataclasses_exist(self):
        from core_trading.strategies.pair_trading.pair_selection import (
            PairMetrics,
            PairSelectionConfig,
        )
        assert PairMetrics is not None
        assert PairSelectionConfig is not None

    def test_analyzer_classes_exist(self):
        from core_trading.strategies.pair_trading.pair_selection import (
            StatisticalPairAnalyzer,
            PairScreener,
            PairRanking,
            PairSelectionEngine,
        )
        assert StatisticalPairAnalyzer is not None
        assert PairScreener is not None
        assert PairRanking is not None
        assert PairSelectionEngine is not None


class TestPerformanceAnalytics:
    """Performance analytics module defines enums and skeleton classes."""

    def test_import_enums(self):
        try:
            from core_trading.strategies.pair_trading.performance_analytics import (
                PerformancePeriod,
                AttributionType,
            )
            assert PerformancePeriod is not None
            assert AttributionType is not None
        except (ImportError, ModuleNotFoundError):
            pytest.skip("Missing dependency for performance_analytics")

    def test_dataclasses_exist(self):
        try:
            from core_trading.strategies.pair_trading.performance_analytics import (
                TradeResult,
                PerformanceMetrics,
                AttributionResult,
            )
            assert TradeResult is not None
            assert PerformanceMetrics is not None
            assert AttributionResult is not None
        except (ImportError, ModuleNotFoundError):
            pytest.skip("Missing dependency for performance_analytics")

    def test_analyzer_classes_exist(self):
        try:
            from core_trading.strategies.pair_trading.performance_analytics import (
                PerformanceCalculator,
                TradeAnalyzer,
                PerformanceAnalyzer,
            )
            assert PerformanceCalculator is not None
            assert TradeAnalyzer is not None
            assert PerformanceAnalyzer is not None
        except (ImportError, ModuleNotFoundError):
            pytest.skip("Missing dependency for performance_analytics")


class TestRiskManagement:
    """Risk management module defines enums and skeleton classes."""

    def test_import_enums(self):
        from core_trading.strategies.pair_trading.risk_management import (
            RiskLevel,
            AlertType,
        )
        assert RiskLevel is not None
        assert AlertType is not None

    def test_risk_level_is_enum(self):
        from core_trading.strategies.pair_trading.risk_management import RiskLevel
        assert hasattr(RiskLevel, "__members__")

    def test_alert_type_is_enum(self):
        from core_trading.strategies.pair_trading.risk_management import AlertType
        assert hasattr(AlertType, "__members__")

    def test_dataclasses_exist(self):
        from core_trading.strategies.pair_trading.risk_management import (
            RiskMetrics,
            RiskAlert,
            RiskLimits,
        )
        assert RiskMetrics is not None
        assert RiskAlert is not None
        assert RiskLimits is not None

    def test_manager_classes_exist(self):
        from core_trading.strategies.pair_trading.risk_management import (
            PositionSizer,
            RiskMonitor,
            PairsRiskManager,
        )
        assert PositionSizer is not None
        assert RiskMonitor is not None
        assert PairsRiskManager is not None


# ---------------------------------------------------------------------------
# Skeleton files -- verify classes exist and modules import cleanly
# ---------------------------------------------------------------------------


class TestConvergenceStrategy:
    """convergence_strategy.py is a skeleton."""

    def test_import(self):
        import core_trading.strategies.pair_trading.convergence_strategy as mod
        assert mod is not None


class TestDivergenceStrategy:
    """divergence_strategy.py is a skeleton."""

    def test_import(self):
        import core_trading.strategies.pair_trading.divergence_strategy as mod
        assert mod is not None

    def test_classes_exist(self):
        from core_trading.strategies.pair_trading.divergence_strategy import (
            PairsSignal,
            PairsRegime,
            PairType,
            PairsConfig,
        )
        assert PairsSignal is not None
        assert PairsRegime is not None
        assert PairType is not None
        assert PairsConfig is not None


class TestInstitutionalPairsTradingStrategy:
    """institutional_pairs_trading_strategy.py is a skeleton."""

    def test_import(self):
        try:
            import core_trading.strategies.pair_trading.institutional_pairs_trading_strategy as mod
            assert mod is not None
        except ImportError:
            pytest.skip("Missing dependency for institutional_pairs_trading_strategy")

    def test_classes_exist(self):
        try:
            from core_trading.strategies.pair_trading.institutional_pairs_trading_strategy import (
                PairRelationship,
                PairSignalType,
                SpreadRegime,
                RiskLevel,
                PairsTradingStrategy,
            )
            assert PairRelationship is not None
            assert PairSignalType is not None
            assert SpreadRegime is not None
            assert RiskLevel is not None
            assert PairsTradingStrategy is not None
        except ImportError:
            pytest.skip("Missing dependency for institutional_pairs_trading_strategy")


class TestPairsStrategies:
    """pairs_strategies.py is a skeleton."""

    def test_import(self):
        try:
            import core_trading.strategies.pair_trading.pairs_strategies as mod
            assert mod is not None
        except ImportError:
            pytest.skip("Missing dependency for pairs_strategies")


class TestPairsTradingStrategies:
    """pairs_trading_strategies.py is a skeleton."""

    def test_import(self):
        import core_trading.strategies.pair_trading.pairs_trading_strategies as mod
        assert mod is not None
