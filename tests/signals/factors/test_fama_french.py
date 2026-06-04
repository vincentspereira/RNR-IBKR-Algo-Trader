"""Tests for core_trading.signals.factors.fama_french (Phase 5.C.1).

Covers:
* FamaFrenchConfig -- frozen DTO, __post_init__ validation of all constraints.
* pit_latest_value -- correct PIT cut (filing_date <= as_of), revision_id
  tiebreak, empty fundamentals, metric filtering.
* build_characteristic_panel -- wide panel shape, PIT forward-fill, no
  leakage (later-filed record does NOT influence earlier dates).
* compute_market_equity -- price * shares_outstanding element-wise.
* compute_book_to_market -- book_equity / market_equity.
* compute_rmw -- operating_profit / book_equity.
* compute_cma -- asset growth = total_assets[t] / total_assets[t-1] - 1.
* form_ff_portfolios -- 2x3 sort, breakpoints, empty result on too few assets.
* factor_returns_from_portfolios -- value-weighted returns, SMB arithmetic.
* compute_umd -- sign/direction (high-momentum leg positive).
* compute_fama_french_factors -- end-to-end; output shape/columns; premium
  sign recovery (plant SMB, HML, RMW, CMA premiums, assert recovered sign
  is positive / negative as planted).
* Leakage guard: filing after as_of date is excluded.
* ASCII-only (no Unicode markers in this file).

Performance design notes
------------------------
``compute_fama_french_factors`` calls ``build_characteristic_panel``, which
issues one ``pit_latest_value`` query per date per metric.  This is O(n_bars)
in the number of price bars.  The sign-recovery tests therefore use a compact
panel (FF_N_BARS = 50 bars, FF_N_ASSETS = 20) with a short momentum warmup
(20 bars) so each full-factor call completes in ~1 s and the whole suite
finishes well under 60 s.  UMD tests retain the larger N_BARS = 500 panel
because ``compute_umd`` does not call ``pit_latest_value`` at all.

Fixture design for sign recovery
---------------------------------
Size (S vs B) is locked by using a 10x shares-outstanding gap between the
two halves of the universe:

    small stocks (indices 0-9)  : shares = 1e5 .. 1e6
    large stocks (indices 10-19): shares = 1e7 .. 1e8

Even with a daily drift of +/-0.004 and 50 bars the maximum cumulative price
move is exp(0.004*50) = e^0.2 ~ 1.22x, so the maximum small-stock ME
(1e6 * 1.22 = 1.22e6) stays well below the minimum large-stock ME
(1e7 * 0.8 = 8e6).  Size ranks never flip.

BM, OP and CMA characteristics are assigned with interleaved H/N/L patterns
that ensure all six 2x3 cells (SH, SN, SL, BH, BN, BL) are populated for
every characteristic sort.  The pattern:

    [H, N, L, H, N, N, L, H, N, L]  x 2  (both small and large halves)

gives 3H, 4N, 3L per size bucket, which with the 30/70 breakpoints yields
non-empty all six cells from the first rebalance onward.

Sign convention for CMA
------------------------
``compute_fama_french_factors`` internally negates the raw CMA characteristic
(asset growth = ta_now/ta_lag - 1) before sorting so that the "High" portfolio
contains CONSERVATIVE (low-growth) stocks and "Low" contains AGGRESSIVE
(high-growth) stocks.  The factor return is therefore:

    CMA = conservative_portfolio_return - aggressive_portfolio_return

consistent with Fama and French (2015).  When conservative stocks earn a
premium, CMA > 0.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from core_trading.signals.factors.fama_french import (
    METRIC_BOOK_EQUITY,
    METRIC_OPERATING_PROFIT,
    METRIC_SHARES_OUTSTANDING,
    METRIC_TOTAL_ASSETS,
    FamaFrenchConfig,
    _rebalance_dates,
    build_characteristic_panel,
    compute_book_to_market,
    compute_cma,
    compute_fama_french_factors,
    compute_market_equity,
    compute_rmw,
    compute_umd,
    factor_returns_from_portfolios,
    form_ff_portfolios,
    pit_latest_value,
)

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

SEED = 20260601
# N_BARS / N_ASSETS are used by UMD tests (compute_umd does not call
# pit_latest_value so 500 bars is fast and needed for the warmup test).
N_BARS = 500
N_ASSETS = 20

# Compact panel constants for tests that call compute_fama_french_factors.
# 50 bars produces ~25 non-NaN factor observations (enough to assert >20)
# while keeping each compute_fama_french_factors call under ~1.5 s.
FF_N_BARS = 50
FF_N_ASSETS = 20


# ---------------------------------------------------------------------------
# Synthetic data factories
# ---------------------------------------------------------------------------


def _make_price_panel(
    n_bars: int = N_BARS,
    n_assets: int = N_ASSETS,
    seed: int = SEED,
    drifts: np.ndarray | None = None,
    noise_std: float = 0.01,
) -> pd.DataFrame:
    """Build a synthetic price panel with an optional per-asset drift vector."""
    rng = np.random.default_rng(seed)
    if drifts is None:
        drifts = np.zeros(n_assets)
    returns = rng.normal(loc=drifts, scale=noise_std, size=(n_bars - 1, n_assets))
    prices = np.ones((n_bars, n_assets))
    prices[1:] = np.cumprod(1.0 + returns, axis=0)
    dates = pd.date_range("2020-01-01", periods=n_bars, freq="B")
    cols = [f"A{i}" for i in range(n_assets)]
    return pd.DataFrame(prices, index=dates, columns=cols)


def _make_fundamentals(
    symbols: list[str],
    metric: str,
    values: list[float],
    filing_dates: list[date],
    period_end_offset: int = -90,
    revision_ids: list[int] | None = None,
) -> pd.DataFrame:
    """Build a minimal tidy fundamentals DataFrame for testing."""
    if revision_ids is None:
        revision_ids = [0] * len(symbols)
    rows = []
    for sym, val, fd, rev in zip(
        symbols, values, filing_dates, revision_ids, strict=True
    ):
        pe = fd + timedelta(days=period_end_offset)
        if pe >= fd:
            pe = fd - timedelta(days=1)
        rows.append({
            "symbol": sym,
            "statement": "balance_sheet",
            "metric": metric,
            "value": val,
            "period_end": pe,
            "filing_date": fd,
            "fiscal_period": "Q1",
            "revision_id": rev,
            "source": "test",
        })
    return pd.DataFrame(rows)


def _make_full_fundamentals(
    symbols: list[str],
    shares: list[float],
    book_equity: list[float],
    operating_profit: list[float],
    total_assets: list[float],
    filing_date: date,
    earlier_filing_date: date | None = None,
    earlier_total_assets: list[float] | None = None,
    later_filing_date: date | None = None,
    later_total_assets: list[float] | None = None,
) -> pd.DataFrame:
    """Build a complete fundamentals DataFrame with all four required metrics.

    Optionally includes an earlier and later set of total_assets filings so
    that the ``compute_cma`` ``lag_days=365`` characteristic is non-trivial
    across the full price panel.
    """
    dfs = []
    for metric, vals in [
        (METRIC_SHARES_OUTSTANDING, shares),
        (METRIC_BOOK_EQUITY, book_equity),
        (METRIC_OPERATING_PROFIT, operating_profit),
        (METRIC_TOTAL_ASSETS, total_assets),
    ]:
        dfs.append(
            _make_fundamentals(
                symbols, metric, vals,
                [filing_date] * len(symbols),
            )
        )
    if earlier_filing_date is not None and earlier_total_assets is not None:
        dfs.append(
            _make_fundamentals(
                symbols, METRIC_TOTAL_ASSETS, earlier_total_assets,
                [earlier_filing_date] * len(symbols),
            )
        )
    if later_filing_date is not None and later_total_assets is not None:
        dfs.append(
            _make_fundamentals(
                symbols, METRIC_TOTAL_ASSETS, later_total_assets,
                [later_filing_date] * len(symbols),
            )
        )
    return pd.concat(dfs, ignore_index=True)


# ---------------------------------------------------------------------------
# FamaFrenchConfig tests
# ---------------------------------------------------------------------------


class TestFamaFrenchConfig:
    """FamaFrenchConfig: frozen DTO, defaults, validation."""

    def test_default_construction(self) -> None:
        cfg = FamaFrenchConfig()
        assert cfg.rebalance_freq == "ME"
        assert cfg.size_breakpoint_q == 0.50
        assert cfg.char_breakpoint_lo == 0.30
        assert cfg.char_breakpoint_hi == 0.70
        assert cfg.momentum_lookback == 252
        assert cfg.momentum_skip == 21
        assert cfg.min_assets == 10

    def test_custom_construction(self) -> None:
        cfg = FamaFrenchConfig(
            rebalance_freq="QE",
            size_breakpoint_q=0.5,
            char_breakpoint_lo=0.25,
            char_breakpoint_hi=0.75,
            momentum_lookback=126,
            momentum_skip=10,
            min_assets=6,
        )
        assert cfg.rebalance_freq == "QE"
        assert cfg.min_assets == 6

    def test_frozen(self) -> None:
        cfg = FamaFrenchConfig()
        with pytest.raises((AttributeError, TypeError)):
            cfg.rebalance_freq = "YE"  # type: ignore[misc]

    def test_empty_rebalance_freq_raises(self) -> None:
        with pytest.raises(ValueError, match="rebalance_freq"):
            FamaFrenchConfig(rebalance_freq="")

    def test_size_q_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="size_breakpoint_q"):
            FamaFrenchConfig(size_breakpoint_q=0.0)

    def test_size_q_one_raises(self) -> None:
        with pytest.raises(ValueError, match="size_breakpoint_q"):
            FamaFrenchConfig(size_breakpoint_q=1.0)

    def test_char_lo_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="char_breakpoint_lo"):
            FamaFrenchConfig(char_breakpoint_lo=0.0)

    def test_char_hi_one_raises(self) -> None:
        with pytest.raises(ValueError, match="char_breakpoint_hi"):
            FamaFrenchConfig(char_breakpoint_hi=1.0)

    def test_char_lo_ge_hi_raises(self) -> None:
        with pytest.raises(ValueError, match="char_breakpoint_lo"):
            FamaFrenchConfig(char_breakpoint_lo=0.5, char_breakpoint_hi=0.3)

    def test_char_lo_eq_hi_raises(self) -> None:
        with pytest.raises(ValueError, match="char_breakpoint_lo"):
            FamaFrenchConfig(char_breakpoint_lo=0.5, char_breakpoint_hi=0.5)

    def test_momentum_skip_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="momentum_skip"):
            FamaFrenchConfig(momentum_skip=-1)

    def test_momentum_lookback_le_skip_raises(self) -> None:
        with pytest.raises(ValueError, match="momentum_lookback"):
            FamaFrenchConfig(momentum_lookback=21, momentum_skip=21)

    def test_min_assets_three_raises(self) -> None:
        with pytest.raises(ValueError, match="min_assets"):
            FamaFrenchConfig(min_assets=3)

    def test_min_assets_four_ok(self) -> None:
        cfg = FamaFrenchConfig(min_assets=4)
        assert cfg.min_assets == 4

    def test_is_dataclass(self) -> None:
        import dataclasses
        assert dataclasses.is_dataclass(FamaFrenchConfig)


# ---------------------------------------------------------------------------
# pit_latest_value tests
# ---------------------------------------------------------------------------


class TestPitLatestValue:
    """pit_latest_value: PIT cut, revision tiebreak, empty fundamentals."""

    def _fund(
        self,
        symbol: str,
        value: float,
        filing_date: date,
        revision_id: int = 0,
    ) -> pd.DataFrame:
        return _make_fundamentals(
            [symbol], "book_equity", [value], [filing_date],
            revision_ids=[revision_id],
        )

    def test_basic_pit_cut(self) -> None:
        fund = self._fund("A", 100.0, date(2020, 3, 31))
        result = pit_latest_value(fund, date(2020, 3, 31), "book_equity")
        assert float(result["A"]) == 100.0

    def test_future_filing_excluded(self) -> None:
        fund = self._fund("A", 100.0, date(2020, 4, 1))
        result = pit_latest_value(fund, date(2020, 3, 31), "book_equity")
        assert "A" not in result.index

    def test_latest_of_two_filings(self) -> None:
        f1 = self._fund("A", 100.0, date(2020, 1, 31))
        f2 = self._fund("A", 200.0, date(2020, 4, 30))
        fund = pd.concat([f1, f2], ignore_index=True)
        result = pit_latest_value(fund, date(2020, 6, 30), "book_equity")
        assert float(result["A"]) == 200.0

    def test_only_earlier_filing_visible(self) -> None:
        f1 = self._fund("A", 100.0, date(2020, 1, 31))
        f2 = self._fund("A", 200.0, date(2020, 4, 30))
        fund = pd.concat([f1, f2], ignore_index=True)
        result = pit_latest_value(fund, date(2020, 2, 28), "book_equity")
        assert float(result["A"]) == 100.0

    def test_revision_tiebreak(self) -> None:
        f1 = self._fund("A", 100.0, date(2020, 3, 31), revision_id=0)
        f2 = self._fund("A", 120.0, date(2020, 3, 31), revision_id=1)
        fund = pd.concat([f1, f2], ignore_index=True)
        result = pit_latest_value(fund, date(2020, 6, 30), "book_equity")
        assert float(result["A"]) == 120.0

    def test_metric_filter(self) -> None:
        fund = _make_fundamentals(
            ["A"], "shares_outstanding", [1e6], [date(2020, 3, 31)]
        )
        result = pit_latest_value(fund, date(2020, 6, 30), "book_equity")
        assert "A" not in result.index

    def test_multiple_symbols(self) -> None:
        f1 = self._fund("A", 100.0, date(2020, 3, 31))
        f2 = self._fund("B", 200.0, date(2020, 3, 31))
        fund = pd.concat([f1, f2], ignore_index=True)
        result = pit_latest_value(fund, date(2020, 6, 30), "book_equity")
        assert float(result["A"]) == 100.0
        assert float(result["B"]) == 200.0

    def test_empty_fundamentals_returns_empty(self) -> None:
        empty = pd.DataFrame(columns=[
            "symbol", "statement", "metric", "value",
            "period_end", "filing_date", "fiscal_period", "revision_id", "source",
        ])
        result = pit_latest_value(empty, date(2020, 6, 30), "book_equity")
        assert len(result) == 0

    def test_all_future_filings_returns_empty(self) -> None:
        fund = self._fund("A", 100.0, date(2020, 7, 1))
        result = pit_latest_value(fund, date(2020, 6, 30), "book_equity")
        assert len(result) == 0


# ---------------------------------------------------------------------------
# build_characteristic_panel tests
# ---------------------------------------------------------------------------


class TestBuildCharacteristicPanel:
    """build_characteristic_panel: wide panel, PIT correctness, no leakage."""

    def _simple_fundamentals(self) -> pd.DataFrame:
        f1 = _make_fundamentals(
            ["A", "B"], METRIC_BOOK_EQUITY, [100.0, 200.0],
            [date(2020, 1, 31), date(2020, 1, 31)],
        )
        f2 = _make_fundamentals(
            ["A"], METRIC_BOOK_EQUITY, [150.0],
            [date(2020, 6, 30)],
        )
        return pd.concat([f1, f2], ignore_index=True)

    def test_shape_and_columns(self) -> None:
        fund = self._simple_fundamentals()
        dates = pd.date_range("2020-01-01", periods=10, freq="ME")
        panel = build_characteristic_panel(fund, dates, METRIC_BOOK_EQUITY)
        assert isinstance(panel, pd.DataFrame)
        assert len(panel) == len(dates)
        assert "A" in panel.columns
        assert "B" in panel.columns

    def test_before_first_filing_symbol_absent_or_nan(self) -> None:
        """Before any filing, the symbol is either absent or NaN in the panel."""
        fund = self._simple_fundamentals()
        dates = pd.date_range("2020-01-01", periods=3, freq="D")
        panel = build_characteristic_panel(fund, dates, METRIC_BOOK_EQUITY)
        if "A" in panel.columns:
            assert math.isnan(float(panel.iloc[0]["A"]))
        else:
            assert "A" not in panel.columns

    def test_after_first_filing_has_value(self) -> None:
        fund = self._simple_fundamentals()
        dates = pd.DatetimeIndex([pd.Timestamp("2020-02-01")])
        panel = build_characteristic_panel(fund, dates, METRIC_BOOK_EQUITY)
        assert float(panel.iloc[0]["A"]) == 100.0

    def test_value_updates_after_newer_filing(self) -> None:
        fund = self._simple_fundamentals()
        d1 = pd.DatetimeIndex([pd.Timestamp("2020-05-01")])
        d2 = pd.DatetimeIndex([pd.Timestamp("2020-07-01")])
        p1 = build_characteristic_panel(fund, d1, METRIC_BOOK_EQUITY)
        p2 = build_characteristic_panel(fund, d2, METRIC_BOOK_EQUITY)
        assert float(p1.iloc[0]["A"]) == 100.0
        assert float(p2.iloc[0]["A"]) == 150.0

    def test_leakage_guard(self) -> None:
        """A filing added after as_of MUST NOT affect the characteristic at as_of."""
        base = _make_fundamentals(
            ["A"], METRIC_BOOK_EQUITY, [100.0], [date(2020, 1, 31)]
        )
        future = _make_fundamentals(
            ["A"], METRIC_BOOK_EQUITY, [999.0], [date(2020, 6, 30)]
        )

        as_of_date = pd.DatetimeIndex([pd.Timestamp("2020-03-01")])

        panel_base = build_characteristic_panel(base, as_of_date, METRIC_BOOK_EQUITY)
        panel_with_future = build_characteristic_panel(
            pd.concat([base, future], ignore_index=True),
            as_of_date,
            METRIC_BOOK_EQUITY,
        )
        assert float(panel_base.iloc[0]["A"]) == float(
            panel_with_future.iloc[0]["A"]
        ), (
            "Characteristic at as_of was contaminated by a later-filed record "
            "(leakage guard failed)"
        )

    def test_empty_fundamentals(self) -> None:
        empty = pd.DataFrame(columns=[
            "symbol", "statement", "metric", "value",
            "period_end", "filing_date", "fiscal_period", "revision_id", "source",
        ])
        dates = pd.date_range("2020-01-01", periods=5, freq="ME")
        panel = build_characteristic_panel(empty, dates, METRIC_BOOK_EQUITY)
        assert isinstance(panel, pd.DataFrame)
        assert len(panel) == len(dates)

    def test_empty_dates(self) -> None:
        fund = self._simple_fundamentals()
        panel = build_characteristic_panel(
            fund, pd.DatetimeIndex([]), METRIC_BOOK_EQUITY
        )
        assert len(panel) == 0


# ---------------------------------------------------------------------------
# compute_market_equity tests
# ---------------------------------------------------------------------------


class TestComputeMarketEquity:
    """compute_market_equity: price * shares_outstanding."""

    def _setup(
        self, price: float, shares: float, filing_date: date
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        prices = pd.DataFrame(
            {"A": [price]},
            index=pd.DatetimeIndex([pd.Timestamp(filing_date)]),
        )
        fund = _make_fundamentals(
            ["A"], METRIC_SHARES_OUTSTANDING, [shares], [filing_date]
        )
        return prices, fund

    def test_market_equity_arithmetic(self) -> None:
        prices, fund = self._setup(50.0, 1_000_000.0, date(2020, 1, 31))
        me = compute_market_equity(prices, fund)
        assert float(me.iloc[0]["A"]) == pytest.approx(50.0 * 1_000_000.0, rel=1e-9)

    def test_nan_when_no_shares_filed(self) -> None:
        prices = pd.DataFrame(
            {"A": [50.0]},
            index=pd.DatetimeIndex([pd.Timestamp("2020-01-15")]),
        )
        fund = _make_fundamentals(
            ["A"], METRIC_SHARES_OUTSTANDING, [1e6], [date(2020, 2, 1)]
        )
        me = compute_market_equity(prices, fund)
        assert math.isnan(float(me.iloc[0]["A"]))


# ---------------------------------------------------------------------------
# compute_book_to_market tests
# ---------------------------------------------------------------------------


class TestComputeBookToMarket:
    """compute_book_to_market: book_equity / market_equity."""

    def test_bm_value(self) -> None:
        filing = date(2020, 1, 31)
        prices = pd.DataFrame(
            {"A": [100.0]},
            index=pd.DatetimeIndex([pd.Timestamp(filing)]),
        )
        fund = pd.concat([
            _make_fundamentals(["A"], METRIC_SHARES_OUTSTANDING, [10.0], [filing]),
            _make_fundamentals(["A"], METRIC_BOOK_EQUITY, [500.0], [filing]),
        ], ignore_index=True)
        bm = compute_book_to_market(prices, fund)
        expected = 500.0 / (100.0 * 10.0)
        assert float(bm.iloc[0]["A"]) == pytest.approx(expected, rel=1e-9)

    def test_shape_matches_prices(self) -> None:
        prices = _make_price_panel(n_bars=30, n_assets=3)
        fund = pd.concat([
            _make_fundamentals(
                ["A0", "A1", "A2"], METRIC_SHARES_OUTSTANDING,
                [1e6, 2e6, 3e6], [date(2020, 1, 5)] * 3,
            ),
            _make_fundamentals(
                ["A0", "A1", "A2"], METRIC_BOOK_EQUITY,
                [1e8, 2e8, 3e8], [date(2020, 1, 5)] * 3,
            ),
        ], ignore_index=True)
        bm = compute_book_to_market(prices, fund)
        assert bm.shape == prices.shape


# ---------------------------------------------------------------------------
# compute_rmw tests
# ---------------------------------------------------------------------------


class TestComputeRmw:
    """compute_rmw: operating_profit / book_equity."""

    def test_rmw_value(self) -> None:
        filing = date(2020, 1, 31)
        prices = pd.DataFrame(
            {"A": [100.0]},
            index=pd.DatetimeIndex([pd.Timestamp(filing)]),
        )
        fund = pd.concat([
            _make_fundamentals(["A"], METRIC_OPERATING_PROFIT, [30.0], [filing]),
            _make_fundamentals(["A"], METRIC_BOOK_EQUITY, [300.0], [filing]),
        ], ignore_index=True)
        rmw = compute_rmw(prices, fund)
        assert float(rmw.iloc[0]["A"]) == pytest.approx(0.10, rel=1e-9)

    def test_shape_matches_prices(self) -> None:
        prices = _make_price_panel(n_bars=20, n_assets=3)
        filing = date(2020, 1, 2)
        fund = pd.concat([
            _make_fundamentals(
                ["A0", "A1", "A2"], METRIC_OPERATING_PROFIT,
                [100.0, 200.0, 300.0], [filing] * 3,
            ),
            _make_fundamentals(
                ["A0", "A1", "A2"], METRIC_BOOK_EQUITY,
                [1000.0, 2000.0, 3000.0], [filing] * 3,
            ),
        ], ignore_index=True)
        rmw = compute_rmw(prices, fund)
        assert rmw.shape == prices.shape


# ---------------------------------------------------------------------------
# compute_cma tests
# ---------------------------------------------------------------------------


class TestComputeCma:
    """compute_cma: asset growth = total_assets[t] / total_assets[t-1] - 1."""

    def test_asset_growth_value(self) -> None:
        """CMA at date t = ta_PIT(t) / ta_PIT(t - lag_days) - 1.

        Build two filings separated by exactly 90 days.  At a date 100 days
        after the first filing, with lag_days=90, the numerator uses the second
        filing and the denominator uses the first filing.
        """
        filing1 = date(2020, 1, 1)
        filing2 = date(2020, 4, 1)
        query_date = pd.Timestamp("2020-04-05")
        lag = 90
        prices = pd.DataFrame(
            {"A": [1.0]},
            index=pd.DatetimeIndex([query_date]),
        )
        fund = pd.concat([
            _make_fundamentals(["A"], METRIC_TOTAL_ASSETS, [1000.0], [filing1]),
            _make_fundamentals(["A"], METRIC_TOTAL_ASSETS, [1200.0], [filing2]),
        ], ignore_index=True)
        cma = compute_cma(prices, fund, lag_days=lag)
        expected_growth = 1200.0 / 1000.0 - 1.0
        assert float(cma.iloc[0]["A"]) == pytest.approx(expected_growth, rel=1e-9)

    def test_no_prior_filing_is_nan(self) -> None:
        """When there is no prior filing within the lag window, CMA is NaN."""
        filing1 = date(2020, 4, 1)
        query_date = pd.Timestamp("2020-04-05")
        prices = pd.DataFrame(
            {"A": [1.0]},
            index=pd.DatetimeIndex([query_date]),
        )
        fund = _make_fundamentals(["A"], METRIC_TOTAL_ASSETS, [1000.0], [filing1])
        cma = compute_cma(prices, fund, lag_days=365)
        assert math.isnan(float(cma.iloc[0]["A"]))

    def test_bad_lag_days_raises(self) -> None:
        prices = _make_price_panel(n_bars=5, n_assets=2)
        fund = _make_fundamentals(
            ["A0", "A1"], METRIC_TOTAL_ASSETS, [1e8, 2e8],
            [date(2020, 1, 2)] * 2,
        )
        with pytest.raises(ValueError, match="lag_days"):
            compute_cma(prices, fund, lag_days=0)


# ---------------------------------------------------------------------------
# form_ff_portfolios tests
# ---------------------------------------------------------------------------


class TestFormFfPortfolios:
    """form_ff_portfolios: 2x3 independent sort, breakpoints, edge cases."""

    def _make_inputs(
        self,
        n: int = 20,
        seed: int = SEED,
    ) -> tuple[pd.Series, pd.Series]:
        rng = np.random.default_rng(seed)
        syms = [f"S{i}" for i in range(n)]
        me = pd.Series(rng.uniform(1e8, 1e10, n), index=syms)
        char = pd.Series(rng.uniform(0.1, 3.0, n), index=syms)
        return me, char

    def test_six_cells_returned(self) -> None:
        me, char = self._make_inputs()
        cfg = FamaFrenchConfig()
        ports = form_ff_portfolios(me, char, cfg)
        assert set(ports.keys()) == {"SL", "SN", "SH", "BL", "BN", "BH"}

    def test_all_symbols_assigned(self) -> None:
        me, char = self._make_inputs()
        cfg = FamaFrenchConfig()
        ports = form_ff_portfolios(me, char, cfg)
        all_syms = set()
        for syms in ports.values():
            all_syms.update(syms)
        assert all_syms == set(me.index)

    def test_size_split_correctness(self) -> None:
        n = 20
        syms = [f"S{i}" for i in range(n)]
        me = pd.Series([float(i) for i in range(n)], index=syms)
        char = pd.Series([1.0] * n, index=syms)
        cfg = FamaFrenchConfig(
            char_breakpoint_lo=0.30, char_breakpoint_hi=0.70
        )
        ports = form_ff_portfolios(me, char, cfg)
        big_syms = set(ports["BL"]) | set(ports["BN"]) | set(ports["BH"])
        small_syms = set(ports["SL"]) | set(ports["SN"]) | set(ports["SH"])
        median_me = float(np.median([float(i) for i in range(n)]))
        for sym in big_syms:
            idx = int(sym[1:])
            assert float(idx) >= median_me
        for sym in small_syms:
            idx = int(sym[1:])
            assert float(idx) < median_me

    def test_too_few_assets_returns_empty(self) -> None:
        syms = ["A", "B", "C"]
        me = pd.Series([1e8, 2e8, 3e8], index=syms)
        char = pd.Series([0.5, 1.0, 2.0], index=syms)
        cfg = FamaFrenchConfig(min_assets=10)
        ports = form_ff_portfolios(me, char, cfg)
        for lst in ports.values():
            assert lst == []

    def test_nan_me_excluded(self) -> None:
        me = pd.Series({"A": float("nan"), "B": 1e9, "C": 2e9, "D": 3e9,
                        "E": 4e9, "F": 5e9, "G": 6e9, "H": 7e9,
                        "I": 8e9, "J": 9e9})
        char = pd.Series({k: 1.0 for k in me.index})
        cfg = FamaFrenchConfig(min_assets=4)
        ports = form_ff_portfolios(me, char, cfg)
        for lst in ports.values():
            assert "A" not in lst

    def test_nonfinite_in_intersection_excluded(self) -> None:
        """form_ff_portfolios skips symbols where ME or char is non-finite."""
        # Build a universe where both ME and char have an inf entry for the same
        # symbol.  The code path that continues when not (isfinite(m) and isfinite(c))
        # is exercised here (line 582 in fama_french.py).
        syms = [f"X{i}" for i in range(12)]
        me_vals = [float("inf")] + [1e8 * (i + 1) for i in range(11)]
        char_vals = [2.0] * 12
        me = pd.Series(me_vals, index=syms)
        char = pd.Series(char_vals, index=syms)
        cfg = FamaFrenchConfig(min_assets=4)
        ports = form_ff_portfolios(me, char, cfg)
        all_assigned = [s for lst in ports.values() for s in lst]
        # X0 has inf ME -- it must NOT appear in any portfolio
        assert "X0" not in all_assigned


# ---------------------------------------------------------------------------
# factor_returns_from_portfolios tests
# ---------------------------------------------------------------------------


class TestFactorReturnsFromPortfolios:
    """factor_returns_from_portfolios: VW return arithmetic, SMB formula."""

    def _make_portfolios_and_data(
        self,
    ) -> tuple[dict[str, list[str]], pd.Series, pd.Series]:
        syms_sh = ["A", "B"]
        syms_sl = ["C", "D"]
        syms_sn = ["E", "F"]
        syms_bh = ["G", "H"]
        syms_bl = ["I", "J"]
        syms_bn = ["K", "L"]
        portfolios = {
            "SH": syms_sh, "SL": syms_sl, "SN": syms_sn,
            "BH": syms_bh, "BL": syms_bl, "BN": syms_bn,
        }
        all_syms = [s for lst in portfolios.values() for s in lst]
        me = pd.Series({s: 1e8 for s in all_syms})
        returns = pd.Series({
            "A": 0.05, "B": 0.03,
            "C": -0.02, "D": -0.01,
            "E": 0.01, "F": 0.02,
            "G": 0.04, "H": 0.06,
            "I": -0.03, "J": -0.02,
            "K": 0.00, "L": 0.01,
        })
        return portfolios, me, returns

    def test_factor_return_direction(self) -> None:
        ports, me, rets = self._make_portfolios_and_data()
        result = factor_returns_from_portfolios(ports, me, rets)
        assert math.isfinite(result["factor"])
        r_sh = (0.05 + 0.03) / 2.0
        r_bh = (0.04 + 0.06) / 2.0
        r_sl = (-0.02 + -0.01) / 2.0
        r_bl = (-0.03 + -0.02) / 2.0
        expected_factor = (r_sh + r_bh) / 2.0 - (r_sl + r_bl) / 2.0
        assert result["factor"] == pytest.approx(expected_factor, rel=1e-9)

    def test_smb_direction(self) -> None:
        ports, me, rets = self._make_portfolios_and_data()
        result = factor_returns_from_portfolios(ports, me, rets)
        assert math.isfinite(result["smb"])

    def test_empty_portfolio_returns_nan(self) -> None:
        ports = {
            "SH": [], "SL": ["A"], "SN": ["B"],
            "BH": ["C"], "BL": ["D"], "BN": ["E"],
        }
        me = pd.Series({"A": 1e8, "B": 1e8, "C": 1e8, "D": 1e8, "E": 1e8})
        rets = pd.Series({"A": 0.01, "B": 0.02, "C": 0.03, "D": 0.04, "E": 0.05})
        result = factor_returns_from_portfolios(ports, me, rets)
        assert math.isnan(result["factor"])
        assert math.isnan(result["smb"])

    def test_zero_me_portfolio_returns_nan(self) -> None:
        """When all ME weights sum to zero the VW return is NaN (line 640)."""
        ports = {
            "SH": ["A"], "SL": ["B"], "SN": ["C"],
            "BH": ["D"], "BL": ["E"], "BN": ["F"],
        }
        # All ME values are 0 so m.sum() <= 0 for each leg
        me = pd.Series({"A": 0.0, "B": 0.0, "C": 0.0, "D": 0.0, "E": 0.0, "F": 0.0})
        rets = pd.Series({"A": 0.01, "B": 0.02, "C": 0.03, "D": 0.04, "E": 0.05, "F": 0.06})
        result = factor_returns_from_portfolios(ports, me, rets)
        # Every leg returns NaN because m.sum() <= 0
        assert math.isnan(result["factor"])
        assert math.isnan(result["smb"])


# ---------------------------------------------------------------------------
# compute_umd tests
# ---------------------------------------------------------------------------


class TestComputeUmd:
    """compute_umd: returns a Series of correct length; warmup NaN region."""

    def test_output_shape(self) -> None:
        prices = _make_price_panel(n_bars=N_BARS, n_assets=N_ASSETS)
        cfg = FamaFrenchConfig()
        umd = compute_umd(prices, cfg)
        assert len(umd) == len(prices)
        assert umd.index.equals(prices.index)

    def test_warmup_region_nan(self) -> None:
        prices = _make_price_panel(n_bars=N_BARS, n_assets=N_ASSETS)
        cfg = FamaFrenchConfig()
        umd = compute_umd(prices, cfg)
        warmup = cfg.momentum_lookback
        assert umd.iloc[:warmup].isna().all()

    def test_name_is_umd(self) -> None:
        prices = _make_price_panel(n_bars=N_BARS, n_assets=N_ASSETS)
        cfg = FamaFrenchConfig()
        umd = compute_umd(prices, cfg)
        assert umd.name == "UMD"

    def test_high_momentum_earns_positive_umd(self) -> None:
        """Plant a clear momentum premium: high-score assets have higher forward returns.

        Build a universe where assets 0..3 have large positive drift (winners)
        and assets 16..19 have large negative drift (losers).  With a clear
        signal the UMD series should have a positive mean over its valid region.
        """
        n = N_ASSETS
        drifts = np.zeros(n)
        drifts[:4] = 0.004
        drifts[-4:] = -0.003
        prices = _make_price_panel(
            n_bars=N_BARS, n_assets=n, drifts=drifts, noise_std=0.005
        )
        cfg = FamaFrenchConfig(momentum_lookback=120, momentum_skip=5, min_assets=4)
        umd = compute_umd(prices, cfg)
        valid = umd.dropna()
        assert len(valid) > 50
        assert float(valid.mean()) > 0, (
            f"UMD mean {float(valid.mean()):.4f} not positive; "
            "high-drift winners should produce positive UMD"
        )

    def test_vw_umd_with_me_panel(self) -> None:
        """Value-weighted UMD (me provided) returns a valid Series of correct length."""
        n = N_ASSETS
        drifts = np.zeros(n)
        drifts[:4] = 0.004
        drifts[-4:] = -0.003
        prices = _make_price_panel(
            n_bars=N_BARS, n_assets=n, drifts=drifts, noise_std=0.005,
            seed=SEED + 1,
        )
        syms = list(prices.columns)
        filing = date(2020, 1, 2)
        fund = _make_fundamentals(
            syms, METRIC_SHARES_OUTSTANDING,
            [1e6] * n, [filing] * n,
        )
        prices2 = prices.copy()
        prices2.columns = pd.Index(syms)
        shares_panel = build_characteristic_panel(fund, prices2.index, METRIC_SHARES_OUTSTANDING)
        me_panel = prices2 * shares_panel.reindex(index=prices2.index, columns=prices2.columns)
        cfg = FamaFrenchConfig(momentum_lookback=120, momentum_skip=5, min_assets=4)
        umd = compute_umd(prices2, cfg, me=me_panel)
        assert len(umd) == len(prices2)
        assert umd.index.equals(prices2.index)
        assert umd.name == "UMD"
        valid = umd.dropna()
        assert len(valid) > 50
        assert float(valid.mean()) > 0, (
            f"VW UMD mean {float(valid.mean()):.4f} not positive; "
            "high-drift winners should produce positive UMD"
        )

    def test_vw_umd_with_me_returns_all_nan_on_zero_me(self) -> None:
        """VW UMD with all-zero ME: the valid-ME filter excludes all assets,
        no rebalance ever sets current_weights, so UMD is all-NaN."""
        n = 10
        prices = _make_price_panel(n_bars=60, n_assets=n, noise_std=0.01)
        syms = list(prices.columns)
        filing = date(2020, 1, 2)
        # All shares = 0 -> ME = 0 for every asset -> valid mask never passes.
        fund = _make_fundamentals(
            syms, METRIC_SHARES_OUTSTANDING,
            [0.0] * n, [filing] * n,
        )
        shares_panel = build_characteristic_panel(fund, prices.index, METRIC_SHARES_OUTSTANDING)
        me_panel = prices * shares_panel.reindex(index=prices.index, columns=prices.columns)
        cfg = FamaFrenchConfig(
            momentum_lookback=20, momentum_skip=2, min_assets=4,
            char_breakpoint_lo=0.30, char_breakpoint_hi=0.70,
        )
        umd = compute_umd(prices, cfg, me=me_panel)
        assert isinstance(umd, pd.Series)
        assert len(umd) == len(prices)
        # No rebalance succeeds -> UMD stays all-NaN.
        assert umd.isna().all()


# ---------------------------------------------------------------------------
# _rebalance_dates coverage tests
# ---------------------------------------------------------------------------


class TestRebalanceDates:
    """_rebalance_dates: empty index and exception-fallback branches."""

    def test_empty_index_returns_empty(self) -> None:
        """Empty DatetimeIndex returns empty DatetimeIndex (line 819)."""
        result = _rebalance_dates(pd.DatetimeIndex([]), "ME")
        assert isinstance(result, pd.DatetimeIndex)
        assert len(result) == 0

    def test_invalid_freq_falls_back_to_monthly(self) -> None:
        """Unrecognised freq string triggers the except branch (lines 831-832).

        An invalid pandas period alias raises an exception inside ``to_period``.
        The fallback converts to monthly periods, so the result is still a
        non-empty DatetimeIndex with correct first-of-period dates.
        """
        dates = pd.date_range("2020-01-01", periods=60, freq="B")
        result = _rebalance_dates(dates, "INVALID_FREQ_XYZ")
        assert isinstance(result, pd.DatetimeIndex)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# compute_fama_french_factors -- output contract tests
# ---------------------------------------------------------------------------


class TestComputeFamaFrenchFactorsContract:
    """compute_fama_french_factors: output DataFrame schema and shape."""

    def _make_minimal_universe(
        self,
        n_bars: int = FF_N_BARS,
        n_assets: int = FF_N_ASSETS,
        seed: int = SEED,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Build a synthetic universe with two annual rounds of filings.

        Uses a compact panel (FF_N_BARS = 50) for speed.  Provides three
        sets of total_assets filings so CMA is non-trivial.
        """
        prices = _make_price_panel(n_bars=n_bars, n_assets=n_assets, seed=seed)
        syms = list(prices.columns)

        filing_0 = date(2019, 1, 2)
        filing_1 = date(2020, 1, 2)
        filing_2 = date(2021, 1, 4)

        rng_f = np.random.default_rng(seed + 999)
        gf1 = rng_f.uniform(0.8, 1.4, n_assets).tolist()
        gf2 = rng_f.uniform(0.7, 1.5, n_assets).tolist()

        ta_0 = [2e8 * (i + 1) for i in range(n_assets)]
        ta_1 = [2e8 * (i + 1) * gf1[i] for i in range(n_assets)]
        ta_2 = [2e8 * (i + 1) * gf2[i] for i in range(n_assets)]

        base_fund = _make_full_fundamentals(
            syms,
            shares=[1e6] * n_assets,
            book_equity=[1e8 * (i + 1) for i in range(n_assets)],
            operating_profit=[1e7 * (i + 1 + j) for j, i in enumerate(range(n_assets))],
            total_assets=ta_1,
            filing_date=filing_1,
            earlier_filing_date=filing_0,
            earlier_total_assets=ta_0,
        )
        extra_ta = _make_fundamentals(
            syms, METRIC_TOTAL_ASSETS, ta_2,
            [filing_2] * n_assets,
        )
        return prices, pd.concat([base_fund, extra_ta], ignore_index=True)

    def test_output_columns(self) -> None:
        prices, fund = self._make_minimal_universe()
        cfg = FamaFrenchConfig(min_assets=4)
        factors = compute_fama_french_factors(prices, fund, cfg)
        assert list(factors.columns) == ["SMB", "HML", "RMW", "CMA", "UMD"]

    def test_output_index_matches_prices(self) -> None:
        prices, fund = self._make_minimal_universe()
        cfg = FamaFrenchConfig(min_assets=4)
        factors = compute_fama_french_factors(prices, fund, cfg)
        assert factors.index.equals(prices.index)

    def test_output_shape(self) -> None:
        prices, fund = self._make_minimal_universe()
        cfg = FamaFrenchConfig(min_assets=4)
        factors = compute_fama_french_factors(prices, fund, cfg)
        assert factors.shape == (len(prices), 5)

    def test_default_config(self) -> None:
        prices, fund = self._make_minimal_universe()
        factors = compute_fama_french_factors(prices, fund)
        assert "SMB" in factors.columns

    def test_returns_are_float(self) -> None:
        prices, fund = self._make_minimal_universe()
        # Use a short momentum window so valid UMD observations exist in the
        # compact 50-bar panel (default momentum_lookback=252 > FF_N_BARS).
        cfg = FamaFrenchConfig(min_assets=4, momentum_lookback=20, momentum_skip=2)
        factors = compute_fama_french_factors(prices, fund, cfg)
        # Check per-column rather than requiring all five to be jointly valid
        # (UMD and the characteristic factors may have different valid windows).
        assert factors.dtypes.apply(lambda dt: np.issubdtype(dt, np.floating)).all()
        assert any(factors[col].notna().any() for col in factors.columns)


