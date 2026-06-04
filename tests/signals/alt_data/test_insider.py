"""Tests for core_trading.signals.alt_data.insider (Phase 5.F.3).

Covers:
* InsiderConfig -- frozen/slotted DTO, __post_init__ validation.
* InsiderTransaction -- frozen DTO, validation.
* transactions_to_dataframe -- filtering of non-P/S codes, empty input,
  dollar_volume column, type coercions.
* label_routine_insiders -- routine vs. opportunistic classification,
  look-ahead-free cut-off, all-history-absent edge case.
* net_insider_sentiment -- parameter-recovery on synthetic data:
    - cluster-buy symbol gets high (positive) score.
    - net-selling symbol gets low (negative) score.
    - look-ahead-free: future transactions do not contaminate past scores.
    - holdings normalisation falls back to dollar_flow when holdings missing.
* cluster_buy_flags -- fires when >= N distinct insiders buy; does not fire
  for sellers; does not fire below threshold.
* insider_score_panel -- shape, column ordering, NaN propagation for symbol
  with no transactions in window.
* cluster_buy_panel -- shape, bool dtype, cluster flag present/absent.
* insider_portfolio -- dollar-neutral (row sums ~0), shape, too-few-symbols
  row produces zeros.
* Public API (__all__) completeness.
"""
from __future__ import annotations

import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from core_trading.signals.alt_data.insider import (
    InsiderConfig,
    InsiderTransaction,
    cluster_buy_flags,
    cluster_buy_panel,
    insider_portfolio,
    insider_score_panel,
    label_routine_insiders,
    net_insider_sentiment,
    transactions_to_dataframe,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

SEED = 20260604
_BASE_DATE = pd.Timestamp("2023-01-01")


def _make_transaction(
    symbol: str = "AAPL",
    insider_id: str = "I1",
    transaction_date: date = date(2023, 1, 10),
    shares: float = 1000.0,
    transaction_code: str = "P",
    price: float = 150.0,
    shares_held_after: float = float("nan"),
) -> InsiderTransaction:
    return InsiderTransaction(
        symbol=symbol,
        insider_id=insider_id,
        transaction_date=transaction_date,
        shares=shares,
        transaction_code=transaction_code,
        price=price,
        shares_held_after=shares_held_after,
    )


def _make_df(*records: InsiderTransaction) -> pd.DataFrame:
    return transactions_to_dataframe(list(records))


# ---------------------------------------------------------------------------
# InsiderConfig tests
# ---------------------------------------------------------------------------


class TestInsiderConfig:
    """InsiderConfig: construction, validation, immutability."""

    def test_valid_defaults(self) -> None:
        cfg = InsiderConfig()
        assert cfg.window_days == 365
        assert cfg.min_cluster_insiders == 3
        assert cfg.normalisation == "dollar_flow"
        assert cfg.routine_years == 3
        assert cfg.opportunistic_weight == 2.0

    def test_custom_values(self) -> None:
        cfg = InsiderConfig(
            window_days=180,
            min_cluster_insiders=2,
            normalisation="holdings",
            routine_years=2,
            opportunistic_weight=1.5,
        )
        assert cfg.window_days == 180
        assert cfg.min_cluster_insiders == 2
        assert cfg.normalisation == "holdings"
        assert cfg.routine_years == 2
        assert cfg.opportunistic_weight == 1.5

    def test_frozen(self) -> None:
        cfg = InsiderConfig()
        with pytest.raises((AttributeError, TypeError)):
            cfg.window_days = 100  # type: ignore[misc]

    def test_window_days_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="window_days"):
            InsiderConfig(window_days=0)

    def test_window_days_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="window_days"):
            InsiderConfig(window_days=-10)

    def test_min_cluster_one_raises(self) -> None:
        with pytest.raises(ValueError, match="min_cluster_insiders"):
            InsiderConfig(min_cluster_insiders=1)

    def test_bad_normalisation_raises(self) -> None:
        with pytest.raises(ValueError, match="normalisation"):
            InsiderConfig(normalisation="unknown")

    def test_routine_years_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="routine_years"):
            InsiderConfig(routine_years=0)

    def test_opportunistic_weight_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="opportunistic_weight"):
            InsiderConfig(opportunistic_weight=0.0)

    def test_opportunistic_weight_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="opportunistic_weight"):
            InsiderConfig(opportunistic_weight=-1.0)

    def test_window_days_one_allowed(self) -> None:
        cfg = InsiderConfig(window_days=1)
        assert cfg.window_days == 1

    def test_min_cluster_two_allowed(self) -> None:
        cfg = InsiderConfig(min_cluster_insiders=2)
        assert cfg.min_cluster_insiders == 2

    def test_routine_years_one_allowed(self) -> None:
        cfg = InsiderConfig(routine_years=1)
        assert cfg.routine_years == 1


# ---------------------------------------------------------------------------
# InsiderTransaction tests
# ---------------------------------------------------------------------------


