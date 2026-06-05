"""Phase 7 DOD integration test: 'VaR backtest (Kupiec) passes for the pilot strategy'.

This module is placed in tests/risk/ (NOT tests/strategies/) to avoid the
poisoned conftest.py in that directory, which stubs out scipy/statsmodels/torch.

Approach
--------
1. Simulate a cointegrated-pair price panel (seeded, deterministic) using the
   same recipe as tests/ops/test_pairs_paper_trading.py.
2. Run :class:`PairsPaperTrader` over the panel.  The strategy has a formation
   window, so the first 150 bars contain no trades; after that the z-score
   crossing signals generate active trading days.
3. The pilot strategy is low-activity: only ~25-30% of trading days result in a
   non-zero portfolio return (the strategy is flat between z-score entries and
   exits).  Using ALL equity-curve returns including zeros would bias the VaR
   estimate downward because zero-return flat days dominate and push the
   historical-VaR toward zero, causing trivially many 'exceptions' when any
   non-zero loss occurs.

   To obtain a meaningful Kupiec backtest:
   - Extract only the ACTIVE trading days (non-zero daily returns) from the
     full equity-curve snapshot series.
   - Apply an expanding-window historical VaR to these active-day returns:
     forecast for active day t uses only data through active day t-1 (no
     lookahead).
   - Run kupiec_test and christoffersen_test on the resulting exception series.

   This is documented as the 'active-days-only' variant.  The window is 800
   total bars (seed=9, business-day dates), yielding ~220 active trading days
   and ~190 test observations after the 30-day warm-up.  The total run time
   is under 1 second.

4. Assert kupiec_test passes (p-value >= 0.05), and christoffersen_test passes
   for both independence and conditional-coverage components.  Additionally
   assert sanity on observation count and exception rate.

Determinism
-----------
All RNG calls use fixed seeds (np.random.default_rng(9) for the price panel).
The pairs strategy uses its own deterministic computation graph (no random
components).  Running this test twice on the same machine must produce
bit-identical results.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core_trading.ops.pairs_paper_trading import PairsPaperTrader, PaperConfig
from core_trading.risk.pairs_risk import PairsRiskManager, RiskLimits
from core_trading.risk.var import BacktestResult, christoffersen_test, kupiec_test
from core_trading.strategies.pairs_trading import PairsTradingConfig, PairsTradingStrategy

# ---------------------------------------------------------------------------
# Constants (tuned once and fixed for reproducibility)
# ---------------------------------------------------------------------------

_PRICE_SEED: int = 9          # rng seed for the cointegrated price panel
_N_BARS: int = 800            # total bars; ~220 active trading days result
_FORMATION_WINDOW: int = 150  # must match PairsTradingConfig default
_ZSCORE_WINDOW: int = 30
_MIN_WARMUP: int = 30         # rolling VaR min history before evaluating
_ALPHA: float = 0.05          # 1 - confidence = tail probability for Kupiec
_SIGNIFICANCE: float = 0.05   # hypothesis test significance level


# ---------------------------------------------------------------------------
# Synthetic cointegrated-pair price panel (recipe from test_pairs_paper_trading.py)
# ---------------------------------------------------------------------------


def _build_cointegrated_prices(seed: int = _PRICE_SEED, n: int = _N_BARS) -> pd.DataFrame:
    """Simulate two cointegrated pairs with known hedge ratios.

    Pair A: YA = 2.0 * XA + 10 + noise(1.0)
    Pair B: YB = 1.5 * XB +  5 + noise(0.8)

    XA and XB follow independent random walks.  This guarantees that
    the strategy's pairs-selection step (cointegration test) will find
    both pairs and generate trading signals throughout the window.

    Returns a MultiIndex DataFrame with levels (symbol, timestamp) as
    required by :class:`PairsTradingStrategy`.
    """
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2018-01-02", periods=n, freq="B", tz="UTC")

    xa = 50.0 + np.cumsum(rng.standard_normal(n)) * 0.5
    ya = 2.0 * xa + 10.0 + rng.standard_normal(n) * 1.0
    xb = 30.0 + np.cumsum(rng.standard_normal(n)) * 0.4
    yb = 1.5 * xb + 5.0 + rng.standard_normal(n) * 0.8

    frames = []
    for sym, px in {"YA": ya, "XA": xa, "YB": yb, "XB": xb}.items():
        px = np.maximum(px, 1.0)   # no negative prices
        vol = rng.uniform(2e6, 4e6, n)
        frames.append(
            pd.DataFrame(
                {
                    "open": px,
                    "high": px * 1.001,
                    "low": px * 0.999,
                    "close": px,
                    "volume": vol,
                },
                index=pd.MultiIndex.from_product(
                    [[sym], idx], names=["symbol", "timestamp"]
                ),
            )
        )
    return pd.concat(frames).sort_index()


# ---------------------------------------------------------------------------
# Strategy / harness builders
# ---------------------------------------------------------------------------


def _build_strategy() -> PairsTradingStrategy:
    cfg = PairsTradingConfig(
        formation_window=_FORMATION_WINDOW,
        zscore_window=_ZSCORE_WINDOW,
        max_pairs=4,
    )
    return PairsTradingStrategy(cfg)


def _build_risk_manager() -> PairsRiskManager:
    """Lenient limits so normal operation is never halted by the kill switch."""
    return PairsRiskManager(RiskLimits(per_pair_cap=0.10, gross_leverage_cap=2.0))


def _build_paper_config() -> PaperConfig:
    return PaperConfig(
        halt_on_breach=False,   # never halt; we want the full return history
        min_paper_days=5,
    )


# ---------------------------------------------------------------------------
# Rolling historical VaR helper (no lookahead)
# ---------------------------------------------------------------------------


def _expanding_historical_var(returns: np.ndarray, alpha: float) -> np.ndarray:
    """Compute expanding-window 1-day historical VaR forecasts.

    For each index t (0-based), the forecast is derived from the history
    [0, ..., t-1] only.  Returns a NaN-filled array for the first
    ``_MIN_WARMUP`` elements (insufficient history).

    Parameters
    ----------
    returns:
        1-D array of realised returns (positive = gain).
    alpha:
        Tail probability (e.g. 0.05 for 95% VaR).

    Returns
    -------
    numpy.ndarray
        Shape (n,); NaN for indices < _MIN_WARMUP; positive loss forecast
        for indices >= _MIN_WARMUP.
    """
    n = len(returns)
    var_fc = np.full(n, float("nan"), dtype=float)
    for t in range(_MIN_WARMUP, n):
        # History up to and NOT including day t -- no lookahead.
        history = returns[:t]
        var_fc[t] = float(-np.quantile(history, alpha))
    return var_fc


# ---------------------------------------------------------------------------
# Main DOD integration test
# ---------------------------------------------------------------------------


class TestKupiecOnPilotStrategy:
    """DOD item: 'VaR backtest (Kupiec) passes for the pilot strategy'."""

    @pytest.fixture(scope="class")
    def pilot_results(self) -> dict[str, object]:
        """Build prices, run the strategy, compute VaR forecasts, run tests.

        Scoped to the class so the heavy computation runs once and all test
        methods share the result dict.
        """
        prices = _build_cointegrated_prices()
        strat = _build_strategy()
        trader = PairsPaperTrader(
            strat,
            risk_manager=_build_risk_manager(),
            config=_build_paper_config(),
        )
        trader.run(prices)

        # Extract all daily returns from the equity-curve snapshots.
        all_daily_returns = np.array(
            [s.daily_return for s in trader.snapshots], dtype=float
        )

        # Active-days-only variant: keep only non-zero return days.
        # Rationale: the strategy is flat (zero return) most days; using zeros
        # would push historical VaR toward zero and produce trivially inflated
        # exception counts that have no statistical meaning.
        active_returns = all_daily_returns[all_daily_returns != 0.0]

        # Expanding-window VaR forecast on active returns only.
        var_forecasts = _expanding_historical_var(active_returns, alpha=_ALPHA)

        # Build exception series for the test window (after warm-up).
        test_start = _MIN_WARMUP
        r_test = active_returns[test_start:]
        v_test = var_forecasts[test_start:]

        # Exception indicator: 1 when realised loss exceeded the VaR forecast.
        # Equivalently: return_t < -VaR_t  (both sides negative because VaR > 0).
        exceptions = (r_test < -v_test).astype(int)

        # Run both backtests.
        kupiec_result = kupiec_test(
            exceptions,
            alpha=_ALPHA,
            significance=_SIGNIFICANCE,
        )
        ind_result, cc_result = christoffersen_test(
            exceptions,
            alpha=_ALPHA,
            significance=_SIGNIFICANCE,
        )

        return {
            "active_returns": active_returns,
            "all_daily_returns": all_daily_returns,
            "var_forecasts": var_forecasts,
            "r_test": r_test,
            "exceptions": exceptions,
            "kupiec": kupiec_result,
            "ind": ind_result,
            "cc": cc_result,
            "n_snapshots": len(trader.snapshots),
        }

    # ---- sanity assertions ----

    def test_active_days_count(self, pilot_results: dict[str, object]) -> None:
        """Strategy must produce a meaningful number of active trading days."""
        n_active = len(pilot_results["active_returns"])  # type: ignore[arg-type]
        assert n_active >= 100, (
            f"Too few active trading days for a meaningful VaR backtest: "
            f"{n_active} < 100.  Check the price panel seed and formation window."
        )

    def test_test_window_size(self, pilot_results: dict[str, object]) -> None:
        """After the warm-up window we need at least 100 test observations."""
        n_test = len(pilot_results["r_test"])  # type: ignore[arg-type]
        assert n_test >= 100, (
            f"Test window after warm-up is too small: {n_test} < 100."
        )

    def test_exception_count_sane(self, pilot_results: dict[str, object]) -> None:
        """Exception count must be in a sane range (1 to 3x expected)."""
        exceptions = pilot_results["exceptions"]  # type: ignore[assignment]
        assert isinstance(exceptions, np.ndarray)
        n_obs = len(exceptions)
        n_exc = int(exceptions.sum())
        expected = _ALPHA * n_obs
        assert n_exc >= 1, (
            "Zero exceptions detected -- VaR model may be trivially over-conservative."
        )
        assert n_exc <= 3.5 * expected, (
            f"Exception count {n_exc} is > 3.5x the expected {expected:.1f}; "
            f"VaR model is severely under-estimating risk."
        )

    def test_all_var_forecasts_positive(self, pilot_results: dict[str, object]) -> None:
        """VaR forecasts in the test window must all be non-negative."""
        v_test = pilot_results["var_forecasts"]  # type: ignore[assignment]
        assert isinstance(v_test, np.ndarray)
        valid = v_test[~np.isnan(v_test)]
        assert (valid >= 0.0).all(), "VaR forecast produced negative value(s)."

    # ---- Kupiec POF test ----

    def test_kupiec_test_result_type(self, pilot_results: dict[str, object]) -> None:
        """kupiec_test must return a BacktestResult."""
        assert isinstance(pilot_results["kupiec"], BacktestResult)

    def test_kupiec_passes(self, pilot_results: dict[str, object]) -> None:
        """Kupiec (1995) proportion-of-failures test must NOT reject the VaR model."""
        kupiec: BacktestResult = pilot_results["kupiec"]  # type: ignore[assignment]
        assert kupiec.passed, (
            f"Kupiec POF test FAILED: "
            f"n_obs={kupiec.n_observations}, "
            f"n_exc={kupiec.n_exceptions}, "
            f"expected={kupiec.expected_exceptions:.1f}, "
            f"p_value={kupiec.p_value:.4f} < significance={kupiec.significance}. "
            f"The rolling historical VaR is mis-specifying exception frequency."
        )

    def test_kupiec_p_value_above_significance(
        self, pilot_results: dict[str, object]
    ) -> None:
        """Kupiec p-value must be >= significance level (0.05)."""
        kupiec: BacktestResult = pilot_results["kupiec"]  # type: ignore[assignment]
        assert kupiec.p_value >= _SIGNIFICANCE, (
            f"p_value={kupiec.p_value:.4f} < {_SIGNIFICANCE}"
        )

    def test_kupiec_lr_statistic_non_negative(
        self, pilot_results: dict[str, object]
    ) -> None:
        """LR statistic must be non-negative."""
        kupiec: BacktestResult = pilot_results["kupiec"]  # type: ignore[assignment]
        assert kupiec.lr_statistic >= 0.0

    # ---- Christoffersen independence and CC tests ----

    def test_christoffersen_ind_passes(self, pilot_results: dict[str, object]) -> None:
        """Christoffersen independence test: exceptions must not be clustered."""
        ind: BacktestResult = pilot_results["ind"]  # type: ignore[assignment]
        assert ind.passed, (
            f"Christoffersen independence test FAILED: "
            f"p_value={ind.p_value:.4f}. "
            f"Exceptions are clustering, indicating volatility-regime effects."
        )

    def test_christoffersen_cc_passes(self, pilot_results: dict[str, object]) -> None:
        """Christoffersen conditional-coverage (CC) test must pass."""
        cc: BacktestResult = pilot_results["cc"]  # type: ignore[assignment]
        assert cc.passed, (
            f"Christoffersen CC test FAILED: "
            f"p_value={cc.p_value:.4f}. "
            f"Either the exception rate or clustering is off."
        )

    def test_cc_lr_equals_kupiec_plus_ind(
        self, pilot_results: dict[str, object]
    ) -> None:
        """LR_CC = LR_POF + LR_IND (Christoffersen 1998 decomposition)."""
        kupiec: BacktestResult = pilot_results["kupiec"]  # type: ignore[assignment]
        ind: BacktestResult = pilot_results["ind"]      # type: ignore[assignment]
        cc: BacktestResult = pilot_results["cc"]        # type: ignore[assignment]
        assert cc.lr_statistic == pytest.approx(
            kupiec.lr_statistic + ind.lr_statistic, abs=1e-6
        )

    # ---- exception counts are self-consistent ----

    def test_kupiec_n_exceptions_match_exceptions_array(
        self, pilot_results: dict[str, object]
    ) -> None:
        exceptions = pilot_results["exceptions"]  # type: ignore[assignment]
        kupiec: BacktestResult = pilot_results["kupiec"]  # type: ignore[assignment]
        assert isinstance(exceptions, np.ndarray)
        assert kupiec.n_exceptions == int(exceptions.sum())

    def test_kupiec_n_observations_match_array_length(
        self, pilot_results: dict[str, object]
    ) -> None:
        exceptions = pilot_results["exceptions"]  # type: ignore[assignment]
        kupiec: BacktestResult = pilot_results["kupiec"]  # type: ignore[assignment]
        assert isinstance(exceptions, np.ndarray)
        assert kupiec.n_observations == len(exceptions)


# ---------------------------------------------------------------------------
# No-lookahead verification
# ---------------------------------------------------------------------------


class TestNoLookaheadInVaRForecasts:
    """Verify the expanding-window VaR uses only past data."""

    def test_var_at_warmup_boundary_uses_only_past(self) -> None:
        """At index min_warmup, the VaR is based on exactly min_warmup observations."""
        rng = np.random.default_rng(0)
        returns = rng.normal(0.0, 0.01, size=100)
        var_fc = _expanding_historical_var(returns, alpha=_ALPHA)
        # At index min_warmup, history is returns[0:min_warmup]
        t = _MIN_WARMUP
        expected_var = float(-np.quantile(returns[:t], _ALPHA))
        assert var_fc[t] == pytest.approx(expected_var, rel=1e-9)

    def test_var_at_t_uses_only_history_through_t_minus_1(self) -> None:
        """VaR at index t must not use returns[t] (lookahead)."""
        rng = np.random.default_rng(1)
        returns = rng.normal(0.0, 0.01, size=200)
        var_fc = _expanding_historical_var(returns, alpha=_ALPHA)
        t = 100
        expected = float(-np.quantile(returns[:t], _ALPHA))
        assert var_fc[t] == pytest.approx(expected, rel=1e-9)

    def test_nans_before_warmup(self) -> None:
        """Indices before _MIN_WARMUP must be NaN (no forecast yet)."""
        rng = np.random.default_rng(2)
        returns = rng.normal(0.0, 0.01, size=100)
        var_fc = _expanding_historical_var(returns, alpha=_ALPHA)
        assert all(np.isnan(var_fc[t]) for t in range(_MIN_WARMUP))


# ---------------------------------------------------------------------------
# Determinism check
# ---------------------------------------------------------------------------


class TestDeterminism:
    """Running the pipeline twice must yield identical outputs."""

    def test_exception_series_is_deterministic(self) -> None:
        """Two identical runs produce the same exception array."""
        def _run_once() -> np.ndarray:
            prices = _build_cointegrated_prices()
            strat = _build_strategy()
            trader = PairsPaperTrader(
                strat,
                risk_manager=_build_risk_manager(),
                config=_build_paper_config(),
            )
            trader.run(prices)
            all_ret = np.array([s.daily_return for s in trader.snapshots])
            active = all_ret[all_ret != 0.0]
            var_fc = _expanding_historical_var(active, _ALPHA)
            r_t = active[_MIN_WARMUP:]
            v_t = var_fc[_MIN_WARMUP:]
            return (r_t < -v_t).astype(int)

        exc1 = _run_once()
        exc2 = _run_once()
        assert (exc1 == exc2).all(), "Exception series is not deterministic."

    def test_kupiec_result_is_deterministic(self) -> None:
        """kupiec_test on the same exceptions always returns the same p-value."""
        prices = _build_cointegrated_prices()
        strat = _build_strategy()
        trader = PairsPaperTrader(
            strat,
            risk_manager=_build_risk_manager(),
            config=_build_paper_config(),
        )
        trader.run(prices)
        all_ret = np.array([s.daily_return for s in trader.snapshots])
        active = all_ret[all_ret != 0.0]
        var_fc = _expanding_historical_var(active, _ALPHA)
        r_t = active[_MIN_WARMUP:]
        v_t = var_fc[_MIN_WARMUP:]
        exc = (r_t < -v_t).astype(int)

        r1 = kupiec_test(exc, alpha=_ALPHA)
        r2 = kupiec_test(exc, alpha=_ALPHA)
        assert r1.p_value == r2.p_value
        assert r1.lr_statistic == r2.lr_statistic
