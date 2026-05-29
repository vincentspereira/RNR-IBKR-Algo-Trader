"""Per-vendor data adapters.

Each module here implements one of the abstract interfaces from
:mod:`core_trading.data` for a specific vendor. Free-vendor adapters land
first per :doc:`docs/FREE_DATA_VENDORS.md`; paid adapters (Norgate, Sharadar,
Polygon, ...) land before live trading.

Available adapters:

* :mod:`core_trading.data.sources.yfinance_source` -- Yahoo Finance OHLCV (no key)
* :mod:`core_trading.data.sources.fred_source` -- FRED macro (free key)
* :mod:`core_trading.data.sources.ibkr_source` -- IBKR bars + live (broker)
* :mod:`core_trading.data.sources.edgar_source` -- SEC EDGAR fundamentals (free)
"""
