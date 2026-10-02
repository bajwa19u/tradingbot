# ORB on stocks in play

IEX 1-minute bars, 252 sessions (2025-09-30 to 2026-10-02): train 151, validation 50, test 51. Pool 108 symbols (hand-assembled earlier: some survivorship bias). 0.05% slippage per side unless stated. Stages decided on train + validation; test run once at the end.

## 1. Baseline: the live rule on the static 10

| version | trades | win % | avg win R | avg loss R | expectancy R | PF | total R | max DD R | Sharpe | Sortino | avg hold min | median hold min | 95% CI expectancy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| static 10, train | 1398 | 39.7% | +1.07 | -0.94 | -0.142 | 0.75 | -198.3 | 199.9 | -4.28 | -8.51 | 201 | 175 | -0.20 to -0.09 |
| static 10, val | 444 | 36.3% | +1.14 | -0.91 | -0.166 | 0.71 | -73.5 | 75.0 | -5.32 | -10.34 | 199 | 144 | -0.27 to -0.06 |

## 2. Feature-by-feature research (staged; each stage starts from the rules adopted so far)

### Universe: stocks in play vs the static 10

Ranked at 09:35 by first-5-minute volume vs its 14-session average; price >= 5 and 14-day average dollar volume >= 50M. Nothing about past trade results is used.

| variant | verdict | train: n | win | avg R | PF | 95% CI | val: n | win | avg R | PF | 95% CI |
|---|---|---|---|---|---|---|---|---|---|---|---|
| current | incumbent | 1398 | 40% | -0.142 | 0.75 | -0.20 to -0.09 | 444 | 36% | -0.166 | 0.71 | -0.27 to -0.06 |
| top 10 by opening relative volume | ADOPT | 1326 | 43% | -0.065 | 0.87 | -0.12 to -0.01 | 441 | 41% | -0.043 | 0.91 | -0.14 to +0.06 |
| top 20 by opening relative volume | ADOPT | 2718 | 42% | -0.067 | 0.87 | -0.11 to -0.03 | 892 | 41% | -0.065 | 0.87 | -0.14 to +0.00 |
| top 30 by opening relative volume | ADOPT | 3951 | 42% | -0.071 | 0.86 | -0.10 to -0.04 | 1344 | 41% | -0.070 | 0.86 | -0.13 to -0.01 |

### OR width / daily ATR

Fixed buckets, not fitted percentiles.

| variant | verdict | train: n | win | avg R | PF | 95% CI | val: n | win | avg R | PF | 95% CI |
|---|---|---|---|---|---|---|---|---|---|---|---|
| current | incumbent | 1326 | 43% | -0.065 | 0.87 | -0.12 to -0.01 | 441 | 41% | -0.043 | 0.91 | -0.14 to +0.06 |
| 0-0.1 | too few validation trades (4) | 7 | 29% | -0.392 | 0.53 | -1.17 to +0.56 | 4 | 75% | +0.684 | 3.57 | +nan to +nan |
| 0.1-0.2 | too few validation trades (52) | 169 | 39% | -0.071 | 0.88 | -0.26 to +0.12 | 52 | 35% | -0.156 | 0.75 | -0.46 to +0.19 |
| 0.2-0.35 | no validation gain | 541 | 39% | -0.128 | 0.77 | -0.22 to -0.03 | 183 | 39% | -0.108 | 0.81 | -0.28 to +0.05 |
| 0.35-9e+09 | ADOPT | 609 | 48% | -0.004 | 0.99 | -0.08 to +0.07 | 202 | 45% | +0.030 | 1.08 | -0.09 to +0.17 |
| 0.1-0.35 | no validation gain | 710 | 39% | -0.114 | 0.80 | -0.20 to -0.03 | 235 | 38% | -0.118 | 0.79 | -0.27 to +0.04 |

### Market / VWAP confirmation

