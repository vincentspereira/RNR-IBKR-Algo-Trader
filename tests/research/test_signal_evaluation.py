"""Tests for core_trading.research.signal_evaluation (Phase 5 DOD harness).

Covers:
* price_panel_from_series -- shape/columns/index handling and guards.
* ou_zscore_series -- warmup, finiteness, look-ahead-freeness, guards.
* mean_reversion_positions -- entry / exit / stop / time-stop state machine.
* positions_to_weights, mean_reversion_grid.
* evaluate_signal -- the gate accepts a genuine OU edge (PROMOTE) and rejects a
  random walk (ARCHIVE) even though its naive PSR looks significant; plus the
  no-trade, single-trial, and empty-grid paths.
* _build_memo -- all rationale branches including the mode-disagreement warning.

The data is simulated with known structure and fixed seeds, so every assertion
is deterministic (no flakiness): a strongly mean-reverting Ornstein-Uhlenbeck
price is genuinely tradeable, a random walk is not.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core_trading.research.overfitting import DeflatedSharpeResult
from core_trading.research.signal_evaluation import (
    SignalEvaluation,
    _build_memo,
    build_mean_reversion_weight_fn,
    evaluate_signal,
    mean_reversion_grid,
    mean_reversion_positions,
    ou_zscore_series,
    positions_to_weights,
    price_panel_from_series,
)
from core_trading.signals.stochastic.ou import simulate as ou_simulate

# ---------------------------------------------------------------------------
# Shared fixtures / builders
# ---------------------------------------------------------------------------

_N = 3000
_OU_SEED = 20240601
_RW_SEED = 7


def _ou_prices() -> pd.Series:
    """Strongly mean-reverting OU price path (genuine, tradeable edge)."""
    return ou_simulate(n=_N, dt=1.0, x0=100.0, kappa=0.30, mu=100.0, sigma=2.0, seed=_OU_SEED)


def _random_walk() -> pd.Series:
    """A random walk -- no mean reversion, so the MR rule has no real edge."""
    rng = np.random.default_rng(_RW_SEED)
    rw = 100.0 + np.cumsum(rng.standard_normal(_N)) * 1.0
    return pd.Series(np.maximum(rw, 1.0))


def _evaluate(close: pd.Series, name: str) -> SignalEvaluation:
    panel = price_panel_from_series(close, symbol="SIM")
    px = panel.xs("SIM", level="symbol")["close"]
    rule = build_mean_reversion_weight_fn(px, symbol="SIM", lookback=120, refit_every=5)
    return evaluate_signal(panel, rule, mean_reversion_grid(), signal_name=name)


# ---------------------------------------------------------------------------
# price_panel_from_series
# ---------------------------------------------------------------------------


class TestPricePanel:
    def test_columns_and_index_names(self) -> None:
        panel = price_panel_from_series(pd.Series([10.0, 11.0, 12.0]), symbol="ABC")
        assert list(panel.columns) == ["open", "high", "low", "close", "volume"]
        assert list(panel.index.names) == ["symbol", "timestamp"]
        assert panel.index.get_level_values("symbol").unique().tolist() == ["ABC"]

    def test_ohlc_equal_close(self) -> None:
        panel = price_panel_from_series(pd.Series([10.0, 11.0, 12.0]))
        for col in ("open", "high", "low"):
            np.testing.assert_array_equal(panel[col].to_numpy(), panel["close"].to_numpy())

    def test_rangeindex_gets_business_days(self) -> None:
        panel = price_panel_from_series(pd.Series([10.0, 11.0, 12.0]))
        ts = panel.index.get_level_values("timestamp")
        assert isinstance(ts, pd.DatetimeIndex)
        assert len(ts) == 3

    def test_datetimeindex_preserved(self) -> None:
        idx = pd.date_range("2021-01-04", periods=4, freq="B", tz="UTC")
        panel = price_panel_from_series(pd.Series([1.0, 2.0, 3.0, 4.0], index=idx))
        ts = panel.index.get_level_values("timestamp")
        assert list(ts) == list(idx)

    def test_raises_too_short(self) -> None:
        with pytest.raises(ValueError, match="at least 2 prices"):
            price_panel_from_series(pd.Series([10.0]))

    def test_raises_non_positive(self) -> None:
        with pytest.raises(ValueError, match="finite and strictly positive"):
            price_panel_from_series(pd.Series([10.0, -1.0, 12.0]))

    def test_raises_non_finite(self) -> None:
        with pytest.raises(ValueError, match="finite and strictly positive"):
            price_panel_from_series(pd.Series([10.0, float("nan"), 12.0]))


# ---------------------------------------------------------------------------
# ou_zscore_series
# ---------------------------------------------------------------------------


class TestOUZscore:
    def test_warmup_is_nan(self) -> None:
        zhl = ou_zscore_series(_ou_prices(), lookback=120, refit_every=5)
        assert zhl["zscore"].iloc[:120].isna().all()

    def test_finite_after_warmup(self) -> None:
        zhl = ou_zscore_series(_ou_prices(), lookback=120, refit_every=5)
        post = zhl["zscore"].iloc[120:]
        assert np.isfinite(post.to_numpy()).all()

    def test_half_life_positive_after_warmup(self) -> None:
        zhl = ou_zscore_series(_ou_prices(), lookback=120, refit_every=5)
        hl = zhl["half_life"].iloc[120:].to_numpy()
        assert np.all(hl[np.isfinite(hl)] > 0.0)

    def test_look_ahead_free(self) -> None:
        """Truncating the series after bar K leaves every z at t < K unchanged.

        The estimate at t depends only on data up to t and on a refit schedule
        fixed from the start, so truncation invariance is exact.
        """
        prices = _ou_prices()
        full = ou_zscore_series(prices, lookback=120, refit_every=5)
        cut = 2000
        trunc = ou_zscore_series(prices.iloc[:cut], lookback=120, refit_every=5)
        np.testing.assert_allclose(
            full["zscore"].iloc[:cut].to_numpy(),
            trunc["zscore"].to_numpy(),
            equal_nan=True,
            rtol=0.0,
            atol=0.0,
        )

    def test_refit_every_one(self) -> None:
        zhl = ou_zscore_series(_ou_prices(), lookback=120, refit_every=1)
        assert np.isfinite(zhl["zscore"].iloc[120:].to_numpy()).all()

    def test_raises_short_lookback(self) -> None:
        with pytest.raises(ValueError, match="lookback must be >= 30"):
            ou_zscore_series(_ou_prices(), lookback=10)

    def test_raises_bad_refit(self) -> None:
        with pytest.raises(ValueError, match="refit_every must be >= 1"):
            ou_zscore_series(_ou_prices(), lookback=120, refit_every=0)


# ---------------------------------------------------------------------------
# mean_reversion_positions
# ---------------------------------------------------------------------------


class TestMeanReversionPositions:
    def test_values_in_set(self) -> None:
        zhl = ou_zscore_series(_ou_prices(), lookback=120, refit_every=5)
        pos = mean_reversion_positions(zhl["zscore"], zhl["half_life"])
        assert set(np.unique(pos.to_numpy())).issubset({-1.0, 0.0, 1.0})

    def test_enters_short_on_high_z(self) -> None:
        # z jumps above entry at index 1, then stays moderate -> short entered.
        z = pd.Series([0.0, 2.5, 1.0, 0.8, 0.7])
        hl = pd.Series([5.0] * 5)
        pos = mean_reversion_positions(z, hl, entry=2.0, exit_band=0.5, stop=4.0)
        assert pos.iloc[1] == -1.0
        assert pos.iloc[2] == -1.0  # still held (|z|=1.0 between exit and stop)

    def test_enters_long_on_low_z(self) -> None:
        z = pd.Series([0.0, -2.5, -1.0, -0.7])
        hl = pd.Series([5.0] * 4)
        pos = mean_reversion_positions(z, hl, entry=2.0, exit_band=0.5, stop=4.0)
        assert pos.iloc[1] == 1.0

    def test_take_profit_exit(self) -> None:
        z = pd.Series([0.0, 2.5, 0.3])  # reverts inside exit band -> flat
        hl = pd.Series([5.0] * 3)
        pos = mean_reversion_positions(z, hl, entry=2.0, exit_band=0.5, stop=4.0)
        assert pos.iloc[1] == -1.0
        assert pos.iloc[2] == 0.0

    def test_stop_loss_exit(self) -> None:
        z = pd.Series([0.0, 2.5, 4.5])  # blows through stop -> flat
        hl = pd.Series([5.0] * 3)
        pos = mean_reversion_positions(z, hl, entry=2.0, exit_band=0.5, stop=4.0)
        assert pos.iloc[2] == 0.0

    def test_time_stop_exit(self) -> None:
        # Held longer than time_stop_mult * half_life (1 * 2 = 2 bars) -> flat.
        z = pd.Series([0.0, 2.5, 1.5, 1.4, 1.3])
        hl = pd.Series([2.0] * 5)
        pos = mean_reversion_positions(
            z, hl, entry=2.0, exit_band=0.5, stop=6.0, time_stop_mult=1.0
        )
        # Enter at 1; after 2 held bars the time stop fires.
        assert pos.iloc[1] == -1.0
        assert pos.iloc[-1] == 0.0

    def test_nan_z_is_flat(self) -> None:
        z = pd.Series([float("nan"), 2.5, float("nan")])
        hl = pd.Series([float("nan")] * 3)
        pos = mean_reversion_positions(z, hl, entry=2.0, exit_band=0.5, stop=4.0)
        assert pos.iloc[0] == 0.0
        assert pos.iloc[2] == 0.0

    def test_infinite_half_life_no_time_stop(self) -> None:
        # Non-mean-reverting half-life -> time stop disabled; exit only on bands.
        z = pd.Series([0.0, 2.5, 1.0, 1.0, 1.0, 1.0])
        hl = pd.Series([float("inf")] * 6)
        pos = mean_reversion_positions(
            z, hl, entry=2.0, exit_band=0.5, stop=4.0, time_stop_mult=1.0
        )
        assert (pos.iloc[1:] == -1.0).all()  # never time-stopped, never reverted

    def test_raises_bad_thresholds(self) -> None:
        z = pd.Series([0.0, 1.0])
        hl = pd.Series([5.0, 5.0])
        with pytest.raises(ValueError, match="0 < exit_band < entry < stop"):
            mean_reversion_positions(z, hl, entry=2.0, exit_band=2.5, stop=4.0)


# ---------------------------------------------------------------------------
# positions_to_weights and grid
# ---------------------------------------------------------------------------


class TestWeightsAndGrid:
    def test_positions_to_weights(self) -> None:
        pos = pd.Series([1.0, 0.0, -1.0], name="position")
        w = positions_to_weights(pos, symbol="XYZ")
        assert list(w.columns) == ["XYZ"]
        np.testing.assert_array_equal(w["XYZ"].to_numpy(), pos.to_numpy())

    def test_grid_size_and_keys(self) -> None:
        grid = mean_reversion_grid()
        assert len(grid) == 6  # 3 entries x 2 exit bands
        for cfg in grid:
            assert set(cfg) == {"entry", "exit_band", "stop"}

    def test_grid_custom(self) -> None:
        grid = mean_reversion_grid(entries=(1.0, 2.0), exit_bands=(0.5,), stop=3.0)
        assert len(grid) == 2
        assert all(cfg["stop"] == 3.0 for cfg in grid)


# ---------------------------------------------------------------------------
# evaluate_signal -- the gate
# ---------------------------------------------------------------------------


class TestGatePromotesGenuineEdge:
    def test_ou_is_promoted(self) -> None:
        ev = _evaluate(_ou_prices(), "OU mean-reversion (genuine)")
        assert ev.is_promoted
        assert ev.verdict == "PROMOTE"
        assert ev.deflated is not None
        assert ev.deflated.deflated_sharpe > 0.95
        assert ev.observed_sharpe_annualised > 0.0

    def test_ou_metadata(self) -> None:
        ev = _evaluate(_ou_prices(), "OU mean-reversion (genuine)")
        assert ev.n_trials == 6
        assert set(ev.best_params) == {"entry", "exit_band", "stop"}
        assert ev.modes_agree
        assert "PROMOTE" in ev.memo
        assert ev.memo.isascii()


class TestGateRejectsNoise:
    def test_random_walk_is_archived(self) -> None:
        ev = _evaluate(_random_walk(), "OU mean-reversion (random walk)")
        assert not ev.is_promoted
        assert ev.verdict == "ARCHIVE"
        assert ev.deflated is not None
        assert ev.deflated.deflated_sharpe <= 0.95
        assert "ARCHIVE" in ev.memo

    def test_deflation_downgrades_spurious_significance(self) -> None:
        """The crux: the random walk's naive PSR-vs-0 looks significant, but the
        deflated Sharpe (correcting for the configurations tried) does not."""
        ev = _evaluate(_random_walk(), "OU mean-reversion (random walk)")
        assert ev.deflated is not None
        assert ev.deflated.probabilistic_sharpe > 0.95  # naive view: "significant"
        assert ev.deflated.deflated_sharpe <= 0.95  # deflated view: not significant


class TestGateContrast:
    def test_ou_beats_random_walk(self) -> None:
        ou = _evaluate(_ou_prices(), "ou")
        rw = _evaluate(_random_walk(), "rw")
        assert ou.deflated is not None and rw.deflated is not None
        assert ou.deflated.deflated_sharpe > rw.deflated.deflated_sharpe


# ---------------------------------------------------------------------------
# evaluate_signal -- edge cases
# ---------------------------------------------------------------------------


class TestEvaluateEdgeCases:
    def test_empty_grid_raises(self) -> None:
        panel = price_panel_from_series(_ou_prices(), symbol="SIM")
        rule = build_mean_reversion_weight_fn(
            panel.xs("SIM", level="symbol")["close"], symbol="SIM"
        )
        with pytest.raises(ValueError, match="at least one configuration"):
            evaluate_signal(panel, rule, [], signal_name="x")

    def test_never_trading_rule_archives_with_no_deflated(self) -> None:
        panel = price_panel_from_series(_ou_prices(), symbol="SIM")

        def flat_rule(p: pd.DataFrame, params: object) -> pd.DataFrame:  # noqa: ARG001
            ts = p.xs("SIM", level="symbol").index
            return pd.DataFrame({"SIM": np.zeros(len(ts))}, index=ts)

        ev = evaluate_signal(
            panel, flat_rule, [{"entry": 2.0}], signal_name="never trades"
        )
        assert ev.verdict == "ARCHIVE"
        assert ev.deflated is None
        assert "fewer than 2" in ev.memo

    def test_single_trial_grid(self) -> None:
        # n_trials == 1 exercises the trial_sharpe_std=0.0 branch.
        ev = _evaluate_single(_ou_prices())
        assert ev.n_trials == 1
        assert ev.deflated is not None
        assert ev.deflated.n_trials == 1

    def test_check_modes_false_skips_event_driven(self) -> None:
        panel = price_panel_from_series(_ou_prices(), symbol="SIM")
        rule = build_mean_reversion_weight_fn(
            panel.xs("SIM", level="symbol")["close"], symbol="SIM"
        )
        ev = evaluate_signal(
            panel, rule, mean_reversion_grid(), signal_name="x", check_modes=False
        )
        assert ev.modes_agree  # defaults to True when the check is skipped


def _evaluate_single(close: pd.Series) -> SignalEvaluation:
    panel = price_panel_from_series(close, symbol="SIM")
    rule = build_mean_reversion_weight_fn(
        panel.xs("SIM", level="symbol")["close"], symbol="SIM", lookback=120
    )
    grid = [{"entry": 2.0, "exit_band": 0.5, "stop": 4.0}]
    return evaluate_signal(panel, rule, grid, signal_name="single")


# ---------------------------------------------------------------------------
# _build_memo -- all rationale branches
# ---------------------------------------------------------------------------


class TestBuildMemo:
    def _dsr(self, deflated: float) -> DeflatedSharpeResult:
        return DeflatedSharpeResult(
            deflated_sharpe=deflated,
            probabilistic_sharpe=0.99,
            observed_sharpe=0.1,
            expected_max_sharpe=0.05,
            n_trials=6,
            n_obs=200,
        )

    def test_memo_no_deflated(self) -> None:
        memo = _build_memo(
            "sig", "ARCHIVE", 6, {"entry": 2.0}, 0.0, None, True, 0.95
        )
        assert "n/a" in memo
        assert memo.isascii()

    def test_memo_promote(self) -> None:
        memo = _build_memo(
            "sig", "PROMOTE", 6, {"entry": 2.0}, 1.2, self._dsr(0.99), True, 0.95
        )
        assert "clears the threshold" in memo
        assert memo.isascii()

    def test_memo_archive_with_deflated(self) -> None:
        memo = _build_memo(
            "sig", "ARCHIVE", 6, {"entry": 2.0}, 0.3, self._dsr(0.4), True, 0.95
        )
        assert "not" in memo.lower()

    def test_memo_mode_disagreement_warning(self) -> None:
        memo = _build_memo(
            "sig", "PROMOTE", 6, {"entry": 2.0}, 1.2, self._dsr(0.99), False, 0.95
        )
        assert "WARNING" in memo
        assert "disagreed" in memo


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class TestPublicAPI:
    def test_imports(self) -> None:
        from core_trading.research.signal_evaluation import (  # noqa: F401
            SignalEvaluation,
            build_mean_reversion_weight_fn,
            evaluate_signal,
            mean_reversion_grid,
            mean_reversion_positions,
            ou_zscore_series,
            positions_to_weights,
            price_panel_from_series,
        )
