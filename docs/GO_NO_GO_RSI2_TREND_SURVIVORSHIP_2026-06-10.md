# Go / No-Go Memo -- rsi2/trend survivorship validation (no paid data)

**Date:** 2026-06-10
**Author:** Vincent S. Pereira (with Claude)
**Supersedes:** `docs/GO_NO_GO_RSI2_TREND_2026-06-09.md` (verdict was
CONDITIONAL HOLD pending survivorship validation)
**Candidate:** `rsi2t15_trend200` -- RSI(2) dip-buy gated by a 200-day trend
filter; low-drawdown sibling `rsi2t10_trend200_volt10`
**Reports:** `logs/strategy_sweep/sweep_report_sp500pit_20260610_014458.txt`,
`logs/strategy_sweep/sweep_report_etf_20260610_012908.txt`,
`logs/strategy_sweep/delisting_stress_20260610_013309.txt` (local, gitignored)

## Verdict: GO -- start the 90-day paper clock

The 2026-06-09 memo pre-registered the GO criterion: *"if rsi2t15_trend200
holds an era-stable Sharpe near 0.8+ with delisted names included -> GO to
the 90-day paper run."* That criterion is now met -- not with Norgate, but
with three independent free tests that all land on the same number:

| Test | What it fixes | Net Sharpe |
| --- | --- | --- |
| Static S&P 100 (old baseline) | nothing -- survivorship-biased | 1.05 |
| **Point-in-time S&P 500 membership** | late-joiner bias; fallen angels included | **0.82** |
| **PIT + worst-case delisting injection** | the unpriced bankrupt cohort | **0.81** |
| **Survivorship-robust ETF universe** | survivorship structurally impossible | **0.81** (family 0.60-0.88) |

Survivorship bias was real -- it inflated the static number by ~0.23 of
Sharpe -- and with it removed three different ways, the edge is still there:
**net Sharpe ~0.8, max drawdown ~-27%, no dead era, no alpha decay.** Plan
forward expectations on 0.8, not 1.05.

## What was built (all free, all repeatable)

1. **Point-in-time membership** (`data/universe/sp500_ticker_start_end.csv`,
   MIT, fja05680/sp500, base list from Clenow's *Trading Evolved*; current
   through 2026-06). Loader: `core_trading/data/universe_history.py`.
   `tools/strategy_research_sweep.py --universe sp500pit` restricts each
   walk-forward window to true members on the first OOS bar, then takes the
   top-100 by formation dollar volume (look-ahead-free).
2. **Coverage measurement:** 727 of 970 historical members since 2005 have
   full free price data (58% of membership-days in 2005 rising to 99.8% in
   2026). The 243 unpriced names are the acquired/bankrupt cohort.
3. **Delisting stress test** (`tools/delisting_stress_test.py`): injects all
   248 unpriced membership spells as synthetic members that track the market
   with idiosyncratic noise, then forces distress exits at their TRUE removal
   dates (-80% gradual deaths and -55% two-day crashes). Even at **100%
   distress share** -- every unpriced removal treated as a bankruptcy --
   the candidate loses only 0.004-0.04 of Sharpe. The SMA-200 gate inside
   `rsi_dip` is the protective mechanism: names grinding to zero disengage
   the long filter before the dip-buys pile in.
4. **ETF cross-validation** (`--universe etf`, 55 long-history liquid ETFs):
   index/sector ETFs cannot go to zero via single-name bankruptcy, so the
   dip-buy survivorship mechanism is structurally absent. The RSI-dip family
   takes the **top 11 of 94 slots**; champion `rsi2t10_calm75` at 0.88 with
   eras 0.78 / 0.79 / 0.91 / 1.41 -- improving, not decaying.

## The numbers on the PIT universe (the honest baseline)

`rsi2t15_trend200`, 5,140 OOS days, net of IBKR costs:

