"""OANDA broker adapter -- ROADMAP MARKER (not implemented).

The canonical broker for paper and live trading is
``core_trading.adapters.ibkr_adapter.IBKRAdapter``. This module exists only
to signal aspirational multi-broker scope; it raises ``NotImplementedError``
on use so that accidental references fail loudly instead of silently.

Plan for future implementation:
    - SDK: ``oandapyV20`` (MIT; MAS-safe)
    - Asset classes: forex, CFD
    - Priority: LOW
    - Reference: project-broker-roadmap memory and PRODUCTION_PUNCH_LIST.md
"""

from __future__ import annotations

__all__ = ["OandaAdapter"]


class OandaAdapter:
    """Roadmap marker for OANDA broker support. Not implemented."""

    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "OandaAdapter is a roadmap marker. Use "
            "core_trading.adapters.ibkr_adapter.IBKRAdapter for paper and "
            "live trading. See project-broker-roadmap memory for plans."
        )
