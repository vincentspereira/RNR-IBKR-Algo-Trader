"""Whole-house strategy validation sweep on long history (free data).

The build-everything-then-validate work order's final step: every
engine-runnable strategy family in the repo -- the TA x quant mix-and-match
grid, the classical rewrites (batches 1+2), and the cross-sectional signal
adapters -- is walked forward over ~21 years of free daily data and gated
through the Phase 10 statistical robustness battery, exactly the
methodology that REJECTED the pairs pilot (docs/PAIRS_RESEARCH_PASS_2026-06.md).

Methodology (inherited from tools/pairs_research_pass.py)
----------------------------------------------------------
* FIXED walk-forward skeleton (formation 252 warm-up + trading 126 OOS bars,
  rolled contiguously) so every config shares one calendar: the trial matrix
  aligns by construction. For these rolling-signal strategies the formation
  segment is pure indicator warm-up (no fitting); only bars [formation:] of
  each window are scored.
* Net of costs: the engine's vectorised mode with the "ibkr" cost model
  (linear per-unit-turnover charge). High-turnover configs pay their way.
* The FULL sweep (~95 configs) is the trial bank handed to the DSR / PBO /
  Reality-Check gates -- the search is what those tests deflate against.
* Era-stability table for every family champion: a full-period Sharpe carried
  by a dead regime (the pairs failure mode) is visible immediately.
* Data: adjusted OHLCV for the current SP100 universe via yfinance
  (snapshot cached). OHLC are scaled by adjusted_close/close so splits and
  dividends do not fake breakouts; volume is the raw share count.

  SURVIVORSHIP CAVEAT (same as the pairs pass): current constituents over
  historical windows flatter results. PROMOTE is an upper bound pending
  point-in-time constituents (Norgate); REJECT is close to decisive.

Run:
    .venv/Scripts/python.exe tools/strategy_research_sweep.py                # full sweep
    .venv/Scripts/python.exe tools/strategy_research_sweep.py --quick       # smoke
    .venv/Scripts/python.exe tools/strategy_research_sweep.py --fetch-only  # refresh snapshot
    .venv/Scripts/python.exe tools/strategy_research_sweep.py --family ta_quant
"""
from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from pairs_research_pass import (  # noqa: E402
    annualised_sharpe,
    era_table,
    max_drawdown,
    window_starts,
)

OUT_DIR = REPO_ROOT / "logs" / "strategy_sweep"
SNAPSHOT = OUT_DIR / "ohlcv_yf.parquet"
DEFAULT_START = "2005-01-01"
FIELDS = ("open", "high", "low", "close", "volume")


# ---------------------------------------------------------------------------
# Data: adjusted OHLCV snapshot
# ---------------------------------------------------------------------------


def fetch_ohlcv_snapshot(start: str) -> pd.DataFrame:
    """Fetch adjusted OHLCV for the SP100 universe and cache it.

    Returns a wide frame with MultiIndex columns ``(field, symbol)`` for
    fields open/high/low/close/volume. OHLC are adjusted by the per-bar
    factor ``adjusted_close / close`` (standard back-adjustment) so that
    long-history levels are split/dividend consistent; volume is raw.
    """
    import datetime as _dt

    from core_trading.data.bars import BarResolution
    from core_trading.data.sources.yfinance_source import fetch_bars_sync
    from core_trading.data.universe import SP100

    symbols = list(SP100.current_symbols())
    print(f"fetching {len(symbols)} symbols (OHLCV) from {start} via yfinance ...")
    raw = fetch_bars_sync(
        symbols,
        _dt.date.fromisoformat(start),
        _dt.date.today(),
        resolution=BarResolution.DAY_1,
    )
    if raw.empty:
        raise SystemExit("ERR: yfinance returned no data")

    factor = (raw["adjusted_close"] / raw["close"]).replace([np.inf, -np.inf], np.nan)
    wide_parts: dict[tuple[str, str], pd.Series] = {}
    for field in FIELDS:
        series = raw[field] * factor if field in ("open", "high", "low", "close") else raw[field]
        wide = series.unstack("symbol").sort_index()
        wide.index = wide.index.tz_localize(None).normalize()
        for sym in wide.columns:
            wide_parts[(field, str(sym))] = wide[sym]
    panel = pd.DataFrame(wide_parts)
    panel.columns = pd.MultiIndex.from_tuples(panel.columns, names=["field", "symbol"])

    empty = [s for s in panel["close"].columns if panel[("close", s)].dropna().empty]
    if empty:
        print(f"WARN: no data for {', '.join(sorted(empty))}; dropped")
        panel = panel.drop(columns=[(f, s) for f in FIELDS for s in empty], errors="ignore")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(SNAPSHOT)
    close = panel["close"]
    print(
        f"snapshot: {close.shape[0]} sessions x {close.shape[1]} symbols x {len(FIELDS)} fields "
        f"({close.index[0].date()} .. {close.index[-1].date()}) -> {SNAPSHOT}"
    )
    return panel


