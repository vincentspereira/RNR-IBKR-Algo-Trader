"""Interactive Brokers shim -- THIS IS NOT THE CANONICAL IBKR ADAPTER.

The canonical IBKR adapter lives at
``core_trading.adapters.ibkr_adapter.IBKRAdapter`` (top-level adapters module).

This module exists only as a historical placeholder inside the
``adapters/brokers/`` package. It used to contain a refactored "handler-pattern"
duplicate that was archived on 2026-05-21 (see
``.archive/2026-05-21_dead_adapters/brokers/interactive_brokers.py.backup``).

Anything importing from here is using the wrong import path -- switch to
``from core_trading.adapters.ibkr_adapter import IBKRAdapter``.
"""

from __future__ import annotations

__all__ = ["InteractiveBrokersAdapter"]


class InteractiveBrokersAdapter:
    """Placeholder that redirects users to the canonical IBKR adapter."""

    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "core_trading.adapters.brokers.interactive_brokers."
            "InteractiveBrokersAdapter is not implemented. The canonical "
            "broker is core_trading.adapters.ibkr_adapter.IBKRAdapter -- "
            "import it from there instead."
        )
