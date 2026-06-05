# Pairs Research Pass -- long-history walk-forward

History    : 2005-01-03 .. 2026-06-04 (5389 sessions, 100 symbols)
Skeleton   : formation 252, trading 126 (contiguous OOS)
Costs      : 'ibkr' (linear turnover charge, vectorised mode)
Trials     : 24 configs (full grid is the DSR/PBO/RC trial bank)
Candidate  : z30_e1.5_x0.5_p20_sector
  net Sharpe          : 0.728
  frictionless Sharpe : 0.883
  pilot config Sharpe : 0.180 (z60_e2.0_x0.5_p10_sector)

CAVEAT: current-constituent SP100 universe over historical windows
(survivorship bias, flatters the result). PROMOTE here is an upper
bound pending point-in-time constituents (Norgate); REJECT is
close to decisive because the bias works in the strategy's favour.

## Config grid (net of costs)

| config                       |  Sharpe | total ret |  max DD | active |
|------------------------------|---------|-----------|---------|--------|
| z30_e1.5_x0.5_p20_sector     |   0.728 |    25.6% |   -6.2% | 100.0% |
| z30_e2.5_x1.0_p20_sector     |   0.720 |    18.4% |   -7.0% |  88.4% |
| z30_e2.0_x0.5_p20_sector     |   0.598 |    19.8% |   -6.7% |  99.8% |
| z60_e2.5_x1.0_p20_sector     |   0.532 |    14.2% |   -6.8% |  90.3% |
| z60_e1.5_x0.5_p20_sector     |   0.450 |    15.3% |   -8.5% | 100.0% |
| z30_e1.5_x0.5_p10_sector     |   0.418 |    10.5% |   -3.4% |  99.5% |
| z30_e2.0_x0.5_p10_sector     |   0.410 |     9.2% |   -4.8% |  94.4% |
| z60_e2.5_x1.0_p10_sector     |   0.408 |     6.3% |   -3.1% |  57.5% |
| z30_e2.5_x1.0_p20_open       |   0.402 |     4.0% |   -1.1% |  27.9% |
| z30_e2.0_x0.5_p20_open       |   0.345 |     6.6% |   -2.5% |  71.9% |
| z60_e2.0_x0.5_p20_sector     |   0.339 |    11.1% |   -8.5% | 100.0% |
| z30_e1.5_x0.5_p20_open       |   0.329 |     6.9% |   -3.1% |  89.3% |
| z30_e2.5_x1.0_p10_sector     |   0.259 |     3.7% |   -4.6% |  53.8% |
| z60_e2.5_x1.0_p10_open       |   0.251 |     2.0% |   -1.3% |  16.5% |
| z60_e2.5_x1.0_p20_open       |   0.227 |     2.7% |   -1.8% |  34.2% |
| z60_e2.0_x0.5_p10_sector     |   0.180 |     4.0% |   -5.2% |  91.8% | <- pilot
| z60_e1.5_x0.5_p10_sector     |   0.179 |     4.3% |   -5.6% |  99.1% |
| z30_e1.5_x0.5_p10_open       |   0.090 |     1.3% |   -3.6% |  69.3% |
| z30_e2.5_x1.0_p10_open       |   0.086 |     0.6% |   -1.2% |  14.9% |
| z60_e2.0_x0.5_p10_open       |   0.079 |     1.1% |   -3.3% |  43.2% |
| z30_e2.0_x0.5_p10_open       |   0.032 |     0.4% |   -2.7% |  46.9% |
| z60_e2.0_x0.5_p20_open       |   0.002 |    -0.0% |   -4.6% |  66.9% |
| z60_e1.5_x0.5_p20_open       |  -0.082 |    -2.0% |   -7.3% |  88.1% |
| z60_e1.5_x0.5_p10_open       |  -0.203 |    -3.5% |   -6.2% |  67.6% |

# Statistical Robustness Report

Verdict    : REJECT
Generated  : 2026-06-05T19:12:01Z
Observations: 5137
Trials     : 24

## Summary Statistics

Annualised Sharpe : 0.7278
Bootstrap CI      : [0.2391, 1.2538] at 95% (1000 resamples)
PSR (vs zero)     : 0.9995
Deflated Sharpe   : 0.8773
PBO               : 0.2445
Reality Check p   : 0.0140
Hansen SPA p      : 0.0220
CPCV OOS Sharpe   : mean 0.6860, std 0.6072, 5th pct -0.1315, frac_neg 0.2000 (15 folds)

## Promotion Gates

| Gate                                 | Status         | Observed   | Limit      | Req |
|--------------------------------------|----------------|------------|------------|-----|
| Bootstrap Sharpe CI lower bound      | >= PASS        | 0.2391     | 0.0000     | yes |
| Deflated Sharpe Ratio                | >= FAIL        | 0.8773     | 0.9500     | yes |
| Probability of Backtest Overfitting  | <= PASS        | 0.2445     | 0.5000     | yes |
| White's Reality Check                | <= PASS        | 0.0140     | 0.1000     | yes |
| CPCV out-of-sample stability         | <= PASS        | 0.2000     | 0.5000     | yes |

## Gate Detail

- [PASS] Bootstrap Sharpe CI lower bound: 95% CI lower bound 0.2391 vs minimum 0.0000
- [FAIL] Deflated Sharpe Ratio: DSR 0.8773 vs minimum 0.9500 across 24 trials
- [PASS] Probability of Backtest Overfitting: PBO 0.2445 vs maximum 0.5000 over 12870 CSCV combinations
- [PASS] White's Reality Check: Reality-Check p-value 0.0140 vs maximum 0.1000
- [PASS] CPCV out-of-sample stability: fraction of negative OOS folds 0.2000 vs maximum 0.5000 (mean OOS Sharpe 0.6860, 5th pct -0.1315)

## ADDENDUM: candidate era stability (net of ibkr costs, post-hoc 2026-06-05)

| era          |  Sharpe |  max DD |  days |
|--------------|---------|---------|-------|
| 2006-2010    |   1.967 |   -2.7% |  1259 |
| 2011-2015    |   0.831 |   -1.6% |  1258 |
| 2016-2020    |   0.210 |   -3.5% |  1259 |
| 2021-2026    |  -0.357 |   -6.2% |  1361 |

The full-period Sharpe 0.728 is carried by the pre-2016 regime (2008 alone:
Sharpe 4.92). The most recent five-plus years are NEGATIVE net of costs --
consistent with the documented decay of distance pairs trading on large caps
(Do & Faff 2010, and since). The DSR gate's REJECT is therefore not marginal:
iterating the config grid on this history would select for exposure to a
regime that no longer exists. The 2026-06-05 IBKR-2Y result (Sharpe -0.03)
and the 2021-2026 era here (-0.36) agree.

CONCLUSION: REJECT is decisive for SP100 daily distance pairs. The 90-day
clock stays HELD for this strategy family. Forward paths are a different
universe (mid/small-cap or ETF pairs), a different signal family (Phase 5/10
promoted signals), or intraday spreads (data-blocked) -- operator decision.
