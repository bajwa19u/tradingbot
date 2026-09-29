"""The opening drive — the trade the retest rule was structurally blind to.

Why this exists
---------------
On 28 September AMD fell 2.5% in the first ten minutes and the bot did not
see it. Three separate things stopped it, and any one of them alone was
enough:

  1. The coil needs 12 bars of history before it can measure a range. On
     5-minute bars that is an hour. The move was over at 09:40.
  2. `no_entry_before = 09:45` rejected the entry before any other condition
     was even evaluated.
  3. The rule waits for a retest. AMD never came back.

All three are the same mistake: a rule that derives its levels from the
session it is trading cannot trade the start of that session.

The fix is to stop deriving them. The prices that matter at 09:30 already
exist before the bell — yesterday's high, low and close, and the premarket
high and low. There is no warmup, because there is nothing to warm up.

What is fixed and what is tested
--------------------------------
Fixed, so the comparison is between rules and not between a rule and a lucky
number: the levels, the window, the scale unit, the hold limit and the
slippage. Tested: entry style (take the break, or wait for the retest), where
the stop goes, the target, and how far through a level price must close.

Everything is measured on an explore split and the single best combination is
then run once on dates it has never seen. A number that only exists in the
explore split is not a result.

Anti-lookahead
--------------
Every input to a decision on bar `i` is known before bar `i` closes:
  * levels come from prior sessions and from premarket bars strictly before
    09:30;
  * `scale` comes from the prior day;
  * the break test reads bar `i`'s close, and entry happens at that close
    (drive) or later (retest);
  * whether a level is support or resistance is decided by the 09:30 open,
    not by where price ends up.
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
from .forensics import CORE, UNIVERSES

EASTERN = ZoneInfo("America/New_York")
REPORTS = REPO_ROOT / "reports"
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("opening")

# --- fixed, not tuned --------------------------------------------------------
PRE_START, PRE_END = "04:00", "09:29"
WIN_START, WIN_END = "09:30", "10:00"   # when a break may be taken
SCALE_WINDOW = ("09:30", "10:00")       # prior day, for the stop unit
# NO HOLD CAP BY DEFAULT. A position is closed by its stop or its target and
# by nothing else. The old 120-minute clock closed seven of eleven trades on
# 29 September without one of them reaching a target, which is not managing a
# trade, it is interrupting one.
#
# The closing bell is the single exception and it is not a choice: the market
# shuts. A trade still open at FORCE_EXIT is closed there, and it is reported
# as "bell" rather than lumped in with the stop and the target, because it is
# not a result the rule produced - it is a result the clock produced.
MAX_HOLD_MIN = None                     # minutes, or None for no cap at all
FORCE_EXIT = "15:55"
SLIP_PCT = 0.05
MIN_SCALE_PCT = 0.01                    # a scale below this is a dead symbol
MIN_PRE_BARS = 30                       # fewer than this is not a premarket
RETEST_EXTEND = 1.0                     # how far a break must run before a
#                                         pullback counts as a retest at all

BASE = {
    "entry_mode": "drive",   # drive | retest
    "stop_mode": "level",    # level | bar | session
    "stop_mult": 1.0,        # scales the stop when stop_mode == "level"
    "target_r": 2.0,
    "pen": 0.0,              # how far through the level the close must be
    "retest_wait": 10,       # bars allowed for a retest, when that mode is on
    "retest_depth": 0.5,     # how close to the level counts as a retest
    "side": "both",
    "risk_pct": 1.0,
    "stop_pad_pct": 0.0,     # extra room beyond the stop, as % of entry
    "use_premarket": True,   # turned off automatically when the feed is thin
    "max_per_symbol": 1,     # one idea per symbol per day, not one per level
    "levels": "prior",       # prior | or | both
    "or_minutes": 5,         # the opening range, when levels includes "or"
}

LEVEL_NAMES = ("pmh", "pml", "pdh", "pdl", "pdc", "orh", "orl")


# --- levels ------------------------------------------------------------------
def session_levels(prior: pd.DataFrame, pre: pd.DataFrame,
                   use_premarket: bool = True) -> dict[str, float]:
    """Every price that matters at 09:30, all of it known before 09:30.

    `prior` is the previous session's regular-hours bars; `pre` is today's
    premarket. Either may be empty, and the levels that need it are simply
    absent rather than guessed.
    """
    out: dict[str, float] = {}
    if len(prior):
        out["pdh"] = float(prior["high"].max())
        out["pdl"] = float(prior["low"].min())
        out["pdc"] = float(prior["close"].iloc[-1])
    if use_premarket and len(pre) >= MIN_PRE_BARS:
        out["pmh"] = float(pre["high"].max())
        out["pml"] = float(pre["low"].min())
    return {k: v for k, v in out.items() if np.isfinite(v) and v > 0}


def minute_scale(prior: pd.DataFrame) -> float:
    """The stop unit: how far this symbol moves in a minute at the open.

    Taken from the PRIOR day's opening window, so it is a known quantity at
    09:29 and owes nothing to the day being traded. Daily ATR is the wrong
    scale here — it would put the stop a dollar away on a move that resolves
    in cents.
    """
    if not len(prior):
        return 0.0
    w = prior.between_time(*SCALE_WINDOW)
    if len(w) < 5:
        w = prior
    tr = (w["high"] - w["low"]).astype(float)
    return float(tr.mean()) if len(tr) else 0.0


def opening_range(rth: pd.DataFrame, minutes: int
                  ) -> tuple[dict[str, float], int]:
    """The first `minutes` of the session, and the bar the range completes on.

    This is the level set that owes nothing to the previous day and nothing
    to a premarket the free feed does not really have. It is also the shape
    the AMD tape actually had: a range in the first five minutes, then a
    close outside it.

    The second return value is what keeps it honest - no break of this range
    can be taken until the bar on which the range is finished.
    """
    if minutes <= 0 or len(rth) < minutes + 1:
        return {}, 0
    w = rth.iloc[:minutes]
    return {"orh": float(w["high"].max()), "orl": float(w["low"].min())}, minutes


def split_session(day_ext: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(premarket, regular hours) for one day of extended-hours bars."""
    return (day_ext.between_time(PRE_START, PRE_END),
            day_ext.between_time("09:30", "15:59"))