| variant | verdict | train: n | win | avg R | PF | 95% CI | val: n | win | avg R | PF | 95% CI |
|---|---|---|---|---|---|---|---|---|---|---|---|
| current | incumbent | 609 | 48% | -0.004 | 0.99 | -0.08 to +0.07 | 202 | 45% | +0.030 | 1.08 | -0.09 to +0.17 |
| B: stock VWAP only | no validation gain | 609 | 48% | -0.004 | 0.99 | -0.08 to +0.07 | 202 | 45% | +0.030 | 1.08 | -0.11 to +0.16 |
| C: SPY and QQQ | no validation gain | 498 | 47% | -0.008 | 0.98 | -0.09 to +0.08 | 163 | 45% | +0.016 | 1.04 | -0.13 to +0.15 |
| D: stock + SPY + QQQ | no validation gain | 498 | 47% | -0.008 | 0.98 | -0.09 to +0.07 | 163 | 45% | +0.016 | 1.04 | -0.12 to +0.15 |

### Breakout displacement (close past the level / OR width)

| variant | verdict | train: n | win | avg R | PF | 95% CI | val: n | win | avg R | PF | 95% CI |
|---|---|---|---|---|---|---|---|---|---|---|---|
| current | incumbent | 609 | 48% | -0.004 | 0.99 | -0.08 to +0.07 | 202 | 45% | +0.030 | 1.08 | -0.09 to +0.17 |
| >= 0.1 | no validation gain | 517 | 50% | +0.022 | 1.06 | -0.05 to +0.10 | 173 | 44% | +0.017 | 1.05 | -0.11 to +0.15 |
| >= 0.25 | no validation gain | 399 | 49% | -0.001 | 1.00 | -0.09 to +0.08 | 126 | 42% | +0.010 | 1.03 | -0.13 to +0.16 |
| >= 0.5 | no validation gain | 228 | 50% | +0.015 | 1.05 | -0.07 to +0.10 | 71 | 46% | +0.003 | 1.01 | -0.16 to +0.19 |

### Breakout-minute relative volume (vs that minute's 14-day average)

| variant | verdict | train: n | win | avg R | PF | 95% CI | val: n | win | avg R | PF | 95% CI |
|---|---|---|---|---|---|---|---|---|---|---|---|
| current | incumbent | 609 | 48% | -0.004 | 0.99 | -0.08 to +0.07 | 202 | 45% | +0.030 | 1.08 | -0.09 to +0.17 |
| >= 1.25x | no validation gain | 558 | 48% | -0.014 | 0.97 | -0.09 to +0.06 | 176 | 44% | +0.036 | 1.10 | -0.10 to +0.17 |
| >= 1.5x | no validation gain | 530 | 48% | -0.012 | 0.97 | -0.09 to +0.07 | 167 | 44% | +0.026 | 1.07 | -0.12 to +0.17 |
| >= 2.0x | no validation gain | 478 | 49% | -0.015 | 0.96 | -0.09 to +0.06 | 145 | 45% | +0.026 | 1.07 | -0.13 to +0.18 |

### Direction

| variant | verdict | train: n | win | avg R | PF | 95% CI | val: n | win | avg R | PF | 95% CI |
|---|---|---|---|---|---|---|---|---|---|---|---|
| current | incumbent | 609 | 48% | -0.004 | 0.99 | -0.08 to +0.07 | 202 | 45% | +0.030 | 1.08 | -0.09 to +0.17 |
| long only | worse on train | 336 | 46% | -0.059 | 0.86 | -0.16 to +0.04 | 111 | 48% | +0.083 | 1.22 | -0.09 to +0.27 |
| short only | no validation gain | 295 | 51% | +0.048 | 1.13 | -0.05 to +0.16 | 102 | 41% | -0.051 | 0.87 | -0.22 to +0.13 |

### Extension (|close - VWAP| / daily ATR)

| variant | verdict | train: n | win | avg R | PF | 95% CI | val: n | win | avg R | PF | 95% CI |
|---|---|---|---|---|---|---|---|---|---|---|---|
| current | incumbent | 609 | 48% | -0.004 | 0.99 | -0.08 to +0.07 | 202 | 45% | +0.030 | 1.08 | -0.09 to +0.17 |
| <= 0.25 | no validation gain | 525 | 48% | -0.014 | 0.96 | -0.09 to +0.06 | 180 | 47% | +0.036 | 1.09 | -0.11 to +0.17 |
| <= 0.5 | no validation gain | 602 | 48% | -0.010 | 0.98 | -0.09 to +0.07 | 201 | 45% | +0.029 | 1.08 | -0.10 to +0.16 |
| <= 1.0 | no validation gain | 609 | 48% | -0.003 | 0.99 | -0.07 to +0.07 | 201 | 45% | +0.031 | 1.08 | -0.10 to +0.17 |

