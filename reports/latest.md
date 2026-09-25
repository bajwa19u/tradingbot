# Break-and-retest backtest

**Period:** 2024-01-01 → today  
**Symbols:** AAPL, MSFT, NVDA, AMD, TSLA, META, AMZN, GOOGL  
**Timeframe:** 5-minute  
**Target:** 2.0R, risking 1.0% of $10,000  
**Generated:** 2026-09-25 19:29

## Headline

| Metric | Value |
|---|---|
| Trades | 942 over 685 days (1.38/day) |
| Win rate | 27.1% |
| Expectancy | -0.234R per trade |
| Total | -220.61R · $-8,736.65 (-87.37%) |
| Profit factor | 0.63 |
| Max drawdown | -87.74% |
| Avg win / avg loss | 1.473R / -0.868R |
| Worst losing streak | 14 |
| Avg hold | 13.1 bars |

## How trades ended

- **stop** — 528 (56%)
- **target** — 224 (24%)
- **breakeven** — 143 (15%)
- **time_stop** — 47 (5%)

## Why setups were rejected

_This is the filter doing its job — high counts here are healthy._

- `break_volume_too_low` — 17622
- `no_confirmation_candle` — 7529
- `retest_never_came` — 2048
- `failed_break` — 915
- `opening_range_too_wide` — 835
- `entry_window_closed` — 474
- `below_vwap_for_long` — 15
- `above_vwap_for_short` — 14

## Last 15 trades

| Symbol | Dir | Entry time | Entry | Exit | R | Exit reason |
|---|---|---|---|---|---|---|
| TSLA | long | 2026-09-10T11:20 | 365.91 | 365.80 | -0.09 | breakeven |
| AMZN | long | 2026-09-10T10:50 | 252.65 | 251.49 | -1.07 | stop |
| AMZN | long | 2026-09-11T14:00 | 257.01 | 256.45 | -1.16 | stop |
| AAPL | long | 2026-09-14T12:25 | 334.69 | 333.99 | -1.17 | stop |
| NVDA | long | 2026-09-14T11:40 | 212.12 | 211.21 | -1.07 | stop |
| AMD | long | 2026-09-14T12:40 | 493.62 | 493.47 | -0.06 | breakeven |
| AMD | long | 2026-09-15T10:20 | 508.91 | 506.10 | -1.06 | stop |
| TSLA | long | 2026-09-16T10:10 | 363.57 | 358.93 | -1.02 | stop |
| TSLA | long | 2026-09-17T10:30 | 371.40 | 369.85 | -1.08 | stop |
| NVDA | long | 2026-09-17T11:55 | 219.03 | 219.33 | +0.57 | time_stop |
| NVDA | long | 2026-09-21T11:25 | 224.94 | 226.20 | +1.65 | target |
| MSFT | long | 2026-09-24T13:25 | 496.10 | 494.77 | -1.13 | stop |
| AAPL | long | 2026-09-24T12:30 | 338.03 | 336.78 | -1.09 | stop |
| NVDA | short | 2026-09-25T11:05 | 224.25 | 224.32 | -0.11 | breakeven |
| AMZN | long | 2026-09-25T12:25 | 250.79 | 249.66 | -1.07 | stop |