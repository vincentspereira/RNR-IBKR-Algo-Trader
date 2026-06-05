"""Chaos / fault-injection tests for the execution layer (master plan Phase 10.4).

These tests deliberately inject broker faults -- duplicate fills, partial-then-
cancel, out-of-order events, mid-flow rejections, connect failures, and order-
placement exceptions -- against the EXISTING execution seams
(:mod:`core_trading.execution.lifecycle`,
:mod:`core_trading.adapters.ibkr_adapter`,
:mod:`core_trading.execution.pairs_execution`) and assert graceful
degradation.

Determinism: faults are injected via event ORDERING and mocked broker objects,
never via real sleeps, timers, or sockets.  Each test's docstring states the
FAULT injected and the EXPECTED graceful behaviour.
"""
