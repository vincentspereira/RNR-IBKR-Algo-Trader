"""Phase 8 (money management) Definition-of-Done integration tests.

This module covers the three Phase 8 DOD checklist items that require an
end-to-end / simulation flavour rather than a primitive unit test (the
"all sizing methods unit-tested with known examples" item is already covered
by ``tests/money/test_sizing.py``).  It mirrors the structure and house style
of ``tests/risk/test_phase7_dod.py``.

DOD items covered
-----------------
2. **Backtest comparison: same signal under different sizing methods**
   (``TestSizingBacktestComparison``).
3. **Drawdown circuit logic verified in simulation**
   (``TestDrawdownCircuitSimulation``).
4. **Live capital allocation tied to the Phase 6 multi-strategy allocator**
   (``TestMoneyPipelineEndToEnd``).

Part A -- sizing-method backtest recipe
---------------------------------------
A single deterministic synthetic asset is simulated with a VOLATILITY REGIME
CHANGE: ``_N_BARS`` (750) daily log-returns, the first half drawn at
``sigma = 1%/day`` with a small positive drift and the second half at
``sigma = 3%/day`` (seeded with ``np.random.default_rng(_BACKTEST_SEED)``).
ONE common signal (constant long, ``direction = +1`` every bar) feeds EVERY
sizing method, so any difference in the equity curves is attributable solely
to the sizing rule, not to the signal.

The book is rebalanced daily from a rolling estimation window of
``_EST_WINDOW`` (60) bars.  Strictly NO LOOKAHEAD: the weight applied over bar
``t`` (i.e. earning return ``r_t``) is computed from returns through bar
``t - 1`` only.  The first ``_EST_WINDOW`` bars therefore trade flat (no
estimate yet) and are dropped from the equity curve.

Five sizing methods share that single signal and rolling window:

1. ``constant``     -- fixed-fractional constant weight (``_CONST_WEIGHT``).
2. ``fixed_dollar`` -- a fixed dollar notional converted to a weight via the
   simulated price and the NAV path (``fixed_dollar``).
3. ``kelly``        -- quarter-Kelly from the rolling mean / std estimate
   (``fractional_kelly``), capped per position.
4. ``vol_target``   -- volatility targeting on the rolling realised vol
   (``vol_target_weight``), capped per position.
5. ``optimal_f``    -- Ralph Vince's Optimal f on the rolling return window
   (``optimal_f``), used as a long weight.

Each method's per-bar weight is hard-capped at ``_PER_POSITION_CAP`` so the
"cap binds" assertion is meaningful, and the resulting equity curve is
``prod(1 + w_t * r_t)``.

Economic assertions (Part A)
----------------------------
* every equity curve is finite and strictly positive throughout;
* vol-targeting de-levers in the high-vol regime: its realised annualised vol
  is materially CLOSER to the target than the constant-weight method's in the
  second (high-vol) half;
* the vol-target weight in the high-vol regime is materially BELOW its
  low-vol-regime weight;
* quarter-Kelly max drawdown <= full-Kelly max drawdown on the SAME path;
* the per-position cap is never exceeded by any method when configured tight;
* the methods genuinely differ (the curves are not all identical).

Part B -- drawdown circuit (DOD item 3)
---------------------------------------
A seeded equity path is built with three phases: a calm rise, a deep crash,
and a partial-then-full recovery.  ``target_exposure`` is replayed bar-by-bar
over an EXPANDING window (no lookahead) and the ladder behaviour is asserted:
full exposure before the crash, a laddered reduction through each configured
rung as the drawdown deepens, exposure staying reduced during the partial
recovery (the new-high-water-mark hysteresis), and restoration to ``1.0`` only
once equity prints a fresh high.

Part C -- end-to-end money pipeline (DOD item 4 + integration)
--------------------------------------------------------------
One test wires the whole layer together for a single rebalance:
per-asset ``size_position`` -> book-level ``apply_leverage_limits`` ->
``check_turnover_budget`` against a realised weight history -> strategy-level
``allocate_live_capital`` fed by the REAL Phase 6 allocator
(``core_trading.portfolio.strategy_allocator.allocate_strategies`` on a small
seeded multi-strategy returns panel).  Invariants are asserted at each stage.

Determinism
-----------
Every RNG call uses a fixed seed; there is no network, no sleep, and dates use
a business-day ``DatetimeIndex``.  Re-running the module on the same machine
produces bit-identical results.  Total runtime is well under five seconds.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import pytest

from core_trading.money import (
    DrawdownConfig,
    LeverageConfig,
    LifecycleConfig,
    SizingConfig,
    StrategyRecord,
    StrategyStage,
    allocate_live_capital,
    apply_leverage_limits,
    check_turnover_budget,
    compute_drawdown,
    fixed_dollar,
    fractional_kelly,
    optimal_f,
    size_position,
    target_exposure,
    vol_target_weight,
)
from core_trading.money.turnover import TurnoverConfig
from core_trading.portfolio.strategy_allocator import (
    StrategyAllocatorConfig,
    allocate_strategies,
)

# ---------------------------------------------------------------------------
# Constants (tuned once and fixed for reproducibility)
# ---------------------------------------------------------------------------

_BACKTEST_SEED: int = 8       # rng seed for the single-asset return path
_N_BARS: int = 750            # total daily bars; regime change at the midpoint
_EST_WINDOW: int = 60         # rolling estimation window (no lookahead)
_PERIODS_PER_YEAR: int = 252

_LOW_VOL: float = 0.01        # 1%/day in the first (calm) regime
_HIGH_VOL: float = 0.03       # 3%/day in the second (turbulent) regime
_DRIFT: float = 0.0004        # small positive per-bar drift (both regimes)

_PER_POSITION_CAP: float = 0.50   # tight per-position cap (fraction of NAV)
_CONST_WEIGHT: float = 0.50       # constant-weight method's fixed long weight
_TARGET_VOL: float = 0.10         # vol-targeting annualised target
_KELLY_FRACTION: float = 0.25     # quarter-Kelly
_FIXED_DOLLARS: float = 5_000.0   # fixed-dollar notional per bar
_INITIAL_NAV: float = 100_000.0   # starting NAV for the fixed-dollar weight


# ---------------------------------------------------------------------------
# Part A: synthetic single-asset path with a volatility regime change
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _BacktestPath:
    """Deterministic single-asset return / price path used by every method.

    Attributes
    ----------
    dates:
        Business-day ``DatetimeIndex`` of length ``_N_BARS``.
    log_returns:
        Per-bar log-returns; the first half low-vol, the second half high-vol.
    simple_returns:
        ``exp(log_returns) - 1`` (the realised simple return earned per bar).
    prices:
        Price path from a unit base via ``cumprod(1 + simple_returns)``.
    split:
        Index at which the volatility regime switches (the midpoint).
    """

    dates: pd.DatetimeIndex
    log_returns: np.ndarray
    simple_returns: np.ndarray
    prices: np.ndarray
    split: int


def _build_backtest_path(
    seed: int = _BACKTEST_SEED, n: int = _N_BARS
) -> _BacktestPath:
    """Simulate a single asset with a low->high volatility regime change."""
    rng = np.random.default_rng(seed)
    split = n // 2
    sigma = np.empty(n, dtype=float)
    sigma[:split] = _LOW_VOL
    sigma[split:] = _HIGH_VOL
    log_returns = _DRIFT + sigma * rng.standard_normal(n)
    simple_returns = np.expm1(log_returns)
    prices = 100.0 * np.cumprod(1.0 + simple_returns)
    dates = pd.date_range("2018-01-02", periods=n, freq="B")
    return _BacktestPath(
        dates=dates,
        log_returns=log_returns,
        simple_returns=simple_returns,
        prices=prices,
        split=split,
    )


def _annualised_vol(simple_returns: np.ndarray) -> float:
    """Annualised realised volatility of a simple-return slice."""
    if simple_returns.size < 2:
        return 0.0
    return float(np.std(simple_returns, ddof=1) * np.sqrt(_PERIODS_PER_YEAR))


def _max_drawdown(equity: np.ndarray) -> float:
    """Maximum drawdown (positive-loss convention) of an equity curve."""
    running_max = np.maximum.accumulate(equity)
    dd = 1.0 - equity / running_max
    return float(np.max(dd))


@dataclass(frozen=True)
class _MethodResult:
    """Per-method backtest output.

    Attributes
    ----------
    weights:
        Applied long weight for each evaluated bar (post-warmup).
    equity:
        Equity curve over the evaluated bars (starts at 1.0).
    realised:
        Simple returns earned over the evaluated bars (aligned to ``weights``).
    """

    weights: np.ndarray
    equity: np.ndarray
    realised: np.ndarray


def _run_method(
    path: _BacktestPath,
    method: str,
    *,
    cap: float = _PER_POSITION_CAP,
    kelly_fraction: float = _KELLY_FRACTION,
) -> _MethodResult:
    """Run one sizing method over the shared path with a rolling window.

    The signal is constant-long (``direction = +1``).  The weight applied to
    bar ``t`` uses only ``simple_returns[t - _EST_WINDOW : t]`` -- data through
    ``t - 1`` -- so there is no lookahead.  Bars before ``_EST_WINDOW`` are not
    evaluated (insufficient history).
    """
    n = path.simple_returns.shape[0]
    weights: list[float] = []
    realised: list[float] = []
    nav = _INITIAL_NAV
    for t in range(_EST_WINDOW, n):
        window = path.simple_returns[t - _EST_WINDOW : t]
        price_t = float(path.prices[t - 1])
        if method == "constant":
            w = _CONST_WEIGHT
        elif method == "fixed_dollar":
            units = fixed_dollar(_FIXED_DOLLARS, price_t)
            w = units * price_t / nav
        elif method == "kelly":
            mu = float(np.mean(window))
            sigma = float(np.std(window, ddof=1))
            w = fractional_kelly(mu, sigma, kelly_fraction=kelly_fraction)
        elif method == "vol_target":
            w = vol_target_weight(
                window,
                target_vol=_TARGET_VOL,
                periods_per_year=_PERIODS_PER_YEAR,
            )
        elif method == "optimal_f":
            w = optimal_f(window, max_f=1.0, grid=200, fraction=1.0)
        else:  # pragma: no cover - guard against typos in the test itself
            raise ValueError(f"unknown method {method!r}")

        # Constant-long signal; hard per-position cap; never short here.
        w = float(min(max(w, 0.0), cap))
        r_t = float(path.simple_returns[t])
        weights.append(w)
        realised.append(r_t)
        nav *= 1.0 + w * r_t

    realised_arr = np.asarray(realised, dtype=float)
    weights_arr = np.asarray(weights, dtype=float)
    equity = np.cumprod(1.0 + weights_arr * realised_arr)
    return _MethodResult(weights=weights_arr, equity=equity, realised=realised_arr)


_METHODS: tuple[str, ...] = (
    "constant",
    "fixed_dollar",
    "kelly",
    "vol_target",
    "optimal_f",
)


class TestSizingBacktestComparison:
    """DOD item 2: same signal under five different sizing methods."""

    @pytest.fixture(scope="class")
    def path(self) -> _BacktestPath:
        return _build_backtest_path()

    @pytest.fixture(scope="class")
    def results(self, path: _BacktestPath) -> dict[str, _MethodResult]:
        return {m: _run_method(path, m) for m in _METHODS}

    def test_all_five_methods_run(
        self, results: dict[str, _MethodResult]
    ) -> None:
        """Every configured sizing method produced an equity curve."""
        assert set(results) == set(_METHODS)
        assert len(results) == 5

    def test_equity_curves_finite_and_positive(
        self, results: dict[str, _MethodResult]
    ) -> None:
        """All equity curves must stay finite and strictly positive."""
        for method, res in results.items():
            assert np.isfinite(res.equity).all(), f"{method}: non-finite equity"
            assert (res.equity > 0.0).all(), f"{method}: non-positive equity"

    def test_per_position_cap_binds(
        self, results: dict[str, _MethodResult]
    ) -> None:
        """No method's applied weight may exceed the tight per-position cap."""
        for method, res in results.items():
            assert (res.weights <= _PER_POSITION_CAP + 1e-12).all(), (
                f"{method}: weight exceeded the per-position cap "
                f"({float(res.weights.max())} > {_PER_POSITION_CAP})"
            )

    def test_vol_target_delevers_in_high_vol_regime(
        self, path: _BacktestPath, results: dict[str, _MethodResult]
    ) -> None:
        """Vol-target weight in the high-vol half is materially below the low-vol half."""
        res = results["vol_target"]
        # The evaluated bars start at _EST_WINDOW; the regime split (in the
        # original index) maps to (split - _EST_WINDOW) in the evaluated array.
        split_eval = path.split - _EST_WINDOW
        low_w = res.weights[:split_eval]
        # Skip the transition window where the rolling estimate still mixes
        # both regimes; compare a clean high-vol slice.
        high_w = res.weights[split_eval + _EST_WINDOW :]
        low_mean = float(np.mean(low_w))
        high_mean = float(np.mean(high_w))
        assert high_mean < 0.6 * low_mean, (
            f"vol-target did not de-lever: high-vol mean weight {high_mean:.4f} "
            f"not < 0.6 * low-vol mean weight {low_mean:.4f}"
        )

    def test_vol_target_tracks_target_better_than_constant(
        self, path: _BacktestPath, results: dict[str, _MethodResult]
    ) -> None:
        """In the high-vol half, vol-target realised vol is closer to target."""
        split_eval = path.split - _EST_WINDOW
        # Clean high-vol slice (after the rolling window has filled with
        # high-vol observations).
        start = split_eval + _EST_WINDOW
        vt = results["vol_target"]
        const = results["constant"]
        # Portfolio realised returns = weight_t * asset_return_t.
        vt_port = vt.weights[start:] * vt.realised[start:]
        const_port = const.weights[start:] * const.realised[start:]
        vt_vol = _annualised_vol(vt_port)
        const_vol = _annualised_vol(const_port)
        assert abs(vt_vol - _TARGET_VOL) < abs(const_vol - _TARGET_VOL), (
            f"vol-target ({vt_vol:.4f}) not closer to target {_TARGET_VOL} "
            f"than constant ({const_vol:.4f})"
        )

    def test_quarter_kelly_drawdown_le_full_kelly(
        self, path: _BacktestPath
    ) -> None:
        """Quarter-Kelly max drawdown must not exceed full-Kelly on the same path.

        Compared on the RAW (uncapped) fractional-Kelly weight so the
        fraction-scaling relationship is preserved bar by bar: a smaller
        ``kelly_fraction`` multiplies every per-bar bet by the same constant,
        hence applies a strictly smaller (same-signed) exposure to identical
        returns and can only shrink the equity swings.  The per-position cap /
        long-only clamp used in the headline backtest is deliberately omitted
        here because clamping would break that clean monotone relationship.
        """

        def _kelly_equity(fraction: float) -> np.ndarray:
            n = path.simple_returns.shape[0]
            equity = [1.0]
            for t in range(_EST_WINDOW, n):
                window = path.simple_returns[t - _EST_WINDOW : t]
                mu = float(np.mean(window))
                sigma = float(np.std(window, ddof=1))
                w = fractional_kelly(mu, sigma, kelly_fraction=fraction)
                r_t = float(path.simple_returns[t])
                equity.append(equity[-1] * (1.0 + w * r_t))
            return np.asarray(equity[1:], dtype=float)

        quarter_dd = _max_drawdown(_kelly_equity(0.25))
        full_dd = _max_drawdown(_kelly_equity(1.0))
        assert quarter_dd <= full_dd + 1e-9, (
            f"quarter-Kelly drawdown {quarter_dd:.4f} exceeded full-Kelly "
            f"{full_dd:.4f}"
        )

    def test_methods_genuinely_differ(
        self, results: dict[str, _MethodResult]
    ) -> None:
        """The five equity curves must not all be identical."""
        terminals = {m: float(res.equity[-1]) for m, res in results.items()}
        unique = {round(v, 6) for v in terminals.values()}
        assert len(unique) >= 4, (
            f"sizing methods did not produce distinct equity curves: {terminals}"
        )

    def test_no_lookahead_first_weight_uses_only_history(
        self, path: _BacktestPath
    ) -> None:
        """The first evaluated vol-target weight matches a manual no-lookahead calc."""
        res = _run_method(path, "vol_target")
        window = path.simple_returns[0:_EST_WINDOW]
        expected = vol_target_weight(
            window, target_vol=_TARGET_VOL, periods_per_year=_PERIODS_PER_YEAR
        )
        expected = min(max(expected, 0.0), _PER_POSITION_CAP)
        assert res.weights[0] == pytest.approx(expected, rel=1e-12)

    def test_determinism(self, path: _BacktestPath) -> None:
        """Re-running a method on the same path yields identical equity."""
        a = _run_method(path, "kelly")
        b = _run_method(path, "kelly")
        assert np.array_equal(a.equity, b.equity)