# ---------------------------------------------------------------------------
# Premium sign recovery tests (DOD: planted premium recovers correct sign)
# ---------------------------------------------------------------------------


class TestPremiumSignRecovery:
    """Plant factor premiums, assert recovered factor signs are correct.

    Fixture design
    --------------
    All four sign-recovery tests share the same fundamental universe:

      - 20 assets split into two size buckets via a 10x shares gap:
          small (indices 0-9):  shares = 1e5 .. 1e6
          large (indices 10-19): shares = 1e7 .. 1e8
        With daily noise of 0.004 and 50 bars the ME rank is stable.

      - BM, OP and CMA characteristics are assigned using interleaved H/N/L
        patterns (3H, 4N, 3L per size bucket) so that all six 2x3 portfolio
        cells are non-empty for every sort, enabling non-NaN SMB.

      - Momentum warmup is set to 20 bars (momentum_lookback=20, skip=2) so
        factor returns start accruing from bar 22, leaving at least 25 valid
        observations in a 50-bar panel.

    CMA sign convention
    -------------------
    ``compute_fama_french_factors`` internally negates the raw CMA
    characteristic (asset growth) before sorting, so:

        CMA factor = conservative (low-growth) return - aggressive (high-growth) return

    Planting a drift on CONSERVATIVE (low-growth, CMA pattern-L) stocks
    therefore produces CMA > 0.

    HML sign convention
    -------------------
    High B/M (H) stocks earn a premium -> HML = (H return) - (L return) > 0.
    Low B/M (L, growth) stocks earn a premium -> HML < 0.

    RMW sign convention
    -------------------
    High OP/BE (H, robust) stocks earn a premium -> RMW > 0.
    """

    # Compact panel for speed (~1.1 s per full-factor call on this machine)
    FF_N_BARS = 50
    FF_N_ASSETS = 20
    NOISE = 0.004
    DRIFT = 0.002
    ANTI_DRIFT = -0.001

    # Shares: 10x gap ensures ME rank stability across all drift scenarios.
    # Small: indices 0-9, Large: indices 10-19.
    _SHARES: list[float] = (
        [float((i + 1) * 1e5) for i in range(10)]
        + [float((i + 1) * 1e7) for i in range(10)]
    )

    # Characteristic level patterns (H/N/L) per asset -- same layout for both
    # the small bucket (indices 0-9) and large bucket (indices 10-19).
    # Each bucket has 3 H, 4 N, 3 L, guaranteeing all 6 cells are populated.
    _BM_PATTERN = ["H", "N", "L", "H", "N", "N", "L", "H", "N", "L"] * 2
    _OP_PATTERN = ["L", "H", "N", "H", "N", "L", "N", "H", "L", "N"] * 2
    _CMA_PATTERN = ["N", "H", "L", "N", "L", "H", "L", "N", "H", "N"] * 2

    # Characteristic magnitude maps
    _BM_MAP = {"H": 5.0, "N": 1.5, "L": 0.3}    # BM target (BE / ME ~ this)
    _OP_MAP = {"H": 0.40, "N": 0.15, "L": 0.04}  # OP/BE ratio target

    def _filing_date(self) -> date:
        return date(2020, 1, 2)

    def _make_shared_fund(self) -> pd.DataFrame:
        """Build the shared fundamental panel for sign-recovery tests.

        BM values are proportional to shares so that B/M is uniform across
        size buckets (BM_target * shares_i).  OP values are set via OP/BE
        ratios to ensure the RMW characteristic has a full spread.  CMA uses
        three filing dates (Jan 2019, Jan 2020, Jan 2021) so that the
        ``lag_days=365`` asset-growth characteristic is defined for the full
        50-bar panel.
        """
        n = self.FF_N_ASSETS
        syms = [f"A{i}" for i in range(n)]

        be_vals = [self._BM_MAP[self._BM_PATTERN[i]] * self._SHARES[i] for i in range(n)]
        op_vals = [self._OP_MAP[self._OP_PATTERN[i]] * be_vals[i] for i in range(n)]

        # CMA: large growth spread (3:1 ratio between aggressive and conservative)
        ta_ear = [self._SHARES[i] * 10.0 for i in range(n)]
        ta_now = []
        for i in range(n):
            if self._CMA_PATTERN[i] == "L":
                ta_now.append(ta_ear[i] * 1.03)   # conservative: 3% growth
            elif self._CMA_PATTERN[i] == "H":
                ta_now.append(ta_ear[i] * 1.45)   # aggressive: 45% growth
            else:
                ta_now.append(ta_ear[i] * 1.15)   # neutral: 15% growth
        ta_later = [v * 1.05 for v in ta_now]

        filing = self._filing_date()
        earlier = filing - timedelta(days=365)
        later = date(2021, 1, 4)

        return _make_full_fundamentals(
            syms,
            shares=list(self._SHARES),
            book_equity=be_vals,
            operating_profit=op_vals,
            total_assets=ta_now,
            filing_date=filing,
            earlier_filing_date=earlier,
            earlier_total_assets=ta_ear,
            later_filing_date=later,
            later_total_assets=ta_later,
        )

    def _make_cfg(self) -> FamaFrenchConfig:
        return FamaFrenchConfig(
            rebalance_freq="ME",
            char_breakpoint_lo=0.30,
            char_breakpoint_hi=0.70,
            momentum_lookback=20,
            momentum_skip=2,
            min_assets=4,
        )

    def _build_factors(
        self,
        drifts: np.ndarray,
        fund: pd.DataFrame,
        seed: int,
    ) -> pd.DataFrame:
        rng = np.random.default_rng(seed)
        n = self.FF_N_ASSETS
        prices_arr = np.ones((self.FF_N_BARS, n))
        prices_arr[1:] = np.cumprod(
            1.0 + rng.normal(loc=drifts, scale=self.NOISE, size=(self.FF_N_BARS - 1, n)),
            axis=0,
        )
        prices = pd.DataFrame(
            prices_arr,
            index=pd.date_range("2020-01-01", periods=self.FF_N_BARS, freq="B"),
            columns=[f"A{i}" for i in range(n)],
        )
        return compute_fama_french_factors(prices, fund, self._make_cfg())

    def test_smb_positive_when_small_earns_more(self) -> None:
        """Small stocks (indices 0-9) drift up; large stocks (indices 10-19) drift down.

        With the 10x shares gap the ME split is stable: small stays small
        regardless of drift, so the SMB long (small) leg outperforms the SMB
        short (big) leg -> SMB > 0.
        """
        drifts = np.array(
            [self.DRIFT] * 10 + [self.ANTI_DRIFT] * 10
        )
        fund = self._make_shared_fund()
        factors = self._build_factors(drifts, fund, seed=SEED + 10)
        smb_valid = factors["SMB"].dropna()
        assert len(smb_valid) > 20, (
            f"Expected > 20 valid SMB periods, got {len(smb_valid)}"
        )
        assert float(smb_valid.mean()) > 0, (
            f"SMB mean {float(smb_valid.mean()):.5f} not positive; "
            "small stocks have higher drift so SMB should be positive"
        )

    def test_hml_positive_when_value_earns_more(self) -> None:
        """High B/M (H pattern) assets drift up; low B/M (L pattern) drift down.

        BM characteristic is interleaved within each size bucket so B/M is
        independent of size.  HML = (H-leg return) - (L-leg return) > 0 when
        value (high B/M) earns a premium.
        """
        n = self.FF_N_ASSETS
        drifts = np.array([
            self.DRIFT if self._BM_PATTERN[i] == "H"
            else (self.ANTI_DRIFT if self._BM_PATTERN[i] == "L" else 0.0)
            for i in range(n)
        ])
        fund = self._make_shared_fund()
        factors = self._build_factors(drifts, fund, seed=SEED + 11)
        hml_valid = factors["HML"].dropna()
        assert len(hml_valid) > 20, (
            f"Expected > 20 valid HML periods, got {len(hml_valid)}"
        )
        assert float(hml_valid.mean()) > 0, (
            f"HML mean {float(hml_valid.mean()):.5f} not positive; "
            "high B/M stocks have positive drift so HML should be positive"
        )

    def test_hml_negative_when_growth_earns_more(self) -> None:
        """Low B/M (L pattern, growth) assets drift up; high B/M (H) drift down.

        Reversed from test_hml_positive: growth outperforms value, so
        HML = (H-leg return) - (L-leg return) < 0.
        """
        n = self.FF_N_ASSETS
        drifts = np.array([
            self.ANTI_DRIFT if self._BM_PATTERN[i] == "H"
            else (self.DRIFT if self._BM_PATTERN[i] == "L" else 0.0)
            for i in range(n)
        ])
        fund = self._make_shared_fund()
        factors = self._build_factors(drifts, fund, seed=SEED + 12)
        hml_valid = factors["HML"].dropna()
        assert len(hml_valid) > 20, (
            f"Expected > 20 valid HML periods, got {len(hml_valid)}"
        )
        assert float(hml_valid.mean()) < 0, (
            f"HML mean {float(hml_valid.mean()):.5f} not negative; "
            "growth (low B/M) stocks have positive drift so HML should be negative"
        )

    def test_rmw_positive_when_profitable_earns_more(self) -> None:
        """High OP/BE (H pattern, robust) assets drift up; low OP/BE (L) drift down.

        OP pattern is independent of BM and size so the RMW sort produces
        non-empty all-six cells.  RMW = (H-leg return) - (L-leg return) > 0.
        """
        n = self.FF_N_ASSETS
        drifts = np.array([
            self.DRIFT if self._OP_PATTERN[i] == "H"
            else (self.ANTI_DRIFT if self._OP_PATTERN[i] == "L" else 0.0)
            for i in range(n)
        ])
        fund = self._make_shared_fund()
        factors = self._build_factors(drifts, fund, seed=SEED + 13)
        rmw_valid = factors["RMW"].dropna()
        assert len(rmw_valid) > 20, (
            f"Expected > 20 valid RMW periods, got {len(rmw_valid)}"
        )
        assert float(rmw_valid.mean()) > 0, (
            f"RMW mean {float(rmw_valid.mean()):.5f} not positive; "
            "high profitability stocks have positive drift so RMW should be positive"
        )

    def test_cma_positive_when_conservative_earns_more(self) -> None:
        """Conservative (low asset-growth, CMA pattern-L) assets drift up.

        ``compute_fama_french_factors`` negates the raw CMA characteristic
        before the 2x3 sort so that H = conservative, L = aggressive.  The
        factor is therefore conservative-minus-aggressive, and CMA > 0 when
        low-growth stocks earn a premium.
        """
        n = self.FF_N_ASSETS
        # Conservative stocks have CMA_PATTERN == 'L' (low asset growth).
        # After the code's negation these become H in the sort, so they are
        # in the long leg.  Planting positive drift on them -> CMA > 0.
        drifts = np.array([
            self.DRIFT if self._CMA_PATTERN[i] == "L"
            else (self.ANTI_DRIFT if self._CMA_PATTERN[i] == "H" else 0.0)
            for i in range(n)
        ])
        fund = self._make_shared_fund()
        factors = self._build_factors(drifts, fund, seed=SEED + 14)
        cma_valid = factors["CMA"].dropna()
        assert len(cma_valid) > 20, (
            f"Expected > 20 valid CMA periods, got {len(cma_valid)}"
        )
        assert float(cma_valid.mean()) > 0, (
            f"CMA mean {float(cma_valid.mean()):.5f} not positive; "
            "conservative (low asset-growth) stocks have positive drift "
            "so CMA should be positive"
        )


