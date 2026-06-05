"""Pairs research pass on long history -- the 90-day-clock unblock.

The 2026-06-05 walk-forward on IBKR 2Y dailies showed the pilot pairs config
has no demonstrated edge (Sharpe -0.03 +/- 0.07), so the paper-trading clock
was HELD pending this research pass: validate (or honestly fail to validate)
a pairs configuration with positive edge on LONGER history, with the Phase 10
statistical robustness battery as the promotion gate.

Methodology
-----------
* **Data:** ~20 years of daily *adjusted* closes for the current SP100
  universe via yfinance (decades of daily history; IBKR caps this path at
  ~2Y). Snapshot cached at ``logs/pairs_research/prices_yf.parquet``.

  KNOWN BIAS -- this is the *current* SP100 constituent list applied
  retroactively (survivorship bias): names that fell out of the index over
  the period are absent, which flatters mean-reversion books built on
  survivors. A survivorship-free pass needs point-in-time constituents
  (the pending paid-Norgate decision). A PROMOTE here is therefore an
  upper bound, not a guarantee; a REJECT here is close to decisive, since
  the bias works in the strategy's favour.

* **Walk-forward:** Gatev-style rolling windows -- ``formation`` bars to
  select pairs and fit hedges/OU, then ``trading`` bars of out-of-sample
  trading; the window then rolls forward by ``trading`` bars, so the
  concatenated OOS daily returns are contiguous and non-overlapping. The
  window skeleton is FIXED across the whole grid so every config's return
  series shares an identical calendar (the trial matrix aligns by
  construction).

* **Universe per window:** symbols with complete, strictly positive data
  over the window slice (later-listed names drop out of early windows).
  Windows with fewer than ``min_symbols`` valid names are skipped.

* **Costs:** the engine's vectorised mode with the ``"ibkr"`` cost model --
  a linear per-unit-turnover charge (half-spread + percent commission).
  Ranking configs frictionless would flatter high-turnover variants; the
  gate certifies net-of-cost returns. The chosen candidate is also re-run
  frictionless for comparison with the 2026-06-05 pass.

* **Grid (the trial bank):** 24 configs around the pilot -- zscore window
  {30, 60} x entry/exit z {(1.5, 0.5), (2.0, 0.5), (2.5, 1.0)} x max pairs
  {10, 20} x same-sector {on, off}. Every config tried is one column of the
  trial matrix handed to the DSR / PBO / Reality-Check gates -- the search
  itself is what those tests deflate against.

* **Gate:** the best config's concatenated OOS returns through
  :func:`core_trading.research.robustness_report.run_robustness_report`
  with the full trial matrix. PROMOTE requires the bootstrap Sharpe CI to
  exclude zero, DSR >= 0.95, PBO <= 0.5, Reality-Check p <= 0.10 and CPCV
  OOS stability -- all of it net of costs.

Run:
    .venv/Scripts/python.exe tools/pairs_research_pass.py              # full pass
    .venv/Scripts/python.exe tools/pairs_research_pass.py --quick      # smoke (tiny grid, short history)
    .venv/Scripts/python.exe tools/pairs_research_pass.py --fetch-only # refresh the price snapshot and exit
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

if TYPE_CHECKING:
    from core_trading.strategies.pairs_trading import PairsTradingConfig

OUT_DIR = REPO_ROOT / "logs" / "pairs_research"
SNAPSHOT = OUT_DIR / "prices_yf.parquet"
DEFAULT_START = "2005-01-01"


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


def fetch_snapshot(start: str) -> pd.DataFrame:
    """Fetch daily adjusted closes for the SP100 universe and cache them.

    Returns a wide frame (timestamp x symbol) of split/dividend-adjusted
    closes. Symbols yfinance cannot resolve (e.g. WBA, private since 2025)
    simply come back empty and are dropped.
    """
    import datetime as _dt

    from core_trading.data.bars import BarResolution
    from core_trading.data.sources.yfinance_source import fetch_bars_sync
    from core_trading.data.universe import SP100

    symbols = list(SP100.current_symbols())
    print(f"fetching {len(symbols)} symbols from {start} via yfinance ...")
    raw = fetch_bars_sync(
        symbols,
        _dt.date.fromisoformat(start),
        _dt.date.today(),
        resolution=BarResolution.DAY_1,
    )
    if raw.empty:
        raise SystemExit("ERR: yfinance returned no data")
    wide = raw["adjusted_close"].unstack("symbol").sort_index()
    # Naive dates: the engine calendar does not need tz, and parquet
    # round-trips are simpler without it.
    wide.index = wide.index.tz_localize(None).normalize()
    empty = [c for c in wide.columns if wide[c].dropna().empty]
    if empty:
        print(f"WARN: no data for {', '.join(sorted(empty))}; dropped")
        wide = wide.drop(columns=empty)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    wide.to_parquet(SNAPSHOT)
    print(
        f"snapshot: {wide.shape[0]} sessions x {wide.shape[1]} symbols "
        f"({wide.index[0].date()} .. {wide.index[-1].date()}) -> {SNAPSHOT}"
    )
    return wide


def load_prices(start: str, refetch: bool) -> pd.DataFrame:
    if SNAPSHOT.exists() and not refetch:
        wide = pd.read_parquet(SNAPSHOT)
        print(
            f"loaded snapshot: {wide.shape[0]} sessions x {wide.shape[1]} symbols "
            f"({wide.index[0].date()} .. {wide.index[-1].date()})"
        )
        return wide
    return fetch_snapshot(start)


def load_sectors(symbols: list[str]) -> dict[str, str]:
    from core_trading.data.reference import build_starter_reference

    ref = build_starter_reference()
    return {s: sec for s in symbols if (sec := ref.sector_of(s))}


# ---------------------------------------------------------------------------
# Grid
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GridSpec:
    """One trial: a named strategy configuration."""

    name: str
    zscore_window: int
    entry_z: float
    exit_z: float
    max_pairs: int
    same_sector: bool

    def build(self) -> PairsTradingConfig:
        from core_trading.portfolio.pairs_portfolio import PortfolioConfig
        from core_trading.signals.pairs.signals import SignalConfig
        from core_trading.strategies.pairs_trading import PairsTradingConfig

        return PairsTradingConfig(
            selection_method="distance",
            zscore_window=self.zscore_window,
            max_pairs=self.max_pairs,
            max_pairs_per_sector=3 if self.same_sector else None,
            max_abs_hedge_beta=3.0,
            unique_symbols=True,
            signal=SignalConfig(entry_z=self.entry_z, exit_z=self.exit_z),
            portfolio=PortfolioConfig(sector_cap=0.95),
        )


def build_grid(quick: bool) -> list[GridSpec]:
    """The trial bank. The pilot config is z60/e2.0/x0.5/p10/sector."""
    if quick:
        axes = [(60, 2.0, 0.5, 10, True), (30, 1.5, 0.5, 10, True)]
    else:
        axes = [
            (zw, ez, xz, mp, ss)
            for zw in (30, 60)
            for ez, xz in ((1.5, 0.5), (2.0, 0.5), (2.5, 1.0))
            for mp in (10, 20)
            for ss in (True, False)
        ]
    return [
        GridSpec(
            name=f"z{zw}_e{ez}_x{xz}_p{mp}_{'sector' if ss else 'open'}",
            zscore_window=zw,
            entry_z=ez,
            exit_z=xz,
            max_pairs=mp,
            same_sector=ss,
        )
        for zw, ez, xz, mp, ss in axes
    ]


PILOT_NAME = "z60_e2.0_x0.5_p10_sector"


# ---------------------------------------------------------------------------
# Walk-forward
# ---------------------------------------------------------------------------


def window_starts(n: int, formation: int, trading: int, min_trade: int) -> list[int]:
    """Start indices of contiguous, non-overlapping walk-forward windows."""
    starts: list[int] = []
    s = 0
    while s + formation + min_trade <= n:
        starts.append(s)
        s += trading
    return starts


def valid_columns(sl: pd.DataFrame) -> list[str]:
    """Symbols with complete, strictly positive data over the slice."""
    ok = sl.notna().all(axis=0) & (sl > 0).all(axis=0)
    return [str(c) for c in sl.columns[ok]]


def run_window(
    sl: pd.DataFrame,
    spec: GridSpec,
    sectors: dict[str, str],
    formation: int,
    cost_model_name: str,
) -> pd.Series:
    """One walk-forward window for one config -> OOS daily returns (net)."""
    from core_trading.backtest.engine import BacktestConfig, BacktestEngine
    from core_trading.research.signal_evaluation import price_panel_from_frame
    from core_trading.strategies.pairs_trading import PairsTradingStrategy

    panel = price_panel_from_frame(sl)
    strategy = PairsTradingStrategy(
        spec.build(), sectors=sectors, require_same_sector=spec.same_sector
    )
    engine = BacktestEngine(BacktestConfig(cost_model_name=cost_model_name))
    result = engine.run(panel, strategy, mode="vectorised")
    # Bars [0, formation) carry zero weight by construction; the OOS segment
    # is the trading window. The first OOS bar's return is earned by the
    # weight set on the last formation bar (always zero), so it is kept as
    # an honest flat day rather than sliced off.
    return result.returns.iloc[formation:]


def walk_forward(
    close: pd.DataFrame,
    specs: list[GridSpec],
    sectors: dict[str, str],
    *,
    formation: int,
    trading: int,
    min_trade: int,
    min_symbols: int,
    cost_model_name: str,
) -> pd.DataFrame:
    """Run every config over the fixed window skeleton.

    Returns a (timestamp x config-name) frame of concatenated OOS daily
    returns -- the trial matrix.
    """
    n = close.shape[0]
    starts = window_starts(n, formation, trading, min_trade)
    print(
        f"walk-forward: {len(starts)} windows of {formation}+{trading} bars "
        f"over {n} sessions, {len(specs)} configs, costs={cost_model_name!r}"
    )
    per_config: dict[str, list[pd.Series]] = {s.name: [] for s in specs}
    t0 = time.monotonic()
    done = 0
    total = len(starts) * len(specs)
    skipped = 0
    for wi, s in enumerate(starts):
        sl = close.iloc[s : s + formation + trading]
        cols = valid_columns(sl)
        if len(cols) < min_symbols:
            skipped += 1
            done += len(specs)
            continue
        slc = sl[cols]
        for spec in specs:
            oos = run_window(slc, spec, sectors, formation, cost_model_name)
            per_config[spec.name].append(oos)
            done += 1
        if (wi + 1) % 5 == 0 or wi == len(starts) - 1:
            elapsed = time.monotonic() - t0
            rate = done / elapsed if elapsed > 0 else 0.0
            eta = (total - done) / rate if rate > 0 else 0.0
            print(
                f"  window {wi + 1}/{len(starts)} "
                f"({sl.index[0].date()}..{sl.index[-1].date()}, {len(cols)} symbols) "
                f"-- {done}/{total} runs, {elapsed:,.0f}s elapsed, eta {eta:,.0f}s"
            )
    if skipped:
        print(f"  {skipped} window(s) skipped (fewer than {min_symbols} complete symbols)")
    frames = {
        name: pd.concat(chunks) for name, chunks in per_config.items() if chunks
    }
    if not frames:
        raise SystemExit("ERR: no window produced returns; check data/min_symbols")
    trials = pd.DataFrame(frames).sort_index()
    # Identical skeleton => identical calendars; assert rather than assume.
    if trials.isna().any().any():
        raise AssertionError("trial matrix has holes; window skeleton diverged")
    return trials


# ---------------------------------------------------------------------------
# Scoring + report
# ---------------------------------------------------------------------------


def annualised_sharpe(returns: pd.Series) -> float:
    sd = float(returns.std(ddof=1))
    if sd == 0.0 or not np.isfinite(sd):
        return 0.0
    return float(returns.mean() / sd * np.sqrt(252.0))


def max_drawdown(returns: pd.Series) -> float:
    equity = (1.0 + returns).cumprod()
    return float((equity / equity.cummax() - 1.0).min())


def active_fraction(returns: pd.Series) -> float:
    return float((returns != 0.0).mean())


def era_table(returns: pd.Series, n_eras: int = 4) -> str:
    """Per-era Sharpe of a return series -- the era-stability check.

    A full-period Sharpe can be carried entirely by one old regime (for
    distance pairs, famously 2008); a candidate whose recent-era Sharpe is
    negative has no *current* edge regardless of the full-period number.
    """
    years = returns.index.year
    span = int(years.max()) - int(years.min()) + 1
    step = max(1, int(np.ceil(span / n_eras)))
    lines = [
        f"| {'era':<12} | {'Sharpe':>7} | {'max DD':>7} | {'days':>5} |",
        f"|{'-' * 14}|{'-' * 9}|{'-' * 9}|{'-' * 7}|",
    ]
    for start in range(int(years.min()), int(years.max()) + 1, step):
        seg = returns[(years >= start) & (years < start + step)]
        if seg.empty:
            continue
        label = f"{start}-{min(start + step - 1, int(years.max()))}"
        lines.append(
            f"| {label:<12} | {annualised_sharpe(seg):>7.3f} "
            f"| {max_drawdown(seg):>7.1%} | {seg.size:>5} |"
        )
    return "\n".join(lines)


def summary_table(trials: pd.DataFrame) -> str:
    rows = []
    for name in trials.columns:
        r = trials[name]
        rows.append(
            (
                name,
                annualised_sharpe(r),
                float((1.0 + r).prod() - 1.0),
                max_drawdown(r),
                active_fraction(r),
            )
        )
    rows.sort(key=lambda t: t[1], reverse=True)
    lines = [
        f"| {'config':<28} | {'Sharpe':>7} | {'total ret':>9} | {'max DD':>7} | {'active':>6} |",
        f"|{'-' * 30}|{'-' * 9}|{'-' * 11}|{'-' * 9}|{'-' * 8}|",
    ]
    for name, sh, tot, dd, act in rows:
        marker = " <- pilot" if name == PILOT_NAME else ""
        lines.append(
            f"| {name:<28} | {sh:>7.3f} | {tot:>8.1%} | {dd:>7.1%} | {act:>6.1%} |{marker}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--start", default=DEFAULT_START, help="history start (YYYY-MM-DD)")
    parser.add_argument("--refetch", action="store_true", help="force a fresh yfinance snapshot")
    parser.add_argument("--fetch-only", action="store_true", help="refresh the snapshot and exit")
    parser.add_argument("--quick", action="store_true", help="smoke run: 2 configs, last ~3y only")
    parser.add_argument("--formation", type=int, default=252)
    parser.add_argument("--trading", type=int, default=126)
    parser.add_argument("--min-trade", type=int, default=40, help="minimum final-window trading bars")
    parser.add_argument("--min-symbols", type=int, default=40, help="minimum complete symbols per window")
    parser.add_argument("--cost-model", default="ibkr", help="engine cost model for the grid")
    parser.add_argument("--output", default=None, help="report path (default under logs/pairs_research/)")
    args = parser.parse_args(argv)

    if args.fetch_only:
        fetch_snapshot(args.start)
        return 0

    close = load_prices(args.start, args.refetch)
    if args.quick:
        close = close.iloc[-756:]
    sectors = load_sectors([str(c) for c in close.columns])
    specs = build_grid(args.quick)

    trials = walk_forward(
        close,
        specs,
        sectors,
        formation=args.formation,
        trading=args.trading,
        min_trade=args.min_trade,
        min_symbols=args.min_symbols,
        cost_model_name=args.cost_model,
    )

    # Persist the trial matrix: any future grid round must count THESE
    # trials too (cumulative trial accounting for DSR/PBO honesty).
    if not args.quick:
        trials_path = OUT_DIR / "trials_net.parquet"
        trials.to_parquet(trials_path)
        print(f"trial matrix saved to {trials_path}")

    table = summary_table(trials)
    print()
    print(table)

    sharpes = {name: annualised_sharpe(trials[name]) for name in trials.columns}
    best = max(sharpes, key=lambda k: sharpes[k])
    candidate = trials[best]
    print()
    print(f"candidate: {best} (net Sharpe {sharpes[best]:.3f} over {candidate.size} OOS days)")
    print()
    print(era_table(candidate))

    # Frictionless re-run of the candidate for comparison with the
    # 2026-06-05 IBKR-2Y pass (which used frictionless marks).
    spec = next(s for s in specs if s.name == best)
    frictionless = walk_forward(
        close,
        [spec],
        sectors,
        formation=args.formation,
        trading=args.trading,
        min_trade=args.min_trade,
        min_symbols=args.min_symbols,
        cost_model_name="zero",
    )[best]
    print(f"candidate frictionless Sharpe: {annualised_sharpe(frictionless):.3f}")

    from core_trading.research.robustness_report import (
        render_robustness_report,
        run_robustness_report,
    )

    report = run_robustness_report(candidate, trial_returns=trials)
    text = render_robustness_report(report)

    header = [
        "# Pairs Research Pass -- long-history walk-forward",
        "",
        f"History    : {close.index[0].date()} .. {close.index[-1].date()} "
        f"({close.shape[0]} sessions, {close.shape[1]} symbols)",
        f"Skeleton   : formation {args.formation}, trading {args.trading} (contiguous OOS)",
        f"Costs      : {args.cost_model!r} (linear turnover charge, vectorised mode)",
        f"Trials     : {len(specs)} configs (full grid is the DSR/PBO/RC trial bank)",
        f"Candidate  : {best}",
        f"  net Sharpe          : {sharpes[best]:.3f}",
        f"  frictionless Sharpe : {annualised_sharpe(frictionless):.3f}",
        f"  pilot config Sharpe : {sharpes.get(PILOT_NAME, float('nan')):.3f} ({PILOT_NAME})",
        "",
        "CAVEAT: current-constituent SP100 universe over historical windows",
        "(survivorship bias, flatters the result). PROMOTE here is an upper",
        "bound pending point-in-time constituents (Norgate); REJECT is",
        "close to decisive because the bias works in the strategy's favour.",
        "",
        "## Config grid (net of costs)",
        "",
        table,
        "",
        "## Candidate era stability (net of costs)",
        "",
        era_table(candidate),
        "",
    ]
    full_text = "\n".join(header) + "\n" + text

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = (
        Path(args.output)
        if args.output
        else OUT_DIR / f"research_report_{pd.Timestamp.utcnow():%Y%m%d_%H%M%S}.txt"
    )
    out_path.write_text(full_text, encoding="utf-8")
    print()
    print(text)
    print(f"report written to {out_path}")
    print()
    print(f"VERDICT: {report.verdict}")
    if report.verdict == "PROMOTE":
        print(
            "next: re-pin --backtest-sharpe in tools/pairs_paper_run.py to "
            f"{sharpes[best]:.2f} and switch the pilot config to {best}"
        )
    else:
        print("next: the 90-day clock stays HELD; record the verdict and iterate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
