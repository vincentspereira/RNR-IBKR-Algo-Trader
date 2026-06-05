"""Tests for core_trading.money.drawdown_management (Phase 8.4)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core_trading.money.drawdown_management import (
    DEFAULT_DRAWDOWN_CONFIG,
    DrawdownConfig,
    compute_drawdown,
    exposure_multiplier,
    releverage_allowed,
    target_exposure,
    vol_of_vol_indicator,
)

# ---------------------------------------------------------------------------
# DrawdownConfig validation
# ---------------------------------------------------------------------------


def test_default_config_singleton() -> None:
    assert isinstance(DEFAULT_DRAWDOWN_CONFIG, DrawdownConfig)
    assert DEFAULT_DRAWDOWN_CONFIG.ladder == {0.05: 0.75, 0.10: 0.50, 0.15: 0.25}


def test_config_rejects_empty_ladder() -> None:
    with pytest.raises(ValueError, match="at least one"):
        DrawdownConfig(ladder={})


def test_config_rejects_bad_depth() -> None:
    with pytest.raises(ValueError, match="depths must be"):
        DrawdownConfig(ladder={0.0: 0.5})
    with pytest.raises(ValueError, match="depths must be"):
        DrawdownConfig(ladder={1.5: 0.5})


def test_config_rejects_bad_multiplier() -> None:
    with pytest.raises(ValueError, match="multipliers must be"):
        DrawdownConfig(ladder={0.1: 1.5})


def test_config_rejects_non_monotone_ladder() -> None:
    # Deeper drawdown (0.10) maps to a LARGER exposure than 0.05 -> reject.
    with pytest.raises(ValueError, match="monotone"):
        DrawdownConfig(ladder={0.05: 0.5, 0.10: 0.8})


@pytest.mark.parametrize(
    "kwargs",
    [
        {"vol_window": 1},
        {"vol_of_vol_window": 0},
        {"releverage_high_water_tol": -0.1},
        {"releverage_high_water_tol": 1.0},
        {"vol_of_vol_halving_factor": 0.0},
        {"vol_of_vol_halving_factor": 1.0},
    ],
)
def test_config_rejects_bad_windows(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        DrawdownConfig(**kwargs)


def test_config_accepts_flat_monotone_ladder() -> None:
    cfg = DrawdownConfig(ladder={0.05: 0.5, 0.10: 0.5})
    assert cfg.ladder[0.05] == 0.5


# ---------------------------------------------------------------------------
# compute_drawdown
# ---------------------------------------------------------------------------


def test_compute_drawdown_basic() -> None:
    equity = pd.Series([100.0, 110.0, 99.0, 121.0])
    dd = compute_drawdown(equity)
    # peaks: 100, 110, 110, 121.
    assert dd.iloc[0] == pytest.approx(0.0)
    assert dd.iloc[1] == pytest.approx(0.0)
    assert dd.iloc[2] == pytest.approx(1.0 - 99.0 / 110.0)
    assert dd.iloc[3] == pytest.approx(0.0)


def test_compute_drawdown_at_new_high_is_zero() -> None:
    equity = pd.Series([100.0, 101.0, 102.0])
    dd = compute_drawdown(equity)
    assert dd.to_numpy() == pytest.approx([0.0, 0.0, 0.0])


def test_compute_drawdown_rejects_empty() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        compute_drawdown(pd.Series([], dtype=float))


def test_compute_drawdown_rejects_non_finite() -> None:
    with pytest.raises(ValueError, match="NaN or infinite"):
        compute_drawdown(pd.Series([100.0, np.nan]))


def test_compute_drawdown_rejects_non_positive() -> None:
    with pytest.raises(ValueError, match="strictly positive"):
        compute_drawdown(pd.Series([100.0, 0.0]))


# ---------------------------------------------------------------------------
# exposure_multiplier
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "dd,expected",
    [
        (0.0, 1.0),
        (0.04, 1.0),
        (0.05, 0.75),
        (0.07, 0.75),
        (0.10, 0.50),
        (0.14, 0.50),
        (0.15, 0.25),
        (0.40, 0.25),
        (-0.10, 1.0),  # negative treated as 0
    ],
)
def test_exposure_multiplier_ladder(dd: float, expected: float) -> None:
    assert exposure_multiplier(dd) == pytest.approx(expected)


def test_exposure_multiplier_rejects_non_finite() -> None:
    with pytest.raises(ValueError, match="finite"):
        exposure_multiplier(float("nan"))


# ---------------------------------------------------------------------------
# vol_of_vol_indicator
# ---------------------------------------------------------------------------


def test_vol_of_vol_disabled_returns_false() -> None:
    cfg = DrawdownConfig(halve_on_vol_of_vol=False)
    rng = np.random.default_rng(1)
    returns = pd.Series(rng.normal(0.0, 0.05, 100))
    assert vol_of_vol_indicator(returns, config=cfg) is False


def test_vol_of_vol_insufficient_history() -> None:
    returns = pd.Series([0.01, -0.01, 0.02])
    assert vol_of_vol_indicator(returns) is False


def test_vol_of_vol_empty_returns_false() -> None:
    assert vol_of_vol_indicator(pd.Series([], dtype=float)) is False


def test_vol_of_vol_rejects_non_finite() -> None:
    returns = pd.Series([0.01] * 30 + [np.inf])
    with pytest.raises(ValueError, match="NaN or infinite"):
        vol_of_vol_indicator(returns)


def test_vol_of_vol_true_on_rising_vol_and_losses() -> None:
    # Calm period then an escalating sequence of losses with growing magnitude
    # so realised vol rises AND cumulative equity falls.
    calm = [0.001, -0.001] * 20  # 40 low-vol bars
    crisis = [-0.02, -0.03, -0.04, -0.05, -0.06, -0.07]  # rising-vol losses
    returns = pd.Series(calm + crisis)
    assert vol_of_vol_indicator(returns) is True


def test_vol_of_vol_false_when_vol_falls() -> None:
    # High-vol then calm: last vol < prior vol, so indicator is False even
    # though there may be losses.
    crisis = [0.06, -0.07, 0.05, -0.06] * 6  # 24 high-vol bars
    calm = [0.0005, -0.0005] * 6  # 12 low-vol bars
    returns = pd.Series(crisis + calm)
    assert vol_of_vol_indicator(returns) is False


# ---------------------------------------------------------------------------
# releverage_allowed
# ---------------------------------------------------------------------------


def test_releverage_true_at_new_high() -> None:
    equity = pd.Series([100.0, 90.0, 105.0])
    assert releverage_allowed(equity) is True


def test_releverage_false_in_drawdown() -> None:
    equity = pd.Series([100.0, 120.0, 110.0])
    assert releverage_allowed(equity) is False


def test_releverage_tolerance_band() -> None:
    cfg = DrawdownConfig(releverage_high_water_tol=0.01)
    # 0.5% below peak, within the 1% tolerance -> allowed.
    equity = pd.Series([100.0, 99.5])
    assert releverage_allowed(equity, config=cfg) is True


# ---------------------------------------------------------------------------
# target_exposure
# ---------------------------------------------------------------------------


def test_target_exposure_full_at_new_high() -> None:
    equity = pd.Series([100.0, 110.0, 120.0])
    returns = equity.pct_change().fillna(0.0)
    assert target_exposure(equity, returns) == pytest.approx(1.0)


def test_target_exposure_laddered_in_drawdown() -> None:
    # Build equity that ends ~12% below peak (no vol-of-vol trigger):
    # short, smooth series so insufficient vol history -> no halving.
    equity = pd.Series([100.0, 88.0])
    returns = equity.pct_change().fillna(0.0)
    # drawdown 0.12 -> ladder bucket [0.10, 0.15) -> 0.50.
    assert target_exposure(equity, returns) == pytest.approx(0.50)


def test_target_exposure_halves_on_vol_of_vol() -> None:
    calm = [0.001, -0.001] * 20
    crisis = [-0.02, -0.03, -0.04, -0.05, -0.06, -0.07]
    returns = pd.Series(calm + crisis)
    equity = (1.0 + returns).cumprod() * 100.0
    dd = compute_drawdown(equity).iloc[-1]
    base = exposure_multiplier(float(dd))
    result = target_exposure(equity, returns)
    assert vol_of_vol_indicator(returns) is True
    assert result == pytest.approx(base * 0.5)


# ---------------------------------------------------------------------------
# Seeded crash-and-recovery simulation (Phase 8 DOD: "drawdown circuit logic
# verified in simulation")
# ---------------------------------------------------------------------------


def test_simulated_crash_and_recovery_multiplier_path() -> None:
    """Replay a synthetic crash + recovery and assert the multiplier path.

    Phases of the synthetic equity curve:

    1. Calm uptrend (full exposure, multiplier 1.0).
    2. Crash with escalating losses (laddered down, then halved on the
       vol-of-vol overlay).
    3. Choppy recovery still below the prior high (stays reduced -- hysteresis
       prevents premature re-leverage).
    4. New high-water mark reached (multiplier restored to 1.0).
    """
    rng = np.random.default_rng(8_2026)

    # Phase 1: calm uptrend, low vol, drifting up.
    calm = list(rng.normal(0.0015, 0.002, 40))
    # Phase 2: crash -- monotonically larger losses (rising vol + growing dd).
    crash = [-0.02, -0.03, -0.04, -0.05, -0.06, -0.07, -0.05]
    # Phase 3: choppy, net-flat recovery that stays below the prior peak.
    chop = [0.01, -0.008, 0.012, -0.009, 0.011, -0.007]
    # Phase 4: strong rally to a fresh all-time high.
    rally = [0.05] * 12

    returns = pd.Series(calm + crash + chop + rally)
    equity = (1.0 + returns).cumprod() * 100.0

    cfg = DEFAULT_DRAWDOWN_CONFIG

    # --- Assert at the end of Phase 1: full exposure ---
    end_calm = len(calm)
    eq1 = equity.iloc[:end_calm]
    ret1 = returns.iloc[:end_calm]
    # Shallow noise keeps the drawdown below the first ladder rung -> full
    # exposure even if the very last calm bar is fractionally off the peak.
    first_rung = min(cfg.ladder)
    assert float(compute_drawdown(eq1).iloc[-1]) < first_rung
    assert target_exposure(eq1, ret1, config=cfg) == pytest.approx(1.0)

    # --- Assert at the bottom of the crash: reduced and halved ---
    end_crash = end_calm + len(crash)
    eq2 = equity.iloc[:end_crash]
    ret2 = returns.iloc[:end_crash]
    dd_bottom = float(compute_drawdown(eq2).iloc[-1])
    assert dd_bottom > 0.15  # deep enough to hit the bottom ladder rung
    base_bottom = exposure_multiplier(dd_bottom, config=cfg)
    assert base_bottom == pytest.approx(0.25)
    assert vol_of_vol_indicator(ret2, config=cfg) is True
    exp_bottom = target_exposure(eq2, ret2, config=cfg)
    assert exp_bottom == pytest.approx(0.25 * 0.5)
    assert releverage_allowed(eq2, config=cfg) is False

    # --- Assert during choppy recovery: still reduced, not re-levered ---
    end_chop = end_crash + len(chop)
    eq3 = equity.iloc[:end_chop]
    ret3 = returns.iloc[:end_chop]
    assert releverage_allowed(eq3, config=cfg) is False
    exp_chop = target_exposure(eq3, ret3, config=cfg)
    assert exp_chop < 1.0  # hysteresis keeps exposure down below prior high

    # --- Assert after the rally to a new high: fully restored ---
    eq4 = equity  # full curve, ends at all-time high
    ret4 = returns
    assert releverage_allowed(eq4, config=cfg) is True
    assert target_exposure(eq4, ret4, config=cfg) == pytest.approx(1.0)

    # Equity really did make a new high vs the pre-crash peak.
    pre_crash_peak = float(equity.iloc[:end_calm].max())
    assert float(equity.iloc[-1]) > pre_crash_peak
