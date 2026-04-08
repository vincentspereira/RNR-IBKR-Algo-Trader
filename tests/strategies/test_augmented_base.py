"""Tests for the AugmentedBaseInstitutionalStrategy."""

import numpy as np
import pandas as pd
import pytest

from core_trading.strategies.core.augmented_base_institutional_strategy import (
    AugmentedBaseInstitutionalStrategy,
    AugmentedConfig,
    AugmentedSignal,
    PillarScores,
)


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------


class TestAugmentedInstantiation:
    def test_default_config(self):
        s = AugmentedBaseInstitutionalStrategy()
        assert s is not None
        assert s.config.name == "AugmentedInstitutionalStrategy"

    def test_custom_config(self):
        cfg = AugmentedConfig(sma_period=10, signal_threshold=0.6)
        s = AugmentedBaseInstitutionalStrategy(cfg)
        assert s.config.sma_period == 10
        assert s.config.signal_threshold == 0.6

    def test_is_not_in_position_initially(self):
        s = AugmentedBaseInstitutionalStrategy()
        assert not s.is_in_position()


# ---------------------------------------------------------------------------
# Pillar scores
# ---------------------------------------------------------------------------


class TestPillarScores:
    def test_defaults(self):
        ps = PillarScores()
        assert ps.signal == 0.0
        assert ps.risk == 0.0
        assert ps.regime == 0.0
        assert ps.execution == 0.0
        assert ps.performance == 0.0

    def test_weighted_score(self):
        ps = PillarScores(signal=1.0, risk=1.0, regime=1.0, execution=1.0, performance=1.0)
        assert ps.weighted_score() == 1.0

    def test_weighted_score_zero(self):
        ps = PillarScores()
        assert ps.weighted_score() == 0.0

    def test_weighted_score_custom_weights(self):
        ps = PillarScores(signal=1.0)
        weights = {"signal": 1.0, "risk": 0, "regime": 0, "execution": 0, "performance": 0}
        assert ps.weighted_score(weights) == 1.0

    def test_to_dict(self):
        ps = PillarScores(signal=0.5)
        d = ps.to_dict()
        assert "signal" in d
        assert "composite" in d
        assert d["signal"] == 0.5


# ---------------------------------------------------------------------------
# Signal generation
# ---------------------------------------------------------------------------


class TestAugmentedSignalGeneration:
    def test_generate_signals_returns_list(self, bull_data_252):
        s = AugmentedBaseInstitutionalStrategy()
        signals = s.generate_signals(bull_data_252)
        assert isinstance(signals, list)
        for sig in signals:
            assert "direction" in sig
            assert sig["direction"] in ("buy", "sell", "hold")
            assert 0 <= sig["confidence"] <= 1
            assert 0 <= sig["strength"] <= 1

    def test_handles_insufficient_data(self, short_data):
        s = AugmentedBaseInstitutionalStrategy()
        signals = s.generate_signals(short_data)
        assert signals == []

    def test_handles_empty_data(self, empty_data):
        s = AugmentedBaseInstitutionalStrategy()
        signals = s.generate_signals(empty_data)
        assert signals == []

    def test_confidence_range(self, bull_data_252):
        s = AugmentedBaseInstitutionalStrategy()
        signals = s.generate_signals(bull_data_252)
        for sig in signals:
            assert 0 <= sig["confidence"] <= 1

    def test_generate_augmented_signals(self, bull_data_252):
        s = AugmentedBaseInstitutionalStrategy()
        signals = s.generate_augmented_signals(bull_data_252)
        assert isinstance(signals, list)
        assert len(signals) >= 1
        sig = signals[0]
        assert isinstance(sig, AugmentedSignal)
        assert sig.direction in ("buy", "sell", "hold")
        assert 0 <= sig.confidence <= 1
        assert 0 <= sig.strength <= 1
        assert isinstance(sig.pillars, PillarScores)

    def test_augmented_signals_insufficient_data(self, short_data):
        s = AugmentedBaseInstitutionalStrategy()
        signals = s.generate_augmented_signals(short_data)
        assert signals == []


# ---------------------------------------------------------------------------
# Pillar score calculation
# ---------------------------------------------------------------------------


class TestPillarScoreCalculation:
    def test_calculate_pillar_scores(self, bull_data_252):
        s = AugmentedBaseInstitutionalStrategy()
        pillars = s.calculate_pillar_scores(bull_data_252)
        assert isinstance(pillars, PillarScores)
        assert 0 <= pillars.signal <= 1
        assert 0 <= pillars.risk <= 1
        assert 0 <= pillars.regime <= 1
        assert 0 <= pillars.execution <= 1
        assert 0 <= pillars.performance <= 1

    def test_pillar_scores_with_flat_data(self, flat_data_252):
        s = AugmentedBaseInstitutionalStrategy()
        pillars = s.calculate_pillar_scores(flat_data_252)
        assert isinstance(pillars, PillarScores)


# ---------------------------------------------------------------------------
# Position sizing
# ---------------------------------------------------------------------------


class TestPositionSizing:
    def test_calculate_position_size(self, bull_data_252):
        s = AugmentedBaseInstitutionalStrategy()
        # Generate a signal first to populate performance history
        s.generate_signals(bull_data_252)
        size = s.calculate_position_size(100000, 150.0)
        assert size >= 0

    def test_position_size_zero_on_bad_inputs(self, bull_data_252):
        s = AugmentedBaseInstitutionalStrategy()
        assert s.calculate_position_size(0, 100) == 0.0
        assert s.calculate_position_size(100000, 0) == 0.0
        assert s.calculate_position_size(-100, 100) == 0.0


# ---------------------------------------------------------------------------
# get_current_values
# ---------------------------------------------------------------------------


class TestGetCurrentValues:
    def test_with_sufficient_data(self, bull_data_252):
        s = AugmentedBaseInstitutionalStrategy()
        vals = s.get_current_values(bull_data_252)
        assert "momentum" in vals
        assert "position" in vals
        assert "signal" in vals
        assert "composite" in vals

    def test_with_insufficient_data(self, short_data):
        s = AugmentedBaseInstitutionalStrategy()
        vals = s.get_current_values(short_data)
        assert vals == {}


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------


class TestReset:
    def test_reset_clears_state(self, bull_data_252):
        s = AugmentedBaseInstitutionalStrategy()
        s.generate_signals(bull_data_252)
        s.reset()
        assert not s.is_in_position()
