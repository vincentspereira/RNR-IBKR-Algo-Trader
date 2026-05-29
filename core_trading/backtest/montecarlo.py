"""Monte Carlo robustness analysis (master plan Phase 3.4).

A single backtest produces one equity path -- one draw from a distribution. This
module resamples that path to estimate the *distribution* of outcomes (terminal
wealth, maximum drawdown, Sharpe) so a strategy is judged by its spread of
plausible results, not a single lucky number.

Three resampling methods:

* ``"iid"`` -- resample period returns with replacement. Destroys autocorrelation;
  a fast first cut.
* ``"block"`` -- circular block bootstrap (Politis-Romano style fixed blocks). It
  resamples contiguous blocks, preserving short-horizon autocorrelation, which
  matters for drawdown statistics.
* ``"gaussian"`` -- simulate synthetic paths from a fitted normal with the sample
  mean and variance. A smooth parametric baseline.

All methods are seeded, so the analysis is reproducible.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from core_trading.backtest.metrics import max_drawdown, sharpe_ratio

__all__ = [
    "MonteCarloResult",
    "iid_bootstrap_paths",
    "block_bootstrap_paths",
    "gaussian_paths",
    "monte_carlo_analysis",
]


@dataclass(frozen=True)
class MonteCarloResult:
    """Distributions of summary statistics across Monte Carlo paths."""

    method: str
    n_sims: int
    terminal_wealth: np.ndarray
    max_drawdown: np.ndarray
    sharpe: np.ndarray

    def percentiles(
        self, statistic: str, quantiles: tuple[float, ...] = (5, 25, 50, 75, 95)
    ) -> dict[float, float]:
        arr = getattr(self, statistic)
        return {q: float(np.percentile(arr, q)) for q in quantiles}

    def probability_of_loss(self) -> float:
        """Fraction of paths ending below the starting equity (wealth < 1)."""
        return float(np.mean(self.terminal_wealth < 1.0))

    def summary(self) -> dict[str, float]:
        return {
            "median_terminal_wealth": float(np.median(self.terminal_wealth)),
            "p05_terminal_wealth": float(np.percentile(self.terminal_wealth, 5)),
            "p95_terminal_wealth": float(np.percentile(self.terminal_wealth, 95)),
            "median_max_drawdown": float(np.median(self.max_drawdown)),
            "p95_max_drawdown": float(np.percentile(self.max_drawdown, 95)),
            "median_sharpe": float(np.median(self.sharpe)),
            "p05_sharpe": float(np.percentile(self.sharpe, 5)),
            "probability_of_loss": self.probability_of_loss(),
        }


def _clean(returns: pd.Series | np.ndarray) -> np.ndarray:
    arr = np.asarray(returns, dtype=float).ravel()
    finite: np.ndarray = arr[np.isfinite(arr)]
    return finite


def iid_bootstrap_paths(returns: np.ndarray, n_paths: int, rng: np.random.Generator) -> np.ndarray:
    """Resample returns i.i.d. with replacement. Shape ``(n_paths, len(returns))``."""
    n = returns.size
    idx = rng.integers(0, n, size=(n_paths, n))
    return returns[idx]


def block_bootstrap_paths(
    returns: np.ndarray, n_paths: int, block_size: int, rng: np.random.Generator
) -> np.ndarray:
    """Circular block bootstrap. Resamples contiguous wrap-around blocks of
    ``block_size`` to preserve short-horizon autocorrelation."""
    n = returns.size
    if block_size < 1:
        raise ValueError("block_size must be >= 1")
    block_size = min(block_size, n)
    n_blocks = int(np.ceil(n / block_size))
    paths = np.empty((n_paths, n), dtype=float)
    extended = np.concatenate([returns, returns[: block_size - 1]]) if block_size > 1 else returns
    for p in range(n_paths):
        starts = rng.integers(0, n, size=n_blocks)
        chunks = [extended[s : s + block_size] for s in starts]
        path = np.concatenate(chunks)[:n]
        paths[p] = path
    return paths


def gaussian_paths(returns: np.ndarray, n_paths: int, rng: np.random.Generator) -> np.ndarray:
    """Simulate normal paths matching the sample mean and standard deviation."""
    mu = float(np.mean(returns))
    sigma = float(np.std(returns, ddof=1)) if returns.size > 1 else 0.0
    return rng.normal(mu, sigma, size=(n_paths, returns.size))


def monte_carlo_analysis(
    returns: pd.Series | np.ndarray,
    n_sims: int = 1000,
    method: str = "block",
    block_size: int = 20,
    periods_per_year: int = 252,
    seed: int = 42,
) -> MonteCarloResult:
    """Run a Monte Carlo robustness analysis on a return series.

    Returns a :class:`MonteCarloResult` holding the per-path terminal wealth
    (starting from 1.0), maximum drawdown and annualised Sharpe.
    """
    arr = _clean(returns)
    if arr.size < 2:
        raise ValueError("need at least 2 finite returns for Monte Carlo")
    if n_sims < 1:
        raise ValueError("n_sims must be >= 1")
    rng = np.random.default_rng(seed)

    if method == "iid":
        paths = iid_bootstrap_paths(arr, n_sims, rng)
    elif method == "block":
        paths = block_bootstrap_paths(arr, n_sims, block_size, rng)
    elif method == "gaussian":
        paths = gaussian_paths(arr, n_sims, rng)
    else:
        raise ValueError(f"unknown method {method!r}; use 'iid', 'block' or 'gaussian'")

    terminal = np.empty(n_sims, dtype=float)
    mdd = np.empty(n_sims, dtype=float)
    sharpe = np.empty(n_sims, dtype=float)
    for i in range(n_sims):
        path = paths[i]
        equity = np.cumprod(1.0 + path)
        terminal[i] = equity[-1]
        mdd[i] = max_drawdown(pd.Series(equity))
        sharpe[i] = sharpe_ratio(path, periods_per_year)

    return MonteCarloResult(
        method=method,
        n_sims=n_sims,
        terminal_wealth=terminal,
        max_drawdown=mdd,
        sharpe=sharpe,
    )
