"""Feature store (master plan Phase 2.1).

Centralised, versioned, look-ahead-free feature computation. The guarantee this
module provides is structural, not procedural: every built-in feature is
**causal** -- the value at timestamp ``t`` uses only bars with timestamp ``≤ t``
(rolling/ewm/shift windows, never centred or forward-filled from the future).
That, combined with the optional ``as_of`` cut, lets a backtest reproduce
exactly the feature vector that would have been observable at any past instant.

Key types
---------
* :class:`Feature` -- a named, **versioned** definition (compute function +
  metadata). Changing a definition means registering a new version, so old
  backtests can recompute with the definition they were built on.
* :class:`FeatureStore` -- registry + computation engine over the standard
  ``(symbol, timestamp)`` bar frame.
* :func:`default_feature_store` -- a store pre-loaded with 60+ built-in features
  across returns, volatility, trend, momentum, volume, range and statistical
  categories.

Usage
-----
>>> store = default_feature_store()
>>> feats = store.compute(bar_frame)            # all features, all symbols
>>> mom = store.compute(bar_frame, ["ret_21", "rsi_14"])  # a subset
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import cast

import numpy as np
import pandas as pd

__all__ = [
    "Feature",
    "FeatureStore",
    "default_feature_store",
]

# A feature computes a Series (aligned to the input index) from a single-symbol
# OHLCV frame whose columns include open/high/low/close/volume.
FeatureFunc = Callable[[pd.DataFrame], pd.Series]


@dataclass(frozen=True)
class Feature:
    """A versioned, causal feature definition.

    Attributes
    ----------
    name:
        Feature identifier, unique per version.
    version:
        Definition version (e.g. ``"v1"``). New behaviour => new version.
    category:
        Grouping (``returns``, ``volatility``, ``trend``, ``momentum``,
        ``volume``, ``range``, ``statistical``).
    description:
        One-line human description.
    min_periods:
        Bars of history required before the feature emits a non-NaN value.
    func:
        Causal compute function ``frame -> Series``.
    """

    name: str
    version: str
    category: str
    description: str
    min_periods: int
    func: FeatureFunc

    @property
    def key(self) -> str:
        """Stable ``name@version`` identifier."""
        return f"{self.name}@{self.version}"


class FeatureStore:
    """Registry and computation engine for versioned features."""

    def __init__(self) -> None:
        # name -> {version -> Feature}; insertion order = registration order.
        self._features: dict[str, dict[str, Feature]] = {}

    # ------------------------------------------------------------------ registry
    def register(self, feature: Feature, *, overwrite: bool = False) -> None:
        """Register ``feature``. Raises on a duplicate name@version unless ``overwrite``."""
        versions = self._features.setdefault(feature.name, {})
        if feature.version in versions and not overwrite:
            raise ValueError(f"feature {feature.key} already registered; pass overwrite=True")
        versions[feature.version] = feature

    def get(self, name: str, version: str | None = None) -> Feature:
        """Return a feature by name (latest version unless ``version`` given)."""
        if name not in self._features:
            raise KeyError(f"unknown feature: {name}")
        versions = self._features[name]
        if version is None:
            version = self.latest_version(name)
        if version not in versions:
            raise KeyError(f"feature {name} has no version {version}")
        return versions[version]

    def latest_version(self, name: str) -> str:
        """Most recently registered version of ``name``."""
        if name not in self._features:
            raise KeyError(f"unknown feature: {name}")
        return next(reversed(self._features[name]))

    def list_features(self) -> list[str]:
        """All registered feature names, in registration order."""
        return list(self._features)

    def list_by_category(self, category: str) -> list[str]:
        return [
            name for name, versions in self._features.items() if self.get(name).category == category
        ]

    def __len__(self) -> int:
        return len(self._features)

    # --------------------------------------------------------------- computation
    def compute_one(
        self,
        symbol_frame: pd.DataFrame,
        name: str,
        version: str | None = None,
    ) -> pd.Series:
        """Compute a single feature for a single-symbol frame (index = timestamp)."""
        feature = self.get(name, version)
        series = feature.func(symbol_frame)
        series = series.astype(float)
        series.name = name
        return series

    def compute(
        self,
        frame: pd.DataFrame,
        features: Sequence[str | tuple[str, str]] | None = None,
        *,
        as_of: pd.Timestamp | None = None,
    ) -> pd.DataFrame:
        """Compute features for a multi-index ``(symbol, timestamp)`` bar frame.

        Parameters
        ----------
        frame:
            Standard bar frame from
            :meth:`core_trading.data.bars.BarSource.bars_to_dataframe`.
        features:
            Names (latest version) or ``(name, version)`` tuples. ``None`` uses
            every registered feature at its latest version.
        as_of:
            Point-in-time cut. When given, each symbol's bars are truncated to
            ``timestamp ≤ as_of`` *before* computation, reproducing the feature
            vector observable at that instant.

        Returns
        -------
        pandas.DataFrame
            Multi-indexed ``(symbol, timestamp)`` with one column per feature.
            The ``attrs["feature_versions"]`` mapping records the exact version
            used for each column (for reproducibility).
        """
        if not isinstance(frame.index, pd.MultiIndex):
            raise ValueError("compute expects a (symbol, timestamp) multi-index frame")

        requested = self._resolve(features)
        if as_of is not None:
            ts = frame.index.get_level_values("timestamp")
            frame = frame[ts <= as_of]

        per_symbol: list[pd.DataFrame] = []
        for symbol, sym_frame in frame.groupby(level="symbol", sort=False):
            sym_frame = sym_frame.droplevel("symbol").sort_index()
            cols = {}
            for name, version in requested:
                cols[name] = self.compute_one(sym_frame, name, version)
            sym_out = pd.DataFrame(cols, index=sym_frame.index)
            sym_out.index = pd.MultiIndex.from_product(
                [[symbol], sym_out.index], names=["symbol", "timestamp"]
            )
            per_symbol.append(sym_out)

        if not per_symbol:
            out = pd.DataFrame(columns=[name for name, _ in requested])
        else:
            out = pd.concat(per_symbol).sort_index()
        out.attrs["feature_versions"] = {name: version for name, version in requested}
        return out

    def _resolve(self, features: Sequence[str | tuple[str, str]] | None) -> list[tuple[str, str]]:
        if features is None:
            return [(name, self.latest_version(name)) for name in self._features]
        resolved: list[tuple[str, str]] = []
        for item in features:
            if isinstance(item, tuple):
                name, version = item
            else:
                name, version = item, self.latest_version(item)
            self.get(name, version)  # validate existence
            resolved.append((name, version))
        return resolved


# --------------------------------------------------------------------- indicators
# Each helper is a causal computation over a single-symbol OHLCV frame.


def _returns(df: pd.DataFrame, periods: int) -> pd.Series:
    return df["close"].pct_change(periods)


def _log_returns(df: pd.DataFrame, periods: int) -> pd.Series:
    return np.log(df["close"]).diff(periods)


def _realised_vol(df: pd.DataFrame, window: int) -> pd.Series:
    return df["close"].pct_change().rolling(window).std(ddof=1)


def _ewma_vol(df: pd.DataFrame, span: int) -> pd.Series:
    return df["close"].pct_change().ewm(span=span, min_periods=span).std()


def _parkinson_vol(df: pd.DataFrame, window: int) -> pd.Series:
    hl = np.log(df["high"] / df["low"]) ** 2
    factor = 1.0 / (4.0 * np.log(2.0))
    return np.sqrt(factor * hl.rolling(window).mean())


def _garman_klass_vol(df: pd.DataFrame, window: int) -> pd.Series:
    hl = 0.5 * np.log(df["high"] / df["low"]) ** 2
    co = (2.0 * np.log(2.0) - 1.0) * np.log(df["close"] / df["open"]) ** 2
    return np.sqrt((hl - co).rolling(window).mean())


def _rogers_satchell_vol(df: pd.DataFrame, window: int) -> pd.Series:
    term = np.log(df["high"] / df["close"]) * np.log(df["high"] / df["open"]) + np.log(
        df["low"] / df["close"]
    ) * np.log(df["low"] / df["open"])
    return np.sqrt(term.rolling(window).mean())


def _sma(df: pd.DataFrame, window: int) -> pd.Series:
    return df["close"].rolling(window).mean()


def _ema(df: pd.DataFrame, span: int) -> pd.Series:
    return df["close"].ewm(span=span, min_periods=span).mean()


def _close_to_sma(df: pd.DataFrame, window: int) -> pd.Series:
    return df["close"] / df["close"].rolling(window).mean() - 1.0


def _rsi(df: pd.DataFrame, window: int) -> pd.Series:
    delta = df["close"].diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / window, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=1.0 / window, min_periods=window).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    return 100.0 - 100.0 / (1.0 + rs)


def _macd_line(df: pd.DataFrame) -> pd.Series:
    return (
        df["close"].ewm(span=12, min_periods=12).mean()
        - df["close"].ewm(span=26, min_periods=26).mean()
    )


def _macd_signal(df: pd.DataFrame) -> pd.Series:
    return _macd_line(df).ewm(span=9, min_periods=9).mean()


def _macd_hist(df: pd.DataFrame) -> pd.Series:
    return _macd_line(df) - _macd_signal(df)


def _bollinger_pctb(df: pd.DataFrame, window: int) -> pd.Series:
    mid = df["close"].rolling(window).mean()
    sd = df["close"].rolling(window).std(ddof=1)
    upper = mid + 2.0 * sd
    lower = mid - 2.0 * sd
    width = (upper - lower).replace(0.0, np.nan)
    return (df["close"] - lower) / width


def _bollinger_width(df: pd.DataFrame, window: int) -> pd.Series:
    mid = df["close"].rolling(window).mean()
    sd = df["close"].rolling(window).std(ddof=1)
    return (4.0 * sd) / mid


def _true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    ranges = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def _atr(df: pd.DataFrame, window: int) -> pd.Series:
    return _true_range(df).ewm(alpha=1.0 / window, min_periods=window).mean()


def _natr(df: pd.DataFrame, window: int) -> pd.Series:
    return _atr(df, window) / df["close"]


def _stochastic_k(df: pd.DataFrame, window: int) -> pd.Series:
    low_n = df["low"].rolling(window).min()
    high_n = df["high"].rolling(window).max()
    rng = (high_n - low_n).replace(0.0, np.nan)
    return 100.0 * (df["close"] - low_n) / rng


def _stochastic_d(df: pd.DataFrame, window: int) -> pd.Series:
    return _stochastic_k(df, window).rolling(3).mean()


def _williams_r(df: pd.DataFrame, window: int) -> pd.Series:
    low_n = df["low"].rolling(window).min()
    high_n = df["high"].rolling(window).max()
    rng = (high_n - low_n).replace(0.0, np.nan)
    return -100.0 * (high_n - df["close"]) / rng


def _cci(df: pd.DataFrame, window: int) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    sma = tp.rolling(window).mean()
    mad = tp.rolling(window).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    return (tp - sma) / (0.015 * mad.replace(0.0, np.nan))


def _adx(df: pd.DataFrame, window: int) -> pd.Series:
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = _true_range(df)
    atr = tr.ewm(alpha=1.0 / window, min_periods=window).mean()
    plus_di = (
        100.0
        * pd.Series(plus_dm, index=df.index).ewm(alpha=1.0 / window, min_periods=window).mean()
        / atr.replace(0.0, np.nan)
    )
    minus_di = (
        100.0
        * pd.Series(minus_dm, index=df.index).ewm(alpha=1.0 / window, min_periods=window).mean()
        / atr.replace(0.0, np.nan)
    )
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    return dx.ewm(alpha=1.0 / window, min_periods=window).mean()


def _obv(df: pd.DataFrame) -> pd.Series:
    sign = np.sign(df["close"].diff()).fillna(0.0)
    return (sign * df["volume"]).cumsum()


def _volume_zscore(df: pd.DataFrame, window: int) -> pd.Series:
    mean = df["volume"].rolling(window).mean()
    sd = df["volume"].rolling(window).std(ddof=1).replace(0.0, np.nan)
    return (df["volume"] - mean) / sd


def _dollar_volume_ratio(df: pd.DataFrame, window: int) -> pd.Series:
    dollar = df["close"] * df["volume"]
    return dollar / dollar.rolling(window).mean().replace(0.0, np.nan)


def _rolling_vwap_distance(df: pd.DataFrame, window: int) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = (tp * df["volume"]).rolling(window).sum()
    vol = df["volume"].rolling(window).sum().replace(0.0, np.nan)
    vwap = pv / vol
    return df["close"] / vwap - 1.0


def _rolling_skew(df: pd.DataFrame, window: int) -> pd.Series:
    return df["close"].pct_change().rolling(window).skew()


def _rolling_kurt(df: pd.DataFrame, window: int) -> pd.Series:
    return df["close"].pct_change().rolling(window).kurt()


def _rolling_autocorr(df: pd.DataFrame, window: int) -> pd.Series:
    returns = df["close"].pct_change()
    return returns.rolling(window).apply(lambda x: pd.Series(x).autocorr(lag=1), raw=False)


def _rolling_sharpe(df: pd.DataFrame, window: int) -> pd.Series:
    returns = df["close"].pct_change()
    mean = returns.rolling(window).mean()
    sd = returns.rolling(window).std(ddof=1).replace(0.0, np.nan)
    return mean / sd * np.sqrt(252.0)


def _downside_deviation(df: pd.DataFrame, window: int) -> pd.Series:
    returns = df["close"].pct_change()
    downside = returns.clip(upper=0.0)
    return np.sqrt((downside**2).rolling(window).mean())


def _rolling_max_drawdown(df: pd.DataFrame, window: int) -> pd.Series:
    def _mdd(x: np.ndarray) -> float:
        peak = np.maximum.accumulate(x)
        return float((x / peak - 1.0).min())

    return df["close"].rolling(window).apply(_mdd, raw=True)


def _zscore(df: pd.DataFrame, window: int) -> pd.Series:
    mean = df["close"].rolling(window).mean()
    sd = df["close"].rolling(window).std(ddof=1).replace(0.0, np.nan)
    return (df["close"] - mean) / sd


def _dist_from_high(df: pd.DataFrame, window: int) -> pd.Series:
    return df["close"] / df["high"].rolling(window).max() - 1.0


def _dist_from_low(df: pd.DataFrame, window: int) -> pd.Series:
    return df["close"] / df["low"].rolling(window).min() - 1.0


def _make(
    name: str,
    category: str,
    desc: str,
    min_periods: int,
    func: FeatureFunc,
    version: str = "v1",
) -> Feature:
    return Feature(
        name=name,
        version=version,
        category=category,
        description=desc,
        min_periods=min_periods,
        func=func,
    )


def default_feature_store() -> FeatureStore:
    """Build a store pre-loaded with the built-in feature library (60+ features).

    Mirrors :func:`core_trading.data.reference.build_starter_reference`: a
    factory returning a ready-to-use, fully-populated instance.
    """
    store = FeatureStore()

    def reg(name: str, category: str, desc: str, mp: int, func: FeatureFunc) -> None:
        store.register(_make(name, category, desc, mp, func))

    # -- returns (8)
    for p in (1, 5, 10, 21, 63, 126, 252):
        reg(
            f"ret_{p}",
            "returns",
            f"{p}-bar simple return",
            p + 1,
            cast(FeatureFunc, lambda d, p=p: _returns(d, p)),
        )
    reg("logret_1", "returns", "1-bar log return", 2, lambda d: _log_returns(d, 1))

    # -- volatility (10)
    for w in (5, 10, 21, 63, 126, 252):
        reg(
            f"vol_{w}",
            "volatility",
            f"{w}-bar realised volatility",
            w + 1,
            cast(FeatureFunc, lambda d, w=w: _realised_vol(d, w)),
        )
    reg("ewma_vol_21", "volatility", "EWMA volatility (span 21)", 21, lambda d: _ewma_vol(d, 21))
    reg(
        "parkinson_vol_21",
        "volatility",
        "Parkinson high-low volatility (21)",
        21,
        lambda d: _parkinson_vol(d, 21),
    )
    reg(
        "garman_klass_vol_21",
        "volatility",
        "Garman-Klass OHLC volatility (21)",
        21,
        lambda d: _garman_klass_vol(d, 21),
    )
    reg(
        "rogers_satchell_vol_21",
        "volatility",
        "Rogers-Satchell OHLC volatility (21)",
        21,
        lambda d: _rogers_satchell_vol(d, 21),
    )

    # -- trend / moving averages (11)
    for w in (5, 10, 20, 50, 100, 200):
        reg(
            f"sma_{w}",
            "trend",
            f"{w}-bar simple moving average",
            w,
            cast(FeatureFunc, lambda d, w=w: _sma(d, w)),
        )
    reg("ema_12", "trend", "12-bar EMA", 12, lambda d: _ema(d, 12))
    reg("ema_26", "trend", "26-bar EMA", 26, lambda d: _ema(d, 26))
    for w in (20, 50, 200):
        reg(
            f"close_to_sma_{w}",
            "trend",
            f"close vs {w}-bar SMA (fraction)",
            w,
            cast(FeatureFunc, lambda d, w=w: _close_to_sma(d, w)),
        )

    # -- momentum / oscillators (13)
    reg("rsi_14", "momentum", "Relative Strength Index (14)", 15, lambda d: _rsi(d, 14))
    reg("rsi_28", "momentum", "Relative Strength Index (28)", 29, lambda d: _rsi(d, 28))
    reg("macd", "momentum", "MACD line (12,26)", 26, _macd_line)
    reg("macd_signal", "momentum", "MACD signal line (9)", 35, _macd_signal)
    reg("macd_hist", "momentum", "MACD histogram", 35, _macd_hist)
    reg("stoch_k_14", "momentum", "Stochastic %K (14)", 14, lambda d: _stochastic_k(d, 14))
    reg("stoch_d_14", "momentum", "Stochastic %D (14)", 16, lambda d: _stochastic_d(d, 14))
    reg("williams_r_14", "momentum", "Williams %R (14)", 14, lambda d: _williams_r(d, 14))
    reg("cci_20", "momentum", "Commodity Channel Index (20)", 20, lambda d: _cci(d, 20))
    reg("adx_14", "momentum", "Average Directional Index (14)", 28, lambda d: _adx(d, 14))
    reg("bb_pctb_20", "momentum", "Bollinger %b (20)", 20, lambda d: _bollinger_pctb(d, 20))
    reg(
        "bb_width_20",
        "momentum",
        "Bollinger band width (20)",
        20,
        lambda d: _bollinger_width(d, 20),
    )
    reg("roc_10", "momentum", "10-bar rate of change", 11, lambda d: _returns(d, 10))

    # -- range / volatility-of-range (4)
    reg("atr_14", "range", "Average True Range (14)", 15, lambda d: _atr(d, 14))
    reg("atr_21", "range", "Average True Range (21)", 22, lambda d: _atr(d, 21))
    reg("natr_14", "range", "Normalised ATR (14)", 15, lambda d: _natr(d, 14))
    reg("true_range", "range", "True range (1-bar)", 2, _true_range)

    # -- volume (5)
    reg("obv", "volume", "On-balance volume", 2, _obv)
    reg("volume_zscore_20", "volume", "Volume z-score (20)", 20, lambda d: _volume_zscore(d, 20))
    reg(
        "dollar_volume_ratio_20",
        "volume",
        "Dollar volume vs 20-bar mean",
        20,
        lambda d: _dollar_volume_ratio(d, 20),
    )
    reg(
        "vwap_distance_20",
        "volume",
        "Close vs 20-bar VWAP (fraction)",
        20,
        lambda d: _rolling_vwap_distance(d, 20),
    )
    reg("obv_change_5", "volume", "5-bar OBV change", 6, lambda d: _obv(d).diff(5))

    # -- statistical / position (12)
    reg("skew_21", "statistical", "21-bar return skewness", 21, lambda d: _rolling_skew(d, 21))
    reg("skew_63", "statistical", "63-bar return skewness", 63, lambda d: _rolling_skew(d, 63))
    reg("kurt_21", "statistical", "21-bar return kurtosis", 21, lambda d: _rolling_kurt(d, 21))
    reg("kurt_63", "statistical", "63-bar return kurtosis", 63, lambda d: _rolling_kurt(d, 63))
    reg(
        "autocorr_21",
        "statistical",
        "21-bar lag-1 return autocorrelation",
        22,
        lambda d: _rolling_autocorr(d, 21),
    )
    reg(
        "sharpe_63",
        "statistical",
        "63-bar annualised rolling Sharpe",
        63,
        lambda d: _rolling_sharpe(d, 63),
    )
    reg(
        "downside_dev_63",
        "statistical",
        "63-bar downside deviation",
        63,
        lambda d: _downside_deviation(d, 63),
    )
    reg(
        "max_drawdown_63",
        "statistical",
        "63-bar rolling max drawdown",
        63,
        lambda d: _rolling_max_drawdown(d, 63),
    )
    reg("zscore_20", "statistical", "Close z-score vs 20-bar window", 20, lambda d: _zscore(d, 20))
    reg("zscore_63", "statistical", "Close z-score vs 63-bar window", 63, lambda d: _zscore(d, 63))
    reg(
        "dist_from_high_252",
        "statistical",
        "Distance below 252-bar high",
        252,
        lambda d: _dist_from_high(d, 252),
    )
    reg(
        "dist_from_low_252",
        "statistical",
        "Distance above 252-bar low",
        252,
        lambda d: _dist_from_low(d, 252),
    )

    return store
