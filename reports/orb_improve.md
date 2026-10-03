# Improving the current day-trade rule

Current rule: `P(universe='top10', window_end=30, orw=(0.35, 9000000000.0), market='none', disp=0.0, bvol=0.0, sides='both', ext=9000000000.0, stop='D', target=2.0, manage='fixed', cluster_max=99, slip=0.0005, delay=0, gap='any', crowd=0, spy_trend=False, spy_vol=0.0, max_risk=0.1)`.

Recent range: 2026-07-07 to 2026-10-02 (63 sessions, 257 trades) - where losing clusters were looked for. Earlier range: 2025-09-30 to 2026-07-06 (189 sessions, 776 trades) - used only to confirm. Each % is one trade as a share of the account (a full stop costs 1%), after 0.05% slippage a side.

## 1. Where the results come from

**Recent:** 17 targets, 47 stops, 193 closed at 15:55. Of the stopped trades, 2% had been at least +1x risk in profit first and 13% at least +0.5x. Of the 15:55 exits, 10% had been +1.5x or more at some point. After a target hit, price ran a further +0.34x risk (median) by 15:55. After a stop, 0% went on to where the target was.

**Earlier:** 52 targets, 235 stops, 489 closed at 15:55. Of the stopped trades, 3% had been at least +1x risk in profit first and 15% at least +0.5x. Of the 15:55 exits, 15% had been +1.5x or more at some point. After a target hit, price ran a further +0.45x risk (median) by 15:55. After a stop, 2% went on to where the target was.

## 2. Segments (recent | earlier)

### Long vs short

| bucket | recent trades | win % | avg | PF | total | earlier trades | win % | avg | PF |
|---|---|---|---|---|---|---|---|---|---|
| long | 139 | 49% | +0.07% | 1.22 | +9.1% | 408 | 47% | -0.02% | 0.96 |
| short | 118 | 58% | +0.18% | 1.70 | +21.4% | 368 | 48% | +0.02% | 1.06 |

### Setup type (with or against the overnight gap)

| bucket | recent trades | win % | avg | PF | total | earlier trades | win % | avg | PF |
|---|---|---|---|---|---|---|---|---|---|
| against / no gap | 134 | 54% | +0.17% | 1.64 | +22.2% | 344 | 50% | +0.04% | 1.11 |
| with the gap | 123 | 51% | +0.07% | 1.22 | +8.3% | 432 | 46% | -0.03% | 0.93 |

### Entry time

| bucket | recent trades | win % | avg | PF | total | earlier trades | win % | avg | PF |
|---|---|---|---|---|---|---|---|---|---|
| 09:35-09:39 | 156 | 54% | +0.13% | 1.47 | +20.0% | 493 | 49% | +0.02% | 1.04 |
| 09:40-09:44 | 44 | 45% | +0.18% | 1.64 | +8.1% | 99 | 45% | +0.03% | 1.07 |
| 09:45-09:49 | 26 | 46% | -0.11% | 0.70 | -2.9% | 93 | 46% | -0.02% | 0.94 |
| 09:50-09:59 | 31 | 61% | +0.17% | 1.68 | +5.3% | 91 | 45% | -0.07% | 0.81 |

### Exit time

| bucket | recent trades | win % | avg | PF | total | earlier trades | win % | avg | PF |
|---|---|---|---|---|---|---|---|---|---|
| 10:30-11:59 | 21 | 24% | -0.32% | 0.59 | -6.7% | 87 | 11% | -0.69% | 0.25 |
| 12:00-13:59 | 12 | 50% | +0.47% | 1.91 | +5.6% | 61 | 30% | -0.15% | 0.79 |
| 14:00-15:54 | 12 | 33% | -0.04% | 0.95 | -0.4% | 37 | 32% | -0.06% | 0.91 |
| 15:55 (bell) | 193 | 62% | +0.24% | 2.94 | +45.7% | 491 | 65% | +0.29% | 3.24 |
| before 10:30 | 19 | 11% | -0.72% | 0.22 | -13.7% | 100 | 12% | -0.68% | 0.26 |

### How it ended

| bucket | recent trades | win % | avg | PF | total | earlier trades | win % | avg | PF |
|---|---|---|---|---|---|---|---|---|---|
| bell | 193 | 62% | +0.24% | 2.94 | +45.7% | 489 | 65% | +0.29% | 3.35 |
| stop | 47 | 0% | -1.04% | 0.00 | -48.7% | 235 | 0% | -1.04% | 0.00 |
| target | 17 | 100% | +1.97% | inf | +33.5% | 52 | 100% | +1.96% | inf |

### Day of week

