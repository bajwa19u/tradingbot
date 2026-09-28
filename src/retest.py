"""Break and retest — which conditions actually matter.

Different entry from everything tested so far. The squeeze buys the break
itself; this waits for price to come BACK to the broken level and enters
there. Three things change: a better price, a tighter stop, and the retest
itself acts as a filter.

The method is the autopsy's, not the backtest's. Every break in the window is
followed, every retest labelled by whether it reached 2R before -1R. That
gives thousands of samples instead of the couple of dozen a portfolio
backtest produces, so a difference between conditions means something.

Conditions tested, one at a time:
  wait        how many bars the retest is allowed to take
  depth       how close to the level price must return
  confirm     enter on the touch, or wait for a bar to close back in the
              direction of the break

Nothing else is tuned. The stop and target are fixed for every combination so
the comparison is between CONDITIONS, not between a condition and a lucky
stop.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from itertools import product
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .config import REPO_ROOT, Credentials
from .data import AlpacaError, MarketData
from .forensics import UNIVERSES
from .squeeze import BASE_SQ, prepare_sq

EASTERN = ZoneInfo("America/New_York")
REPORTS = REPO_ROOT / "reports"
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("retest")

SCAN = {**BASE_SQ, "squeeze_atr": 3.0, "vol_mult": 1.0}
TARGET_R = 2.0
STOP_ATR = 1.0          # beyond the level, fixed for every combination


def breaks_in(day: pd.DataFrame, p: dict) -> list[tuple[int, str, float]]:
    """(bar index, direction, the level that broke)."""
    a, close, vol = day["atr"], day["close"], day["volume"]
    ch, cl, cv = day["coil_high"], day["coil_low"], day["coil_vol"]
    ok = (((ch - cl) <= p["squeeze_atr"] * a) & (vol >= p["vol_mult"] * cv)
          & a.notna() & ch.notna() & cv.notna() & (a > 0))
    up = ok & (close > ch) & (close > day["open"])
    dn = ok & (close < cl) & (close < day["open"])
    lo_t = pd.Timestamp(p["no_entry_before"]).time()
    hi_t = pd.Timestamp(p["no_entry_after"]).time()
    times = day.index.tz_convert(EASTERN).time
    out = []
    for i in range(p["base_len"] + p["atr_len"], len(day) - 6):
        if not (lo_t <= times[i] <= hi_t):
            continue
        if bool(up.iloc[i]):
            out.append((i, "long", float(ch.iloc[i])))
        elif bool(dn.iloc[i]):
            out.append((i, "short", float(cl.iloc[i])))
    return out


def find_retest(day: pd.DataFrame, i: int, side: str, level: float,
                wait: int, depth_atr: float, confirm: bool) -> int | None:
    """The bar the retest entry happens on, or None if it never sets up.

    A retest that never comes back is NOT a missed trade to be counted later -
    it is simply no trade. Counting those as winners because the price ran
    away is the single easiest way to fake a good result here, so they are
    dropped entirely.
    """
    a = float(day["atr"].iloc[i])
    if a <= 0:
        return None
    band = depth_atr * a
    for j in range(i + 1, min(i + 1 + wait, len(day))):
        b = day.iloc[j]
        came_back = (float(b["low"]) <= level + band if side == "long"
                     else float(b["high"]) >= level - band)
        if not came_back:
            continue
        # the level has to hold: price must not close through it
        broke_back = (float(b["close"]) < level if side == "long"
                      else float(b["close"]) > level)
        if broke_back:
            return None
        if not confirm:
            return j
        # confirmation: a later bar closes back in the break's direction
        for k in range(j, min(j + 3, len(day))):
            c = day.iloc[k]
            if (float(c["close"]) > float(c["open"]) if side == "long"
                    else float(c["close"]) < float(c["open"])):
                return k
        return None
    return None


def label(day: pd.DataFrame, j: int, side: str, level: float,
          i: int) -> dict | None:
    """2R before -1R, from the retest entry, stop beyond the level."""
    a = float(day["atr"].iloc[i])
    entry = float(day["close"].iloc[j])
    stop = level - STOP_ATR * a if side == "long" else level + STOP_ATR * a
    rps = abs(entry - stop)
    if rps <= 0 or rps / entry > 0.10:
        return None
    target = entry + TARGET_R * rps if side == "long" else entry - TARGET_R * rps
    for k in range(j + 1, len(day)):
        b = day.iloc[k]
        hi, lo = float(b["high"]), float(b["low"])
        if (lo <= stop if side == "long" else hi >= stop):
            return {"won": 0, "r": -1.0}
        if (hi >= target if side == "long" else lo <= target):
            return {"won": 1, "r": TARGET_R}
    # The session ended before this hit either side. It is NOT a loss - it is
    # a trade that never finished, and filing it with the real losers makes
    # the win rate look worse and the average loss look smaller than they are.
    last = float(day["close"].iloc[-1])
    r = (last - entry) / rps if side == "long" else (entry - last) / rps
    return {"won": 1 if r > 0 else 0, "r": round(r, 2), "unfinished": True}


def run(data: dict, p: dict, combos: list[dict]) -> list[dict]:
    tally = {c["name"]: {"n": 0, "won": 0, "r": 0.0, "long": 0, "long_won": 0,
                         "short": 0, "short_won": 0, **c} for c in combos}
    breaks_seen = 0
    for sym, df in data.items():
        if df.empty:
            continue
        d = prepare_sq(df, p)
        for _, day in d.groupby(d.index.tz_convert(EASTERN).date):
            if len(day) < p["base_len"] + p["atr_len"] + 8:
                continue
            for i, side, level in breaks_in(day, p):
                breaks_seen += 1
                for c in combos:
                    j = find_retest(day, i, side, level, c["wait"],
                                    c["depth"], c["confirm"])
                    if j is None:
                        continue
                    res = label(day, j, side, level, i)
                    if res is None:
                        continue
                    t = tally[c["name"]]
                    t["n"] += 1
                    t["won"] += res["won"]
                    t["r"] += res["r"]
                    t[side] += 1
                    t[f"{side}_won"] += res["won"]
    rows = []
    for t in tally.values():
        if t["n"] < 30:
            continue
        rows.append({
            "name": t["name"], "wait": t["wait"], "depth": t["depth"],
            "confirm": t["confirm"], "n": t["n"], "won": t["won"],
            "lost": t["n"] - t["won"],
            "win_rate_pct": round(100 * t["won"] / t["n"], 1),
            "avg_r": round(t["r"] / t["n"], 3),
            "long_pct": round(100 * t["long_won"] / t["long"], 1) if t["long"] else None,
            "short_pct": round(100 * t["short_won"] / t["short"], 1) if t["short"] else None,
        })
    rows.sort(key=lambda r: -r["avg_r"])
    return rows, breaks_seen


def breakeven_rate() -> float:
    """The win rate a 2:1 payoff needs just to break even."""
    return 100 / (1 + TARGET_R)


def render(p: dict) -> str:
    rows = p["rows"]
    be = breakeven_rate()
    out = [f"# Break and retest — which conditions matter", "",
           f"**{p['breaks']} breaks followed · {p['symbols']} symbols · from "
           f"{p['start']} · {p['generated']}**", "",
           f"Entry on the retest of the broken level. Stop {STOP_ATR} ATR "
           f"beyond it, target {TARGET_R}R, identical for every row - so the "
           "comparison is between conditions, not between a condition and a "
           "lucky stop.", "",
           f"**Break-even needs {be:.1f}%.** Below that the setup loses, "
           "however good the win rate looks next to a coin flip.", "",
           "| Wait | Depth | Confirm | Trades | Won | Lost | Win % | Avg R |",
           "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        mark = " ✅" if r["win_rate_pct"] > be else ""
        out.append(f"| {r['wait']} bars | {r['depth']} ATR | "
                   f"{'yes' if r['confirm'] else 'no'} | {r['n']} | "
                   f"{r['won']} | {r['lost']} | **{r['win_rate_pct']}%**{mark} "
                   f"| {r['avg_r']:+.3f} |")
    out.append("")
    good = [r for r in rows if r["win_rate_pct"] > be]
    if not good:
        best = rows[0] if rows else None
        out.append(f"**Nothing clears break-even.** The best is "
                   f"{best['win_rate_pct']}% against the {be:.1f}% needed."
                   if best else "**No condition produced enough trades.**")
        return "\n".join(out)

    b = good[0]
    out += [f"### Best: wait {b['wait']} bars, {b['depth']} ATR depth, "
            f"confirm {'on' if b['confirm'] else 'off'}", "",
            f"**{b['win_rate_pct']}% of {b['n']} trades, {b['avg_r']:+.3f}R "
            f"average.** Break-even is {be:.1f}%.", ""]
    if b["long_pct"] is not None and b["short_pct"] is not None:
        out.append(f"Long {b['long_pct']}% · short {b['short_pct']}%")
    out += ["", f"_{len(rows)} combinations were compared. With that many, "
            "the best one looks better than it is - treat this as the "
            "candidate to test on unseen symbols, not as a result._"]
    return "\n".join(out)


# The rule this bot trades. Fixed, and chosen BEFORE the holdout was run:
#   retest entry, shorts only, no confirmation candle, 12-bar wait, 0.25 ATR
# On 50 fresh symbols it never saw: 40.4% of shorts against a 33.3% break-even.
LIVE = {"wait": 12, "depth": 0.25, "confirm": False, "side": "short"}


def signals_today(data: dict, p: dict) -> list[dict]:
    """Every entry the rule would have taken today, in order.

    A replay, not a forecast. Each signal is stamped with the bar time it
    fired on so it can be checked against the chart rather than believed.
    """
    from .paper import settings, shares
    cfg = settings()
    out = []
    for sym, df in data.items():
        if df.empty:
            continue
        d = prepare_sq(df, p)
        for _, day in d.groupby(d.index.tz_convert(EASTERN).date):
            if len(day) < p["base_len"] + p["atr_len"] + 8:
                continue
            for i, side, level in breaks_in(day, p):
                if side != LIVE["side"]:
                    continue
                j = find_retest(day, i, side, level, LIVE["wait"],
                                LIVE["depth"], LIVE["confirm"])
                if j is None:
                    continue
                a = float(day["atr"].iloc[i])
                entry = float(day["close"].iloc[j])
                stop = level + STOP_ATR * a
                rps = abs(entry - stop)
                if rps <= 0 or rps / entry > 0.10:
                    continue
                target = entry - TARGET_R * rps
                res = label(day, j, side, level, i)
                out.append({
                    "symbol": sym, "side": side,
                    "break_time": str(day.index[i].tz_convert(EASTERN))[11:16],
                    "entry_time": str(day.index[j].tz_convert(EASTERN))[11:16],
                    "level": round(level, 2), "entry": round(entry, 2),
                    "stop": round(stop, 2), "target": round(target, 2),
                    "shares": shares(entry, rps, cfg["equity"], cfg["risk_pct"]),
                    "risk": round(shares(entry, rps, cfg["equity"],
                                         cfg["risk_pct"]) * rps, 2),
                    "outcome": res})
    out.sort(key=lambda r: r["entry_time"])
    return out


def day_log_path():
    return REPO_ROOT / "state" / "replay_log.jsonl"


def record_day(date: str, universe: str, sigs: list[dict],
               equity: float, risk_pct: float) -> dict:
    """Append this day's result and return it. Append-only, never rewritten."""
    done = [s for s in sigs if not s["outcome"].get("unfinished")]
    won = sum(1 for s in done if s["outcome"]["won"])
    # profit as a percentage of the account, which is the only unit the owner
    # asked for. R multiples are kept out of every message on purpose.
    pct = sum(s["outcome"]["r"] * risk_pct for s in sigs)
    cash = sum(s["risk"] * s["outcome"]["r"] for s in sigs)
    row = {"date": date, "universe": universe, "trades": len(sigs),
           "won": won, "lost": len(done) - won,
           "unfinished": len(sigs) - len(done),
           "win_pct": round(100 * won / len(done), 1) if done else 0.0,
           "profit_pct": round(pct, 2), "profit_dollars": round(cash, 2)}
    path = day_log_path()
    path.parent.mkdir(exist_ok=True)
    seen = []
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            # re-running the same day replaces that day rather than
            # double-counting it into the running total
            if not (r.get("date") == date and r.get("universe") == universe):
                seen.append(r)
    seen.append(row)
    path.write_text("\n".join(json.dumps(r) for r in seen) + "\n")
    return row


