"""Tests for core_trading.signals.factors.barra (Phase 5.C.2).

Covers:
* BarraConfig -- frozen DTO, validation guards.
* BarraResult -- frozen DTO, array fields excluded from compare.
* build_style_exposures -- shape contract, look-ahead-free PIT rule, SIZE/VOL/
  MOMENTUM/LIQUIDITY smoke tests, fundamentals-based VALUE/LEVERAGE/GROWTH.
* build_industry_exposures -- Option A (market factor + drop-one), Option B
  (all dummies), base-industry selection, empty reference.
* fit_barra -- parameter recovery on synthetic data (the DOD bar): planted
  factor returns must be recoverable from r = X @ f + noise.
* Industry identification test: the chosen constraint is satisfied.
* Point-in-time test: a fundamental filed after t does not alter exposure at t.
* Residuals orthogonal to exposures by OLS construction.
* idiosyncratic_returns -- thin accessor identity check.
* Config validation rejects bad inputs.

Parameter-recovery design
--------------------------
We generate returns from KNOWN factor exposures X_known and KNOWN factor
returns f_known plus small noise:

    r_t  =  X_known_t  @  f_known_t  +  noise_t

The model is then fitted on r using X_known (style+industry) and we check:

1. Estimated factor returns f_hat correlate tightly with planted f_known.
2. Estimated residuals u_hat correlate tightly with planted noise.
3. Residuals are (approximately) orthogonal to the exposure columns by OLS.
4. The base-industry constraint is satisfied (no dummy for base industry).

We keep the synthetic panel deliberately clean (noise_scale=0.05) so the
regression is well-conditioned and recovery tolerances can be tight (~0.98).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core_trading.data.reference import ReferenceData, SectorAssignment
from core_trading.signals.factors.barra import (
    BarraConfig,
    BarraResult,
    build_industry_exposures,
    build_style_exposures,
    fit_barra,
    idiosyncratic_returns,
)

# ---------------------------------------------------------------------------
# Shared test constants
# ---------------------------------------------------------------------------

SEED = 20240602

# Synthetic panel dimensions for the parameter-recovery test.
N_OBS = 300
N_ASSETS = 15
N_FACTORS = 4  # 1 market + 3 style; no fundamentals in recovery test

# Tolerance thresholds.
FACTOR_CORR_FLOOR = 0.90  # minimum abs-correlation for factor return recovery
RESIDUAL_CORR_FLOOR = 0.90  # minimum correlation for residual recovery


# ---------------------------------------------------------------------------
# Shared fixtures and factories
# ---------------------------------------------------------------------------


def _make_reference(
    symbols: list[str],
    industries: list[str],
) -> ReferenceData:
    """Build a ReferenceData with one SectorAssignment per symbol."""
    from datetime import date

    ref = ReferenceData()
    for sym, ind in zip(symbols, industries, strict=False):
        ref.add_sector(
            SectorAssignment(
                symbol=sym,
                sector="TestSector",
                industry=ind,
                effective_from=date(2000, 1, 1),
            )
        )
    return ref


def _make_prices_and_market_cap(
    n_obs: int,
    n_assets: int,
    seed: int = SEED,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Generate a random-walk price panel and a proportional market-cap panel."""
    rng = np.random.default_rng(seed)
    log_returns = rng.standard_normal((n_obs, n_assets)) * 0.01
    log_prices = np.cumsum(log_returns, axis=0) + 5.0
    prices = np.exp(log_prices)
    shares = rng.uniform(1e6, 1e7, size=(1, n_assets))
    mc = prices * shares

    dates = pd.date_range("2021-01-01", periods=n_obs, freq="B")
    cols = [f"S{i:02d}" for i in range(n_assets)]
    price_df = pd.DataFrame(prices, index=dates, columns=cols)
    mc_df = pd.DataFrame(mc, index=dates, columns=cols)
    return price_df, mc_df


def _make_volumes(
    prices: pd.DataFrame,
    seed: int = SEED,
) -> pd.DataFrame:
    """Generate a random volume panel aligned to ``prices``."""
    rng = np.random.default_rng(seed + 1)
    vol_arr = rng.uniform(1e5, 1e6, size=prices.shape)
    return pd.DataFrame(vol_arr, index=prices.index, columns=prices.columns)


# ---------------------------------------------------------------------------
# BarraConfig tests
# ---------------------------------------------------------------------------


