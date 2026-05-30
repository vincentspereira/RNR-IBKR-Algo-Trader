"""Tests for core_trading.signals.pairs.signals (Phase 4.3).

Covers:
* SignalConfig -- construction, validation errors.
* PairState -- enum values.
* generate_pair_signals -- deterministic z-score paths asserting exact state/
  position/reason sequences; time-stop; NaN handling; no look-ahead property.
* signal_to_weights -- mapping from position to weight.
"""
from __future__ import annotations

import pandas as pd
import pytest

from core_trading.signals.pairs.signals import (
    PairState,
    SignalConfig,
    generate_pair_signals,
    signal_to_weights,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_zscore(values: list[float]) -> pd.Series:
    idx = pd.date_range("2023-01-01", periods=len(values), freq="D")
    return pd.Series(values, index=idx, name="zscore", dtype=float)


# ---------------------------------------------------------------------------
# SignalConfig
# ---------------------------------------------------------------------------


class TestSignalConfig:
    def test_defaults_valid(self) -> None:
        cfg = SignalConfig()
        assert cfg.entry_z == 2.0
        assert cfg.exit_z == 0.5
        assert cfg.stop_z == 4.0
        assert cfg.time_stop_mult == 3.0

    def test_custom_valid(self) -> None:
        cfg = SignalConfig(entry_z=1.5, exit_z=0.3, stop_z=3.0, time_stop_mult=2.5)
        assert cfg.entry_z == 1.5

    def test_raises_entry_not_gt_exit(self) -> None:
        with pytest.raises(ValueError, match="entry_z"):
            SignalConfig(entry_z=0.5, exit_z=0.5)

    def test_raises_exit_negative(self) -> None:
        with pytest.raises(ValueError, match="exit_z"):
            SignalConfig(exit_z=-0.1)

    def test_raises_stop_not_gt_entry(self) -> None:
        with pytest.raises(ValueError, match="stop_z"):
            SignalConfig(entry_z=2.0, stop_z=2.0)

    def test_raises_time_stop_mult_zero(self) -> None:
        with pytest.raises(ValueError, match="time_stop_mult"):
            SignalConfig(time_stop_mult=0.0)

    def test_raises_time_stop_mult_negative(self) -> None:
        with pytest.raises(ValueError, match="time_stop_mult"):
            SignalConfig(time_stop_mult=-1.0)


# ---------------------------------------------------------------------------
# PairState
# ---------------------------------------------------------------------------


class TestPairState:
    def test_values(self) -> None:
        assert PairState.FLAT.value == "flat"
        assert PairState.LONG_SPREAD.value == "long_spread"
        assert PairState.SHORT_SPREAD.value == "short_spread"


# ---------------------------------------------------------------------------
# generate_pair_signals -- deterministic path tests
# ---------------------------------------------------------------------------


class TestGeneratePairSignals:
    """Core state-machine logic verified against manually-traced z-score paths."""

    # Default config: entry=2, exit=0.5, stop=4
    CFG = SignalConfig()

    def test_entry_long_spread(self) -> None:
        """z dips below -entry_z -> enter LONG_SPREAD."""
        z = _make_zscore([0.0, 0.0, -2.5, 0.0])
        sig = generate_pair_signals(z, config=self.CFG)

        assert sig.loc[sig.index[2], "state"] == PairState.LONG_SPREAD.value
        assert sig.loc[sig.index[2], "position"] == 1
        assert sig.loc[sig.index[2], "reason"] == "entry_long"

    def test_entry_short_spread(self) -> None:
        """z rises above +entry_z -> enter SHORT_SPREAD."""
        z = _make_zscore([0.0, 0.0, 2.5, 0.0])
        sig = generate_pair_signals(z, config=self.CFG)

        assert sig.loc[sig.index[2], "state"] == PairState.SHORT_SPREAD.value
        assert sig.loc[sig.index[2], "position"] == -1
        assert sig.loc[sig.index[2], "reason"] == "entry_short"

    def test_exit_mean_reversion_long(self) -> None:
        """After entering LONG, z reverts through exit_z -> flat."""
        # Bar 0: flat; bar 1: enter long (-2.5); bar 2: hold (-1.5);
        # bar 3: exit (|z|=0.3 < 0.5)
        z = _make_zscore([0.0, -2.5, -1.5, -0.3])
        sig = generate_pair_signals(z, config=self.CFG)

        assert sig.iloc[1]["reason"] == "entry_long"
        assert sig.iloc[2]["reason"] == "hold"
        assert sig.iloc[3]["reason"] == "exit_meanrev"
        assert sig.iloc[3]["position"] == 0
        assert sig.iloc[3]["state"] == PairState.FLAT.value

    def test_exit_mean_reversion_short(self) -> None:
        """After entering SHORT, z reverts through exit_z -> flat."""
        z = _make_zscore([0.0, 3.0, 1.5, 0.3])
        sig = generate_pair_signals(z, config=self.CFG)

        assert sig.iloc[1]["reason"] == "entry_short"
        assert sig.iloc[2]["reason"] == "hold"
        assert sig.iloc[3]["reason"] == "exit_meanrev"
        assert sig.iloc[3]["position"] == 0

    def test_stop_loss_long(self) -> None:
        """z continues beyond -stop_z while long -> stop_loss."""
        z = _make_zscore([0.0, -2.5, -4.5])
        sig = generate_pair_signals(z, config=self.CFG)

        assert sig.iloc[1]["reason"] == "entry_long"
        assert sig.iloc[2]["reason"] == "stop_loss"
        assert sig.iloc[2]["position"] == 0

    def test_stop_loss_short(self) -> None:
        """z continues beyond +stop_z while short -> stop_loss."""
        z = _make_zscore([0.0, 2.5, 4.5])
        sig = generate_pair_signals(z, config=self.CFG)

        assert sig.iloc[1]["reason"] == "entry_short"
        assert sig.iloc[2]["reason"] == "stop_loss"
        assert sig.iloc[2]["position"] == 0

    def test_time_stop_fires(self) -> None:
        """Position held beyond time_stop_mult * half_life bars is closed.

        Tracing the state machine:
          bar 0: flat (z=0)
          bar 1: entry_long (bars_held=1)
          bar 2: hold, bars_held incremented to 2
          ...
          bar max_bars: hold, bars_held incremented to max_bars
          bar max_bars+1: bars_held >= max_bars -> time_stop
        """
        half_life = 5.0
        cfg = SignalConfig(time_stop_mult=2.0)  # max_bars = round(2*5) = 10
        max_bars = round(cfg.time_stop_mult * half_life)  # 10

        # Need max_bars + 2 bars: flat, entry_long, (max_bars-1) holds, time_stop
        z_vals = [0.0] + [-2.5] * (max_bars + 1)
        z = _make_zscore(z_vals)
        sig = generate_pair_signals(z, config=cfg, half_life=half_life)

        time_stop_idx = max_bars + 1
        assert sig.iloc[time_stop_idx]["reason"] == "time_stop", (
            f"Expected time_stop at bar {time_stop_idx}, "
            f"got {sig.iloc[time_stop_idx]['reason']}"
        )
        assert sig.iloc[time_stop_idx]["position"] == 0

    def test_time_stop_disabled_on_infinite_half_life(self) -> None:
        """With half_life=inf the time-stop must never fire."""
        cfg = SignalConfig(time_stop_mult=1.0)
        z_vals = [0.0] + [-2.5] * 50  # hold 50 bars
        z = _make_zscore(z_vals)
        sig = generate_pair_signals(z, config=cfg, half_life=float("inf"))

        assert "time_stop" not in sig["reason"].values

    def test_nan_does_not_trigger_entry(self) -> None:
        """NaN z-scores from FLAT state stay flat (no new entry)."""
        z = _make_zscore([0.0, float("nan"), float("nan"), 0.0])
        sig = generate_pair_signals(z)
        assert (sig["state"] == PairState.FLAT.value).all()
        assert (sig["position"] == 0).all()

    def test_nan_holds_existing_position(self) -> None:
        """NaN z-scores while in a position hold without counting toward time-stop."""
        cfg = SignalConfig(time_stop_mult=1.0)
        half_life = 3.0  # max_bars = round(3) = 3
        # bar 0: flat; bar 1: entry_long; bars 2-4: NaN (hold); bar 5: |z|=0.3 < exit -> exit
        z = _make_zscore([0.0, -2.5, float("nan"), float("nan"), float("nan"), 0.3])
        sig = generate_pair_signals(z, config=cfg, half_life=half_life)

        for i in range(2, 5):
            assert sig.iloc[i]["reason"] == "hold", f"bar {i} should be hold, not {sig.iloc[i]['reason']}"
            assert sig.iloc[i]["position"] == 1
        assert sig.iloc[5]["reason"] == "exit_meanrev"

    def test_full_cycle(self) -> None:
        """Trace a full sequence: flat -> long -> exit -> short -> stop."""
        cfg = SignalConfig(entry_z=2.0, exit_z=0.5, stop_z=4.0)
        z_vals = [
            0.0,   # 0: flat
            -2.5,  # 1: entry_long
            -1.5,  # 2: hold
            -0.3,  # 3: exit_meanrev
            0.0,   # 4: flat
            2.5,   # 5: entry_short
            4.5,   # 6: stop_loss
            0.0,   # 7: flat
        ]
        z = _make_zscore(z_vals)
        sig = generate_pair_signals(z, config=cfg)

        expected = [
            ("flat", 0, "flat"),
            ("long_spread", 1, "entry_long"),
            ("long_spread", 1, "hold"),
            ("flat", 0, "exit_meanrev"),
            ("flat", 0, "flat"),
            ("short_spread", -1, "entry_short"),
            ("flat", 0, "stop_loss"),
            ("flat", 0, "flat"),
        ]
        for i, (exp_state, exp_pos, exp_reason) in enumerate(expected):
            row = sig.iloc[i]
            assert row["state"] == exp_state, f"bar {i}: state {row['state']} != {exp_state}"
            assert row["position"] == exp_pos, f"bar {i}: pos {row['position']} != {exp_pos}"
            assert row["reason"] == exp_reason, f"bar {i}: reason {row['reason']} != {exp_reason}"

    def test_no_look_ahead(self) -> None:
        """Truncating the input at bar t must not change earlier bar results."""
        z_vals = [0.0, -2.5, -1.5, -0.3, 0.0, 3.0, 4.5, 0.0]
        z = _make_zscore(z_vals)
        full = generate_pair_signals(z)

        for cutoff in range(2, len(z_vals)):
            partial = generate_pair_signals(z.iloc[:cutoff])
            for i in range(cutoff):
                assert full.iloc[i]["state"] == partial.iloc[i]["state"], (
                    f"Look-ahead at bar {i} with cutoff {cutoff}: "
                    f"full={full.iloc[i]['state']}, partial={partial.iloc[i]['state']}"
                )
                assert full.iloc[i]["position"] == partial.iloc[i]["position"], (
                    f"Look-ahead at bar {i} (position) with cutoff {cutoff}"
                )

    def test_output_columns(self) -> None:
        z = _make_zscore([0.0, -2.5, -0.3])
        sig = generate_pair_signals(z)
        assert set(sig.columns) == {"zscore", "state", "position", "reason"}
        assert (sig["zscore"].values == [0.0, -2.5, -0.3]).all()

    def test_output_index_preserved(self) -> None:
        z = _make_zscore([0.0, 1.0, -2.5])
        sig = generate_pair_signals(z)
        assert (sig.index == z.index).all()

    def test_re_entry_after_exit(self) -> None:
        """After exiting flat the state machine accepts new entries."""
        z_vals = [0.0, -2.5, 0.3, 0.0, -2.5]
        z = _make_zscore(z_vals)
        sig = generate_pair_signals(z)

        assert sig.iloc[1]["reason"] == "entry_long"
        assert sig.iloc[2]["reason"] == "exit_meanrev"
        assert sig.iloc[3]["reason"] == "flat"
        assert sig.iloc[4]["reason"] == "entry_long"


# ---------------------------------------------------------------------------
# signal_to_weights
# ---------------------------------------------------------------------------


class TestSignalToWeights:
    def test_maps_positions_correctly(self) -> None:
        z = _make_zscore([0.0, -2.5, -0.3])
        sig = generate_pair_signals(z)
        weights = signal_to_weights(sig)

        assert isinstance(weights, pd.Series)
        assert weights.name == "spread_weight"
        assert (weights.index == sig.index).all()

    def test_gross_multiplier(self) -> None:
        z = _make_zscore([0.0, -2.5])
        sig = generate_pair_signals(z)
        w = signal_to_weights(sig, gross=2.0)
        # bar 1: position=1, weight=2.0
        assert w.iloc[1] == pytest.approx(2.0)

    def test_flat_position_zero_weight(self) -> None:
        z = _make_zscore([0.0, 0.0])
        sig = generate_pair_signals(z)
        w = signal_to_weights(sig)
        assert (w == 0.0).all()


# ---------------------------------------------------------------------------
# Time-stop edge-cases
# ---------------------------------------------------------------------------


class TestTimeStop:
    def test_time_stop_uses_round(self) -> None:
        """max_bars = round(time_stop_mult * half_life) must use Python round.

        Time-stop fires at bar index max_bars+1 (see test_time_stop_fires for
        the full trace).
        """
        cfg = SignalConfig(time_stop_mult=2.0)
        half_life = 5.5  # round(2 * 5.5) = round(11.0) = 11
        max_bars = round(cfg.time_stop_mult * half_life)
        assert max_bars == 11

        z_vals = [0.0] + [-2.5] * (max_bars + 1)
        z = _make_zscore(z_vals)
        sig = generate_pair_signals(z, config=cfg, half_life=half_life)

        assert sig.iloc[max_bars + 1]["reason"] == "time_stop"

    def test_time_stop_disabled_when_nan_half_life(self) -> None:
        cfg = SignalConfig(time_stop_mult=1.0)
        z_vals = [0.0] + [-2.5] * 20
        z = _make_zscore(z_vals)
        sig = generate_pair_signals(z, config=cfg, half_life=float("nan"))
        assert "time_stop" not in sig["reason"].values
