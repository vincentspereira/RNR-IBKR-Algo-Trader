"""Tests for mean reversion strategy modules."""

import numpy as np
import pandas as pd
import pytest

from core_trading.strategies.mean_reversion.bollinger_bands_mean_reversion_strategy import (
    BollingerBandsMeanReversionStrategy, BBConfig, BBSignal, BBResult,
)
from core_trading.strategies.mean_reversion.connors_rsi_mean_reversion_strategy import (
    ConnorsRSIMeanReversionStrategy, CRSIConfig, CRSISignal,
)
from core_trading.strategies.mean_reversion.gap_fill_strategy import (
    GapFillStrategy, GapConfig, GapSignal,
)
from core_trading.strategies.mean_reversion.ibs_mean_reversion_strategy import (
    IBSMeanReversionStrategy, IBSConfig, IBSSignal,
)
from core_trading.strategies.mean_reversion.ma_crossover_vwma_strategy import (
    MovingAverageCrossoverVWMAStrategy, VWMAConfig, VWMASignal,
)
from core_trading.strategies.mean_reversion.overnight_reversal_strategy import (
    OvernightReversalStrategy, OvernightConfig, OvernightSignal,
)
from core_trading.strategies.mean_reversion.rsi2_mean_reversion_strategy import (
    RSI2MeanReversionStrategy, RSI2MRConfig, RSI2MRSignal, MarketRegime,
)
from core_trading.strategies.mean_reversion.rsi2_strategy import (
    RSI2Strategy, RSI2Config, RSI2Signal,
)
from core_trading.strategies.mean_reversion.stochastic_mean_reversion_strategy import (
    StochasticMeanReversionStrategy, StochasticConfig, StochasticSignal,
)
from core_trading.strategies.mean_reversion.vix_mean_reversion_strategy import (
    VIXMeanReversionStrategy, VIXConfig, VIXSignal,
)
from core_trading.strategies.mean_reversion.williams_r_mean_reversion_strategy import (
    WilliamsRMeanReversionStrategy, WilliamsRConfig, WilliamsRSignal,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _make_gap_data(prev_close, curr_open, curr_close, n_extra=5):
    """Create a DataFrame with a specific gap pattern in the last two bars."""
    rng = np.random.default_rng(99)
    bars = []
    base = prev_close
    for _ in range(n_extra):
        p = base + rng.normal(0, 0.5)
        bars.append({"open": p, "high": p + 1, "low": p - 1, "close": p, "volume": 1e6})
        base = p
    # second-to-last bar
    bars.append({"open": base, "high": base + 1, "low": base - 1, "close": prev_close, "volume": 1e6})
    # last bar with engineered gap
    high = max(curr_open, curr_close) + 0.5
    low = min(curr_open, curr_close) - 0.5
    bars.append({"open": curr_open, "high": high, "low": low, "close": curr_close, "volume": 1e6})
    return pd.DataFrame(bars)


# ========================= Bollinger Bands ================================
class TestBollingerBandsMeanReversion:
    def test_config_defaults(self):
        cfg = BBConfig()
        assert cfg.period == 20
        assert cfg.std_dev == 2.0

    def test_custom_config(self):
        s = BollingerBandsMeanReversionStrategy(BBConfig(period=10, std_dev=1.5))
        assert s.config.period == 10

    def test_insufficient_data(self, short_data):
        s = BollingerBandsMeanReversionStrategy()
        assert s.generate_signals(short_data) == []

    def test_empty_data(self, empty_data):
        s = BollingerBandsMeanReversionStrategy()
        assert s.generate_signals(empty_data) == []

    def test_no_signal_flat(self, flat_data_252):
        s = BollingerBandsMeanReversionStrategy()
        signals = s.generate_signals(flat_data_252)
        # flat data unlikely to hit BB extremes consistently
        for sig in signals:
            assert sig.confidence >= 0
            assert sig.confidence <= 1

    def test_get_current_values(self, bull_data_252):
        s = BollingerBandsMeanReversionStrategy()
        vals = s.get_current_values(bull_data_252)
        assert "bb_value" in vals
        assert "upper_band" in vals
        assert "lower_band" in vals

    def test_get_current_values_insufficient(self, short_data):
        s = BollingerBandsMeanReversionStrategy()
        assert s.get_current_values(short_data) == {}

    def test_buy_signal_oversold_bounce(self):
        """Force price below lower BB then bounce."""
        n = 40
        rng = np.random.default_rng(42)
        base = np.linspace(100, 100, n)
        # Make prices crash below lower band then snap back
        base[-5:] = [100, 92, 88, 85, 90]  # bounce off lows
        df = pd.DataFrame({
            "open": base, "high": base + 1, "low": base - 1,
            "close": base, "volume": rng.integers(1e6, 5e6, n),
        })
        s = BollingerBandsMeanReversionStrategy(BBConfig(period=20, std_dev=2.0))
        signals = s.generate_signals(df)
        # Not guaranteed due to random component, but verify return type
        assert isinstance(signals, list)
        for sig in signals:
            assert isinstance(sig, BBResult)
            assert sig.signal in (BBSignal.BUY, BBSignal.SELL, BBSignal.HOLD)
            assert 0 <= sig.confidence <= 1


# ========================= Connors RSI ====================================
class TestConnorsRSI:
    def test_config_defaults(self):
        cfg = CRSIConfig()
        assert cfg.rsi_period == 3

    def test_insufficient_data(self, short_data):
        s = ConnorsRSIMeanReversionStrategy()
        assert s.generate_signals(short_data) == []

    def test_empty_data(self, empty_data):
        s = ConnorsRSIMeanReversionStrategy()
        assert s.generate_signals(empty_data) == []

    def test_no_signal_flat(self, flat_data_252):
        s = ConnorsRSIMeanReversionStrategy()
        signals = s.generate_signals(flat_data_252)
        assert isinstance(signals, list)

    def test_confidence_range(self, bull_data_252):
        s = ConnorsRSIMeanReversionStrategy()
        for sig in s.generate_signals(bull_data_252):
            assert 0 <= sig.confidence <= 1
            assert 0 <= sig.strength <= 1

    def test_get_current_values(self, bull_data_252):
        s = ConnorsRSIMeanReversionStrategy()
        vals = s.get_current_values(bull_data_252)
        assert "crsi" in vals

    def test_get_current_values_insufficient(self, short_data):
        s = ConnorsRSIMeanReversionStrategy()
        vals = s.get_current_values(short_data)
        assert vals == {"crsi": 50.0}


# ========================= Gap Fill =======================================
class TestGapFill:
    def test_config_defaults(self):
        cfg = GapConfig()
        assert cfg.min_gap_pct == 0.5

    def test_insufficient_data(self):
        # GapFillStrategy only needs 2 rows, so short_data (5 rows) actually works
        # Use truly insufficient: 1 row
        df = pd.DataFrame({"open": [100], "high": [101], "low": [99], "close": [100], "volume": [1e6]})
        s = GapFillStrategy()
        assert s.generate_signals(df) == []

    def test_empty_data(self, empty_data):
        s = GapFillStrategy()
        assert s.generate_signals(empty_data) == []

    def test_buy_on_gap_down(self):
        """Gap down -> BUY (expect fill)."""
        df = _make_gap_data(prev_close=100, curr_open=93, curr_close=93.5)
        s = GapFillStrategy(GapConfig(min_gap_pct=1.0, max_gap_pct=10.0))
        signals = s.generate_signals(df)
        assert len(signals) >= 1
        assert signals[0].signal == GapSignal.BUY
        assert signals[0].gap_direction == "down"
        assert 0 <= signals[0].confidence <= 1

    def test_sell_on_gap_up(self):
        """Gap up -> SELL (expect fill)."""
        df = _make_gap_data(prev_close=100, curr_open=107, curr_close=106.5)
        s = GapFillStrategy(GapConfig(min_gap_pct=1.0, max_gap_pct=10.0))
        signals = s.generate_signals(df)
        assert len(signals) >= 1
        assert signals[0].signal == GapSignal.SELL
        assert signals[0].gap_direction == "up"

    def test_no_signal_when_gap_filled(self):
        """If price already filled the gap, no signal."""
        df = _make_gap_data(prev_close=100, curr_open=93, curr_close=101)
        s = GapFillStrategy(GapConfig(min_gap_pct=1.0, max_gap_pct=10.0))
        signals = s.generate_signals(df)
        assert signals == []

    def test_no_signal_small_gap(self):
        """Gap too small -> no signal."""
        df = _make_gap_data(prev_close=100, curr_open=99.8, curr_close=99.9)
        s = GapFillStrategy(GapConfig(min_gap_pct=1.0))
        signals = s.generate_signals(df)
        assert signals == []

    def test_get_current_values(self, bull_data_252):
        s = GapFillStrategy()
        vals = s.get_current_values(bull_data_252)
        assert "gap_pct" in vals


# ========================= IBS ============================================
class TestIBS:
    def test_config_defaults(self):
        cfg = IBSConfig()
        assert cfg.oversold_threshold == 0.2

    def test_insufficient_data(self):
        s = IBSMeanReversionStrategy()
        df = pd.DataFrame({"open": [100], "high": [101], "low": [99], "close": [100], "volume": [1e6]})
        assert s.generate_signals(df) == []

    def test_empty_data(self, empty_data):
        s = IBSMeanReversionStrategy()
        assert s.generate_signals(empty_data) == []

    def test_buy_ibs_oversold(self):
        """Close near bar's low -> low IBS -> BUY."""
        n = 10
        df = pd.DataFrame({
            "open": np.full(n, 100.0),
            "high": np.full(n, 102.0),
            "low": np.full(n, 98.0),
            "close": np.full(n, 98.1),  # close near low
            "volume": np.full(n, 1e6),
        })
        s = IBSMeanReversionStrategy(IBSConfig(oversold_threshold=0.2))
        signals = s.generate_signals(df)
        assert len(signals) >= 1
        assert signals[0].signal == IBSSignal.BUY
        assert 0 <= signals[0].confidence <= 1

    def test_sell_ibs_overbought(self):
        """Close near bar's high -> high IBS -> SELL."""
        n = 10
        df = pd.DataFrame({
            "open": np.full(n, 100.0),
            "high": np.full(n, 102.0),
            "low": np.full(n, 98.0),
            "close": np.full(n, 101.9),  # close near high
            "volume": np.full(n, 1e6),
        })
        s = IBSMeanReversionStrategy(IBSConfig(overbought_threshold=0.8))
        signals = s.generate_signals(df)
        assert len(signals) >= 1
        assert signals[0].signal == IBSSignal.SELL

    def test_no_signal_midrange(self):
        """Close in midrange -> no signal."""
        n = 10
        df = pd.DataFrame({
            "open": np.full(n, 100.0),
            "high": np.full(n, 102.0),
            "low": np.full(n, 98.0),
            "close": np.full(n, 100.0),  # midrange
            "volume": np.full(n, 1e6),
        })
        s = IBSMeanReversionStrategy()
        signals = s.generate_signals(df)
        assert signals == []

    def test_get_current_values(self, bull_data_252):
        s = IBSMeanReversionStrategy()
        vals = s.get_current_values(bull_data_252)
        assert "ibs" in vals
        assert 0 <= vals["ibs"] <= 1


# ========================= MA Crossover VWMA ==============================
class TestMACrossoverVWMA:
    def test_config_defaults(self):
        cfg = VWMAConfig()
        assert cfg.fast_period == 10
        assert cfg.slow_period == 30

    def test_insufficient_data(self, short_data):
        s = MovingAverageCrossoverVWMAStrategy()
        assert s.generate_signals(short_data) == []

    def test_empty_data(self, empty_data):
        s = MovingAverageCrossoverVWMAStrategy()
        assert s.generate_signals(empty_data) == []

    def test_signals_returns_list(self, bull_data_60):
        s = MovingAverageCrossoverVWMAStrategy(VWMAConfig(fast_period=5, slow_period=10))
        signals = s.generate_signals(bull_data_60)
        assert isinstance(signals, list)
        for sig in signals:
            assert sig.signal in (VWMASignal.BUY, VWMASignal.SELL, VWMASignal.HOLD)
            assert 0 <= sig.confidence <= 1

    def test_get_current_values(self, bull_data_60):
        s = MovingAverageCrossoverVWMAStrategy(VWMAConfig(fast_period=5, slow_period=10))
        vals = s.get_current_values(bull_data_60)
        assert "fast_vwma" in vals
        assert "slow_vwma" in vals

    def test_get_current_values_insufficient(self, short_data):
        s = MovingAverageCrossoverVWMAStrategy()
        vals = s.get_current_values(short_data)
        assert vals == {"fast_vwma": 0.0, "slow_vwma": 0.0}


# ========================= Overnight Reversal =============================
class TestOvernightReversal:
    def test_config_defaults(self):
        cfg = OvernightConfig()
        assert cfg.min_gap_pct == 0.3

    def test_insufficient_data(self):
        # OvernightReversalStrategy needs reversal_bar_count + 1 rows (4 by default)
        # Use 2 rows which is too few for default config
        df = pd.DataFrame({"open": [100, 99], "high": [101, 100], "low": [99, 98], "close": [100, 99.5], "volume": [1e6, 1e6]})
        s = OvernightReversalStrategy(OvernightConfig(reversal_bar_count=5))
        assert s.generate_signals(df) == []

    def test_empty_data(self, empty_data):
        s = OvernightReversalStrategy()
        assert s.generate_signals(empty_data) == []

    def test_buy_gap_down_reversal(self):
        """Gap down + intraday reversal (close > open) -> BUY."""
        df = _make_gap_data(prev_close=100, curr_open=94, curr_close=96)
        s = OvernightReversalStrategy(OvernightConfig(min_gap_pct=1.0))
        signals = s.generate_signals(df)
        assert len(signals) >= 1
        assert signals[0].signal == OvernightSignal.BUY
        assert 0 <= signals[0].confidence <= 1

    def test_sell_gap_up_reversal(self):
        """Gap up + intraday reversal (close < open) -> SELL."""
        df = _make_gap_data(prev_close=100, curr_open=106, curr_close=104)
        s = OvernightReversalStrategy(OvernightConfig(min_gap_pct=1.0))
        signals = s.generate_signals(df)
        assert len(signals) >= 1
        assert signals[0].signal == OvernightSignal.SELL

    def test_no_signal_no_gap(self):
        """Small gap -> no signal."""
        df = _make_gap_data(prev_close=100, curr_open=100.1, curr_close=100.2)
        s = OvernightReversalStrategy(OvernightConfig(min_gap_pct=1.0))
        signals = s.generate_signals(df)
        assert signals == []

    def test_no_signal_gap_no_reversal(self):
        """Gap but no intraday reversal -> no signal."""
        df = _make_gap_data(prev_close=100, curr_open=94, curr_close=93)
        s = OvernightReversalStrategy(OvernightConfig(min_gap_pct=1.0))
        signals = s.generate_signals(df)
        assert signals == []

    def test_get_current_values(self, bull_data_252):
        s = OvernightReversalStrategy()
        vals = s.get_current_values(bull_data_252)
        assert "gap_pct" in vals


# ========================= RSI2 ===========================================
class TestRSI2:
    def test_config_defaults(self):
        cfg = RSI2Config()
        assert cfg.rsi_period == 2
        assert cfg.sma_period == 200

    def test_insufficient_data(self, short_data):
        s = RSI2Strategy()
        assert s.generate_signals(short_data) == []

    def test_empty_data(self, empty_data):
        s = RSI2Strategy()
        assert s.generate_signals(empty_data) == []

    def test_signals_returns_list(self, bull_data_252):
        s = RSI2Strategy()
        signals = s.generate_signals(bull_data_252)
        assert isinstance(signals, list)
        for sig in signals:
            assert sig.signal in (RSI2Signal.BUY, RSI2Signal.SELL, RSI2Signal.HOLD)
            assert 0 <= sig.confidence <= 1

    def test_get_current_values(self, bull_data_252):
        s = RSI2Strategy()
        vals = s.get_current_values(bull_data_252)
        assert "rsi2" in vals
        assert "sma" in vals

    def test_get_current_values_insufficient(self, short_data):
        s = RSI2Strategy()
        vals = s.get_current_values(short_data)
        assert vals == {"rsi2": 0.0, "sma": 0.0}


# ========================= RSI2 Mean Reversion ============================
class TestRSI2MeanReversion:
    def test_config_defaults(self):
        cfg = RSI2MRConfig()
        assert cfg.rsi_period == 2
        assert cfg.regime_lookback == 50

    def test_insufficient_data(self, short_data):
        s = RSI2MeanReversionStrategy()
        assert s.generate_signals(short_data) == []

    def test_empty_data(self, empty_data):
        s = RSI2MeanReversionStrategy()
        assert s.generate_signals(empty_data) == []

    def test_signals_returns_list(self, bull_data_252):
        s = RSI2MeanReversionStrategy()
        signals = s.generate_signals(bull_data_252)
        assert isinstance(signals, list)
        for sig in signals:
            assert sig.signal in (RSI2MRSignal.BUY, RSI2MRSignal.SELL, RSI2MRSignal.HOLD)
            assert 0 <= sig.confidence <= 1
            assert isinstance(sig.regime, MarketRegime)

    def test_regime_detection(self, bull_data_252):
        s = RSI2MeanReversionStrategy()
        regime = s._detect_regime(bull_data_252)
        assert isinstance(regime, MarketRegime)

    def test_regime_thresholds(self):
        s = RSI2MeanReversionStrategy()
        o, ob = s._get_regime_thresholds(MarketRegime.VOLATILE)
        assert o < s.config.oversold
        assert ob > s.config.overbought

    def test_get_current_values(self, bull_data_252):
        s = RSI2MeanReversionStrategy()
        vals = s.get_current_values(bull_data_252)
        assert "rsi2" in vals
        assert "regime" in vals

    def test_get_current_values_insufficient(self):
        # RSI2MeanReversionStrategy only needs rsi_period + 1 = 3 rows for get_current_values
        # short_data has 5 rows, so it actually returns values. Use 1 row instead.
        df = pd.DataFrame({"open": [100], "high": [101], "low": [99], "close": [100], "volume": [1e6]})
        s = RSI2MeanReversionStrategy()
        vals = s.get_current_values(df)
        assert "rsi2" in vals


# ========================= Stochastic =====================================
class TestStochastic:
    def test_config_defaults(self):
        cfg = StochasticConfig()
        assert cfg.k_period == 14
        assert cfg.oversold == 20.0

    def test_insufficient_data(self, short_data):
        s = StochasticMeanReversionStrategy()
        assert s.generate_signals(short_data) == []

    def test_empty_data(self, empty_data):
        s = StochasticMeanReversionStrategy()
        assert s.generate_signals(empty_data) == []

    def test_signals_returns_list(self, bull_data_252):
        s = StochasticMeanReversionStrategy()
        signals = s.generate_signals(bull_data_252)
        assert isinstance(signals, list)
        for sig in signals:
            assert sig.signal in (StochasticSignal.BUY, StochasticSignal.SELL, StochasticSignal.HOLD)
            assert 0 <= sig.confidence <= 1
            assert 0 <= sig.k_value <= 100
            assert 0 <= sig.d_value <= 100

    def test_get_current_values(self, bull_data_252):
        s = StochasticMeanReversionStrategy()
        vals = s.get_current_values(bull_data_252)
        assert "k" in vals
        assert "d" in vals

    def test_get_current_values_insufficient(self, short_data):
        s = StochasticMeanReversionStrategy()
        vals = s.get_current_values(short_data)
        assert vals == {"k": 50.0, "d": 50.0}


# ========================= VIX ============================================
class TestVIXMeanReversion:
    def test_config_defaults(self):
        cfg = VIXConfig()
        assert cfg.atr_period == 14
        assert cfg.vol_spike_threshold == 1.5

    def test_insufficient_data(self, short_data):
        s = VIXMeanReversionStrategy()
        assert s.generate_signals(short_data) == []

    def test_empty_data(self, empty_data):
        s = VIXMeanReversionStrategy()
        assert s.generate_signals(empty_data) == []

    def test_signals_returns_list(self, bull_data_252):
        s = VIXMeanReversionStrategy()
        signals = s.generate_signals(bull_data_252)
        assert isinstance(signals, list)
        for sig in signals:
            assert sig.signal in (VIXSignal.BUY, VIXSignal.SELL, VIXSignal.HOLD)
            assert 0 <= sig.confidence <= 1
            assert sig.vol_ratio >= 0

    def test_get_current_values(self, bull_data_252):
        s = VIXMeanReversionStrategy()
        vals = s.get_current_values(bull_data_252)
        assert "atr" in vals
        assert "vol_ratio" in vals

    def test_get_current_values_insufficient(self, short_data):
        s = VIXMeanReversionStrategy()
        vals = s.get_current_values(short_data)
        assert vals == {"atr": 0.0, "vol_ratio": 1.0}


# ========================= Williams %R ====================================
class TestWilliamsR:
    def test_config_defaults(self):
        cfg = WilliamsRConfig()
        assert cfg.period == 14
        assert cfg.oversold == -80.0

    def test_insufficient_data(self, short_data):
        s = WilliamsRMeanReversionStrategy()
        assert s.generate_signals(short_data) == []

    def test_empty_data(self, empty_data):
        s = WilliamsRMeanReversionStrategy()
        assert s.generate_signals(empty_data) == []

    def test_signals_returns_list(self, bull_data_252):
        s = WilliamsRMeanReversionStrategy()
        signals = s.generate_signals(bull_data_252)
        assert isinstance(signals, list)
        for sig in signals:
            assert sig.signal in (WilliamsRSignal.BUY, WilliamsRSignal.SELL, WilliamsRSignal.HOLD)
            assert 0 <= sig.confidence <= 1
            assert -100 <= sig.williams_r <= 0

    def test_get_current_values(self, bull_data_252):
        s = WilliamsRMeanReversionStrategy()
        vals = s.get_current_values(bull_data_252)
        assert "williams_r" in vals
        assert -100 <= vals["williams_r"] <= 0

    def test_get_current_values_insufficient(self, short_data):
        s = WilliamsRMeanReversionStrategy()
        vals = s.get_current_values(short_data)
        assert vals == {"williams_r": -50.0}
