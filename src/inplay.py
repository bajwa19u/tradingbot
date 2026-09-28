"""Stocks in play — testing the part of the published work we left out.

Why this module exists
----------------------
Our opening-range rule lost money out of sample and the obvious objection is
that other people trade this for a living. The published research answers
that objection directly, and it agrees with our result.

Zarattini, Barbon and Aziz tested a five-minute opening-range breakout across
7,000+ US equities, 2016-2023. Applied broadly it returned 29% against 198%
for simply holding the S&P. Their words: a simple five-minute ORB applied
broadly across liquid US stocks was not enough. Restricted to the twenty
stocks with the most abnormal opening volume each day, the same rule returned
1,637%. The paper is explicit that most of the apparent edge came from the
selection rather than from the breakout rule.

So the thing we were missing is not a better entry. It is that we never chose
what to trade. We scan the same twelve megacaps every morning whether or not
anything is happening in them, which is the unfiltered version - the one the
research says does not work.

Three differences from what we built, all taken from the papers:

  1. SELECTION. Rank the universe each morning by relative volume - today's
     first five minutes against the average first five minutes over the prior
     fourteen sessions - and trade only the top names. This is the part the
     research says carries the edge.
  2. NO PROFIT TARGET. Exit at the close, or at the stop. Our 2R target and
     two-hour cap turned AMD's 28 September collapse into +1.97% while the
     stock went on to fall five percent. A rule with a low win rate only
     survives if the winners are allowed to be large.
  3. STOP FROM DAILY ATR, as a fraction of the 14-day average true range,
     rather than from a one-minute range estimate.

What the papers do NOT establish, and why this is still a test and not a
plan: they report no clean out-of-sample period after the parameters were
fixed, they model no slippage, they assume four times leverage and that
shorts can always be located. Any of those can account for a large result on
its own. So this module keeps the same discipline as everything else here -
an explore split, a holdout of dates never seen, slippage charged on both
ends, and no leverage.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from itertools import product
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .config import REPO_ROOT, Credentials
from .data import AlpacaError, MarketData
from .forensics import UNIVERSES
from . import opening as op

EASTERN = ZoneInfo("America/New_York")
REPORTS = REPO_ROOT / "reports"
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("inplay")

RVOL_LOOKBACK = 14        # sessions, as in the paper
OR_MINUTES = 5
MIN_PRICE = 5.0           # the paper's liquidity floor
MIN_ATR = 0.50

BASE = {**op.BASE,
        "levels": "or", "or_minutes": OR_MINUTES, "entry_mode": "drive",
        "side": "both", "max_per_symbol": 1, "pen": 0.0,
        "exit_mode": "close",     # close | target
        "stop_mode": "atr",       # atr | session | level
        "atr_frac": 0.10,         # of the 14-day ATR, as in the paper
        "select_top": 20,
        "risk_pct": 1.0}


# --- daily summaries, built from the minute data we already have -------------
def daily_frame(df: pd.DataFrame) -> pd.DataFrame:
    """One row per session: high, low, close, and the first five minutes'
    volume. Everything selection needs, and nothing that needs a second fetch."""
    rows = []
    for date, day in op.by_day(df):
        _, rth = op.split_session(day)
        if len(rth) < OR_MINUTES + 1:
            continue
        rows.append({"date": date,
                     "high": float(rth["high"].max()),
                     "low": float(rth["low"].min()),
                     "close": float(rth["close"].iloc[-1]),
                     "open": float(rth["open"].iloc[0]),
                     "first5": float(rth["volume"].iloc[:OR_MINUTES].sum())})
    return pd.DataFrame(rows).set_index("date") if rows else pd.DataFrame()


def atr14(daily: pd.DataFrame, upto: int) -> float:
    """14-day average true range using only sessions BEFORE `upto`.

    Including the session being traded would be reading the day's own range
    before it has happened, which is the quietest way to fake a good stop.
    """
    if upto < 2:
        return 0.0
    d = daily.iloc[max(0, upto - 14):upto]
    if len(d) < 2:
        return 0.0
    prev = d["close"].shift(1)
    tr = pd.concat([d["high"] - d["low"],
                    (d["high"] - prev).abs(),
                    (d["low"] - prev).abs()], axis=1).max(axis=1)
    return float(tr.dropna().mean() or 0.0)


def relative_volume(daily: pd.DataFrame, i: int,
                    lookback: int = RVOL_LOOKBACK) -> float:
    """Today's first five minutes against its own recent normal.

    A ratio rather than a level, which matters on this data feed: IEX is a
    small slice of consolidated volume, but the slice is reasonably stable,
    so the RATIO survives even though the raw number is not the real volume.
    """
    if i < 3:
        return 0.0
    past = daily["first5"].iloc[max(0, i - lookback):i]
    past = past[past > 0]
    if len(past) < 3:
        return 0.0
    base = float(past.mean())
    return float(daily["first5"].iloc[i] / base) if base > 0 else 0.0


def build(data: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    out = {}
    for sym, df in data.items():
        d = daily_frame(df)
        if len(d) >= RVOL_LOOKBACK + 5:
            out[sym] = d
    return out


def in_play(dailies: dict[str, pd.DataFrame], date, top: int,
            ) -> list[tuple[str, float]]:
    """The names most in play this morning, decided from the first five
    minutes alone — so the pick is known at 09:35 and the trade is taken
    after it."""
    scored = []
    for sym, d in dailies.items():
        if date not in d.index:
            continue
        i = d.index.get_loc(date)
        if isinstance(i, slice) or i < RVOL_LOOKBACK:
            continue
        if float(d["open"].iloc[i]) < MIN_PRICE or atr14(d, i) < MIN_ATR:
            continue
        r = relative_volume(d, i)
        if r > 0:
            scored.append((sym, r))
    scored.sort(key=lambda t: -t[1])
    return scored[:top] if top else scored


# --- the trade ---------------------------------------------------------------
def trade_day(rth: pd.DataFrame, atr: float, p: dict) -> list[dict]:
    """Opening-range break, stop from daily ATR, out at the close."""
    lv, ready = op.opening_range(rth, p.get("or_minutes", OR_MINUTES))
    if not lv or atr <= 0:
        return []
    scale = atr * p.get("atr_frac", 0.10)
    if scale <= 0:
        return []
    out = []
    for i, side, level, name in op.opening_breaks(
            rth, lv, scale, p, {k: ready for k in lv}):
        if len(out) >= p.get("max_per_symbol", 1):
            break
        j = op.entry_index(rth, i, side, level, scale, p)
        if j is None:
            continue
        t = simulate(rth, j, side, atr, p)
        if t is None:
            continue
        t.update(level=round(level, 4), level_name=name,
                 break_time=str(rth.index[i].tz_convert(EASTERN))[11:16])
        out.append(t)
    return out


def simulate(rth: pd.DataFrame, j: int, side: str, atr: float,
             p: dict) -> dict | None:
    """Stop is a fraction of the daily ATR from entry. No profit target
    unless one is asked for; otherwise the position runs to the bell."""
    slip = op.SLIP_PCT / 100.0
    raw = float(rth["close"].iloc[j])
    entry = raw * (1 - slip) if side == "short" else raw * (1 + slip)
    rps = atr * p.get("atr_frac", 0.10)
    if rps <= 0 or rps / entry > 0.10:
        return None
    stop = entry + rps if side == "short" else entry - rps
    target = None
    if p.get("exit_mode") == "target":
        target = (entry - p["target_r"] * rps if side == "short"
                  else entry + p["target_r"] * rps)

    times = rth.index.tz_convert(EASTERN)
    flat = pd.Timestamp(op.FORCE_EXIT).time()
    px, why, k_out = None, None, len(rth) - 1
    for k in range(j + 1, len(rth)):
        b = rth.iloc[k]
        hi, lo = float(b["high"]), float(b["low"])
        k_out = k
        if (hi >= stop if side == "short" else lo <= stop):
            px, why = stop, "stop"
        elif target is not None and (lo <= target if side == "short"
                                     else hi >= target):
            px, why = target, "target"
        elif times[k].time() >= flat:
            px, why = float(b["close"]), "close"
        if px is not None:
            break
    if px is None:
        px, why = float(rth["close"].iloc[-1]), "close"

    exit_px = px * (1 + slip) if side == "short" else px * (1 - slip)
    gain = (entry - exit_px) if side == "short" else (exit_px - entry)
    r = gain / rps
    return {"side": side, "entry": round(entry, 4), "stop": round(stop, 4),
            "exit": round(exit_px, 4), "reason": why, "r": round(float(r), 4),
            "pct": round(float(r) * p["risk_pct"], 4),
            "entry_time": str(times[j])[11:16],
            "exit_time": str(times[k_out])[11:16], "rps": round(rps, 4)}


def run(data: dict[str, pd.DataFrame], dailies: dict[str, pd.DataFrame],
        p: dict, dates: set) -> list[dict]:
    """Date-major, because selection is a decision made once per morning
    across the whole universe — not per symbol."""
    per_symbol_days = {s: dict(op.by_day(df)) for s, df in data.items()}
    trades = []
    for date in sorted(dates):
        picks = in_play(dailies, date, p.get("select_top", 0))
        for sym, rvol in picks:
            day = per_symbol_days.get(sym, {}).get(date)
            if day is None:
                continue
            _, rth = op.split_session(day)
            if len(rth) < OR_MINUTES + 5:
                continue
            d = dailies[sym]
            atr = atr14(d, d.index.get_loc(date))
            for t in trade_day(rth, atr, p):
                t.update(symbol=sym, date=str(date), rvol=round(rvol, 2))
                trades.append(t)
    return trades


# --- report ------------------------------------------------------------------
def tally(trades: list[dict], p: dict) -> dict:
    n = len(trades)
    won = sum(1 for t in trades if t["pct"] > 0)
    pct = sum(t["pct"] for t in trades)
    return {"n": n, "won": won, "lost": n - won,
            "win_pct": round(100 * won / n, 1) if n else 0.0,
            "profit_pct": round(pct, 2),
            "avg_pct": round(pct / n, 3) if n else 0.0,
            "best": round(max((t["pct"] for t in trades), default=0.0), 2),
            "worst": round(min((t["pct"] for t in trades), default=0.0), 2),
            "trades": trades}


HEAD = ("| rule | trades | win % | won | lost | profit % | avg/trade |\n"
        "|---|---|---|---|---|---|---|")


def row(name: str, t: dict) -> str:
    return (f"| {name} | {t['n']} | {t['win_pct']:.1f}% | {t['won']} | "
            f"{t['lost']} | {t['profit_pct']:+.1f}% | {t['avg_pct']:+.3f}% |")


def grid() -> list[dict]:
    """Small and pre-specified. The claim under test is that SELECTION is
    what matters, so the dimension that has to vary is how many names are
    traded — including the unfiltered case the research says fails."""
    out = []
    for top, frac, side in product((0, 20, 10, 5), (0.05, 0.10, 0.20),
                                   ("both", "short")):
        out.append({**BASE, "select_top": top, "atr_frac": frac, "side": side,
                    "name": f"top{top or 'ALL'}/atr{frac}/{side}"})
    return out


def research(data, dailies, universe: str) -> str:
    all_dates = sorted({d for x in dailies.values() for d in x.index})
    all_dates = all_dates[RVOL_LOOKBACK:]          # need history to rank
    if len(all_dates) < 20:
        return f"Only {len(all_dates)} usable days — not enough to split.\n"
    cut = int(len(all_dates) * 2 / 3)
    explore, holdout = set(all_dates[:cut]), set(all_dates[cut:])
    log.info("Explore %d days, holdout %d days", len(explore), len(holdout))

    combos = grid()
    results = []
    for c in combos:
        r = tally(run(data, dailies, c, explore), c)
        r["name"], r["cfg"] = c["name"], {k: v for k, v in c.items() if k != "name"}
        results.append(r)
        log.info("%-24s n=%-5d win=%.1f%% profit=%+.1f%%",
                 c["name"], r["n"], r["win_pct"], r["profit_pct"])

    sized = [r for r in results if r["n"] >= 30]
    if not sized:
        return "No configuration produced 30+ trades in the explore split.\n"
    best = max(sized, key=lambda r: r["profit_pct"])
    conf = tally(run(data, dailies, best["cfg"], holdout), best["cfg"])
    unfiltered = next((r for r in results
                       if r["cfg"]["select_top"] == 0
                       and r["cfg"]["atr_frac"] == best["cfg"]["atr_frac"]
                       and r["cfg"]["side"] == best["cfg"]["side"]), None)

    L = [f"# Stocks in play — {universe}", "",
         f"1-minute bars · {len(all_dates)} trading days "
         f"({all_dates[0]} to {all_dates[-1]}) · {len(dailies)} symbols ranked",
         "",
         "Opening-range break on the names with the most abnormal opening "
         "volume. No profit target — out at the stop or at the bell. Stop is "
         "a fraction of the 14-day ATR. Slippage "
         f"{op.SLIP_PCT}% each way, no leverage.", "",
         "## Does choosing what to trade change anything?", "", HEAD]
    for r in sorted(results, key=lambda r: -r["profit_pct"]):
        L.append(row(r["name"], r))

    L += ["", "## The best one, then the same rule on dates it never saw", "",
          f"**{best['name']}**", "", HEAD,
          row("explore", best), row("holdout (unseen)", conf), ""]
    if unfiltered:
        L += ["Against the same rule with NO selection, on the explore split:",
              "", HEAD, row(unfiltered["name"], unfiltered),
              row(best["name"], best), ""]

    verdict = []
    if conf["n"] < 20:
        verdict.append(f"Only {conf['n']} holdout trades — too few to conclude.")
    if conf["profit_pct"] <= 0:
        verdict.append("**Loses money on unseen dates.** Selection did not "
                       "rescue it, and that is now three independent rules "
                       "that failed the same way. Do not deploy it.")
    elif unfiltered and unfiltered["profit_pct"] >= best["profit_pct"]:
        verdict.append("Selection did not beat trading everything, which is "
                       "the opposite of what the research reports.")
    else:
        verdict.append("**Holds up on dates it never saw.** First time in "
                       "this project. It still needs a forward record before "
                       "it sizes a position.")
    L += ["## Verdict", ""] + [f"- {v}" for v in verdict] + ["",
          "## By side", "", HEAD]
    for side in ("short", "long"):
        sub = [t for t in best["trades"] + conf["trades"] if t["side"] == side]
        if sub:
            L.append(row(side, tally(sub, best["cfg"])))
    L += ["", "## How trades ended", "", HEAD]
    for why in ("stop", "close", "target"):
        sub = [t for t in best["trades"] + conf["trades"] if t["reason"] == why]
        if sub:
            L.append(row(why, tally(sub, best["cfg"])))

    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "inplay.json").write_text(json.dumps(
        {"best": best["cfg"],
         "explore": {k: v for k, v in best.items() if k != "trades"},
         "holdout": {k: v for k, v in conf.items() if k != "trades"},
         "all": [{k: v for k, v in r.items() if k not in ("trades", "cfg")}
                 for r in results]}, indent=2, default=str))
    return "\n".join(L) + "\n"


def sensitivity(data, dailies, cfg: dict, dates: set) -> str:
    """What the result is worth at costs we have not proved we can achieve.

    The winning configuration stops at five percent of the 14-day ATR. On a
    $600 stock with a $15 ATR that is about seventy-five cents, and our
    assumed slippage of 0.05% is already thirty cents of it each way. The
    published work carries the same warning about its own tightest variant.

    So the question is not whether the rule made money at the costs we
    assumed. It is how much worse the costs have to get before it does not.
    """
    base = op.SLIP_PCT
    rows = []
    try:
        for slip in (0.0, 0.05, 0.10, 0.15, 0.25, 0.50):
            op.SLIP_PCT = slip
            t = tally(run(data, dailies, cfg, dates), cfg)
            t["name"] = f"slippage {slip:.2f}% each way"
            rows.append(t)
            log.info("slip %.2f%%: n=%d win=%.1f%% profit=%+.1f%%",
                     slip, t["n"], t["win_pct"], t["profit_pct"])
    finally:
        op.SLIP_PCT = base

    L = ["## How much cost does it survive?", "",
         f"`{cfg.get('name', '')}` over every date, costs varied:", "", HEAD]
    for t in rows:
        L.append(row(t["name"], t))
    dies = next((t for t in rows if t["profit_pct"] <= 0), None)
    L.append("")
    if dies:
        L.append(f"- **It stops making money at {dies['name']}.** Our backtest "
                 f"assumes 0.05%. The gap between those two numbers is the "
                 f"entire result.")
    else:
        L.append("- Survives every cost level tested, including 0.50% each "
                 "way, which is far worse than these names actually trade.")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--universe", default="wide")
    ap.add_argument("--symbols", default="")

    symbols = ([s.strip().upper() for s in args.symbols.split(",") if s.strip()]
               or UNIVERSES.get(args.universe) or UNIVERSES["wide"])
    try:
        md = MarketData(Credentials.from_env(), feed="iex")
        data = op.fetch(md, symbols, args.days)
    except AlpacaError as exc:
        log.error("Fetch failed: %s", exc)
        return 1
    dailies = build(data)
    log.info("%d symbols with enough history to rank", len(dailies))
    if not dailies:
        log.error("Nothing rankable.")
        return 1
    out = research(data, dailies, args.universe)
    try:
        cfg = json.loads((REPORTS / "inplay.json").read_text())["best"]
        all_dates = {d for x in dailies.values() for d in x.index}
        out += "\n" + sensitivity(data, dailies, cfg, all_dates)
    except Exception as exc:                                   # noqa: BLE001
        log.warning("Sensitivity pass failed: %s", exc)
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "inplay.md").write_text(out)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