# --- the rule ----------------------------------------------------------------
def opening_breaks(rth: pd.DataFrame, levels: dict[str, float], scale: float,
                   p: dict, ready: dict[str, int] | None = None
                   ) -> list[tuple[int, str, float, str]]:
    """(bar index, side, level, level name) for breaks inside the window.

    Which side of a level we are on is decided by the 09:30 OPEN, before a
    single bar has closed. A level below the open is support and breaking it
    is a short; a level above is resistance and breaking it is a long. That
    choice cannot be made later without peeking.
    """
    if not len(rth) or scale <= 0 or not levels:
        return []
    ref = float(rth["open"].iloc[0])
    close = rth["close"].astype(float).values
    times = rth.index.tz_convert(EASTERN).time
    lo_t, hi_t = pd.Timestamp(WIN_START).time(), pd.Timestamp(WIN_END).time()
    pen = p["pen"] * scale
    want = p.get("side", "both")

    ready = ready or {}
    out: list[tuple[int, str, float, str]] = []
    for name, lvl in sorted(levels.items(), key=lambda kv: kv[0]):
        if lvl == ref:
            continue
        side = "short" if lvl < ref else "long"
        if want != "both" and side != want:
            continue
        for i in range(ready.get(name, 0), len(rth)):
            if not (lo_t <= times[i] <= hi_t):
                continue
            # Only the FIRST break of a level counts. A level that breaks,
            # recovers and breaks again is one story, not two trades.
            if (close[i] < lvl - pen if side == "short"
                    else close[i] > lvl + pen):
                out.append((i, side, float(lvl), name))
                break
    out.sort(key=lambda t: t[0])
    return out


