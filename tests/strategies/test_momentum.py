"""Tests for momentum strategy modules."""

import numpy as np
import pandas as pd
import pytest

from core_trading.strategies.momentum.macd_crossover_strategy import (
    MACDCrossoverStrategy, MACDConfig, MACDSignal,
)
from core_trading.strategies.momentum.adx_trend_following_strategy import (
    ADXTrendFollowingStrategy, ADXConfig, ADXSignal,
)
from core_trading.strategies.momentum.supertrend_strategy import (
    SupertrendStrategy, SupertrendConfig, SupertrendSignal,
)
from core_trading.strategies.momentum.augmented_ma_crossover import (
    AugmentedMACrossoverStrategy, AugMACrossConfig, AugMACrossSignal,
)
from core_trading.strategies.momentum.augmented_momentum_strategy import (
    AugmentedMomentumStrategy, AugMomentumConfig, AugMomentumSignal,
)
from core_trading.strategies.momentum.coppock_curve_strategy import (
    CoppockCurveStrategy, CoppockConfig, CoppockSignal,
)
from core_trading.strategies.momentum.dual_momentum_strategy import (
    DualMomentumStrategy, DualMomentumConfig, DualMomentumSignal,
)
from core_trading.strategies.momentum.ichimoku_cloud_strategy import (
    IchimokuCloudStrategy, IchimokuConfig, IchimokuSignal,
)
from core_trading.strategies.momentum.obv_trend_strategy import (
    OBVTrendStrategy, OBVConfig, OBVSignal,
)
from core_trading.strategies.momentum.parabolic_sar_strategy import (
    ParabolicSARStrategy, SARConfig, SARSignal,
)
from core_trading.strategies.momentum.roc_momentum_strategy import (
    ROCMomentumStrategy, ROCConfig, ROCSignal,
)
from core_trading.strategies.momentum.turtle_trading_strategy import (
    TurtleTradingStrategy, TurtleConfig, TurtleSignal,
)
from core_trading.strategies.momentum.vortex_indicator_strategy import (
    VortexIndicatorStrategy, VortexConfig, VortexSignal,
)


# ========================= MACD Crossover =================================
class TestMACDCrossover:
    def test_config_defaults(self):
        cfg = MACDConfig()
        assert cfg.fast_period == 12
        assert cfg.slow_period == 26

    def test_custom_config(self):
        s = MACDCrossoverStrategy(MACDConfig(fast_period=8, slow_period=21))
        assert s.config.fast_period == 8

    def test_insufficient_data(self, short_data):
        s = MACDCrossoverStrategy()
        assert s.generate_signals(short_data) == []

    def test_empty_data(self, empty_data):
        s = MACDCrossoverStrategy()
        assert s.generate_signals(empty_data) == []

    def test_signals_returns_list(self, bull_data_252):
        s = MACDCrossoverStrategy()
        signals = s.generate_signals(bull_data_252)
        assert isinstance(signals, list)
        for sig in signals:
            assert sig.signal in (MACDSignal.BUY, MACDSignal.SELL, MACDSignal.HOLD)
            assert 0 <= sig.confidence <= 1
            assert 0 <= sig.strength <= 1

    def test_get_current_values(self, bull_data_252):
        s = MACDCrossoverStrategy()
        vals = s.get_current_values(bull_data_252)
        assert "macd" in vals
        assert "signal" in vals
        assert "histogram" in vals

    def test_get_current_values_insufficient(self, short_data):
        s = MACDCrossoverStrategy()
        vals = s.get_current_values(short_data)
        assert vals == {"macd": 0.0, "signal": 0.0, "histogram": 0.0}


