# Break & Retest V1 — baseline backtest

SIP 1-minute bars, 252 sessions (2025-10-07 to 2026-10-07), 13 symbols. In-sample 151 sessions (2025-10-07 to 2026-05-13), out-of-sample 101 (2026-05-14 to 2026-10-07). Rules exactly as in `br_config.yaml` — **nothing tuned**. $1,000 risk per trade, 0.025% slippage per side, stop 0.5% beyond the level, target 2.0R, out at 15:55 if neither. Headline = the combined variant (every setup timeframe, first confirmation wins), which is what the live bot runs.

## Verdict

- All sessions: **LOSING - does not work as specified**
- In-sample: **LOSING - does not work as specified**
- Out-of-sample: **LOSING - does not work as specified**

| period | trades | won | lost | win % | profit | avg R | median R | total R | PF | max DD | avg min |
|---|---|---|---|---|---|---|---|---|---|---|---|
| all | 5403 | 1971 | 3432 | 36.5% | -$178,811 | -0.033 | -1.02 | -178.8 | 0.95 | -$203,296 | 101 |
| in-sample | 3229 | 1198 | 2031 | 37.1% | -$42,483 | -0.013 | -1.03 | -42.5 | 0.98 | -$105,562 | 100 |
| out-of-sample | 2174 | 773 | 1401 | 35.6% | -$136,328 | -0.063 | -1.02 | -136.3 | 0.90 | -$157,406 | 103 |

Average R 95% bootstrap interval, all sessions: -0.069 to +0.004. Expectancy -$33 per trade.

## Setup funnel (combined)

| stage | count |
|---|---|
| breakouts (close beyond a level) | 35034 |
| ... of which retested | 27674 |
| ... of which confirmed | 18507 |
| ended as `failed_breakout` | 8756 |
| ended as `retest_timeout` | 3140 |
| ended as `window_closed` | 883 |
| ended as `confirm_timeout` | 44 |

| complete setups not taken, by rule | count |
|---|---|
| `position_open` | 9290 |
| `max_signals_per_day` | 4205 |
| `inactive_level` | 1552 |
| `gap_beyond_level` | 1274 |

## By setup timeframe

Each row is the same rules run on one bar size alone; the combined row is the headline.

| variant / period | trades | won | lost | win % | profit | avg R | median R | total R | PF | max DD | avg min |
|---|---|---|---|---|---|---|---|---|---|---|---|
| combined (1m+3m+5m, live) · in-sample | 3229 | 1198 | 2031 | 37.1% | -$42,483 | -0.013 | -1.03 | -42.5 | 0.98 | -$105,562 | 100 |
| combined (1m+3m+5m, live) · out-of-sample | 2174 | 773 | 1401 | 35.6% | -$136,328 | -0.063 | -1.02 | -136.3 | 0.90 | -$157,406 | 103 |
| 1m only · in-sample | 3223 | 1187 | 2036 | 36.8% | -$65,022 | -0.020 | -1.03 | -65.0 | 0.97 | -$121,844 | 99 |
| 1m only · out-of-sample | 2170 | 766 | 1404 | 35.3% | -$146,496 | -0.068 | -1.03 | -146.5 | 0.89 | -$158,512 | 102 |
| 3m only · in-sample | 2330 | 897 | 1433 | 38.5% | -$44,478 | -0.019 | -1.02 | -44.5 | 0.97 | -$76,265 | 135 |
| 3m only · out-of-sample | 1623 | 617 | 1006 | 38.0% | -$79,997 | -0.049 | -1.02 | -80.0 | 0.92 | -$118,430 | 138 |
| 5m only · in-sample | 1678 | 679 | 999 | 40.5% | $3,968 | +0.002 | -0.75 | +4.0 | 1.00 | -$58,191 | 157 |
| 5m only · out-of-sample | 1157 | 459 | 698 | 39.7% | -$31,959 | -0.028 | -0.73 | -32.0 | 0.95 | -$82,444 | 160 |

In the combined run, which bar size found the trade first:

| tf (min) | trades | won | lost | win % | profit | avg R | median R | total R | PF | max DD | avg min |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 5270 | 1910 | 3360 | 36.2% | -$212,654 | -0.040 | -1.03 | -212.7 | 0.94 | -$235,832 | 102 |
| 3 | 99 | 42 | 57 | 42.4% | $16,288 | +0.165 | -0.71 | +16.3 | 1.30 | -$15,726 | 105 |
| 5 | 34 | 19 | 15 | 55.9% | $17,554 | +0.516 | +0.42 | +17.6 | 2.14 | -$4,560 | 78 |

## By ticker

| symbol | trades | won | lost | win % | profit | avg R | median R | total R | PF | max DD | avg min |
|---|---|---|---|---|---|---|---|---|---|---|---|
| SPY | 283 | 132 | 151 | 46.6% | -$1,245 | -0.004 | -0.09 | -1.2 | 0.99 | -$18,485 | 284 |
| QQQ | 318 | 143 | 175 | 45.0% | -$9,187 | -0.029 | -0.22 | -9.2 | 0.94 | -$25,125 | 232 |
| AAPL | 361 | 131 | 230 | 36.3% | -$36,957 | -0.102 | -1.03 | -37.0 | 0.82 | -$46,143 | 178 |
| TSLA | 438 | 154 | 284 | 35.2% | -$25,311 | -0.058 | -1.03 | -25.3 | 0.91 | -$31,567 | 88 |
| AMD | 469 | 152 | 317 | 32.4% | -$39,308 | -0.084 | -1.03 | -39.3 | 0.88 | -$67,971 | 57 |
| NVDA | 410 | 159 | 251 | 38.8% | -$830 | -0.002 | -1.03 | -0.8 | 1.00 | -$14,992 | 113 |
| MU | 477 | 153 | 324 | 32.1% | -$41,632 | -0.087 | -1.03 | -41.6 | 0.87 | -$56,910 | 41 |
| GOOGL | 387 | 146 | 241 | 37.7% | -$19,217 | -0.050 | -1.03 | -19.2 | 0.92 | -$24,188 | 140 |
| AMZN | 382 | 145 | 237 | 38.0% | -$2,414 | -0.006 | -1.02 | -2.4 | 0.99 | -$20,120 | 153 |
| HOOD | 465 | 159 | 306 | 34.2% | -$10,169 | -0.022 | -1.03 | -10.2 | 0.97 | -$25,282 | 49 |
| SHOP | 452 | 164 | 288 | 36.3% | $1,860 | +0.004 | -1.03 | +1.9 | 1.01 | -$43,821 | 70 |
| COIN | 479 | 160 | 319 | 33.4% | -$16,321 | -0.034 | -1.03 | -16.3 | 0.95 | -$39,372 | 39 |
| SNDK | 482 | 173 | 309 | 35.9% | $21,920 | +0.045 | -1.02 | +21.9 | 1.07 | -$30,052 | 28 |

## By setup (level broken)

| level | trades | won | lost | win % | profit | avg R | median R | total R | PF | max DD | avg min |
|---|---|---|---|---|---|---|---|---|---|---|---|
| pdh | 414 | 157 | 257 | 37.9% | -$12,605 | -0.030 | -1.02 | -12.6 | 0.95 | -$32,154 | 126 |
| pdl | 386 | 161 | 225 | 41.7% | $25,342 | +0.066 | -1.02 | +25.3 | 1.11 | -$18,273 | 113 |
| pmh | 372 | 141 | 231 | 37.9% | -$7,813 | -0.021 | -1.02 | -7.8 | 0.96 | -$36,020 | 124 |
| pml | 367 | 133 | 234 | 36.2% | -$1,535 | -0.004 | -1.02 | -1.5 | 0.99 | -$22,430 | 99 |
| pdc | 783 | 292 | 491 | 37.3% | -$18,678 | -0.024 | -1.02 | -18.7 | 0.96 | -$34,545 | 98 |
| swing_high | 1564 | 545 | 1019 | 34.8% | -$126,505 | -0.081 | -1.03 | -126.5 | 0.87 | -$137,099 | 102 |
| swing_low | 1517 | 542 | 975 | 35.7% | -$37,017 | -0.024 | -1.03 | -37.0 | 0.96 | -$93,805 | 88 |

### By level and period