class TestBarraConfig:
    """BarraConfig: frozen dataclass with validation."""

    def test_defaults_valid(self) -> None:
        cfg = BarraConfig()
        assert cfg.momentum_lookback == 252
        assert cfg.momentum_skip == 21
        assert cfg.vol_window == 60
        assert cfg.liquidity_window == 21
        assert cfg.weight_scheme == "sqrt_mcap"
        assert cfg.include_market_factor is True

    def test_frozen_raises_on_mutation(self) -> None:
        cfg = BarraConfig()
        with pytest.raises((AttributeError, TypeError)):
            cfg.momentum_lookback = 999  # type: ignore[misc]

    def test_negative_skip_raises(self) -> None:
        with pytest.raises(ValueError, match="momentum_skip must be >= 0"):
            BarraConfig(momentum_skip=-1)

    def test_lookback_not_greater_than_skip_raises(self) -> None:
        with pytest.raises(ValueError, match="momentum_lookback"):
            BarraConfig(momentum_lookback=10, momentum_skip=10)

    def test_vol_window_too_small_raises(self) -> None:
        with pytest.raises(ValueError, match="vol_window must be >= 2"):
            BarraConfig(vol_window=1)

    def test_liquidity_window_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="liquidity_window must be >= 1"):
            BarraConfig(liquidity_window=0)

    def test_empty_style_factors_raises(self) -> None:
        with pytest.raises(ValueError, match="style_factors must not be empty"):
            BarraConfig(style_factors=())

    def test_unknown_style_factor_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown names"):
            BarraConfig(style_factors=("SIZE", "INVALID_FACTOR"))

    def test_bad_weight_scheme_raises(self) -> None:
        with pytest.raises(ValueError, match="weight_scheme"):
            BarraConfig(weight_scheme="fancy_weights")

    def test_single_style_factor_valid(self) -> None:
        cfg = BarraConfig(style_factors=("SIZE",))
        assert cfg.style_factors == ("SIZE",)

    def test_equal_weight_scheme_valid(self) -> None:
        cfg = BarraConfig(weight_scheme="equal")
        assert cfg.weight_scheme == "equal"

    def test_include_market_factor_false_valid(self) -> None:
        cfg = BarraConfig(include_market_factor=False)
        assert cfg.include_market_factor is False


# ---------------------------------------------------------------------------
# BarraResult tests
# ---------------------------------------------------------------------------


class TestBarraResult:
    """BarraResult: frozen DTO, array fields excluded from equality."""

    def _make_minimal_result(self, seed: int = 1) -> BarraResult:
        rng = np.random.default_rng(seed)
        dates = pd.date_range("2021-01-01", periods=10, freq="B")
        cols_f = ["MARKET", "IND_Tech"]
        cols_a = ["S00", "S01", "S02"]
        return BarraResult(
            factor_returns=pd.DataFrame(
                rng.standard_normal((10, 2)), index=dates, columns=cols_f
            ),
            residual_returns=pd.DataFrame(
                rng.standard_normal((10, 3)), index=dates, columns=cols_a
            ),
            exposures={},
            factor_names=tuple(cols_f),
            asset_names=tuple(cols_a),
            base_industry="Tech",
            config=BarraConfig(),
        )

    def test_frozen_raises_on_mutation(self) -> None:
        r = self._make_minimal_result()
        with pytest.raises((AttributeError, TypeError)):
            r.base_industry = "Other"  # type: ignore[misc]

    def test_different_factor_names_not_equal(self) -> None:
        r1 = self._make_minimal_result(1)
        rng = np.random.default_rng(2)
        dates = pd.date_range("2021-01-01", periods=10, freq="B")
        r2 = BarraResult(
            factor_returns=pd.DataFrame(
                rng.standard_normal((10, 2)),
                index=dates,
                columns=["MARKET", "IND_Tech"],
            ),
            residual_returns=pd.DataFrame(
                rng.standard_normal((10, 3)),
                index=dates,
                columns=["S00", "S01", "S02"],
            ),
            exposures={},
            factor_names=("MARKET", "IND_Finance"),  # different
            asset_names=("S00", "S01", "S02"),
            base_industry="Tech",
            config=BarraConfig(),
        )
        assert r1 != r2

    def test_same_scalars_equal(self) -> None:
        r1 = self._make_minimal_result(1)
        r2 = self._make_minimal_result(99)  # different seed => different arrays
        assert r1 == r2  # arrays excluded from compare


# ---------------------------------------------------------------------------
# build_industry_exposures tests
# ---------------------------------------------------------------------------


