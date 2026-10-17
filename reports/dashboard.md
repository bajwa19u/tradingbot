# Dashboard summary

Built 2026-10-17 11:30 ET from the bots' own records. Open `reports/dashboard.html` in a browser for the interactive version.

Each bot is one record: backtest before its first real trade, real trades from then on. The two bots are in different units and are never added together.

| bot | unit | record | trades | won / lost | win % | profit | verdict |
|---|---|---|---|---|---|---|---|
| Day-trade bot | % of account | all, 2024-10-01 to 2026-10-16 | 643 | 285 / 358 | 44% | +0.10% | Net +0.10 over 643 trades, but the 95% interval of the average trade includes zero: not distinguishable from noise. |
| Day-trade bot | % of account | real only, from 2026-10-14 | 5 | 4 / 1 | 80% | +2.31% | Net +2.31 over 5 trades: too few to judge (under 30). Read it as a record, not a result. |
| Swing bot | % stock move | all, 2024-05-06 to 2026-10-14 | 397 | 234 / 163 | 59% | +742.47% | Net +742.47 over 397 trades and the 95% interval of the average trade stays above zero. |
| Swing bot | % stock move | real only, from 2026-09-28 | 4 | 3 / 1 | 75% | +7.03% | Net +7.03 over 4 trades: too few to judge (under 30). Read it as a record, not a result. |

## Sources

- Day-trade bot: real from `state/ledger_daytrade.csv`, backtest from `bajwa19u/tradingbot@profitability-audit:reports/orb_audit_trades.csv`
- Swing bot: real from `bajwa19u/vwap-ema-swing@main:state/ledger.csv`, backtest from `bajwa19u/vwap-ema-swing@profitability-audit:reports/audit_trades.csv`

## Checks

- OK · daytrade · trades = wins + losses + flat: 643 = 285 + 358 + 0
- OK · daytrade · no backtest trade on or after the first real trade: real from 2026-10-14
- OK · daytrade · no trade listed twice: 0 duplicate(s)
- OK · swing · trades = wins + losses + flat: 397 = 234 + 163 + 0
- OK · swing · no backtest trade on or after the first real trade: real from 2026-09-28
- OK · swing · no trade listed twice: 0 duplicate(s)