def entry_index(rth: pd.DataFrame, i: int, side: str, level: float,
                scale: float, p: dict) -> int | None:
    """Which bar we get filled on, or None if the setup never completes.

    In `drive` mode that is the break bar itself — the whole point is that a
    move which never looks back is still a move.

    `retest` mode is deliberately two-stage: price must first EXTEND away
    from the level, and only then come back to it. Without the extension
    stage a shallow break makes every following bar count as a retest, the
    two modes collapse into the same rule, and the comparison between them
    means nothing. A close back through the level kills the setup rather
    than becoming a worse entry.
    """
    if p["entry_mode"] == "drive":
        return i
    band = p["retest_depth"] * scale
    reach = level - RETEST_EXTEND * scale if side == "short" \
        else level + RETEST_EXTEND * scale
    hi = rth["high"].astype(float).values
    lo = rth["low"].astype(float).values
    cl = rth["close"].astype(float).values
    extended = False
    for j in range(i, min(i + 1 + p["retest_wait"], len(rth))):
        if not extended:
            extended = lo[j] <= reach if side == "short" else hi[j] >= reach
            continue
        back = (hi[j] >= level - band if side == "short"
                else lo[j] <= level + band)
        if not back:
            continue
        through = cl[j] > level if side == "short" else cl[j] < level
        return None if through else j
    return None


def simulate(rth: pd.DataFrame, i: int, j: int, side: str, level: float,
             scale: float, p: dict) -> dict | None:
    """One trade, priced with slippage on both ends. None if unsizeable."""
    slip = SLIP_PCT / 100.0
    raw = float(rth["close"].iloc[j])
    entry = raw * (1 - slip) if side == "short" else raw * (1 + slip)

    if p["stop_mode"] in ("bar", "session"):
        # "bar" stops just past the break itself. "session" stops past the
        # high of the whole session so far, which is what the AMD audit said
        # was missing: price spiked to the session high AFTER the break and
        # took out a stop sitting on the level, then fell thirty dollars.
        lo_i = 0 if p["stop_mode"] == "session" else i
        edge = (float(rth["high"].iloc[lo_i:j + 1].max()) if side == "short"
                else float(rth["low"].iloc[lo_i:j + 1].min()))
        stop = edge + 0.1 * scale if side == "short" else edge - 0.1 * scale
    else:
        stop = (level + p["stop_mult"] * scale if side == "short"
                else level - p["stop_mult"] * scale)

    # Optional extra room, measured in percent OF THE ENTRY PRICE, so "give
    # it another 1%" means the same thing on a $40 stock and a $600 one.
    pad = float(p.get("stop_pad_pct", 0.0)) / 100.0
    if pad:
        stop = stop + pad * entry if side == "short" else stop - pad * entry

    rps = abs(entry - stop)
    if rps <= 0 or rps / entry > 0.10:
        return None
    target = (entry - p["target_r"] * rps if side == "short"
              else entry + p["target_r"] * rps)

    times = rth.index.tz_convert(EASTERN)
    cap = p.get("max_hold_min", MAX_HOLD_MIN)
    deadline = (times[j] + pd.Timedelta(minutes=int(cap))) if cap else None
    flat = pd.Timestamp(FORCE_EXIT).time()

    px, why, k_out = None, None, len(rth) - 1
    for k in range(j + 1, len(rth)):
        b = rth.iloc[k]
        hi, lo = float(b["high"]), float(b["low"])
        k_out = k
        hit_stop = hi >= stop if side == "short" else lo <= stop
        hit_targ = lo <= target if side == "short" else hi >= target
        if hit_stop:                      # stop wins ties: the honest choice
            px, why = stop, "stop"
        elif hit_targ:
            px, why = target, "target"
        elif deadline is not None and times[k] >= deadline:
            px, why = float(b["close"]), "time"
        elif times[k].time() >= flat:
            px, why = float(b["close"]), "bell"
        if px is not None:
            break
    if px is None:
        # Neither side was hit and neither deadline has passed, so the trade
        # is simply still running. Backtests almost never land here; the live
        # bot lands here constantly, and calling it a closed trade would post
        # a result for a position that has not finished.
        px, why = float(rth["close"].iloc[-1]), "open"

    exit_px = px * (1 + slip) if side == "short" else px * (1 - slip)
    gain = (entry - exit_px) if side == "short" else (exit_px - entry)
    r = gain / rps
    return {"side": side, "entry": round(entry, 4), "stop": round(stop, 4),
            "target": round(target, 4), "exit": round(exit_px, 4),
            "reason": why, "r": round(float(r), 4),
            "pct": round(float(r) * p["risk_pct"], 4),
            "entry_time": str(times[j])[11:16],
            "exit_time": str(times[k_out])[11:16],
            "rps": round(rps, 4)}


