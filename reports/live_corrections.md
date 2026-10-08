# Live record corrections

Sessions whose saved record does not match what was actually posted, and the
true record. The desk's History page uses the corrected rows.

## 5 October 2026 — day-trade channel

Posted live, on time, under the in-play rule the day started on:

| symbol | side | entry | exit | result |
|---|---|---|---|---|
| MSFT | long | 09:38 | 15:55 bell | -0.69% |
| BAC | short | 09:40 | 10:19 stop | -1.05% |
| NVDA | long | 09:41 | 15:55 bell | +0.35% |
| **total** | | | | **-1.39%** (3 trades, 1 won, 2 lost) |

What went wrong in the saved record (`reports/live_today.md`, `state/live_bot_seen.json`):

1. A live-bot run queued at 10:03 ran on the commit it was queued on and
   started after the open job saved at 10:05. It re-detected the three
   trades, posted three duplicate "EXPIRED · do not chase" cards, and
   overwrote the saved Discord card ids, so the results edited the expired
   cards and the original on-time cards never showed a result.
2. That evening the channel switched to the big tech rule. The 23:04 catch-up
   re-scored the day under the new rule (the morning's record predates the
   `strategy` field), dropping BAC and adding an AMD 09:44 trade that was
   never posted.

Fixed 8 Oct (PR #1, #2): every state-writing workflow checks out the branch
head, day-end queues with live-bot. The rule-continuity check now has the
`strategy` field every morning.