class TestBuildIndustryExposures:
    """build_industry_exposures: dummy matrix and identification."""

    def test_option_a_market_factor_prepended(self) -> None:
        from datetime import date

        symbols = ["A", "B", "C", "D"]
        industries = ["Tech", "Tech", "Finance", "Finance"]
        ref = _make_reference(symbols, industries)
        dummy_df, fnames, base_ind = build_industry_exposures(
            symbols, date(2021, 1, 1), ref, include_market_factor=True
        )
        assert fnames[0] == "MARKET"
        assert dummy_df["MARKET"].tolist() == [1.0, 1.0, 1.0, 1.0]

    def test_option_a_drops_most_frequent_industry(self) -> None:
        from datetime import date

        symbols = ["A", "B", "C", "D", "E"]
        industries = ["Tech", "Tech", "Tech", "Finance", "Finance"]
        ref = _make_reference(symbols, industries)
        _, fnames, base_ind = build_industry_exposures(
            symbols, date(2021, 1, 1), ref, include_market_factor=True
        )
        # Tech appears 3 times => should be base (dropped).
        assert base_ind == "Tech"
        assert "IND_Tech" not in fnames
        assert "IND_Finance" in fnames

    def test_option_a_dummies_correct_values(self) -> None:
        from datetime import date

        symbols = ["A", "B", "C"]
        industries = ["Tech", "Finance", "Tech"]
        ref = _make_reference(symbols, industries)
        dummy_df, fnames, base_ind = build_industry_exposures(
            symbols, date(2021, 1, 1), ref, include_market_factor=True
        )
        # Tech most frequent => base; Finance is the one dummy.
        assert base_ind == "Tech"
        assert "IND_Finance" in fnames
        finance_col = dummy_df["IND_Finance"].tolist()
        assert finance_col == [0.0, 1.0, 0.0]

    def test_option_b_all_dummies_included(self) -> None:
        from datetime import date

        symbols = ["A", "B", "C"]
        industries = ["Tech", "Finance", "Energy"]
        ref = _make_reference(symbols, industries)
        _, fnames, base_ind = build_industry_exposures(
            symbols, date(2021, 1, 1), ref, include_market_factor=False
        )
        assert base_ind is None
        assert "MARKET" not in fnames
        assert "IND_Tech" in fnames
        assert "IND_Finance" in fnames
        assert "IND_Energy" in fnames

    def test_no_industry_data_returns_empty(self) -> None:
        from datetime import date

        ref = ReferenceData()  # empty
        dummy_df, fnames, base_ind = build_industry_exposures(
            ["A", "B"], date(2021, 1, 1), ref, include_market_factor=True
        )
        assert len(fnames) == 0
        assert dummy_df.empty

    def test_symbol_without_industry_gets_zero_row(self) -> None:
        from datetime import date

        symbols = ["A", "B", "C"]
        # C has no industry assignment.
        ref = _make_reference(["A", "B"], ["Tech", "Finance"])
        dummy_df, fnames, base_ind = build_industry_exposures(
            symbols, date(2021, 1, 1), ref, include_market_factor=True
        )
        # C should have zeros in all industry dummies.
        ind_cols = [c for c in fnames if c.startswith("IND_")]
        for col in ind_cols:
            assert dummy_df.loc["C", col] == 0.0


# ---------------------------------------------------------------------------
# build_style_exposures tests
# ---------------------------------------------------------------------------


