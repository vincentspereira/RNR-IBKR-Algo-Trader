"""Unit tests for the P&L Tracker with Black-Scholes Greeks.

Covers:
- Data class creation and defaults
- PnLTracker initialisation and configuration
- Position P&L calculation (long/short, profit/loss, zero-quantity)
- Price updates and portfolio-wide recalculation
- Portfolio summary aggregation
- Snapshot history with bounded growth
- Black-Scholes Greeks across moneyness and edge cases
"""

import math
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from core_trading.analytics.pnl_tracker import (
    Greeks,
    PnLConfig,
    PnLTracker,
    PortfolioPnL,
    PositionInfo,
    PositionPnL,
)


# ======================================================================
# Data-class tests
# ======================================================================


class TestPnLDataClasses:
    """Tests for the data-class definitions."""

    def test_position_info_creation(self):
        pos = PositionInfo(symbol="AAPL", quantity=100, avg_cost=150.0)
        assert pos.symbol == "AAPL"
        assert pos.quantity == 100
        assert pos.avg_cost == 150.0
        assert pos.market_price == 0.0
        assert pos.realized_pnl == 0.0
        assert pos.asset_type == "equity"

    def test_greeks_creation(self):
        greeks = Greeks(delta=0.5, gamma=0.02, theta=-0.03, vega=0.15)
        assert greeks.delta == 0.5
        assert greeks.gamma == 0.02
        assert greeks.theta == -0.03
        assert greeks.vega == 0.15
        assert greeks.rho == 0.0
        assert greeks.implied_volatility == 0.0

    def test_position_pnl_creation(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        pnl = PositionPnL(
            symbol="MSFT",
            quantity=50,
            avg_cost=300.0,
            market_price=310.0,
            unrealized_pnl=500.0,
            realized_pnl=0.0,
            pnl_pct=3.33,
        )
        assert pnl.symbol == "MSFT"
        assert pnl.quantity == 50
        assert pnl.unrealized_pnl == 500.0
        assert pnl.asset_type == "equity"
        assert pnl.greeks is None

    def test_portfolio_pnl_creation(self):
        summary = PortfolioPnL(
            total_unrealized_pnl=1000.0,
            total_realized_pnl=-200.0,
            total_pnl=800.0,
            total_value=50000.0,
            total_cost=49200.0,
            position_count=3,
            positions={},
        )
        assert summary.total_unrealized_pnl == 1000.0
        assert summary.total_realized_pnl == -200.0
        assert summary.total_pnl == 800.0
        assert summary.position_count == 3
        assert summary.daily_pnl == 0.0
        assert summary.daily_pnl_pct == 0.0

    def test_pnl_config_defaults(self):
        config = PnLConfig()
        assert config.risk_free_rate == 0.05
        assert config.update_interval_seconds == 1.0
        assert config.max_position_age_days == 365


# ======================================================================
# PnL Tracker tests
# ======================================================================


class TestPnLTracker:
    """Tests for the PnLTracker class."""

    # -- Initialisation ---------------------------------------------------

    def test_initialization(self):
        tracker = PnLTracker()
        assert len(tracker._positions) == 0
        assert len(tracker._position_cache) == 0
        assert len(tracker._price_cache) == 0
        assert len(tracker._history) == 0
        assert tracker._config.risk_free_rate == 0.05

    def test_initialization_with_config(self):
        config = PnLConfig(
            risk_free_rate=0.03,
            update_interval_seconds=0.5,
            max_position_age_days=180,
        )
        tracker = PnLTracker(config=config)
        assert tracker._config.risk_free_rate == 0.03
        assert tracker._config.update_interval_seconds == 0.5
        assert tracker._config.max_position_age_days == 180

    # -- update_positions -------------------------------------------------

    @pytest.mark.asyncio
    async def test_update_positions_long(self):
        tracker = PnLTracker()
        positions = [
            PositionInfo(
                symbol="AAPL",
                quantity=100,
                avg_cost=150.0,
                market_price=155.0,
            )
        ]
        await tracker.update_positions(positions)

        pnl = tracker.get_position_pnl("AAPL")
        assert pnl is not None
        assert pnl.unrealized_pnl == pytest.approx(500.0)
        assert pnl.quantity == 100

    @pytest.mark.asyncio
    async def test_update_positions_short(self):
        tracker = PnLTracker()
        positions = [
            PositionInfo(
                symbol="TSLA",
                quantity=-50,
                avg_cost=200.0,
                market_price=190.0,
            )
        ]
        await tracker.update_positions(positions)

        pnl = tracker.get_position_pnl("TSLA")
        assert pnl is not None
        # Short profit: (200 - 190) * 50 = 500
        assert pnl.unrealized_pnl == pytest.approx(500.0)

    @pytest.mark.asyncio
    async def test_update_positions_multiple(self):
        tracker = PnLTracker()
        positions = [
            PositionInfo(
                symbol="AAPL", quantity=100, avg_cost=150.0, market_price=155.0
            ),
            PositionInfo(
                symbol="MSFT", quantity=50, avg_cost=300.0, market_price=310.0
            ),
        ]
        await tracker.update_positions(positions)

        all_pnl = tracker.get_all_positions()
        assert len(all_pnl) == 2
        assert "AAPL" in all_pnl
        assert "MSFT" in all_pnl

    @pytest.mark.asyncio
    async def test_update_positions_zero_quantity_skipped(self):
        """Positions with zero quantity still get an entry but zero P&L."""
        tracker = PnLTracker()
        positions = [
            PositionInfo(
                symbol="AAPL", quantity=0, avg_cost=150.0, market_price=155.0
            )
        ]
        await tracker.update_positions(positions)

        pnl = tracker.get_position_pnl("AAPL")
        assert pnl is not None
        assert pnl.unrealized_pnl == 0.0
        assert pnl.pnl_pct == 0.0

    # -- update_price -----------------------------------------------------

    @pytest.mark.asyncio
    async def test_update_price(self):
        tracker = PnLTracker()
        positions = [
            PositionInfo(
                symbol="AAPL", quantity=100, avg_cost=150.0, market_price=150.0
            )
        ]
        await tracker.update_positions(positions)

        # Now update the price
        await tracker.update_price("AAPL", 160.0)

        pnl = tracker.get_position_pnl("AAPL")
        assert pnl is not None
        assert pnl.market_price == 160.0
        assert pnl.unrealized_pnl == pytest.approx(1000.0)

    @pytest.mark.asyncio
    async def test_update_price_updates_position_pnl(self):
        tracker = PnLTracker()
        positions = [
            PositionInfo(
                symbol="AAPL", quantity=100, avg_cost=150.0, market_price=150.0
            )
        ]
        await tracker.update_positions(positions)

        # First update
        await tracker.update_price("AAPL", 140.0)
        pnl = tracker.get_position_pnl("AAPL")
        assert pnl.unrealized_pnl == pytest.approx(-1000.0)

        # Second update -- back to profit
        await tracker.update_price("AAPL", 160.0)
        pnl = tracker.get_position_pnl("AAPL")
        assert pnl.unrealized_pnl == pytest.approx(1000.0)

    # -- calculate_position_pnl -------------------------------------------

    def test_calculate_position_pnl_long_profit(self):
        tracker = PnLTracker()
        pos = PositionInfo(symbol="AAPL", quantity=100, avg_cost=150.0)
        result = tracker.calculate_position_pnl(pos, 160.0)
        assert result.unrealized_pnl == pytest.approx(1000.0)
        assert result.symbol == "AAPL"

    def test_calculate_position_pnl_long_loss(self):
        tracker = PnLTracker()
        pos = PositionInfo(symbol="AAPL", quantity=100, avg_cost=150.0)
        result = tracker.calculate_position_pnl(pos, 140.0)
        assert result.unrealized_pnl == pytest.approx(-1000.0)

    def test_calculate_position_pnl_short_profit(self):
        tracker = PnLTracker()
        pos = PositionInfo(symbol="AAPL", quantity=-100, avg_cost=150.0)
        result = tracker.calculate_position_pnl(pos, 140.0)
        # Short profit: (150 - 140) * 100 = 1000
        assert result.unrealized_pnl == pytest.approx(1000.0)

    def test_calculate_position_pnl_short_loss(self):
        tracker = PnLTracker()
        pos = PositionInfo(symbol="AAPL", quantity=-100, avg_cost=150.0)
        result = tracker.calculate_position_pnl(pos, 160.0)
        # Short loss: (150 - 160) * 100 = -1000
        assert result.unrealized_pnl == pytest.approx(-1000.0)

    def test_calculate_position_pnl_zero_quantity(self):
        tracker = PnLTracker()
        pos = PositionInfo(symbol="AAPL", quantity=0, avg_cost=150.0)
        result = tracker.calculate_position_pnl(pos, 160.0)
        assert result.unrealized_pnl == 0.0
        assert result.pnl_pct == 0.0

    def test_calculate_position_pnl_pct(self):
        tracker = PnLTracker()
        pos = PositionInfo(symbol="AAPL", quantity=100, avg_cost=100.0)
        result = tracker.calculate_position_pnl(pos, 110.0)
        assert result.pnl_pct == pytest.approx(10.0)

    def test_calculate_position_pnl_pct_with_zero_cost(self):
        """When avg_cost is zero, pnl_pct should be 0 to avoid division by zero."""
        tracker = PnLTracker()
        pos = PositionInfo(symbol="AAPL", quantity=100, avg_cost=0.0)
        result = tracker.calculate_position_pnl(pos, 10.0)
        assert result.pnl_pct == 0.0

    # -- Portfolio summary ------------------------------------------------

    def test_get_portfolio_summary(self):
        tracker = PnLTracker()
        tracker._positions = {
            "AAPL": PositionPnL(
                symbol="AAPL",
                quantity=100,
                avg_cost=150.0,
                market_price=160.0,
                unrealized_pnl=1000.0,
                realized_pnl=200.0,
                pnl_pct=6.67,
            ),
            "MSFT": PositionPnL(
                symbol="MSFT",
                quantity=50,
                avg_cost=300.0,
                market_price=310.0,
                unrealized_pnl=500.0,
                realized_pnl=-100.0,
                pnl_pct=3.33,
            ),
        }
        summary = tracker.get_portfolio_summary()
        assert summary.total_unrealized_pnl == pytest.approx(1500.0)
        assert summary.total_realized_pnl == pytest.approx(100.0)
        assert summary.total_pnl == pytest.approx(1600.0)
        assert summary.position_count == 2

    def test_get_portfolio_summary_empty(self):
        tracker = PnLTracker()
        summary = tracker.get_portfolio_summary()
        assert summary.total_unrealized_pnl == 0.0
        assert summary.total_realized_pnl == 0.0
        assert summary.total_pnl == 0.0
        assert summary.total_value == 0.0
        assert summary.total_cost == 0.0
        assert summary.position_count == 0

    # -- Individual position lookups --------------------------------------

    def test_get_position_pnl_existing(self):
        tracker = PnLTracker()
        tracker._positions["AAPL"] = PositionPnL(
            symbol="AAPL",
            quantity=100,
            avg_cost=150.0,
            market_price=160.0,
            unrealized_pnl=1000.0,
            realized_pnl=0.0,
            pnl_pct=6.67,
        )
        pnl = tracker.get_position_pnl("AAPL")
        assert pnl is not None
        assert pnl.symbol == "AAPL"

    def test_get_position_pnl_nonexistent(self):
        tracker = PnLTracker()
        pnl = tracker.get_position_pnl("NONEXISTENT")
        assert pnl is None

    def test_get_all_positions(self):
        tracker = PnLTracker()
        tracker._positions = {
            "AAPL": PositionPnL(
                symbol="AAPL",
                quantity=100,
                avg_cost=150.0,
                market_price=160.0,
                unrealized_pnl=1000.0,
                realized_pnl=0.0,
                pnl_pct=6.67,
            ),
        }
        all_pnl = tracker.get_all_positions()
        assert len(all_pnl) == 1
        assert "AAPL" in all_pnl

    # -- History ----------------------------------------------------------

    def test_get_history(self):
        tracker = PnLTracker()
        for i in range(5):
            tracker._history.append(
                PortfolioPnL(
                    total_unrealized_pnl=float(i),
                    total_realized_pnl=0.0,
                    total_pnl=float(i),
                    total_value=10000.0,
                    total_cost=10000.0,
                    position_count=1,
                    positions={},
                )
            )
        history = tracker.get_history(limit=3)
        assert len(history) == 3
        assert history[0].total_unrealized_pnl == 2.0
        assert history[2].total_unrealized_pnl == 4.0

    def test_save_snapshot_respects_max_history(self):
        tracker = PnLTracker()
        tracker._max_history = 5

        for i in range(10):
            snapshot = PortfolioPnL(
                total_unrealized_pnl=float(i),
                total_realized_pnl=0.0,
                total_pnl=float(i),
                total_value=10000.0,
                total_cost=10000.0,
                position_count=1,
                positions={},
            )
            tracker._save_snapshot(snapshot)

        assert len(tracker._history) == 5
        # Should keep the last 5 snapshots (indices 5..9)
        assert tracker._history[0].total_unrealized_pnl == 5.0
        assert tracker._history[4].total_unrealized_pnl == 9.0

    # -- update_pnl (full recalculation) ----------------------------------

    @pytest.mark.asyncio
    async def test_update_pnl_recalculates_all(self):
        tracker = PnLTracker()
        tracker._position_cache = {
            "AAPL": PositionInfo(
                symbol="AAPL", quantity=100, avg_cost=150.0, market_price=0.0
            ),
            "MSFT": PositionInfo(
                symbol="MSFT", quantity=50, avg_cost=300.0, market_price=0.0
            ),
        }
        tracker._price_cache = {
            "AAPL": 160.0,
            "MSFT": 310.0,
        }

        result = await tracker.update_pnl()

        assert len(result) == 2
        assert result["AAPL"].unrealized_pnl == pytest.approx(1000.0)
        assert result["MSFT"].unrealized_pnl == pytest.approx(500.0)
        # Should have saved a snapshot
        assert len(tracker._history) == 1


# ======================================================================
# Black-Scholes Greeks tests
# ======================================================================


class TestGreeks:
    """Tests for Black-Scholes Greeks calculations.

    Standard test parameters:
        spot  = 100
        strike = 100  (ATM)
        T     = 0.25  (3 months)
        r     = 0.05  (5 %)
        sigma = 0.20  (20 %)
    """

    def _tracker(self) -> PnLTracker:
        return PnLTracker()

    def test_greeks_call_atm(self):
        """ATM call delta should be close to 0.5.

        With a positive risk-free rate the forward exceeds spot, so ATM call
        delta is slightly above 0.5 (approximately 0.57 with these params).
        """
        greeks = self._tracker().calculate_greeks(
            spot=100, strike=100, time_to_expiry=0.25,
            risk_free_rate=0.05, volatility=0.20, option_type="call",
        )
        assert 0.45 < greeks.delta < 0.65

    def test_greeks_put_atm(self):
        """ATM put delta should be close to -0.5.

        With a positive risk-free rate the forward exceeds spot, so ATM put
        delta is slightly above -0.5 (approximately -0.43 with these params).
        """
        greeks = self._tracker().calculate_greeks(
            spot=100, strike=100, time_to_expiry=0.25,
            risk_free_rate=0.05, volatility=0.20, option_type="put",
        )
        assert -0.55 < greeks.delta < -0.35

    def test_greeks_call_itm(self):
        """ITM call (spot >> strike) should have delta > 0.5."""
        greeks = self._tracker().calculate_greeks(
            spot=120, strike=100, time_to_expiry=0.25,
            risk_free_rate=0.05, volatility=0.20, option_type="call",
        )
        assert greeks.delta > 0.5

    def test_greeks_call_otm(self):
        """OTM call (spot << strike) should have delta < 0.5."""
        greeks = self._tracker().calculate_greeks(
            spot=80, strike=100, time_to_expiry=0.25,
            risk_free_rate=0.05, volatility=0.20, option_type="call",
        )
        assert greeks.delta < 0.5

    def test_greeks_put_itm(self):
        """ITM put (spot << strike) should have delta < -0.5."""
        greeks = self._tracker().calculate_greeks(
            spot=80, strike=100, time_to_expiry=0.25,
            risk_free_rate=0.05, volatility=0.20, option_type="put",
        )
        assert greeks.delta < -0.5

    def test_greeks_put_otm(self):
        """OTM put (spot >> strike) should have delta > -0.5."""
        greeks = self._tracker().calculate_greeks(
            spot=120, strike=100, time_to_expiry=0.25,
            risk_free_rate=0.05, volatility=0.20, option_type="put",
        )
        assert greeks.delta > -0.5

    def test_greeks_gamma_positive(self):
        """Gamma is always positive for both calls and puts."""
        greeks = self._tracker().calculate_greeks(
            spot=100, strike=100, time_to_expiry=0.25,
            risk_free_rate=0.05, volatility=0.20, option_type="call",
        )
        assert greeks.gamma > 0

    def test_greeks_theta_negative_for_long(self):
        """Theta is negative for long option positions (time decay)."""
        greeks = self._tracker().calculate_greeks(
            spot=100, strike=100, time_to_expiry=0.25,
            risk_free_rate=0.05, volatility=0.20, option_type="call",
        )
        assert greeks.theta < 0

    def test_greeks_vega_positive(self):
        """Vega is always positive for both calls and puts."""
        greeks = self._tracker().calculate_greeks(
            spot=100, strike=100, time_to_expiry=0.25,
            risk_free_rate=0.05, volatility=0.20, option_type="call",
        )
        assert greeks.vega > 0

    def test_greeks_rho_call_positive(self):
        """Rho is positive for calls (higher rates increase call value)."""
        greeks = self._tracker().calculate_greeks(
            spot=100, strike=100, time_to_expiry=0.25,
            risk_free_rate=0.05, volatility=0.20, option_type="call",
        )
        assert greeks.rho > 0

    def test_greeks_rho_put_negative(self):
        """Rho is negative for puts (higher rates decrease put value)."""
        greeks = self._tracker().calculate_greeks(
            spot=100, strike=100, time_to_expiry=0.25,
            risk_free_rate=0.05, volatility=0.20, option_type="put",
        )
        assert greeks.rho < 0

    def test_greeks_zero_time_to_expiry(self):
        """At expiry, gamma/theta/vega/rho are 0; delta is binary."""
        tracker = self._tracker()

        # ITM call at expiry -> delta ~1
        greeks = tracker.calculate_greeks(
            spot=110, strike=100, time_to_expiry=0.0,
            risk_free_rate=0.05, volatility=0.20, option_type="call",
        )
        assert greeks.delta == 1.0
        assert greeks.gamma == 0.0
        assert greeks.theta == 0.0
        assert greeks.vega == 0.0

        # OTM call at expiry -> delta ~0
        greeks = tracker.calculate_greeks(
            spot=90, strike=100, time_to_expiry=0.0,
            risk_free_rate=0.05, volatility=0.20, option_type="call",
        )
        assert greeks.delta == 0.0

        # ITM put at expiry -> delta ~-1
        greeks = tracker.calculate_greeks(
            spot=90, strike=100, time_to_expiry=0.0,
            risk_free_rate=0.05, volatility=0.20, option_type="put",
        )
        assert greeks.delta == -1.0

        # OTM put at expiry -> delta ~0
        greeks = tracker.calculate_greeks(
            spot=110, strike=100, time_to_expiry=0.0,
            risk_free_rate=0.05, volatility=0.20, option_type="put",
        )
        assert greeks.delta == 0.0

    def test_greeks_zero_volatility(self):
        """Zero volatility returns all-zero Greeks."""
        greeks = self._tracker().calculate_greeks(
            spot=100, strike=100, time_to_expiry=0.25,
            risk_free_rate=0.05, volatility=0.0, option_type="call",
        )
        assert greeks.delta == 0.0
        assert greeks.gamma == 0.0
        assert greeks.theta == 0.0
        assert greeks.vega == 0.0
        assert greeks.rho == 0.0

    def test_greeks_dataclass(self):
        """Verify the Greeks dataclass holds implied volatility."""
        greeks = self._tracker().calculate_greeks(
            spot=100, strike=100, time_to_expiry=0.25,
            risk_free_rate=0.05, volatility=0.25, option_type="call",
        )
        assert greeks.implied_volatility == 0.25

    def test_greeks_with_dividend_yield(self):
        """Verify dividend yield shifts call delta downward."""
        tracker = self._tracker()

        greeks_no_div = tracker.calculate_greeks(
            spot=100, strike=100, time_to_expiry=0.25,
            risk_free_rate=0.05, volatility=0.20,
            option_type="call", dividend_yield=0.0,
        )
        greeks_with_div = tracker.calculate_greeks(
            spot=100, strike=100, time_to_expiry=0.25,
            risk_free_rate=0.05, volatility=0.20,
            option_type="call", dividend_yield=0.03,
        )
        # Dividends reduce call delta
        assert greeks_with_div.delta < greeks_no_div.delta

    def test_greeks_negative_time_to_expiry(self):
        """Negative time to expiry is treated as expired."""
        greeks = self._tracker().calculate_greeks(
            spot=110, strike=100, time_to_expiry=-0.1,
            risk_free_rate=0.05, volatility=0.20, option_type="call",
        )
        assert greeks.delta == 1.0
        assert greeks.gamma == 0.0
