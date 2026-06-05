"""Tests for core_trading.risk.pretrade (Phase 7, module 7.1).

Coverage targets
----------------
* Unit: each of the six checks (liquidity, concentration, exposure, margin,
  restricted, kill_switch) pass / fail at exact boundary values (<= vs <
  semantics pinned); multiple simultaneous failures all reported; kill switch
  overrides everything; case-insensitivity of restricted list; short side
  handled.
* Integration: real PairOrder -> gate_pair_order -> PairExecutor; passing
  order proceeds to fill; failing order (restricted symbol / kill switch)
  blocked before execution.

All assertion messages are ASCII only.
"""
from __future__ import annotations

import threading

import pytest

from core_trading.execution.pairs_execution import (
    DeterministicFillModel,
    ExecutionConfig,
    Leg,
    PairExecutor,
    PairOrder,
)
from core_trading.risk.pairs_risk import RiskCheck
from core_trading.risk.pretrade import (
    CheckDetail,
    GateConfig,
    PairGateResult,
    PortfolioState,
    PreTradeDecision,
    PreTradeGate,
    ProposedOrder,
    gate_pair_order,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _base_state(
    nav: float = 100_000.0,
    positions: dict[str, float] | None = None,
    available_margin: float = 50_000.0,
    adv: dict[str, float] | None = None,
    position_prices: dict[str, float] | None = None,
) -> PortfolioState:
    return PortfolioState(
        nav=nav,
        positions=positions or {},
        available_margin=available_margin,
        adv=adv,
        position_prices=position_prices,
    )


def _order(
    symbol: str = "AAPL",
    side: str = "buy",
    quantity: float = 100.0,
    price: float = 100.0,
    asset_class: str = "equity",
) -> ProposedOrder:
    return ProposedOrder(
        symbol=symbol,
        side=side,  # type: ignore[arg-type]
        quantity=quantity,
        price=price,
        asset_class=asset_class,  # type: ignore[arg-type]
    )


def _gate(
    adv_participation_cap: float = 0.10,
    concentration_cap: float = 0.05,
    gross_exposure_cap: float = 2.0,
    net_exposure_cap: float = 1.0,
    default_margin_rate: float = 0.50,
    restricted_symbols: frozenset[str] | None = None,
) -> PreTradeGate:
    cfg = GateConfig(
        adv_participation_cap=adv_participation_cap,
        concentration_cap=concentration_cap,
        gross_exposure_cap=gross_exposure_cap,
        net_exposure_cap=net_exposure_cap,
        default_margin_rate=default_margin_rate,
        restricted_symbols=restricted_symbols or frozenset(),
    )
    return PreTradeGate(config=cfg)


# ---------------------------------------------------------------------------
# ProposedOrder validation
# ---------------------------------------------------------------------------


class TestProposedOrder:
    def test_notional_buy(self) -> None:
        o = _order(side="buy", quantity=100.0, price=50.0)
        assert o.notional == pytest.approx(5_000.0)
        assert o.abs_notional == pytest.approx(5_000.0)

    def test_notional_sell(self) -> None:
        o = _order(side="sell", quantity=100.0, price=50.0)
        assert o.notional == pytest.approx(-5_000.0)
        assert o.abs_notional == pytest.approx(5_000.0)

    def test_invalid_quantity(self) -> None:
        with pytest.raises(ValueError, match="quantity must be > 0"):
            ProposedOrder("AAPL", "buy", 0.0, 100.0)

    def test_invalid_price(self) -> None:
        with pytest.raises(ValueError, match="price must be > 0"):
            ProposedOrder("AAPL", "buy", 10.0, 0.0)

    def test_invalid_side(self) -> None:
        with pytest.raises(ValueError, match="side must be"):
            ProposedOrder("AAPL", "long", 10.0, 100.0)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# PortfolioState helpers
# ---------------------------------------------------------------------------


class TestPortfolioState:
    def test_invalid_nav(self) -> None:
        with pytest.raises(ValueError, match="nav must be > 0"):
            PortfolioState(nav=0.0, positions={}, available_margin=1000.0)

    def test_invalid_margin(self) -> None:
        with pytest.raises(ValueError, match="available_margin must be >= 0"):
            PortfolioState(nav=1000.0, positions={}, available_margin=-1.0)

    def test_post_trade_buy_new_position(self) -> None:
        state = _base_state(positions={})
        o = _order(symbol="AAPL", side="buy", quantity=100.0)
        assert state.post_trade_position(o) == pytest.approx(100.0)

    def test_post_trade_sell_new_position(self) -> None:
        state = _base_state(positions={})
        o = _order(symbol="AAPL", side="sell", quantity=100.0)
        assert state.post_trade_position(o) == pytest.approx(-100.0)

    def test_post_trade_buy_add_to_long(self) -> None:
        state = _base_state(positions={"AAPL": 200.0})
        o = _order(symbol="AAPL", side="buy", quantity=50.0)
        assert state.post_trade_position(o) == pytest.approx(250.0)

    def test_post_trade_sell_reduce_long(self) -> None:
        state = _base_state(positions={"AAPL": 200.0})
        o = _order(symbol="AAPL", side="sell", quantity=50.0)
        assert state.post_trade_position(o) == pytest.approx(150.0)

    def test_gross_exposure_increases_on_buy(self) -> None:
        state = _base_state(nav=100_000.0, positions={}, position_prices={})
        o = _order(symbol="AAPL", side="buy", quantity=100.0, price=100.0)
        assert state.gross_exposure(o) == pytest.approx(10_000.0)

    def test_net_exposure_positive_on_buy(self) -> None:
        state = _base_state(nav=100_000.0, positions={})
        o = _order(symbol="AAPL", side="buy", quantity=100.0, price=100.0)
        assert state.net_exposure(o) == pytest.approx(10_000.0)

    def test_net_exposure_negative_on_sell(self) -> None:
        state = _base_state(nav=100_000.0, positions={})
        o = _order(symbol="AAPL", side="sell", quantity=100.0, price=100.0)
        assert state.net_exposure(o) == pytest.approx(-10_000.0)

    def test_gross_exposure_does_not_double_count(self) -> None:
        # Buy replaces existing long: gross should reflect only new size.
        state = _base_state(
            nav=100_000.0,
            positions={"AAPL": 50.0},
            position_prices={"AAPL": 100.0},
        )
        o = _order(symbol="AAPL", side="buy", quantity=50.0, price=100.0)
        # Old abs = 50*100=5000, new abs = 100*100=10000, delta=5000
        assert state.gross_exposure(o) == pytest.approx(10_000.0)


# ---------------------------------------------------------------------------
# GateConfig validation
# ---------------------------------------------------------------------------


class TestGateConfig:
    def test_invalid_adv_participation_cap(self) -> None:
        with pytest.raises(ValueError, match="adv_participation_cap"):
            GateConfig(adv_participation_cap=0.0)

    def test_invalid_concentration_cap(self) -> None:
        with pytest.raises(ValueError, match="concentration_cap"):
            GateConfig(concentration_cap=1.5)

    def test_invalid_gross_exposure_cap(self) -> None:
        with pytest.raises(ValueError, match="gross_exposure_cap"):
            GateConfig(gross_exposure_cap=0.0)

    def test_invalid_net_exposure_cap(self) -> None:
        with pytest.raises(ValueError, match="net_exposure_cap"):
            GateConfig(net_exposure_cap=-1.0)

    def test_invalid_default_margin_rate(self) -> None:
        with pytest.raises(ValueError, match="default_margin_rate"):
            GateConfig(default_margin_rate=0.0)

    def test_invalid_per_class_margin_rate(self) -> None:
        with pytest.raises(ValueError, match="margin_rates"):
            GateConfig(margin_rates={"equity": 0.0})

    def test_margin_rate_lookup_default(self) -> None:
        cfg = GateConfig(default_margin_rate=0.30)
        assert cfg.margin_rate_for("equity") == pytest.approx(0.30)

    def test_margin_rate_lookup_custom(self) -> None:
        cfg = GateConfig(margin_rates={"equity": 0.25}, default_margin_rate=0.50)
        assert cfg.margin_rate_for("equity") == pytest.approx(0.25)
        assert cfg.margin_rate_for("futures") == pytest.approx(0.50)


# ---------------------------------------------------------------------------
# Check 1: Liquidity
# ---------------------------------------------------------------------------


class TestLiquidityCheck:
    def _gate_with_cap(self, cap: float) -> PreTradeGate:
        return _gate(adv_participation_cap=cap)

    def test_passes_at_exact_boundary(self) -> None:
        """qty == adv * cap must PASS (<= boundary)."""
        # adv=1000, cap=0.10 -> limit=100; qty=100 must pass
        gate = self._gate_with_cap(0.10)
        state = _base_state(adv={"AAPL": 1_000.0})
        o = _order(quantity=100.0, price=1.0)
        dec = gate.evaluate(o, state)
        liq = next(c for c in dec.checks if c.check_name == "liquidity")
        assert liq.passed, f"Expected pass at boundary, got: {liq.message}"

    def test_fails_above_boundary(self) -> None:
        """qty == adv * cap + 1 must FAIL (> boundary)."""
        gate = self._gate_with_cap(0.10)
        state = _base_state(adv={"AAPL": 1_000.0})
        o = _order(quantity=100.1, price=1.0)
        dec = gate.evaluate(o, state)
        liq = next(c for c in dec.checks if c.check_name == "liquidity")
        assert not liq.passed
        assert "FAIL" in liq.message
        assert liq.limit is not None
        assert liq.observed is not None

    def test_no_adv_data_skips_check(self) -> None:
        gate = self._gate_with_cap(0.10)
        state = _base_state(adv=None)
        o = _order(quantity=1_000_000.0, price=1.0)  # huge qty
        dec = gate.evaluate(o, state)
        liq = next(c for c in dec.checks if c.check_name == "liquidity")
        assert liq.passed  # skip is pass-through
        assert "no ADV data" in liq.message

    def test_symbol_missing_from_adv_skips(self) -> None:
        gate = self._gate_with_cap(0.10)
        state = _base_state(adv={"MSFT": 10_000.0})  # AAPL not present
        o = _order(symbol="AAPL", quantity=999_999.0, price=1.0)
        dec = gate.evaluate(o, state)
        liq = next(c for c in dec.checks if c.check_name == "liquidity")
        assert liq.passed


# ---------------------------------------------------------------------------
# Check 2: Concentration
# ---------------------------------------------------------------------------


class TestConcentrationCheck:
    def test_passes_at_exact_boundary(self) -> None:
        """pos_frac == concentration_cap must PASS."""
        # nav=100_000, cap=0.05 -> limit_value=5_000; qty*price=5_000 -> frac=0.05 -> pass
        gate = _gate(concentration_cap=0.05)
        state = _base_state(nav=100_000.0)
        o = _order(quantity=50.0, price=100.0)  # notional=5000, frac=0.05
        dec = gate.evaluate(o, state)
        c = next(ch for ch in dec.checks if ch.check_name == "concentration")
        assert c.passed, f"Expected pass at boundary: {c.message}"

    def test_fails_above_boundary(self) -> None:
        """pos_frac slightly above cap must FAIL."""
        gate = _gate(concentration_cap=0.05)
        state = _base_state(nav=100_000.0)
        o = _order(quantity=51.0, price=100.0)  # notional=5100, frac=0.051
        dec = gate.evaluate(o, state)
        c = next(ch for ch in dec.checks if ch.check_name == "concentration")
        assert not c.passed
        assert "FAIL" in c.message

    def test_existing_position_combined(self) -> None:
        """Post-trade value = existing + new; checks combined."""
        gate = _gate(concentration_cap=0.05)
        state = _base_state(
            nav=100_000.0,
            positions={"AAPL": 25.0},
            position_prices={"AAPL": 100.0},
        )
        # Existing=2500, add 25 more at 100 -> post=5000, frac=0.05 -> pass
        o = _order(quantity=25.0, price=100.0)
        dec = gate.evaluate(o, state)
        c = next(ch for ch in dec.checks if ch.check_name == "concentration")
        assert c.passed

    def test_short_side_uses_absolute_value(self) -> None:
        """Sell-side orders: concentration uses abs(post_trade_value)."""
        gate = _gate(concentration_cap=0.05)
        state = _base_state(nav=100_000.0)
        o = _order(side="sell", quantity=51.0, price=100.0)  # short = -5100
        dec = gate.evaluate(o, state)
        c = next(ch for ch in dec.checks if ch.check_name == "concentration")
        # abs(pos_val/nav)=0.051 > 0.05 -> fail
        assert not c.passed


# ---------------------------------------------------------------------------
# Check 3: Aggregate Exposure
# ---------------------------------------------------------------------------


class TestExposureCheck:
    def test_gross_passes_at_boundary(self) -> None:
        """gross == gross_cap * nav must PASS."""
        # nav=100_000, gross_cap=2.0 -> limit=200_000
        gate = _gate(gross_exposure_cap=2.0, net_exposure_cap=5.0)
        state = _base_state(nav=100_000.0)
        # Buy 2000 shares at 100 -> gross = 200_000
        o = _order(quantity=2_000.0, price=100.0)
        dec = gate.evaluate(o, state)
        g = next(ch for ch in dec.checks if ch.check_name == "exposure_gross")
        assert g.passed, f"Expected pass: {g.message}"

    def test_gross_fails_above_boundary(self) -> None:
        gate = _gate(gross_exposure_cap=2.0, net_exposure_cap=5.0)
        state = _base_state(nav=100_000.0)
        o = _order(quantity=2_001.0, price=100.0)
        dec = gate.evaluate(o, state)
        g = next(ch for ch in dec.checks if ch.check_name == "exposure_gross")
        assert not g.passed

    def test_net_passes_at_boundary(self) -> None:
        """abs(net) == net_cap * nav must PASS."""
        gate = _gate(gross_exposure_cap=5.0, net_exposure_cap=1.0)
        state = _base_state(nav=100_000.0)
        # Buy 1000@100 -> net=100_000 = 1.0*nav -> pass
        o = _order(quantity=1_000.0, price=100.0)
        dec = gate.evaluate(o, state)
        n = next(ch for ch in dec.checks if ch.check_name == "exposure_net")
        assert n.passed, f"Expected pass: {n.message}"

    def test_net_fails_above_boundary(self) -> None:
        gate = _gate(gross_exposure_cap=5.0, net_exposure_cap=1.0)
        state = _base_state(nav=100_000.0)
        o = _order(quantity=1_001.0, price=100.0)
        dec = gate.evaluate(o, state)
        n = next(ch for ch in dec.checks if ch.check_name == "exposure_net")
        assert not n.passed

    def test_net_exposure_short_side(self) -> None:
        """Net exposure from a short order is negative; abs is used for cap."""
        gate = _gate(gross_exposure_cap=5.0, net_exposure_cap=1.0)
        state = _base_state(nav=100_000.0)
        o = _order(side="sell", quantity=1_001.0, price=100.0)
        dec = gate.evaluate(o, state)
        n = next(ch for ch in dec.checks if ch.check_name == "exposure_net")
        assert not n.passed  # abs(-100100) > 100000

    def test_both_exposure_checks_present(self) -> None:
        gate = _gate()
        state = _base_state(nav=100_000.0)
        o = _order(quantity=1.0, price=1.0)
        dec = gate.evaluate(o, state)
        names = [ch.check_name for ch in dec.checks]
        assert "exposure_gross" in names
        assert "exposure_net" in names


# ---------------------------------------------------------------------------
# Check 4: Margin
# ---------------------------------------------------------------------------


class TestMarginCheck:
    def test_passes_at_boundary(self) -> None:
        """required_margin == available_margin must PASS."""
        # available=10_000, notional=20_000, rate=0.50 -> required=10_000
        gate = _gate(default_margin_rate=0.50)
        state = _base_state(available_margin=10_000.0, nav=1_000_000.0)
        o = _order(quantity=200.0, price=100.0)  # notional=20_000
        dec = gate.evaluate(o, state)
        m = next(ch for ch in dec.checks if ch.check_name == "margin")
        assert m.passed, f"Expected pass at boundary: {m.message}"
        assert m.observed == pytest.approx(10_000.0)
        assert m.limit == pytest.approx(10_000.0)

    def test_fails_above_boundary(self) -> None:
        gate = _gate(default_margin_rate=0.50)
        state = _base_state(available_margin=9_999.0, nav=1_000_000.0)
        o = _order(quantity=200.0, price=100.0)  # notional=20_000, required=10_000
        dec = gate.evaluate(o, state)
        m = next(ch for ch in dec.checks if ch.check_name == "margin")
        assert not m.passed
        assert "FAIL" in m.message

    def test_sell_uses_abs_notional(self) -> None:
        """Short side: margin is based on abs notional."""
        gate = _gate(default_margin_rate=0.50)
        state = _base_state(available_margin=10_000.0, nav=1_000_000.0)
        o = _order(side="sell", quantity=200.0, price=100.0)
        dec = gate.evaluate(o, state)
        m = next(ch for ch in dec.checks if ch.check_name == "margin")
        assert m.passed  # required=10_000 <= 10_000

    def test_per_asset_class_rate(self) -> None:
        """Custom margin rate for futures."""
        cfg = GateConfig(
            margin_rates={"futures": 0.10},
            default_margin_rate=0.50,
            gross_exposure_cap=100.0,
            net_exposure_cap=100.0,
            concentration_cap=1.0,
        )
        gate = PreTradeGate(config=cfg)
        state = _base_state(available_margin=1_000.0, nav=1_000_000.0)
        # notional=10_000, futures rate=0.10, required=1_000 -> pass
        o = ProposedOrder("CL", "buy", 100.0, 100.0, "futures")
        dec = gate.evaluate(o, state)
        m = next(ch for ch in dec.checks if ch.check_name == "margin")
        assert m.passed
        assert m.observed == pytest.approx(1_000.0)


# ---------------------------------------------------------------------------
# Check 5: Restricted list
# ---------------------------------------------------------------------------


class TestRestrictedCheck:
    def test_not_restricted_passes(self) -> None:
        gate = _gate(restricted_symbols=frozenset({"XYZ"}))
        state = _base_state(nav=1_000_000.0, available_margin=500_000.0)
        o = _order(symbol="AAPL")
        dec = gate.evaluate(o, state)
        r = next(ch for ch in dec.checks if ch.check_name == "restricted")
        assert r.passed

    def test_restricted_fails(self) -> None:
        gate = _gate(restricted_symbols=frozenset({"AAPL"}))
        state = _base_state(nav=1_000_000.0, available_margin=500_000.0)
        o = _order(symbol="AAPL")
        dec = gate.evaluate(o, state)
        r = next(ch for ch in dec.checks if ch.check_name == "restricted")
        assert not r.passed
        assert "restricted list" in r.message

    def test_case_insensitive_upper(self) -> None:
        gate = _gate(restricted_symbols=frozenset({"aapl"}))
        state = _base_state(nav=1_000_000.0, available_margin=500_000.0)
        o = _order(symbol="AAPL")
        dec = gate.evaluate(o, state)
        r = next(ch for ch in dec.checks if ch.check_name == "restricted")
        assert not r.passed

    def test_case_insensitive_lower(self) -> None:
        gate = _gate(restricted_symbols=frozenset({"AAPL"}))
        state = _base_state(nav=1_000_000.0, available_margin=500_000.0)
        o = _order(symbol="aapl")
        dec = gate.evaluate(o, state)
        r = next(ch for ch in dec.checks if ch.check_name == "restricted")
        assert not r.passed

    def test_case_insensitive_mixed(self) -> None:
        gate = _gate(restricted_symbols=frozenset({"AaPl"}))
        state = _base_state(nav=1_000_000.0, available_margin=500_000.0)
        o = _order(symbol="aApL")
        dec = gate.evaluate(o, state)
        r = next(ch for ch in dec.checks if ch.check_name == "restricted")
        assert not r.passed


# ---------------------------------------------------------------------------
# Check 6: Kill switch
# ---------------------------------------------------------------------------


class TestKillSwitch:
    def test_kill_switch_off_passes(self) -> None:
        gate = PreTradeGate()
        state = _base_state(nav=1_000_000.0, available_margin=500_000.0)
        o = _order()
        dec = gate.evaluate(o, state)
        ks = next(ch for ch in dec.checks if ch.check_name == "kill_switch")
        assert ks.passed

    def test_kill_switch_on_fails(self) -> None:
        gate = PreTradeGate()
        gate.set_kill_switch()
        state = _base_state(nav=1_000_000.0, available_margin=500_000.0)
        o = _order()
        dec = gate.evaluate(o, state)
        ks = next(ch for ch in dec.checks if ch.check_name == "kill_switch")
        assert not ks.passed
        assert "kill switch is active" in ks.message

    def test_kill_switch_overrides_all_checks(self) -> None:
        """When kill switch is active the gate fails even for a trivial order."""
        gate = _gate()
        gate.set_kill_switch()
        state = _base_state(
            nav=1_000_000.0,
            available_margin=999_000.0,
            adv={"AAPL": 1_000_000.0},
        )
        o = _order(quantity=1.0, price=1.0)
        dec = gate.evaluate(o, state)
        assert not dec.passed
        assert not dec.ok

    def test_kill_switch_clear_resumes(self) -> None:
        gate = _gate()
        gate.set_kill_switch()
        gate.clear_kill_switch()
        state = _base_state(
            nav=1_000_000.0,
            available_margin=999_000.0,
            adv={"AAPL": 1_000_000.0},
        )
        o = _order(quantity=1.0, price=1.0)
        dec = gate.evaluate(o, state)
        # Kill switch cleared -> should pass (assuming all other checks pass)
        ks = next(ch for ch in dec.checks if ch.check_name == "kill_switch")
        assert ks.passed

    def test_kill_switch_property(self) -> None:
        gate = PreTradeGate()
        assert not gate.kill_switch_active
        gate.set_kill_switch()
        assert gate.kill_switch_active
        gate.clear_kill_switch()
        assert not gate.kill_switch_active

    def test_shared_kill_switch_across_gates(self) -> None:
        """Two gates sharing a kill switch are both blocked when switch fires."""
        from core_trading.risk.pretrade import _KillSwitch  # noqa: PLC0415
        ks = _KillSwitch()
        gate_a = PreTradeGate(kill_switch=ks)
        gate_b = PreTradeGate(kill_switch=ks)
        ks.set()
        state = _base_state(nav=1_000_000.0, available_margin=500_000.0)
        o = _order(quantity=1.0, price=1.0)
        assert not gate_a.evaluate(o, state).passed
        assert not gate_b.evaluate(o, state).passed

    def test_kill_switch_thread_safety(self) -> None:
        """Multiple threads toggling the kill switch must not corrupt state."""
        from core_trading.risk.pretrade import _KillSwitch  # noqa: PLC0415
        ks = _KillSwitch()
        errors: list[Exception] = []

        def toggle(n: int) -> None:
            try:
                for _ in range(n):
                    ks.set()
                    ks.clear()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=toggle, args=(200,)) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors


