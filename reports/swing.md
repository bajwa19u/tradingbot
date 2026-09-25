# Daily trend pullback

**Research:** 40 large caps · trading from 2023-01-01 · daily bars (indicators warmed on earlier history)  
**Locked holdout:** 30 different companies (insurers, financials, industrials, materials) — opened once, at the end  
**Generated:** 2026-09-25 22:59

**30 configurations tried.** 13 passed.

| Configuration | Trades | Expectancy | Positive in | Worst period | Max DD |
|---|---|---|---|---|---|
| `ema20_tgt0.0_trail1_stop0.5` | 403 | +0.1102R | 3/4 | -0.1706R | -25.57% |
| `ema20_tgt0.0_trail1_stop1.0` | 320 | +0.0984R | 3/4 | -0.2818R | -26.13% |
| `ema10_tgt3.0_trail1_stop0.3` | 559 | +0.0651R | 3/4 | -0.0818R | -30.79% |
| `ema20_tgt2.0_trail0_stop0.5` | 400 | +0.0635R | 2/4 | -0.0092R | -24.41% |
| `ema20_tgt2.0_trail1_stop0.5` | 498 | +0.0576R | 3/4 | -0.0821R | -21.94% |
| `ema10_tgt3.0_trail0_stop1.0` | 265 | +0.0543R | 2/4 | -0.2247R | -26.6% |
| `ema20_tgt3.0_trail1_stop0.5` | 454 | +0.0493R | 3/4 | -0.1402R | -24.17% |
| `ema10_tgt3.0_trail0_stop0.3` | 361 | +0.0460R | 3/4 | -0.3056R | -36.13% |
| `ema10_tgt3.0_trail0_stop0.5` | 342 | +0.0406R | 3/4 | -0.3774R | -38.34% |
| `ema20_tgt3.0_trail0_stop0.3` | 371 | +0.0375R | 3/4 | -0.2054R | -28.28% |
| `ema20_tgt2.0_trail1_stop1.0` | 381 | +0.0299R | 3/4 | -0.2012R | -25.19% |
| `ema20_tgt0.0_trail1_stop0.3` | 443 | +0.0291R | 2/4 | -0.2728R | -30.03% |

## Selected configuration

**`ema10_tgt3.0_trail1_stop0.3`** — {"fast": 10, "mid": 50, "slow": 200, "touch_atr": 0.25, "touch_window": 3, "trend_bars": 10, "stop_atr": 0.3, "target_r": 3.0, "trail_ema": true, "trail_after_r": 1.0, "max_hold": 60, "risk_pct": 1.0, "max_open": 8}

| | Research | **Holdout (unseen companies)** |
|---|---|---|
| Trades | 559 | **548** |
| Expectancy | +0.0651R | **+0.1128R** |
| Total R | +36.4 | **+61.8** |
| Positive in | 3/4 | **2/4** |
| Win rate | — | **48.3%** |
| Return (1% risk) | — | **88.1%** |
| Max drawdown | -30.79% | **-29.14%** |

### Verdict

**Did not clear the bar on unseen companies.**

Expectancy +0.1128R over 548 trades, positive in 2/4 periods. Positive numbers that small do not survive real costs. No re-tuning against the holdout.