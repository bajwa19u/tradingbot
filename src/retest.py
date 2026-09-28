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
    last = float(day["close"].iloc[-1])
    r = (last - entry) / rps if side == "long" else (entry - last) / rps
    return {"won": 1 if r > 0 else 0, "r": round(r, 2)}


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


def replay_message(sigs: list[dict], when: str) -> str:
    if not sigs:
        return (f"**Replay — {when}**\n\nNo setups today. The rule needs a "
                "coil, a break down through it, and price back at the level. "
                "Empty days are normal.\n_Replay of a closed session, not a "
                "live signal._")
    lines = [f"🔁 **REPLAY — {when}** · {len(sigs)} setup"
             f"{'s' if len(sigs) != 1 else ''}",
             "_What the rule would have sent today, at the times it would "
             "have sent them. The session is closed - none of this is "
             "actionable now._", ""]
    won = 0
    for s in sigs:
        size = (f"{s['shares']} share{'s' if s['shares'] != 1 else ''}"
                if s["shares"] else "**too small for the account**")
        lines += [f"🔻 **SHORT {s['symbol']}** — {s['entry_time']} ET",
                  f"Broke `${s['level']:,.2f}` at {s['break_time']}, retested "
                  f"it, entered `${s['entry']:,.2f}`",
                  f"Stop `${s['stop']:,.2f}` · target `${s['target']:,.2f}` "
                  f"· {size}"
                  + (f" · risking `${s['risk']:,.2f}`" if s["shares"] else "")]
        o = s.get("outcome")
        if o:
            won += o["won"]
            lines.append(f"→ _Result: {'WON' if o['won'] else 'lost'} "
                         f"({o['r']:+.2f}R)_")
        lines.append("")
    lines += [f"**Today: {won} won, {len(sigs) - won} lost.**",
              "_Paper only. No orders were placed._"]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--minutes", type=int, default=5)
    ap.add_argument("--universe", default="movers", choices=list(UNIVERSES))
    ap.add_argument("--symbols", default=None,
                    help="comma-separated, overrides --universe")
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

    if args.replay:
        today = pd.Timestamp.now(tz=EASTERN).date()
        data = {s: d[d.index.tz_convert(EASTERN).date == today]
                for s, d in data.items()}
        data = {s: d for s, d in data.items() if len(d) > 20}
        sigs = signals_today(data, p)
        when = f"{today} · {len(data)} symbols"
        msg = replay_message(sigs, when)
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