# ---------------------------------------------------------------------------
# Multiple simultaneous failures
# ---------------------------------------------------------------------------


class TestMultipleFailures:
    def test_all_six_checks_fail_together(self) -> None:
        """Gate must report ALL failures, not just the first."""
        cfg = GateConfig(
            adv_participation_cap=0.01,   # very tight -> liquidity fail
            concentration_cap=0.001,       # very tight -> concentration fail
            gross_exposure_cap=0.001,      # very tight -> gross exposure fail
            net_exposure_cap=0.001,        # very tight -> net exposure fail
            default_margin_rate=1.0,       # 100% margin, available=0 -> margin fail
            restricted_symbols=frozenset({"AAPL"}),  # restricted -> fail
        )
        gate = PreTradeGate(config=cfg)
        gate.set_kill_switch()

        state = PortfolioState(
            nav=100_000.0,
            positions={},
            available_margin=0.0,
            adv={"AAPL": 1_000.0},
        )
        o = _order(symbol="AAPL", quantity=1_000.0, price=100.0)
        dec = gate.evaluate(o, state)

        assert not dec.passed
        failed = [ch for ch in dec.checks if not ch.passed]
        # liquidity, concentration, exposure_gross, exposure_net, margin,
        # restricted, kill_switch = at least 7 failures
        assert len(failed) >= 7
        assert len(dec.violations) == len(failed)

    def test_two_simultaneous_failures_both_reported(self) -> None:
        """Kill switch + restricted list both fire; both must appear."""
        gate = _gate(restricted_symbols=frozenset({"AAPL"}))
        gate.set_kill_switch()
        state = _base_state(nav=1_000_000.0, available_margin=500_000.0)
        o = _order(symbol="AAPL", quantity=1.0, price=1.0)
        dec = gate.evaluate(o, state)
        failed_names = [ch.check_name for ch in dec.checks if not ch.passed]
        assert "restricted" in failed_names
        assert "kill_switch" in failed_names

    def test_violations_tuple_nonempty_when_failed(self) -> None:
        gate = _gate(restricted_symbols=frozenset({"AAPL"}))
        state = _base_state(nav=1_000_000.0, available_margin=500_000.0)
        o = _order(symbol="AAPL")
        dec = gate.evaluate(o, state)
        assert not dec.passed
        assert len(dec.violations) >= 1
        for v in dec.violations:
            assert isinstance(v, str)


