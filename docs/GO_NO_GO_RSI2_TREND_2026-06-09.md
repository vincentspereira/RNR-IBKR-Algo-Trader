# Go / No-Go Memo -- rsi2/trend (ta_quant family)

**Date:** 2026-06-09
**Author:** Vincent S. Pereira (with Claude)
**Candidate:** `rsi2t15_trend200` -- RSI(2) mean-reversion dip-buy, gated by a
200-day trend filter, ta_quant family champion
**Source:** full 94-config walk-forward sweep, 2005-2026, S&P 100, net of IBKR
costs (`logs/strategy_sweep/sweep_report_20260609_021324.txt`)

## Verdict: CONDITIONAL HOLD -- do not start the 90-day paper clock yet

One thing stands between this strategy and paper trading, and it is **not** a
code problem and **not** the deflated-Sharpe REJECT. It is the data: every
number below is computed on a **survivorship-biased universe** (today's S&P 100
constituents projected back to 2005), and this particular signal -- buying
short-term dips -- is the single signal family that survivorship bias flatters
most. The decision is binary and cheap to resolve: **re-run on point-in-time
data (Norgate, ~USD 300-500/yr). If the edge survives, promote to paper. If it
collapses, it was survivorship all along.**

## The numbers in plain English

The champion bought oversold dips (RSI(2) < 15) in names trading above their
200-day average, across the S&P 100, for 21 years. Net of costs:

| Metric | Value | What it means |
| --- | --- | --- |
| Net Sharpe | 1.05 | Strong for a single strategy (the plan's own realistic ceiling for a solo operator is 1.0-1.5) |
| Total return | 2461% | Over 21 years; flattered by survivorship -- see below |
| Max drawdown | -22% | Tolerable, not scary |
| Time in market | 97% | Almost always invested (long-biased, NOT market-neutral) |

### Era stability -- this is the genuinely impressive part

| Era | Sharpe |
| --- | --- |
| 2006-2011 (incl. GFC) | 0.80 |
| 2012-2017 | 1.53 |
| 2018-2023 (incl. COVID) | 0.91 |
| 2024-2026 | 1.13 |

Every era is positive and above 0.79. This is the **opposite** of the pairs
pilot, which had a dead regime (Sharpe -0.36 in 2021-26) hiding inside a decent
full-period number. There is no dead era here. A real, persistent effect looks
like this.

## Why the gate says REJECT -- and why that single REJECT is misleading

The robustness battery runs five gates. **Four of five PASS, including the hard
search-aware ones:**

| Gate | Result | Verdict |
| --- | --- | --- |
| Bootstrap Sharpe 95% CI lower bound | 0.68 (> 0) | PASS -- the edge is not a coin-flip |
| Probability of Backtest Overfitting (PBO) | 0.11 (< 0.50) | PASS -- low overfit risk over 12,870 combinations |
| White's Reality Check (search-aware) | p = 0.001 | PASS -- best-of-94 is genuinely significant |
| Hansen SPA (search-aware) | p = 0.001 | PASS |
| CPCV out-of-sample stability | 0/15 folds negative, mean OOS Sharpe 1.06, 5th-pct 0.82 | PASS -- every single out-of-sample path is positive |
| **Deflated Sharpe Ratio (DSR)** | **0.295 vs 0.95 required** | **FAIL -- the only failure** |

The lone failure is the Deflated Sharpe. Here is the subtlety, in plain terms:

- The DSR penalises you for the **number** of strategies you tried (94) before
  picking the winner. It assumes those 94 were 94 independent shots on goal.
- But the 94 configs are **not** 94 independent ideas. They are a dense
  parameter grid of a handful of correlated families (RSI2 with different
  thresholds and overlays, Donchian channels, Keltner squeezes). Sweeping
  correlated knobs of the same idea is not the same as testing 94 different
  edges. The DSR over-counts the search and therefore over-penalises.
- The tests that model the **actual joint behaviour** of the trials rather than
  assuming independence -- White's Reality Check and Hansen's SPA -- both say
  the winner is significant at p = 0.001. When the independence-assuming test
  (DSR) disagrees with the correlation-aware tests (RC/SPA), and CPCV shows
  every fold positive, the DSR is the one being too conservative.

So the DSR REJECT is a **trial-bank artifact**, not evidence the strategy is
noise. The weight of the evidence (RC, SPA, PBO, CPCV, bootstrap CI, era
stability) says this is a real effect.

## So why is the verdict still HOLD, not GO?

Because of the one thing none of those gates can fix: **survivorship bias.**

- The universe is the *current* S&P 100, walked backwards. Every name in it is,
  by definition, a company that survived and thrived to 2026. The dippers that
  went to zero (Lehman, Bear Stearns, Wachovia, Monsanto, dozens of delisted
  names) are simply absent.
- RSI(2) dip-buying is a bet that "what fell will bounce." On a universe of
  guaranteed survivors, that bet is rigged in your favour -- every dip you
  bought eventually recovered, because you only ever held future winners.
- On a true point-in-time universe that includes the names that dipped and then
  *delisted*, some of those "buy the dip" trades end in -100%. That is exactly
  the cohort that erodes a mean-reversion edge.

The sweep report says it directly: *"PROMOTE is an upper bound pending Norgate;
REJECT is close to decisive."* This is a PROMOTE-leaning result, so we are in
"upper bound" territory -- the number is the best case, and the real number is
somewhere at or below it. We do not know how far below without clean data.

## The one action that resolves this

1. **Buy Norgate Data** (~USD 300-500/yr) for point-in-time S&P membership with
   delisted names. (Tiingo free tier is a partial fallback.)
2. **Re-run `tools/strategy_research_sweep.py`** against the survivorship-free
   universe.
3. **Read the era table.** If `rsi2t15_trend200` (or its close siblings
   `rsi2t10_trend200`, or the lower-drawdown `rsi2t10_trend200_volt10` at
   Sharpe 1.00 / -15% maxDD) holds an era-stable Sharpe near 0.8+ with delisted
   names included -> **GO to the 90-day paper run** (it has already cleared
   every search-aware gate). If the edge halves or develops a dead era ->
   **NO-GO**, it was survivorship, retire it.

That is the entire decision. Everything else is built and waiting:
`docs/OPERATOR_SETUP_RUNBOOK.md` covers data ingest -> dashboard -> paper run.

## Secondary candidate worth keeping warm: pca_statarb

`pca5_lb252_q0.2` (Avellaneda-Lee PCA residual reversion) is the runner-up at
net Sharpe 0.66. It fails DSR for the same trial-bank reason but passes bootstrap
CI / PBO / RC / CPCV. Two contrasting properties vs rsi2/trend:

- **Pro:** it is dollar-neutral long/short, so survivorship bias hits it far less
  than a 97%-long dip-buyer. Its 0.66 is closer to its "real" number.
- **Con:** its era table decays monotonically (1.22 -> 0.50 -> 0.37 -> 0.20).
  The edge is fading; by 2024-26 it is only 0.20. Classic alpha decay.

Net: rsi2/trend has the higher and more stable headline but the bigger
survivorship asterisk; pca_statarb has the cleaner survivorship profile but a
visibly decaying edge. Validate rsi2/trend first (one data purchase tests both,
since the sweep runs every family at once).

## Bottom line

- This is the **strongest candidate the system has produced.** It is not noise.
- It cannot start the paper clock on survivorship-biased data, because its signal
  family is the one most flattered by that bias.
- **Cost to resolve: one ~USD 300-500/yr data subscription and a re-run.** This
  is the highest-leverage dollar in the whole project.