def day_trades(day_ext: pd.DataFrame, prior_rth: pd.DataFrame,
               p: dict) -> list[dict]:
    """Every trade the rule takes on one day of one symbol."""
    pre, rth = split_session(day_ext)
    if len(rth) < 10 or not len(prior_rth):
        return []
    scale = minute_scale(prior_rth)
    ref = float(rth["open"].iloc[0])
    if scale <= 0 or scale / ref * 100 < MIN_SCALE_PCT:
        return []
    which = p.get("levels", "prior")
    lv, ready = {}, {}
    if which in ("prior", "both"):
        lv.update(session_levels(prior_rth, pre, p.get("use_premarket", True)))
    if which in ("or", "both"):
        orl, first = opening_range(rth, p.get("or_minutes", 5))
        lv.update(orl)
        ready.update({k: first for k in orl})
    out = []
    for i, side, level, name in opening_breaks(rth, lv, scale, p, ready):
        # Yesterday's low and the premarket low are usually the same idea a
        # few cents apart. Taking both is not diversification, it is the same
        # trade at two or three times the intended risk.
        if len(out) >= p.get("max_per_symbol", 1):
            break
        j = entry_index(rth, i, side, level, scale, p)
        if j is None:
            continue
        t = simulate(rth, i, j, side, level, scale, p)
        if t is None:
            continue
        t.update(level=round(level, 4), level_name=name, scale=round(scale, 4),
                 break_time=str(rth.index[i].tz_convert(EASTERN))[11:16])
        out.append(t)
    return out


# --- measurement -------------------------------------------------------------
def by_day(df: pd.DataFrame) -> list[tuple[pd.Timestamp, pd.DataFrame]]:
    if not len(df):
        return []
    d = df.index.tz_convert(EASTERN).date
    return [(k, df[d == k]) for k in sorted(set(d))]


def run_combo(data: dict[str, pd.DataFrame], p: dict,
              dates: set | None = None) -> dict:
    """Every trade for one configuration, tallied the way results get read."""
    trades: list[dict] = []
    for sym, df in data.items():
        days = by_day(df)
        for n in range(1, len(days)):
            date, day = days[n]
            if dates is not None and date not in dates:
                continue
            _, prior_rth = split_session(days[n - 1][1])
            for t in day_trades(day, prior_rth, p):
                t.update(symbol=sym, date=str(date))
                trades.append(t)
    return tally(trades, p)


def tally(trades: list[dict], p: dict) -> dict:
    # A trade that has not finished is not a result. Filing unfinished trades
    # with the real ones is how a win rate quietly drifts away from the truth.
    trades = [t for t in trades if t.get("reason") != "open"]
    n = len(trades)
    won = sum(1 for t in trades if t["pct"] > 0)
    pct = sum(t["pct"] for t in trades)
    out = {"n": n, "won": won, "lost": n - won,
           "win_pct": round(100 * won / n, 1) if n else 0.0,
           "profit_pct": round(pct, 2),
           "avg_pct": round(pct / n, 3) if n else 0.0,
           "trades": trades}
    for side in ("short", "long"):
        s = [t for t in trades if t["side"] == side]
        w = sum(1 for t in s if t["pct"] > 0)
        out[side] = {"n": len(s), "won": w, "lost": len(s) - w,
                     "win_pct": round(100 * w / len(s), 1) if s else 0.0,
                     "profit_pct": round(sum(t["pct"] for t in s), 2)}
    out["breakeven_win_pct"] = round(100 / (1 + p["target_r"]), 1)
    return out


def noise_floor(n_trades: int, n_configs: int, target_r: float) -> float:
    """How much the best of N configurations beats the truth by luck alone.

    Same yardstick used on the squeeze sweep. A best-of-24 result inside this
    band is what searching 24 configurations produces on random data.
    """
    if n_trades <= 0:
        return 0.0
    q = 1.0 / (1.0 + target_r)
    se = float(np.sqrt(q * (1 - q) / n_trades)) * 100
    return round(float(np.sqrt(2 * np.log(max(n_configs, 2)))) * se, 2)


