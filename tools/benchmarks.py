"""Performance benchmarks for the quant trading stack (master plan Phase 10.5).

A runnable script -- NOT a pytest module -- that measures and prints an
ASCII-only table of throughput / latency / memory for the hot paths a research
or production loop exercises most:

* Backtest throughput (bars/second) through the Phase 3 engine, run in BOTH the
  vectorised and event-driven modes over a seeded synthetic OHLCV panel.
* Execution-schedule generation (Almgren-Chriss ``ac_trajectory`` and
  percent-of-volume ``pov_schedule``) in calls/second.
* Risk / microstructure compute throughput: historical VaR and VPIN over a
  seeded series, in calls/second.
* Memory: peak resident allocation (via ``tracemalloc``) for one event-driven
  backtest run.

Methodology
-----------
* All inputs are seeded (``numpy.random.default_rng(SEED)``) so the numbers are
  reproducible run-to-run on the same machine.
* Each benchmark performs a warmup pass (to amortise import / JIT-free Python
  warm caches) and then ``N_REPEATS`` timed repeats with
  :func:`time.perf_counter`; the reported figure is the MEDIAN repeat (robust to
  the occasional GC pause), never the mean.
* No external benchmarking dependency is used (no pytest-benchmark, no asv) --
  only the standard library plus the project's own modules.

Operator-gated half
-------------------
The *live* half of Phase 10.5 -- tick-to-order wire latency -- is intentionally
NOT measured here.  It requires a live (or paper) broker session and a real
market-data feed, both of which are operator-gated deployment concerns outside
this repo.  This script benches only the deterministic, in-process compute.

Usage
-----
``.venv/bin/python tools/benchmarks.py``
    Run all benchmarks and print the ASCII table to stdout.

``.venv/bin/python tools/benchmarks.py --output PATH``
    Also write the table to ``PATH``.

``.venv/bin/python tools/benchmarks.py --repeats N --bars M``
    Override the repeat count and the synthetic-panel bar count.
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
import tracemalloc
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from core_trading.backtest import (
    BacktestConfig,
    BacktestEngine,
    WeightStrategy,
)
from core_trading.execution.adverse_selection import vpin
from core_trading.execution.exec_algorithms import (
    ACParams,
    ac_trajectory,
    pov_schedule,
)
from core_trading.risk.var import VaRConfig, historical_var

SEED = 42
DEFAULT_REPEATS = 5
DEFAULT_BARS = 1000
DEFAULT_SYMBOLS = 8


# ---------------------------------------------------------------------------
# Result DTO and timing core
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BenchResult:
    """One benchmark line.

    Attributes
    ----------
    name:
        Human-readable benchmark name.
    median_seconds:
        Median wall-clock time of a single timed unit across repeats.
    unit_count:
        Number of work units processed per timed unit (bars, calls, ...).
    unit_label:
        Label for the throughput denominator (e.g. ``"bars"``, ``"calls"``).
    """

    name: str
    median_seconds: float
    unit_count: int
    unit_label: str

    @property
    def throughput(self) -> float:
        """Work units per second (``unit_count / median_seconds``)."""
        if self.median_seconds <= 0.0:
            return float("inf")
        return self.unit_count / self.median_seconds


def _time_median(
    fn: Callable[[], object],
    *,
    repeats: int,
    warmup: int = 1,
) -> float:
    """Run ``fn`` ``warmup`` times (untimed) then ``repeats`` times (timed).

    Returns the MEDIAN timed duration in seconds.
    """
    for _ in range(warmup):
        fn()
    durations: list[float] = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        durations.append(time.perf_counter() - start)
    return statistics.median(durations)


# ---------------------------------------------------------------------------
# Seeded synthetic data builders
# ---------------------------------------------------------------------------


def build_price_panel(n_bars: int, n_symbols: int, *, seed: int = SEED) -> pd.DataFrame:
    """Build a seeded synthetic OHLCV panel with a (symbol, timestamp) index.

    The panel matches the Phase 3 engine contract: a 2-level MultiIndex named
    ``['symbol', 'timestamp']`` with ``open/high/low/close/volume`` columns.
    """
    rng = np.random.default_rng(seed)
    timestamps = pd.date_range("2020-01-01", periods=n_bars, freq="B")
    frames: list[pd.DataFrame] = []
    for s in range(n_symbols):
        symbol = f"SYM{s:02d}"
        rets = rng.normal(0.0003, 0.012, size=n_bars)
        close = 100.0 * np.cumprod(1.0 + rets)
        open_ = close * (1.0 + rng.normal(0.0, 0.001, size=n_bars))
        high = np.maximum(open_, close) * (1.0 + np.abs(rng.normal(0.0, 0.002, size=n_bars)))
        low = np.minimum(open_, close) * (1.0 - np.abs(rng.normal(0.0, 0.002, size=n_bars)))
        volume = rng.uniform(1e5, 5e5, size=n_bars)
        idx = pd.MultiIndex.from_product(
            [[symbol], timestamps], names=["symbol", "timestamp"]
        )
        frames.append(
            pd.DataFrame(
                {
                    "open": open_,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": volume,
                },
                index=idx,
            )
        )
    return pd.concat(frames).sort_index()


def build_weight_frame(panel: pd.DataFrame) -> pd.DataFrame:
    """Build an equal-weight target-weight frame aligned to the panel."""
    close = panel["close"].unstack("symbol").sort_index()
    n_symbols = close.shape[1]
    return pd.DataFrame(
        1.0 / n_symbols, index=close.index, columns=close.columns
    )


def build_return_series(n: int, *, seed: int = SEED) -> pd.Series:
    """Seeded daily-return series for VaR benchmarking."""
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(0.0005, 0.013, size=n), name="returns")


def build_ohlcv_series(n: int, *, seed: int = SEED) -> tuple[pd.Series, pd.Series]:
    """Seeded (prices, volumes) pair for VPIN benchmarking."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0, 0.01, size=n)
    prices = pd.Series(100.0 * np.cumprod(1.0 + rets), name="close")
    volumes = pd.Series(rng.uniform(800.0, 1200.0, size=n), name="volume")
    return prices, volumes


