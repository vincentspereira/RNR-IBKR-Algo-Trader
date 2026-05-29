"""Tests for core_trading.research.overfitting.

Validated against known regimes: pure-noise strategy banks should look overfit
(high PBO, non-significant reality checks); a strategy with a genuine edge
planted among noise should be detected (low PBO, significant SPA/RC). The
lockbox tests assert the single-use discipline and its persistence.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from core_trading.research import overfitting as ofit


@pytest.fixture
def rng() -> np.random.Generator:
    return np.random.default_rng(424242)


# ----------------------------------------------------------------------- Sharpe
class TestSharpeRatio:
    def test_annualised_scaling(self, rng) -> None:
        r = rng.standard_normal(1000) * 0.01 + 0.001
        ann = ofit.sharpe_ratio(r, periods_per_year=252)
        per = ofit.sharpe_ratio(r, annualised=False)
        assert ann == pytest.approx(per * np.sqrt(252), rel=1e-9)

    def test_zero_volatility(self) -> None:
        assert ofit.sharpe_ratio([0.01, 0.01, 0.01]) == 0.0

    def test_too_few(self) -> None:
        with pytest.raises(ValueError):
            ofit.sharpe_ratio([0.01])


class TestProbabilisticSharpe:
    def test_increases_with_sample(self) -> None:
        a = ofit.probabilistic_sharpe_ratio(0.1, 100)
        b = ofit.probabilistic_sharpe_ratio(0.1, 1000)
        assert b > a  # more data => more confident a positive Sharpe is real

    def test_at_benchmark_is_half(self) -> None:
        assert ofit.probabilistic_sharpe_ratio(0.1, 500, benchmark_sharpe=0.1) == pytest.approx(
            0.5, abs=1e-9
        )

    def test_bad_n_obs(self) -> None:
        with pytest.raises(ValueError):
            ofit.probabilistic_sharpe_ratio(0.1, 1)

    def test_bad_denominator(self) -> None:
        # Extreme negative skew with high Sharpe can drive the denominator <= 0.
        with pytest.raises(ValueError):
            ofit.probabilistic_sharpe_ratio(2.0, 100, skew=2.0, kurtosis=1.0)


class TestDeflatedSharpe:
    def test_with_trial_std(self, rng) -> None:
        r = rng.standard_normal(1000) * 0.01 + 0.0008
        res = ofit.deflated_sharpe_ratio(r, n_trials=20, trial_sharpe_std=0.3)
        assert 0.0 <= res.deflated_sharpe <= 1.0
        assert res.expected_max_sharpe > 0
        assert res.n_trials == 20

    def test_more_trials_lowers_dsr(self, rng) -> None:
        r = rng.standard_normal(1000) * 0.01 + 0.0015
        few = ofit.deflated_sharpe_ratio(r, n_trials=5, trial_sharpe_std=0.3)
        many = ofit.deflated_sharpe_ratio(r, n_trials=500, trial_sharpe_std=0.3)
        assert many.deflated_sharpe <= few.deflated_sharpe

    def test_with_trial_sharpes(self, rng) -> None:
        r = rng.standard_normal(500) * 0.01 + 0.001
        trials = rng.standard_normal(30) * 0.3
        res = ofit.deflated_sharpe_ratio(r, n_trials=30, trial_sharpes=trials)
        assert isinstance(res.deflated_sharpe, float)

    def test_single_trial_expected_max_zero(self, rng) -> None:
        r = rng.standard_normal(500) * 0.01 + 0.001
        res = ofit.deflated_sharpe_ratio(r, n_trials=1, trial_sharpe_std=0.3)
        assert res.expected_max_sharpe == 0.0

    def test_missing_spread_inputs(self, rng) -> None:
        with pytest.raises(ValueError):
            ofit.deflated_sharpe_ratio(rng.standard_normal(100), n_trials=10)

    def test_too_few_returns(self) -> None:
        with pytest.raises(ValueError):
            ofit.deflated_sharpe_ratio([0.01], n_trials=10, trial_sharpe_std=0.3)

    def test_zero_trials_raises(self, rng) -> None:
        with pytest.raises(ValueError):
            ofit.deflated_sharpe_ratio(rng.standard_normal(100), n_trials=0, trial_sharpe_std=0.3)

    def test_single_trial_sharpe_raises(self, rng) -> None:
        with pytest.raises(ValueError):
            ofit.deflated_sharpe_ratio(rng.standard_normal(100), n_trials=5, trial_sharpes=[0.1])

    def test_significance_threshold(self) -> None:
        hi = ofit.DeflatedSharpeResult(0.99, 0.99, 1.0, 0.1, 10, 500)
        lo = ofit.DeflatedSharpeResult(0.5, 0.5, 0.1, 0.5, 10, 500)
        assert hi.is_significant and not lo.is_significant


# -------------------------------------------------------------------------- PBO
class TestPBO:
    def test_noise_is_overfit(self, rng) -> None:
        mat = rng.standard_normal((500, 20)) * 0.01
        res = ofit.probability_of_backtest_overfitting(mat, n_splits=10)
        assert res.pbo > 0.4  # pure noise: selection no better than chance
        assert res.n_strategies == 20

    def test_genuine_edge_low_pbo(self, rng) -> None:
        noise = rng.standard_normal((600, 15)) * 0.01
        edge = (rng.standard_normal(600) * 0.005 + 0.004).reshape(-1, 1)
        mat = np.hstack([noise, edge])  # last column has a persistent edge
        res = ofit.probability_of_backtest_overfitting(mat, n_splits=10)
        assert res.pbo < 0.25
        assert not res.is_overfit

    def test_accepts_dataframe(self, rng) -> None:
        df = pd.DataFrame(rng.standard_normal((200, 5)) * 0.01)
        res = ofit.probability_of_backtest_overfitting(df, n_splits=8)
        assert 0.0 <= res.pbo <= 1.0

    def test_odd_n_splits(self, rng) -> None:
        with pytest.raises(ValueError):
            ofit.probability_of_backtest_overfitting(rng.standard_normal((100, 5)), n_splits=7)

    def test_one_strategy(self, rng) -> None:
        with pytest.raises(ValueError):
            ofit.probability_of_backtest_overfitting(rng.standard_normal((100, 1)))

    def test_not_2d(self, rng) -> None:
        with pytest.raises(ValueError):
            ofit.probability_of_backtest_overfitting(rng.standard_normal(100))

    def test_too_few_rows(self, rng) -> None:
        with pytest.raises(ValueError):
            ofit.probability_of_backtest_overfitting(rng.standard_normal((4, 5)), n_splits=8)


# ------------------------------------------------------ reality check / SPA test
class TestBootstrapTests:
    def test_noise_not_significant(self, rng) -> None:
        mat = rng.standard_normal((400, 10)) * 0.01
        rc = ofit.whites_reality_check(mat, n_bootstrap=300, seed=1)
        spa = ofit.hansens_spa_test(mat, n_bootstrap=300, seed=1)
        assert not rc.is_significant()
        assert not spa.is_significant()

    def test_strong_strategy_detected(self, rng) -> None:
        noise = rng.standard_normal((400, 8)) * 0.01
        strong = (rng.standard_normal(400) * 0.005 + 0.006).reshape(-1, 1)
        mat = np.hstack([noise, strong])
        rc = ofit.whites_reality_check(mat, n_bootstrap=400, seed=2)
        spa = ofit.hansens_spa_test(mat, n_bootstrap=400, seed=2)
        assert rc.is_significant()
        assert spa.is_significant()
        assert rc.best_strategy == 8

    def test_reproducible_with_seed(self, rng) -> None:
        mat = rng.standard_normal((300, 6)) * 0.01
        a = ofit.whites_reality_check(mat, n_bootstrap=200, seed=7)
        b = ofit.whites_reality_check(mat, n_bootstrap=200, seed=7)
        assert a.pvalue == b.pvalue

    def test_spa_less_conservative(self, rng) -> None:
        # SPA removes obviously-bad strategies, so its p-value should be <= RC's
        # when many poor strategies pad the set.
        noise = rng.standard_normal((400, 20)) * 0.01
        mild = (rng.standard_normal(400) * 0.01 + 0.0025).reshape(-1, 1)
        mat = np.hstack([noise, mild])
        rc = ofit.whites_reality_check(mat, n_bootstrap=500, seed=3)
        spa = ofit.hansens_spa_test(mat, n_bootstrap=500, seed=3)
        assert spa.pvalue <= rc.pvalue + 1e-9

    def test_not_2d(self, rng) -> None:
        with pytest.raises(ValueError):
            ofit.whites_reality_check(rng.standard_normal(100))

    def test_zero_strategies(self) -> None:
        with pytest.raises(ValueError):
            ofit.whites_reality_check(np.zeros((10, 0)))

    def test_spa_short_sample_newey_west(self, rng) -> None:
        # 2 rows exercises the short-sample Newey-West branch (n < 3).
        res = ofit.hansens_spa_test(rng.standard_normal((2, 3)) * 0.01, n_bootstrap=50, seed=1)
        assert 0.0 <= res.pvalue <= 1.0


# ----------------------------------------------------------------------- lockbox
class TestOutOfSampleLockbox:
    @pytest.fixture
    def data(self) -> pd.DataFrame:
        idx = pd.date_range("2020-01-01", periods=100, freq="D", tz="UTC")
        return pd.DataFrame({"px": np.arange(100, dtype=float)}, index=idx)

    def test_development_set_size(self, data, tmp_path) -> None:
        box = ofit.OutOfSampleLockbox(
            data, lockbox_fraction=0.2, ledger_path=tmp_path / "ledger.json"
        )
        assert len(box.development_set) == 80
        assert box.lockbox_size == 20

    def test_open_returns_holdout_once(self, data, tmp_path) -> None:
        box = ofit.OutOfSampleLockbox(
            data, lockbox_fraction=0.2, ledger_path=tmp_path / "ledger.json"
        )
        held = box.open_lockbox("final evaluation of pairs strategy")
        assert len(held) == 20
        assert box.is_opened()

    def test_second_open_raises(self, data, tmp_path) -> None:
        ledger = tmp_path / "ledger.json"
        box = ofit.OutOfSampleLockbox(data, ledger_path=ledger)
        box.open_lockbox("first look")
        with pytest.raises(ofit.LockboxAlreadyOpenedError):
            box.open_lockbox("sneaky second look")

    def test_persistence_across_instances(self, data, tmp_path) -> None:
        ledger = tmp_path / "ledger.json"
        ofit.OutOfSampleLockbox(data, ledger_path=ledger).open_lockbox("once")
        fresh = ofit.OutOfSampleLockbox(data, ledger_path=ledger)
        assert fresh.is_opened()
        with pytest.raises(ofit.LockboxAlreadyOpenedError):
            fresh.open_lockbox("again")

    def test_force_records_violation(self, data, tmp_path) -> None:
        ledger = tmp_path / "ledger.json"
        box = ofit.OutOfSampleLockbox(data, ledger_path=ledger)
        box.open_lockbox("legit")
        box.open_lockbox("forced override", force=True)
        record = json.loads(ledger.read_text(encoding="utf-8"))
        assert record["default"]["violations"][0]["forced"] is True

    def test_named_lockboxes_independent(self, data, tmp_path) -> None:
        ledger = tmp_path / "ledger.json"
        a = ofit.OutOfSampleLockbox(data, ledger_path=ledger, name="stratA")
        b = ofit.OutOfSampleLockbox(data, ledger_path=ledger, name="stratB")
        a.open_lockbox("eval A")
        assert not b.is_opened()
        b.open_lockbox("eval B")  # independent, must not raise

    def test_empty_reason_rejected(self, data, tmp_path) -> None:
        box = ofit.OutOfSampleLockbox(data, ledger_path=tmp_path / "l.json")
        with pytest.raises(ValueError):
            box.open_lockbox("   ")

    def test_bad_fraction(self, data, tmp_path) -> None:
        with pytest.raises(ValueError):
            ofit.OutOfSampleLockbox(data, lockbox_fraction=1.5, ledger_path=tmp_path / "l.json")

    def test_tiny_dataset(self, tmp_path) -> None:
        with pytest.raises(ValueError):
            ofit.OutOfSampleLockbox(pd.Series([1.0]), ledger_path=tmp_path / "l.json")

    def test_fingerprint_changes_with_data(self, tmp_path) -> None:
        idx = pd.date_range("2020-01-01", periods=50, freq="D", tz="UTC")
        d1 = pd.DataFrame({"px": np.arange(50, dtype=float)}, index=idx)
        d2 = pd.DataFrame({"px": np.arange(50, dtype=float) * 2}, index=idx)
        l1, l2 = tmp_path / "a.json", tmp_path / "b.json"
        ofit.OutOfSampleLockbox(d1, ledger_path=l1).open_lockbox("x")
        ofit.OutOfSampleLockbox(d2, ledger_path=l2).open_lockbox("x")
        fp1 = json.loads(l1.read_text())["default"]["fingerprint"]
        fp2 = json.loads(l2.read_text())["default"]["fingerprint"]
        assert fp1 != fp2
