# Rule sweep (train / test split)

**Symbols:** TSLA, NVDA, AAPL, AMD  
**Period:** 2025-01-01 → today  
**Generated:** 2026-09-25 20:06

Variants are ranked by the **TRAIN** window. The **TEST** columns are dates the variant was never selected on. Only the test column tells you anything about the future.

| TF | Variant | Train n | Train exp | Train R | **Test n** | **Test exp** | **Test R** | Test DD |
|---|---|---|---|---|---|---|---|---|
| 1m | faithful +fast-retest-only | 38 | +0.190R | +7.2 | **13 ⚠** | **+0.028R** | **+0.4** | -1.06% |
| 1m | faithful +partial-at-1R | 68 | +0.132R | +9.0 | **25 ⚠** | **+0.271R** | **+6.8** | -1.24% |
| 1m | faithful | 68 | +0.097R | +6.6 | **25 ⚠** | **+0.297R** | **+7.4** | -1.16% |
| 1m | faithful +late-entries | 71 | +0.085R | +6.1 | **26 ⚠** | **+0.282R** | **+7.3** | -1.16% |
| 1m | faithful +no-breakeven | 68 | +0.085R | +5.8 | **25 ⚠** | **+0.168R** | **+4.2** | -1.71% |
| 1m | faithful +tight-window | 67 | +0.078R | +5.2 | **25 ⚠** | **+0.297R** | **+7.4** | -1.16% |
| 1m | faithful -stop-after-win | 70 | +0.077R | +5.4 | **26 ⚠** | **+0.244R** | **+6.3** | -1.16% |
| 1m | faithful +shorts-off | 27 ⚠ | +0.048R | +1.3 | **16 ⚠** | **+0.464R** | **+7.4** | -0.68% |
| 1m | faithful +3R-target | 69 | +0.033R | +2.3 | **26 ⚠** | **+0.276R** | **+7.2** | -1.05% |
| 5m | faithful +fast-retest-only | 62 | +0.026R | +1.6 | **31** | **+0.041R** | **+1.3** | -2.67% |
| 1m | faithful +loose-volume | 68 | +0.020R | +1.4 | **27 ⚠** | **+0.056R** | **+1.5** | -2.44% |
| 5m | faithful +strong-volume | 61 | -0.039R | -2.4 | **35** | **+0.111R** | **+3.9** | -4.02% |
| 5m | faithful +no-breakeven | 89 | -0.056R | -5.0 | **50** | **+0.003R** | **+0.1** | -6.87% |
| 1m | faithful +strong-volume | 67 | -0.064R | -4.3 | **25 ⚠** | **-0.027R** | **-0.7** | -2.22% |
| 1m | faithful -displacement | 266 | -0.090R | -23.9 | **103** | **-0.153R** | **-15.8** | -11.8% |
| 1m | faithful +15min-range | 26 ⚠ | -0.097R | -2.5 | **11 ⚠** | **+0.113R** | **+1.2** | -0.93% |
| 5m | faithful +tight-window | 69 | -0.097R | -6.7 | **39** | **+0.146R** | **+5.7** | -3.83% |
| 5m | faithful -displacement | 119 | -0.099R | -11.8 | **56** | **+0.104R** | **+5.8** | -5.51% |
| 5m | faithful +partial-at-1R | 88 | -0.108R | -9.5 | **50** | **+0.053R** | **+2.6** | -5.26% |
| 5m | faithful | 89 | -0.111R | -9.9 | **50** | **+0.075R** | **+3.8** | -5.63% |
| 5m | faithful -stop-after-win | 89 | -0.111R | -9.9 | **50** | **+0.075R** | **+3.8** | -5.63% |
| 2m | faithful +shorts-off | 45 | -0.113R | -5.1 | **23 ⚠** | **+0.033R** | **+0.8** | -4.63% |
| 5m | faithful +3R-target | 89 | -0.119R | -10.6 | **50** | **+0.029R** | **+1.5** | -6.66% |
| 2m | faithful +no-breakeven | 83 | -0.158R | -13.1 | **35** | **-0.125R** | **-4.4** | -7.22% |
| 5m | faithful +loose-volume | 110 | -0.163R | -17.9 | **62** | **+0.166R** | **+10.3** | -4.5% |
| 5m | faithful +late-entries | 118 | -0.179R | -21.1 | **61** | **-0.070R** | **-4.3** | -7.71% |
| 2m | faithful -displacement | 204 | -0.201R | -40.9 | **80** | **-0.189R** | **-15.1** | -10.89% |
| 2m | current-rules | 283 | -0.204R | -57.6 | **117** | **-0.177R** | **-20.7** | -10.79% |
| 2m | faithful +strong-volume | 50 | -0.228R | -11.4 | **26 ⚠** | **+0.113R** | **+2.9** | -4.5% |
| 5m | faithful +shorts-off | 58 | -0.252R | -14.6 | **30** | **-0.060R** | **-1.8** | -4.07% |
| 1m | current-rules | 330 | -0.253R | -83.6 | **138** | **-0.197R** | **-27.2** | -12.03% |
| 2m | faithful -stop-after-win | 86 | -0.257R | -22.1 | **36** | **-0.122R** | **-4.4** | -6.86% |
| 2m | faithful +partial-at-1R | 83 | -0.257R | -21.3 | **35** | **-0.099R** | **-3.5** | -5.53% |
| 2m | faithful | 83 | -0.261R | -21.7 | **35** | **-0.096R** | **-3.4** | -6.12% |
| 2m | faithful +loose-volume | 101 | -0.262R | -26.4 | **40** | **-0.022R** | **-0.9** | -7.4% |
| 2m | faithful +late-entries | 88 | -0.269R | -23.7 | **36** | **-0.052R** | **-1.9** | -6.12% |
| 2m | faithful +3R-target | 85 | -0.278R | -23.6 | **35** | **-0.214R** | **-7.5** | -6.65% |
| 2m | faithful +tight-window | 73 | -0.283R | -20.7 | **31** | **-0.159R** | **-4.9** | -6.06% |
| 2m | faithful +15min-range | 54 | -0.286R | -15.4 | **25 ⚠** | **+0.186R** | **+4.6** | -2.44% |
| 5m | current-rules | 204 | -0.359R | -73.2 | **89** | **-0.313R** | **-27.9** | -14.74% |
| 2m | faithful +fast-retest-only | 44 | -0.398R | -17.5 | **21 ⚠** | **-0.220R** | **-4.6** | -4.55% |
| 5m | faithful +15min-range | 45 | -0.517R | -23.3 | **23 ⚠** | **-0.028R** | **-0.7** | -5.31% |

## Verdict

**1 variant(s) were positive on BOTH windows with adequate sample size.**

- `faithful +fast-retest-only` @ 5m — train +0.026R (n=62), test +0.041R (n=31)

This is a necessary condition, not proof. Before risking money: re-run on different symbols, check the test drawdown is one you could actually sit through, and paper-trade the live signals for a few months. Free IEX data also understates volume, so the volume filter behaves differently live.

## Notes

- Slippage 0.03% each side; a bar touching both stop and target is scored as a loss.
- Train window is the first 70% of dates, test is the last 30%.
- `faithful` = published method: 5-minute opening range, entries 09:30-11:00, displacement before retest, 2 attempts, done after a win.
- Each `faithful +/-x` changes exactly ONE rule, so the gap to `faithful` prices that rule.