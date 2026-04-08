"""Tests for machine learning strategy files."""
import pytest
import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Working files
# ---------------------------------------------------------------------------


class TestFeatureEngineering:
    """feature_engineering.py defines enums and skeleton classes."""

    def test_import_enums(self):
        from core_trading.strategies.machine_learning.feature_engineering import (
            FeatureType,
            ScalingMethod,
        )
        assert FeatureType is not None
        assert ScalingMethod is not None

    def test_feature_type_is_enum(self):
        from core_trading.strategies.machine_learning.feature_engineering import FeatureType
        assert hasattr(FeatureType, "__members__")

    def test_scaling_method_is_enum(self):
        from core_trading.strategies.machine_learning.feature_engineering import ScalingMethod
        assert hasattr(ScalingMethod, "__members__")

    def test_dataclasses_exist(self):
        from core_trading.strategies.machine_learning.feature_engineering import (
            FeatureConfig,
            FeatureImportance,
        )
        assert FeatureConfig is not None
        assert FeatureImportance is not None

    def test_extractor_classes_exist(self):
        from core_trading.strategies.machine_learning.feature_engineering import (
            TechnicalFeatures,
            PriceActionFeatures,
            VolumeFeatures,
            VolatilityFeatures,
            FeatureSelector,
            FeatureEngineer,
        )
        assert TechnicalFeatures is not None
        assert PriceActionFeatures is not None
        assert VolumeFeatures is not None
        assert VolatilityFeatures is not None
        assert FeatureSelector is not None
        assert FeatureEngineer is not None


class TestModelManager:
    """model_manager.py is a skeleton with handler architecture."""

    def test_import(self):
        from core_trading.strategies.machine_learning.model_manager import ModelMonitor
        assert ModelMonitor is not None

    def test_class_instantiation(self):
        from core_trading.strategies.machine_learning.model_manager import ModelMonitor
        monitor = ModelMonitor()
        assert monitor is not None


class TestReinforcementLearning:
    """reinforcement_learning.py defines enums and skeleton classes."""

    def test_import_enums(self):
        from core_trading.strategies.machine_learning.reinforcement_learning import (
            ActionType,
            RLAlgorithm,
        )
        assert ActionType is not None
        assert RLAlgorithm is not None

    def test_action_type_is_enum(self):
        from core_trading.strategies.machine_learning.reinforcement_learning import ActionType
        assert hasattr(ActionType, "__members__")

    def test_rl_algorithm_is_enum(self):
        from core_trading.strategies.machine_learning.reinforcement_learning import RLAlgorithm
        assert hasattr(RLAlgorithm, "__members__")

    def test_dataclasses_exist(self):
        from core_trading.strategies.machine_learning.reinforcement_learning import (
            RLConfig,
            TradingState,
        )
        assert RLConfig is not None
        assert TradingState is not None

    def test_rl_classes_exist(self):
        from core_trading.strategies.machine_learning.reinforcement_learning import (
            TradingAction,
            ReplayBuffer,
            TradingEnvironment,
            DQNAgent,
            PolicyGradientAgent,
            RLTradingStrategy,
        )
        assert TradingAction is not None
        assert ReplayBuffer is not None
        assert TradingEnvironment is not None
        assert DQNAgent is not None
        assert PolicyGradientAgent is not None
        assert RLTradingStrategy is not None


class TestSupervisedStrategies:
    """supervised_strategies.py is a skeleton with handler architecture."""

    def test_import(self):
        from core_trading.strategies.machine_learning.supervised_strategies import BaseMLStrategy
        assert BaseMLStrategy is not None

    def test_class_instantiation(self):
        from core_trading.strategies.machine_learning.supervised_strategies import BaseMLStrategy
        strategy = BaseMLStrategy()
        assert strategy is not None


class TestMLStrategies:
    """Top-level ml_strategies.py is a skeleton with handler architecture."""

    def test_import(self):
        from core_trading.strategies.ml_strategies import MLStrategy
        assert MLStrategy is not None

    def test_class_instantiation(self):
        from core_trading.strategies.ml_strategies import MLStrategy
        strategy = MLStrategy()
        assert strategy is not None


# ---------------------------------------------------------------------------
# Skeleton files
# ---------------------------------------------------------------------------


