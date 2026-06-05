"""Phase 9 (execution layer) Definition-of-Done integration tests.

This module exercises the Phase 9 DOD checklist
(``docs/QUANT_TRADING_MASTER_PLAN.md`` ~line 1896) end-to-end against the
PACKAGE surface ``core_trading.execution`` (every symbol imported from the
package ``__init__`` so the public re-exports are themselves under test).  The
four DOD items, and the half of each that is feasible without a live TWS
session (the live half is operator-gated), are:

1. **All execution algorithms run in backtest and live** -- the BACKTEST half.
   ``TestExecutionAlgorithmsBacktest``.
2. **TCA report auto-generated daily** -- the generation PIPELINE.
   ``TestDailyTCAReport``.
3. **Market impact models calibrated on actual fills** -- the calibration
   pipeline on SIMULATED fills.  ``TestImpactCalibrationRoundTrip``.
4. **Reconciliation runs daily with zero unexplained mismatches** -- the
   zero-mismatch predicate + alert path.  ``TestReconciliationZeroMismatch``.

Supporting evidence for the adverse-selection wiring (Phase 9.5) is in
``TestAdverseSelectionWiring``.

The simulation recipe (shared across the classes)
-------------------------------------------------
A single deterministic intraday backtest fill simulator lives in this file
(``_simulate_fills``).  Given:

* a child-order schedule (unsigned per-interval clip magnitudes from any of the
  Phase 9.1 generators),
* a seeded intraday mid-price path of ``_N_BARS`` (78) five-minute bars built
  by a Gaussian random walk (``np.random.default_rng``), and
* a square-root temporary-impact model (the REAL
  ``core_trading.execution.ac_temporary_impact`` with ``ImpactACParams``),

it produces one simulated fill per non-zero clip.  Each clip ``i`` trades into
bar ``i`` (clips beyond the bar count wrap onto the last bar).  The fill price
is side-signed::

    participation_i = clip_i / bar_volume_i
    impact_i        = mid_i * ac_temporary_impact(participation_i, params)
    fill_price_i    = mid_i + side * (impact_i + half_spread_i)

so a BUY (``side = +1``) always pays mid plus impact plus half-spread -- a
strictly positive arrival-slippage cost under the repo positive-loss
convention -- and a SELL pays mid minus the same.  The simulator is pure and
deterministic: the only randomness is the seeded price/volume path, so
re-running the module on the same machine yields bit-identical fills, TCA
numbers, calibration coefficients and reconciliation verdicts.

Part A converts the simulated fills nowhere -- it asserts directly on the raw
schedules and fills.  Parts B/C re-shape the SAME simulated fills into the two
documented input contracts (the 13-column TCA fills frame and the
``calibrate_impact`` fills frame).  Part D drives the same fill stream through
the lifecycle state machine and the reconciliation engine.  Part E feeds the
seeded bar path through VPIN and the per-fill markouts through the toxicity
monitor.

Determinism
-----------
Every RNG call uses a fixed seed; there is no network, no sleep, no wall-clock
dependence on any asserted value.  Total runtime is well under five seconds.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt
import pandas as pd
import pytest

from core_trading.execution import (
    REQUIRED_FILL_COLUMNS,
    AckEvent,
    AdverseSelectionConfig,
    CancelEvent,
    ExecutionToxicityMonitor,
    FillEvent,
    ImpactACParams,
    LifecycleTracker,
    MismatchClass,
    MonitorState,
    OrderState,
    ReconciliationAlert,
    TCAConfig,
    ac_temporary_impact,
    ac_trajectory,
    adaptive_liquidity_schedule,
    arrival_price_schedule,
    build_daily_tca_report,
    calibrate_impact,
    iceberg_clip_sizes,
    pov_schedule,
    render_reconciliation,
    render_report,
    run_daily_reconciliation,
    validate_schedule,
    vpin,
)
from core_trading.execution.exec_algorithms import ACParams as SchedACParams
from core_trading.execution.tca import DailyTCAReport
from core_trading.execution.tca import main as tca_main

# ---------------------------------------------------------------------------
# Constants (tuned once, fixed for reproducibility)
# ---------------------------------------------------------------------------

_PRICE_SEED: int = 20260605      # rng seed for the intraday price/volume path
_N_BARS: int = 78                # 78 five-minute bars = one 6.5h session
_BAR_SECONDS: int = 300          # five-minute bars
_SESSION_OPEN: str = "2026-06-05 13:30:00"  # UTC; ~ US cash-open
_TOTAL_SHARES: float = 50_000.0
_START_PRICE: float = 100.0

# Square-root impact model used by the fill simulator (the "ground truth" the
# Part C calibration must recover).
_TRUE_ETA: float = 0.45
_TRUE_BETA: float = 0.5
_SIM_SIGMA: float = 0.02         # per-fill volatility fed to the impact model

_PARTICIPATION_CAP: float = 0.10  # POV max participation

# Smallest tradable child clip; sub-epsilon clips (float-cleanup tails) are not
# turned into fills by the simulator.
_CLIP_EPS: float = 1e-6


# ---------------------------------------------------------------------------
# Seeded intraday price / volume path
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _MarketPath:
    """A seeded intraday market path shared by every test class.

    Attributes
    ----------
    timestamps:
        ``_N_BARS`` five-minute bar timestamps (UTC ``DatetimeIndex``).
    mid:
        Mid-price path (Gaussian random walk, strictly positive).
    volume:
        Per-bar share volume (strictly positive).
    half_spread:
        Per-bar half-spread in price units (strictly positive).
    """

    timestamps: pd.DatetimeIndex
    mid: npt.NDArray[np.float64]
    volume: npt.NDArray[np.float64]
    half_spread: npt.NDArray[np.float64]


def _build_market_path(seed: int = _PRICE_SEED, n: int = _N_BARS) -> _MarketPath:
    """Build a deterministic intraday five-minute market path.

    The mid is a small-drift Gaussian random walk floored at a positive value;
    bar volumes follow a U-shaped intraday profile (heavy at the open/close)
    times a seeded multiplicative shock; the half-spread is a small positive
    fraction of the mid.
    """
    rng = np.random.default_rng(seed)
    timestamps = pd.date_range(_SESSION_OPEN, periods=n, freq="5min", tz="UTC")

    steps = rng.normal(0.0, 0.15, size=n)
    mid = _START_PRICE + np.cumsum(steps)
    mid = np.maximum(mid, 1.0)

    # U-shaped intraday volume profile (open + close heavy), times a shock.
    frac = np.linspace(0.0, 1.0, n)
    u_shape = 0.6 + 1.4 * (frac - 0.5) ** 2 * 4.0
    shock = rng.uniform(0.8, 1.2, size=n)
    volume = 40_000.0 * u_shape * shock

    half_spread = mid * rng.uniform(0.00005, 0.00020, size=n)

    return _MarketPath(
        timestamps=timestamps,
        mid=mid.astype(np.float64),
        volume=volume.astype(np.float64),
        half_spread=half_spread.astype(np.float64),
    )


# ---------------------------------------------------------------------------
# The backtest fill simulator (shared, deterministic)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _SimFill:
    """One simulated fill produced by ``_simulate_fills``.

    All prices are in price units; ``side`` is ``+1`` (buy) / ``-1`` (sell);
    ``participation = clip / bar_volume``; ``impact_frac`` is the square-root
    temporary-impact fraction applied to the mid for this clip.
    """

    interval: int
    timestamp: pd.Timestamp
    side: int
    clip: float
    mid: float
    bar_volume: float
    participation: float
    impact_frac: float
    half_spread: float
    fill_price: float


def _simulate_fills(
    schedule: npt.NDArray[np.float64],
    path: _MarketPath,
    *,
    side: int,
    params: ImpactACParams,
) -> list[_SimFill]:
    """Run a child schedule through the seeded path and return simulated fills.

    One fill per strictly-positive clip.  Clip ``i`` trades into bar
    ``min(i, n_bars - 1)`` (a schedule longer than the bar grid wraps its tail
    onto the last bar -- only the iceberg helper, whose clip count depends on
    ``display_size``, can exceed the bar count here).  The fill price is

        fill = mid + side * (mid * ac_temporary_impact(part, params) + half_spread)

    which is strictly worse than mid for the trader on both sides.
    """
    n_bars = path.mid.size
    fills: list[_SimFill] = []
    for i, clip in enumerate(schedule):
        clip_f = float(clip)
        # Skip zero and negligible (sub-microshare) clips: the schedule
        # generators may leave a ~1e-12 float-cleanup tail on the final
        # interval, which is not a tradable child order.
        if clip_f <= _CLIP_EPS:
            continue
        b = min(i, n_bars - 1)
        mid = float(path.mid[b])
        vol = float(path.volume[b])
        hs = float(path.half_spread[b])
        participation = clip_f / vol if vol > 0.0 else 0.0
        impact_frac = ac_temporary_impact(participation, params)
        fill_price = mid + side * (mid * impact_frac + hs)
        fills.append(
            _SimFill(
                interval=i,
                timestamp=path.timestamps[b],
                side=side,
                clip=clip_f,
                mid=mid,
                bar_volume=vol,
                participation=participation,
                impact_frac=impact_frac,
                half_spread=hs,
                fill_price=fill_price,
            )
        )
    return fills


# ---------------------------------------------------------------------------
# Module-level fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def market_path() -> _MarketPath:
    """The shared seeded intraday market path."""
    return _build_market_path()


@pytest.fixture(scope="module")
def impact_params() -> ImpactACParams:
    """The ground-truth square-root impact model used by the simulator."""
    return ImpactACParams(
        eta=_TRUE_ETA, gamma=0.05, beta=_TRUE_BETA, sigma=_SIM_SIGMA
    )


def _all_schedules(path: _MarketPath) -> dict[str, npt.NDArray[np.float64]]:
    """Build one schedule from every Phase 9.1 generator on the shared path.

    Every schedule sums to ``_TOTAL_SHARES`` and is validated here so the
    backtest-runs assertions can rely on the sum-to-total invariant.
    """
    n = path.mid.size
    out: dict[str, npt.NDArray[np.float64]] = {}

    # Almgren-Chriss trajectories at three risk-aversions (incl. TWAP limit).
    for tag, lam in (("ac_lam0", 0.0), ("ac_lam_lo", 1e-6), ("ac_lam_hi", 5e-5)):
        sched = ac_trajectory(
            _TOTAL_SHARES,
            n,
            params=SchedACParams(horizon=1.0, sigma=0.3, eta=0.1, lam=lam),
        )
        out[tag] = np.asarray(sched.trades, dtype=np.float64)

    # POV against the simulated bar volumes.
    out["pov"] = pov_schedule(
        _TOTAL_SHARES, path.volume, _PARTICIPATION_CAP, cleanup=True
    )

    # Arrival price: both variants (AC high-urgency and exponential decay).
    out["arrival_ac"] = arrival_price_schedule(
        _TOTAL_SHARES,
        n,
        params=SchedACParams(horizon=1.0, sigma=0.3, eta=0.1, lam=5e-5),
    )
    out["arrival_exp"] = arrival_price_schedule(
        _TOTAL_SHARES, n, front_load_factor=0.08
    )

    # Adaptive liquidity-seeking against the simulated bar volumes.
    out["adaptive"] = adaptive_liquidity_schedule(
        _TOTAL_SHARES,
        path.volume,
        min_clip=10.0,
        max_participation=_PARTICIPATION_CAP,
        urgency=1.0,
    )

    # Iceberg clip list (a flat sequence of equal clips + remainder).
    out["iceberg"] = np.asarray(
        iceberg_clip_sizes(_TOTAL_SHARES, display_size=900.0), dtype=np.float64
    )

    for arr in out.values():
        validate_schedule(arr, _TOTAL_SHARES)
    return out


# ===========================================================================
# Part A -- DOD 1: all execution algorithms run in backtest
# ===========================================================================


class TestExecutionAlgorithmsBacktest:
    """DOD 1 (backtest half): every Phase 9.1 schedule executes in backtest."""

    def test_every_schedule_validates_and_sums_to_total(
        self, market_path: _MarketPath
    ) -> None:
        schedules = _all_schedules(market_path)
        # Eight schedules from six distinct generators (AC x3, POV, arrival x2,
        # adaptive, iceberg).
        assert len(schedules) == 8
        for name, sched in schedules.items():
            validate_schedule(sched, _TOTAL_SHARES)
            assert np.isclose(sched.sum(), _TOTAL_SHARES, atol=1e-6), name

    def test_every_schedule_produces_fills_for_every_nonzero_clip(
        self, market_path: _MarketPath, impact_params: ImpactACParams
    ) -> None:
        schedules = _all_schedules(market_path)
        for name, sched in schedules.items():
            fills = _simulate_fills(
                sched, market_path, side=1, params=impact_params
            )
            tradable = int(np.count_nonzero(sched > _CLIP_EPS))
            assert len(fills) == tradable, name
            # Full quantity executed (fills reproduce the schedule total).
            executed = sum(f.clip for f in fills)
            assert np.isclose(executed, _TOTAL_SHARES, atol=1e-6), name

    def test_buy_fills_cost_positive_sell_fills_cost_positive(
        self, market_path: _MarketPath, impact_params: ImpactACParams
    ) -> None:
        # On BOTH sides every simulated fill is adverse vs its bar mid (the
        # positive-loss convention): buys fill above mid, sells below.
        sched = _all_schedules(market_path)["pov"]
        buys = _simulate_fills(sched, market_path, side=1, params=impact_params)
        sells = _simulate_fills(sched, market_path, side=-1, params=impact_params)
        for f in buys:
            assert f.fill_price > f.mid
        for f in sells:
            assert f.fill_price < f.mid

    def test_ac_higher_lambda_front_loads_more(
        self, market_path: _MarketPath
    ) -> None:
        # First-interval share of the parent strictly increases with lambda.
        n = market_path.mid.size
        shares: list[float] = []
        for lam in (0.0, 1e-6, 5e-5, 2e-4):
            sched = ac_trajectory(
                _TOTAL_SHARES,
                n,
                params=SchedACParams(horizon=1.0, sigma=0.3, eta=0.1, lam=lam),
            )
            shares.append(float(sched.trades[0]) / _TOTAL_SHARES)
        diffs = np.diff(shares)
        assert np.all(diffs > 0.0), shares
        # The risk-neutral (lambda=0) trajectory is exactly TWAP.
        assert shares[0] == pytest.approx(1.0 / n, abs=1e-9)

    def test_pov_respects_max_participation_against_simulated_volumes(
        self, market_path: _MarketPath
    ) -> None:
        sched = pov_schedule(
            _TOTAL_SHARES, market_path.volume, _PARTICIPATION_CAP, cleanup=False
        )
        # With cleanup=False no final-interval dump can breach the ceiling:
        # every clip stays at or below cap * bar_volume (a tiny float pad).
        participation = sched / market_path.volume
        assert np.all(participation <= _PARTICIPATION_CAP + 1e-9)

    def test_adaptive_completes_and_caps_each_interval(
        self, market_path: _MarketPath
    ) -> None:
        sched = adaptive_liquidity_schedule(
            _TOTAL_SHARES,
            market_path.volume,
            min_clip=10.0,
            max_participation=_PARTICIPATION_CAP,
            urgency=1.0,
        )
        validate_schedule(sched, _TOTAL_SHARES)
        assert np.isclose(sched.sum(), _TOTAL_SHARES, atol=1e-6)


# ---------------------------------------------------------------------------
# Shared helper: simulated fills -> the 13-column TCA fills contract
# ---------------------------------------------------------------------------


def _fills_to_tca_frame(
    fills: list[_SimFill],
    *,
    symbol: str,
    order_prefix: str,
) -> pd.DataFrame:
    """Map simulated fills to the 13-column ``REQUIRED_FILL_COLUMNS`` contract.

    Every simulated clip becomes one fully-filled order whose ``avg_fill_price``
    is the simulator's side-signed fill price.  ``decision_price`` and
    ``arrival_price`` are set to the bar mid the clip traded into, so the
    arrival-slippage metric isolates the per-clip impact + spread (a strictly
    positive cost on a buy) rather than the intraday drift of the mid away from
    a fixed session-open reference; ``mid_at_fill`` is that same bar mid.
    """
    rows: list[dict[str, object]] = []
    for f in fills:
        side_str = "buy" if f.side > 0 else "sell"
        rows.append(
            {
                "order_id": f"{order_prefix}{f.interval:03d}",
                "symbol": symbol,
                "side": side_str,
                "quantity": f.clip,
                "filled_quantity": f.clip,
                "decision_price": f.mid,
                "arrival_price": f.mid,
                "avg_fill_price": f.fill_price,
                "mid_at_fill": f.mid,
                "half_spread": f.half_spread,
                "fill_time": f.timestamp,
                "close_price": f.mid,
                "fees": f.clip * 0.001,
            }
        )
    frame = pd.DataFrame(rows)
    # Guard: the contract is exactly the 13 documented columns.
    for col in REQUIRED_FILL_COLUMNS:
        assert col in frame.columns
    return frame


# ===========================================================================
# Part B -- DOD 2: TCA report auto-generated daily
# ===========================================================================


class TestDailyTCAReport:
    """DOD 2: a daily TCA report is generated from the simulated fills."""

    def _report_and_fills(
        self, market_path: _MarketPath, impact_params: ImpactACParams
    ) -> tuple[pd.DataFrame, DailyTCAReport]:
        schedules = _all_schedules(market_path)
        # Two symbols traded the same day (POV buy, adaptive buy) so the report
        # has multiple symbols to aggregate.
        buys_a = _simulate_fills(
            schedules["pov"], market_path, side=1, params=impact_params
        )
        buys_b = _simulate_fills(
            schedules["adaptive"], market_path, side=1, params=impact_params
        )
        frame_a = _fills_to_tca_frame(buys_a, symbol="ALPH", order_prefix="A")
        frame_b = _fills_to_tca_frame(buys_b, symbol="BETA", order_prefix="B")
        fills = pd.concat([frame_a, frame_b], ignore_index=True)
        prices = pd.Series(market_path.mid, index=market_path.timestamps)
        report = build_daily_tca_report(fills, prices=prices)
        return fills, report

    def test_report_contains_every_symbol_traded(
        self, market_path: _MarketPath, impact_params: ImpactACParams
    ) -> None:
        fills, report = self._report_and_fills(market_path, impact_params)
        traded = set(fills["symbol"].unique())
        assert set(report.per_symbol.keys()) == traded
        assert report.portfolio["n_symbols"] == float(len(traded))

    def test_buy_slippage_is_positive_on_average(
        self, market_path: _MarketPath, impact_params: ImpactACParams
    ) -> None:
        # The impact model only ever pushes buy fills above arrival, so the
        # mean arrival slippage must be strictly positive (a cost) per symbol.
        _fills, report = self._report_and_fills(market_path, impact_params)
        for sym, stats in report.per_symbol.items():
            assert stats["mean_arrival_bps"] > 0.0, sym
        assert report.portfolio["mean_arrival_bps"] > 0.0

    def test_markouts_computed_at_configured_horizons(
        self, market_path: _MarketPath, impact_params: ImpactACParams
    ) -> None:
        _fills, report = self._report_and_fills(market_path, impact_params)
        cfg = TCAConfig()
        labels = {label for label, _secs in cfg.horizons}
        # Every fill carries the full horizon ladder; the early intraday
        # horizons (5m and below) are within the 78-bar window so at least one
        # finite markout must exist across the book.
        any_finite = False
        for fill in report.fills:
            assert set(fill.markout_bps.keys()) == labels
            if any(np.isfinite(v) for v in fill.markout_bps.values()):
                any_finite = True
        assert any_finite

    def test_render_report_is_pure_ascii(
        self, market_path: _MarketPath, impact_params: ImpactACParams
    ) -> None:
        _fills, report = self._report_and_fills(market_path, impact_params)
        text = render_report(report)
        assert text  # non-empty
        assert max(ord(c) for c in text) < 128

    def test_demo_cli_writes_report_file(self, tmp_path: Path) -> None:
        out = tmp_path / "tca_report.md"
        tca_main(["--demo", "--output", str(out)])
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "Daily TCA Report" in content
        assert max(ord(c) for c in content) < 128


# ===========================================================================
# Part C -- DOD 3: market impact models calibrated on (simulated) fills
# ===========================================================================


def _fills_to_calibration_frame(
    impact_params: ImpactACParams,
    *,
    seed: int,
    n_days: int,
) -> pd.DataFrame:
    """Generate many seeded simulated fills in the ``calibrate_impact`` contract.

    For a stable OLS fit we need variation in the participation regressor across
    a healthy sample.  Each "day" draws a fresh seeded market path and runs a
    POV schedule at a random participation cap, yielding clips that span a wide
    participation range.  The simulator's fill price embeds exactly the
    square-root law ``avg_fill = arrival * (1 + side * eta * sigma * part**beta)``
    (zero half-spread here so the calibration sees the pure impact signal), so
    a correct OLS must recover ``eta`` and ``beta``.
    """
    day_rng = np.random.default_rng(seed)
    rows: list[dict[str, object]] = []
    for d in range(n_days):
        path = _build_market_path(seed=seed + 1000 + d, n=_N_BARS)
        # Zero out the half-spread so the only cost is the impact law.
        clean_path = _MarketPath(
            timestamps=path.timestamps,
            mid=path.mid,
            volume=path.volume,
            half_spread=np.zeros_like(path.half_spread),
        )
        cap = float(day_rng.uniform(0.04, 0.16))
        sched = pov_schedule(
            _TOTAL_SHARES, clean_path.volume, cap, cleanup=False
        )
        side = 1 if d % 2 == 0 else -1
        fills = _simulate_fills(
            sched, clean_path, side=side, params=impact_params
        )
        for f in fills:
            if f.participation <= 0.0:
                continue
            side_str = "buy" if f.side > 0 else "sell"
            rows.append(
                {
                    "symbol": "SIMX",
                    "side": side_str,
                    "quantity": f.clip,
                    "adv": f.bar_volume * _N_BARS,
                    "sigma": impact_params.sigma,
                    "participation": f.participation,
                    "arrival_price": f.mid,
                    "avg_fill_price": f.fill_price,
                }
            )
    return pd.DataFrame(rows)


class TestImpactCalibrationRoundTrip:
    """DOD 3: calibrating on the simulated fills recovers the true law."""

    @pytest.fixture(scope="class")
    def calibration_frame(
        self, impact_params: ImpactACParams
    ) -> pd.DataFrame:
        return _fills_to_calibration_frame(
            impact_params, seed=_PRICE_SEED, n_days=20
        )

    def test_fit_is_well_determined_with_healthy_r2(
        self, calibration_frame: pd.DataFrame
    ) -> None:
        result = calibrate_impact(calibration_frame)
        assert result.well_determined is True
        assert result.n_obs > 100
        assert result.r_squared > 0.99

    def test_recovers_eta_and_beta_within_tolerance(
        self, calibration_frame: pd.DataFrame
    ) -> None:
        result = calibrate_impact(calibration_frame)
        # The log-linear fit recovers the simulator's ground-truth law.  The
        # fill price is arrival*(1 + side*eta*sigma*part**beta); for small x,
        # log(1+x) ~= x - x^2/2, a mild downward bias that keeps the estimates
        # close but not exact -- hence generous-but-meaningful tolerances.
        assert result.beta == pytest.approx(_TRUE_BETA, rel=0.05)
        assert result.eta == pytest.approx(_TRUE_ETA, rel=0.10)


# ---------------------------------------------------------------------------
# Shared helper: simulated fills -> reconciliation frames
# ---------------------------------------------------------------------------


def _fills_to_recon_frame(fills: list[_SimFill], order_id: str) -> pd.DataFrame:
    """Map simulated fills to the reconciliation per-fill contract.

    All clips of one schedule become partial fills of a single ``order_id`` so
    the reconciler exercises its per-order aggregation path.
    """
    rows = [
        {
            "order_id": order_id,
            "qty": f.clip,
            "price": f.fill_price,
            "fees": f.clip * 0.001,
        }
        for f in fills
    ]
    return pd.DataFrame(rows)


# ===========================================================================
# Part D -- DOD 4: lifecycle + reconciliation, zero unexplained mismatches
# ===========================================================================


class TestReconciliationZeroMismatch:
    """DOD 4: daily reconciliation is clean and the alert path fires correctly."""

    def test_lifecycle_drives_to_terminal_states(
        self, market_path: _MarketPath, impact_params: ImpactACParams
    ) -> None:
        schedules = _all_schedules(market_path)
        tracker = LifecycleTracker()

        # A fully-filled multi-clip order (POV) and a cancelled-remainder order
        # (adaptive: fill all but the last clip, then cancel).
        pov_fills = _simulate_fills(
            schedules["pov"], market_path, side=1, params=impact_params
        )
        adaptive_fills = _simulate_fills(
            schedules["adaptive"], market_path, side=1, params=impact_params
        )

        lc_full = tracker.register("POV-1", _TOTAL_SHARES)
        tracker.apply("POV-1", AckEvent(timestamp=pov_fills[0].timestamp))
        assert lc_full.state is OrderState.ACK
        for f in pov_fills:
            tracker.apply(
                "POV-1",
                FillEvent(
                    qty=f.clip,
                    price=f.fill_price,
                    timestamp=f.timestamp,
                    fees=f.clip * 0.001,
                ),
            )
        assert lc_full.state is OrderState.FILLED
        assert np.isclose(lc_full.filled_qty, _TOTAL_SHARES, atol=1e-6)

        # Cancelled-remainder case: fill all but the last clip, then cancel.
        head = adaptive_fills[:-1]
        partial_qty = sum(f.clip for f in head)
        lc_cancel = tracker.register("ADP-1", _TOTAL_SHARES)
        tracker.apply("ADP-1", AckEvent(timestamp=adaptive_fills[0].timestamp))
        for f in head:
            tracker.apply(
                "ADP-1",
                FillEvent(
                    qty=f.clip, price=f.fill_price, timestamp=f.timestamp
                ),
            )
        assert lc_cancel.state is OrderState.PARTIAL
        tracker.apply(
            "ADP-1", CancelEvent(timestamp=adaptive_fills[-1].timestamp)
        )
        assert lc_cancel.state is OrderState.CANCELLED
        assert np.isclose(lc_cancel.filled_qty, partial_qty, atol=1e-6)
        assert lc_cancel.remaining_qty > 0.0

    def _recon_frames(
        self, market_path: _MarketPath, impact_params: ImpactACParams
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        schedules = _all_schedules(market_path)
        frames: list[pd.DataFrame] = []
        for name in ("pov", "adaptive", "arrival_exp"):
            fills = _simulate_fills(
                schedules[name], market_path, side=1, params=impact_params
            )
            frames.append(_fills_to_recon_frame(fills, order_id=f"ORD-{name}"))
        internal = pd.concat(frames, ignore_index=True)
        # Broker frame is the SAME fill stream (a faithful drop-copy).
        broker = internal.copy()
        return internal, broker

    def test_clean_reconciliation_zero_mismatches_no_alerts(
        self, market_path: _MarketPath, impact_params: ImpactACParams
    ) -> None:
        internal, broker = self._recon_frames(market_path, impact_params)
        alerts: list[ReconciliationAlert] = []
        report = run_daily_reconciliation(
            internal, broker, alert_fn=alerts.append
        )
        # The Phase 9 DOD predicate: zero unexplained mismatches.
        assert report.clean is True
        assert len(report.mismatches) == 0
        assert report.matched == 3
        assert alerts == []
        text = render_reconciliation(report)
        assert "CLEAN" in text
        assert max(ord(c) for c in text) < 128

    def test_perturbed_broker_row_fires_exactly_one_alert(
        self, market_path: _MarketPath, impact_params: ImpactACParams
    ) -> None:
        internal, broker = self._recon_frames(market_path, impact_params)
        # Bump one broker qty well beyond the default qty tolerance (1e-6).
        broker = broker.copy()
        target = broker.index[broker["order_id"] == "ORD-pov"][0]
        broker.loc[target, "qty"] = float(broker.loc[target, "qty"]) + 25.0

        alerts: list[ReconciliationAlert] = []
        report = run_daily_reconciliation(
            internal, broker, alert_fn=alerts.append
        )
        assert report.clean is False
        assert len(report.mismatches) == 1
        assert len(alerts) == 1
        only = report.mismatches[0]
        assert only.kind is MismatchClass.QTY_MISMATCH
        assert only.order_id == "ORD-pov"
        assert alerts[0].mismatch is only
        # The other two orders still reconcile.
        assert report.matched == 2

        text = render_reconciliation(report)
        assert "MISMATCHES FOUND" in text
        assert "QTY_MISMATCH" in text
        assert "ORD-pov" in text
        assert max(ord(c) for c in text) < 128


# ===========================================================================
# Part E -- adverse-selection wiring (supporting evidence, Phase 9.5)
# ===========================================================================


class TestAdverseSelectionWiring:
    """Phase 9.5 VPIN + toxicity monitor on the simulated path."""

    def test_vpin_on_simulated_path_in_unit_interval(
        self, market_path: _MarketPath
    ) -> None:
        # bucket_size tuned so several buckets complete over the 78-bar session.
        cfg = AdverseSelectionConfig(
            sigma_window=10, bucket_size=200_000.0, n_buckets=3
        )
        prices = pd.Series(market_path.mid, index=market_path.timestamps)
        volumes = pd.Series(market_path.volume, index=market_path.timestamps)
        series = vpin(prices, volumes, config=cfg)
        clean = series.dropna()
        assert len(clean) >= 1
        assert bool(((clean >= 0.0) & (clean <= 1.0)).all())

    def test_monitor_stays_active_on_benign_then_pauses_on_toxic_burst(
        self,
    ) -> None:
        cfg = AdverseSelectionConfig(
            markout_window=8,
            drift_t_threshold=2.0,
            toxicity_threshold=0.7,
            cooldown_buckets=3,
        )
        monitor = ExecutionToxicityMonitor(config=cfg)

        # Benign phase: small, mean-zero markouts (no adverse drift) -> ACTIVE.
        benign_rng = np.random.default_rng(_PRICE_SEED + 7)
        benign = benign_rng.normal(0.0, 0.5, size=20)
        for i in range(2, len(benign) + 1):
            window = pd.Series(benign[:i])
            monitor.update(f"benign-{i}", markouts=window)
        assert monitor.state is MonitorState.ACTIVE
        assert monitor.status is MonitorState.ACTIVE

        # Toxic burst: a one-sided run of strongly adverse markouts -> PAUSED.
        toxic = pd.Series(np.full(cfg.markout_window, 5.0))
        monitor.update("toxic", markouts=toxic)
        assert monitor.state is MonitorState.PAUSED
        assert monitor.paused is True
        assert "markout drift" in monitor.last_reason
        assert monitor.events[-1].trigger.value == "MARKOUT_DRIFT"

        # Re-arm: feed exactly cooldown_buckets clean readings -> ACTIVE.
        clean = pd.Series(np.full(cfg.markout_window, -1.0))
        for k in range(cfg.cooldown_buckets):
            monitor.update(f"recover-{k}", markouts=clean)
        assert monitor.state is MonitorState.ACTIVE
        assert monitor.events[-1].trigger.value == "COOLDOWN"