| level · period | trades | won | lost | win % | profit | avg R | median R | total R | PF | max DD | avg min |
|---|---|---|---|---|---|---|---|---|---|---|---|
| pdc · in-sample | 444 | 171 | 273 | 38.5% | $9,514 | +0.021 | -1.02 | +9.5 | 1.04 | -$16,988 | 101 |
| pdc · out-of-sample | 339 | 121 | 218 | 35.7% | -$28,192 | -0.083 | -1.02 | -28.2 | 0.87 | -$33,588 | 95 |
| pdh · in-sample | 254 | 100 | 154 | 39.4% | -$472 | -0.002 | -1.02 | -0.5 | 1.00 | -$29,211 | 129 |
| pdh · out-of-sample | 160 | 57 | 103 | 35.6% | -$12,133 | -0.076 | -1.02 | -12.1 | 0.88 | -$17,554 | 122 |
| pdl · in-sample | 239 | 101 | 138 | 42.3% | $29,312 | +0.123 | -1.02 | +29.3 | 1.22 | -$11,383 | 108 |
| pdl · out-of-sample | 147 | 60 | 87 | 40.8% | -$3,970 | -0.027 | -1.02 | -4.0 | 0.95 | -$18,273 | 122 |
| pmh · in-sample | 216 | 80 | 136 | 37.0% | -$13,622 | -0.063 | -1.02 | -13.6 | 0.90 | -$36,020 | 124 |
| pmh · out-of-sample | 156 | 61 | 95 | 39.1% | $5,809 | +0.037 | -1.02 | +5.8 | 1.07 | -$13,774 | 123 |
| pml · in-sample | 220 | 85 | 135 | 38.6% | $10,090 | +0.046 | -1.02 | +10.1 | 1.08 | -$16,697 | 104 |
| pml · out-of-sample | 147 | 48 | 99 | 32.7% | -$11,625 | -0.079 | -1.02 | -11.6 | 0.88 | -$22,430 | 91 |
| swing_high · in-sample | 928 | 326 | 602 | 35.1% | -$66,462 | -0.072 | -1.03 | -66.5 | 0.89 | -$95,658 | 99 |
| swing_high · out-of-sample | 636 | 219 | 417 | 34.4% | -$60,043 | -0.094 | -1.03 | -60.0 | 0.85 | -$81,639 | 107 |
| swing_low · in-sample | 928 | 335 | 593 | 36.1% | -$10,843 | -0.012 | -1.03 | -10.8 | 0.98 | -$73,465 | 85 |
| swing_low · out-of-sample | 589 | 207 | 382 | 35.1% | -$26,174 | -0.044 | -1.03 | -26.2 | 0.93 | -$48,795 | 94 |

## By time of day (signal time)

| window | trades | won | lost | win % | profit | avg R | median R | total R | PF | max DD | avg min |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 09:30-10:00 | 3097 | 1162 | 1935 | 37.5% | -$31,567 | -0.010 | -1.02 | -31.6 | 0.98 | -$67,172 | 102 |
| 10:00-10:30 | 1534 | 531 | 1003 | 34.6% | -$104,664 | -0.068 | -1.03 | -104.7 | 0.89 | -$132,345 | 94 |
| 10:30-11:00 | 514 | 181 | 333 | 35.2% | -$40,192 | -0.078 | -1.03 | -40.2 | 0.88 | -$44,583 | 106 |
| 11:00-11:30 | 258 | 97 | 161 | 37.6% | -$2,388 | -0.009 | -0.89 | -2.4 | 0.98 | -$31,976 | 131 |

## By direction

| side | trades | won | lost | win % | profit | avg R | median R | total R | PF | max DD | avg min |
|---|---|---|---|---|---|---|---|---|---|---|---|
| long | 2708 | 970 | 1738 | 35.8% | -$157,148 | -0.058 | -1.02 | -157.1 | 0.91 | -$171,246 | 106 |
| short | 2695 | 1001 | 1694 | 37.1% | -$21,662 | -0.008 | -1.03 | -21.7 | 0.99 | -$121,972 | 97 |

## By market condition

Market bias = SPY + QQQ context at the signal (known then). SPY day = how SPY's morning actually went by 11:30 (hindsight; describes the day, not usable as a filter).

