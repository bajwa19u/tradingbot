# In-play ORB signal speed

Session replayed: 2026-10-02, real Alpaca IEX data, on a GitHub runner. 6 signals that morning.

| stage | before (seconds) | after (seconds) |
|---|---|---|
| warm-up before the bell | 12.3 | 7.4 |
| 09:36 tick (picks the 10 + first check) | 0.9 | 0.9 |
| 09:40 tick | 0.8 | 0.9 |
| 09:59 tick | 0.8 | 0.8 |
| 15:56 tick (managing exits) | 0.8 | 0.8 |
| late start: first tick at 09:45, cold | 13.0 | 14.6 |

A signal's bar closes on the minute; the bot checks 4 seconds later, so a check's time is roughly how long after the bar a signal is ready (plus Discord, about half a second).
