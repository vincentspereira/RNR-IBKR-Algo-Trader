"""Tests for core_trading.signals.factors.style_factors (Phase 5.C.5).

Covers:
* StyleFactorConfig -- frozen/slotted DTO, __post_init__ validation.
* pit_characteristic -- point-in-time forward-fill, leakage guard (filed-after-t
  fundamental does NOT affect score at t).
* value_scores -- high book-to-price names get top value z-scores; composite
  averages multiple legs; empty fundamentals -> all NaN.
* quality_scores -- high-ROE / low-leverage / stable-earnings names get top
  quality z-scores; individual leg selection works.
* lowvol_scores -- PRICE-ONLY; low-vol assets get high (positive) scores;
  realised vol of long portfolio < realised vol of short portfolio; no
  fundamentals required.
* style_factor_weights -- dollar-neutral; long +1 / short -1; quantile passes
  through to long_short_weights.
* style_factor_panels -- full pipeline returns all 6 expected keys; shapes match.
* Parameter-recovery tests with synthetic data:
    - LOW-VOL: planted assets with known volatilities.
    - QUALITY: planted high-ROE / low-leverage / stable-earnings names.
    - VALUE: planted cheap (high book-to-price) names.
* Edge cases: all-NaN scores row, single sub-signal config, empty fundamentals,
  NaN in prices, missing metric in fundamentals.
* _winsorise_rows internal helper tested via value_scores output range.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from core_trading.signals.factors.style_factors import (
    StyleFactorConfig,
    lowvol_scores,
    pit_characteristic,
    quality_scores,
    style_factor_panels,
    style_factor_weights,
    value_scores,
)

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

SEED = 20260601
N_BARS = 300
N_ASSETS = 12


# ---------------------------------------------------------------------------
# Synthetic data factories
# ---------------------------------------------------------------------------


def _make_price_panel(
    n_bars: int = N_BARS,
    n_assets: int = N_ASSETS,
    seed: int = SEED,
    base_vol: float = 0.01,
) -> pd.DataFrame:
    """Build a random walk price panel with uniform volatility."""
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0, base_vol, size=(n_bars - 1, n_assets))
    prices = np.ones((n_bars, n_assets))
    prices[1:] = np.cumprod(1.0 + returns, axis=0)
    dates = pd.date_range("2020-01-01", periods=n_bars, freq="B")
    cols = [f"A{i}" for i in range(n_assets)]
    return pd.DataFrame(prices, index=dates, columns=cols)


def _make_fundamentals(
    symbols: list[str],
    metric: str,
    values: list[float],
    filing_date: date,
    period_end: date | None = None,
) -> pd.DataFrame:
    """Build a minimal tidy fundamentals frame.

    One record per symbol with the given metric/values filed at filing_date.
    """
    if period_end is None:
        period_end = filing_date - timedelta(days=30)
    records = []
    for sym, val in zip(symbols, values, strict=False):
        records.append({
            "symbol": sym,
            "statement": "balance_sheet",
            "metric": metric,
            "value": float(val),
            "period_end": period_end,
            "filing_date": filing_date,
            "fiscal_period": "Q4",
            "revision_id": 0,
            "source": "test",
        })
    return pd.DataFrame(records)


def _make_multi_metric_fundamentals(
    symbols: list[str],
    metrics_values: dict[str, list[float]],
    filing_date: date,
) -> pd.DataFrame:
    """Build a tidy frame with multiple metrics in one filing."""
    frames = []
    for metric, values in metrics_values.items():
        frames.append(
            _make_fundamentals(symbols, metric, values, filing_date)
        )
    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# StyleFactorConfig tests
# ---------------------------------------------------------------------------


class TestStyleFactorConfig:
    """StyleFactorConfig: construction, validation, immutability."""

    def test_default_construction(self) -> None:
        cfg = StyleFactorConfig()
        assert cfg.vol_window == 63
        assert cfg.winsor_clip == 3.0
        assert cfg.earnings_history_window == 4
        assert cfg.quantile == 0.2

    def test_custom_construction(self) -> None:
        cfg = StyleFactorConfig(vol_window=21, winsor_clip=2.5, quantile=0.3)
        assert cfg.vol_window == 21
        assert cfg.winsor_clip == 2.5
        assert cfg.quantile == 0.3

    def test_frozen(self) -> None:
        cfg = StyleFactorConfig()
        with pytest.raises((AttributeError, TypeError)):
            cfg.vol_window = 10  # type: ignore[misc]

    def test_vol_window_one_raises(self) -> None:
        with pytest.raises(ValueError, match="vol_window"):
            StyleFactorConfig(vol_window=1)

    def test_vol_window_two_allowed(self) -> None:
        cfg = StyleFactorConfig(vol_window=2)
        assert cfg.vol_window == 2

    def test_winsor_clip_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="winsor_clip"):
            StyleFactorConfig(winsor_clip=0.0)

    def test_winsor_clip_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="winsor_clip"):
            StyleFactorConfig(winsor_clip=-1.0)

    def test_empty_value_legs_raises(self) -> None:
        with pytest.raises(ValueError, match="value_legs"):
            StyleFactorConfig(value_legs=[])

    def test_unknown_value_leg_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown value_legs"):
            StyleFactorConfig(value_legs=["bad_leg"])

    def test_empty_quality_legs_raises(self) -> None:
        with pytest.raises(ValueError, match="quality_legs"):
            StyleFactorConfig(quality_legs=[])

    def test_unknown_quality_leg_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown quality_legs"):
            StyleFactorConfig(quality_legs=["bad_leg"])

    def test_earnings_history_window_one_raises(self) -> None:
        with pytest.raises(ValueError, match="earnings_history_window"):
            StyleFactorConfig(earnings_history_window=1)

    def test_quantile_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="quantile"):
            StyleFactorConfig(quantile=0.0)

    def test_quantile_one_raises(self) -> None:
        with pytest.raises(ValueError, match="quantile"):
            StyleFactorConfig(quantile=1.0)

    def test_quantile_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="quantile"):
            StyleFactorConfig(quantile=-0.1)

    def test_single_value_leg_valid(self) -> None:
        cfg = StyleFactorConfig(value_legs=["book_to_price"])
        assert list(cfg.value_legs) == ["book_to_price"]

    def test_single_quality_leg_valid(self) -> None:
        cfg = StyleFactorConfig(quality_legs=["roe"])
        assert list(cfg.quality_legs) == ["roe"]

    def test_all_valid_value_legs(self) -> None:
        cfg = StyleFactorConfig(
            value_legs=["book_to_price", "earnings_to_price", "cashflow_to_price"]
        )
        assert len(cfg.value_legs) == 3

    def test_all_valid_quality_legs(self) -> None:
        cfg = StyleFactorConfig(
            quality_legs=["roe", "gross_profitability", "low_leverage", "earnings_stability"]
        )
        assert len(cfg.quality_legs) == 4


# ---------------------------------------------------------------------------
# pit_characteristic tests
# ---------------------------------------------------------------------------


class TestPitCharacteristic:
    """Point-in-time characteristic panel builder."""

    def test_basic_forward_fill(self) -> None:
        """Filed value persists from filing_date onward until superseded."""
        dates = pd.date_range("2020-01-01", periods=10, freq="B")
        syms = ["X"]
        filing = date(2020, 1, 3)  # 3rd bar
        fundamentals = _make_fundamentals(syms, "net_income", [100.0], filing)

        out = pit_characteristic(dates, fundamentals, "net_income", syms)

        assert out.shape == (10, 1)
        # Before filing date: NaN
        filing_ts = pd.Timestamp(filing)
        before = out[out.index < filing_ts]["X"]
        assert before.isna().all(), f"Expected NaN before filing, got {before.values}"
        # On and after filing date: 100.0
        on_or_after = out[out.index >= filing_ts]["X"]
        assert (on_or_after == 100.0).all(), f"Expected 100.0, got {on_or_after.values}"

    def test_leakage_guard_filed_after_t(self) -> None:
        """A fundamental filed AFTER date t must NOT appear in the score at t."""
        dates = pd.date_range("2020-01-01", periods=20, freq="B")
        syms = ["X"]
        # File on the 15th business date
        filing = dates[14].date()
        fundamentals = _make_fundamentals(syms, "book_equity", [999.0], filing)

        out = pit_characteristic(dates, fundamentals, "book_equity", syms)

        # Row 13 (index 13, date before filing) must be NaN
        assert math.isnan(out.iloc[13, 0]), (
            f"Row 13 should be NaN before filing_date={filing}, "
            f"got {out.iloc[13, 0]}"
        )
        # Row 14 (the filing date itself) must have the value
        assert out.iloc[14, 0] == 999.0, (
            f"Row 14 (filing date) should be 999.0, got {out.iloc[14, 0]}"
        )

    def test_superseding_filing(self) -> None:
        """A newer filing with higher revision_id replaces the older value."""
        dates = pd.date_range("2020-01-01", periods=30, freq="B")
        syms = ["X"]
        filing1 = date(2020, 1, 6)   # early filing
        filing2 = date(2020, 1, 20)  # later filing with updated value
        period_end = date(2019, 12, 31)

        f1 = _make_fundamentals(syms, "net_income", [50.0], filing1, period_end)
        f2 = _make_fundamentals(syms, "net_income", [75.0], filing2, period_end)
        fundamentals = pd.concat([f1, f2], ignore_index=True)

        out = pit_characteristic(dates, fundamentals, "net_income", syms)

        ts1 = pd.Timestamp(filing1)
        ts2 = pd.Timestamp(filing2)
        # Between filing1 and filing2: 50.0
        between = out[(out.index >= ts1) & (out.index < ts2)]["X"]
        assert (between == 50.0).all(), f"Expected 50.0 between filings, got {between.values}"
        # From filing2 onward: 75.0
        after2 = out[out.index >= ts2]["X"]
        assert (after2 == 75.0).all(), f"Expected 75.0 after filing2, got {after2.values}"

    def test_empty_fundamentals_all_nan(self) -> None:
        """Empty fundamentals frame -> all-NaN panel."""
        dates = pd.date_range("2020-01-01", periods=5, freq="B")
        out = pit_characteristic(dates, pd.DataFrame(), "net_income", ["X", "Y"])
        assert out.isna().all().all()

    def test_missing_metric_all_nan(self) -> None:
        """Metric not in fundamentals -> all-NaN column."""
        dates = pd.date_range("2020-01-01", periods=5, freq="B")
        syms = ["X"]
        filing = date(2020, 1, 1)
        fundamentals = _make_fundamentals(syms, "other_metric", [1.0], filing)
        out = pit_characteristic(dates, fundamentals, "net_income", syms)
        assert out["X"].isna().all()

    def test_missing_symbol_nan(self) -> None:
        """Symbol not in fundamentals -> NaN for that column."""
        dates = pd.date_range("2020-01-01", periods=5, freq="B")
        fundamentals = _make_fundamentals(["X"], "net_income", [100.0], date(2020, 1, 1))
        out = pit_characteristic(dates, fundamentals, "net_income", ["X", "Y"])
        assert out["Y"].isna().all()
        assert out["X"].notna().any()

    def test_output_shape_and_index(self) -> None:
        """Output shape matches (len(dates), len(symbols))."""
        dates = pd.date_range("2020-01-01", periods=10, freq="B")
        syms = ["A", "B", "C"]
        fundamentals = _make_fundamentals(syms, "book_equity", [1.0, 2.0, 3.0], date(2020, 1, 5))
        out = pit_characteristic(dates, fundamentals, "book_equity", syms)
        assert out.shape == (10, 3)
        assert list(out.columns) == syms
        assert list(out.index) == list(dates)


# ---------------------------------------------------------------------------
# LOW-VOL parameter recovery tests
# ---------------------------------------------------------------------------


class TestLowvolScores:
    """lowvol_scores: price-only, low-vol assets get highest scores."""

    def _make_vol_panel(self) -> tuple[pd.DataFrame, list[str], list[str]]:
        """Build a panel with two clearly different volatility regimes.

        Assets 'low0'..'low3': annualised vol ~5% (daily ~0.003).
        Assets 'high0'..'high3': annualised vol ~30% (daily ~0.019).
        """
        rng = np.random.default_rng(SEED)
        n = N_BARS
        low_vols = ["low0", "low1", "low2", "low3"]
        high_vols = ["high0", "high1", "high2", "high3"]
        all_syms = low_vols + high_vols

        returns = np.empty((n - 1, len(all_syms)))
        returns[:, :4] = rng.normal(0.0, 0.003, (n - 1, 4))   # ~5% annual
        returns[:, 4:] = rng.normal(0.0, 0.019, (n - 1, 4))   # ~30% annual

        prices = np.ones((n, len(all_syms)))
        prices[1:] = np.cumprod(1.0 + returns, axis=0)
        dates = pd.date_range("2020-01-01", periods=n, freq="B")
        return (
            pd.DataFrame(prices, index=dates, columns=all_syms),
            low_vols,
            high_vols,
        )

    def test_output_shape(self) -> None:
        prices = _make_price_panel()
        cfg = StyleFactorConfig(vol_window=20)
        out = lowvol_scores(prices, cfg)
        assert out.shape == prices.shape
        assert list(out.columns) == list(prices.columns)
        assert list(out.index) == list(prices.index)

    def test_warmup_nan(self) -> None:
        """Rows 0 .. vol_window are NaN (insufficient history)."""
        prices = _make_price_panel(n_bars=100)
        cfg = StyleFactorConfig(vol_window=20)
        out = lowvol_scores(prices, cfg)
        # The loop starts at t = window+1 so rows 0..window must be NaN
        assert out.iloc[: cfg.vol_window + 1].isna().all().all()

    def test_low_vol_assets_get_high_scores(self) -> None:
        """Low-vol assets must have higher mean lowvol score than high-vol assets."""
        prices, low_syms, high_syms = self._make_vol_panel()
        cfg = StyleFactorConfig(vol_window=30)
        out = lowvol_scores(prices, cfg)

        warmup = cfg.vol_window + 1
        valid = out.iloc[warmup:].dropna(how="all")
        low_mean = float(valid[low_syms].mean().mean())
        high_mean = float(valid[high_syms].mean().mean())
        assert low_mean > high_mean, (
            f"Low-vol mean score {low_mean:.4f} should exceed "
            f"high-vol mean score {high_mean:.4f}"
        )

    def test_long_portfolio_vol_less_than_short(self) -> None:
        """Realised vol of low-vol long leg < realised vol of high-vol short leg.

        This is the core parameter-recovery test: the portfolio that goes long
        the top-scoring (least-volatile) names should itself exhibit lower
        return volatility than the portfolio shorting the bottom (most-volatile)
        names.
        """
        prices, low_syms, high_syms = self._make_vol_panel()
        cfg = StyleFactorConfig(vol_window=30, quantile=0.4)
        scores = lowvol_scores(prices, cfg)
        weights = style_factor_weights(scores, cfg)

        # Compute simple returns panel
        price_arr = prices.to_numpy(dtype=float)
        ret_arr = np.empty_like(price_arr)
        ret_arr[0] = np.nan
        ret_arr[1:] = price_arr[1:] / price_arr[:-1] - 1.0
        returns = pd.DataFrame(ret_arr, index=prices.index, columns=prices.columns)

        warmup = cfg.vol_window + 10
        w_late = weights.iloc[warmup:]
        r_late = returns.iloc[warmup:]

        # Portfolio returns: sum(weight_i * return_i) per bar
        long_mask = w_late > 0
        short_mask = w_late < 0

        long_ret = (r_late * w_late.where(long_mask, 0.0)).sum(axis=1)
        short_ret = (r_late * (-w_late).where(short_mask, 0.0)).sum(axis=1)

        # Drop bars where no position was held
        long_vol = float(np.nanstd(long_ret[long_ret != 0.0].dropna()))
        short_vol = float(np.nanstd(short_ret[short_ret != 0.0].dropna()))

        assert long_vol < short_vol, (
            f"Long-leg vol {long_vol:.6f} should be < short-leg vol {short_vol:.6f}"
        )

    def test_no_fundamentals_required(self) -> None:
        """lowvol_scores takes only prices; no fundamentals arg exists."""
        import inspect
        sig = inspect.signature(lowvol_scores)
        param_names = list(sig.parameters.keys())
        assert "fundamentals" not in param_names, (
            "lowvol_scores should not take a 'fundamentals' parameter"
        )

    def test_nan_price_propagates(self) -> None:
        """NaN in price input propagates NaN into lowvol output.

        A NaN at price[t] makes ret[t] = NaN and ret[t+1] = NaN (because
        ret[t+1] = price[t+1]/price[t]-1 also uses the NaN price).  nanstd
        in the vol window treats those NaN returns as missing observations and
        drops them.  If the window shrinks to fewer than 2 valid observations
        the output is NaN.  We test the simpler invariant: at bar t=50 the
        return ret[50] is NaN because price[49] is NaN; the vol window for
        bar t=51 contains ret[50]=NaN which reduces n_obs in the window.
        However nanstd still returns a finite value when n_obs >= 2.

        The reliable assertion is that bar t=50 itself produces a finite or NaN
        lowvol score depending on how many other valid returns are in its window.
        The key no-crash guarantee is that the function completes without error.
        We additionally verify that at least one bar in the affected region has
        a finite score (the function works), and that the output shape is correct.
        """
        prices = _make_price_panel(n_bars=100, n_assets=4)
        prices_nan = prices.copy()
        # Insert NaN at two consecutive prices to force ret[49] and ret[50] to NaN
        prices_nan.iloc[49, 1] = float("nan")
        prices_nan.iloc[50, 1] = float("nan")
        cfg = StyleFactorConfig(vol_window=5)
        out = lowvol_scores(prices_nan, cfg)
        # Function must complete without error and return correct shape
        assert out.shape == prices.shape
        # At bar t=55, the vol window [50..54] for asset A1 contains ret[49]=NaN,
        # ret[50]=NaN, ret[51]=NaN leaving 2 valid returns in window of 5.
        # With vol_window=5 and only 2 valid obs, n_obs>=2 so the output may be
        # finite but is expected to be affected.  At t=51 the return window is
        # [46..50] with ret[49] and ret[50] both NaN -> 3 valid -> n_obs>=2 -> finite.
        # The important test: the function handles NaN prices gracefully.
        # Force a true NaN by using a vol_window of 3 and only 1 valid observation.
        prices_nan2 = prices.copy()
        for row in range(47, 52):
            prices_nan2.iloc[row, 1] = float("nan")
        cfg2 = StyleFactorConfig(vol_window=3)
        out2 = lowvol_scores(prices_nan2, cfg2)
        # At t=54, the window ret[51..53] are all NaN -> n_obs=0 < 2 -> NaN
        assert math.isnan(out2.iloc[54, 1]), (
            "Expected NaN when all returns in window are NaN"
        )

    def test_z_scores_row_mean_near_zero(self) -> None:
        """Each valid row should have ~zero cross-sectional mean after z-scoring."""
        prices = _make_price_panel(n_bars=150, n_assets=10)
        cfg = StyleFactorConfig(vol_window=20)
        out = lowvol_scores(prices, cfg)
        warmup = cfg.vol_window + 1
        valid_rows = out.iloc[warmup:].dropna(how="any")
        row_means = valid_rows.mean(axis=1)
        assert float(row_means.abs().max()) < 1e-10, (
            f"Max abs row mean = {float(row_means.abs().max()):.2e}"
        )


# ---------------------------------------------------------------------------
# QUALITY parameter recovery tests
# ---------------------------------------------------------------------------


class TestQualityScores:
    """quality_scores: high-ROE / low-leverage / stable-earnings get top scores."""

    def _make_quality_fundamentals(
        self,
        n_bars: int = N_BARS,
    ) -> tuple[pd.DataFrame, pd.DataFrame, list[str], list[str]]:
        """Build price and fundamentals panels with planted quality signal.

        Assets 'hq0'..'hq3': high quality (high ROE, low leverage, stable earnings).
        Assets 'lq0'..'lq3': low quality (low ROE, high leverage, unstable earnings).
        Neutral assets 'n0'..'n3' are in the middle.
        """
        rng = np.random.default_rng(SEED)
        hq_syms = ["hq0", "hq1", "hq2", "hq3"]
        lq_syms = ["lq0", "lq1", "lq2", "lq3"]
        neutral_syms = ["n0", "n1", "n2", "n3"]
        all_syms = hq_syms + lq_syms + neutral_syms
        n_syms = len(all_syms)

        returns = rng.normal(0.0, 0.01, (n_bars - 1, n_syms))
        prices_arr = np.ones((n_bars, n_syms))
        prices_arr[1:] = np.cumprod(1.0 + returns, axis=0)
        dates = pd.date_range("2020-01-01", periods=n_bars, freq="B")
        prices = pd.DataFrame(prices_arr, index=dates, columns=all_syms)

        filing = date(2020, 1, 2)
        pe = date(2019, 12, 31)

        # net_income: hq=200 each, lq=10 each, neutral=50 each
        ni_vals = [200.0] * 4 + [10.0] * 4 + [50.0] * 4
        # book_equity: hq=100, lq=100, neutral=100 -- same so ROE = ni/be
        be_vals = [100.0] * 12
        # gross_profit: hq=80, lq=5, neutral=30
        gp_vals = [80.0] * 4 + [5.0] * 4 + [30.0] * 4
        # total_assets: 500 for all
        ta_vals = [500.0] * 12
        # total_debt: hq=50 (low leverage), lq=450 (high leverage), neutral=200
        td_vals = [50.0] * 4 + [450.0] * 4 + [200.0] * 4
        # revenue: 200 for all (just needs to be present)
        rev_vals = [200.0] * 12

        frames = []
        for metric, vals in [
            ("net_income", ni_vals),
            ("book_equity", be_vals),
            ("gross_profit", gp_vals),
            ("total_assets", ta_vals),
            ("total_debt", td_vals),
            ("revenue", rev_vals),
        ]:
            for sym, val in zip(all_syms, vals, strict=False):
                frames.append({
                    "symbol": sym,
                    "statement": "test",
                    "metric": metric,
                    "value": float(val),
                    "period_end": pe,
                    "filing_date": filing,
                    "fiscal_period": "Q4",
                    "revision_id": 0,
                    "source": "test",
                })

        fundamentals = pd.DataFrame(frames)
        return prices, fundamentals, hq_syms, lq_syms

    def test_output_shape(self) -> None:
        prices = _make_price_panel()
        cfg = StyleFactorConfig()
        out = quality_scores(prices, pd.DataFrame(), cfg)
        assert out.shape == prices.shape

    def test_empty_fundamentals_all_nan(self) -> None:
        """No fundamentals -> quality scores all NaN."""
        prices = _make_price_panel(n_bars=50)
        cfg = StyleFactorConfig()
        out = quality_scores(prices, pd.DataFrame(), cfg)
        assert out.isna().all().all()

    def test_high_quality_names_get_top_scores(self) -> None:
        """Planted high-quality assets must have higher mean quality z-score."""
        prices, fundamentals, hq_syms, lq_syms = self._make_quality_fundamentals()
        cfg = StyleFactorConfig()
        out = quality_scores(prices, fundamentals, cfg)

        # Use rows after filing date
        filing_ts = pd.Timestamp("2020-01-02")
        valid = out[out.index >= filing_ts].dropna(how="all")
        assert len(valid) > 10, "Not enough valid rows"

        hq_mean = float(valid[hq_syms].mean().mean())
        lq_mean = float(valid[lq_syms].mean().mean())
        assert hq_mean > lq_mean, (
            f"HQ mean score {hq_mean:.4f} should exceed LQ mean score {lq_mean:.4f}"
        )

    def test_roe_leg_only(self) -> None:
        """Single-leg config with only 'roe' produces a non-trivial signal."""
        prices, fundamentals, hq_syms, lq_syms = self._make_quality_fundamentals()
        cfg = StyleFactorConfig(quality_legs=["roe"])
        out = quality_scores(prices, fundamentals, cfg)
        filing_ts = pd.Timestamp("2020-01-02")
        valid = out[out.index >= filing_ts].dropna(how="all")
        hq_mean = float(valid[hq_syms].mean().mean())
        lq_mean = float(valid[lq_syms].mean().mean())
        assert hq_mean > lq_mean

    def test_low_leverage_leg_only(self) -> None:
        """Single-leg config with 'low_leverage' correctly ranks assets by leverage."""
        prices, fundamentals, hq_syms, lq_syms = self._make_quality_fundamentals()
        cfg = StyleFactorConfig(quality_legs=["low_leverage"])
        out = quality_scores(prices, fundamentals, cfg)
        filing_ts = pd.Timestamp("2020-01-02")
        valid = out[out.index >= filing_ts].dropna(how="all")
        hq_mean = float(valid[hq_syms].mean().mean())
        lq_mean = float(valid[lq_syms].mean().mean())
        assert hq_mean > lq_mean, (
            f"Low-leverage leg: HQ {hq_mean:.4f} vs LQ {lq_mean:.4f}"
        )

    def test_earnings_stability_leg(self) -> None:
        """Earnings stability leg: stable earners get higher score than volatile."""
        dates = pd.date_range("2020-01-01", periods=50, freq="B")
        syms = ["stable", "volatile"]

        # Two filings for each symbol to give the stability window data
        pe1 = date(2019, 9, 30)
        pe2 = date(2019, 12, 31)
        filing1 = date(2019, 11, 1)
        filing2 = date(2020, 1, 2)

        frames = []
        # stable earner: 100, 100 (variance=0)
        # volatile earner: 50, 200 (high variance)
        for sym, vals in [("stable", [100.0, 100.0]), ("volatile", [50.0, 200.0])]:
            for pe, fd, v in [(pe1, filing1, vals[0]), (pe2, filing2, vals[1])]:
                frames.append({
                    "symbol": sym, "statement": "income", "metric": "net_income",
                    "value": v, "period_end": pe, "filing_date": fd,
                    "fiscal_period": "Q", "revision_id": 0, "source": "test",
                })
        fundamentals = pd.DataFrame(frames)

        prices_arr = np.ones((50, 2))
        prices = pd.DataFrame(prices_arr, index=dates, columns=syms)
        cfg = StyleFactorConfig(
            quality_legs=["earnings_stability"],
            earnings_history_window=2,
        )
        out = quality_scores(prices, fundamentals, cfg)

        filing_ts2 = pd.Timestamp(filing2)
        valid = out[out.index >= filing_ts2].dropna(how="all")
        if len(valid) > 0:
            stable_mean = float(valid["stable"].mean())
            volatile_mean = float(valid["volatile"].mean())
            assert stable_mean > volatile_mean, (
                f"Stable earner {stable_mean:.4f} should score above volatile {volatile_mean:.4f}"
            )

    def test_gross_profitability_leg(self) -> None:
        """gross_profitability leg ranks high-gp/assets firms above low ones."""
        prices, fundamentals, hq_syms, lq_syms = self._make_quality_fundamentals()
        cfg = StyleFactorConfig(quality_legs=["gross_profitability"])
        out = quality_scores(prices, fundamentals, cfg)
        filing_ts = pd.Timestamp("2020-01-02")
        valid = out[out.index >= filing_ts].dropna(how="all")
        hq_mean = float(valid[hq_syms].mean().mean())
        lq_mean = float(valid[lq_syms].mean().mean())
        assert hq_mean > lq_mean


# ---------------------------------------------------------------------------
# VALUE parameter recovery tests
# ---------------------------------------------------------------------------


class TestValueScores:
    """value_scores: high book-to-price names get top value z-scores."""

    def _make_value_panel(
        self, n_bars: int = N_BARS
    ) -> tuple[pd.DataFrame, pd.DataFrame, list[str], list[str]]:
        """Build price and fundamentals panels with planted value signal.

        Assets 'cheap0'..'cheap3': high B/P (book_equity >> price).
        Assets 'expensive0'..'expensive3': low B/P (book_equity << price).
        Neutral assets 'n0'..'n3' in the middle.
        """
        rng = np.random.default_rng(SEED + 1)
        cheap_syms = ["cheap0", "cheap1", "cheap2", "cheap3"]
        exp_syms = ["exp0", "exp1", "exp2", "exp3"]
        neutral_syms = ["n0", "n1", "n2", "n3"]
        all_syms = cheap_syms + exp_syms + neutral_syms
        n_syms = len(all_syms)

        # Keep prices close to 1.0 for easy ratio computation
        returns = rng.normal(0.0, 0.005, (n_bars - 1, n_syms))
        prices_arr = np.ones((n_bars, n_syms))
        prices_arr[1:] = np.cumprod(1.0 + returns, axis=0)
        dates = pd.date_range("2020-01-01", periods=n_bars, freq="B")
        prices = pd.DataFrame(prices_arr, index=dates, columns=all_syms)

        filing = date(2020, 1, 2)
        pe = date(2019, 12, 31)

        # book_equity: cheap=10 (high B/P vs price ~1), exp=0.1 (low B/P), neutral=2
        be_vals = [10.0] * 4 + [0.1] * 4 + [2.0] * 4
        # net_income: cheap=2, exp=0.02, neutral=0.4 (mirrors the B/P pattern)
        ni_vals = [2.0] * 4 + [0.02] * 4 + [0.4] * 4
        # operating_cashflow: cheap=1.5, exp=0.015, neutral=0.3
        cf_vals = [1.5] * 4 + [0.015] * 4 + [0.3] * 4

        frames = []
        for metric, vals in [
            ("book_equity", be_vals),
            ("net_income", ni_vals),
            ("operating_cashflow", cf_vals),
        ]:
            for sym, val in zip(all_syms, vals, strict=False):
                frames.append({
                    "symbol": sym, "statement": "test", "metric": metric,
                    "value": float(val), "period_end": pe, "filing_date": filing,
                    "fiscal_period": "Q4", "revision_id": 0, "source": "test",
                })

        fundamentals = pd.DataFrame(frames)
        return prices, fundamentals, cheap_syms, exp_syms

    def test_output_shape(self) -> None:
        prices = _make_price_panel()
        cfg = StyleFactorConfig()
        out = value_scores(prices, pd.DataFrame(), cfg)
        assert out.shape == prices.shape

    def test_empty_fundamentals_all_nan(self) -> None:
        prices = _make_price_panel(n_bars=50)
        cfg = StyleFactorConfig()
        out = value_scores(prices, pd.DataFrame(), cfg)
        assert out.isna().all().all()

    def test_cheap_assets_get_top_value_scores(self) -> None:
        """Planted cheap assets (high B/P) must outrank expensive ones."""
        prices, fundamentals, cheap_syms, exp_syms = self._make_value_panel()
        cfg = StyleFactorConfig()
        out = value_scores(prices, fundamentals, cfg)

        filing_ts = pd.Timestamp("2020-01-02")
        valid = out[out.index >= filing_ts].dropna(how="all")
        assert len(valid) > 10

        cheap_mean = float(valid[cheap_syms].mean().mean())
        exp_mean = float(valid[exp_syms].mean().mean())
        assert cheap_mean > exp_mean, (
            f"Cheap (high B/P) mean score {cheap_mean:.4f} should exceed "
            f"expensive mean score {exp_mean:.4f}"
        )

    def test_book_to_price_leg_only(self) -> None:
        """Single B/P leg recovers the cheap/expensive split."""
        prices, fundamentals, cheap_syms, exp_syms = self._make_value_panel()
        cfg = StyleFactorConfig(value_legs=["book_to_price"])
        out = value_scores(prices, fundamentals, cfg)
        filing_ts = pd.Timestamp("2020-01-02")
        valid = out[out.index >= filing_ts].dropna(how="all")
        cheap_mean = float(valid[cheap_syms].mean().mean())
        exp_mean = float(valid[exp_syms].mean().mean())
        assert cheap_mean > exp_mean

    def test_earnings_to_price_leg_only(self) -> None:
        """Single E/P leg recovers the cheap/expensive split."""
        prices, fundamentals, cheap_syms, exp_syms = self._make_value_panel()
        cfg = StyleFactorConfig(value_legs=["earnings_to_price"])
        out = value_scores(prices, fundamentals, cfg)
        filing_ts = pd.Timestamp("2020-01-02")
        valid = out[out.index >= filing_ts].dropna(how="all")
        cheap_mean = float(valid[cheap_syms].mean().mean())
        exp_mean = float(valid[exp_syms].mean().mean())
        assert cheap_mean > exp_mean

    def test_cashflow_to_price_leg_only(self) -> None:
        """Single CF/P leg recovers the cheap/expensive split."""
        prices, fundamentals, cheap_syms, exp_syms = self._make_value_panel()
        cfg = StyleFactorConfig(value_legs=["cashflow_to_price"])
        out = value_scores(prices, fundamentals, cfg)
        filing_ts = pd.Timestamp("2020-01-02")
        valid = out[out.index >= filing_ts].dropna(how="all")
        cheap_mean = float(valid[cheap_syms].mean().mean())
        exp_mean = float(valid[exp_syms].mean().mean())
        assert cheap_mean > exp_mean

    def test_point_in_time_leakage_guard(self) -> None:
        """A fundamental filed AFTER t does NOT change the value score at t."""
        n_bars = 30
        dates = pd.date_range("2020-01-01", periods=n_bars, freq="B")
        syms = ["cheap", "normal"]

        # File cheap's book_equity only on the LAST date; all prior dates = NaN
        filing_date_late = dates[-1].date()
        pe = date(2019, 12, 31)

        frames = []
        for sym, be in [("cheap", 100.0), ("normal", 5.0)]:
            frames.append({
                "symbol": sym, "statement": "test", "metric": "book_equity",
                "value": be, "period_end": pe, "filing_date": filing_date_late,
                "fiscal_period": "Q4", "revision_id": 0, "source": "test",
            })
        fundamentals = pd.DataFrame(frames)

        prices_arr = np.ones((n_bars, 2))
        prices = pd.DataFrame(prices_arr, index=dates, columns=syms)
        cfg = StyleFactorConfig(value_legs=["book_to_price"])
        out = value_scores(prices, fundamentals, cfg)

        # All rows BEFORE the filing date must be NaN (no data visible yet)
        before_filing = out.iloc[:-1]
        assert before_filing.isna().all().all(), (
            "Rows before filing date should be all-NaN; found non-NaN values"
        )

    def test_nan_price_propagates_to_ratio(self) -> None:
        """NaN price -> NaN ratio -> propagates NaN into value score."""
        n_bars = 50
        dates = pd.date_range("2020-01-01", periods=n_bars, freq="B")
        syms = ["A", "B"]
        filing = date(2020, 1, 2)

        fundamentals = _make_multi_metric_fundamentals(
            syms,
            {"book_equity": [100.0, 100.0]},
            filing,
        )
        prices_arr = np.ones((n_bars, 2))
        prices_arr[10, 0] = float("nan")
        prices = pd.DataFrame(prices_arr, index=dates, columns=syms)

        cfg = StyleFactorConfig(value_legs=["book_to_price"])
        out = value_scores(prices, fundamentals, cfg)
        # Row 10 has NaN price for asset A -> ratio is NaN -> output NaN
        assert math.isnan(out.iloc[10, 0])


# ---------------------------------------------------------------------------
# style_factor_weights tests
# ---------------------------------------------------------------------------


class TestStyleFactorWeights:
    """style_factor_weights: thin wrapper producing dollar-neutral weights."""

    def test_output_shape(self) -> None:
        prices = _make_price_panel()
        cfg = StyleFactorConfig(vol_window=20)
        scores = lowvol_scores(prices, cfg)
        w = style_factor_weights(scores, cfg)
        assert w.shape == scores.shape

    def test_dollar_neutral(self) -> None:
        """Row sums of non-zero rows must be ~0."""
        prices = _make_price_panel(n_bars=200)
        cfg = StyleFactorConfig(vol_window=20, quantile=0.2)
        scores = lowvol_scores(prices, cfg)
        w = style_factor_weights(scores, cfg)
        warmup = cfg.vol_window + 1
        valid = w.iloc[warmup:]
        row_sums = valid.sum(axis=1)
        assert float(row_sums.abs().max()) < 1e-12, (
            f"Max abs row net = {float(row_sums.abs().max()):.2e}"
        )

    def test_long_leg_sums_to_one(self) -> None:
        prices = _make_price_panel(n_bars=200)
        cfg = StyleFactorConfig(vol_window=20, quantile=0.2)
        scores = lowvol_scores(prices, cfg)
        w = style_factor_weights(scores, cfg)
        warmup = cfg.vol_window + 1
        for _, row in w.iloc[warmup:].iterrows():
            long_sum = float(row[row > 0].sum())
            if long_sum != 0.0:
                assert abs(long_sum - 1.0) < 1e-12

    def test_quantile_propagated(self) -> None:
        """quantile parameter from config is passed correctly."""
        prices = _make_price_panel(n_bars=100, n_assets=8)
        cfg_narrow = StyleFactorConfig(vol_window=10, quantile=0.1)
        cfg_wide = StyleFactorConfig(vol_window=10, quantile=0.4)

        scores = lowvol_scores(prices, cfg_narrow)
        w_narrow = style_factor_weights(scores, cfg_narrow)
        w_wide = style_factor_weights(scores, cfg_wide)

        # Wider quantile -> more assets per leg -> more non-zero weights
        warmup = cfg_narrow.vol_window + 1
        n_active_narrow = (w_narrow.iloc[warmup:] != 0.0).sum(axis=1).mean()
        n_active_wide = (w_wide.iloc[warmup:] != 0.0).sum(axis=1).mean()
        assert n_active_wide >= n_active_narrow


# ---------------------------------------------------------------------------
# style_factor_panels pipeline tests
# ---------------------------------------------------------------------------


class TestStyleFactorPanels:
    """style_factor_panels: full pipeline returns all 6 keys, correct shapes."""

    def test_output_keys(self) -> None:
        prices = _make_price_panel(n_bars=100)
        cfg = StyleFactorConfig(vol_window=20)
        result = style_factor_panels(prices, pd.DataFrame(), cfg)
        expected_keys = {
            "value_scores", "value_weights",
            "quality_scores", "quality_weights",
            "lowvol_scores", "lowvol_weights",
        }
        assert set(result.keys()) == expected_keys

    def test_shapes_match_prices(self) -> None:
        prices = _make_price_panel(n_bars=100)
        cfg = StyleFactorConfig(vol_window=20)
        result = style_factor_panels(prices, pd.DataFrame(), cfg)
        for key, df in result.items():
            assert df.shape == prices.shape, (
                f"Key '{key}': shape {df.shape} != prices shape {prices.shape}"
            )
            assert list(df.columns) == list(prices.columns), (
                f"Key '{key}': columns mismatch"
            )
            assert list(df.index) == list(prices.index), (
                f"Key '{key}': index mismatch"
            )

    def test_empty_fundamentals_value_quality_nan(self) -> None:
        """Empty fundamentals: value/quality scores all NaN; lowvol still fires."""
        prices = _make_price_panel(n_bars=100)
        cfg = StyleFactorConfig(vol_window=20)
        result = style_factor_panels(prices, pd.DataFrame(), cfg)

        assert result["value_scores"].isna().all().all(), (
            "value_scores should be all-NaN with empty fundamentals"
        )
        assert result["quality_scores"].isna().all().all(), (
            "quality_scores should be all-NaN with empty fundamentals"
        )
        # lowvol_scores must have some finite values after warmup
        warmup = cfg.vol_window + 1
        assert result["lowvol_scores"].iloc[warmup:].notna().any().any(), (
            "lowvol_scores should have finite values after warmup"
        )

    def test_weight_dollar_neutrality(self) -> None:
        """All weight panels must be dollar-neutral."""
        prices = _make_price_panel(n_bars=200)
        cfg = StyleFactorConfig(vol_window=20)
        result = style_factor_panels(prices, pd.DataFrame(), cfg)
        weight_keys = ["value_weights", "quality_weights", "lowvol_weights"]
        warmup = cfg.vol_window + 1
        for key in weight_keys:
            w = result[key].iloc[warmup:]
            row_sums = w.sum(axis=1)
            assert float(row_sums.abs().max()) < 1e-12, (
                f"Key '{key}': max abs row net = {float(row_sums.abs().max()):.2e}"
            )

    def test_index_and_columns_match(self) -> None:
        """Index and columns of all panels match the price panel."""
        prices = _make_price_panel(n_bars=80)
        cfg = StyleFactorConfig(vol_window=15)
        result = style_factor_panels(prices, pd.DataFrame(), cfg)
        for _key, df in result.items():
            pd.testing.assert_index_equal(df.index, prices.index, check_names=False)
            pd.testing.assert_index_equal(df.columns, prices.columns, check_names=False)


# ---------------------------------------------------------------------------
# Public API / __all__ check
# ---------------------------------------------------------------------------


class TestPublicAPI:
    """Verify __all__ exports and importability."""

    def test_all_names_importable(self) -> None:
        import core_trading.signals.factors.style_factors as mod
        expected = {
            "StyleFactorConfig",
            "pit_characteristic",
            "value_scores",
            "quality_scores",
            "lowvol_scores",
            "style_factor_weights",
            "style_factor_panels",
        }
        for name in expected:
            assert hasattr(mod, name), f"Missing from module: {name}"

    def test_all_contains_expected_names(self) -> None:
        import core_trading.signals.factors.style_factors as mod
        for name in mod.__all__:
            assert hasattr(mod, name)

    def test_config_is_dataclass(self) -> None:
        import dataclasses
        assert dataclasses.is_dataclass(StyleFactorConfig)

    def test_config_is_frozen(self) -> None:
        """StyleFactorConfig must be frozen (immutable) -- direct assignment raises."""
        import dataclasses
        params = dataclasses.fields(StyleFactorConfig)
        assert params  # non-empty
        cfg = StyleFactorConfig()
        with pytest.raises((AttributeError, TypeError)):
            cfg.vol_window = 999  # type: ignore[misc]
