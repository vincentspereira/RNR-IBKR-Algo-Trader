"""Signal generation library (master plan Phase 4 / Phase 5).

Phase 4 ships the pairs-trading (statistical arbitrage) signal stack under
:mod:`core_trading.signals.pairs`. Phase 5 (the "alpha factory") extends this
package incrementally, one signal family at a time.

Sub-packages
------------
* :mod:`core_trading.signals.pairs` -- pairs / statistical-arbitrage (Phase 4).
* :mod:`core_trading.signals.regimes` -- Hidden Markov regime detection
  (Phase 5.A.1).
* :mod:`core_trading.signals.volatility` -- GARCH family and HAR-RV volatility
  models (Phase 5.A.5).
* :mod:`core_trading.signals.timeseries` -- ARIMA / SARIMA and fractional
  differencing / ARFIMA (Phase 5.A.4).
* :mod:`core_trading.signals.stochastic` -- Ornstein-Uhlenbeck mean-reverting
  process estimation (Phase 5.B.1).

Each sub-module lazily imports its heavy statistical dependency (``hmmlearn``,
``arch``, ``statsmodels``) inside the call sites, so importing this package is
cheap. Import the concrete API from the relevant sub-package, e.g.
``from core_trading.signals.regimes import RegimeDetector``.
"""
