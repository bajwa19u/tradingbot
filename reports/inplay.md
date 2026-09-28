# Stocks in play — wide

1-minute bars · 52 trading days (2026-07-16 to 2026-09-28) · 103 symbols ranked

Opening-range break on the names with the most abnormal opening volume. No profit target — out at the stop or at the bell. Stop is a fraction of the 14-day ATR. Slippage 0.05% each way, no leverage.

## Does choosing what to trade change anything?

| rule | trades | win % | won | lost | profit % | avg/trade |
|---|---|---|---|---|---|---|
| top5/atr0.05/both | 123 | 8.9% | 11 | 112 | +66.1% | +0.538% |
| top5/atr0.1/both | 123 | 14.6% | 18 | 105 | +29.4% | +0.239% |
| top20/atr0.05/both | 538 | 9.5% | 51 | 487 | +21.7% | +0.040% |
| top5/atr0.2/both | 123 | 26.0% | 32 | 91 | +20.6% | +0.167% |
| top5/atr0.2/short | 56 | 30.4% | 17 | 39 | +0.5% | +0.008% |
| top20/atr0.1/both | 538 | 16.4% | 88 | 450 | +0.1% | +0.000% |
| top20/atr0.2/both | 538 | 28.3% | 152 | 386 | -6.0% | -0.011% |
| top10/atr0.05/both | 257 | 8.6% | 22 | 235 | -11.7% | -0.045% |
| top20/atr0.2/short | 254 | 29.9% | 76 | 178 | -15.1% | -0.059% |
| top10/atr0.1/both | 257 | 14.8% | 38 | 219 | -17.4% | -0.068% |
| top10/atr0.2/both | 257 | 25.7% | 66 | 191 | -18.1% | -0.070% |
| top5/atr0.1/short | 56 | 14.3% | 8 | 48 | -18.3% | -0.327% |
| top10/atr0.2/short | 120 | 26.7% | 32 | 88 | -27.3% | -0.228% |
| top20/atr0.1/short | 254 | 16.9% | 43 | 211 | -29.7% | -0.117% |
| top5/atr0.05/short | 56 | 5.4% | 3 | 53 | -38.6% | -0.690% |
| top10/atr0.1/short | 120 | 11.7% | 14 | 106 | -69.1% | -0.576% |
| top20/atr0.05/short | 254 | 7.5% | 19 | 235 | -105.8% | -0.417% |
| top10/atr0.05/short | 120 | 4.2% | 5 | 115 | -109.5% | -0.913% |
| topALL/atr0.2/short | 1437 | 31.5% | 453 | 984 | -155.7% | -0.108% |
| topALL/atr0.2/both | 2698 | 29.5% | 795 | 1903 | -359.7% | -0.133% |
| topALL/atr0.1/short | 1437 | 16.4% | 235 | 1202 | -400.7% | -0.279% |
| topALL/atr0.05/short | 1437 | 8.6% | 123 | 1314 | -597.9% | -0.416% |
| topALL/atr0.1/both | 2698 | 16.5% | 445 | 2253 | -598.7% | -0.222% |
| topALL/atr0.05/both | 2698 | 9.2% | 248 | 2450 | -748.1% | -0.277% |

## The best one, then the same rule on dates it never saw

**top5/atr0.05/both**

| rule | trades | win % | won | lost | profit % | avg/trade |
|---|---|---|---|---|---|---|
| explore | 123 | 8.9% | 11 | 112 | +66.1% | +0.538% |
| holdout (unseen) | 73 | 9.6% | 7 | 66 | +32.8% | +0.449% |

Against the same rule with NO selection, on the explore split:

| rule | trades | win % | won | lost | profit % | avg/trade |
|---|---|---|---|---|---|---|
| topALL/atr0.05/both | 2698 | 9.2% | 248 | 2450 | -748.1% | -0.277% |
| top5/atr0.05/both | 123 | 8.9% | 11 | 112 | +66.1% | +0.538% |

## Verdict

- **Holds up on dates it never saw.** First time in this project. It still needs a forward record before it sizes a position.

## By side

| rule | trades | win % | won | lost | profit % | avg/trade |
|---|---|---|---|---|---|---|
| short | 100 | 7.0% | 7 | 93 | -19.3% | -0.193% |
| long | 96 | 11.5% | 11 | 85 | +118.2% | +1.232% |

## How trades ended

| rule | trades | win % | won | lost | profit % | avg/trade |
|---|---|---|---|---|---|---|
| stop | 178 | 0.0% | 0 | 178 | -241.3% | -1.356% |
| close | 18 | 100.0% | 18 | 0 | +340.2% | +18.900% |
