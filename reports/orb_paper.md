# ORB on stocks in play - forward paper record

Observation only: nothing is posted or traded. Rule: the 10 names with the most abnormal first-five-minute volume, range at least 0.35 of daily ATR, first 1-minute close outside the 09:30-09:34 range before 09:45, stop at the session extreme (moved to entry once +1x risk), target 2x the risk, out at 15:55. Results are the stock's move from entry to exit after 0.05% slippage each way.

8 sessions, 2026-10-05 to 2026-10-14.

| signals | count | win % | winners / losers | avg per trade | avg winner / loser | total |
|---|---|---|---|---|---|---|
| all (backtest view of each day) | 29 | 38% | 11 / 18 | -0.42% | +1.07% / -1.33% | -12.1% |
| seen live in time | 18 | 44% | 8 / 10 | -0.28% | +1.13% / -1.41% | -5.1% |
| seen live but late (expired) | 2 | 50% | 1 / 1 | +0.14% | +1.04% / -0.77% | +0.3% |
| long | 14 | 36% | 5 / 9 | -0.48% | +1.01% / -1.31% | -6.7% |
| short | 15 | 40% | 6 / 9 | -0.36% | +1.13% / -1.35% | -5.4% |

With real quotes (the NBBO seconds after each signal was seen, and at the exit): -0.33% per trade over 28 trades, against -0.40% at the assumed 0.05% a side. Median entry cost 0.027%, exit 0.011%.

Live and backtest agreed on 100% of live signals; 9 backtest signals were never seen live. Median latency 4s after the bar closed.

## Last 10

| date | stock | side | bar | seen | result | exit |
|---|---|---|---|---|---|---|
| 2026-10-13 | JPM | short | 09:35 | 09:36:04 | -0.05% | stop 10:54 |
| 2026-10-13 | UNH | short | 09:40 | 09:41:04 | +1.78% | bell 15:55 |
| 2026-10-13 | JNJ | short | 09:37 | 09:38:04 | +1.42% | bell 15:55 |
| 2026-10-13 | CAT | long | 09:42 | 09:43:04 | -1.75% | stop 09:55 |
| 2026-10-13 | AAPL | short | 09:40 | 09:41:04 | +0.75% | bell 15:55 |
| 2026-10-14 | MS | long | 09:36 | 09:37:04 | -1.22% | bell 15:55 |
| 2026-10-14 | UNH | long | 09:40 | 09:41:04 | +0.41% | bell 15:55 |
| 2026-10-14 | GS | long | 09:36 | 09:37:04 | -2.42% | stop 12:13 |
| 2026-10-14 | JPM | long | 09:37 | 09:38:04 | +0.94% | bell 15:55 |
| 2026-10-14 | CRWD | short | 09:37 | 09:38:04 | -2.59% | stop 10:16 |
