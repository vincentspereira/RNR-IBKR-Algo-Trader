"""Tests for core_trading.portfolio.pairs_portfolio (Phase 4.5).

Covers:
* inverse_variance_weights: exact arithmetic, zero-direction, zero-variance exclusion.
* construct_pairs_portfolio: per-pair cap, leg expansion signs, sector cap,
  gross-leverage cap, beta neutralisation, symbol netting across pairs,
  empty-input edge case, all-zero spread_var edge case.
"""

from __future__ import annotations

import math

import pytest  # noqa: F401 (imported for pytest.raises)

from core_trading.portfolio.pairs_portfolio import (
    PairAllocation,
    PortfolioConfig,
    PortfolioWeights,
    construct_pairs_portfolio,
    inverse_variance_weights,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pair(
    pair_id: str,
    symbol_y: str,
    symbol_x: str,
    hedge_ratio: float = 1.0,
    direction: int = 1,
    spread_var: float = 1.0,
    sector: str | None = None,
) -> PairAllocation:
    return PairAllocation(
        pair_id=pair_id,
        symbol_y=symbol_y,
        symbol_x=symbol_x,
        hedge_ratio=hedge_ratio,
        direction=direction,
        spread_var=spread_var,
        sector=sector,
    )


# ---------------------------------------------------------------------------
# PortfolioConfig validation
# ---------------------------------------------------------------------------


class TestPortfolioConfigValidation:
    def test_default_config_is_valid(self) -> None:
        cfg = PortfolioConfig()
        assert cfg.gross_leverage_cap == 2.0
        assert cfg.sector_cap == 0.30
        assert cfg.per_pair_cap == 0.02
        assert cfg.beta_neutralize is True
        assert cfg.hedge_symbol == "SPY"

    def test_zero_gross_leverage_raises(self) -> None:
        with pytest.raises(ValueError, match="gross_leverage_cap"):
            PortfolioConfig(gross_leverage_cap=0.0)

    def test_negative_gross_leverage_raises(self) -> None:
        with pytest.raises(ValueError, match="gross_leverage_cap"):
            PortfolioConfig(gross_leverage_cap=-1.0)

    def test_sector_cap_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="sector_cap"):
            PortfolioConfig(sector_cap=0.0)

    def test_sector_cap_above_one_raises(self) -> None:
        with pytest.raises(ValueError, match="sector_cap"):
            PortfolioConfig(sector_cap=1.5)

    def test_per_pair_cap_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="per_pair_cap"):
            PortfolioConfig(per_pair_cap=0.0)

    def test_per_pair_cap_above_one_raises(self) -> None:
        with pytest.raises(ValueError, match="per_pair_cap"):
            PortfolioConfig(per_pair_cap=2.0)

    def test_sector_cap_exactly_one_is_valid(self) -> None:
        cfg = PortfolioConfig(sector_cap=1.0)
        assert cfg.sector_cap == 1.0


# ---------------------------------------------------------------------------
# inverse_variance_weights
# ---------------------------------------------------------------------------


