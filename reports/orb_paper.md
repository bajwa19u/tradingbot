# ORB on stocks in play - forward paper record

Observation only: nothing is posted or traded. Rule: the 10 names with the most abnormal first-five-minute volume, range at least 0.35 of daily ATR, first 1-minute close outside the 09:30-09:34 range before 09:45, stop at the session extreme (moved to entry once +1x risk), target 2x the risk, out at 15:55. Results are the stock's move from entry to exit after 0.05% slippage each way.

6 sessions, 2026-10-05 to 2026-10-12.

| signals | count | win % | winners / losers | avg per trade | avg winner / loser | total |
|---|---|---|---|---|---|---|
| all (backtest view of each day) | 19 | 32% | 6 / 13 | -0.49% | +1.08% / -1.22% | -9.4% |
| seen live in time | 8 | 38% | 3 / 5 | -0.29% | +1.26% / -1.22% | -2.3% |
| seen live but late (expired) | 2 | 50% | 1 / 1 | +0.14% | +1.04% / -0.77% | +0.3% |
| long | 9 | 33% | 3 / 6 | -0.30% | +1.23% / -1.06% | -2.7% |
| short | 10 | 30% | 3 / 7 | -0.67% | +0.94% / -1.36% | -6.7% |

With real quotes (the NBBO seconds after each signal was seen, and at the exit): -0.42% per trade over 18 trades, against -0.48% at the assumed 0.05% a side. Median entry cost 0.033%, exit 0.009%.

Live and backtest agreed on 100% of live signals; 9 backtest signals were never seen live. Median latency 64s after the bar closed.

## Last 10

| date | stock | side | bar | seen | result | exit |
|---|---|---|---|---|---|---|
| 2026-10-08 | PEP | long | 09:37 | 09:39:48 | +1.85% | bell 15:55 |
| 2026-10-08 | PLTR | short | 09:40 | 09:43:04 | -0.77% | bell 15:55 |
| 2026-10-08 | GOOGL | short | 09:40 | 09:43:04 | +1.04% | bell 15:55 |
| 2026-10-09 | UNH | long | 09:35 | 09:37:04 | -0.05% | stop 09:59 |
| 2026-10-09 | PLTR | short | 09:40 | 09:42:04 | -2.16% | stop 11:22 |
| 2026-10-09 | MRK | long | 09:36 | 09:37:04 | +1.44% | bell 15:55 |
| 2026-10-09 | TSLA | long | 09:42 | 09:43:04 | -1.51% | stop 11:29 |
| 2026-10-12 | UNH | short | 09:35 | 09:37:04 | -0.52% | bell 15:55 |
| 2026-10-12 | CRM | short | 09:44 | 09:45:04 | +0.48% | bell 15:55 |
| 2026-10-12 | PLTR | long | 09:35 | 09:37:04 | -1.85% | stop 10:07 |
