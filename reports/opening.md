# Opening range breakout — core

1-minute bars · 66 trading days (2026-06-25 to 2026-09-28) · 12 symbols
Window 09:30–10:00 ET · levels: the session's own opening range · hold limit 120 min · slippage 0.05% each way

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
| drive/level/3.0R/OR15m | 320 | 30.9% | 99 | 221 | +4.1% | +0.013% |
| retest/session/2.0R/OR15m | 123 | 48.8% | 60 | 63 | +3.1% | +0.025% |
| retest/session/3.0R/OR15m | 123 | 48.8% | 60 | 63 | +2.3% | +0.019% |
| retest/session/1.5R/OR15m | 123 | 48.8% | 60 | 63 | +1.2% | +0.010% |
| retest/level/3.0R/OR15m | 123 | 31.7% | 39 | 84 | +0.7% | +0.006% |
| drive/session/3.0R/OR5m | 450 | 46.2% | 208 | 242 | -1.1% | -0.002% |
| drive/session/2.0R/OR5m | 450 | 46.2% | 208 | 242 | -4.5% | -0.010% |
| retest/session/2.0R/OR5m | 199 | 43.7% | 87 | 112 | -4.7% | -0.024% |
| retest/session/3.0R/OR5m | 199 | 43.7% | 87 | 112 | -4.7% | -0.024% |
| retest/session/1.5R/OR5m | 199 | 43.7% | 87 | 112 | -5.7% | -0.029% |
| retest/level/2.0R/OR15m | 123 | 35.8% | 44 | 79 | -9.8% | -0.080% |
| drive/session/1.5R/OR5m | 450 | 46.4% | 209 | 241 | -11.7% | -0.026% |
| drive/session/2.0R/OR15m | 320 | 44.1% | 141 | 179 | -12.4% | -0.039% |
| drive/session/1.5R/OR15m | 320 | 44.1% | 141 | 179 | -14.4% | -0.045% |
| drive/session/3.0R/OR15m | 320 | 44.1% | 141 | 179 | -16.1% | -0.050% |
| retest/level/1.5R/OR15m | 123 | 39.0% | 48 | 75 | -17.0% | -0.138% |
| retest/level/3.0R/OR5m | 199 | 26.6% | 53 | 146 | -25.3% | -0.127% |
| retest/level/2.0R/OR5m | 199 | 31.2% | 62 | 137 | -32.9% | -0.165% |
| drive/level/2.0R/OR15m | 320 | 33.8% | 108 | 212 | -37.5% | -0.117% |
| retest/level/1.5R/OR5m | 199 | 35.7% | 71 | 128 | -40.4% | -0.203% |
| drive/level/3.0R/OR5m | 450 | 28.9% | 130 | 320 | -46.5% | -0.103% |
| drive/level/1.5R/OR15m | 320 | 38.1% | 122 | 198 | -49.7% | -0.155% |
| drive/level/2.0R/OR5m | 450 | 33.6% | 151 | 299 | -62.5% | -0.139% |
| drive/level/1.5R/OR5m | 450 | 38.0% | 171 | 279 | -72.8% | -0.162% |

## The best one, then the same rule on dates it never saw

**drive/level/3.0R/OR15m**

| rule | trades | win % | won | lost | profit % | avg/trade |
|---|---|---|---|---|---|---|
| explore | 320 | 30.9% | 99 | 221 | +4.1% | +0.013% |
| holdout (unseen) | 133 | 27.1% | 36 | 97 | -30.4% | -0.229% |

- break-even win rate at 3.0R: **25.0%**
- best-of-24 noise floor on the explore split: **±6.1%** win rate

## Verdict

- **The best explore configuration loses money on unseen dates.** That is the signature of a fitted result, and it is the same thing every configuration search in this project has produced. Do not deploy it.
- The explore edge (30.9% versus 25.0% break-even) is inside the ±6.1% band that searching 24 configurations produces on random data.

## By level — which price actually matters

| rule | trades | win % | won | lost | profit % | avg/trade |
|---|---|---|---|---|---|---|
| orh | 234 | 28.2% | 66 | 168 | -32.0% | -0.137% |
| orl | 219 | 31.5% | 69 | 150 | +5.7% | +0.026% |

## By side

| rule | trades | win % | won | lost | profit % | avg/trade |
|---|---|---|---|---|---|---|
| short | 219 | 31.5% | 69 | 150 | +5.7% | +0.026% |
| long | 234 | 28.2% | 66 | 168 | -32.0% | -0.137% |
