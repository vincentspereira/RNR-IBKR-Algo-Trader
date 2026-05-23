"""Coinbase broker adapter -- ROADMAP MARKER (not implemented).

The canonical broker for paper and live trading is
``core_trading.adapters.ibkr_adapter.IBKRAdapter``. This module exists only
to signal aspirational multi-broker scope; it raises ``NotImplementedError``
on use so that accidental references fail loudly instead of silently.

Plan for future implementation:
    - SDK: ``coinbase-advanced-py`` (Apache-2.0; MAS-safe)
    - Asset classes: crypto
    - Priority: MEDIUM (needed if crypto strategies emerge)
    - Reference: project-broker-roadmap memory and PRODUCTION_PUNCH_LIST.md

A working pre-refactor implementation is archived at
``.archive/2026-05-21_dead_adapters/brokers/coinbase.py.backup``.
"""

from __future__ import annotations

__all__ = ["CoinbaseAdapter"]


class CoinbaseAdapter:
    """Roadmap marker for Coinbase broker support. Not implemented."""

    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "CoinbaseAdapter is a roadmap marker. Use "
            "core_trading.adapters.ibkr_adapter.IBKRAdapter for paper and "
            "live trading. See project-broker-roadmap memory for plans."
        )