### Entry window

| variant | verdict | train: n | win | avg R | PF | 95% CI | val: n | win | avg R | PF | 95% CI |
|---|---|---|---|---|---|---|---|---|---|---|---|
| current | incumbent | 609 | 48% | -0.004 | 0.99 | -0.08 to +0.07 | 202 | 45% | +0.030 | 1.08 | -0.09 to +0.17 |
| until 9:40 | no validation gain | 379 | 50% | +0.015 | 1.04 | -0.08 to +0.11 | 135 | 44% | +0.004 | 1.01 | -0.15 to +0.16 |
| until 9:45 | no validation gain | 463 | 49% | +0.021 | 1.05 | -0.07 to +0.10 | 156 | 44% | +0.020 | 1.05 | -0.12 to +0.16 |
| until 9:50 | no validation gain | 541 | 49% | +0.015 | 1.04 | -0.06 to +0.09 | 172 | 45% | +0.022 | 1.06 | -0.12 to +0.16 |
| until 10:15 | no validation gain | 654 | 49% | +0.009 | 1.02 | -0.06 to +0.08 | 215 | 45% | +0.017 | 1.04 | -0.12 to +0.14 |
| until 10:30 | no validation gain | 679 | 49% | +0.004 | 1.01 | -0.07 to +0.07 | 223 | 45% | +0.014 | 1.04 | -0.11 to +0.14 |

### Stop (live: D, session extreme)

| variant | verdict | train: n | win | avg R | PF | 95% CI | val: n | win | avg R | PF | 95% CI |
|---|---|---|---|---|---|---|---|---|---|---|---|
| current | incumbent | 609 | 48% | -0.004 | 0.99 | -0.08 to +0.07 | 202 | 45% | +0.030 | 1.08 | -0.09 to +0.17 |
| A: opposite side of OR | no validation gain | 609 | 48% | -0.004 | 0.99 | -0.08 to +0.07 | 202 | 45% | +0.040 | 1.10 | -0.10 to +0.18 |
| B: level - 0.1 ATR | no validation gain | 610 | 32% | -0.160 | 0.79 | -0.26 to -0.05 | 202 | 32% | -0.175 | 0.77 | -0.36 to +0.03 |
| C: 5-minute swing - 0.02 ATR | no validation gain | 610 | 41% | -0.068 | 0.88 | -0.17 to +0.03 | 202 | 38% | -0.082 | 0.86 | -0.26 to +0.09 |

### Target

| variant | verdict | train: n | win | avg R | PF | 95% CI | val: n | win | avg R | PF | 95% CI |
|---|---|---|---|---|---|---|---|---|---|---|---|
| current | incumbent | 609 | 48% | -0.004 | 0.99 | -0.08 to +0.07 | 202 | 45% | +0.030 | 1.08 | -0.09 to +0.17 |
| 1.0R | no validation gain | 609 | 51% | -0.015 | 0.96 | -0.08 to +0.05 | 202 | 47% | -0.013 | 0.97 | -0.12 to +0.10 |
| 1.5R | no validation gain | 609 | 49% | -0.014 | 0.96 | -0.08 to +0.06 | 202 | 45% | +0.007 | 1.02 | -0.13 to +0.14 |
| 2.5R | no validation gain | 609 | 48% | -0.007 | 0.98 | -0.08 to +0.07 | 202 | 45% | +0.039 | 1.10 | -0.10 to +0.17 |
| 3.0R | no validation gain | 609 | 48% | -0.010 | 0.97 | -0.09 to +0.06 | 202 | 45% | +0.051 | 1.13 | -0.09 to +0.19 |

### Trade management