def load_ohlcv(start: str, refetch: bool) -> pd.DataFrame:
    if SNAPSHOT.exists() and not refetch:
        panel = pd.read_parquet(SNAPSHOT)
        close = panel["close"]
        print(
            f"loaded snapshot: {close.shape[0]} sessions x {close.shape[1]} symbols "
            f"({close.index[0].date()} .. {close.index[-1].date()})"
        )
        return panel
    return fetch_ohlcv_snapshot(start)


def load_sectors(symbols: list[str]) -> dict[str, str]:
    from core_trading.data.reference import build_starter_reference

    ref = build_starter_reference()
    return {s: sec for s in symbols if (sec := ref.sector_of(s))}


def valid_window_symbols(wide: pd.DataFrame) -> list[str]:
    """Symbols with complete positive close AND positive volume over the slice."""
    close, volume = wide["close"], wide["volume"]
    ok = (
        close.notna().all(axis=0)
        & (close > 0).all(axis=0)
        & volume.notna().all(axis=0)
        & (volume > 0).all(axis=0)
    )
    return [str(c) for c in close.columns[ok]]


def engine_panel(wide: pd.DataFrame, symbols: list[str]) -> pd.DataFrame:
    """(symbol, timestamp) MultiIndex OHLCV panel from a wide slice."""
    parts: list[pd.DataFrame] = []
    for sym in symbols:
        df = pd.DataFrame(
            {field: wide[(field, sym)] for field in FIELDS}, index=wide.index
        )
        df.index = pd.MultiIndex.from_product(
            [[sym], wide.index], names=["symbol", "timestamp"]
        )
        parts.append(df)
    return pd.concat(parts).sort_index()


# ---------------------------------------------------------------------------
# Strategy wrappers (everything becomes an engine Strategy)
# ---------------------------------------------------------------------------


class PerSymbolRuleStrategy:
    """Cross-sectional wrapper over a per-symbol classical signal function.

    ``signal_fn(ohlcv_frame, config) -> position Series in {-1, 0, +1}`` is
    applied to every symbol; active positions are equal-weighted to
    ``gross_cap`` (the TAQuantStrategy convention).
    """

    def __init__(
        self,
        signal_fn: Callable[..., pd.Series],
        config: object,
        *,
        gross_cap: float = 1.0,
    ) -> None:
        self.signal_fn = signal_fn
        self.config = config
        self.gross_cap = gross_cap

    def generate_weights(self, prices: pd.DataFrame) -> pd.DataFrame:
        close = prices["close"].unstack("symbol").sort_index()
        positions = pd.DataFrame(0.0, index=close.index, columns=close.columns)
        for sym in close.columns:
            ohlcv = (
                prices.xs(sym, level="symbol")[list(FIELDS)].sort_index()
            )
            positions[sym] = self.signal_fn(ohlcv, self.config).to_numpy()
        active = positions.abs().sum(axis=1).replace(0.0, np.nan)
        return positions.div(active, axis=0).fillna(0.0) * self.gross_cap