# ---------------------------------------------------------------------------
# Individual benchmarks
# ---------------------------------------------------------------------------


def bench_backtest_vectorised(
    panel: pd.DataFrame, weights: pd.DataFrame, *, repeats: int
) -> BenchResult:
    """Backtest throughput in vectorised mode (bars/second)."""
    engine = BacktestEngine(BacktestConfig(seed=SEED))
    strategy = WeightStrategy(weights)
    n_bars = int(panel.index.get_level_values("timestamp").nunique())
    median = _time_median(
        lambda: engine.run_vectorised(panel, strategy), repeats=repeats
    )
    return BenchResult("backtest vectorised", median, n_bars, "bars")


def bench_backtest_event_driven(
    panel: pd.DataFrame, weights: pd.DataFrame, *, repeats: int
) -> BenchResult:
    """Backtest throughput in event-driven mode (bars/second)."""
    engine = BacktestEngine(BacktestConfig(seed=SEED))
    strategy = WeightStrategy(weights)
    n_bars = int(panel.index.get_level_values("timestamp").nunique())
    median = _time_median(
        lambda: engine.run_event_driven(panel, strategy), repeats=repeats
    )
    return BenchResult("backtest event-driven", median, n_bars, "bars")


def bench_ac_trajectory(*, repeats: int, n_calls: int = 2000) -> BenchResult:
    """Almgren-Chriss schedule generation throughput (calls/second)."""
    params = ACParams(horizon=1.0, sigma=0.3, eta=0.1, gamma=0.05, lam=2e-6)

    def _run() -> None:
        for _ in range(n_calls):
            ac_trajectory(1_000_000.0, 50, params=params)

    median = _time_median(_run, repeats=repeats)
    return BenchResult("ac_trajectory", median, n_calls, "calls")


def bench_pov_schedule(*, repeats: int, n_calls: int = 5000) -> BenchResult:
    """Percent-of-volume schedule generation throughput (calls/second)."""
    rng = np.random.default_rng(SEED)
    volumes = rng.uniform(1e4, 5e4, size=50)

    def _run() -> None:
        for _ in range(n_calls):
            pov_schedule(500_000.0, volumes, 0.1)

    median = _time_median(_run, repeats=repeats)
    return BenchResult("pov_schedule", median, n_calls, "calls")


def bench_historical_var(returns: pd.Series, *, repeats: int, n_calls: int = 2000) -> BenchResult:
    """Historical VaR throughput (calls/second)."""
    cfg = VaRConfig(confidence=0.99, horizon=1, rng_seed=SEED)

    def _run() -> None:
        for _ in range(n_calls):
            historical_var(returns, config=cfg)

    median = _time_median(_run, repeats=repeats)
    return BenchResult("historical_var", median, n_calls, "calls")


def bench_vpin(prices: pd.Series, volumes: pd.Series, *, repeats: int, n_calls: int = 20) -> BenchResult:
    """VPIN computation throughput (calls/second).

    Note: ``vpin`` is markedly more expensive per call than the other compute
    benchmarks (it scales super-linearly in the input length), so ``n_calls``
    is deliberately small and the input series is bounded (see
    :func:`run_all`).  The reported figure is still a per-call throughput.
    """
    def _run() -> None:
        for _ in range(n_calls):
            vpin(prices, volumes)

    median = _time_median(_run, repeats=repeats)
    return BenchResult("vpin", median, n_calls, "calls")


