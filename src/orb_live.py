"""ORB on stocks in play - the day-trade channel's candidate rule, live.

Selected by `live_bot.STRATEGY = "inplay_orb"`. The classic opening rule on
the fixed ten megacaps stays in live_bot untouched behind the same switch.

The rules are the research's, by reference: `orb_research.first_signal` finds
the entry and `orb_research.exit_r` manages it, with `orb_paper.CANDIDATE` as
the only parameter set. Nothing here re-implements a rule, so the live feed,
the paper record and the backtest cannot disagree about what a signal is.

  universe   the 10 names (of ~105 liquid ones, price >= 5, 14-day average
             dollar volume >= 50M) with the highest first-5-minute volume
             against their own 14-session average, ranked once at 09:35
  range      09:30-09:34 one-minute high and low
  filter     range at least 0.35 of the 14-day average daily true range
  entry      first completed 1-minute close outside the range, bars 09:35-09:59;
             one trade per stock per day; both directions
  stop       the session low (long) / high (short) so far, 0.02 ATR beyond it
  target     2x the risk; otherwise out at the 15:55 bar's close
  costs      researched at 0.05% slippage per side

Speed: the wide history is fetched once before the bell; after that each tick
asks only for today's bars of the ten picks plus SPY and QQQ (one request).
"""
from __future__ import annotations

import json
import logging

import numpy as np
import pandas as pd

from . import orb_research as orr
from .config import REPO_ROOT
from .orb_paper import CANDIDATE, Feed, bar_label

log = logging.getLogger("orb_live")

RULE = CANDIDATE
PICKS_FILE = REPO_ROOT / "state" / "orb_live_picks.json"
SETUP_NAME = "ORB · Stocks in Play"
_FEED: Feed | None = None


def feed(md_factory) -> Feed:
    global _FEED
    if _FEED is None:
        _FEED = Feed(md_factory(), RULE)
    return _FEED


def warm(now: pd.Timestamp, md_factory) -> None:
    """Fetch the wide history before the bell so 09:35 costs one request."""
    feed(md_factory).history(now.date(), orr.POOL)


def completed_minutes(now: pd.Timestamp) -> int:
    """Regular-session one-minute bars that have closed by `now` (0-390)."""
    open_ts = now.normalize() + pd.Timedelta(hours=9, minutes=30)
    return int(max(0, min(orr.N_MIN, (now - open_ts).total_seconds() // 60)))


def picks(f: Feed, now: pd.Timestamp, dry_run: bool) -> list[tuple[str, float]]:
    """Today's ten names and their opening relative volume. Chosen once, from
    the first five minutes only, and kept for the day (a later job reads the
    file rather than re-ranking on bars that may since have been revised)."""
    today = str(now.date())
    try:
        saved = json.loads(PICKS_FILE.read_text())
        if saved.get("date") == today:
            return [tuple(x) for x in saved["picks"]]
    except (OSError, json.JSONDecodeError, KeyError):
        pass
    f.history(now.date(), orr.POOL)
    D = f.today_days(orr.POOL, now, 5)
    chosen = orr.select({s: {now.date(): x} for s, x in D.items()}, now.date(), RULE.universe)
    out = [(s, round(float(D[s].rvol5), 2)) for s in chosen]
    if out and not dry_run:
        PICKS_FILE.parent.mkdir(exist_ok=True)
        PICKS_FILE.write_text(json.dumps({"date": today, "at": now.strftime("%H:%M:%S"), "picks": out}))
    log.info("In play today: %s", out)
    return out


def scan(now: pd.Timestamp, md_factory, risk_pct: float, dry_run: bool = False
         ) -> tuple[list[dict], pd.Timestamp | None]:
    """Every trade the rule has taken today, open or closed, and the newest bar seen."""
    k_end = completed_minutes(now)
    if k_end < 6:                                    # range forms 09:30-09:34; first entry bar is 09:35
        return [], None
    f = feed(md_factory)
    chosen = picks(f, now, dry_run)
    if not chosen:
        return [], f.newest
    syms = [s for s, _ in chosen]
    f.history(now.date(), syms + ["SPY", "QQQ"])
    D = f.today_days(syms + ["SPY", "QQQ"], now, k_end)
    if "SPY" not in D or "QQQ" not in D:
        return [], f.newest
    sa, qa = D["SPY"].c > D["SPY"].vwap, D["QQQ"].c > D["QQQ"].vwap
    rank = {s: (i + 1, r) for i, (s, r) in enumerate(chosen)}
    out = []
    for s in syms:
        x = D.get(s)
        if x is None:
            continue
        sig = orr.first_signal(x, sa, qa, RULE, k_end, D["SPY"])
        if sig is None:
            continue
        R, j, why = orr.exit_r(x, sig["kk"], sig["sign"], sig["entry"], sig["stop"], RULE, j_end=k_end)
        rps = abs(sig["entry"] - sig["stop"])
        live = why == "open"
        exit_px = None
        if not live:
            exit_px = (sig["stop"] if why == "stop" else sig["target"] if why == "target" else float(x.c[j]))
        out.append({
            "id": f"ORB-{s}-{now.date()}", "rule": "inplay_orb", "symbol": s, "side": sig["side"],
            "entry_time": bar_label(sig["k"]), "minute": sig["k"],
            "entry": round(sig["entry"], 2), "stop": round(sig["stop"], 2), "target": round(sig["target"], 2),
            "rr": RULE.target, "level": round(sig["level"], 2), "level_name": "orh" if sig["sign"] > 0 else "orl",
            "rank": rank[s][0], "rvol5": rank[s][1], "or_width_atr": round(sig["orw"], 2),
            "breakout_rvol": round(float(sig["bvol"]), 1), "gap": round(float(x.gap) * 100, 2) if x.gap == x.gap else None,
            "vwap_ok": bool(sig["vwap_ok"]), "spy_ok": bool(sig["spy_ok"]),
            "risk_pct_price": round(rps / sig["entry"] * 100, 2),
            "exit": None if live else round(exit_px, 2),
            "exit_time": None if live else bar_label(j), "reason": None if live else why,
            "pct": None if live or not np.isfinite(R) else round(float(R) * risk_pct, 2),
            "post": True})
    out.sort(key=lambda t: (t["minute"], t["symbol"]))
    return out, f.newest


def features_line(t: dict) -> str:
    """The setup, in one line: why this name, how big the range, which way it gapped."""
    bits = [f"#{t['rank']} in play · opening volume {t['rvol5']:.1f}x normal",
            f"range {t['or_width_atr']:.2f} of daily ATR"]
    if t.get("gap") is not None:
        bits.append(f"gap {t['gap']:+.1f}%")
    bits.append(f"break-minute volume {t['breakout_rvol']:.1f}x")
    return " · ".join(bits)
