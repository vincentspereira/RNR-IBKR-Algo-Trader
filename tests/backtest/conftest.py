"""Shared fixtures for backtest tests: synthetic OHLCV panels."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def make_panel(
    seed: int = 11, n: int = 260, symbols: tuple[str, ...] = ("AAA", "BBB")
) -> pd.DataFrame:
    """A look-ahead-free synthetic (symbol, timestamp) OHLCV panel."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2021-01-04", periods=n, freq="B", tz="UTC")
    frames = []
    for s in symbols:
        px = np.maximum(100 + np.cumsum(rng.standard_normal(n)) * 0.4, 5.0)
        hi = px + np.abs(rng.standard_normal(n)) * 0.25
        lo = px - np.abs(rng.standard_normal(n)) * 0.25
        frames.append(
            pd.DataFrame(
                {
                    "open": px,
                    "high": np.maximum(hi, px),
                    "low": np.minimum(lo, px),
                    "close": px,
                    "volume": rng.uniform(1e6, 3e6, n),
                },
                index=pd.MultiIndex.from_product([[s], idx], names=["symbol", "timestamp"]),
            )
        )
    return pd.concat(frames).sort_index()


@pytest.fixture
def panel() -> pd.DataFrame:
    return make_panel()


@pytest.fixture
def timeline(panel: pd.DataFrame) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(panel.index.get_level_values("timestamp").unique()).sort_values()
