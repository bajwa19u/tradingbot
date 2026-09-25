# Break-and-retest backtest

**Period:** 2025-06-01 → today  
**Symbols:** AAPL, NVDA  
**Timeframe:** 5-minute  
**Target:** 2.0R, risking 1.0% of $2,000  
**Generated:** 2026-09-25 19:14

## Headline

| Metric | Value |
|---|---|
| Trades | 7 over 332 days (0.02/day) |
| Win rate | 28.6% |
| Expectancy | -0.282R per trade |
| Total | -1.97R · $-17.19 (-0.86%) |
| Profit factor | 0.63 |
| Max drawdown | -1.44% |
| Avg win / avg loss | 1.692R / -1.072R |
| Worst losing streak | 3 |
| Avg hold | 10.6 bars |

## How trades ended

- **stop** — 5 (71%)
- **target** — 2 (29%)

## Why setups were rejected

_This is the filter doing its job — high counts here are healthy._

- `break_volume_too_low` — 2711
- `opening_range_too_wide` — 538
- `entry_window_closed` — 79
- `no_confirmation_candle` — 32
- `retest_never_came` — 29
- `failed_break` — 9

## Last 15 trades

| Symbol | Dir | Entry time | Entry | Exit | R | Exit reason |
|---|---|---|---|---|---|---|
| AAPL | short | 2025-06-05T10:05 | 201.51 | 202.94 | -1.04 | stop |
| AAPL | short | 2025-08-15T10:15 | 232.28 | 231.24 | +1.58 | target |
| NVDA | long | 2025-10-16T10:50 | 182.87 | 182.36 | -1.12 | stop |
| NVDA | long | 2025-12-03T10:40 | 181.68 | 180.90 | -1.07 | stop |
| NVDA | short | 2025-12-10T10:50 | 182.86 | 183.90 | -1.06 | stop |
| NVDA | short | 2026-06-05T10:20 | 211.80 | 209.42 | +1.81 | target |
| NVDA | long | 2026-07-02T10:15 | 199.28 | 198.30 | -1.06 | stop |