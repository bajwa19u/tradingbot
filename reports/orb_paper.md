# ORB on stocks in play - forward paper record

Observation only: nothing is posted or traded. Rule: the 10 names with the most abnormal first-five-minute volume, range at least 0.35 of daily ATR, first 1-minute close outside the 09:30-09:34 range before 09:45, stop at the session extreme (moved to entry once +1x risk), target 2x the risk, out at 15:55. Results are the stock's move from entry to exit after 0.05% slippage each way.

4 sessions, 2026-10-05 to 2026-10-08.

| signals | count | win % | winners / losers | avg per trade | avg winner / loser | total |
|---|---|---|---|---|---|---|
| all (backtest view of each day) | 12 | 33% | 4 / 8 | -0.43% | +1.15% / -1.22% | -5.2% |
| seen live in time | 1 | 100% | 1 / 0 | +1.85% | +1.85% / +0.00% | +1.9% |
| seen live but late (expired) | 2 | 50% | 1 / 1 | +0.14% | +1.04% / -0.77% | +0.3% |
| long | 5 | 40% | 2 / 3 | -0.14% | +1.12% / -0.98% | -0.7% |
| short | 7 | 29% | 2 / 5 | -0.64% | +1.17% / -1.36% | -4.5% |

With real quotes (the NBBO seconds after each signal was seen, and at the exit): -0.35% per trade over 11 trades, against -0.40% at the assumed 0.05% a side. Median entry cost 0.037%, exit 0.009%.

Live and backtest agreed on 100% of live signals; 9 backtest signals were never seen live. Median latency 124s after the bar closed.

## Last 10

| date | stock | side | bar | seen | result | exit |
|---|---|---|---|---|---|---|
| 2026-10-05 | MSFT | long | 09:38 | nan | -0.95% | bell 15:55 |
| 2026-10-06 | CRWD | long | 09:38 | nan | -1.63% | bell 15:55 |
| 2026-10-06 | AMD | short | 09:35 | nan | -3.31% | stop 10:35 |
| 2026-10-06 | PLTR | long | 09:36 | nan | -0.35% | bell 15:55 |
| 2026-10-07 | PEP | short | 09:35 | nan | +1.30% | bell 15:55 |
| 2026-10-07 | MSFT | short | 09:41 | nan | -0.59% | bell 15:55 |
| 2026-10-07 | AAPL | short | 09:35 | nan | -1.18% | bell 15:55 |
| 2026-10-08 | PEP | long | 09:37 | 09:39:48 | +1.85% | bell 15:55 |
| 2026-10-08 | PLTR | short | 09:40 | 09:43:04 | -0.77% | bell 15:55 |
| 2026-10-08 | GOOGL | short | 09:40 | 09:43:04 | +1.04% | bell 15:55 |
