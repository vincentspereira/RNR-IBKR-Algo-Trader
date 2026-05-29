# Free Data Vendors -- Development and Paper Trading

**Date:** 2026-05-28
**Author:** Vincent S. Pereira (drafted with Claude)
**Status:** Vendor inventory for Phase 1 data infrastructure (development + paper-trading horizon)

---

## Purpose

While the system is being built and through the 90-day paper-trading period,
we use free / open-source data sources only. Paid vendors are revisited
immediately before live trading begins (when data quality directly affects
real-money decisions and stricter point-in-time guarantees matter).

This document inventories the free options, what they cover, what their limits
are, and recommends the stack to use.

---

## TL;DR Recommended Stack (free, dev + paper)

| Data type | Vendor | Library / API | Why |
|---|---|---|---|
| Historical OHLCV bars (equities) | **IBKR** | `ib_insync` / native | Already paying broker fees; clean adjusted/unadjusted; survivorship-bias-free if requested properly |
| Historical OHLCV fallback | **yfinance** | `yfinance` Python library | Free, no API key, broad coverage, easy |
| Real-time / live data | **IBKR** | `ib_insync` | Comes with the broker connection |
| Intraday bars (1m / 5m, recent) | **yfinance** + **Alpha Vantage** | Mixed | yfinance has limits past ~60 days; AV fills the gap |
| Fundamentals (basic) | **yfinance** | `Ticker.financials`, `.balance_sheet`, `.cashflow` | Free, but NOT point-in-time |
| Fundamentals (point-in-time) | **SEC EDGAR** | `sec-edgar-downloader` or direct API | Authoritative source; requires parsing |
| Macro indicators | **FRED** | `fredapi` Python library | Free, official, full history |
| Treasury yields | **FRED** + **U.S. Treasury direct** | `fredapi` | Free, clean |
| News & sentiment | **Finnhub free tier** + **NewsAPI free tier** | REST | Limited but usable for prototyping |
| Options chains (basic) | **yfinance** | `Ticker.options` | Surface-level only; no historical greeks |
| Corporate actions (splits/divs) | **yfinance** + **IBKR** | `Ticker.actions` | Cross-validate the two |
| Crypto | **CCXT** | `ccxt` (multi-exchange) | Free, supports Binance/Coinbase/etc public endpoints |
| Universe membership (S&P 500 etc.) | **Wikipedia + nasdaq.com** | scrape + cache | Free; survivorship bias needs careful handling |

**Honest caveat:** every free source has either rate limits, gaps, or point-in-time
issues. The Phase 1 data quality framework (see master plan §1.8) is mandatory
because of this. Free data is fine *if* you actively validate it.

---

## Detailed vendor list

### 1. yfinance (Yahoo Finance scraper)

- **Cost:** Free, no API key
- **Install:** `pip install yfinance`
- **Coverage:** Global equities, ETFs, indices, FX, crypto, mutual funds, basic options
- **Strengths:**
  - Zero friction; 5 lines of code to download 20 years of daily bars
  - Adjusted close + dividend/split history
  - Basic fundamentals (income statement, balance sheet, cash flow)
- **Weaknesses:**
  - **Not point-in-time** -- fundamentals are restated; using them in backtests leaks future information unless you handle this manually
  - Subject to Yahoo's terms of service; can break unexpectedly when Yahoo changes their site
  - Intraday data: only ~60 days for 1m bars, ~730 days for hourly
  - No survivorship-bias-free universe construction (delisted tickers vanish)
- **Use for:** OHLCV bars (development), prototyping signals, cross-validating IBKR data
- **Do not use for:** point-in-time fundamental backtests of strategies you will trade live

### 2. Alpha Vantage

- **Cost:** Free tier with key; premium $50/mo
- **Install:** `pip install alpha-vantage`
- **API key:** free signup at https://www.alphavantage.co/support/#api-key
- **Free tier limits:** 25 requests/day (down from 500/day historically)
- **Coverage:** Equities (US + global), FX, crypto, technicals, basic fundamentals, sector/economic indicators
- **Strengths:** Clean REST API, no scraping
- **Weaknesses:**
  - 25/day free limit is severe; useful only for spot checks or cached one-time pulls
  - Premium tier needed for serious use ($50/mo lifts to 75/min unlimited daily)
- **Use for:** spot-checks, intraday-bar fallback when yfinance is rate-limited
- **Recommendation:** sign up for the free key but plan as backup, not primary

### 3. SEC EDGAR (fundamentals, point-in-time)

- **Cost:** Free, official US government source
- **Install:** `pip install sec-edgar-downloader` or use REST directly
- **API:** https://data.sec.gov/submissions/ (rate limit: 10 requests/sec)
- **Coverage:** All SEC filings for all US-listed companies (10-K, 10-Q, 8-K, Form 4 insider, 13F holdings)
- **Strengths:**
  - **Point-in-time correct** -- filings have a date stamp; you can reconstruct what was known on any historical date
  - Authoritative source; no third-party scraping risk
  - Covers insider trades and institutional 13F holdings (alt-data signals from Phase 5)