# ---------------------------------------------------------------------------
# Part B: drawdown circuit replayed bar-by-bar (DOD item 3)
# ---------------------------------------------------------------------------


def _build_crash_recovery_equity() -> pd.Series:
    """Deterministic equity path: calm rise -> deep crash -> full recovery.

    Constructed so the drawdown sweeps cleanly through each default ladder
    rung (0.05, 0.10, 0.15) on the way down, dwells in a partial recovery that
    stays below the prior peak (to exercise hysteresis), then prints a new
    high-water mark at the very end.
    """
    rise = np.linspace(100.0, 120.0, 40)          # calm climb to a peak of 120
    crash = np.linspace(120.0, 96.0, 30)[1:]      # -20% crash through every rung
    partial = np.linspace(96.0, 114.0, 25)[1:]    # partial recovery, still < 120
    full = np.linspace(114.0, 126.0, 20)[1:]      # new high-water mark at the end
    values = np.concatenate([rise, crash, partial, full])
    dates = pd.date_range("2020-01-01", periods=values.shape[0], freq="B")
    return pd.Series(values, index=dates)


class TestDrawdownCircuitSimulation:
    """DOD item 3: drawdown circuit logic verified bar-by-bar in simulation."""

    @pytest.fixture(scope="class")
    def equity(self) -> pd.Series:
        return _build_crash_recovery_equity()

    @pytest.fixture(scope="class")
    def config(self) -> DrawdownConfig:
        # Disable the vol-of-vol overlay so the ladder behaviour is isolated
        # and deterministic from the price path alone.
        return DrawdownConfig(halve_on_vol_of_vol=False)

    @pytest.fixture(scope="class")
    def replay(
        self, equity: pd.Series, config: DrawdownConfig
    ) -> pd.DataFrame:
        """Replay target_exposure over an expanding window (no lookahead)."""
        drawdowns: list[float] = []
        exposures: list[float] = []
        returns = equity.pct_change().fillna(0.0)
        for t in range(1, len(equity) + 1):
            eq_t = equity.iloc[:t]
            ret_t = returns.iloc[:t]
            dd = float(compute_drawdown(eq_t).iloc[-1])
            exp = target_exposure(eq_t, ret_t, config=config)
            drawdowns.append(dd)
            exposures.append(exp)
        return pd.DataFrame(
            {"drawdown": drawdowns, "exposure": exposures},
            index=equity.index,
        )

    def test_full_exposure_before_crash(self, replay: pd.DataFrame) -> None:
        """During the calm climb (each bar a new high) exposure is full."""
        # The rise phase is the first 40 bars; every bar is a new high there.
        rise = replay.iloc[:40]
        assert (rise["drawdown"] <= 1e-12).all()
        assert (rise["exposure"] == 1.0).all()

    def test_ladder_steps_down_through_each_rung(
        self, replay: pd.DataFrame
    ) -> None:
        """As drawdown deepens, exposure visits each laddered level 0.75/0.50/0.25."""
        exposures = set(np.round(replay["exposure"].to_numpy(), 6))
        for rung in (0.75, 0.50, 0.25):
            assert rung in exposures, (
                f"ladder rung {rung} never reached; observed {sorted(exposures)}"
            )

    def test_deeper_drawdown_never_increases_exposure_on_the_way_down(
        self, replay: pd.DataFrame
    ) -> None:
        """Through the crash, exposure is monotone non-increasing as dd grows."""
        # Crash spans bars 40..68 (after the 40-bar rise, 29 crash bars).
        crash = replay.iloc[39:69]
        exp = crash["exposure"].to_numpy()
        assert np.all(np.diff(exp) <= 1e-12), (
            f"exposure rose during the crash: {exp}"
        )
        # Minimum exposure reached the deepest rung.
        assert float(exp.min()) == pytest.approx(0.25)

    def test_exposure_stays_reduced_during_partial_recovery(
        self, replay: pd.DataFrame
    ) -> None:
        """Hysteresis: while equity recovers but stays below the peak, exposure < 1."""
        # Partial recovery spans the bars after the crash but before the new
        # high.  Identify them as bars where drawdown is positive but shrinking.
        partial = replay.iloc[69:93]
        assert (partial["drawdown"] > 0.0).all(), "partial slice not in drawdown"
        assert (partial["exposure"] < 1.0).all(), (
            "exposure re-levered before a new high-water mark (hysteresis broken)"
        )

    def test_full_exposure_restored_only_after_new_high(
        self, replay: pd.DataFrame
    ) -> None:
        """Exposure returns to 1.0 only once a fresh high-water mark prints."""
        # The new high is printed in the final 'full' phase.
        final_exposure = float(replay["exposure"].iloc[-1])
        final_drawdown = float(replay["drawdown"].iloc[-1])
        assert final_drawdown <= 1e-12, "final bar is not a new high-water mark"
        assert final_exposure == 1.0, "exposure not restored at the new high"

        # Every bar whose drawdown reached the first ladder rung (0.05) was
        # de-levered below full size; only sub-rung (dd < 0.05) bars stay at
        # 1.0, which is the correct ladder behaviour.
        laddered = replay[replay["drawdown"] >= 0.05]
        assert not laddered.empty
        assert (laddered["exposure"] < 1.0).all()

    def test_determinism(
        self, equity: pd.Series, config: DrawdownConfig
    ) -> None:
        """Replaying twice gives identical exposure paths."""

        def _run() -> np.ndarray:
            returns = equity.pct_change().fillna(0.0)
            out: list[float] = []
            for t in range(1, len(equity) + 1):
                out.append(
                    target_exposure(
                        equity.iloc[:t], returns.iloc[:t], config=config
                    )
                )
            return np.asarray(out, dtype=float)

        assert np.array_equal(_run(), _run())


