# Project context — read this first

Handoff note so a new conversation can pick up without re-deriving anything.

## What this repo is

A signal bot and, more importantly, a **testing rig** for intraday trading
strategies. It does not place orders. Everything runs itself on GitHub
Actions; the only file normally edited is `config.yaml`.

Owner trades **USDJPY forex**, 07:30–17:00 IST, 1-hour for context and
5-minute for entries, one trade most days. Everything built so far runs on
**US equities via Alpaca**, which is a different market at different hours —
see Open questions.

## Where things stand (as of 2026-09-25)

Nothing profitable has been found. That is the honest summary.

| Run | Result |
|---|---|
| Original config | −0.234R expectancy, −87% drawdown, 942 trades |
| After fixing filters + adopting the published ruleset | −0.060R, −9.2% drawdown, 236 trades |
| Sweep, 63 variants × 5 market periods | one survivor at **+0.008R** (≈ $21 over 2.5 years) |
| Wide search, 114 configs × 6 families, locked holdout | winner held up in sign only: **+0.007R** on the holdout, positive in 2/4 periods |

**+0.007R is economically zero** — about 14 cents per trade at $20 risk. The
correct reading is that the search found no edge, not that it found a small
one.

## Bugs found and fixed (all have regression tests)

1. Fixed 2R target fired before the momentum exit logic could run — the whole
   fast-exit path was dead code.
2. 1-hour trend filter read candles that had not closed yet (look-ahead).
   Fixed by shifting the HTF series one bar forward.
3. Volume filter compared breakout volume to the *opening range* average, the
   highest-volume window of the day, so it rejected ~80% of all setups.
4. Engines were rebuilt each day with no warmup, so a 50-period EMA was not
   ready until 4 hours into the session and a 100-period one never was —
   **every `ema_pullback` config produced zero trades** in the wide search.
   Fixed; that family still needs a real run.

## What exists

- `src/strategy/` — 6 families: `break_retest`, `ema_pullback`,
  `vwap_reversion`, `orb_simple`, `rsi_extreme`, `momentum_breakout`
- `src/backtest.py` — bar-by-bar, pessimistic (stop wins ties), 0.03% slippage
- `src/sweep.py` — many rule sets, same bars, scored across N market periods
- `src/discover.py` — 114-config search + **one** run against a locked holdout
  (META/AMZN/GOOGL/MSFT, 2022–2024)
- `src/history.py` — `reports/history.md`, every run with only the settings
  that changed between them
- 35 tests. Run `python -m pytest tests/ -q`.

### Workflows
- **Tests** — every push
- **Backtest** — one config, detailed report (by hour, direction, MAE/stop analysis)
- **Sweep** — many rule sets compared
- **Discover** — the wide search with the holdout
- **Live signals** — every 5 min during market hours, Discord alerts

### Reports
`reports/latest.md` (backtest) · `reports/sweep.md` · `reports/discovery.md` ·
`reports/history.md` (run comparison)

## Method rules worth keeping

Owner's exit management, implemented as `exit_style: momentum`:
- watch 3 candles after entry
- ran fast to 2R → stop up to 2R, then trail each candle
- got past 1.5R but not convincingly through 2R → bank 1.5R
- never got going → target drops to 1.5R
- stop to entry on the **first** retest of entry (one retest, not two)

Published Scarface rules implemented: 5-minute opening range (first candle),
entries 09:35–11:00 only, displacement before the retest counts, FVG retests
accepted, max 2 trades, done after one winner.

## Open questions / next steps

1. **Wrong market.** Owner trades USDJPY; Alpaca has no retail forex. Needs a
   data source (OANDA API is the cleanest fit). The engine, backtester, sweep
   and discovery all port over; only `src/data.py` is equity-specific.
2. **EMA pullback is untested** — the warmup bug meant zero trades. Re-run
   Discover.
3. **Holdout is spent for `break_retest`.** Do not re-tune against it. A fresh
   holdout means new symbols or new dates.
4. **Longer horizons** — intraday is the most competitive corner. Daily or
   multi-day setups face weaker competition.

## Ground rules that have served this project well

- Expectancy (average R per trade) decides whether there is an edge. Win rate
  is misleading — breakeven scratches drag it down while costing nothing.
- A result only counts if it survives periods it was not selected on.
- Report how many configurations were tried. Search 114 things and ~5 clear a
  1-in-20 bar on noise alone.
- Never tune until the number turns green. That is how backtests lie.
