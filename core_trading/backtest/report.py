"""Backtest reporting (master plan Phase 3.8).

:class:`BacktestReport` wraps a :class:`~core_trading.backtest.engine.BacktestResult`
and exposes everything a human or a downstream pipeline needs:

* the equity curve, daily PnL and drawdown series,
* the trade ledger as a tidy :class:`pandas.DataFrame`,
* per-symbol PnL attribution,
* the full :class:`~core_trading.backtest.metrics.PerformanceMetrics`,
* a standardised, deterministic JSON document (``to_json`` / ``save_json``) for
  ML-pipeline ingestion, and
* an optional one-page PDF tear sheet (``save_pdf``) rendered headless via
  matplotlib's Agg backend.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from core_trading.backtest.engine import BacktestResult
from core_trading.backtest.metrics import PerformanceMetrics, compute_metrics, drawdown_series

__all__ = ["BacktestReport"]


@dataclass
class BacktestReport:
    """A formatted view over a backtest run."""

    result: BacktestResult
    metrics: PerformanceMetrics
    periods_per_year: int = 252

    @classmethod
    def from_result(
        cls,
        result: BacktestResult,
        periods_per_year: int = 252,
        risk_free: float = 0.0,
    ) -> BacktestReport:
        metrics = compute_metrics(
            result.equity,
            result.trades,
            periods_per_year=periods_per_year,
            risk_free=risk_free,
            turnover=result.turnover,
        )
        return cls(result=result, metrics=metrics, periods_per_year=periods_per_year)

    # ------------------------------------------------------------- time series
    @property
    def equity_curve(self) -> pd.Series:
        return self.result.equity

    def daily_pnl(self) -> pd.Series:
        """Period-over-period change in equity."""
        pnl = self.result.equity.diff().fillna(0.0)
        pnl.name = "pnl"
        return pnl

    def drawdown(self) -> pd.Series:
        dd = drawdown_series(self.result.equity)
        dd.name = "drawdown"
        return dd

    def position_weights(self) -> pd.DataFrame:
        """Target portfolio weights over time (position history)."""
        return self.result.weights

    # ------------------------------------------------------------ trade ledger
    def trade_ledger(self) -> pd.DataFrame:
        """All realised round-trip trades as a DataFrame (empty if none)."""
        if not self.result.trades:
            return pd.DataFrame(
                columns=[
                    "symbol",
                    "direction",
                    "quantity",
                    "entry_time",
                    "exit_time",
                    "entry_price",
                    "exit_price",
                    "pnl",
                    "costs",
                    "return_pct",
                    "bars_held",
                ]
            )
        rows = [
            {
                "symbol": t.symbol,
                "direction": t.direction,
                "quantity": t.quantity,
                "entry_time": t.entry_time,
                "exit_time": t.exit_time,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "pnl": t.pnl,
                "costs": t.costs,
                "return_pct": t.return_pct,
                "bars_held": t.bars_held,
            }
            for t in self.result.trades
        ]
        return pd.DataFrame(rows)

    def attribution(self) -> dict[str, float]:
        """Realised PnL by symbol (from the trade ledger)."""
        attrib: dict[str, float] = {}
        for t in self.result.trades:
            attrib[t.symbol] = attrib.get(t.symbol, 0.0) + t.pnl
        return attrib

    # -------------------------------------------------------------------- JSON
    def to_dict(self) -> dict[str, object]:
        """Standardised, JSON-serialisable summary of the run."""
        equity = self.result.equity
        return {
            "mode": self.result.mode,
            "initial_cash": self.result.initial_cash,
            "final_equity": float(equity.iloc[-1]) if equity.size else self.result.initial_cash,
            "n_periods": int(equity.size),
            "n_trades": len(self.result.trades),
            "total_costs": self.result.total_costs,
            "turnover": self.result.turnover,
            "fingerprint": self.result.fingerprint(),
            "metrics": self.metrics.to_dict(),
            "attribution": self.attribution(),
            "equity_curve": {
                "timestamps": [ts.isoformat() for ts in equity.index],
                "values": [float(v) for v in equity.to_numpy()],
            },
        }

    def to_json(self, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    def save_json(self, path: str | Path) -> Path:
        path = Path(path)
        path.write_text(self.to_json(), encoding="utf-8")
        return path

    # --------------------------------------------------------------------- PDF
    def save_pdf(self, path: str | Path) -> Path:
        """Render a one-page tear sheet to ``path`` (requires matplotlib)."""
        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError as exc:  # pragma: no cover - matplotlib is a dependency
            raise RuntimeError("save_pdf requires matplotlib") from exc

        path = Path(path)
        equity = self.result.equity
        dd = self.drawdown()
        fig, axes = plt.subplots(3, 1, figsize=(8.27, 11.69), height_ratios=[3, 2, 2])

        axes[0].plot(equity.index, equity.to_numpy(), color="navy")
        axes[0].set_title(f"Equity curve ({self.result.mode})")
        axes[0].set_ylabel("Equity")

        axes[1].fill_between(dd.index, dd.to_numpy(), color="firebrick", alpha=0.5)
        axes[1].set_title("Drawdown")
        axes[1].set_ylabel("Fraction")

        axes[2].axis("off")
        m = self.metrics
        text = (
            f"Total return: {m.total_return:.2%}    CAGR: {m.cagr:.2%}\n"
            f"Sharpe: {m.sharpe:.2f}    Sortino: {m.sortino:.2f}    Calmar: {m.calmar:.2f}\n"
            f"Max drawdown: {m.max_drawdown:.2%}    Ulcer: {m.ulcer_index:.2f}\n"
            f"VaR(95): {m.var_95:.2%}    CVaR(95): {m.cvar_95:.2%}\n"
            f"Trades: {m.n_trades}    Win rate: {m.win_rate:.2%}    "
            f"Profit factor: {m.profit_factor:.2f}"
        )
        axes[2].text(0.01, 0.95, text, va="top", family="monospace", fontsize=10)

        fig.tight_layout()
        fig.savefig(path)
        plt.close(fig)
        return path
