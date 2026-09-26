# Project context — read this first

Handoff note so a new conversation can pick up without re-deriving anything.

**Status as of 2026-09-26: US equity work is stopped. Nothing here is
tradeable. The infrastructure is good; the strategies are not.**

## What this repo is

A testing rig for trading strategies, with a signal bot attached. It does not
place orders. Everything runs on GitHub Actions. `config.yaml` is the only
file normally edited.

Owner trades **USDJPY forex**, 07:30–17:00 IST, 1-hour context and 5-minute
entries, roughly one trade a day. Everything built so far runs on **US
equities via Alpaca** — a different market at different hours. That mismatch
is the single biggest open item.

## The headline finding

A self-improving loop was built: every month, search all 39 configurations on
the trailing year, adopt the best, trade it forward. Over 33 refits on 30
unseen companies:

| | Trades | Expectancy | Win % | Max DD |
|---|---|---|---|---|
| **ADAPTIVE** (refits monthly) | 223 | **−0.368R** | 20.6% | **−56.8%** |
| STATIC (fixed config) | 288 | +0.092R | 45.8% | −20.7% |
| HINDSIGHT (unknowable) | 212 | +0.137R | 42.0% | −22.6% |

**Refitting was 0.46R per trade WORSE than standing still.** The per-refit log
in `reports/adaptive_holdout.md` shows why: fit expectancy averaged about
+0.4R, forward expectancy was consistently around −1.0R. Thirty-three
searches, thirty-three failures to generalise.

This matters beyond the loop. Each refit performed the same operation as the
rest of this project — search configurations, pick the best. It failed every
time. That is strong evidence the earlier positive results were selection
noise that simply lacked a forward test.

**Do not build on a configuration selected by searching this data.**

## Every result, in order

| What | Expectancy | Note |
|---|---|---|
| Intraday break-and-retest, original config | −0.234R (942 trades) | −87% drawdown |
| Same, after fixing filters + published ruleset | −0.060R (236) | −9.2% drawdown |
| Sweep, 63 variants × 5 periods | +0.008R best | ≈ $21 over 2.5 years |
| Wide search, 114 configs, locked holdout | +0.007R holdout | economically zero |
| Daily swing, 2023–2025 | +0.148R / +0.144R holdout | looked real |
| Daily swing, 2016–2022, same config | **−0.082R** | bear markets |
| Daily swing, **2026 YTD only** | **−0.090R** (71) | losing right now |
| Adaptive loop vs static | **−0.368R vs +0.092R** | see above |

## Bugs found and fixed (all have regression tests)

1. Fixed 2R target fired before the momentum exit logic — the fast-exit path
   was dead code.
2. 1-hour trend filter read candles that had not closed (look-ahead).
3. Volume filter compared breakout volume to the opening-range average, the
   highest-volume window of the day — rejected ~80% of all setups.
4. Engines rebuilt daily with no warmup, so a 50-period EMA was not ready
   until 4 hours in and a 100-period one never was. Every `ema_pullback`
   config produced zero trades in the wide search.
5. `by_periods` sliced data then computed indicators, restarting every moving
   average at each period boundary.
6. Inspector's explanation table drifted from the live signal function — a
   test comparing the two caught it immediately.

## What exists

- `src/strategy/` — 6 intraday families behind a registry
- `src/swing.py` — daily trend pullback, portfolio-level, with position cap
- `src/backtest.py` — bar-by-bar, pessimistic (stop wins ties), 0.03% slippage
- `src/sweep.py` — many rule sets, same bars, scored across N periods
- `src/discover.py` — 114-config search + one run at a locked holdout
- `src/adaptive.py` — the walk-forward loop, measured against static/hindsight
- `src/inspect_symbol.py` — one symbol, every rule as a column, per bar
- `src/history.py` — run comparison showing only settings that changed
- 48 tests. `python -m pytest tests/ -q`

### Workflows
Tests (every push) · Backtest · Sweep · Discover · Swing · Adaptive · Inspect ·
Live signals (**schedule disabled 2026-09-26** — it was firing every 5 minutes
on the −0.234R strategy)

## Method rules that worked

Owner's exit management, as `exit_style: momentum` — measurably better than
the fixed 2R it replaced:
- watch 3 candles after entry
- fast to 2R → stop up to 2R, then trail each candle
- past 1.5R but not convincingly through 2R → bank 1.5R
- never got going → target drops to 1.5R
- stop to entry on the **first** retest of entry, not the second

The trend-slope chop filter came from the owner spotting, on a MET chart, that
the strategy fired repeatedly into a flat market. It improved expectancy and
cut drawdown by a third. Two of the best ideas in this project came from
reading charts, not from searching parameters.

## Ground rules earned the hard way

- Expectancy (average R per trade) decides whether there is an edge. Win rate
  misleads — breakeven scratches drag it down while costing nothing.
- A result counts only if it survives periods it was not selected on.
- Report how many configurations were tried. Search 114 and about 5 clear a
  1-in-20 bar on noise alone.
- Never tune until the number turns green.
- **A forward test beats any backtest.** The adaptive run is the proof.

## Next steps

1. **Forex.** The owner trades USDJPY; Alpaca has no retail FX. Needs a data
   source — OANDA's REST API is the cleanest fit. The engine, backtester,
   sweep, walk-forward and holdout machinery all port; only `src/data.py` is
   equity-specific. **Blocked on: which broker or data provider.**
2. If pursuing stocks again, use a **fixed, unoptimised rule**. Searching is
   the thing that has demonstrably failed here.
3. Do not re-open the holdout universes for the daily swing strategy. They
   have been used and are no longer clean.

## Open questions for the owner

- Which forex data source / broker?
- Drawdown number that would make them stop.
- Check-in frequency (daily / few times a week / on ping only).