| market bias at signal | trades | won | lost | win % | profit | avg R | median R | total R | PF | max DD | avg min |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Bullish | 2423 | 909 | 1514 | 37.5% | -$63,420 | -0.026 | -1.02 | -63.4 | 0.96 | -$82,631 | 109 |
| Neutral | 1636 | 580 | 1056 | 35.5% | -$75,249 | -0.046 | -1.03 | -75.2 | 0.93 | -$87,241 | 95 |
| Bearish | 1344 | 482 | 862 | 35.9% | -$40,141 | -0.030 | -1.03 | -40.1 | 0.95 | -$60,713 | 96 |

| trade vs market bias | trades | won | lost | win % | profit | avg R | median R | total R | PF | max DD | avg min |
|---|---|---|---|---|---|---|---|---|---|---|---|
| against the market | 1493 | 567 | 926 | 38.0% | $31,523 | +0.021 | -1.02 | +31.5 | 1.03 | -$67,003 | 99 |
| market neutral | 1636 | 580 | 1056 | 35.5% | -$75,249 | -0.046 | -1.03 | -75.2 | 0.93 | -$87,241 | 95 |
| with the market | 2274 | 824 | 1450 | 36.2% | -$135,085 | -0.059 | -1.02 | -135.1 | 0.90 | -$145,413 | 108 |

| SPY morning (hindsight) | trades | won | lost | win % | profit | avg R | median R | total R | PF | max DD | avg min |
|---|---|---|---|---|---|---|---|---|---|---|---|
| trend up | 853 | 328 | 525 | 38.5% | $7,464 | +0.009 | -1.02 | +7.5 | 1.01 | -$30,729 | 100 |
| trend down | 927 | 397 | 530 | 42.8% | $183,027 | +0.197 | -1.02 | +183.0 | 1.35 | -$22,720 | 86 |
| range | 3623 | 1246 | 2377 | 34.4% | -$369,302 | -0.102 | -1.03 | -369.3 | 0.84 | -$383,888 | 106 |

## By confidence and stock bias

| confidence | trades | won | lost | win % | profit | avg R | median R | total R | PF | max DD | avg min |
|---|---|---|---|---|---|---|---|---|---|---|---|
| HIGH | 1508 | 552 | 956 | 36.6% | -$98,760 | -0.065 | -1.02 | -98.8 | 0.89 | -$110,197 | 117 |
| MEDIUM | 1194 | 419 | 775 | 35.1% | -$52,413 | -0.044 | -1.03 | -52.4 | 0.93 | -$71,896 | 86 |
| LOW | 2701 | 1000 | 1701 | 37.0% | -$27,638 | -0.010 | -1.02 | -27.6 | 0.98 | -$109,368 | 100 |

| stock bias at signal | trades | won | lost | win % | profit | avg R | median R | total R | PF | max DD | avg min |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Bullish | 1831 | 681 | 1150 | 37.2% | -$63,585 | -0.035 | -1.02 | -63.6 | 0.94 | -$94,876 | 106 |
| Neutral | 2191 | 807 | 1384 | 36.8% | -$39,548 | -0.018 | -1.02 | -39.5 | 0.97 | -$96,907 | 106 |
| Bearish | 1381 | 483 | 898 | 35.0% | -$75,678 | -0.055 | -1.03 | -75.7 | 0.91 | -$87,777 | 88 |

| VWAP | trades | won | lost | win % | profit | avg R | median R | total R | PF | max DD | avg min |
|---|---|---|---|---|---|---|---|---|---|---|---|
| VWAP against | 511 | 175 | 336 | 34.2% | -$30,756 | -0.060 | -1.03 | -30.8 | 0.91 | -$50,992 | 76 |
| VWAP supports | 4892 | 1796 | 3096 | 36.7% | -$148,055 | -0.030 | -1.02 | -148.1 | 0.95 | -$188,738 | 104 |

| open vs previous day | trades | won | lost | win % | profit | avg R | median R | total R | PF | max DD | avg min |
|---|---|---|---|---|---|---|---|---|---|---|---|
| above_pdh | 1108 | 406 | 702 | 36.6% | -$28,352 | -0.026 | -1.02 | -28.4 | 0.96 | -$69,561 | 104 |
| below_pdl | 881 | 306 | 575 | 34.7% | -$52,339 | -0.059 | -1.02 | -52.3 | 0.91 | -$72,914 | 95 |
| inside | 3414 | 1259 | 2155 | 36.9% | -$98,120 | -0.029 | -1.03 | -98.1 | 0.95 | -$129,908 | 102 |

