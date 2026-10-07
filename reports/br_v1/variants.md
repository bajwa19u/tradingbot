# Break & Retest V1 — variant test

14 variants fixed before the run. A change has to beat the baseline in BOTH halves; with 14 looks, anything under about 2.3 standard errors is noise. Account % assumes 1% risked per trade (simple sum). Nothing here changes the live settings.

| variant | half | trades | win % | account % | avg account % per trade | t vs baseline | verdict |
|---|---|---|---|---|---|---|---|
| **baseline (V1)** | in-sample | 3229 | 37.1% | -42.5% | -0.013% |  |  |
|  | out-of-sample | 2174 | 35.6% | -136.3% | -0.063% |  |  |
| **exits** (same trades) | | | | | | | |
| exit at 60m close | in-sample | 3229 | 40.9% | -70.2% | -0.022% | -0.8 | rejected (not better in both halves) |
|  | out-of-sample | 2174 | 39.2% | -116.3% | -0.053% | +0.7 |  |
| exit at 60m close if in profit | in-sample | 3229 | 44.8% | -67.1% | -0.021% | -0.8 | rejected (not better in both halves) |
|  | out-of-sample | 2174 | 43.1% | -125.6% | -0.058% | +0.4 |  |
| stop to breakeven at 60m if in profit | in-sample | 3229 | 30.9% | -35.6% | -0.011% | +0.3 | better in both halves, still losing - within noise |
|  | out-of-sample | 2174 | 29.6% | -132.9% | -0.061% | +0.2 |  |
| exit at 120m close | in-sample | 3229 | 38.4% | -101.7% | -0.031% | -2.2 | rejected (not better in both halves) |
|  | out-of-sample | 2174 | 37.9% | -125.9% | -0.058% | +0.5 |  |
| exit at 120m close if in profit | in-sample | 3229 | 41.4% | -61.1% | -0.019% | -0.9 | rejected (not better in both halves) |
|  | out-of-sample | 2174 | 40.3% | -121.5% | -0.056% | +0.8 |  |
| stop to breakeven at 120m if in profit | in-sample | 3229 | 33.1% | -44.1% | -0.014% | -0.1 | rejected (not better in both halves) |
|  | out-of-sample | 2174 | 31.1% | -135.5% | -0.062% | +0.1 |  |
| exit at 180m close | in-sample | 3229 | 38.2% | -72.3% | -0.022% | -1.4 | rejected (not better in both halves) |
|  | out-of-sample | 2174 | 37.4% | -118.7% | -0.055% | +1.0 |  |
| exit at 180m close if in profit | in-sample | 3229 | 40.3% | -54.0% | -0.017% | -0.6 | rejected (not better in both halves) |
|  | out-of-sample | 2174 | 39.1% | -119.8% | -0.055% | +1.2 |  |
| stop to breakeven at 180m if in profit | in-sample | 3229 | 33.8% | -52.7% | -0.016% | -1.0 | rejected (not better in both halves) |
|  | out-of-sample | 2174 | 32.1% | -135.2% | -0.062% | +0.1 |  |
| **entries** (different trades) | | | | | | | |
| break closes >= 0.10% beyond | in-sample | 2779 | 35.6% | -122.1% | -0.044% | -0.9 | rejected (not better in both halves) |
|  | out-of-sample | 1872 | 35.5% | -103.3% | -0.055% | +0.2 |  |
| break closes >= 0.20% beyond | in-sample | 1954 | 36.5% | -23.5% | -0.012% | +0.0 | better in both halves, still losing - within noise |
|  | out-of-sample | 1357 | 35.2% | -59.8% | -0.044% | +0.4 |  |
| moves >= 0.20% away before retest | in-sample | 2948 | 36.6% | -48.9% | -0.017% | -0.1 | rejected (not better in both halves) |
|  | out-of-sample | 2001 | 36.1% | -86.2% | -0.043% | +0.5 |  |
| moves >= 0.40% away before retest | in-sample | 2343 | 36.4% | -19.8% | -0.008% | +0.1 | better in both halves, still losing - within noise |
|  | out-of-sample | 1604 | 34.4% | -93.9% | -0.059% | +0.1 |  |
| 0.10% close + 0.20% move away | in-sample | 2624 | 35.6% | -116.2% | -0.044% | -0.9 | rejected (not better in both halves) |
|  | out-of-sample | 1780 | 35.6% | -93.3% | -0.052% | +0.2 |  |