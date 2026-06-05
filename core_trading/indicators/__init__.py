"""core_trading.indicators -- clean vectorised technical indicator library.

All indicators are pure functions accepting ``pd.Series`` (or explicit
high/low/close/volume Series) and returning ``pd.Series`` / ``pd.DataFrame``
of ``float64``, indexed like the input, with ``NaN`` during warm-up.
Every function is look-ahead-free by construction.
"""
from __future__ import annotations

from core_trading.indicators.momentum import (
    cci,
    macd,
    roc,
    rsi,
    stochastic,
    stochrsi,
    tsi,
    ultimate_oscillator,
    williams_r,
)
from core_trading.indicators.moving_averages import (
    dema,
    ema,
    hma,
    kama,
    mcginley_dynamic,
    sma,
    tema,
    vwma,
    wma,
    zlema,
)
from core_trading.indicators.volatility import (
    atr,
    bollinger_bands,
    donchian_channels,
    historical_volatility,
    keltner_channels,
    natr,
    true_range,
    ulcer_index,
)
from core_trading.indicators.volume import (
    ad_line,
    cmf,
    eom,
    force_index,
    mfi,
    obv,
    vwap_anchored,
    vwap_rolling,
)

__all__ = [
    # moving averages
    "sma",
    "ema",
    "wma",
    "dema",
    "tema",
    "hma",
    "kama",
    "zlema",
    "vwma",
    "mcginley_dynamic",
    # momentum
    "rsi",
    "macd",
    "stochastic",
    "stochrsi",
    "cci",
    "williams_r",
    "roc",
    "tsi",
    "ultimate_oscillator",
    # volatility
    "true_range",
    "atr",
    "natr",
    "bollinger_bands",
    "keltner_channels",
    "donchian_channels",
    "ulcer_index",
    "historical_volatility",
    # volume
    "obv",
    "vwap_rolling",
    "vwap_anchored",
    "mfi",
    "cmf",
    "ad_line",
    "force_index",
    "eom",
]
