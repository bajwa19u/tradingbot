# Day-trade ORB audit: big tech (live rule), baseline and five pre-registered changes

Alpaca IEX 1-minute bars. Sessions: train 233 (2024-10-01 to 2025-09-29), validation 189 (2025-09-30 to 2026-07-06), test 63 (2026-07-07 to 2026-10-02; seen when the big tech list was chosen, so not untouched for the baseline), forward 10 (2026-10-05 to 2026-10-16; untouched).

Rule: `P(universe='bigtech', window_end=15, orw=(0.35, 9000000000.0), market='none', disp=0.0, bvol=0.0, sides='both', ext=9000000000.0, stop='D', target=2.0, manage='be', cluster_max=99, slip=0.0005, delay=0, delay_fill='open', gap='any', crowd=0, spy_trend=False, spy_vol=0.0, max_risk=0.1)`. Names: TSLA, AMD, NVDA, META, AAPL, MSFT.

Results are % of the account per trade when a full stop costs 1% (sums, not compounded). Backtest only - the live and paper records are in `reports/audit_baseline.md`.

## 1. Reproduction of reports/orb_bigtech.md

| range | published trades | published expectancy | reproduced trades | reproduced expectancy |
|---|---|---|---|---|
| recent | 88 | +0.170% | 88 | +0.170% |
| earlier | 265 | -0.028% | 267 | -0.027% |

Differences come from a longer warm-up history (ATR and volume baselines on the first sessions) and any IEX bar revisions since 2 Oct.

## 2. Baseline

### realistic costs

| | trades | win % (won/lost) | expectancy (account %/trade) | PF | cumulative | max DD | avg win / loss | avg stock move | t |
|---|---|---|---|---|---|---|---|---|---|
| train | 272 | 41.5% (113/159) | -0.020% | 0.95 | -5.6% | 17.2% | +0.88% / -0.66% | -0.011% | -0.36 |
| val | 267 | 43.8% (117/150) | -0.027% | 0.93 | -7.3% | 24.6% | +0.85% / -0.71% | -0.084% | -0.48 |
| test | 88 | 53.4% (47/41) | +0.170% | 1.60 | +15.0% | 8.1% | +0.85% / -0.61% | +0.332% | +1.71 |
| forward | 16 | 50.0% (8/8) | -0.023% | 0.93 | -0.4% | 3.3% | +0.61% / -0.66% | -0.191% | -0.11 |
| train+val | 539 | 42.7% (230/309) | -0.024% | 0.94 | -12.9% | 27.5% | +0.87% / -0.69% | -0.047% | -0.60 |
| all | 643 | 44.3% (285/358) | +0.003% | 1.01 | +1.7% | 27.5% | +0.86% / -0.68% | +0.001% | +0.07 |

### stressed costs

| | trades | win % (won/lost) | expectancy (account %/trade) | PF | cumulative | max DD | avg win / loss | avg stock move | t |
|---|---|---|---|---|---|---|---|---|---|
| train | 272 | 39.7% (108/164) | -0.098% | 0.76 | -26.6% | 33.6% | +0.80% / -0.69% | -0.119% | -1.80 |
| val | 267 | 41.6% (111/156) | -0.095% | 0.78 | -25.3% | 31.1% | +0.79% / -0.72% | -0.181% | -1.72 |
| test | 88 | 53.4% (47/41) | +0.124% | 1.41 | +10.9% | 8.6% | +0.79% / -0.64% | +0.257% | +1.26 |
| forward | 16 | 37.5% (6/10) | -0.084% | 0.76 | -1.3% | 3.9% | +0.71% / -0.56% | -0.281% | -0.42 |
| train+val | 539 | 40.6% (219/320) | -0.096% | 0.77 | -51.9% | 63.5% | +0.80% / -0.71% | -0.150% | -2.50 |
| all | 643 | 42.3% (272/371) | -0.066% | 0.84 | -42.4% | 63.5% | +0.79% / -0.70% | -0.097% | -1.86 |

### stressed+late costs

