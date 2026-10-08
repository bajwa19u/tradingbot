"""The day-trade channel's strategy, replayed over the last N sessions, for
the Trading Bot Desk page.

Follows the live switch (repo variable DAYTRADE_STRATEGY, via
`orb_live.RULES`): the desk must describe the rule the channel is actually
running. Until 8 Oct 2026 this file hard-coded the in-play rule, so after the
switch to the big tech list on 5 Oct the desk kept showing the old rule.

Same rules and code path as the live feed: `orb_research.select` picks the
day's ten names, `first_signal` finds the entry, `exit_r` manages it, with
`orb_paper.CANDIDATE` as the parameters. Every pick is listed, including the
ones that never traded and why. Results are per trade as a share of the
account at the live sizing (a full stop costs 1%), after 0.05% slippage a side.

Usage: python -m src.orb_month [--sessions 21]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

from . import orb_research as orr
from .config import REPO_ROOT
from .orb_live import RULES
from .orb_paper import CANDIDATE, bar_label

OUT = REPO_ROOT / "reports" / "orb_month.json"


def day_rows(D: dict, d, p: orr.P = CANDIDATE) -> tuple[list[dict], list[dict]]:
    """(picks with what happened to each, trades) for one session."""
    spy, qqq = D["SPY"][d], D["QQQ"][d]
    sa, qa = spy.c > spy.vwap, qqq.c > qqq.vwap
    picks, trades = [], []
    for rank, s in enumerate(orr.select(D, d, p.universe), 1):
        x = D[s][d]
        ratio = x.or_w / x.atr if x.atr > 0 else 0.0
        pick = {"symbol": s, "rank": rank, "rvol5": round(float(x.rvol5), 2), "or_width_atr": round(ratio, 2),
                "gap_pct": round(float(x.gap) * 100, 2) if x.gap == x.gap else None}
        sig = orr.first_signal(x, sa, qa, p, orr.FLAT_IDX - 1, spy)
        if sig is None:
            pick["outcome"] = ("range too narrow" if ratio < p.orw[0] else "no breakout before 09:45")
            picks.append(pick)
            continue
        R, j, why = orr.exit_r(x, sig["kk"], sig["sign"], sig["entry"], sig["stop"], p)
        rps = abs(sig["entry"] - sig["stop"])
        exit_px = sig["stop"] if why == "stop" else sig["target"] if why == "target" else float(x.c[j])
        t = {"date": str(d), "symbol": s, "side": sig["side"], "rank": rank,
             "entry_time": bar_label(sig["k"]), "exit_time": bar_label(j), "exit_reason": why,
             "entry": round(sig["entry"], 2), "stop": round(sig["stop"], 2), "target": round(sig["target"], 2),
             "exit": round(exit_px, 2), "result_pct": round(float(R), 3),
             "move_pct": round(float(R) * rps / sig["entry"] * 100, 2),
             "risk_pct_price": round(rps / sig["entry"] * 100, 2),
             "rvol5": pick["rvol5"], "or_width_atr": pick["or_width_atr"], "gap_pct": pick["gap_pct"],
             "hold_min": int(j - sig["kk"])}
        pick["outcome"] = "traded"
        picks.append(pick)
        trades.append(t)
    return picks, trades


RULE_TEXT = {
    "top10": "Top 10 by first-5-minute volume vs normal (of ~105 liquid names)",
    "bigtech": "Fixed list: " + " ".join(orr.BIG_TECH),
}


def live_rule() -> tuple[str, orr.P, str]:
    """(switch value, parameters, setup name) of the rule the channel runs."""
    # Read exactly as live_bot does: the repo variable is "bigtech\r\n\n".
    key = (os.environ.get("DAYTRADE_STRATEGY") or "inplay_orb").strip().lower()
    if key not in RULES:            # e.g. "classic": not an ORB rule; show the in-play one
        key = "inplay_orb"
    p, name = RULES[key]
    return key, p, name


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions", type=int, default=21)
    args = ap.parse_args(argv)
    key, p, name = live_rule()
    D, common = orr.build(orr.load(max(60, args.sessions), False))
    dates = common[-args.sessions:]
    days, trades = [], []
    for d in dates:
        picks, ts = day_rows(D, d, p)
        r = [t["result_pct"] for t in ts]
        days.append({"date": str(d), "picks": picks, "trades": len(ts), "won": sum(x > 0 for x in r),
                     "result_pct": round(float(np.sum(r)), 3) if r else 0.0})
        trades += ts
    out = {"strategy": name, "switch": key,
           "rules": RULE_TEXT.get(p.universe, p.universe) + ", opening range "
                    "09:30-09:34 at least 0.35 of daily ATR, first 1-minute close outside it before 09:45, "
                    "stop at the session extreme (moved to entry at +1x risk), target 2x risk, out by 15:55. 0.05% slippage a side.",
           "sizing": "Results are % of the account with a full stop costing 1%.",
           "from": str(dates[0]), "to": str(dates[-1]), "days": days, "trades": trades}
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1))
    w = sum(t["result_pct"] > 0 for t in trades)
    print(f"{len(dates)} sessions {dates[0]}..{dates[-1]}: {len(trades)} trades, {w} won, "
          f"total {sum(t['result_pct'] for t in trades):+.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
