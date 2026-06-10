"""Adapter: TAQuantStrategy behind the live runner's Strategy seam.

:class:`~core_trading.ops.pairs_live_runner.PairsLiveRunner` is pairs-named
but strategy-generic: it needs ``config.formation_window`` and
``generate_weights(wide_close_frame) -> wide_weight_frame``; everything else
(sizing, delta orders, fills, ledger, kill switch, promotion gate) is
signal-agnostic. This module makes the validated TA x quant configs
(``docs/GO_NO_GO_RSI2_TREND_SURVIVORSHIP_2026-06-10.md``) fit that seam.

The runner's bar source provides daily CLOSES only, so the adapter is
restricted to close-only primaries (the RSI-dip family and friends). The
inner :class:`TAQuantStrategy` expects the engine's ``(symbol, timestamp)``
OHLCV panel; the adapter lifts the close frame into a close-only panel
(open = high = low = close, volume = 1.0). All three overlays
(trend_regime / vol_regime / vol_target) are close-driven, so signals are
bit-identical to a close-only backtest.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from core_trading.strategies.ta_quant import TAQuantConfig, TAQuantStrategy

__all__ = ["CLOSE_ONLY_PRIMARIES", "TAQuantRunnerConfig", "TAQuantRunnerStrategy"]

# Primaries computable from closes alone. Donchian and Keltner need true
# high/low channels and would silently degrade on flat bars -- refuse them.
CLOSE_ONLY_PRIMARIES = frozenset(
    {"rsi_dip", "ma_cross", "macd_trend", "bollinger_fade"}
)


@dataclass(frozen=True, slots=True)
class TAQuantRunnerConfig:
    """The slice of strategy config the live runner reads.

    Attributes
    ----------
    formation_window:
        Bars of pure indicator warm-up before the first tradeable signal --
        the runner pins its formation anchor so this many bars precede the
        first trading day. 252 matches the validated sweep skeleton (RSI-2
        plus SMA-200 plus vol windows all fit comfortably).
    """

    formation_window: int = 252

    def __post_init__(self) -> None:
        if self.formation_window < 1:
            raise ValueError("formation_window must be >= 1")


class TAQuantRunnerStrategy:
    """Close-only TAQuant strategy satisfying the live runner's seam.

    Parameters
    ----------
    taquant_config:
        A validated :class:`TAQuantConfig` whose primary is in
        :data:`CLOSE_ONLY_PRIMARIES`.
    formation_window:
        See :class:`TAQuantRunnerConfig`.

    Diagnostics
    -----------
    ``last_active_count`` mirrors the inner strategy after each call.
    """

    def __init__(
        self, taquant_config: TAQuantConfig, *, formation_window: int = 252
    ) -> None:
        if taquant_config.primary not in CLOSE_ONLY_PRIMARIES:
            raise ValueError(
                f"primary {taquant_config.primary!r} needs true high/low bars; "
                f"the live runner provides closes only. Allowed: "
                f"{sorted(CLOSE_ONLY_PRIMARIES)}"
            )
        self._inner = TAQuantStrategy(taquant_config)
        self.config = TAQuantRunnerConfig(formation_window=formation_window)
        self.last_active_count: pd.Series | None = None

    @property
    def taquant_config(self) -> TAQuantConfig:
        return self._inner.config

    @staticmethod
    def _close_only_panel(closes: pd.DataFrame) -> pd.DataFrame:
        """Lift a (date x symbol) close frame to a (symbol, timestamp) panel."""
        parts: list[pd.DataFrame] = []
        for sym in closes.columns:
            c = closes[sym]
            df = pd.DataFrame(
                {
                    "open": c,
                    "high": c,
                    "low": c,
                    "close": c,
                    "volume": 1.0,
                },
                index=closes.index,
            )
            df.index = pd.MultiIndex.from_product(
                [[str(sym)], closes.index], names=["symbol", "timestamp"]
            )
            parts.append(df)
        return pd.concat(parts).sort_index()

    def generate_weights(self, prices: pd.DataFrame) -> pd.DataFrame:
        """(date x symbol) closes in, (date x symbol) target weights out."""
        weights = self._inner.generate_weights(self._close_only_panel(prices))
        self.last_active_count = self._inner.last_active_count
        # Column order must match the input frame for positional callers.
        return weights.reindex(columns=prices.columns).fillna(0.0)