def measure_backtest_peak_rss(panel: pd.DataFrame, weights: pd.DataFrame) -> float:
    """Peak traced allocation (MiB) for one event-driven backtest run.

    Uses :mod:`tracemalloc`, which measures Python-object allocation rather than
    OS RSS; it is deterministic and dependency-free, and is the closest portable
    proxy for the run's memory footprint.
    """
    engine = BacktestEngine(BacktestConfig(seed=SEED))
    strategy = WeightStrategy(weights)
    tracemalloc.start()
    tracemalloc.reset_peak()
    engine.run_event_driven(panel, strategy)
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return peak / (1024.0 * 1024.0)


# ---------------------------------------------------------------------------
# Orchestration and rendering
# ---------------------------------------------------------------------------


def run_all(
    *, n_bars: int, n_symbols: int, repeats: int
) -> tuple[list[BenchResult], float, dict[str, int]]:
    """Run every benchmark; return (results, peak_mib, environment-sizes)."""
    panel = build_price_panel(n_bars, n_symbols)
    weights = build_weight_frame(panel)
    returns = build_return_series(max(n_bars, 256))
    # VPIN scales super-linearly in series length and is the most expensive
    # compute benchmark; bound its input to a realistic microstructure window
    # (a few hundred bars) so the default invocation completes promptly.
    vpin_len = min(max(n_bars, 256), 512)
    prices, volumes = build_ohlcv_series(vpin_len)

    results = [
        bench_backtest_vectorised(panel, weights, repeats=repeats),
        bench_backtest_event_driven(panel, weights, repeats=repeats),
        bench_ac_trajectory(repeats=repeats),
        bench_pov_schedule(repeats=repeats),
        bench_historical_var(returns, repeats=repeats),
        bench_vpin(prices, volumes, repeats=repeats),
    ]
    peak_mib = measure_backtest_peak_rss(panel, weights)
    sizes = {
        "bars": n_bars,
        "symbols": n_symbols,
        "repeats": repeats,
    }
    return results, peak_mib, sizes


def render_table(
    results: list[BenchResult], peak_mib: float, sizes: dict[str, int]
) -> str:
    """Render the benchmark results as an ASCII-only table."""
    lines: list[str] = []
    lines.append("# Phase 10.5 Performance Benchmarks")
    lines.append("")
    lines.append(
        f"Panel: {sizes['bars']} bars x {sizes['symbols']} symbols | "
        f"repeats: {sizes['repeats']} (median reported) | seed: {SEED}"
    )
    lines.append(
        "Python compute only; tick-to-order live latency is operator-gated."
    )
    lines.append("")

    w_name = 26
    w_med = 14
    w_thru = 20
    header = (
        f"| {'Benchmark':<{w_name}} "
        f"| {'Median (ms)':<{w_med}} "
        f"| {'Throughput':<{w_thru}} |"
    )
    divider = (
        f"|{'-' * (w_name + 2)}"
        f"|{'-' * (w_med + 2)}"
        f"|{'-' * (w_thru + 2)}|"
    )
    lines.append(header)
    lines.append(divider)
    for r in results:
        median_ms = r.median_seconds * 1000.0
        thru = f"{r.throughput:,.0f} {r.unit_label}/s"
        lines.append(
            f"| {r.name:<{w_name}} "
            f"| {median_ms:<{w_med}.3f} "
            f"| {thru:<{w_thru}} |"
        )
    lines.append("")
    lines.append("## Memory")
    lines.append("")
    lines.append(
        f"Event-driven backtest peak traced allocation: {peak_mib:.2f} MiB "
        f"(tracemalloc)"
    )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Parse args, run benchmarks, print (and optionally write) the table."""
    parser = argparse.ArgumentParser(
        prog="python tools/benchmarks.py",
        description="Phase 10.5 performance benchmarks (Python compute only).",
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        default=None,
        help="Write the ASCII benchmark table to this file path.",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=DEFAULT_REPEATS,
        help=f"Timed repeats per benchmark (median reported). Default {DEFAULT_REPEATS}.",
    )
    parser.add_argument(
        "--bars",
        type=int,
        default=DEFAULT_BARS,
        help=f"Synthetic-panel bar count. Default {DEFAULT_BARS}.",
    )
    parser.add_argument(
        "--symbols",
        type=int,
        default=DEFAULT_SYMBOLS,
        help=f"Synthetic-panel symbol count. Default {DEFAULT_SYMBOLS}.",
    )
    args = parser.parse_args(argv)

    if args.repeats < 1:
        parser.error("--repeats must be >= 1")
    if args.bars < 32:
        parser.error("--bars must be >= 32")
    if args.symbols < 1:
        parser.error("--symbols must be >= 1")

    results, peak_mib, sizes = run_all(
        n_bars=args.bars, n_symbols=args.symbols, repeats=args.repeats
    )
    table = render_table(results, peak_mib, sizes)
    print(table)

    if args.output is not None:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(table)
        print(f"[benchmarks] Table written to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
