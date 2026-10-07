# ORB on stocks in play - forward paper record

Observation only: nothing is posted or traded. Rule: the 10 names with the most abnormal first-five-minute volume, range at least 0.35 of daily ATR, first 1-minute close outside the 09:30-09:34 range before 09:45, stop at the session extreme (moved to entry once +1x risk), target 2x the risk, out at 15:55. Results are the stock's move from entry to exit after 0.05% slippage each way.

3 sessions, 2026-10-05 to 2026-10-07.

| signals | count | win % | winners / losers | avg per trade | avg winner / loser | total |
|---|---|---|---|---|---|---|
| all (backtest view of each day) | 9 | 22% | 2 / 7 | -0.81% | +0.85% / -1.28% | -7.3% |
| seen live in time | 0 | | | | | |
| seen live but late (expired) | 0 | | | | | |
| long | 4 | 25% | 1 / 3 | -0.64% | +0.39% / -0.98% | -2.5% |
| short | 5 | 20% | 1 / 4 | -0.95% | +1.30% / -1.51% | -4.7% |

With real quotes (the NBBO seconds after each signal was seen, and at the exit): -0.76% per trade over 9 trades, against -0.81% at the assumed 0.05% a side. Median entry cost 0.037%, exit 0.009%.

## Last 10

| date | stock | side | bar | seen | result | exit |
|---|---|---|---|---|---|---|
| 2026-10-05 | BAC | short | 09:40 | nan | -0.97% | stop 10:19 |
| 2026-10-05 | NVDA | long | 09:41 | nan | +0.39% | bell 15:55 |
| 2026-10-05 | MSFT | long | 09:38 | nan | -0.95% | bell 15:55 |
| 2026-10-06 | CRWD | long | 09:38 | nan | -1.63% | bell 15:55 |
| 2026-10-06 | AMD | short | 09:35 | nan | -3.31% | stop 10:35 |
| 2026-10-06 | PLTR | long | 09:36 | nan | -0.35% | bell 15:55 |
| 2026-10-07 | PEP | short | 09:35 | nan | +1.30% | bell 15:55 |
| 2026-10-07 | MSFT | short | 09:41 | nan | -0.59% | bell 15:55 |
| 2026-10-07 | AAPL | short | 09:35 | nan | -1.18% | bell 15:55 |
