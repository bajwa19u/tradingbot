# Rule sweep — consistency across market periods

**Symbols:** TSLA, NVDA, AAPL, AMD  
**Period:** 2024-06-01 → today  
**Generated:** 2026-09-25 20:52

The period is cut into consecutive chunks and every rule set is scored in each one separately. **Consistency is the column that matters.** A rule set that only works in one chunk was carried by that market, not by its rules.

| TF | Variant | Trades | Expectancy | Total R | **Positive in** | Worst period | Max DD |
|---|---|---|---|---|---|---|---|
| 1m | faithful +fast-retest-only | 68 ⚠ | +0.151R | +10.3 | **4/5** | -0.207R | -2.71% |
| 5m | faithful +fast-retest-only | 130 | +0.008R | +1.0 | **4/5** | -0.228R | -6.21% |
| 1m | faithful +15min-range | 53 ⚠ | +0.168R | +8.9 | **3/4** | -0.527R | -2.56% |
| 5m | faithful +tight-window | 159 | +0.056R | +8.9 | **3/5** | -0.184R | -5.42% |
| 5m | faithful +strong-volume | 141 | +0.046R | +6.4 | **3/5** | -0.183R | -5.74% |
| 5m | faithful +1H-context | 115 | +0.045R | +5.2 | **3/5** | -0.153R | -3.44% |
| 5m | faithful +momentum arm0.8 | 196 | -0.006R | -1.2 | **3/5** | -0.199R | -6.3% |
| 5m | faithful +momentum arm1.2 | 196 | -0.010R | -2.0 | **3/5** | -0.273R | -6.3% |
| 5m | faithful | 196 | -0.011R | -2.2 | **3/5** | -0.150R | -6.13% |
| 5m | faithful -stop-after-win | 196 | -0.011R | -2.2 | **3/5** | -0.150R | -6.13% |
| 2m | faithful +shorts-off | 87 ⚠ | -0.015R | -1.3 | **3/5** | -0.442R | -4.44% |
| 1m | faithful +shorts-off | 68 ⚠ | -0.016R | -1.1 | **3/5** | -0.610R | -3.42% |
| 5m | faithful +partial-at-1R | 195 | -0.027R | -5.2 | **3/5** | -0.198R | -6.19% |
| 1m | faithful +late-entries | 148 | -0.041R | -6.0 | **3/5** | -0.248R | -7.43% |
| 1m | faithful +momentum arm1.2 | 141 | -0.090R | -12.6 | **3/5** | -0.280R | -7.53% |
| 5m | faithful +loose-volume | 231 | +0.012R | +2.7 | **2/5** | -0.245R | -8.94% |
| 1m | faithful +1H-context | 82 ⚠ | +0.009R | +0.8 | **2/5** | -0.272R | -3.81% |
| 5m | faithful +momentum no-BE | 196 | -0.014R | -2.8 | **2/5** | -0.242R | -6.3% |
| 5m | faithful +no-breakeven | 196 | -0.025R | -5.0 | **2/5** | -0.133R | -6.82% |
| 1m | faithful +partial-at-1R | 141 | -0.028R | -4.0 | **2/5** | -0.255R | -7.14% |
| 1m | faithful | 142 | -0.041R | -5.9 | **2/5** | -0.251R | -6.99% |
| 2m | faithful +strong-volume | 109 | -0.045R | -4.9 | **2/5** | -0.600R | -5.3% |
| 5m | faithful +momentum +1H | 115 | -0.046R | -5.2 | **2/5** | -0.200R | -3.15% |
| 1m | faithful -stop-after-win | 144 | -0.049R | -7.1 | **2/5** | -0.251R | -6.99% |
| 1m | faithful +tight-window | 141 | -0.054R | -7.6 | **2/5** | -0.251R | -6.99% |
| 5m | faithful +3R-target | 196 | -0.064R | -12.5 | **2/5** | -0.300R | -7.0% |
| 2m | faithful +momentum +1H | 88 ⚠ | -0.073R | -6.4 | **2/5** | -0.426R | -4.81% |
| 1m | faithful +strong-volume | 133 | -0.074R | -9.8 | **2/5** | -0.346R | -4.63% |
| 1m | faithful +loose-volume | 139 | -0.088R | -12.2 | **2/5** | -0.336R | -5.81% |
| 1m | faithful +momentum arm0.8 | 141 | -0.100R | -14.1 | **2/5** | -0.280R | -7.53% |
| 2m | faithful +1H-context | 88 ⚠ | -0.159R | -14.0 | **2/5** | -0.742R | -6.56% |
| 5m | faithful -displacement | 246 | -0.033R | -8.0 | **1/5** | -0.147R | -7.86% |
| 1m | faithful +momentum 5-candle | 141 | -0.063R | -8.9 | **1/5** | -0.156R | -4.28% |
| 1m | current-rules | 141 | -0.066R | -9.4 | **1/5** | -0.157R | -4.5% |
| 1m | faithful +momentum-exits | 141 | -0.066R | -9.4 | **1/5** | -0.157R | -4.5% |
| 5m | current-rules | 196 | -0.073R | -14.3 | **1/5** | -0.161R | -6.29% |
| 5m | faithful +momentum-exits | 196 | -0.073R | -14.3 | **1/5** | -0.161R | -6.29% |
| 5m | faithful +momentum 5-candle | 196 | -0.073R | -14.3 | **1/5** | -0.161R | -6.29% |
| 1m | faithful +3R-target | 144 | -0.084R | -12.1 | **1/5** | -0.246R | -9.18% |
| 2m | faithful +momentum 5-candle | 162 | -0.085R | -13.8 | **1/5** | -0.307R | -5.31% |
| 5m | faithful +late-entries | 243 | -0.085R | -20.6 | **1/5** | -0.258R | -7.56% |
| 1m | faithful +momentum +1H | 81 ⚠ | -0.090R | -7.3 | **1/5** | -0.185R | -3.17% |
| 2m | current-rules | 162 | -0.097R | -15.6 | **1/5** | -0.307R | -5.31% |
| 2m | faithful +momentum-exits | 162 | -0.097R | -15.6 | **1/5** | -0.307R | -5.31% |
| 1m | faithful +no-breakeven | 142 | -0.098R | -14.0 | **1/5** | -0.279R | -8.09% |
| 1m | faithful +momentum no-BE | 141 | -0.125R | -17.6 | **1/5** | -0.291R | -8.09% |
| 2m | faithful -displacement | 382 | -0.153R | -58.3 | **1/5** | -0.341R | -12.67% |
| 5m | faithful +shorts-off | 115 | -0.157R | -18.1 | **1/5** | -0.574R | -5.36% |
| 2m | faithful +late-entries | 173 | -0.166R | -28.7 | **1/5** | -0.541R | -9.69% |
| 2m | faithful +no-breakeven | 162 | -0.177R | -28.7 | **1/5** | -0.520R | -9.31% |
| 2m | faithful +momentum arm0.8 | 162 | -0.178R | -28.9 | **1/5** | -0.480R | -8.87% |
| 2m | faithful +15min-range | 98 ⚠ | -0.198R | -19.4 | **1/5** | -0.588R | -5.54% |
| 2m | faithful +loose-volume | 185 | -0.211R | -39.1 | **1/5** | -0.415R | -10.59% |
| 2m | faithful +momentum arm1.2 | 162 | -0.228R | -36.9 | **1/5** | -0.514R | -9.42% |
| 2m | faithful +momentum no-BE | 162 | -0.241R | -39.1 | **1/5** | -0.549R | -9.89% |
| 1m | faithful -displacement | 496 | -0.100R | -49.7 | **0/5** | -0.211R | -9.14% |
| 2m | faithful -stop-after-win | 166 | -0.188R | -31.2 | **0/5** | -0.527R | -9.21% |
| 2m | faithful | 162 | -0.201R | -32.5 | **0/5** | -0.527R | -9.21% |
| 2m | faithful +tight-window | 146 | -0.214R | -31.2 | **0/5** | -0.536R | -7.83% |
| 2m | faithful +3R-target | 164 | -0.218R | -35.7 | **0/5** | -0.463R | -8.29% |
| 2m | faithful +partial-at-1R | 161 | -0.220R | -35.5 | **0/5** | -0.527R | -9.16% |
| 2m | faithful +fast-retest-only | 87 ⚠ | -0.275R | -24.0 | **0/5** | -0.665R | -6.5% |
| 5m | faithful +15min-range | 93 ⚠ | -0.309R | -28.8 | **0/5** | -0.688R | -6.54% |

## Verdict

**1 rule set(s) were profitable overall AND positive in all but at most one period, on 100+ trades.**

- `faithful +fast-retest-only` @ 5m — +0.008R over 130 trades, positive in 4/5 periods, worst -0.228R, max DD -6.21%

That is the strongest evidence a backtest can give, and it is still not proof. Before money: re-run on symbols not in this list, confirm the drawdown is one you could sit through, and paper-trade the live signals for several months. Free IEX data understates volume, so the volume filter behaves differently live than it does here.

## Notes

- Slippage 0.03% each side; a bar touching both stop and target is scored as a loss.
- A period needs 5+ trades to be scored at all.
- `faithful` = published method: 5-minute opening range, entries 09:30-11:00, displacement before retest, 2 attempts, done after a win.
- Each `faithful +/-x` changes exactly ONE rule, so the gap to `faithful` prices that rule.