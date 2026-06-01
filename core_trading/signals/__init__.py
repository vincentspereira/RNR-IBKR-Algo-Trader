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
* :mod:`core_trading.signals.filters` -- Kalman filter and unobserved-components
  structural time-series models (Phase 5.A.2-3).
* :mod:`core_trading.signals.stochastic` -- stochastic-process models:
  Ornstein-Uhlenbeck (Phase 5.B.1), Merton jump-diffusion (5.B.2), Heston
  stochastic volatility (5.B.3), and Geometric Brownian Motion (5.B.4).

Each sub-module lazily imports its heavy statistical dependency (``hmmlearn``,
``arch``, ``statsmodels``, ``scipy``) inside the call sites, so importing this
package is cheap. The Kalman filter is implemented in pure NumPy. Import the
concrete API from the relevant sub-package, e.g.
``from core_trading.signals.regimes import RegimeDetector``.
"""
