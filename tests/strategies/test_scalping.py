"""Tests for scalping strategy files (all skeletons with enums/classes)."""
import pytest


class TestScalpingStrategy:
    """scalping_strategy.py defines enums and a skeleton class."""

    def test_import(self):
        from core_trading.strategies.scalping.scalping_strategy import (
            ScalpingMode,
            MarketMicrostructure,
            ScalpingSignal,
            ScalpingConfig,
            ScalpingStrategy,
        )
        assert ScalpingMode is not None
        assert MarketMicrostructure is not None
        assert ScalpingSignal is not None
        assert ScalpingConfig is not None
        assert ScalpingStrategy is not None

    def test_scalping_mode_is_enum(self):
        from core_trading.strategies.scalping.scalping_strategy import ScalpingMode
        assert hasattr(ScalpingMode, "__members__")

    def test_market_microstructure_is_enum(self):
        from core_trading.strategies.scalping.scalping_strategy import MarketMicrostructure
        assert hasattr(MarketMicrostructure, "__members__")


class TestHighFrequencyScalpingStrategy:
    """high_frequency_scalping_strategy.py defines enums and skeleton classes."""

    def test_import(self):
        from core_trading.strategies.scalping.high_frequency_scalping_strategy import (
            LatencyType,
            MicrostructurePattern,
            ExecutionUrgency,
            TickData,
            OrderBookLevel,
            MicrostructureSignal,
            LatencyMeasurement,
            HFScalpingConfig,
            HighFrequencyScalpingStrategy,
        )
        assert LatencyType is not None
        assert MicrostructurePattern is not None
        assert ExecutionUrgency is not None
        assert TickData is not None
        assert OrderBookLevel is not None
        assert MicrostructureSignal is not None
        assert LatencyMeasurement is not None
        assert HFScalpingConfig is not None
        assert HighFrequencyScalpingStrategy is not None

    def test_latency_type_is_enum(self):
        from core_trading.strategies.scalping.high_frequency_scalping_strategy import LatencyType
        assert hasattr(LatencyType, "__members__")

    def test_execution_urgency_is_enum(self):
        from core_trading.strategies.scalping.high_frequency_scalping_strategy import ExecutionUrgency
        assert hasattr(ExecutionUrgency, "__members__")


class TestNewsBasedScalpingStrategy:
    """news_based_scalping_strategy.py defines enums and skeleton classes."""

    def test_import(self):
        from core_trading.strategies.scalping.news_based_scalping_strategy import (
            NewsEventType,
            NewsSentiment,
            NewsEvent,
            NewsScalpingConfig,
            NewsBasedScalpingStrategy,
        )
        assert NewsEventType is not None
        assert NewsSentiment is not None
        assert NewsEvent is not None
        assert NewsScalpingConfig is not None
        assert NewsBasedScalpingStrategy is not None

    def test_news_event_type_is_enum(self):
        from core_trading.strategies.scalping.news_based_scalping_strategy import NewsEventType
        assert hasattr(NewsEventType, "__members__")

    def test_news_sentiment_is_enum(self):
        from core_trading.strategies.scalping.news_based_scalping_strategy import NewsSentiment
        assert hasattr(NewsSentiment, "__members__")


class TestOrderFlowScalpingStrategy:
    """order_flow_scalping_strategy.py defines enums and skeleton classes."""

    def test_import(self):
        from core_trading.strategies.scalping.order_flow_scalping_strategy import (
            OrderFlowType,
            LiquidityType,
            InstitutionalActivity,
            OrderBookLevel,
            OrderBookSnapshot,
            TradeExecution,
            OrderFlowMetrics,
            OrderFlowScalpingConfig,
            OrderFlowScalpingStrategy,
        )
        assert OrderFlowType is not None
        assert LiquidityType is not None
        assert InstitutionalActivity is not None
        assert OrderBookLevel is not None
        assert OrderBookSnapshot is not None
        assert TradeExecution is not None
        assert OrderFlowMetrics is not None
        assert OrderFlowScalpingConfig is not None
        assert OrderFlowScalpingStrategy is not None

    def test_order_flow_type_is_enum(self):
        from core_trading.strategies.scalping.order_flow_scalping_strategy import OrderFlowType
        assert hasattr(OrderFlowType, "__members__")

    def test_liquidity_type_is_enum(self):
        from core_trading.strategies.scalping.order_flow_scalping_strategy import LiquidityType
        assert hasattr(LiquidityType, "__members__")


class TestStatisticalArbitrageScalpingStrategy:
    """statistical_arbitrage_scalping_strategy.py defines enums and skeleton classes."""

    def test_import(self):
        from core_trading.strategies.scalping.statistical_arbitrage_scalping_strategy import (
            ArbitrageType,
            MeanReversionSignal,
            CointegrationStatus,
            TradingPair,
            ArbitrageOpportunity,
            SpreadAnalysis,
            StatArbConfig,
            StatisticalArbitrageScalpingStrategy,
        )
        assert ArbitrageType is not None
        assert MeanReversionSignal is not None
        assert CointegrationStatus is not None
        assert TradingPair is not None
        assert ArbitrageOpportunity is not None
        assert SpreadAnalysis is not None
        assert StatArbConfig is not None
        assert StatisticalArbitrageScalpingStrategy is not None

    def test_arbitrage_type_is_enum(self):
        from core_trading.strategies.scalping.statistical_arbitrage_scalping_strategy import ArbitrageType
        assert hasattr(ArbitrageType, "__members__")

    def test_mean_reversion_signal_is_enum(self):
        from core_trading.strategies.scalping.statistical_arbitrage_scalping_strategy import MeanReversionSignal
        assert hasattr(MeanReversionSignal, "__members__")
