# Research Notebooks

Per `docs/QUANT_TRADING_MASTER_PLAN.md` Phase 0.4 and Phase 2.2.

Standardised research workflow. Notebooks here are exploratory; code only
graduates into `core_trading/` after passing the Phase 2 validation gates
(purged CV, deflated Sharpe, PBO) documented in the master plan.

## Directory map

| Dir | Purpose |
|---|---|
| `00_data_exploration/` | Sanity-check data sources, coverage, quality |
| `01_feature_research/` | Build and evaluate candidate features (feature store) |
| `02_signal_research/` | Build signals in-sample; validate out-of-sample |
| `03_portfolio_research/` | Portfolio construction experiments (MVO, HRP, RP) |
| `04_risk_research/` | VaR/CVaR, GARCH, stress testing experiments |

## Rules

1. **Outputs are stripped on commit** via the `nbstripout` pre-commit hook --
   keeps diffs clean and avoids committing data snapshots. Do not disable it.
2. **No look-ahead bias.** Use `core_trading.data` with point-in-time-aware
   queries; never restated fundamentals in a backtest.
3. **Reproducibility.** Call `core_trading.research.reproducibility.set_seeds()`
   at the top of every notebook and log experiments to MLflow.
4. **Promotion.** A signal moves from `02_signal_research/` into
   `core_trading/signals/` only after the Phase 2 robustness checks pass and a
   rejection/promotion memo is written.

## Parameterised execution

Notebooks can be run headless with papermill, e.g.:

```bash
poetry run papermill notebooks/research/00_data_exploration/template.ipynb \
    out.ipynb -p symbol AAPL -p start 2020-01-01
```