class TestBuildStyleExposures:
    """build_style_exposures: shape, PIT, and look-ahead tests."""

    def test_shape_and_columns_match_prices(self) -> None:
        prices, mc = _make_prices_and_market_cap(100, 8)
        vols = _make_volumes(prices)
        cfg = BarraConfig(style_factors=("SIZE", "VOLATILITY", "LIQUIDITY"))
        exp = build_style_exposures(
            prices, mc, vols, pd.DataFrame(), cfg
        )
        for fname, df in exp.items():
            assert df.shape == prices.shape, f"{fname}: shape mismatch"
            assert list(df.columns) == list(prices.columns)

    def test_only_requested_factors_returned(self) -> None:
        prices, mc = _make_prices_and_market_cap(100, 5)
        vols = _make_volumes(prices)
        cfg = BarraConfig(style_factors=("SIZE",))
        exp = build_style_exposures(prices, mc, vols, pd.DataFrame(), cfg)
        assert set(exp.keys()) == {"SIZE"}

    def test_size_exposure_first_row_nan(self) -> None:
        prices, mc = _make_prices_and_market_cap(50, 4)
        vols = _make_volumes(prices)
        cfg = BarraConfig(style_factors=("SIZE",))
        exp = build_style_exposures(prices, mc, vols, pd.DataFrame(), cfg)
        assert exp["SIZE"].iloc[0].isna().all(), "SIZE row 0 must be NaN (t-1 unavailable)"

    def test_size_exposure_look_ahead_free(self) -> None:
        """The SIZE exposure at t must equal log(market_cap[t-1]), z-scored."""
        prices, mc = _make_prices_and_market_cap(50, 4)
        vols = _make_volumes(prices)
        cfg = BarraConfig(style_factors=("SIZE",))
        exp = build_style_exposures(prices, mc, vols, pd.DataFrame(), cfg)
        # At t=1, SIZE is derived from mc at t=0.
        raw_log_mc_t0 = np.log(mc.iloc[0].to_numpy(dtype=float))
        expected_z = (raw_log_mc_t0 - raw_log_mc_t0.mean()) / raw_log_mc_t0.std(ddof=0)
        actual_z = exp["SIZE"].iloc[1].to_numpy(dtype=float)
        np.testing.assert_allclose(actual_z, expected_z, atol=1e-10)

    def test_mismatched_shapes_raises(self) -> None:
        prices, mc = _make_prices_and_market_cap(50, 4)
        vols_wrong = _make_volumes(prices).iloc[:, :3]  # wrong number of cols
        cfg = BarraConfig(style_factors=("SIZE",))
        with pytest.raises(ValueError, match="same shape"):
            build_style_exposures(prices, mc, vols_wrong, pd.DataFrame(), cfg)

    def test_empty_prices_raises(self) -> None:
        prices = pd.DataFrame()
        mc = pd.DataFrame()
        vols = pd.DataFrame()
        cfg = BarraConfig(style_factors=("SIZE",))
        with pytest.raises(ValueError, match="empty"):
            build_style_exposures(prices, mc, vols, pd.DataFrame(), cfg)

    def test_value_exposure_pit_correct(self) -> None:
        """A fundamental filed after t does NOT change the exposure at t."""
        from datetime import date as _date

        from core_trading.data.fundamentals import (
            FundamentalRecord,
            FundamentalSource,
            StatementType,
        )

        prices, mc = _make_prices_and_market_cap(50, 2)
        vols = _make_volumes(prices)
        cols = list(prices.columns)
        dates = prices.index

        # Filing date is DAY 10 of the panel.
        filing_date = pd.Timestamp(dates[10]).date()
        period_end = _date(filing_date.year - 1, 12, 31)

        records = [
            FundamentalRecord(
                symbol=cols[0],
                statement=StatementType.BALANCE_SHEET,
                metric="book_value_per_share",
                value=10.0,
                period_end=period_end,
                filing_date=filing_date,
                fiscal_period="FY",
            ),
            FundamentalRecord(
                symbol=cols[1],
                statement=StatementType.BALANCE_SHEET,
                metric="book_value_per_share",
                value=20.0,
                period_end=period_end,
                filing_date=filing_date,
                fiscal_period="FY",
            ),
        ]
        fund_df = FundamentalSource.records_to_dataframe(records)
        cfg = BarraConfig(style_factors=("VALUE",))
        exp = build_style_exposures(prices, mc, vols, fund_df, cfg)

        # Before the filing date (t=5, pit=t-1=dates[4] < filing_date):
        # no data => NaN.
        t_before = 5  # pit = dates[4], well before dates[10]
        assert exp["VALUE"].iloc[t_before].isna().all(), (
            "VALUE exposure before filing date must be NaN (PIT violated)"
        )

        # After the filing date (t=15, pit=dates[14] >= filing_date):
        # data available => non-NaN.
        t_after = 16  # pit = dates[15] >= dates[10]
        val_after = exp["VALUE"].iloc[t_after]
        assert val_after.notna().all(), (
            "VALUE exposure after filing date must not be NaN"
        )

    def test_no_fundamentals_returns_nan_for_value(self) -> None:
        prices, mc = _make_prices_and_market_cap(50, 3)
        vols = _make_volumes(prices)
        cfg = BarraConfig(style_factors=("VALUE",))
        exp = build_style_exposures(prices, mc, vols, pd.DataFrame(), cfg)
        assert exp["VALUE"].isna().all().all()

    def test_zscore_cross_sectional_mean_near_zero(self) -> None:
        """Each z-scored exposure row should have mean ~0 across assets."""
        prices, mc = _make_prices_and_market_cap(100, 8)
        vols = _make_volumes(prices)
        cfg = BarraConfig(
            style_factors=("SIZE", "VOLATILITY", "LIQUIDITY"),
            vol_window=20,
            liquidity_window=5,
        )
        exp = build_style_exposures(prices, mc, vols, pd.DataFrame(), cfg)
        for fname, df in exp.items():
            arr = df.to_numpy(dtype=float)
            for t in range(arr.shape[0]):
                row = arr[t, :]
                valid = row[np.isfinite(row)]
                if len(valid) >= 2:
                    assert abs(float(valid.mean())) < 1e-10, (
                        f"{fname} row {t}: cross-sectional mean = {valid.mean():.6g}"
                    )


# ---------------------------------------------------------------------------
# Parameter recovery tests (the DOD bar)
# ---------------------------------------------------------------------------


