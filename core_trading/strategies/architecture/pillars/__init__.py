"""Pillar architecture re-export shim.

The canonical implementation of the 5-pillar scoring framework lives at
:mod:`core_trading.strategies.core.augmented_base_institutional_strategy`.
This package previously held a set of damaged extracts from a failed
god-class refactoring; those files were archived on 2026-05-28 (see
``.archive/2026-05-28_remediation/misplaced_pillars/``).

This module re-exports the canonical types so any legacy import paths of
the form ``from core_trading.strategies.architecture.pillars import PillarScores``
continue to resolve.
"""
from core_trading.strategies.core.augmented_base_institutional_strategy import (
    AugmentedConfig,
    PillarScores,
)

__all__ = ["AugmentedConfig", "PillarScores"]