def grid() -> list[dict]:
    """Deliberately small. Every extra knob raises the bar a result must clear."""
    out = []
    for mode, stop_mode, tr, pen in product(
            ("drive", "retest"), ("level", "bar", "session"),
            (1.5, 2.0, 3.0), (0.0, 0.5)):
        out.append({**BASE, "entry_mode": mode, "stop_mode": stop_mode,
                    "target_r": tr, "pen": pen,
                    "name": f"{mode}/{stop_mode}/{tr}R/pen{pen}"})
    return out


def or_grid() -> list[dict]:
    """A separate, pre-specified hypothesis with its own small grid.

    The first study tested breaks of yesterday's levels. This tests breaks of
    the range the session makes in its own first minutes, which is a
    different claim and gets its own holdout rather than being folded into
    the earlier search as more configurations.
    """
    out = []
    for mode, stop_mode, tr, mins in product(
            ("drive", "retest"), ("level", "session"), (1.5, 2.0, 3.0), (5, 15)):
        out.append({**BASE, "levels": "or", "entry_mode": mode,
                    "stop_mode": stop_mode, "target_r": tr, "or_minutes": mins,
                    "pen": 0.0,
                    "name": f"{mode}/{stop_mode}/{tr}R/OR{mins}m"})
    return out


def fetch(md: MarketData, symbols: list[str], days: int
          ) -> dict[str, pd.DataFrame]:
    start = (pd.Timestamp.now(tz=EASTERN)
             - pd.Timedelta(days=int(days * 1.5) + 5)).date().isoformat()
    log.info("Fetching 1-minute extended-hours bars from %s for %d symbols",
             start, len(symbols))
    data = md.intraday_bars(symbols, 1, start=start, extended=True)
    keep = {s: d for s, d in data.items() if len(d) > 500}
    log.info("Usable: %d symbols, %d bars total",
             len(keep), sum(len(d) for d in keep.values()))
    return keep


