"""Why the opening-range trades lose, feature by feature.

On 29 September the rule went 0 for 6 and every loss was the same loss:
AVGO, AMD, NVDA, TSLA, GOOGL, AMZN, MSFT, MU, PLTR, SMCI and META all broke
their opening-range LOW between 09:35 and 09:45, all went short, and all of
them reversed together. That is not six signals, it is one market move read
six times - and a rule that cannot tell the difference will keep betting the
whole account on a single opinion.

Sweeping stop widths, targets, hold caps and range lengths has now been done
and every one of them loses out of sample. So this stops tuning dials and
asks a different question: of all the breaks this rule takes, is there any
observable property that separates the ones that work from the ones that do
not?

The features, and why each is here:

  cohort       how many OTHER names broke the same way within ten minutes.
               The 29 September hypothesis, stated so it can be measured: a
               break that the whole sector is making at once is the market
               moving, and a break only one or two names are making is that
               name doing something of its own.
  minute       how long after the bell the break came. An 09:31 break and an
               09:55 break are not the same event.
  gap          the overnight gap, open against yesterday's close. A stock
               that gapped is already extended before the range even forms.
  width        the range as a percent of price - a tight range breaks more
               easily and means less.
  push         the break bar's volume against the range's own average, the
               usual test of whether anyone is actually behind the move.
  with_gap     whether the break runs the same way as the gap or against it.
  alone        cohort of one: nobody else broke with it.

Nothing is tuned here. Every break is labelled at the settings the bot
actually trades and then grouped, so a difference between groups is a
property of the market rather than of a parameter search.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .config import REPO_ROOT, Credentials
from .data import AlpacaError, MarketData
from .forensics import BIGTECH, UNIVERSES
from . import opening as op
from .live_bot import OPENING

EASTERN = ZoneInfo("America/New_York")
REPORTS = REPO_ROOT / "reports"
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("orb_autopsy")

COHORT_WINDOW_MIN = 10


def cfg(or_minutes: int, pad: float) -> dict:
    p = {k: v for k, v in OPENING.items()
         if k not in ("enabled", "observe", "post_sides")}
    p["or_minutes"] = int(or_minutes)
    p["stop_pad_pct"] = float(pad)
    p["win_after_range_min"] = 60
    return p


def minute_of(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:5]) - (9 * 60 + 30)


def label_all(data: dict[str, pd.DataFrame], p: dict) -> list[dict]:
    """Every break in the window, with what happened to it and the context
    it happened in."""
    per_day: dict = {}
    for sym, df in data.items():
        days = op.by_day(df)
        for n in range(1, len(days)):
            date, day = days[n]
            _, prior = op.split_session(days[n - 1][1])
            if not len(prior):
                continue
            pre, rth = op.split_session(day)
            if len(rth) < p["or_minutes"] + 5:
                continue
            prev_close = float(prior["close"].iloc[-1])
            open_px = float(rth["open"].iloc[0])
            lv, _ = op.opening_range(rth, p["or_minutes"])
            width = ((lv["orh"] - lv["orl"]) / open_px * 100) if lv else 0.0
            base_vol = float(rth["volume"].iloc[:p["or_minutes"]].mean() or 1.0)

            for t in op.day_trades(day, prior, p):
                i = rth.index.get_indexer(
                    [pd.Timestamp(f"{date} {t['break_time']}", tz=EASTERN)])[0]
                push = (float(rth["volume"].iloc[i]) / base_vol
                        if i >= 0 and base_vol else 0.0)
                gap = (open_px - prev_close) / prev_close * 100
                t.update(symbol=sym, date=str(date),
                         minute=minute_of(t["break_time"]),
                         gap=round(gap, 2), width=round(width, 2),
                         push=round(push, 2),
                         with_gap=(gap > 0) == (t["side"] == "long"))
                per_day.setdefault(str(date), []).append(t)

    # cohort has to be computed across the whole universe for that morning,
    # which is why this is date-major rather than symbol-major
    out = []
    for date, ts in per_day.items():
        for t in ts:
            t["cohort"] = sum(
                1 for o in ts
                if o["side"] == t["side"]
                and abs(o["minute"] - t["minute"]) <= COHORT_WINDOW_MIN)
            t["alone"] = t["cohort"] == 1
            out.append(t)
    return [t for t in out if t.get("reason") != "open"]


def tally(ts: list[dict]) -> dict:
    n = len(ts)
    won = sum(1 for t in ts if t["pct"] > 0)
    pct = sum(t["pct"] for t in ts)
    return {"n": n, "won": won, "lost": n - won,
            "win_pct": round(100 * won / n, 1) if n else 0.0,
            "profit_pct": round(pct, 2),
            "avg_pct": round(pct / n, 3) if n else 0.0}


HEAD = ("| group | trades | win % | won | lost | profit % | avg/trade |"
        "\n|---|---|---|---|---|---|---|")


def row(name, t: dict) -> str:
    return (f"| {name} | {t['n']} | {t['win_pct']:.1f}% | {t['won']} | "
            f"{t['lost']} | {t['profit_pct']:+.1f}% | {t['avg_pct']:+.3f}% |")


def buckets(ts: list[dict], field: str, edges: list[float],
            fmt=lambda a, b: f"{a:g}–{b:g}") -> list[tuple[str, list[dict]]]:
    out = []
    for a, b in zip(edges, edges[1:]):
        grp = [t for t in ts if a <= t[field] < b]
        if grp:
            out.append((fmt(a, b), grp))
    return out


def separation(ts: list[dict], field: str) -> float:
    """How far apart winners and losers sit on this feature, in pooled
    standard deviations. The same yardstick the squeeze autopsy used: under
    about 0.3 is not a difference worth acting on."""
    w = np.array([t[field] for t in ts if t["pct"] > 0], dtype=float)
    l = np.array([t[field] for t in ts if t["pct"] <= 0], dtype=float)
    if len(w) < 10 or len(l) < 10:
        return 0.0
    sd = np.sqrt((w.var(ddof=1) + l.var(ddof=1)) / 2)
    return round(float(abs(w.mean() - l.mean()) / sd), 3) if sd > 0 else 0.0


def report(ts: list[dict], universe: str, or_min: int, pad: float,
           dates: list) -> str:
    cut = int(len(dates) * 2 / 3)
    explore = set(dates[:cut])
    ex = [t for t in ts if pd.Timestamp(t["date"]).date() in explore]
    ho = [t for t in ts if pd.Timestamp(t["date"]).date() not in explore]

    L = [f"# Opening range autopsy — {universe}", "",
         f"{len(ts)} breaks · {len(dates)} trading days "
         f"({dates[0]} to {dates[-1]}) · {or_min}-minute range · "
         f"+{pad:.1f}% stop room", "",
         "Every break the live rule takes, labelled at the live settings and "
         "then grouped. Nothing here is tuned; a difference between groups is "
         "a property of the market, not of a search.", "",
         "## Overall", "", HEAD, row("all breaks", tally(ts)),
         row("explore", tally(ex)), row("holdout", tally(ho)), ""]

    L += ["## How many names broke together", "",
          f"Same side, within {COHORT_WINDOW_MIN} minutes. This is the "
          "29 September question: is a break the whole sector is making at "
          "once worth less than one a single name is making alone?", "", HEAD]
    for lab, grp in buckets(ts, "cohort", [1, 2, 3, 5, 8, 99],
                            lambda a, b: (f"{a:g} name" if b == a + 1
                                          else f"{a:g}–{b - 1:g} names")):
        L.append(row(lab, tally(grp)))
    L += ["", HEAD,
          row("alone (cohort 1)", tally([t for t in ts if t["alone"]])),
          row("with the crowd", tally([t for t in ts if not t["alone"]])), ""]

    L += ["## When the break came", "", HEAD]
    for lab, grp in buckets(ts, "minute", [0, 5, 10, 20, 30, 45, 90],
                            lambda a, b: f"{a:g}–{b:g} min after the bell"):
        L.append(row(lab, tally(grp)))

    L += ["", "## Direction", "", HEAD]
    for side in ("long", "short"):
        L.append(row(side, tally([t for t in ts if t["side"] == side])))
    L += ["", HEAD,
          row("with the gap", tally([t for t in ts if t["with_gap"]])),
          row("against the gap", tally([t for t in ts if not t["with_gap"]]))]

    L += ["", "## Overnight gap", "", HEAD]
    for lab, grp in buckets(ts, "gap", [-99, -2, -0.5, 0.5, 2, 99],
                            lambda a, b: f"{a:g}% to {b:g}%"):
        L.append(row(lab, tally(grp)))

    L += ["", "## How wide the range was", "", HEAD]
    for lab, grp in buckets(ts, "width", [0, 0.3, 0.6, 1.0, 2.0, 99],
                            lambda a, b: f"{a:g}%–{b:g}% of price"):
        L.append(row(lab, tally(grp)))

    L += ["", "## Volume behind the break", "", HEAD]
    for lab, grp in buckets(ts, "push", [0, 0.8, 1.2, 2.0, 4.0, 999],
                            lambda a, b: f"{a:g}x–{b:g}x the range average"):
        L.append(row(lab, tally(grp)))

    L += ["", "## Which feature separates winners from losers at all", "",
          "Pooled standard deviations between the winning and losing groups. "
          "Under about 0.3 is noise — that threshold has already retired two "
          "feature searches in this project.", "",
          "| feature | separation |", "|---|---|"]
    seps = {f: separation(ts, f)
            for f in ("cohort", "minute", "gap", "width", "push")}
    for f, v in sorted(seps.items(), key=lambda kv: -kv[1]):
        L.append(f"| {f} | {v:.3f} |")
    best = max(seps.values()) if seps else 0.0
    L += ["", "## Verdict", ""]
    if best < 0.3:
        L.append(f"- **Nothing separates them.** The strongest feature is "
                 f"{max(seps, key=seps.get)} at {best:.3f} standard "
                 f"deviations, well inside noise. The losing trades are not "
                 f"distinguishable from the winning ones by anything measured "
                 f"here, which means no filter built from these features will "
                 f"help — including the cohort idea.")
    else:
        L.append(f"- **{max(seps, key=seps.get)}** separates winners from "
                 f"losers by {best:.3f} standard deviations. That is worth "
                 f"testing as a filter, on the holdout, before anything else.")
    if tally(ho)["profit_pct"] > 0:
        L.append("- The holdout is profitable at these settings.")
    else:
        L.append(f"- The holdout loses {tally(ho)['profit_pct']:+.1f}%, so any "
                 f"filter has to do more than shuffle which losses are taken.")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--universe", default="bigtech")
    ap.add_argument("--or-minutes", type=int, default=15)
    ap.add_argument("--pad", type=float, default=2.0)
    args = ap.parse_args(argv)

    symbols = UNIVERSES.get(args.universe) or BIGTECH
    try:
        md = MarketData(Credentials.from_env(), feed="iex")
        data = op.fetch(md, symbols, args.days)
    except AlpacaError as exc:
        log.error("Fetch failed: %s", exc)
        return 1
    if not data:
        log.error("No usable data.")
        return 1

    p = cfg(args.or_minutes, args.pad)
    ts = label_all(data, p)
    log.info("%d labelled breaks", len(ts))
    if not ts:
        log.error("No breaks to analyse.")
        return 1
    dates = sorted({d for df in data.values()
                    for d in df.index.tz_convert(EASTERN).date})
    out = report(ts, args.universe, args.or_minutes, args.pad, dates)

    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "orb_autopsy.md").write_text(out)
    (REPORTS / "orb_autopsy.json").write_text(json.dumps(
        {"n": len(ts), "or_minutes": args.or_minutes, "pad": args.pad,
         "separation": {f: separation(ts, f)
                        for f in ("cohort", "minute", "gap", "width", "push")}},
        indent=2, default=str))
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