| | trades | win % (won/lost) | expectancy (account %/trade) | PF | cumulative | max DD | avg win / loss | avg stock move | t |
|---|---|---|---|---|---|---|---|---|---|
| train | 272 | 39.7% (108/164) | -0.104% | 0.75 | -28.4% | 33.7% | +0.80% / -0.70% | -0.139% | -1.92 |
| val | 267 | 41.9% (112/155) | -0.083% | 0.81 | -22.1% | 30.1% | +0.82% / -0.73% | -0.112% | -1.48 |
| test | 88 | 50.0% (44/44) | +0.100% | 1.32 | +8.8% | 8.9% | +0.83% / -0.63% | +0.178% | +1.04 |
| forward | 16 | 37.5% (6/10) | -0.186% | 0.49 | -3.0% | 4.2% | +0.48% / -0.58% | -0.317% | -1.15 |
| train+val | 539 | 40.8% (220/319) | -0.094% | 0.78 | -50.5% | 63.8% | +0.81% / -0.71% | -0.126% | -2.40 |
| all | 643 | 42.0% (270/373) | -0.070% | 0.83 | -44.7% | 63.8% | +0.80% / -0.70% | -0.089% | -1.96 |

## 3. Baseline breakdowns (realistic costs)

#### By ticker

| bucket | train n | train exp | val n | val exp | test n | test exp | fwd n | fwd exp | all n | all exp | all PF |
|---|---|---|---|---|---|---|---|---|---|---|---|
| AAPL | 60 | -0.163% | 64 | -0.114% | 14 | +0.051% | 3 | +0.003% | 141 | -0.116% | 0.73 |
| AMD | 53 | +0.028% | 43 | -0.186% | 9 | -0.016% | 2 | -0.531% | 107 | -0.072% | 0.80 |
| META | 33 | +0.124% | 36 | -0.161% | 23 | +0.167% | 3 | +0.462% | 95 | +0.037% | 1.10 |
| MSFT | 50 | -0.043% | 50 | +0.215% | 18 | +0.130% | 3 | +0.220% | 121 | +0.096% | 1.29 |
| NVDA | 39 | +0.050% | 38 | +0.108% | 13 | +0.285% | 3 | -0.054% | 93 | +0.103% | 1.30 |
| TSLA | 37 | -0.032% | 36 | -0.031% | 11 | +0.409% | 2 | -0.599% | 86 | +0.012% | 1.03 |

#### By side

| bucket | train n | train exp | val n | val exp | test n | test exp | fwd n | fwd exp | all n | all exp | all PF |
|---|---|---|---|---|---|---|---|---|---|---|---|
| long | 126 | +0.016% | 131 | -0.093% | 48 | +0.275% | 7 | -0.283% | 312 | +0.003% | 1.01 |
| short | 146 | -0.052% | 136 | +0.036% | 40 | +0.045% | 9 | +0.180% | 331 | +0.002% | 1.01 |

#### By entry time

| bucket | train n | train exp | val n | val exp | test n | test exp | fwd n | fwd exp | all n | all exp | all PF |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 09:35-09:39 | 216 | +0.015% | 210 | -0.031% | 67 | +0.117% | 9 | +0.173% | 502 | +0.012% | 1.03 |
| 09:40-09:44 | 56 | -0.157% | 57 | -0.015% | 21 | +0.338% | 7 | -0.275% | 141 | -0.032% | 0.92 |

#### By SPY 20-day trend (known at the open)

| bucket | train n | train exp | val n | val exp | test n | test exp | fwd n | fwd exp | all n | all exp | all PF |
|---|---|---|---|---|---|---|---|---|---|---|---|
| SPY down-trend | 86 | +0.036% | 95 | -0.060% | 38 | +0.052% | 2 | -0.304% | 221 | -0.005% | 0.99 |
| SPY up-trend | 186 | -0.047% | 172 | -0.009% | 50 | +0.260% | 14 | +0.017% | 422 | +0.007% | 1.02 |

#### Trade direction vs SPY trend