def premarket_health(data: dict[str, pd.DataFrame]) -> dict:
    """Is the free feed's premarket good enough to build a level on?

    IEX is a couple of percent of consolidated volume and its premarket is
    thin. If most days have almost no premarket bars, the premarket levels
    are noise and only the prior-day levels can be trusted.
    """
    rows = []
    for sym, df in data.items():
        for date, day in by_day(df):
            pre, rth = split_session(day)
            if not len(rth):
                continue
            rows.append({"symbol": sym, "date": str(date),
                         "pre_bars": len(pre),
                         "pre_vol": float(pre["volume"].sum()) if len(pre) else 0.0})
    if not rows:
        return {"days": 0}
    n = len(rows)
    bars = sorted(r["pre_bars"] for r in rows)
    return {"days": n,
            "median_pre_bars": bars[n // 2],
            "days_with_no_premarket": sum(1 for b in bars if b == 0),
            "days_under_30_bars": sum(1 for b in bars if b < 30),
            "pct_usable": round(100 * sum(1 for b in bars if b >= 30) / n, 1)}


# --- report ------------------------------------------------------------------
def fmt_row(name: str, t: dict) -> str:
    return (f"| {name} | {t['n']} | {t['win_pct']:.1f}% | {t['won']} | "
            f"{t['lost']} | {t['profit_pct']:+.1f}% | {t['avg_pct']:+.3f}% |")


HEAD = ("| rule | trades | win % | won | lost | profit % | avg/trade |\n"
        "|---|---|---|---|---|---|---|")


MODE = {"levels": "prior"}


def research(data: dict[str, pd.DataFrame], universe: str) -> str:
    """Explore on the older dates, confirm the winner on dates never seen."""
    all_dates = sorted({d for df in data.values()
                        for d in df.index.tz_convert(EASTERN).date})
    if len(all_dates) < 20:
        return f"Only {len(all_dates)} days of data — not enough to split.\n"
    cut = int(len(all_dates) * 2 / 3)
    explore, holdout = set(all_dates[:cut]), set(all_dates[cut:])
    log.info("Explore %d days (%s..%s), holdout %d days (%s..%s)",
             len(explore), all_dates[0], all_dates[cut - 1],
             len(holdout), all_dates[cut], all_dates[-1])

    health = premarket_health(data)
    log.info("Premarket health: %s", health)

    combos = or_grid() if MODE["levels"] == "or" else grid()
    results = []
    for c in combos:
        r = run_combo(data, c, dates=explore)
        r["name"] = c["name"]
        r["cfg"] = {k: v for k, v in c.items() if k != "name"}
        results.append(r)
        log.info("%-28s n=%-5d win=%.1f%% profit=%+.1f%%",
                 c["name"], r["n"], r["win_pct"], r["profit_pct"])

    sized = [r for r in results if r["n"] >= 30]
    if not sized:
        return ("No configuration produced at least 30 trades in the explore "
                "split — nothing measurable.\n")
    best = max(sized, key=lambda r: r["profit_pct"])
    floor = noise_floor(best["n"], len(combos), best["cfg"]["target_r"])
    conf = run_combo(data, best["cfg"], dates=holdout)

    title = ("Opening range breakout" if MODE["levels"] == "or"
             else "Opening drive")
    L = [f"# {title} — {universe}", "",
         f"1-minute bars · {len(all_dates)} trading days "
         f"({all_dates[0]} to {all_dates[-1]}) · {len(data)} symbols",
         f"Window {WIN_START}–{WIN_END} ET · levels: "
         + ("the session's own opening range"
            if MODE["levels"] == "or"
            else "prior-day high/low/close and premarket high/low")
         + (f" · hold limit {MAX_HOLD_MIN} min"
            if MAX_HOLD_MIN else " · no hold limit — stop, target or the bell")
         + " "
         f"· slippage {SLIP_PCT}% each way", "",
         "## Does the free feed have a usable premarket?", ""]
    if health.get("days"):
        L += [f"- {health['days']} symbol-days examined",
              f"- median premarket bars per day: **{health['median_pre_bars']}**",
              f"- days with no premarket at all: {health['days_with_no_premarket']}",
              f"- days with fewer than 30 premarket bars: {health['days_under_30_bars']}",
              f"- **{health['pct_usable']}% of days have a usable premarket**", ""]
        if health["pct_usable"] < 50:
            L += ["> The premarket on this feed is too thin to trust. "
                  "Premarket levels are still tested below, but a result that "
                  "depends on them is a result built on 2% of the volume.", ""]
    L += ["## Every configuration, explore split only", "", HEAD]
    for r in sorted(results, key=lambda r: -r["profit_pct"]):
        L.append(fmt_row(r["name"], r))
    L += ["", "## The best one, then the same rule on dates it never saw", "",
          f"**{best['name']}**", "", HEAD,
          fmt_row("explore", best), fmt_row("holdout (unseen)", conf), "",
          f"- break-even win rate at {best['cfg']['target_r']}R: "
          f"**{best['breakeven_win_pct']}%**",
          f"- best-of-{len(combos)} noise floor on the explore split: "
          f"**±{floor}%** win rate", ""]

    verdict = []
    if conf["n"] < 20:
        verdict.append(f"The holdout produced only {conf['n']} trades. "
                       "That is too few to confirm anything.")
    if conf["profit_pct"] <= 0:
        verdict.append("**The best explore configuration loses money on unseen "
                       "dates.** That is the signature of a fitted result, and "
                       "it is the same thing every configuration search in this "
                       "project has produced. Do not deploy it.")
    elif conf["win_pct"] < best["breakeven_win_pct"]:
        verdict.append("The holdout win rate is below break-even for this "
                       "target, so the profit comes from a handful of large "
                       "winners rather than from an edge that repeats.")
    else:
        verdict.append("**The rule holds up on dates it never saw.** That is "
                       "the first condition for deploying it, and the only one "
                       "this project has ever failed.")
    if best["win_pct"] - best["breakeven_win_pct"] < floor:
        verdict.append(f"The explore edge ({best['win_pct']}% versus "
                       f"{best['breakeven_win_pct']}% break-even) is inside the "
                       f"±{floor}% band that searching {len(combos)} "
                       "configurations produces on random data.")
    L += ["## Verdict", ""] + [f"- {v}" for v in verdict] + [""]

    L += ["## By level — which price actually matters", "", HEAD]
    for nm in LEVEL_NAMES:
        sub = [t for t in best["trades"] + conf["trades"]
               if t["level_name"] == nm]
        if sub:
            L.append(fmt_row(nm, tally(sub, best["cfg"])))
    L += ["", "## By side", "", HEAD]
    for side in ("short", "long"):
        sub = [t for t in best["trades"] + conf["trades"] if t["side"] == side]
        if sub:
            L.append(fmt_row(side, tally(sub, best["cfg"])))

    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "opening.json").write_text(json.dumps(
        {"health": health, "best": best["cfg"], "explore": {
            k: v for k, v in best.items() if k != "trades"},
         "holdout": {k: v for k, v in conf.items() if k != "trades"},
         "all": [{k: v for k, v in r.items() if k not in ("trades", "cfg")}
                 for r in results]}, indent=2, default=str))
    return "\n".join(L) + "\n"


