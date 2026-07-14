"""core_trading -- top-level package for the trading engine.

Explicitly a regular package (not a PEP 420 namespace package) so its subpackages
(indicators, strategies, ...) resolve robustly under pytest collection regardless
of import order. Sibling top-level dirs (libs, services, tools) remain namespace
packages.
"""
