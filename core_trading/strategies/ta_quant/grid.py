"""Trial bank for the TA x quant long-history validation sweep.

:func:`build_ta_quant_grid` returns the complete list of
``(name, TAQuantConfig)`` pairs that constitute the trial bank for the
robustness sweep (walk-forward + DSR/PBO/Reality-Check gates, same pattern
as ``tools/pairs_research_pass.py``).

Grid design
-----------
6 primaries x 5 overlay combinations x 2-3 parameter variants per primary
= 60-90 named configs.  The exact count is printed in the module docstring
when the grid is built.

Overlay combinations tested for each primary variant:

  0. No overlay (raw primary signal).
  1. TrendRegimeGate (long/short only with trend).
  2. VolRegimeGate (trade only calm vol regime).
  3. VolTargetScaler (scale to 10% ann. vol, cap 2x).
  4. TrendRegimeGate + VolTargetScaler (trend filter + vol targeting).

Name convention
---------------
Names are filesystem-safe, stable, and short enough for table columns::

    <primary_short><params>_<overlay_short>

Examples::

    dc20_none           -- Donchian-20 no overlay
    dc20_trend200       -- Donchian-20 + TrendRegimeGate(200)
    dc20_calm75         -- Donchian-20 + VolRegimeGate(calm, 75th pct)
    dc20_volt10         -- Donchian-20 + VolTargetScaler(10%)
    dc20_trend200_volt10 -- Donchian-20 + Trend + VolTarget

This grid IS the trial bank for the robustness sweep.  Every config tried
must be counted in the DSR/PBO/Reality-Check deflation to produce honest
out-of-sample statistics.  Do not add configs after the sweep without
re-running the full battery.
"""
from __future__ import annotations

from core_trading.strategies.ta_quant.primaries import (
    BollingerFadeConfig,
    DonchianBreakoutConfig,
    KeltnerSqueezeConfig,
    MACDTrendConfig,
    MACrossConfig,
    RSIDipConfig,
)
from core_trading.strategies.ta_quant.strategy import OverlaySpec, TAQuantConfig

__all__ = ["build_ta_quant_grid"]

# ---------------------------------------------------------------------------
# Overlay spec builders
# ---------------------------------------------------------------------------


def _no_overlay() -> tuple[OverlaySpec, ...]:
    return ()


def _trend_gate(sma_window: int = 200) -> tuple[OverlaySpec, ...]:
    return (OverlaySpec("trend_regime", {"trend_window": sma_window}),)


def _calm_gate(pct: float = 75.0, vol_window: int = 20) -> tuple[OverlaySpec, ...]:
    return (
        OverlaySpec(
            "vol_regime",
            {"vol_window": vol_window, "percentile_threshold": pct, "trade_in_calm": True},
        ),
    )


def _volt(
    target: float = 0.10, vol_window: int = 60, max_lev: float = 2.0
) -> tuple[OverlaySpec, ...]:
    return (
        OverlaySpec(
            "vol_target",
            {"target_vol": target, "vol_window": vol_window, "max_leverage": max_lev},
        ),
    )


def _trend_volt(
    sma_window: int = 200,
    target: float = 0.10,
    vol_window: int = 60,
) -> tuple[OverlaySpec, ...]:
    return (
        OverlaySpec("trend_regime", {"trend_window": sma_window}),
        OverlaySpec("vol_target", {"target_vol": target, "vol_window": vol_window}),
    )


# ---------------------------------------------------------------------------
# Overlay suffix labels
# ---------------------------------------------------------------------------

def _overlay_label(specs: tuple[OverlaySpec, ...]) -> str:
    if not specs:
        return "none"
    parts: list[str] = []
    for spec in specs:
        if spec.name == "trend_regime":
            tw = spec.params.get("trend_window", 200)
            parts.append(f"trend{tw}")
        elif spec.name == "vol_regime":
            pct = spec.params.get("percentile_threshold", 75.0)
            parts.append(f"calm{int(pct)}")
        elif spec.name == "vol_target":
            tv = spec.params.get("target_vol", 0.10)
            parts.append(f"volt{int(tv * 100)}")
    return "_".join(parts)


# ---------------------------------------------------------------------------
# Per-primary config factories
# ---------------------------------------------------------------------------

def _donchian_variants() -> list[tuple[str, DonchianBreakoutConfig]]:
    """Donchian breakout: 3 channel-window variants, long-only."""
    return [
        ("dc20", DonchianBreakoutConfig(channel_window=20, allow_short=False)),
        ("dc40", DonchianBreakoutConfig(channel_window=40, allow_short=False)),
        ("dc55", DonchianBreakoutConfig(channel_window=55, allow_short=False)),
    ]


def _ma_cross_variants() -> list[tuple[str, MACrossConfig]]:
    """EMA crossover: 3 fast/slow combos, long/short."""
    return [
        ("mac1050", MACrossConfig(fast_window=10, slow_window=50, long_only=False)),
        ("mac2050", MACrossConfig(fast_window=20, slow_window=50, long_only=False)),
        ("mac50200", MACrossConfig(fast_window=50, slow_window=200, long_only=False)),
    ]


