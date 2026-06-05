"""Tests for core_trading.strategies.ta_quant.grid.

Coverage:
- All config names are unique.
- All configs construct without error.
- Grid count is in the expected range (40-80 configs).
- Each config has a valid primary and overlay chain.
- Names are filesystem-safe (no spaces, slashes, or special chars).
"""
from __future__ import annotations

import re

import pytest

from core_trading.strategies.ta_quant.grid import build_ta_quant_grid
from core_trading.strategies.ta_quant.strategy import TAQuantConfig

_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9_.]+$")


class TestBuildTAQuantGrid:
    @pytest.fixture(scope="class")
    def grid(self) -> list[tuple[str, TAQuantConfig]]:
        return build_ta_quant_grid()

    def test_names_unique(self, grid: list[tuple[str, TAQuantConfig]]) -> None:
        names = [name for name, _ in grid]
        assert len(names) == len(set(names)), "grid contains duplicate names"

    def test_count_in_expected_range(self, grid: list[tuple[str, TAQuantConfig]]) -> None:
        count = len(grid)
        assert 40 <= count <= 100, f"grid size {count} outside expected range [40, 100]"

    def test_all_configs_construct_without_error(
        self, grid: list[tuple[str, TAQuantConfig]]
    ) -> None:
        for name, cfg in grid:
            assert isinstance(cfg, TAQuantConfig), f"{name}: config is not TAQuantConfig"

    def test_names_are_filesystem_safe(self, grid: list[tuple[str, TAQuantConfig]]) -> None:
        for name, _ in grid:
            assert _SAFE_NAME_RE.match(name), (
                f"name {name!r} contains characters unsafe for filesystems"
            )

    def test_primary_names_valid(self, grid: list[tuple[str, TAQuantConfig]]) -> None:
        valid_primaries = {
            "donchian_breakout",
            "ma_cross",
            "rsi_dip",
            "macd_trend",
            "bollinger_fade",
            "keltner_squeeze",
        }
        for name, cfg in grid:
            assert cfg.primary in valid_primaries, (
                f"{name}: invalid primary {cfg.primary!r}"
            )

    def test_all_six_primaries_represented(
        self, grid: list[tuple[str, TAQuantConfig]]
    ) -> None:
        primaries = {cfg.primary for _, cfg in grid}
        expected = {
            "donchian_breakout",
            "ma_cross",
            "rsi_dip",
            "macd_trend",
            "bollinger_fade",
            "keltner_squeeze",
        }
        missing = expected - primaries
        assert not missing, f"primaries missing from grid: {missing}"

    def test_overlay_specs_are_tuples(self, grid: list[tuple[str, TAQuantConfig]]) -> None:
        for name, cfg in grid:
            assert isinstance(cfg.overlay_specs, tuple), (
                f"{name}: overlay_specs is not a tuple"
            )

    def test_gross_cap_positive(self, grid: list[tuple[str, TAQuantConfig]]) -> None:
        for name, cfg in grid:
            assert cfg.gross_cap > 0.0, f"{name}: gross_cap must be positive"