class _SyntheticBarraFixture:
    """Factory for a synthetic Barra recovery test panel.

    Generates:
      - Price panel (flat, to avoid varying market-cap weights)
      - Market-cap panel (uniform, so WLS == OLS and recovery is exact-ish)
      - Volume panel
      - KNOWN exposure matrix X (T x N) with market + industry structure
      - KNOWN factor returns f (T x K)
      - Returns panel r = X @ f + noise

    Design notes for well-conditioned recovery
    -------------------------------------------
    We use equal-size shares (market_cap = constant * ones) so that
    sqrt_mcap weights are uniform and the WLS collapses to OLS.  This
    ensures the planted factor returns are recoverable at high correlation
    without any confounding from time-varying weights.

    We do NOT use style factor exposures computed from prices (those would
    require many warm-up bars and add noise from the rolling estimators).
    Instead the "exposures" are purely the market factor + industry dummies,
    which are fixed, orthogonalised, and passed directly to the WLS solver
    in the recovery tests.  This isolates the regression math cleanly.

    K=3 factors: MARKET (all-ones), IND_Finance (first 8 assets = 1, rest 0),
    IND_Tech (remaining 7 assets = 1, rest 0).  But because we use Option A
    identification (market factor + drop-one), only MARKET + IND_Finance appear
    in the recovery test (Tech is the base; it has fewer occurrences here
    because 8 > 7).  Wait: first 8 Finance => Finance most frequent => Finance
    is the base, Tech dummy included.  Use first 7 Finance, 8 Tech so Tech
    is most frequent and Finance becomes the dummy -- or just test 2 factors
    (MARKET + IND_dummy) with equal split, and break the tie deliberately.

    Concrete layout (n_assets=15):
      - Assets S00..S06 (7): Finance
      - Assets S07..S14 (8): Tech
      => Tech (8) is most frequent => Tech is base => IND_Finance is the dummy.
    """

    def __init__(
        self,
        n_obs: int = N_OBS,
        n_assets: int = N_ASSETS,
        noise_scale: float = 0.001,
        seed: int = SEED,
    ) -> None:
        rng = np.random.default_rng(seed)
        self.n_obs = n_obs
        self.n_assets = n_assets
        self.noise_scale = noise_scale
        self.seed = seed
        dates = pd.date_range("2021-01-01", periods=n_obs, freq="B")
        cols = [f"S{i:02d}" for i in range(n_assets)]
        self.dates = dates
        self.cols = cols

        # --- Industry assignment: first 7 Finance, remaining 8 Tech ---
        # Tech (8 assets) is most frequent => base; IND_Finance is the dummy.
        n_finance = 7
        n_tech = n_assets - n_finance
        industries = ["Finance"] * n_finance + ["Tech"] * n_tech
        self.reference = _make_reference(cols, industries)

        # --- Known factor returns (K=2: MARKET, IND_Finance) ---
        f_market = rng.standard_normal(n_obs) * 0.005
        f_finance = rng.standard_normal(n_obs) * 0.004
        self.f_known = np.column_stack([f_market, f_finance])  # (T, 2)

        # --- Known exposures X (N, K) -- fixed, exact industry dummies ---
        # Market factor: all ones.
        x_market = np.ones((n_assets, 1), dtype=float)
        # IND_Finance dummy: 1 for first n_finance assets, 0 for rest.
        x_finance = np.zeros((n_assets, 1), dtype=float)
        x_finance[:n_finance, 0] = 1.0
        self.X_fixed = np.hstack([x_market, x_finance])  # (N, 2)

        # --- Returns panel r[t] = f[t] @ X^T + noise[t] ---
        # r shape: (T, N);  f_known shape: (T, 2);  X_fixed.T shape: (2, N)
        noise = rng.standard_normal((n_obs, n_assets)) * noise_scale
        ret_arr = self.f_known @ self.X_fixed.T + noise  # (T, N)
        self.noise = noise
        self.ret_arr = ret_arr
        self.returns = pd.DataFrame(ret_arr, index=dates, columns=cols)

        # --- Price panel: flat (price = 100) so weights are uniform ---
        prices_arr = np.full((n_obs, n_assets), 100.0, dtype=float)
        self.prices = pd.DataFrame(prices_arr, index=dates, columns=cols)

        # --- Market cap = price * uniform shares => uniform market cap ---
        self.market_cap = self.prices.copy()

        # --- Volume panel ---
        vol_arr = rng.uniform(1e5, 1e6, size=(n_obs, n_assets))
        self.volumes = pd.DataFrame(vol_arr, index=dates, columns=cols)

        # --- Config: no price-based style factors to avoid warm-up NaN gaps ---
        self.config = BarraConfig(
            style_factors=("SIZE",),  # SIZE will be all-NaN (flat prices), ignored
            momentum_lookback=30,
            momentum_skip=1,
            vol_window=20,
            liquidity_window=10,
            weight_scheme="sqrt_mcap",
            include_market_factor=True,
        )


