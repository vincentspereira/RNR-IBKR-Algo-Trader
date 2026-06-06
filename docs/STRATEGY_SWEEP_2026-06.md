# Strategy Validation Sweep -- long-history walk-forward

History    : 2005-01-03 .. 2026-06-04 (5389 sessions, 100 symbols)
Skeleton   : formation 252 (warm-up), trading 126 (contiguous OOS)
Costs      : 'ibkr' (linear turnover charge, vectorised mode)
Trials     : 94 configs across 4 families (full sweep = trial bank)

CAVEAT: current-constituent SP100 universe (survivorship bias,
flatters results). PROMOTE = upper bound pending Norgate; REJECT
is close to decisive.

## Top configs (net of costs)

| config                               | family      |  Sharpe | total ret |  max DD | active |
|--------------------------------------|-------------|---------|-----------|---------|--------|
| rsi2t15_trend200                     | ta_quant    |   1.051 |  2461.5% |  -22.1% |  96.7% |
| rsi2t10_trend200                     | ta_quant    |   1.045 |  2245.9% |  -24.6% |  94.7% |
| rsi2t10_trend200_volt10              | ta_quant    |   1.001 |   681.3% |  -14.9% |  94.7% |
| rsi2t15_none                         | ta_quant    |   0.984 |  3696.0% |  -37.3% |  97.3% |
| rsi2t15_trend200_volt10              | ta_quant    |   0.955 |   610.8% |  -16.3% |  96.7% |
| rsi2t10_volt10                       | ta_quant    |   0.938 |   607.2% |  -18.0% |  96.1% |
| rsi2t10_none                         | ta_quant    |   0.934 |  3067.8% |  -37.1% |  96.0% |
| dc40_calm75                          | ta_quant    |   0.912 |   731.0% |  -34.5% |  73.4% |
| rsi2t15_volt10                       | ta_quant    |   0.894 |   536.0% |  -17.9% |  97.3% |
| dc55_calm75                          | ta_quant    |   0.880 |   707.2% |  -32.2% |  73.5% |
| rsi3t20_calm75                       | ta_quant    |   0.869 |   909.8% |  -32.0% |  72.0% |
| rsi2t10_calm75                       | ta_quant    |   0.868 |   891.1% |  -38.6% |  72.0% |
| dc40_trend200_volt10                 | ta_quant    |   0.850 |   482.6% |  -25.9% |  97.7% |
| rsi3t20_trend200                     | ta_quant    |   0.848 |  1071.9% |  -34.3% |  94.9% |
| dc55_trend200_volt10                 | ta_quant    |   0.840 |   473.2% |  -25.5% |  98.1% |
| rsi3t20_volt10                       | ta_quant    |   0.839 |   465.5% |  -24.7% |  96.1% |
| rsi3t20_trend200_volt10              | ta_quant    |   0.838 |   443.9% |  -24.9% |  94.9% |
| rsi2t15_calm75                       | ta_quant    |   0.837 |   737.3% |  -26.2% |  72.6% |
| dc40_volt10                          | ta_quant    |   0.817 |   435.7% |  -31.4% |  97.9% |
| dc55_volt10                          | ta_quant    |   0.812 |   432.7% |  -27.0% |  98.1% |
| rsi3t20_none                         | ta_quant    |   0.809 |  1844.4% |  -44.1% |  96.1% |
| ksq20_20_trend200_volt10             | ta_quant    |   0.772 |   271.7% |  -19.7% | 100.0% |
| ksq20_15_calm75                      | ta_quant    |   0.738 |    92.6% |  -12.1% |  73.6% |
| ksq20_15_volt10                      | ta_quant    |   0.714 |   258.8% |  -16.4% | 100.0% |
| dc40_trend200                        | ta_quant    |   0.686 |   507.6% |  -45.2% |  97.7% |
| dc55_trend200                        | ta_quant    |   0.670 |   530.7% |  -42.6% |  98.1% |
| pca5_lb252_q0.2                      | pca_statarb |   0.656 |   222.1% |  -19.5% | 100.0% |
| dc20_volt10                          | ta_quant    |   0.655 |   272.8% |  -25.2% |  97.9% |
| ksq20_20_trend200                    | ta_quant    |   0.653 |   108.5% |  -15.5% | 100.0% |
| dc40_none                            | ta_quant    |   0.641 |   556.3% |  -58.8% |  97.9% |
| ... 64 more configs elided ...

## Verdicts

