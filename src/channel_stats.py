"""What each day-trade Discord channel's rule would have done over the last
week, month and three months (5, 21 and 63 sessions).

  day-trade channel, current rule   in-play ORB (live_bot STRATEGY=inplay_orb)
  day-trade channel, previous rule  opening-range break on the fixed 10 (research version)
  in-play channel                   inplay_bot.RULE: top 5 by opening volume, stop 0.5 x daily
                                    ATR, no target, out at the stop or 15:55

Each result is one trade as a share of the account at the live sizing (a full
stop costs about 1%). Same IEX minute bars as every other study here.

Usage: python -m src.channel_stats
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

from . import inplay as ip
from . import orb_research as orr
from .config import REPO_ROOT
from .inplay_bot import RULE as INPLAY_RULE
from .orb_month import day_rows

OUT = REPO_ROOT / "reports" / "channel_stats.json"
TRADES = REPO_ROOT / "reports" / "channel_trades.json"     # every trade, for the full report
WINDOWS = {"week": 5, "month": 21, "3 months": 63}


def summarize(trades: list[dict], dates: list) -> dict:
    """trades: dicts with date (str) and pct (account %), in time order."""
    r = np.array([t["pct"] for t in trades], float)
    if not len(r):
        return {"sessions": len(dates), "trades": 0}
    by_day = pd.Series(r).groupby([t["date"] for t in trades]).sum()
    eq = np.cumsum(r)
    dd = float((np.maximum.accumulate(np.concatenate([[0], eq]))[1:] - eq).max())
    w, l = r[r > 0], r[r <= 0]
    return {"sessions": len(dates), "trades": int(len(r)), "won": int(len(w)), "lost": int(len(l)),
            "win_pct": round(100 * len(w) / len(r), 1), "avg_pct": round(float(r.mean()), 3),
            "total_pct": round(float(r.sum()), 2), "best_pct": round(float(r.max()), 2),
            "worst_pct": round(float(r.min()), 2),
            "profit_factor": round(float(w.sum() / -l.sum()), 2) if l.sum() < 0 else None,
            "green_days": int((by_day > 0).sum()), "days_traded": int(len(by_day)),
            "max_drawdown_pct": round(dd, 2)}


def main(argv=None) -> int:
    data = orr.load(70, False)
    D, common = orr.build(data)
    dates = common[-max(WINDOWS.values()):]
    lab = {d: "test" for d in dates}

    # day-trade channel, current rule
    cur, picks = [], {}
    for d in dates:
        pk, ts = day_rows(D, d)
        picks[str(d)] = pk
        cur += [{**t, "pct": t["result_pct"]} for t in ts]
    # day-trade channel, previous rule
    prev = orr.trades(D, dates, lab, orr.P())
    prev = [{"date": str(r.date), "pct": float(r.R), "symbol": r.sym} for r in prev.sort_values(["date", "k"]).itertuples()]
    # in-play channel
    wide = {s: df for s, df in data.items() if s in ip.UNIVERSES["wide"]}
    dailies = ip.build(wide)
    inp = ip.run(wide, dailies, INPLAY_RULE, set(dates))
    inp = sorted(({"date": t["date"], "pct": float(t["pct"]), "symbol": t["symbol"], "t": t["entry_time"],
                   "side": t["side"], "entry_time": t["entry_time"], "exit_time": t["exit_time"], "exit_reason": t["reason"],
                   "entry": t["entry"], "stop": t["stop"], "exit": t["exit"], "rvol5": t.get("rvol")} for t in inp),
                 key=lambda t: (t["date"], t["t"]))

    out = {"last_session": str(dates[-1]), "windows": {}}
    for name, n in WINDOWS.items():
        ds = [str(d) for d in dates[-n:]]
        keep = lambda ts: [t for t in ts if t["date"] in set(ds)]
        out["windows"][name] = {"from": ds[0], "to": ds[-1],
                                "day_trade_current": summarize(keep(cur), ds),
                                "day_trade_previous": summarize(keep(prev), ds),
                                "inplay": summarize(keep(inp), ds)}
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1))
    TRADES.write_text(json.dumps({"sessions": [str(d) for d in dates], "day_trade": cur, "day_trade_picks": picks,
                                  "inplay": inp, "old_rule": prev}, default=float))
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