# ---------------------------------------------------------------------------
# Part C: end-to-end money pipeline (DOD item 4 + integration)
# ---------------------------------------------------------------------------


def _build_strategy_returns_panel() -> pd.DataFrame:
    """Small seeded multi-strategy live-returns panel for the Phase 6 allocator.

    Three strategies with distinct, positive-Sharpe return profiles so the
    real allocator produces a clean, strictly-positive weight split with no
    decommission haircut.
    """
    rng = np.random.default_rng(21)
    n = 120
    dates = pd.date_range("2021-01-04", periods=n, freq="B")
    cols = {
        "alpha_momentum": 0.0008 + 0.010 * rng.standard_normal(n),
        "beta_meanrev": 0.0006 + 0.012 * rng.standard_normal(n),
        "gamma_carry": 0.0010 + 0.009 * rng.standard_normal(n),
    }
    return pd.DataFrame(cols, index=dates)


class TestMoneyPipelineEndToEnd:
    """DOD item 4: full money pipeline wired through the real Phase 6 allocator."""

    @pytest.fixture(scope="class")
    def sized_book(self) -> dict[str, float]:
        """Per-asset sizing via size_position with a constant-long signal."""
        # Two assets, each sized independently; the rolling-window returns are
        # synthetic but deterministic.
        rng = np.random.default_rng(5)
        ret_a = (0.0005 + 0.012 * rng.standard_normal(80)).tolist()
        ret_b = (0.0003 + 0.020 * rng.standard_normal(80)).tolist()
        cfg = SizingConfig(
            kelly_fraction=0.25,
            target_vol=0.10,
            per_position_cap=0.40,
            max_leverage=1.0,
        )
        size_a = size_position(
            direction=1,
            mu=float(np.mean(ret_a)),
            sigma=float(np.std(ret_a, ddof=1)),
            returns=ret_a,
            config=cfg,
        )
        size_b = size_position(
            direction=1,
            mu=float(np.mean(ret_b)),
            sigma=float(np.std(ret_b, ddof=1)),
            returns=ret_b,
            config=cfg,
        )
        return {"AAA": size_a.weight, "BBB": size_b.weight}

    def test_stage1_sizes_respect_per_position_cap(
        self, sized_book: dict[str, float]
    ) -> None:
        """Each per-asset size is within the configured per-position cap."""
        for sym, w in sized_book.items():
            assert 0.0 <= w <= 0.40 + 1e-12, f"{sym} weight {w} out of range"

    def test_stage2_leverage_limits_enforce_gross_cap(self) -> None:
        """Book-level apply_leverage_limits keeps gross within the cap."""
        # Build a book that deliberately breaches a tight gross cap so the
        # scale-down path is exercised.
        book = {
            "AAA": 0.8,
            "BBB": -0.7,
            "CCC": 0.6,
        }
        cfg = LeverageConfig(max_gross=1.0, max_net=1.0)
        report = apply_leverage_limits(book, config=cfg)
        assert report.gross_before > cfg.max_gross
        assert report.gross_after <= cfg.max_gross + 1e-12
        assert report.net_after <= cfg.max_net + 1e-12
        assert "gross" in report.binding_constraints

    def test_stage2_within_cap_book_unchanged(
        self, sized_book: dict[str, float]
    ) -> None:
        """A sized book already within the cap passes through unscaled."""
        cfg = LeverageConfig(max_gross=2.0, max_net=1.0)
        report = apply_leverage_limits(dict(sized_book), config=cfg)
        gross = sum(abs(v) for v in sized_book.values())
        if gross <= cfg.max_gross and abs(sum(sized_book.values())) <= cfg.max_net:
            assert report.binding_constraints == []
            for sym, w in sized_book.items():
                assert report.weights[sym] == pytest.approx(w)

    def test_stage3_turnover_budget_scales_a_large_move(self) -> None:
        """check_turnover_budget scales an oversized rebalance to the budget."""
        # Realised history that already consumed some of the monthly budget.
        dates = pd.date_range("2021-06-01", periods=5, freq="B")
        history = pd.DataFrame(
            {
                "AAA": [0.0, 0.10, 0.10, 0.10, 0.10],
                "BBB": [0.0, 0.10, 0.10, 0.10, 0.10],
            },
            index=dates,
        )
        current = {"AAA": 0.10, "BBB": 0.10}
        # Propose a full rotation into a new name -> large turnover.
        proposed = {"AAA": 0.0, "BBB": 0.0, "CCC": 1.0}
        cfg = TurnoverConfig(max_monthly_turnover=0.30, periods_per_month=21)
        decision = check_turnover_budget(current, proposed, history, config=cfg)
        # The proposed move is large; with a tight cap it must be scaled.
        assert decision.proposed_turnover > decision.remaining_budget
        assert not decision.allowed
        assert decision.reason in {"breach_scaled", "no_budget"}
        if decision.reason == "breach_scaled":
            # Executed turnover equals the remaining budget (within tolerance).
            executed = (
                sum(
                    abs(decision.scaled_weights.get(k, 0.0) - current.get(k, 0.0))
                    for k in set(decision.scaled_weights) | set(current)
                )
                / 2.0
            )
            assert executed == pytest.approx(decision.remaining_budget, rel=1e-9)

    @pytest.fixture(scope="class")
    def allocator_weights(self) -> dict[str, float]:
        """Run the REAL Phase 6 allocator on a seeded panel."""
        panel = _build_strategy_returns_panel()
        cfg = StrategyAllocatorConfig(method="risk_parity")
        allocation = allocate_strategies(panel, cfg)
        # Convert to a plain dict (the money layer does not depend on pandas).
        return {str(k): float(v) for k, v in allocation.weights.items()}

    def test_stage4_allocator_weights_valid(
        self, allocator_weights: dict[str, float]
    ) -> None:
        """The Phase 6 allocator produced a clean positive weight split summing to 1."""
        assert set(allocator_weights) == {
            "alpha_momentum",
            "beta_meanrev",
            "gamma_carry",
        }
        assert all(w > 0.0 for w in allocator_weights.values())
        assert sum(allocator_weights.values()) == pytest.approx(1.0, abs=1e-9)

    def test_stage4_lifecycle_caps_overlay_allocator(
        self, allocator_weights: dict[str, float]
    ) -> None:
        """allocate_live_capital overlays lifecycle caps on the allocator weights."""
        cfg = LifecycleConfig()
        records = [
            # SCALED_LIVE: allocator weight sizes it (up to the ceiling).
            StrategyRecord(
                strategy_id="alpha_momentum",
                stage=StrategyStage.SCALED_LIVE,
                capital=40_000.0,
                days_at_stage=120,
                clean_days=120,
                paper_sharpe=0.10,
                live_sharpe=0.09,
                reference_sharpe=0.10,
                live_sharpe_negative_days=0,
                incident_count=0,
            ),
            # SMALL_LIVE: flat-sized at its own capital, ignoring the weight.
            StrategyRecord(
                strategy_id="beta_meanrev",
                stage=StrategyStage.SMALL_LIVE,
                capital=5_000.0,
                days_at_stage=20,
                clean_days=20,
                paper_sharpe=0.08,
                live_sharpe=0.07,
                reference_sharpe=0.09,
                live_sharpe_negative_days=0,
                incident_count=0,
            ),
            # PAPER: zero live capital regardless of allocator weight.
            StrategyRecord(
                strategy_id="gamma_carry",
                stage=StrategyStage.PAPER,
                capital=0.0,
                days_at_stage=15,
                clean_days=15,
                paper_sharpe=0.09,
                live_sharpe=None,
                reference_sharpe=0.10,
                live_sharpe_negative_days=0,
                incident_count=0,
            ),
        ]
        total_capital = 1_000_000.0
        live = allocate_live_capital(
            records,
            allocator_weights,
            total_capital=total_capital,
            config=cfg,
        )

        # PAPER strategy gets zero live capital.
        assert live["gamma_carry"] == 0.0
        # SMALL_LIVE is flat-sized at the record capital (allocator weight ignored).
        assert live["beta_meanrev"] == pytest.approx(5_000.0)
        # SCALED_LIVE sized by the allocator weight, capped at max_strategy_capital.
        expected_scaled = min(
            allocator_weights["alpha_momentum"] * total_capital,
            cfg.max_strategy_capital,
        )
        assert live["alpha_momentum"] == pytest.approx(expected_scaled)
        # Total deployed never exceeds total capital (cash held back).
        assert sum(live.values()) <= total_capital + 1e-6

    def test_stage4_small_live_capped_at_record_capital(
        self, allocator_weights: dict[str, float]
    ) -> None:
        """A SMALL_LIVE strategy is capped at its record capital, never the weight."""
        records = [
            StrategyRecord(
                strategy_id="alpha_momentum",
                stage=StrategyStage.SMALL_LIVE,
                capital=5_000.0,
                days_at_stage=20,
                clean_days=20,
                paper_sharpe=0.08,
                live_sharpe=0.07,
                reference_sharpe=0.09,
                live_sharpe_negative_days=0,
                incident_count=0,
            ),
            StrategyRecord(
                strategy_id="beta_meanrev",
                stage=StrategyStage.RESEARCH,
                capital=0.0,
                days_at_stage=5,
                clean_days=5,
                paper_sharpe=None,
                live_sharpe=None,
                reference_sharpe=0.10,
                live_sharpe_negative_days=0,
                incident_count=0,
            ),
            StrategyRecord(
                strategy_id="gamma_carry",
                stage=StrategyStage.DECOMMISSIONED,
                capital=0.0,
                days_at_stage=200,
                clean_days=0,
                paper_sharpe=0.02,
                live_sharpe=-0.05,
                reference_sharpe=0.10,
                live_sharpe_negative_days=70,
                incident_count=3,
            ),
        ]
        total_capital = 1_000_000.0
        live = allocate_live_capital(
            records,
            allocator_weights,
            total_capital=total_capital,
        )
        # SMALL_LIVE capped at its 5k record capital even though the allocator
        # weight * total_capital would be far larger.
        assert live["alpha_momentum"] == pytest.approx(5_000.0)
        weighted = allocator_weights["alpha_momentum"] * total_capital
        assert weighted > 5_000.0  # sanity: the weight WOULD have over-allocated
        # RESEARCH and DECOMMISSIONED strategies get nothing.
        assert live["beta_meanrev"] == 0.0
        assert live["gamma_carry"] == 0.0

    def test_full_pipeline_invariants_hold_together(
        self, sized_book: dict[str, float], allocator_weights: dict[str, float]
    ) -> None:
        """One pass through all four stages; every stage invariant holds."""
        # Stage 1: per-asset sizing already in sized_book.
        for w in sized_book.values():
            assert 0.0 <= w <= 0.40 + 1e-12

        # Stage 2: leverage limits.
        lev_cfg = LeverageConfig(max_gross=1.0, max_net=1.0)
        report = apply_leverage_limits(dict(sized_book), config=lev_cfg)
        assert report.gross_after <= lev_cfg.max_gross + 1e-12
        assert report.net_after <= lev_cfg.max_net + 1e-12

        # Stage 3: turnover budget against a (here empty) history allows the
        # first move in full.
        history = pd.DataFrame(columns=list(report.weights.keys()), dtype=float)
        decision = check_turnover_budget(
            {k: 0.0 for k in report.weights},
            dict(report.weights),
            history,
        )
        assert decision.allowed  # default 2.0 cap easily covers a single move

        # Stage 4: lifecycle overlay on the real allocator weights.
        records = [
            StrategyRecord(
                strategy_id="alpha_momentum",
                stage=StrategyStage.SCALED_LIVE,
                capital=40_000.0,
                days_at_stage=120,
                clean_days=120,
                paper_sharpe=0.10,
                live_sharpe=0.10,
                reference_sharpe=0.10,
                live_sharpe_negative_days=0,
                incident_count=0,
            ),
            StrategyRecord(
                strategy_id="beta_meanrev",
                stage=StrategyStage.SCALED_LIVE,
                capital=30_000.0,
                days_at_stage=120,
                clean_days=120,
                paper_sharpe=0.10,
                live_sharpe=0.10,
                reference_sharpe=0.10,
                live_sharpe_negative_days=0,
                incident_count=0,
            ),
            StrategyRecord(
                strategy_id="gamma_carry",
                stage=StrategyStage.SCALED_LIVE,
                capital=30_000.0,
                days_at_stage=120,
                clean_days=120,
                paper_sharpe=0.10,
                live_sharpe=0.10,
                reference_sharpe=0.10,
                live_sharpe_negative_days=0,
                incident_count=0,
            ),
        ]
        total_capital = 500_000.0
        live = allocate_live_capital(
            records, allocator_weights, total_capital=total_capital
        )
        assert set(live) == set(allocator_weights)
        for cap in live.values():
            assert cap >= 0.0
            assert cap <= LifecycleConfig().max_strategy_capital + 1e-6
        assert sum(live.values()) <= total_capital + 1e-6