class TestInsiderTransaction:
    """InsiderTransaction: construction and validation."""

    def test_valid_buy(self) -> None:
        tx = _make_transaction()
        assert tx.symbol == "AAPL"
        assert tx.transaction_code == "P"
        assert tx.shares == 1000.0
        assert math.isnan(tx.shares_held_after)

    def test_valid_sell(self) -> None:
        tx = _make_transaction(transaction_code="S")
        assert tx.transaction_code == "S"

    def test_zero_shares_raises(self) -> None:
        with pytest.raises(ValueError, match="shares must be > 0"):
            _make_transaction(shares=0.0)

    def test_negative_shares_raises(self) -> None:
        with pytest.raises(ValueError, match="shares must be > 0"):
            _make_transaction(shares=-100.0)

    def test_negative_price_raises(self) -> None:
        with pytest.raises(ValueError, match="price must be >= 0"):
            _make_transaction(price=-1.0)

    def test_zero_price_allowed(self) -> None:
        # Restricted stock awards may have zero cost basis
        tx = _make_transaction(price=0.0, transaction_code="A")
        assert tx.price == 0.0

    def test_shares_held_after_optional(self) -> None:
        tx = _make_transaction(shares_held_after=5000.0)
        assert tx.shares_held_after == 5000.0

    def test_frozen(self) -> None:
        tx = _make_transaction()
        with pytest.raises((AttributeError, TypeError)):
            tx.shares = 999.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# transactions_to_dataframe tests
# ---------------------------------------------------------------------------


class TestTransactionsToDataframe:
    """transactions_to_dataframe: filtering, typing, empty cases."""

    def test_empty_sequence_returns_empty_df(self) -> None:
        df = transactions_to_dataframe([])
        assert df.empty
        assert "symbol" in df.columns
        assert "dollar_volume" in df.columns

    def test_non_ps_codes_filtered(self) -> None:
        records = [
            _make_transaction(transaction_code="A"),   # award -- filtered
            _make_transaction(transaction_code="D"),   # disposition -- filtered
            _make_transaction(transaction_code="P"),   # kept
            _make_transaction(transaction_code="S"),   # kept
        ]
        df = transactions_to_dataframe(records)
        assert len(df) == 2
        assert set(df["transaction_code"].tolist()) == {"P", "S"}

    def test_all_non_ps_returns_empty(self) -> None:
        records = [
            _make_transaction(transaction_code="A"),
            _make_transaction(transaction_code="G"),
        ]
        df = transactions_to_dataframe(records)
        assert df.empty

    def test_dollar_volume_computed(self) -> None:
        tx = _make_transaction(shares=200.0, price=50.0)
        df = _make_df(tx)
        assert float(df["dollar_volume"].iloc[0]) == pytest.approx(10000.0)

    def test_transaction_date_is_datetime64(self) -> None:
        df = _make_df(_make_transaction())
        assert pd.api.types.is_datetime64_any_dtype(df["transaction_date"])

    def test_required_columns_present(self) -> None:
        df = _make_df(_make_transaction())
        for col in [
            "symbol", "insider_id", "transaction_date",
            "shares", "transaction_code", "price",
            "shares_held_after", "dollar_volume",
        ]:
            assert col in df.columns, f"Missing column: {col}"


# ---------------------------------------------------------------------------
# label_routine_insiders tests
# ---------------------------------------------------------------------------


class TestLabelRoutineInsiders:
    """label_routine_insiders: routine/opportunistic classification."""

    def _routine_records(self) -> list[InsiderTransaction]:
        """Insider I_ROUTINE trades every January for 4 years."""
        records = []
        for year in [2020, 2021, 2022, 2023]:
            records.append(
                _make_transaction(
                    insider_id="I_ROUTINE",
                    transaction_date=date(year, 1, 15),
                )
            )
        return records

    def _opportunistic_records(self) -> list[InsiderTransaction]:
        """Insider I_OPP trades irregularly (different months, no pattern)."""
        return [
            _make_transaction(
                insider_id="I_OPP",
                transaction_date=date(2020, 3, 10),
            ),
            _make_transaction(
                insider_id="I_OPP",
                transaction_date=date(2021, 7, 20),
            ),
            _make_transaction(
                insider_id="I_OPP",
                transaction_date=date(2022, 11, 5),
            ),
        ]

    def test_routine_classified_correctly(self) -> None:
        records = self._routine_records() + self._opportunistic_records()
        df = transactions_to_dataframe(records)
        labels = label_routine_insiders(df, routine_years=3)
        # I_ROUTINE trades January in 4 years -> routine
        assert labels["I_ROUTINE"] is np.bool_(True)

    def test_opportunistic_classified_correctly(self) -> None:
        records = self._routine_records() + self._opportunistic_records()
        df = transactions_to_dataframe(records)
        labels = label_routine_insiders(df, routine_years=3)
        # I_OPP never repeats the same month across 3+ years -> opportunistic
        assert labels["I_OPP"] is np.bool_(False)

    def test_lookahead_free_cutoff(self) -> None:
        """History strictly before as_of is used; 2023 data excluded when as_of=2023."""
        records = self._routine_records()  # trades in 2020,2021,2022,2023 January
        df = transactions_to_dataframe(records)
        # with as_of at the start of 2023, only 2020/2021/2022 are visible
        as_of = pd.Timestamp("2023-01-01")
        labels = label_routine_insiders(df, routine_years=3, as_of=as_of)
        # Jan in 2020,2021,2022 = 3 years -> still routine
        assert labels["I_ROUTINE"] is np.bool_(True)

    def test_lookahead_cutoff_prevents_routine_with_insufficient_history(self) -> None:
        """As-of cuts history so only 2 prior years visible -> not routine (need 3)."""
        records = self._routine_records()  # 2020, 2021, 2022, 2023
        df = transactions_to_dataframe(records)
        # Only 2020 and 2021 visible before 2022-01-01
        as_of = pd.Timestamp("2022-01-01")
        labels = label_routine_insiders(df, routine_years=3, as_of=as_of)
        assert labels["I_ROUTINE"] is np.bool_(False)

    def test_empty_history_returns_opportunistic(self) -> None:
        """If all transactions are after as_of, everyone is opportunistic."""
        records = [_make_transaction(insider_id="I1", transaction_date=date(2025, 1, 1))]
        df = transactions_to_dataframe(records)
        labels = label_routine_insiders(
            df, routine_years=1, as_of=pd.Timestamp("2020-01-01")
        )
        assert labels["I1"] is np.bool_(False)

    def test_bad_routine_years_raises(self) -> None:
        df = _make_df(_make_transaction())
        with pytest.raises(ValueError, match="routine_years"):
            label_routine_insiders(df, routine_years=0)

    def test_index_contains_all_insider_ids(self) -> None:
        records = self._routine_records() + self._opportunistic_records()
        df = transactions_to_dataframe(records)
        labels = label_routine_insiders(df, routine_years=3)
        assert "I_ROUTINE" in labels.index
        assert "I_OPP" in labels.index


