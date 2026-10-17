# Profitability audit, both bots: executive summary (17 Oct 2026)

Per-bot reports: day trade [audit_daytrade.md](audit_daytrade.md) (this repo, PR #4);
swing `reports/audit_swing.md` in bajwa19u/vwap-ema-swing (its PR). Same file in both repos.

## Bottom line

| | day trade: ORB on big tech (live) | swing: EMA21 x weekly VWAP (live) |
|---|---|---|
| edge after realistic costs | **none**: about 0% a trade over 2 years; negative on every period except the 63 sessions it was picked on | **yes in backtest**: +1.50% a trade on the holdout, PF 1.79 |
| survives stressed costs | no (-0.066% a trade at 0.10% a side) | yes (+1.20% at 0.20% a side; +1.36% filled an hour late) |
| untouched data | 2024-25 year -0.020% (272 trades); forward -0.023% (16) | forward 1 trade; holdout was used as a veto, so optimistic |
| strategy changes promoted | none (5 pre-registered, all failed) | none (none justified by evidence; settled list not re-tested) |
| fixes | late signals (REST lag), 10:05 blind window | weekly retune broken + could change live rule on noise, stale-checkout, options model and README wrong |
| on the live bot's own data | backtest matches all 13 posted/replayed trades 6-16 Oct | holdout +1.65% a trade (225 trades); the 17-min delay costs ~0.04% a trade |
| recommendation | observation only, or switch the channel back; do not trade it | keep as signals; validate on the live-data record first |

## Before / After table

Before = After for every strategy metric: nothing passed the promotion rules, so the strategies are unchanged.

| metric | day trade (backtest, IEX 1-min, 2024-10-01 to 2026-10-16, 643 trades) | swing (backtest, Yahoo 1h, holdout 2025-07-01 to 2026-10-01, 215 trades) |
|---|---|---|
| completed trades | 643 / 643 / 0 | 215 / 215 / 0 |
| win rate | 44.3% / same / 0 | 56.7% / same / 0 |
| avg net P&L per trade (expectancy) | +0.003% of account / same / 0 | +1.50% / same / 0 |
| profit factor | 1.01 / same / 0 | 1.79 / same / 0 |
| cumulative net return | +1.7% (1% risk a trade, summed) / same / 0 | +36.2% (10% a position) / same / 0 |
| max drawdown | 27.5% / same / 0 | -6.4% / same / 0 |
| net after stressed costs | -0.066% a trade at 0.10% a side / same / 0 | +1.40% at 0.10%, +1.20% at 0.20% / same / 0 |
| untouched-test expectancy | -0.020% (2024-25, 272 trades) / same / 0 | forward: 1 trade +0.84% / same / too few |

Cells read Before / After / Change. Day-trade results are % of the account with a full stop costing 1%;
swing results are the stock's move per trade.

## What remains blocked

- **Your approval to merge both PRs.** They change live jobs' timing and process only, not rules:
  the day-trade REST re-read and the 10:35 polling window; the swing retune becoming report-only, plus
  workflow checkout fixes.
- **Day-trade channel decision:** `DAYTRADE_STRATEGY=bigtech` is your repo variable; this audit
  recommends it is not traded. Changing it is yours to do.
- **Forward evidence:** both bots need more forward trades (5 and 4 posted so far) before any number
  here can be confirmed live.
- Options returns are modelled, not observed, so they stay estimates until real fills are recorded.
