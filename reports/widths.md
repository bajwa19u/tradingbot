# Opening range, stop width and target

## Every stop width and target, 66 days (2026-06-26 to 2026-09-29)

Explore = first 44 days, holdout = last 22. Stop room is extra distance beyond the rule's own stop, as a percent of the entry price.

### Explore

| range | stop room | target | trades | win % | won | lost | avg win | avg loss | profit % |
|---|---|---|---|---|---|---|---|---|---|
| 5m | +0.0% | 2x | 480 | 45.8% | 220 | 260 | +0.99% | -0.83% | +0.6% |
| 5m | +0.0% | next level | 480 | 46.0% | 221 | 259 | +0.96% | -0.83% | -4.8% |
| 5m | +2.0% | 2x | 480 | 52.1% | 250 | 230 | +0.44% | -0.40% | +16.6% |
| 5m | +2.0% | next level | 480 | 52.1% | 250 | 230 | +0.43% | -0.40% | +15.8% |
| 15m | +0.0% | 2x | 445 | 45.2% | 201 | 244 | +0.70% | -0.66% | -20.6% |
| 15m | +0.0% | next level | 445 | 45.4% | 202 | 243 | +0.71% | -0.67% | -18.9% |
| 15m | +2.0% | 2x | 445 | 47.9% | 213 | 232 | +0.34% | -0.32% | -1.5% |
| 15m | +2.0% | next level | 445 | 47.9% | 213 | 232 | +0.34% | -0.32% | -1.5% |
| 30m | +0.0% | 2x | 375 | 45.3% | 170 | 205 | +0.54% | -0.54% | -18.0% |
| 30m | +0.0% | next level | 375 | 45.6% | 171 | 204 | +0.54% | -0.54% | -16.5% |
| 30m | +2.0% | 2x | 373 | 47.7% | 178 | 195 | +0.27% | -0.26% | -3.1% |
| 30m | +2.0% | next level | 373 | 47.7% | 178 | 195 | +0.27% | -0.26% | -3.1% |
| 60m | +0.0% | 2x | 286 | 42.7% | 122 | 164 | +0.42% | -0.43% | -20.0% |
| 60m | +0.0% | next level | 286 | 43.0% | 123 | 163 | +0.43% | -0.43% | -17.6% |
| 60m | +2.0% | 2x | 278 | 43.5% | 121 | 157 | +0.23% | -0.21% | -5.4% |
| 60m | +2.0% | next level | 278 | 43.5% | 121 | 157 | +0.23% | -0.21% | -5.4% |

### Holdout (never used to choose anything)

| range | stop room | target | trades | win % | won | lost | avg win | avg loss | profit % |
|---|---|---|---|---|---|---|---|---|---|
| 5m | +0.0% | 2x | 248 | 40.7% | 101 | 147 | +0.90% | -0.79% | -25.0% |
| 5m | +0.0% | next level | 248 | 41.1% | 102 | 146 | +0.91% | -0.79% | -22.6% |
| 5m | +2.0% | 2x | 248 | 46.4% | 115 | 133 | +0.32% | -0.34% | -8.7% |
| 5m | +2.0% | next level | 248 | 46.4% | 115 | 133 | +0.32% | -0.34% | -8.3% |
| 15m | +0.0% | 2x | 207 | 46.4% | 96 | 111 | +0.67% | -0.63% | -5.6% |
| 15m | +0.0% | next level | 207 | 46.4% | 96 | 111 | +0.66% | -0.63% | -6.5% |
| 15m | +2.0% | 2x | 207 | 47.8% | 99 | 108 | +0.27% | -0.27% | -1.7% |
| 15m | +2.0% | next level | 207 | 47.8% | 99 | 108 | +0.27% | -0.27% | -1.7% |
| 30m | +0.0% | 2x | 182 | 42.9% | 78 | 104 | +0.53% | -0.56% | -16.8% |
| 30m | +0.0% | next level | 182 | 42.9% | 78 | 104 | +0.52% | -0.56% | -17.0% |
| 30m | +2.0% | 2x | 182 | 44.0% | 80 | 102 | +0.23% | -0.24% | -6.2% |
| 30m | +2.0% | next level | 182 | 44.0% | 80 | 102 | +0.23% | -0.24% | -6.2% |
| 60m | +0.0% | 2x | 117 | 41.9% | 49 | 68 | +0.36% | -0.52% | -17.8% |
| 60m | +0.0% | next level | 117 | 41.9% | 49 | 68 | +0.34% | -0.52% | -18.8% |
| 60m | +2.0% | 2x | 117 | 41.9% | 49 | 68 | +0.17% | -0.26% | -9.2% |
| 60m | +2.0% | next level | 117 | 41.9% | 49 | 68 | +0.17% | -0.26% | -9.2% |

### Did the level target actually get used?

| stop room | trades aiming at a real level | of |
|---|---|---|
| +0.0% | 98 | 480 |
| +2.0% | 18 | 480 |

### What the extra room actually buys, at the live target

| stop room | losers rescued | losers made worse | net profit % |
|---|---|---|---|
| +2.0% | 33 | 0 | +16.0% |

### Verdict

- **Every combination loses money on the holdout**, the best being a 15m range with +2.0% room at 2.0 on -1.7%. Widening the stop rescues trades and costs more on the ones it does not rescue, and the two cancel. This is not the dial that is wrong.
