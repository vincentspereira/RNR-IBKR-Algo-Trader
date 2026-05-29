"""Generate the 9-step strategy-development notebook templates (Phase 2.2).

Run with ``poetry run python notebooks/research/strategy_template/_generate.py``.
Each template is hermetic (seeded synthetic data, no network) so it executes in
CI as a smoke test; flip ``USE_SYNTHETIC = False`` in a notebook's parameters
cell to point it at real vendors via ``core_trading.data.sources``.

The templates mirror the de Prado research pipeline in the master plan:
each step gates the next, and code only graduates into ``core_trading/signals/``
after step 08.
"""
from __future__ import annotations

from pathlib import Path

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

HERE = Path(__file__).parent

# Shared setup prepended to every notebook (after its parameters cell): builds a
# hermetic, seeded OHLCV frame in the standard (symbol, timestamp) layout.
SETUP = '''\
import numpy as np
import pandas as pd

from core_trading.research.reproducibility import set_seeds

set_seeds(SEED)


def synthetic_bars(symbols, n, seed, start=START):
    """Seeded OHLCV frame in the canonical (symbol, timestamp) layout."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n, freq="B", tz="UTC")
    frames = []
    for k, sym in enumerate(symbols):
        drift = 0.0003 * (1 + k)
        px = 100.0 + np.cumsum(rng.standard_normal(n) + drift)
        px = np.maximum(px, 1.0)
        high = px + np.abs(rng.standard_normal(n)) * 0.4
        low = px - np.abs(rng.standard_normal(n)) * 0.4
        frame = pd.DataFrame(
            {
                "open": px,
                "high": np.maximum(high, px),
                "low": np.minimum(low, px),
                "close": px,
                "volume": rng.uniform(1e6, 5e6, n),
                "source": "synthetic",
            },
            index=pd.MultiIndex.from_product(
                [[sym], idx], names=["symbol", "timestamp"]
            ),
        )
        frames.append(frame)
    return pd.concat(frames).sort_index()


if USE_SYNTHETIC:
    bars = synthetic_bars(SYMBOLS, N_DAYS, SEED)
else:  # pragma: no cover - exercised only against live vendors
    import asyncio

    from core_trading.data.bars import BarRequest, BarResolution
    from core_trading.data.sources.yfinance_source import YFinanceBarSource

    req = BarRequest(
        symbols=tuple(SYMBOLS),
        resolution=BarResolution.DAY_1,
        start=pd.Timestamp(START, tz="UTC").to_pydatetime(),
        end=pd.Timestamp.now(tz="UTC").to_pydatetime(),
    )
    bars = asyncio.run(YFinanceBarSource().fetch_bars(req))

print(f"loaded {bars.shape[0]} bars across {len(SYMBOLS)} symbols")
bars.head()
'''

PARAMS = """\
# Parameters (papermill-overridable: `papermill ... -p SYMBOLS '["AAPL","MSFT"]'`)
SYMBOLS = ["ALPHA", "BRAVO", "CHARLIE"]
START = "2018-01-01"
N_DAYS = 600
SEED = 7
USE_SYNTHETIC = True  # set False to fetch real data via core_trading.data.sources
"""


def _params_cell():
    cell = new_code_cell(PARAMS)
    cell.metadata["tags"] = ["parameters"]
    return cell


def _nb(title, intro, *cells):
    nb = new_notebook()
    nb.cells = [
        new_markdown_cell(f"# {title}\n\n{intro}"),
        _params_cell(),
        new_code_cell(SETUP),
        *cells,
    ]
    nb.metadata["kernelspec"] = {
        "display_name": "Python 3",
        "language": "python",
        "name": "python3",
    }
    nb.metadata["language_info"] = {"name": "python"}
    return nb