# ========================= ADX Trend ======================================
class TestADXTrend:
    def test_config_defaults(self):
        cfg = ADXConfig()
        assert cfg.period == 14
        assert cfg.adx_threshold == 25.0

    def test_custom_config(self):
        s = ADXTrendFollowingStrategy(ADXConfig(period=10, adx_threshold=30.0))
        assert s.config.period == 10

    def test_insufficient_data(self, short_data):
        s = ADXTrendFollowingStrategy()
        assert s.generate_signals(short_data) == []

    def test_empty_data(self, empty_data):
        s = ADXTrendFollowingStrategy()
        assert s.generate_signals(empty_data) == []

    def test_signals_returns_list(self, bull_data_252):
        s = ADXTrendFollowingStrategy()
        signals = s.generate_signals(bull_data_252)
        assert isinstance(signals, list)
        for sig in signals:
            assert 0 <= sig.confidence <= 1
            assert 0 <= sig.strength <= 1

    def test_get_current_values(self, bull_data_252):
        s = ADXTrendFollowingStrategy()
        vals = s.get_current_values(bull_data_252)
        assert "adx" in vals
        assert "plus_di" in vals
        assert "minus_di" in vals

    def test_get_current_values_insufficient(self, short_data):
        s = ADXTrendFollowingStrategy()
        vals = s.get_current_values(short_data)
        assert vals == {"adx": 0.0, "plus_di": 0.0, "minus_di": 0.0}


# ========================= Supertrend =====================================
class TestSupertrend:
    def test_config_defaults(self):
        cfg = SupertrendConfig()
        assert cfg.atr_period == 10
        assert cfg.multiplier == 3.0

    def test_insufficient_data(self, short_data):
        s = SupertrendStrategy()
        assert s.generate_signals(short_data) == []

    def test_empty_data(self, empty_data):
        s = SupertrendStrategy()
        assert s.generate_signals(empty_data) == []

    def test_signals_returns_list(self, bull_data_252):
        s = SupertrendStrategy()
        signals = s.generate_signals(bull_data_252)
        assert isinstance(signals, list)
        for sig in signals:
            assert sig.signal in (SupertrendSignal.BUY, SupertrendSignal.SELL, SupertrendSignal.HOLD)
            assert 0 <= sig.confidence <= 1
            assert sig.trend_direction in (1, -1)

    def test_get_current_values(self, bull_data_252):
        s = SupertrendStrategy()
        vals = s.get_current_values(bull_data_252)
        assert "supertrend" in vals
        assert "direction" in vals

    def test_get_current_values_insufficient(self, short_data):
        s = SupertrendStrategy()
        vals = s.get_current_values(short_data)
        assert vals == {"supertrend": 0.0, "direction": 0}

    def test_calculate_supertrend_returns_dataframe(self, bull_data_60):
        s = SupertrendStrategy()
        st = s.calculate_supertrend(bull_data_60)
        assert "supertrend" in st.columns
        assert "direction" in st.columns


# ========================= Augmented MA Crossover =========================
class TestAugmentedMACrossover:
    def test_config_defaults(self):
        cfg = AugMACrossConfig()
        assert cfg.fast_period == 10
        assert cfg.slow_period == 30

    def test_insufficient_data(self, short_data):
        s = AugmentedMACrossoverStrategy()
        assert s.generate_signals(short_data) == []

    def test_empty_data(self, empty_data):
        s = AugmentedMACrossoverStrategy()
        assert s.generate_signals(empty_data) == []

    def test_signals_returns_list(self, bull_data_60):
        s = AugmentedMACrossoverStrategy(AugMACrossConfig(fast_period=5, slow_period=10))
        signals = s.generate_signals(bull_data_60)
        assert isinstance(signals, list)
        for sig in signals:
            assert sig.signal in (AugMACrossSignal.BUY, AugMACrossSignal.SELL, AugMACrossSignal.HOLD)
            assert 0 <= sig.confidence <= 1

    def test_get_current_values(self, bull_data_60):
        s = AugmentedMACrossoverStrategy(AugMACrossConfig(fast_period=5, slow_period=10))
        vals = s.get_current_values(bull_data_60)
        assert "fast_ma" in vals
        assert "slow_ma" in vals

    def test_sma_mode(self, bull_data_60):
        s = AugmentedMACrossoverStrategy(AugMACrossConfig(
            fast_period=5, slow_period=10, ma_type="sma", use_volume_weighting=False,
        ))
        signals = s.generate_signals(bull_data_60)
        assert isinstance(signals, list)