| bucket | train n | train exp | val n | val exp | test n | test exp | fwd n | fwd exp | all n | all exp | all PF |
|---|---|---|---|---|---|---|---|---|---|---|---|
| against SPY trend | 128 | -0.012% | 151 | +0.016% | 52 | +0.201% | 11 | +0.092% | 342 | +0.036% | 1.11 |
| with SPY trend | 144 | -0.028% | 116 | -0.084% | 36 | +0.125% | 5 | -0.275% | 301 | -0.035% | 0.91 |

#### By exit

| bucket | train n | train exp | val n | val exp | test n | test exp | fwd n | fwd exp | all n | all exp | all PF |
|---|---|---|---|---|---|---|---|---|---|---|---|
| bell | 146 | +0.264% | 158 | +0.253% | 55 | +0.330% | 12 | +0.064% | 371 | +0.263% | 3.11 |
| stop | 104 | -0.840% | 90 | -0.939% | 24 | -0.869% | 3 | -1.029% | 221 | -0.886% | 0.00 |
| target | 22 | +1.967% | 19 | +1.959% | 9 | +1.964% | 1 | +1.948% | 51 | +1.963% | inf |

#### By opening relative volume

| bucket | train n | train exp | val n | val exp | test n | test exp | fwd n | fwd exp | all n | all exp | all PF |
|---|---|---|---|---|---|---|---|---|---|---|---|
| [0.0, 0.75) | 56 | -0.118% | 57 | -0.195% | 25 | +0.122% | 3 | +0.105% | 141 | -0.102% | 0.76 |
| [0.75, 1.0) | 39 | -0.043% | 52 | -0.167% | 13 | +0.240% | 3 | +0.967% | 107 | -0.041% | 0.90 |
| [1.0, 1.5) | 72 | -0.040% | 74 | +0.025% | 22 | +0.148% | 6 | -0.469% | 174 | -0.003% | 0.99 |
| [1.5, 99.0) | 105 | +0.053% | 84 | +0.128% | 28 | +0.198% | 4 | -0.193% | 221 | +0.095% | 1.29 |

#### By opening range / daily ATR

| bucket | train n | train exp | val n | val exp | test n | test exp | fwd n | fwd exp | all n | all exp | all PF |
|---|---|---|---|---|---|---|---|---|---|---|---|
| [0.35, 0.5) | 203 | -0.053% | 178 | -0.034% | 54 | +0.177% | 9 | +0.095% | 444 | -0.014% | 0.97 |
| [0.5, 0.75) | 61 | +0.039% | 73 | -0.004% | 25 | +0.136% | 5 | +0.091% | 164 | +0.036% | 1.13 |
| [0.75, 99.0) | 8 | +0.347% | 16 | -0.060% | 9 | +0.223% | 2 | -0.838% | 35 | +0.061% | 1.25 |

## 4. Month by month (realistic costs) - why recent months worked

