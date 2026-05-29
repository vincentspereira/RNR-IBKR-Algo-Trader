"""Hybrid vectorised + event-driven backtest engine (master plan Phase 3.1).

A strategy expresses itself as **target portfolio weights** -- a frame indexed by
timestamp with one column per symbol, the value being the fraction of equity to
hold in that symbol at that bar's close. This single representation drives two
execution modes:

* **Vectorised** (:meth:`BacktestEngine.run_vectorised`) -- computes the whole
  equity curve with NumPy in one pass. The weight set at the close of bar ``t``
  earns bar ``t+1``'s return, so there is no look-ahead. Fast; used for research
  sweeps. Costs are applied as a linear turnover charge.

* **Event-driven** (:meth:`BacktestEngine.run_event_driven`) -- walks bar by bar,
  turning the weight delta into orders, filling them through the
  :class:`~core_trading.backtest.execution.ExecutionSimulator` (slippage, market
  impact, partial fills) and booking them in the :class:`Portfolio`. Realistic;
  used for the final backtest and for live-parity checks.

With a frictionless cost model and fractional shares the two modes agree to
floating-point precision (well inside the master plan's 1bp/day tolerance),
because both rebalance to the target weight every bar and therefore realise the
identical period return ``sum_i w_{i,t-1} * r_{i,t}``.

The engine is deterministic: identical inputs and config produce a byte-identical
:class:`BacktestResult`, so a saved run replays exactly (Phase 3 DOD).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
import pandas as pd

from core_trading.backtest.costs import CostModel, get_cost_model
from core_trading.backtest.execution import Bar, ExecutionConfig, ExecutionSimulator
from core_trading.backtest.orders import Order, OrderType, Side, Trade
from core_trading.backtest.portfolio import LotMethod, Portfolio

__all__ = [
    "Strategy",
    "WeightStrategy",
    "BacktestConfig",
    "BacktestResult",
    "BacktestEngine",
]

_REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")


class Strategy(Protocol):
    """A strategy maps a price panel to target weights.

    ``generate_weights`` must be look-ahead-free: the row for timestamp ``t`` may
    use data only up to and including ``t``. The returned frame is indexed by
    timestamp with one column per symbol; missing entries are treated as "hold
    the previous weight".
    """

    def generate_weights(self, prices: pd.DataFrame) -> pd.DataFrame:
        ...


@dataclass
class WeightStrategy:
    """Trivial strategy that replays a precomputed weight frame.

    Useful for tests, Monte Carlo and walk-forward, where weights are produced
    elsewhere and simply fed to the engine.
    """

    weights: pd.DataFrame

    def generate_weights(self, prices: pd.DataFrame) -> pd.DataFrame:  # noqa: ARG002
        return self.weights


@dataclass
class BacktestConfig:
    """Engine configuration. ``cost_model`` overrides ``cost_model_name``."""

    initial_cash: float = 1_000_000.0
    cost_model_name: str = "zero"
    cost_model: CostModel | None = None
    periods_per_year: int = 252
    allow_fractional_shares: bool = True
    max_participation_rate: float = 1.0
    lot_method: LotMethod = LotMethod.FIFO
    market_fill_price: str = "close"
    vol_window: int = 20
    rebalance_threshold: float = 1e-9
    seed: int = 42

    def resolve_cost_model(self) -> CostModel:
        return (
            self.cost_model if self.cost_model is not None else get_cost_model(self.cost_model_name)
        )


@dataclass
class BacktestResult:
    """Raw output of a backtest run; :class:`BacktestReport` formats it."""

    mode: str
    equity: pd.Series
    returns: pd.Series
    weights: pd.DataFrame
    trades: list[Trade] = field(default_factory=list)
    turnover: float = 0.0
    total_costs: float = 0.0
    initial_cash: float = 0.0

    def fingerprint(self) -> str:
        """Stable SHA-256 of the equity curve and trade ledger, for replay
        verification (two identical runs share a fingerprint)."""
        hasher = hashlib.sha256()
        eq = np.ascontiguousarray(self.equity.to_numpy(dtype=float))
        hasher.update(eq.tobytes())
        hasher.update(self.equity.index.astype("int64").to_numpy().tobytes())
        for t in self.trades:
            hasher.update(
                f"{t.symbol}|{t.direction}|{t.quantity:.10f}|{t.entry_price:.10f}|"
                f"{t.exit_price:.10f}|{t.pnl:.10f}".encode()
            )
        return hasher.hexdigest()


def _validate_panel(prices: pd.DataFrame) -> None:
    if not isinstance(prices.index, pd.MultiIndex) or prices.index.nlevels != 2:
        raise ValueError("prices must have a (symbol, timestamp) MultiIndex")
    if list(prices.index.names) != ["symbol", "timestamp"]:
        raise ValueError("prices index names must be ['symbol', 'timestamp']")
    missing = [c for c in _REQUIRED_COLUMNS if c not in prices.columns]
    if missing:
        raise ValueError(f"prices missing required columns: {missing}")


class BacktestEngine:
    """Runs a :class:`Strategy` over a price panel in either mode."""

    def __init__(self, config: BacktestConfig | None = None) -> None:
        self.config = config or BacktestConfig()

    # ------------------------------------------------------------- preparation
    def _wide(self, prices: pd.DataFrame, field_name: str) -> pd.DataFrame:
        return prices[field_name].unstack("symbol").sort_index()

    def _aligned_weights(
        self, strategy: Strategy, prices: pd.DataFrame, close: pd.DataFrame
    ) -> pd.DataFrame:
        weights = strategy.generate_weights(prices)
        if not isinstance(weights, pd.DataFrame):
            raise TypeError("generate_weights must return a DataFrame")
        weights = weights.reindex(index=close.index, columns=close.columns)
        return weights.ffill().fillna(0.0)

    # -------------------------------------------------------------- vectorised
    def run_vectorised(self, prices: pd.DataFrame, strategy: Strategy) -> BacktestResult:
        """Compute the equity curve analytically (fast, costless-exact)."""
        _validate_panel(prices)
        close = self._wide(prices, "close")
        weights = self._aligned_weights(strategy, prices, close)

        asset_returns = close.pct_change().fillna(0.0)
        held = weights.shift(1).fillna(0.0)
        gross = (held * asset_returns).sum(axis=1)

        # Linear turnover cost: charge a per-unit-turnover rate derived from the
        # cost model's spread + commission. Zero under the frictionless model.
        cost_model = self.config.resolve_cost_model()
        turnover_rate = self._linear_cost_rate(cost_model)
        turnover_per_bar = weights.diff().abs().sum(axis=1).fillna(weights.iloc[0].abs().sum())
        cost = turnover_per_bar * turnover_rate
        net = gross - cost

        equity = self.config.initial_cash * (1.0 + net).cumprod()
        equity.name = "equity"
        returns = net.copy()
        returns.name = "returns"
        return BacktestResult(
            mode="vectorised",
            equity=equity,
            returns=returns,
            weights=weights,
            turnover=float(turnover_per_bar.sum()),
            total_costs=float((cost * equity.shift(1).fillna(self.config.initial_cash)).sum()),
            initial_cash=self.config.initial_cash,
        )

    def _linear_cost_rate(self, cost_model: CostModel) -> float:
        """Approximate per-unit-turnover cost (fraction) for the vectorised mode:
        half-spread plus percent commission, expressed as a fraction of notional."""
        spread_frac = cost_model.slippage.half_spread_bps / 1e4
        commission_frac = cost_model.commission.percent_of_notional
        return spread_frac + commission_frac

    # ------------------------------------------------------------ event-driven
    def run_event_driven(self, prices: pd.DataFrame, strategy: Strategy) -> BacktestResult:
        """Walk bar by bar, generating and filling orders realistically."""
        _validate_panel(prices)
        close = self._wide(prices, "close")
        open_ = self._wide(prices, "open")
        high = self._wide(prices, "high")
        low = self._wide(prices, "low")
        volume = self._wide(prices, "volume")
        weights = self._aligned_weights(strategy, prices, close)

        returns_wide = close.pct_change()
        vol = returns_wide.rolling(self.config.vol_window, min_periods=2).std().fillna(0.0)
        adv = volume.rolling(self.config.vol_window, min_periods=1).mean().fillna(0.0)

        cost_model = self.config.resolve_cost_model()
        exec_config = ExecutionConfig(
            max_participation_rate=self.config.max_participation_rate,
            allow_partial_fills=self.config.max_participation_rate < 1.0,
            market_fill_price=self.config.market_fill_price,
        )
        simulator = ExecutionSimulator(cost_model, exec_config)
        portfolio = Portfolio(
            initial_cash=self.config.initial_cash,
            lot_method=self.config.lot_method,
            borrow_model=cost_model.borrow,
        )

        symbols = list(close.columns)
        order_seq = 0
        for i, ts in enumerate(close.index):
            close_row = close.loc[ts]
            price_map = {s: float(close_row[s]) for s in symbols if not np.isnan(close_row[s])}
            if i > 0:
                portfolio.accrue_carry(price_map, days=1)
            equity = portfolio.equity(price_map)

            target_row = weights.loc[ts]
            for sym in symbols:
                price = price_map.get(sym)
                if price is None or price <= 0:
                    continue
                target_w = float(target_row[sym])
                target_qty = target_w * equity / price
                if not self.config.allow_fractional_shares:
                    target_qty = float(np.trunc(target_qty))
                cur_qty = portfolio.position(sym).quantity
                delta = target_qty - cur_qty
                if abs(delta) <= self.config.rebalance_threshold:
                    continue
                side = Side.BUY if delta > 0 else Side.SELL
                order_seq += 1
                order = Order(
                    order_id=f"{sym}-{i}-{order_seq}",
                    symbol=sym,
                    side=side,
                    quantity=abs(delta),
                    order_type=OrderType.MARKET,
                    created_at=ts,
                )
                bar = Bar(
                    timestamp=ts,
                    open=float(open_.loc[ts, sym]),
                    high=float(high.loc[ts, sym]),
                    low=float(low.loc[ts, sym]),
                    close=float(close_row[sym]),
                    volume=float(volume.loc[ts, sym]) if not np.isnan(volume.loc[ts, sym]) else 0.0,
                    adv=float(adv.loc[ts, sym]),
                    volatility=float(vol.loc[ts, sym]) * price,
                )
                result = simulator.execute(order, bar)
                if result.fill is not None:
                    portfolio.apply_fill(result.fill)

            portfolio.record(ts, price_map)

        equity_series = portfolio.equity_series()
        returns = equity_series.pct_change().fillna(0.0)
        returns.name = "returns"
        return BacktestResult(
            mode="event_driven",
            equity=equity_series,
            returns=returns,
            weights=weights,
            trades=portfolio.trades,
            turnover=float(weights.diff().abs().sum(axis=1).sum()),
            total_costs=portfolio.total_costs,
            initial_cash=self.config.initial_cash,
        )

    # -------------------------------------------------------------------- run
    def run(
        self, prices: pd.DataFrame, strategy: Strategy, mode: str = "event_driven"
    ) -> BacktestResult:
        """Run the backtest in ``mode`` ('event_driven' or 'vectorised')."""
        if mode == "vectorised":
            return self.run_vectorised(prices, strategy)
        if mode == "event_driven":
            return self.run_event_driven(prices, strategy)
        raise ValueError(f"unknown mode {mode!r}; use 'vectorised' or 'event_driven'")