| bucket | recent trades | win % | avg | PF | total | earlier trades | win % | avg | PF |
|---|---|---|---|---|---|---|---|---|---|
| Fri | 53 | 51% | +0.10% | 1.38 | +5.2% | 151 | 50% | +0.04% | 1.10 |
| Mon | 52 | 58% | +0.15% | 1.56 | +7.9% | 154 | 49% | +0.03% | 1.08 |
| Thu | 57 | 58% | +0.19% | 1.77 | +11.1% | 159 | 42% | -0.01% | 0.98 |
| Tue | 48 | 44% | +0.11% | 1.36 | +5.2% | 166 | 47% | -0.12% | 0.72 |
| Wed | 47 | 53% | +0.02% | 1.06 | +1.0% | 146 | 51% | +0.09% | 1.27 |

### SPY above/below VWAP, matching the trade

| bucket | recent trades | win % | avg | PF | total | earlier trades | win % | avg | PF |
|---|---|---|---|---|---|---|---|---|---|
| against | 91 | 52% | +0.15% | 1.56 | +13.8% | 270 | 51% | +0.07% | 1.20 |
| matches | 166 | 54% | +0.10% | 1.35 | +16.6% | 506 | 45% | -0.03% | 0.92 |

### SPY move since its open, matching the trade

| bucket | recent trades | win % | avg | PF | total | earlier trades | win % | avg | PF |
|---|---|---|---|---|---|---|---|---|---|
| against | 105 | 54% | +0.16% | 1.61 | +16.4% | 293 | 50% | +0.05% | 1.15 |
| matches | 152 | 52% | +0.09% | 1.31 | +14.1% | 483 | 46% | -0.03% | 0.93 |

### SPY 20-day trend, matching the trade

| bucket | recent trades | win % | avg | PF | total | earlier trades | win % | avg | PF |
|---|---|---|---|---|---|---|---|---|---|
| against | 126 | 53% | +0.11% | 1.42 | +14.2% | 368 | 50% | +0.05% | 1.15 |
| matches | 131 | 53% | +0.12% | 1.43 | +16.2% | 408 | 45% | -0.05% | 0.89 |

### Market volatility: SPY opening range / its ATR

| bucket | recent trades | win % | avg | PF | total | earlier trades | win % | avg | PF |
|---|---|---|---|---|---|---|---|---|---|
| normal (0.1-0.2) | 163 | 52% | +0.08% | 1.26 | +13.0% | 420 | 50% | +0.04% | 1.09 |
| quiet open (<0.1) | 26 | 62% | +0.24% | 1.87 | +6.2% | 113 | 45% | -0.06% | 0.84 |
| wild open (>=0.2) | 68 | 53% | +0.17% | 1.74 | +11.3% | 243 | 45% | -0.03% | 0.93 |

### Market volatility: SPY daily ATR as % of price

| bucket | recent trades | win % | avg | PF | total | earlier trades | win % | avg | PF |
|---|---|---|---|---|---|---|---|---|---|
| high (>=1.2%) | 26 | 50% | -0.04% | 0.91 | -1.1% | 302 | 47% | -0.00% | 0.99 |
| low (<0.8%) | 81 | 57% | +0.20% | 1.80 | +16.2% | 88 | 39% | -0.16% | 0.69 |
| mid | 150 | 51% | +0.10% | 1.38 | +15.3% | 386 | 50% | +0.04% | 1.11 |

### Room to yesterday's high (long) / low (short), in ATR

| bucket | recent trades | win % | avg | PF | total | earlier trades | win % | avg | PF |
|---|---|---|---|---|---|---|---|---|---|
| already through it | 134 | 50% | +0.06% | 1.22 | +8.6% | 405 | 48% | -0.04% | 0.90 |
| more than 0.5 ATR away | 74 | 55% | +0.18% | 1.66 | +13.5% | 233 | 41% | -0.09% | 0.80 |
| within 0.5 ATR | 49 | 57% | +0.17% | 1.62 | +8.4% | 136 | 58% | +0.27% | 1.90 |

### Stock rank by opening volume

| bucket | recent trades | win % | avg | PF | total | earlier trades | win % | avg | PF |
|---|---|---|---|---|---|---|---|---|---|
| 1-3 | 87 | 52% | +0.14% | 1.54 | +12.3% | 309 | 47% | -0.00% | 0.99 |
| 4-6 | 76 | 55% | +0.03% | 1.10 | +2.3% | 219 | 44% | -0.04% | 0.91 |
| 7-10 | 94 | 52% | +0.17% | 1.61 | +15.9% | 248 | 52% | +0.05% | 1.12 |

### Opening volume vs normal

