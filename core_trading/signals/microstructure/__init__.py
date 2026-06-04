"""Market-microstructure signals estimable from OHLCV data (Phase 5.E).

This package provides three families of microstructure signals that can be
computed from daily OHLCV bars alone, without requiring Level-2 order-book
data or individual trade ticks.

Package contents
----------------
:mod:`~core_trading.signals.microstructure.spread` -- bid-ask spread proxies
    Two classical bid-ask spread estimators based on price-change autocorrelation
    and the daily high-low ratio:

    * ``SpreadConfig``           -- frozen DTO for window / min-period parameters.
    * ``roll_spread``            -- Roll (1984) implied spread from the first-order
                                    serial covariance of price changes.
    * ``corwin_schultz_spread``  -- Corwin-Schultz (2012) beta/gamma/alpha
                                    high-low spread estimator (two-day window).

    References: Roll (1984) JF; Corwin & Schultz (2012) JF.

:mod:`~core_trading.signals.microstructure.kyle_lambda` -- price impact / illiquidity
    Illiquidity and price-impact measures using close, volume, and a tick-rule
    signed-volume proxy for net order flow:

    * ``KyleConfig``    -- frozen DTO for window / scale parameters.
    * ``amihud_illiq``  -- Amihud (2002) rolling mean |return| / dollar-volume
                            illiquidity ratio (scale = 1e6 by default, i.e.
                            per-million-dollars units).
    * ``kyle_lambda``   -- Kyle (1985) price-impact coefficient estimated by OLS
                            of price changes on tick-rule signed volume.

    References: Kyle (1985) Econometrica; Amihud (2002) JFM.

:mod:`~core_trading.signals.microstructure.hf_vol` -- range-based realised volatility
    Five OHLC-based volatility estimators ordered by statistical efficiency
    (relative to close-to-close):

    * ``VolConfig``             -- frozen DTO for window / annualisation parameters.
    * ``close_to_close_vol``    -- classical baseline (efficiency 1x).
    * ``parkinson_vol``         -- Parkinson (1980) high-low range (~5.2x).
    * ``garman_klass_vol``      -- Garman-Klass (1980) OHLC (~7.4x).
    * ``rogers_satchell_vol``   -- Rogers-Satchell (1991) drift-robust (~8x).
    * ``yang_zhang_vol``        -- Yang-Zhang (2000) drift + overnight gap-robust
                                    (~14x); requires previous close (first bar NaN).

    References: Parkinson (1980) JB; Garman & Klass (1980) JB;
    Rogers & Satchell (1991) AAP; Yang & Zhang (2000) JB.

Deferred signals (require Level-2 / tick data)
----------------------------------------------
The following microstructure signals are deferred because they require data
not present in OHLCV bars and are therefore NOT included in this package:

* **OBI** (Order-Book Imbalance): requires bid/ask quantity at each price level
  from a Level-2 (depth-of-market) feed.
* **VPIN** (Volume-Synchronized Probability of Informed Trading, Easley et al.
  2012): requires the full intraday trade-by-trade volume time series bucketed
  by volume (not by time) and the per-bucket buy/sell classification, which
  depends on trade-level data.

These signals will be implemented in a future sub-package once a tick-data
feed is available.

References
----------
Roll, R. (1984). "A Simple Implicit Measure of the Effective Bid-Ask Spread
    in an Efficient Market." Journal of Finance, 39(4), 1127-1139.

Corwin, S.A. & Schultz, P. (2012). "A Simple Way to Estimate Bid-Ask Spreads
    from Daily High and Low Prices." Journal of Finance, 67(2), 719-760.

Kyle, A.S. (1985). "Continuous Auctions and Insider Trading."
    Econometrica, 53(6), 1315-1335.

Amihud, Y. (2002). "Illiquidity and Stock Returns: Cross-Section and
    Time-Series Effects." Journal of Financial Markets, 5(1), 31-56.

Parkinson, M. (1980). "The Extreme Value Method for Estimating the Variance of
    the Rate of Return." Journal of Business, 53(1), 61-65.

Garman, M.B. & Klass, M.J. (1980). "On the Estimation of Security Price
    Volatilities from Historical Data." Journal of Business, 53(1), 67-78.

Rogers, L.C.G. & Satchell, S.E. (1991). "Estimating Variance from High, Low
    and Closing Prices." Annals of Applied Probability, 1(4), 504-512.

Yang, D. & Zhang, Q. (2000). "Drift-Independent Volatility Estimation Based
    on High, Low, Open, and Close Prices." Journal of Business, 73(3), 477-491.

Easley, D., Lopez de Prado, M.M. & O'Hara, M. (2012). "Flow Toxicity and
    Liquidity in a High-Frequency World." Review of Financial Studies,
    25(5), 1457-1493.
"""
from __future__ import annotations

from core_trading.signals.microstructure.hf_vol import (
    VolConfig,
    close_to_close_vol,
    garman_klass_vol,
    parkinson_vol,
    rogers_satchell_vol,
    yang_zhang_vol,
)
from core_trading.signals.microstructure.kyle_lambda import (
    KyleConfig,
    amihud_illiq,
    kyle_lambda,
)
from core_trading.signals.microstructure.spread import (
    SpreadConfig,
    corwin_schultz_spread,
    roll_spread,
)

__all__ = [
    # spread (bid-ask proxies)
    "SpreadConfig",
    "roll_spread",
    "corwin_schultz_spread",
    # kyle_lambda (price impact / illiquidity)
    "KyleConfig",
    "amihud_illiq",
    "kyle_lambda",
    # hf_vol (range-based realised volatility)
    "VolConfig",
    "close_to_close_vol",
    "parkinson_vol",
    "garman_klass_vol",
    "rogers_satchell_vol",
    "yang_zhang_vol",
]