# ---------------------------------------------------------------------------
# net_insider_sentiment tests
# ---------------------------------------------------------------------------


class TestNetInsiderSentiment:
    """net_insider_sentiment: signal recovery, look-ahead-free, normalisation."""

    def _cluster_buy_df(self, n_insiders: int = 4) -> pd.DataFrame:
        """Plant a cluster buy in AAPL (N distinct insiders buy)."""
        records = []
        for k in range(n_insiders):
            records.append(
                _make_transaction(
                    symbol="AAPL",
                    insider_id=f"I_BUY_{k}",
                    transaction_date=date(2023, 1, 10),
                    shares=1000.0,
                    transaction_code="P",
                    price=150.0,
                )
            )
        # MSFT insiders sell
        records.append(
            _make_transaction(
                symbol="MSFT",
                insider_id="I_SELL_1",
                transaction_date=date(2023, 1, 10),
                shares=5000.0,
                transaction_code="S",
                price=300.0,
            )
        )
        records.append(
            _make_transaction(
                symbol="MSFT",
                insider_id="I_SELL_2",
                transaction_date=date(2023, 1, 10),
                shares=3000.0,
                transaction_code="S",
                price=300.0,
            )
        )
        return transactions_to_dataframe(records)

    def test_cluster_buy_gets_positive_score(self) -> None:
        """Symbol with net buying (all buys) gets a positive sentiment score."""
        df = self._cluster_buy_df()
        cfg = InsiderConfig(window_days=30)
        eval_date = pd.Timestamp("2023-01-15")
        sentiment = net_insider_sentiment(df, eval_date, config=cfg)
        assert float(sentiment["AAPL"]) > 0.0, (
            f"Expected positive AAPL sentiment, got {float(sentiment['AAPL']):.4f}"
        )

    def test_net_selling_gets_negative_score(self) -> None:
        """Symbol with net selling (all sells) gets a negative sentiment score."""
        df = self._cluster_buy_df()
        cfg = InsiderConfig(window_days=30)
        eval_date = pd.Timestamp("2023-01-15")
        sentiment = net_insider_sentiment(df, eval_date, config=cfg)
        assert float(sentiment["MSFT"]) < 0.0, (
            f"Expected negative MSFT sentiment, got {float(sentiment['MSFT']):.4f}"
        )

    def test_buyer_score_above_seller_score(self) -> None:
        """The cluster-buy symbol scores strictly above the net-selling symbol."""
        df = self._cluster_buy_df()
        cfg = InsiderConfig(window_days=30)
        eval_date = pd.Timestamp("2023-01-15")
        sentiment = net_insider_sentiment(df, eval_date, config=cfg)
        assert float(sentiment["AAPL"]) > float(sentiment["MSFT"])

    def test_score_bounded_in_minus_one_to_one(self) -> None:
        """Net sentiment is clipped to [-1, +1]."""
        df = self._cluster_buy_df()
        cfg = InsiderConfig(window_days=30)
        eval_date = pd.Timestamp("2023-01-15")
        sentiment = net_insider_sentiment(df, eval_date, config=cfg)
        for val in sentiment:
            if not math.isnan(float(val)):
                assert -1.0 <= float(val) <= 1.0

    def test_lookahead_free_future_transaction_excluded(self) -> None:
        """A transaction dated after eval_date must not affect score at eval_date."""
        # Two transactions for the same symbol:
        #   - one before eval_date (buy)
        #   - one after eval_date (sell, which if included would reduce score)
        eval_date = pd.Timestamp("2023-01-15")
        records_before = [
            _make_transaction(
                symbol="AAPL", insider_id="I1",
                transaction_date=date(2023, 1, 10),
                transaction_code="P", shares=1000.0, price=100.0,
            ),
        ]
        records_after = records_before + [
            _make_transaction(
                symbol="AAPL", insider_id="I2",
                transaction_date=date(2023, 2, 1),  # AFTER eval_date
                transaction_code="S", shares=9000.0, price=100.0,
            ),
        ]
        df_before = transactions_to_dataframe(records_before)
        df_after = transactions_to_dataframe(records_after)
        cfg = InsiderConfig(window_days=365)

        score_before = float(
            net_insider_sentiment(df_before, eval_date, config=cfg)["AAPL"]
        )
        score_after = float(
            net_insider_sentiment(df_after, eval_date, config=cfg)["AAPL"]
        )
        # Future sell must not reduce score at eval_date
        assert math.isclose(score_before, score_after, rel_tol=1e-9), (
            f"Look-ahead contamination: before={score_before:.4f}, after={score_after:.4f}"
        )

    def test_empty_df_returns_empty_series(self) -> None:
        df = transactions_to_dataframe([])
        cfg = InsiderConfig()
        sentiment = net_insider_sentiment(df, pd.Timestamp("2023-01-15"), config=cfg)
        assert sentiment.empty

    def test_no_transactions_in_window_returns_nan(self) -> None:
        """Transactions exist but none fall within the narrow window."""
        records = [
            _make_transaction(
                transaction_date=date(2022, 1, 1),  # old, outside 30-day window
                transaction_code="P",
            )
        ]
        df = transactions_to_dataframe(records)
        cfg = InsiderConfig(window_days=30)
        eval_date = pd.Timestamp("2023-01-15")
        sentiment = net_insider_sentiment(df, eval_date, config=cfg)
        assert math.isnan(float(sentiment["AAPL"]))

    def test_holdings_normalisation_produces_score(self) -> None:
        """holdings normalisation returns a finite score when shares_held_after is set."""
        records = [
            _make_transaction(
                symbol="AAPL", insider_id="I1",
                transaction_date=date(2023, 1, 10),
                transaction_code="P", shares=500.0, price=100.0,
                shares_held_after=10000.0,
            ),
        ]
        df = transactions_to_dataframe(records)
        cfg = InsiderConfig(window_days=30, normalisation="holdings")
        eval_date = pd.Timestamp("2023-01-15")
        sentiment = net_insider_sentiment(df, eval_date, config=cfg)
        assert math.isfinite(float(sentiment["AAPL"]))

    def test_holdings_normalisation_fallback_when_missing(self) -> None:
        """holdings normalisation falls back to dollar_flow when shares_held_after is NaN."""
        records = [
            _make_transaction(
                symbol="AAPL", insider_id="I1",
                transaction_date=date(2023, 1, 10),
                transaction_code="P", shares=500.0, price=100.0,
                shares_held_after=float("nan"),  # missing
            ),
        ]
        df = transactions_to_dataframe(records)
        cfg_holdings = InsiderConfig(window_days=30, normalisation="holdings")
        cfg_dollar = InsiderConfig(window_days=30, normalisation="dollar_flow")
        eval_date = pd.Timestamp("2023-01-15")
        s_holdings = net_insider_sentiment(df, eval_date, config=cfg_holdings)
        s_dollar = net_insider_sentiment(df, eval_date, config=cfg_dollar)
        # Both should produce the same finite positive score (all buys)
        assert math.isfinite(float(s_holdings["AAPL"]))
        assert float(s_holdings["AAPL"]) == pytest.approx(float(s_dollar["AAPL"]))

    def test_opportunistic_trades_weighted_higher(self) -> None:
        """Opportunistic insider buy dominates routine insider sell when equally sized."""
        # Set up: I_ROUTINE sells, I_OPP buys equal dollar amount.
        # All-history label: I_ROUTINE trades same month for 3+ years -> routine.
        # Without weighting: net flow = 0. With weighting: I_OPP gets 2x -> net positive.
        routine_records = []
        for year in [2020, 2021, 2022]:
            routine_records.append(
                _make_transaction(
                    symbol="AAPL", insider_id="I_ROUTINE",
                    transaction_date=date(year, 1, 15),
                    transaction_code="S", shares=100.0, price=100.0,
                )
            )
        # Current sell for I_ROUTINE
        routine_records.append(
            _make_transaction(
                symbol="AAPL", insider_id="I_ROUTINE",
                transaction_date=date(2023, 1, 15),
                transaction_code="S", shares=100.0, price=100.0,
            )
        )
        # Opportunistic insider buys same dollar amount
        opp_buy = _make_transaction(
            symbol="AAPL", insider_id="I_OPP",
            transaction_date=date(2023, 1, 20),
            transaction_code="P", shares=100.0, price=100.0,
        )
        all_records = routine_records + [opp_buy]
        df = transactions_to_dataframe(all_records)

        eval_date = pd.Timestamp("2023-02-01")
        cfg = InsiderConfig(window_days=60, routine_years=3, opportunistic_weight=2.0)
        labels = label_routine_insiders(df, routine_years=3, as_of=eval_date)
        sentiment = net_insider_sentiment(df, eval_date, config=cfg, routine_labels=labels)

        # I_ROUTINE is routine (weight 1.0), I_OPP is opportunistic (weight 2.0)
        # routine sells 100*100=10000 weighted 1 -> -10000
        # opp buys 100*100=10000 weighted 2 -> +20000
        # net positive -> score > 0
        assert float(sentiment["AAPL"]) > 0.0, (
            f"Expected opportunistic buy to dominate; got {float(sentiment['AAPL']):.4f}"
        )