# ---------------------------------------------------------------------------
# PreTradeDecision helpers
# ---------------------------------------------------------------------------


class TestPreTradeDecision:
    def test_ok_alias(self) -> None:
        gate = _gate()
        state = _base_state(nav=1_000_000.0, available_margin=999_000.0)
        o = _order(quantity=1.0, price=1.0)
        dec = gate.evaluate(o, state)
        assert dec.ok == dec.passed

    def test_as_risk_check_passed(self) -> None:
        gate = _gate()
        state = _base_state(nav=1_000_000.0, available_margin=999_000.0)
        o = _order(quantity=1.0, price=1.0)
        dec = gate.evaluate(o, state)
        rc = dec.as_risk_check()
        assert isinstance(rc, RiskCheck)
        assert rc.passed == dec.passed
        assert rc.violations == dec.violations

    def test_as_risk_check_failed(self) -> None:
        gate = _gate(restricted_symbols=frozenset({"AAPL"}))
        state = _base_state(nav=1_000_000.0, available_margin=500_000.0)
        o = _order(symbol="AAPL")
        dec = gate.evaluate(o, state)
        rc = dec.as_risk_check()
        assert not rc.passed
        assert len(rc.violations) >= 1

    def test_check_detail_fields_present(self) -> None:
        gate = _gate(
            adv_participation_cap=0.10,
            concentration_cap=0.05,
            gross_exposure_cap=2.0,
            net_exposure_cap=1.0,
        )
        state = _base_state(
            nav=100_000.0,
            available_margin=50_000.0,
            adv={"AAPL": 10_000.0},
        )
        o = _order(quantity=100.0, price=100.0)
        dec = gate.evaluate(o, state)
        for ch in dec.checks:
            assert isinstance(ch, CheckDetail)
            assert isinstance(ch.check_name, str)
            assert isinstance(ch.passed, bool)
            assert isinstance(ch.message, str)
            # ASCII-only check
            ch.message.encode("ascii")

    def test_decision_symbol_side_quantity(self) -> None:
        gate = _gate()
        state = _base_state(nav=1_000_000.0, available_margin=999_000.0)
        o = ProposedOrder("MSFT", "sell", 42.0, 200.0)
        dec = gate.evaluate(o, state)
        assert dec.symbol == "MSFT"
        assert dec.side == "sell"
        assert dec.quantity == pytest.approx(42.0)