## Stops: correct, or too tight?

Stops hit: **3147** of 5403 trades.

| after the stop | back to entry | reached 1R | reached original 2R | avg best R (from entry) |
|---|---|---|---|---|
| +5 min | 10% | 2% | 0% | -0.58 |
| +10 min | 17% | 4% | 1% | -0.43 |
| +15 min | 22% | 6% | 2% | -0.32 |
| +30 min | 32% | 11% | 4% | -0.08 |
| rest of day | 61% | 36% | 22% | +0.99 |

| classification (within +30 min) | stops | share |
|---|---|---|
| TRUE FAILURE | 2142 | 68% |
| POSSIBLY TOO-TIGHT STOP | 875 | 28% |
| STOP-OUT -> 2R RECOVERY | 130 | 4% |

### The same entries with other stops (each with its own 2R target)

Exploratory. 21 alternative exits are listed across this and the next table; with that many looks, a difference smaller than about 2.5 standard errors is noise. Judge on out-of-sample, and expect the best in-sample row to shrink.

| stop | period | trades | win % | profit | avg R | PF |
|---|---|---|---|---|---|---|
| 0.25pct | in-sample | 3229 | 33.0% | -$242,513 | -0.075 | 0.89 |
| 0.25pct | out-of-sample | 2174 | 33.2% | -$163,309 | -0.075 | 0.89 |
| 0.35pct | in-sample | 3229 | 35.4% | -$78,550 | -0.024 | 0.96 |
| 0.35pct | out-of-sample | 2174 | 34.2% | -$135,089 | -0.062 | 0.91 |
| 0.5pct | in-sample | 3229 | 37.1% | -$42,483 | -0.013 | 0.98 |
| 0.5pct | out-of-sample | 2174 | 35.6% | -$136,328 | -0.063 | 0.90 |
| 0.75pct | in-sample | 3229 | 40.5% | $34,781 | +0.011 | 1.02 |
| 0.75pct | out-of-sample | 2174 | 38.8% | -$49,434 | -0.023 | 0.96 |
| 1pct | in-sample | 3229 | 42.5% | $26,166 | +0.008 | 1.02 |
| 1pct | out-of-sample | 2174 | 40.8% | -$37,935 | -0.017 | 0.97 |
| 0.25atr | in-sample | 3229 | 42.6% | $22,618 | +0.007 | 1.01 |
| 0.25atr | out-of-sample | 2174 | 41.7% | -$78,505 | -0.036 | 0.93 |

## Targets: is 2R too conservative?

2R targets hit: **1388** of 5403 trades.

| after the target | reached 3R | reached 4R | avg extra R beyond 2R |
|---|---|---|---|
| +5 min | 12% | 2% | +0.47 |
| +10 min | 21% | 5% | +0.63 |
| +15 min | 27% | 7% | +0.76 |
| +30 min | 38% | 14% | +1.03 |
| rest of day | | | +2.25 |

Reversed within 5 minutes (gave back to +1R or worse): **11%** of 2R hits.

Trades that reached 2R at any point before the bell: 39%; average best R before the bell (MFE): +2.13; average worst R while open (MAE): -0.86.

### The same entries and stop with other exits

| target | period | trades | win % | profit | avg R | PF |
|---|---|---|---|---|---|---|
| 1.5r | in-sample | 3229 | 41.3% | -$71,302 | -0.022 | 0.96 |
| 1.5r | out-of-sample | 2174 | 39.8% | -$131,402 | -0.060 | 0.90 |
| 2r | in-sample | 3229 | 37.1% | -$42,483 | -0.013 | 0.98 |
| 2r | out-of-sample | 2174 | 35.6% | -$136,328 | -0.063 | 0.90 |
| 3r | in-sample | 3229 | 33.0% | -$25,394 | -0.008 | 0.99 |
| 3r | out-of-sample | 2174 | 32.2% | -$84,023 | -0.039 | 0.94 |
| 4r | in-sample | 3229 | 31.3% | -$37,678 | -0.012 | 0.98 |
| 4r | out-of-sample | 2174 | 30.2% | -$123,537 | -0.057 | 0.92 |
| no target (stop or time exit) | in-sample | 3229 | 30.5% | $17,739 | +0.005 | 1.01 |
| no target (stop or time exit) | out-of-sample | 2174 | 29.4% | -$95,494 | -0.044 | 0.94 |
| trail 1R behind the high after 2R | in-sample | 3229 | 37.1% | -$31,911 | -0.010 | 0.98 |
| trail 1R behind the high after 2R | out-of-sample | 2174 | 35.6% | -$120,417 | -0.055 | 0.91 |