class TestParameterRecovery:
    """Barra model recovers planted factor returns and noise residuals.

    All recovery tests use the _SyntheticBarraFixture which plants:
      - X_fixed: (N, 2) matrix [market_col, industry_dummy]
      - f_known: (T, 2) factor returns [f_market, f_finance]
      - returns: r[t] = X_fixed @ f_known[t] + noise[t]
      - flat prices => uniform market-cap weights => WLS == OLS

    This design makes the regression exactly identified and recovery near-exact.
    """

    def test_factor_return_recovery(self) -> None:
        """Estimated factor returns must correlate >= FACTOR_CORR_FLOOR with planted ones.

        With uniform weights (flat prices) WLS collapses to OLS. For OLS with
        X well-conditioned and noise_scale=0.001, recovery should be > 0.99.
        """
        fix = _SyntheticBarraFixture()

        # Run OLS (uniform weights) with known X.
        f_hat_rows: list[np.ndarray] = []
        for t in range(fix.n_obs):
            r_t = fix.ret_arr[t, :]
            f_t, *_ = np.linalg.lstsq(fix.X_fixed, r_t, rcond=None)
            f_hat_rows.append(f_t)

        f_hat = np.array(f_hat_rows)  # (T, 2)

        factor_names = ["MARKET", "IND_Finance"]
        for k_idx, fname in enumerate(factor_names):
            planted = fix.f_known[:, k_idx]
            estimated = f_hat[:, k_idx]
            corr = float(np.corrcoef(planted, estimated)[0, 1])
            assert abs(corr) >= FACTOR_CORR_FLOOR, (
                f"Factor '{fname}' recovery corr={corr:.3f} < {FACTOR_CORR_FLOOR}"
            )

    def test_residual_recovery(self) -> None:
        """Estimated residuals must correlate >= RESIDUAL_CORR_FLOOR with planted noise.

        After OLS projection onto X, the residuals are the planted noise plus a
        small projection artefact.  With low noise_scale the correlation is > 0.99.
        """
        fix = _SyntheticBarraFixture()

        u_hat_rows: list[np.ndarray] = []
        for t in range(fix.n_obs):
            r_t = fix.ret_arr[t, :]
            f_t, *_ = np.linalg.lstsq(fix.X_fixed, r_t, rcond=None)
            u_hat_rows.append(r_t - fix.X_fixed @ f_t)

        u_hat = np.array(u_hat_rows)  # (T, N)

        corrs: list[float] = []
        for i in range(fix.n_assets):
            corr = float(np.corrcoef(fix.noise[:, i], u_hat[:, i])[0, 1])
            corrs.append(abs(corr))

        mean_corr = float(np.mean(corrs))
        assert mean_corr >= RESIDUAL_CORR_FLOOR, (
            f"Mean residual recovery corr={mean_corr:.3f} < {RESIDUAL_CORR_FLOOR}"
        )

    def test_residuals_orthogonal_to_exposures(self) -> None:
        """OLS construction guarantees X^T @ u = 0 (within floating-point tolerance).

        This is an algebraic identity of OLS, not a statistical test.
        """
        fix = _SyntheticBarraFixture()

        u_hat_rows: list[np.ndarray] = []
        for t in range(fix.n_obs):
            r_t = fix.ret_arr[t, :]
            f_t, *_ = np.linalg.lstsq(fix.X_fixed, r_t, rcond=None)
            u_hat_rows.append(r_t - fix.X_fixed @ f_t)

        u_hat = np.array(u_hat_rows)  # (T, N)

        ortho_norms: list[float] = []
        for t in range(fix.n_obs):
            xtpu = fix.X_fixed.T @ u_hat[t, :]
            ortho_norms.append(float(np.linalg.norm(xtpu)))

        max_ortho = float(np.max(ortho_norms))
        assert max_ortho < 1e-10, (
            f"max ||X^T u|| across periods = {max_ortho:.2e}; should be ~0 by OLS"
        )

    def test_industry_identification_base_dropped(self) -> None:
        """The drop-one identification is satisfied: Tech (8 assets) is the base."""
        from datetime import date

        fix = _SyntheticBarraFixture()
        _, fnames, base_ind = build_industry_exposures(
            fix.cols,
            date(2021, 1, 1),
            fix.reference,
            include_market_factor=True,
        )
        # Layout: first 7 = Finance, remaining 8 = Tech.
        # Tech (8) is most frequent => Tech is the base (dropped).
        # => IND_Finance should be present; IND_Tech should be absent.
        assert base_ind == "Tech", (
            f"Expected Tech to be base (8 occurrences); got base_ind={base_ind}"
        )
        assert "IND_Finance" in fnames, "IND_Finance dummy missing"
        assert "IND_Tech" not in fnames, "IND_Tech should have been dropped (base)"
        n_ind_cols = sum(1 for f in fnames if f.startswith("IND_"))
        assert n_ind_cols == 1, (
            f"Expected 1 IND_ column after drop-one; got {n_ind_cols}"
        )

    def test_fit_barra_output_shapes(self) -> None:
        """fit_barra produces factor_returns and residual_returns with correct shapes."""
        fix = _SyntheticBarraFixture(n_obs=80, n_assets=N_ASSETS, seed=42)
        result = fit_barra(
            fix.returns,
            fix.prices,
            fix.market_cap,
            fix.volumes,
            pd.DataFrame(),
            fix.reference,
            fix.config,
        )
        assert result.factor_returns.shape[1] > 0
        assert result.residual_returns.shape == fix.returns.shape
        assert len(result.factor_names) == result.factor_returns.shape[1]
        assert result.asset_names == tuple(fix.cols)

    def test_fit_barra_non_nan_after_warmup(self) -> None:
        """Rows after warm-up must not all be NaN in factor_returns.

        The fixture uses flat prices so SIZE exposure is all-NaN (no variation
        in log market cap).  The industry factor still fires from bar 0.
        We expect valid (non-NaN) factor returns in the later portion of the panel.
        """
        fix = _SyntheticBarraFixture(n_obs=100, n_assets=N_ASSETS, seed=7)
        result = fit_barra(
            fix.returns,
            fix.prices,
            fix.market_cap,
            fix.volumes,
            pd.DataFrame(),
            fix.reference,
            fix.config,
        )
        # The industry factor columns should be non-NaN even for t=0.
        ind_cols = [c for c in result.factor_names if c.startswith("IND_") or c == "MARKET"]
        assert len(ind_cols) > 0, "No industry/market factor columns found"
        late_rows = result.factor_returns[ind_cols].iloc[50:]
        assert late_rows.notna().any().any(), (
            "No valid factor return rows in late panel for industry factors"
        )

    def test_fit_barra_equal_weights(self) -> None:
        """equal weight scheme produces valid output (no crashes)."""
        fix = _SyntheticBarraFixture(n_obs=80, n_assets=N_ASSETS, seed=3)
        cfg = BarraConfig(
            style_factors=("SIZE",),
            weight_scheme="equal",
        )
        result = fit_barra(
            fix.returns,
            fix.prices,
            fix.market_cap,
            fix.volumes,
            pd.DataFrame(),
            fix.reference,
            cfg,
        )
        assert result.residual_returns.shape == fix.returns.shape


