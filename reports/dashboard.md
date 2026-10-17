# Dashboard summary

Built 2026-10-17 00:05 ET from the repo's own records. Open `reports/dashboard.html` in a browser for the interactive version.

Win %, profit % and winners against losers. Each book is in its own unit and never summed with another.

| book | unit | trades | won / lost | win % | net | avg per trade | worst drop | verdict |
|---|---|---|---|---|---|---|---|---|
| Day-trade channel | % of account, 1% risked per trade | 14 | 6 / 8 | 43% | -3.38 | -0.24 | -4.86 | No. Net -3.38 (% of account, 1% risked per trade) over 14 closed trades, 6 won, 8 lost. |
| In-play channel | % of account, 1% risked per trade | 38 | 15 / 23 | 39% | +1.22 | +0.03 | -6.03 | Net +1.22 over 38 trades, but the 95% interval of the average trade includes zero: not distinguishable from noise. |
| ORB candidate · paper | % move of the stock, entry to exit | 36 | 13 / 23 | 36% | -15.59 | -0.43 | -21.26 | No. Net -15.59 (% move of the stock, entry to exit) over 36 closed trades, 13 won, 23 lost. |
| Swing breakout · paper | % of account, 1% risked per trade | 4 | 0 / 4 | 0% | -4.01 | -1.00 | -4.01 | No. Net -4.01 (% of account, 1% risked per trade) over 4 closed trades, 0 won, 4 lost. |
| Live rule · month replay | % of account, 1% risked per trade | 36 | 17 / 19 | 47% | -0.77 | -0.02 | -6.66 | No. Net -0.77 (% of account, 1% risked per trade) over 36 closed trades, 17 won, 19 lost. |

## Issues

- **serious** · Market data: 2026-10-15: data stale 12:59-14:11 ET (newest bar stuck at 12:56, 55 polls). New signals were held.
- **warning** · Coverage: Last 5 sessions: 2 poll gap(s) of 10-29 min (worst 21 min), starting at 10:04 ET. 10:04 is when the opening job hands over to the session job; stops and targets hit in a gap post late.
- **warning** · Latency: Last 5 sessions: 4 of 7 on-time signals were first detected about 61 s after their bar closed, i.e. one poll late (still inside the 120 s expiry). The others took 1.3 s.
- **info** · Delivery: Discord delivery per signal was not logged before this dashboard; the live bot now records it. Until then delivery is inferred from saved Discord message ids.
- **info** · Records: 8 of 14 day-trade ledger rows are replays, not posts. They are left out of the bot views: the month replay covers the same sessions.
- **info** · Records: The in-play channel writes no latency log, so its signal ages are not tracked.
- **past** · Coverage: 2026-10-08: no live-bot scan logged 09:30-10:06 ET (36 min). A signal in that window could not post on time.
- **past** · Coverage: 2026-10-07: no live-bot scan logged 10:04-15:43 ET (339 min). A signal in that window could not post on time.
- **past** · Coverage: 2026-10-06: no live-bot scan logged 10:04-15:39 ET (335 min). A signal in that window could not post on time.
- **past** · Coverage: 2026-10-05: no live-bot scan logged 09:30-10:06 ET (36 min). A signal in that window could not post on time.
- **past** · Coverage: 2026-10-05: no live-bot scan logged 15:25-15:55 ET (30 min). A signal in that window could not post on time.
- **past** · Coverage: 2026-10-02: no live-bot scan logged 10:26-15:48 ET (322 min). A signal in that window could not post on time.

## Integrity checks

- OK · daytrade · unique trade ids: 0 duplicate id(s)
- OK · daytrade · trades = wins + losses + flat: 14 = 6 + 8 + 0
- OK · daytrade · open / unresolved rows kept out of closed stats: 0 row(s) excluded
- OK · inplay · unique trade ids: 0 duplicate id(s)
- OK · inplay · trades = wins + losses + flat: 38 = 15 + 23 + 0
- OK · inplay · open / unresolved rows kept out of closed stats: 0 row(s) excluded
- OK · orb_paper · unique trade ids: 0 duplicate id(s)
- OK · orb_paper · trades = wins + losses + flat: 36 = 13 + 23 + 0
- OK · orb_paper · open / unresolved rows kept out of closed stats: 0 row(s) excluded
- OK · swing_paper · unique trade ids: 0 duplicate id(s)
- OK · swing_paper · trades = wins + losses + flat: 4 = 0 + 4 + 0
- OK · swing_paper · open / unresolved rows kept out of closed stats: 0 row(s) excluded
- OK · month_replay · unique trade ids: 0 duplicate id(s)
- OK · month_replay · trades = wins + losses + flat: 36 = 17 + 19 + 0
- OK · month_replay · open / unresolved rows kept out of closed stats: 0 row(s) excluded
- OK · daytrade · live posts match the month replay: 2 shared session(s): 3 trades in both, 0 only live, 0 only in replay, 0 with results >0.05 apart
- OK · swing_paper · matches src/paper.py's own totals: paper.py: 4 trades, 0 won, -4.0% · here: 4 trades, 0 won, -4.01%