| month | trades | win % | expectancy | total | longs | bell exits avg | range filter pass | SPY month | SPY daily vol (ann.) | SPY trend days up |
|---|---|---|---|---|---|---|---|---|---|---|
| 2024-10 | 34 | 59% | +0.256% | +8.7% | 41% | +0.340% | 38% | -1.0% | 11% | 52% |
| 2024-11 | 24 | 21% | -0.371% | -8.9% | 38% | +0.168% | 38% | +5.3% | 12% | 74% |
| 2024-12 | 28 | 46% | -0.093% | -2.6% | 43% | +0.338% | 34% | -2.1% | 16% | 42% |
| 2025-01 | 37 | 41% | -0.021% | -0.8% | 35% | +0.116% | 40% | +2.7% | 14% | 60% |
| 2025-02 | 11 | 55% | +0.168% | +1.9% | 64% | +0.542% | 22% | -1.3% | 13% | 53% |
| 2025-03 | 10 | 50% | -0.004% | -0.0% | 50% | +0.793% | 14% | -5.8% | 22% | 45% |
| 2025-04 | 13 | 46% | +0.153% | +2.0% | 31% | +0.616% | 15% | -0.9% | 49% | 57% |
| 2025-05 | 15 | 33% | -0.243% | -3.7% | 60% | +0.040% | 20% | +6.4% | 17% | 62% |
| 2025-06 | 24 | 42% | -0.045% | -1.1% | 62% | +0.463% | 40% | +4.8% | 10% | 65% |
| 2025-07 | 24 | 33% | +0.064% | +1.5% | 54% | +0.214% | 37% | +2.3% | 6% | 57% |
| 2025-08 | 19 | 37% | -0.096% | -1.8% | 58% | +0.354% | 31% | +2.1% | 12% | 43% |
| 2025-09 | 35 | 37% | -0.064% | -2.2% | 40% | +0.147% | 41% | +3.3% | 7% | 62% |
| 2025-10 | 31 | 48% | -0.110% | -3.4% | 35% | +0.336% | 34% | +2.4% | 13% | 65% |
| 2025-11 | 17 | 35% | -0.153% | -2.6% | 59% | +0.118% | 26% | -0.4% | 16% | 61% |
| 2025-12 | 22 | 32% | -0.115% | -2.5% | 55% | -0.016% | 25% | +0.3% | 8% | 57% |
| 2026-01 | 46 | 59% | +0.321% | +14.8% | 35% | +0.358% | 52% | +1.5% | 10% | 55% |
| 2026-02 | 25 | 52% | +0.128% | +3.2% | 40% | +0.344% | 34% | -0.8% | 13% | 47% |
| 2026-03 | 26 | 50% | +0.063% | +1.6% | 65% | +0.386% | 36% | -5.3% | 18% | 36% |
| 2026-04 | 31 | 39% | -0.180% | -5.6% | 52% | +0.018% | 42% | +10.5% | 12% | 71% |
| 2026-05 | 30 | 30% | -0.232% | -6.9% | 60% | +0.174% | 38% | +5.3% | 10% | 70% |
| 2026-06 | 32 | 31% | -0.303% | -9.7% | 56% | +0.161% | 40% | -1.3% | 17% | 52% |
| 2026-07 | 28 | 64% | +0.474% | +13.3% | 54% | +0.363% | 33% | +0.0% | 12% | 45% |
| 2026-08 | 17 | 65% | +0.340% | +5.8% | 59% | +0.420% | 28% | +2.7% | 10% | 48% |
| 2026-09 | 45 | 49% | +0.075% | +3.4% | 51% | +0.352% | 54% | -0.6% | 11% | 29% |
| 2026-10 | 19 | 47% | -0.128% | -2.4% | 53% | +0.061% | 40% | +0.1% | 10% | 50% |

Correlation of the month's expectancy with: spy -0.35, vol +0.06, pass_rate -0.01, longs -0.11 (25 months; descriptive, not a filter).

## 5. Pre-registered changes

Variants: 6. Noise floor sqrt(2 ln 6) = 1.89 standard errors.