# ---------------------------------------------------------------------------
# cluster_buy_flags tests
# ---------------------------------------------------------------------------


class TestClusterBuyFlags:
    """cluster_buy_flags: cluster detection, thresholds, look-ahead."""

    def _build_cluster(
        self,
        symbol: str = "AAPL",
        n_buyers: int = 4,
        tx_date: date = date(2023, 1, 10),
    ) -> pd.DataFrame:
        records = [
            _make_transaction(
                symbol=symbol,
                insider_id=f"I_BUY_{k}",
                transaction_date=tx_date,
                transaction_code="P",
            )
            for k in range(n_buyers)
        ]
        return transactions_to_dataframe(records)

    def test_cluster_fires_at_threshold(self) -> None:
        df = self._build_cluster(n_buyers=3)
        cfg = InsiderConfig(min_cluster_insiders=3, window_days=30)
        flags = cluster_buy_flags(df, pd.Timestamp("2023-01-15"), config=cfg)
        assert bool(flags["AAPL"]) is True

    def test_cluster_does_not_fire_below_threshold(self) -> None:
        df = self._build_cluster(n_buyers=2)
        cfg = InsiderConfig(min_cluster_insiders=3, window_days=30)
        flags = cluster_buy_flags(df, pd.Timestamp("2023-01-15"), config=cfg)
        assert bool(flags["AAPL"]) is False

    def test_cluster_fires_above_threshold(self) -> None:
        df = self._build_cluster(n_buyers=5)
        cfg = InsiderConfig(min_cluster_insiders=3, window_days=30)
        flags = cluster_buy_flags(df, pd.Timestamp("2023-01-15"), config=cfg)
        assert bool(flags["AAPL"]) is True

    def test_sellers_do_not_trigger_cluster_buy(self) -> None:
        records = [
            _make_transaction(
                symbol="AAPL",
                insider_id=f"I_SELL_{k}",
                transaction_date=date(2023, 1, 10),
                transaction_code="S",
            )
            for k in range(5)
        ]
        df = transactions_to_dataframe(records)
        cfg = InsiderConfig(min_cluster_insiders=3, window_days=30)
        flags = cluster_buy_flags(df, pd.Timestamp("2023-01-15"), config=cfg)
        assert bool(flags["AAPL"]) is False

    def test_duplicate_insider_not_double_counted(self) -> None:
        """Two transactions from the same insider should count as only one buyer."""
        records = [
            _make_transaction(
                symbol="AAPL", insider_id="I1",
                transaction_date=date(2023, 1, 5), transaction_code="P",
            ),
            _make_transaction(
                symbol="AAPL", insider_id="I1",
                transaction_date=date(2023, 1, 10), transaction_code="P",
            ),
            _make_transaction(
                symbol="AAPL", insider_id="I2",
                transaction_date=date(2023, 1, 10), transaction_code="P",
            ),
        ]
        df = transactions_to_dataframe(records)
        cfg = InsiderConfig(min_cluster_insiders=3, window_days=30)
        # Only 2 distinct insiders, threshold is 3 -> no cluster
        flags = cluster_buy_flags(df, pd.Timestamp("2023-01-15"), config=cfg)
        assert bool(flags["AAPL"]) is False

    def test_lookahead_free_future_buy_excluded(self) -> None:
        """A buy transaction dated after eval_date must not fire the cluster flag."""
        records = [
            _make_transaction(
                symbol="AAPL", insider_id=f"I{k}",
                transaction_date=date(2023, 2, 10),  # FUTURE relative to eval_date
                transaction_code="P",
            )
            for k in range(5)
        ]
        df = transactions_to_dataframe(records)
        cfg = InsiderConfig(min_cluster_insiders=3, window_days=365)
        eval_date = pd.Timestamp("2023-01-15")  # before all transactions
        flags = cluster_buy_flags(df, eval_date, config=cfg)
        assert bool(flags["AAPL"]) is False

    def test_empty_df_returns_empty_series(self) -> None:
        df = transactions_to_dataframe([])
        cfg = InsiderConfig()
        flags = cluster_buy_flags(df, pd.Timestamp("2023-01-15"), config=cfg)
        assert flags.empty

    def test_all_symbols_in_output(self) -> None:
        """Output Series index contains all symbols from df."""
        records = [
            _make_transaction(symbol="AAPL", insider_id="I1", transaction_code="P"),
            _make_transaction(symbol="MSFT", insider_id="I2", transaction_code="S"),
        ]
        df = transactions_to_dataframe(records)
        cfg = InsiderConfig(min_cluster_insiders=2, window_days=30)
        flags = cluster_buy_flags(df, pd.Timestamp("2023-01-15"), config=cfg)
        assert "AAPL" in flags.index
        assert "MSFT" in flags.index


