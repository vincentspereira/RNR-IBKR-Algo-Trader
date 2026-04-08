"""Real-time mark-to-market P&L tracking with Black-Scholes Greeks for options.

This module provides institutional-grade P&L tracking across all position types
(equity, option, future, forex) with real-time mark-to-market valuation and
Black-Scholes Greeks calculation for options positions.
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Helper functions for Black-Scholes calculations
# ---------------------------------------------------------------------------

def _normal_cdf(x: float) -> float:
    """Cumulative standard normal distribution using the error function.

    Uses the identity: N(x) = 0.5 * (1 + erf(x / sqrt(2)))
    """
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _normal_pdf(x: float) -> float:
    """Standard normal probability density function."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PositionInfo:
    """Position information from broker."""

    symbol: str
    quantity: float  # positive for long, negative for short
    avg_cost: float
    market_price: float = 0.0
    realized_pnl: float = 0.0
    asset_type: str = "equity"  # "equity", "option", "future", "forex"


@dataclass
class Greeks:
    """Options Greeks."""

    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    rho: float = 0.0
    implied_volatility: float = 0.0


@dataclass
class PositionPnL:
    """P&L for a single position."""

    symbol: str
    quantity: float
    avg_cost: float
    market_price: float
    unrealized_pnl: float
    realized_pnl: float
    pnl_pct: float
    asset_type: str = "equity"
    greeks: Optional[Greeks] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class PortfolioPnL:
    """Aggregate P&L across all positions."""

    total_unrealized_pnl: float
    total_realized_pnl: float
    total_pnl: float
    total_value: float
    total_cost: float
    position_count: int
    positions: Dict[str, PositionPnL]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    daily_pnl: float = 0.0
    daily_pnl_pct: float = 0.0


@dataclass
class PnLConfig:
    """Configuration for P&L tracking."""

    risk_free_rate: float = 0.05  # 5% risk-free rate
    update_interval_seconds: float = 1.0
    max_position_age_days: int = 365


# ---------------------------------------------------------------------------
# PnL Tracker
# ---------------------------------------------------------------------------

