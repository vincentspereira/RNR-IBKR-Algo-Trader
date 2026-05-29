"""Phase 2 smoke check: sanity-validate research toolkit on synthetic data."""
import warnings

import numpy as np
import pandas as pd

import core_trading.research as R


def main() -> None:
    warnings.simplefilter("error")  # surface any hidden warnings
    rng = np.random.default_rng(0)

    rw = np.cumsum(rng.standard_normal(500))
    wn = rng.standard_normal(500)
    print("ADF rw  sig@5%:", R.adf_test(rw).is_significant())  # expect False
    print("ADF wn  sig@5%:", R.adf_test(wn).is_significant())  # expect True
    print("KPSS wn sig@5%:", R.kpss_test(wn).is_significant())  # expect False
    print("PP  rw  sig@5%:", R.phillips_perron_test(rw).is_significant())
    print("Hurst rw:", round(R.hurst_exponent(rw).exponent, 3))  # ~0.5

    n = 3000
    theta = 0.05
    s = np.zeros(n)
    for t in range(1, n):
        s[t] = s[t - 1] + theta * (0.0 - s[t - 1]) + rng.standard_normal()
    hl = R.half_life(s)
    print("half-life:", round(hl.half_life, 2), "expected ~", round(np.log(2) / theta, 1))

    # cointegration: y = 2x + stationary noise
    x = np.cumsum(rng.standard_normal(600))
    y = 2.0 * x + rng.standard_normal(600)
    eg = R.engle_granger_test(y, x)
    print("EG coint sig@5%:", eg.is_significant(), "hedge:", round(eg.extra["hedge_ratio"], 2))
    jo = R.johansen_test(pd.DataFrame({"y": y, "x": x}))
    print("Johansen rank@95%:", jo.rank())

    r = rng.standard_normal(1000) * 0.01 + 0.0005
    print("sharpe ann:", round(R.sharpe_ratio(r), 3))
    dsr = R.deflated_sharpe_ratio(r, n_trials=50, trial_sharpe_std=0.5)
    print("DSR:", round(dsr.deflated_sharpe, 3), "E[maxSR]:", round(dsr.expected_max_sharpe, 3))

    # PBO: pure-noise strategies should be heavily overfit (PBO near/above 0.5)
    mat = rng.standard_normal((400, 20)) * 0.01
    pbo = R.probability_of_backtest_overfitting(mat, n_splits=8)
    print("PBO (noise):", round(pbo.pbo, 3))

    rc = R.whites_reality_check(mat, n_bootstrap=200, seed=1)
    spa = R.hansens_spa_test(mat, n_bootstrap=200, seed=1)
    print("White RC p:", round(rc.pvalue, 3), "SPA p:", round(spa.pvalue, 3))

    # feature store
    store = R.default_feature_store()
    print("n features:", len(store))
    idx = pd.date_range("2020-01-01", periods=400, freq="D", tz="UTC")
    px = 100 + np.cumsum(rng.standard_normal(400))
    bars = pd.DataFrame(
        {
            "open": px,
            "high": px + 0.5,
            "low": px - 0.5,
            "close": px,
            "volume": rng.uniform(1e6, 2e6, 400),
            "source": "test",
        },
        index=pd.MultiIndex.from_product([["AAPL"], idx], names=["symbol", "timestamp"]),
    )
    feats = store.compute(bars)
    print("feature matrix:", feats.shape, "versions tracked:", len(feats.attrs["feature_versions"]))
    print("any inf:", np.isinf(feats.to_numpy(dtype=float)).any())
    print("OK")


if __name__ == "__main__":
    main()
