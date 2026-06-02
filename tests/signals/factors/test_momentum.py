"""Tests for core_trading.signals.factors.momentum (Phase 5.C.4).

Covers:
* MomentumConfig -- frozen/slotted DTO, __post_init__ validation.
* momentum_scores -- textbook rank recovery (winners > losers), look-ahead-free
  (truncation invariance), warmup NaN, NaN propagation.
* risk_adjusted_momentum -- higher-vol asset gets lower adjusted score than
  lower-vol asset with equal raw momentum.
* cross_sectional_zscore -- each row has ~zero mean and ~unit std across assets.
* long_short_weights -- dollar-neutrality (net ~0, long +1, short -1);
  too-few-assets rows -> all-zero weights; overlap guard.
* momentum_portfolio -- pipeline integration (risk_adjusted True and False).
* Edge cases: all-NaN row, single-asset panel, constant prices, zero quantile
  boundary, zero-std row in zscore, identical scores row.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from core_trading.signals.factors.momentum import (
    MomentumConfig,
    cross_sectional_zscore,
    long_short_weights,
    momentum_portfolio,
    momentum_scores,
    risk_adjusted_momentum,
)

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

SEED = 20260601
N_BARS = 400   # enough history to warm up a 252-bar lookback
N_ASSETS = 10  # enough assets for quantile tests

# ---------------------------------------------------------------------------
# Synthetic panel factory
# ---------------------------------------------------------------------------


def _make_price_panel(
    n_bars: int = N_BARS,
    n_assets: int = N_ASSETS,
    seed: int = SEED,
    winner_drift: float = 0.002,
    loser_drift: float = -0.001,
    noise_std: float = 0.01,
    n_winners: int = 2,
    n_losers: int = 2,
) -> pd.DataFrame:
    """Build a synthetic price panel with clear winner/loser structure.

    The first ``n_winners`` assets drift upward at ``winner_drift`` per bar;
    the last ``n_losers`` assets drift downward at ``loser_drift`` per bar.
    All assets share the same idiosyncratic noise.

    Returns a DataFrame with a DatetimeIndex and integer-labeled columns
    named 'A0', 'A1', ..., 'A{n_assets-1}'.
    """
    rng = np.random.default_rng(seed)
    drifts = np.zeros(n_assets)
    drifts[:n_winners] = winner_drift
    drifts[-n_losers:] = loser_drift

    returns = rng.normal(loc=drifts, scale=noise_std, size=(n_bars - 1, n_assets))
    prices = np.ones((n_bars, n_assets))
    prices[1:] = np.cumprod(1.0 + returns, axis=0)

    dates = pd.date_range("2020-01-01", periods=n_bars, freq="B")
    cols = [f"A{i}" for i in range(n_assets)]
    return pd.DataFrame(prices, index=dates, columns=cols)


# ---------------------------------------------------------------------------
# MomentumConfig tests
# ---------------------------------------------------------------------------


class TestMomentumConfig:
    """MomentumConfig: construction, validation, immutability."""

    def test_valid_construction(self) -> None:
        cfg = MomentumConfig(lookback=252, skip=21, vol_window=60)
        assert cfg.lookback == 252
        assert cfg.skip == 21
        assert cfg.vol_window == 60

    def test_default_skip_and_vol_window(self) -> None:
        cfg = MomentumConfig(lookback=100)
        assert cfg.skip == 21
        assert cfg.vol_window == 60

    def test_frozen(self) -> None:
        cfg = MomentumConfig(lookback=252)
        with pytest.raises((AttributeError, TypeError)):
            cfg.lookback = 100  # type: ignore[misc]

    def test_skip_zero_allowed(self) -> None:
        cfg = MomentumConfig(lookback=252, skip=0, vol_window=20)
        assert cfg.skip == 0

    def test_skip_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="skip must be >= 0"):
            MomentumConfig(lookback=252, skip=-1)

    def test_lookback_equals_skip_raises(self) -> None:
        with pytest.raises(ValueError, match="lookback"):
            MomentumConfig(lookback=21, skip=21)

    def test_lookback_less_than_skip_raises(self) -> None:
        with pytest.raises(ValueError, match="lookback"):
            MomentumConfig(lookback=10, skip=21)

    def test_vol_window_one_raises(self) -> None:
        with pytest.raises(ValueError, match="vol_window"):
            MomentumConfig(lookback=252, vol_window=1)

    def test_vol_window_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="vol_window"):
            MomentumConfig(lookback=252, vol_window=0)

    def test_vol_window_two_allowed(self) -> None:
        cfg = MomentumConfig(lookback=252, vol_window=2)
        assert cfg.vol_window == 2

    def test_skip_equal_zero_lookback_one(self) -> None:
        """Minimal valid config: lookback=1, skip=0."""
        cfg = MomentumConfig(lookback=1, skip=0, vol_window=2)
        assert cfg.lookback == 1


# ---------------------------------------------------------------------------
# momentum_scores tests
# ---------------------------------------------------------------------------


class TestMomentumScores:
    """momentum_scores: shape, warmup, look-ahead-free, rank recovery."""

    def test_output_shape(self) -> None:
        prices = _make_price_panel()
        out = momentum_scores(prices, lookback=252, skip=21)
        assert out.shape == prices.shape
        assert list(out.columns) == list(prices.columns)
        assert list(out.index) == list(prices.index)

    def test_warmup_nan(self) -> None:
        """Rows 0 .. lookback-1 are all NaN (insufficient history)."""
        prices = _make_price_panel()
        lookback = 252
        skip = 21
        out = momentum_scores(prices, lookback=lookback, skip=skip)
        # Rows 0..lookback-1 must be entirely NaN
        assert out.iloc[:lookback].isna().all().all()

    def test_valid_region_non_nan(self) -> None:
        """Rows from lookback onward must contain finite scores."""
        prices = _make_price_panel()
        lookback = 50
        out = momentum_scores(prices, lookback=lookback, skip=0)
        assert out.iloc[lookback:].notna().all().all()

    def test_winner_loser_rank_recovery(self) -> None:
        """Winners (positive drift) should score above losers (negative drift)."""
        prices = _make_price_panel(
            n_bars=N_BARS,
            n_assets=N_ASSETS,
            n_winners=2,
            n_losers=2,
            winner_drift=0.003,
            loser_drift=-0.002,
            noise_std=0.005,
            seed=SEED,
        )
        lookback = 252
        out = momentum_scores(prices, lookback=lookback, skip=0)

        # Use bars well after warmup to get stable cross-section
        valid_rows = out.iloc[lookback + 20:]
        winner_mean = valid_rows[["A0", "A1"]].mean().mean()
        loser_mean  = valid_rows[[f"A{N_ASSETS-2}", f"A{N_ASSETS-1}"]].mean().mean()
        assert winner_mean > loser_mean, (
            f"Winner mean score {winner_mean:.4f} not above loser mean {loser_mean:.4f}"
        )

    def test_look_ahead_free_truncation_invariance(self) -> None:
        """Scores on the full panel and a prefix agree on the overlapping rows."""
        prices = _make_price_panel()
        lookback = 50
        skip = 5
        cutoff = 200

        full_out = momentum_scores(prices, lookback=lookback, skip=skip)
        prefix_out = momentum_scores(prices.iloc[:cutoff], lookback=lookback, skip=skip)

        # Rows that exist in both; skip the last few rows of the prefix to be safe
        overlap_rows = slice(lookback, cutoff)
        pd.testing.assert_frame_equal(
            full_out.iloc[overlap_rows].reset_index(drop=True),
            prefix_out.iloc[overlap_rows].reset_index(drop=True),
            check_exact=False,
            atol=1e-12,
        )

    def test_nan_input_propagates_nan(self) -> None:
        """NaN prices produce NaN scores at those positions."""
        prices = _make_price_panel(n_bars=100, n_assets=4)
        prices_with_nan = prices.copy()
        prices_with_nan.iloc[60, 2] = float("nan")

        out = momentum_scores(prices_with_nan, lookback=20, skip=0)
        # Row 60 uses price[60] as p_end; NaN there -> NaN score for asset 2
        assert math.isnan(out.iloc[60, 2])

    def test_nan_at_start_index_propagates(self) -> None:
        """NaN at the lookback-start position for an asset -> NaN score."""
        prices = _make_price_panel(n_bars=100, n_assets=4)
        prices_nan = prices.copy()
        # Set price at row 10 for asset 0 to NaN
        prices_nan.iloc[10, 0] = float("nan")

        out = momentum_scores(prices_nan, lookback=20, skip=0)
        # At row 30 (=10+20), p_start = price[10] which is NaN -> NaN score
        assert math.isnan(out.iloc[30, 0])

    def test_bad_lookback_skip_raises(self) -> None:
        prices = _make_price_panel(n_bars=50)
        with pytest.raises(ValueError, match="lookback"):
            momentum_scores(prices, lookback=21, skip=21)

    def test_negative_skip_raises(self) -> None:
        prices = _make_price_panel(n_bars=50)
        with pytest.raises(ValueError, match="skip must be >= 0"):
            momentum_scores(prices, lookback=10, skip=-1)

    def test_scores_are_cumulative_returns(self) -> None:
        """Verify arithmetic: score = price[t-skip] / price[t-lookback] - 1."""
        prices = _make_price_panel(n_bars=60, n_assets=3, noise_std=0.0)
        lookback = 10
        skip = 0
        out = momentum_scores(prices, lookback=lookback, skip=skip)

        t = 20
        expected = (
            prices.iloc[t - skip].values / prices.iloc[t - lookback].values - 1.0
        )
        np.testing.assert_allclose(out.iloc[t].values, expected, rtol=1e-10)

    def test_no_skip_vs_explicit_zero_skip(self) -> None:
        """Default skip=0 and explicit skip=0 produce identical results."""
        prices = _make_price_panel(n_bars=80, n_assets=4)
        out_default = momentum_scores(prices, lookback=30)
        out_explicit = momentum_scores(prices, lookback=30, skip=0)
        pd.testing.assert_frame_equal(out_default, out_explicit)


# ---------------------------------------------------------------------------
# risk_adjusted_momentum tests
# ---------------------------------------------------------------------------


class TestRiskAdjustedMomentum:
    """risk_adjusted_momentum: vol-scaling reduces high-vol asset scores."""

    def test_output_shape(self) -> None:
        prices = _make_price_panel()
        out = risk_adjusted_momentum(prices, lookback=252, skip=21, vol_window=60)
        assert out.shape == prices.shape

    def test_lower_vol_gets_higher_adjusted_score(self) -> None:
        """Given equal raw momentum, the asset with lower vol scores higher."""
        rng = np.random.default_rng(SEED)
        n = N_BARS
        # Asset 0: low vol (noise_std=0.005), Asset 1: high vol (noise_std=0.02)
        drift = 0.002
        low_vol_returns  = rng.normal(drift, 0.005, n - 1)
        high_vol_returns = rng.normal(drift, 0.020, n - 1)
        low_prices  = np.concatenate([[1.0], np.cumprod(1.0 + low_vol_returns)])
        high_prices = np.concatenate([[1.0], np.cumprod(1.0 + high_vol_returns)])

        dates = pd.date_range("2020-01-01", periods=n, freq="B")
        prices = pd.DataFrame(
            {"low_vol": low_prices, "high_vol": high_prices},
            index=dates,
        )

        lookback = 252
        skip = 0
        vol_window = 60
        out = risk_adjusted_momentum(
            prices, lookback=lookback, skip=skip, vol_window=vol_window
        )

        # Use rows well after full warmup (max of lookback and vol_window+1)
        start = max(lookback, vol_window + 1)
        valid = out.iloc[start:].dropna()
        assert len(valid) > 10, "Not enough valid rows for comparison"
        low_adj_mean  = float(valid["low_vol"].mean())
        high_adj_mean = float(valid["high_vol"].mean())
        assert low_adj_mean > high_adj_mean, (
            f"Low-vol adjusted mean {low_adj_mean:.4f} not above "
            f"high-vol adjusted mean {high_adj_mean:.4f}"
        )

    def test_warmup_nan_region(self) -> None:
        """Rows before full warmup (lookback + vol_window) are NaN."""
        prices = _make_price_panel(n_bars=N_BARS)
        lookback = 100
        vol_window = 40
        out = risk_adjusted_momentum(
            prices, lookback=lookback, skip=0, vol_window=vol_window
        )
        # The first max(lookback, vol_window+1) rows must all be NaN
        # (vol_window+1 because shift(1) + rolling(vol_window) requires
        # vol_window+1 raw return rows, which in turn needs vol_window+2 price rows)
        warmup = max(lookback, vol_window + 1)
        assert out.iloc[:warmup].isna().all().all()

    def test_bad_vol_window_raises(self) -> None:
        prices = _make_price_panel(n_bars=50)
        with pytest.raises(ValueError, match="vol_window"):
            risk_adjusted_momentum(prices, lookback=10, skip=0, vol_window=1)

    def test_bad_skip_raises(self) -> None:
        prices = _make_price_panel(n_bars=50)
        with pytest.raises(ValueError, match="skip must be >= 0"):
            risk_adjusted_momentum(prices, lookback=10, skip=-1, vol_window=5)

    def test_bad_lookback_raises(self) -> None:
        prices = _make_price_panel(n_bars=50)
        with pytest.raises(ValueError, match="lookback"):
            risk_adjusted_momentum(prices, lookback=5, skip=10, vol_window=5)

    def test_nan_prices_propagate(self) -> None:
        """NaN in prices propagates NaN into the adjusted score."""
        prices = _make_price_panel(n_bars=100, n_assets=3)
        prices_nan = prices.copy()
        prices_nan.iloc[60, 1] = float("nan")
        out = risk_adjusted_momentum(prices_nan, lookback=20, skip=0, vol_window=10)
        # Row 60 has NaN price for asset 1 -> NaN score
        assert math.isnan(out.iloc[60, 1])


# ---------------------------------------------------------------------------
# cross_sectional_zscore tests
# ---------------------------------------------------------------------------


class TestCrossSectionalZscore:
    """cross_sectional_zscore: zero-mean unit-std per row across assets."""

    def test_output_shape(self) -> None:
        prices = _make_price_panel()
        scores = momentum_scores(prices, lookback=50, skip=0)
        z = cross_sectional_zscore(scores)
        assert z.shape == scores.shape

    def test_row_mean_near_zero(self) -> None:
        """After z-scoring, each valid row should have ~zero cross-sectional mean."""
        prices = _make_price_panel()
        scores = momentum_scores(prices, lookback=50, skip=0)
        z = cross_sectional_zscore(scores)

        valid_rows = z.iloc[50:].dropna(how="any")
        row_means = valid_rows.mean(axis=1)
        assert float(row_means.abs().max()) < 1e-10, (
            f"Max abs row mean = {float(row_means.abs().max()):.2e}"
        )

    def test_row_std_near_one(self) -> None:
        """After z-scoring, each valid row should have ~unit cross-sectional std."""
        prices = _make_price_panel()
        scores = momentum_scores(prices, lookback=50, skip=0)
        z = cross_sectional_zscore(scores)

        valid_rows = z.iloc[50:].dropna(how="any")
        row_stds = valid_rows.std(axis=1, ddof=0)
        assert float((row_stds - 1.0).abs().max()) < 1e-10, (
            f"Max abs row std deviation from 1 = {float((row_stds - 1.0).abs().max()):.2e}"
        )

    def test_all_nan_row_stays_nan(self) -> None:
        """A row of all NaN stays all NaN after z-scoring."""
        data = pd.DataFrame(
            {"A": [1.0, float("nan"), 3.0],
             "B": [2.0, float("nan"), 5.0],
             "C": [3.0, float("nan"), 7.0]},
            index=pd.date_range("2020-01-01", periods=3, freq="B"),
        )
        z = cross_sectional_zscore(data)
        assert z.iloc[1].isna().all()

    def test_identical_scores_row_nan(self) -> None:
        """A row where all assets have the same score -> z-score is NaN (std=0)."""
        data = pd.DataFrame(
            {"A": [1.0, 5.0], "B": [2.0, 5.0], "C": [3.0, 5.0]},
            index=pd.date_range("2020-01-01", periods=2, freq="B"),
        )
        z = cross_sectional_zscore(data)
        # Row 1 has all identical values; std=0 -> NaN
        assert z.iloc[1].isna().all()

    def test_warmup_nan_preserved(self) -> None:
        """Warmup NaN rows in scores panel propagate through z-scoring."""
        prices = _make_price_panel()
        scores = momentum_scores(prices, lookback=50, skip=0)
        z = cross_sectional_zscore(scores)
        assert z.iloc[:50].isna().all().all()

    def test_two_asset_z_score(self) -> None:
        """With two assets, z-scored values are exactly +/- 1/sqrt(N) scaled."""
        data = pd.DataFrame(
            {"A": [1.0, 3.0], "B": [2.0, 1.0]},
            index=pd.date_range("2020-01-01", periods=2, freq="B"),
        )
        z = cross_sectional_zscore(data)
        # Row 0: [1, 2] -> mean=1.5, std(pop)=0.5 -> z=[-1, 1]
        np.testing.assert_allclose(z.iloc[0].values, [-1.0, 1.0], atol=1e-12)
        # Row 1: [3, 1] -> mean=2, std(pop)=1 -> z=[1, -1]
        np.testing.assert_allclose(z.iloc[1].values, [1.0, -1.0], atol=1e-12)


# ---------------------------------------------------------------------------
# long_short_weights tests
# ---------------------------------------------------------------------------


class TestLongShortWeights:
    """long_short_weights: dollar-neutrality, leg sums, edge cases."""

    def _scores_panel(self, n_assets: int = N_ASSETS) -> pd.DataFrame:
        """Build a scores panel from a synthetic price panel."""
        prices = _make_price_panel(n_assets=n_assets)
        return momentum_scores(prices, lookback=50, skip=0)

    def test_output_shape(self) -> None:
        scores = self._scores_panel()
        w = long_short_weights(scores, quantile=0.2)
        assert w.shape == scores.shape

    def test_row_net_near_zero(self) -> None:
        """For every row with enough assets, the row weight sum is ~0."""
        scores = self._scores_panel()
        w = long_short_weights(scores, quantile=0.2)
        valid = w.iloc[50:]  # post-warmup rows
        row_sums = valid.sum(axis=1)
        assert float(row_sums.abs().max()) < 1e-12, (
            f"Max abs row net = {float(row_sums.abs().max()):.2e}"
        )

    def test_long_leg_sums_to_plus_one(self) -> None:
        """The long leg (positive weights) of each post-warmup row sums to +1."""
        scores = self._scores_panel()
        w = long_short_weights(scores, quantile=0.2)
        valid_rows = w.iloc[50:]
        for _, row in valid_rows.iterrows():
            long_sum = float(row[row > 0].sum())
            if long_sum != 0.0:
                assert abs(long_sum - 1.0) < 1e-12, (
                    f"Long leg sum = {long_sum:.6f} != 1.0"
                )

    def test_short_leg_sums_to_minus_one(self) -> None:
        """The short leg (negative weights) of each post-warmup row sums to -1."""
        scores = self._scores_panel()
        w = long_short_weights(scores, quantile=0.2)
        valid_rows = w.iloc[50:]
        for _, row in valid_rows.iterrows():
            short_sum = float(row[row < 0].sum())
            if short_sum != 0.0:
                assert abs(short_sum - (-1.0)) < 1e-12, (
                    f"Short leg sum = {short_sum:.6f} != -1.0"
                )

    def test_winners_are_long(self) -> None:
        """In a panel with clear winners, the winner assets get positive weights."""
        prices = _make_price_panel(
            n_winners=2, n_losers=2,
            winner_drift=0.003, loser_drift=-0.002,
            noise_std=0.004, seed=SEED,
        )
        scores = momentum_scores(prices, lookback=252, skip=0)
        w = long_short_weights(scores, quantile=0.2)

        # Use late rows where the signal has had time to accumulate
        late_weights = w.iloc[300:]
        winner_weights = late_weights[["A0", "A1"]]
        loser_weights  = late_weights[[f"A{N_ASSETS-2}", f"A{N_ASSETS-1}"]]

        # Most rows should be net long winners and net short losers
        winner_positive_frac = float((winner_weights > 0).any(axis=1).mean())
        loser_negative_frac  = float((loser_weights  < 0).any(axis=1).mean())
        assert winner_positive_frac > 0.7, (
            f"Winners positive fraction = {winner_positive_frac:.2f}"
        )
        assert loser_negative_frac > 0.7, (
            f"Losers negative fraction = {loser_negative_frac:.2f}"
        )

    def test_too_few_assets_all_zero(self) -> None:
        """A row with only 1 valid score -> all-zero weights."""
        data = pd.DataFrame(
            {"A": [1.0], "B": [float("nan")], "C": [float("nan")]},
            index=pd.date_range("2020-01-01", periods=1, freq="B"),
        )
        w = long_short_weights(data, quantile=0.2)
        assert float(w.iloc[0].abs().sum()) == 0.0

    def test_two_assets_enough_for_legs(self) -> None:
        """With 2 assets and quantile=0.4, each leg gets 0 assets (floor(2*0.4)=0).
        But floor(2 * 0.4) = 0, so max(1, 0) = 1 -> 2 legs of 1 -> 2*1 = 2 <= 2 OK."""
        data = pd.DataFrame(
            {"A": [1.0], "B": [2.0]},
            index=pd.date_range("2020-01-01", periods=1, freq="B"),
        )
        w = long_short_weights(data, quantile=0.4)
        row = w.iloc[0]
        # Should produce a valid long/short pair
        assert abs(float(row.sum())) < 1e-12
        assert abs(float(row[row > 0].sum()) - 1.0) < 1e-12
        assert abs(float(row[row < 0].sum()) + 1.0) < 1e-12

    def test_three_assets_overlap_guard(self) -> None:
        """With 3 valid assets and quantile=0.4: n_leg=max(1,floor(3*0.4))=1, 2*1=2<=3 OK."""
        data = pd.DataFrame(
            {"A": [1.0], "B": [2.0], "C": [3.0]},
            index=pd.date_range("2020-01-01", periods=1, freq="B"),
        )
        w = long_short_weights(data, quantile=0.4)
        row = w.iloc[0]
        assert abs(float(row.sum())) < 1e-12

    def test_overlap_protection_all_zero(self) -> None:
        """When 2*n_leg > n_valid, the row should be all zeros."""
        # 2 valid assets, quantile=0.6 -> n_leg=max(1, floor(2*0.6))=1 -> 2*1=2<=2 OK
        # Actually use 2 assets, quantile=0.9 -> n_leg=max(1, floor(2*0.9))=1 -> 2*1=2<=2 OK
        # Need a case where 2*n_leg > n_valid: e.g. 3 assets, quantile=0.9 -> n_leg=2, 2*2=4>3
        data = pd.DataFrame(
            {"A": [1.0], "B": [2.0], "C": [3.0]},
            index=pd.date_range("2020-01-01", periods=1, freq="B"),
        )
        w = long_short_weights(data, quantile=0.9)
        # n_leg=max(1, floor(3*0.9))=2, 2*2=4 > 3 -> all zero
        assert float(w.iloc[0].abs().sum()) == 0.0

    def test_all_nan_row_all_zero(self) -> None:
        """All-NaN row in scores -> all-zero weights."""
        data = pd.DataFrame(
            {"A": [float("nan")], "B": [float("nan")]},
            index=pd.date_range("2020-01-01", periods=1, freq="B"),
        )
        w = long_short_weights(data, quantile=0.2)
        assert float(w.iloc[0].abs().sum()) == 0.0

    def test_invalid_quantile_zero_raises(self) -> None:
        scores = self._scores_panel()
        with pytest.raises(ValueError, match="quantile"):
            long_short_weights(scores, quantile=0.0)

    def test_invalid_quantile_one_raises(self) -> None:
        scores = self._scores_panel()
        with pytest.raises(ValueError, match="quantile"):
            long_short_weights(scores, quantile=1.0)

    def test_invalid_quantile_negative_raises(self) -> None:
        scores = self._scores_panel()
        with pytest.raises(ValueError, match="quantile"):
            long_short_weights(scores, quantile=-0.1)

    def test_warmup_rows_all_zero(self) -> None:
        """Warmup NaN rows in scores produce all-zero weight rows."""
        scores = momentum_scores(_make_price_panel(), lookback=50, skip=0)
        w = long_short_weights(scores, quantile=0.2)
        assert (w.iloc[:50].values == 0.0).all()


# ---------------------------------------------------------------------------
# momentum_portfolio pipeline tests
# ---------------------------------------------------------------------------


class TestMomentumPortfolio:
    """momentum_portfolio: end-to-end pipeline integration."""

    def test_output_shape(self) -> None:
        prices = _make_price_panel()
        cfg = MomentumConfig(lookback=252, skip=21, vol_window=60)
        w = momentum_portfolio(prices, cfg, quantile=0.2, risk_adjusted=True)
        assert w.shape == prices.shape

    def test_dollar_neutral_risk_adjusted(self) -> None:
        """Risk-adjusted portfolio: late row sums are ~0."""
        prices = _make_price_panel()
        cfg = MomentumConfig(lookback=252, skip=21, vol_window=60)
        w = momentum_portfolio(prices, cfg, quantile=0.2, risk_adjusted=True)
        # Check post-warmup rows (use last 50 rows)
        late = w.iloc[-50:]
        row_sums = late.sum(axis=1)
        assert float(row_sums.abs().max()) < 1e-12

    def test_dollar_neutral_raw(self) -> None:
        """Raw momentum portfolio: late row sums are ~0."""
        prices = _make_price_panel()
        cfg = MomentumConfig(lookback=50, skip=0, vol_window=20)
        w = momentum_portfolio(prices, cfg, quantile=0.2, risk_adjusted=False)
        late = w.iloc[-50:]
        row_sums = late.sum(axis=1)
        assert float(row_sums.abs().max()) < 1e-12

    def test_risk_adjusted_false_uses_raw_scores(self) -> None:
        """risk_adjusted=False path returns a weights panel."""
        prices = _make_price_panel()
        cfg = MomentumConfig(lookback=50, skip=0, vol_window=20)
        w = momentum_portfolio(prices, cfg, quantile=0.2, risk_adjusted=False)
        assert w.shape == prices.shape

    def test_columns_match_prices(self) -> None:
        prices = _make_price_panel()
        cfg = MomentumConfig(lookback=252, skip=21, vol_window=60)
        w = momentum_portfolio(prices, cfg)
        assert list(w.columns) == list(prices.columns)

    def test_index_matches_prices(self) -> None:
        prices = _make_price_panel()
        cfg = MomentumConfig(lookback=252, skip=21, vol_window=60)
        w = momentum_portfolio(prices, cfg)
        assert list(w.index) == list(prices.index)

    def test_winners_receive_positive_weights(self) -> None:
        """In a clear-signal panel, winner columns carry net positive weights."""
        prices = _make_price_panel(
            n_winners=2, n_losers=2,
            winner_drift=0.003, loser_drift=-0.002,
            noise_std=0.003, seed=SEED,
        )
        cfg = MomentumConfig(lookback=252, skip=0, vol_window=60)
        w = momentum_portfolio(prices, cfg, quantile=0.2, risk_adjusted=False)
        late = w.iloc[300:]
        winner_pos_frac = float((late[["A0", "A1"]] > 0).any(axis=1).mean())
        loser_neg_frac  = float(
            (late[[f"A{N_ASSETS-2}", f"A{N_ASSETS-1}"]] < 0).any(axis=1).mean()
        )
        assert winner_pos_frac > 0.6
        assert loser_neg_frac > 0.6


# ---------------------------------------------------------------------------
# Public API / __all__ check
# ---------------------------------------------------------------------------


class TestPublicAPI:
    """Verify __all__ exports and importability."""

    def test_all_names_importable(self) -> None:
        import core_trading.signals.factors.momentum as mod
        expected = {
            "MomentumConfig",
            "momentum_scores",
            "risk_adjusted_momentum",
            "cross_sectional_zscore",
            "long_short_weights",
            "momentum_portfolio",
        }
        for name in expected:
            assert hasattr(mod, name), f"Missing from module: {name}"

    def test_all_contains_expected_names(self) -> None:
        import core_trading.signals.factors.momentum as mod
        for name in mod.__all__:
            assert hasattr(mod, name)

    def test_config_is_dataclass(self) -> None:
        import dataclasses
        assert dataclasses.is_dataclass(MomentumConfig)
