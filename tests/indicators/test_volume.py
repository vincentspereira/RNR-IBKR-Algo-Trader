"""Tests for core_trading.indicators.volume.

Covers:
- Warm-up NaN count / cumulative behaviour.
- Truncation invariance.
- Reference values from first principles.
- Input validation.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_N = 60


def _prices(n: int = _N, seed: int = 42) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(100.0 + np.cumsum(rng.normal(0, 0.5, n)), dtype="float64")


def _ohlcv(n: int = _N, seed: int = 42) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    c = _prices(n, seed)
    rng = np.random.default_rng(seed + 1)
    high = c + rng.uniform(0.3, 2.0, n)
    low = c - rng.uniform(0.3, 2.0, n)
    vol = pd.Series(rng.integers(100_000, 5_000_000, n).astype(float))
    return high.rename(None), low.rename(None), c, vol


def _check_truncation(fn, *args, k: int | None = None) -> None:
    if k is None:
        k = len(args[0]) // 2
    full = fn(*args)
    trunc = fn(*[a.iloc[:k] if isinstance(a, pd.Series) else a for a in args])
    if isinstance(full, pd.DataFrame):
        for col in full.columns:
            fs = full[col].iloc[:k]
            ts_ = trunc[col]
            valid = fs.notna() & ts_.notna()
            if valid.any():
                np.testing.assert_allclose(
                    fs[valid].values,
                    ts_[valid].values,
                    rtol=1e-10,
                    err_msg=f"{fn.__name__}[{col}]: truncation invariance failed",
                )
    else:
        fs = full.iloc[:k]
        ts_ = trunc
        valid = fs.notna() & ts_.notna()
        if valid.any():
            np.testing.assert_allclose(
                fs[valid].values,
                ts_[valid].values,
                rtol=1e-10,
                err_msg=f"{fn.__name__}: truncation invariance failed",
            )


# ---------------------------------------------------------------------------
# OBV
# ---------------------------------------------------------------------------


class TestOBV:
    def test_all_valid(self) -> None:
        h, low, c, v = _ohlcv()
        result = obv(c, v)
        assert result.notna().all()

    def test_reference_ascending(self) -> None:
        # Prices always up: OBV cumulates all volume
        c = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        v = pd.Series([100.0, 200.0, 300.0, 400.0, 500.0])
        result = obv(c, v)
        np.testing.assert_allclose(result.iloc[0], 100.0)
        np.testing.assert_allclose(result.iloc[1], 300.0)
        np.testing.assert_allclose(result.iloc[2], 600.0)
        np.testing.assert_allclose(result.iloc[3], 1000.0)
        np.testing.assert_allclose(result.iloc[4], 1500.0)

    def test_reference_descending(self) -> None:
        c = pd.Series([5.0, 4.0, 3.0, 2.0, 1.0])
        v = pd.Series([100.0, 200.0, 300.0, 400.0, 500.0])
        result = obv(c, v)
        np.testing.assert_allclose(result.iloc[0], 100.0)
        np.testing.assert_allclose(result.iloc[1], -100.0)  # 100 - 200
        np.testing.assert_allclose(result.iloc[2], -400.0)

    def test_truncation_invariance(self) -> None:
        h, low, c, v = _ohlcv()
        _check_truncation(obv, c, v, k=30)

    def test_output_dtype(self) -> None:
        h, low, c, v = _ohlcv()
        assert obv(c, v).dtype == np.float64

    def test_mismatched_index_raises(self) -> None:
        c = _prices(30)
        v = _prices(25)
        with pytest.raises(ValueError):
            obv(c, v)


# ---------------------------------------------------------------------------
# VWAP Rolling
# ---------------------------------------------------------------------------


class TestVWAPRolling:
    def test_warmup_nan_count(self) -> None:
        h, low, c, v = _ohlcv()
        result = vwap_rolling(h, low, c, v, window=20)
        assert result.iloc[:19].isna().all()
        assert result.iloc[19:].notna().all()

    def test_reference_unit_volume(self) -> None:
        # Equal volume: VWAP == average of typical prices
        h = pd.Series([10.0, 12.0, 14.0])
        low = pd.Series([8.0, 10.0, 12.0])
        c = pd.Series([9.0, 11.0, 13.0])
        v = pd.Series([1.0, 1.0, 1.0])
        result = vwap_rolling(h, low, c, v, window=3)
        # TP = [(10+8+9)/3, (12+10+11)/3, (14+12+13)/3] = [9, 11, 13]
        # VWAP = mean([9, 11, 13]) = 11
        np.testing.assert_allclose(result.iloc[2], 11.0, rtol=1e-10)

    def test_truncation_invariance(self) -> None:
        h, low, c, v = _ohlcv()
        _check_truncation(vwap_rolling, h, low, c, v, k=35)

    def test_output_dtype(self) -> None:
        h, low, c, v = _ohlcv()
        assert vwap_rolling(h, low, c, v).dtype == np.float64

    def test_invalid_window(self) -> None:
        h, low, c, v = _ohlcv()
        with pytest.raises(ValueError):
            vwap_rolling(h, low, c, v, window=0)


# ---------------------------------------------------------------------------
# VWAP Anchored
# ---------------------------------------------------------------------------


class TestVWAPAnchored:
    def test_all_valid_fallback(self) -> None:
        """With a plain RangeIndex, falls back to cumulative VWAP."""
        h, low, c, v = _ohlcv()
        result = vwap_anchored(h, low, c, v)
        assert result.notna().all()

    def test_session_reset_with_datetime_index(self) -> None:
        """With a DatetimeIndex, resets each day -- each day's first bar equals TP."""
        idx = pd.date_range("2024-01-01 09:30", periods=_N, freq="5min")
        h, low, c, v = _ohlcv()
        h.index = idx
        low.index = idx
        c.index = idx
        v.index = idx
        result = vwap_anchored(h, low, c, v)
        assert result.notna().all()

    def test_output_dtype(self) -> None:
        h, low, c, v = _ohlcv()
        assert vwap_anchored(h, low, c, v).dtype == np.float64


