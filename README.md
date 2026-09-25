# TradingBot — opening-range break & retest

A signal bot for the Scarface Trades 5-minute opening-range break-and-retest
setup. It scans a watchlist plus the day's highest relative-volume movers,
applies the rules strictly, and messages you when a setup confirms.

**It does not place trades.** Every signal is an alert with an entry, a stop
and a 2R target. Execution stays manual until the signals have proven
themselves on paper.

---

## The 30-second version

| | |
|---|---|
| **Where it runs** | GitHub Actions — free, no server, no laptop |
| **How often** | Every 5 minutes, 9:30–16:00 ET, weekdays |
| **How you change it** | Edit `config.yaml`, commit, push. That's the whole workflow. |
| **How you trust it** | `tests/` proves every rule; `reports/latest.md` shows the backtest |
| **Where signals go** | Discord (default), Telegram, or email |

---

## Setup (about 10 minutes, once)

### 1. Push this to a private GitHub repo

```bash
git init
git add .
git commit -m "feat: break-and-retest signal bot"
gh repo create tradingbot --private --source=. --push
```

### 2. Get Alpaca API keys

Log in at <https://alpaca.markets> → **Home** → **API Keys** → generate.
Paper-trading keys are fine; only market data is used.

### 3. Set up a Discord channel for alerts

Any server you own → channel settings → **Integrations** → **Webhooks** →
**New Webhook** → **Copy Webhook URL**. (Prefer Telegram or email? See
`config.yaml` → `notifications.channels`.)

### 4. Add the secrets

Repo → **Settings** → **Secrets and variables** → **Actions** → **New
repository secret**:

| Secret | Value |
|---|---|
| `ALPACA_API_KEY` | from step 2 |
| `ALPACA_API_SECRET` | from step 2 |
| `DISCORD_WEBHOOK_URL` | from step 3 |

### 5. Turn it on

Repo → **Actions** tab → **I understand my workflows, go ahead and enable
them**. Then run **Backtest** manually once to confirm data access works.

Done. The bot now runs itself.

---

## Making changes

Everything tunable is in `config.yaml`, commented. Common edits:

```yaml
universe:
  watchlist: [AAPL, NVDA, TSLA]     # what to always scan
  min_relative_volume: 1.5          # raise to 2.0 for fewer, cleaner setups

strategy:
  breakout:
    volume_multiple: 1.3            # raise to demand a stronger break
  retest:
    max_bars_after_break: 8         # lower to only take fast retests
  filters:
    trade_shorts: false             # longs only
    max_trades_per_day: 4

risk:
  account_equity: 10000
  risk_per_trade_pct: 1.0
  reward_multiple: 2.0              # the 2R target
```

Change a value → commit → push. The tests run automatically on push; if a
change breaks a rule, the Actions tab goes red before any money is involved.

**Before trusting a change, backtest it:** Actions → **Backtest** → **Run
workflow**. Results land in `reports/latest.md`.

---

## Running it locally

```bash
pip install -r requirements.txt
export ALPACA_API_KEY=...  ALPACA_API_SECRET=...

python -m pytest tests/ -q                  # verify the rules
python -m src.run_live --dry-run            # scan now, print, don't notify
python -m src.run_backtest --symbols AAPL,NVDA --start 2025-01-01
```

---

## The rules it enforces

1. **Opening range** — first 15 minutes set the high and low. The range must
   be between 0.15x and 1.5x ATR: tighter is noise, wider means the move is
   already spent.
2. **Break** — a 5-minute candle must *close* beyond the level, clearing it
   by at least 0.05%, on 1.3x the opening-range average volume.
3. **Retest** — price must return to the broken level within 8 bars. A close
   back *through* the level kills the setup for the day.
4. **Confirmation** — the retest must be rejected by a hammer or an engulfing
   candle. No confirmation candle, no trade. This is the rule that separates
   the setup from buying any old pullback.
5. **Risk** — stop beyond the confirmation candle's extreme plus an ATR
   buffer; target at 2R; stop to breakeven once 1R is reached; everything
   flat by 15:55 ET.

Plus: VWAP alignment, a daily loss limit of -2R, one trade per symbol per
day, four trades per day maximum.

Every rejected setup is logged with a reason, so the backtest tells you *why*
setups were skipped, not just how the survivors did.

---

## Repo map

```
config.yaml                 ← the only file you normally edit
src/
  config.py                 loading + validation
  data.py                   Alpaca market data (REST, no SDK)
  indicators.py             ATR, VWAP, candle patterns
  universe.py               watchlist + relative-volume movers scanner
  strategy/break_retest.py  the rules, as a state machine
  backtest.py               bar-by-bar simulation
  run_live.py               the scheduled scan
  run_backtest.py           historical validation + reports
  notify.py                 Discord / Telegram / email
tests/
  fixtures.py               hand-built bars with known outcomes
  test_strategy.py          proves every rule fires and every filter blocks
.github/workflows/
  live-signals.yml          every 5 min during market hours
  backtest.yml              weekly + on demand
  tests.yml                 every push
reports/latest.md           most recent backtest, human-readable
```

---

## Things worth knowing

- **Free Alpaca data is the IEX feed**, which is a slice of total volume.
  Signals are directionally right but volume filters are less precise than
  on the paid consolidated (SIP) feed. Switch with `backtest.bar_feed`.
- **GitHub's scheduler is best-effort.** A 5-minute cron can slip by a few
  minutes under load. Fine for alerts; not good enough for auto-execution,
  which is one more reason execution stays manual for now.
- **Scheduled workflows pause after 60 days** of no repo activity. The bot
  commits its state file on signal days, which keeps it alive.
- **Backtest results are not a promise.** Slippage is modelled at 0.03% and
  a bar that touches both stop and target is scored as a loss — deliberately
  pessimistic, and still optimistic compared to live fills.

---

## Not financial advice

This is a tool for generating and testing signals. Intraday breakout trading
loses money for most people who try it. Trade the signals on paper until the
sample is large enough to mean something, and size positions you can afford
to be wrong about.
