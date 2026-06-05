"""Backtest regression hashes (master plan Phase 10.1).

This module pins the *numerical output* of a small set of seeded, canonical
backtests run through the Phase 3 engine
(:class:`core_trading.backtest.BacktestEngine`).  Each run produces a stable
SHA-256 fingerprint of its results; the fingerprint is compared against a
checked-in golden value in ``golden_hashes.json``.  A mismatch means the
engine's numbers changed -- which is exactly what we want a regression test to
catch.

What counts as an INTENTIONAL change
------------------------------------
A golden-hash mismatch is *expected* (and the goldens must be regenerated) when
you deliberately change something that legitimately moves the backtest numbers,
for example:

* a fix or improvement to the backtest engine's return / equity / cost maths
  (:mod:`core_trading.backtest.engine`, ``costs``, ``execution``, ``portfolio``);
* a change to the canonical recipes below (panel seed/length/symbols, the
  weight books, the cost model, the engine config) made on purpose;
* a NumPy / pandas upgrade that changes a low-order floating-point bit in a way
  you have reviewed and accepted.

In any of those cases, regenerate the goldens with::

    python tests/regression/test_backtest_hashes.py --regen

and commit the updated ``golden_hashes.json`` alongside the code change, so the
diff records the intentional numerical move.

A mismatch is a BUG (do NOT regenerate) when the numbers moved without any such
intentional change -- e.g. accidental non-determinism, an unseeded RNG, or a
refactor that was supposed to be behaviour-preserving but was not.

Hash construction (stable + deterministic)
------------------------------------------
For each run we serialise a small, ordered digest of the result -- the equity
curve, the per-period returns, the realised turnover and total costs -- with
every float rounded to 1e-9 before being written, then take the SHA-256 of the
canonical JSON.  Rounding absorbs sub-nanometre float jitter so the hash is
stable across runs and platforms while still catching any real numerical drift.
The engine itself is documented as deterministic (identical inputs -> identical
:class:`BacktestResult`), which this test also exercises by running twice.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from core_trading.backtest import (
    BacktestConfig,
    BacktestEngine,
    WeightStrategy,
)

# Goldens live next to this module so the test is hermetic.
_GOLDEN_PATH = Path(__file__).with_name("golden_hashes.json")

# Float rounding applied before hashing: 1e-9 absorbs float jitter while still
# catching any genuine numerical drift in the engine.
_ROUND_DECIMALS = 9


# ---------------------------------------------------------------------------
# Canonical seeded panel (self-contained -- never imports from tests/backtest)
# ---------------------------------------------------------------------------


def _make_panel(
    seed: int,
    n: int,
    symbols: tuple[str, ...],
) -> pd.DataFrame:
    """Build a deterministic look-ahead-free (symbol, timestamp) OHLCV panel.

    This mirrors the synthetic-panel recipe used elsewhere in the backtest test
    suite, but is reproduced here verbatim so the regression module has no
    cross-test imports and its inputs are frozen against this file alone.
    """
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2021-01-04", periods=n, freq="B", tz="UTC")
    frames = []
    for s in symbols:
        px = np.maximum(100.0 + np.cumsum(rng.standard_normal(n)) * 0.4, 5.0)
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
                index=pd.MultiIndex.from_product(
                    [[s], idx], names=["symbol", "timestamp"]
                ),
            )
        )
    return pd.concat(frames).sort_index()


def _constant_weights(
    panel: pd.DataFrame, alloc: dict[str, float]
) -> pd.DataFrame:
    """A constant target-weight frame (same weights at every timestamp)."""
    timeline = (
        pd.DatetimeIndex(panel.index.get_level_values("timestamp").unique())
        .sort_values()
    )
    return pd.DataFrame(
        {sym: w for sym, w in alloc.items()},
        index=timeline,
    )


# ---------------------------------------------------------------------------
# Canonical run definitions
# ---------------------------------------------------------------------------


def _run_constant_long_vectorised() -> dict[str, object]:
    """50/50 constant-long book, frictionless, vectorised mode."""
    panel = _make_panel(seed=11, n=120, symbols=("AAA", "BBB"))
    weights = _constant_weights(panel, {"AAA": 0.5, "BBB": 0.5})
    engine = BacktestEngine(BacktestConfig(cost_model_name="zero"))
    result = engine.run(panel, WeightStrategy(weights), mode="vectorised")
    return _digest_from_result(result)


def _run_long_short_vectorised() -> dict[str, object]:
    """A long/short book through the IBKR cost model, vectorised mode."""
    panel = _make_panel(seed=7, n=120, symbols=("AAA", "BBB", "CCC"))
    weights = _constant_weights(panel, {"AAA": 0.6, "BBB": -0.4, "CCC": 0.2})
    engine = BacktestEngine(
        BacktestConfig(cost_model_name="ibkr", initial_cash=500_000.0)
    )
    result = engine.run(panel, WeightStrategy(weights), mode="vectorised")
    return _digest_from_result(result)


def _run_constant_long_event_driven() -> dict[str, object]:
    """Same constant-long book but through the realistic event-driven path."""
    panel = _make_panel(seed=11, n=90, symbols=("AAA", "BBB"))
    weights = _constant_weights(panel, {"AAA": 0.5, "BBB": 0.5})
    engine = BacktestEngine(BacktestConfig(cost_model_name="zero"))
    result = engine.run(panel, WeightStrategy(weights), mode="event_driven")
    return _digest_from_result(result)


# Registry of canonical runs: name -> zero-arg builder returning a digest dict.
_RUNS: dict[str, object] = {
    "constant_long_vectorised": _run_constant_long_vectorised,
    "long_short_ibkr_vectorised": _run_long_short_vectorised,
    "constant_long_event_driven": _run_constant_long_event_driven,
}


# ---------------------------------------------------------------------------
# Stable digest + hash
# ---------------------------------------------------------------------------


def _round_list(values: np.ndarray) -> list[float]:
    """Round a float array to the hashing precision and return a plain list."""
    return [round(float(v), _ROUND_DECIMALS) for v in values]


def _digest_from_result(result: object) -> dict[str, object]:
    """Build a stable, JSON-serialisable digest of a BacktestResult.

    The digest captures the equity curve, per-period returns, realised
    turnover and total costs -- the numbers a regression must pin -- plus the
    engine's own replay fingerprint, with every float rounded to absorb jitter.
    """
    equity = result.equity  # type: ignore[attr-defined]
    returns = result.returns  # type: ignore[attr-defined]
    return {
        "mode": str(result.mode),  # type: ignore[attr-defined]
        "n": int(len(equity)),
        "equity": _round_list(equity.to_numpy(dtype=float)),
        "returns": _round_list(returns.to_numpy(dtype=float)),
        "turnover": round(float(result.turnover), _ROUND_DECIMALS),  # type: ignore[attr-defined]
        "total_costs": round(float(result.total_costs), _ROUND_DECIMALS),  # type: ignore[attr-defined]
        "fingerprint": result.fingerprint(),  # type: ignore[attr-defined]
    }


def _hash_digest(digest: dict[str, object]) -> str:
    """SHA-256 of the canonical JSON serialisation of a digest."""
    blob = json.dumps(digest, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def compute_hashes() -> dict[str, str]:
    """Run every canonical backtest and return ``{run_name: sha256}``."""
    out: dict[str, str] = {}
    for name, builder in _RUNS.items():
        digest = builder()  # type: ignore[operator]
        out[name] = _hash_digest(digest)
    return out


def _load_goldens() -> dict[str, str]:
    if not _GOLDEN_PATH.exists():
        raise FileNotFoundError(
            f"golden hash file missing: {_GOLDEN_PATH}. Regenerate with "
            "`python tests/regression/test_backtest_hashes.py --regen`."
        )
    with _GOLDEN_PATH.open("r", encoding="utf-8") as fh:
        data: dict[str, str] = json.load(fh)
    return data


def _write_goldens(hashes: dict[str, str]) -> None:
    payload = {k: hashes[k] for k in sorted(hashes)}
    with _GOLDEN_PATH.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_backtest_hashes_match_goldens() -> None:
    """Each canonical run's hash matches its checked-in golden value."""
    goldens = _load_goldens()
    current = compute_hashes()

    assert set(current) == set(goldens), (
        "regression run set drifted from goldens: "
        f"runs={sorted(current)} goldens={sorted(goldens)}. "
        "An INTENTIONAL change requires regenerating goldens via "
        "`python tests/regression/test_backtest_hashes.py --regen`."
    )

    for name in sorted(current):
        old = goldens[name]
        new = current[name]
        assert new == old, (
            f"backtest regression hash mismatch for run '{name}': "
            f"old hash {old}, new hash {new}. "
            "An INTENTIONAL change requires regenerating goldens via "
            "`python tests/regression/test_backtest_hashes.py --regen`."
        )


def test_backtest_hashes_are_stable_across_runs() -> None:
    """Recomputing the hashes yields byte-identical values (determinism)."""
    first = compute_hashes()
    second = compute_hashes()
    assert first == second, (
        "canonical backtest hashes are non-deterministic across runs: "
        f"{first} != {second}"
    )


# ---------------------------------------------------------------------------
# __main__ -- golden regeneration
# ---------------------------------------------------------------------------


def _main(argv: list[str]) -> int:
    if "--regen" in argv:
        hashes = compute_hashes()
        _write_goldens(hashes)
        print(f"[OK] wrote {len(hashes)} golden hashes to {_GOLDEN_PATH}")
        for name in sorted(hashes):
            print(f"  {name}: {hashes[name]}")
        return 0
    print(
        "usage: python tests/regression/test_backtest_hashes.py --regen\n"
        "  --regen  recompute and overwrite golden_hashes.json (use only for "
        "an INTENTIONAL numerical change)"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
