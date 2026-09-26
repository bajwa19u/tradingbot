# Break-and-retest backtest

**Period:** 2023-01-01 → today  
**Symbols:** TSLA, NVDA, AAPL, AMD  
**Timeframe:** 5-minute  
**Target:** 2.0R, risking 1.0% of $10,000  
**Generated:** 2026-09-26 13:09

## Headline

| Metric | Value |
|---|---|
| Trades | 405 over 935 days (0.43/day) |
| Win rate | 21.0% |
| Expectancy | -0.036R per trade |
| Total | -14.58R · $-283.62 (-2.84%) |
| Profit factor | 0.97 |
| Max drawdown | -10.41% |
| Avg win / avg loss | 1.412R / -0.421R |
| Worst losing streak | 15 |
| Avg hold | 10.7 bars |

## How trades ended

- **breakeven** — 199 (49%)
- **stop** — 118 (29%)
- **target** — 66 (16%)
- **time_stop** — 15 (4%)
- **trail** — 7 (2%)

## Why setups were rejected

_This is the filter doing its job — high counts here are healthy._

- `break_volume_too_low` — 8217
- `no_confirmation_candle` — 3937
- `no_displacement_before_retest` — 1362
- `entry_window_closed` — 1074
- `failed_break` — 906
- `retest_never_came` — 825
- `opening_range_too_wide` — 418
- `below_vwap_for_long` — 15
- `above_vwap_for_short` — 15

## Was the stop in the right place?

_MAE = how far a trade went against you before resolving. It is the standard way to test stop placement._

| Measure | Value | What it means |
|---|---|---|
| Median stop distance | 0.0% of price | how much room each trade got |
| Winners' typical heat | 0.199R | half of winners never went further against you than this |
| Winners' worst heat (90th pct) | 0.781R | 9 in 10 winners stayed inside this |
| Deepest winner | 0.961R | the single winner that came closest to being stopped |
| Losers' best moment (median) | 0.433R | how far losers got in your favour before failing |
| Losers' best moment (75th pct) | 0.677R | a quarter of losers got at least this far |

**Tightening the stop would have cost you:**

- a stop at 0.5R would have killed **15** of 85 winners (18%)
- a stop at 0.7R would have killed **11** of 85 winners (13%)
- a stop at 0.8R would have killed **7** of 85 winners (8%)

_Read it this way: if winners rarely take much heat, the stop is wider than it needs to be and can be tightened for smaller losses and bigger size. If losers routinely reach 1R+ in your favour before failing, the problem is the exit, not the stop._


## Where the money actually goes

_Buckets with n < 20 are marked unreliable - slicing enough ways always finds a flattering subset by chance._

### By entry hour (ET)

| Bucket | n | Expectancy | Win rate | Total R | |
|---|---|---|---|---|---|
| 10:00-10:59 | 220 | -0.021R | 21.4% | -4.6 |  |
| 11:00-11:59 | 16 | -0.323R | 25.0% | -5.2 | low n |
| 09:00-09:59 | 169 | -0.029R | 20.1% | -4.8 |  |

### By direction

| Bucket | n | Expectancy | Win rate | Total R | |
|---|---|---|---|---|---|
| long | 203 | -0.036R | 19.7% | -7.2 |  |
| short | 202 | -0.036R | 22.3% | -7.3 |  |

### By confirmation pattern

| Bucket | n | Expectancy | Win rate | Total R | |
|---|---|---|---|---|---|
| bearish_engulfing@fvg | 23 | +0.264R | 39.1% | +6.1 |  |
| bearish_engulfing@level | 89 | -0.098R | 18.0% | -8.8 |  |
| bullish_engulfing@fvg | 25 | +0.037R | 24.0% | +0.9 |  |
| bullish_engulfing@level | 82 | -0.017R | 22.0% | -1.4 |  |
| hammer@fvg | 15 | +0.158R | 26.7% | +2.4 | low n |
| hammer@level | 81 | -0.113R | 14.8% | -9.1 |  |
| shooting_star@fvg | 28 | -0.039R | 21.4% | -1.1 |  |
| shooting_star@level | 62 | -0.057R | 22.6% | -3.6 |  |

### By bars between break and retest

| Bucket | n | Expectancy | Win rate | Total R | |
|---|---|---|---|---|---|
| 1 | 51 | -0.137R | 13.7% | -7.0 |  |
| 2 | 112 | +0.004R | 22.3% | +0.4 |  |
| 3 | 66 | -0.091R | 19.7% | -6.0 |  |
| 4 | 50 | -0.042R | 22.0% | -2.1 |  |
| 5 | 49 | +0.179R | 28.6% | +8.8 |  |
| 6+ | 77 | -0.112R | 19.5% | -8.7 |  |

### By symbol

| Bucket | n | Expectancy | Win rate | Total R | |
|---|---|---|---|---|---|
| AAPL | 95 | -0.113R | 17.9% | -10.7 |  |
| AMD | 105 | +0.187R | 31.4% | +19.7 |  |
| NVDA | 103 | -0.165R | 17.5% | -17.0 |  |
| TSLA | 102 | -0.064R | 16.7% | -6.5 |  |


## Last 15 trades

| Symbol | Dir | Entry time | Entry | Exit | R | Exit reason |
|---|---|---|---|---|---|---|
| TSLA | long | 2026-08-06T10:00 | 320.17 | 320.07 | -0.04 | breakeven |
| NVDA | short | 2026-08-11T10:15 | 219.28 | 219.35 | -0.04 | breakeven |
| TSLA | long | 2026-08-13T09:45 | 330.74 | 334.24 | +1.46 | target |
| TSLA | long | 2026-08-14T09:40 | 347.71 | 347.61 | -0.04 | breakeven |
| AAPL | long | 2026-08-18T10:25 | 309.74 | 309.65 | -0.05 | breakeven |
| AAPL | long | 2026-08-19T09:45 | 313.04 | 316.21 | +1.46 | target |
| AMD | short | 2026-08-21T09:45 | 472.58 | 468.56 | +1.45 | target |
| NVDA | short | 2026-08-26T10:50 | 211.02 | 211.08 | -0.08 | breakeven |
| AAPL | long | 2026-08-27T10:45 | 313.59 | 313.50 | -0.05 | breakeven |
| AAPL | short | 2026-09-02T09:45 | 324.46 | 324.56 | -0.07 | breakeven |
| NVDA | long | 2026-09-04T09:45 | 234.18 | 234.11 | -0.04 | breakeven |
| AMD | long | 2026-09-04T10:35 | 470.28 | 470.14 | -0.04 | breakeven |
| TSLA | long | 2026-09-11T09:45 | 367.64 | 363.26 | -1.03 | stop |
| AMD | long | 2026-09-15T10:20 | 508.91 | 506.10 | -1.06 | stop |
| AMD | long | 2026-09-22T10:20 | 617.37 | 617.18 | -0.05 | breakeven |