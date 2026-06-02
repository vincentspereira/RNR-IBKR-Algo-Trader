"""Phase 5 signal-evaluation adapter: PCA statistical arbitrage (residual reversion).

Wires the PCA statistical-factor module
(:mod:`~core_trading.signals.factors.pca_factors`, master plan 5.C.3) through the
evaluation gate (:mod:`~core_trading.research.signal_evaluation`) as a
cross-sectional, dollar-neutral long/short signal -- the Avellaneda-Lee (2010)
statistical-arbitrage construction.

Idea
----
At each rebalance bar a PCA is fitted on the trailing window of asset returns; the
systematic (common-factor) component is regressed out, leaving idiosyncratic
*residual* returns. The cumulative residual behaves like a mean-reverting
(Ornstein-Uhlenbeck) process around zero: an asset whose idiosyncratic component
has drifted high is "rich" and is expected to revert down (short it); one that has
drifted low is "cheap" and expected to revert up (long it). The standardised
cumulative residual is the Avellaneda-Lee **s-score**::

    s_{i,t} = (X_{i,t} - mean_w(X_i)) / std_w(X_i),   X_{i,t} = sum_{tau in w} e_{i,tau}

computed on the trailing window ``w`` ending at ``t``, so it is look-ahead-free.
The portfolio **longs the most negative s-scores and shorts the most positive**
(the reversion direction) -- the sign-flipped image of the momentum adapter,
reusing the same dollar-neutral long/short construction.

Compute-once / sweep-cheap
--------------------------
The expensive rolling PCA + residual + s-score path is computed *once* in
:func:`build_pca_statarb_weight_fn`; the returned :data:`WeightRule` only applies
the cheap long/short construction at a given ``quantile``, so a sweep over
:func:`pca_statarb_grid` reuses the single computed s-score panel. The PCA
loadings are refreshed every ``refit_every`` bars and the s-score row is carried
(a stale *past* estimate) between refits, mirroring the OU / trend adapters.

Mathematical references
-----------------------
* Avellaneda, M. & Lee, J.H. (2010). "Statistical Arbitrage in the US Equities
  Market." Quantitative Finance 10(7), 761-782 (eigenportfolios + the s-score).
* Deflated Sharpe gate: Bailey, D. & Lopez de Prado, M. (2014), as applied by
  :mod:`~core_trading.research.signal_evaluation`.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd

from core_trading.research.signal_evaluation import WeightRule
from core_trading.signals.factors.momentum import long_short_weights
from core_trading.signals.factors.pca_factors import fit_pca_factors, residual_returns

__all__ = [
    "pca_sscore_panel",
    "residual_reversion_weights",
    "build_pca_statarb_weight_fn",
    "pca_statarb_grid",
]


# ---------------------------------------------------------------------------
# Step 1 -- look-ahead-free s-score panel (the expensive path)
# ---------------------------------------------------------------------------


def pca_sscore_panel(
    prices: pd.DataFrame,
    *,
    n_factors: int,
    lookback: int,
    refit_every: int = 5,
    standardize: bool = True,
) -> pd.DataFrame:
    """Look-ahead-free Avellaneda-Lee s-score panel from a wide price panel.

    At each refit bar ``t`` the PCA is fitted on the trailing return window
    ``returns[t - lookback + 1 : t + 1]``, the systematic component is regressed
    out, and the standardised cumulative residual gives one s-score per asset.
    Only data up to and including ``t`` enters the estimate, so the panel is
    look-ahead-free; between refits the last computed s-score row is carried.

    Parameters
    ----------
    prices:
        Wide price panel: ascending ``DatetimeIndex`` rows, one column per
        symbol, strictly positive values.
    n_factors:
        Number of PCA factors to remove (``1 <= n_factors <= n_assets``).
    lookback:
        Trailing window length in bars for the PCA fit. Must be ``>= n_assets``
        (the PCA fit requires at least as many observations as assets).
    refit_every:
        Re-fit the PCA every this many bars (``>= 1``); the s-score row is
        carried between refits.
    standardize:
        Forwarded to :func:`~core_trading.signals.factors.pca_factors.fit_pca_factors`
        (``True`` = correlation-matrix PCA, the Avellaneda-Lee choice).

    Returns
    -------
    pd.DataFrame
        s-score panel, same index and columns as ``prices``; NaN during the
        warmup and for any window that is not complete (contains NaN) or whose
        residual is degenerate.

    Raises
    ------
    ValueError
        If ``lookback < 2``, ``refit_every < 1``, or ``n_factors < 1``.
    """
    if lookback < 2:
        raise ValueError("lookback must be >= 2")
    if refit_every < 1:
        raise ValueError("refit_every must be >= 1")
    if n_factors < 1:
        raise ValueError("n_factors must be >= 1")

    columns = list(prices.columns)
    price_arr = np.asarray(prices.to_numpy(), dtype=float)
    n, n_assets = price_arr.shape

    # Look-ahead-free simple returns: ret[t] = price[t] / price[t-1] - 1.
    with np.errstate(divide="ignore", invalid="ignore"):
        returns = np.empty_like(price_arr)
        returns[0] = np.nan
        returns[1:] = price_arr[1:] / price_arr[:-1] - 1.0

    sscores = np.full((n, n_assets), np.nan, dtype=float)
    current = np.full(n_assets, np.nan, dtype=float)
    bars_since_fit = refit_every  # force a fit on the first eligible bar

    # The first usable window ends at t = lookback (window rows t-lookback+1..t
    # exclude the NaN return at row 0).
    for t in range(lookback, n):
        if bars_since_fit >= refit_every:
            window = returns[t - lookback + 1 : t + 1]  # (lookback, n_assets)
            if np.all(np.isfinite(window)):
                current = _window_sscore(window, columns, n_factors, standardize)
            else:
                current = np.full(n_assets, np.nan, dtype=float)
            bars_since_fit = 0
        else:
            bars_since_fit += 1
        sscores[t] = current

    return pd.DataFrame(sscores, index=prices.index, columns=prices.columns)


def _window_sscore(
    window: np.ndarray,
    columns: list[str],
    n_factors: int,
    standardize: bool,
) -> np.ndarray:
    """s-score for each asset from one complete return window (the last bar)."""
    frame = pd.DataFrame(window, columns=columns)
    result = fit_pca_factors(frame, n_factors=n_factors, standardize=standardize)
    residuals = residual_returns(frame, result).to_numpy()  # (lookback, n_assets)
    cum = np.cumsum(residuals, axis=0)  # (lookback, n_assets)
    mean = cum.mean(axis=0)
    std = cum.std(axis=0, ddof=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.asarray(
            np.where(std > 0.0, (cum[-1] - mean) / std, np.nan), dtype=float
        )


# ---------------------------------------------------------------------------
# Step 2 -- dollar-neutral reversion long/short (cheap, swept by the grid)
# ---------------------------------------------------------------------------


def residual_reversion_weights(sscores: pd.DataFrame, *, quantile: float = 0.2) -> pd.DataFrame:
    """Dollar-neutral long/short weights that trade *against* the s-score.

    Reversion direction: long the bottom ``quantile`` of s-scores (idiosyncratically
    cheap, expected to revert up) and short the top ``quantile`` (rich, expected to
    revert down). Implemented by feeding the negated s-scores to
    :func:`~core_trading.signals.factors.momentum.long_short_weights` (which longs
    its top quantile), so the most negative s-scores become the long leg.
    """
    return long_short_weights(-sscores, quantile=quantile)


# ---------------------------------------------------------------------------
# Step 3 -- weight-rule factory (computes s-scores once, sweeps quantile)
# ---------------------------------------------------------------------------


def build_pca_statarb_weight_fn(
    prices: pd.DataFrame,
    *,
    n_factors: int,
    lookback: int,
    refit_every: int = 5,
    standardize: bool = True,
) -> WeightRule:
    """Build a :data:`WeightRule` for PCA residual-reversion statistical arbitrage.

    The expensive look-ahead-free s-score panel is computed *once* here; the
    returned rule only applies the cheap reversion long/short from ``params``, so
    a sweep over the long/short ``quantile`` -- as fed to
    :func:`~core_trading.research.signal_evaluation.evaluate_signal` -- reuses the
    single computed s-score panel. Each configuration must supply ``"quantile"``.

    Parameters
    ----------
    prices:
        Wide price panel used to compute the s-scores; the same frame must back
        the OHLCV panel passed to the gate (see
        :func:`~core_trading.research.signal_evaluation.price_panel_from_frame`).
    n_factors, lookback, refit_every, standardize:
        Forwarded to :func:`pca_sscore_panel`.

    Returns
    -------
    WeightRule
        A ``(panel, params) -> weights`` callable. ``params`` must contain the
        key ``"quantile"`` (float in ``(0, 1)``).
    """
    s = pca_sscore_panel(
        prices,
        n_factors=n_factors,
        lookback=lookback,
        refit_every=refit_every,
        standardize=standardize,
    )

    def weight_rule(panel: pd.DataFrame, params: Mapping[str, float]) -> pd.DataFrame:
        weights = residual_reversion_weights(s, quantile=float(params["quantile"]))
        # Defensively reindex onto the panel's own (sorted, unique) timestamp
        # index -- same chronological rows in the same order as the s-score
        # panel, so a positional reindex is correct and prevents a silent
        # all-zero misalignment when the engine reindexes the weights.
        ts_index = panel.index.get_level_values("timestamp").unique().sort_values()
        if len(ts_index) == len(weights):
            weights = pd.DataFrame(
                weights.to_numpy(), index=ts_index, columns=weights.columns
            )
        return weights

    return weight_rule


# ---------------------------------------------------------------------------
# Step 4 -- parameter grid
# ---------------------------------------------------------------------------


def pca_statarb_grid(
    *,
    quantiles: Sequence[float] = (0.1, 0.2, 0.3, 0.4),
) -> list[dict[str, float]]:
    """Standard long/short quantile grid for the PCA stat-arb sweep.

    Parameters
    ----------
    quantiles:
        Long/short leg fractions to evaluate. Must contain >= 1 element; the
        default (0.1, 0.2, 0.3, 0.4) gives 4 trials, enough for a meaningful
        deflated-Sharpe discount.

    Returns
    -------
    list[dict[str, float]]
        One configuration dict per quantile.
    """
    return [{"quantile": float(q)} for q in quantiles]