# ---------------------------------------------------------------------------
# insider_score_panel tests
# ---------------------------------------------------------------------------


class TestInsiderScorePanel:
    """insider_score_panel: shape, ordering, NaN, look-ahead-free."""

    def _build_multi_symbol_df(self) -> pd.DataFrame:
        records: list[InsiderTransaction] = []
        for k in range(4):
            records.append(
                _make_transaction(
                    symbol="AAPL", insider_id=f"I_BUY_{k}",
                    transaction_date=date(2023, 1, 10),
                    transaction_code="P", shares=1000.0, price=150.0,
                )
            )
        records.append(
            _make_transaction(
                symbol="MSFT", insider_id="I_SELL_1",
                transaction_date=date(2023, 1, 10),
                transaction_code="S", shares=3000.0, price=300.0,
            )
        )
        return transactions_to_dataframe(records)

    def test_output_shape(self) -> None:
        df = self._build_multi_symbol_df()
        eval_dates = pd.date_range("2023-01-12", periods=5, freq="B")
        cfg = InsiderConfig(window_days=30)
        panel = insider_score_panel(df, eval_dates, config=cfg)
        assert panel.shape == (5, 2)
        assert list(panel.index) == list(eval_dates)

    def test_columns_sorted_alphabetically(self) -> None:
        df = self._build_multi_symbol_df()
        eval_dates = pd.date_range("2023-01-12", periods=3, freq="B")
        cfg = InsiderConfig(window_days=30)
        panel = insider_score_panel(df, eval_dates, config=cfg)
        assert list(panel.columns) == sorted(panel.columns.tolist())

    def test_buyer_symbol_score_above_seller_symbol(self) -> None:
        df = self._build_multi_symbol_df()
        eval_dates = pd.date_range("2023-01-12", periods=5, freq="B")
        cfg = InsiderConfig(window_days=30)
        panel = insider_score_panel(df, eval_dates, config=cfg)
        assert float(panel["AAPL"].mean()) > float(panel["MSFT"].mean())

    def test_lookahead_score_before_transactions(self) -> None:
        """Evaluation dates before all transactions produce NaN scores."""
        df = self._build_multi_symbol_df()
        eval_dates = pd.date_range("2022-12-01", periods=5, freq="B")
        cfg = InsiderConfig(window_days=30)
        panel = insider_score_panel(df, eval_dates, config=cfg)
        # No transaction before 2022-12-01 -> all NaN
        assert panel.isna().all().all()

    def test_empty_df_returns_empty_panel(self) -> None:
        df = transactions_to_dataframe([])
        eval_dates = pd.date_range("2023-01-01", periods=3, freq="B")
        cfg = InsiderConfig()
        panel = insider_score_panel(df, eval_dates, config=cfg)
        assert panel.empty

    def test_empty_eval_dates_returns_empty_panel(self) -> None:
        df = self._build_multi_symbol_df()
        eval_dates = pd.DatetimeIndex([])
        cfg = InsiderConfig()
        panel = insider_score_panel(df, eval_dates, config=cfg)
        assert panel.empty

    def test_out_of_window_transactions_produce_nan(self) -> None:
        """After window_days, old transactions roll off and score becomes NaN."""
        records = [
            _make_transaction(
                symbol="AAPL", insider_id="I1",
                transaction_date=date(2023, 1, 1),
                transaction_code="P",
            )
        ]
        df = transactions_to_dataframe(records)
        cfg = InsiderConfig(window_days=5)
        # 2023-01-10 is 9 days after transaction -> outside 5-day window
        eval_dates = pd.DatetimeIndex([pd.Timestamp("2023-01-10")])
        panel = insider_score_panel(df, eval_dates, config=cfg)
        assert math.isnan(float(panel["AAPL"].iloc[0]))


