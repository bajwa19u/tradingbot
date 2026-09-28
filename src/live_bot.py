"""The live bot. Break and retest, shorts only, on the core watchlist.

Runs every five minutes through the session. Posts an entry the moment the
rule fires, a close when the trade ends, and one summary at the bell.

Two design choices that matter:

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
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from .config import REPO_ROOT, Credentials
from .data import AlpacaError, MarketData
from .forensics import CORE
from .paper import notify, settings, shares
from .retest import LIVE, SCAN, STOP_ATR, TARGET_R, breaks_in, find_retest
from .squeeze import prepare_sq

EASTERN = ZoneInfo("America/New_York")
REPORTS = REPO_ROOT / "reports"
STATE = REPO_ROOT / "state"
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("live_bot")

OPEN_T, CLOSE_T = "09:45", "15:55"


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
        t = {"id": f"{sym}-{str(day.index[j])[:16]}", "symbol": sym,
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
    data = md.intraday_bars(CORE, LIVE.get("minutes", 5) or 5, start=start)
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


def entry_msg(t: dict) -> str:
    size = (f"{t['shares']} share{'s' if t['shares'] != 1 else ''}"
            if t["shares"] else "**0 — too small for the account**")
    return (f"🔻 **SHORT {t['symbol']}**  ·  {t['entry_time']} ET\n"
            f"Entry `${t['entry']:,.2f}`\n"
            f"🛑 SL `${t['stop']:,.2f}`\n"
            f"🎯 TP `${t['target']:,.2f}`\n"
            f"{size} · risking `${t['risk']:,.2f}`")


def close_msg(t: dict) -> str:
    won = (t["pct"] or 0) > 0
    why = {"target": "hit target", "stop": "hit stop",
           "bell": "closed at the bell"}.get(t["reason"], t["reason"])
    return (f"{'✅' if won else '❌'} **CLOSED {t['symbol']}**  ·  "
            f"{t['exit_time']} ET\n"
            f"Exit `${t['exit']:,.2f}` — {why}\n"
            f"**{t['pct']:+.2f}%**  (${t.get('cash', 0):+,.2f})")


def summary_msg(trades: list[dict], date: str) -> str:
    done = [t for t in trades if t["exit"] is not None]
    if not done:
        return (f"📊 **{date}** — no trades today.\n"
                "_Quiet days are normal for this setup._")
    won = sum(1 for t in done if (t["pct"] or 0) > 0)
    pct = sum(t["pct"] or 0 for t in done)
    cash = sum(t.get("cash", 0) for t in done)
    lines = [f"📊 **{date}**", "",
             f"**{len(done)} trade{'s' if len(done) != 1 else ''} · "
             f"{won} won, {len(done) - won} lost · "
             f"{100 * won / len(done):.0f}% win rate**",
             f"**{pct:+.2f}%  (${cash:+,.2f})**", ""]
    for t in done:
        lines.append(f"{'✅' if (t['pct'] or 0) > 0 else '❌'} {t['symbol']} "
                     f"{t['entry_time']}→{t['exit_time']}  {t['pct']:+.2f}%")
    lines.append("\n_Paper only. No orders were placed._")
    return "\n".join(lines)


def load_seen(date: str) -> dict:
    f = STATE / "live_seen.json"
    if f.exists():
        try:
            s = json.loads(f.read_text())
            if s.get("date") == date:
                return s
        except json.JSONDecodeError:
            pass
    return {"date": date, "entries": [], "exits": [], "summary": False}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true",
                    help="ignore the market-hours check")
    args = ap.parse_args(argv)

    now = pd.Timestamp.now(tz=EASTERN)
    if not args.force:
        if now.weekday() > 4:
            log.info("Weekend — nothing to do."); return 0
        if not (pd.Timestamp(OPEN_T).time() <= now.time()
                <= pd.Timestamp("16:10").time()):
            log.info("Outside the window (%s ET)", now.strftime("%H:%M"))
            return 0

    cfg = settings()
    try:
        trades, stamp, day_done = scan(cfg)
    except AlpacaError as exc:
        log.error("Fetch failed: %s", exc); return 1

    date = str(now.date())
    seen = load_seen(date)
    msgs = []
    for t in trades:
        if t["id"] not in seen["entries"]:
            msgs.append(entry_msg(t)); seen["entries"].append(t["id"])
        if t["exit"] is not None and t["id"] not in seen["exits"]:
            msgs.append(close_msg(t)); seen["exits"].append(t["id"])
    if day_done and not seen["summary"]:
        msgs.append(summary_msg(trades, now.strftime("%A %d %B")))
        seen["summary"] = True

    log.info("bars through %s · %d trades today · %d new message(s)",
             stamp, len(trades), len(msgs))
    for m in msgs:
        print("\n" + m)
    if args.dry_run:
        return 0

    STATE.mkdir(exist_ok=True); REPORTS.mkdir(exist_ok=True)
    (STATE / "live_seen.json").write_text(json.dumps(seen, indent=2))
    (REPORTS / "live_today.md").write_text(
        summary_msg(trades, date) + "\n\n" +
        "\n\n".join(entry_msg(t) + ("\n" + close_msg(t) if t["exit"] else "")
                    for t in trades))
    for m in msgs:
        notify(m)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