class WeightRuleStrategy:
    """Wrapper over the signal-adapter ``build_*_weight_fn`` pattern.

    ``builder(wide_close) -> WeightRule`` is invoked per window (the builders
    compute their score panels look-ahead-free), then the rule is applied
    with ``params``.
    """

    def __init__(
        self,
        builder: Callable[[pd.DataFrame], Callable[..., pd.DataFrame]],
        params: Mapping[str, float],
    ) -> None:
        self.builder = builder
        self.params = params

    def generate_weights(self, prices: pd.DataFrame) -> pd.DataFrame:
        close = prices["close"].unstack("symbol").sort_index()
        rule = self.builder(close)
        return rule(prices, self.params)


# ---------------------------------------------------------------------------
# Families
# ---------------------------------------------------------------------------


def build_families(quick: bool) -> list[tuple[str, str, Callable[[], object]]]:
    """(family, name, strategy_factory) for every config in the sweep."""
    from core_trading.research.signal_adapters.cross_sectional_momentum import (
        build_momentum_weight_fn,
    )
    from core_trading.research.signal_adapters.pca_stat_arb import (
        build_pca_statarb_weight_fn,
    )
    from core_trading.signals.factors.momentum import MomentumConfig
    from core_trading.strategies.classical.volatility_breakout import (
        BreakoutConfig,
        breakout_signal,
    )
    from core_trading.strategies.classical.volume_weighted_trend import (
        VWTrendConfig,
        vw_trend_signal,
    )
    from core_trading.strategies.classical.vw_mean_reversion import (
        VWMeanReversionConfig,
        vw_mean_reversion_signal,
    )
    from core_trading.strategies.ta_quant import TAQuantStrategy, build_ta_quant_grid

    entries: list[tuple[str, str, Callable[[], object]]] = []

    # --- TA x quant grid (85 configs) ---
    grid = build_ta_quant_grid()
    if quick:
        grid = grid[:2]
    for name, cfg in grid:
        entries.append(
            ("ta_quant", name, lambda c=cfg: TAQuantStrategy(c))  # type: ignore[misc]
        )

    # --- classical batches 1+2 (2 variants each) ---
    classical: list[tuple[str, Callable[..., pd.Series], object]] = [
        ("breakout_default", breakout_signal, BreakoutConfig()),
        ("breakout_loose", breakout_signal, BreakoutConfig(vol_k=1.1)),
        ("vwtrend_default", vw_trend_signal, VWTrendConfig()),
        ("vwmr_default", vw_mean_reversion_signal, VWMeanReversionConfig()),
        ("vwmr_loose", vw_mean_reversion_signal, VWMeanReversionConfig(vol_k=1.0)),
    ]
    if quick:
        classical = classical[:1]
    for name, fn, cfg in classical:
        entries.append(
            (
                "classical",
                name,
                lambda f=fn, c=cfg: PerSymbolRuleStrategy(f, c),  # type: ignore[misc]
            )
        )

    # --- cross-sectional adapters ---
    if not quick:
        mom_cfg = MomentumConfig(lookback=252, skip=21, vol_window=60)
        for q in (0.2, 0.4):
            entries.append(
                (
                    "csmom",
                    f"csmom_q{q}",
                    lambda qq=q: WeightRuleStrategy(
                        lambda close: build_momentum_weight_fn(close, config=mom_cfg),
                        {"quantile": qq},
                    ),
                )
            )
        for q in (0.2, 0.4):
            entries.append(
                (
                    "pca_statarb",
                    f"pca5_lb60_q{q}",
                    lambda qq=q: WeightRuleStrategy(
                        lambda close: build_pca_statarb_weight_fn(
                            close, n_factors=5, lookback=60, refit_every=5
                        ),
                        {"quantile": qq},
                    ),
                )
            )
    return entries


# ---------------------------------------------------------------------------
# Walk-forward
# ---------------------------------------------------------------------------


