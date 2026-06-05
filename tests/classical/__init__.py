"""Tests for core_trading.strategies.classical and its evaluation adapters.

This package is deliberately separate from ``tests/strategies`` (whose conftest
mocks heavy libraries into ``sys.modules``); the classical strategies are pure
numpy/pandas and must run against the real libraries.
"""
