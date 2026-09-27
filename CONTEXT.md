# Project context — read this first

Handoff note so a new conversation can pick up without re-deriving anything.

**Status as of 2026-09-27: one rule has survived an out-of-sample test and is
now in a forward test. Nothing is being searched or tuned any more.**

## What this repo is

A testing rig for trading strategies, with a paper-trading forward test
attached. It does not place orders. Everything runs on GitHub Actions.

Owner trades **US stocks** (shares first, options later), 1-hour context and
5-minute entries by hand, roughly one trade a day. $2,000 account, paper only
for now. Earlier notes in this file claimed forex — that was wrong and the
owner corrected it: the USDJPY charts were reference material, not their
market.

Reporting rule the owner set: **win %, profit %, winners vs losers.** R
multiples are for internal work, not for reports.

## Where it landed

`base10_sq4.0_vol1.0_atr0.0` on the volatility-screened movers universe:

| | Tuned on | Never seen |
|---|---|---|
| Trades | 56 | 68 |
| Won / lost | 32 / 24 | 37 / 31 |
| Win % | 57.1% | 54.4% |
| Profit | +14.6% | +14.5% |
| Worst drop | −8.3% | −11.6% |

**The profit is the same on both sides.** That is the point. Every earlier
result in this project fell apart out of sample; the adaptive loop fit at
+0.4R and forward-tested at −1.0R over 33 refits. A rule with no fit-vs-forward
gap is the first thing here that has not behaved like memorised noise.

### What the volatility screen is and where it came from

Skip any symbol whose typical daily range is under **3.0%** of price, judged on
history *before* the trading window. Two independent measurements point at it:

1. The autopsy on 2026 found the one condition separating winners from losers
   was daily range — 5.35% vs 3.80%, +0.64 SD. Nothing else came close.
2. Split across all 103 names, the volatile half returned +24.4% on 65 trades
   at 61.5% win, the quiet half +5.8% on 56 at 51.8%.

**The honest limit:** the 3.0% threshold was chosen after seeing a split that
covered every symbol on every list. No stock is naive to that decision any
more, so there is no clean backtest left to run on it. The only remaining
honest test is forward, which is why `src/paper.py` exists.

## The other headline finding, still true

Searching configurations does not generalise on this data. The adaptive loop
refit monthly for 33 months: **refitting was 0.46R per trade worse than
standing still** (ADAPTIVE −0.368R vs STATIC +0.092R). Each refit performed
the same search-and-pick operation as the rest of the project, and failed
every time.

**Do not pick a configuration by searching this data.** The surviving rule came
from a forensic finding, not a sweep.

## Every result, in order

| What | Result | Note |
|---|---|---|
| Intraday break-and-retest, original | −0.234R (942 trades) | −87% drawdown |
| Same, filters fixed | −0.060R (236) | −9.2% drawdown |
| Sweep, 63 variants × 5 periods | +0.008R best | ≈ $21 over 2.5 years |
| Wide search, 114 configs, holdout | +0.007R | economically zero |
| Daily swing, 2023–2025 | +0.148R | looked real |
| Daily swing, 2016–2022 | −0.082R | bear markets |
| Daily swing, 2026 YTD | −0.090R (71) | losing |
| Adaptive loop vs static | −0.368R vs +0.092R | 33 refits, all failed |
| Expansion breakout, screened, unseen | **+14.5%, 54.4%, 37W/31L** | holds up |

## Bugs found and fixed (all have regression tests)

1. Fixed 2R target fired before the momentum exit — fast-exit path was dead.
2. 1-hour trend filter read candles that had not closed (look-ahead).
3. Volume filter compared breakout volume to the opening range, the day's
   highest-volume window — rejected ~80% of setups.
4. Engines rebuilt daily with no warmup, so long EMAs were never ready. Every
   `ema_pullback` config produced zero trades in the wide search.
5. `by_periods` sliced data then computed indicators, restarting every moving
   average at each period boundary.
6. Inspector's explanation table drifted from the live signal function.
7. **Trades did not equal won + lost.** The count was summed over period
   slices, which cut trades at each boundary, while wins and losses came from
   the full run. Worst-drop was understated the same way.
