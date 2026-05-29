"""Performance and risk metrics (master plan Phase 3.8).

Functions operate on an equity curve (a price-like :class:`pandas.Series`), its
period returns, or a list of realised
:class:`~core_trading.backtest.orders.Trade` records, and feed
:class:`PerformanceMetrics` -- the standardised summary the backtest report and
the ML pipeline consume.

The metric set mirrors (and replaces) the intent of the old
``strategies/backtesting/metrics.py``: Sharpe, Sortino, Calmar, MAR, maximum
drawdown, historical VaR/CVaR, Ulcer index, Omega, profit factor, win rate,
expectancy and tail ratio. Every function guards degenerate inputs (empty
series, zero variance, no losing trades) so a backtest never raises or emits a
numpy warning under ``-W error``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from core_trading.backtest.orders import Trade

__all__ = [
    "PerformanceMetrics",
    "returns_from_equity",
    "annualized_return",
    "annualized_volatility",
    "cagr",
    "sharpe_ratio",
    "sortino_ratio",
    "drawdown_series",
    "max_drawdown",
    "calmar_ratio",
    "mar_ratio",
    "value_at_risk",
    "conditional_value_at_risk",
    "ulcer_index",
    "omega_ratio",
    "tail_ratio",
    "profit_factor",
    "win_rate",
    "average_win_loss",
    "expectancy",
    "compute_metrics",
]

_TRADING_DAYS = 252

# Below this, a return standard deviation is floating-point noise (e.g. the
# residual std of identical returns), not real risk, so ratios return 0.
_VOL_EPS = 1e-12


def _clean_returns(returns: pd.Series | np.ndarray) -> np.ndarray:
    arr = np.asarray(returns, dtype=float).ravel()
    finite: np.ndarray = arr[np.isfinite(arr)]
    return finite


def returns_from_equity(equity: pd.Series) -> pd.Series:
    """Simple period returns of an equity curve (first NaN dropped)."""
    return equity.pct_change().dropna()


def annualized_return(
    returns: pd.Series | np.ndarray, periods_per_year: int = _TRADING_DAYS
) -> float:
    """Geometric annualised return from period returns."""
    arr = _clean_returns(returns)
    if arr.size == 0:
        return 0.0
    growth = float(np.prod(1.0 + arr))
    if growth <= 0:
        return -1.0
    return float(growth ** (periods_per_year / arr.size) - 1.0)


def annualized_volatility(
    returns: pd.Series | np.ndarray, periods_per_year: int = _TRADING_DAYS
) -> float:
    arr = _clean_returns(returns)
    if arr.size < 2:
        return 0.0
    return float(np.std(arr, ddof=1) * np.sqrt(periods_per_year))


def cagr(equity: pd.Series, periods_per_year: int = _TRADING_DAYS) -> float:
    """Compound annual growth rate from an equity curve."""
    vals = _clean_returns(equity)
    if vals.size < 2 or vals[0] <= 0:
        return 0.0
    total_growth = vals[-1] / vals[0]
    if total_growth <= 0:
        return -1.0
    n_periods = vals.size - 1
    return float(total_growth ** (periods_per_year / n_periods) - 1.0)


def sharpe_ratio(
    returns: pd.Series | np.ndarray,
    periods_per_year: int = _TRADING_DAYS,
    risk_free: float = 0.0,
) -> float:
    """Annualised Sharpe ratio. ``risk_free`` is an annual rate."""
    arr = _clean_returns(returns)
    if arr.size < 2:
        return 0.0
    excess = arr - risk_free / periods_per_year
    sd = float(np.std(excess, ddof=1))
    if sd < _VOL_EPS:
        return 0.0
    return float(float(np.mean(excess)) / sd * np.sqrt(periods_per_year))


def sortino_ratio(
    returns: pd.Series | np.ndarray,
    periods_per_year: int = _TRADING_DAYS,
    risk_free: float = 0.0,
) -> float:
    """Annualised Sortino ratio (downside-deviation denominator)."""
    arr = _clean_returns(returns)
    if arr.size < 2:
        return 0.0
    excess = arr - risk_free / periods_per_year
    downside = excess[excess < 0]
    if downside.size == 0:
        return 0.0
    dd = float(np.sqrt(np.mean(downside**2)))
    if dd < _VOL_EPS:
        return 0.0
    return float(float(np.mean(excess)) / dd * np.sqrt(periods_per_year))


def drawdown_series(equity: pd.Series) -> pd.Series:
    """Fractional drawdown from the running peak at each point (<= 0)."""
    running_max = equity.cummax()
    return equity / running_max - 1.0


def max_drawdown(equity: pd.Series) -> float:
    """Maximum drawdown as a positive fraction (0.2 == a 20% drawdown)."""
    if equity.size == 0:
        return 0.0
    return float(-drawdown_series(equity).min())


def calmar_ratio(equity: pd.Series, periods_per_year: int = _TRADING_DAYS) -> float:
    """CAGR divided by maximum drawdown."""
    mdd = max_drawdown(equity)
    if mdd == 0:
        return 0.0
    return cagr(equity, periods_per_year) / mdd


def mar_ratio(equity: pd.Series, periods_per_year: int = _TRADING_DAYS) -> float:
    """MAR ratio -- identical definition to Calmar (CAGR / max drawdown),
    provided under its conventional name."""
    return calmar_ratio(equity, periods_per_year)


def value_at_risk(returns: pd.Series | np.ndarray, alpha: float = 0.05) -> float:
    """Historical Value-at-Risk at ``alpha`` as a positive loss fraction."""
    if not 0 < alpha < 1:
        raise ValueError("alpha must be in (0, 1)")
    arr = _clean_returns(returns)
    if arr.size == 0:
        return 0.0
    return float(-np.quantile(arr, alpha))


def conditional_value_at_risk(returns: pd.Series | np.ndarray, alpha: float = 0.05) -> float:
    """Historical CVaR (expected shortfall) at ``alpha`` as a positive loss."""
    if not 0 < alpha < 1:
        raise ValueError("alpha must be in (0, 1)")
    arr = _clean_returns(returns)
    if arr.size == 0:
        return 0.0
    threshold = np.quantile(arr, alpha)
    tail = arr[arr <= threshold]
    if tail.size == 0:
        return float(-threshold)
    return float(-np.mean(tail))


def ulcer_index(equity: pd.Series) -> float:
    """Ulcer index: RMS of percentage drawdowns (in percent)."""
    if equity.size == 0:
        return 0.0
    dd_pct = drawdown_series(equity).to_numpy(dtype=float) * 100.0
    return float(np.sqrt(np.mean(dd_pct**2)))


def omega_ratio(returns: pd.Series | np.ndarray, threshold: float = 0.0) -> float:
    """Omega ratio: gains above ``threshold`` over losses below it."""
    arr = _clean_returns(returns)
    if arr.size == 0:
        return 0.0
    excess = arr - threshold
    gains = float(np.sum(excess[excess > 0]))
    losses = float(-np.sum(excess[excess < 0]))
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return gains / losses


def tail_ratio(returns: pd.Series | np.ndarray, tail: float = 0.05) -> float:
    """Ratio of the right-tail to the left-tail magnitude (95th vs 5th pctile)."""
    arr = _clean_returns(returns)
    if arr.size == 0:
        return 0.0
    right = np.quantile(arr, 1 - tail)
    left = np.quantile(arr, tail)
    if left == 0:
        return float("inf") if right > 0 else 0.0
    return float(abs(right) / abs(left))


def profit_factor(trades: list[Trade]) -> float:
    """Gross profit divided by gross loss across realised trades."""
    if not trades:
        return 0.0
    gross_profit = sum(t.pnl for t in trades if t.pnl > 0)
    gross_loss = -sum(t.pnl for t in trades if t.pnl < 0)
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def win_rate(trades: list[Trade]) -> float:
    """Fraction of realised trades with positive PnL."""
    if not trades:
        return 0.0
    return sum(1 for t in trades if t.is_win) / len(trades)


def average_win_loss(trades: list[Trade]) -> tuple[float, float]:
    """Mean winning PnL and mean losing PnL (the latter <= 0)."""
    wins = [t.pnl for t in trades if t.pnl > 0]
    losses = [t.pnl for t in trades if t.pnl < 0]
    avg_win = float(np.mean(wins)) if wins else 0.0
    avg_loss = float(np.mean(losses)) if losses else 0.0
    return avg_win, avg_loss


def expectancy(trades: list[Trade]) -> float:
    """Expected PnL per trade = mean realised PnL."""
    if not trades:
        return 0.0
    return float(np.mean([t.pnl for t in trades]))


@dataclass(frozen=True)
class PerformanceMetrics:
    """Standardised performance summary for a backtest."""

    total_return: float = 0.0
    cagr: float = 0.0
    annual_volatility: float = 0.0
    sharpe: float = 0.0
    sortino: float = 0.0
    calmar: float = 0.0
    mar: float = 0.0
    max_drawdown: float = 0.0
    ulcer_index: float = 0.0
    var_95: float = 0.0
    cvar_95: float = 0.0
    omega: float = 0.0
    tail_ratio: float = 0.0
    n_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    expectancy: float = 0.0
    turnover: float = 0.0
    extra: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, float]:
        out: dict[str, float] = {
            "total_return": self.total_return,
            "cagr": self.cagr,
            "annual_volatility": self.annual_volatility,
            "sharpe": self.sharpe,
            "sortino": self.sortino,
            "calmar": self.calmar,
            "mar": self.mar,
            "max_drawdown": self.max_drawdown,
            "ulcer_index": self.ulcer_index,
            "var_95": self.var_95,
            "cvar_95": self.cvar_95,
            "omega": self.omega,
            "tail_ratio": self.tail_ratio,
            "n_trades": float(self.n_trades),
            "win_rate": self.win_rate,
            "profit_factor": self.profit_factor,
            "avg_win": self.avg_win,
            "avg_loss": self.avg_loss,
            "expectancy": self.expectancy,
            "turnover": self.turnover,
        }
        out.update(self.extra)
        return out


def compute_metrics(
    equity: pd.Series,
    trades: list[Trade] | None = None,
    periods_per_year: int = _TRADING_DAYS,
    risk_free: float = 0.0,
    turnover: float = 0.0,
) -> PerformanceMetrics:
    """Compute the full :class:`PerformanceMetrics` summary."""
    trades = trades or []
    rets = returns_from_equity(equity) if equity.size >= 2 else pd.Series(dtype=float)
    vals = _clean_returns(equity)
    total_return = float(vals[-1] / vals[0] - 1.0) if vals.size >= 2 and vals[0] > 0 else 0.0
    avg_win, avg_loss = average_win_loss(trades)
    return PerformanceMetrics(
        total_return=total_return,
        cagr=cagr(equity, periods_per_year),
        annual_volatility=annualized_volatility(rets, periods_per_year),
        sharpe=sharpe_ratio(rets, periods_per_year, risk_free),
        sortino=sortino_ratio(rets, periods_per_year, risk_free),
        calmar=calmar_ratio(equity, periods_per_year),
        mar=mar_ratio(equity, periods_per_year),
        max_drawdown=max_drawdown(equity),
        ulcer_index=ulcer_index(equity),
        var_95=value_at_risk(rets, 0.05),
        cvar_95=conditional_value_at_risk(rets, 0.05),
        omega=omega_ratio(rets, 0.0),
        tail_ratio=tail_ratio(rets),
        n_trades=len(trades),
        win_rate=win_rate(trades),
        profit_factor=profit_factor(trades),
        avg_win=avg_win,
        avg_loss=avg_loss,
        expectancy=expectancy(trades),
        turnover=turnover,
    )