class PnLTracker:
    """Real-time mark-to-market P&L tracking with Greeks for options.

    Provides real-time portfolio valuation, unrealized/realized P&L
    computation, and Black-Scholes Greeks for options positions.
    """

    def __init__(
        self,
        broker_adapter=None,
        event_bus=None,
        config: Optional[PnLConfig] = None,
    ):
        self._broker = broker_adapter
        self._event_bus = event_bus
        self._config = config or PnLConfig()
        self._positions: Dict[str, PositionPnL] = {}
        self._position_cache: Dict[str, PositionInfo] = {}
        self._price_cache: Dict[str, float] = {}
        self._history: List[PortfolioPnL] = []
        self._max_history: int = 10000
        self._logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Position updates
    # ------------------------------------------------------------------

    async def update_positions(self, positions: List[PositionInfo]) -> None:
        """Update position data and recalculate P&L for all positions.

        For each position with non-zero quantity, the unrealized P&L is
        computed using the supplied market price or the last known cached
        price.  Positions with zero quantity are skipped.
        """
        for pos in positions:
            self._position_cache[pos.symbol] = pos

            # Use the incoming market price if provided; otherwise fall back
            # to the previously cached price.
            if pos.market_price > 0.0:
                self._price_cache[pos.symbol] = pos.market_price

            price = self._price_cache.get(pos.symbol, pos.market_price)
            pnl = self.calculate_position_pnl(pos, price)
            self._positions[pos.symbol] = pnl

        self._logger.debug(
            "Updated P&L for %d positions", len(positions)
        )

    async def update_price(self, symbol: str, price: float) -> None:
        """Update market price for a symbol and recalculate its P&L."""
        self._price_cache[symbol] = price

        if symbol in self._position_cache:
            pos = self._position_cache[symbol]
            pnl = self.calculate_position_pnl(pos, price)
            self._positions[symbol] = pnl
            self._logger.debug(
                "Price updated for %s -> %.4f, unrealized P&L: %.4f",
                symbol,
                price,
                pnl.unrealized_pnl,
            )

    async def update_pnl(self) -> Dict[str, PositionPnL]:
        """Recalculate P&L for all cached positions.

        Returns the updated mapping of symbol -> PositionPnL.
        """
        for symbol, pos in self._position_cache.items():
            price = self._price_cache.get(symbol, pos.market_price)
            self._positions[symbol] = self.calculate_position_pnl(pos, price)

        snapshot = self.get_portfolio_summary()
        self._save_snapshot(snapshot)

        self._logger.debug(
            "P&L recalculated for %d positions", len(self._positions)
        )
        return dict(self._positions)

    # ------------------------------------------------------------------
    # P&L calculations
    # ------------------------------------------------------------------

    def calculate_position_pnl(
        self, position: PositionInfo, market_price: float
    ) -> PositionPnL:
        """Calculate P&L for a single position.

        For long positions (positive quantity):
            unrealized_pnl = (market_price - avg_cost) * quantity

        For short positions (negative quantity):
            unrealized_pnl = (avg_cost - market_price) * abs(quantity)

        pnl_pct is always calculated as the percentage return relative to
        the average cost basis.
        """
        quantity = position.quantity

        if quantity == 0:
            return PositionPnL(
                symbol=position.symbol,
                quantity=0.0,
                avg_cost=position.avg_cost,
                market_price=market_price,
                unrealized_pnl=0.0,
                realized_pnl=position.realized_pnl,
                pnl_pct=0.0,
                asset_type=position.asset_type,
            )

        if quantity > 0:
            # Long position
            unrealized_pnl = (market_price - position.avg_cost) * quantity
        else:
            # Short position
            unrealized_pnl = (
                (position.avg_cost - market_price) * abs(quantity)
            )

        if position.avg_cost != 0.0:
            pnl_pct = (
                (market_price - position.avg_cost) / position.avg_cost
            ) * 100.0
        else:
            pnl_pct = 0.0

        return PositionPnL(
            symbol=position.symbol,
            quantity=quantity,
            avg_cost=position.avg_cost,
            market_price=market_price,
            unrealized_pnl=unrealized_pnl,
            realized_pnl=position.realized_pnl,
            pnl_pct=pnl_pct,
            asset_type=position.asset_type,
        )

    # ------------------------------------------------------------------
    # Black-Scholes Greeks
    # ------------------------------------------------------------------

    def calculate_greeks(
        self,
        spot: float,
        strike: float,
        time_to_expiry: float,
        risk_free_rate: float,
        volatility: float,
        option_type: str = "call",
        dividend_yield: float = 0.0,
    ) -> Greeks:
        """Calculate Greeks using the Black-Scholes model.

        Parameters
        ----------
        spot : float
            Current price of the underlying asset.
        strike : float
            Option strike price.
        time_to_expiry : float
            Time to expiration in years (e.g. 30/365).
        risk_free_rate : float
            Annualised risk-free interest rate.
        volatility : float
            Annualised implied volatility.
        option_type : str
            ``"call"`` or ``"put"``.
        dividend_yield : float
            Annualised continuous dividend yield.

        Returns
        -------
        Greeks
            Delta, gamma, theta (daily), vega (per 1 % vol), rho (per
            1 % rate), and implied volatility.

        Edge cases
        ----------
        * ``time_to_expiry <= 0`` -- the option is at expiry.  For a call
          delta approaches 1 if ITM else 0; for a put delta approaches -1
          if ITM else 0.  All other Greeks are set to 0.
        * ``volatility <= 0`` -- returns Greeks with all values at 0.
        """
        # --- Edge case: expired option ----------------------------------
        if time_to_expiry <= 0.0:
            if option_type == "call":
                delta = 1.0 if spot > strike else 0.0
            else:
                delta = -1.0 if spot < strike else 0.0
            return Greeks(
                delta=delta,
                gamma=0.0,
                theta=0.0,
                vega=0.0,
                rho=0.0,
                implied_volatility=0.0,
            )

        # --- Edge case: zero volatility ---------------------------------
        if volatility <= 0.0:
            return Greeks()

        # --- Standard Black-Scholes computation -------------------------
        sqrt_t = math.sqrt(time_to_expiry)
        d1 = (
            math.log(spot / strike)
            + (risk_free_rate - dividend_yield + 0.5 * volatility * volatility)
            * time_to_expiry
        ) / (volatility * sqrt_t)
        d2 = d1 - volatility * sqrt_t

        n_d1 = _normal_cdf(d1)
        n_d2 = _normal_cdf(d2)
        pdf_d1 = _normal_pdf(d1)

        exp_qt = math.exp(-dividend_yield * time_to_expiry)
        exp_rt = math.exp(-risk_free_rate * time_to_expiry)

        # Gamma is the same for calls and puts
        gamma = pdf_d1 * exp_qt / (spot * volatility * sqrt_t)

        # Vega is the same for calls and puts (per 1 % change in vol)
        vega = spot * sqrt_t * pdf_d1 * exp_qt / 100.0

        if option_type == "call":
            delta = n_d1 * exp_qt
            theta = (
                -(
                    spot * pdf_d1 * volatility * exp_qt
                ) / (2.0 * sqrt_t)
                - risk_free_rate * strike * exp_rt * n_d2
                + dividend_yield * spot * exp_qt * n_d1
            ) / 365.0
            rho = strike * time_to_expiry * exp_rt * n_d2 / 100.0
        else:
            # Put
            delta = (n_d1 - 1.0) * exp_qt
            n_neg_d2 = _normal_cdf(-d2)
            n_neg_d1 = _normal_cdf(-d1)
            theta = (
                -(
                    spot * pdf_d1 * volatility * exp_qt
                ) / (2.0 * sqrt_t)
                + risk_free_rate * strike * exp_rt * n_neg_d2
                - dividend_yield * spot * exp_qt * n_neg_d1
            ) / 365.0
            rho = -strike * time_to_expiry * exp_rt * n_neg_d2 / 100.0

        return Greeks(
            delta=delta,
            gamma=gamma,
            theta=theta,
            vega=vega,
            rho=rho,
            implied_volatility=volatility,
        )

    # ------------------------------------------------------------------
    # Portfolio-level queries
    # ------------------------------------------------------------------

    def get_portfolio_summary(self) -> PortfolioPnL:
        """Aggregate P&L across all positions."""
        total_unrealized = sum(
            p.unrealized_pnl for p in self._positions.values()
        )
        total_realized = sum(
            p.realized_pnl for p in self._positions.values()
        )
        total_value = sum(
            p.market_price * abs(p.quantity)
            for p in self._positions.values()
        )
        total_cost = sum(
            p.avg_cost * abs(p.quantity) for p in self._positions.values()
        )

        return PortfolioPnL(
            total_unrealized_pnl=total_unrealized,
            total_realized_pnl=total_realized,
            total_pnl=total_unrealized + total_realized,
            total_value=total_value,
            total_cost=total_cost,
            position_count=len(self._positions),
            positions=dict(self._positions),
        )

    def get_position_pnl(self, symbol: str) -> Optional[PositionPnL]:
        """Get P&L for a specific position."""
        return self._positions.get(symbol)

    def get_all_positions(self) -> Dict[str, PositionPnL]:
        """Get P&L for all positions."""
        return dict(self._positions)

    def get_history(self, limit: int = 100) -> List[PortfolioPnL]:
        """Get historical P&L snapshots.

        Returns the most recent *limit* snapshots, ordered oldest first.
        """
        return list(self._history[-limit:])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _save_snapshot(self, snapshot: PortfolioPnL) -> None:
        """Save P&L snapshot to history with bounded size."""
        self._history.append(snapshot)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]
