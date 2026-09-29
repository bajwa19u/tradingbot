"""Would a wider stop have saved the losers? Would a different target help?

The question every losing day produces, and the one that is easiest to
answer dishonestly. Looking at a loser and noting that price came back is
hindsight; the only fair test runs the SAME rule with a wider stop over
every trade, so the rescues and the extra damage are counted together.

Two things get measured, because a wider stop does two opposite things:

  RESCUES      losers that no longer stop out, and go on to reach the target
  EXTRA COST   losers that still fail, now failing from further away

Room is never free. A stop pushed 1% further out turns some -1% losses into
+2% wins and turns every remaining -1% loss into something worse. Whether
that trade is worth making is arithmetic, not opinion, and this does the
arithmetic.

The target is swept alongside it because the two are not independent: a
wider stop with the same reward multiple is a bigger absolute target, and
price has to travel further to reach it.

Everything keeps the project's usual discipline - explore split, holdout of
dates never used to choose anything, slippage charged both ends, and a
verdict that refuses to call a least-bad configuration an improvement.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from itertools import product
from zoneinfo import ZoneInfo

import pandas as pd

from .config import REPO_ROOT, Credentials
from .data import AlpacaError, MarketData
from .forensics import CORE, UNIVERSES
from . import opening as op
from .live_bot import OPENING

EASTERN = ZoneInfo("America/New_York")
REPORTS = REPO_ROOT / "reports"
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("widths")

PADS = [0.0, 0.5, 1.0, 2.0]             # extra stop room, % of entry price
TARGETS = [1.0, 1.5, 2.0, 3.0, "level"]   # multiple of risk, or structure


def cfg() -> dict:
    return {k: v for k, v in OPENING.items()
            if k not in ("enabled", "observe", "post_sides")}


def variant(p: dict, pad: float, target) -> dict:
    """`target` is a reward multiple, or "level" for the next structural
    price in our direction — yesterday's high/low/close or the other side of
    the opening range."""
    if target == "level":
        return {**p, "stop_pad_pct": pad, "target_mode": "level"}
    return {**p, "stop_pad_pct": pad, "target_mode": "r", "target_r": target}


def trades_for(data: dict[str, pd.DataFrame], dates: set | None,
               p: dict) -> list[dict]:
    out = []
    for sym, df in data.items():
        days = op.by_day(df)
        for n in range(1, len(days)):
            date, day = days[n]
            if dates is not None and date not in dates:
                continue
            _, prior = op.split_session(days[n - 1][1])
            for t in op.day_trades(day, prior, p):
                t.update(symbol=sym, date=str(date))
                out.append(t)
    return out


def tally(trades: list[dict]) -> dict:
    trades = [t for t in trades if t.get("reason") != "open"]
    n = len(trades)
    won = sum(1 for t in trades if t["pct"] > 0)
    pct = sum(t["pct"] for t in trades)
    losses = [t["pct"] for t in trades if t["pct"] <= 0]
    wins = [t["pct"] for t in trades if t["pct"] > 0]
    return {"n": n, "won": won, "lost": n - won,
            "win_pct": round(100 * won / n, 1) if n else 0.0,
            "profit_pct": round(pct, 2),
            "avg_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
            "trades": trades}


def key(t: dict) -> tuple:
    return (t["symbol"], t["date"], t["entry_time"], t["side"])


def rescue_count(base: list[dict], wider: list[dict]) -> tuple[int, int, int]:
    """(rescued, still lost but worse, unchanged) between two runs.

    Matched by symbol, date, entry time and side - the same trade, differing
    only in where its stop sat. Anything that does not match in both runs is
    ignored rather than guessed at.
    """
    b = {key(t): t for t in base}
    w = {key(t): t for t in wider}
    rescued = worse = same = 0
    for k, bt in b.items():
        wt = w.get(k)
        if wt is None:
            continue
        if bt["pct"] <= 0 < wt["pct"]:
            rescued += 1
        elif bt["pct"] <= 0 and wt["pct"] < bt["pct"]:
            worse += 1
        else:
            same += 1
    return rescued, worse, same


HEAD = ("| stop room | target | trades | win % | won | lost | avg win | "
        "avg loss | profit % |\n|---|---|---|---|---|---|---|---|---|")


def row(pad: float, tr, t: dict) -> str:
    lab = "next level" if tr == "level" else f"{tr:g}x"
    return (f"| +{pad:.1f}% | {lab} | {t['n']} | {t['win_pct']:.1f}% | "
            f"{t['won']} | {t['lost']} | {t['avg_win']:+.2f}% | "
            f"{t['avg_loss']:+.2f}% | {t['profit_pct']:+.1f}% |")


def day_detail(data: dict[str, pd.DataFrame], date: str, p: dict) -> str:
    """Today's losers, one row each, at every stop width."""
    d = pd.Timestamp(date).date()
    runs = {}
    for pad in PADS:
        runs[pad] = {key(t)[:1] + key(t)[2:]: t
                     for t in trades_for(data, {d}, variant(p, pad,
                                                            p["target_r"]))}
    base = runs[PADS[0]]
    losers = {k: t for k, t in base.items() if t["pct"] <= 0}
    if not losers:
        return f"No losing trades on {date}.\n"

    L = [f"## {date} — the losers, with more room on the stop", "",
         "| symbol | as traded | " +
         " | ".join(f"stop +{p:.1f}%" for p in PADS[1:]) + " |",
         "|---" * (len(PADS) + 1) + "|"]
    for k in sorted(losers, key=lambda k: base[k]["entry_time"]):
        cells = []
        for pad in PADS[1:]:
            t = runs[pad].get(k)
            cells.append("—" if t is None
                         else f"**{t['pct']:+.2f}%** ({t['reason']})")
        L.append(f"| {k[0]} | {base[k]['pct']:+.2f}% "
                 f"({base[k]['reason']}) | " + " | ".join(cells) + " |")

    L += ["", "| stop room | day total | won | lost |", "|---|---|---|---|"]
    for pad in PADS:
        ts = list(runs[pad].values())
        w = sum(1 for t in ts if t["pct"] > 0)
        L.append(f"| +{pad:.1f}% | **{sum(t['pct'] for t in ts):+.2f}%** | "
                 f"{w} | {len(ts) - w} |")
    return "\n".join(L) + "\n"


