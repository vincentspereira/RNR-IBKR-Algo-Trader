"""Chaos-suite conftest.

The chaos tests import :mod:`core_trading.adapters.ibkr_adapter` at module
scope, which transitively imports ``ib_insync`` -> ``eventkit``.  On Python
3.12 ``eventkit`` calls ``asyncio.get_event_loop()`` at *import* time, which
emits a ``DeprecationWarning`` ("There is no current event loop") when no loop
is set on the current thread.  Under ``-W error`` that warning becomes a fatal
error during test COLLECTION -- before the project-level autouse fixture in
``tests/conftest.py`` can run.

This conftest establishes a current event loop at import time (before pytest
collects the chaos modules) so the transitive import is clean.  It is the
collection-time analogue of the runtime guard in ``tests/conftest.py`` and is
deterministic -- it creates and sets a loop, it never sleeps or runs anything.
"""
from __future__ import annotations

import asyncio
import warnings

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    try:
        _loop = asyncio.get_event_loop()
        if _loop.is_closed():  # pragma: no cover - defensive
            raise RuntimeError("event loop is closed")
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