def build() -> dict[str, nbformat.NotebookNode]:
    nbs: dict[str, nbformat.NotebookNode] = {}

    # 00 -- universe -------------------------------------------------------------
    nbs["00_universe.ipynb"] = _nb(
        "00 -- Universe",
        "Confirm the tradable universe (survivorship-bias aware) before any "
        "research. We use a built-in static snapshot here; vintage membership "
        "for backtests comes from `core_trading.data.universe`.",
        new_code_cell(
            "from core_trading.data.universe import get_universe\n\n"
            "sp100 = get_universe('SP100')\n"
            "print('SP100 snapshot date:', sp100.snapshot_date)\n"
            "print('member count:', len(sp100.current_symbols()))\n"
            "print('first 10:', sp100.current_symbols()[:10])"
        ),
        new_code_cell(
            "# The working universe for this study (synthetic tickers by default).\n"
            "universe = SYMBOLS\n"
            "print('research universe:', universe)"
        ),
        new_markdown_cell(
            "**Gate:** universe fixed and point-in-time aware -> proceed to "
            "`01_hypothesis.ipynb`."
        ),
    )

    # 01 -- hypothesis -----------------------------------------------------------
    nbs["01_hypothesis.ipynb"] = _nb(
        "01 -- Hypothesis",
        "State the alpha hypothesis in plain English *before* looking at the "
        "data. A hypothesis written after the fact is just curve-fitting.",
        new_markdown_cell(
            "## Hypothesis\n\n"
            "> *Short-horizon returns over-extend and partially reverse: a "
            "negative 20-day z-score of price predicts positive forward "
            "returns (mean reversion).*\n\n"
            "- **Economic rationale:** liquidity provision / overreaction.\n"
            "- **Horizon:** 1-5 days.\n"
            "- **Failure mode:** trending regimes (momentum dominates).\n"
            "- **Falsifiable prediction:** forward returns rise monotonically "
            "as the entry z-score falls."
        ),
        new_code_cell(
            "rets = bars['close'].groupby(level='symbol').pct_change()\n"
            "print('daily return summary:')\n"
            "rets.groupby(level='symbol').describe()"
        ),
        new_markdown_cell(
            "**Gate:** hypothesis + rationale written -> proceed to " "`02_features.ipynb`."
        ),
    )

    # 02 -- features -------------------------------------------------------------
    nbs["02_features.ipynb"] = _nb(
        "02 -- Features",
        "Compute candidate features with the **look-ahead-free** feature store "
        "and inspect their distributions.",
        new_code_cell(
            "from core_trading.research.feature_store import default_feature_store\n\n"
            "store = default_feature_store()\n"
            "print('available features:', len(store))\n"
            "candidates = ['zscore_20', 'rsi_14', 'vol_21', 'ret_5']\n"
            "feats = store.compute(bars, candidates)\n"
            "feats.attrs['feature_versions']"
        ),
        new_code_cell("feats.groupby(level='symbol').describe().T"),
        new_code_cell(
            "# Correlation of candidate features (pooled across symbols).\n" "feats.corr()"
        ),
        new_markdown_cell(
            "**Gate:** features computed, no look-ahead, distributions sane -> "
            "proceed to `03_signal.ipynb`."
        ),
    )

    # 03 -- signal ---------------------------------------------------------------
    nbs["03_signal.ipynb"] = _nb(
        "03 -- Signal (in-sample only)",
        "Turn a feature into a signal. **In-sample only** -- no validation yet. "
        "The signal is the negative 20-day z-score (mean reversion).",
        new_code_cell(
            "from core_trading.research.feature_store import default_feature_store\n\n"
            "store = default_feature_store()\n"
            "z = store.compute(bars, ['zscore_20'])['zscore_20']\n"
            "# Mean-reversion signal: fade extension, clipped to [-1, 1].\n"
            "signal = (-z / 2.0).clip(-1.0, 1.0)\n"
            "signal.name = 'signal'\n"
            "signal.groupby(level='symbol').describe()"
        ),
        new_code_cell(
            "# Forward 1-day return, aligned per symbol (the label).\n"
            "fwd = bars['close'].groupby(level='symbol').pct_change().groupby(\n"
            "    level='symbol').shift(-1)\n"
            "panel = pd.concat([signal, fwd.rename('fwd_ret')], axis=1).dropna()\n"
            "ic = panel['signal'].corr(panel['fwd_ret'])\n"
            "print(f'in-sample information coefficient: {ic:.4f}')"
        ),
        new_markdown_cell(
            "**Gate:** signal defined, IC has the expected sign -> proceed to "
            "`04_validation.ipynb`. (A positive IC is necessary, not "
            "sufficient -- it is in-sample.)"
        ),
    )

    # 04 -- validation -----------------------------------------------------------
    nbs["04_validation.ipynb"] = _nb(
        "04 -- Validation (purged CV + walk-forward)",
        "Validate the signal out-of-sample with **purged k-fold** and "
        "**walk-forward** splits that respect label spans and embargo.",
        new_code_cell(
            "from core_trading.research.feature_store import default_feature_store\n"
            "from core_trading.research.cross_validation import (\n"
            "    PurgedKFold, WalkForwardSplit, make_label_end_times)\n\n"
            "store = default_feature_store()\n"
            "z = store.compute(bars, ['zscore_20'])['zscore_20']\n"
            "signal = (-z / 2.0).clip(-1.0, 1.0)\n"
            "fwd = bars['close'].groupby(level='symbol').pct_change().groupby(\n"
            "    level='symbol').shift(-1)\n\n"
            "# Work on a single symbol for the CV illustration.\n"
            "sym = SYMBOLS[0]\n"
            "s = signal.xs(sym, level='symbol')\n"
            "r = fwd.xs(sym, level='symbol')\n"
            "panel = pd.concat([s.rename('sig'), r.rename('ret')], axis=1).dropna()\n"
            "times = panel.index"
        ),
        new_code_cell(
            "def fold_ic(idx):\n"
            "    sub = panel.iloc[idx]\n"
            "    return sub['sig'].corr(sub['ret'])\n\n"
            "t1 = make_label_end_times(times, 1)\n"
            "pkf = PurgedKFold(n_splits=5, embargo_pct=0.02)\n"
            "oos_ic = [fold_ic(sp.test_indices) for sp in pkf.split(times, t1)]\n"
            "print('purged k-fold OOS ICs:', [round(x, 4) for x in oos_ic])\n"
            "print('mean OOS IC:', round(float(np.nanmean(oos_ic)), 4))"
        ),
        new_code_cell(
            "wf = WalkForwardSplit(n_splits=5, test_size=60, anchored=True)\n"
            "wf_ic = [fold_ic(sp.test_indices) for sp in wf.split(times)]\n"
            "print('walk-forward OOS ICs:', [round(x, 4) for x in wf_ic])"
        ),
        new_markdown_cell(
            "**Gate:** OOS IC stable and same-signed across folds -> proceed to "
            "`05_portfolio.ipynb`. Unstable signs across folds = overfit; stop."
        ),
    )

    # 05 -- portfolio ------------------------------------------------------------
    nbs["05_portfolio.ipynb"] = _nb(
        "05 -- Portfolio construction",
        "Combine the signal across the universe into positions. This baseline "
        "uses signal-proportional, gross-normalised weights; **Phase 6** "
        "replaces it with mean-variance / HRP / risk-parity construction.",
        new_code_cell(
            "from core_trading.research.feature_store import default_feature_store\n\n"
            "store = default_feature_store()\n"
            "z = store.compute(bars, ['zscore_20'])['zscore_20']\n"
            "signal = (-z / 2.0).clip(-1.0, 1.0)\n"
            "sig_wide = signal.unstack('symbol').dropna(how='all')\n\n"
            "# Gross-normalised weights (sum |w| = 1) each day -- market-neutral-ish.\n"
            "gross = sig_wide.abs().sum(axis=1).replace(0.0, np.nan)\n"
            "weights = sig_wide.div(gross, axis=0).fillna(0.0)\n"
            "print('mean gross exposure:', float(weights.abs().sum(axis=1).mean()))\n"
            "weights.tail()"
        ),
        new_markdown_cell(
            "**Gate:** weights respect gross/again-net limits -> proceed to "
            "`06_backtest.ipynb`. _Phase 6 will enforce sector caps and "
            "beta-neutralisation here._"
        ),
    )

    # 06 -- backtest -------------------------------------------------------------
    nbs["06_backtest.ipynb"] = _nb(
        "06 -- Backtest (with costs)",
        "Vectorised backtest of the portfolio with a simple turnover-based cost "
        "model. **Phase 3** replaces this with the event-driven engine "
        "(slippage, market impact, partial fills).",
        new_code_cell(
            "from core_trading.research.feature_store import default_feature_store\n\n"
            "store = default_feature_store()\n"
            "z = store.compute(bars, ['zscore_20'])['zscore_20']\n"
            "signal = (-z / 2.0).clip(-1.0, 1.0)\n"
            "weights = signal.unstack('symbol')\n"
            "gross = weights.abs().sum(axis=1).replace(0.0, np.nan)\n"
            "weights = weights.div(gross, axis=0).fillna(0.0)\n\n"
            "rets = bars['close'].unstack('symbol').pct_change()\n"
            "rets, weights = rets.align(weights, join='inner')\n\n"
            "COST_BPS = 1.0  # round-trip cost per unit turnover, in basis points\n"
            "turnover = weights.diff().abs().sum(axis=1).fillna(0.0)\n"
            "# Yesterday's weights earn today's return; charge cost on rebalancing.\n"
            "gross_ret = (weights.shift(1) * rets).sum(axis=1)\n"
            "net_ret = gross_ret - turnover * COST_BPS / 1e4\n"
            "equity = (1.0 + net_ret).cumprod()\n"
            "print('final equity (net):', round(float(equity.iloc[-1]), 4))\n"
            "print('avg daily turnover:', round(float(turnover.mean()), 4))"
        ),
        new_code_cell(
            "from core_trading.research.overfitting import sharpe_ratio\n\n"
            "print('net Sharpe (ann.):', round(sharpe_ratio(net_ret.dropna()), 3))\n"
            "dd = equity / equity.cummax() - 1.0\n"
            "print('max drawdown:', round(float(dd.min()), 4))\n"
            "equity.plot(title='Equity curve (net of costs)')"
        ),
        new_markdown_cell(
            "**Gate:** positive net Sharpe after realistic costs -> proceed to "
            "`07_robustness.ipynb`."
        ),
    )

    # 07 -- robustness -----------------------------------------------------------
    nbs["07_robustness.ipynb"] = _nb(
        "07 -- Robustness (DSR, PBO, reality check)",
        "The anti-overfitting battery. We build a small matrix of parameter "
        "variants and ask whether the best one is real or lucky.",
        new_code_cell(
            "from core_trading.research.feature_store import default_feature_store\n"
            "from core_trading.research.overfitting import (\n"
            "    deflated_sharpe_ratio, probability_of_backtest_overfitting,\n"
            "    whites_reality_check, sharpe_ratio)\n\n"
            "store = default_feature_store()\n"
            "rets = bars['close'].unstack('symbol').pct_change()\n\n"
            "# Variants: z-score thresholds for the same mean-reversion signal.\n"
            "variant_returns = {}\n"
            "z = store.compute(bars, ['zscore_20'])['zscore_20'].unstack('symbol')\n"
            "for thr in (0.5, 1.0, 1.5, 2.0, 2.5):\n"
            "    w = (-z).clip(-thr, thr) / thr\n"
            "    g = w.abs().sum(axis=1).replace(0.0, np.nan)\n"
            "    w = w.div(g, axis=0).fillna(0.0)\n"
            "    r = (w.shift(1) * rets).sum(axis=1).fillna(0.0)\n"
            "    variant_returns[f'thr_{thr}'] = r\n"
            "ret_mat = pd.DataFrame(variant_returns).dropna()\n"
            "ret_mat.apply(sharpe_ratio).round(3)"
        ),
        new_code_cell(
            "best = ret_mat.apply(sharpe_ratio).idxmax()\n"
            "dsr = deflated_sharpe_ratio(\n"
            "    ret_mat[best], n_trials=ret_mat.shape[1],\n"
            "    trial_sharpes=[sharpe_ratio(ret_mat[c], annualised=False)\n"
            "                   for c in ret_mat.columns])\n"
            "print(f'best variant: {best}')\n"
            "print(f'deflated Sharpe: {dsr.deflated_sharpe:.3f} '\n"
            "      f'(significant={dsr.is_significant})')"
        ),
        new_code_cell(
            "pbo = probability_of_backtest_overfitting(ret_mat.values, n_splits=8)\n"
            "rc = whites_reality_check(ret_mat.values, n_bootstrap=500, seed=SEED)\n"
            "print(f'PBO: {pbo.pbo:.3f} (overfit={pbo.is_overfit})')\n"
            'print(f"White\'s Reality Check p-value: {rc.pvalue:.3f}")'
        ),
        new_markdown_cell(
            "**Gate:** Deflated Sharpe >= 0.95 **and** PBO < 0.5 **and** reality "
            "check significant -> proceed to `08_promotion.ipynb`. Otherwise "
            "reject and document why."
        ),
    )

    # 08 -- promotion ------------------------------------------------------------
    nbs["08_promotion.ipynb"] = _nb(
        "08 -- Promotion / rejection memo",
        "The final, single-use out-of-sample check and the written decision. "
        "The lockbox enforces that the held-out slice is touched exactly once.",
        new_code_cell(
            "from pathlib import Path\n\n"
            "from core_trading.research.feature_store import default_feature_store\n"
            "from core_trading.research.overfitting import (\n"
            "    OutOfSampleLockbox, sharpe_ratio)\n\n"
            "store = default_feature_store()\n"
            "z = store.compute(bars, ['zscore_20'])['zscore_20'].unstack('symbol')\n"
            "rets = bars['close'].unstack('symbol').pct_change()\n"
            "w = (-z / 2.0).clip(-1.0, 1.0)\n"
            "g = w.abs().sum(axis=1).replace(0.0, np.nan)\n"
            "w = w.div(g, axis=0).fillna(0.0)\n"
            "strat_ret = (w.shift(1) * rets).sum(axis=1).fillna(0.0).to_frame('ret')"
        ),
        new_code_cell(
            "ledger = Path('lockbox_ledger.json')\n"
            "box = OutOfSampleLockbox(strat_ret, lockbox_fraction=0.2,\n"
            "                         ledger_path=ledger, name='zscore20_meanrev')\n"
            "dev_sharpe = sharpe_ratio(box.development_set['ret'])\n"
            "print(f'development Sharpe: {dev_sharpe:.3f}')\n\n"
            "# Touch the lockbox exactly once for the final read-out.\n"
            "if not box.is_opened():\n"
            "    holdout = box.open_lockbox('final OOS evaluation of zscore20 mean-reversion')\n"
            "    oos_sharpe = sharpe_ratio(holdout['ret'])\n"
            "    print(f'lockbox (OOS) Sharpe: {oos_sharpe:.3f}')\n"
            "else:\n"
            "    print('lockbox already opened -- OOS is single-use; see ledger.')"
        ),
        new_markdown_cell(
            "## Decision memo\n\n"
            "| Criterion | Threshold | Result |\n"
            "|---|---|---|\n"
            "| Deflated Sharpe | >= 0.95 | _fill in_ |\n"
            "| PBO | < 0.5 | _fill in_ |\n"
            "| OOS Sharpe vs development | within 1 SE | _fill in_ |\n\n"
            "**Decision:** PROMOTE to paper / REJECT (delete). If promoting, the "
            "signal graduates into `core_trading/signals/` and enters the "
            "Phase 4 paper-trading pipeline. If rejecting, record the reason "
            "here so the idea is not silently retried."
        ),
    )

    return nbs


def main() -> None:
    notebooks = build()
    for filename, nb in notebooks.items():
        path = HERE / filename
        nbformat.write(nb, path)
        print(f"wrote {path.relative_to(HERE.parents[2])}")


if __name__ == "__main__":
    main()
