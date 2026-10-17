# Day-trade bot: profitability audit, 17 Oct 2026

Branch `profitability-audit`. Evidence: [orb_audit.md](orb_audit.md) (backtest, GitHub Action "ORB audit"),
[audit_baseline.md](audit_baseline.md) (live, replay and paper records). Results are % of the account per trade
with a full stop costing 1%, summed (not compounded).

## Verdict

**Nothing promoted. The live rule (ORB on big tech) has no edge outside the 63 sessions it was chosen on.**
On the year no earlier study touched (Oct 2024 - Sep 2025) it loses -0.020% a trade; on the nine months
before July 2026, -0.027%; in the forward weeks since 5 Oct, -0.023%. The +0.170% "recent" result is the
window the big tech list was picked from. At 0.10% a side every period except that window is negative.
Recommendation: keep posting it as observation only, or switch the channel back to `classic` / off; do not
trade it. The Stocks-in-Play candidate also fails its pre-set criteria and stays in paper.

## Before / After

Strategy version: `orb_live.RULES["bigtech"]` = `orb_paper.CANDIDATE` on TSLA AMD NVDA META AAPL MSFT.
Before = After because no change passed; the only changes are execution reliability (below), which a bar
backtest cannot score.

| metric | kind, data, trades | Before | After | Change |
|---|---|---|---|---|
| completed trades | backtest, IEX 1-min, 2024-10-01 to 2026-10-16 | 643 | 643 | 0 |
| win rate | same | 44.3% (285 / 358) | 44.3% | 0 |
| avg net P&L per trade (= expectancy) | same, 0.05% a side | +0.003% | +0.003% | 0 |
| profit factor | same | 1.01 | 1.01 | 0 |
| cumulative net return | same | +1.7% | +1.7% | 0 |
| max drawdown | same | 27.5% | 27.5% | 0 |
| net after stressed costs | same, 0.10% a side / + 1 min late | -0.066% / -0.070% a trade (-42.4% / -44.7%) | same | 0 |
| untouched-test expectancy | backtest, 2024-10-01 to 2025-09-29, 272 trades | -0.020% (PF 0.95) | same | 0 |
| untouched forward expectancy | backtest, 2026-10-05 to 10-16, 16 trades | -0.023% | same | 0 |
| live (posted) | live, 2026-10-14 to 10-16, 5 trades | +2.31%, 4 won / 1 lost | - | too few to judge |

By period (realistic costs): train 272 trades -0.020%, validation 267 trades -0.027%, recent/test 88 trades
+0.170% (selection window), forward 16 trades -0.023%. Full tables, splits by ticker, side, entry time, SPY
trend, exit, opening volume and range width: [orb_audit.md](orb_audit.md).

## Why big tech ORB "worked" July-Oct 2026 and not before

- It mostly did not work before either: 25 months, positive in 10; the month's result is unrelated to market
  volatility (correlation +0.06) or how often the range filter passes (-0.01), and mildly negative with SPY's
  month (-0.35). Jul-Aug 2026 (+0.47%, +0.34%) and Jan 2026 (+0.32%) are clusters, not a regime a filter
  known at the open can pick out.
- The edge is entirely the trades held to the bell (+0.26% avg, 58% of trades); stops (-0.89%) eat it.
  Good months are months with all-day drift after the break.
- Six correlated names: several same-side trades a day are one bet, which is why monthly swings are large.

## Pre-registered changes (fixed in `src/orb_audit.py` before running; 6 variants, noise floor 1.89 SE)

| change | train | validation | verdict |
|---|---|---|---|
| H1 trade with SPY's 20-day trend | -0.039% | -0.083% | rejected (worse everywhere; trades against the trend did better) |
| H2 max 2 same-side entries / 10 min | -0.010% | -0.059% | rejected |
| H3 opening volume >= its 14-day average | +0.015% | +0.079% | closest; rejected: t 0.87 below the 1.89 floor, forward -0.36% (10 trades), negative at 0.10% on train |
| H4 breakout close >= 0.10 range past | +0.003% | +0.006% | rejected (zero edge, worse when late) |
| H5 entries 09:35-09:39 only | +0.015% | -0.031% | rejected |
| all five combined (information only) | +0.162% (53) | +0.043% (43) | not eligible; test -0.153% |

The all-negative case was checked first: H1, H2 and H5 stay negative on train+validation. No stop/target
variant was run: 63-78% of trades end at the bell and the settled research found none positive.

## What was wrong (with evidence) and what changed

| problem | evidence | change | file |
|---|---|---|---|
| Signals posted a minute late | 4 of 9 big tech signals 9-16 Oct posted 60 s after their bar (`state/latency.jsonl`): the websocket wakes the bot, but the bars are re-read over REST, which can lag a few seconds; the missing minute was forward-filled | re-read up to 4 x 1.5 s when the minute that just closed is missing; tests show the signal now comes on the same tick and the wait is capped at 6 s | `src/orb_live.py`, `src/orb_paper.py`, `tests/test_orb_live.py` |
| Blind window after 10:05 | polling gaps of 9, 21, 7, 14, 9 min on 2, 9, 14, 15, 16 Oct: the open job stopped at 10:05 and cron started the next job late | open job polls to 10:35 (timeout 130 min); session job runs 335 min so it does not hand over at the 15:55 exits | `.github/workflows/live-open.yml`, `live-bot.yml`, `src/live_bot.py` |
| Late-fill stress could not be modelled | `delay=1` filled at the next minute's open, about the same price as the signal close | default-off `delay_fill="close"` for a full-minute-late fill (live unchanged) | `src/orb_research.py` |
| Research/live drift | none found: the backtest matches all 13 ledger trades 6-16 Oct exactly (side, time, result) | - | `orb_audit.md` §7 |
| Reproduction | `orb_bigtech.md` reproduced: 88 / +0.170% and 267 / -0.027% (published 265 / -0.028%) | - | - |

No strategy logic was changed. `DAYTRADE_STRATEGY` still selects `bigtech` and is still stripped and lower-cased.
Break-and-retest stays off; `autotrade.ENABLED` stays False.

## What did not improve / remaining risks

- No filter makes the rule positive outside its selection window. The forward record is 16 backtest / 5 live
  trades - too small to overturn a two-year backtest in either direction.
- IEX bars only (2-3% of volume); the hand-made 105-name pool carries survivorship bias, which matters more
  for the 2024-25 year.
- The two live fixes change timing only, but they do change live jobs: they need your merge, and the first
  session after merging should be checked in `state/latency.jsonl`.
- The test suite once showed 2 failures that did not repeat in 5 later runs; not investigated.

## Reproduce

```
python -m src.audit_baseline                 # records baseline, local
gh workflow run orb-audit.yml --ref profitability-audit   # backtest audit (needs the Alpaca secrets)
python -m pytest -q
```
