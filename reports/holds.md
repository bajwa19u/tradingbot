# How long should a trade be allowed to live?

## 2026-09-29 — the trades that ran out of clock

| symbol | capped at 2h | if left alone | difference |
|---|---|---|---|
| AVGO | -1.03% (stop 10:30) | — same, it never hit the clock | — |
| NVDA | -0.23% (timed out 11:36) | **+0.47%** (open 13:38) | +0.71% |
| AMD | -1.03% (stop 09:51) | — same, it never hit the clock | — |
| TSLA | -0.30% (timed out 11:37) | **-0.04%** (open 13:38) | +0.26% |
| GOOGL | +0.76% (timed out 11:39) | **+0.59%** (open 13:38) | -0.17% |
| AMZN | -0.19% (timed out 11:40) | **-1.09%** (stop 12:50) | -0.91% |
| MSFT | -1.05% (stop 10:26) | — same, it never hit the clock | — |
| MU | -1.03% (stop 10:19) | — same, it never hit the clock | — |
| PLTR | +0.08% (timed out 11:41) | **+0.13%** (open 13:38) | +0.05% |
| SMCI | +1.23% (timed out 11:43) | **+1.27%** (open 13:38) | +0.05% |
| META | +0.51% (timed out 11:45) | **-1.05%** (stop 13:21) | -1.56% |

Of the 7 that timed out, letting them run turns **+1.86% into +0.28%** (4 better, 3 worse).


## Every hold cap, 66 days (2026-06-26 to 2026-09-29)

Explore = the first 44 days, holdout = the last 22. Entries, stops and targets are identical in every row; only the clock moves.

### Explore

| hold cap | trades | win % | won | lost | profit % | avg/trade |
|---|---|---|---|---|---|---|
| 15 min | 450 | 46.9% | 211 | 239 | -25.1% | -0.056% |
| 30 min | 450 | 48.4% | 218 | 232 | -17.9% | -0.040% |
| 60 min | 450 | 50.0% | 225 | 225 | +5.5% | +0.012% |
| 120 min | 450 | 46.0% | 207 | 243 | -7.3% | -0.016% |
| 240 min | 450 | 46.0% | 207 | 243 | +14.5% | +0.032% |
| no cap (stop/target/bell) | 450 | 46.2% | 208 | 242 | +6.8% | +0.015% |

### Holdout (dates never used to choose anything)

| hold cap | trades | win % | won | lost | profit % | avg/trade |
|---|---|---|---|---|---|---|
| 15 min | 221 | 35.7% | 79 | 142 | -32.4% | -0.147% |
| 30 min | 221 | 38.9% | 86 | 135 | -33.9% | -0.153% |
| 60 min | 221 | 40.7% | 90 | 131 | -29.3% | -0.133% |
| 120 min | 221 | 42.1% | 93 | 128 | -20.8% | -0.094% |
| 240 min | 218 | 41.3% | 90 | 128 | -18.7% | -0.086% |
| no cap (stop/target/bell) | 216 | 41.7% | 90 | 126 | -22.2% | -0.103% |

### Verdict

- **240 min beats the live two-hour cap on the explore split** (+14.5% against -7.3%), and on the holdout it is -18.7% against -20.8%.
- The holdout agrees, which is the only reason this is worth changing.

### How trades ended, by cap

| hold cap | stop | target | time | bell |
|---|---|---|---|---|
| 15 min | 40 | 1 | 409 | 0 |
| 30 min | 73 | 8 | 369 | 0 |
| 60 min | 113 | 23 | 314 | 0 |
| 120 min | 144 | 38 | 268 | 0 |
| 240 min | 159 | 52 | 239 | 0 |
| no cap (stop/target/bell) | 168 | 66 | 216 | 0 |
