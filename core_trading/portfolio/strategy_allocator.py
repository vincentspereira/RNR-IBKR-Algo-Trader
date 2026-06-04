"""Multi-strategy capital allocation (Phase 6.6).

Splits the book's capital across STRATEGIES (the pairs vertical, momentum
sleeves, future Phase 5 signal portfolios...) rather than across assets.
Three allocation methods, in increasing order of how much live evidence
they consume, plus the master plan's decommission rule:

1. ``"equal"`` -- 1/K per strategy.  The right answer when live track
   records are too short to differentiate (DeMiguel, Garlappi & Uppal 2009
   show how hard 1/N is to beat after estimation error).
2. ``"risk_parity"`` -- equal risk contribution across the strategies'
   live return covariance (Ledoit-Wolf shrunk), via
   :func:`core_trading.portfolio.risk_parity.risk_parity_weights`.
   Falls back to equal weight until every strategy has ``min_history``
   overlapping observations.
3. ``"bayesian"`` -- weights proportional to the POSTERIOR expected
   Sharpe ratio of each strategy under a conjugate-style shrinkage
   towards a common prior (Jones & Shanken 2005: learning across funds):

       sharpe_post_k = (n0 * sharpe_prior + T_k * sharpe_hat_k) / (n0 + T_k)

   where n0 is the prior strength in pseudo-observations and T_k the live
   sample size.  Young strategies are pulled towards the prior; seasoned
   ones earn their own estimate.  Negative-posterior strategies score 0;
   if every posterior is <= 0 the allocator falls back to equal weight
   (no positive conviction anywhere -> diversify, do not concentrate).

Decommission rule (master plan, Phase 6.6): any strategy whose LIVE
Sharpe over the trailing ``decommission_window`` bars (default 60) is
below ``decommission_sharpe`` (default 0) has its weight multiplied by
``decommission_factor`` (default 0.5 -- "halve"), after which weights are
renormalised: the freed capital migrates to the healthy strategies.

The returns panel may contain LEADING NaN per column (a strategy that
went live later); interior gaps raise.

:func:`combine_strategy_weights` is the glue to the Phase 4 pairs
vertical: it nets per-strategy ASSET weight vectors (e.g. the output of
:func:`core_trading.portfolio.pairs_portfolio.construct_pairs_portfolio`)
into one tradeable book, scaled by the capital allocation.

Mathematical references
-----------------------
  * DeMiguel, V., Garlappi, L. & Uppal, R. (2009). "Optimal Versus Naive
    Diversification: How Inefficient is the 1/N Portfolio Strategy?"
    Review of Financial Studies, 22(5), 1915-1953.
  * Roncalli, T. (2013). "Introduction to Risk Parity and Budgeting."
    Chapman & Hall/CRC.  (Risk parity across strategies, Ch. 6.)
  * Jones, C.S. & Shanken, J. (2005). "Mutual Fund Performance with
    Learning Across Funds." Journal of Financial Economics, 78(3),
    507-552.  (Shrinkage of performance estimates towards a common prior.)
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from core_trading.portfolio.covariance import ledoit_wolf_covariance
from core_trading.portfolio.risk_parity import risk_parity_weights

__all__ = [
    "StrategyAllocation",
    "StrategyAllocatorConfig",
    "allocate_strategies",
    "combine_strategy_weights",
]

_ALLOWED_METHODS = ("equal", "risk_parity", "bayesian")


# ---------------------------------------------------------------------------
# Configuration / result DTOs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StrategyAllocatorConfig:
    """Parameters for the multi-strategy allocator.

    Attributes
    ----------
    method:
        ``"equal"``, ``"risk_parity"`` or ``"bayesian"`` (see module
        docstring).
    lookback:
        Maximum trailing window (bars) of live returns consumed by the
        risk-parity covariance and the Bayesian Sharpe estimates.
    min_history:
        Minimum number of OVERLAPPING observations (across all
        strategies) required before risk parity activates; below it the
        allocator falls back to equal weight.
    decommission_window:
        Trailing window (bars) for the live-Sharpe decommission check.
    decommission_sharpe:
        Sharpe threshold (per bar, not annualised -- the comparison is
        scale-free at the default 0): strictly below it triggers the
        haircut.
    decommission_factor:
        Multiplier applied to a decommissioned strategy's weight, in
        (0, 1].  Master plan default: 0.5.
    bayesian_prior_sharpe:
        Prior mean PER-BAR Sharpe for the Bayesian method.
    bayesian_prior_strength:
        Prior pseudo-observations n0 > 0; larger = slower to trust live
        track records.
    """

    method: str = "risk_parity"
    lookback: int = 252
    min_history: int = 20
    decommission_window: int = 60
    decommission_sharpe: float = 0.0
    decommission_factor: float = 0.5
    bayesian_prior_sharpe: float = 0.0
    bayesian_prior_strength: float = 60.0

    def __post_init__(self) -> None:
        """Validate parameter consistency."""
        if self.method not in _ALLOWED_METHODS:
            raise ValueError(
                f"method must be one of {_ALLOWED_METHODS}, got {self.method!r}"
            )
        if self.lookback < 2:
            raise ValueError(f"lookback must be >= 2, got {self.lookback}")
        if not 2 <= self.min_history <= self.lookback:
            raise ValueError(
                f"min_history must be in [2, lookback={self.lookback}], "
                f"got {self.min_history}"
            )
        if self.decommission_window < 2:
            raise ValueError(
                f"decommission_window must be >= 2, got {self.decommission_window}"
            )
        if not np.isfinite(self.decommission_sharpe):
            raise ValueError(
                f"decommission_sharpe must be finite, got {self.decommission_sharpe}"
            )
        if not 0.0 < self.decommission_factor <= 1.0:
            raise ValueError(
                f"decommission_factor must be in (0, 1], got {self.decommission_factor}"
            )
        if not np.isfinite(self.bayesian_prior_sharpe):
            raise ValueError(
                f"bayesian_prior_sharpe must be finite, "
                f"got {self.bayesian_prior_sharpe}"
            )
        if (
            not np.isfinite(self.bayesian_prior_strength)
            or self.bayesian_prior_strength <= 0.0
        ):
            raise ValueError(
                f"bayesian_prior_strength must be a finite positive float, "
                f"got {self.bayesian_prior_strength}"
            )


@dataclass(frozen=True, slots=True)
class StrategyAllocation:
    """Capital split across strategies.

    Attributes
    ----------
    weights:
        Capital fraction per strategy: strictly positive, sums to 1.
    method_used:
        The method that actually produced the base weights -- equals the
        configured method, or ``"equal_fallback"`` when risk parity
        lacked ``min_history`` overlapping bars, or the Bayesian
        posterior had no positive conviction.
    decommissioned:
        Strategies whose weight was haircut by the live-Sharpe rule, in
        panel column order.
    live_sharpes:
        Per-bar Sharpe over the trailing decommission window per
        strategy; NaN where live history is shorter than the window.
    """

    weights: pd.Series = field(compare=False)
    method_used: str
    decommissioned: tuple[str, ...]
    live_sharpes: pd.Series = field(compare=False)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_returns(returns: pd.DataFrame) -> pd.DataFrame:
    """Validate the live strategy-returns panel (leading NaN allowed)."""
    if returns.shape[1] < 1:
        raise ValueError("returns panel must have at least 1 strategy column.")
    if returns.shape[0] < 2:
        raise ValueError(
            f"returns panel must have at least 2 rows; got {returns.shape[0]}."
        )
    for col in returns.columns:
        series = returns[col]
        first_valid = series.first_valid_index()
        if first_valid is None:
            raise ValueError(f"strategy {col!r} has no valid observations.")
        live = series.loc[first_valid:]
        if bool(live.isnull().any()):
            raise ValueError(
                f"strategy {col!r} has interior NaN gaps; only LEADING NaN "
                "(pre-launch) is permitted."
            )
        if not np.isfinite(live.to_numpy(dtype=float)).all():
            raise ValueError(f"strategy {col!r} contains infinite values.")
    return returns


def _trailing_sharpe(live: np.ndarray) -> float:
    """Per-bar Sharpe of a return sample; signed inf on zero dispersion."""
    mean = float(live.mean())
    std = float(live.std(ddof=1))
    if std <= 0.0:
        if mean == 0.0:
            return 0.0
        return float(np.inf) if mean > 0.0 else float(-np.inf)
    return mean / std


def _live_sharpes(
    returns: pd.DataFrame, window: int
) -> pd.Series:
    """Trailing-window per-bar Sharpe per strategy (NaN if too young)."""
    values: list[float] = []
    for col in returns.columns:
        live = returns[col].dropna().to_numpy(dtype=float)
        if live.shape[0] < window:
            values.append(float("nan"))
        else:
            values.append(_trailing_sharpe(live[-window:]))
    return pd.Series(values, index=returns.columns, dtype=float)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def allocate_strategies(
    returns: pd.DataFrame,
    config: StrategyAllocatorConfig | None = None,
) -> StrategyAllocation:
    """Split capital across strategies from their live return panel.

    See the module docstring for the three methods and the decommission
    rule.  Output weights are strictly positive and sum to exactly 1.

    Parameters
    ----------
    returns:
        Live per-strategy returns: rows = bars (ascending), columns =
        strategy names.  Leading NaN per column marks the pre-launch
        period; interior NaN raises.
    config:
        :class:`StrategyAllocatorConfig`; ``None`` uses the defaults
        (risk parity).

    Returns
    -------
    StrategyAllocation

    Raises
    ------
    ValueError
        On an invalid panel or configuration.
    """
    cfg = config if config is not None else StrategyAllocatorConfig()
    panel = _validate_returns(returns)
    strategies = [str(c) for c in panel.columns]
    n_strategies = len(strategies)

    # ----- base weights by method ----------------------------------------
    method_used = cfg.method
    if n_strategies == 1:
        base = np.array([1.0])
        method_used = "equal" if cfg.method == "equal" else "equal_fallback"
    elif cfg.method == "equal":
        base = np.full(n_strategies, 1.0 / n_strategies)
    elif cfg.method == "risk_parity":
        # Overlapping window: every strategy must be live.
        overlap = panel.dropna()
        window = min(overlap.shape[0], cfg.lookback)
        if window < cfg.min_history:
            base = np.full(n_strategies, 1.0 / n_strategies)
            method_used = "equal_fallback"
        else:
            tail = overlap.iloc[-window:]
            cov = ledoit_wolf_covariance(tail).covariance
            if float(np.trace(cov.to_numpy())) <= 0.0:
                # Every strategy's live history is constant: no risk
                # information at all -> diversify.  (For any panel with
                # positive total variance the Ledoit-Wolf estimate is
                # strictly PD -- delta * m * I with m > 0 -- so this is
                # the only degenerate case.)
                base = np.full(n_strategies, 1.0 / n_strategies)
                method_used = "equal_fallback"
            else:
                base = risk_parity_weights(cov).weights.to_numpy()
    else:  # "bayesian"
        scores = np.empty(n_strategies)
        for k, col in enumerate(panel.columns):
            live = panel[col].dropna().to_numpy(dtype=float)
            live = live[-cfg.lookback:]
            t_k = live.shape[0]
            sharpe_hat = _trailing_sharpe(live)
            if not np.isfinite(sharpe_hat):
                # Zero-dispersion degenerate stream: sign carries the info.
                sharpe_hat = float(np.sign(sharpe_hat))
            posterior = (
                cfg.bayesian_prior_strength * cfg.bayesian_prior_sharpe
                + float(t_k) * sharpe_hat
            ) / (cfg.bayesian_prior_strength + float(t_k))
            scores[k] = max(posterior, 0.0)
        total = float(scores.sum())
        if total <= 0.0:
            base = np.full(n_strategies, 1.0 / n_strategies)
            method_used = "equal_fallback"
        else:
            base = scores / total

    # ----- decommission rule ----------------------------------------------
    live_sharpes = _live_sharpes(panel, cfg.decommission_window)
    decommissioned: list[str] = []
    adjusted = base.copy()
    for k, col in enumerate(strategies):
        sharpe = live_sharpes.iloc[k]
        if np.isnan(sharpe):
            continue  # too young for the rule
        if float(sharpe) < cfg.decommission_sharpe:
            adjusted[k] *= cfg.decommission_factor
            decommissioned.append(col)

    weights = adjusted / float(adjusted.sum())
    return StrategyAllocation(
        weights=pd.Series(weights, index=strategies),
        method_used=method_used,
        decommissioned=tuple(decommissioned),
        live_sharpes=live_sharpes,
    )


def combine_strategy_weights(
    strategy_weights: Mapping[str, pd.Series],
    allocation: pd.Series,
) -> pd.Series:
    """Net per-strategy asset books into one tradeable weight vector.

    The Phase 4 integration glue: each strategy contributes an
    asset-level signed weight vector (for the pairs vertical, the
    ``weights`` of
    :func:`core_trading.portfolio.pairs_portfolio.construct_pairs_portfolio`
    wrapped in a Series); each is scaled by the strategy's capital share
    and overlapping symbols are NETTED:

        combined[asset] = sum_s allocation[s] * strategy_weights[s][asset]

    Parameters
    ----------
    strategy_weights:
        Strategy name -> asset weight Series (signed, in strategy NAV
        fractions).  Missing assets count as 0.
    allocation:
        Capital fraction per strategy (e.g.
        ``allocate_strategies(...).weights``); its index must contain
        exactly the keys of ``strategy_weights``.

    Returns
    -------
    pd.Series
        Combined signed asset weights in book-NAV fractions, indexed by
        symbol in sorted order.

    Raises
    ------
    ValueError
        On mismatched strategy sets or non-finite inputs.
    """
    if sorted(strategy_weights.keys()) != sorted(str(s) for s in allocation.index):
        raise ValueError(
            "allocation index must contain exactly the strategy_weights keys."
        )
    alloc_arr = allocation.to_numpy(dtype=float)
    if not np.isfinite(alloc_arr).all():
        raise ValueError("allocation contains NaN or infinite values.")

    symbols: set[str] = set()
    for name, book in strategy_weights.items():
        if not np.isfinite(book.to_numpy(dtype=float)).all():
            raise ValueError(
                f"strategy {name!r} weights contain NaN or infinite values."
            )
        symbols.update(str(s) for s in book.index)

    ordered = sorted(symbols)
    combined = pd.Series(0.0, index=ordered)
    for name in allocation.index:
        share = float(allocation[name])
        book = strategy_weights[str(name)]
        combined = combined.add(share * book.reindex(ordered, fill_value=0.0))
    return combined
