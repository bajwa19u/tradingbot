# Audit baseline (BEFORE) - day-trade bot, from the repo's records

Commit 36a9cc6. Written by `python -m src.audit_baseline`; reads only committed files. Backtest, paper and posted records are separate rows and are never summed.

## Production entry point and active strategy (read from code, workflows and config)

- Entry point: `python -m src.live_bot` from `.github/workflows/live-open.yml` (the open, polling) and `live-bot.yml` (rest of the session); `day-end.yml` settles the day.
- Strategy switch: `live_bot.strategy()` reads the repo variable `DAYTRADE_STRATEGY`, `.strip().lower()`, default `classic`. The variable is set to `bigtech` (stored as `bigtech\r\n\n`), so the channel runs `orb_live.RULES['bigtech']` = `orb_paper.CANDIDATE` on TSLA AMD NVDA META AAPL MSFT every day.
- Rule: opening range 09:30-09:34; range >= 0.35 of 14-day ATR; first 1-minute close outside it, 09:35-09:44; stop at the session extreme -/+ 0.02 ATR, moved to entry at +1x risk; target 2x risk; out at 15:55. Researched at 0.05% slippage a side.
- Orders: none. `autotrade.ENABLED = False` (pinned by a test); signals only.
- Break and retest: off (`retest` not in the live path; settled research).

## Records

| record | kind | period | trades | win % (won/lost) | avg per trade | PF | cumulative | max DD | avg win / loss |
|---|---|---|---|---|---|---|---|---|---|
| day-trade channel, big tech rule | posted (live) | 2026-10-14 to 2026-10-16 | 5 | 80% (4/1) | +0.46% | 3.22 | +2.31% | 1.04% | +0.84% / -1.04% |
| day-trade channel, big tech rule | replay of the live rule | 2026-10-06 to 2026-10-13 | 8 | 38% (3/5) | -0.29% | 0.34 | -2.29% | 2.94% | +0.39% / -0.69% |
| day-trade channel, big tech rule | all ledger rows | 2026-10-06 to 2026-10-16 | 13 | 54% (7/6) | +0.00% | 1.00 | +0.02% | 2.94% | +0.65% / -0.75% |
| day-trade channel, 5 Oct (in-play rule) | posted (corrected) | 2026-10-05 to 2026-10-05 | 3 | 33% (1/2) | -0.46% | 0.20 | -1.39% | 1.74% | +0.35% / -0.87% |
| in-play channel (inplay_bot) | posted (live) | 2026-10-14 to 2026-10-16 | 13 | 31% (4/9) | -0.09% | 0.87 | -1.12% | 4.45% | +1.86% / -0.95% |
| in-play channel (inplay_bot) | replay | 2026-10-05 to 2026-10-13 | 30 | 43% (13/17) | +0.13% | 1.29 | +3.86% | 6.03% | +1.32% / -0.78% |
| Stocks-in-Play candidate (stock move, 0.05%/side) | paper, seen live | 2026-10-08 to 2026-10-16 | 29 | 41% (12/17) | -0.34% | 0.61 | -9.92% | 12.04% | +1.32% / -1.52% |
| Stocks-in-Play candidate (stock move, measured costs) | paper, seen live | 2026-10-08 to 2026-10-16 | 28 | 43% (12/16) | -0.24% | 0.72 | -6.69% | 9.71% | +1.41% / -1.48% |
| Stocks-in-Play candidate (account % at 1% risk) | paper, seen live | 2026-10-08 to 2026-10-16 | 29 | 41% (12/17) | -0.17% | 0.62 | -5.03% | 7.07% | +0.69% / -0.78% |
| Stocks-in-Play candidate (account % at 1% risk, measured costs) | paper, seen live | 2026-10-08 to 2026-10-16 | 28 | 43% (12/16) | -0.13% | 0.72 | -3.52% | 5.89% | +0.74% / -0.78% |
| Stocks-in-Play candidate (account % at 1% risk) | paper, filled in afterwards | 2026-10-05 to 2026-10-07 | 9 | 22% (2/7) | -0.35% | 0.36 | -3.18% | 3.32% | +0.88% / -0.70% |
| Stocks-in-Play candidate (stock move, 0.05%/side) | paper, all | 2026-10-05 to 2026-10-16 | 38 | 37% (14/24) | -0.45% | 0.50 | -17.21% | 17.21% | +1.25% / -1.45% |
| Stocks-in-Play candidate (stock move, measured costs) | paper, all | 2026-10-05 to 2026-10-16 | 37 | 38% (14/23) | -0.37% | 0.58 | -13.56% | 13.56% | +1.33% / -1.40% |
| Stocks-in-Play candidate (account % at 1% risk) | paper, all | 2026-10-05 to 2026-10-16 | 38 | 37% (14/24) | -0.22% | 0.55 | -8.21% | 8.21% | +0.71% / -0.76% |
| Stocks-in-Play candidate (account % at 1% risk, measured costs) | paper, all | 2026-10-05 to 2026-10-16 | 37 | 38% (14/23) | -0.17% | 0.63 | -6.30% | 6.30% | +0.76% / -0.74% |
| month replay of the live rule (bigtech) | backtest | 2026-09-18 to 2026-10-16 | 35 | 54% (19/16) | +0.11% | 1.39 | +3.86% | 6.55% | +0.73% / -0.62% |

## Day-trade channel, big tech rule: splits (ledger, posted + replay)

| ticker | trades | win % | avg | total |
|---|---|---|---|---|
| AAPL | 3 | 67% | +0.00% | +0.01% |
| AMD | 1 | 0% | -1.02% | -1.02% |
| META | 3 | 100% | +0.46% | +1.38% |
| MSFT | 2 | 50% | +0.68% | +1.35% |
| NVDA | 2 | 50% | -0.26% | -0.51% |
| TSLA | 2 | 0% | -0.59% | -1.19% |

| side | trades | win % | avg | total |
|---|---|---|---|---|
| long | 4 | 50% | -0.40% | -1.60% |
| short | 9 | 56% | +0.18% | +1.62% |

| exit | trades | win % | avg | total |
|---|---|---|---|---|
| bell | 9 | 67% | +0.13% | +1.16% |
| stop | 3 | 0% | -1.03% | -3.09% |
| target | 1 | 100% | +1.95% | +1.95% |

## Stocks-in-Play candidate: promotion criterion on the forward paper record

Criterion fixed in `src/orb_audit.py` before the audit ran: forward paper record positive over >= 60 trades. Seen-live paper trades so far: 28, average -0.13% of account (measured costs). **NOT MET** - the candidate stays in paper.

## Research results already on file (backtest; quoted, not re-run here)

| study | data | result |
|---|---|---|
| reports/orb_bigtech.md | IEX 1-min, 2025-09-30 to 2026-10-02 | live rule on big tech: recent 63 sessions 88 trades, 53% win, +0.170%/trade, PF 1.60, +15.0%; earlier 189 sessions 265 trades, 44% win, -0.028%/trade, PF 0.93, -7.5%; at 0.10% slippage +0.124% / -0.096% |
| reports/orb_improve.md | same | the two adopted changes (entries by 09:44, stop to entry at +1x) |
| reports/orb_checks.md | SIP NBBO | median round-trip cost 0.045%, mean 0.054% |

Reproduction, full splits, cost stress and the untouched periods are in `reports/orb_audit.md` (GitHub Action `ORB audit`).

