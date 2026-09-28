# Stocks in play — wide

1-minute bars · 52 trading days (2026-07-16 to 2026-09-28) · 103 symbols ranked

Opening-range break on the names with the most abnormal opening volume. No profit target — out at the stop or at the bell. Stop is a fraction of the 14-day ATR. Slippage **0.15% each way**, no leverage.

## Does choosing what to trade change anything?

| rule | trades | win % | won | lost | profit % | avg/trade |
|---|---|---|---|---|---|---|
| top5/atr0.5/both | 123 | 41.5% | 51 | 72 | -1.3% | -0.010% |
| top5/atr0.5/short | 56 | 44.6% | 25 | 31 | -2.7% | -0.048% |
| top5/atr0.35/both | 123 | 34.1% | 42 | 81 | -6.1% | -0.050% |
| top5/atr0.2/both | 123 | 22.8% | 28 | 95 | -14.8% | -0.120% |
| top5/atr0.35/short | 56 | 32.1% | 18 | 38 | -15.4% | -0.276% |
| top5/atr0.2/short | 56 | 25.0% | 14 | 42 | -17.4% | -0.312% |
| top20/atr0.5/short | 254 | 43.7% | 111 | 143 | -19.1% | -0.075% |
| top10/atr0.5/short | 120 | 40.0% | 48 | 72 | -22.7% | -0.189% |
| top10/atr0.5/both | 257 | 38.9% | 100 | 157 | -35.4% | -0.138% |
| top10/atr0.35/short | 120 | 31.7% | 38 | 82 | -41.5% | -0.346% |
| top20/atr0.35/short | 254 | 37.4% | 95 | 159 | -43.4% | -0.171% |
| top10/atr0.35/both | 257 | 32.3% | 83 | 174 | -54.2% | -0.211% |
| top10/atr0.2/short | 120 | 21.7% | 26 | 94 | -64.9% | -0.541% |
| top20/atr0.5/both | 538 | 39.4% | 212 | 326 | -65.5% | -0.122% |
| top20/atr0.35/both | 538 | 34.4% | 185 | 353 | -91.0% | -0.169% |
| top20/atr0.2/short | 254 | 25.2% | 64 | 190 | -91.8% | -0.361% |
| top10/atr0.2/both | 257 | 21.8% | 56 | 201 | -93.0% | -0.362% |
| top20/atr0.2/both | 538 | 23.0% | 124 | 414 | -177.5% | -0.330% |
| topALL/atr0.5/short | 1437 | 40.6% | 584 | 853 | -259.3% | -0.180% |
| topALL/atr0.35/short | 1437 | 36.5% | 525 | 912 | -364.2% | -0.253% |
| topALL/atr0.5/both | 2698 | 38.2% | 1031 | 1667 | -568.1% | -0.211% |
| topALL/atr0.2/short | 1437 | 25.9% | 372 | 1065 | -613.0% | -0.427% |
| topALL/atr0.35/both | 2698 | 34.1% | 920 | 1778 | -766.9% | -0.284% |
| topALL/atr0.2/both | 2698 | 24.2% | 654 | 2044 | -1209.4% | -0.448% |

## The best one, then the same rule on dates it never saw

**top5/atr0.5/both**

| rule | trades | win % | won | lost | profit % | avg/trade |
|---|---|---|---|---|---|---|
| explore | 123 | 41.5% | 51 | 72 | -1.3% | -0.010% |
| holdout (unseen) | 73 | 53.4% | 39 | 34 | +5.9% | +0.081% |

Against the same rule with NO selection, on the explore split:

| rule | trades | win % | won | lost | profit % | avg/trade |
|---|---|---|---|---|---|---|
| topALL/atr0.5/both | 2698 | 38.2% | 1031 | 1667 | -568.1% | -0.211% |
| top5/atr0.5/both | 123 | 41.5% | 51 | 72 | -1.3% | -0.010% |

## Verdict

- **Holds up on dates it never saw.** First time in this project. It still needs a forward record before it sizes a position.

## By side

| rule | trades | win % | won | lost | profit % | avg/trade |
|---|---|---|---|---|---|---|
| short | 100 | 49.0% | 49 | 51 | +1.1% | +0.011% |
| long | 96 | 42.7% | 41 | 55 | +3.6% | +0.037% |

## How trades ended

| rule | trades | win % | won | lost | profit % | avg/trade |
|---|---|---|---|---|---|---|
| stop | 73 | 0.0% | 0 | 73 | -80.7% | -1.106% |
| close | 123 | 73.2% | 90 | 33 | +85.4% | +0.694% |

## How much cost does it survive?

`` over every date, costs varied:

| rule | trades | win % | won | lost | profit % | avg/trade |
|---|---|---|---|---|---|---|
| slippage 0.00% each way | 196 | 52.0% | 102 | 94 | +47.1% | +0.240% |
| slippage 0.05% each way | 196 | 50.5% | 99 | 97 | +31.4% | +0.160% |
| slippage 0.10% each way | 196 | 48.5% | 95 | 101 | +19.3% | +0.098% |
| slippage 0.15% each way | 196 | 45.9% | 90 | 106 | +4.7% | +0.024% |
| slippage 0.25% each way | 196 | 40.3% | 79 | 117 | -26.2% | -0.134% |
| slippage 0.50% each way | 196 | 27.6% | 54 | 142 | -111.2% | -0.567% |

- **It stops making money at slippage 0.25% each way.** Our backtest assumes 0.05%. The gap between those two numbers is the entire result.
