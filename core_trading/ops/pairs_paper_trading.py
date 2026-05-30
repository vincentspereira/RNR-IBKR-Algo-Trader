"""Pairs paper-trading harness (master plan Phase 4.9).

A day-by-day operational driver for the Phase 4 pilot. Unlike the backtest engine
(which answers "what would the equity curve have been?"), this harness answers the
*operations* questions the plan requires before live capital is committed:

* Does every day's target portfolio pass pre-trade risk before it is sent?
* When a circuit breaker trips, does the kill switch halt trading and record an
  incident?
* What does the daily monitoring record look like (PnL, drawdown, rolling Sharpe,
  active pairs, leverage)?
* Has the strategy earned promotion -- enough paper days, a paper Sharpe within a
  standard error of the backtest Sharpe, and zero unresolved incidents?

Over historical data the harness runs as a *risk-gated walk-forward*: it consumes
the look-ahead-free target weights from :class:`PairsTradingStrategy`, marks them
to market one bar forward (the same no-look-ahead convention the engine uses), and
applies the risk gate each day. The execution seam (:class:`FillModel`) defaults
to a deterministic simulator; in live paper trading it is replaced by the IBKR
paper adapter without changing this module.

The harness is deliberately broker-agnostic. The genuine 90-calendar-day paper run
and the subsequent small-capital live phase (plan Phase 4.10) are operational
milestones gated on elapsed time and a live IBKR paper account; this module is the
code that drives them and that lets the monitoring and promotion logic be unit
tested today.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from core_trading.backtest.metrics import max_drawdown, sharpe_ratio
from core_trading.risk.pairs_risk import PairsRiskManager
from core_trading.strategies.pairs_trading import PairsTradingStrategy

__all__ = [
    "PaperConfig",
    "DailySnapshot",
    "PromotionDecision",
    "PairsPaperTrader",
]


@dataclass(frozen=True, slots=True)
class PaperConfig:
    """Paper-trading and promotion-gate configuration.

    Attributes
    ----------
    backtest_sharpe:
        The annualised Sharpe achieved in the validated backtest. Promotion
        requires the paper Sharpe to land within ``promotion_se_mult`` standard
        errors of this value (decay is expected; collapse is not).
    promotion_se_mult:
        Number of Sharpe standard errors the paper result may sit below the
        backtest before promotion is refused.
    min_paper_days:
        Minimum number of paper-trading observations before promotion can be
        considered (the plan mandates >= 90 calendar days).
    periods_per_year:
        Annualisation factor for Sharpe (252 for daily bars).
    halt_on_breach:
        When true, the first risk breach halts trading for the remainder of the
        run (kill switch) and is recorded as an incident.
    """

    backtest_sharpe: float = 1.0
    promotion_se_mult: float = 1.0
    min_paper_days: int = 90
    periods_per_year: int = 252
    halt_on_breach: bool = True

    def __post_init__(self) -> None:
        if self.min_paper_days < 1:
            raise ValueError("min_paper_days must be at least 1")
        if self.promotion_se_mult < 0:
            raise ValueError("promotion_se_mult must be non-negative")
        if self.periods_per_year < 1:
            raise ValueError("periods_per_year must be at least 1")


@dataclass(frozen=True, slots=True)
class DailySnapshot:
    """One trading day's monitoring record."""

    date: pd.Timestamp
    equity: float
    daily_return: float
    gross_leverage: float
    n_active_pairs: int
    rolling_sharpe: float
    drawdown: float
    risk_ok: bool
    halted: bool
    violations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    """Outcome of the paper-to-live promotion gate."""

    eligible: bool
    reasons: tuple[str, ...]
    paper_sharpe: float
    backtest_sharpe: float
    sharpe_standard_error: float
    n_days: int
    n_incidents: int


def sharpe_standard_error(sharpe: float, n_obs: int) -> float:
    """Asymptotic standard error of an annualised Sharpe ratio.

    Uses the Lo (2002) large-sample approximation ``sqrt((1 + 0.5*SR^2)/n)`` on
    the per-period Sharpe, then rescales to the annualised figure. Returns
    ``inf`` when there are too few observations to estimate it.
    """
    if n_obs < 2:
        return float("inf")
    return math.sqrt((1.0 + 0.5 * sharpe**2) / n_obs)