- **Weaknesses:**
  - Filings are XBRL / HTML; need parsing (XBRL parsers exist: `python-edgar`, `arelle`)
  - Filing dates != event dates (a 10-K covers fiscal year ending Dec 31 but is filed in March -- backtests must use filing date)
- **Use for:** all fundamental data that will be used in research that may go live
- **This is the gold standard for free fundamentals**

### 4. FRED (Federal Reserve Economic Data)

- **Cost:** Free with API key
- **Install:** `pip install fredapi`
- **API key:** free signup at https://fred.stlouisfed.org/docs/api/api_key.html
- **Free tier limits:** 120 requests/minute (generous)
- **Coverage:** 800,000+ macro time series -- interest rates, inflation, GDP, employment, money supply, exchange rates, commodities, credit spreads
- **Strengths:**
  - Authoritative U.S. macro source
  - Long history (often 50+ years)
  - Clean API; vintage data available (point-in-time)
- **Weaknesses:**
  - U.S.-centric (other central banks have their own portals)
- **Use for:** all macro factor signals, regime detection inputs, term structure analysis
- **No reason not to use FRED if your strategy needs macro data**

### 5. Finnhub

- **Cost:** Free tier with key; premium tiers from $50/mo
- **Install:** `pip install finnhub-python`
- **API key:** free signup at https://finnhub.io/register
- **Free tier limits:** 60 calls/minute
- **Coverage:** Real-time stock quotes (limited symbols on free tier), news, basic fundamentals, earnings calendar, IPO calendar, insider transactions, social sentiment
- **Strengths:**
  - 60 calls/minute is workable for many use cases
  - News API is usable on free tier (limited history)
  - Earnings calendar is high-quality
- **Weaknesses:**
  - Free tier real-time data is delayed or restricted to U.S. equities only
  - Historical OHLCV is limited on free tier
- **Use for:** earnings calendar, basic news for sentiment prototyping
- **Recommendation:** sign up free, use selectively

### 6. Polygon.io

- **Cost:** Free tier; paid from $29/mo
- **Install:** `pip install polygon-api-client`
- **API key:** free signup at https://polygon.io/
- **Free tier limits:** 5 calls/minute (severe)
- **Coverage:** US equities, options, FX, crypto, news
- **Strengths:** Clean data, professional-grade infrastructure
- **Weaknesses:** Free tier is essentially useless for ongoing work
- **Use for:** N/A on free tier; mark as a paid upgrade candidate

### 7. Tiingo

- **Cost:** Free tier; paid from $30/mo
- **Install:** `pip install tiingo`
- **API key:** free signup at https://api.tiingo.com/
- **Free tier limits:** 50 calls/hour, 1000 calls/day, daily-only data
- **Coverage:** US equities (long history including delisted -- survivorship-bias-friendly), forex, crypto, news
- **Strengths:**
  - **Includes delisted equities** -- one of the few free sources that does
  - Long history (1962+ for major U.S. stocks)
  - Adjusted prices including survivor names
- **Weaknesses:** Free tier rate limits will pinch for full-universe pulls
- **Use for:** survivorship-bias-free U.S. equity history; supplement to IBKR
- **Recommendation:** sign up free; useful specifically for the delisted-name problem

### 8. CCXT (crypto, multi-exchange)

- **Cost:** Free library wrapping public exchange APIs
- **Install:** `pip install ccxt`
- **Coverage:** 100+ crypto exchanges (Binance, Coinbase, Kraken, etc.)
- **Strengths:** Unified API across exchanges; public endpoints are free
- **Weaknesses:** Each exchange has its own rate limits; deep historical tick data may not be available on public endpoints
- **Use for:** all crypto data if/when crypto strategies enter scope

### 9. IBKR (your broker)

- **Cost:** Bundled with the broker account (no extra fees for many data types)
- **Install:** `pip install ib_insync` or `ibapi`
- **Coverage:** Equities, options, futures, FX, bonds, mutual funds across all global exchanges IBKR supports
- **Strengths:**
  - You are already paying for the broker; data is largely included
  - Live tick streams + historical bars via the same connection
  - Professional-grade quality
  - Real venue identifiers; supports backtest realism
- **Weaknesses:**
  - Some data types require additional subscription (e.g., NASDAQ Level 2)
  - API pacing rules apply (avoid hammering)
  - Historical depth varies by instrument
- **Use for:** PRIMARY source for OHLCV and live data
- **This is your gold standard for daily/intraday bars while developing**

### 10. NewsAPI

- **Cost:** Free tier; paid from $449/mo (jump is large)
- **Install:** `pip install newsapi-python`
- **API key:** free at https://newsapi.org/
- **Free tier limits:** 100 requests/day, articles only up to 24 hours old (development)
- **Use for:** prototyping sentiment signals; not production
- **Recommendation:** sign up; usable for proof-of-concept only

### 11. Wikipedia + Wikidata (universe construction)

