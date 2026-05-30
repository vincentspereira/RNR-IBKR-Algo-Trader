"""End-to-end statistical-arbitrage (pairs-trading) strategy -- the Phase 4 pilot.

This module is the keystone of master-plan Phase 4: it composes the pairs signal
stack (selection -> spread -> signals), the money-management layer (volatility
targeting) and the portfolio constructor (inverse-variance allocation, leverage
and sector caps, market-beta neutralisation) into a single object that satisfies
the Phase 3 backtest engine's ``Strategy`` protocol
(:class:`core_trading.backtest.engine.Strategy`). Running it through
:class:`~core_trading.backtest.engine.BacktestEngine` therefore exercises the
entire vertical end to end -- the explicit goal of Phase 4 ("prove the whole
stack on one strategy").

Design -- formation / trading split (Gatev, Goetzmann & Rouwenhorst 2006)
------------------------------------------------------------------------
The strategy is look-ahead-free by construction:

* **Formation window** -- the first ``formation_window`` bars are used *only* to
  select pairs (cointegration or distance), fit each pair's static hedge ratio
  (OLS intercept + slope), estimate its Ornstein-Uhlenbeck parameters, and
  measure its spread-change variance. No trades are taken in this window.
* **Trading window** -- from ``formation_window`` onward, each pair's spread
  z-score is computed on a trailing rolling window, the entry/exit/stop/time-stop
  state machine turns it into a per-bar position in ``{-1, 0, +1}``, and the
  active positions are handed to the portfolio constructor to produce per-symbol
  target weights. The weight set at bar ``t`` uses information only up to ``t``;
  the engine applies it to bar ``t+1``'s return, so there is no leakage.

Layer responsibilities (no double counting)
--------------------------------------------
* :mod:`core_trading.signals.pairs.selection` -- which pairs, and the hedge ratio.
* :mod:`core_trading.signals.pairs.spread` -- spread series, OU fit, rolling z.
* :mod:`core_trading.signals.pairs.signals` -- per-bar direction from the z-score.
* :mod:`core_trading.money.sizing` -- the gross leverage *budget* deployed, via
  volatility targeting on the formation pair sleeve (how much risk to run).
* :mod:`core_trading.portfolio.pairs_portfolio` -- how that budget is distributed
  (inverse-variance across pairs), capped (per-pair, sector, gross) and
  beta-neutralised, and expanded into per-symbol leg weights.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from core_trading.money.sizing import SizingConfig, vol_target_weight
from core_trading.portfolio.pairs_portfolio import (
    PairAllocation,
    PortfolioConfig,
    construct_pairs_portfolio,
)
from core_trading.signals.pairs.selection import (
    PairCandidate,
    select_pairs_cointegration,
    select_pairs_distance,
)
from core_trading.signals.pairs.signals import SignalConfig, generate_pair_signals
from core_trading.signals.pairs.spread import (
    StaticHedge,
    compute_spread,
    fit_ou,
    static_hedge_ratio,
    zscore,
)

__all__ = [
    "PairsTradingConfig",
    "PairTradePlan",
    "PairsTradingStrategy",
]


@dataclass(frozen=True, slots=True)
class PairsTradingConfig:
    """Configuration for :class:`PairsTradingStrategy`.

    Attributes
    ----------
    formation_window:
        Bars used to select pairs and fit hedge ratios / OU parameters. No
        trading happens before this many bars have elapsed.
    zscore_window:
        Trailing window (bars) for the rolling spread z-score during trading.
    max_pairs:
        Cap on the number of pairs carried into the trading window.
    selection_method:
        ``"cointegration"`` (Engle-Granger with multiple-testing correction) or
        ``"distance"`` (sum-of-squared normalised price differences).
    coint_alpha, max_half_life, correction:
        Cointegration-selection parameters (significance, OU half-life ceiling in
        bars, multiple-testing correction method).
    signal, sizing, portfolio:
        Sub-configs for the signal state machine, money-management volatility
        target, and portfolio construction respectively.
    """

    formation_window: int = 252
    zscore_window: int = 60
    max_pairs: int = 10
    selection_method: str = "cointegration"
    coint_alpha: float = 0.05
    max_half_life: float = 30.0
    correction: str = "bonferroni"
    min_avg_volume: float = 0.0
    signal: SignalConfig = field(default_factory=SignalConfig)
    sizing: SizingConfig = field(default_factory=SizingConfig)
    portfolio: PortfolioConfig = field(default_factory=PortfolioConfig)

    def __post_init__(self) -> None:
        if self.formation_window < 2:
            raise ValueError("formation_window must be at least 2 bars")
        if self.zscore_window < 2:
            raise ValueError("zscore_window must be at least 2 bars")
        if self.max_pairs < 1:
            raise ValueError("max_pairs must be at least 1")
        if self.selection_method not in ("cointegration", "distance"):
            raise ValueError("selection_method must be 'cointegration' or 'distance'")


@dataclass(frozen=True, slots=True)
class PairTradePlan:
    """A pair carried into the trading window, with its fitted parameters.

    Attributes
    ----------
    candidate:
        The :class:`~core_trading.signals.pairs.selection.PairCandidate` chosen in
        formation.
    hedge:
        Static (formation-fitted) hedge ``alpha`` and ``beta``; spread is
        ``y - (alpha + beta*x)``.
    half_life:
        OU half-life of the formation spread (bars); drives the time stop.
    spread_var:
        Variance of formation spread first-differences; the inverse of this is
        the pair's inverse-variance allocation weight.
    """

    candidate: PairCandidate
    hedge: StaticHedge
    half_life: float
    spread_var: float


# A small positive floor so a (near-)constant formation spread cannot produce an
# infinite inverse-variance weight.
_MIN_SPREAD_VAR = 1e-12


def _pair_id(candidate: PairCandidate) -> str:
    """Stable identifier for a pair (selection candidates are keyed by symbols)."""
    return f"{candidate.symbol_y}__{candidate.symbol_x}"


class PairsTradingStrategy:
    """Composable pairs-trading strategy implementing the engine ``Strategy`` API.

    Parameters
    ----------
    config:
        Strategy configuration. Defaults are sensible for daily equity bars.
    sectors:
        Optional symbol -> sector map used both to restrict candidate pairs to
        the same sector and to enforce the portfolio sector-exposure cap.
    market_betas:
        Optional symbol -> market beta map. When provided (and
        ``config.portfolio.beta_neutralize`` is true), the portfolio constructor
        adds an offsetting position in ``config.portfolio.hedge_symbol`` so the
        net market beta is ~0.
    require_same_sector:
        Restrict candidate pairs to symbols sharing a sector (needs ``sectors``).
    """

    def __init__(
        self,
        config: PairsTradingConfig | None = None,
        *,
        sectors: dict[str, str] | None = None,
        market_betas: dict[str, float] | None = None,
        require_same_sector: bool = False,
    ) -> None:
        self.config = config or PairsTradingConfig()
        self.sectors = sectors
        self.market_betas = market_betas
        self.require_same_sector = require_same_sector
        # Diagnostics populated by the most recent generate_weights call.
        self.plans: list[PairTradePlan] = []
        self.gross_budget: float = 0.0

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _wide_close(prices: pd.DataFrame) -> pd.DataFrame:
        """Return a (timestamp x symbol) close-price frame from an engine panel.

        Accepts either the engine's ``(symbol, timestamp)`` MultiIndex panel or a
        plain wide close frame (already timestamp-indexed with symbol columns).
        """
        if isinstance(prices.index, pd.MultiIndex):
            return prices["close"].unstack("symbol").sort_index()
        return prices.sort_index()

    def _wide_volume(self, prices: pd.DataFrame, columns: pd.Index) -> pd.DataFrame | None:
        if isinstance(prices.index, pd.MultiIndex) and "volume" in prices.columns:
            return prices["volume"].unstack("symbol").sort_index().reindex(columns=columns)
        return None

    def _select(
        self, formation: pd.DataFrame, volume: pd.DataFrame | None
    ) -> list[PairCandidate]:
        cfg = self.config
        if cfg.selection_method == "cointegration":
            candidates = select_pairs_cointegration(
                formation,
                alpha=cfg.coint_alpha,
                max_half_life=cfg.max_half_life,
                correction=cfg.correction,
                sectors=self.sectors,
                require_same_sector=self.require_same_sector,
                volume=volume,
                min_avg_volume=cfg.min_avg_volume,
            )
        else:
            candidates = select_pairs_distance(
                formation,
                top_n=cfg.max_pairs,
                sectors=self.sectors,
                require_same_sector=self.require_same_sector,
                volume=volume,
                min_avg_volume=cfg.min_avg_volume,
            )
        return candidates[: cfg.max_pairs]

    def _build_plan(self, formation: pd.DataFrame, pc: PairCandidate) -> PairTradePlan | None:
        """Fit the static hedge, OU and variance for a pair on formation data."""
        if pc.symbol_y not in formation.columns or pc.symbol_x not in formation.columns:
            return None
        fy = formation[pc.symbol_y]
        fx = formation[pc.symbol_x]
        hedge = static_hedge_ratio(fy, fx)
        form_spread = compute_spread(fy, fx, hedge).dropna()
        if form_spread.size < 3:
            return None
        ou = fit_ou(form_spread)
        diffs = np.diff(form_spread.to_numpy())
        spread_var = float(np.var(diffs, ddof=1)) if diffs.size >= 2 else _MIN_SPREAD_VAR
        spread_var = max(spread_var, _MIN_SPREAD_VAR)
        return PairTradePlan(
            candidate=pc, hedge=hedge, half_life=ou.half_life, spread_var=spread_var
        )

    def _gross_budget(self, formation: pd.DataFrame, plans: list[PairTradePlan]) -> float:
        """Money-management: volatility-target the formation pair sleeve.

        Builds an equal-weight long-spread sleeve over the formation window and
        uses :func:`core_trading.money.sizing.vol_target_weight` to decide how much
        gross leverage to deploy. Each pair's per-bar return is the spread change
        per unit of *gross price notional* ``P_y + |beta|*P_x`` -- the return on
        one dollar of gross (long-y / short-x) exposure. That denominator is a sum
        of positive prices, so it is always well defined (unlike the spread level,
        which for a market-neutral pair sits near zero). The vol-target weight is
        clamped to the portfolio's ``gross_leverage_cap`` so the money-management
        layer can only *reduce* risk, never loosen the hard leverage limit.
        """
        if not plans:
            return 0.0
        sleeve = np.zeros(formation.shape[0], dtype=float)
        count = 0
        for plan in plans:
            py = formation[plan.candidate.symbol_y]
            px = formation[plan.candidate.symbol_x]
            spread = compute_spread(py, px, plan.hedge)
            gross_notional = py.abs() + abs(plan.hedge.beta) * px.abs()
            denom = gross_notional.replace(0.0, np.nan)
            sleeve_returns = (spread.diff() / denom).fillna(0.0).to_numpy()
            sleeve += sleeve_returns
            count += 1
        sleeve /= count
        target = vol_target_weight(
            sleeve,
            target_vol=self.config.sizing.target_vol,
            periods_per_year=self.config.sizing.periods_per_year,
        )
        cap = self.config.portfolio.gross_leverage_cap
        if target <= 0.0:
            return cap
        return float(min(target, cap))

    # -------------------------------------------------------------------- main
    def generate_weights(self, prices: pd.DataFrame) -> pd.DataFrame:
        """Produce a (timestamp x symbol) target-weight frame for the engine."""
        close = self._wide_close(prices)
        timeline = close.index
        n = len(timeline)
        weights = pd.DataFrame(0.0, index=timeline, columns=close.columns)
        cfg = self.config
        self.plans = []
        self.gross_budget = 0.0
        if n <= cfg.formation_window:
            return weights

        formation = close.iloc[: cfg.formation_window]
        volume = self._wide_volume(prices, close.columns)
        form_volume = volume.iloc[: cfg.formation_window] if volume is not None else None

        candidates = self._select(formation, form_volume)
        plans = [p for pc in candidates if (p := self._build_plan(formation, pc)) is not None]
        self.plans = plans
        if not plans:
            return weights

        self.gross_budget = self._gross_budget(formation, plans)
        port_cfg = self._portfolio_config_with_budget(self.gross_budget)

        # Pre-compute each pair's per-bar position over the whole timeline.
        positions: dict[str, np.ndarray] = {}
        for plan in plans:
            spread = compute_spread(
                close[plan.candidate.symbol_y], close[plan.candidate.symbol_x], plan.hedge
            )
            z = zscore(spread, window=cfg.zscore_window)
            sig = generate_pair_signals(z, config=cfg.signal, half_life=plan.half_life)
            positions[_pair_id(plan.candidate)] = sig["position"].to_numpy()

        for i in range(cfg.formation_window, n):
            allocations: list[PairAllocation] = []
            for plan in plans:
                pos = positions[_pair_id(plan.candidate)][i]
                if not np.isfinite(pos) or int(pos) == 0:
                    continue
                pc = plan.candidate
                allocations.append(
                    PairAllocation(
                        pair_id=_pair_id(pc),
                        symbol_y=pc.symbol_y,
                        symbol_x=pc.symbol_x,
                        hedge_ratio=plan.hedge.beta,
                        direction=int(pos),
                        spread_var=plan.spread_var,
                        sector=None if self.sectors is None else self.sectors.get(pc.symbol_y),
                    )
                )
            if not allocations:
                continue
            built = construct_pairs_portfolio(
                allocations, config=port_cfg, market_betas=self.market_betas
            )
            ts = timeline[i]
            for sym, w in built.weights.items():
                if sym not in weights.columns:
                    weights[sym] = 0.0
                weights.at[ts, sym] = w
        return weights

    def _portfolio_config_with_budget(self, budget: float) -> PortfolioConfig:
        base = self.config.portfolio
        return PortfolioConfig(
            gross_leverage_cap=max(budget, _MIN_SPREAD_VAR),
            sector_cap=base.sector_cap,
            per_pair_cap=base.per_pair_cap,
            beta_neutralize=base.beta_neutralize,
            hedge_symbol=base.hedge_symbol,
        )
