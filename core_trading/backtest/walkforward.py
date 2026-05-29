"""Walk-forward optimisation and CPCV distribution-of-Sharpe (master plan 3.5, 3.6).

Two anti-overfitting validation drivers that wrap the engine:

* :func:`walk_forward` -- split the timeline into sequential train/test folds
  (anchored or rolling), pick the best parameter set in-sample on each fold, then
  score it out-of-sample. A strategy whose best parameters jump around fold to
  fold is overfit; :attr:`WalkForwardResult.parameter_stability` quantifies that.

* :func:`cpcv_sharpe_distribution` -- run the strategy over every combinatorial
  purged test set (de Prado CPCV, reusing
  :class:`core_trading.research.cross_validation.CombinatorialPurgedCV`) to obtain
  a *distribution* of out-of-sample Sharpe ratios rather than one fragile number.

Both restrict the price panel to a fold's timestamps and run the engine
(vectorised by default for speed) on that slice.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from core_trading.backtest.engine import BacktestConfig, BacktestEngine, Strategy
from core_trading.backtest.metrics import sharpe_ratio
from core_trading.research.cross_validation import CombinatorialPurgedCV, WalkForwardSplit

__all__ = [
    "FoldResult",
    "WalkForwardResult",
    "walk_forward",
    "cpcv_sharpe_distribution",
]

StrategyBuilder = Callable[[dict[str, object]], Strategy]


@dataclass(frozen=True)
class FoldResult:
    """One walk-forward fold: the chosen params and in/out-of-sample Sharpe."""

    fold: int
    best_params: dict[str, object]
    train_sharpe: float
    test_sharpe: float
    n_train: int
    n_test: int


@dataclass
class WalkForwardResult:
    """Aggregate walk-forward outcome."""

    folds: list[FoldResult] = field(default_factory=list)
    oos_equity: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    parameter_stability: dict[str, float] = field(default_factory=dict)

    @property
    def mean_test_sharpe(self) -> float:
        if not self.folds:
            return 0.0
        return float(np.mean([f.test_sharpe for f in self.folds]))

    @property
    def degradation(self) -> float:
        """Mean in-sample minus out-of-sample Sharpe; large => overfit."""
        if not self.folds:
            return 0.0
        return float(np.mean([f.train_sharpe - f.test_sharpe for f in self.folds]))


def _timeline(prices: pd.DataFrame) -> pd.DatetimeIndex:
    ts = prices.index.get_level_values("timestamp").unique()
    return pd.DatetimeIndex(ts).sort_values()


def _slice(prices: pd.DataFrame, timestamps: Sequence[pd.Timestamp]) -> pd.DataFrame:
    mask = prices.index.get_level_values("timestamp").isin(timestamps)
    return prices.loc[mask]


def _run_sharpe(
    engine: BacktestEngine,
    prices: pd.DataFrame,
    strategy: Strategy,
    mode: str,
    periods_per_year: int,
) -> float:
    result = engine.run(prices, strategy, mode=mode)
    return sharpe_ratio(result.returns, periods_per_year)


def walk_forward(
    prices: pd.DataFrame,
    build_strategy: StrategyBuilder,
    param_grid: Sequence[dict[str, object]],
    n_splits: int = 5,
    test_size: int | None = None,
    train_size: int | None = None,
    anchored: bool = True,
    config: BacktestConfig | None = None,
    mode: str = "vectorised",
    periods_per_year: int = 252,
) -> WalkForwardResult:
    """Anchored or rolling walk-forward parameter selection.

    For each fold the parameter set with the highest in-sample Sharpe is chosen
    and scored out-of-sample. Rolling (``anchored=False``) requires
    ``train_size``. Returns a :class:`WalkForwardResult`.
    """
    if not param_grid:
        raise ValueError("param_grid must be non-empty")
    engine = BacktestEngine(config)
    timeline = _timeline(prices)
    n = len(timeline)
    splitter = WalkForwardSplit(
        n_splits=n_splits, test_size=test_size, train_size=train_size, anchored=anchored
    )

    folds: list[FoldResult] = []
    oos_segments: list[pd.Series] = []
    chosen: list[dict[str, object]] = []
    dummy = np.arange(n)
    for fold_i, split in enumerate(splitter.split(dummy)):
        train_ts = timeline[split.train_indices]
        test_ts = timeline[split.test_indices]
        train_prices = _slice(prices, train_ts)
        test_prices = _slice(prices, test_ts)

        best_params: dict[str, object] | None = None
        best_sharpe = -np.inf
        for params in param_grid:
            strat = build_strategy(dict(params))
            s = _run_sharpe(engine, train_prices, strat, mode, periods_per_year)
            if s > best_sharpe:
                best_sharpe = s
                best_params = dict(params)
        assert best_params is not None

        test_strat = build_strategy(dict(best_params))
        test_result = engine.run(test_prices, test_strat, mode=mode)
        test_sharpe = sharpe_ratio(test_result.returns, periods_per_year)
        folds.append(
            FoldResult(
                fold=fold_i,
                best_params=best_params,
                train_sharpe=float(best_sharpe),
                test_sharpe=test_sharpe,
                n_train=len(train_ts),
                n_test=len(test_ts),
            )
        )
        chosen.append(best_params)
        oos_segments.append(test_result.equity)

    oos_equity = pd.concat(oos_segments) if oos_segments else pd.Series(dtype=float)
    oos_equity = oos_equity[~oos_equity.index.duplicated(keep="first")].sort_index()
    return WalkForwardResult(
        folds=folds,
        oos_equity=oos_equity,
        parameter_stability=_parameter_stability(chosen),
    )


def _parameter_stability(chosen: list[dict[str, object]]) -> dict[str, float]:
    """For each parameter, the fraction of folds using its most-common value.

    1.0 means the same value won every fold (stable); near 1/n_folds means the
    choice is essentially random (overfit)."""
    if not chosen:
        return {}
    keys = chosen[0].keys()
    stability: dict[str, float] = {}
    n = len(chosen)
    for key in keys:
        values = [repr(c.get(key)) for c in chosen]
        modal_count = Counter(values).most_common(1)[0][1]
        stability[key] = modal_count / n
    return stability


def cpcv_sharpe_distribution(
    prices: pd.DataFrame,
    strategy: Strategy,
    n_groups: int = 6,
    n_test_groups: int = 2,
    embargo_pct: float = 0.0,
    config: BacktestConfig | None = None,
    mode: str = "vectorised",
    periods_per_year: int = 252,
) -> np.ndarray:
    """Distribution of out-of-sample Sharpe over all CPCV test combinations.

    Returns an array of Sharpe ratios, one per combinatorial test set. A single
    train-test Sharpe is fiction; this is its sampling distribution.
    """
    engine = BacktestEngine(config)
    timeline = _timeline(prices)
    n = len(timeline)
    cpcv = CombinatorialPurgedCV(
        n_groups=n_groups, n_test_groups=n_test_groups, embargo_pct=embargo_pct
    )
    dummy = np.arange(n)
    sharpes: list[float] = []
    for split in cpcv.split(dummy):
        test_ts = timeline[split.test_indices]
        test_prices = _slice(prices, test_ts)
        result = engine.run(test_prices, strategy, mode=mode)
        sharpes.append(sharpe_ratio(result.returns, periods_per_year))
    return np.asarray(sharpes, dtype=float)
