# ORB on stocks in play - forward paper record

Observation only: nothing is posted or traded. Rule: the 10 names with the most abnormal first-five-minute volume, range at least 0.35 of daily ATR, first 1-minute close outside the 09:30-09:34 range before 09:45, stop at the session extreme (moved to entry once +1x risk), target 2x the risk, out at 15:55. Results are the stock's move from entry to exit after 0.05% slippage each way.

10 sessions, 2026-10-05 to 2026-10-16.

| signals | count | win % | winners / losers | avg per trade | avg winner / loser | total |
|---|---|---|---|---|---|---|
| all (backtest view of each day) | 38 | 37% | 14 / 24 | -0.45% | +1.25% / -1.45% | -17.2% |
| seen live in time | 27 | 41% | 11 / 16 | -0.38% | +1.35% / -1.56% | -10.2% |
| seen live but late (expired) | 2 | 50% | 1 / 1 | +0.14% | +1.04% / -0.77% | +0.3% |
| long | 18 | 39% | 7 / 11 | -0.21% | +1.53% / -1.31% | -3.7% |
| short | 20 | 35% | 7 / 13 | -0.67% | +0.98% / -1.56% | -13.5% |

With real quotes (the NBBO seconds after each signal was seen, and at the exit): -0.37% per trade over 37 trades, against -0.44% at the assumed 0.05% a side. Median entry cost 0.021%, exit 0.013%.

Live and backtest agreed on 100% of live signals; 9 backtest signals were never seen live. Median latency 4s after the bar closed.

## Last 10

| date | stock | side | bar | seen | result | exit |
|---|---|---|---|---|---|---|
| 2026-10-14 | CRWD | short | 09:37 | 09:38:04 | -2.59% | stop 10:16 |
| 2026-10-15 | WMT | long | 09:35 | 09:37:04 | -1.34% | stop 09:44 |
| 2026-10-15 | SHOP | long | 09:36 | 09:37:04 | +5.35% | bell 15:55 |
| 2026-10-15 | ETN | short | 09:35 | 09:37:04 | -2.60% | stop 11:04 |
| 2026-10-15 | CAT | short | 09:35 | 09:37:04 | -2.81% | stop 10:48 |
| 2026-10-15 | HD | short | 09:44 | 09:45:04 | -1.05% | stop 09:51 |
| 2026-10-15 | NVDA | long | 09:42 | 09:43:04 | -1.35% | stop 09:55 |
| 2026-10-15 | UNH | long | 09:41 | 09:42:04 | +0.32% | bell 15:55 |
| 2026-10-16 | UNH | short | 09:36 | 09:38:04 | +0.08% | bell 15:55 |
| 2026-10-16 | SHOP | short | 09:39 | 09:40:04 | -1.71% | stop 09:55 |
