# ORB on stocks in play - forward paper record

Observation only: nothing is posted or traded. Rule: the 10 names with the most abnormal first-five-minute volume, range at least 0.35 of daily ATR, first 1-minute close outside the 09:30-09:34 range before 09:45, stop at the session extreme (moved to entry once +1x risk), target 2x the risk, out at 15:55. Results are the stock's move from entry to exit after 0.05% slippage each way.

9 sessions, 2026-10-05 to 2026-10-15.

| signals | count | win % | winners / losers | avg per trade | avg winner / loser | total |
|---|---|---|---|---|---|---|
| all (backtest view of each day) | 36 | 36% | 13 / 23 | -0.43% | +1.34% / -1.44% | -15.6% |
| seen live in time | 25 | 40% | 10 / 15 | -0.34% | +1.47% / -1.55% | -8.6% |
| seen live but late (expired) | 2 | 50% | 1 / 1 | +0.14% | +1.04% / -0.77% | +0.3% |
| long | 18 | 39% | 7 / 11 | -0.21% | +1.53% / -1.31% | -3.7% |
| short | 18 | 33% | 6 / 12 | -0.66% | +1.13% / -1.55% | -11.8% |

With real quotes (the NBBO seconds after each signal was seen, and at the exit): -0.33% per trade over 35 trades, against -0.42% at the assumed 0.05% a side. Median entry cost 0.012%, exit 0.011%.

Live and backtest agreed on 100% of live signals; 9 backtest signals were never seen live. Median latency 4s after the bar closed.

## Last 10

| date | stock | side | bar | seen | result | exit |
|---|---|---|---|---|---|---|
| 2026-10-14 | GS | long | 09:36 | 09:37:04 | -2.42% | stop 12:13 |
| 2026-10-14 | JPM | long | 09:37 | 09:38:04 | +0.94% | bell 15:55 |
| 2026-10-14 | CRWD | short | 09:37 | 09:38:04 | -2.59% | stop 10:16 |
| 2026-10-15 | WMT | long | 09:35 | 09:37:04 | -1.34% | stop 09:44 |
| 2026-10-15 | SHOP | long | 09:36 | 09:37:04 | +5.35% | bell 15:55 |
| 2026-10-15 | ETN | short | 09:35 | 09:37:04 | -2.60% | stop 11:04 |
| 2026-10-15 | CAT | short | 09:35 | 09:37:04 | -2.81% | stop 10:48 |
| 2026-10-15 | HD | short | 09:44 | 09:45:04 | -1.05% | stop 09:51 |
| 2026-10-15 | NVDA | long | 09:42 | 09:43:04 | -1.35% | stop 09:55 |
| 2026-10-15 | UNH | long | 09:41 | 09:42:04 | +0.32% | bell 15:55 |
