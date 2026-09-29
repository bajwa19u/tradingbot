"""How long should a trade be allowed to live?

On 29 September seven of eleven trades exited on the two-hour hold cap and
not one reached its target. Four were stopped out fast at a clean -1%; the
other seven drifted for two hours and closed wherever they happened to be.
+0.08% on PLTR and -0.19% on AMZN are not results, they are noise with a
timer attached.

That cap was MAX_HOLD_MIN = 120, and it was chosen with no evidence at all.
This measures it: the same trades, the same entries, the same stops, with
nothing varied except how long a position is allowed to stay open.

Two questions, in this order:

  1. What actually happened to the trades that timed out - where would they
     have gone if left alone? That is one day and it settles an argument, not
     a strategy.
  2. Does the cap help or hurt across every day we have? That is the part
     worth changing code over.

The exits compared are the same in every case: the stop, the target, or the
closing bell. Only the clock moves.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from zoneinfo import ZoneInfo

import pandas as pd

from .config import REPO_ROOT, Credentials
from .data import AlpacaError, MarketData
from .forensics import CORE, UNIVERSES
from . import opening as op

EASTERN = ZoneInfo("America/New_York")
REPORTS = REPO_ROOT / "reports"
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("holds")

# The live bot's settings, imported rather than retyped so this cannot drift
# away from what actually traded.
from .live_bot import OPENING                                   # noqa: E402

CAPS = [15, 30, 60, 120, 240, 0]        # 0 means no cap: stop, target or bell
NO_CAP = 10_000


def with_cap(minutes: int):
    """Run a block with a different hold cap, then put it back.

    MAX_HOLD_MIN is a module global read inside op.simulate, so this is the
    honest way to vary it. Leaving it mutated would silently change every
    later run in the same process.
    """
    class _Ctx:
        def __enter__(self):
            self.before = op.MAX_HOLD_MIN
            op.MAX_HOLD_MIN = NO_CAP if minutes in (0, None) else int(minutes)
            return self

        def __exit__(self, *a):
            op.MAX_HOLD_MIN = self.before
            return False
    return _Ctx()


def cfg() -> dict:
    return {k: v for k, v in OPENING.items()
            if k not in ("enabled", "observe", "post_sides")}


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
    ends = {}
    for t in trades:
        ends[t["reason"]] = ends.get(t["reason"], 0) + 1
    return {"n": n, "won": won, "lost": n - won,
            "win_pct": round(100 * won / n, 1) if n else 0.0,
            "profit_pct": round(pct, 2),
            "avg_pct": round(pct / n, 3) if n else 0.0,
            "ends": ends, "trades": trades}


HEAD = ("| hold cap | trades | win % | won | lost | profit % | avg/trade |"
        "\n|---|---|---|---|---|---|---|")


def row(label: str, t: dict) -> str:
    return (f"| {label} | {t['n']} | {t['win_pct']:.1f}% | {t['won']} | "
            f"{t['lost']} | {t['profit_pct']:+.1f}% | {t['avg_pct']:+.3f}% |")


def label(cap: int) -> str:
    return "no cap (stop/target/bell)" if cap in (0, None) else f"{cap} min"


def one_day(data: dict[str, pd.DataFrame], date: str, p: dict) -> str:
    """The trades that timed out, and where they actually went."""
    d = pd.Timestamp(date).date()
    base = {}
    with with_cap(OPENING.get("max_hold", 120) or 120):
        for t in trades_for(data, {d}, p):
            base[t["symbol"]] = t
    freed = {}
    with with_cap(0):
        for t in trades_for(data, {d}, p):
            freed[t["symbol"]] = t
    if not base:
        return f"No trades on {date}.\n"

    L = [f"## {date} — the trades that ran out of clock", "",
         "| symbol | capped at 2h | if left alone | difference |",
         "|---|---|---|---|"]
    timed, better, worse = [], 0, 0
    for sym, b in sorted(base.items(), key=lambda kv: kv[1]["entry_time"]):
        f = freed.get(sym)
        if f is None:
            continue
        if b["reason"] != "time":
            L.append(f"| {sym} | {b['pct']:+.2f}% ({b['reason']} "
                     f"{b['exit_time']}) | — same, it never hit the clock | — |")
            continue
        timed.append((sym, b, f))
        diff = f["pct"] - b["pct"]
        better += diff > 0
        worse += diff < 0
        L.append(f"| {sym} | {b['pct']:+.2f}% (timed out {b['exit_time']}) | "
                 f"**{f['pct']:+.2f}%** ({f['reason']} {f['exit_time']}) | "
                 f"{diff:+.2f}% |")
    if timed:
        bt = sum(b["pct"] for _, b, _ in timed)
        ft = sum(f["pct"] for _, _, f in timed)
        L += ["", f"Of the {len(timed)} that timed out, letting them run turns "
                  f"**{bt:+.2f}% into {ft:+.2f}%** "
                  f"({better} better, {worse} worse).", ""]
    return "\n".join(L) + "\n"


def sweep(data: dict[str, pd.DataFrame], p: dict) -> tuple[str, dict]:
    """Every cap over every date, so one good day cannot decide this."""
    dates = sorted({d for df in data.values()
                    for d in df.index.tz_convert(EASTERN).date})
    if len(dates) < 20:
        return f"Only {len(dates)} days — too few to judge a hold cap.\n", {}
    cut = int(len(dates) * 2 / 3)
    explore, holdout = set(dates[:cut]), set(dates[cut:])

    rows, out = [], {}
    for cap in CAPS:
        with with_cap(cap):
            e = tally(trades_for(data, explore, p))
            h = tally(trades_for(data, holdout, p))
        rows.append((cap, e, h))
        out[label(cap)] = {"explore": {k: v for k, v in e.items() if k != "trades"},
                           "holdout": {k: v for k, v in h.items() if k != "trades"}}
        log.info("cap %-6s explore %+.1f%%  holdout %+.1f%%",
                 label(cap), e["profit_pct"], h["profit_pct"])

    L = [f"## Every hold cap, {len(dates)} days "
         f"({dates[0]} to {dates[-1]})", "",
         f"Explore = the first {cut} days, holdout = the last "
         f"{len(dates) - cut}. Entries, stops and targets are identical in "
         "every row; only the clock moves.", "",
         "### Explore", "", HEAD]
    for cap, e, _ in rows:
        L.append(row(label(cap), e))
    L += ["", "### Holdout (dates never used to choose anything)", "", HEAD]
    for cap, _, h in rows:
        L.append(row(label(cap), h))

    live = next((r for r in rows if r[0] == 120), None)
    best_e = max(rows, key=lambda r: r[1]["profit_pct"])
    L += ["", "### Verdict", ""]

    # The holdout is the split that decides. If EVERY cap loses there, then
    # "best" means least-bad and ranking them is picking a favourite among
    # losses. Saying "the holdout agrees" about -18.7% versus -20.8% is the
    # same overclaim that had to be pulled out of the stocks-in-play report.
    if all(r[2]["profit_pct"] <= 0 for r in rows):
        L.append(f"- **Every hold cap loses money on the holdout**, from "
                 f"{min(r[2]['profit_pct'] for r in rows):+.1f}% to "
                 f"{max(r[2]['profit_pct'] for r in rows):+.1f}%. The clock is "
                 f"not what is wrong with this rule — it only decides how the "
                 f"losses are distributed. Ranking these is choosing a "
                 f"favourite among losses.")
    elif live and best_e[0] == 120:
        L.append("- The two-hour cap is the best of the caps tested on the "
                 "explore split. It was a guess, and it happens to hold up.")
    elif live:
        be, bh = best_e[1], dict(rows[[r[0] for r in rows].index(best_e[0])][2])
        L.append(f"- **{label(best_e[0])} beats the live two-hour cap on the "
                 f"explore split** ({be['profit_pct']:+.1f}% against "
                 f"{live[1]['profit_pct']:+.1f}%), and on the holdout it is "
                 f"{bh['profit_pct']:+.1f}% against "
                 f"{live[2]['profit_pct']:+.1f}%.")
        agree = (bh["profit_pct"] > live[2]["profit_pct"])
        L.append("- The holdout agrees, which is the only reason this is "
                 "worth changing." if agree else
                 "- The holdout does NOT agree, so this is a preference of "
                 "the explore dates and not a finding. Leave the cap alone.")
    if all(r[1]["profit_pct"] <= 0 for r in rows):
        L.append("- **Every cap loses money on the explore split.** The hold "
                 "limit is not what is wrong with this rule; it only decides "
                 "how the losses are distributed.")
    L.append("")
    L.append("### How trades ended, by cap")
    L.append("")
    L.append("| hold cap | stop | target | time | bell |")
    L.append("|---|---|---|---|---|")
    for cap, e, _ in rows:
        n = e["ends"]
        L.append(f"| {label(cap)} | {n.get('stop', 0)} | {n.get('target', 0)} "
                 f"| {n.get('time', 0)} | {n.get('close', 0) + n.get('bell', 0)} |")
    return "\n".join(L) + "\n", out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--universe", default="core")
    ap.add_argument("--date", default="", help="one day to break down in detail")
    args = ap.parse_args(argv)

    symbols = UNIVERSES.get(args.universe) or CORE
    try:
        md = MarketData(Credentials.from_env(), feed="iex")
        data = op.fetch(md, symbols, args.days)
    except AlpacaError as exc:
        log.error("Fetch failed: %s", exc)
        return 1
    if not data:
        log.error("No usable data.")
        return 1

    p = cfg()
    parts = ["# How long should a trade be allowed to live?", ""]
    if args.date:
        parts.append(one_day(data, args.date, p))
    body, js = sweep(data, p)
    parts.append(body)

    out = "\n".join(parts)
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "holds.md").write_text(out)
    (REPORTS / "holds.json").write_text(json.dumps(js, indent=2, default=str))
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