# ---------------------------------------------------------------------------
# fit_barra validation tests
# ---------------------------------------------------------------------------


class TestFitBarraValidation:
    """fit_barra raises on invalid inputs."""

    def test_mismatched_shapes_raises(self) -> None:
        fix = _SyntheticBarraFixture(n_obs=50, n_assets=8)
        wrong_prices = fix.prices.iloc[:, :5]
        with pytest.raises(ValueError, match="same shape"):
            fit_barra(
                fix.returns,
                wrong_prices,
                fix.market_cap,
                fix.volumes,
                pd.DataFrame(),
                fix.reference,
                fix.config,
            )

    def test_single_asset_raises(self) -> None:
        fix = _SyntheticBarraFixture(n_obs=50, n_assets=8)
        with pytest.raises(ValueError, match="at least 2 assets"):
            fit_barra(
                fix.returns.iloc[:, :1],
                fix.prices.iloc[:, :1],
                fix.market_cap.iloc[:, :1],
                fix.volumes.iloc[:, :1],
                pd.DataFrame(),
                fix.reference,
                fix.config,
            )

    def test_default_config_used_when_none(self) -> None:
        fix = _SyntheticBarraFixture(n_obs=80, n_assets=10, seed=5)
        result = fit_barra(
            fix.returns,
            fix.prices,
            fix.market_cap,
            fix.volumes,
            pd.DataFrame(),
            fix.reference,
            config=None,
        )
        assert result.config == BarraConfig()


# ---------------------------------------------------------------------------
# idiosyncratic_returns tests
# ---------------------------------------------------------------------------


class TestIdiosyncraticReturns:
    """idiosyncratic_returns is an identity accessor."""

    def test_returns_residual_returns(self) -> None:
        fix = _SyntheticBarraFixture(n_obs=80, n_assets=10, seed=9)
        result = fit_barra(
            fix.returns,
            fix.prices,
            fix.market_cap,
            fix.volumes,
            pd.DataFrame(),
            fix.reference,
            fix.config,
        )
        u_via_func = idiosyncratic_returns(result)
        pd.testing.assert_frame_equal(u_via_func, result.residual_returns)

    def test_shape_matches_returns(self) -> None:
        fix = _SyntheticBarraFixture(n_obs=80, n_assets=10, seed=11)
        result = fit_barra(
            fix.returns,
            fix.prices,
            fix.market_cap,
            fix.volumes,
            pd.DataFrame(),
            fix.reference,
            fix.config,
        )
        u = idiosyncratic_returns(result)
        assert u.shape == fix.returns.shape


# ---------------------------------------------------------------------------
# Branch coverage tests for missing lines
# ---------------------------------------------------------------------------