# ---------------------------------------------------------------------------
# Clean passing order end-to-end
# ---------------------------------------------------------------------------


class TestCleanPass:
    def test_trivial_order_passes_all_checks(self) -> None:
        gate = _gate(
            adv_participation_cap=0.10,
            concentration_cap=0.05,
            gross_exposure_cap=2.0,
            net_exposure_cap=1.0,
            default_margin_rate=0.50,
        )
        state = _base_state(
            nav=1_000_000.0,
            available_margin=500_000.0,
            adv={"AAPL": 100_000.0},
        )
        o = _order(symbol="AAPL", quantity=100.0, price=100.0)  # notional=10_000
        dec = gate.evaluate(o, state)
        assert dec.passed
        assert len(dec.violations) == 0

    def test_all_check_names_present(self) -> None:
        gate = _gate()
        state = _base_state(nav=1_000_000.0, available_margin=999_000.0)
        o = _order(quantity=1.0, price=1.0)
        dec = gate.evaluate(o, state)
        names = {ch.check_name for ch in dec.checks}
        expected = {
            "liquidity",
            "concentration",
            "exposure_gross",
            "exposure_net",
            "margin",
            "restricted",
            "kill_switch",
        }
        assert expected == names


# ---------------------------------------------------------------------------
# Execution-layer integration tests
# ---------------------------------------------------------------------------


