"""Phase 5 signal-evaluation harness (closes the per-signal DOD loop).

The Phase 5 "Definition of Done" requires that each signal module is not only
unit-validated against a textbook example but also (a) run through the standard
backtest framework, (b) scored with a deflated Sharpe, and (c) either promoted to
paper trading or archived with a rejection memo. Batches 1-2 satisfied the
unit-validation half; this module supplies the evaluation half, reusably, for any
signal that can be expressed as a position rule.

How it works
------------
A signal is turned into a **weight rule** -- a callable that maps the price panel
and a parameter configuration to the engine's target-weight frame. The caller
supplies the *grid* of configurations that were tried. The harness:

1. runs every configuration through :class:`~core_trading.backtest.engine.BacktestEngine`
   (vectorised) and records each one's per-period Sharpe -- the *trials*;
2. takes the best configuration, optionally checks that the vectorised and
   event-driven engine modes agree (a look-ahead / accounting sanity check);
3. computes the **deflated Sharpe ratio** of the best configuration's returns
   against the expected maximum Sharpe of ``len(grid)`` trials, so the verdict is
   honest about selection bias; and
4. returns a PROMOTE / ARCHIVE verdict with a human-readable memo.

Trying ``N`` configurations inflates the best in-sample Sharpe purely by chance;
the deflated Sharpe (Bailey & de Prado 2014) discounts exactly that inflation, so
a genuinely skilful signal clears the bar while an overfit one does not. The
harness is data-source-agnostic: pass a real Phase 1 price panel when one is
available, or a simulated textbook series (genuine Ornstein-Uhlenbeck vs a random
walk) to validate that the gate accepts skill and rejects noise.

A high deflated Sharpe here is *necessary but not sufficient* for live promotion:
the conventional pipeline still requires the real-data backtest and the paper
trading run (master plan Phase 4.9 / Phase 11), both of which are gated on Phase 1
data and wall-clock time. This harness closes the in-framework evaluation; it does
not bypass those operational gates.

Layering
--------
This module orchestrates :mod:`core_trading.backtest` (engine) and
:mod:`core_trading.research.overfitting` (deflated Sharpe). The backtest engine is
imported lazily inside the functions, so importing this module stays cheap and
there is no module-load coupling. It is intentionally *not* re-exported from
``core_trading.research.__init__`` -- import it by its submodule path.

Mathematical references
-----------------------
* Bailey, D. & Lopez de Prado, M. (2014). "The Deflated Sharpe Ratio: Correcting
  for Selection Bias, Backtest Overfitting, and Non-Normality." Journal of
  Portfolio Management 40(5).
* Lopez de Prado, M. (2018). "Advances in Financial Machine Learning", ch. 8
  (the backtest overfitting framework).
* Ornstein-Uhlenbeck mean-reversion trading rule: see
  :mod:`core_trading.signals.stochastic.ou` and master plan Phase 4.3.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from core_trading.research.overfitting import (
    DeflatedSharpeResult,
    deflated_sharpe_ratio,
    sharpe_ratio,
)
from core_trading.signals.stochastic.ou import fit_ou_ols

if TYPE_CHECKING:
    from core_trading.backtest.engine import BacktestConfig

__all__ = [
    "SignalEvaluation",
    "price_panel_from_series",
    "price_panel_from_frame",
    "evaluate_signal",
    "ou_zscore_series",
    "mean_reversion_positions",
    "positions_to_weights",
    "build_mean_reversion_weight_fn",
    "mean_reversion_grid",
]

# A weight rule maps (price panel, parameter configuration) -> target weights.
WeightRule = Callable[[pd.DataFrame, Mapping[str, float]], pd.DataFrame]

_OHLCV = ("open", "high", "low", "close", "volume")


# ---------------------------------------------------------------------------
# Result DTO
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SignalEvaluation:
    """Outcome of running a signal through the backtest + deflated-Sharpe gate.

    Attributes
    ----------
    signal_name:
        Human label for the signal under test.
    verdict:
        ``"PROMOTE"`` if the deflated Sharpe exceeds ``promote_threshold``,
        otherwise ``"ARCHIVE"``.
    n_trials:
        Number of parameter configurations evaluated (the selection-bias count
        fed to the deflated Sharpe).
    best_params:
        The configuration with the highest in-sample per-period Sharpe.
    observed_sharpe_annualised:
        Annualised Sharpe of the best configuration's active (non-flat) returns,
        for human reporting only.
    deflated:
        Full :class:`~core_trading.research.overfitting.DeflatedSharpeResult` for
        the best configuration, or ``None`` when the best configuration produced
        fewer than two active return observations (no tradeable signal).
    modes_agree:
        Whether the vectorised and event-driven engine modes agreed to within
        1bp of initial equity on the best configuration (``True`` when the mode
        check was skipped).
    memo:
        Plain-ASCII rationale, suitable to drop into a rejection / promotion log.
    """

    signal_name: str
    verdict: str
    n_trials: int
    best_params: dict[str, float]
    observed_sharpe_annualised: float
    deflated: DeflatedSharpeResult | None
    modes_agree: bool
    memo: str = field(compare=False)

    @property
    def is_promoted(self) -> bool:
        """True when the verdict is PROMOTE."""
        return self.verdict == "PROMOTE"


# ---------------------------------------------------------------------------
# Price-panel helper
# ---------------------------------------------------------------------------


def price_panel_from_series(
    close: pd.Series,
    *,
    symbol: str = "SIM",
    volume: float = 1_000_000.0,
) -> pd.DataFrame:
    """Wrap a single close-price series in the engine's OHLCV panel format.

    The backtest engine expects a ``(symbol, timestamp)`` MultiIndex frame with
    ``open/high/low/close/volume`` columns. For a single instrument with no
    intrabar information we set open = high = low = close, which leaves the
    vectorised and event-driven modes in exact agreement under a frictionless
    cost model (both fill at the close).

    Parameters
    ----------
    close:
        Close prices. The index becomes the timestamp level; if it is not a
        ``DatetimeIndex`` a business-day calendar is synthesised so the engine's
        period accounting is well-defined.
    symbol:
        Symbol label for the single column.
    volume:
        Constant per-bar volume (large enough to avoid participation throttling).

    Returns
    -------
    pd.DataFrame
        OHLCV panel indexed by ``["symbol", "timestamp"]``.

    Raises
    ------
    ValueError
        If fewer than two prices are supplied or any price is non-positive.
    """
    prices = np.asarray(close.to_numpy(), dtype=float)
    if prices.size < 2:
        raise ValueError("price_panel_from_series needs at least 2 prices")
    if not np.all(np.isfinite(prices)) or np.any(prices <= 0.0):
        raise ValueError("prices must be finite and strictly positive")

    if isinstance(close.index, pd.DatetimeIndex):
        timestamps = close.index
    else:
        timestamps = pd.date_range("2000-01-03", periods=prices.size, freq="B", tz="UTC")

    return pd.DataFrame(
        {
            "open": prices,
            "high": prices,
            "low": prices,
            "close": prices,
            "volume": np.full(prices.size, float(volume)),
        },
        index=pd.MultiIndex.from_product([[symbol], timestamps], names=["symbol", "timestamp"]),
    )


def price_panel_from_frame(
    prices: pd.DataFrame,
    *,
    volume: float = 1_000_000.0,
) -> pd.DataFrame:
    """Wrap a wide multi-asset close-price frame in the engine's OHLCV panel.

    The cross-sectional analogue of :func:`price_panel_from_series`, for signals
    that trade a whole cross-section (e.g. a dollar-neutral long/short factor).
    ``prices`` is a *wide* frame -- one row per bar, one column per symbol -- and
    each symbol's open/high/low/close are set equal to its close, so the
    vectorised and event-driven engine modes agree exactly under a frictionless
    cost model.

    Parameters
    ----------
    prices:
        Wide price frame: ascending index of timestamps, one column per symbol.
        If the index is not a ``DatetimeIndex`` a business-day calendar is
        synthesised. Every value must be finite and strictly positive (the gate
        path requires a complete panel; the underlying factor functions tolerate
        NaN for general use, but the engine does not price missing assets here).
    volume:
        Constant per-bar volume for every symbol.

    Returns
    -------
    pd.DataFrame
        OHLCV panel indexed by ``["symbol", "timestamp"]`` across all symbols.

    Raises
    ------
    ValueError
        If there are fewer than two rows or one column, or any price is not
        finite and strictly positive.
    """
    if prices.shape[0] < 2:
        raise ValueError("price_panel_from_frame needs at least 2 timestamps")
    if prices.shape[1] < 1:
        raise ValueError("price_panel_from_frame needs at least 1 symbol")
    values = np.asarray(prices.to_numpy(), dtype=float)
    if not np.all(np.isfinite(values)) or np.any(values <= 0.0):
        raise ValueError("prices must be finite and strictly positive")

    if isinstance(prices.index, pd.DatetimeIndex):
        timestamps = prices.index
    else:
        timestamps = pd.date_range("2000-01-03", periods=prices.shape[0], freq="B", tz="UTC")

    frames = []
    for column in prices.columns:
        series = np.asarray(prices[column].to_numpy(), dtype=float)
        frames.append(
            pd.DataFrame(
                {
                    "open": series,
                    "high": series,
                    "low": series,
                    "close": series,
                    "volume": np.full(series.size, float(volume)),
                },
                index=pd.MultiIndex.from_product(
                    [[str(column)], timestamps], names=["symbol", "timestamp"]
                ),
            )
        )
    return pd.concat(frames)


# ---------------------------------------------------------------------------
# Generic evaluation runner
# ---------------------------------------------------------------------------


def _annualised(returns: pd.Series, periods_per_year: int) -> float:
    active = returns[returns != 0.0]
    if active.size < 2:
        return 0.0
    return sharpe_ratio(active, periods_per_year=periods_per_year, annualised=True)


def _per_period(returns: pd.Series) -> float:
    active = returns[returns != 0.0]
    if active.size < 2:
        return 0.0
    return sharpe_ratio(active, annualised=False)


def _build_memo(
    signal_name: str,
    verdict: str,
    n_trials: int,
    best_params: Mapping[str, float],
    observed_annualised: float,
    deflated: DeflatedSharpeResult | None,
    modes_agree: bool,
    promote_threshold: float,
) -> str:
    params_str = ", ".join(f"{k}={v:g}" for k, v in best_params.items()) or "(none)"
    lines = [
        f"Signal: {signal_name}",
        f"Verdict: {verdict}",
        f"Configurations tried (n_trials): {n_trials}",
        f"Best configuration: {params_str}",
        f"Observed annualised Sharpe (active bars): {observed_annualised:.3f}",
    ]
    if deflated is None:
        lines.append(
            "Deflated Sharpe: n/a -- the best configuration produced fewer than 2 "
            "active return observations (the rule never traded), so there is no "
            "performance to evaluate. Archived."
        )
    else:
        lines.append(
            f"Deflated Sharpe (vs expected max of {n_trials} trials): "
            f"{deflated.deflated_sharpe:.4f} "
            f"(threshold {promote_threshold:.2f}); "
            f"probabilistic Sharpe vs 0: {deflated.probabilistic_sharpe:.4f}; "
            f"expected-max trial Sharpe: {deflated.expected_max_sharpe:.4f}; "
            f"observations: {deflated.n_obs}."
        )
        if verdict == "PROMOTE":
            lines.append(
                "The deflated Sharpe clears the threshold: the edge survives the "
                "selection bias of trying every configuration. Eligible for the "
                "real-data backtest and paper-trading gate (Phase 1 / Phase 4.9)."
            )
        else:
            lines.append(
                "The deflated Sharpe is below the threshold: once discounted for "
                "having tried this many configurations, the result is not "
                "distinguishable from luck. Archived with this memo."
            )
    if not modes_agree:
        lines.append(
            "WARNING: vectorised and event-driven engine modes disagreed beyond "
            "1bp of initial equity -- investigate the weight rule for look-ahead "
            "or accounting issues before trusting this verdict."
        )
    return "\n".join(lines)


def evaluate_signal(
    panel: pd.DataFrame,
    weight_rule: WeightRule,
    param_grid: Sequence[Mapping[str, float]],
    *,
    signal_name: str,
    config: BacktestConfig | None = None,
    check_modes: bool = True,
    promote_threshold: float = 0.95,
    periods_per_year: int = 252,
) -> SignalEvaluation:
    """Run a signal's weight rule through the engine and the deflated-Sharpe gate.

    Parameters
    ----------
    panel:
        ``(symbol, timestamp)`` OHLCV price panel (see
        :func:`price_panel_from_series`).
    weight_rule:
        Callable mapping ``(panel, params)`` to a look-ahead-free target-weight
        frame. Look-ahead-freeness is the rule's responsibility; the engine earns
        bar ``t+1``'s return on the weight set at bar ``t``.
    param_grid:
        The parameter configurations that were tried. Its length is the
        ``n_trials`` fed to the deflated Sharpe; supplying the genuine search grid
        is what makes the verdict honest about selection bias.
    signal_name:
        Label for the result and memo.
    config:
        Optional ``BacktestConfig``; defaults to a frictionless (``"zero"`` cost)
        configuration so the two engine modes agree exactly.
    check_modes:
        When ``True`` (default) also runs the best configuration event-driven and
        records whether it agrees with the vectorised run.
    promote_threshold:
        Deflated-Sharpe cutoff for PROMOTE (default 0.95, the convention in
        :class:`~core_trading.research.overfitting.DeflatedSharpeResult`).
    periods_per_year:
        Annualisation factor for the reported Sharpe.

    Returns
    -------
    SignalEvaluation
        Verdict, deflated-Sharpe result, and a rejection / promotion memo.

    Raises
    ------
    ValueError
        If ``param_grid`` is empty.
    """
    if len(param_grid) == 0:
        raise ValueError("param_grid must contain at least one configuration")

    # Lazy import keeps this module cheap to import and avoids load-time coupling.
    from core_trading.backtest.engine import BacktestConfig, BacktestEngine, WeightStrategy

    cfg = config if config is not None else BacktestConfig(cost_model_name="zero")
    engine = BacktestEngine(cfg)

    trial_sharpes: list[float] = []
    per_config_returns: list[pd.Series] = []
    for params in param_grid:
        weights = weight_rule(panel, params)
        result = engine.run_vectorised(panel, WeightStrategy(weights))
        trial_sharpes.append(_per_period(result.returns))
        per_config_returns.append(result.returns)

    best_i = int(np.argmax(trial_sharpes))
    best_params = dict(param_grid[best_i])
    best_returns = per_config_returns[best_i]
    n_trials = len(param_grid)

    modes_agree = True
    if check_modes:
        weights = weight_rule(panel, param_grid[best_i])
        vec = engine.run_vectorised(panel, WeightStrategy(weights))
        evt = engine.run_event_driven(panel, WeightStrategy(weights))
        diff = (vec.equity - evt.equity).abs() / vec.initial_cash
        modes_agree = bool(diff.max() < 1e-4)

    active = best_returns[best_returns != 0.0]
    observed_annualised = _annualised(best_returns, periods_per_year)

    deflated: DeflatedSharpeResult | None
    if active.size < 2:
        deflated = None
        verdict = "ARCHIVE"
    else:
        if n_trials < 2:
            deflated = deflated_sharpe_ratio(active, n_trials=n_trials, trial_sharpe_std=0.0)
        else:
            deflated = deflated_sharpe_ratio(
                active, n_trials=n_trials, trial_sharpes=trial_sharpes
            )
        verdict = "PROMOTE" if deflated.deflated_sharpe > promote_threshold else "ARCHIVE"

    memo = _build_memo(
        signal_name,
        verdict,
        n_trials,
        best_params,
        observed_annualised,
        deflated,
        modes_agree,
        promote_threshold,
    )
    return SignalEvaluation(
        signal_name=signal_name,
        verdict=verdict,
        n_trials=n_trials,
        best_params=best_params,
        observed_sharpe_annualised=observed_annualised,
        deflated=deflated,
        modes_agree=modes_agree,
        memo=memo,
    )


# ---------------------------------------------------------------------------
# Ornstein-Uhlenbeck mean-reversion adapter (master plan 5.B.1 application)
# ---------------------------------------------------------------------------


def ou_zscore_series(
    close: pd.Series,
    *,
    lookback: int = 120,
    refit_every: int = 5,
) -> pd.DataFrame:
    """Look-ahead-free Ornstein-Uhlenbeck z-score and half-life of a price series.

    At each timestamp ``t`` (warmup permitting) the OU parameters are estimated
    from a trailing window ending at ``t`` via
    :func:`core_trading.signals.stochastic.ou.fit_ou_ols`. The z-score is the
    standardised deviation of the current price from the OU long-run mean::

        z_t = (x_t - mu_hat) / sigma_eq_hat

    where ``sigma_eq`` is the OU stationary standard deviation. Only data up to
    and including ``t`` enters the estimate, so the series is look-ahead-free. To
    keep the rolling estimation cheap the parameters are refreshed every
    ``refit_every`` bars and carried (a stale *past* estimate) in between; the
    numerator ``x_t`` still updates every bar.

    Parameters
    ----------
    close:
        Price series.
    lookback:
        Length of the trailing estimation window (must be >= 30).
    refit_every:
        Re-estimate the OU parameters every this many bars (>= 1).

    Returns
    -------
    pd.DataFrame
        Columns ``zscore`` and ``half_life`` indexed like ``close``; both are NaN
        during the warmup and where the window is non-mean-reverting.

    Raises
    ------
    ValueError
        If ``lookback < 30`` or ``refit_every < 1``.
    """
    if lookback < 30:
        raise ValueError("lookback must be >= 30 for a stable OU estimate")
    if refit_every < 1:
        raise ValueError("refit_every must be >= 1")

    values = np.asarray(close.to_numpy(), dtype=float)
    n = values.size
    zscore = np.full(n, np.nan, dtype=float)
    half_life = np.full(n, np.nan, dtype=float)

    mu = 0.0
    sigma_eq = float("nan")
    hl = float("inf")
    bars_since_fit = refit_every  # force a fit on the first eligible bar
    for t in range(lookback, n):
        if bars_since_fit >= refit_every:
            window = pd.Series(values[t - lookback + 1 : t + 1])
            params = fit_ou_ols(window, dt=1.0)
            mu = params.mu
            sigma_eq = params.sigma_eq
            hl = params.half_life
            bars_since_fit = 0
        else:
            bars_since_fit += 1
        if np.isfinite(sigma_eq) and sigma_eq > 0.0:
            zscore[t] = (values[t] - mu) / sigma_eq
            half_life[t] = hl

    return pd.DataFrame({"zscore": zscore, "half_life": half_life}, index=close.index)


def mean_reversion_positions(
    zscore: pd.Series,
    half_life: pd.Series,
    *,
    entry: float = 2.0,
    exit_band: float = 0.5,
    stop: float = 4.0,
    time_stop_mult: float = 3.0,
) -> pd.Series:
    """Convert an OU z-score path into a long / flat / short position series.

    The classic Ornstein-Uhlenbeck mean-reversion state machine (master plan
    Phase 4.3): enter against the deviation when ``|z| >= entry`` (short when the
    price is above its mean, long when below), and exit when the spread reverts
    (``|z| <= exit_band``), blows out (``|z| >= stop``), or the trade has been
    open longer than ``time_stop_mult`` half-lives. Decisions at ``t`` use only
    ``z`` up to ``t`` and are therefore look-ahead-free.

    Parameters
    ----------
    zscore, half_life:
        Aligned series from :func:`ou_zscore_series`.
    entry, exit_band, stop:
        Z-score thresholds for entry, profit-taking exit, and stop-loss
        (``0 < exit_band < entry < stop``).
    time_stop_mult:
        Maximum holding period as a multiple of the (estimate-time) half-life;
        ignored when the half-life is not finite.

    Returns
    -------
    pd.Series
        Position in ``{-1.0, 0.0, 1.0}`` indexed like ``zscore``.

    Raises
    ------
    ValueError
        If the thresholds are not ordered ``0 < exit_band < entry < stop``.
    """
    if not (0.0 < exit_band < entry < stop):
        raise ValueError("thresholds must satisfy 0 < exit_band < entry < stop")

    z = np.asarray(zscore.to_numpy(), dtype=float)
    hl = np.asarray(half_life.to_numpy(), dtype=float)
    n = z.size
    positions = np.zeros(n, dtype=float)

    current = 0.0
    bars_held = 0
    entry_half_life = float("inf")
    for t in range(n):
        zt = z[t]
        if not np.isfinite(zt):
            current = 0.0
            bars_held = 0
            positions[t] = 0.0
            continue
        if current == 0.0:
            if zt >= entry:
                current = -1.0
                bars_held = 0
                entry_half_life = hl[t] if np.isfinite(hl[t]) else float("inf")
            elif zt <= -entry:
                current = 1.0
                bars_held = 0
                entry_half_life = hl[t] if np.isfinite(hl[t]) else float("inf")
        else:
            bars_held += 1
            time_stopped = (
                np.isfinite(entry_half_life) and bars_held > time_stop_mult * entry_half_life
            )
            if abs(zt) <= exit_band or abs(zt) >= stop or time_stopped:
                current = 0.0
                bars_held = 0
        positions[t] = current

    return pd.Series(positions, index=zscore.index, name="position")


def positions_to_weights(positions: pd.Series, *, symbol: str) -> pd.DataFrame:
    """Express a single-instrument position series as an engine weight frame.

    A position of ``+1 / 0 / -1`` becomes a target weight of ``+1 / 0 / -1`` (full
    long / flat / full short of equity) in a one-column frame.
    """
    return positions.to_frame(name=symbol)


def build_mean_reversion_weight_fn(
    close: pd.Series,
    *,
    symbol: str = "SIM",
    lookback: int = 120,
    refit_every: int = 5,
) -> WeightRule:
    """Build a :data:`WeightRule` for OU mean reversion over a fixed lookback.

    The expensive look-ahead-free z-score path is computed once here; the returned
    rule only applies the (cheap) entry / exit / stop state machine, so a parameter
    sweep over those bands -- as fed to :func:`evaluate_signal` -- reuses the same
    z-score series. Each configuration must supply ``entry``, ``exit_band`` and
    ``stop`` (and may supply ``time_stop_mult``).
    """
    zhl = ou_zscore_series(close, lookback=lookback, refit_every=refit_every)

    def weight_rule(panel: pd.DataFrame, params: Mapping[str, float]) -> pd.DataFrame:
        positions = mean_reversion_positions(
            zhl["zscore"],
            zhl["half_life"],
            entry=params["entry"],
            exit_band=params["exit_band"],
            stop=params["stop"],
            time_stop_mult=params.get("time_stop_mult", 3.0),
        )
        # Align positions onto the panel's own timestamp index (the z-score was
        # computed from ``close``, whose index may differ from the panel's). The
        # two are the same chronological observations in the same order, so a
        # positional reindex is correct and prevents a silent all-zero misalign.
        sym_index = panel.xs(symbol, level="symbol").index
        if len(sym_index) == len(positions):
            positions = pd.Series(
                positions.to_numpy(), index=sym_index, name="position"
            )
        return positions_to_weights(positions, symbol=symbol)

    return weight_rule


def mean_reversion_grid(
    *,
    entries: Sequence[float] = (1.5, 2.0, 2.5),
    exit_bands: Sequence[float] = (0.25, 0.5),
    stop: float = 4.0,
) -> list[dict[str, float]]:
    """Standard entry/exit parameter grid for the OU mean-reversion sweep."""
    return [
        {"entry": float(e), "exit_band": float(x), "stop": float(stop)}
        for e in entries
        for x in exit_bands
    ]