| bucket | recent trades | win % | avg | PF | total | earlier trades | win % | avg | PF |
|---|---|---|---|---|---|---|---|---|---|
| 1.5-3x | 117 | 46% | -0.01% | 0.97 | -1.3% | 389 | 48% | +0.02% | 1.06 |
| <1.5x | 90 | 52% | +0.13% | 1.44 | +11.7% | 238 | 49% | +0.01% | 1.02 |
| >=3x | 50 | 70% | +0.40% | 4.57 | +20.1% | 149 | 44% | -0.06% | 0.85 |

### Opening range / stock's ATR

| bucket | recent trades | win % | avg | PF | total | earlier trades | win % | avg | PF |
|---|---|---|---|---|---|---|---|---|---|
| 0.35-0.5 | 136 | 54% | +0.12% | 1.39 | +16.7% | 454 | 45% | -0.04% | 0.91 |
| 0.5-0.75 | 78 | 53% | +0.13% | 1.50 | +10.3% | 227 | 52% | +0.11% | 1.33 |
| >=0.75 | 43 | 49% | +0.08% | 1.39 | +3.4% | 95 | 48% | -0.04% | 0.85 |

### Breakout strength (close past the level / range)

| bucket | recent trades | win % | avg | PF | total | earlier trades | win % | avg | PF |
|---|---|---|---|---|---|---|---|---|---|
| 0.1-0.3 | 97 | 55% | +0.16% | 1.59 | +15.6% | 280 | 53% | +0.05% | 1.14 |
| <0.1 | 150 | 53% | +0.11% | 1.39 | +16.7% | 463 | 46% | -0.01% | 0.98 |
| >=0.3 | 10 | 40% | -0.18% | 0.44 | -1.8% | 33 | 27% | -0.28% | 0.42 |

### Breakout-minute volume vs that minute's normal

| bucket | recent trades | win % | avg | PF | total | earlier trades | win % | avg | PF |
|---|---|---|---|---|---|---|---|---|---|
| 1-2x | 77 | 51% | +0.19% | 1.73 | +14.7% | 285 | 45% | -0.03% | 0.93 |
| <1x | 84 | 57% | +0.11% | 1.35 | +9.4% | 206 | 50% | -0.00% | 1.00 |
| >=2x | 96 | 51% | +0.07% | 1.25 | +6.4% | 285 | 48% | +0.04% | 1.10 |

### Stop distance (% of price)

| bucket | recent trades | win % | avg | PF | total | earlier trades | win % | avg | PF |
|---|---|---|---|---|---|---|---|---|---|
| 1-2% | 99 | 51% | +0.07% | 1.21 | +7.0% | 387 | 47% | -0.03% | 0.93 |
| 2-3% | 72 | 61% | +0.26% | 2.23 | +18.6% | 175 | 47% | +0.02% | 1.05 |
| <1% | 22 | 55% | +0.08% | 1.22 | +1.7% | 82 | 49% | +0.06% | 1.14 |
| >=3% | 64 | 47% | +0.05% | 1.19 | +3.2% | 132 | 50% | +0.04% | 1.11 |

### Tickers (recent, worst 8 and best 8)

| ticker | recent trades | recent total | earlier trades | earlier total |
|---|---|---|---|---|
| DDOG | 4 | -3.04% | 2 | -0.04% |
| JNJ | 5 | -2.41% | 22 | -2.51% |
| SMCI | 7 | -2.28% | 3 | +0.60% |
| HOOD | 10 | -1.70% | 23 | +6.50% |
| FCX | 9 | -1.30% | 9 | -3.92% |
| AAPL | 7 | -1.11% | 28 | -1.39% |
| NET | 1 | -1.11% | 0 | - |
| PEP | 1 | -1.03% | 0 | - |
| GOOGL | 8 | +2.02% | 28 | -1.52% |
| AMD | 4 | +2.78% | 32 | -1.15% |
| META | 10 | +2.86% | 27 | -2.08% |
| PG | 3 | +2.87% | 6 | -1.75% |
| MSTR | 5 | +3.30% | 3 | -0.55% |
| TSLA | 12 | +4.63% | 25 | -0.14% |
| CRM | 10 | +5.03% | 29 | -2.75% |
| CRWD | 16 | +8.27% | 7 | +2.46% |

Only 2-6 trades per name in the recent range: far too few to drop a ticker on. Not tested as a rule.

## 3. Candidate changes (fixed before the run; each tested on both ranges)

13 candidates. With that many tries, one can look good by chance; that is why each must hold on the earlier range too.

