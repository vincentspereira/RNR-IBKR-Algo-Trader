"""Alpaca broker adapter -- ROADMAP MARKER (not implemented).

The canonical broker for paper and live trading is
``core_trading.adapters.ibkr_adapter.IBKRAdapter``. This module exists only
to signal aspirational multi-broker scope; it raises ``NotImplementedError``
on use so that accidental references fail loudly instead of silently.

Plan for future implementation:
    - SDK: ``alpaca-py`` (Apache-2.0; MAS-safe)
    - Asset classes: US equities, crypto
    - Priority: HIGH (complements IBKR for US equities)
    - Reference: project-broker-roadmap memory and PRODUCTION_PUNCH_LIST.md

A working pre-refactor implementation is archived at
``.archive/2026-05-21_dead_adapters/brokers/alpaca.py.backup``.
"""

from __future__ import annotations

__all__ = ["AlpacaAdapter"]


class AlpacaAdapter:
    """Roadmap marker for Alpaca broker support. Not implemented."""

    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "AlpacaAdapter is a roadmap marker. Use "
            "core_trading.adapters.ibkr_adapter.IBKRAdapter for paper and "
            "live trading. See project-broker-roadmap memory for plans."
        )