class TestGatePairOrder:
    """Integration tests: gate_pair_order -> PairExecutor.

    Test (a): A passing order proceeds to PairExecutor.execute() and fills.
    Test (b): A failing order (restricted symbol or kill switch) is blocked
              BEFORE execution (executor is NOT called).
    """

    def _make_pair_order(
        self,
        pair_id: str = "GLD/SLV",
        sym_y: str = "GLD",
        qty_y: float = 100.0,
        price_y: float = 180.0,
        sym_x: str = "SLV",
        qty_x: float = -200.0,
        price_x: float = 24.0,
    ) -> PairOrder:
        return PairOrder(
            pair_id=pair_id,
            leg_y=Leg(symbol=sym_y, quantity=qty_y, decision_price=price_y),
            leg_x=Leg(symbol=sym_x, quantity=qty_x, decision_price=price_x),
        )

    def test_passing_order_fills(self) -> None:
        """(a) Gate passes -> executor.execute() called -> filled=True."""
        cfg = GateConfig(
            adv_participation_cap=1.0,
            concentration_cap=1.0,
            gross_exposure_cap=100.0,
            net_exposure_cap=100.0,
            default_margin_rate=0.01,
        )
        gate = PreTradeGate(config=cfg)

        state = _base_state(
            nav=1_000_000.0,
            available_margin=999_000.0,
            adv={"GLD": 1_000_000.0, "SLV": 1_000_000.0},
        )
        pair_order = self._make_pair_order()
        fill_model = DeterministicFillModel(slippage_bps=1.0)
        executor = PairExecutor(fill_model, ExecutionConfig(require_full_fill=True))

        result = gate_pair_order(gate, pair_order, state, executor=executor)

        assert result.passed, f"Expected gate pass; violations: {result.violations}"
        assert result.execution_result is not None
        assert result.execution_result.filled, (
            f"Expected fill; reason: {result.execution_result.reason}"
        )
        assert result.execution_result.pair_id == "GLD/SLV"
        assert len(result.execution_result.fills) == 2

    def test_restricted_symbol_blocks_execution(self) -> None:
        """(b) Restricted symbol -> gate fails -> executor NOT called."""
        cfg = GateConfig(
            adv_participation_cap=1.0,
            concentration_cap=1.0,
            gross_exposure_cap=100.0,
            net_exposure_cap=100.0,
            default_margin_rate=0.01,
            restricted_symbols=frozenset({"GLD"}),
        )
        gate = PreTradeGate(config=cfg)

        state = _base_state(
            nav=1_000_000.0,
            available_margin=999_000.0,
            adv={"GLD": 1_000_000.0, "SLV": 1_000_000.0},
        )
        pair_order = self._make_pair_order()

        # Use a fill model that would succeed if called -- we'll verify it ISN'T
        fill_model = DeterministicFillModel(slippage_bps=0.0)
        executor = PairExecutor(fill_model)

        result = gate_pair_order(gate, pair_order, state, executor=executor)

        assert not result.passed
        assert result.execution_result is None  # executor not called
        restricted_violations = [v for v in result.violations if "restricted" in v]
        assert len(restricted_violations) >= 1

    def test_kill_switch_blocks_execution(self) -> None:
        """(b) Kill switch active -> gate fails -> executor NOT called."""
        cfg = GateConfig(
            adv_participation_cap=1.0,
            concentration_cap=1.0,
            gross_exposure_cap=100.0,
            net_exposure_cap=100.0,
            default_margin_rate=0.01,
        )
        gate = PreTradeGate(config=cfg)
        gate.set_kill_switch()

        state = _base_state(
            nav=1_000_000.0,
            available_margin=999_000.0,
            adv={"GLD": 1_000_000.0, "SLV": 1_000_000.0},
        )
        pair_order = self._make_pair_order()
        fill_model = DeterministicFillModel(slippage_bps=0.0)
        executor = PairExecutor(fill_model)

        result = gate_pair_order(gate, pair_order, state, executor=executor)

        assert not result.passed
        assert result.execution_result is None
        ks_violations = [v for v in result.violations if "kill switch" in v]
        assert len(ks_violations) >= 1

    def test_no_executor_returns_none_exec_result(self) -> None:
        """Gate passes but no executor provided -> execution_result is None."""
        cfg = GateConfig(
            adv_participation_cap=1.0,
            concentration_cap=1.0,
            gross_exposure_cap=100.0,
            net_exposure_cap=100.0,
            default_margin_rate=0.01,
        )
        gate = PreTradeGate(config=cfg)
        state = _base_state(nav=1_000_000.0, available_margin=999_000.0)
        pair_order = self._make_pair_order()

        result = gate_pair_order(gate, pair_order, state)

        assert result.passed
        assert result.execution_result is None

    def test_pair_gate_result_structure(self) -> None:
        """PairGateResult has correct shape on a passing order."""
        cfg = GateConfig(
            adv_participation_cap=1.0,
            concentration_cap=1.0,
            gross_exposure_cap=100.0,
            net_exposure_cap=100.0,
            default_margin_rate=0.01,
        )
        gate = PreTradeGate(config=cfg)
        state = _base_state(nav=1_000_000.0, available_margin=999_000.0)
        pair_order = self._make_pair_order()
        fill_model = DeterministicFillModel()
        executor = PairExecutor(fill_model)

        result = gate_pair_order(gate, pair_order, state, executor=executor)

        assert isinstance(result, PairGateResult)
        assert len(result.leg_decisions) == 2
        assert isinstance(result.leg_decisions[0], PreTradeDecision)
        assert isinstance(result.leg_decisions[1], PreTradeDecision)
        assert isinstance(result.combined_exposure_check, RiskCheck)

    def test_leg_y_is_buy_leg_x_is_sell(self) -> None:
        """Legs are converted correctly: positive qty -> buy, negative -> sell."""
        cfg = GateConfig(
            adv_participation_cap=1.0,
            concentration_cap=1.0,
            gross_exposure_cap=100.0,
            net_exposure_cap=100.0,
            default_margin_rate=0.01,
        )
        gate = PreTradeGate(config=cfg)
        state = _base_state(nav=1_000_000.0, available_margin=999_000.0)
        pair_order = self._make_pair_order(qty_y=100.0, qty_x=-200.0)

        result = gate_pair_order(gate, pair_order, state)

        dec_y, dec_x = result.leg_decisions
        assert dec_y.side == "buy"
        assert dec_y.symbol == "GLD"
        assert dec_x.side == "sell"
        assert dec_x.symbol == "SLV"

    def test_violations_aggregated_from_both_legs(self) -> None:
        """Violations from both legs are aggregated in PairGateResult."""
        cfg = GateConfig(
            adv_participation_cap=1.0,
            concentration_cap=1.0,
            gross_exposure_cap=100.0,
            net_exposure_cap=100.0,
            default_margin_rate=0.01,
            restricted_symbols=frozenset({"GLD", "SLV"}),
        )
        gate = PreTradeGate(config=cfg)
        state = _base_state(nav=1_000_000.0, available_margin=999_000.0)
        pair_order = self._make_pair_order()

        result = gate_pair_order(gate, pair_order, state)

        assert not result.passed
        # Both GLD and SLV restricted -> at least 2 restricted violations
        restricted_v = [v for v in result.violations if "restricted" in v]
        assert len(restricted_v) >= 2

    def test_fill_model_partial_rejection_blocks_pair(self) -> None:
        """If fill model rejects a leg symbol, executor returns leg_failed."""
        cfg = GateConfig(
            adv_participation_cap=1.0,
            concentration_cap=1.0,
            gross_exposure_cap=100.0,
            net_exposure_cap=100.0,
            default_margin_rate=0.01,
        )
        gate = PreTradeGate(config=cfg)
        state = _base_state(nav=1_000_000.0, available_margin=999_000.0)
        pair_order = self._make_pair_order()

        # Fill model rejects GLD but gate allows it through
        fill_model = DeterministicFillModel(reject_symbols=frozenset({"GLD"}))
        executor = PairExecutor(fill_model)

        result = gate_pair_order(gate, pair_order, state, executor=executor)

        # Gate passes but execution fails at fill level
        assert result.passed  # gate level passes
        assert result.execution_result is not None
        assert not result.execution_result.filled
        assert result.execution_result.reason == "leg_failed"

    def test_combined_exposure_fail_blocks_pair(self) -> None:
        """Combined exposure check fails when pair notional > gross cap."""
        cfg = GateConfig(
            adv_participation_cap=1.0,
            concentration_cap=1.0,
            gross_exposure_cap=0.001,  # extremely tight cap -> combined exposure fail
            net_exposure_cap=100.0,
            default_margin_rate=0.01,
        )
        gate = PreTradeGate(config=cfg)
        state = _base_state(nav=1_000_000.0, available_margin=999_000.0)
        pair_order = self._make_pair_order(
            qty_y=100.0, price_y=180.0,   # notional=18000
            qty_x=-200.0, price_x=24.0,   # notional=4800
        )

        result = gate_pair_order(gate, pair_order, state)

        assert not result.passed
        combined_violations = [v for v in result.violations if "combined_exposure" in v]
        assert len(combined_violations) >= 1
        assert "FAIL" in combined_violations[0]


# ---------------------------------------------------------------------------
# PortfolioState.position_value direct test
# ---------------------------------------------------------------------------


class TestPortfolioStatePositionValue:
    def test_position_value_with_known_price(self) -> None:
        state = _base_state(
            positions={"AAPL": 100.0},
            position_prices={"AAPL": 150.0},
        )
        val = state.position_value("AAPL", fallback_price=200.0)
        assert val == pytest.approx(15_000.0)

    def test_position_value_uses_fallback_price(self) -> None:
        state = _base_state(
            positions={"AAPL": 100.0},
            position_prices={},  # no price known
        )
        val = state.position_value("AAPL", fallback_price=200.0)
        assert val == pytest.approx(20_000.0)

    def test_position_value_zero_position(self) -> None:
        state = _base_state(positions={})
        val = state.position_value("AAPL", fallback_price=200.0)
        assert val == pytest.approx(0.0)

    def test_position_value_short(self) -> None:
        state = _base_state(
            positions={"MSFT": -50.0},
            position_prices={"MSFT": 300.0},
        )
        val = state.position_value("MSFT", fallback_price=1.0)
        assert val == pytest.approx(-15_000.0)
