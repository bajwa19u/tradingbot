# Break-and-retest backtest

**Period:** 2024-01-01 → today  
**Symbols:** TSLA, NVDA, AAPL, AMD  
**Timeframe:** 5-minute  
**Target:** 2.0R, risking 1.0% of $10,000  
**Generated:** 2026-09-25 20:36

## Headline

| Metric | Value |
|---|---|
| Trades | 236 over 685 days (0.34/day) |
| Win rate | 19.5% |
| Expectancy | -0.06R per trade |
| Total | -14.17R · $-626.58 (-6.27%) |
| Profit factor | 0.87 |
| Max drawdown | -9.2% |
| Avg win / avg loss | 1.455R / -0.427R |
| Worst losing streak | 14 |
| Avg hold | 7.5 bars |

## How trades ended

- **breakeven** — 119 (50%)
- **stop** — 71 (30%)
- **target** — 37 (16%)
- **trail** — 6 (3%)
- **time_stop** — 3 (1%)

## Why setups were rejected

_This is the filter doing its job — high counts here are healthy._

- `break_volume_too_low` — 6149
- `no_confirmation_candle` — 1889
- `no_displacement_before_retest` — 948
- `entry_window_closed` — 838
- `failed_break` — 642
- `retest_never_came` — 620
- `opening_range_too_wide` — 344
- `above_vwap_for_short` — 11
- `below_vwap_for_long` — 9

## Where the money actually goes

_Buckets with n < 20 are marked unreliable - slicing enough ways always finds a flattering subset by chance._

### By entry hour (ET)

| Bucket | n | Expectancy | Win rate | Total R | |
|---|---|---|---|---|---|
| 10:00-10:59 | 121 | -0.034R | 19.8% | -4.0 |  |
| 11:00-11:59 | 8 | -0.323R | 25.0% | -2.6 | low n |
| 09:00-09:59 | 107 | -0.070R | 18.7% | -7.5 |  |

### By direction

| Bucket | n | Expectancy | Win rate | Total R | |
|---|---|---|---|---|---|
| long | 128 | -0.075R | 19.5% | -9.5 |  |
| short | 108 | -0.043R | 19.4% | -4.6 |  |

### By confirmation pattern

| Bucket | n | Expectancy | Win rate | Total R | |
|---|---|---|---|---|---|
| bearish_engulfing | 61 | -0.123R | 16.4% | -7.5 |  |
| bullish_engulfing | 62 | +0.009R | 25.8% | +0.5 |  |
| hammer | 66 | -0.153R | 13.6% | -10.1 |  |
| shooting_star | 47 | +0.061R | 23.4% | +2.9 |  |

### By bars between break and retest

| Bucket | n | Expectancy | Win rate | Total R | |
|---|---|---|---|---|---|
| 1 | 22 | -0.142R | 22.7% | -3.1 |  |
| 2 | 70 | -0.135R | 15.7% | -9.5 |  |
| 3 | 37 | +0.039R | 24.3% | +1.4 |  |
| 4 | 27 | -0.166R | 14.8% | -4.5 |  |
| 5 | 28 | +0.161R | 25.0% | +4.5 |  |
| 6+ | 52 | -0.058R | 19.2% | -3.0 |  |

### By symbol

| Bucket | n | Expectancy | Win rate | Total R | |
|---|---|---|---|---|---|
| AAPL | 55 | -0.137R | 18.2% | -7.5 |  |
| AMD | 62 | +0.055R | 22.6% | +3.4 |  |
| NVDA | 58 | -0.155R | 17.2% | -9.0 |  |
| TSLA | 61 | -0.018R | 19.7% | -1.1 |  |


## Last 15 trades

| Symbol | Dir | Entry time | Entry | Exit | R | Exit reason |
|---|---|---|---|---|---|---|
| AMD | long | 2026-08-04T10:10 | 515.42 | 515.27 | -0.03 | breakeven |
| NVDA | long | 2026-08-05T09:55 | 221.21 | 221.14 | -0.03 | breakeven |
| TSLA | long | 2026-08-06T10:00 | 320.17 | 320.07 | -0.04 | breakeven |
| NVDA | short | 2026-08-11T10:15 | 219.28 | 219.35 | -0.04 | breakeven |
| TSLA | long | 2026-08-13T09:45 | 330.74 | 334.24 | +1.46 | target |
| TSLA | long | 2026-08-14T09:40 | 347.71 | 347.61 | -0.04 | breakeven |
| AAPL | long | 2026-08-19T09:45 | 313.04 | 316.21 | +1.46 | target |
| AMD | short | 2026-08-21T09:45 | 472.58 | 468.56 | +1.45 | target |
| NVDA | short | 2026-08-26T10:50 | 211.02 | 211.08 | -0.08 | breakeven |
| AAPL | short | 2026-09-02T09:45 | 324.46 | 324.56 | -0.07 | breakeven |
| NVDA | long | 2026-09-04T09:45 | 234.18 | 234.11 | -0.04 | breakeven |
| AMD | long | 2026-09-04T10:35 | 470.28 | 470.14 | -0.04 | breakeven |
| TSLA | long | 2026-09-11T09:45 | 367.64 | 363.26 | -1.03 | stop |
| AMD | long | 2026-09-15T10:20 | 508.91 | 506.10 | -1.06 | stop |
| AMD | long | 2026-09-22T10:20 | 617.37 | 617.18 | -0.05 | breakeven |