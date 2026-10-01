"""The live bot. Two rules, one watchlist, one Discord feed.

  * OPENING DRIVE, 09:30-10:00, one-minute bars. Breaks of prices that
    already existed before the bell - yesterday's high, low and close, and
    the premarket high and low. No warmup, no pullback required. This is the
    rule that exists because the bot sat out AMD's 2.5% opening drop on
    28 September.
  * BREAK AND RETEST, 09:45-15:30, five-minute bars. The original rule,
    unchanged.

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
import sys
import time as _time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from . import autotrade
from . import confidence as conf
from . import discord_msg as dm
from . import opening as op
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
CLUSTER_MINUTES = 15
CLUSTER_WARN = 4


def simulate_day(day: pd.DataFrame, sym: str, p: dict, cfg: dict) -> list[dict]:
    """Every trade the rule would have taken today, with how each ended.

    A trade with no exit yet is returned open, which is what makes the close
    alert possible: the next run finds it finished and announces it.
    """
    out = []
    for i, side, level in breaks_in(day, p):
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


def scan(cfg: dict) -> tuple[list[dict], str, bool]:
    md = MarketData(Credentials.from_env(), feed="iex")
    now = pd.Timestamp.now(tz=EASTERN)
    start = (now - pd.Timedelta(days=5)).date().isoformat()
    data = md.intraday_bars(WATCHLIST, LIVE.get("minutes", 5) or 5, start=start)
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
    start = (now - pd.Timedelta(days=6)).date().isoformat()
    data = md.intraday_bars(WATCHLIST, 1, start=start, extended=True)
    today = now.date()
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


SETUP = {"opening": "opening range", "retest": "break & retest"}


def card(t: dict) -> str:
    """One trade, one message. Rendered open, then rewritten closed.

    The same function draws both states so the card cannot drift between
    them, and so the prices a trade was taken on stay visible after it has
    finished - a result with no entry next to it is not reviewable.
    """
    short = t.get("side", "short") == "short"
    side = f"{'SHORT' if short else 'LONG'} {t['symbol']}"
    levels = (f"`Entry {t['entry']:>9,.2f}`\n"
              f"`SL    {t['stop']:>9,.2f}`\n"
              f"`TP    {t['target']:>9,.2f}`")
    setup = SETUP.get(t.get("rule"), t.get("rule", ""))

    # Colour carries the direction while a trade is open and the RESULT once
    # it closes, because those are the two things worth seeing at a glance.
    # The stop and target sit in a code block so the numbers line up in a
    # column instead of wrapping into the prose.
    #
    # No share count. Position size is a property of one account, and a card
    # that prints it reads like an instruction to buy that many.
    if t.get("exit") is None:
        why = conf.note(t)
        return (f"{'🔴' if short else '🟢'} **{side}**  ·  {t['entry_time']} ET\n"
                f"{levels}\n"
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
    return (f"{'✅' if won else '❌'} **{side}**  ·  "
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
    blank = {"date": date, "entries": [], "exits": [], "summary": False,
             "cards": {}}
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
    if now.time() >= pd.Timestamp(OPEN_T).time():
        try:
            trades, stamp, day_done = scan(cfg)
        except AlpacaError as exc:
            log.error("Retest scan failed: %s", exc)
        except Exception as exc:                               # noqa: BLE001
            log.exception("Retest scan blew up: %s", exc)
    try:
        trades += opening_scan(cfg, now)
    except AlpacaError as exc:
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
    now = pd.Timestamp.now(tz=EASTERN)
    trades, stamp, day_done = all_trades(cfg, now)

    date = str(now.date())
    seen = load_seen(date)
    # (text, trade id, is_close) — held until after the dry-run check so a
    # dry run never touches Discord and never records anything as announced.
    outbox: list[tuple[str, str, bool]] = []
    for t in trades:
        if not t.get("post", True):
            continue
        if t["id"] not in seen["entries"]:
            outbox.append((card({**t, "exit": None}), t["id"], False))
        if t["exit"] is not None and t["id"] not in seen["exits"]:
            outbox.append((card(t), t["id"], True))
    if day_done and not seen["summary"]:
        outbox.append((summary_msg(trades, now.strftime("%A %d %B")), "", False))
        seen["summary"] = True

    log.info("%s ET · bars through %s · %d trade(s) today · %d new message(s)",
             now.strftime("%H:%M:%S"), stamp, len(trades), len(outbox))
    for text, _, _ in outbox:
        print("\n" + text)
    if dry_run:
        return len(outbox)

    hook = Credentials.from_env().discord_webhook
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
            if mid:
                seen["cards"][tid] = mid
            seen["entries"].append(tid)

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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="ignore the market-hours check")
    ap.add_argument("--until", default="",
                    help="poll until this Eastern time, e.g. 10:05")
    ap.add_argument("--every", type=int, default=45,
                    help="seconds between polls when --until is set")
    args = ap.parse_args(argv)

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
    if not args.until:
        return 0 if tick(cfg, args.dry_run) >= 0 else 1

    # Polling mode. Cron only has to be roughly on time once; this job then
    # covers the open at its own cadence. Sleeping past the bell rather than
    # scanning before it keeps the log honest about what it has seen.
    stop = pd.Timestamp(args.until).time()
    log.info("Polling every %ds until %s ET", args.every, args.until)
    while True:
        now = pd.Timestamp.now(tz=EASTERN)
        if now.time() > stop:
            log.info("Reached %s ET — done.", args.until)
            return 0
        if now.time() >= pd.Timestamp(first).time():
            try:
                tick(cfg, args.dry_run)
            except Exception as exc:                           # noqa: BLE001
                log.exception("Tick failed, continuing: %s", exc)
        else:
            log.info("%s ET — waiting for %s", now.strftime("%H:%M:%S"), first)
        _time.sleep(max(5, args.every))


if __name__ == "__main__":
    raise SystemExit(main())