def sweep(data: dict[str, pd.DataFrame], p: dict) -> tuple[str, dict]:
    dates = sorted({d for df in data.values()
                    for d in df.index.tz_convert(EASTERN).date})
    if len(dates) < 20:
        return f"Only {len(dates)} days — too few to judge.\n", {}
    cut = int(len(dates) * 2 / 3)
    explore, holdout = set(dates[:cut]), set(dates[cut:])

    base_e = trades_for(data, explore, variant(p, 0.0, p["target_r"]))
    # which target each trade actually used, so a level target can be seen
    # to be doing something rather than silently falling back
    rows, js = [], {}
    for pad, tr in product(PADS, TARGETS):
        q = variant(p, pad, tr)
        e = tally(trades_for(data, explore, q))
        h = tally(trades_for(data, holdout, q))
        rows.append((pad, tr, e, h))
        js[f"pad{pad}/target{tr}"] = {
            "explore": {k: v for k, v in e.items() if k != "trades"},
            "holdout": {k: v for k, v in h.items() if k != "trades"}}
        log.info("pad %+.1f%% target %-6s explore %+.1f%%  holdout %+.1f%%",
                 pad, tr, e["profit_pct"], h["profit_pct"])

    L = [f"## Every stop width and target, {len(dates)} days "
         f"({dates[0]} to {dates[-1]})", "",
         f"Explore = first {cut} days, holdout = last {len(dates) - cut}. "
         "Stop room is extra distance beyond the rule's own stop, as a "
         "percent of the entry price.", "", "### Explore", "", HEAD]
    for pad, tr, e, _ in rows:
        L.append(row(pad, tr, e))
    L += ["", "### Holdout (never used to choose anything)", "", HEAD]
    for pad, tr, _, h in rows:
        L.append(row(pad, tr, h))

    # A level target that silently falls back to the multiple produces a row
    # identical to the multiple's. That happened once and went unnoticed, so
    # the report now states outright how often the level was really used.
    lv_used = {}
    for pad in PADS:
        ts = [t for t in trades_for(data, explore, variant(p, pad, "level"))
              if t.get("reason") != "open"]
        named = sum(1 for t in ts if t.get("target_name") not in
                    (None, f"{p['target_r']:g}x"))
        lv_used[pad] = (named, len(ts))
    L += ["", "### Did the level target actually get used?", "",
          "| stop room | trades aiming at a real level | of |",
          "|---|---|---|"]
    for pad in PADS:
        a, b = lv_used[pad]
        L.append(f"| +{pad:.1f}% | {a} | {b} |")
    if all(a == 0 for a, _ in lv_used.values()):
        L.append("")
        L.append("> **Never used.** Every level target fell back to the fixed "
                 "multiple, so those rows measure nothing new.")

    L += ["", "### What the extra room actually buys, at the live target", "",
          "| stop room | losers rescued | losers made worse | net profit % |",
          "|---|---|---|---|"]
    for pad in PADS[1:]:
        wider = trades_for(data, explore, variant(p, pad, p["target_r"]))
        r, w, _ = rescue_count(base_e, wider)
        net = tally(wider)["profit_pct"] - tally(base_e)["profit_pct"]
        L.append(f"| +{pad:.1f}% | {r} | {w} | {net:+.1f}% |")

    L += ["", "### Verdict", ""]
    if all(h["profit_pct"] <= 0 for _, _, _, h in rows):
        best_h = max(rows, key=lambda r: r[3]["profit_pct"])
        L.append(f"- **Every stop width and every target loses money on the "
                 f"holdout**, the best being +{best_h[0]:.1f}% room at "
                 f"{best_h[1]} on {best_h[3]['profit_pct']:+.1f}%. Widening "
                 f"the stop rescues trades and costs more on the ones it does "
                 f"not rescue, and the two cancel. This is not the dial that "
                 f"is wrong.")
    else:
        best_e = max(rows, key=lambda r: r[2]["profit_pct"])
        agrees = best_e[3]["profit_pct"] > 0
        L.append(f"- Best on explore: +{best_e[0]:.1f}% room at "
                 f"{best_e[1]}, {best_e[2]['profit_pct']:+.1f}%.")
        L.append(f"- On the holdout that setting makes "
                 f"{best_e[3]['profit_pct']:+.1f}%"
                 + (", which is the only reason it is worth anything."
                    if agrees else
                    ", so it is a preference of the explore dates. Ignore it."))
    return "\n".join(L) + "\n", js


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--universe", default="core")
    ap.add_argument("--date", default="", help="one day to break down")
    args = ap.parse_args(argv)

    try:
        md = MarketData(Credentials.from_env(), feed="iex")
        data = op.fetch(md, UNIVERSES.get(args.universe) or CORE, args.days)
    except AlpacaError as exc:
        log.error("Fetch failed: %s", exc)
        return 1
    if not data:
        log.error("No usable data.")
        return 1

    p = cfg()
    parts = ["# Stop width and target", ""]
    if args.date:
        parts.append(day_detail(data, args.date, p))
    body, js = sweep(data, p)
    parts.append(body)

    out = "\n".join(parts)
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "widths.md").write_text(out)
    (REPORTS / "widths.json").write_text(json.dumps(js, indent=2, default=str))
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
