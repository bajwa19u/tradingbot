# Wide search

**Research set:** TSLA, NVDA, AAPL, AMD · 2024-06-01 → today · 5-minute  
**Locked holdout:** META, AMZN, GOOGL, MSFT · 2022-06-01 → 2024-05-31 — untouched until the end  
**Generated:** 2026-09-25 21:17

**114 configurations tried** across 6 strategy families. 2 passed the selection rule.

> Search enough configurations and the best one looks good by luck. With 114 tries, expect roughly 5 to clear a 1-in-20 bar on noise alone. That is why the holdout below is the only number that counts.

## Top 15 on the research set

| Configuration | Trades | Expectancy | Positive in | Worst period | Max DD |
|---|---|---|---|---|---|
| `break_retest/vol1.8_disp0.3_to11:00/fixed` | 27 ⚠ | +0.318R | 3/3 | +0.150R | -1.76% |
| `break_retest/vol1.8_disp0.3_to11:00/momentum` | 27 ⚠ | +0.277R | 3/3 | +0.170R | -2.03% |
| `break_retest/vol1.8_disp0.3_to14:30/momentum` | 33 ⚠ | +0.272R | 3/3 | +0.132R | -2.06% |
| `break_retest/vol1.8_disp0.3_to14:30/fixed` | 33 ⚠ | +0.237R | 3/3 | +0.150R | -1.76% |
| `break_retest/vol1.8_disp0.15_to11:00/fixed` | 141 | +0.046R | 2/4 | -0.050R | -5.75% |
| `break_retest/vol1.0_disp0.3_to14:30/fixed` | 45 ⚠ | +0.022R | 1/4 | -0.810R | -3.78% |
| `break_retest/vol1.8_disp0.0_to11:00/fixed` | 177 | +0.020R | 3/4 | -0.057R | -7.08% |
| `break_retest/vol1.0_disp0.0_to11:00/fixed` | 302 | +0.017R | 2/4 | -0.201R | -10.39% |
| `break_retest/vol1.0_disp0.15_to11:00/fixed` | 231 | +0.012R | 2/4 | -0.188R | -8.74% |
| `vwap_reversion/stretch0.5_stop0.2/momentum` | 362 | +0.012R | 3/4 | -0.070R | -8.05% |
| `break_retest/vol1.3_disp0.3_to14:30/fixed` | 42 ⚠ | +0.003R | 1/4 | -0.593R | -2.58% |
| `orb_simple/or30_stop0.3/momentum` | 1129 | +0.001R | 2/4 | -0.032R | -11.19% |
| `ema_pullback/ema9x100_slope0.05/fixed` | 0 ⚠ | +0.000R | 0/0 | +0.000R | 0.0% |
| `ema_pullback/ema9x100_slope0.05/momentum` | 0 ⚠ | +0.000R | 0/0 | +0.000R | 0.0% |
| `ema_pullback/ema9x100_slope0.15/fixed` | 0 ⚠ | +0.000R | 0/0 | +0.000R | 0.0% |

## The one that was selected

**`break_retest/vol1.8_disp0.0_to11:00/fixed`**

| | Research set | **Holdout (never seen)** |
|---|---|---|
| Trades | 177 | **166** |
| Expectancy | +0.020R | **+0.007R**
| Total R | +3.5 | **+1.2** |
| Positive in | 3/4 | **2/4** |
| Max drawdown | -7.08% | **-7.27%** |

### Verdict

**It held up on data it had never seen.**

That is the strongest result this process can produce, and it is still not a guarantee. Next steps, in order: paper trade the live signals for at least three months; compare the paper fills against what the backtest predicted; only then consider money, at a size where being wrong is survivable.

Do not re-tune on the holdout. It has been spent.