| variant | verdict | train: n | win | avg R | PF | 95% CI | val: n | win | avg R | PF | 95% CI |
|---|---|---|---|---|---|---|---|---|---|---|---|
| current | incumbent | 609 | 48% | -0.004 | 0.99 | -0.08 to +0.07 | 202 | 45% | +0.030 | 1.08 | -0.09 to +0.17 |
| half at 1R + runner to 3R | no validation gain | 609 | 51% | -0.009 | 0.98 | -0.08 to +0.06 | 202 | 47% | +0.018 | 1.05 | -0.10 to +0.13 |
| trail 1R behind the best price after 1R | no validation gain | 609 | 50% | -0.006 | 0.98 | -0.08 to +0.06 | 202 | 47% | +0.020 | 1.05 | -0.12 to +0.15 |
| trail 1R behind the best close after 1R | no validation gain | 609 | 50% | -0.011 | 0.97 | -0.08 to +0.06 | 202 | 47% | +0.059 | 1.16 | -0.08 to +0.21 |

### Correlated signals (max same-side signals in 10 min)

| variant | verdict | train: n | win | avg R | PF | 95% CI | val: n | win | avg R | PF | 95% CI |
|---|---|---|---|---|---|---|---|---|---|---|---|
| current | incumbent | 609 | 48% | -0.004 | 0.99 | -0.08 to +0.07 | 202 | 45% | +0.030 | 1.08 | -0.09 to +0.17 |
| max 1 | no validation gain | 322 | 51% | +0.032 | 1.09 | -0.07 to +0.14 | 114 | 44% | +0.006 | 1.01 | -0.17 to +0.18 |
| max 2 | no validation gain | 486 | 48% | -0.016 | 0.96 | -0.10 to +0.07 | 167 | 46% | +0.050 | 1.13 | -0.09 to +0.20 |
| max 3 | no validation gain | 562 | 49% | +0.018 | 1.05 | -0.06 to +0.10 | 193 | 46% | +0.024 | 1.06 | -0.11 to +0.16 |

### Overnight gap direction (follow-up)

| variant | verdict | train: n | win | avg R | PF | 95% CI | val: n | win | avg R | PF | 95% CI |
|---|---|---|---|---|---|---|---|---|---|---|---|
| current | incumbent | 609 | 48% | -0.004 | 0.99 | -0.08 to +0.07 | 202 | 45% | +0.030 | 1.08 | -0.09 to +0.17 |
| only breaks with the gap | no validation gain | 341 | 46% | -0.062 | 0.85 | -0.16 to +0.03 | 117 | 44% | +0.027 | 1.07 | -0.12 to +0.21 |

### Crowd, prior-only (follow-up)

| variant | verdict | train: n | win | avg R | PF | 95% CI | val: n | win | avg R | PF | 95% CI |
|---|---|---|---|---|---|---|---|---|---|---|---|
| current | incumbent | 609 | 48% | -0.004 | 0.99 | -0.08 to +0.07 | 202 | 45% | +0.030 | 1.08 | -0.09 to +0.17 |
| 5+ same-side signals in the last 10 min | too few validation trades (3) | 17 | 24% | -0.329 | 0.39 | -0.70 to +0.11 | 3 | 33% | +0.315 | 1.91 | +nan to +nan |
| gap AND 5+ crowd | too few validation trades (1) | 5 | 20% | -0.621 | 0.00 | -0.96 to -0.27 | 1 | 100% | +1.985 | inf | +nan to +nan |

## 3. Decisions

