# Working on this repo

Read this first. It exists so a new session does not have to rediscover the
project by reading everything, and so the mistakes below are not made twice.

## What this is

Two unrelated programs sharing a folder.

**The intraday bot** — opening-range breaks on ~10 megacaps, Alpaca minute
bars, posts signals to Discord. `live_bot`, `opening`, `retest`, `inplay`,
`data`, `paper`, `forensics`, `confidence`, `broker`, `smoke`, `calendars`.

**The earnings study** — do some companies drift up before they report. SEC
filings and daily closes, posts nowhere. `preearn`, `preearn_screen`,
`fundamentals`.

They share `config.py` and nothing else. `tests/test_boundaries.py` walks the
import graph and fails if either side grows a dependency on the other. If it
goes red, the fix is almost never to add a name to a list — it is that the
shared thing belongs in its own module.

## House rules

- **Report win %, profit % and winners vs losers. Never R multiples.** Uday
  has asked for this more than once.
- **No dollar signs in Discord cards.** No share counts either — position
  size belongs to one account and printing it reads as an instruction.
- **Explore and holdout, always.** Choose on the explore dates, report the
  holdout beside it, and print the noise floor for the number of variants
  tried. `sqrt(2 ln N)` standard errors.
- **A verdict must check the all-negative case FIRST.** This project has
  twice shipped a report saying something "held up" while the number was
  negative. `exitsweep.py` has the pattern and the tests that pin it.
- **Profit rules fire on a bar's close, never its high or low.** A rule that
  fills at a wick books money nobody could have taken. Stops and targets may
  use high/low because those are resting orders.
- **Nothing goes live untested.** New exit rules, filters and entry windows
  ship switched off, with a test asserting the live settings still have them
  off, until a holdout says otherwise.

## Things that are already settled — do not re-litigate

- **The free IEX premarket feed is unusable.** It carries premarket bars on
  about 1% of days. Anything built on premarket highs and lows silently does
  nothing. This is a data-plan problem, not a code problem.
- **The cohort/correlation idea was wrong.** Crowd breaks won *more* than
  lone breaks, the opposite of the hypothesis. Measured on 3,388 breaks.
- **Wider stops help a lot and do not reach profit.** +2% stop room took the
  holdout from -25.0% to -8.7%.
- **The gap direction is the only filter that survived both splits.** With
  the gap +27.0% holdout, against it heavily negative. It is what the
  confidence levels in `confidence.py` are built from.
- **Holding to the bell is the biggest leak.** 30 September: +7.01% of
  favourable movement across seven trades became -4.58%.

## Running things

Nothing that needs market data runs locally — Alpaca and Yahoo are not
reachable from the container, and SEC is not either. Everything real runs as
a GitHub Action and commits its report back to `reports/`.

```
tests.yml            every push; two jobs, one per program
exitsweep.yml        which exit rule keeps the money
calendars.yml        shares and contracts, day by day
preearn-screen.yml   the two-gate earnings screen
smoke.yml            09:00 ET, can the paper account trade today
live-open.yml        the open, polling
live-bot.yml         the rest of the session
```

`python -m pytest -q` works locally and should stay green.

## Alpaca

`broker.py` is paper-only by construction: the base URL is a constant, not
config, and a test fails if a live hostname appears in the source. Caps are
enforced inside the broker so a caller that forgets cannot spend past them:
$1,000 a trade, $6,000 a day, 8 positions. `flatten()` closes everything
before the bell — letting options expire cost $24,773 on 30 September.

## Keeping sessions cheap

- Work in **Claude Code on the Mac**, not through the desktop bridge. Direct
  git, no bundles, no screenshots.
- **One task per session.** Long sessions re-read themselves every turn.
- Point at a file and say what to change. Do not ask for a tour of the repo.
- Ask for the report, not the raw numbers — `reports/*.md` are written to be
  read directly.