8. **A fake holdout.** `universe=wide` is every list at once, so nothing is
   left over — but the code still took the holdout from inside the traded set
   and labelled it "never seen".
9. **A leaking holdout.** `movers` and `research` share TSLA, NVDA and AMD, so
   every earlier "unseen" number from a movers run had 3 of 40 contaminated.
10. The volatility screen filtered the traded universe but not the holdout,
    comparing two different strategies to each other.
11. The split verdict claimed "the edge lives in the movers" on a universe
    where both halves averaged ~2% daily range — it never tested the idea.

Bugs 7–11 all inflated results or invented confirmation. Any number quoted in
an old conversation predating them should be re-derived, not trusted.

## What exists

- `src/paper.py` — **the forward test.** Replays from `paper.start` through the
  same `run_portfolio` as the backtest, every run. The ledger is derived, not
  stored, so it cannot drift or corrupt. Reports win %, profit %, W/L, open
  positions with entry/stop/target/shares, and halts at the drawdown line.
- `src/breakout.py` — the surviving strategy, plus the volatility split
- `src/swing.py` — daily trend pullback, portfolio-level; `run_portfolio` is
  shared by both strategies and now exposes still-open positions
- `src/forensics.py` — `autopsy()` (winners vs losers on 7 features),
  `missed()` (big moves not taken, and which gate blocked each)
- `src/adaptive.py` — the walk-forward loop, measured against static/hindsight
- `src/discover.py`, `src/sweep.py` — search machinery. Kept for reference;
  the finding above says not to trust what it selects.
- `src/backtest.py` — bar-by-bar, pessimistic (stop wins ties), 0.03% slippage
- `src/inspect_symbol.py` — one symbol, every rule as a column, per bar
- 67 tests. `python -m pytest tests/ -q`

### Workflows
Tests (every push) · **Paper account (daily, 21:30 UTC, weekdays)** · Backtest ·
Sweep · Discover · Swing · Adaptive · Inspect · Forensics · Breakout ·
Live signals (**schedule disabled 2026-09-26** — it was firing every 5 minutes
on the −0.234R strategy)

## Method rules from the owner that earned their place

`exit_style: momentum`, measurably better than the fixed 2R it replaced:
- watch 3 candles after entry
- fast to 2R → stop up to 2R, then trail each candle
- past 1.5R but not convincingly through 2R → bank 1.5R
- never got going → target drops to 1.5R
- stop to entry on the **first** retest of entry, not the second

The trend-slope chop filter came from the owner spotting, on a MET chart, that
the strategy fired repeatedly into a flat market. **Two of the best ideas in
this project came from reading charts, not from searching parameters.**

## Ground rules earned the hard way

- A result counts only if it survives data it was not selected on.
- Report how many configurations were tried. Search 114 and about 5 clear a
  1-in-20 bar on noise alone.
- Never tune until the number turns green.
- **A forward test beats any backtest.** The adaptive run is the proof.
- Every headline number must come from one run, so trades = won + lost.
- A holdout must have the traded universe subtracted, not merely be a
  different list.

## Next steps

1. **Let the paper account run.** It needs 20+ closed trades before its
   numbers mean anything, 50+ before they settle. Do not touch the rule while
   it accumulates — that restarts the clock and is the exact mistake the
   adaptive loop proved costly.
2. On a $2,000 account at 1% risk the budget is $20 a trade, so some signals
   are un-takeable at any whole share count. `paper.md` marks these "too
   small". Worth counting how often it happens.
3. Options come after shares are working. Same signals, more leverage, and
   every mistake amplified.
4. Do not re-open any holdout universe. All three have been used.

## Open questions for the owner

- Drawdown number that would make them stop. **Defaulted to 25% in
  `config.yaml` (`paper.halt_drawdown_pct`)** — change it there.
- Discord webhook is still wrong: the `DISCORD_WEBHOOK_URL` secret does not
  start with `https://discord.com/api/webhooks/`, so notify-test fails. Likely
  a `discord.gg` invite link was pasted instead of a webhook URL.
- Check-in frequency (daily / few times a week / on ping only).
