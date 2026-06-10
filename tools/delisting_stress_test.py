"""Delisting stress test: bound residual survivorship bias without paid data.

The PIT sweep (``strategy_research_sweep.py --universe sp500pit``) fixes
membership bias (late joiners, fallen angels) but cannot price the
acquired/bankrupt cohort -- free vendors carry no data for most delisted
tickers. This tool bounds what those missing names could have done to the
candidate strategies by INJECTING SYNTHETIC MEMBERS into the PIT panel:

* Every unpriced membership spell becomes a synthetic price series that
  tracks the equal-weight market of priced members plus idiosyncratic
  noise (so it generates realistic entry signals through the actual
  strategy code, trend gates included).
* A scenario-controlled fraction of the spells that END (removals) are
  shaped into distress exits at their TRUE removal date:
  - ``gradual``: -80% linear decay over the final 252 bars (tests whether
    the SMA-200 trend gate disengages, as it should);
  - ``crash``: a two-day -55% gap ten days before removal, from above
    trend -- the Enron/fraud case the gate cannot see coming.
  The rest are treated as M&A exits (series simply continues market-like;
  ignoring the typical takeover premium is conservative -- real M&A exits
  would have ADDED return).
* After the distress event the series re-tracks the market (proceeds
  redeployed), so the window skeleton keeps complete data and the loss is
  actually sampled by every walk-forward window that holds it.

Scenarios sweep the distress share of unpriced removals: 25% (about the
historical share of forced/distress index removals), 50%, and 100%
(paranoid: every unpriced removal was a bankruptcy). For each scenario the
candidate configs are walked forward with the same skeleton, costs, PIT
membership filter and top-N dollar-volume slice as the PIT sweep, and the
Sharpe degradation vs the unstressed PIT baseline is reported.

Run:
    .venv/Scripts/python.exe tools/delisting_stress_test.py
    .venv/Scripts/python.exe tools/delisting_stress_test.py --configs rsi2t15_trend200
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from pairs_research_pass import annualised_sharpe, era_table, max_drawdown  # noqa: E402
from strategy_research_sweep import (  # noqa: E402
    DEFAULT_START,
    OUT_DIR,
    snapshot_path,
    sweep,
)

DEFAULT_CONFIGS = ("rsi2t15_trend200", "rsi2t10_trend200", "rsi2t10_trend200_volt10")
DISTRESS_FRACTIONS = (0.25, 0.50, 1.00)
GRADUAL_DECAY_BARS = 252
GRADUAL_DECAY_TO = 0.20  # -80%
CRASH_DROP = 0.55  # -55% across two bars
CRASH_LEAD_BARS = 10
IDIO_VOL_DAILY = 0.02
SEED = 20260610


def candidate_entries(names: tuple[str, ...]) -> list[tuple[str, str, object]]:
    """(family, name, factory) for the requested ta_quant config names."""
    from core_trading.strategies.ta_quant import TAQuantStrategy, build_ta_quant_grid

    grid = dict(build_ta_quant_grid())
    missing = [n for n in names if n not in grid]
    if missing:
        raise SystemExit(f"ERR: unknown ta_quant config(s): {missing}")
    return [
        ("ta_quant", name, (lambda c=grid[name]: TAQuantStrategy(c)))
        for name in names
    ]


def unpriced_spells(
    panel: pd.DataFrame, universe: object, start: pd.Timestamp
) -> list[tuple[str, pd.Timestamp, pd.Timestamp | None]]:
    """Membership spells overlapping the panel with no price data at all."""
    priced = {str(c) for c in panel["close"].columns}
    spells: list[tuple[str, pd.Timestamp, pd.Timestamp | None]] = []
    for m in universe.memberships:  # type: ignore[attr-defined]
        removed = pd.Timestamp(m.removed) if m.removed is not None else None
        if removed is not None and removed < start:
            continue
        if m.symbol in priced:
            continue
        spells.append((m.symbol, pd.Timestamp(m.added), removed))
    return spells


def build_synthetic_panel(
    panel: pd.DataFrame,
    spells: list[tuple[str, pd.Timestamp, pd.Timestamp | None]],
    distress_frac: float,
) -> pd.DataFrame:
    """Return ``panel`` augmented with one synthetic column per spell.

    Synthetic close = equal-weight market return of priced members plus
    seeded idiosyncratic noise; distress shaping per the module docstring.
    Volume is set so each synthetic name's dollar volume sits at the
    median of priced members (it competes realistically for the top-N
    dollar-volume slice). Open/high/low equal close: the rsi_dip family
    under test is close-only, so flat bars do not distort its signals.
    """
    idx = panel.index
    close = panel["close"]
    r_mkt = close.pct_change().mean(axis=1).fillna(0.0).to_numpy()
    median_dv = float((close * panel["volume"]).median(axis=1).median())

    rng = np.random.default_rng(SEED)
    order = rng.permutation(len(spells))
    ends_at = np.array([s[2] is not None for s in spells])
    removal_order = [i for i in order if ends_at[i]]
    n_distress = int(round(distress_frac * len(removal_order)))
    distress_ids = set(removal_order[:n_distress])

    new_parts: dict[tuple[str, str], pd.Series] = {}
    for k, (symbol, _added, removed) in enumerate(spells):
        eps = rng.normal(0.0, IDIO_VOL_DAILY, size=len(idx))
        r = r_mkt + eps
        if k in distress_ids and removed is not None:
            # locate the removal bar on the panel calendar
            pos = int(idx.searchsorted(removed))
            pos = min(pos, len(idx) - 1)
            if k % 2 == 0:
                # gradual death: -80% spread linearly over the final year
                span = min(GRADUAL_DECAY_BARS, pos)
                if span > 0:
                    per_bar = GRADUAL_DECAY_TO ** (1.0 / span) - 1.0
                    r[pos - span : pos] = per_bar
            else:
                # sudden crash from above trend ten bars before removal
                cpos = max(pos - CRASH_LEAD_BARS, 1)
                half = 1.0 - (1.0 - CRASH_DROP) ** 0.5
                r[cpos] = -half
                r[min(cpos + 1, len(idx) - 1)] = -half
        prices = 100.0 * np.cumprod(1.0 + r)
        sclose = pd.Series(prices, index=idx)
        svolume = pd.Series(median_dv, index=idx) / sclose
        col = f"{symbol}~SYN"
        for fieldname in ("open", "high", "low", "close"):
            new_parts[(fieldname, col)] = sclose
        new_parts[("volume", col)] = svolume

    synth = pd.DataFrame(new_parts)
    synth.columns = pd.MultiIndex.from_tuples(synth.columns, names=["field", "symbol"])
    return pd.concat([panel, synth], axis=1).sort_index(axis=1)


class _SynthAwareUniverse:
    """Wraps the vintage universe so synthetic columns pass the member check.

    ``SYM~SYN`` is a member exactly when ``SYM`` is -- real (priced)
    symbols are unaffected.
    """

    def __init__(self, base: object) -> None:
        self._base = base
        self.memberships = base.memberships  # type: ignore[attr-defined]

    def members_on(self, as_of: object) -> tuple[str, ...]:
        members = self._base.members_on(as_of)  # type: ignore[attr-defined]
        return tuple(members) + tuple(f"{s}~SYN" for s in members)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument(
        "--configs", nargs="+", default=list(DEFAULT_CONFIGS), help="ta_quant config names"
    )
    parser.add_argument("--formation", type=int, default=252)
    parser.add_argument("--trading", type=int, default=126)
    parser.add_argument("--min-trade", type=int, default=40)
    parser.add_argument("--min-symbols", type=int, default=40)
    parser.add_argument("--top-n", type=int, default=100)
    parser.add_argument("--cost-model", default="ibkr")
    parser.add_argument("--output", default=None)
    args = parser.parse_args(argv)

    from core_trading.data.universe_history import load_sp500_pit

    pit_path = snapshot_path("sp500pit")
    if not pit_path.exists():
        raise SystemExit(
            "ERR: PIT snapshot missing -- run "
            "tools/strategy_research_sweep.py --fetch-only --universe sp500pit first"
        )
    panel = pd.read_parquet(pit_path)
    universe = load_sp500_pit()
    start_ts = pd.Timestamp(args.start)

    spells = unpriced_spells(panel, universe, start_ts)
    n_removed = sum(1 for s in spells if s[2] is not None)
    print(
        f"unpriced membership spells overlapping {args.start}+: {len(spells)} "
        f"({n_removed} with removal dates, {len(spells) - n_removed} open/unmapped)"
    )

    entries = candidate_entries(tuple(args.configs))
    common = dict(
        formation=args.formation,
        trading=args.trading,
        min_trade=args.min_trade,
        min_symbols=args.min_symbols,
        cost_model_name=args.cost_model,
        top_n=args.top_n,
    )

    print("\n=== baseline: PIT panel, no synthetics ===")
    baseline = sweep(panel, entries, pit_universe=universe, **common)

    results: dict[float, pd.DataFrame] = {}
    synth_universe = _SynthAwareUniverse(universe)
    for frac in DISTRESS_FRACTIONS:
        print(f"\n=== scenario: distress_frac={frac:.0%} of unpriced removals ===")
        augmented = build_synthetic_panel(panel, spells, frac)
        results[frac] = sweep(augmented, entries, pit_universe=synth_universe, **common)

    lines: list[str] = [
        "# Delisting stress test -- synthetic-member injection on the PIT panel",
        "",
        f"Unpriced spells: {len(spells)} ({n_removed} with removal dates)",
        f"Candidates     : {', '.join(args.configs)}",
        "Distress model : gradual -80%/252d (even ids) | crash -55%/2d (odd ids),",
        "                 at true removal dates; M&A share continues market-like",
        "                 (no takeover premium credited -- conservative).",
        "",
        "| config | scenario | Sharpe | delta | total ret | max DD |",
        "|--------|----------|--------|-------|-----------|--------|",
    ]
    for name in args.configs:
        base_r = baseline[name]
        base_sh = annualised_sharpe(base_r)
        lines.append(
            f"| {name} | baseline (PIT) | {base_sh:.3f} | -- "
            f"| {float((1 + base_r).prod() - 1):.1%} | {max_drawdown(base_r):.1%} |"
        )
        for frac, trials in results.items():
            r = trials[name]
            sh = annualised_sharpe(r)
            lines.append(
                f"| {name} | distress {frac:.0%} | {sh:.3f} | {sh - base_sh:+.3f} "
                f"| {float((1 + r).prod() - 1):.1%} | {max_drawdown(r):.1%} |"
            )
    worst = max(DISTRESS_FRACTIONS)
    lines += ["", f"## Era stability under the worst scenario (distress {worst:.0%})", ""]
    for name in args.configs:
        lines += [f"### {name}", "", era_table(results[worst][name]), ""]

    text = "\n".join(lines)
    out_path = (
        Path(args.output)
        if args.output
        else OUT_DIR / f"delisting_stress_{pd.Timestamp.utcnow():%Y%m%d_%H%M%S}.txt"
    )
    out_path.write_text(text, encoding="utf-8")
    print()
    print(text)
    print(f"\nreport written to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