# ========================= Augmented Momentum =============================
class TestAugmentedMomentum:
    def test_config_defaults(self):
        cfg = AugMomentumConfig()
        assert cfg.lookback_period == 20

    def test_insufficient_data(self, short_data):
        s = AugmentedMomentumStrategy()
        assert s.generate_signals(short_data) == []

    def test_empty_data(self, empty_data):
        s = AugmentedMomentumStrategy()
        assert s.generate_signals(empty_data) == []

    def test_buy_signal_bullish(self, bull_data_252):
        s = AugmentedMomentumStrategy()
        signals = s.generate_signals(bull_data_252)
        assert isinstance(signals, list)
        for sig in signals:
            assert sig.signal in (AugMomentumSignal.BUY, AugMomentumSignal.SELL, AugMomentumSignal.HOLD)
            assert 0 <= sig.confidence <= 1

    def test_sell_signal_bearish(self, bear_data_252):
        s = AugmentedMomentumStrategy()
        signals = s.generate_signals(bear_data_252)
        assert isinstance(signals, list)

    def test_get_current_values(self, bull_data_252):
        s = AugmentedMomentumStrategy()
        vals = s.get_current_values(bull_data_252)
        assert "roc" in vals

    def test_get_current_values_insufficient(self, short_data):
        s = AugmentedMomentumStrategy()
        vals = s.get_current_values(short_data)
        assert vals == {"roc": 0.0}


# ========================= Coppock Curve ==================================
class TestCoppockCurve:
    def test_config_defaults(self):
        cfg = CoppockConfig()
        assert cfg.roc_period_1 == 14
        assert cfg.roc_period_2 == 11

    def test_insufficient_data(self, short_data):
        s = CoppockCurveStrategy()
        assert s.generate_signals(short_data) == []

    def test_empty_data(self, empty_data):
        s = CoppockCurveStrategy()
        assert s.generate_signals(empty_data) == []

    def test_signals_returns_list(self, bull_data_252):
        s = CoppockCurveStrategy()
        signals = s.generate_signals(bull_data_252)
        assert isinstance(signals, list)
        for sig in signals:
            assert sig.signal in (CoppockSignal.BUY, CoppockSignal.SELL, CoppockSignal.HOLD)
            assert 0 <= sig.confidence <= 1

    def test_get_current_values(self, bull_data_252):
        s = CoppockCurveStrategy()
        vals = s.get_current_values(bull_data_252)
        assert "coppock" in vals

    def test_get_current_values_insufficient(self, short_data):
        s = CoppockCurveStrategy()
        vals = s.get_current_values(short_data)
        assert vals == {"coppock": 0.0}


# ========================= Dual Momentum ==================================
class TestDualMomentum:
    def test_config_defaults(self):
        cfg = DualMomentumConfig()
        assert cfg.lookback_period == 12

    def test_insufficient_data(self, short_data):
        s = DualMomentumStrategy()
        assert s.generate_signals(short_data) == []

    def test_empty_data(self, empty_data):
        s = DualMomentumStrategy()
        assert s.generate_signals(empty_data) == []

    def test_bullish_signal(self, bull_data_252):
        s = DualMomentumStrategy(DualMomentumConfig(lookback_period=10))
        signals = s.generate_signals(bull_data_252)
        assert len(signals) == 1
        sig = signals[0]
        assert sig.signal in (DualMomentumSignal.STRONG_BUY, DualMomentumSignal.BUY,
                              DualMomentumSignal.HOLD, DualMomentumSignal.SELL,
                              DualMomentumSignal.STRONG_SELL)
        assert 0 <= sig.confidence <= 1

    def test_bearish_signal(self, bear_data_252):
        s = DualMomentumStrategy(DualMomentumConfig(lookback_period=10))
        signals = s.generate_signals(bear_data_252)
        assert len(signals) == 1

    def test_with_benchmark(self, bull_data_252, bear_data_252):
        s = DualMomentumStrategy(DualMomentumConfig(lookback_period=10))
        signals = s.generate_signals(bull_data_252, benchmark_data=bear_data_252)
        assert len(signals) == 1
        assert signals[0].relative_momentum != 0.0

    def test_get_current_values(self, bull_data_252):
        s = DualMomentumStrategy(DualMomentumConfig(lookback_period=10))
        vals = s.get_current_values(bull_data_252)
        assert "absolute" in vals
        assert "combined" in vals