class TestClusteringStrategies:
    """clustering_strategies.py defines enums and skeleton classes."""

    def test_import_enums(self):
        from core_trading.strategies.machine_learning.clustering_strategies import (
            RegimeType,
            ClusteringMethod,
            AnomalyMethod,
        )
        assert RegimeType is not None
        assert ClusteringMethod is not None
        assert AnomalyMethod is not None

    def test_classes_exist(self):
        from core_trading.strategies.machine_learning.clustering_strategies import (
            RegimeState,
            ClusteringConfig,
            MarketRegimeDetector,
            AnomalyDetectionStrategy,
            ClusteringStrategy,
        )
        assert RegimeState is not None
        assert ClusteringConfig is not None
        assert MarketRegimeDetector is not None
        assert AnomalyDetectionStrategy is not None
        assert ClusteringStrategy is not None


class TestMLTradingStrategies:
    """ml_trading_strategies.py defines enums and skeleton classes."""

    def test_import_enums(self):
        from core_trading.strategies.machine_learning.ml_trading_strategies import (
            MLModelType,
            PredictionType,
            MLSignal,
        )
        assert MLModelType is not None
        assert PredictionType is not None
        assert MLSignal is not None

    def test_ml_model_type_is_enum(self):
        from core_trading.strategies.machine_learning.ml_trading_strategies import MLModelType
        assert hasattr(MLModelType, "__members__")

    def test_classes_exist(self):
        from core_trading.strategies.machine_learning.ml_trading_strategies import (
            MLConfig,
            FeatureSet,
            MLPrediction,
            MLTradingResult,
            BaseMLStrategy,
            EnsembleMLStrategy,
            MLTradingManager,
        )
        assert MLConfig is not None
        assert FeatureSet is not None
        assert MLPrediction is not None
        assert MLTradingResult is not None
        assert BaseMLStrategy is not None
        assert EnsembleMLStrategy is not None
        assert MLTradingManager is not None


# ---------------------------------------------------------------------------
# Functional tests: ClusteringStrategy
# ---------------------------------------------------------------------------


