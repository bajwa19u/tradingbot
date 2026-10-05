# ORB on stocks in play - forward paper record

Observation only: nothing is posted or traded. Rule: the 10 names with the most abnormal first-five-minute volume, range at least 0.35 of daily ATR, first 1-minute close outside the 09:30-09:34 range before 09:45, stop at the session extreme (moved to entry once +1x risk), target 2x the risk, out at 15:55. Results are the stock's move from entry to exit after 0.05% slippage each way.

1 sessions, 2026-10-05 to 2026-10-05.

| signals | count | win % | winners / losers | avg per trade | avg winner / loser | total |
|---|---|---|---|---|---|---|
| all (backtest view of each day) | 3 | 33% | 1 / 2 | -0.51% | +0.39% / -0.96% | -1.5% |
| seen live in time | 0 | | | | | |
| seen live but late (expired) | 0 | | | | | |
| long | 2 | 50% | 1 / 1 | -0.28% | +0.39% / -0.95% | -0.6% |
| short | 1 | 0% | 0 / 1 | -0.97% | +0.00% / -0.97% | -1.0% |

With real quotes (the NBBO seconds after each signal was seen, and at the exit): -0.46% per trade over 3 trades, against -0.51% at the assumed 0.05% a side. Median entry cost 0.037%, exit 0.009%.

## Last 10

| date | stock | side | bar | seen | result | exit |
|---|---|---|---|---|---|---|
| 2026-10-05 | BAC | short | 09:40 | nan | -0.97% | stop 10:19 |
| 2026-10-05 | NVDA | long | 09:41 | nan | +0.39% | bell 15:55 |
| 2026-10-05 | MSFT | long | 09:38 | nan | -0.95% | bell 15:55 |
