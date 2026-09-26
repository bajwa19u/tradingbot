# Run history

3 run(s). Columns shown are the settings that **changed** between runs — identical settings are hidden.

| # | When | Kind | strategy | timeframe | retest_bars | exits | arm_R | Trades | Expectancy | Total R | Win % | Max DD | Δ exp |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2026-09-25 20:36 | backtest | None | 5 | 8 | momentum | None | 236 | -0.060R | -14.2 | 19.5 | -9.2% |  |
| 2 | 2026-09-25 20:52 | sweep | None | 1 | 4 | fixed | 0.3 | 68 ⚠ | +0.151R | +10.3 | 0.0 | -2.71% | +0.211 ✅ |
| 3 | 2026-09-26 13:09 | backtest | break_retest | 5 | 8 | momentum | 0.3 | 405 | -0.036R | -14.6 | 21.0 | -10.41% | -0.187 ❌ |

## Best so far

**Run #3** (2026-09-26 13:09) — -0.036R over 405 trades, max drawdown -10.41%.

Its settings: `strategy=break_retest`, `timeframe=5`, `retest_bars=8`, `exits=momentum`, `arm_R=0.3`

Note: the best run so far still has **negative expectancy**. Nothing here is tradeable yet.

## Reading this

- **Expectancy** is the average R per trade and is the number that decides whether there is an edge.
- **Δ exp** compares each run to the one before it. It is only meaningful when one thing changed.
- Runs with fewer than 100 trades are marked ⚠ and should not drive decisions.
- Comparing runs over different periods or symbols compares markets, not rules. Check the period column before concluding.