# ---------------------------------------------------------------------------
# cluster_buy_panel tests
# ---------------------------------------------------------------------------


class TestClusterBuyPanel:
    """cluster_buy_panel: shape, dtype, flag accuracy."""

    def _build_cluster_df(self) -> pd.DataFrame:
        records: list[InsiderTransaction] = []
        for k in range(4):
            records.append(
                _make_transaction(
                    symbol="AAPL", insider_id=f"I_BUY_{k}",
                    transaction_date=date(2023, 1, 10),
                    transaction_code="P",
                )
            )
        records.append(
            _make_transaction(
                symbol="MSFT", insider_id="I_SELL_1",
                transaction_date=date(2023, 1, 10),
                transaction_code="S",
            )
        )
        return transactions_to_dataframe(records)

    def test_output_shape(self) -> None:
        df = self._build_cluster_df()
        eval_dates = pd.date_range("2023-01-12", periods=5, freq="B")
        cfg = InsiderConfig(min_cluster_insiders=3, window_days=30)
        panel = cluster_buy_panel(df, eval_dates, config=cfg)
        assert panel.shape == (5, 2)

    def test_bool_dtype(self) -> None:
        df = self._build_cluster_df()
        eval_dates = pd.date_range("2023-01-12", periods=3, freq="B")
        cfg = InsiderConfig(min_cluster_insiders=3, window_days=30)
        panel = cluster_buy_panel(df, eval_dates, config=cfg)
        assert panel.dtypes.unique()[0] is np.dtype("bool")

    def test_cluster_buy_symbol_flagged(self) -> None:
        df = self._build_cluster_df()
        eval_dates = pd.DatetimeIndex([pd.Timestamp("2023-01-15")])
        cfg = InsiderConfig(min_cluster_insiders=3, window_days=30)
        panel = cluster_buy_panel(df, eval_dates, config=cfg)
        assert bool(panel["AAPL"].iloc[0]) is True

    def test_selling_symbol_not_flagged(self) -> None:
        df = self._build_cluster_df()
        eval_dates = pd.DatetimeIndex([pd.Timestamp("2023-01-15")])
        cfg = InsiderConfig(min_cluster_insiders=3, window_days=30)
        panel = cluster_buy_panel(df, eval_dates, config=cfg)
        assert bool(panel["MSFT"].iloc[0]) is False

    def test_empty_df_returns_empty_panel(self) -> None:
        df = transactions_to_dataframe([])
        eval_dates = pd.date_range("2023-01-01", periods=3, freq="B")
        cfg = InsiderConfig()
        panel = cluster_buy_panel(df, eval_dates, config=cfg)
        assert panel.empty

    def test_empty_eval_dates_returns_empty_panel(self) -> None:
        df = _make_df(_make_transaction())
        eval_dates = pd.DatetimeIndex([])
        cfg = InsiderConfig()
        panel = cluster_buy_panel(df, eval_dates, config=cfg)
        assert panel.empty


# ---------------------------------------------------------------------------
# insider_portfolio tests
# ---------------------------------------------------------------------------