## Missed and rejected setups

Rules flagged for review (blocked complete setups beat the trades taken, 20+ setups): none

| rejected by | stage | setups | would-win % | would-profit | avg R | vs trades taken |
|---|---|---|---|---|---|---|
| confirm_timeout | never completed (at the break, hindsight-selected) | 108 | 26.9% | -$31,000 | -0.287 | not evidence (selected by outcome) |
| failed_breakout | never completed (at the break, hindsight-selected) | 11790 | 12.2% | -$8,192,549 | -0.695 | not evidence (selected by outcome) |
| gap_beyond_level | blocked | 1274 | 36.3% | -$91,176 | -0.072 |  |
| inactive_level | blocked | 1552 | 36.9% | -$74,117 | -0.048 |  |
| max_signals_per_day | blocked | 4205 | 34.3% | -$133,685 | -0.032 |  |
| position_open | blocked | 9290 | 36.9% | -$448,063 | -0.048 |  |
| retest_timeout | never completed (at the break, hindsight-selected) | 3844 | 70.1% | $2,912,426 | +0.758 | not evidence (selected by outcome) |
| window_closed | never completed (at the break, hindsight-selected) | 1495 | 45.8% | $360,826 | +0.241 | not evidence (selected by outcome) |

**Is waiting for the retest worth it?** The same breakouts, every one bought at the breakout candle's close with the same stop and target:

| entry | trades | won | lost | win % | profit | avg R | median R | total R | PF | max DD | avg min |
|---|---|---|---|---|---|---|---|---|---|---|---|
| every breakout, at the break | 38961 | 13420 | 25541 | 34.4% | -$3,408,725 | -0.087 | -1.03 | -3408.7 | 0.86 | -$5,081,584 |  |
| V1 (break, retest, confirm) | 5403 | 1971 | 3432 | 36.5% | -$178,811 | -0.033 | -1.02 | -178.8 | 0.95 | -$203,296 | 101 |

**Most profitable complete setups that a rule blocked (top 15):**

| date | time | symbol | side | level | blocked by | would-R |
|---|---|---|---|---|---|---|
| 2026-06-01 | 11:07 | AMD | long | swing_high@10:55 509.90 | max_signals_per_day | +2.00 |
| 2026-07-01 | 11:15 | SNDK | long | swing_high@11:04 2043.99 | max_signals_per_day | +2.00 |
| 2025-11-26 | 09:58 | COIN | long | pdh 254.37 | gap_beyond_level | +2.00 |
| 2026-07-15 | 09:59 | AMZN | long | swing_high@09:51 251.96 | position_open | +2.00 |
| 2025-12-03 | 09:48 | HOOD | long | pdc 125.95 | max_signals_per_day | +2.00 |
| 2026-06-29 | 10:56 | AMD | long | swing_high@10:50 508.87 | max_signals_per_day | +2.00 |
| 2026-06-15 | 10:02 | SNDK | long | pdh 2021.65 | gap_beyond_level | +2.00 |
| 2026-05-28 | 10:37 | AMD | long | swing_high@09:36 507.00 | max_signals_per_day | +2.00 |
| 2026-07-29 | 10:17 | COIN | short | swing_low@09:52 166.68 | position_open | +2.00 |
| 2026-04-23 | 10:15 | NVDA | short | pdh 202.50 | position_open | +2.00 |
| 2026-04-23 | 10:01 | NVDA | short | swing_low@09:51 203.15 | position_open | +2.00 |
| 2026-03-11 | 10:45 | AMZN | short | swing_low@09:52 214.62 | position_open | +2.00 |
| 2026-04-23 | 09:50 | SPY | short | pdh 711.45 | gap_beyond_level | +2.00 |
| 2026-07-30 | 09:36 | MU | long | pmh 794.97 | inactive_level | +2.00 |
| 2026-04-23 | 09:32 | HOOD | short | pdl 87.48 | gap_beyond_level | +2.00 |