- **Cost:** Free
- **Install:** `pip install wikipedia` or use Wikipedia API directly
- **Coverage:** Historical S&P 500 / Russell / Nifty constituent lists (often by-year tables)
- **Strengths:** Free way to reconstruct historical universe membership
- **Weaknesses:** Quality varies; manual cross-check needed
- **Use for:** universe construction with survivorship-bias awareness

---

## Mapping vendors to plan phases

### Phase 1 (Data Infrastructure)

Required pulls (one-time + scheduled):

| Phase 1 task | Vendor (free) | Vendor (paid, future) |
|---|---|---|
| 1.1 Universe construction | Wikipedia + IBKR contract universe | Norgate Data |
| 1.2 Historical OHLCV bars | **IBKR** primary, yfinance fallback | -- |
| 1.3 Corporate actions | IBKR + yfinance cross-check | Norgate |
| 1.4 Fundamentals (point-in-time) | **SEC EDGAR** | Sharadar, SimFin Premium |
| 1.5 Reference data (sectors, etc.) | Wikipedia + EDGAR | Compustat |
| 1.6 Alternative data (deferred) | Finnhub, NewsAPI for prototypes | Refinitiv, Benzinga |
| 1.7 Live data feed | **IBKR** | -- |
| 1.8 Data quality | -- | -- |

### Phase 5 (signal library)

| Signal class | Free data sources sufficient? | Notes |
|---|---|---|
| Pairs trading (cointegration) | Yes -- IBKR OHLCV | No fundamentals needed |
| Statistical arbitrage | Yes -- IBKR OHLCV | -- |
| Multi-factor (Fama-French style) | Yes if SEC EDGAR parsing works | Otherwise stub with point-in-time aware yfinance for development |
| Momentum / mean reversion | Yes -- IBKR OHLCV | -- |
| ML on technical features | Yes -- IBKR OHLCV | -- |
| Earnings drift (PEAD) | Yes -- Finnhub earnings calendar + IBKR price | Cross-validate timestamps |
| News sentiment | Limited -- prototype only on NewsAPI/Finnhub free | Paid news needed for serious live |
| Macro / regime | Yes -- FRED | -- |
| Options-based signals | Limited -- yfinance options chains have no historical | Paid feed needed for live |

**Conclusion:** with free data alone we can do the **majority** of the Phase 5
signal library through paper trading. The exceptions are:
- Production-grade news / sentiment signals
- Historical options chains (greeks history)
- High-quality survivorship-bias-free universes for serious factor backtests

These remain on the "before live trading" upgrade list.

---

## Free-tier integration checklist (Phase 1 execution)

For each vendor we adopt, we will:

- [ ] Sign up for the free key (Alpha Vantage, FRED, Finnhub, Tiingo, NewsAPI)
- [ ] Store all keys in `.env` (already present); add fields to `.env.example`
- [ ] Wrap each vendor with a clean `core_trading/data/sources/<vendor>.py` adapter implementing a uniform interface
- [ ] Add rate-limit-aware retry logic (per-vendor specifics)
- [ ] Add caching layer so repeated pulls during research don't burn quota
- [ ] Add cross-vendor validation (e.g., yfinance vs IBKR close prices) to data-quality dashboard
- [ ] Document each vendor's known limitations in the source adapter's docstring

---

## Upgrade decision triggers (when to move to paid)

Move a specific data type to a paid vendor when **any** of:

1. The free source is rate-limiting often enough to delay research
2. A live strategy depends on data that only a paid source provides at production quality (e.g., point-in-time fundamentals for a factor strategy)
3. The free source goes down or changes API and we lose a week to remediation (yfinance has done this twice historically)
4. A signal moves from paper to live trading and consumes data that may not be reliable at the moment of decision

Concrete paid vendor candidates when triggered:

- **Norgate Data** ($300-$500/yr) -- survivorship-bias-free U.S. equity history with delisted names. Top of the upgrade list.
- **Sharadar** ($50-$200/mo) -- point-in-time fundamentals at ~3-year history minimum. Second.
- **Polygon.io** ($29-$199/mo) -- when intraday quality matters and IBKR depth isn't sufficient.
- **Refinitiv / Benzinga** -- only if news-sentiment becomes a confirmed live signal.

---

## Risks of free-only data (acknowledge them now)

1. **Yahoo Finance may break.** The scraping library has been broken twice in recent history; we keep a fallback (Alpha Vantage cache) and our data-quality dashboard alerts on stale data.
2. **No survivorship-bias-free history without Tiingo or paid sources.** Mitigation: use Tiingo free tier for delisted-name validation; document all backtest results with this caveat.
3. **Point-in-time fundamental data requires EDGAR parsing.** This is real engineering work (~40 hours), but it is doable and free.
4. **Alternative data signals are limited.** Sentiment and options-flow strategies cannot be fully validated on free data. Defer those to post-live-trading phase.
5. **News feeds are restricted on free tier.** Prototype on Finnhub free; do not promote to paper trading without paid news.

These risks are acceptable for the dev + paper-trading horizon, given the
cost savings and the parallel work of building the data quality framework.