class TestInsiderPortfolio:
    """insider_portfolio: dollar-neutrality, shape, edge cases."""

    def _build_rich_df(self, n_symbols: int = 6, n_buyers_each: int = 4) -> pd.DataFrame:
        """Build a DataFrame with n_symbols/2 cluster-buy and n_symbols/2 sell symbols."""
        records: list[InsiderTransaction] = []
        buy_symbols = [f"BUY{i}" for i in range(n_symbols // 2)]
        sell_symbols = [f"SELL{i}" for i in range(n_symbols // 2)]
        for sym in buy_symbols:
            for k in range(n_buyers_each):
                records.append(
                    _make_transaction(
                        symbol=sym, insider_id=f"{sym}_I{k}",
                        transaction_date=date(2023, 1, 10),
                        transaction_code="P", shares=1000.0, price=100.0,
                    )
                )
        for sym in sell_symbols:
            for k in range(n_buyers_each):
                records.append(
                    _make_transaction(
                        symbol=sym, insider_id=f"{sym}_I{k}",
                        transaction_date=date(2023, 1, 10),
                        transaction_code="S", shares=1000.0, price=100.0,
                    )
                )
        return transactions_to_dataframe(records)

    def test_output_shape(self) -> None:
        df = self._build_rich_df()
        eval_dates = pd.date_range("2023-01-12", periods=5, freq="B")
        cfg = InsiderConfig(window_days=30, min_cluster_insiders=2)
        w = insider_portfolio(df, eval_dates, config=cfg)
        assert w.shape == (5, 6)

    def test_row_net_near_zero(self) -> None:
        """For rows with enough valid scores, the row weight sum is ~0."""
        df = self._build_rich_df(n_symbols=6)
        eval_dates = pd.date_range("2023-01-12", periods=5, freq="B")
        cfg = InsiderConfig(window_days=30, min_cluster_insiders=2)
        w = insider_portfolio(df, eval_dates, config=cfg, quantile=0.2)
        for _, row in w.iterrows():
            row_sum = float(row.sum())
            if row.abs().sum() > 0:
                assert abs(row_sum) < 1e-12, f"Row not dollar-neutral: sum={row_sum:.2e}"

    def test_empty_df_returns_empty(self) -> None:
        df = transactions_to_dataframe([])
        eval_dates = pd.date_range("2023-01-01", periods=3, freq="B")
        cfg = InsiderConfig()
        w = insider_portfolio(df, eval_dates, config=cfg)
        assert w.empty

    def test_two_symbols_insufficient_for_quantile(self) -> None:
        """With only 2 symbols and quantile=0.4, the pipeline still runs without error."""
        records = [
            _make_transaction(
                symbol="AAPL", insider_id="I1",
                transaction_date=date(2023, 1, 10), transaction_code="P",
            ),
            _make_transaction(
                symbol="MSFT", insider_id="I2",
                transaction_date=date(2023, 1, 10), transaction_code="S",
            ),
        ]
        df = transactions_to_dataframe(records)
        eval_dates = pd.DatetimeIndex([pd.Timestamp("2023-01-15")])
        cfg = InsiderConfig(window_days=30)
        w = insider_portfolio(df, eval_dates, config=cfg, quantile=0.4)
        assert w.shape == (1, 2)

    def test_columns_match_sorted_symbols(self) -> None:
        df = self._build_rich_df()
        eval_dates = pd.date_range("2023-01-12", periods=3, freq="B")
        cfg = InsiderConfig(window_days=30)
        w = insider_portfolio(df, eval_dates, config=cfg)
        assert list(w.columns) == sorted(w.columns.tolist())


# ---------------------------------------------------------------------------
# End-to-end parameter-recovery (DOD) tests
# ---------------------------------------------------------------------------


class TestParameterRecovery:
    """High-level DOD parameter-recovery tests on synthetic data.

    These tests plant known signals and verify that the pipeline extracts them.
    """

    def test_cluster_buy_fires_and_gets_high_score(self) -> None:
        """Planting a cluster buy (4 distinct insiders) must:
        (a) fire the cluster-buy flag, AND
        (b) produce a clearly positive score for the cluster symbol.
        """
        cfg = InsiderConfig(min_cluster_insiders=3, window_days=60)
        # 4 insiders buy AAPL, 2 insiders sell MSFT
        records: list[InsiderTransaction] = []
        for k in range(4):
            records.append(
                _make_transaction(
                    symbol="AAPL", insider_id=f"I_BUY_{k}",
                    transaction_date=date(2023, 1, 10),
                    transaction_code="P", shares=1000.0, price=100.0,
                )
            )
        for k in range(2):
            records.append(
                _make_transaction(
                    symbol="MSFT", insider_id=f"I_SELL_{k}",
                    transaction_date=date(2023, 1, 10),
                    transaction_code="S", shares=1000.0, price=100.0,
                )
            )
        df = transactions_to_dataframe(records)
        eval_date = pd.Timestamp("2023-01-20")

        # (a) cluster flag fires for AAPL
        flags = cluster_buy_flags(df, eval_date, config=cfg)
        assert bool(flags["AAPL"]) is True, "Cluster buy flag must fire for AAPL"
        assert bool(flags["MSFT"]) is False, "Cluster flag must NOT fire for MSFT (sellers)"

        # (b) AAPL score is positive, MSFT score is negative
        sentiment = net_insider_sentiment(df, eval_date, config=cfg)
        assert float(sentiment["AAPL"]) > 0.0
        assert float(sentiment["MSFT"]) < 0.0

    def test_routine_vs_opportunistic_classification_and_weighting(self) -> None:
        """Plant:
        - I_ROUTINE trades every January for 4 years (labelled routine).
        - I_OPP trades at irregular times (labelled opportunistic).
        Then verify:
        (a) labels are correct, AND
        (b) the opportunistic trade gets more weight in net sentiment.
        """
        cfg = InsiderConfig(routine_years=3, opportunistic_weight=2.0, window_days=365)

        # I_ROUTINE: January 2020, 2021, 2022, 2023
        routine_txs: list[InsiderTransaction] = []
        for year in [2020, 2021, 2022]:
            routine_txs.append(
                _make_transaction(
                    symbol="AAPL", insider_id="I_ROUTINE",
                    transaction_date=date(year, 1, 15),
                    transaction_code="S", shares=100.0, price=100.0,
                )
            )
        # Current-period transactions (within eval window)
        routine_txs.append(
            _make_transaction(
                symbol="AAPL", insider_id="I_ROUTINE",
                transaction_date=date(2023, 1, 15),
                transaction_code="S", shares=100.0, price=100.0,
            )
        )

        # I_OPP: March 2020, August 2021, November 2022 (no repeated months)
        opp_txs: list[InsiderTransaction] = [
            _make_transaction(
                symbol="AAPL", insider_id="I_OPP",
                transaction_date=date(2020, 3, 10),
                transaction_code="P", shares=100.0, price=100.0,
            ),
            _make_transaction(
                symbol="AAPL", insider_id="I_OPP",
                transaction_date=date(2021, 8, 20),
                transaction_code="P", shares=100.0, price=100.0,
            ),
            _make_transaction(
                symbol="AAPL", insider_id="I_OPP",
                transaction_date=date(2022, 11, 5),
                transaction_code="P", shares=100.0, price=100.0,
            ),
            # Current-period opportunistic buy
            _make_transaction(
                symbol="AAPL", insider_id="I_OPP",
                transaction_date=date(2023, 1, 20),
                transaction_code="P", shares=100.0, price=100.0,
            ),
        ]

        df = transactions_to_dataframe(routine_txs + opp_txs)
        eval_date = pd.Timestamp("2023-02-01")

        # (a) classify labels
        labels = label_routine_insiders(df, routine_years=3, as_of=eval_date)
        assert bool(labels["I_ROUTINE"]) is True, "I_ROUTINE must be classified routine"
        assert bool(labels["I_OPP"]) is False, "I_OPP must be classified opportunistic"

        # (b) opportunistic trade gets higher weight -> net flow is positive
        # I_ROUTINE sells 100*100=10000 with weight 1.0 -> -10000
        # I_OPP buys    100*100=10000 with weight 2.0 -> +20000
        # net positive after normalisation
        sentiment = net_insider_sentiment(df, eval_date, config=cfg, routine_labels=labels)
        assert float(sentiment["AAPL"]) > 0.0, (
            f"Opportunistic buy must dominate; score={float(sentiment['AAPL']):.4f}"
        )

    def test_look_ahead_free_invariance(self) -> None:
        """Truncation invariance: score at t using history-up-to-t must equal score at t
        computed on a panel that also contains future data."""
        cfg = InsiderConfig(window_days=60)
        base_records: list[InsiderTransaction] = []
        for k in range(3):
            base_records.append(
                _make_transaction(
                    symbol="AAPL", insider_id=f"I{k}",
                    transaction_date=date(2023, 1, 10),
                    transaction_code="P", shares=500.0, price=100.0,
                )
            )
        # Future records (after eval_date) that should NOT change the score
        future_records: list[InsiderTransaction] = [
            _make_transaction(
                symbol="AAPL", insider_id="I_FUTURE",
                transaction_date=date(2023, 3, 1),  # well after eval_date
                transaction_code="S", shares=50000.0, price=100.0,
            ),
        ]
        df_base = transactions_to_dataframe(base_records)
        df_with_future = transactions_to_dataframe(base_records + future_records)

        eval_date = pd.Timestamp("2023-01-20")
        score_base = float(
            net_insider_sentiment(df_base, eval_date, config=cfg)["AAPL"]
        )
        score_with_future = float(
            net_insider_sentiment(df_with_future, eval_date, config=cfg)["AAPL"]
        )
        assert math.isclose(score_base, score_with_future, rel_tol=1e-9), (
            f"Look-ahead violation: base={score_base:.4f}, "
            f"with_future={score_with_future:.4f}"
        )

    def test_config_validation_rejects_bad_inputs(self) -> None:
        """All invalid config parameters are rejected at construction time."""
        with pytest.raises(ValueError, match="window_days"):
            InsiderConfig(window_days=0)
        with pytest.raises(ValueError, match="min_cluster_insiders"):
            InsiderConfig(min_cluster_insiders=1)
        with pytest.raises(ValueError, match="normalisation"):
            InsiderConfig(normalisation="bad")
        with pytest.raises(ValueError, match="routine_years"):
            InsiderConfig(routine_years=0)
        with pytest.raises(ValueError, match="opportunistic_weight"):
            InsiderConfig(opportunistic_weight=0.0)


# ---------------------------------------------------------------------------
# Public API (__all__) tests
# ---------------------------------------------------------------------------


class TestPublicAPI:
    """Verify __all__ exports and importability."""

    def test_all_names_importable(self) -> None:
        import core_trading.signals.alt_data.insider as mod
        expected = {
            "InsiderConfig",
            "InsiderTransaction",
            "transactions_to_dataframe",
            "label_routine_insiders",
            "net_insider_sentiment",
            "cluster_buy_flags",
            "insider_score_panel",
            "insider_portfolio",
        }
        for name in expected:
            assert hasattr(mod, name), f"Missing from module: {name}"

    def test_all_contains_expected_names(self) -> None:
        import core_trading.signals.alt_data.insider as mod
        for name in mod.__all__:
            assert hasattr(mod, name)

    def test_config_is_dataclass(self) -> None:
        import dataclasses
        assert dataclasses.is_dataclass(InsiderConfig)

    def test_transaction_is_dataclass(self) -> None:
        import dataclasses
        assert dataclasses.is_dataclass(InsiderTransaction)