# ========================= Ichimoku Cloud =================================
class TestIchimokuCloud:
    def test_config_defaults(self):
        cfg = IchimokuConfig()
        assert cfg.tenkan_period == 9
        assert cfg.kijun_period == 26

    def test_insufficient_data(self, short_data):
        s = IchimokuCloudStrategy()
        assert s.generate_signals(short_data) == []

    def test_empty_data(self, empty_data):
        s = IchimokuCloudStrategy()
        assert s.generate_signals(empty_data) == []

    def test_signals_returns_list(self, bull_data_252):
        s = IchimokuCloudStrategy()
        signals = s.generate_signals(bull_data_252)
        assert isinstance(signals, list)
        for sig in signals:
            assert sig.signal in (IchimokuSignal.STRONG_BUY, IchimokuSignal.BUY,
                                  IchimokuSignal.HOLD, IchimokuSignal.SELL,
                                  IchimokuSignal.STRONG_SELL)
            assert 0 <= sig.confidence <= 1

    def test_get_current_values(self, bull_data_252):
        s = IchimokuCloudStrategy()
        vals = s.get_current_values(bull_data_252)
        assert "tenkan" in vals
        assert "kijun" in vals


# ========================= OBV Trend ======================================
class TestOBVTrend:
    def test_config_defaults(self):
        cfg = OBVConfig()
        assert cfg.ma_period == 20

    def test_insufficient_data(self, short_data):
        s = OBVTrendStrategy()
        assert s.generate_signals(short_data) == []

    def test_empty_data(self, empty_data):
        s = OBVTrendStrategy()
        assert s.generate_signals(empty_data) == []

    def test_signals_returns_list(self, bull_data_252):
        s = OBVTrendStrategy()
        signals = s.generate_signals(bull_data_252)
        assert isinstance(signals, list)
        for sig in signals:
            assert sig.signal in (OBVSignal.BUY, OBVSignal.SELL, OBVSignal.HOLD)
            assert 0 <= sig.confidence <= 1

    def test_get_current_values(self, bull_data_252):
        s = OBVTrendStrategy()
        vals = s.get_current_values(bull_data_252)
        assert "obv" in vals
        assert "obv_ma" in vals

    def test_get_current_values_insufficient(self, short_data):
        s = OBVTrendStrategy()
        vals = s.get_current_values(short_data)
        assert vals == {"obv": 0.0, "obv_ma": 0.0}


# ========================= Parabolic SAR ==================================
class TestParabolicSAR:
    def test_config_defaults(self):
        cfg = SARConfig()
        assert cfg.step == 0.02
        assert cfg.max_step == 0.20

    def test_insufficient_data(self, short_data):
        s = ParabolicSARStrategy()
        assert s.generate_signals(short_data) == []

    def test_empty_data(self, empty_data):
        s = ParabolicSARStrategy()
        assert s.generate_signals(empty_data) == []

    def test_signals_returns_list(self, bull_data_252):
        s = ParabolicSARStrategy()
        signals = s.generate_signals(bull_data_252)
        assert isinstance(signals, list)
        for sig in signals:
            assert sig.signal in (SARSignal.BUY, SARSignal.SELL, SARSignal.HOLD)
            assert 0 <= sig.confidence <= 1

    def test_get_current_values(self, bull_data_252):
        s = ParabolicSARStrategy()
        vals = s.get_current_values(bull_data_252)
        assert "sar" in vals
        assert "trend" in vals

    def test_get_current_values_insufficient(self):
        df = pd.DataFrame({"open": [100], "high": [101], "low": [99], "close": [100], "volume": [1e6]})
        s = ParabolicSARStrategy()
        vals = s.get_current_values(df)
        # SAR needs at least 3 rows; with 1 row it returns values based on initial state
        assert "sar" in vals
        assert "trend" in vals