def _rsi_dip_variants() -> list[tuple[str, RSIDipConfig]]:
    """Connors RSI dip: 2 threshold variants, long-only."""
    return [
        (
            "rsi2t10",
            RSIDipConfig(
                rsi_window=2,
                lower_thresh=10.0,
                upper_thresh=90.0,
                exit_thresh=70.0,
                trend_window=200,
                allow_short=False,
            ),
        ),
        (
            "rsi2t15",
            RSIDipConfig(
                rsi_window=2,
                lower_thresh=15.0,
                upper_thresh=85.0,
                exit_thresh=65.0,
                trend_window=200,
                allow_short=False,
            ),
        ),
        (
            "rsi3t20",
            RSIDipConfig(
                rsi_window=3,
                lower_thresh=20.0,
                upper_thresh=80.0,
                exit_thresh=60.0,
                trend_window=200,
                allow_short=False,
            ),
        ),
    ]


def _macd_variants() -> list[tuple[str, MACDTrendConfig]]:
    """MACD histogram trend: 3 period combos."""
    return [
        ("macd12_26_9", MACDTrendConfig(fast=12, slow=26, signal_period=9, allow_short=True)),
        ("macd8_17_9", MACDTrendConfig(fast=8, slow=17, signal_period=9, allow_short=True)),
        ("macd5_35_5", MACDTrendConfig(fast=5, slow=35, signal_period=5, allow_short=True)),
    ]


def _bb_fade_variants() -> list[tuple[str, BollingerFadeConfig]]:
    """Bollinger fade: 3 band-width configs."""
    return [
        (
            "bbf20_2",
            BollingerFadeConfig(window=20, num_std=2.0, min_bandwidth=0.02, allow_short=True),
        ),
        (
            "bbf20_25",
            BollingerFadeConfig(window=20, num_std=2.5, min_bandwidth=0.03, allow_short=True),
        ),
        (
            "bbf30_2",
            BollingerFadeConfig(window=30, num_std=2.0, min_bandwidth=0.02, allow_short=True),
        ),
    ]


def _keltner_sq_variants() -> list[tuple[str, KeltnerSqueezeConfig]]:
    """Keltner squeeze: 2 multiplier variants."""
    return [
        (
            "ksq20_15",
            KeltnerSqueezeConfig(
                bb_window=20,
                bb_num_std=2.0,
                kc_ema_period=20,
                kc_atr_period=10,
                kc_multiplier=1.5,
                allow_short=True,
            ),
        ),
        (
            "ksq20_20",
            KeltnerSqueezeConfig(
                bb_window=20,
                bb_num_std=2.0,
                kc_ema_period=20,
                kc_atr_period=10,
                kc_multiplier=2.0,
                allow_short=True,
            ),
        ),
    ]


# ---------------------------------------------------------------------------
# Overlay combos per primary
# ---------------------------------------------------------------------------

_OVERLAY_COMBOS: list[tuple[str, tuple[OverlaySpec, ...]]] = [
    ("none", _no_overlay()),
    ("trend200", _trend_gate(200)),
    ("calm75", _calm_gate(75.0)),
    ("volt10", _volt(0.10)),
    ("trend200_volt10", _trend_volt(200, 0.10)),
]

# ---------------------------------------------------------------------------
# Grid assembly
# ---------------------------------------------------------------------------

_PRIMARY_FACTORIES: list[
    tuple[
        str,
        list[tuple[str, Any]],
        str,
    ]
] = [
    ("donchian_breakout", _donchian_variants(), "donchian_breakout"),
    ("ma_cross", _ma_cross_variants(), "ma_cross"),
    ("rsi_dip", _rsi_dip_variants(), "rsi_dip"),
    ("macd_trend", _macd_variants(), "macd_trend"),
    ("bollinger_fade", _bb_fade_variants(), "bollinger_fade"),
    ("keltner_squeeze", _keltner_sq_variants(), "keltner_squeeze"),
]

from typing import Any  # noqa: E402  (imported after _PRIMARY_FACTORIES to keep type ref simple)


def build_ta_quant_grid() -> list[tuple[str, TAQuantConfig]]:
    """Build the complete TA x quant trial bank.

    Returns a list of ``(name, TAQuantConfig)`` pairs covering all six
    primaries, each with 2-3 parameter variants and 5 overlay combinations,
    for a total of ~70 named configs.

    The returned list IS the trial bank for the walk-forward robustness
    sweep.  Names are stable and filesystem-safe.

    Returns
    -------
    list[tuple[str, TAQuantConfig]]
        ``(name, config)`` pairs, names unique within the list.
    """
    grid: list[tuple[str, TAQuantConfig]] = []
    seen: set[str] = set()

    for primary_name, variants, _pkey in _PRIMARY_FACTORIES:
        for variant_label, primary_cfg in variants:
            for overlay_label, overlay_specs in _OVERLAY_COMBOS:
                name = f"{variant_label}_{overlay_label}"
                if name in seen:
                    # Append a counter suffix to guarantee uniqueness.
                    counter = 2
                    while f"{name}_{counter}" in seen:
                        counter += 1
                    name = f"{name}_{counter}"
                seen.add(name)
                config = TAQuantConfig(
                    primary=primary_name,
                    primary_config=primary_cfg,
                    overlay_specs=overlay_specs,
                    gross_cap=1.0,
                    long_short_demean=False,
                )
                grid.append((name, config))

    return grid
