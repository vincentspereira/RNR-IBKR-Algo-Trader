"""VIN-48 Wave 1 regression tests: inverted VIN-40 audit proofs (F1, F2).

Each test here DEMONSTRATES THE FIX for a VIN-40 critical finding and must
FAIL on master and PASS on the fix branch:

* F2 -- fill-contract break: the adapter's ``get_order_status`` used to emit
  ``"filled"`` while every consumer (pairs_live_runner.py:394,
  order_store.py:316,331) reads ``filled_quantity``. Fills parsed as 0.0
  forever, the position book never updated, and every run re-fired the delta.
* F1 -- market-order limit bypass: ``price = order_data.get("price", 0)``
  made notional 0 for market orders, so the max_position_size gate passed
  for ANY quantity.

These are merged as permanent regression protection, unlike the audit
proofs attached to VIN-40.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("IBKR_ACCOUNT_ID", "DU_TEST_ACCOUNT")

import core_trading.adapters.ibkr_adapter as ibkr_mod
from core_trading.adapters.ibkr_adapter import IBKRAdapter

TEST_ACCOUNT = "DU_TEST_ACCOUNT"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_trade(order_id="1001", status="Filled", filled=100, remaining=0,
               avg_fill_price=190.5):
    """Fake ib_insync Trade with a filled OrderStatus."""
    trade = MagicMock(name="Trade")
    trade.order = MagicMock()
    trade.order.orderId = order_id
    trade.orderStatus = MagicMock()
    trade.orderStatus.status = status
    trade.orderStatus.filled = filled
    trade.orderStatus.remaining = remaining
    trade.orderStatus.avgFillPrice = avg_fill_price
    return trade


async def connected_adapter():
    """IBKRAdapter wired to a fake IB (no network, no TWS)."""
    adapter = IBKRAdapter(account_id=TEST_ACCOUNT)
    fake_ib = MagicMock(name="IB")
    fake_ib.connectAsync = AsyncMock(return_value=True)
    fake_ib.isConnected = MagicMock(return_value=True)
    fake_ib.disconnectedEvent = MagicMock()
    fake_ib.errorEvent = MagicMock()
    with patch.object(ibkr_mod, "IB", return_value=fake_ib):
        await adapter.connect()
    adapter.ib = fake_ib
    return adapter, fake_ib


# ---------------------------------------------------------------------------
# F2: fill-contract alignment (BrokerLike)
# ---------------------------------------------------------------------------


class TestF2FillContract:
    """Adapter status dict keys must match the BrokerLike protocol."""

    @pytest.mark.asyncio
    async def test_status_dict_has_filled_quantity_key(self):
        """Inverts audit proof TestFilledQuantityContractBreak.

        Master: emits "filled"; consumers read "filled_quantity" -> 0.0 fills
        forever. Fix branch: adapter emits the contract key.
        """
        adapter, fake_ib = await connected_adapter()
        fake_ib.placeOrder.return_value = make_trade(
            status="Filled", filled=5, remaining=0, avg_fill_price=190.5
        )
        result = await adapter.place_order({
            "symbol": "AAPL", "side": "buy", "quantity": 5,
            "order_type": "market", "price": 190.0,
        })
        st = await adapter.get_order_status(result["order_id"])
        assert "filled_quantity" in st, (
            "BrokerLike contract requires filled_quantity; adapter emitted: "
            f"{sorted(st.keys())}"
        )
        assert float(st["filled_quantity"]) == 5.0

    @pytest.mark.asyncio
    async def test_consumer_read_path_parses_real_fill(self):
        """The exact consumer read (pairs_live_runner.py:394) sees the fill.

        Master: float(st.get("filled_quantity") or 0.0) == 0.0 always.
        """
        adapter, fake_ib = await connected_adapter()
        fake_ib.placeOrder.return_value = make_trade(filled=5, avg_fill_price=190.5)
        result = await adapter.place_order({
            "symbol": "AAPL", "side": "buy", "quantity": 5,
            "order_type": "market", "price": 190.0,
        })
        st = await adapter.get_order_status(result["order_id"])
        # pairs_live_runner.py:394-395 consumer read:
        filled_qty = float(st.get("filled_quantity") or 0.0)
        avg_price = float(st.get("avg_fill_price") or 0.0)
        assert filled_qty == 5.0, "consumer must observe the real fill"
        assert avg_price == pytest.approx(190.5)

    @pytest.mark.asyncio
    async def test_status_keys_match_brokerlike_exactly(self):
        """Contract test: adapter status keys must be a superset of the
        BrokerLike-required keys {status, filled_quantity, avg_fill_price}.

        Acceptance criteria: "adapter status dict keys match BrokerLike
        protocol exactly."
        """
        adapter, fake_ib = await connected_adapter()
        fake_ib.placeOrder.return_value = make_trade(filled=5, avg_fill_price=190.5)
        result = await adapter.place_order({
            "symbol": "AAPL", "side": "buy", "quantity": 5,
            "order_type": "market", "price": 190.0,
        })
        st = await adapter.get_order_status(result["order_id"])
        required = {"status", "filled_quantity", "avg_fill_price"}
        assert required.issubset(set(st.keys())), (
            f"missing keys: {required - set(st.keys())}"
        )
        # No stray legacy fill key that consumers might mistake for a fill.
        assert "filled" not in st, "legacy 'filled' key must be removed"

    @pytest.mark.asyncio
    async def test_tracked_but_not_live_trade_status_also_has_contract_keys(self):
        """Fallback path (order record without a live trade) must also speak
        the contract, so consumers never parse a missing key."""
        adapter, _ = await connected_adapter()
        adapter._orders["1"] = {
            "status": "filled", "symbol": "AAPL",
            "quantity": 100, "order_type": "market",
        }
        st = await adapter.get_order_status("1")
        assert st["status"] == "filled"
        assert float(st.get("filled_quantity", -1)) == 0.0
        assert float(st.get("avg_fill_price", -1)) == 0.0


# ---------------------------------------------------------------------------
# F1: market-order notional limit bypass
# ---------------------------------------------------------------------------


class TestF1MarketOrderLimitBypass:
    """Market orders must be sized against a reference price pre-trade."""

    @pytest.mark.asyncio
    async def test_large_market_order_without_price_is_rejected(self):
        """Inverts audit proof TestMarketOrderLimitBypass.

        Master: 10M shares x price 0 = notional 0 <= 1000.0 limit -> pass.
        Fix branch: rejected before the broker is contacted.
        """
        adapter, fake_ib = await connected_adapter()
        result = await adapter.place_order({
            "symbol": "AAPL", "side": "buy", "quantity": 10_000_000,
            "order_type": "market",  # no price key -- the exact audit payload
        })
        assert result["status"] == "rejected", (
            "unsizable market order must be rejected, not passed with notional 0"
        )
        fake_ib.placeOrder.assert_not_called()

    @pytest.mark.asyncio
    async def test_market_order_notional_checked_against_price_estimate(self):
        """A market order WITH an honest price estimate is sized and rejected
        when the notional exceeds max_position_size."""
        adapter, fake_ib = await connected_adapter()
        result = await adapter.place_order({
            "symbol": "AAPL", "side": "buy", "quantity": 100,
            "order_type": "market", "price": 200.0,  # 100 * 200 = 20,000 > 1,000
        })
        assert result["status"] == "rejected"
        assert result["reason"] == "Risk limit violated"
        fake_ib.placeOrder.assert_not_called()

    @pytest.mark.asyncio
    async def test_small_market_order_with_price_estimate_passes(self):
        """Sizable market orders still flow: 5 * 100 = 500 <= 1,000."""
        adapter, fake_ib = await connected_adapter()
        fake_ib.placeOrder.return_value = make_trade(order_id="2001")
        result = await adapter.place_order({
            "symbol": "AAPL", "side": "buy", "quantity": 5,
            "order_type": "market", "price": 100.0,
        })
        assert result["status"] == "submitted"
        fake_ib.placeOrder.assert_called_once()

    @pytest.mark.asyncio
    async def test_zero_price_estimate_is_rejected(self):
        """price=0.0 explicitly (not just missing) must not compute notional 0."""
        adapter, fake_ib = await connected_adapter()
        result = await adapter.place_order({
            "symbol": "AAPL", "side": "buy", "quantity": 100,
            "order_type": "market", "price": 0,
        })
        assert result["status"] == "rejected"
        fake_ib.placeOrder.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_order_sized_against_stop_price(self):
        """Stop orders (no limit price) fall back to stop_price for sizing."""
        adapter, fake_ib = await connected_adapter()
        result = await adapter.place_order({
            "symbol": "AAPL", "side": "sell", "quantity": 100,
            "order_type": "stop", "stop_price": 200.0,  # 100 * 200 = 20,000
        })
        assert result["status"] == "rejected"
        fake_ib.placeOrder.assert_not_called()

    @pytest.mark.asyncio
    async def test_market_order_without_price_in_engine_rejected(self):
        """ExecutionEngine._validate_order mirrors the adapter policy:
        market orders without a reference price never reach the adapter.
        """
        from src.engines import execution_engine as ee
        order = ee.Order(
            instrument="AAPL",
            side=ee.OrderSide.BUY,
            order_type=ee.OrderType.MARKET,
            quantity=1_000_000,
            price=None,
        )
        engine = ee.ExecutionEngine()
        assert engine._validate_order(order) is False

    @pytest.mark.asyncio
    async def test_market_order_with_price_in_engine_passes_validation(self):
        """Same engine, honest estimate -> validation passes (the adapter's
        risk gate still applies downstream)."""
        from src.engines import execution_engine as ee
        order = ee.Order(
            instrument="AAPL",
            side=ee.OrderSide.BUY,
            order_type=ee.OrderType.MARKET,
            quantity=10,
            price=100.0,
        )
        engine = ee.ExecutionEngine()
        assert engine._validate_order(order) is True


# ---------------------------------------------------------------------------
# F1 producer wiring: runners and kill switch attach reference prices
# ---------------------------------------------------------------------------


class TestF1ProducerWiring:
    """Every internal producer of market orders attaches a reference price."""

    def test_pairs_delta_orders_include_price(self):
        from core_trading.ops.pairs_live_runner import PairsLiveRunner
        orders = PairsLiveRunner._delta_orders(
            current={"AAA": 0}, target={"AAA": 10}, closes={"AAA": 50.0}
        )
        assert orders and orders[0]["price"] == 50.0

    def test_pairs_delta_orders_drop_unsizable_leg(self):
        from core_trading.ops.pairs_live_runner import PairsLiveRunner
        orders = PairsLiveRunner._delta_orders(
            current={"AAA": 0}, target={"AAA": 10}, closes={}
        )
        assert orders == [], "leg without a reference close must not be sent"

    def test_intraday_orders_include_price(self):
        """intraday_runner builds orders with prices[sym] attached (static
        check mirrors the runtime payload shape)."""
        import inspect
        from core_trading.ops import intraday_runner as ir
        src = inspect.getsource(ir)
        assert '"order_type": "market"' in src
        assert '"price": float(prices[sym])' in src

    def test_kill_switch_flatten_includes_reference_price(self):
        """KillSwitch._close_all_positions attaches market_price/avg_cost as
        the sizing reference (static source check)."""
        import inspect
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        ks_path = os.path.join(
            repo_root, "services", "risk-manager", "src", "engines", "kill_switch.py"
        )
        with open(ks_path) as f:
            src = f.read()
        assert 'pos.get("market_price") or pos.get("avg_cost")' in src
        assert '"price": ref_price' in src


# ---------------------------------------------------------------------------
# F1: kill-switch effectiveness is preserved (hard rule)
# ---------------------------------------------------------------------------


class TestKillSwitchNotNeutered:
    """The flatten path must still fire with the fail-closed sizing fix."""

    @pytest.mark.asyncio
    async def test_flatten_still_submits_orders_for_priced_positions(self):
        """With market_price/avg_cost on positions, flatten still submits."""
        from kill_switch import KillSwitch

        class FakeBroker:
            async def get_positions(self):
                return [
                    {"symbol": "AAPL", "quantity": 100, "avg_cost": 190.0},
                    {"symbol": "MSFT", "quantity": 50, "avg_cost": 300.0},
                ]

            async def place_order(self, order_data):
                self.last_order = dict(order_data)
                return {"status": "submitted"}

        broker = FakeBroker()
        ks = KillSwitch(broker_adapter=broker)
        closed, errors = await ks._close_all_positions()
        assert closed == 2
        assert errors == []

    @pytest.mark.asyncio
    async def test_flatten_reports_unsizable_positions_as_errors(self):
        """A position with no price reference is surfaced as an error, not
        silently skipped -- the kill switch stays loud."""
        from kill_switch import KillSwitch

        class FakeBroker:
            async def get_positions(self):
                return [
                    {"symbol": "AAPL", "quantity": 100, "avg_cost": 0.0},
                ]

            async def place_order(self, order_data):
                return {"status": "submitted"}

        ks = KillSwitch(broker_adapter=FakeBroker())
        closed, errors = await ks._close_all_positions()
        assert closed == 0
        assert errors and "Cannot size flatten" in errors[0]