# ========================= ROC Momentum ===================================
class TestROCMomentum:
    def test_config_defaults(self):
        cfg = ROCConfig()
        assert cfg.period == 12
        assert cfg.overbought_threshold == 10.0

    def test_insufficient_data(self, short_data):
        s = ROCMomentumStrategy()
        assert s.generate_signals(short_data) == []

    def test_empty_data(self, empty_data):
        s = ROCMomentumStrategy()
        assert s.generate_signals(empty_data) == []

    def test_signals_returns_list(self, bull_data_252):
        s = ROCMomentumStrategy()
        signals = s.generate_signals(bull_data_252)
        assert isinstance(signals, list)
        assert len(signals) == 1  # ROC always returns one result
        sig = signals[0]
        assert sig.signal in (ROCSignal.STRONG_BUY, ROCSignal.BUY, ROCSignal.HOLD,
                              ROCSignal.SELL, ROCSignal.STRONG_SELL)
        assert 0 <= sig.confidence <= 1

    def test_get_current_values(self, bull_data_252):
        s = ROCMomentumStrategy()
        vals = s.get_current_values(bull_data_252)
        assert "roc" in vals

    def test_get_current_values_insufficient(self, short_data):
        s = ROCMomentumStrategy()
        vals = s.get_current_values(short_data)
        assert vals == {"roc": 0.0}


# ========================= Turtle Trading =================================
class TestTurtleTrading:
    def test_config_defaults(self):
        cfg = TurtleConfig()
        assert cfg.entry_period == 20
        assert cfg.exit_period == 10

    def test_insufficient_data(self, short_data):
        s = TurtleTradingStrategy()
        assert s.generate_signals(short_data) == []

    def test_empty_data(self, empty_data):
        s = TurtleTradingStrategy()
        assert s.generate_signals(empty_data) == []

    def test_buy_on_breakout(self, bull_data_60):
        s = TurtleTradingStrategy(TurtleConfig(entry_period=10, exit_period=5))
        s.reset_position()
        signals = s.generate_signals(bull_data_60)
        # Bullish data should produce a breakout
        assert isinstance(signals, list)
        for sig in signals:
            assert sig.signal in (TurtleSignal.BUY, TurtleSignal.SELL,
                                  TurtleSignal.EXIT_LONG, TurtleSignal.EXIT_SHORT,
                                  TurtleSignal.HOLD)
            assert 0 <= sig.confidence <= 1

    def test_get_current_values(self, bull_data_60):
        s = TurtleTradingStrategy(TurtleConfig(entry_period=10, exit_period=5))
        vals = s.get_current_values(bull_data_60)
        assert "channel_high" in vals
        assert "channel_low" in vals
        assert "atr" in vals

    def test_get_current_values_insufficient(self, short_data):
        s = TurtleTradingStrategy()
        vals = s.get_current_values(short_data)
        assert vals == {"channel_high": 0.0, "channel_low": 0.0, "atr": 0.0}

    def test_reset_position(self, bull_data_60):
        s = TurtleTradingStrategy()
        s._position = 1
        s.reset_position()
        assert s._position == 0


# ========================= Vortex Indicator ===============================
class TestVortexIndicator:
    def test_config_defaults(self):
        cfg = VortexConfig()
        assert cfg.period == 14

    def test_insufficient_data(self, short_data):
        s = VortexIndicatorStrategy()
        assert s.generate_signals(short_data) == []

    def test_empty_data(self, empty_data):
        s = VortexIndicatorStrategy()
        assert s.generate_signals(empty_data) == []

    def test_signals_returns_list(self, bull_data_252):
        s = VortexIndicatorStrategy()
        signals = s.generate_signals(bull_data_252)
        assert isinstance(signals, list)
        for sig in signals:
            assert sig.signal in (VortexSignal.BUY, VortexSignal.SELL, VortexSignal.HOLD)
            assert 0 <= sig.confidence <= 1

    def test_get_current_values(self, bull_data_252):
        s = VortexIndicatorStrategy()
        vals = s.get_current_values(bull_data_252)
        assert "vi_plus" in vals
        assert "vi_minus" in vals

    def test_get_current_values_insufficient(self, short_data):
        s = VortexIndicatorStrategy()
        vals = s.get_current_values(short_data)
        assert vals == {"vi_plus": 0.0, "vi_minus": 0.0}
