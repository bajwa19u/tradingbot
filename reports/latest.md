# Break-and-retest backtest

**Period:** 2023-01-01 → today  
**Symbols:** TSLA, NVDA, AAPL, AMD  
**Timeframe:** 5-minute  
**Target:** 2.0R, risking 1.0% of $10,000  
**Generated:** 2026-10-17 13:23

## Headline

| Metric | Value |
|---|---|
| Trades | 411 over 950 days (0.43/day) |
| Win rate | 20.9% |
| Expectancy | -0.04R per trade |
| Total | -16.39R · $-449.12 (-4.49%) |
| Profit factor | 0.95 |
| Max drawdown | -10.97% |
| Avg win / avg loss | 1.412R / -0.424R |
| Worst losing streak | 15 |
| Avg hold | 10.6 bars |

## How trades ended

- **breakeven** — 201 (49%)
- **stop** — 121 (29%)
- **target** — 67 (16%)
- **time_stop** — 15 (4%)
- **trail** — 7 (2%)

## Why setups were rejected

_This is the filter doing its job — high counts here are healthy._

- `break_volume_too_low` — 8355
- `no_confirmation_candle` — 3978
- `no_displacement_before_retest` — 1379
- `entry_window_closed` — 1094
- `failed_break` — 916
- `retest_never_came` — 835
- `opening_range_too_wide` — 430
- `below_vwap_for_long` — 16
- `above_vwap_for_short` — 15

## Was the stop in the right place?

_MAE = how far a trade went against you before resolving. It is the standard way to test stop placement._

| Measure | Value | What it means |
|---|---|---|
| Median stop distance | 0.0% of price | how much room each trade got |
| Winners' typical heat | 0.2R | half of winners never went further against you than this |
| Winners' worst heat (90th pct) | 0.79R | 9 in 10 winners stayed inside this |
| Deepest winner | 0.961R | the single winner that came closest to being stopped |
| Losers' best moment (median) | 0.433R | how far losers got in your favour before failing |
| Losers' best moment (75th pct) | 0.677R | a quarter of losers got at least this far |

**Tightening the stop would have cost you:**

- a stop at 0.5R would have killed **16** of 86 winners (19%)
- a stop at 0.7R would have killed **12** of 86 winners (14%)
- a stop at 0.8R would have killed **8** of 86 winners (9%)

_Read it this way: if winners rarely take much heat, the stop is wider than it needs to be and can be tightened for smaller losses and bigger size. If losers routinely reach 1R+ in your favour before failing, the problem is the exit, not the stop._


## Where the money actually goes

_Buckets with n < 20 are marked unreliable - slicing enough ways always finds a flattering subset by chance._

### By entry hour (ET)

| Bucket | n | Expectancy | Win rate | Total R | |
|---|---|---|---|---|---|
| 10:00-10:59 | 223 | -0.030R | 21.1% | -6.7 |  |
| 11:00-11:59 | 16 | -0.323R | 25.0% | -5.2 | low n |
| 09:00-09:59 | 172 | -0.026R | 20.3% | -4.5 |  |

### By direction

| Bucket | n | Expectancy | Win rate | Total R | |
|---|---|---|---|---|---|
| long | 207 | -0.039R | 19.8% | -8.0 |  |
| short | 204 | -0.041R | 22.1% | -8.4 |  |

### By confirmation pattern

| Bucket | n | Expectancy | Win rate | Total R | |
|---|---|---|---|---|---|
| bearish_engulfing@fvg | 23 | +0.264R | 39.1% | +6.1 |  |
| bearish_engulfing@level | 91 | -0.108R | 17.6% | -9.8 |  |
| bullish_engulfing@fvg | 25 | +0.037R | 24.0% | +0.9 |  |
| bullish_engulfing@level | 85 | -0.042R | 21.2% | -3.5 |  |
| hammer@fvg | 15 | +0.158R | 26.7% | +2.4 | low n |
| hammer@level | 82 | -0.094R | 15.9% | -7.7 |  |
| shooting_star@fvg | 28 | -0.039R | 21.4% | -1.1 |  |
| shooting_star@level | 62 | -0.057R | 22.6% | -3.6 |  |

### By bars between break and retest

| Bucket | n | Expectancy | Win rate | Total R | |
|---|---|---|---|---|---|
| 1 | 51 | -0.137R | 13.7% | -7.0 |  |
| 2 | 113 | -0.006R | 22.1% | -0.6 |  |
| 3 | 70 | -0.082R | 20.0% | -5.7 |  |
| 4 | 51 | -0.062R | 21.6% | -3.1 |  |
| 5 | 49 | +0.179R | 28.6% | +8.8 |  |
| 6+ | 77 | -0.112R | 19.5% | -8.7 |  |

### By symbol

| Bucket | n | Expectancy | Win rate | Total R | |
|---|---|---|---|---|---|
| AAPL | 95 | -0.113R | 17.9% | -10.7 |  |
| AMD | 107 | +0.174R | 30.8% | +18.6 |  |
| NVDA | 104 | -0.174R | 17.3% | -18.1 |  |
| TSLA | 105 | -0.059R | 17.1% | -6.2 |  |


## Last 15 trades

| Symbol | Dir | Entry time | Entry | Exit | R | Exit reason |
|---|---|---|---|---|---|---|
| AMD | short | 2026-08-21T09:45 | 472.58 | 468.56 | +1.45 | target |
| NVDA | short | 2026-08-26T10:50 | 211.02 | 211.08 | -0.08 | breakeven |
| AAPL | long | 2026-08-27T10:45 | 313.59 | 313.50 | -0.05 | breakeven |
| AAPL | short | 2026-09-02T09:45 | 324.46 | 324.56 | -0.07 | breakeven |
| NVDA | long | 2026-09-04T09:45 | 234.18 | 234.11 | -0.04 | breakeven |
| AMD | long | 2026-09-04T10:35 | 470.28 | 470.14 | -0.04 | breakeven |
| TSLA | long | 2026-09-11T09:45 | 367.64 | 363.26 | -1.03 | stop |
| AMD | long | 2026-09-15T10:20 | 508.91 | 506.10 | -1.06 | stop |
| AMD | long | 2026-09-22T10:20 | 617.37 | 617.18 | -0.05 | breakeven |
| NVDA | long | 2026-10-01T09:50 | 231.72 | 230.19 | -1.05 | stop |
| AMD | long | 2026-10-02T10:45 | 640.41 | 636.10 | -1.05 | stop |
| TSLA | long | 2026-10-13T09:50 | 374.40 | 376.41 | +1.42 | target |
| TSLA | short | 2026-10-14T09:50 | 366.45 | 366.56 | -0.05 | breakeven |
| TSLA | short | 2026-10-15T10:10 | 355.55 | 358.47 | -1.04 | stop |
| AMD | long | 2026-10-15T10:55 | 546.13 | 545.97 | -0.05 | breakeven |