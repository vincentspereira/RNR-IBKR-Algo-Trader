"""Strategy lab -- author, visualise, and gate your own strategies.

The workshop in front of the validation machinery: pick a config from the
TA x quant grid (or write your own), LOOK at what it does on real data
(interactive chart of prices, entry/exit markers, equity, drawdown), then
run it through the exact walk-forward + robustness battery that gated the
production candidates. The promotion path is deliberately the same bar the
rsi2 family had to clear -- see ``docs/GO_NO_GO_RSI2_TREND_SURVIVORSHIP_2026-06-10.md``.

Subcommands
-----------
list
    Show every available primary, overlay, and named grid config.
chart --config NAME [--universe etf|sp100|sp500pit] [--symbols A,B] [--last N]
    Interactive HTML chart: per-symbol candles-free close lines with
    long/short entry and exit markers, plus the net-of-costs portfolio
    equity and drawdown over the charted window.
backtest --config NAME [--universe ...]
    Full 2005+ walk-forward (the sweep skeleton), era table, and the
    robustness gate battery. Deflates against the saved trial bank of the
    chosen universe when present -- your strategy is judged as the N+1-th
    trial, exactly as honesty requires.

Custom strategies: pass ``--custom path/to/file.py`` instead of
``--config``. The file must define ``build()`` returning ``(name, factory)``
where ``factory()`` yields an object with
``generate_weights(prices_panel) -> weight frame`` (the engine Strategy
protocol). See ``examples/custom_strategy_example.py``.

Promotion path (manual, deliberate): a config that PASSES the battery on
the PIT universe gets a slot in ``tools/taquant_paper_run.py`` (daily) or
``tools/intraday_paper_run.py`` (experimental lane) and earns live capital
only through the 90-day paper gate.
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from pairs_research_pass import annualised_sharpe, era_table, max_drawdown  # noqa: E402
from strategy_research_sweep import (  # noqa: E402
    OUT_DIR as SWEEP_DIR,
)
from strategy_research_sweep import (  # noqa: E402
    UNIVERSES,
    engine_panel,
    load_ohlcv,
    sweep,
    valid_window_symbols,
)

LAB_DIR = REPO_ROOT / "logs" / "strategy_lab"
DEFAULT_START = "2005-01-01"


# ---------------------------------------------------------------------------
# Strategy resolution
# ---------------------------------------------------------------------------


def resolve_strategy(args: argparse.Namespace) -> tuple[str, Callable[[], object]]:
    """(name, factory) from --config (grid) or --custom (user file)."""
    if bool(args.config) == bool(args.custom):
        raise SystemExit("ERR: pass exactly one of --config NAME or --custom FILE.py")
    if args.config:
        from core_trading.strategies.ta_quant import TAQuantStrategy, build_ta_quant_grid

        grid = dict(build_ta_quant_grid())
        if args.config not in grid:
            close = [n for n in grid if args.config.split("_")[0] in n][:8]
            raise SystemExit(
                f"ERR: unknown grid config {args.config!r}."
                + (f" Close matches: {', '.join(close)}" if close else "")
                + " Use 'list' to see all."
            )
        cfg = grid[args.config]
        return args.config, lambda: TAQuantStrategy(cfg)

    path = Path(args.custom)
    if not path.exists():
        raise SystemExit(f"ERR: custom strategy file not found: {path}")
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "build"):
        raise SystemExit(f"ERR: {path} must define build() -> (name, factory)")
    name, factory = module.build()
    return str(name), factory


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def cmd_list(_args: argparse.Namespace) -> int:
    from core_trading.strategies.ta_quant import build_ta_quant_grid
    from core_trading.strategies.ta_quant.strategy import _OVERLAY_TYPES, _PRIMARY_NAMES

    print("primaries :", ", ".join(sorted(_PRIMARY_NAMES)))
    print("overlays  :", ", ".join(sorted(_OVERLAY_TYPES)))
    grid = build_ta_quant_grid()
    print(f"grid      : {len(grid)} named configs")
    by_prefix: dict[str, list[str]] = {}
    for name, _cfg in grid:
        by_prefix.setdefault(name.split("_")[0], []).append(name)
    for prefix in sorted(by_prefix):
        print(f"  {prefix:<10} {', '.join(by_prefix[prefix])}")
    print()
    print("chart    : strategy_lab.py chart --config rsi2t15_trend200 --universe etf")
    print("backtest : strategy_lab.py backtest --config rsi2t15_trend200 --universe sp500pit")
    print("custom   : strategy_lab.py chart --custom examples/custom_strategy_example.py")
    return 0


# ---------------------------------------------------------------------------
# chart
# ---------------------------------------------------------------------------


def _signal_markers(weights: pd.Series) -> tuple[list, list, list, list]:
    """(long_entries, long_exits, short_entries, short_exits) timestamp lists."""
    w = weights.fillna(0.0)
    prev = w.shift(1).fillna(0.0)
    return (
        list(w.index[(prev <= 0) & (w > 0)]),
        list(w.index[(prev > 0) & (w <= 0)]),
        list(w.index[(prev >= 0) & (w < 0)]),
        list(w.index[(prev < 0) & (w >= 0)]),
    )


def cmd_chart(args: argparse.Namespace) -> int:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    from core_trading.backtest.engine import BacktestConfig, BacktestEngine

    name, factory = resolve_strategy(args)
    ohlcv = load_ohlcv(DEFAULT_START, refetch=False, universe=args.universe)
    window = ohlcv.iloc[-args.last :]
    symbols = valid_window_symbols(window)
    if not symbols:
        raise SystemExit("ERR: no complete symbols in the charted window")
    panel = engine_panel(window, symbols)

    engine = BacktestEngine(BacktestConfig(cost_model_name=args.cost_model))
    strategy = factory()
    result = engine.run(panel, strategy, mode="vectorised")  # type: ignore[arg-type]
    weights = strategy.generate_weights(panel)
    equity = (1.0 + result.returns).cumprod()
    drawdown = equity / equity.cummax() - 1.0

    # Chart the most active symbols (the interesting ones), or the requested.
    if args.symbols:
        chart_syms = [s for s in args.symbols.split(",") if s in weights.columns]
        if not chart_syms:
            raise SystemExit(f"ERR: none of {args.symbols} present; have {symbols[:10]}...")
    else:
        activity = (weights != 0).sum().sort_values(ascending=False)
        chart_syms = [str(s) for s in activity.index[: args.max_symbols]]

    rows = len(chart_syms) + 1
    fig = make_subplots(
        rows=rows,
        cols=1,
        shared_xaxes=True,
        row_heights=[2.0] + [1.0] * len(chart_syms),
        vertical_spacing=0.02,
        subplot_titles=[f"{name} -- net equity (top) / drawdown shading"] + chart_syms,
    )
    fig.add_trace(
        go.Scatter(x=equity.index, y=equity, name="equity", line={"width": 1.6}),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=drawdown.index,
            y=drawdown,
            name="drawdown",
            yaxis="y2",
            line={"width": 1.0, "color": "#f08f96"},
        ),
        row=1,
        col=1,
    )
    marker_styles = [
        ("long entry", "triangle-up", "#7fd6a2"),
        ("long exit", "x", "#bac7d5"),
        ("short entry", "triangle-down", "#f08f96"),
        ("short exit", "x", "#8b97a5"),
    ]
    for i, sym in enumerate(chart_syms, start=2):
        close = window[("close", sym)]
        fig.add_trace(
            go.Scatter(x=close.index, y=close, name=sym, line={"width": 1.0}),
            row=i,
            col=1,
        )
        for stamps, (label, symbol_shape, colour) in zip(
            _signal_markers(weights[sym]), marker_styles, strict=True
        ):
            if not stamps:
                continue
            fig.add_trace(
                go.Scatter(
                    x=stamps,
                    y=[float(close.loc[t]) for t in stamps],
                    mode="markers",
                    name=f"{sym} {label}",
                    showlegend=False,
                    marker={"symbol": symbol_shape, "size": 9, "color": colour},
                ),
                row=i,
                col=1,
            )
    sh = annualised_sharpe(result.returns)
    fig.update_layout(
        template="plotly_dark",
        height=280 * rows,
        title=(
            f"{name} on {args.universe} (last {args.last} sessions, net of "
            f"{args.cost_model!r} costs) -- Sharpe {sh:.2f}, "
            f"maxDD {max_drawdown(result.returns):.1%}"
        ),
        legend={"orientation": "h"},
    )

    LAB_DIR.mkdir(parents=True, exist_ok=True)
    out = LAB_DIR / f"chart_{name}_{args.universe}.html"
    fig.write_html(out, include_plotlyjs="cdn")
    print(f"Sharpe {sh:.3f} | maxDD {max_drawdown(result.returns):.1%} over charted window")
    print(f"chart written to {out}")
    return 0


# ---------------------------------------------------------------------------
# backtest
# ---------------------------------------------------------------------------


def cmd_backtest(args: argparse.Namespace) -> int:
    from core_trading.research.robustness_report import (
        render_robustness_report,
        run_robustness_report,
    )

    name, factory = resolve_strategy(args)
    ohlcv = load_ohlcv(DEFAULT_START, refetch=False, universe=args.universe)

    pit_universe = None
    top_n = 0
    if args.universe == "sp500pit":
        from core_trading.data.universe_history import load_sp500_pit

        pit_universe = load_sp500_pit()
        top_n = 100

    t0 = time.monotonic()
    trials = sweep(
        ohlcv,
        [("lab", name, factory)],
        formation=252,
        trading=126,
        min_trade=40,
        min_symbols=20 if args.universe == "etf" else 40,
        cost_model_name=args.cost_model,
        pit_universe=pit_universe,
        top_n=top_n,
    )
    candidate = trials[name]
    print(f"walk-forward done in {time.monotonic() - t0:,.0f}s")

    # Judge the candidate as the N+1-th trial against the saved bank.
    suffix = f"_{args.universe}" if args.universe != "sp100" else ""
    bank_path = SWEEP_DIR / f"trials_net{suffix}.parquet"
    if bank_path.exists():
        bank = pd.read_parquet(bank_path)
        joint = bank.join(candidate.rename(name), how="inner")
        candidate_aligned = joint[name]
        bank_note = f"{joint.shape[1]} trials (saved bank + this candidate)"
        report = run_robustness_report(candidate_aligned, trial_returns=joint)
    else:
        bank_note = "NO SAVED BANK -- gates run single-trial; run the full sweep first"
        report = run_robustness_report(candidate, trial_returns=trials)

    lines = [
        f"# Strategy Lab backtest -- {name} on {args.universe}",
        "",
        f"OOS days   : {candidate.size}",
        f"Net Sharpe : {annualised_sharpe(candidate):.3f}",
        f"Total ret  : {float((1 + candidate).prod() - 1):.1%}",
        f"Max DD     : {max_drawdown(candidate):.1%}",
        f"Trial bank : {bank_note}",
        "",
        "## Era stability",
        "",
        era_table(candidate),
        "",
        "## Robustness battery",
        "",
        render_robustness_report(report),
        "",
        "Promotion path: PASS on sp500pit -> add a slot in tools/taquant_paper_run.py",
        "-> 90-day paper gate -> live. See the GO memo for the bar this implies.",
    ]
    text = "\n".join(lines)
    LAB_DIR.mkdir(parents=True, exist_ok=True)
    out = LAB_DIR / f"backtest_{name}_{args.universe}_{pd.Timestamp.utcnow():%Y%m%d_%H%M%S}.txt"
    out.write_text(text, encoding="utf-8")
    print()
    print(text)
    print(f"\nreport written to {out}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="show primaries, overlays, and grid configs")

    def _common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--config", default=None, help="named grid config")
        p.add_argument("--custom", default=None, help="path to custom strategy .py")
        p.add_argument("--universe", default="etf", choices=UNIVERSES)
        p.add_argument("--cost-model", default="ibkr")

    p_chart = sub.add_parser("chart", help="interactive signal/equity chart")
    _common(p_chart)
    p_chart.add_argument("--last", type=int, default=756, help="sessions to chart (default 3y)")
    p_chart.add_argument("--symbols", default=None, help="comma-separated symbols to chart")
    p_chart.add_argument("--max-symbols", type=int, default=4)

    p_bt = sub.add_parser("backtest", help="full walk-forward + robustness gates")
    _common(p_bt)

    args = parser.parse_args(argv)
    if args.command == "list":
        return cmd_list(args)
    if args.command == "chart":
        return cmd_chart(args)
    return cmd_backtest(args)


if __name__ == "__main__":
    raise SystemExit(main())