| variant | realistic: train | val | test | forward | train+val t | stressed+late: train | val | verdict |
|---|---|---|---|---|---|---|---|---|
| baseline | 272 / -0.020% / PF 0.95 | 267 / -0.027% / PF 0.93 | 88 / +0.170% / PF 1.60 | 16 / -0.023% / PF 0.93 | -0.60 | 272 / -0.104% / PF 0.75 | 267 / -0.083% / PF 0.81 | - |
| H1 regime (with SPY 20-day trend) | 133 / -0.039% / PF 0.91 | 117 / -0.083% / PF 0.81 | 36 / +0.125% / PF 1.36 | 5 / -0.275% / PF 0.22 | -0.97 | 133 / -0.163% / PF 0.65 | 117 / -0.174% / PF 0.64 | 1: no validation gain; 2: worse on train; 3: profit factor lower; 4: gain rests on 2 trades; 5: not better at stressed+late costs; 6: train+val expectancy not positive |
| H2 crowding (max 2 same-side / 10 min) | 248 / -0.010% / PF 0.98 | 243 / -0.059% / PF 0.86 | 84 / +0.195% / PF 1.72 | 14 / -0.011% / PF 0.97 | -0.80 | 248 / -0.094% / PF 0.78 | 243 / -0.122% / PF 0.73 | 1: no validation gain; 3: profit factor lower; 4: gain rests on 2 trades; 5: not better at stressed+late costs; 6: train+val expectancy not positive |
| H3 in play (rvol5 >= 1.0) | 177 / +0.015% / PF 1.04 | 158 / +0.079% / PF 1.23 | 50 / +0.176% / PF 1.84 | 10 / -0.359% / PF 0.29 | +0.87 | 177 / -0.057% / PF 0.86 | 158 / +0.039% / PF 1.11 | 7: t 0.87 < noise floor 1.89 |
| H4 strength (close >= 0.10 range past) | 220 / +0.003% / PF 1.01 | 203 / +0.006% / PF 1.02 | 78 / +0.119% / PF 1.39 | 12 / +0.178% / PF 1.82 | +0.10 | 220 / -0.111% / PF 0.72 | 203 / -0.047% / PF 0.88 | 5: not better at stressed+late costs; 7: t 0.10 < noise floor 1.89 |
| H5 timing (entries 09:35-09:39) | 216 / +0.015% / PF 1.04 | 210 / -0.031% / PF 0.92 | 67 / +0.117% / PF 1.38 | 9 / +0.173% / PF 1.66 | -0.17 | 216 / -0.064% / PF 0.84 | 210 / -0.107% / PF 0.75 | 1: no validation gain; 3: profit factor lower; 4: gain rests on 2 trades; 5: not better at stressed+late costs; 6: train+val expectancy not positive |
| all five combined (information only - fewer than two passed): H1 + H2 + H3 + H4 + H5 | 53 / +0.162% / PF 1.46 | 43 / +0.043% / PF 1.12 | 13 / -0.153% / PF 0.59 | 0 | +1.08 | 53 / -0.010% / PF 0.97 | 43 / -0.030% / PF 0.92 | not eligible (fewer than two singles passed); 1: 43 validation trades; 4: gain rests on 2 trades; 7: t 1.08 < noise floor 1.89 |

Cells: trades / expectancy / profit factor.

Promoted (passes 1-7 and test and forward both positive and >= baseline): none.

## 6. Stocks-in-Play candidate re-check (top 10 by opening relative volume)

### realistic costs

| | trades | win % (won/lost) | expectancy (account %/trade) | PF | cumulative | max DD | avg win / loss | avg stock move | t |
|---|---|---|---|---|---|---|---|---|---|
| train | 591 | 44.5% (263/328) | +0.019% | 1.05 | +11.2% | 26.8% | +0.88% / -0.67% | +0.056% | +0.49 |
| val | 593 | 46.2% (274/319) | +0.026% | 1.07 | +15.7% | 24.5% | +0.87% / -0.70% | +0.055% | +0.68 |
| test | 200 | 50.5% (101/99) | +0.143% | 1.54 | +28.5% | 3.5% | +0.81% / -0.53% | +0.361% | +2.35 |
| forward | 37 | 35.1% (13/24) | -0.228% | 0.54 | -8.4% | 8.4% | +0.75% / -0.76% | -0.474% | -1.64 |
| train+val | 1184 | 45.4% (537/647) | +0.023% | 1.06 | +26.9% | 33.4% | +0.88% / -0.68% | +0.056% | +0.83 |
| all | 1421 | 45.8% (651/770) | +0.033% | 1.09 | +47.0% | 33.4% | +0.86% / -0.67% | +0.085% | +1.34 |

### stressed costs