## SNDK — benchmark ticker

| SNDK | trades | won | lost | win % | profit | avg R | median R | total R | PF | max DD | avg min |
|---|---|---|---|---|---|---|---|---|---|---|---|
| all | 482 | 173 | 309 | 35.9% | $21,920 | +0.045 | -1.02 | +21.9 | 1.07 | -$30,052 | 28 |

SNDK candidates: 4136 breakouts, 2029 complete setups, 482 taken. Premarket-level setups (PMH/PML) on SNDK: 1041 candidates, 58 taken.

| date | time | side | level | tf | outcome | R |
|---|---|---|---|---|---|---|
| 2026-09-18 | 09:37 | long | pmh 1649.80 | 1m | target | +2.00 |
| 2026-09-18 | 10:13 | long | swing_high@10:01 1700.71 | 1m | stop | -1.03 |
| 2026-09-21 | 09:59 | short | pdc 1792.83 | 1m | target | +2.00 |
| 2026-09-22 | 10:11 | short | swing_low@09:57 1888.28 | 1m | target | +2.00 |
| 2026-09-22 | 10:52 | short | swing_low@09:49 1868.11 | 1m | target | +2.00 |
| 2026-09-23 | 09:37 | short | pdc 1886.05 | 1m | target | +2.00 |
| 2026-09-23 | 10:48 | long | swing_high@10:41 1832.10 | 1m | stop | -1.04 |
| 2026-09-24 | 10:01 | long | swing_high@09:38 1767.72 | 1m | stop | -1.02 |
| 2026-09-24 | 11:10 | short | swing_low@09:59 1763.04 | 1m | stop | -1.03 |
| 2026-09-25 | 09:38 | long | pdh 1802.99 | 1m | stop | -1.04 |
| 2026-09-25 | 09:58 | short | swing_low@09:45 1771.50 | 1m | stop | -1.03 |
| 2026-09-28 | 09:33 | long | pmh 1740.45 | 1m | stop | -1.03 |
| 2026-09-28 | 10:10 | short | swing_low@10:00 1715.53 | 1m | target | +2.00 |
| 2026-09-29 | 09:36 | short | pdc 1712.00 | 1m | stop | -1.03 |
| 2026-09-29 | 10:01 | long | swing_high@09:46 1715.69 | 1m | stop | -1.02 |
| 2026-09-30 | 09:36 | short | pdc 1729.75 | 1m | stop | -1.03 |
| 2026-09-30 | 09:57 | long | swing_high@09:51 1735.96 | 1m | time | +0.65 |
| 2026-10-01 | 09:32 | long | pdc 1739.89 | 1m | stop | -1.02 |
| 2026-10-01 | 10:01 | short | swing_low@09:48 1744.00 | 1m | target | +2.00 |
| 2026-10-02 | 09:57 | short | swing_low@09:50 1738.21 | 1m | stop | -1.04 |
| 2026-10-02 | 10:11 | long | swing_high@09:48 1747.95 | 1m | stop | -1.04 |
| 2026-10-05 | 09:33 | long | pml 1719.00 | 1m | stop | -1.02 |
| 2026-10-06 | 09:34 | short | pdc 1704.13 | 1m | target | +2.00 |
| 2026-10-07 | 09:51 | long | pmh 1652.00 | 1m | target | +2.00 |
| 2026-10-07 | 10:42 | long | swing_high@10:26 1707.09 | 1m | stop | -1.03 |

## Benchmark trades

No benchmark trades entered yet. Add them to `br_benchmarks.yaml` (symbol, date, time, direction, level, note).

## Data notes

- Premarket bars per symbol-session (SIP): median 266, 2% of sessions under 30 bars (thin premarket = PMH/PML less meaningful).
- Context votes use only bars closed before the signal; daily vote and ATR use yesterday's row.
- Live trades will use IEX real-time bars and SIP data delayed 15 minutes for premarket levels, so PMH/PML live may miss 09:15-09:29 prints. See `src/br_live.py`.

## Charts

67 chart(s): the best and worst trades and the latest SNDK trades, at the signal and at the exit. They are in the workflow run's `br-v1-charts` artifact (not committed, to keep the repo small).