# ---------------------------------------------------------------------------
# MFI
# ---------------------------------------------------------------------------


class TestMFI:
    def test_warmup_nan_count(self) -> None:
        # pos_mf/neg_mf are 0 at bar 0 (no prior TP), valid from bar 0.
        # rolling sum of width 14 with min_periods=14 first valid at index 13.
        h, low, c, v = _ohlcv()
        result = mfi(h, low, c, v, window=14)
        assert result.iloc[:13].isna().all()
        assert result.iloc[13:].notna().all()

    def test_range_0_100(self) -> None:
        h, low, c, v = _ohlcv()
        result = mfi(h, low, c, v, window=14)
        valid = result.dropna()
        assert (valid >= 0.0).all() and (valid <= 100.0).all()

    def test_truncation_invariance(self) -> None:
        h, low, c, v = _ohlcv()
        _check_truncation(mfi, h, low, c, v, k=40)

    def test_output_dtype(self) -> None:
        h, low, c, v = _ohlcv()
        assert mfi(h, low, c, v).dtype == np.float64

    def test_invalid_window(self) -> None:
        h, low, c, v = _ohlcv()
        with pytest.raises(ValueError):
            mfi(h, low, c, v, window=0)


# ---------------------------------------------------------------------------
# CMF
# ---------------------------------------------------------------------------


class TestCMF:
    def test_warmup_nan_count(self) -> None:
        h, low, c, v = _ohlcv()
        result = cmf(h, low, c, v, window=20)
        assert result.iloc[:19].isna().all()
        assert result.iloc[19:].notna().all()

    def test_range_minus1_to_1(self) -> None:
        h, low, c, v = _ohlcv()
        result = cmf(h, low, c, v, window=20)
        valid = result.dropna()
        assert (valid >= -1.0).all() and (valid <= 1.0).all()

    def test_truncation_invariance(self) -> None:
        h, low, c, v = _ohlcv()
        _check_truncation(cmf, h, low, c, v, k=40)

    def test_output_dtype(self) -> None:
        h, low, c, v = _ohlcv()
        assert cmf(h, low, c, v).dtype == np.float64

    def test_reference_close_at_high(self) -> None:
        # close == high: CLV = 1, CMF > 0
        n = 25
        h = pd.Series([10.0] * n)
        low = pd.Series([5.0] * n)
        c = h.copy()  # close == high
        v = pd.Series([1000.0] * n)
        result = cmf(h, low, c, v, window=10)
        np.testing.assert_allclose(result.dropna().values, 1.0, atol=1e-10)

    def test_invalid_window(self) -> None:
        h, low, c, v = _ohlcv()
        with pytest.raises(ValueError):
            cmf(h, low, c, v, window=0)


# ---------------------------------------------------------------------------
# AD Line
# ---------------------------------------------------------------------------


class TestADLine:
    def test_all_valid(self) -> None:
        h, low, c, v = _ohlcv()
        result = ad_line(h, low, c, v)
        assert result.notna().all()

    def test_truncation_invariance(self) -> None:
        h, low, c, v = _ohlcv()
        _check_truncation(ad_line, h, low, c, v, k=30)

    def test_output_dtype(self) -> None:
        h, low, c, v = _ohlcv()
        assert ad_line(h, low, c, v).dtype == np.float64

    def test_reference_close_at_high(self) -> None:
        # close == high => CLV = 1 => ADL cumulates volume
        h = pd.Series([10.0, 10.0, 10.0])
        low = pd.Series([5.0, 5.0, 5.0])
        c = pd.Series([10.0, 10.0, 10.0])
        v = pd.Series([1000.0, 1000.0, 1000.0])
        result = ad_line(h, low, c, v)
        np.testing.assert_allclose(result.iloc[0], 1000.0)
        np.testing.assert_allclose(result.iloc[1], 2000.0)
        np.testing.assert_allclose(result.iloc[2], 3000.0)


# ---------------------------------------------------------------------------
# Force Index
# ---------------------------------------------------------------------------


class TestForceIndex:
    def test_warmup_nans(self) -> None:
        h, low, c, v = _ohlcv()
        result = force_index(c, v, window=13)
        assert result.isna().sum() > 0

    def test_truncation_invariance(self) -> None:
        h, low, c, v = _ohlcv()
        _check_truncation(force_index, c, v, k=35)

    def test_output_dtype(self) -> None:
        h, low, c, v = _ohlcv()
        assert force_index(c, v).dtype == np.float64

    def test_invalid_window(self) -> None:
        h, low, c, v = _ohlcv()
        with pytest.raises(ValueError):
            force_index(c, v, window=0)


# ---------------------------------------------------------------------------
# EOM
# ---------------------------------------------------------------------------


class TestEOM:
    def test_warmup_nans(self) -> None:
        h, low, c, v = _ohlcv()
        result = eom(h, low, v, window=14)
        assert result.isna().sum() > 0

    def test_truncation_invariance(self) -> None:
        h, low, c, v = _ohlcv()
        _check_truncation(eom, h, low, v, k=35)

    def test_output_dtype(self) -> None:
        h, low, c, v = _ohlcv()
        assert eom(h, low, v).dtype == np.float64

    def test_invalid_window(self) -> None:
        h, low, c, v = _ohlcv()
        with pytest.raises(ValueError):
            eom(h, low, v, window=0)