| | trades | win % (won/lost) | expectancy (account %/trade) | PF | cumulative | max DD | avg win / loss | avg stock move | t |
|---|---|---|---|---|---|---|---|---|---|
| train | 591 | 42.0% (248/343) | -0.047% | 0.88 | -27.5% | 39.5% | +0.84% / -0.68% | -0.045% | -1.24 |
| val | 593 | 44.5% (264/329) | -0.033% | 0.92 | -19.9% | 30.7% | +0.83% / -0.73% | -0.045% | -0.88 |
| test | 200 | 50.0% (100/100) | +0.094% | 1.34 | +18.9% | 4.2% | +0.75% / -0.56% | +0.270% | +1.59 |
| forward | 37 | 32.4% (12/25) | -0.279% | 0.46 | -10.3% | 10.3% | +0.72% / -0.76% | -0.572% | -2.07 |
| train+val | 1184 | 43.2% (512/672) | -0.040% | 0.90 | -47.4% | 67.9% | +0.83% / -0.70% | -0.045% | -1.50 |
| all | 1421 | 43.9% (624/797) | -0.027% | 0.93 | -38.8% | 67.9% | +0.82% / -0.69% | -0.015% | -1.13 |

### stressed+late costs

| | trades | win % (won/lost) | expectancy (account %/trade) | PF | cumulative | max DD | avg win / loss | avg stock move | t |
|---|---|---|---|---|---|---|---|---|---|
| train | 591 | 43.0% (254/337) | -0.023% | 0.94 | -13.4% | 29.3% | +0.86% / -0.69% | -0.031% | -0.59 |
| val | 593 | 43.8% (260/333) | -0.046% | 0.89 | -27.4% | 31.9% | +0.82% / -0.72% | -0.064% | -1.23 |
| test | 200 | 48.0% (96/104) | +0.074% | 1.25 | +14.7% | 5.1% | +0.77% / -0.57% | +0.230% | +1.24 |
| forward | 37 | 32.4% (12/25) | -0.263% | 0.50 | -9.7% | 9.7% | +0.82% / -0.78% | -0.497% | -1.79 |
| train+val | 1184 | 43.4% (514/670) | -0.034% | 0.91 | -40.8% | 54.1% | +0.84% / -0.70% | -0.047% | -1.28 |
| all | 1421 | 43.8% (622/799) | -0.025% | 0.93 | -35.9% | 54.1% | +0.83% / -0.69% | -0.020% | -1.04 |

Untouched train year: FAILS (not positive at 0.05%, or negative at 0.10%). The forward paper criterion is checked in reports/audit_baseline.md.

## 7. Live ledger vs this backtest on the forward dates

| date | symbol | ledger side / entry / exit / result (source) | backtest side / entry / exit / result |
|---|---|---|---|
| 2026-10-06 | AMD | short 09:35 10:35 -1.02% (replay) | short 09:35 stop -1.02% |
| 2026-10-07 | AAPL | short 09:35 15:55 -0.66% (replay) | short 09:35 bell -0.66% |
| 2026-10-07 | MSFT | short 09:41 15:55 -0.60% (replay) | short 09:41 bell -0.60% |
| 2026-10-07 | TSLA | short 09:42 15:55 -0.16% (replay) | short 09:42 bell -0.16% |
| 2026-10-09 | NVDA | short 09:35 15:55 +0.53% (replay) | short 09:35 bell +0.53% |
| 2026-10-09 | TSLA | long 09:42 11:29 -1.03% (replay) | long 09:42 stop -1.03% |
| 2026-10-12 | META | long 09:37 15:55 +0.04% (replay) | long 09:37 bell +0.04% |
| 2026-10-13 | AAPL | short 09:40 15:55 +0.61% (replay) | short 09:40 bell +0.61% |
| 2026-10-14 | META | short 09:35 15:55 +0.91% (live) | short 09:35 bell +0.91% |
| 2026-10-15 | META | long 09:36 15:55 +0.43% (live) | long 09:36 bell +0.43% |
| 2026-10-15 | NVDA | long 09:42 09:55 -1.04% (live) | long 09:42 stop -1.04% |
| 2026-10-16 | AAPL | short 09:35 15:55 +0.06% (live) | short 09:35 bell +0.06% |
| 2026-10-16 | MSFT | short 09:37 11:56 +1.95% (live) | short 09:37 target +1.95% |

Ledger 13 trades, backtest 13, in both 13. Ledger total +0.02%, backtest total +0.02% (forward dates only).