def audit_day(data: dict[str, pd.DataFrame], symbol: str, date: str,
              p: dict) -> str:
    """What the rule saw on one specific symbol and day. Used to check AMD."""
    df = data.get(symbol)
    if df is None or not len(df):
        return f"No data for {symbol}.\n"
    days = by_day(df)
    idx = next((n for n, (d, _) in enumerate(days) if str(d) == date), None)
    if idx is None or idx == 0:
        return f"No usable {date} for {symbol} (need the prior day too).\n"
    _, prior = split_session(days[idx - 1][1])
    pre, rth = split_session(days[idx][1])
    scale = minute_scale(prior)
    lv = session_levels(prior, pre, p.get("use_premarket", True))
    if p.get("levels") in ("or", "both"):
        lv.update(opening_range(rth, p.get("or_minutes", 5))[0])
    L = [f"# {symbol} · {date}", "",
         f"- 09:30 open: **{float(rth['open'].iloc[0]):.2f}**",
         f"- premarket bars: {len(pre)}",
         f"- minute scale (prior day): **{scale:.3f}**", "", "Levels:"]
    for k, v in sorted(lv.items()):
        L.append(f"  - {k} = {v:.2f}")
    L += ["", "First ten minutes, one-minute bars:", "",
          "| time | open | high | low | close |", "|---|---|---|---|---|"]
    for ts, b in rth.head(10).iterrows():
        L.append(f"| {str(ts.tz_convert(EASTERN))[11:16]} | {b['open']:.2f} | "
                 f"{b['high']:.2f} | {b['low']:.2f} | {b['close']:.2f} |")
    L += ["", "Breaks in the window:"]
    brk = opening_breaks(rth, lv, scale, p)
    if not brk:
        L.append("  - none")
    for i, side, level, name in brk:
        j = entry_index(rth, i, side, level, scale, p)
        when = str(rth.index[i].tz_convert(EASTERN))[11:16]
        if j is None:
            L.append(f"  - {when} {side} {name} @ {level:.2f} — no entry "
                     f"({p['entry_mode']} never completed)")
            continue
        t = simulate(rth, i, j, side, level, scale, p)
        if t is None:
            L.append(f"  - {when} {side} {name} @ {level:.2f} — unsizeable")
            continue
        L.append(f"  - {when} {side} {name} @ {level:.2f} → entry "
                 f"{t['entry']:.2f} at {t['entry_time']}, stop {t['stop']:.2f}, "
                 f"target {t['target']:.2f} → **{t['pct']:+.2f}%** "
                 f"({t['reason']} at {t['exit_time']})")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--universe", default="core")
    ap.add_argument("--symbols", default="")
    ap.add_argument("--audit", default="", help="SYMBOL:YYYY-MM-DD")
    ap.add_argument("--levels", default="prior", choices=("prior", "or", "both"),
                    help="yesterday's levels, the opening range, or both")
    args = ap.parse_args(argv)

    MODE["levels"] = args.levels
    BASE["levels"] = args.levels
    symbols = ([s.strip().upper() for s in args.symbols.split(",") if s.strip()]
               or UNIVERSES.get(args.universe, CORE))
    try:
        md = MarketData(Credentials.from_env(), feed="iex")
        data = fetch(md, symbols, args.days)
    except AlpacaError as exc:
        log.error("Fetch failed: %s", exc)
        return 1
    if not data:
        log.error("No usable data.")
        return 1

    REPORTS.mkdir(exist_ok=True)
    if args.audit:
        sym, _, date = args.audit.partition(":")
        out = audit_day(data, sym.strip().upper(), date.strip(), dict(BASE))
        (REPORTS / "opening_audit.md").write_text(out)
    else:
        out = research(data, args.universe)
        (REPORTS / "opening.md").write_text(out)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