| change | verdict | recent trades | recent avg | recent PF | earlier trades | earlier avg | earlier PF | recent avg @0.10% | earlier avg @0.10% |
|---|---|---|---|---|---|---|---|---|---|
| current rule | - | 257 | +0.119% | 1.42 | 776 | +0.002% | 1.01 | +0.060% | -0.053% |
| No entries after 09:45 (late signals) | ADOPT | 200 | +0.141% | 1.51 | 592 | +0.018% | 1.05 | +0.085% | -0.037% |
| No entries after 09:50 | avg not better on both | 226 | +0.111% | 1.39 | 685 | +0.012% | 1.03 | +0.053% | -0.043% |
| Longs only | avg not better on both | 144 | +0.072% | 1.24 | 425 | -0.017% | 0.96 | +0.017% | -0.073% |
| Shorts only | keeps < 60% of trades | 121 | +0.170% | 1.65 | 384 | +0.009% | 1.02 | +0.107% | -0.044% |
| SPY above/below VWAP must match (SPY and QQQ) | avg not better on both | 193 | +0.104% | 1.38 | 635 | -0.010% | 0.97 | +0.048% | -0.065% |
| SPY's move since the open must match | avg not better on both | 192 | +0.116% | 1.41 | 600 | -0.022% | 0.94 | +0.060% | -0.075% |
| Skip quiet market opens (SPY range < 0.1 ATR) | avg not better on both | 231 | +0.105% | 1.37 | 663 | +0.012% | 1.03 | +0.051% | -0.043% |
| Stronger breakout (close >= 0.1 of the range past it) | avg not better on both | 222 | +0.113% | 1.44 | 664 | +0.020% | 1.06 | +0.064% | -0.032% |
| Breakout-minute volume >= 1.5x normal | avg not better on both | 219 | +0.109% | 1.42 | 676 | -0.010% | 0.97 | +0.053% | -0.060% |
| Only the top 5 by opening volume | avg not better on both | 139 | +0.121% | 1.46 | 456 | -0.018% | 0.95 | +0.062% | -0.069% |
| Skip wide stops (> 3% of price) | avg not better on both | 193 | +0.141% | 1.49 | 644 | -0.005% | 0.99 | +0.066% | -0.068% |
| Stop to breakeven after +1x risk | ADOPT | 257 | +0.121% | 1.44 | 776 | +0.009% | 1.02 | +0.068% | -0.050% |
| Target 3x risk instead of 2x | avg not better on both | 257 | +0.112% | 1.40 | 776 | +0.001% | 1.00 | +0.057% | -0.060% |

## 4. Result

Adopted: No entries after 09:45 (late signals); Stop to breakeven after +1x risk.
Final rule: `P(universe='top10', window_end=15, orw=(0.35, 9000000000.0), market='none', disp=0.0, bvol=0.0, sides='both', ext=9000000000.0, stop='D', target=2.0, manage='be', cluster_max=99, slip=0.0005, delay=0, gap='any', crowd=0, spy_trend=False, spy_vol=0.0, max_risk=0.1)`

### week

| metric | old rule | current rule | improved rule |
|---|---|---|---|
| Trades | 46 | 27 | 21 |
| Win rate | 28.3% | 48.1% | 52.4% |
| Avg/trade | -0.47% | -0.04% | +0.03% |
| Total | -21.75% | -1.20% | +0.69% |
| Profit factor | 0.27 | 0.90 | 1.09 |
| Max drawdown | 21.75% | 5.27% | 1.99% |
| Green days | 0 | 1 | 3 |
| Best trade | +1.97% | +1.98% | +1.97% |
| Worst trade | -1.23% | -1.08% | -1.08% |

### month

| metric | old rule | current rule | improved rule |
|---|---|---|---|
| Trades | 180 | 100 | 77 |
| Win rate | 36.1% | 53.0% | 53.2% |
| Avg/trade | -0.26% | +0.12% | +0.15% |
| Total | -47.11% | +11.78% | +11.44% |
| Profit factor | 0.53 | 1.35 | 1.48 |
| Max drawdown | 47.11% | 5.27% | 3.14% |
| Green days | 6 | 11 | 13 |
| Best trade | +1.97% | +1.98% | +1.98% |
| Worst trade | -1.36% | -1.08% | -1.08% |

### 3 months

| metric | old rule | current rule | improved rule |
|---|---|---|---|
| Trades | 551 | 257 | 200 |
| Win rate | 41.9% | 52.9% | 50.5% |
| Avg/trade | -0.10% | +0.12% | +0.14% |
| Total | -57.29% | +30.46% | +28.52% |
| Profit factor | 0.79 | 1.42 | 1.54 |
| Max drawdown | 64.13% | 5.27% | 3.46% |
| Green days | 27 | 38 | 38 |
| Best trade | +1.98% | +1.98% | +1.98% |
| Worst trade | -1.41% | -1.11% | -1.09% |