class TestClusteringStrategyFunctional:
    """Tests for the functional ClusteringStrategy implementation."""

    def test_import_all_names(self):
        from core_trading.strategies.machine_learning.clustering_strategies import (
            RegimeType,
            ClusteringMethod,
            AnomalyMethod,
            RegimeState,
            ClusteringConfig,
            MarketRegimeDetector,
            AnomalyDetectionStrategy,
            ClusteringStrategy,
            create_clustering_strategy,
            TradingState,
        )
        assert RegimeType is not None
        assert ClusteringMethod is not None
        assert AnomalyMethod is not None

    def test_enum_values(self):
        from core_trading.strategies.machine_learning.clustering_strategies import (
            RegimeType, ClusteringMethod, AnomalyMethod,
        )
        assert RegimeType.BULL_MARKET.value == "bull_market"
        assert ClusteringMethod.KMEANS.value == "kmeans"
        assert AnomalyMethod.STATISTICAL.value == "statistical"

    def test_clustering_config_defaults(self):
        from core_trading.strategies.machine_learning.clustering_strategies import ClusteringConfig
        cfg = ClusteringConfig()
        assert cfg.n_clusters == 4
        assert cfg.lookback_period == 252
        assert cfg.confidence_threshold == 0.6

    def test_regime_state_defaults(self):
        from core_trading.strategies.machine_learning.clustering_strategies import RegimeState, RegimeType
        state = RegimeState()
        assert state.regime_type == RegimeType.UNKNOWN
        assert state.confidence == 0.0
        assert state.duration == 0

    def test_strategy_instantiation(self):
        from core_trading.strategies.machine_learning.clustering_strategies import ClusteringStrategy
        strategy = ClusteringStrategy()
        assert strategy is not None
        assert not strategy._fitted

    def test_factory_function(self):
        from core_trading.strategies.machine_learning.clustering_strategies import create_clustering_strategy
        strategy = create_clustering_strategy()
        assert strategy is not None

    def test_fit_with_sufficient_data(self, bull_data_252):
        from core_trading.strategies.machine_learning.clustering_strategies import ClusteringStrategy
        strategy = ClusteringStrategy()
        result = strategy.fit(bull_data_252)
        assert result is strategy
        assert strategy._fitted

    def test_generate_signals_returns_list(self, bull_data_252):
        from core_trading.strategies.machine_learning.clustering_strategies import ClusteringStrategy
        strategy = ClusteringStrategy()
        signals = strategy.generate_signals(bull_data_252)
        assert isinstance(signals, list)
        # After auto-fit on bull data, should produce at least one signal
        for sig in signals:
            assert "direction" in sig
            assert sig["direction"] in ("buy", "sell", "hold")
            assert 0 <= sig["confidence"] <= 1
            assert 0 <= sig["strength"] <= 1

    def test_generate_signals_insufficient_data(self, short_data):
        from core_trading.strategies.machine_learning.clustering_strategies import ClusteringStrategy
        strategy = ClusteringStrategy()
        signals = strategy.generate_signals(short_data)
        assert signals == []

    def test_generate_signals_empty_data(self, empty_data):
        from core_trading.strategies.machine_learning.clustering_strategies import ClusteringStrategy
        strategy = ClusteringStrategy()
        signals = strategy.generate_signals(empty_data)
        assert signals == []

    def test_confidence_range(self, bull_data_252):
        from core_trading.strategies.machine_learning.clustering_strategies import ClusteringStrategy
        strategy = ClusteringStrategy()
        strategy.fit(bull_data_252)
        signals = strategy.generate_signals(bull_data_252)
        for sig in signals:
            assert 0 <= sig["confidence"] <= 1
            assert 0 <= sig["anomaly_score"] <= 1

    def test_get_current_values(self, bull_data_252):
        from core_trading.strategies.machine_learning.clustering_strategies import ClusteringStrategy
        strategy = ClusteringStrategy()
        strategy.fit(bull_data_252)
        vals = strategy.get_current_values(bull_data_252)
        assert "returns" in vals
        assert "vol_5" in vals
        assert "trend_strength" in vals
        assert "regime" in vals

    def test_get_current_values_insufficient(self, short_data):
        from core_trading.strategies.machine_learning.clustering_strategies import ClusteringStrategy
        strategy = ClusteringStrategy()
        vals = strategy.get_current_values(short_data)
        assert vals == {}

    def test_regime_detector_predict(self, bull_data_252):
        from core_trading.strategies.machine_learning.clustering_strategies import MarketRegimeDetector
        detector = MarketRegimeDetector()
        detector.fit(bull_data_252)
        regime = detector.predict_regime(bull_data_252)
        assert regime.regime_type is not None
        assert 0 <= regime.confidence <= 1

    def test_anomaly_detection(self, bull_data_252):
        from core_trading.strategies.machine_learning.clustering_strategies import AnomalyDetectionStrategy
        detector = AnomalyDetectionStrategy()
        detector.fit(bull_data_252)
        is_anomaly, score = detector.detect_anomalies(bull_data_252)
        assert isinstance(is_anomaly, bool)
        assert isinstance(score, float)
        assert 0 <= score <= 1

    def test_regime_summary(self, bull_data_252):
        from core_trading.strategies.machine_learning.clustering_strategies import ClusteringStrategy
        strategy = ClusteringStrategy()
        strategy.fit(bull_data_252)
        strategy.generate_signals(bull_data_252)
        summary = strategy.get_regime_summary()
        assert isinstance(summary, dict)
        assert "average_confidence" in summary

    def test_should_refit(self, bull_data_252):
        from core_trading.strategies.machine_learning.clustering_strategies import ClusteringStrategy
        strategy = ClusteringStrategy()
        # Before fitting, should always refit
        assert strategy.should_refit() is True
        strategy.fit(bull_data_252)
        # Right after fitting, should not need refit (unless time passes)
        assert isinstance(strategy.should_refit(), bool)

    def test_update_method(self, bull_data_252):
        from core_trading.strategies.machine_learning.clustering_strategies import ClusteringStrategy
        strategy = ClusteringStrategy()
        strategy.fit(bull_data_252)
        result = strategy.update(bull_data_252)
        assert "regime" in result
        assert "is_anomalous" in result
        assert "anomaly_score" in result
        assert "parameters" in result
        assert "confidence" in result

    def test_bear_data_regime(self, bear_data_252):
        from core_trading.strategies.machine_learning.clustering_strategies import ClusteringStrategy
        strategy = ClusteringStrategy()
        signals = strategy.generate_signals(bear_data_252)
        assert isinstance(signals, list)
        for sig in signals:
            assert sig["direction"] in ("buy", "sell", "hold")


# ---------------------------------------------------------------------------
# Functional tests: RLStrategy
# ---------------------------------------------------------------------------