- Universe: stocks in play vs the static 10: **top 10 by opening relative volume** (validation expectancy -0.166R -> -0.043R)
- OR width / daily ATR: **0.35-9e+09** (validation expectancy -0.043R -> +0.030R)
- Market / VWAP confirmation: no change
- Breakout displacement (close past the level / OR width): no change
- Breakout-minute relative volume (vs that minute's 14-day average): no change
- Direction: no change
- Extension (|close - VWAP| / daily ATR): no change
- Entry window: no change
- Stop (live: D, session extreme): no change
- Target: no change
- Trade management: no change
- Correlated signals (max same-side signals in 10 min): no change
- Overnight gap direction (follow-up): no change
- Crowd, prior-only (follow-up): no change

Final candidate: `P(universe='top10', window_end=30, orw=(0.35, 9000000000.0), market='none', disp=0.0, bvol=0.0, sides='both', ext=9000000000.0, stop='D', target=2.0, manage='fixed', cluster_max=99, slip=0.0005, delay=0, gap='any', crowd=0)`

## 4. Train, validation and the untouched test

| version | trades | win % | avg win R | avg loss R | expectancy R | PF | total R | max DD R | Sharpe | Sortino | avg hold min | median hold min | 95% CI expectancy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| baseline (static 10, live rule) - train | 1398 | 39.7% | +1.07 | -0.94 | -0.142 | 0.75 | -198.3 | 199.9 | -4.28 | -8.51 | 201 | 175 | -0.20 to -0.09 |
| baseline (static 10, live rule) - val | 444 | 36.3% | +1.14 | -0.91 | -0.166 | 0.71 | -73.5 | 75.0 | -5.32 | -10.34 | 199 | 144 | -0.27 to -0.06 |
| baseline (static 10, live rule) - test | 442 | 43.2% | +0.92 | -0.87 | -0.094 | 0.81 | -41.7 | 64.1 | -3.51 | -6.02 | 234 | 360 | -0.18 to +0.00 |
| candidate - train | 609 | 48.4% | +0.81 | -0.76 | -0.004 | 0.99 | -2.3 | 34.0 | -0.11 | -0.21 | 282 | 369 | -0.08 to +0.08 |
| candidate - val | 202 | 45.0% | +0.91 | -0.69 | +0.030 | 1.08 | +6.0 | 20.2 | 0.99 | 1.73 | 276 | 369 | -0.11 to +0.16 |
| candidate - test | 218 | 54.6% | +0.74 | -0.57 | +0.144 | 1.55 | +31.4 | 5.3 | 7.11 | 16.04 | 323 | 375 | +0.04 to +0.25 |

Test-period verdict: candidate expectancy +0.144R (95% CI +0.04 to +0.25) on 218 trades; positive and its interval excludes zero.

## 4b. The autopsy's filters, re-run the production way (diagnostic)

Live rule, 5-minute range. Not used to choose anything; shows whether the autopsy's result carries over.

| variant | verdict | train: n | win | avg R | PF | 95% CI | val: n | win | avg R | PF | 95% CI | test: n | win | avg R | PF | 95% CI |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| static 10, no filter |  | 1398 | 40% | -0.142 | 0.75 | -0.20 to -0.09 | 444 | 36% | -0.166 | 0.71 | -0.27 to -0.06 | 442 | 43% | -0.094 | 0.81 | -0.19 to +0.00 |
| static 10, with the gap |  | 807 | 39% | -0.162 | 0.72 | -0.23 to -0.09 | 229 | 36% | -0.184 | 0.69 | -0.32 to -0.05 | 243 | 44% | -0.063 | 0.87 | -0.20 to +0.09 |
| static 10, crowd 5+ (prior-only) |  | 493 | 41% | -0.105 | 0.81 | -0.20 to -0.01 | 128 | 27% | -0.359 | 0.48 | -0.53 to -0.16 | 115 | 53% | +0.113 | 1.29 | -0.07 to +0.30 |
| static 10, gap AND crowd 5+ |  | 168 | 40% | -0.106 | 0.81 | -0.28 to +0.06 | 26 | 27% | -0.451 | 0.30 | -0.74 to -0.11 | 37 | 62% | +0.388 | 2.29 | +0.06 to +0.72 |
| top 10 in play, with the gap |  | 777 | 44% | -0.059 | 0.88 | -0.13 to +0.02 | 260 | 43% | -0.017 | 0.96 | -0.14 to +0.11 | 238 | 47% | +0.040 | 1.10 | -0.08 to +0.17 |
| final candidate, with the gap |  | 341 | 46% | -0.062 | 0.85 | -0.16 to +0.04 | 117 | 44% | +0.027 | 1.07 | -0.14 to +0.20 | 113 | 55% | +0.128 | 1.47 | -0.02 to +0.29 |

## 4c. Slippage by period (final candidate)

| slippage per side | train avg R | train PF | val avg R | val PF | test avg R | test PF | test win % |
|---|---|---|---|---|---|---|---|
| 0.05% | -0.004 | 0.99 | +0.030 | 1.08 | +0.144 | 1.55 | 54.6% |
| 0.10% | -0.060 | 0.86 | -0.021 | 0.95 | +0.083 | 1.30 | 52.3% |
| 0.15% | -0.117 | 0.73 | -0.073 | 0.83 | +0.026 | 1.09 | 49.5% |

### Go-live gate (fixed before the run)

- PASS: test expectancy > 0 at 0.05%
- PASS: test 95% interval above zero at 0.05%
- PASS: test expectancy > 0 at 0.10%
- FAIL: validation expectancy > 0 at 0.10%
- PASS: test > 0 without its best 3 stocks
- PASS: beats the live rule on train, validation and test

**Gate: FAILED.** 0.15% is reported, not gated: it is the stress case.

## 5. Execution sensitivity (candidate, validation + test)

| slippage per side | delay | trades | expectancy R | PF |
|---|---|---|---|---|
| 0.02% | breakout close | 420 | +0.124 | 1.40 |
| 0.02% | next minute open | 420 | +0.126 | 1.41 |
| 0.05% | breakout close | 420 | +0.089 | 1.28 |
| 0.05% | next minute open | 420 | +0.081 | 1.25 |
| 0.10% | breakout close | 420 | +0.033 | 1.10 |
| 0.10% | next minute open | 420 | +0.028 | 1.08 |
| 0.15% | breakout close | 420 | -0.021 | 0.94 |
| 0.15% | next minute open | 420 | -0.024 | 0.93 |

## 6. Drawdown (candidate, all periods)

Max drawdown 34.0R; longest losing streak 8 trades.

## 7. Breakdowns (candidate, train + validation)

#### Long vs short

| bucket | trades | win % | expectancy R | PF |
|---|---|---|---|---|
| long | 430 | 46 | -0.025 | 0.94 |
| short | 381 | 49 | +0.038 | 1.10 |

#### Breakout minute (5 = 09:35)

| bucket | trades | win % | expectancy R | PF |
|---|---|---|---|---|
| [5, 10) | 514 | 48 | +0.012 | 1.03 |
| [10, 15) | 105 | 46 | +0.064 | 1.17 |
| [15, 20) | 94 | 48 | -0.009 | 0.98 |
| [20, 30) | 98 | 45 | -0.084 | 0.79 |

#### OR width / ATR

| bucket | trades | win % | expectancy R | PF |
|---|---|---|---|---|
| [0.35, 99.0) | 811 | 48 | +0.005 | 1.01 |

#### Opening relative volume

| bucket | trades | win % | expectancy R | PF |
|---|---|---|---|---|
| [0.0, 1.0) | 43 | 40 | -0.146 | 0.72 |
| [1.0, 1.5) | 206 | 50 | +0.026 | 1.07 |
| [1.5, 2.0) | 206 | 50 | +0.055 | 1.15 |
| [2.0, 3.0) | 203 | 47 | +0.007 | 1.02 |
| [3.0, 999.0) | 153 | 44 | -0.052 | 0.87 |

#### Breakout-minute relative volume

| bucket | trades | win % | expectancy R | PF |
|---|---|---|---|---|
| [0.0, 1.0) | 225 | 50 | -0.006 | 0.98 |
| [1.0, 1.5) | 168 | 46 | -0.016 | 0.96 |
| [1.5, 2.0) | 122 | 43 | -0.040 | 0.91 |
| [2.0, 3.0) | 143 | 45 | +0.026 | 1.08 |
| [3.0, 999.0) | 153 | 51 | +0.058 | 1.16 |

#### Same-side signals in the prior 10 min

| bucket | trades | win % | expectancy R | PF |
|---|---|---|---|---|
| [0, 1) | 495 | 49 | +0.040 | 1.11 |
| [1, 2) | 180 | 43 | -0.093 | 0.80 |
| [2, 4) | 123 | 47 | -0.002 | 1.00 |
| [4, 99) | 13 | 38 | +0.075 | 1.21 |

#### Market regime at the signal

| bucket | trades | win % | expectancy R | PF |
|---|---|---|---|---|
| SPY above VWAP | 410 | 50 | +0.024 | 1.06 |
| SPY below VWAP | 401 | 45 | -0.015 | 0.96 |

#### SPY opening volatility (SPY OR width / ATR)

| bucket | trades | win % | expectancy R | PF |
|---|---|---|---|---|
| [0.0, 0.1) | 114 | 46 | -0.057 | 0.85 |
| [0.1, 0.2) | 454 | 49 | +0.037 | 1.09 |
| [0.2, 99.0) | 243 | 45 | -0.027 | 0.93 |

#### Setup-quality score (0-7; research only)

| bucket | trades | win % | expectancy R | PF |
|---|---|---|---|---|
| 2 | 32 | 41 | -0.135 | 0.71 |
| 3 | 125 | 58 | +0.099 | 1.33 |
| 4 | 242 | 46 | -0.014 | 0.97 |
| 5 | 275 | 46 | -0.004 | 0.99 |
| 6 | 133 | 45 | +0.001 | 1.00 |
| 7 | 4 | 50 | -0.020 | 0.95 |

#### By stock (train + validation; 10 worst and 10 best by total R)

| stock | trades | expectancy R | total R |
|---|---|---|---|
| UNH | 19 | -0.439 | -8.3 |
| SNOW | 7 | -0.795 | -5.6 |
| GE | 18 | -0.267 | -4.8 |
| SHOP | 10 | -0.441 | -4.4 |
| BAC | 28 | -0.150 | -4.2 |
| FCX | 11 | -0.380 | -4.2 |
| JNJ | 24 | -0.151 | -3.6 |
| NKE | 13 | -0.257 | -3.3 |
| PLTR | 31 | -0.096 | -3.0 |
| AAPL | 29 | -0.084 | -2.4 |
| LIN | 4 | +0.523 | +2.1 |
| TXN | 8 | +0.331 | +2.6 |
| QCOM | 8 | +0.351 | +2.8 |
| CSCO | 19 | +0.165 | +3.1 |
| T | 19 | +0.174 | +3.3 |
| WMT | 25 | +0.148 | +3.7 |
| ORCL | 18 | +0.349 | +6.3 |
| HOOD | 24 | +0.277 | +6.6 |
| KO | 21 | +0.451 | +9.5 |
| INTC | 37 | +0.377 | +13.9 |

## 8. Source of the result (diagnostics, run after the test; not used to choose rules)

Variants tried in the staged search: 43. Noise floor sqrt(2 ln N) = 2.74 standard errors.

- candidate train: t = -0.10 (below the noise floor)
- candidate val: t = +0.44 (below the noise floor)
- candidate test: t = +2.56 (below the noise floor)

### Month by month (all periods)

| month / version | trades | win % | avg % per trade (price) | expectancy R | PF |
|---|---|---|---|---|---|
| 2025-09 static 10 | 9 | 11% | -0.371% | -0.643 | 0.25 |
| 2025-09 candidate | 3 | 33% | -0.634% | -0.455 | 0.34 |
| 2025-10 static 10 | 206 | 31% | -0.204% | -0.328 | 0.51 |
| 2025-10 candidate | 94 | 40% | -0.198% | -0.149 | 0.69 |
| 2025-11 static 10 | 174 | 39% | -0.143% | -0.096 | 0.84 |
| 2025-11 candidate | 67 | 42% | -0.486% | -0.167 | 0.67 |
| 2025-12 static 10 | 197 | 37% | -0.154% | -0.199 | 0.64 |
| 2025-12 candidate | 52 | 52% | +0.251% | +0.167 | 1.51 |
| 2026-01 static 10 | 190 | 42% | +0.014% | -0.079 | 0.85 |
| 2026-01 candidate | 114 | 52% | +0.242% | +0.038 | 1.10 |
| 2026-02 static 10 | 177 | 53% | +0.213% | +0.159 | 1.36 |
| 2026-02 candidate | 77 | 52% | +0.354% | +0.136 | 1.39 |
| 2026-03 static 10 | 201 | 41% | -0.046% | -0.136 | 0.77 |
| 2026-03 candidate | 75 | 57% | +0.115% | +0.100 | 1.30 |
| 2026-04 static 10 | 186 | 37% | -0.220% | -0.269 | 0.55 |
| 2026-04 candidate | 95 | 47% | -0.164% | -0.030 | 0.92 |
| 2026-05 static 10 | 184 | 36% | -0.208% | -0.229 | 0.61 |
| 2026-05 candidate | 96 | 50% | +0.376% | +0.141 | 1.39 |
| 2026-06 static 10 | 180 | 39% | -0.114% | -0.062 | 0.89 |
| 2026-06 candidate | 83 | 43% | -0.156% | -0.061 | 0.85 |
| 2026-07 static 10 | 202 | 39% | -0.022% | -0.111 | 0.80 |
| 2026-07 candidate | 79 | 46% | -0.036% | -0.032 | 0.90 |
| 2026-08 static 10 | 179 | 50% | +0.115% | +0.020 | 1.05 |
| 2026-08 candidate | 84 | 56% | +0.400% | +0.210 | 2.08 |
| 2026-09 static 10 | 181 | 36% | -0.136% | -0.217 | 0.60 |
| 2026-09 candidate | 101 | 52% | +0.277% | +0.104 | 1.32 |
| 2026-10 static 10 | 18 | 33% | -0.221% | -0.471 | 0.30 |
| 2026-10 candidate | 9 | 44% | +0.121% | -0.068 | 0.88 |

### How trades end

| version | period | stop % | target % | bell % | avg R at stop | avg R at target | avg R at bell |
|---|---|---|---|---|---|---|---|
| static 10 | train | 48 | 13 | 39 | -1.09 | +1.92 | +0.32 |
| static 10 | val | 49 | 14 | 38 | -1.07 | +1.94 | +0.26 |
| static 10 | test | 39 | 12 | 50 | -1.09 | +1.92 | +0.22 |
| candidate | train | 30 | 6 | 63 | -1.04 | +1.96 | +0.29 |
| candidate | val | 29 | 9 | 62 | -1.04 | +1.97 | +0.25 |
| candidate | test | 16 | 6 | 78 | -1.04 | +1.97 | +0.26 |

### OR width: real effect or just smaller costs in R?

Top 10 by opening volume, no width filter, all periods.

| OR width / ATR | trades | median stop distance % | gross R (no slippage) | net R | win % gross |
|---|---|---|---|---|---|
| 0-0.2 | 290 | 0.85% | +0.110 | -0.060 | 43% |
| 0.2-0.35 | 888 | 1.08% | -0.024 | -0.125 | 41% |
| 0.35-0.5 | 587 | 1.55% | +0.073 | +0.002 | 49% |
| 0.5-0.75 | 305 | 2.07% | +0.172 | +0.111 | 53% |
| 0.75-9e+09 | 137 | 3.11% | +0.043 | +0.002 | 55% |

### Neighbours of the chosen settings (plateau check, every period)

| universe | min OR width / ATR | train avg R | val avg R | test avg R | test trades |
|---|---|---|---|---|---|
| top5 | 0.25 | -0.060 | -0.020 | +0.072 | 166 |
| top5 | 0.30 | -0.041 | +0.015 | +0.142 | 144 |
| top5 | 0.35 | -0.030 | +0.015 | +0.154 | 119 |
| top5 | 0.40 | -0.033 | -0.039 | +0.231 | 99 |
| top5 | 0.50 | +0.045 | -0.089 | +0.289 | 68 |
| top10 | 0.25 | -0.026 | -0.037 | +0.043 | 338 |
| top10 | 0.30 | -0.018 | +0.010 | +0.063 | 276 |
| top10 | 0.35 | -0.004 | +0.030 | +0.144 | 218 |
| top10 | 0.40 | +0.002 | +0.049 | +0.210 | 178 |
| top10 | 0.50 | +0.067 | +0.016 | +0.150 | 104 |
| top20 | 0.25 | -0.023 | -0.043 | -0.002 | 626 |
| top20 | 0.30 | -0.012 | -0.001 | +0.020 | 497 |
| top20 | 0.35 | +0.019 | -0.002 | +0.110 | 373 |
| top20 | 0.40 | +0.021 | +0.024 | +0.151 | 280 |
| top20 | 0.50 | +0.062 | +0.049 | +0.084 | 146 |

### How concentrated is the test result?

- Test total +31.4R over 50 days and 218 trades.
- Without the best 2 days: +0.113R per trade.
- Without the best 5 trades: +0.101R per trade.
- Best 3 stocks (CRM, TSLA, CRWD) made +18.1R; without them +0.071R per trade.
- Winning days 66% of 50.

#### Test by side

| side | trades | win % | avg % per trade (price) | expectancy R | PF |
|---|---|---|---|---|---|
| long | 116 | 53% | +0.335% | +0.127 | 1.50 |
| short | 102 | 57% | +0.350% | +0.163 | 1.61 |