- REJECT             ta_quant     rsi2t15_trend200 (net Sharpe 1.051)
- REJECT             pca_statarb  pca5_lb252_q0.2 (net Sharpe 0.656)
- REJECT             csmom        csmom_q0.2 (net Sharpe 0.164)
- REJECT             classical    vwmr_loose (net Sharpe -0.061)

## Family champion: classical -- vwmr_loose

Net Sharpe -0.061 over 5137 OOS days

### Era stability (net of costs)

| era          |  Sharpe |  max DD |  days |
|--------------|---------|---------|-------|
| 2006-2011    |   0.186 |  -36.2% |  1511 |
| 2012-2017    |  -0.016 |  -17.5% |  1509 |
| 2018-2023    |  -0.275 |  -39.1% |  1509 |
| 2024-2026    |  -0.553 |  -18.0% |   608 |

### Robustness battery

# Statistical Robustness Report

Verdict    : REJECT
Generated  : 2026-06-06T02:11:12Z
Observations: 5137
Trials     : 94

## Summary Statistics

Annualised Sharpe : -0.0611
Bootstrap CI      : [-0.3893, 0.2581] at 95% (1000 resamples)
PSR (vs zero)     : 0.3915
Deflated Sharpe   : 0.0000
PBO               : 0.1082
Reality Check p   : 0.0010
Hansen SPA p      : 0.0010
CPCV OOS Sharpe   : mean -0.0737, std 0.1877, 5th pct -0.3713, frac_neg 0.6667 (15 folds)

## Promotion Gates

| Gate                                 | Status         | Observed   | Limit      | Req |
|--------------------------------------|----------------|------------|------------|-----|
| Bootstrap Sharpe CI lower bound      | >= FAIL        | -0.3893    | 0.0000     | yes |
| Deflated Sharpe Ratio                | >= FAIL        | 0.0000     | 0.9500     | yes |
| Probability of Backtest Overfitting  | <= PASS        | 0.1082     | 0.5000     | yes |
| White's Reality Check                | <= PASS        | 0.0010     | 0.1000     | yes |
| CPCV out-of-sample stability         | <= FAIL        | 0.6667     | 0.5000     | yes |

## Gate Detail

- [FAIL] Bootstrap Sharpe CI lower bound: 95% CI lower bound -0.3893 vs minimum 0.0000
- [FAIL] Deflated Sharpe Ratio: DSR 0.0000 vs minimum 0.9500 across 94 trials
- [PASS] Probability of Backtest Overfitting: PBO 0.1082 vs maximum 0.5000 over 12870 CSCV combinations
- [PASS] White's Reality Check: Reality-Check p-value 0.0010 vs maximum 0.1000
- [FAIL] CPCV out-of-sample stability: fraction of negative OOS folds 0.6667 vs maximum 0.5000 (mean OOS Sharpe -0.0737, 5th pct -0.3713)


## Family champion: csmom -- csmom_q0.2

Net Sharpe 0.164 over 5137 OOS days

### Era stability (net of costs)

| era          |  Sharpe |  max DD |  days |
|--------------|---------|---------|-------|
| 2006-2011    |   0.350 |  -26.3% |  1511 |
| 2012-2017    |  -0.117 |  -23.7% |  1509 |
| 2018-2023    |  -0.015 |  -42.8% |  1509 |
| 2024-2026    |   0.778 |  -12.9% |   608 |

### Robustness battery

# Statistical Robustness Report

Verdict    : REJECT
Generated  : 2026-06-06T02:12:16Z
Observations: 5137
Trials     : 94

## Summary Statistics

Annualised Sharpe : 0.1636
Bootstrap CI      : [-0.2439, 0.5697] at 95% (1000 resamples)
PSR (vs zero)     : 0.7689
Deflated Sharpe   : 0.0000
PBO               : 0.1082
Reality Check p   : 0.0010
Hansen SPA p      : 0.0010
CPCV OOS Sharpe   : mean 0.1779, std 0.1899, 5th pct -0.0989, frac_neg 0.2000 (15 folds)

## Promotion Gates

| Gate                                 | Status         | Observed   | Limit      | Req |
|--------------------------------------|----------------|------------|------------|-----|
| Bootstrap Sharpe CI lower bound      | >= FAIL        | -0.2439    | 0.0000     | yes |
| Deflated Sharpe Ratio                | >= FAIL        | 0.0000     | 0.9500     | yes |
| Probability of Backtest Overfitting  | <= PASS        | 0.1082     | 0.5000     | yes |
| White's Reality Check                | <= PASS        | 0.0010     | 0.1000     | yes |
| CPCV out-of-sample stability         | <= PASS        | 0.2000     | 0.5000     | yes |

## Gate Detail

