# Daily trend pullback

**Research:** 40 large caps · trading from 2023-01-01 · daily bars (indicators warmed on earlier history)  
**Locked holdout:** 30 different companies (insurers, financials, industrials, materials) — opened once, at the end  
**Generated:** 2026-09-26 02:00

**39 configurations tried.** 17 passed.

| Configuration | Trades | Expectancy | Positive in | Worst period | Max DD |
|---|---|---|---|---|---|
| `ema10_tgt3.0_stop0.3_slope2.0` | 373 | +0.1477R | 3/4 | -0.0306R | -18.65% |
| `ema20_tgt0.0_trail1_stop0.5` | 403 | +0.1102R | 3/4 | -0.1706R | -25.57% |
| `ema20_tgt0.0_trail1_stop1.0` | 320 | +0.0984R | 3/4 | -0.2818R | -26.13% |
| `ema20_tgt0.0_stop0.5_slope2.0` | 251 | +0.0817R | 1/4 | -0.1628R | -19.2% |
| `ema10_tgt3.0_stop0.3_slope0.5` | 516 | +0.0707R | 2/4 | -0.0637R | -27.13% |
| `ema10_tgt3.0_stop0.3_slope1.0` | 516 | +0.0680R | 3/4 | -0.0528R | -24.86% |
| `ema10_tgt3.0_trail1_stop0.3` | 559 | +0.0651R | 3/4 | -0.0818R | -30.79% |
| `ema20_tgt2.0_trail0_stop0.5` | 400 | +0.0635R | 2/4 | -0.0092R | -24.41% |
| `ema20_tgt0.0_stop0.5_slope1.0` | 344 | +0.0613R | 3/4 | -0.1932R | -26.57% |
| `ema20_tgt2.0_trail1_stop0.5` | 498 | +0.0576R | 3/4 | -0.0821R | -21.94% |
| `ema10_tgt3.0_trail0_stop1.0` | 265 | +0.0543R | 2/4 | -0.2247R | -26.6% |
| `ema20_tgt0.0_stop0.5_slope0.5` | 367 | +0.0529R | 3/4 | -0.2613R | -29.77% |

## Selected configuration

**`ema10_tgt3.0_stop0.3_slope2.0`** — {"fast": 10, "mid": 50, "slow": 200, "touch_atr": 0.25, "touch_window": 3, "trend_bars": 10, "stop_atr": 0.3, "target_r": 3.0, "trail_ema": true, "trail_after_r": 1.0, "max_hold": 60, "risk_pct": 1.0, "max_open": 8, "slope_bars": 20, "min_slope_atr": 2.0, "cooldown_bars": 0}

| | Research | **Holdout (unseen companies)** |
|---|---|---|
| Trades | 373 | **350** |
| Expectancy | +0.1477R | **+0.1437R** |
| Total R | +55.1 | **+50.3** |
| Positive in | 3/4 | **3/4** |
| Win rate | — | **48.3%** |
| Return (1% risk) | — | **61.3%** |
| Max drawdown | -18.65% | **-21.94%** |

### Verdict

**Held up on companies it had never seen.**

At this horizon that is a meaningful result — daily trend following has real academic support, unlike the intraday patterns tested earlier. Still: paper trade it, check the drawdown is one you could actually sit through, and do not re-tune against this holdout. It has been spent.