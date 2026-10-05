"""The day-trade rule on the owner's big tech list, before it goes live.

Same rule as the in-play version (range filter, entries by 09:44, stop to
entry at +1x risk, 2x target, out at 15:55) but trading the same six names
every day. Compared with the old big-tech rule and with the in-play version,
on the last 63 sessions and on the 189 before them, so a result that only
holds recently shows up as such. Results: % of account per trade at 1% risk.

Usage: python -m src.orb_bigtech
"""
from __future__ import annotations

import json
import sys
from dataclasses import replace

import pandas as pd

from . import orb_research as orr
from .config import REPO_ROOT
from .orb_improve import st, summary
from .orb_paper import CANDIDATE

REPORT = REPO_ROOT / "reports" / "orb_bigtech.md"
VARIANTS = {
    "old big-tech rule (retired)": replace(orr.P(), universe="bigtech"),
    "current rule on big tech": replace(CANDIDATE, universe="bigtech"),
    "current rule on big tech, no range filter": replace(CANDIDATE, universe="bigtech", orw=(0.0, 9e9)),
    "current rule on big tech, entries to 10:00": replace(CANDIDATE, universe="bigtech", window_end=30),
    "in-play version (for reference)": CANDIDATE,
}


def main(argv=None) -> int:
    D, common = orr.build(orr.load(260, False))
    dates = common[-252:]
    lab = {d: "x" for d in dates}
    rec, ear = [str(d) for d in dates[-63:]], [str(d) for d in dates[:-63]]
    runs = {}
    for nm, p in VARIANTS.items():
        t = orr.trades(D, dates, lab, p)
        t["date"] = t.date.astype(str)
        t2 = orr.trades(D, dates, lab, replace(p, slip=0.001))
        t2["date"] = t2.date.astype(str)
        runs[nm] = (t.sort_values(["date", "k"]), t2)
    f = lambda v, d=3: "-" if v != v else f"{v:+.{d}f}%"
    L = ["# Day trades on big tech: " + ", ".join(orr.BIG_TECH), "",
         f"Recent: {rec[0]} to {rec[-1]} (63 sessions). Earlier: {ear[0]} to {ear[-1]} (189 sessions).", "",
         "## Both date ranges", "",
         "| version | recent trades | win % | avg | PF | total | earlier trades | win % | avg | PF | total | recent avg @0.10% | earlier avg @0.10% |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for nm, (t, t2) in runs.items():
        a, e = st(t.R[t.date.isin(rec)]), st(t.R[t.date.isin(ear)])
        a2, e2 = st(t2.R[t2.date.isin(rec)]), st(t2.R[t2.date.isin(ear)])
        L.append(f"| {nm} | {a['n']} | {a['win']:.0f}% | {f(a['avg'])} | {a['pf']:.2f} | {a['tot']:+.1f}% | {e['n']} | {e['win']:.0f}% | "
                 f"{f(e['avg'])} | {e['pf']:.2f} | {e['tot']:+.1f}% | {f(a2['avg'])} | {f(e2['avg'])} |")
    comp = {}
    for w, n in (("week", 5), ("month", 21), ("3 months", 63)):
        ds = [str(d) for d in dates[-n:]]
        comp[w] = {nm: summary(t[t.date.isin(ds)], ds) for nm, (t, _) in runs.items()}
        L += ["", f"## {w}", "", "| version | trades | win % | avg | total | PF | max DD | green days | best | worst |", "|---|---|---|---|---|---|---|---|---|---|"]
        for nm, s in comp[w].items():
            if not s.get("trades"):
                L.append(f"| {nm} | 0 | | | | | | | | |"); continue
            L.append(f"| {nm} | {s['trades']} | {s['win']:.0f}% | {f(s['avg'])} | {s['total']:+.2f}% | {s['pf']:.2f} | {s['dd']:.2f}% | "
                     f"{s['green']}/{s['sessions']} | {s['best']:+.2f}% | {s['worst']:+.2f}% |")
    t = runs["current rule on big tech"][0]
    L += ["", "## Current rule on big tech, by ticker (both ranges)", "", "| ticker | recent trades | recent total | earlier trades | earlier total |", "|---|---|---|---|---|"]
    for s_ in orr.BIG_TECH:
        a, e = t[(t.sym == s_) & t.date.isin(rec)], t[(t.sym == s_) & t.date.isin(ear)]
        L.append(f"| {s_} | {len(a)} | {a.R.sum():+.2f}% | {len(e)} | {e.R.sum():+.2f}% |")
    out = "\n".join(L) + "\n"
    REPORT.write_text(out)
    REPORT.with_suffix(".json").write_text(json.dumps(comp, indent=1, default=float))
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
