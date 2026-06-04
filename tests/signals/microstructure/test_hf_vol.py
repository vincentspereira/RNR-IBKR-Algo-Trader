"""Tests for core_trading.signals.microstructure.hf_vol.

Covers:
* VolConfig -- frozen/slotted DTO, __post_init__ validation.
* close_to_close_vol -- baseline estimator recovery.
* parkinson_vol     -- GBM sigma recovery; lower estimation variance than CC.
* garman_klass_vol  -- GBM sigma recovery; lower estimation variance than CC.
* rogers_satchell_vol -- GBM sigma recovery; drift-robust.
* yang_zhang_vol    -- GBM sigma recovery; first bar NaN.
* Cross-estimator efficiency: Parkinson, GK, RS, YZ each have lower
  estimation variance than close-to-close (their whole design point).
* Config validation rejects bad inputs.
* NaN propagation and warmup behaviour.
* Public API / __all__ completeness.

Synthetic GBM OHLC simulation
------------------------------
We simulate N OHLC bars consistent with a GBM process with known sigma_true.
For each bar we:
1. Draw M intraday steps from N(0, (sigma_true / sqrt(M))^2).
2. Compute the log-price path within the bar.
3. Extract H, L, O, C from the path (first step = open, last = close,
   max / min = high / low).

This produces OHLC bars that are exactly consistent with the GBM assumption
underlying all five estimators, allowing us to verify recovery within
statistical tolerance.

Estimation variance comparison
--------------------------------
For a single-bar estimator with theoretical variance V, the standard error of
the rolling-mean-of-N-bars estimator converges to sqrt(V / N).  We test that
the SAMPLE variance of the per-bar estimates from Parkinson / GK / RS / YZ is
strictly lower than from close-to-close, consistent with their reported
efficiency gains.  We use a large N (2000 bars) to reduce Monte Carlo noise.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core_trading.signals.microstructure.hf_vol import (
    VolConfig,
    close_to_close_vol,
    garman_klass_vol,
    parkinson_vol,
    rogers_satchell_vol,
    yang_zhang_vol,
)

SEED = 20260604
N_BARS = 2000
SIGMA_TRUE = 0.20  # 20% annualised vol (~ 0.20 / sqrt(252) per day = 1.26% daily)
N_INTRADAY = 78    # intraday steps per bar (~ 5-min bars in a 6.5-hr session)
TRADING_PERIODS = 252


# ---------------------------------------------------------------------------
# GBM OHLC simulator
# ---------------------------------------------------------------------------


def _simulate_ohlc(
    n: int = N_BARS,
    sigma_ann: float = SIGMA_TRUE,
    trading_periods: int = TRADING_PERIODS,
    n_intraday: int = N_INTRADAY,
    seed: int = SEED,
    drift_ann: float = 0.0,
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """Simulate OHLC bars from a GBM with known annualised sigma.

    Each bar has n_intraday intraday steps.  Returns (open, high, low, close)
    as daily pd.Series.

    Parameters
    ----------
    n:
        Number of daily bars.
    sigma_ann:
        Annualised volatility (e.g. 0.20 = 20%).
    trading_periods:
        Trading days per year.
    n_intraday:
        Intraday steps per bar.
    seed:
        RNG seed.
    drift_ann:
        Annualised drift (to test drift-robustness).
    """
    rng = np.random.default_rng(seed)
    sigma_step = sigma_ann / np.sqrt(trading_periods * n_intraday)
    drift_step = drift_ann / (trading_periods * n_intraday)

    idx = pd.date_range("2020-01-01", periods=n, freq="B")

    opens = np.empty(n)
    highs = np.empty(n)
    lows = np.empty(n)
    closes = np.empty(n)

    # Start at price 100 in log space
    current_log = np.log(100.0)

    for i in range(n):
        steps = rng.normal(drift_step, sigma_step, n_intraday)
        log_path = np.concatenate([[current_log], current_log + np.cumsum(steps)])
        opens[i] = np.exp(log_path[0])
        closes[i] = np.exp(log_path[-1])
        highs[i] = np.exp(log_path.max())
        lows[i] = np.exp(log_path.min())
        current_log = log_path[-1]

    return (
        pd.Series(opens, index=idx, name="open"),
        pd.Series(highs, index=idx, name="high"),
        pd.Series(lows, index=idx, name="low"),
        pd.Series(closes, index=idx, name="close"),
    )


# ---------------------------------------------------------------------------
# VolConfig tests
# ---------------------------------------------------------------------------


class TestVolConfig:
    """VolConfig: construction, validation, immutability."""

    def test_valid_defaults(self) -> None:
        cfg = VolConfig()
        assert cfg.window == 21
        assert cfg.trading_periods == 252
        assert cfg.effective_min_periods == 21

    def test_custom(self) -> None:
        cfg = VolConfig(window=30, min_periods=15, trading_periods=260)
        assert cfg.window == 30
        assert cfg.effective_min_periods == 15
        assert cfg.trading_periods == 260

    def test_frozen(self) -> None:
        cfg = VolConfig()
        with pytest.raises((AttributeError, TypeError)):
            cfg.window = 10  # type: ignore[misc]

    def test_window_one_raises(self) -> None:
        with pytest.raises(ValueError, match="window must be >= 2"):
            VolConfig(window=1)

    def test_min_periods_one_raises(self) -> None:
        with pytest.raises(ValueError, match="min_periods must be >= 2"):
            VolConfig(window=10, min_periods=1)

    def test_min_periods_gt_window_raises(self) -> None:
        with pytest.raises(ValueError, match="min_periods"):
            VolConfig(window=10, min_periods=20)

    def test_trading_periods_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="trading_periods must be >= 1"):
            VolConfig(trading_periods=0)

    def test_window_two_allowed(self) -> None:
        cfg = VolConfig(window=2, min_periods=2)
        assert cfg.window == 2


# ---------------------------------------------------------------------------
# Close-to-close tests
# ---------------------------------------------------------------------------


class TestCloseToCLoseVol:
    """close_to_close_vol: shape, warmup, recovery."""

    def test_output_index_and_length(self) -> None:
        _, _, _, close = _simulate_ohlc()
        result = close_to_close_vol(close, window=21)
        assert list(result.index) == list(close.index)
        assert len(result) == len(close)

    def test_warmup_nan(self) -> None:
        """First window bars are NaN (one extra for diff)."""
        _, _, _, close = _simulate_ohlc()
        window = 21
        result = close_to_close_vol(close, window=window)
        # The diff removes bar 0, so the first window bars of the estimator are NaN
        assert result.iloc[:window].isna().all()

    def test_sigma_recovery(self) -> None:
        """Estimator should recover sigma_true within 15% (relative)."""
        _, _, _, close = _simulate_ohlc()
        result = close_to_close_vol(
            close, window=252, min_periods=200, trading_periods=TRADING_PERIODS
        )
        valid = result.dropna()
        assert len(valid) > 100
        median_est = float(valid.median())
        rel_err = abs(median_est - SIGMA_TRUE) / SIGMA_TRUE
        assert rel_err < 0.15, (
            f"CC vol recovery error {rel_err:.1%}; estimated {median_est:.4f}, "
            f"true {SIGMA_TRUE:.4f}"
        )

    def test_non_negative_output(self) -> None:
        _, _, _, close = _simulate_ohlc()
        result = close_to_close_vol(close, window=21).dropna()
        assert (result >= 0.0).all()

    def test_series_name(self) -> None:
        _, _, _, close = _simulate_ohlc(n=50)
        result = close_to_close_vol(close, window=10)
        assert result.name == "cc_vol"


# ---------------------------------------------------------------------------
# Parkinson tests
# ---------------------------------------------------------------------------


class TestParkinsonVol:
    """parkinson_vol: recovery and efficiency over CC."""

    def test_output_index_and_length(self) -> None:
        _, high, low, _ = _simulate_ohlc()
        result = parkinson_vol(high, low, window=21)
        assert list(result.index) == list(high.index)
        assert len(result) == len(high)

    def test_warmup_nan(self) -> None:
        _, high, low, _ = _simulate_ohlc()
        window = 21
        result = parkinson_vol(high, low, window=window)
        assert result.iloc[: window - 1].isna().all()

    def test_sigma_recovery(self) -> None:
        _, high, low, _ = _simulate_ohlc()
        result = parkinson_vol(
            high, low, window=252, min_periods=200, trading_periods=TRADING_PERIODS
        )
        valid = result.dropna()
        median_est = float(valid.median())
        rel_err = abs(median_est - SIGMA_TRUE) / SIGMA_TRUE
        assert rel_err < 0.15, (
            f"Parkinson recovery error {rel_err:.1%}; {median_est:.4f} vs {SIGMA_TRUE:.4f}"
        )

    def test_lower_variance_than_cc(self) -> None:
        """Parkinson per-bar estimates should have lower sample variance than CC.

        Use window=2 (the minimum allowed) with min_periods=2 so each output is
        effectively a 2-bar mean of the per-bar estimator.  This is close to a
        per-bar comparison; relative efficiency ordering is preserved.
        """
        _, high, low, close = _simulate_ohlc(n=N_BARS)
        window = 2
        pk = parkinson_vol(
            high, low, window=window, min_periods=2, trading_periods=TRADING_PERIODS
        ).dropna()
        cc = close_to_close_vol(
            close, window=window, min_periods=2, trading_periods=TRADING_PERIODS
        ).dropna()
        assert float(pk.var()) < float(cc.var()), (
            f"Parkinson sample var {pk.var():.4f} should be < CC {cc.var():.4f}"
        )

    def test_non_negative_output(self) -> None:
        _, high, low, _ = _simulate_ohlc()
        result = parkinson_vol(high, low, window=21).dropna()
        assert (result >= 0.0).all()

    def test_series_name(self) -> None:
        _, high, low, _ = _simulate_ohlc(n=50)
        result = parkinson_vol(high, low, window=10)
        assert result.name == "parkinson_vol"

    def test_mismatched_length_raises(self) -> None:
        _, high, low, _ = _simulate_ohlc(n=50)
        with pytest.raises(ValueError, match="same length"):
            parkinson_vol(high, low.iloc[:-1], window=10)

    def test_mismatched_index_raises(self) -> None:
        _, high, low, _ = _simulate_ohlc(n=50)
        low_ri = low.copy()
        low_ri.index = pd.date_range("2021-01-01", periods=50, freq="B")
        with pytest.raises(ValueError, match="same index"):
            parkinson_vol(high, low_ri, window=10)

    def test_nan_propagation(self) -> None:
        _, high, low, _ = _simulate_ohlc(n=100)
        high_nan = high.copy()
        high_nan.iloc[50] = float("nan")
        result = parkinson_vol(high_nan, low, window=10)
        # The window containing bar 50 should have NaN
        assert result.iloc[50:60].isna().any()


# ---------------------------------------------------------------------------
# Garman-Klass tests
# ---------------------------------------------------------------------------


class TestGarmanKlassVol:
    """garman_klass_vol: recovery and efficiency over CC."""

    def test_output_index_and_length(self) -> None:
        open_, high, low, close = _simulate_ohlc()
        result = garman_klass_vol(open_, high, low, close, window=21)
        assert list(result.index) == list(open_.index)

    def test_warmup_nan(self) -> None:
        open_, high, low, close = _simulate_ohlc()
        window = 21
        result = garman_klass_vol(open_, high, low, close, window=window)
        assert result.iloc[: window - 1].isna().all()

    def test_sigma_recovery(self) -> None:
        open_, high, low, close = _simulate_ohlc()
        result = garman_klass_vol(
            open_, high, low, close,
            window=252, min_periods=200, trading_periods=TRADING_PERIODS
        )
        valid = result.dropna()
        median_est = float(valid.median())
        rel_err = abs(median_est - SIGMA_TRUE) / SIGMA_TRUE
        assert rel_err < 0.15, (
            f"GK recovery error {rel_err:.1%}; {median_est:.4f} vs {SIGMA_TRUE:.4f}"
        )

    def test_lower_variance_than_cc(self) -> None:
        open_, high, low, close = _simulate_ohlc(n=N_BARS)
        window = 2
        gk = garman_klass_vol(
            open_, high, low, close,
            window=window, min_periods=2, trading_periods=TRADING_PERIODS
        ).dropna()
        cc = close_to_close_vol(
            close, window=window, min_periods=2, trading_periods=TRADING_PERIODS
        ).dropna()
        assert float(gk.var()) < float(cc.var()), (
            f"GK sample var {gk.var():.4f} should be < CC {cc.var():.4f}"
        )

    def test_series_name(self) -> None:
        open_, high, low, close = _simulate_ohlc(n=50)
        result = garman_klass_vol(open_, high, low, close, window=10)
        assert result.name == "garman_klass_vol"

    def test_mismatched_length_raises(self) -> None:
        open_, high, low, close = _simulate_ohlc(n=50)
        with pytest.raises(ValueError, match="same length"):
            garman_klass_vol(open_, high, low.iloc[:-1], close, window=10)

    def test_mismatched_index_raises(self) -> None:
        open_, high, low, close = _simulate_ohlc(n=50)
        close_ri = close.copy()
        close_ri.index = pd.date_range("2021-01-01", periods=50, freq="B")
        with pytest.raises(ValueError, match="same index"):
            garman_klass_vol(open_, high, low, close_ri, window=10)


# ---------------------------------------------------------------------------
# Rogers-Satchell tests
# ---------------------------------------------------------------------------


class TestRogersSatchellVol:
    """rogers_satchell_vol: recovery, drift-robustness, efficiency."""

    def test_output_index_and_length(self) -> None:
        open_, high, low, close = _simulate_ohlc()
        result = rogers_satchell_vol(open_, high, low, close, window=21)
        assert list(result.index) == list(open_.index)

    def test_warmup_nan(self) -> None:
        open_, high, low, close = _simulate_ohlc()
        window = 21
        result = rogers_satchell_vol(open_, high, low, close, window=window)
        assert result.iloc[: window - 1].isna().all()

    def test_sigma_recovery_no_drift(self) -> None:
        open_, high, low, close = _simulate_ohlc(drift_ann=0.0)
        result = rogers_satchell_vol(
            open_, high, low, close,
            window=252, min_periods=200, trading_periods=TRADING_PERIODS
        )
        valid = result.dropna()
        median_est = float(valid.median())
        rel_err = abs(median_est - SIGMA_TRUE) / SIGMA_TRUE
        assert rel_err < 0.15, (
            f"RS recovery error {rel_err:.1%}; {median_est:.4f} vs {SIGMA_TRUE:.4f}"
        )

    def test_sigma_recovery_with_drift(self) -> None:
        """Rogers-Satchell should recover sigma even with non-zero drift."""
        open_, high, low, close = _simulate_ohlc(drift_ann=0.30)  # 30% annual drift
        result = rogers_satchell_vol(
            open_, high, low, close,
            window=252, min_periods=200, trading_periods=TRADING_PERIODS
        )
        valid = result.dropna()
        median_est = float(valid.median())
        rel_err = abs(median_est - SIGMA_TRUE) / SIGMA_TRUE
        assert rel_err < 0.20, (
            f"RS drift-robust recovery error {rel_err:.1%}; "
            f"{median_est:.4f} vs {SIGMA_TRUE:.4f}"
        )

    def test_lower_variance_than_cc(self) -> None:
        open_, high, low, close = _simulate_ohlc(n=N_BARS)
        window = 2
        rs = rogers_satchell_vol(
            open_, high, low, close,
            window=window, min_periods=2, trading_periods=TRADING_PERIODS
        ).dropna()
        cc = close_to_close_vol(
            close, window=window, min_periods=2, trading_periods=TRADING_PERIODS
        ).dropna()
        assert float(rs.var()) < float(cc.var()), (
            f"RS sample var {rs.var():.4f} should be < CC {cc.var():.4f}"
        )

    def test_series_name(self) -> None:
        open_, high, low, close = _simulate_ohlc(n=50)
        result = rogers_satchell_vol(open_, high, low, close, window=10)
        assert result.name == "rogers_satchell_vol"

    def test_mismatched_length_raises(self) -> None:
        open_, high, low, close = _simulate_ohlc(n=50)
        with pytest.raises(ValueError, match="same length"):
            rogers_satchell_vol(open_, high.iloc[:-1], low, close, window=10)

    def test_mismatched_index_raises(self) -> None:
        open_, high, low, close = _simulate_ohlc(n=50)
        high_ri = high.copy()
        high_ri.index = pd.date_range("2021-01-01", periods=50, freq="B")
        with pytest.raises(ValueError, match="same index"):
            rogers_satchell_vol(open_, high_ri, low, close, window=10)


# ---------------------------------------------------------------------------
# Yang-Zhang tests
# ---------------------------------------------------------------------------


class TestYangZhangVol:
    """yang_zhang_vol: recovery, overnight gap handling, first-bar NaN."""

    def test_output_index_and_length(self) -> None:
        open_, high, low, close = _simulate_ohlc()
        result = yang_zhang_vol(open_, high, low, close, window=21)
        assert list(result.index) == list(open_.index)

    def test_first_bar_always_nan(self) -> None:
        """The first bar is always NaN (requires previous close for overnight gap)."""
        open_, high, low, close = _simulate_ohlc(n=100)
        result = yang_zhang_vol(open_, high, low, close, window=2, min_periods=2)
        assert result.iloc[0] != result.iloc[0]  # NaN check via reflexivity

    def test_warmup_nan(self) -> None:
        open_, high, low, close = _simulate_ohlc()
        window = 21
        result = yang_zhang_vol(open_, high, low, close, window=window)
        assert result.iloc[:window].isna().all()

    def test_sigma_recovery_no_gap(self) -> None:
        """Without overnight gaps (open=prev close), should recover sigma_true."""
        open_, high, low, close = _simulate_ohlc(drift_ann=0.0)
        result = yang_zhang_vol(
            open_, high, low, close,
            window=252, min_periods=200, trading_periods=TRADING_PERIODS
        )
        valid = result.dropna()
        median_est = float(valid.median())
        rel_err = abs(median_est - SIGMA_TRUE) / SIGMA_TRUE
        assert rel_err < 0.20, (
            f"YZ recovery error {rel_err:.1%}; {median_est:.4f} vs {SIGMA_TRUE:.4f}"
        )

    def test_lower_variance_than_cc(self) -> None:
        open_, high, low, close = _simulate_ohlc(n=N_BARS)
        window = 2
        yz = yang_zhang_vol(
            open_, high, low, close,
            window=window, min_periods=2, trading_periods=TRADING_PERIODS
        ).dropna()
        cc = close_to_close_vol(
            close, window=window, min_periods=2, trading_periods=TRADING_PERIODS
        ).dropna()
        assert float(yz.var()) < float(cc.var()), (
            f"YZ sample var {yz.var():.4f} should be < CC {cc.var():.4f}"
        )

    def test_non_negative_output(self) -> None:
        open_, high, low, close = _simulate_ohlc()
        result = yang_zhang_vol(open_, high, low, close, window=21).dropna()
        assert (result >= 0.0).all()

    def test_series_name(self) -> None:
        open_, high, low, close = _simulate_ohlc(n=50)
        result = yang_zhang_vol(open_, high, low, close, window=10)
        assert result.name == "yang_zhang_vol"

    def test_mismatched_length_raises(self) -> None:
        open_, high, low, close = _simulate_ohlc(n=50)
        with pytest.raises(ValueError, match="same length"):
            yang_zhang_vol(open_, high, low, close.iloc[:-1], window=10)

    def test_mismatched_index_raises(self) -> None:
        open_, high, low, close = _simulate_ohlc(n=50)
        low_ri = low.copy()
        low_ri.index = pd.date_range("2021-01-01", periods=50, freq="B")
        with pytest.raises(ValueError, match="same index"):
            yang_zhang_vol(open_, high, low_ri, close, window=10)

    def test_nan_propagation(self) -> None:
        open_, high, low, close = _simulate_ohlc(n=100)
        close_nan = close.copy()
        close_nan.iloc[50] = float("nan")
        result = yang_zhang_vol(open_, high, low, close_nan, window=10)
        # bar 50 has NaN close; bar 51 has NaN overnight (uses close 50)
        assert result.iloc[50:60].isna().any()


# ---------------------------------------------------------------------------
# Cross-estimator efficiency comparison
# ---------------------------------------------------------------------------


class TestEfficiencyOrdering:
    """All range estimators should have lower estimation variance than CC."""

    def test_all_beat_cc(self) -> None:
        """Each OHLC estimator's sample variance is < CC's when using window=2.

        window=2 (the minimum allowed) with min_periods=2 gives 2-bar rolling
        means of the per-bar estimator, which preserves the relative efficiency
        ordering.
        """
        open_, high, low, close = _simulate_ohlc(n=N_BARS)
        window = 2
        kw = dict(window=window, min_periods=2, trading_periods=TRADING_PERIODS)

        cc_var = float(
            close_to_close_vol(close, **kw).dropna().var()
        )
        pk_var = float(
            parkinson_vol(high, low, **kw).dropna().var()
        )
        gk_var = float(
            garman_klass_vol(open_, high, low, close, **kw).dropna().var()
        )
        rs_var = float(
            rogers_satchell_vol(open_, high, low, close, **kw).dropna().var()
        )
        yz_var = float(
            yang_zhang_vol(open_, high, low, close, **kw).dropna().var()
        )

        for name, var in [("Parkinson", pk_var), ("GK", gk_var), ("RS", rs_var), ("YZ", yz_var)]:
            assert var < cc_var, (
                f"{name} sample var {var:.4f} should be < CC {cc_var:.4f}"
            )


# ---------------------------------------------------------------------------
# Public API / __all__ check
# ---------------------------------------------------------------------------


class TestPublicAPI:
    """Verify __all__ exports and importability."""

    def test_all_names_importable(self) -> None:
        import core_trading.signals.microstructure.hf_vol as mod

        expected = {
            "VolConfig",
            "close_to_close_vol",
            "parkinson_vol",
            "garman_klass_vol",
            "rogers_satchell_vol",
            "yang_zhang_vol",
        }
        for name in expected:
            assert hasattr(mod, name), f"Missing: {name}"

    def test_all_contains_expected(self) -> None:
        import core_trading.signals.microstructure.hf_vol as mod

        for name in mod.__all__:
            assert hasattr(mod, name)

    def test_config_is_dataclass(self) -> None:
        import dataclasses

        assert dataclasses.is_dataclass(VolConfig)
