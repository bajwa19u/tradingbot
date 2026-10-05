"""The live bot. Two rules, one watchlist, one Discord feed.

  * OPENING RANGE BREAK, one-minute bars. The range is the high and low of
    the first five regular-session candles (09:30-09:34). The first candle
    that CLOSES above the range high is a long, below the range low a short;
    breaks count from 09:30 to 10:00, first break of each level only, one
    trade per stock per day. Entry at that close (+0.05% slippage), stop past
    the session's extreme so far plus a small buffer from yesterday's opening
    half hour, target twice the stop distance, else out at 15:55.
    (`OPENING["levels"] == "or"`. The opening module can also trade
    yesterday's and the premarket's levels; the live bot does not.)
  * BREAK AND RETEST, five-minute bars, SHORTS ONLY. A tight one-hour coil
    (12 bars, width <= 3 average 5-minute moves) breaks on a red candle with
    at least average volume; price comes back within a quarter of an average
    move of the level inside 12 bars; entry at that close, stop one average
    move past the level, target twice the stop distance, else out at 15:55.
    The window is 09:45-15:30 on paper, but the indicators warm up on today's
    bars alone, so the first possible break is about 11:40.

Posts an entry the moment either rule fires, a close when the trade ends,
and one summary at the bell.

Three design choices that matter:

The opening window is covered by a POLLING run, not by cron. GitHub's
scheduled workflows are routinely several minutes late, which is survivable
at 11am and useless at 09:31. One job starts before the bell and checks
every forty-five seconds until 10:05; cron only has to be roughly on time
once, to start it.

The day is REPLAYED in full on every run, and what has already been announced
is tracked separately. Nothing about a position is carried forward in mutable
state, so a missed run, a duplicate run or a crash cannot corrupt the record -
the next run simply recomputes the same day and announces whatever is new.
The alternative, mutating a positions file, is how a bot ends up holding a
trade that closed an hour ago.

The last bar is always DROPPED. A five-minute bar that is still forming has a
close that has not happened yet, and the rule enters on a close. Acting on a
partial bar means entering at a price the rule never saw.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time as _time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from . import autotrade
from . import confidence as conf
from . import discord_msg as dm
from . import opening as op
from . import orb_live
from . import stream as st
from .config import REPO_ROOT, Credentials
from .data import AlpacaError, MarketData
from .forensics import LIVE as WATCHLIST
from .paper import settings, shares
from .retest import LIVE, SCAN, STOP_ATR, TARGET_R, breaks_in, find_retest
from .squeeze import prepare_sq

EASTERN = ZoneInfo("America/New_York")
REPORTS = REPO_ROOT / "reports"
STATE = REPO_ROOT / "state"
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("live_bot")

OPEN_T, CLOSE_T = "09:45", "15:55"      # the retest rule's window
BELL = "09:30"                          # the opening rule's window starts here
OPENING_LAST_RUN = "10:05"              # after this the polling job stops

# The opening rule runs in OBSERVATION mode, and the distinction is the whole
# point of this block.
#
# Two studies were run against it, each with its own holdout. Breaks of
# yesterday's levels made +12.5% on the dates the settings came from and lost
# 18.2% on dates they had never seen. Breaks of the session's own opening
# range made +4.1% and then lost 30.4% the same way. Neither is an edge;
# both are what searching a grid produces. So this rule does not size
# positions and its results are reported apart from the validated one.
#
# It runs anyway, on purpose, for two reasons: it is the only thing on the
# board that can see the first fifteen minutes at all, and a forward record
# gathered live is the one kind of evidence this project does not yet have.
#
# The settings are chosen by MECHANISM, not by rank in the table. `drive`
# because a move that never pulls back is exactly what the old rule could not
# take. `session` because the AMD audit showed the level stop dying in the
# opening spike at 09:32 before the real move began. A five-minute range
# because that is the shape the AMD tape actually had.
OPENING = {**op.BASE, "enabled": True, "observe": False,
           "levels": "or", "or_minutes": 5, "entry_mode": "drive",
           "stop_mode": "session", "target_r": 2.0, "pen": 0.0,
           "side": "both", "max_per_symbol": 1,
           # BOTH SIDES ARE POSTED. This started as shorts-only, on the
           # grounds that longs off the opening range lost 32.0% while shorts
           # made 5.7%. On 29 September that filter hid a working trade: AMD
           # broke its opening-range high at 09:51 and ran, and the feed never
           # showed it because it was a long.
           #
           # The asymmetry is also not stable. It favoured shorts in the
           # retest studies, favoured LONGS heavily in the stocks-in-play run
           # at a tight stop (+118% against -19%), and was roughly even at a
           # wide one. An argument that flips sign between studies is not an
           # argument for throwing away half the forward record of a rule
           # whose entire job right now is to gather one.
           "post_sides": ("short", "long")}

# How many entries inside this many minutes counts as one market move rather
# than several independent ideas. On 29 September ALL TWELVE core names broke
# their opening-range low between 09:35 and 09:45 and every one went short.
# That is not twelve signals; it is the whole market dipping at the open,
# read twelve times. At 1% risk each it would have been 11% of the account on
# a single directional bet, and in the forward record it will look like
# twelve data points when it is worth about one.
# Break & retest is off. 12 months of minute bars (reports/day_research.md):
# -0.29R per trade on train, -0.42R on validation, -0.43R on the untouched
# test dates, 95% intervals below zero in all three, and every variant tried
# (longs, both sides, volume, range width, four confirmations, warm-up) lost
# too. The code stays; turning it back on is a deliberate edit and a test.
RETEST_ENABLED = False

# Which opening strategy the day-trade channel runs. A feature flag, read from
# the DAYTRADE_STRATEGY environment variable (a GitHub repository variable of
# the same name sets it for the live jobs), default "classic".
#
#   classic     the opening-range rule above on the fixed ten megacaps
#   inplay_orb  ORB on the day's ten most in-play names with a wide range
#               (src/orb_live.py; rules from reports/orb_research.md)
#   bigtech     the same ORB rule on the owner's fixed big tech list
#               (orb_research.BIG_TECH; reports/orb_bigtech.md)
#
# inplay_orb beat classic on train, validation and test, and is positive on
# the untouched test (+0.14R, 95% CI above zero). It stays OFF by default
# because it failed the go-live gate fixed before that run: at 0.10% slippage
# per side its validation result turns negative. Its forward record is kept
# by src/orb_paper.py either way. A test pins the default.
STRATEGIES = ("classic", "inplay_orb", "bigtech")
ORB_STRATEGIES = ("inplay_orb", "bigtech")     # both run src/orb_live.py, on different lists


def strategy() -> str:
    s = (os.environ.get("DAYTRADE_STRATEGY") or "classic").strip().lower()
    if s not in STRATEGIES:
        log.warning("Unknown DAYTRADE_STRATEGY %r - using classic", s)
        return "classic"
    return s


STRATEGY = strategy()
if STRATEGY in ORB_STRATEGIES:
    orb_live.use(STRATEGY)
CLUSTER_MINUTES = 15
CLUSTER_WARN = 4


def simulate_day(day: pd.DataFrame, sym: str, p: dict, cfg: dict) -> list[dict]:
    """Every trade the rule would have taken today, with how each ended.

    A trade with no exit yet is returned open, which is what makes the close
    alert possible: the next run finds it finished and announces it.
    """
    out = []
    for i, side, level in breaks_in(day, {**p, "tail": 0}):
        if side != LIVE["side"]:
            continue
        j = find_retest(day, i, side, level, LIVE["wait"], LIVE["depth"],
                        LIVE["confirm"])
        if j is None:
            continue
        a = float(day["atr"].iloc[i])
        entry = float(day["close"].iloc[j])
        stop = level + STOP_ATR * a
        rps = abs(entry - stop)
        if rps <= 0 or rps / entry > 0.10:
            continue
        target = entry - TARGET_R * rps
        n = shares(entry, rps, cfg["equity"], cfg["risk_pct"])
        # The level is part of the identity. Without it two different breaks
        # that happen to enter on the same bar collide, and the second is
        # counted in the recap but never announced.
        t = {"id": f"{sym}-{str(day.index[j])[:16]}-{level:.2f}", "symbol": sym,
             "rule": "retest",
             "entry_time": str(day.index[j].tz_convert(EASTERN))[11:16],
             "entry": round(entry, 2), "stop": round(stop, 2),
             "target": round(target, 2), "shares": n,
             "risk": round(n * rps, 2), "level": round(level, 2),
             "exit": None, "exit_time": None, "reason": None, "pct": None}
        flat = pd.Timestamp(CLOSE_T).time()
        times = day.index.tz_convert(EASTERN).time
        for k in range(j + 1, len(day)):
            b = day.iloc[k]
            hi, lo = float(b["high"]), float(b["low"])
            px, why = None, None
            if hi >= stop:                    # stop first on ties
                px, why = stop, "stop"
            elif lo <= target:
                px, why = target, "target"
            elif times[k] >= flat:
                px, why = float(b["close"]), "bell"
            if px is not None:
                r = (entry - px) / rps
                t.update(exit=round(px, 2), reason=why,
                         exit_time=str(day.index[k].tz_convert(EASTERN))[11:16],
                         pct=round(r * cfg["risk_pct"], 2),
                         cash=round(n * (entry - px), 2))
                break
        out.append(t)
    return out


# --- latency ------------------------------------------------------------------
# A signal is only worth posting while its setup is still there. The bot used
# to sleep a fixed 45-60 s between polls and re-download five days of bars
# each time; on 1 October all ten opening signals reached Discord together at
# 10:13, 13-43 minutes after their bars closed. Now: poll a few seconds after
# each minute closes, fetch only what changed, stamp every signal with its age,
# and mark anything older than its setup allows as EXPIRED instead of posting
# it as a fresh entry.
BAR_LAG_S = 4                                  # IEX publishes a minute bar ~1-3 s after it closes
BAR_MIN = {"opening": 1, "retest": 5, "inplay_orb": 1}          # bar length each rule enters on
MAX_AGE_S = {"opening": 120, "retest": 360, "inplay_orb": 120}  # older than this at first sight = expired
STALE_AFTER_S = 180                            # newest 1-minute bar older than this = stale data
LATENCY_FILE = "latency.jsonl"
_TIMES: dict = {}                              # per-tick stage timings, seconds
_LAST_1M: dict = {}                            # newest 1-minute bar seen this tick
_PRIOR: dict = {}                              # yesterday's minute bars, fetched once a day
_ERRORS: list = []                             # data failures this tick (e.g. 401 after a key change)
_STREAM: "st.BarStore | None" = None           # set while the websocket is live; scans read from it
_DRY: list = [False]                           # this tick is a dry run (nothing may be written)


def clean_bars(df: pd.DataFrame) -> pd.DataFrame:
    """Never signal off impossible data: drop non-positive or missing prices,
    bars whose high is below their low or outside open/close, duplicate and
    out-of-order timestamps. Counts what it dropped in _TIMES["bad_bars"]."""
    if df is None or df.empty:
        return df
    px = df[["open", "high", "low", "close"]]
    ok = (px > 0).all(axis=1) & px.notna().all(axis=1) & (df["high"] >= df["low"]) \
        & (df["high"] >= px[["open", "close"]].max(axis=1)) & (df["low"] <= px[["open", "close"]].min(axis=1)) \
        & (df["volume"].fillna(0) >= 0)
    out = df[ok]
    out = out[~out.index.duplicated(keep="last")].sort_index()
    bad = len(df) - len(out)
    if bad:
        _TIMES["bad_bars"] = _TIMES.get("bad_bars", 0) + bad
    return out


def latency_line(path, date: str) -> str:
    """Median and slowest posting delay for today's signals, for the recap."""
    try:
        rows = [json.loads(x) for x in open(path)]
    except OSError:
        return ""
    ages = [r["posted_age_s"] for r in rows if r.get("kind") == "signal" and r.get("posted_age_s") is not None
            and str(r.get("posted_at", "")).startswith(date) and not r.get("expired")]
    exp = sum(1 for r in rows if r.get("kind") == "signal" and r.get("expired") and str(r.get("posted_at", "")).startswith(date))
    if not ages and not exp:
        return ""
    ages.sort()
    med = ages[len(ages) // 2] if ages else None
    return ("⏱ Signal delay: " + (f"median {med:.0f}s, slowest {ages[-1]:.0f}s" if ages else "no live signals")
            + (f" · {exp} expired" if exp else ""))


def in_session(now: pd.Timestamp) -> bool:
    return pd.Timestamp("09:25").time() <= now.time() < pd.Timestamp("16:00").time()


def seconds_to_next_poll(now: pd.Timestamp, every: int) -> float:
    """Sleep until just after the next bar boundary, not a fixed interval, so
    a closed bar is seen within seconds instead of up to `every` later."""
    period = 60 if every <= 60 else int(every)
    nxt = now.floor(f"{period}s") + pd.Timedelta(seconds=period + BAR_LAG_S)
    return max(1.0, (nxt - now).total_seconds())


def signal_age(t: dict, now: pd.Timestamp) -> float | None:
    """Seconds between the close of the bar a signal entered on and `now`."""
    try:
        hh, mm = int(t["entry_time"][:2]), int(t["entry_time"][3:5])
    except (KeyError, ValueError, TypeError):
        return None
    start = now.normalize() + pd.Timedelta(hours=hh, minutes=mm)
    return (now - (start + pd.Timedelta(minutes=BAR_MIN.get(t.get("rule"), 5)))).total_seconds()


def stale_since(now: pd.Timestamp) -> pd.Timestamp | None:
    """The newest bar's time if market data has gone stale during the session."""
    if not (pd.Timestamp("09:33").time() <= now.time() < pd.Timestamp("16:00").time()):
        return None
    last = _LAST_1M.get("ts")
    if last is None:
        return None                      # no bars at all: a failed fetch, already logged as an error
    return last if (now - last).total_seconds() > STALE_AFTER_S else None


def _minute_bars(md: MarketData, now: pd.Timestamp) -> dict[str, pd.DataFrame]:
    """Yesterday's minute bars once a day; after that only today's."""
    today = now.date()
    t0 = _time.perf_counter()
    if _STREAM is not None:                    # live stream: the day is already in memory
        _TIMES["fetch_1m"] = 0.0
        return _STREAM.minute_frames()
    if _PRIOR.get("date") != today:
        start = (now - pd.Timedelta(days=6)).date().isoformat()
        full = md.intraday_bars(WATCHLIST, 1, start=start, extended=True)
        _PRIOR.update(date=today, data={s: df[df.index.tz_convert(EASTERN).date < today]
                                        for s, df in full.items()})
        out = {k: clean_bars(v) for k, v in full.items()}
    else:
        fresh = md.intraday_bars(WATCHLIST, 1, start=today.isoformat(), extended=True)
        out = {}
        for s in set(_PRIOR["data"]) | set(fresh):
            parts = [x for x in (_PRIOR["data"].get(s), fresh.get(s)) if x is not None and len(x)]
            if not parts:
                out[s] = fresh.get(s, pd.DataFrame())
                continue
            out[s] = clean_bars(pd.concat(parts))
    _TIMES["fetch_1m"] = round(_time.perf_counter() - t0, 3)
    return out


def scan(cfg: dict) -> tuple[list[dict], str, bool]:
    md = MarketData(Credentials.from_env(), feed="iex")
    now = pd.Timestamp.now(tz=EASTERN)
    t0 = _time.perf_counter()
    # Only today's bars: everything before today is dropped below anyway.
    data = (_STREAM.five_minute_frames(now.date()) if _STREAM is not None else
            md.intraday_bars(WATCHLIST, LIVE.get("minutes", 5) or 5, start=now.date().isoformat()))
    data = {k: clean_bars(v) for k, v in data.items()}
    _TIMES["fetch_5m"] = round(_time.perf_counter() - t0, 3)
    p = {**SCAN, "minutes": 5}
    today = now.date()
    trades, last_bar = [], None
    for sym, df in data.items():
        if df.empty:
            continue
        df = df[df.index.tz_convert(EASTERN).date == today]
        # drop the bar still forming - its close has not happened
        if len(df) and now < df.index[-1].tz_convert(EASTERN) + pd.Timedelta(minutes=5):
            df = df.iloc[:-1]
        if len(df) < SCAN["base_len"] + SCAN["atr_len"] + 3:
            continue
        last_bar = max(last_bar or df.index[-1], df.index[-1])
        trades += simulate_day(prepare_sq(df, p), sym, p, cfg)
    trades.sort(key=lambda t: t["entry_time"])
    closed_for_day = now.time() >= pd.Timestamp("16:00").time()
    stamp = str(last_bar.tz_convert(EASTERN))[11:16] if last_bar is not None else "—"
    return trades, stamp, closed_for_day


LEVEL_LABEL = {"pmh": "premarket high", "pml": "premarket low",
               "pdh": "yesterday's high", "pdl": "yesterday's low",
               "pdc": "yesterday's close",
               "orh": "the opening-range high", "orl": "the opening-range low"}


def opening_scan(cfg: dict, now: pd.Timestamp) -> list[dict]:
    """The opening-drive rule, live. Same shape of trade as the retest rule.

    Prices from before the bell, so the very first minute of the session is
    tradeable. The forming bar is dropped exactly as elsewhere - a one-minute
    bar that has not closed has a close that has not happened.
    """
    if not OPENING["enabled"]:
        return []
    md = MarketData(Credentials.from_env(), feed="iex")
    data = _minute_bars(md, now)
    today = now.date()
    newest = [df.index[-1].tz_convert(EASTERN) for df in data.values() if len(df)]
    if newest:
        _LAST_1M["ts"] = max(newest)
    out = []
    for sym, df in data.items():
        if df.empty:
            continue
        if len(df) and now < df.index[-1].tz_convert(EASTERN) + pd.Timedelta(minutes=1):
            df = df.iloc[:-1]
        days = op.by_day(df)
        if len(days) < 2 or days[-1][0] != today:
            continue
        _, prior = op.split_session(days[-2][1])
        _, rth = op.split_session(days[-1][1])
        # The overnight gap, which is half of the confidence level. Both legs
        # are known before the range even forms, so nothing here reads ahead.
        gap = (conf.gap_pct(float(rth["open"].iloc[0]),
                            float(prior["close"].iloc[-1]))
               if len(rth) and len(prior) else 0.0)
        for t in op.day_trades(days[-1][1], prior, OPENING):
            rps, live = t["rps"], t["reason"] == "open"
            n = shares(t["entry"], rps, cfg["equity"], cfg["risk_pct"])
            out.append({
                "id": f"OPEN-{sym}-{t['level_name']}-{today}",
                "rule": "opening", "symbol": sym, "side": t["side"],
                "entry_time": t["entry_time"], "entry": round(t["entry"], 2),
                "stop": round(t["stop"], 2), "target": round(t["target"], 2),
                "shares": n, "risk": round(n * rps, 2),
                "observe": bool(OPENING.get("observe")),
                "level": t["level"], "level_name": t["level_name"],
                "gap": round(gap, 2),
                "with_gap": conf.with_gap(gap, t["side"]),
                "minute": conf.minute_of(t["break_time"]),
                "exit": None if live else round(t["exit"], 2),
                "exit_time": None if live else t["exit_time"],
                "reason": None if live else t["reason"],
                "pct": None if live else round(t["pct"], 2),
                "cash": None if live else round(n * rps * t["r"], 2)})
    # How many names broke the same way at the same time - the other half of
    # the confidence level, and only answerable once every symbol is in.
    conf.tag(out)
    # Both sides are computed so the forward record is complete; only the
    # posting sides reach the feed. Everything lands in the day file either
    # way, which is what the later study will read.
    posted = OPENING.get("post_sides", ("short", "long"))
    for t in out:
        t["post"] = (not OPENING.get("observe")) or t["side"] in posted
    return out


def _md() -> MarketData:
    return MarketData(Credentials.from_env(), feed="iex")


def inplay_orb_scan(cfg: dict, now: pd.Timestamp) -> list[dict]:
    """The in-play ORB rule, live (STRATEGY = "inplay_orb"). The rule lives in
    orb_live / orb_research; this only feeds the bot's freshness checks."""
    t0 = _time.perf_counter()
    out, newest = orb_live.scan(now, _md, cfg["risk_pct"], dry_run=_DRY[0])
    _TIMES["fetch_1m"] = round(_time.perf_counter() - t0, 3)
    if newest is not None:
        _LAST_1M["ts"] = newest
    return out


SETUP = {"opening": "Opening Range Breakout", "retest": "Break & Retest", "inplay": "In-play · opening range",
         "inplay_orb": orb_live.SETUP_NAME}


def card(t: dict) -> str:
    """One trade, one message. Rendered open, then rewritten closed.

    The same function draws both states so the card cannot drift between
    them, and so the prices a trade was taken on stay visible after it has
    finished - a result with no entry next to it is not reviewable.
    """
    short = t.get("side", "short") == "short"
    side = f"{'SHORT' if short else 'LONG'} {t['symbol']}"
    tp = (f"`TP    {t['target']:>9,.2f}`" if t.get("target")
          else "`TP         none`  held until the stop or 15:55")
    levels = (f"`Entry {t['entry']:>9,.2f}`\n"
              f"`SL    {t['stop']:>9,.2f}`\n"
              f"{tp}")
    setup = t.get("setup") or SETUP.get(t.get("rule"), t.get("rule", ""))

    # Colour carries the direction while a trade is open and the RESULT once
    # it closes, because those are the two things worth seeing at a glance.
    # The stop and target sit in a code block so the numbers line up in a
    # column instead of wrapping into the prose.
    #
    # No share count. Position size is a property of one account, and a card
    # that prints it reads like an instruction to buy that many.
    if t.get("exit") is None:
        why = conf.note(t)
        age = t.get("age_s")
        if t.get("expired"):
            late = f"{age / 60:.0f} min" if age and age >= 90 else f"{age:.0f}s" if age else "too"
            head = f"⚪ **EXPIRED · {side}**  ·  {t['entry_time']} ET  ·  seen {late} late, do not chase\n"
        else:
            # Words, not just colour: a reader scrolling back must see at once
            # whether a card is a live entry or a finished trade (5 Oct 2026).
            head = (f"{'🔴' if short else '🟢'} **NEW SIGNAL · {side}**  ·  {t['entry_time']} ET"
                    + (f"  ·  ⏱ {age:.0f}s" if age is not None else "") + "\n")
        if t.get("rule") == "inplay_orb":
            # Signal time = the close of the breakout bar; age = how long ago that was.
            hh, mm = int(t["entry_time"][:2]), int(t["entry_time"][3:5]) + 1
            closed = f"{hh + mm // 60:02d}:{mm % 60:02d}"
            rr = abs(t["target"] - t["entry"]) / max(abs(t["entry"] - t["stop"]), 1e-9)
            return (head + f"{levels}\n"
                    + f"R:R 1:{rr:.1f} · risk {t.get('risk_pct_price', 0):.2f}% of price · signal {closed}:00 ET\n"
                    + f"{orb_live.features_line(t)}\n"
                    + f"_{setup} · out by 15:55_")
        return (head + f"{levels}\n"
                + (f"{why}\n" if why else "")
                + f"_{setup}_")

    won = (t["pct"] or 0) > 0
    why = {"target": "hit target", "stop": "hit stop",
           "bell": "closed at the bell",
           "time": "closed on the hold limit"}.get(t["reason"], t["reason"])
    # The level it was given stays on the closed card too. A confidence
    # scheme nobody can audit after the fact is decoration.
    lv = conf.level(t)
    badge = f"{conf.LABEL[lv]} · " if lv else ""
    return (f"{'✅' if won else '❌'} **CLOSED · {'WIN' if won else 'LOSS'} · {side}**  ·  "
            f"{t['entry_time']} → {t['exit_time']}\n"
            f"{levels}\n"
            f"`Exit  {t['exit']:>9,.2f}`  {why}\n"
            f"**{t['pct']:+.2f}%** · {badge}_{setup}_")


def entry_msg(t: dict) -> str:
    return card({**t, "exit": None})


def close_msg(t: dict) -> str:
    return card(t)


def cluster_note(trades: list[dict]) -> str:
    """Warn when most of the day's entries are really one market move.

    Counts entries by side inside a rolling window. Twelve shorts in ten
    minutes is the open selling off, not twelve findings, and a win rate
    computed across them is one coin flip reported as twelve.
    """
    out = []
    for side in ("short", "long"):
        times = sorted(int(t["entry_time"][:2]) * 60 + int(t["entry_time"][3:5])
                       for t in trades if t.get("side") == side
                       and t.get("entry_time"))
        best, n = 0, len(times)
        for i, a in enumerate(times):
            k = sum(1 for b in times[i:] if b - a <= CLUSTER_MINUTES)
            best = max(best, k)
        if best >= CLUSTER_WARN:
            out.append(f"{best} {side}s within {CLUSTER_MINUTES} min"
                       + (f" (of {n})" if n != best else ""))
    if not out:
        return ""
    return ("\n⚠️ _" + "; ".join(out) +
            " — that is one market move read several times, not several "
            "independent trades. Count it as roughly one result._")


def block(done: list[dict], head: str, mark: tuple[str, str],
          cash: float | None = None) -> list[str]:
    won = sum(1 for t in done if (t["pct"] or 0) > 0)
    pct = sum(t["pct"] or 0 for t in done)
    total = f"**{pct:+.2f}%**"
    lines = ([head] if head else []) + [
             f"**{len(done)} trade{'s' if len(done) != 1 else ''} · "
             f"{won} won, {len(done) - won} lost · "
             f"{100 * won / len(done):.0f}% win rate**",
             total]
    for t in done:
        lines.append(f"{mark[0] if (t['pct'] or 0) > 0 else mark[1]} "
                     f"{t['symbol']} {t['entry_time']}→{t['exit_time']}  "
                     f"{t['pct']:+.2f}%")
    return lines + [""]


def summary_msg(trades: list[dict], date: str) -> str:
    """The day, with the traded rule and the watched rule kept apart.

    Mixing them would put an unvalidated rule's results into the account's
    running total, which is exactly how a number stops meaning anything.
    """
    done = [t for t in trades if t["exit"] is not None]
    if not done:
        return (f"📊 **{date}** — no trades today.\n"
                "_Quiet days are normal for this setup._")
    lines = [f"📊 **{date}**", ""]
    lines += block(done, "", ("✅", "❌"))
    note = cluster_note(done)
    if note:
        lines.append(note)
    lines.append("_Paper account: each signal bought as a weekly option, one "
                 "strike out of the money._" if autotrade.ENABLED
                 else "_Paper only. No orders were placed._")
    return "\n".join(lines)


# Its own filename: src/paper.py --live already owns state/live_seen.json with
# a different shape, and sharing it meant today's file loaded and then failed
# on a missing key. Every field is also defaulted, so a file written by an
# older version of this bot degrades to "announce it again" rather than
# crashing the run.
SEEN_FILE = "live_bot_seen.json"


def load_seen(date: str) -> dict:
    # `cards` maps a trade id to the Discord message posted for it, so the
    # close can rewrite that message instead of posting a second one. A file
    # written before this existed simply has no cards, and every close in it
    # falls back to its own message.
    blank = {"date": date, "entries": [], "exits": [], "summary": False, "strategy": "",
             "cards": {}, "expired": [], "stale_warned": "", "error_warned": ""}
    f = STATE / SEEN_FILE
    if not f.exists():
        return blank
    try:
        s = json.loads(f.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Could not read %s (%s) - starting the day fresh",
                    SEEN_FILE, exc)
        return blank
    if s.get("date") != date:
        return blank
    return {**blank, **{k: s.get(k, blank[k]) for k in blank}}


def all_trades(cfg: dict, now: pd.Timestamp) -> tuple[list[dict], str, bool]:
    """Both rules, merged and ordered by entry time.

    Either rule failing is logged and survived. A broken opening scan must
    not take the retest rule off the air, and the reverse.
    """
    trades, stamp, day_done = [], "—", False
    # Before 09:45 the retest rule cannot fire by its own definition, so
    # fetching five-minute bars for it every forty-five seconds is pure waste.
    if RETEST_ENABLED and now.time() >= pd.Timestamp(OPEN_T).time():
        try:
            trades, stamp, day_done = scan(cfg)
        except AlpacaError as exc:
            _ERRORS.append(str(exc)[:60])
            log.error("Retest scan failed: %s", exc)
        except Exception as exc:                               # noqa: BLE001
            log.exception("Retest scan blew up: %s", exc)
    try:
        trades += inplay_orb_scan(cfg, now) if STRATEGY in ORB_STRATEGIES else opening_scan(cfg, now)
    except AlpacaError as exc:
        _ERRORS.append(str(exc)[:60])
        log.error("Opening scan failed: %s", exc)
    except Exception as exc:                                   # noqa: BLE001
        log.exception("Opening scan blew up: %s", exc)
    trades.sort(key=lambda t: (t["entry_time"], t["symbol"]))
    if now.time() >= pd.Timestamp("16:00").time():
        day_done = True
    return trades, stamp, day_done


def tick(cfg: dict, dry_run: bool) -> int:
    """One pass: recompute the day, announce whatever is new. Returns the
    number of messages sent."""
    t0 = _time.perf_counter()
    now = pd.Timestamp.now(tz=EASTERN)
    _TIMES.clear()
    _LAST_1M.clear()
    _ERRORS.clear()
    _DRY[0] = dry_run
    trades, stamp, day_done = all_trades(cfg, now)
    _TIMES["scan"] = round(_time.perf_counter() - t0, 3)
    detected = pd.Timestamp.now(tz=EASTERN)

    date = str(now.date())
    seen = load_seen(date)
    seen["strategy"] = seen.get("strategy") or STRATEGY      # the rule that started the day finishes it
    stale = stale_since(detected)
    # (text, trade id, is_close) — held until after the dry-run check so a
    # dry run never touches Discord and never records anything as announced.
    outbox: list[tuple[str, str, bool]] = []
    for t in trades:
        if t["id"] in seen["expired"]:
            t["expired"] = True            # the auto-trader must not chase it either
        if not t.get("post", True):
            continue
        if t["id"] not in seen["entries"]:
            if stale is not None:
                continue                   # never announce on stale data
            t["age_s"] = signal_age(t, detected)
            if t["age_s"] is not None and t["age_s"] > MAX_AGE_S.get(t.get("rule"), 360):
                t["expired"] = True
                seen["expired"].append(t["id"])
            outbox.append((card({**t, "exit": None}), t["id"], False))
        if t["exit"] is not None and t["id"] not in seen["exits"]:
            outbox.append((card(t), t["id"], True))
    if stale is not None:
        last_warn = seen.get("stale_warned") or ""
        if not last_warn or (detected - pd.Timestamp(last_warn)).total_seconds() > 1800:
            outbox.append((f"⚠️ **DATA WARNING** · newest market data {stale.strftime('%H:%M')} ET · "
                           f"new signals suppressed until data is fresh", "", False))
            seen["stale_warned"] = str(detected)
        log.warning("Stale data: newest bar %s", stale)
    if _ERRORS and in_session(detected):
        last_err = seen.get("error_warned") or ""
        if not last_err or (detected - pd.Timestamp(last_err)).total_seconds() > 1800:
            auth = any("401" in e or "403" in e for e in _ERRORS)
            outbox.append((f"⚠️ **DATA ERROR** · market data request failed"
                           + (" (unauthorized: the Alpaca key was rejected, check the repo secrets)" if auth else "")
                           + " · no signals until it recovers", "", False))
            seen["error_warned"] = str(detected)
    if day_done and not seen["summary"]:
        lat = latency_line(STATE / LATENCY_FILE, date)
        outbox.append((summary_msg(trades, now.strftime("%A %d %B")) + (f"\n{lat}" if lat else ""), "", False))
        seen["summary"] = True

    log.info("%s ET · bars through %s · %d trade(s) today · %d new message(s)",
             now.strftime("%H:%M:%S"), stamp, len(trades), len(outbox))
    for text, _, _ in outbox:
        print("\n" + text)
    if dry_run:
        _TIMES["total"] = round(_time.perf_counter() - t0, 3)
        return len(outbox)

    hook = Credentials.from_env().discord_webhook
    t_send = _time.perf_counter()
    lat_rows = []
    by_id = {t["id"]: t for t in trades}
    for text, tid, is_close in outbox:
        if is_close:
            # Edit the card this trade already has. A missing or un-editable
            # message means posting the result on its own - an extra message
            # is a nuisance, a silently dropped result is not.
            mid = seen["cards"].get(tid)
            if not (mid and dm.edit(hook, mid, text)):
                dm.post(hook, text)
            seen["exits"].append(tid)
        else:
            mid = dm.post(hook, text)
            if not tid:                     # the daily recap, not a trade
                continue
            t = by_id.get(tid, {})
            posted = pd.Timestamp.now(tz=EASTERN)
            lat_rows.append({"id": tid, "rule": t.get("rule"), "entry_bar": t.get("entry_time"),
                             "detected_age_s": t.get("age_s"),
                             "posted_age_s": signal_age(t, posted) if t else None,
                             "expired": bool(t.get("expired")), "posted_at": str(posted)})
            if mid:
                seen["cards"][tid] = mid
            seen["entries"].append(tid)

    _TIMES["discord"] = round(_time.perf_counter() - t_send, 3)

    # The paper account follows the feed. It runs every tick, not only when
    # there is news, because the pre-bell sell has no message of its own. A
    # failure here is logged and survived: the signals matter more.
    try:
        p = autotrade.client() if autotrade.ENABLED else None
        for line in (autotrade.run(trades, now, p) if p else []):
            log.info("paper: %s", line)
    except Exception as exc:                                   # noqa: BLE001
        log.exception("Paper trading failed: %s", exc)

    STATE.mkdir(exist_ok=True); REPORTS.mkdir(exist_ok=True)
    _TIMES["total"] = round(_time.perf_counter() - t0, 3)
    log.info("timings %s", _TIMES)
    # Latency audit trail: one line per signal posted, plus one per tick.
    with open(STATE / LATENCY_FILE, "a") as f:
        for r in lat_rows:
            f.write(json.dumps({"kind": "signal", **r}) + "\n")
        f.write(json.dumps({"kind": "tick", "at": str(detected), "newest_bar": str(_LAST_1M.get("ts")),
                            "stale": stale is not None, "new_messages": len(outbox), **_TIMES}) + "\n")
    # Only touch the record when this run actually announced something.
    # A run that did nothing must leave the file completely alone, mtime
    # included: on 30 September a run that exited with "nothing to do"
    # rewrote it from its own stale checkout, wiping ten message ids, and the
    # next run could not find the cards so it posted all ten trades again.
    if outbox:
        (STATE / SEEN_FILE).write_text(json.dumps(seen, indent=2))
    (REPORTS / "live_today.md").write_text(
        summary_msg(trades, date) + "\n\n" +
        "\n\n".join(card(t) for t in trades))
    return len(outbox)


def stream_loop(cfg: dict, dry_run: bool, stop, deadline, first, every: int) -> int:
    """Event-driven session: tick the moment a minute's bars arrive.

    The day is seeded from REST once, then extended bar by bar from the
    websocket. While the stream is down the bot polls exactly as before, and
    on reconnect it re-seeds from REST so the gap is filled before scanning.
    """
    global _STREAM
    creds = Credentials.from_env()
    trigger = st.MinuteTrigger(WATCHLIST)
    ws, retry_at, last_bar_at = None, 0.0, st.now_s()
    while True:
        now = pd.Timestamp.now(tz=EASTERN)
        if now.time() > stop or (deadline is not None and now >= deadline):
            log.info("Stream session over at %s ET.", now.strftime("%H:%M:%S"))
            if ws is not None:
                ws.close()
            _STREAM = None
            return 0
        if ws is None and st.now_s() >= retry_at:
            try:
                _STREAM = None
                _PRIOR.clear()
                seed = _minute_bars(MarketData(creds, feed="iex"), now)
                ws = st.connect(creds.alpaca_key, creds.alpaca_secret, list(WATCHLIST))
                _STREAM = st.BarStore(seed)
                last_bar_at = st.now_s()
            except Exception as exc:                           # noqa: BLE001
                log.error("Stream unavailable (%s) - polling until it is back", exc)
                ws, retry_at = None, st.now_s() + 60
        if ws is None:                                         # fallback: the old polling tick
            if now.time() >= pd.Timestamp(first).time():
                try:
                    tick(cfg, dry_run)
                except Exception as exc:                       # noqa: BLE001
                    log.exception("Tick failed, continuing: %s", exc)
            _time.sleep(seconds_to_next_poll(pd.Timestamp.now(tz=EASTERN), every))
            continue
        try:
            for m in st.read(ws):
                trigger.arrive(m["S"], _STREAM.add(m), st.now_s())
                last_bar_at = st.now_s()
        except ConnectionError as exc:
            log.error("%s - reconnecting", exc)
            ws, _STREAM = None, None
            continue
        if trigger.due(st.now_s()):
            trigger.fired()
            if now.time() >= pd.Timestamp(first).time():
                try:
                    tick(cfg, dry_run)
                except Exception as exc:                       # noqa: BLE001
                    log.exception("Tick failed, continuing: %s", exc)
        # A silent socket in the session means a dead connection, not a quiet market.
        if (pd.Timestamp("09:31").time() <= now.time() < pd.Timestamp("16:00").time()
                and st.now_s() - last_bar_at > 150):
            log.error("No bars for 150 s - polling for 5 min, then retrying the stream")
            ws.close()
            ws, _STREAM, retry_at = None, None, st.now_s() + 300


def bench(cfg: dict, n: int) -> int:
    """Stage timings over n dry-run ticks: the first is a cold start (fetches
    yesterday too), the rest are warm. Nothing is posted or traded."""
    rows = []
    for _ in range(n):
        tick(cfg, dry_run=True)
        rows.append(dict(_TIMES))
    df = pd.DataFrame(rows)
    lines = ["# Live bot latency benchmark", "", f"{n} dry-run ticks · {pd.Timestamp.now(tz=EASTERN):%Y-%m-%d %H:%M} ET", "",
             "| stage | cold start s | warm median s | warm p95 s | warm max s |", "|---|---|---|---|---|"]
    warm = df.iloc[1:] if len(df) > 1 else df
    for c in df.columns:
        lines.append(f"| {c} | {df[c].iloc[0]:.2f} | {warm[c].median():.2f} | {warm[c].quantile(.95):.2f} | {warm[c].max():.2f} |")
    out = "\n".join(lines)
    print(out)
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "latency.md").write_text(out + "\n")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="ignore the market-hours check")
    ap.add_argument("--until", default="",
                    help="poll until this Eastern time, e.g. 10:05")
    ap.add_argument("--every", type=int, default=45,
                    help="seconds between polls when --until is set")
    ap.add_argument("--for", dest="minutes", type=int, default=0,
                    help="stop polling after this many minutes, even before "
                         "--until; GitHub kills a job at six hours")
    ap.add_argument("--stream", action="store_true",
                    help="react to live minute bars over the websocket (falls back to polling)")
    ap.add_argument("--bench", type=int, default=0,
                    help="run N dry-run ticks back to back and report stage timings")
    args = ap.parse_args(argv)
    if args.bench:
        return bench(settings(), args.bench)

    now = pd.Timestamp.now(tz=EASTERN)
    first = BELL if OPENING["enabled"] else OPEN_T
    if not args.force:
        if now.weekday() > 4:
            log.info("Weekend — nothing to do."); return 0
        end = args.until or "16:10"
        if now.time() > pd.Timestamp(end).time():
            log.info("Past %s ET — nothing to do.", end); return 0
        if not args.until and now.time() < pd.Timestamp(first).time():
            log.info("Before %s ET — nothing to do.", first); return 0

    cfg = settings()
    # A day is finished on the rule it started with, even if the switch was
    # changed mid-session (5 Oct 2026): otherwise a late job would close the
    # morning's cards with a different rule's trades.
    global STRATEGY
    recorded = load_seen(str(now.date())).get("strategy")
    if recorded in STRATEGIES and recorded != STRATEGY:
        log.info("Today started on %s; finishing it on that rule (switch says %s)", recorded, STRATEGY)
        STRATEGY = recorded
    if STRATEGY in ORB_STRATEGIES:
        orb_live.use(STRATEGY)
    log.info("Day-trade strategy: %s", STRATEGY)
    if STRATEGY in ORB_STRATEGIES:
        try:                       # the history, before the bell, so 09:35 is one request
            orb_live.warm(now, _md)
        except Exception as exc:                               # noqa: BLE001
            log.error("In-play warm-up failed (%s) - will retry on the first scan", exc)
    if not args.until:
        return 0 if tick(cfg, args.dry_run) >= 0 else 1

    # Polling mode. Cron only has to be roughly on time once; this job then
    # covers the open at its own cadence. Sleeping past the bell rather than
    # scanning before it keeps the log honest about what it has seen.
    stop = pd.Timestamp(args.until).time()
    deadline = (pd.Timestamp.now(tz=EASTERN) + pd.Timedelta(minutes=args.minutes)
                if args.minutes else None)
    log.info("Polling every %ds until %s ET%s", args.every, args.until,
             f" or for {args.minutes} min" if deadline is not None else "")
    if args.stream:
        return stream_loop(cfg, args.dry_run, stop, deadline, first, args.every)
    while True:
        now = pd.Timestamp.now(tz=EASTERN)
        if now.time() > stop:
            log.info("Reached %s ET — done.", args.until)
            return 0
        if deadline is not None and now >= deadline:
            # The next scheduled run is already queued behind this one and
            # starts the moment this job commits and exits.
            log.info("Polled for %d min — handing over to the next run.",
                     args.minutes)
            return 0
        if now.time() >= pd.Timestamp(first).time():
            try:
                tick(cfg, args.dry_run)
            except Exception as exc:                           # noqa: BLE001
                log.exception("Tick failed, continuing: %s", exc)
        else:
            log.info("%s ET — waiting for %s", now.strftime("%H:%M:%S"), first)
        _time.sleep(seconds_to_next_poll(pd.Timestamp.now(tz=EASTERN), args.every))


if __name__ == "__main__":
    raise SystemExit(main())