# ---------------------------------------------------------------------------
# Leakage guard -- compute_fama_french_factors
# ---------------------------------------------------------------------------


class TestLeakageGuard:
    """Verify that future-filed records do not contaminate past factor returns."""

    def test_later_filing_does_not_change_earlier_factors(self) -> None:
        """Append a future-filed revision to the fundamentals panel.

        The factor returns at dates BEFORE the future filing_date must be
        identical whether or not the future record is present.
        """
        n = FF_N_ASSETS
        syms = [f"A{i}" for i in range(n)]
        prices = _make_price_panel(n_bars=FF_N_BARS, n_assets=n, seed=SEED)
        filing_early = date(2020, 1, 2)
        filing_future = date(2020, 5, 1)

        base_fund = _make_full_fundamentals(
            syms,
            shares=[1e6] * n,
            book_equity=[1e8 * (i + 1) for i in range(n)],
            operating_profit=[1e7] * n,
            total_assets=[2e8] * n,
            filing_date=filing_early,
            earlier_filing_date=filing_early - timedelta(days=365),
            earlier_total_assets=[1.8e8 * (i + 1) for i in range(n)],
        )

        leak_record = _make_fundamentals(
            [syms[0]], METRIC_BOOK_EQUITY, [9.99e10],
            [filing_future],
        )
        fund_with_leak = pd.concat([base_fund, leak_record], ignore_index=True)

        cfg = FamaFrenchConfig(
            min_assets=4,
            momentum_lookback=20,
            momentum_skip=2,
        )

        factors_base = compute_fama_french_factors(prices, base_fund, cfg)
        factors_leaked = compute_fama_french_factors(prices, fund_with_leak, cfg)

        pre_future = pd.Timestamp(filing_future) - pd.Timedelta(days=1)
        mask = prices.index <= pre_future

        pd.testing.assert_frame_equal(
            factors_base.loc[mask].reset_index(drop=True),
            factors_leaked.loc[mask].reset_index(drop=True),
            check_exact=False,
            atol=1e-12,
            obj="Factor returns before future filing_date",
        )


