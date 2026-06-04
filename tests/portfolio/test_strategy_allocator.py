"""Tests for core_trading.portfolio.strategy_allocator (Phase 6.6).

Covers:
* Config validation of every parameter bound.
* Equal weighting; risk parity exact wiring (matches calling the Batch 2
  ERC solver on the Ledoit-Wolf covariance of the overlapping window);
  the min-history and zero-variance equal fallbacks.
* Bayesian posterior-Sharpe weighting against hand-computed shrinkage
  values; zero-floor for negative posteriors; the all-negative equal
  fallback; prior dominance for young strategies; zero-dispersion
  degenerate streams.
* The master-plan decommission rule: live Sharpe below threshold over
  the trailing window halves the weight (renormalised); too-young
  strategies are exempt; diagnostics report the trailing Sharpes.
* Panel validation: leading NaN accepted, interior NaN / all-NaN /
  infinite values rejected.
* combine_strategy_weights: hand-computed netting, validation.
* PHASE 4 INTEGRATION (Phase 6 DOD): the pairs vertical's
  construct_pairs_portfolio output flows through allocate_strategies +
  combine_strategy_weights into one netted book, with the losing sleeve
  decommissioned.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest

from core_trading.portfolio.covariance import ledoit_wolf_covariance
from core_trading.portfolio.pairs_portfolio import (
    PairAllocation,
    PortfolioConfig,
    construct_pairs_portfolio,
)
from core_trading.portfolio.risk_parity import risk_parity_weights
from core_trading.portfolio.strategy_allocator import (
    StrategyAllocation,
    StrategyAllocatorConfig,
    allocate_strategies,
    combine_strategy_weights,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _panel(arr: np.ndarray, names: list[str]) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=arr.shape[0], freq="B")
    return pd.DataFrame(arr, index=index, columns=names)


def _drifting_panel(
    seed: int,
    n_obs: int,
    drifts: list[float],
    vols: list[float] | None = None,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    k = len(drifts)
    sigma = vols if vols is not None else [0.01] * k
    data = rng.standard_normal((n_obs, k)) * np.asarray(sigma) + np.asarray(drifts)
    return _panel(data, [f"S{i}" for i in range(k)])


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


class TestConfigValidation:
    def test_defaults_are_valid(self) -> None:
        cfg = StrategyAllocatorConfig()
        assert cfg.method == "risk_parity"
        assert cfg.decommission_window == 60
        assert cfg.decommission_factor == 0.5

    def test_bad_method(self) -> None:
        with pytest.raises(ValueError, match="method"):
            StrategyAllocatorConfig(method="momentum")

    def test_bad_lookback(self) -> None:
        with pytest.raises(ValueError, match="lookback"):
            StrategyAllocatorConfig(lookback=1)

    @pytest.mark.parametrize("mh", [1, 300])
    def test_bad_min_history(self, mh: int) -> None:
        with pytest.raises(ValueError, match="min_history"):
            StrategyAllocatorConfig(min_history=mh, lookback=252)

    def test_bad_decommission_window(self) -> None:
        with pytest.raises(ValueError, match="decommission_window"):
            StrategyAllocatorConfig(decommission_window=1)

    def test_bad_decommission_sharpe(self) -> None:
        with pytest.raises(ValueError, match="decommission_sharpe"):
            StrategyAllocatorConfig(decommission_sharpe=float("nan"))

    @pytest.mark.parametrize("f", [0.0, 1.5, -0.5])
    def test_bad_decommission_factor(self, f: float) -> None:
        with pytest.raises(ValueError, match="decommission_factor"):
            StrategyAllocatorConfig(decommission_factor=f)

    def test_bad_prior_sharpe(self) -> None:
        with pytest.raises(ValueError, match="bayesian_prior_sharpe"):
            StrategyAllocatorConfig(bayesian_prior_sharpe=float("inf"))

    @pytest.mark.parametrize("n0", [0.0, -1.0, float("nan")])
    def test_bad_prior_strength(self, n0: float) -> None:
        with pytest.raises(ValueError, match="bayesian_prior_strength"):
            StrategyAllocatorConfig(bayesian_prior_strength=n0)


# ---------------------------------------------------------------------------
# Methods
# ---------------------------------------------------------------------------


class TestMethods:
    def test_equal_weighting(self) -> None:
        # decommission_sharpe=-10 isolates the method from the haircut
        # (trailing-60-bar Sharpe noise can dip negative at drift 0.001).
        panel = _drifting_panel(0, 100, [0.001, 0.001, 0.001])
        result = allocate_strategies(
            panel,
            StrategyAllocatorConfig(method="equal", decommission_sharpe=-10.0),
        )
        np.testing.assert_allclose(result.weights.to_numpy(), 1.0 / 3.0, atol=1e-15)
        assert result.method_used == "equal"
        assert result.decommissioned == ()
        assert float(result.weights.sum()) == pytest.approx(1.0, abs=1e-12)

    def test_risk_parity_matches_direct_pipeline(self) -> None:
        # Different strategy vols, all positive drift (no decommission):
        # the allocator must equal risk_parity_weights on the Ledoit-Wolf
        # covariance of the trailing overlap window.
        cfg = StrategyAllocatorConfig(method="risk_parity", lookback=200)
        panel = _drifting_panel(
            1, 300, [0.002, 0.002, 0.002], vols=[0.005, 0.01, 0.02]
        )
        result = allocate_strategies(panel, cfg)
        expected_cov = ledoit_wolf_covariance(panel.iloc[-200:]).covariance
        expected = risk_parity_weights(expected_cov).weights.to_numpy()
        np.testing.assert_allclose(result.weights.to_numpy(), expected, atol=1e-12)
        assert result.method_used == "risk_parity"
        # Low-vol strategy earns the largest share.
        assert result.weights["S0"] > result.weights["S1"] > result.weights["S2"]

    def test_risk_parity_min_history_fallback(self) -> None:
        # The youngest strategy launched 10 bars ago: the overlap window
        # is shorter than min_history -> equal fallback.
        panel = _drifting_panel(2, 100, [0.002, 0.002, 0.002])
        panel.iloc[:90, 2] = np.nan  # S2 live for only 10 bars
        cfg = StrategyAllocatorConfig(method="risk_parity", min_history=20)
        result = allocate_strategies(panel, cfg)
        np.testing.assert_allclose(result.weights.to_numpy(), 1.0 / 3.0, atol=1e-15)
        assert result.method_used == "equal_fallback"

    def test_risk_parity_zero_variance_fallback(self) -> None:
        # Constant live histories carry no risk information at all.
        arr = np.zeros((50, 2))
        panel = _panel(arr, ["S0", "S1"])
        cfg = StrategyAllocatorConfig(method="risk_parity", min_history=10)
        result = allocate_strategies(panel, cfg)
        np.testing.assert_allclose(result.weights.to_numpy(), 0.5, atol=1e-15)
        assert result.method_used == "equal_fallback"

    def test_bayesian_matches_hand_computation(self) -> None:
        cfg = StrategyAllocatorConfig(
            method="bayesian",
            lookback=252,
            bayesian_prior_sharpe=0.0,
            bayesian_prior_strength=60.0,
            decommission_sharpe=-10.0,  # disable the haircut for this test
        )
        panel = _drifting_panel(3, 120, [0.002, 0.0005], vols=[0.01, 0.01])
        result = allocate_strategies(panel, cfg)

        scores = []
        for col in panel.columns:
            live = panel[col].to_numpy()
            sharpe_hat = float(live.mean()) / float(live.std(ddof=1))
            posterior = (60.0 * 0.0 + 120.0 * sharpe_hat) / (60.0 + 120.0)
            scores.append(max(posterior, 0.0))
        expected = np.asarray(scores) / sum(scores)
        np.testing.assert_allclose(result.weights.to_numpy(), expected, atol=1e-12)
        assert result.method_used == "bayesian"

    def test_bayesian_floors_negative_posterior_at_zero(self) -> None:
        cfg = StrategyAllocatorConfig(
            method="bayesian", decommission_sharpe=-10.0
        )
        panel = _drifting_panel(4, 200, [0.003, -0.005], vols=[0.01, 0.01])
        result = allocate_strategies(panel, cfg)
        assert result.weights["S1"] == 0.0
        assert result.weights["S0"] == pytest.approx(1.0, abs=1e-12)

    def test_bayesian_all_negative_equal_fallback(self) -> None:
        cfg = StrategyAllocatorConfig(
            method="bayesian", decommission_sharpe=-10.0
        )
        panel = _drifting_panel(5, 200, [-0.003, -0.005], vols=[0.01, 0.01])
        result = allocate_strategies(panel, cfg)
        np.testing.assert_allclose(result.weights.to_numpy(), 0.5, atol=1e-15)
        assert result.method_used == "equal_fallback"

    def test_bayesian_shrinkage_tempers_young_hot_streak(self) -> None:
        # A 10-bar hot streak carries a per-bar Sharpe ~2; unshrunk
        # Sharpe-proportional weighting would hand it ~90% of capital.
        # The posterior must (a) pull its share far below the raw share,
        # and (b) pull harder as the prior strengthens.
        rng = np.random.default_rng(6)
        veteran = rng.standard_normal(200) * 0.01 + 0.002
        hot = np.full(200, np.nan)
        hot[-10:] = rng.standard_normal(10) * 0.005 + 0.01
        panel = _panel(np.column_stack([veteran, hot]), ["VET", "HOT"])

        def hot_share(prior_strength: float) -> float:
            cfg = StrategyAllocatorConfig(
                method="bayesian",
                decommission_sharpe=-10.0,
                bayesian_prior_strength=prior_strength,
            )
            return float(allocate_strategies(panel, cfg).weights["HOT"])

        vet_live = veteran
        hot_live = hot[-10:]
        raw_sharpes = np.array(
            [
                float(vet_live.mean()) / float(vet_live.std(ddof=1)),
                float(hot_live.mean()) / float(hot_live.std(ddof=1)),
            ]
        )
        raw_hot_share = float(raw_sharpes[1] / raw_sharpes.sum())
        assert raw_hot_share > 0.8  # the streak really is that hot, unshrunk

        share_n60 = hot_share(60.0)
        share_n600 = hot_share(600.0)
        assert share_n60 < raw_hot_share - 0.2  # shrinkage bites hard
        assert share_n600 < share_n60  # stronger prior -> stronger pull

    def test_single_strategy_gets_everything(self) -> None:
        panel = _drifting_panel(7, 100, [0.001])
        result = allocate_strategies(panel)
        assert result.weights.to_numpy().tolist() == [1.0]
        assert result.method_used == "equal_fallback"

    def test_single_strategy_equal_method(self) -> None:
        panel = _drifting_panel(7, 100, [0.001])
        result = allocate_strategies(
            panel, StrategyAllocatorConfig(method="equal")
        )
        assert result.weights.to_numpy().tolist() == [1.0]
        assert result.method_used == "equal"

    def test_constant_positive_stream_bayesian(self) -> None:
        # Zero dispersion, positive mean: signed-infinity Sharpe maps to a
        # +1 conviction score (not a crash).  The constant must be a
        # binary-exact value (2^-7) so the sample std is EXACTLY zero.
        cfg = StrategyAllocatorConfig(
            method="bayesian", decommission_sharpe=-10.0
        )
        arr = np.column_stack(
            [
                np.full(100, 0.0078125),
                np.random.default_rng(8).normal(0.0005, 0.01, 100),
            ]
        )
        panel = _panel(arr, ["CONST", "NOISY"])
        result = allocate_strategies(panel, cfg)
        assert float(result.live_sharpes["CONST"]) == float("inf")
        assert float(result.weights.sum()) == pytest.approx(1.0, abs=1e-12)
        assert result.weights["CONST"] > 0.0


# ---------------------------------------------------------------------------
# Decommission rule
# ---------------------------------------------------------------------------


class TestDecommission:
    def test_halves_and_renormalises(self) -> None:
        # Equal base [1/3, 1/3, 1/3]; S2 is bleeding -> halved to 1/6,
        # renormalised: [0.4, 0.4, 0.2].
        panel = _drifting_panel(9, 100, [0.002, 0.002, -0.003])
        result = allocate_strategies(
            panel, StrategyAllocatorConfig(method="equal")
        )
        np.testing.assert_allclose(
            result.weights.to_numpy(), [0.4, 0.4, 0.2], atol=1e-12
        )
        assert result.decommissioned == ("S2",)
        assert float(result.live_sharpes["S2"]) < 0.0
        assert float(result.live_sharpes["S0"]) > 0.0

    def test_custom_factor(self) -> None:
        panel = _drifting_panel(9, 100, [0.002, -0.003])
        result = allocate_strategies(
            panel,
            StrategyAllocatorConfig(method="equal", decommission_factor=0.25),
        )
        # [0.5, 0.125] renormalised -> [0.8, 0.2].
        np.testing.assert_allclose(result.weights.to_numpy(), [0.8, 0.2], atol=1e-12)

    def test_too_young_is_exempt(self) -> None:
        # Drift 0.005 at vol 0.01 keeps the mature strategies' trailing
        # Sharpe safely positive, isolating the youth exemption.
        panel = _drifting_panel(10, 100, [0.005, 0.005])
        bleed = np.full(100, np.nan)
        bleed[-30:] = -0.005  # 30 bars of losses < 60-bar window
        panel["S2"] = bleed
        result = allocate_strategies(
            panel, StrategyAllocatorConfig(method="equal")
        )
        assert result.decommissioned == ()
        assert np.isnan(result.live_sharpes["S2"])

    def test_constant_negative_stream_decommissioned(self) -> None:
        panel = _drifting_panel(11, 100, [0.005])
        panel["DEAD"] = np.full(100, -0.0078125)  # binary-exact: -inf Sharpe
        result = allocate_strategies(
            panel, StrategyAllocatorConfig(method="equal")
        )
        assert "DEAD" in result.decommissioned
        assert float(result.live_sharpes["DEAD"]) == float("-inf")

    def test_threshold_is_strict_inequality(self) -> None:
        # Sharpe exactly AT the threshold is kept (rule fires strictly below).
        panel = _drifting_panel(12, 100, [0.002])
        panel["FLAT"] = np.zeros(100)  # zero-dispersion zero-mean: Sharpe 0.0
        result = allocate_strategies(
            panel, StrategyAllocatorConfig(method="equal", decommission_sharpe=0.0)
        )
        assert result.decommissioned == ()


# ---------------------------------------------------------------------------
# Panel validation
# ---------------------------------------------------------------------------


class TestPanelValidation:
    def test_leading_nan_accepted(self) -> None:
        panel = _drifting_panel(13, 100, [0.001, 0.001])
        panel.iloc[:40, 1] = np.nan
        result = allocate_strategies(panel, StrategyAllocatorConfig(method="equal"))
        assert float(result.weights.sum()) == pytest.approx(1.0, abs=1e-12)

    def test_interior_nan_raises(self) -> None:
        panel = _drifting_panel(13, 100, [0.001, 0.001])
        panel.iloc[50, 1] = np.nan
        with pytest.raises(ValueError, match="interior NaN"):
            allocate_strategies(panel)

    def test_all_nan_column_raises(self) -> None:
        panel = _drifting_panel(13, 100, [0.001, 0.001])
        panel["S1"] = np.nan
        with pytest.raises(ValueError, match="no valid observations"):
            allocate_strategies(panel)

    def test_infinite_values_raise(self) -> None:
        panel = _drifting_panel(13, 100, [0.001, 0.001])
        panel.iloc[50, 1] = np.inf
        with pytest.raises(ValueError, match="infinite"):
            allocate_strategies(panel)

    def test_no_columns_raises(self) -> None:
        empty = pd.DataFrame(index=pd.date_range("2024-01-01", periods=10))
        with pytest.raises(ValueError, match="at least 1 strategy"):
            allocate_strategies(empty)

    def test_too_few_rows_raises(self) -> None:
        panel = _drifting_panel(13, 100, [0.001]).iloc[:1]
        with pytest.raises(ValueError, match="at least 2 rows"):
            allocate_strategies(panel)


# ---------------------------------------------------------------------------
# combine_strategy_weights
# ---------------------------------------------------------------------------


class TestCombineStrategyWeights:
    def test_hand_computed_netting(self) -> None:
        books = {
            "pairs": pd.Series({"AAA": 0.5, "BBB": -0.5, "SPY": -0.1}),
            "momo": pd.Series({"AAA": 0.3, "SPY": 0.7}),
        }
        allocation = pd.Series({"pairs": 0.6, "momo": 0.4})
        combined = combine_strategy_weights(books, allocation)
        assert list(combined.index) == ["AAA", "BBB", "SPY"]
        assert combined["AAA"] == pytest.approx(0.6 * 0.5 + 0.4 * 0.3, abs=1e-15)
        assert combined["BBB"] == pytest.approx(-0.3, abs=1e-15)
        assert combined["SPY"] == pytest.approx(0.6 * -0.1 + 0.4 * 0.7, abs=1e-15)

    def test_mismatched_strategies_raise(self) -> None:
        books = {"pairs": pd.Series({"AAA": 1.0})}
        allocation = pd.Series({"pairs": 0.5, "momo": 0.5})
        with pytest.raises(ValueError, match="exactly the strategy_weights"):
            combine_strategy_weights(books, allocation)

    def test_nan_book_raises(self) -> None:
        books = {"pairs": pd.Series({"AAA": np.nan})}
        allocation = pd.Series({"pairs": 1.0})
        with pytest.raises(ValueError, match="pairs"):
            combine_strategy_weights(books, allocation)

    def test_nan_allocation_raises(self) -> None:
        books = {"pairs": pd.Series({"AAA": 1.0})}
        allocation = pd.Series({"pairs": np.nan})
        with pytest.raises(ValueError, match="allocation"):
            combine_strategy_weights(books, allocation)


# ---------------------------------------------------------------------------
# Phase 4 pairs integration (Phase 6 DOD)
# ---------------------------------------------------------------------------


class TestPairsIntegration:
    def test_pairs_vertical_through_allocator_into_one_book(self) -> None:
        # 1. The Phase 4 pairs constructor produces its asset book.
        allocations = [
            PairAllocation(
                pair_id="AAA_BBB",
                symbol_y="AAA",
                symbol_x="BBB",
                hedge_ratio=1.0,
                direction=1,
                spread_var=1.0,
                sector="tech",
            ),
            PairAllocation(
                pair_id="CCC_DDD",
                symbol_y="CCC",
                symbol_x="DDD",
                hedge_ratio=0.8,
                direction=-1,
                spread_var=2.0,
                sector="fin",
            ),
        ]
        pairs_book = construct_pairs_portfolio(
            allocations,
            config=PortfolioConfig(beta_neutralize=False),
        )
        pairs_weights = pd.Series(pairs_book.weights)
        assert set(pairs_weights.index) == {"AAA", "BBB", "CCC", "DDD"}

        # 2. A second sleeve (long-only momentum book) plus live returns:
        # the pairs sleeve earns, the momentum sleeve bleeds badly enough
        # to trip the decommission rule.
        momo_weights = pd.Series({"EEE": 0.6, "SPY": 0.4})
        rng = np.random.default_rng(14)
        live = pd.DataFrame(
            {
                "pairs": rng.standard_normal(120) * 0.004 + 0.001,
                "momo": rng.standard_normal(120) * 0.01 - 0.004,
            },
            index=pd.date_range("2024-01-01", periods=120, freq="B"),
        )

        # 3. Allocate capital across the two strategies and net the books.
        allocation = allocate_strategies(
            live,
            StrategyAllocatorConfig(method="risk_parity", min_history=20),
        )
        assert allocation.decommissioned == ("momo",)
        assert allocation.weights["pairs"] > allocation.weights["momo"]

        combined = combine_strategy_weights(
            {"pairs": pairs_weights, "momo": momo_weights},
            allocation.weights,
        )

        # The combined book nets every symbol from both sleeves, each
        # scaled by its sleeve's capital share.
        assert set(combined.index) == {"AAA", "BBB", "CCC", "DDD", "EEE", "SPY"}
        share = float(allocation.weights["pairs"])
        for symbol in ["AAA", "BBB", "CCC", "DDD"]:
            assert combined[symbol] == pytest.approx(
                share * float(pairs_weights[symbol]), abs=1e-15
            )
        assert combined["EEE"] == pytest.approx(
            float(allocation.weights["momo"]) * 0.6, abs=1e-15
        )
        # Gross of the combined book equals the allocation-weighted sum of
        # sleeve grosses (no overlap between these sleeves' symbols).
        expected_gross = share * float(
            np.abs(pairs_weights.to_numpy()).sum()
        ) + float(allocation.weights["momo"]) * 1.0
        assert float(np.abs(combined.to_numpy()).sum()) == pytest.approx(
            expected_gross, abs=1e-12
        )


# ---------------------------------------------------------------------------
# Result DTO
# ---------------------------------------------------------------------------


class TestStrategyAllocationDTO:
    def test_frozen(self) -> None:
        panel = _drifting_panel(15, 100, [0.001, 0.001])
        result = allocate_strategies(panel, StrategyAllocatorConfig(method="equal"))
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.method_used = "other"  # type: ignore[misc]

    def test_equality_ignores_series(self) -> None:
        s1 = pd.Series([0.5, 0.5])
        s2 = pd.Series([0.9, 0.1])
        a = StrategyAllocation(
            weights=s1, method_used="equal", decommissioned=(), live_sharpes=s1
        )
        b = StrategyAllocation(
            weights=s2, method_used="equal", decommissioned=(), live_sharpes=s2
        )
        assert a == b