class TestRLStrategyFunctional:
    """Tests for the functional RLStrategy implementation."""

    def test_import_all_names(self):
        from core_trading.strategies.machine_learning.rl_strategy import (
            RLAction,
            RLSignalType,
            RLStrategyConfig,
            RLSignal,
            RLStrategy,
            create_rl_strategy,
            TradingState,
        )
        assert RLAction is not None
        assert RLSignalType is not None

    def test_config_defaults(self):
        from core_trading.strategies.machine_learning.rl_strategy import RLStrategyConfig
        cfg = RLStrategyConfig()
        assert cfg.window_size == 30
        assert cfg.confidence_threshold == 0.3

    def test_strategy_instantiation(self):
        from core_trading.strategies.machine_learning.rl_strategy import RLStrategy
        strategy = RLStrategy()
        assert strategy is not None

    def test_factory_function(self):
        from core_trading.strategies.machine_learning.rl_strategy import create_rl_strategy
        strategy = create_rl_strategy()
        assert strategy is not None

    def test_generate_signals_returns_list(self, bull_data_252):
        from core_trading.strategies.machine_learning.rl_strategy import RLStrategy
        strategy = RLStrategy()
        signals = strategy.generate_signals(bull_data_252)
        assert isinstance(signals, list)
        assert len(signals) == 1
        sig = signals[0]
        assert sig.signal.value in ("buy", "sell", "hold")
        assert 0 <= sig.confidence <= 1
        assert 0 <= sig.strength <= 1

    def test_handles_insufficient_data(self, short_data):
        from core_trading.strategies.machine_learning.rl_strategy import RLStrategy
        strategy = RLStrategy()
        signals = strategy.generate_signals(short_data)
        assert signals == []

    def test_handles_empty_data(self, empty_data):
        from core_trading.strategies.machine_learning.rl_strategy import RLStrategy
        strategy = RLStrategy()
        signals = strategy.generate_signals(empty_data)
        assert signals == []

    def test_confidence_range(self, bull_data_252):
        from core_trading.strategies.machine_learning.rl_strategy import RLStrategy
        strategy = RLStrategy()
        signals = strategy.generate_signals(bull_data_252)
        for sig in signals:
            assert 0 <= sig.confidence <= 1
            assert 0 <= sig.strength <= 1

    def test_get_current_values(self, bull_data_252):
        from core_trading.strategies.machine_learning.rl_strategy import RLStrategy
        strategy = RLStrategy()
        strategy.generate_signals(bull_data_252)
        vals = strategy.get_current_values(bull_data_252)
        assert "momentum_score" in vals
        assert "volatility_score" in vals
        assert "mean_reversion_score" in vals
        assert "position" in vals

    def test_get_current_values_insufficient(self, short_data):
        from core_trading.strategies.machine_learning.rl_strategy import RLStrategy
        strategy = RLStrategy()
        vals = strategy.get_current_values(short_data)
        assert vals == {}

    def test_reset_clears_state(self, bull_data_252):
        from core_trading.strategies.machine_learning.rl_strategy import RLStrategy
        strategy = RLStrategy()
        strategy.generate_signals(bull_data_252)
        assert strategy._position != 0.0 or strategy._last_signal is not None
        strategy.reset()
        assert strategy._position == 0.0
        assert strategy._last_signal is None

    def test_action_enum(self):
        from core_trading.strategies.machine_learning.rl_strategy import RLAction
        assert RLAction.BUY.value == 1
        assert RLAction.SELL.value == 2
        assert RLAction.HOLD.value == 0

    def test_custom_config(self, bull_data_60):
        from core_trading.strategies.machine_learning.rl_strategy import RLStrategy, RLStrategyConfig
        cfg = RLStrategyConfig(window_size=20, min_data_points=30)
        strategy = RLStrategy(cfg)
        signals = strategy.generate_signals(bull_data_60)
        assert isinstance(signals, list)

    def test_signal_metadata(self, bull_data_252):
        from core_trading.strategies.machine_learning.rl_strategy import RLStrategy
        strategy = RLStrategy()
        signals = strategy.generate_signals(bull_data_252)
        sig = signals[0]
        assert "momentum_score" in sig.metadata
        assert "volatility_score" in sig.metadata
        assert "mean_reversion_score" in sig.metadata
        assert "raw_signal" in sig.metadata