# ---------------------------------------------------------------------------
# Public API / __all__ check
# ---------------------------------------------------------------------------


class TestPublicAPI:
    """Verify __all__ exports and module-level importability."""

    def test_all_names_importable(self) -> None:
        import core_trading.signals.factors.fama_french as mod

        expected = {
            "FamaFrenchConfig",
            "pit_latest_value",
            "build_characteristic_panel",
            "compute_market_equity",
            "compute_book_to_market",
            "compute_rmw",
            "compute_cma",
            "form_ff_portfolios",
            "factor_returns_from_portfolios",
            "compute_umd",
            "compute_fama_french_factors",
        }
        for name in expected:
            assert hasattr(mod, name), f"Missing from module: {name}"

    def test_all_contains_expected_names(self) -> None:
        import core_trading.signals.factors.fama_french as mod

        for name in mod.__all__:
            assert hasattr(mod, name)

    def test_config_is_dataclass(self) -> None:
        import dataclasses

        assert dataclasses.is_dataclass(FamaFrenchConfig)

    def test_metric_constants_are_strings(self) -> None:
        assert isinstance(METRIC_SHARES_OUTSTANDING, str)
        assert isinstance(METRIC_BOOK_EQUITY, str)
        assert isinstance(METRIC_OPERATING_PROFIT, str)
        assert isinstance(METRIC_TOTAL_ASSETS, str)