class TestInverseVarianceWeights:
    def test_two_pairs_exact_arithmetic(self) -> None:
        """Textbook check: spread_var 1.0 and 3.0 give weights 3/4 and 1/4."""
        a1 = _make_pair("P1", "A", "B", spread_var=1.0, direction=1)
        a2 = _make_pair("P2", "C", "D", spread_var=3.0, direction=1)
        w = inverse_variance_weights([a1, a2])
        assert math.isclose(w["P1"], 0.75, rel_tol=1e-9)
        assert math.isclose(w["P2"], 0.25, rel_tol=1e-9)

    def test_normalises_to_one(self) -> None:
        pairs = [
            _make_pair("P1", "A", "B", spread_var=2.0),
            _make_pair("P2", "C", "D", spread_var=5.0),
            _make_pair("P3", "E", "F", spread_var=0.5),
        ]
        w = inverse_variance_weights(pairs)
        assert math.isclose(sum(w.values()), 1.0, rel_tol=1e-9)

    def test_direction_zero_excluded(self) -> None:
        a1 = _make_pair("P1", "A", "B", spread_var=1.0, direction=0)
        a2 = _make_pair("P2", "C", "D", spread_var=1.0, direction=1)
        w = inverse_variance_weights([a1, a2])
        assert w["P1"] == 0.0
        assert math.isclose(w["P2"], 1.0, rel_tol=1e-9)

    def test_non_positive_spread_var_excluded(self) -> None:
        a1 = _make_pair("P1", "A", "B", spread_var=0.0, direction=1)
        a2 = _make_pair("P2", "C", "D", spread_var=-1.0, direction=1)
        a3 = _make_pair("P3", "E", "F", spread_var=2.0, direction=1)
        w = inverse_variance_weights([a1, a2, a3])
        assert w["P1"] == 0.0
        assert w["P2"] == 0.0
        assert math.isclose(w["P3"], 1.0, rel_tol=1e-9)

    def test_all_excluded_returns_zeros(self) -> None:
        pairs = [
            _make_pair("P1", "A", "B", spread_var=1.0, direction=0),
            _make_pair("P2", "C", "D", spread_var=0.0, direction=1),
        ]
        w = inverse_variance_weights(pairs)
        assert all(v == 0.0 for v in w.values())

    def test_empty_returns_empty(self) -> None:
        assert inverse_variance_weights([]) == {}

    def test_single_eligible_pair_gets_weight_one(self) -> None:
        a = _make_pair("P1", "A", "B", spread_var=42.0)
        w = inverse_variance_weights([a])
        assert math.isclose(w["P1"], 1.0, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# construct_pairs_portfolio -- edge cases
# ---------------------------------------------------------------------------


class TestConstructEdgeCases:
    def test_empty_allocations(self) -> None:
        pw = construct_pairs_portfolio([])
        assert pw.weights == {}
        assert pw.gross_leverage == 0.0
        assert pw.net_beta == 0.0
        assert pw.sector_exposure == {}

    def test_all_zero_spread_var(self) -> None:
        pairs = [
            _make_pair("P1", "A", "B", spread_var=0.0),
            _make_pair("P2", "C", "D", spread_var=0.0),
        ]
        pw = construct_pairs_portfolio(pairs)
        assert pw.weights == {}
        assert pw.gross_leverage == 0.0

    def test_all_direction_zero(self) -> None:
        pairs = [
            _make_pair("P1", "A", "B", direction=0, spread_var=1.0),
            _make_pair("P2", "C", "D", direction=0, spread_var=2.0),
        ]
        pw = construct_pairs_portfolio(pairs)
        assert pw.gross_leverage == 0.0


# ---------------------------------------------------------------------------
# construct_pairs_portfolio -- per-pair cap
# ---------------------------------------------------------------------------


class TestPerPairCap:
    def test_cap_binds_on_single_large_pair(self) -> None:
        """A single pair gets raw weight 1.0, must be capped at per_pair_cap."""
        cfg = PortfolioConfig(
            per_pair_cap=0.02,
            gross_leverage_cap=10.0,
            sector_cap=1.0,
            beta_neutralize=False,
        )
        pair = _make_pair("P1", "AAPL", "MSFT", hedge_ratio=1.0, direction=1, spread_var=1.0)
        pw = construct_pairs_portfolio([pair], config=cfg)
        # y leg = +0.02, x leg = -1.0 * 0.02 = -0.02 -> gross = 0.04
        assert math.isclose(pw.weights["AAPL"], 0.02, rel_tol=1e-9)
        assert math.isclose(pw.weights["MSFT"], -0.02, rel_tol=1e-9)
        assert math.isclose(pw.gross_leverage, 0.04, rel_tol=1e-9)

    def test_cap_does_not_affect_smaller_weight(self) -> None:
        """When the raw weight is below the cap, no clipping occurs."""
        # Two equal pairs split the weight: each gets 0.5.
        # With per_pair_cap = 0.6, no clipping.
        cfg = PortfolioConfig(
            per_pair_cap=0.60,
            gross_leverage_cap=10.0,
            sector_cap=1.0,
            beta_neutralize=False,
        )
        p1 = _make_pair("P1", "A", "B", spread_var=1.0, direction=1, hedge_ratio=1.0)
        p2 = _make_pair("P2", "C", "D", spread_var=1.0, direction=1, hedge_ratio=1.0)
        pw = construct_pairs_portfolio([p1, p2], config=cfg)
        # Each pair gets 0.5; gross per pair = 1.0; total gross = 2.0
        assert math.isclose(pw.weights["A"], 0.5, rel_tol=1e-9)
        assert math.isclose(pw.weights["C"], 0.5, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# construct_pairs_portfolio -- leg expansion signs
# ---------------------------------------------------------------------------


class TestLegExpansionSigns:
    def test_direction_plus_one(self) -> None:
        """direction +1: long y, short x (short by hedge_ratio)."""
        cfg = PortfolioConfig(
            per_pair_cap=0.5,
            gross_leverage_cap=10.0,
            sector_cap=1.0,
            beta_neutralize=False,
        )
        pair = _make_pair("P1", "Y", "X", hedge_ratio=2.0, direction=1, spread_var=1.0)
        pw = construct_pairs_portfolio([pair], config=cfg)
        # raw weight = 1.0, capped at 0.5
        w = 0.5
        assert math.isclose(pw.weights["Y"], w, rel_tol=1e-9)
        assert math.isclose(pw.weights["X"], -2.0 * w, rel_tol=1e-9)

    def test_direction_minus_one(self) -> None:
        """direction -1: short y, long x (long by hedge_ratio)."""
        cfg = PortfolioConfig(
            per_pair_cap=0.5,
            gross_leverage_cap=10.0,
            sector_cap=1.0,
            beta_neutralize=False,
        )
        pair = _make_pair("P1", "Y", "X", hedge_ratio=2.0, direction=-1, spread_var=1.0)
        pw = construct_pairs_portfolio([pair], config=cfg)
        w = 0.5
        assert math.isclose(pw.weights["Y"], -w, rel_tol=1e-9)
        assert math.isclose(pw.weights["X"], 2.0 * w, rel_tol=1e-9)

    def test_hedge_ratio_scales_x_leg(self) -> None:
        """Confirm x-leg magnitude = w * hedge_ratio regardless of direction."""
        cfg = PortfolioConfig(
            per_pair_cap=1.0,
            gross_leverage_cap=10.0,
            sector_cap=1.0,
            beta_neutralize=False,
        )
        for hr in (0.5, 1.0, 3.0):
            pair = _make_pair("P1", "Y", "X", hedge_ratio=hr, direction=1, spread_var=1.0)
            pw = construct_pairs_portfolio([pair], config=cfg)
            assert math.isclose(abs(pw.weights["X"]), hr * abs(pw.weights["Y"]), rel_tol=1e-9)


# ---------------------------------------------------------------------------
# construct_pairs_portfolio -- symbol netting across pairs
# ---------------------------------------------------------------------------


class TestSymbolNetting:
    def test_opposing_legs_net_to_zero(self) -> None:
        """A symbol appearing as y in one pair and x in another with matching
        weights and direction should net to approximately zero."""
        cfg = PortfolioConfig(
            per_pair_cap=1.0,
            gross_leverage_cap=10.0,
            sector_cap=1.0,
            beta_neutralize=False,
        )
        # P1: long spread -> long COMMON short B
        # P2: long spread -> long A short COMMON
        # Both pairs same spread_var -> equal weight 0.5 each
        # COMMON: +0.5 (y-leg of P1) - 1.0*0.5 (x-leg of P2) = 0.0
        p1 = _make_pair("P1", "COMMON", "B", hedge_ratio=1.0, direction=1, spread_var=1.0)
        p2 = _make_pair("P2", "A", "COMMON", hedge_ratio=1.0, direction=1, spread_var=1.0)
        pw = construct_pairs_portfolio([p1, p2], config=cfg)
        assert math.isclose(pw.weights.get("COMMON", 0.0), 0.0, abs_tol=1e-9)

    def test_same_side_legs_accumulate(self) -> None:
        """A symbol as y-leg in two separate pairs accumulates weight."""
        cfg = PortfolioConfig(
            per_pair_cap=1.0,
            gross_leverage_cap=10.0,
            sector_cap=1.0,
            beta_neutralize=False,
        )
        # AAPL is y in both pairs; each pair weight = 0.5 (equal spread_var)
        p1 = _make_pair("P1", "AAPL", "B", hedge_ratio=1.0, direction=1, spread_var=1.0)
        p2 = _make_pair("P2", "AAPL", "C", hedge_ratio=1.0, direction=1, spread_var=1.0)
        pw = construct_pairs_portfolio([p1, p2], config=cfg)
        assert math.isclose(pw.weights["AAPL"], 1.0, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# construct_pairs_portfolio -- sector cap
# ---------------------------------------------------------------------------


class TestSectorCap:
    def test_sector_cap_enforced(self) -> None:
        """TECH pairs start at 50% of gross; sector_cap=0.40 must scale them down.

        Setup: 2 TECH pairs + 1 ENERGY pair + 1 uncategorised pair, all with
        equal spread_var.  Each pair receives raw weight 1/4.
        TECH gross = 2*(1/4 + 1/4)*hedge_ratio_correction... with hedge_ratio=1.0
        and direction=1, each pair contributes abs(w) + abs(-1*w) = 2*w = 0.5
        in gross.  Two TECH pairs -> TECH gross = 1.0; ENERGY + uncategorised
        = 0.5 + 0.5 = 1.0; total = 2.0; TECH fraction = 50% > 40%.

        After sector scaling TECH is at exactly 40%; ENERGY (25%) stays below cap.
        The uncategorised pair is not counted in any sector, so sector_cap does
        not constrain it.
        """
        cfg = PortfolioConfig(
            per_pair_cap=1.0,
            gross_leverage_cap=10.0,
            sector_cap=0.40,
            beta_neutralize=False,
        )
        tech1 = _make_pair("T1", "AAPL", "MSFT", spread_var=1.0, sector="TECH")
        tech2 = _make_pair("T2", "GOOGL", "META", spread_var=1.0, sector="TECH")
        energy = _make_pair("E1", "XOM", "CVX", spread_var=1.0, sector="ENERGY")
        # Uncategorised pair absorbs 25% of gross -> makes the cap feasible.
        uncat = _make_pair("U1", "GLD", "SLV", spread_var=1.0, sector=None)
        pw = construct_pairs_portfolio([tech1, tech2, energy, uncat], config=cfg)

        total_gross = pw.gross_leverage
        tech_gross = sum(
            abs(pw.weights.get(sym, 0.0)) for sym in ("AAPL", "MSFT", "GOOGL", "META")
        )
        assert tech_gross <= cfg.sector_cap * total_gross + 1e-9

    def test_non_breaching_sector_unchanged(self) -> None:
        """When sector is comfortably within cap, weights are not touched."""
        cfg = PortfolioConfig(
            per_pair_cap=1.0,
            gross_leverage_cap=10.0,
            sector_cap=0.90,
            beta_neutralize=False,
        )
        p1 = _make_pair("P1", "A", "B", spread_var=1.0, sector="TECH")
        p2 = _make_pair("P2", "C", "D", spread_var=1.0, sector="ENERGY")
        pw = construct_pairs_portfolio([p1, p2], config=cfg)
        tech_gross = sum(abs(pw.weights.get(s, 0.0)) for s in ("A", "B"))
        total_gross = pw.gross_leverage
        assert tech_gross <= cfg.sector_cap * total_gross + 1e-9

    def test_no_sector_no_sector_exposure(self) -> None:
        """Pairs without sector labels produce empty sector_exposure dict."""
        cfg = PortfolioConfig(beta_neutralize=False, gross_leverage_cap=10.0)
        p1 = _make_pair("P1", "A", "B")
        pw = construct_pairs_portfolio([p1], config=cfg)
        assert pw.sector_exposure == {}


# ---------------------------------------------------------------------------
# construct_pairs_portfolio -- gross leverage cap
# ---------------------------------------------------------------------------


class TestGrossLeverageCap:
    def test_gross_leverage_capped(self) -> None:
        """Large raw allocations must be scaled so gross == gross_leverage_cap."""
        cfg = PortfolioConfig(
            per_pair_cap=1.0,      # no per-pair clip
            gross_leverage_cap=2.0,
            sector_cap=1.0,
            beta_neutralize=False,
        )
        # Four equal pairs -> each gets weight 0.25 (magnitude per pair).
        # Each pair: y+0.25, x-0.25*hedge_ratio (1.0) -> gross per pair = 0.5.
        # Total gross without cap = 4 * 0.5 = 2.0; exactly at cap, no scale needed.
        # Switch to hedge_ratio=2.0: gross per pair = 0.75; total = 3.0 -> must cap.
        pairs = [
            _make_pair(f"P{i}", f"Y{i}", f"X{i}", hedge_ratio=2.0, spread_var=1.0)
            for i in range(4)
        ]
        pw = construct_pairs_portfolio(pairs, config=cfg)
        assert math.isclose(pw.gross_leverage, cfg.gross_leverage_cap, rel_tol=1e-9)

    def test_gross_leverage_below_cap_not_scaled(self) -> None:
        """When raw gross is below the cap, weights must remain unchanged."""
        cfg = PortfolioConfig(
            per_pair_cap=0.01,     # small cap -> tiny gross
            gross_leverage_cap=2.0,
            sector_cap=1.0,
            beta_neutralize=False,
        )
        pair = _make_pair("P1", "A", "B", hedge_ratio=1.0, spread_var=1.0)
        pw = construct_pairs_portfolio([pair], config=cfg)
        # Gross = 0.02 << 2.0
        assert pw.gross_leverage < cfg.gross_leverage_cap

    def test_gross_leverage_excludes_hedge_symbol(self) -> None:
        """gross_leverage must not include the beta-hedge leg."""
        cfg = PortfolioConfig(
            per_pair_cap=0.5,
            gross_leverage_cap=10.0,
            sector_cap=1.0,
            beta_neutralize=True,
            hedge_symbol="SPY",
        )
        pair = _make_pair("P1", "AAPL", "MSFT", hedge_ratio=1.0, spread_var=1.0)
        market_betas = {"AAPL": 1.2, "MSFT": 1.1}
        pw = construct_pairs_portfolio([pair], config=cfg, market_betas=market_betas)
        gross_without_spy = sum(
            abs(v) for sym, v in pw.weights.items() if sym != "SPY"
        )
        assert math.isclose(pw.gross_leverage, gross_without_spy, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# construct_pairs_portfolio -- beta neutralisation
# ---------------------------------------------------------------------------


class TestBetaNeutralisation:
    def _simple_pair_portfolio(
        self,
        betas: dict[str, float],
        direction: int = 1,
        hedge_ratio: float = 1.0,
    ) -> PortfolioWeights:
        cfg = PortfolioConfig(
            per_pair_cap=0.5,
            gross_leverage_cap=10.0,
            sector_cap=1.0,
            beta_neutralize=True,
            hedge_symbol="SPY",
        )
        pair = _make_pair("P1", "AAPL", "MSFT", hedge_ratio=hedge_ratio, direction=direction)
        return construct_pairs_portfolio([pair], config=cfg, market_betas=betas)

    def test_net_beta_near_zero(self) -> None:
        """After beta neutralisation, net portfolio beta should be ~0."""
        betas = {"AAPL": 1.3, "MSFT": 1.1, "SPY": 1.0}
        pw = self._simple_pair_portfolio(betas)
        assert abs(pw.net_beta) < 1e-9

    def test_hedge_weight_correct_sign(self) -> None:
        """If the pairs position is net long beta, the SPY hedge must be short."""
        # AAPL w=+0.5, beta=1.5; MSFT w=-0.5, beta=0.5
        # Portfolio beta from pairs = 0.5*1.5 + (-0.5)*0.5 = 0.75 - 0.25 = 0.50
        # hedge_weight = -0.50 (short SPY)
        betas = {"AAPL": 1.5, "MSFT": 0.5, "SPY": 1.0}
        pw = self._simple_pair_portfolio(betas, hedge_ratio=1.0, direction=1)
        assert pw.weights["SPY"] < 0.0

    def test_beta_neutralise_disabled(self) -> None:
        """When beta_neutralize=False, hedge symbol is absent."""
        cfg = PortfolioConfig(
            per_pair_cap=0.5,
            gross_leverage_cap=10.0,
            sector_cap=1.0,
            beta_neutralize=False,
        )
        pair = _make_pair("P1", "AAPL", "MSFT")
        betas = {"AAPL": 1.3, "MSFT": 1.1}
        pw = construct_pairs_portfolio([pair], config=cfg, market_betas=betas)
        assert "SPY" not in pw.weights

    def test_beta_neutralise_no_betas_provided(self) -> None:
        """When beta_neutralize=True but market_betas is None, no hedge."""
        cfg = PortfolioConfig(
            per_pair_cap=0.5,
            gross_leverage_cap=10.0,
            sector_cap=1.0,
            beta_neutralize=True,
        )
        pair = _make_pair("P1", "AAPL", "MSFT")
        pw = construct_pairs_portfolio([pair], config=cfg, market_betas=None)
        assert "SPY" not in pw.weights

    def test_net_beta_exact(self) -> None:
        """Cross-check the exact hedge weight calculation.

        AAPL weight = +0.5, beta = 2.0; MSFT weight = -0.5, beta = 0.0.
        Portfolio beta (before hedge) = 0.5*2.0 + (-0.5)*0.0 = 1.0.
        Hedge weight = -1.0 (short 1 unit of SPY).
        Net beta = 1.0 + (-1.0)*1.0 = 0.0.
        """
        betas = {"AAPL": 2.0, "MSFT": 0.0, "SPY": 1.0}
        pw = self._simple_pair_portfolio(betas, hedge_ratio=1.0, direction=1)
        assert math.isclose(pw.weights["SPY"], -1.0, rel_tol=1e-9)
        assert abs(pw.net_beta) < 1e-9


# ---------------------------------------------------------------------------
# construct_pairs_portfolio -- PortfolioWeights fields
# ---------------------------------------------------------------------------


class TestPortfolioWeightsFields:
    def test_returns_portfolio_weights_type(self) -> None:
        pair = _make_pair("P1", "A", "B")
        pw = construct_pairs_portfolio([pair])
        assert isinstance(pw, PortfolioWeights)

    def test_weights_is_dict(self) -> None:
        pair = _make_pair("P1", "A", "B")
        pw = construct_pairs_portfolio([pair])
        assert isinstance(pw.weights, dict)

    def test_sector_exposure_is_dict(self) -> None:
        pair = _make_pair("P1", "A", "B", sector="TECH")
        pw = construct_pairs_portfolio([pair])
        assert isinstance(pw.sector_exposure, dict)


# ---------------------------------------------------------------------------
# Integration: full pipeline with multiple pairs, all constraints active
# ---------------------------------------------------------------------------


class TestFullPipeline:
    def test_combined_constraints_respected(self) -> None:
        """Run a realistic multi-pair portfolio through all constraints."""
        cfg = PortfolioConfig(
            per_pair_cap=0.02,
            gross_leverage_cap=2.0,
            sector_cap=0.35,
            beta_neutralize=True,
            hedge_symbol="SPY",
        )
        pairs = [
            _make_pair("T1", "AAPL", "MSFT", hedge_ratio=0.9, spread_var=0.001, sector="TECH"),
            _make_pair("T2", "GOOGL", "META", hedge_ratio=1.1, spread_var=0.002, sector="TECH"),
            _make_pair("E1", "XOM", "CVX", hedge_ratio=0.8, spread_var=0.003, sector="ENERGY"),
            _make_pair("F1", "JPM", "BAC", hedge_ratio=1.2, spread_var=0.005, sector="FINANCE"),
        ]
        market_betas = {
            "AAPL": 1.2, "MSFT": 1.1,
            "GOOGL": 1.3, "META": 1.4,
            "XOM": 0.8, "CVX": 0.7,
            "JPM": 1.0, "BAC": 1.1,
            "SPY": 1.0,
        }
        pw = construct_pairs_portfolio(pairs, config=cfg, market_betas=market_betas)

        # Gross leverage <= cap
        assert pw.gross_leverage <= cfg.gross_leverage_cap + 1e-9

        # Sector exposures <= cap
        for sec, exposure in pw.sector_exposure.items():
            assert exposure <= cfg.sector_cap + 1e-9, f"{sec} exposure {exposure} > cap"

        # Net beta near zero
        assert abs(pw.net_beta) < 1e-9

        # All weights finite
        for sym, w in pw.weights.items():
            assert math.isfinite(w), f"{sym} weight {w} is not finite"