def recap(universe: str, days: int = 10) -> tuple[list[dict], dict]:
    path = day_log_path()
    if not path.exists():
        return [], {}
    rows = []
    for line in path.read_text().splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("universe") == universe:
            rows.append(r)
    rows.sort(key=lambda r: r["date"])
    if not rows:
        return [], {}
    t = sum(r["trades"] for r in rows)
    w = sum(r["won"] for r in rows)
    total = {"days": len(rows), "trades": t, "won": w, "lost": t - w,
             "win_pct": round(100 * w / t, 1) if t else 0.0,
             "profit_pct": round(sum(r["profit_pct"] for r in rows), 2),
             "profit_dollars": round(sum(r["profit_dollars"] for r in rows), 2),
             "green_days": sum(1 for r in rows if r["profit_pct"] > 0)}
    return rows[-days:], total


def replay_message(sigs: list[dict], when: str, universe: str = "fresh",
                   risk_pct: float = 1.0) -> str:
    date = when.split(" ")[0]
    if not sigs:
        head = (f"**Replay — {when}**\n\nNo setups today. The rule needs a "
                "coil, a break down through it, and price back at the level. "
                "Empty days are normal.")
    else:
        done = [s for s in sigs if not s["outcome"].get("unfinished")]
        open_at_bell = len(sigs) - len(done)
        won = sum(1 for s in done if s["outcome"]["won"])
        day_pct = sum(s["outcome"]["r"] * risk_pct for s in sigs)
        day_cash = sum(s["risk"] * s["outcome"]["r"] for s in sigs)
        lines = [f"🔁 **REPLAY — {when}** · {len(sigs)} setup"
                 f"{'s' if len(sigs) != 1 else ''}",
                 "_What the rule would have sent today, at the times it would "
                 "have sent them. The session is closed - none of this is "
                 "actionable now._", ""]
        for s in sigs:
            size = (f"{s['shares']} share{'s' if s['shares'] != 1 else ''}"
                    if s["shares"] else "**too small for the account**")
            o = s["outcome"]
            pct = o["r"] * risk_pct
            cash = s["risk"] * o["r"]
            verdict = ("UNFINISHED" if o.get("unfinished")
                       else "WON" if o["won"] else "LOST")
            lines += [f"🔻 **SHORT {s['symbol']}** — {s['entry_time']} ET",
                      f"Broke `${s['level']:,.2f}` at {s['break_time']}, "
                      f"retested it, entered `${s['entry']:,.2f}`",
                      f"Stop `${s['stop']:,.2f}` · target "
                      f"`${s['target']:,.2f}` · {size}",
                      f"→ **{verdict} {pct:+.2f}%** (${cash:+,.2f})"
                      + ("  _(still open at the bell, closed at the last "
                         "price)_" if o.get("unfinished") else ""), ""]
        rate = (f"{100 * won / len(done):.0f}% win rate" if done
                else "no finished trades")
        tail = (f" · {open_at_bell} still open at the bell"
                if open_at_bell else "")
        lines += [f"**Today: {won} won, {len(done) - won} lost · {rate} · "
                  f"{day_pct:+.2f}% (${day_cash:+,.2f})**{tail}"]
        head = "\n".join(lines)

    rows, total = recap(universe)
    if not rows:
        return head + "\n_Paper only. No orders were placed._"
    out = [head, "", "---", "", f"**Last {len(rows)} day"
           f"{'s' if len(rows) != 1 else ''} — {universe}**", "",
           "| Day | Trades | Won | Lost | Win % | Profit |",
           "|---|---|---|---|---|---|"]
    for r in rows:
        out.append(f"| {r['date'][5:]} | {r['trades']} | {r['won']} | "
                   f"{r['lost']} | {r['win_pct']}% | "
                   f"**{r['profit_pct']:+.2f}%** |")
    out += ["",
            f"**Running total: {total['trades']} trades · {total['won']} won, "
            f"{total['lost']} lost · {total['win_pct']}% win rate · "
            f"{total['profit_pct']:+.2f}% "
            f"(${total['profit_dollars']:+,.2f})**",
            f"_{total['green_days']} of {total['days']} days green._"]
    if total["trades"] < 50:
        out.append(f"_{total['trades']} trades so far. The backtest needed "
                   "about fifty before the numbers stopped moving around._")
    out.append("_Paper only. No orders were placed._")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--minutes", type=int, default=5)
    ap.add_argument("--universe", default="movers", choices=list(UNIVERSES))
    ap.add_argument("--symbols", default=None,
                    help="comma-separated, overrides --universe")
    ap.add_argument("--chart", default=None,
                    help="SYMBOL to export bars + the day's signals for, so "
                         "the setup can be drawn and checked by eye")
    ap.add_argument("--replay", action="store_true",
                    help="run the live rule over today only and send what it "
                         "would have fired to Discord")
    ap.add_argument("--no-notify", action="store_true")
    args = ap.parse_args(argv)

    p = {**SCAN, "minutes": args.minutes}
    combos = [{"name": f"w{w}_d{d}_{'c' if c else 'n'}",
               "wait": w, "depth": d, "confirm": c}
              for w, d, c in product((3, 6, 12), (0.0, 0.25, 0.5),
                                     (False, True))]
    syms = ([x.strip().upper() for x in args.symbols.split(",")]
            if args.symbols else UNIVERSES[args.universe])
    start = args.start or (pd.Timestamp.now(tz=EASTERN)
                           - pd.Timedelta(days=60)).date().isoformat()
    try:
        md = MarketData(Credentials.from_env(), feed="iex")
        log.info("Fetching %d symbols, %d-min bars from %s",
                 len(syms), args.minutes, start)
        data = md.intraday_bars(syms, args.minutes, start=start, end=args.end)
    except AlpacaError as exc:
        log.error("Fetch failed: %s", exc)
        return 1
    data = {s: d for s, d in data.items() if not d.empty}

    if args.chart:
        sym = args.chart.upper()
        if sym not in data:
            log.error("No data for %s. Have: %s", sym,
                      ", ".join(sorted(data)[:12]))
            return 1
        today = pd.Timestamp.now(tz=EASTERN).date()
        df = data[sym]
        df = df[df.index.tz_convert(EASTERN).date == today]
        if len(df) < 20:
            log.error("Only %d bars for %s today", len(df), sym)
            return 1
        d = prepare_sq(df, p)
        sigs = [x for x in signals_today({sym: df}, p)]
        bars = [{"t": str(i.tz_convert(EASTERN))[11:16],
                 "o": round(float(r["open"]), 2),
                 "h": round(float(r["high"]), 2),
                 "l": round(float(r["low"]), 2),
                 "c": round(float(r["close"]), 2),
                 "v": int(r["volume"]),
                 # the coil the rule was watching, as it looked on that bar
                 "ch": None if r["coil_high"] != r["coil_high"] else round(float(r["coil_high"]), 2),
                 "cl": None if r["coil_low"] != r["coil_low"] else round(float(r["coil_low"]), 2)}
                for i, r in d.iterrows()]
        out = {"symbol": sym, "date": str(today), "bars": bars,
               "signals": sigs}
        REPORTS.mkdir(exist_ok=True)
        (REPORTS / f"chart_{sym}.json").write_text(
            json.dumps(out, indent=1, default=str))
        log.info("Exported %d bars and %d signal(s) for %s",
                 len(bars), len(sigs), sym)
        return 0

    if args.replay:
        today = pd.Timestamp.now(tz=EASTERN).date()
        data = {s: d[d.index.tz_convert(EASTERN).date == today]
                for s, d in data.items()}
        data = {s: d for s, d in data.items() if len(d) > 20}
        sigs = signals_today(data, p)
        from .paper import settings
        cfg = settings()
        uni = args.symbols and "custom" or args.universe
        if sigs:
            record_day(str(today), uni, sigs, cfg["equity"], cfg["risk_pct"])
        when = f"{today} · {len(data)} symbols"
        msg = replay_message(sigs, when, uni, cfg["risk_pct"])
        print(msg)
        REPORTS.mkdir(exist_ok=True)
        (REPORTS / "replay.md").write_text(msg)
        (REPORTS / "replay.json").write_text(json.dumps(
            {"date": str(today), "signals": sigs}, indent=2, default=str))
        if not args.no_notify:
            from .paper import notify
            notify(msg)
            log.info("Replay sent: %d signal(s)", len(sigs))
        return 0

    rows, seen = run(data, p, combos)
    log.info("%d breaks followed, %d combinations with enough trades",
             seen, len(rows))
    payload = {"symbols": len(data), "start": start, "breaks": seen,
               "rows": rows,
               "generated": datetime.now().strftime("%Y-%m-%d %H:%M")}
    REPORTS.mkdir(exist_ok=True)
    text = render(payload)
    (REPORTS / "retest.md").write_text(text)
    (REPORTS / "retest.json").write_text(json.dumps(payload, indent=2,
                                                    default=str))
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