def sweep(
    ohlcv: pd.DataFrame,
    entries: list[tuple[str, str, Callable[[], object]]],
    *,
    formation: int,
    trading: int,
    min_trade: int,
    min_symbols: int,
    cost_model_name: str,
) -> pd.DataFrame:
    """Run every entry over the fixed skeleton; return the trial matrix."""
    from core_trading.backtest.engine import BacktestConfig, BacktestEngine

    n = ohlcv.shape[0]
    starts = window_starts(n, formation, trading, min_trade)
    engine = BacktestEngine(BacktestConfig(cost_model_name=cost_model_name))
    print(
        f"sweep: {len(starts)} windows of {formation}+{trading} bars over {n} sessions, "
        f"{len(entries)} configs, costs={cost_model_name!r}"
    )
    per_config: dict[str, list[pd.Series]] = {name: [] for _, name, _ in entries}
    failed: dict[str, str] = {}
    t0 = time.monotonic()
    done = 0
    total = len(starts) * len(entries)
    skipped = 0
    for wi, s in enumerate(starts):
        wide = ohlcv.iloc[s : s + formation + trading]
        symbols = valid_window_symbols(wide)
        if len(symbols) < min_symbols:
            skipped += 1
            done += len(entries)
            continue
        panel = engine_panel(wide, symbols)
        for _family, name, factory in entries:
            if name in failed:
                done += 1
                continue
            try:
                result = engine.run(panel, factory(), mode="vectorised")  # type: ignore[arg-type]
                per_config[name].append(result.returns.iloc[formation:])
            except Exception as exc:  # one bad config must not sink the sweep
                failed[name] = f"window {wi}: {type(exc).__name__}: {exc}"
            done += 1
        if (wi + 1) % 2 == 0 or wi == len(starts) - 1:
            elapsed = time.monotonic() - t0
            rate = done / elapsed if elapsed > 0 else 0.0
            eta = (total - done) / rate if rate > 0 else 0.0
            print(
                f"  window {wi + 1}/{len(starts)} "
                f"({wide.index[0].date()}..{wide.index[-1].date()}, {len(symbols)} symbols) "
                f"-- {done}/{total} runs, {elapsed:,.0f}s elapsed, eta {eta:,.0f}s",
                flush=True,
            )
    if skipped:
        print(f"  {skipped} window(s) skipped (fewer than {min_symbols} complete symbols)")
    for name, reason in failed.items():
        print(f"  FAILED config dropped: {name} ({reason})")
    frames = {
        name: pd.concat(chunks)
        for name, chunks in per_config.items()
        if chunks and name not in failed
    }
    if not frames:
        raise SystemExit("ERR: no config produced returns")
    trials = pd.DataFrame(frames).sort_index()
    if trials.isna().any().any():
        raise AssertionError("trial matrix has holes; window skeleton diverged")
    return trials


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def family_of(entries: list[tuple[str, str, Callable[[], object]]]) -> dict[str, str]:
    return {name: family for family, name, _ in entries}


