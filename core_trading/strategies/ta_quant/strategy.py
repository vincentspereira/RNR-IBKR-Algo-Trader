"""TAQuantStrategy: composes TA primaries and quantitative overlays.

This module wires the six primaries from :mod:`.primaries` and the three
overlays from :mod:`.overlays` into a single :class:`TAQuantStrategy` object
that satisfies the Phase 3 backtest engine ``Strategy`` protocol
(:class:`core_trading.backtest.engine.Strategy`).

Design
------
* The config is a single frozen dataclass with a ``primary`` name string and
  a ``primary_config`` of the matching primary's config type.
* Overlays are applied in the order they appear in ``overlay_specs``.
* Equal-weight allocation: each active symbol gets weight
  ``gross_cap / max(1, n_active)``, scaled by its position sign.
* Optional long-short normalisation (``long_short_demean``) subtracts the
  cross-sectional mean of active weights so the book is approximately
  dollar-neutral.  This is applied after equal-weight assignment but before
  overlays.
* Diagnostics attributes (``last_positions``, ``last_active_count``) are
  populated after each ``generate_weights`` call, mirroring the pattern in
  :class:`~core_trading.strategies.pairs_trading.PairsTradingStrategy`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from core_trading.strategies.ta_quant.overlays import (
    TrendRegimeGate,
    VolRegimeGate,
    VolTargetScaler,
)
from core_trading.strategies.ta_quant.primaries import (
    BollingerFadeConfig,
    DonchianBreakoutConfig,
    KeltnerSqueezeConfig,
    MACDTrendConfig,
    MACrossConfig,
    RSIDipConfig,
    bollinger_fade,
    donchian_breakout,
    keltner_squeeze,
    ma_cross,
    macd_trend,
    rsi_dip,
)

__all__ = [
    "OverlaySpec",
    "TAQuantConfig",
    "TAQuantStrategy",
]

# ---------------------------------------------------------------------------
# Overlay spec
# ---------------------------------------------------------------------------

# Supported overlay type literals
_OVERLAY_TYPES = frozenset({"vol_regime", "trend_regime", "vol_target"})

# Supported primary name literals
_PRIMARY_NAMES = frozenset(
    {"donchian_breakout", "ma_cross", "rsi_dip", "macd_trend", "bollinger_fade", "keltner_squeeze"}
)


@dataclass(frozen=True, slots=True)
class OverlaySpec:
    """A single overlay declaration in a strategy config.

    Parameters
    ----------
    name:
        Overlay type: ``"vol_regime"``, ``"trend_regime"``, or ``"vol_target"``.
    params:
        Keyword arguments forwarded to the overlay constructor.  Defaults to
        an empty dict (all overlay defaults are used).
    """

    name: str
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.name not in _OVERLAY_TYPES:
            raise ValueError(
                f"overlay name {self.name!r} not recognised; "
                f"valid names: {sorted(_OVERLAY_TYPES)}"
            )

    def build(self) -> VolRegimeGate | TrendRegimeGate | VolTargetScaler:
        """Instantiate the overlay object."""
        if self.name == "vol_regime":
            return VolRegimeGate(**self.params)
        if self.name == "trend_regime":
            return TrendRegimeGate(**self.params)
        # vol_target
        return VolTargetScaler(**self.params)


# ---------------------------------------------------------------------------
# TAQuantConfig
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TAQuantConfig:
    """Full configuration for :class:`TAQuantStrategy`.

    Parameters
    ----------
    primary:
        Name of the primary signal rule (one of ``"donchian_breakout"``,
        ``"ma_cross"``, ``"rsi_dip"``, ``"macd_trend"``,
        ``"bollinger_fade"``, ``"keltner_squeeze"``).
    primary_config:
        Config dataclass instance matching the chosen primary.  Pass
        ``None`` to use the primary's defaults (the primary's config class
        will be instantiated with no arguments).
    overlay_specs:
        Ordered sequence of :class:`OverlaySpec` instances.  Applied left
        to right after the primary produces a weight frame.  Default is no
        overlays.
    gross_cap:
        Maximum sum of absolute weights across all symbols.  Default 1.0.
    long_short_demean:
        When ``True``, subtract the cross-sectional mean of active weights
        so the book is approximately dollar-neutral.  Default ``False``.
    """

    primary: str
    primary_config: (
        DonchianBreakoutConfig
        | MACrossConfig
        | RSIDipConfig
        | MACDTrendConfig
        | BollingerFadeConfig
        | KeltnerSqueezeConfig
        | None
    ) = None
    overlay_specs: tuple[OverlaySpec, ...] = field(default_factory=tuple)
    gross_cap: float = 1.0
    long_short_demean: bool = False

    def __post_init__(self) -> None:
        if self.primary not in _PRIMARY_NAMES:
            raise ValueError(
                f"primary {self.primary!r} not recognised; "
                f"valid names: {sorted(_PRIMARY_NAMES)}"
            )
        if self.gross_cap <= 0.0:
            raise ValueError("gross_cap must be > 0")


# ---------------------------------------------------------------------------
# Default primary configs
# ---------------------------------------------------------------------------

_DEFAULT_PRIMARY_CONFIGS: dict[str, Any] = {
    "donchian_breakout": DonchianBreakoutConfig,
    "ma_cross": MACrossConfig,
    "rsi_dip": RSIDipConfig,
    "macd_trend": MACDTrendConfig,
    "bollinger_fade": BollingerFadeConfig,
    "keltner_squeeze": KeltnerSqueezeConfig,
}


# ---------------------------------------------------------------------------
# TAQuantStrategy
# ---------------------------------------------------------------------------


class TAQuantStrategy:
    """Composable TA x quant strategy implementing the engine Strategy protocol.

    Parameters
    ----------
    config:
        :class:`TAQuantConfig` instance.  Defaults to a ``ma_cross`` strategy
        with all defaults and no overlays.

    Diagnostics
    -----------
    last_positions:
        The raw position frame (``{-1, 0, +1}``) from the last
        ``generate_weights`` call.
    last_active_count:
        Series of ``n_active`` positions per bar from the last call.
    """

    def __init__(self, config: TAQuantConfig | None = None) -> None:
        self.config = config or TAQuantConfig(primary="ma_cross")
        # Diagnostics populated after each generate_weights call.
        self.last_positions: pd.DataFrame | None = None
        self.last_active_count: pd.Series | None = None

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _unpack_panel(
        prices: pd.DataFrame,
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """Unpack a (symbol, timestamp) MultiIndex panel to wide frames.

        Returns ``(close, high, low, volume)`` as ``(timestamp x symbol)``
        DataFrames.
        """
        close = prices["close"].unstack("symbol").sort_index()
        high = prices["high"].unstack("symbol").sort_index()
        low = prices["low"].unstack("symbol").sort_index()
        volume = prices["volume"].unstack("symbol").sort_index()
        return close, high, low, volume

    def _compute_primary(
        self,
        close: pd.DataFrame,
        high: pd.DataFrame,
        low: pd.DataFrame,
    ) -> pd.DataFrame:
        """Dispatch to the configured primary and return a position frame."""
        cfg = self.config
        primary_cfg = (
            cfg.primary_config
            if cfg.primary_config is not None
            else _DEFAULT_PRIMARY_CONFIGS[cfg.primary]()
        )
        if cfg.primary == "donchian_breakout":
            return donchian_breakout(close, high, low, primary_cfg)  # type: ignore[arg-type]
        if cfg.primary == "ma_cross":
            return ma_cross(close, primary_cfg)  # type: ignore[arg-type]
        if cfg.primary == "rsi_dip":
            return rsi_dip(close, primary_cfg)  # type: ignore[arg-type]
        if cfg.primary == "macd_trend":
            return macd_trend(close, primary_cfg)  # type: ignore[arg-type]
        if cfg.primary == "bollinger_fade":
            return bollinger_fade(close, primary_cfg)  # type: ignore[arg-type]
        # keltner_squeeze
        return keltner_squeeze(close, high, low, primary_cfg)  # type: ignore[arg-type]

    @staticmethod
    def _positions_to_weights(
        positions: pd.DataFrame,
        gross_cap: float,
        long_short_demean: bool,
    ) -> pd.DataFrame:
        """Convert a ``{-1, 0, +1}`` position frame to target weights.

        Each active bar's active symbols receive weight
        ``position_sign / max(1, n_active) * gross_cap``.
        Long-short demeaning is applied per-bar after equal-weight assignment.
        """
        pos_arr = positions.to_numpy(dtype=float)
        n_active = (pos_arr != 0.0).sum(axis=1, keepdims=True)
        # Avoid divide-by-zero; inactive bars stay zero.
        denom = np.where(n_active > 0, n_active, 1.0)
        weights = (pos_arr / denom) * gross_cap

        if long_short_demean:
            # For each row, subtract the cross-sectional mean of the *active*
            # (non-zero) weights so the signed sum is approximately zero.
            for row_idx in range(len(weights)):
                row = weights[row_idx]
                active_mask = pos_arr[row_idx] != 0.0
                if active_mask.any():
                    row[active_mask] -= row[active_mask].mean()

        return pd.DataFrame(
            weights, index=positions.index, columns=positions.columns, dtype="float64"
        )

    # ------------------------------------------------------------------ main

    def generate_weights(self, prices: pd.DataFrame) -> pd.DataFrame:
        """Produce a ``(timestamp x symbol)`` target-weight frame.

        Accepts the engine's ``(symbol, timestamp)`` MultiIndex OHLCV panel.

        Parameters
        ----------
        prices:
            Price panel with ``(symbol, timestamp)`` MultiIndex and columns
            ``open, high, low, close, volume``.

        Returns
        -------
        pd.DataFrame
            Weight frame indexed by timestamp, one column per symbol.  Values
            are ``0.0`` where inactive.  ``NaN``-free.
        """
        close, high, low, _ = self._unpack_panel(prices)

        positions = self._compute_primary(close, high, low)
        self.last_positions = positions
        self.last_active_count = pd.Series(
            (positions != 0.0).sum(axis=1).values,
            index=positions.index,
            name="n_active",
        )

        weights = self._positions_to_weights(
            positions,
            gross_cap=self.config.gross_cap,
            long_short_demean=self.config.long_short_demean,
        )

        # Apply overlays in order.
        overlays = [spec.build() for spec in self.config.overlay_specs]
        for overlay in overlays:
            weights = overlay.apply(weights, close)

        return weights.fillna(0.0)