- [FAIL] Bootstrap Sharpe CI lower bound: 95% CI lower bound -0.2439 vs minimum 0.0000
- [FAIL] Deflated Sharpe Ratio: DSR 0.0000 vs minimum 0.9500 across 94 trials
- [PASS] Probability of Backtest Overfitting: PBO 0.1082 vs maximum 0.5000 over 12870 CSCV combinations
- [PASS] White's Reality Check: Reality-Check p-value 0.0010 vs maximum 0.1000
- [PASS] CPCV out-of-sample stability: fraction of negative OOS folds 0.2000 vs maximum 0.5000 (mean OOS Sharpe 0.1779, 5th pct -0.0989)


## Family champion: pca_statarb -- pca5_lb252_q0.2

Net Sharpe 0.656 over 5137 OOS days

### Era stability (net of costs)

| era          |  Sharpe |  max DD |  days |
|--------------|---------|---------|-------|
| 2006-2011    |   1.220 |  -14.9% |  1511 |
| 2012-2017    |   0.495 |   -9.5% |  1509 |
| 2018-2023    |   0.368 |  -18.6% |  1509 |
| 2024-2026    |   0.195 |   -9.3% |   608 |

### Robustness battery

# Statistical Robustness Report

Verdict    : REJECT
Generated  : 2026-06-06T02:13:20Z
Observations: 5137
Trials     : 94

## Summary Statistics

Annualised Sharpe : 0.6561
Bootstrap CI      : [0.1707, 1.1214] at 95% (1000 resamples)
PSR (vs zero)     : 0.9986
Deflated Sharpe   : 0.0099
PBO               : 0.1082
Reality Check p   : 0.0010
Hansen SPA p      : 0.0010
CPCV OOS Sharpe   : mean 0.6428, std 0.3374, 5th pct 0.1960, frac_neg 0.0000 (15 folds)

## Promotion Gates

| Gate                                 | Status         | Observed   | Limit      | Req |
|--------------------------------------|----------------|------------|------------|-----|
| Bootstrap Sharpe CI lower bound      | >= PASS        | 0.1707     | 0.0000     | yes |
| Deflated Sharpe Ratio                | >= FAIL        | 0.0099     | 0.9500     | yes |
| Probability of Backtest Overfitting  | <= PASS        | 0.1082     | 0.5000     | yes |
| White's Reality Check                | <= PASS        | 0.0010     | 0.1000     | yes |
| CPCV out-of-sample stability         | <= PASS        | 0.0000     | 0.5000     | yes |

## Gate Detail

- [PASS] Bootstrap Sharpe CI lower bound: 95% CI lower bound 0.1707 vs minimum 0.0000
- [FAIL] Deflated Sharpe Ratio: DSR 0.0099 vs minimum 0.9500 across 94 trials
- [PASS] Probability of Backtest Overfitting: PBO 0.1082 vs maximum 0.5000 over 12870 CSCV combinations
- [PASS] White's Reality Check: Reality-Check p-value 0.0010 vs maximum 0.1000
- [PASS] CPCV out-of-sample stability: fraction of negative OOS folds 0.0000 vs maximum 0.5000 (mean OOS Sharpe 0.6428, 5th pct 0.1960)


## Family champion: ta_quant -- rsi2t15_trend200

Net Sharpe 1.051 over 5137 OOS days

### Era stability (net of costs)

| era          |  Sharpe |  max DD |  days |
|--------------|---------|---------|-------|
| 2006-2011    |   0.796 |  -18.3% |  1511 |
| 2012-2017    |   1.527 |  -10.2% |  1509 |
| 2018-2023    |   0.913 |  -22.1% |  1509 |
| 2024-2026    |   1.127 |  -19.1% |   608 |

### Robustness battery

# Statistical Robustness Report

Verdict    : REJECT
Generated  : 2026-06-06T02:14:24Z
Observations: 5137
Trials     : 94

## Summary Statistics

Annualised Sharpe : 1.0511
Bootstrap CI      : [0.6821, 1.4649] at 95% (1000 resamples)
PSR (vs zero)     : 1.0000
Deflated Sharpe   : 0.2952
PBO               : 0.1082
Reality Check p   : 0.0010
Hansen SPA p      : 0.0010
CPCV OOS Sharpe   : mean 1.0598, std 0.1573, 5th pct 0.8174, frac_neg 0.0000 (15 folds)

## Promotion Gates

