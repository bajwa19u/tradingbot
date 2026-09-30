# Opening range autopsy — fresh

3388 breaks · 97 trading days (2026-05-12 to 2026-09-29) · 15-minute range · +2.0% stop room

Every break the live rule takes, labelled at the live settings and then grouped. Nothing here is tuned; a difference between groups is a property of the market, not of a search.

## Overall

| group | trades | win % | won | lost | profit % | avg/trade |
|---|---|---|---|---|---|---|
| all breaks | 3388 | 47.9% | 1623 | 1765 | -36.9% | -0.011% |
| explore | 2286 | 49.0% | 1120 | 1166 | -18.6% | -0.008% |
| holdout | 1102 | 45.6% | 503 | 599 | -18.3% | -0.017% |

## How many names broke together

Same side, within 10 minutes. This is the 29 September question: is a break the whole sector is making at once worth less than one a single name is making alone?

| group | trades | win % | won | lost | profit % | avg/trade |
|---|---|---|---|---|---|---|
| 1 name | 95 | 52.6% | 50 | 45 | -2.0% | -0.021% |
| 2 name | 157 | 48.4% | 76 | 81 | -5.5% | -0.035% |
| 3–4 names | 339 | 38.9% | 132 | 207 | -28.4% | -0.084% |
| 5–7 names | 436 | 45.4% | 198 | 238 | -24.0% | -0.055% |
| 8–98 names | 2361 | 49.4% | 1167 | 1194 | +23.0% | +0.010% |

| group | trades | win % | won | lost | profit % | avg/trade |
|---|---|---|---|---|---|---|
| alone (cohort 1) | 95 | 52.6% | 50 | 45 | -2.0% | -0.021% |
| with the crowd | 3293 | 47.8% | 1573 | 1720 | -34.9% | -0.011% |

## When the break came

| group | trades | win % | won | lost | profit % | avg/trade |
|---|---|---|---|---|---|---|
| 10–20 min after the bell | 1066 | 48.4% | 516 | 550 | +0.6% | +0.001% |
| 20–30 min after the bell | 1014 | 48.1% | 488 | 526 | +1.5% | +0.002% |
| 30–45 min after the bell | 749 | 47.0% | 352 | 397 | -28.3% | -0.038% |
| 45–90 min after the bell | 559 | 47.8% | 267 | 292 | -10.7% | -0.019% |

## Direction

| group | trades | win % | won | lost | profit % | avg/trade |
|---|---|---|---|---|---|---|
| long | 1645 | 46.1% | 758 | 887 | -13.5% | -0.008% |
| short | 1743 | 49.6% | 865 | 878 | -23.4% | -0.013% |

| group | trades | win % | won | lost | profit % | avg/trade |
|---|---|---|---|---|---|---|
| with the gap | 1659 | 50.2% | 833 | 826 | +53.4% | +0.032% |
| against the gap | 1729 | 45.7% | 790 | 939 | -90.3% | -0.052% |

## Overnight gap

| group | trades | win % | won | lost | profit % | avg/trade |
|---|---|---|---|---|---|---|
| -99% to -2% | 573 | 48.3% | 277 | 296 | +8.1% | +0.014% |
| -2% to -0.5% | 883 | 45.5% | 402 | 481 | -30.9% | -0.035% |
| -0.5% to 0.5% | 726 | 47.0% | 341 | 385 | -25.1% | -0.035% |
| 0.5% to 2% | 641 | 49.3% | 316 | 325 | +7.0% | +0.011% |
| 2% to 99% | 565 | 50.8% | 287 | 278 | +3.9% | +0.007% |

## How wide the range was

| group | trades | win % | won | lost | profit % | avg/trade |
|---|---|---|---|---|---|---|
| 0.3%–0.6% of price | 3 | 66.7% | 2 | 1 | +0.7% | +0.230% |
| 0.6%–1% of price | 70 | 44.3% | 31 | 39 | -8.1% | -0.115% |
| 1%–2% of price | 751 | 48.2% | 362 | 389 | -7.9% | -0.011% |
| 2%–99% of price | 2564 | 47.9% | 1228 | 1336 | -21.6% | -0.008% |

## Volume behind the break

| group | trades | win % | won | lost | profit % | avg/trade |
|---|---|---|---|---|---|---|
| 0x–0.8x the range average | 1518 | 48.7% | 740 | 778 | -7.4% | -0.005% |
| 0.8x–1.2x the range average | 653 | 46.7% | 305 | 348 | -14.0% | -0.021% |
| 1.2x–2x the range average | 641 | 46.8% | 300 | 341 | -12.3% | -0.019% |
| 2x–4x the range average | 411 | 49.6% | 204 | 207 | -2.8% | -0.007% |
| 4x–999x the range average | 165 | 44.8% | 74 | 91 | -0.3% | -0.002% |

## Candidate filters, explore against holdout

A filter is only worth anything if it survives dates it was not chosen on. Both splits are shown side by side so a filter that only works on one cannot be presented as a finding.

| filter | explore trades | explore win % | explore profit % | holdout trades | holdout win % | holdout profit % |
|---|---|---|---|---|---|---|
| no filter (everything) | 2286 | 49.0% | -18.6% | 1102 | 45.6% | -18.3% |
| with the gap | 1103 | 50.4% | +26.4% | 556 | 49.8% | +27.0% |
| volume 1.2x+ | 816 | 47.7% | -9.6% | 401 | 47.1% | -5.8% |
| crowd of 5+ | 1907 | 49.3% | -4.6% | 890 | 47.6% | +3.6% |
| with the gap AND volume 1.2x+ | 421 | 48.7% | +1.8% | 215 | 52.6% | +11.7% |
| with the gap AND crowd of 5+ | 908 | 51.2% | +28.6% | 463 | 52.1% | +34.1% |

**Survives both splits:** with the gap (explore +26.4%, holdout +27.0%), with the gap AND volume 1.2x+ (explore +1.8%, holdout +11.7%), with the gap AND crowd of 5+ (explore +28.6%, holdout +34.1%)


## Which feature separates winners from losers at all

Pooled standard deviations between the winning and losing groups. Under about 0.3 is noise — that threshold has already retired two feature searches in this project.

| feature | separation |
|---|---|
| cohort | 0.192 |
| minute | 0.021 |
| gap | 0.019 |
| width | 0.006 |
| push | 0.002 |

## Verdict

- **Nothing separates them.** The strongest feature is cohort at 0.192 standard deviations, well inside noise. The losing trades are not distinguishable from the winning ones by anything measured here, which means no filter built from these features will help — including the cohort idea.
- The holdout loses -18.3%, so any filter has to do more than shuffle which losses are taken.
