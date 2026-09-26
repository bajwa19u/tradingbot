# Self-improving loop — holdout universe

**Symbols:** 30 · **From:** 2024-01-01 · **Refits:** every 21 trading days on a 252-day lookback  
**Generated:** 2026-09-26 23:36

Every ADAPTIVE trade was chosen by data that ended before the trade began. Nothing here is fitted to the trades it is judged on.

| | Trades | Expectancy | Total R | Win % | Max DD |
|---|---|---|---|---|---|
| **ADAPTIVE** (refits itself) | 223 | **-0.3675R** | -82.0 | 20.6 | -56.84% |
| STATIC (`ema10_tgt3.0_stop0.3_slope2.0`, never changes) | 288 | +0.0915R | +26.4 | 45.8 | -20.74% |
| HINDSIGHT (`ema20_tgt2.0_trail0_stop1.0`, unknowable at the time) | 212 | +0.1366R | +29.0 | 42.0 | -22.6% |

## Does refitting help?

**No — adaptive LOST to static by -0.4590R per trade.** The loop chased configurations that had just had a good run and then stopped working. This is the expected failure of performance chasing, and it is the reason to measure it rather than assume it.

_HINDSIGHT is what the best fixed config would have returned if you had known in advance which one it was. It is not achievable; it is there to show how much of the gap is foresight rather than method._

## What it chose, and what happened next

| Refit | Chose | Fit expectancy | Forward expectancy | Forward trades |
|---|---|---|---|---|
| 2024-01-02 | `ema10_tgt3.0_stop0.3_slope2.0` | +0.342R | **-0.397R** | 14 |
| 2024-02-01 | `ema10_tgt3.0_stop0.3_slope2.0` | +0.253R | **+1.176R** | 3 |
| 2024-03-04 | `ema10_tgt3.0_stop0.3_slope2.0` | +0.414R | **+0.286R** | 6 |
| 2024-04-03 | `ema10_tgt3.0_trail0_stop0.5` | +0.794R | **-1.023R** | 15 |
| 2024-05-02 | `ema10_tgt3.0_trail0_stop0.5` | +0.696R | **-0.225R** | 10 |
| 2024-06-03 | `ema10_tgt3.0_trail0_stop0.5` | +0.751R | **-1.021R** | 4 |
| 2024-07-03 | `ema10_tgt3.0_trail0_stop0.3` | +0.571R | **+0.980R** | 10 |
| 2024-08-02 | `ema10_tgt2.0_trail0_stop1.0` | +0.491R | **+1.988R** | 1 |
| 2024-09-03 | `ema10_tgt3.0_trail0_stop1.0` | +0.655R | **-1.020R** | 2 |
| 2024-10-02 | `ema10_tgt3.0_trail0_stop1.0` | +0.824R | **-1.018R** | 5 |
| 2024-10-31 | `ema10_tgt3.0_trail0_stop0.5` | +0.901R | **+2.316R** | 6 |
| 2024-12-02 | `ema10_tgt3.0_trail0_stop1.0` | +0.782R | **-1.016R** | 11 |
| 2025-01-02 | `ema20_tgt0.0_stop0.5_slope1.0` | +0.477R | **+0.000R** | 0 |
| 2025-02-04 | `ema10_tgt2.0_trail0_stop1.0` | +0.516R | **-1.009R** | 8 |
| 2025-03-06 | `ema20_tgt0.0_trail1_stop0.3` | +0.451R | **-0.094R** | 2 |
| 2025-04-04 | `ema20_tgt0.0_trail1_stop0.3` | +0.157R | **-0.925R** | 3 |
| 2025-05-06 | `ema20_tgt0.0_stop0.5_slope1.0` | +0.331R | **-0.846R** | 2 |
| 2025-06-05 | `ema20_tgt0.0_stop0.5_slope0.5` | +0.274R | **-1.025R** | 8 |
| 2025-07-08 | `ema20_tgt0.0_trail1_stop1.0` | +0.356R | **-0.671R** | 6 |
| 2025-08-06 | `ema10_tgt3.0_trail0_stop0.5` | +0.272R | **+0.000R** | 0 |
| 2025-09-05 | `ema10_tgt2.0_trail0_stop0.5` | +0.167R | **-0.267R** | 12 |
| 2025-10-06 | `ema10_tgt3.0_trail0_stop0.5` | +0.087R | **-1.013R** | 13 |
| 2025-11-04 | `ema20_tgt3.0_trail0_stop0.5` | +0.154R | **+0.183R** | 10 |
| 2025-12-04 | `ema10_tgt3.0_stop0.3_slope0.5` | -0.054R | **+0.222R** | 8 |
| 2026-01-06 | `ema10_tgt2.0_trail0_stop1.0` | +0.149R | **-1.010R** | 5 |
| 2026-02-05 | `ema10_tgt2.0_trail0_stop0.5` | +0.219R | **-0.261R** | 8 |
| 2026-03-09 | `ema10_tgt3.0_trail0_stop0.5` | +0.345R | **-1.013R** | 3 |
| 2026-04-08 | `ema10_tgt3.0_trail0_stop0.5` | +0.306R | **-1.012R** | 7 |
| 2026-05-07 | `ema10_tgt3.0_stop0.3_slope2.0` | +0.203R | **+0.064R** | 6 |
| 2026-06-08 | `ema10_tgt3.0_trail0_stop1.0` | +0.250R | **-1.005R** | 2 |
| 2026-07-09 | `ema10_tgt3.0_stop0.3_slope2.0` | +0.158R | **+0.863R** | 10 |
| 2026-08-07 | `ema10_tgt3.0_stop0.3_slope2.0` | +0.163R | **-0.804R** | 15 |
| 2026-09-08 | `ema10_tgt3.0_trail1_stop0.3` | +0.133R | **-0.915R** | 8 |

_The gap between the fit column and the forward column is the cost of selection. If fit is consistently high and forward consistently low, the search is finding noise._