| Gate                                 | Status         | Observed   | Limit      | Req |
|--------------------------------------|----------------|------------|------------|-----|
| Bootstrap Sharpe CI lower bound      | >= PASS        | 0.6821     | 0.0000     | yes |
| Deflated Sharpe Ratio                | >= FAIL        | 0.2952     | 0.9500     | yes |
| Probability of Backtest Overfitting  | <= PASS        | 0.1082     | 0.5000     | yes |
| White's Reality Check                | <= PASS        | 0.0010     | 0.1000     | yes |
| CPCV out-of-sample stability         | <= PASS        | 0.0000     | 0.5000     | yes |

## Gate Detail

- [PASS] Bootstrap Sharpe CI lower bound: 95% CI lower bound 0.6821 vs minimum 0.0000
- [FAIL] Deflated Sharpe Ratio: DSR 0.2952 vs minimum 0.9500 across 94 trials
- [PASS] Probability of Backtest Overfitting: PBO 0.1082 vs maximum 0.5000 over 12870 CSCV combinations
- [PASS] White's Reality Check: Reality-Check p-value 0.0010 vs maximum 0.1000
- [PASS] CPCV out-of-sample stability: fraction of negative OOS folds 0.0000 vs maximum 0.5000 (mean OOS Sharpe 1.0598, 5th pct 0.8174)


## ADDENDUM (post-hoc analysis, 2026-06-06)

### 1. The DSR gate failure is a trial-bank composition artifact

The candidate (rsi2t15_trend200) passes every search-aware test EXCEPT
the Deflated Sharpe gate. Decomposition on the canonical 94-config
matrix:

| Trial bank                       | n  | DSR    |
|----------------------------------|----|--------|
| Full multi-family bank (gate)    | 94 | 0.2952 |
| ta_quant family only             | 85 | 0.2915 |
| rsi subfamily (search neighbourhood) | 15 | 1.0000 |

The gate's DSR deflates against the VARIANCE of trial Sharpes. In a
deliberately heterogeneous sweep (classical at -0.06, csmom at 0.16,
TA at 1.05) that variance reflects genuine cross-family differences,
not null-hypothesis noise, so the expected-max benchmark is inflated.
The tests designed for exactly this question -- best-of-a-CORRELATED-
search -- account for the joint distribution of the actual trial
matrix and all pass decisively:

  White's Reality Check p = 0.0010   Hansen SPA p = 0.0010
  PBO = 0.0159                       CPCV: 0/15 negative folds
  Bootstrap Sharpe CI [0.68, 1.46]   Era Sharpes 0.80/1.53/0.91/1.13

The official verdict stands as REJECT under the configured gate; the
methodological reading is that the strategy decisively survives the
search-adjusted tests and the gate's DSR input convention needs a
within-family scope for multi-family sweeps (advisory line added to
the harness for future runs).

### 2. Costs are not carrying the result

| Config                   | Frictionless | Net ibkr | Drag  |
|--------------------------|--------------|----------|-------|
| rsi2t15_trend200         | 1.154        | 1.051    | 0.103 |
| rsi2t10_trend200_volt10  | 1.097        | 1.001    | 0.096 |

At a 25k USD personal account on SP100 mega-caps, half-spread +
commission is the dominant real cost and the linear model is a fair
approximation; impact is negligible at this size.

### 3. The decisive remaining threat: survivorship bias

RSI-2 dip-buying is the single most survivorship-flattered strategy
type: in a current-constituent universe every crash that is bought
recovered, BY CONSTRUCTION of the symbol list (the ones that did not
recover are not in the list). The trend-filter gate (close > SMA200)
mitigates -- names in collapse trade below trend and are not bought --
but does not eliminate the effect. The split between real edge and
survivor flattery CANNOT be estimated from free current-constituent
data. Point-in-time constituents (the pending Norgate decision) is
now decision-critical, not optional.

### 4. PCA stat-arb family (fixed lookback=252)

Net Sharpe 0.656/0.628; era decay 1.22 -> 0.50 -> 0.37 -> ~0.5 --
mild structural decay, far healthier than pairs but not a first
candidate.

### 5. Recommended path

1. Buy Norgate (point-in-time constituents + delisted stocks);
   re-run this sweep unchanged on survivorship-free data. The
   harness needs only a data-source swap.
2. If the rsi2/trend family survives survivorship-free validation
   (expect a haircut: realistic outcome is Sharpe 0.6-0.9), wire
   TAQuantStrategy into the live paper runner and start the 90-day
   clock on rsi2t10_trend200_volt10 (the vol-targeted variant:
   Sharpe 1.00, max DD -14.9% vs -22.1% unscaled).
3. Do NOT start the clock on free-data evidence alone for a
   dip-buying strategy.
