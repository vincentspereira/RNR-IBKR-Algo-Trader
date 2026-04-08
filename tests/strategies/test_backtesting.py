"""Tests for backtesting strategy files."""
import pytest


# ---------------------------------------------------------------------------
# Working files (skeleton with handler architecture)
# ---------------------------------------------------------------------------


class TestBacktestEngine:
    """backtest_engine.py defines skeleton classes."""

    def test_import(self):
        from core_trading.strategies.backtesting.backtest_engine import (
            MarketData,
            Order,
            Portfolio,
            ExecutionEngine,
            BacktestEngine,
        )
        assert MarketData is not None
        assert Order is not None
        assert Portfolio is not None
        assert ExecutionEngine is not None
        assert BacktestEngine is not None


class TestIntegration:
    """integration.py defines skeleton classes."""

    def test_import(self):
        from core_trading.strategies.backtesting.integration import (
            EventMessage,
            KafkaEventStreamer,
            KafkaConfig,
            IntegrationConfig,
            EventStreamer,
            NautilusIntegration,
            IntegratedBacktestEngine,
        )
        assert EventMessage is not None
        assert KafkaEventStreamer is not None
        assert KafkaConfig is not None
        assert IntegrationConfig is not None
        assert EventStreamer is not None
        assert NautilusIntegration is not None
        assert IntegratedBacktestEngine is not None


class TestPerformanceAnalyzer:
    """performance_analyzer.py is a skeleton with handler architecture."""

    def test_import(self):
        from core_trading.strategies.backtesting.performance_analyzer import PerformanceAnalyzer
        assert PerformanceAnalyzer is not None

    def test_class_instantiation(self):
        from core_trading.strategies.backtesting.performance_analyzer import PerformanceAnalyzer
        analyzer = PerformanceAnalyzer()
        assert analyzer is not None


class TestResults:
    """results.py is a skeleton with handler architecture."""

    def test_import(self):
        from core_trading.strategies.backtesting.results import BacktestResults
        assert BacktestResults is not None

    def test_class_instantiation(self):
        from core_trading.strategies.backtesting.results import BacktestResults
        results = BacktestResults()
        assert results is not None


class TestVisualization:
    """visualization.py defines skeleton classes."""

    def test_import(self):
        from core_trading.strategies.backtesting.visualization import (
            ChartConfig,
            VisualizationEngine,
        )
        assert ChartConfig is not None
        assert VisualizationEngine is not None


# ---------------------------------------------------------------------------
# Skeleton files
# ---------------------------------------------------------------------------


class TestBacktestConfig:
    """config.py defines skeleton enums and classes."""

    def test_import_enums(self):
        from core_trading.strategies.backtesting.config import (
            BacktestMode,
            RebalanceFrequency,
            BenchmarkType,
        )
        assert BacktestMode is not None
        assert RebalanceFrequency is not None
        assert BenchmarkType is not None

    def test_backtest_mode_is_enum(self):
        from core_trading.strategies.backtesting.config import BacktestMode
        assert hasattr(BacktestMode, "__members__")

    def test_classes_exist(self):
        from core_trading.strategies.backtesting.config import (
            TransactionCosts,
            RiskLimits,
            BacktestConfig,
        )
        assert TransactionCosts is not None
        assert RiskLimits is not None
        assert BacktestConfig is not None


class TestBacktestCore:
    """core.py is a skeleton."""

    def test_import(self):
        from core_trading.strategies.backtesting.core import Core
        assert Core is not None

    def test_class_instantiation(self):
        from core_trading.strategies.backtesting.core import Core
        obj = Core()
        assert obj is not None


class TestDataManager:
    """data_manager.py defines skeleton classes."""

    def test_import(self):
        from core_trading.strategies.backtesting.data_manager import (
            DataConfig,
            MarketData,
            DataSource,
            YahooFinanceSource,
            MockDataSource,
            DataManager,
        )
        assert DataConfig is not None
        assert MarketData is not None
        assert DataSource is not None
        assert YahooFinanceSource is not None
        assert MockDataSource is not None
        assert DataManager is not None


class TestMetrics:
    """metrics.py defines skeleton classes."""

    def test_import(self):
        from core_trading.strategies.backtesting.metrics import (
            PerformanceMetrics,
            RiskMetrics,
            TradeMetrics,
            DrawdownMetrics,
            BenchmarkMetrics,
            MetricsCalculator,
        )
        assert PerformanceMetrics is not None
        assert RiskMetrics is not None
        assert TradeMetrics is not None
        assert DrawdownMetrics is not None
        assert BenchmarkMetrics is not None
        assert MetricsCalculator is not None


class TestPortfolioSimulator:
    """portfolio_simulator.py defines skeleton enums and classes."""

    def test_import_enums(self):
        from core_trading.strategies.backtesting.portfolio_simulator import (
            OrderType,
            OrderSide,
            OrderStatus,
        )
        assert OrderType is not None
        assert OrderSide is not None
        assert OrderStatus is not None

    def test_classes_exist(self):
        from core_trading.strategies.backtesting.portfolio_simulator import (
            Order,
            PortfolioState,
            PortfolioSimulator,
        )
        assert Order is not None
        assert PortfolioState is not None
        assert PortfolioSimulator is not None


class TestReportGenerator:
    """report_generator.py defines skeleton classes."""

    def test_import(self):
        from core_trading.strategies.backtesting.report_generator import (
            ReportConfig,
            ReportGenerator,
        )
        assert ReportConfig is not None
        assert ReportGenerator is not None


class TestRiskAnalyzer:
    """risk_analyzer.py is a skeleton."""

    def test_import(self):
        from core_trading.strategies.backtesting.risk_analyzer import RiskAnalyzer
        assert RiskAnalyzer is not None
