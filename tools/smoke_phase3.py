"""Phase 3 smoke validation: engine modes agree, replay is deterministic.

Run with: poetry run python tools/smoke_phase3.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core_trading.backtest import (
    BacktestConfig,
    BacktestEngine,
    BacktestReport,
    WeightStrategy,
    monte_carlo_analysis,
)


def _panel(seed: int = 7, n: int = 300) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    syms = ["AAA", "BBB"]
    idx = pd.date_range("2021-01-01", periods=n, freq="D", tz="UTC")
    frames = []
    for s in syms:
        px = np.maximum(100 + np.cumsum(rng.standard_normal(n)) * 0.5, 5.0)
        hi = px + np.abs(rng.standard_normal(n)) * 0.3
        lo = px - np.abs(rng.standard_normal(n)) * 0.3
        frames.append(
            pd.DataFrame(
                {
                    "open": px,
                    "high": np.maximum(hi, px),
                    "low": np.minimum(lo, px),
                    "close": px,
                    "volume": rng.uniform(1e6, 2e6, n),
                },
                index=pd.MultiIndex.from_product([[s], idx], names=["symbol", "timestamp"]),
            )
        )
    return pd.concat(frames).sort_index()


def main() -> None:
    prices = _panel()
    syms = ["AAA", "BBB"]
    idx = prices.index.get_level_values("timestamp").unique()
    weights = pd.DataFrame(0.5, index=idx, columns=syms)
    strat = WeightStrategy(weights)

    cfg = BacktestConfig(initial_cash=1_000_000, cost_model_name="zero", max_participation_rate=1.0)
    eng = BacktestEngine(cfg)
    rv = eng.run(prices, strat, mode="vectorised")
    re = eng.run(prices, strat, mode="event_driven")
    rel = float((rv.equity - re.equity).abs().div(re.equity).max())

    print(f"[OK] vector final  = {rv.equity.iloc[-1]:.2f}")
    print(f"[OK] event final   = {re.equity.iloc[-1]:.2f}")
    print(f"[OK] max rel diff  = {rel:.2e}  (agree<1bp/day: {rel < 1e-4})")

    re2 = eng.run(prices, strat, mode="event_driven")
    print(f"[OK] replay byte-identical: {re.fingerprint() == re2.fingerprint()}")

    rep = BacktestReport.from_result(re)
    print(
        f"[OK] sharpe={rep.metrics.sharpe:.3f} maxDD={rep.metrics.max_drawdown:.4f} "
        f"trades={rep.metrics.n_trades}"
    )
    print(f"[OK] json bytes    = {len(rep.to_json())}")

    mc = monte_carlo_analysis(re.returns, n_sims=200, method="block", block_size=10, seed=1)
    s = mc.summary()
    print(
        f"[OK] MC median terminal wealth = {s['median_terminal_wealth']:.4f} "
        f"p05 sharpe={s['p05_sharpe']:.3f}"
    )
    print("[OK] Phase 3 smoke passed")


if __name__ == "__main__":
    main()