def summary_table(trials: pd.DataFrame, families: dict[str, str], top_n: int = 30) -> str:
    rows = []
    for name in trials.columns:
        r = trials[name]
        rows.append(
            (
                name,
                families.get(name, "?"),
                annualised_sharpe(r),
                float((1.0 + r).prod() - 1.0),
                max_drawdown(r),
                float((r != 0.0).mean()),
            )
        )
    rows.sort(key=lambda t: t[2], reverse=True)
    lines = [
        f"| {'config':<36} | {'family':<11} | {'Sharpe':>7} | {'total ret':>9} "
        f"| {'max DD':>7} | {'active':>6} |",
        f"|{'-' * 38}|{'-' * 13}|{'-' * 9}|{'-' * 11}|{'-' * 9}|{'-' * 8}|",
    ]
    for name, fam, sh, tot, dd, act in rows[:top_n]:
        lines.append(
            f"| {name:<36} | {fam:<11} | {sh:>7.3f} | {tot:>8.1%} | {dd:>7.1%} | {act:>6.1%} |"
        )
    if len(rows) > top_n:
        lines.append(f"| ... {len(rows) - top_n} more configs elided ...")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--refetch", action="store_true")
    parser.add_argument("--fetch-only", action="store_true")
    parser.add_argument("--quick", action="store_true", help="smoke: 3 configs, last ~3y")
    parser.add_argument("--family", default=None, help="restrict to one family")
    parser.add_argument("--formation", type=int, default=252)
    parser.add_argument("--trading", type=int, default=126)
    parser.add_argument("--min-trade", type=int, default=40)
    parser.add_argument("--min-symbols", type=int, default=40)
    parser.add_argument("--cost-model", default="ibkr")
    parser.add_argument("--output", default=None)
    args = parser.parse_args(argv)

    if args.fetch_only:
        fetch_ohlcv_snapshot(args.start)
        return 0

    ohlcv = load_ohlcv(args.start, args.refetch)
    if args.quick:
        ohlcv = ohlcv.iloc[-756:]

    entries = build_families(args.quick)
    if args.family:
        entries = [e for e in entries if e[0] == args.family]
        if not entries:
            raise SystemExit(f"ERR: unknown family {args.family!r}")

    trials = sweep(
        ohlcv,
        entries,
        formation=args.formation,
        trading=args.trading,
        min_trade=args.min_trade,
        min_symbols=args.min_symbols,
        cost_model_name=args.cost_model,
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not args.quick:
        trials.to_parquet(OUT_DIR / "trials_net.parquet")
        print(f"trial matrix saved to {OUT_DIR / 'trials_net.parquet'}")

    families = family_of(entries)
    table = summary_table(trials, families)
    print()
    print(table)

    from core_trading.research.robustness_report import (
        render_robustness_report,
        run_robustness_report,
    )

    sharpes = {name: annualised_sharpe(trials[name]) for name in trials.columns}
    champions: dict[str, str] = {}
    for name in trials.columns:
        fam = families.get(name, "?")
        if fam not in champions or sharpes[name] > sharpes[champions[fam]]:
            champions[fam] = name

    close = ohlcv["close"]
    header: list[str] = [
        "# Strategy Validation Sweep -- long-history walk-forward",
        "",
        f"History    : {close.index[0].date()} .. {close.index[-1].date()} "
        f"({close.shape[0]} sessions, {close.shape[1]} symbols)",
        f"Skeleton   : formation {args.formation} (warm-up), trading {args.trading} "
        "(contiguous OOS)",
        f"Costs      : {args.cost_model!r} (linear turnover charge, vectorised mode)",
        f"Trials     : {trials.shape[1]} configs across "
        f"{len(set(families.values()))} families (full sweep = trial bank)",
        "",
        "CAVEAT: current-constituent SP100 universe (survivorship bias,",
        "flatters results). PROMOTE = upper bound pending Norgate; REJECT",
        "is close to decisive.",
        "",
        "## Top configs (net of costs)",
        "",
        table,
        "",
    ]

    verdicts: list[tuple[str, str, str, float]] = []
    sections: list[str] = []
    for fam in sorted(champions):
        name = champions[fam]
        candidate = trials[name]
        report = run_robustness_report(candidate, trial_returns=trials)
        verdicts.append((fam, name, report.verdict, sharpes[name]))
        sections.extend(
            [
                f"## Family champion: {fam} -- {name}",
                "",
                f"Net Sharpe {sharpes[name]:.3f} over {candidate.size} OOS days",
                "",
                "### Era stability (net of costs)",
                "",
                era_table(candidate),
                "",
                "### Robustness battery",
                "",
                render_robustness_report(report),
                "",
            ]
        )

    header.append("## Verdicts")
    header.append("")
    for fam, name, verdict, sh in sorted(verdicts, key=lambda v: v[3], reverse=True):
        header.append(f"- {verdict:<18} {fam:<12} {name} (net Sharpe {sh:.3f})")
    header.append("")

    full_text = "\n".join(header) + "\n" + "\n".join(sections)
    out_path = (
        Path(args.output)
        if args.output
        else OUT_DIR / f"sweep_report_{pd.Timestamp.utcnow():%Y%m%d_%H%M%S}.txt"
    )
    out_path.write_text(full_text, encoding="utf-8")
    print()
    for fam, name, verdict, sh in sorted(verdicts, key=lambda v: v[3], reverse=True):
        print(f"VERDICT {verdict:<18} {fam:<12} {name} (net Sharpe {sh:.3f})")
    print(f"report written to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