| Era | Sharpe | max DD |
| --- | --- | --- |
| 2006-2011 (incl. GFC) | 0.65 | -21.0% |
| 2012-2017 | 1.18 | -12.7% |
| 2018-2023 (incl. COVID) | 0.69 | -26.6% |
| 2024-2026 | 0.97 | -23.8% |

| Gate | Result | Verdict |
| --- | --- | --- |
| Bootstrap Sharpe 95% CI lower bound | 0.45 (> 0) | PASS |
| PBO | 0.093 | PASS |
| CPCV stability | 0/15 folds negative, 5th pct 0.68 | PASS |
| Hansen SPA (search-aware) | p = 0.020 | PASS |
| White's Reality Check | p = 0.115 vs 0.10 | MARGINAL FAIL |
| Deflated Sharpe Ratio | 0.13 vs 0.95 | FAIL (trial-bank artifact, as documented 2026-06-09) |

On the honest universe the champion's margin over the 94-trial bank narrows,
so the unstandardised Reality Check slips just over its limit while Hansen's
SPA -- the studentised successor designed to stop irrelevant high-variance
trials from masking a real winner -- stays clearly significant. Combined
with zero negative CPCV folds and a strictly positive bootstrap CI, the
weight of evidence is unchanged: real, modest, persistent edge.

## Why this is enough to start PAPER (and what still gates LIVE)

* Paper trading risks nothing; its 90-day wall-clock is the scarce resource.
  The pre-registered bar for spending that clock -- era-stable ~0.8 with
  delisted names accounted for -- is met three independent ways.
* The Norgate purchase (~USD 300-500/yr) is NOT cancelled; it moves to the
  **live gate**, where it belongs: before the first real dollar, buy the
  point-in-time data, re-run `--universe sp500pit` against Norgate vintage
  membership AND delisted price series, and confirm the paper-period Sharpe.
  By then the subscription pays for itself or the 90-day paper run will have
  failed on its own.

## Honest caveats (kept deliberately visible)

1. The PIT top-100 dollar-volume slice competes only among PRICED members;
   residual within-slice selection is what the stress test bounds (answer:
   small). The stress synthetic series are a model, not data.
2. The membership CSV is community-maintained (Wikipedia-reconciled). Spot
   checks pass (LEHMQ in 2007 not 2009, TSLA absent 2015, ~500 members on
   every sampled date); it is not an audited vendor product.
3. yfinance back-adjusted OHLC; a handful of malformed Yahoo bars are dropped
   (`drop_invalid=True` on bulk research fetches only -- production stays
   strict).
4. DSR still fails and always will against a 94-config dense grid; RC is
   marginal on PIT. The promotion logic leans on SPA/CPCV/PBO/bootstrap as
   analysed in the 2026-06-09 memo.

## Recommended paper book (start of the 90-day clock)

| Slot | Config | Universe | Why |
| --- | --- | --- | --- |
| Primary | `rsi2t15_trend200` | PIT top-100 large caps | Highest honest Sharpe (0.82), the validated thesis |
| Defensive sibling | `rsi2t10_trend200_volt10` | PIT top-100 large caps | Vol-targeted: -19.6% maxDD vs -26.6%, Sharpe 0.77 |
| Zero-asterisk lane | `rsi2t10_calm75` | ETF_CORE | 0.88 on a universe with no survivorship question at all; improving eras |

Run all three at paper weights; the 90-day evaluation (per
`docs/OPERATOR_SETUP_RUNBOOK.md`) decides which graduates. TWS paper
connectivity re-verified 2026-06-10 (order lifecycle OK; fill pending market
open).

## Bottom line

* The survivorship question that blocked the 90-day clock is **answered with
  free data**: the edge survives point-in-time membership, survives a
  paranoid delisting stress, and reproduces on a survivorship-free asset
  class.
* The honest expectation is **~0.8 net Sharpe, ~-27% worst drawdown** -- plan
  position sizing and the kill-switch around that, not around 1.05.
* **Norgate moves to the live gate.** Nothing about going live changes; this
  memo only unblocks paper.
