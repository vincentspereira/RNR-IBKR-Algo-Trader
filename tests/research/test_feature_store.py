"""Tests for core_trading.research.feature_store.

The headline guarantee -- features are look-ahead-free -- is tested directly in
:class:`TestNoLookAhead`: a feature value at time ``t`` must not change when
future bars are appended. Versioning, registry behaviour, the ``as_of`` cut and
multi-symbol computation are covered alongside.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core_trading.research import feature_store as fs


@pytest.fixture
def rng() -> np.random.Generator:
    return np.random.default_rng(99)


def _bar_frame(rng, symbols=("AAPL",), n: int = 400) -> pd.DataFrame:
    frames = []
    idx = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
    for sym in symbols:
        px = 100 + np.cumsum(rng.standard_normal(n))
        px = np.maximum(px, 1.0)
        high = px + np.abs(rng.standard_normal(n)) * 0.5
        low = px - np.abs(rng.standard_normal(n)) * 0.5
        frame = pd.DataFrame(
            {
                "open": px,
                "high": np.maximum(high, px),
                "low": np.minimum(low, px),
                "close": px,
                "volume": rng.uniform(1e6, 5e6, n),
                "source": "test",
            },
            index=pd.MultiIndex.from_product([[sym], idx], names=["symbol", "timestamp"]),
        )
        frames.append(frame)
    return pd.concat(frames).sort_index()


# ------------------------------------------------------------------- registry
class TestRegistry:
    def test_register_and_get(self) -> None:
        store = fs.FeatureStore()
        feat = fs.Feature("x", "v1", "returns", "test", 1, lambda d: d["close"])
        store.register(feat)
        assert store.get("x") is feat
        assert len(store) == 1

    def test_duplicate_raises(self) -> None:
        store = fs.FeatureStore()
        feat = fs.Feature("x", "v1", "returns", "t", 1, lambda d: d["close"])
        store.register(feat)
        with pytest.raises(ValueError):
            store.register(feat)

    def test_overwrite_allowed(self) -> None:
        store = fs.FeatureStore()
        store.register(fs.Feature("x", "v1", "returns", "t", 1, lambda d: d["close"]))
        store.register(
            fs.Feature("x", "v1", "returns", "t2", 1, lambda d: d["open"]),
            overwrite=True,
        )
        assert store.get("x").description == "t2"

    def test_versioning_latest(self) -> None:
        store = fs.FeatureStore()
        store.register(fs.Feature("x", "v1", "returns", "t", 1, lambda d: d["close"]))
        store.register(fs.Feature("x", "v2", "returns", "t", 1, lambda d: d["open"]))
        assert store.latest_version("x") == "v2"
        assert store.get("x").version == "v2"
        assert store.get("x", "v1").version == "v1"

    def test_get_unknown(self) -> None:
        with pytest.raises(KeyError):
            fs.FeatureStore().get("nope")

    def test_get_unknown_version(self) -> None:
        store = fs.FeatureStore()
        store.register(fs.Feature("x", "v1", "returns", "t", 1, lambda d: d["close"]))
        with pytest.raises(KeyError):
            store.get("x", "v9")

    def test_latest_version_unknown(self) -> None:
        with pytest.raises(KeyError):
            fs.FeatureStore().latest_version("nope")

    def test_feature_key(self) -> None:
        assert fs.Feature("x", "v3", "c", "d", 1, lambda d: d).key == "x@v3"


# ------------------------------------------------------------------- defaults
class TestDefaultStore:
    def test_at_least_fifty_features(self) -> None:
        store = fs.default_feature_store()
        assert len(store) >= 50

    def test_categories_present(self) -> None:
        store = fs.default_feature_store()
        for cat in ("returns", "volatility", "trend", "momentum", "volume", "range", "statistical"):
            assert store.list_by_category(cat), f"no features in {cat}"

    def test_all_features_listed(self) -> None:
        store = fs.default_feature_store()
        assert "rsi_14" in store.list_features()
        assert "ret_21" in store.list_features()


# ------------------------------------------------------------------- compute
class TestCompute:
    def test_shape_and_index(self, rng) -> None:
        store = fs.default_feature_store()
        frame = _bar_frame(rng)
        out = store.compute(frame)
        assert isinstance(out.index, pd.MultiIndex)
        assert out.index.names == ["symbol", "timestamp"]
        assert out.shape[0] == frame.shape[0]
        assert out.shape[1] == len(store)

    def test_subset_by_name(self, rng) -> None:
        store = fs.default_feature_store()
        out = store.compute(_bar_frame(rng), ["ret_21", "rsi_14"])
        assert list(out.columns) == ["ret_21", "rsi_14"]

    def test_subset_by_name_version_tuple(self, rng) -> None:
        store = fs.default_feature_store()
        out = store.compute(_bar_frame(rng), [("ret_5", "v1")])
        assert list(out.columns) == ["ret_5"]
        assert out.attrs["feature_versions"]["ret_5"] == "v1"

    def test_versions_tracked(self, rng) -> None:
        store = fs.default_feature_store()
        out = store.compute(_bar_frame(rng))
        assert len(out.attrs["feature_versions"]) == len(store)

    def test_no_infinities(self, rng) -> None:
        store = fs.default_feature_store()
        out = store.compute(_bar_frame(rng))
        assert not np.isinf(out.to_numpy(dtype=float)).any()

    def test_multi_symbol(self, rng) -> None:
        store = fs.default_feature_store()
        frame = _bar_frame(rng, symbols=("AAPL", "MSFT", "GOOG"))
        out = store.compute(frame, ["ret_5", "vol_21"])
        assert set(out.index.get_level_values("symbol").unique()) == {"AAPL", "MSFT", "GOOG"}

    def test_compute_one(self, rng) -> None:
        store = fs.default_feature_store()
        sym = _bar_frame(rng).droplevel("symbol")
        series = store.compute_one(sym, "ret_5")
        assert series.name == "ret_5"
        assert len(series) == len(sym)

    def test_requires_multiindex(self, rng) -> None:
        store = fs.default_feature_store()
        flat = _bar_frame(rng).droplevel("symbol")
        with pytest.raises(ValueError):
            store.compute(flat)

    def test_empty_frame(self) -> None:
        store = fs.default_feature_store()
        empty = pd.DataFrame(
            {"open": [], "high": [], "low": [], "close": [], "volume": []},
            index=pd.MultiIndex.from_arrays([[], []], names=["symbol", "timestamp"]),
        )
        out = store.compute(empty, ["ret_5", "rsi_14"])
        assert list(out.columns) == ["ret_5", "rsi_14"]
        assert out.empty

    def test_warmup_is_nan(self, rng) -> None:
        store = fs.default_feature_store()
        out = store.compute(_bar_frame(rng), ["sma_200"])
        # the first 199 rows cannot have a 200-bar SMA
        assert out["sma_200"].iloc[:199].isna().all()
        assert not np.isnan(out["sma_200"].iloc[-1])


# ----------------------------------------------------------------- as-of cut
class TestAsOf:
    def test_as_of_truncates(self, rng) -> None:
        store = fs.default_feature_store()
        frame = _bar_frame(rng)
        cut = frame.index.get_level_values("timestamp")[250]
        out = store.compute(frame, ["ret_5"], as_of=cut)
        assert out.index.get_level_values("timestamp").max() <= cut

    def test_as_of_matches_manual_truncation(self, rng) -> None:
        store = fs.default_feature_store()
        frame = _bar_frame(rng)
        ts = frame.index.get_level_values("timestamp")
        cut = ts[250]
        via_asof = store.compute(frame, ["rsi_14", "vol_21"], as_of=cut)
        manual = store.compute(frame[ts <= cut], ["rsi_14", "vol_21"])
        pd.testing.assert_frame_equal(via_asof, manual)


# --------------------------------------------------------------- look-ahead
class TestNoLookAhead:
    """The core guarantee: appending future bars never changes past features."""

    def test_prefix_is_stable(self, rng) -> None:
        store = fs.default_feature_store()
        full = _bar_frame(rng, n=400)
        cut = 300
        ts = full.index.get_level_values("timestamp")
        prefix_cut = ts[cut - 1]

        full_feats = store.compute(full)
        prefix_feats = store.compute(full[ts <= prefix_cut])

        # Align the overlapping prefix and compare every feature column.
        full_prefix = full_feats.iloc[:cut]
        assert len(full_prefix) == len(prefix_feats)
        for col in full_feats.columns:
            a = full_prefix[col].to_numpy(dtype=float)
            b = prefix_feats[col].to_numpy(dtype=float)
            assert np.allclose(a, b, equal_nan=True), f"look-ahead leak in {col}"