class PairsPaperTrader:
    """Risk-gated daily driver for the pairs pilot.

    Parameters
    ----------
    strategy:
        The configured :class:`PairsTradingStrategy` to paper-trade.
    risk_manager:
        Pre-trade and circuit-breaker gate. A default :class:`PairsRiskManager`
        is used when omitted.
    config:
        Paper-trading / promotion configuration.
    initial_cash:
        Starting paper equity.
    """

    def __init__(
        self,
        strategy: PairsTradingStrategy,
        *,
        risk_manager: PairsRiskManager | None = None,
        config: PaperConfig | None = None,
        initial_cash: float = 1_000_000.0,
    ) -> None:
        self.strategy = strategy
        self.risk_manager = risk_manager or PairsRiskManager()
        self.config = config or PaperConfig()
        self.initial_cash = float(initial_cash)
        self.snapshots: list[DailySnapshot] = []
        self.incidents: list[str] = []
        self._sectors = strategy.sectors

    # ------------------------------------------------------------------- run
    def run(self, prices: pd.DataFrame) -> list[DailySnapshot]:
        """Walk the trading window day by day, gating each day on risk.

        Returns the list of :class:`DailySnapshot` and populates ``snapshots`` and
        ``incidents``. The kill switch halts trading after the first breach when
        ``config.halt_on_breach`` is set; halted days are marked flat (no new risk
        is taken) but still recorded for monitoring continuity.
        """
        self.snapshots = []
        self.incidents = []

        weights = self.strategy.generate_weights(prices)
        if isinstance(prices.index, pd.MultiIndex):
            close = prices["close"].unstack("symbol").sort_index()
        else:
            close = prices.sort_index()
        asset_returns = close.pct_change().fillna(0.0)
        # No look-ahead: weights set at t earn t+1's return.
        held = weights.shift(1).fillna(0.0)

        equity = self.initial_cash
        equity_path: list[float] = []
        ret_path: list[float] = []
        halted = False

        active_mask = weights.abs().sum(axis=1) > 0
        first_active = active_mask.idxmax() if active_mask.any() else None

        for ts in weights.index:
            target_row = weights.loc[ts]
            gross = float(target_row.abs().sum())
            n_active = int((target_row.abs() > 0).sum()) // 2  # two legs per pair

            # Pre-trade gate on the day's target portfolio.
            proposed = {s: float(v) for s, v in target_row.items() if v != 0.0}
            risk = self.risk_manager.pre_trade(proposed, sectors=self._sectors)
            violations = list(risk.violations)

            period_return = (
                0.0 if halted else float((held.loc[ts] * asset_returns.loc[ts]).sum())
            )

            equity *= 1.0 + period_return
            equity_path.append(equity)
            ret_path.append(period_return)

            # Daily circuit breaker once we have a couple of marks.
            if first_active is not None and ts >= first_active and len(equity_path) >= 2:
                eq_series = pd.Series(equity_path)
                daily_check = self.risk_manager.daily_check(eq_series)
                if not daily_check.passed:
                    violations.extend(daily_check.violations)

            day_ok = not violations
            if not day_ok and self.config.halt_on_breach and not halted:
                halted = True
                self.incidents.append(f"{ts.date()}: {'; '.join(violations)}")

            eq_arr = np.asarray(equity_path, dtype=float)
            self.snapshots.append(
                DailySnapshot(
                    date=ts,
                    equity=equity,
                    daily_return=period_return,
                    gross_leverage=gross,
                    n_active_pairs=n_active,
                    rolling_sharpe=sharpe_ratio(
                        np.asarray(ret_path, dtype=float), self.config.periods_per_year
                    ),
                    drawdown=max_drawdown(pd.Series(eq_arr)) if eq_arr.size >= 2 else 0.0,
                    risk_ok=day_ok,
                    halted=halted,
                    violations=tuple(violations),
                )
            )
        return self.snapshots

    # ------------------------------------------------------------- monitoring
    def monitoring_frame(self) -> pd.DataFrame:
        """Daily monitoring records as a DataFrame (empty before :meth:`run`)."""
        if not self.snapshots:
            return pd.DataFrame(
                columns=[
                    "equity",
                    "daily_return",
                    "gross_leverage",
                    "n_active_pairs",
                    "rolling_sharpe",
                    "drawdown",
                    "risk_ok",
                    "halted",
                ]
            )
        return pd.DataFrame(
            {
                "equity": [s.equity for s in self.snapshots],
                "daily_return": [s.daily_return for s in self.snapshots],
                "gross_leverage": [s.gross_leverage for s in self.snapshots],
                "n_active_pairs": [s.n_active_pairs for s in self.snapshots],
                "rolling_sharpe": [s.rolling_sharpe for s in self.snapshots],
                "drawdown": [s.drawdown for s in self.snapshots],
                "risk_ok": [s.risk_ok for s in self.snapshots],
                "halted": [s.halted for s in self.snapshots],
            },
            index=pd.Index([s.date for s in self.snapshots], name="date"),
        )

    def paper_returns(self) -> pd.Series:
        """The realised daily paper-trading return series (active days only)."""
        if not self.snapshots:
            return pd.Series(dtype=float)
        returns = pd.Series(
            [s.daily_return for s in self.snapshots],
            index=[s.date for s in self.snapshots],
        )
        return returns[returns != 0.0]

    @property
    def is_halted(self) -> bool:
        return bool(self.snapshots) and self.snapshots[-1].halted

    # -------------------------------------------------------------- promotion
    def evaluate_promotion(self) -> PromotionDecision:
        """Apply the paper-to-live promotion gate.

        Promotion requires all of: (a) at least ``min_paper_days`` active paper
        observations; (b) zero unresolved incidents (kill-switch trips); and
        (c) a paper Sharpe no worse than ``backtest_sharpe`` minus
        ``promotion_se_mult`` standard errors. Decay toward the backtest Sharpe is
        tolerated up to that band; a paper Sharpe that *exceeds* the backtest is
        always acceptable.
        """
        returns = self.paper_returns()
        n_days = int(returns.size)
        paper_sharpe = sharpe_ratio(returns.to_numpy(), self.config.periods_per_year)
        se = sharpe_standard_error(paper_sharpe, n_days)
        floor = self.config.backtest_sharpe - self.config.promotion_se_mult * se

        reasons: list[str] = []
        if n_days < self.config.min_paper_days:
            reasons.append(
                f"insufficient paper history: {n_days} < {self.config.min_paper_days} days"
            )
        if self.incidents:
            reasons.append(f"{len(self.incidents)} unresolved risk incident(s)")
        if math.isfinite(se) and paper_sharpe < floor:
            reasons.append(
                f"paper Sharpe {paper_sharpe:.2f} below promotion floor {floor:.2f} "
                f"(backtest {self.config.backtest_sharpe:.2f} - "
                f"{self.config.promotion_se_mult} SE)"
            )

        return PromotionDecision(
            eligible=not reasons,
            reasons=tuple(reasons),
            paper_sharpe=paper_sharpe,
            backtest_sharpe=self.config.backtest_sharpe,
            sharpe_standard_error=se,
            n_days=n_days,
            n_incidents=len(self.incidents),
        )
