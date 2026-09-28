# Opening drive — core

1-minute bars · 66 trading days (2026-06-25 to 2026-09-28) · 12 symbols
Window 09:30–10:00 ET · levels: prior-day high/low/close and premarket high/low · hold limit 120 min · slippage 0.05% each way

## Does the free feed have a usable premarket?

- 792 symbol-days examined
- median premarket bars per day: **2**
- days with no premarket at all: 222
- days with fewer than 30 premarket bars: 783
- **1.1% of days have a usable premarket**

> The premarket on this feed is too thin to trust. Premarket levels are still tested below, but a result that depends on them is a result built on 2% of the volume.

## Every configuration, explore split only

| rule | trades | win % | won | lost | profit % | avg/trade |
|---|---|---|---|---|---|---|
| retest/level/3.0R/pen0.5 | 182 | 34.1% | 62 | 120 | +12.5% | +0.069% |
| retest/level/3.0R/pen0.0 | 182 | 33.5% | 61 | 121 | +8.6% | +0.047% |
| retest/level/2.0R/pen0.5 | 182 | 39.6% | 72 | 110 | +7.7% | +0.042% |
| drive/level/3.0R/pen0.5 | 303 | 35.6% | 108 | 195 | +4.4% | +0.015% |
| retest/level/1.5R/pen0.5 | 182 | 45.1% | 82 | 100 | +3.0% | +0.017% |
| retest/session/3.0R/pen0.5 | 182 | 42.9% | 78 | 104 | +3.0% | +0.016% |
| retest/level/2.0R/pen0.0 | 182 | 39.0% | 71 | 111 | +2.4% | +0.013% |
| retest/session/2.0R/pen0.5 | 182 | 44.0% | 80 | 102 | -1.1% | -0.006% |
| retest/session/3.0R/pen0.0 | 182 | 41.2% | 75 | 107 | -2.5% | -0.014% |
| retest/bar/3.0R/pen0.0 | 182 | 32.4% | 59 | 123 | -4.0% | -0.022% |
| retest/session/1.5R/pen0.5 | 182 | 45.1% | 82 | 100 | -7.0% | -0.038% |
| retest/level/1.5R/pen0.0 | 182 | 42.9% | 78 | 104 | -7.0% | -0.039% |
| retest/session/2.0R/pen0.0 | 182 | 41.8% | 76 | 106 | -10.3% | -0.057% |
| drive/session/3.0R/pen0.5 | 303 | 42.2% | 128 | 175 | -11.7% | -0.039% |
| drive/session/3.0R/pen0.0 | 345 | 40.6% | 140 | 205 | -12.0% | -0.035% |
| drive/level/2.0R/pen0.5 | 303 | 38.0% | 115 | 188 | -13.5% | -0.045% |
| retest/bar/3.0R/pen0.5 | 182 | 31.3% | 57 | 125 | -13.8% | -0.076% |
| retest/session/1.5R/pen0.0 | 182 | 42.9% | 78 | 104 | -15.1% | -0.083% |
| drive/session/2.0R/pen0.5 | 303 | 43.2% | 131 | 172 | -21.1% | -0.070% |
| drive/session/2.0R/pen0.0 | 345 | 42.0% | 145 | 200 | -22.6% | -0.066% |
| drive/session/1.5R/pen0.5 | 303 | 43.9% | 133 | 170 | -27.3% | -0.090% |
| retest/bar/2.0R/pen0.0 | 182 | 34.1% | 62 | 120 | -28.3% | -0.156% |
| retest/bar/2.0R/pen0.5 | 182 | 35.2% | 64 | 118 | -28.6% | -0.157% |
| drive/session/1.5R/pen0.0 | 345 | 42.9% | 148 | 197 | -30.4% | -0.088% |
| drive/level/3.0R/pen0.0 | 345 | 30.1% | 104 | 241 | -34.1% | -0.099% |
| retest/bar/1.5R/pen0.0 | 182 | 37.4% | 68 | 114 | -34.2% | -0.188% |
| drive/level/1.5R/pen0.5 | 303 | 39.9% | 121 | 182 | -35.1% | -0.116% |
| drive/level/2.0R/pen0.0 | 345 | 34.5% | 119 | 226 | -39.2% | -0.114% |
| retest/bar/1.5R/pen0.5 | 182 | 37.9% | 69 | 113 | -42.2% | -0.232% |
| drive/bar/3.0R/pen0.0 | 345 | 30.1% | 104 | 241 | -56.4% | -0.164% |
| drive/level/1.5R/pen0.0 | 345 | 37.7% | 130 | 215 | -61.0% | -0.177% |
| drive/bar/3.0R/pen0.5 | 303 | 27.7% | 84 | 219 | -79.2% | -0.261% |
| drive/bar/1.5R/pen0.5 | 303 | 34.7% | 105 | 198 | -83.9% | -0.277% |
| drive/bar/1.5R/pen0.0 | 345 | 35.7% | 123 | 222 | -86.3% | -0.250% |
| drive/bar/2.0R/pen0.0 | 345 | 31.9% | 110 | 235 | -89.0% | -0.258% |
| drive/bar/2.0R/pen0.5 | 303 | 29.4% | 89 | 214 | -100.9% | -0.333% |

## The best one, then the same rule on dates it never saw

**retest/level/3.0R/pen0.5**

| rule | trades | win % | won | lost | profit % | avg/trade |
|---|---|---|---|---|---|---|
| explore | 182 | 34.1% | 62 | 120 | +12.5% | +0.069% |
| holdout (unseen) | 87 | 26.4% | 23 | 64 | -18.2% | -0.209% |

- break-even win rate at 3.0R: **25.0%**
- best-of-36 noise floor on the explore split: **±8.59%** win rate

## Verdict

- **The best explore configuration loses money on unseen dates.** That is the signature of a fitted result, and it is the same thing every configuration search in this project has produced. Do not deploy it.

## By level — which price actually matters

| rule | trades | win % | won | lost | profit % | avg/trade |
|---|---|---|---|---|---|---|
| pdh | 74 | 31.1% | 23 | 51 | -3.5% | -0.047% |
| pdl | 72 | 25.0% | 18 | 54 | -12.3% | -0.171% |
| pdc | 123 | 35.8% | 44 | 79 | +10.2% | +0.083% |

## By side

| rule | trades | win % | won | lost | profit % | avg/trade |
|---|---|---|---|---|---|---|
| short | 141 | 29.8% | 42 | 99 | -5.8% | -0.041% |
| long | 128 | 33.6% | 43 | 85 | +0.1% | +0.001% |
