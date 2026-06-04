"""Alternative-data signals (master plan Phase 5.F).

The alt-data family derives trading signals from data beyond price and volume.
This package ships the sub-signals whose data is available from free / public
sources (FRED macro series, SEC EDGAR fundamentals and Form 4 filings):

* :mod:`~core_trading.signals.alt_data.macro` -- macro indicators (5.F.5): yield
  curve slope / curvature / inversion, VIX term structure, credit spreads, and a
  rate-differential carry signal. Consumes FRED-shaped macro series.
* :mod:`~core_trading.signals.alt_data.earnings` -- earnings surprise and
  post-earnings-announcement drift (5.F.2): Standardised Unexpected Earnings
  (SUE) and the PEAD long/short, computed point-in-time from the EDGAR
  fundamentals panel (a quarter's SUE is tradeable only from its filing date).
* :mod:`~core_trading.signals.alt_data.insider` -- insider-trading signal
  (5.F.3): net insider sentiment, Lakonishok-Lee cluster-buy detection, and the
  Cohen-Malloy-Pomorski routine-vs-opportunistic weighting, over a defined Form 4
  transaction shape (the SEC Form 4 ingest adapter is a Phase 1 data-layer
  follow-up; Form 4 filings are free on EDGAR).

Deferred -- these require data feeds that are not freely available and are not in
the Phase 1 data layer:

* News sentiment (5.F.1) needs a news / headline corpus (Benzinga, Refinitiv, or
  an RSS pipeline) plus a sentiment model (e.g. FinBERT).
* Options flow (5.F.4) needs an options-chain feed (put/call ratio, unusual
  activity, implied-volatility skew) -- IBKR options data or CBOE DataShop.
"""
from __future__ import annotations

from core_trading.signals.alt_data.earnings import (
    EarningsConfig,
    compute_sue_panel,
    pead_signal,
)
from core_trading.signals.alt_data.insider import (
    InsiderConfig,
    InsiderTransaction,
    cluster_buy_flags,
    cluster_buy_panel,
    insider_portfolio,
    insider_score_panel,
    label_routine_insiders,
    net_insider_sentiment,
    transactions_to_dataframe,
)
from core_trading.signals.alt_data.macro import (
    MacroConfig,
    align_series,
    credit_spread_signal,
    currency_carry_signal,
    vix_term_structure,
    yield_curve_signal,
)

__all__ = [
    # macro indicators (5.F.5)
    "MacroConfig",
    "align_series",
    "yield_curve_signal",
    "vix_term_structure",
    "credit_spread_signal",
    "currency_carry_signal",
    # earnings surprise / PEAD (5.F.2)
    "EarningsConfig",
    "compute_sue_panel",
    "pead_signal",
    # insider trading (5.F.3)
    "InsiderConfig",
    "InsiderTransaction",
    "transactions_to_dataframe",
    "label_routine_insiders",
    "net_insider_sentiment",
    "cluster_buy_flags",
    "cluster_buy_panel",
    "insider_score_panel",
    "insider_portfolio",
]
