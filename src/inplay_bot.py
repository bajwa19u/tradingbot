"""Stocks in play — the second channel.

A different question from the main feed. That one asks "is this a good
break?" on a fixed list of ten megacaps. This one asks "what is worth
watching at all this morning?" and only then looks for a break.

The universe is wide. At 09:35 every name is ranked by relative volume -
today's first five minutes against its own average first five minutes over
the prior fourteen sessions - and only the handful with the most abnormal
opening interest are traded. That ratio is knowable at 09:35 and the trade
is taken after it, so nothing here reads the future.

Why this and not another dial on the existing rule
--------------------------------------------------
Zarattini, Barbon and Aziz ran a five-minute opening-range breakout across
7,000+ US equities. Applied broadly it returned 29% against 198% for simply
holding the index. Restricted to the twenty names with the most abnormal
opening volume it returned 1,637%, and the paper says plainly that most of
the edge came from the SELECTION rather than from the breakout rule.

Our own version of that test, on our data and our costs: trading everything
lost 748%, trading the top five made 66% and held up on dates it had never
seen. That gap is the largest single effect measured anywhere in this
project, and it is the reason this gets its own channel rather than another
parameter in the old one.

What it has NOT shown
---------------------
The version that survived stops at five percent of the 14-day ATR, which on
a $600 stock is about seventy-five cents, and it stops making money once
slippage reaches 0.10% each way - roughly sixty cents round trip. The margin
is the whole result. So this runs to build a forward record on a genuinely
different idea, not because it is proven; the settings below use the wider,
duller stop deliberately, because a rule whose edge lives inside the spread
is not a rule.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time as _time
from zoneinfo import ZoneInfo

import pandas as pd

from . import discord_msg as dm
from . import inplay as ip
from . import opening as op
from .config import REPO_ROOT, Credentials
from .data import AlpacaError, MarketData
from .forensics import UNIVERSES
from .live_bot import SETUP, card, summary_msg
from .paper import settings, shares

EASTERN = ZoneInfo("America/New_York")
REPORTS = REPO_ROOT / "reports"
STATE = REPO_ROOT / "state"
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("inplay_bot")

SEEN_FILE = "inplay_bot_seen.json"
UNIVERSE = "wide"
TOP_N = 5
BELL, LAST = "09:30", "15:58"

# The wide stop on purpose. The tight one measured better and dies the moment
# real execution costs show up, which is the trap the source paper warns
# about for its own tightest variant.
RULE = {**ip.BASE, "select_top": TOP_N, "atr_frac": 0.20, "exit_mode": "close",
        "side": "both", "max_per_symbol": 1, "or_minutes": 5, "risk_pct": 1.0}


def scan(cfg: dict, now: pd.Timestamp) -> tuple[list[dict], list[tuple], str]:
    """Today's trades on today's most-in-play names.

    Returns (trades, the ranking, a timestamp) so the ranking can be shown
    once in the morning - what got picked is as interesting as what it did.
    """
    md = MarketData(Credentials.from_env(), feed="iex")
    symbols = UNIVERSES.get(UNIVERSE) or UNIVERSES["wide"]
    start = (now - pd.Timedelta(days=40)).date().isoformat()
    data = md.intraday_bars(symbols, 1, start=start, extended=True)

    today = now.date()
    fresh = {}
    for sym, df in data.items():
        if df.empty:
            continue
        # drop the bar still forming - its close has not happened yet
        if now < df.index[-1].tz_convert(EASTERN) + pd.Timedelta(minutes=1):
            df = df.iloc[:-1]
        if len(df):
            fresh[sym] = df
    dailies = ip.build(fresh)
    if not dailies:
        return [], [], "—"

    picks = ip.in_play(dailies, today, TOP_N)
    per_day = {s: dict(op.by_day(df)) for s, df in fresh.items()}
    out = []
    for sym, rvol in picks:
        day = per_day.get(sym, {}).get(today)
        if day is None:
            continue
        _, rth = op.split_session(day)
        if len(rth) < RULE["or_minutes"] + 5:
            continue
        d = dailies[sym]
        atr = ip.atr14(d, d.index.get_loc(today))
        for t in ip.trade_day(rth, atr, RULE):
            live = t["reason"] == "open"
            rps = t["rps"]
            n = shares(t["entry"], rps, cfg["equity"], cfg["risk_pct"])
            out.append({
                "id": f"IP-{sym}-{t['level_name']}-{today}",
                "rule": "inplay", "symbol": sym, "side": t["side"],
                "entry_time": t["entry_time"], "entry": round(t["entry"], 2),
                "stop": round(t["stop"], 2),
                "target": round(t.get("target") or 0.0, 2),
                "shares": n, "risk": round(n * rps, 2), "rvol": round(rvol, 1),
                "level": t["level"], "level_name": t["level_name"],
                "exit": None if live else round(t["exit"], 2),
                "exit_time": None if live else t["exit_time"],
                "reason": None if live else t["reason"],
                "pct": None if live else round(t["pct"], 2),
                "post": True})
    out.sort(key=lambda t: (t["entry_time"], t["symbol"]))
    stamp = max((df.index[-1] for df in fresh.values()), default=None)
    return out, picks, (str(stamp.tz_convert(EASTERN))[11:16] if stamp is not None
                        else "—")


def picks_msg(picks: list[tuple], date: str) -> str:
    if not picks:
        return f"📡 **{date}** — nothing unusual at the open."
    rows = "\n".join(f"`{s:<6}{r:>6.1f}x`" for s, r in picks)
    return (f"📡 **In play · {date}**\n{rows}\n"
            f"_ranked by opening volume against their own normal_")


def load_seen(date: str) -> dict:
    blank = {"date": date, "entries": [], "exits": [], "summary": False,
             "picks": False, "cards": {}}
    f = STATE / SEEN_FILE
    if not f.exists():
        return blank
    try:
        s = json.loads(f.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Could not read %s (%s) — starting fresh", SEEN_FILE, exc)
        return blank
    if s.get("date") != date:
        return blank
    return {**blank, **{k: s.get(k, blank[k]) for k in blank}}


def tick(cfg: dict, dry_run: bool) -> int:
    now = pd.Timestamp.now(tz=EASTERN)
    try:
        trades, picks, stamp = scan(cfg, now)
    except AlpacaError as exc:
        log.error("Fetch failed: %s", exc); return 0
    except Exception as exc:                                   # noqa: BLE001
        log.exception("Scan blew up: %s", exc); return 0

    date = str(now.date())
    seen = load_seen(date)
    outbox: list[tuple[str, str, bool]] = []

    if picks and not seen["picks"]:
        outbox.append((picks_msg(picks, now.strftime("%A %d %B")), "", False))
        seen["picks"] = True
    for t in trades:
        if t["id"] not in seen["entries"]:
            outbox.append((card({**t, "exit": None}), t["id"], False))
        if t["exit"] is not None and t["id"] not in seen["exits"]:
            outbox.append((card(t), t["id"], True))
    if now.time() >= pd.Timestamp("16:00").time() and not seen["summary"]:
        outbox.append((summary_msg(trades, now.strftime("%A %d %B")), "", False))
        seen["summary"] = True

    log.info("%s ET · bars through %s · %d in play · %d trade(s) · %d new",
             now.strftime("%H:%M:%S"), stamp, len(picks), len(trades),
             len(outbox))
    for text, _, _ in outbox:
        print("\n" + text)
    if dry_run:
        return len(outbox)

    hook = Credentials.from_env().discord_webhook_inplay
    if not hook:
        log.error("DISCORD_WEBHOOK_INPLAY is not set — nothing sent")
        return 0
    for text, tid, is_close in outbox:
        if is_close:
            mid = seen["cards"].get(tid)
            if not (mid and dm.edit(hook, mid, text)):
                dm.post(hook, text)
            seen["exits"].append(tid)
        else:
            mid = dm.post(hook, text)
            if not tid:
                continue
            if mid:
                seen["cards"][tid] = mid
            seen["entries"].append(tid)

    if outbox:
        STATE.mkdir(exist_ok=True); REPORTS.mkdir(exist_ok=True)
        (STATE / SEEN_FILE).write_text(json.dumps(seen, indent=2))
        (REPORTS / "inplay_today.md").write_text(
            summary_msg(trades, date) + "\n\n"
            + "\n\n".join(card(t) for t in trades))
    return len(outbox)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--until", default="", help="poll until this Eastern time")
    ap.add_argument("--every", type=int, default=60)
    args = ap.parse_args(argv)

    now = pd.Timestamp.now(tz=EASTERN)
    if not args.force:
        if now.weekday() > 4:
            log.info("Weekend — nothing to do."); return 0
        end = args.until or LAST
        if now.time() > pd.Timestamp(end).time():
            log.info("Past %s ET — nothing to do.", end); return 0

    cfg = settings()
    if not args.until:
        tick(cfg, args.dry_run)
        return 0

    stop = pd.Timestamp(args.until).time()
    log.info("Polling every %ds until %s ET", args.every, args.until)
    while True:
        now = pd.Timestamp.now(tz=EASTERN)
        if now.time() > stop:
            log.info("Reached %s ET — done.", args.until); return 0
        if now.time() >= pd.Timestamp(BELL).time():
            try:
                tick(cfg, args.dry_run)
            except Exception as exc:                           # noqa: BLE001
                log.exception("Tick failed, continuing: %s", exc)
        else:
            log.info("%s ET — waiting for %s", now.strftime("%H:%M:%S"), BELL)
        _time.sleep(max(5, args.every))


if __name__ == "__main__":
    raise SystemExit(main())
