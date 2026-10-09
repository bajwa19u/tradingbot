# ORB on stocks in play - forward paper record

Observation only: nothing is posted or traded. Rule: the 10 names with the most abnormal first-five-minute volume, range at least 0.35 of daily ATR, first 1-minute close outside the 09:30-09:34 range before 09:45, stop at the session extreme (moved to entry once +1x risk), target 2x the risk, out at 15:55. Results are the stock's move from entry to exit after 0.05% slippage each way.

5 sessions, 2026-10-05 to 2026-10-09.

| signals | count | win % | winners / losers | avg per trade | avg winner / loser | total |
|---|---|---|---|---|---|---|
| all (backtest view of each day) | 16 | 31% | 5 / 11 | -0.47% | +1.20% / -1.23% | -7.5% |
| seen live in time | 5 | 40% | 2 / 3 | -0.09% | +1.64% / -1.24% | -0.4% |
| seen live but late (expired) | 2 | 50% | 1 / 1 | +0.14% | +1.04% / -0.77% | +0.3% |
| long | 8 | 38% | 3 / 5 | -0.10% | +1.23% / -0.90% | -0.8% |
| short | 8 | 25% | 2 / 6 | -0.83% | +1.17% / -1.50% | -6.6% |

With real quotes (the NBBO seconds after each signal was seen, and at the exit): -0.39% per trade over 15 trades, against -0.45% at the assumed 0.05% a side. Median entry cost 0.037%, exit 0.009%.

Live and backtest agreed on 100% of live signals; 9 backtest signals were never seen live. Median latency 64s after the bar closed.

## Last 10

| date | stock | side | bar | seen | result | exit |
|---|---|---|---|---|---|---|
| 2026-10-07 | PEP | short | 09:35 | nan | +1.30% | bell 15:55 |
| 2026-10-07 | MSFT | short | 09:41 | nan | -0.59% | bell 15:55 |
| 2026-10-07 | AAPL | short | 09:35 | nan | -1.18% | bell 15:55 |
| 2026-10-08 | PEP | long | 09:37 | 09:39:48 | +1.85% | bell 15:55 |
| 2026-10-08 | PLTR | short | 09:40 | 09:43:04 | -0.77% | bell 15:55 |
| 2026-10-08 | GOOGL | short | 09:40 | 09:43:04 | +1.04% | bell 15:55 |
| 2026-10-09 | UNH | long | 09:35 | 09:37:04 | -0.05% | stop 09:59 |
| 2026-10-09 | PLTR | short | 09:40 | 09:42:04 | -2.16% | stop 11:22 |
| 2026-10-09 | MRK | long | 09:36 | 09:37:04 | +1.44% | bell 15:55 |
| 2026-10-09 | TSLA | long | 09:42 | 09:43:04 | -1.51% | stop 11:29 |