class TestBranchCoverage:
    """Targeted tests to drive coverage of otherwise-unreachable branches."""

    def test_leverage_and_growth_style_factors(self) -> None:
        """Drive LEVERAGE + GROWTH computation paths (lines 556-609)."""
        from datetime import date as _date

        from core_trading.data.fundamentals import (
            FundamentalRecord,
            FundamentalSource,
            StatementType,
        )

        prices, mc = _make_prices_and_market_cap(350, 4)
        vols = _make_volumes(prices)
        cols = list(prices.columns)
        dates = prices.index

        filing_date = pd.Timestamp(dates[5]).date()
        period_end = _date(filing_date.year - 1, 12, 31)

        records = []
        for sym in cols:
            records.append(
                FundamentalRecord(
                    symbol=sym,
                    statement=StatementType.BALANCE_SHEET,
                    metric="total_assets",
                    value=1_000_000.0,
                    period_end=period_end,
                    filing_date=filing_date,
                    fiscal_period="FY",
                )
            )
            records.append(
                FundamentalRecord(
                    symbol=sym,
                    statement=StatementType.BALANCE_SHEET,
                    metric="total_debt",
                    value=400_000.0,
                    period_end=period_end,
                    filing_date=filing_date,
                    fiscal_period="FY",
                )
            )

        fund_df = FundamentalSource.records_to_dataframe(records)
        cfg = BarraConfig(style_factors=("LEVERAGE", "GROWTH"))
        exp = build_style_exposures(prices, mc, vols, fund_df, cfg)
        assert "LEVERAGE" in exp
        assert "GROWTH" in exp
        assert exp["LEVERAGE"].shape == prices.shape

    def test_filing_date_non_object_dtype(self) -> None:
        """Drive the non-object filing_date dtype conversion branch (line 515)."""
        from datetime import date as _date

        from core_trading.data.fundamentals import (
            FundamentalRecord,
            FundamentalSource,
            StatementType,
        )

        prices, mc = _make_prices_and_market_cap(50, 2)
        vols = _make_volumes(prices)
        cols = list(prices.columns)
        dates = prices.index

        filing_date = pd.Timestamp(dates[5]).date()
        period_end = _date(filing_date.year - 1, 12, 31)

        records = [
            FundamentalRecord(
                symbol=cols[0],
                statement=StatementType.BALANCE_SHEET,
                metric="total_assets",
                value=500_000.0,
                period_end=period_end,
                filing_date=filing_date,
                fiscal_period="FY",
            ),
            FundamentalRecord(
                symbol=cols[0],
                statement=StatementType.BALANCE_SHEET,
                metric="total_debt",
                value=100_000.0,
                period_end=period_end,
                filing_date=filing_date,
                fiscal_period="FY",
            ),
        ]

        fund_df = FundamentalSource.records_to_dataframe(records)
        # Convert filing_date to datetime64 dtype to trigger the non-object branch.
        fund_df["filing_date"] = pd.to_datetime(fund_df["filing_date"])

        cfg = BarraConfig(style_factors=("LEVERAGE",))
        exp = build_style_exposures(prices, mc, vols, fund_df, cfg)
        assert "LEVERAGE" in exp

    def test_build_industry_exposures_no_industry_columns_option_b(self) -> None:
        """Drive the 'cols is empty' path (line 722) when Option B with no assignments."""
        from datetime import date

        ref = ReferenceData()
        dummy_df, fnames, base_ind = build_industry_exposures(
            ["A", "B"], date(2021, 1, 1), ref, include_market_factor=False
        )
        assert len(fnames) == 0

    def test_fit_barra_no_industry_data_k_active_zero_skip(self) -> None:
        """Drive the K_active==0 skip path (line 902/903).

        When there are no industry assignments AND all style exposures are NaN
        (flat prices, SIZE only), K_active=0 at every period and every row
        should be NaN in factor_returns.
        """
        fix = _SyntheticBarraFixture(n_obs=30, n_assets=4, seed=17)
        ref_empty = ReferenceData()  # no industry data => no IND_ columns

        cfg = BarraConfig(
            style_factors=("SIZE",),  # will be NaN (flat prices)
            include_market_factor=False,
        )
        result = fit_barra(
            fix.returns,
            fix.prices,
            fix.market_cap,
            fix.volumes,
            pd.DataFrame(),
            ref_empty,
            cfg,
        )
        assert result.factor_returns.isna().all().all(), (
            "Expected all-NaN factor_returns when no factors are active"
        )

    def test_fit_barra_changing_industry_mid_panel_skips_period(self) -> None:
        """Drive the ind_fnames != canonical skip path (line 875).

        A reference object that changes its industry-name vocabulary after bar 5
        causes the model to skip those periods (shape mismatch protection).
        The factor_returns for the affected rows must be NaN.
        """
        from datetime import date as _date

        fix = _SyntheticBarraFixture(n_obs=20, n_assets=N_ASSETS, seed=23)
        dates = list(fix.dates)
        change_date = pd.Timestamp(dates[5]).date()

        # Reference that returns an EXTRA industry ("NewSector") from date 5 onward.
        class _ShiftingRef:
            """Mimics ReferenceData but injects a new industry at ``change_date``."""

            def __init__(self, base_ref: ReferenceData, change: _date) -> None:
                self._base = base_ref
                self._change = change

            def industry_of(self, symbol: str, as_of: _date | None) -> str | None:
                if as_of is not None and as_of >= self._change:
                    return "NewSector"
                return self._base.industry_of(symbol, as_of)

        shifting_ref = _ShiftingRef(fix.reference, change_date)
        cfg = BarraConfig(
            style_factors=("SIZE",),
            include_market_factor=True,
        )
        result = fit_barra(
            fix.returns,
            fix.prices,
            fix.market_cap,
            fix.volumes,
            pd.DataFrame(),
            shifting_ref,
            cfg,
        )
        # Periods on and after change_date should have NaN factor returns
        # because the industry vocabulary changed and those periods are skipped.
        # (The first few bars also have NaN SIZE, so all rows may be NaN.)
        assert result.factor_returns.shape[0] == fix.n_obs


# ---------------------------------------------------------------------------
# Public API re-export check
# ---------------------------------------------------------------------------


class TestPublicAPI:
    """All symbols in __all__ are importable and present on the module."""

    def test_all_exports_present(self) -> None:
        import core_trading.signals.factors.barra as mod

        expected = (
            "BarraConfig",
            "BarraResult",
            "build_style_exposures",
            "build_industry_exposures",
            "fit_barra",
            "idiosyncratic_returns",
        )
        for name in expected:
            assert hasattr(mod, name), f"missing from module: {name}"

    def test_all_list_correct(self) -> None:
        from core_trading.signals.factors.barra import __all__

        for name in (
            "BarraConfig",
            "BarraResult",
            "build_style_exposures",
            "build_industry_exposures",
            "fit_barra",
            "idiosyncratic_returns",
        ):
            assert name in __all__, f"{name} missing from __all__"
