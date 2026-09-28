"""Why the breaks fail.

The sweep settled one thing: stop width, hold length and re-entry are not the
problem. All 24 combinations lost. That means the ENTRY is wrong - the rule
cannot tell a break that runs from a break that dies, and two out of three die.

So this stops tuning and asks the only question left: of every coil break in
the window, what do the winners have that the losers do not?

Same method that produced the one real finding in this project. The autopsy on
2026 daily data found winners averaged 5.35% daily range against losers at
3.80%, and that became the volatility screen. Nothing found by searching
parameters has ever survived; both things that did survive came from comparing
winners to losers directly.

Every break is labelled, not just the ones the portfolio had room to take, so
the sample is every opportunity rather than a scheduling accident.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
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
log = logging.getLogger("sq_autopsy")

# Deliberately loose: the point is to see every break and let the evidence say
# which ones are worth taking, not to pre-filter with the assumptions that
# already failed.
SCAN = {**BASE_SQ, "squeeze_atr": 3.0, "vol_mult": 1.0}


def htf_context(df: pd.DataFrame, span: int = 20) -> pd.Series:
    """1-hour trend, mapped back onto the 5-minute bars.

    The one piece of the owner's own method the bot has never had: he reads
    the hour for context and the five for entry.

    The shift is load-bearing. Without it the 5-minute bar at 10:05 would see
    the 10:00-11:00 hourly candle that has not closed yet - a look-ahead that
    would make any result from this feature fiction. The same bug was found
    and fixed in the daily engine earlier.
    """
    h = df.resample("1h").agg({"open": "first", "high": "max", "low": "min",
                               "close": "last"}).dropna()
    if len(h) < span + 2:
        return pd.Series(np.nan, index=df.index)
    ema = h["close"].ewm(span=span, adjust=False).mean()
    trend = (h["close"] > ema).astype(float).shift(1)
    return trend.reindex(df.index, method="ffill")


def features_at(day: pd.DataFrame, i: int, side: str) -> dict:
    """Conditions on the break bar. Backward-looking only."""
    bar = day.iloc[i]
    a, close = float(bar["atr"]), float(bar["close"])
    ch, cl, cv = (float(bar["coil_high"]), float(bar["coil_low"]),
                  float(bar["coil_vol"]))
    prior = day.iloc[:i + 1]
    tp = (prior["high"] + prior["low"] + prior["close"]) / 3
    vwap = float((tp * prior["volume"]).sum() / max(prior["volume"].sum(), 1))
    opened = float(day["open"].iloc[0])
    et = day.index[i].tz_convert(EASTERN)
    level = ch if side == "long" else cl
    return {
        "minutes_in": (et.hour - 9) * 60 + et.minute - 30,
        "coil_tight_atr": round((ch - cl) / a, 2) if a else 0.0,
        "rvol": round(float(bar["volume"]) / cv, 2) if cv else 0.0,
        "atr_pct": round(100 * a / close, 2) if close else 0.0,
        "break_size_atr": round(abs(close - level) / a, 2) if a else 0.0,
        "vwap_dist_atr": round((close - vwap) / a * (1 if side == "long" else -1), 2)
        if a else 0.0,
        "day_move_atr": round((close - opened) / a * (1 if side == "long" else -1), 2)
        if a else 0.0,
        "range_used_atr": round(
            (float(prior["high"].max()) - float(prior["low"].min())) / a, 2)
        if a else 0.0,
        "body_frac": round(abs(close - float(bar["open"]))
                           / max(float(bar["high"]) - float(bar["low"]), 1e-9), 2),
        # 1 when the hourly trend agrees with the break's direction
        "htf_aligned": (float(bar["htf_up"]) if side == "long"
                        else 1.0 - float(bar["htf_up"]))
        if bar["htf_up"] == bar["htf_up"] else 0.5,
    }


def outcome(day: pd.DataFrame, i: int, side: str, p: dict) -> dict | None:
    """Did this break reach 2R before -1R, on a fixed neutral rule?"""
    bar = day.iloc[i]
    a = float(bar["atr"])
    ch, cl, close = (float(bar["coil_high"]), float(bar["coil_low"]),
                     float(bar["close"]))
    if a <= 0:
        return None
    stop = cl - a if side == "long" else ch + a
    rps = abs(close - stop)
    if rps <= 0 or rps / close > 0.10:
        return None
    target = close + 2 * rps if side == "long" else close - 2 * rps
    best = 0.0
    for j in range(i + 1, len(day)):
        b = day.iloc[j]
        hi, lo = float(b["high"]), float(b["low"])
        mfe = (hi - close) / rps if side == "long" else (close - lo) / rps
        best = max(best, mfe)
        hit_stop = lo <= stop if side == "long" else hi >= stop
        hit_tgt = hi >= target if side == "long" else lo <= target
        if hit_stop:                      # stop first on ties, as always
            return {"won": 0, "r": -1.0, "mfe": round(best, 2)}
        if hit_tgt:
            return {"won": 1, "r": 2.0, "mfe": round(best, 2)}
    last = float(day["close"].iloc[-1])
    r = (last - close) / rps if side == "long" else (close - last) / rps
    return {"won": 1 if r > 0 else 0, "r": round(r, 2), "mfe": round(best, 2)}


def collect(data: dict, p: dict) -> list[dict]:
    rows = []
    for sym, df in data.items():
        if df.empty:
            continue
        d = prepare_sq(df, p)
        d["htf_up"] = htf_context(df)
        for _, day in d.groupby(d.index.tz_convert(EASTERN).date):
            if len(day) < p["base_len"] + p["atr_len"] + 5:
                continue
            a, close, vol = day["atr"], day["close"], day["volume"]
            ch, cl, cv = day["coil_high"], day["coil_low"], day["coil_vol"]
            tight = (ch - cl) <= p["squeeze_atr"] * a
            pushed = vol >= p["vol_mult"] * cv
            ok = tight & pushed & a.notna() & ch.notna() & cv.notna() & (a > 0)
            up = ok & (close > ch) & (close > day["open"])
            dn = ok & (close < cl) & (close < day["open"])
            lo_t = pd.Timestamp(p["no_entry_before"]).time()
            hi_t = pd.Timestamp(p["no_entry_after"]).time()
            times = day.index.tz_convert(EASTERN).time
            for i in range(p["base_len"] + p["atr_len"], len(day) - 3):
                if not (lo_t <= times[i] <= hi_t):
                    continue
                side = ("long" if bool(up.iloc[i])
                        else "short" if bool(dn.iloc[i]) else None)
                if side is None:
                    continue
                res = outcome(day, i, side, p)
                if res is None:
                    continue
                rows.append({"symbol": sym, "side": side,
                             "time": str(day.index[i]),
                             **features_at(day, i, side), **res})
    return rows


def separation(rows: list[dict], keys: list[str]) -> list[dict]:
    """Winners vs losers on each condition, in pooled standard deviations."""
    win = [r for r in rows if r["won"] == 1]
    loss = [r for r in rows if r["won"] == 0]
    out = []
    for k in keys:
        w = np.array([r[k] for r in win], dtype=float)
        l = np.array([r[k] for r in loss], dtype=float)
        if len(w) < 5 or len(l) < 5:
            continue
        sd = np.sqrt((w.var(ddof=1) + l.var(ddof=1)) / 2) or 1e-9
        out.append({"feature": k, "winners": round(float(w.mean()), 2),
                    "losers": round(float(l.mean()), 2),
                    "separation_sd": round(float((w.mean() - l.mean()) / sd), 2)})
    out.sort(key=lambda r: -abs(r["separation_sd"]))
    return out


def render(p: dict) -> str:
    rows, sep = p["rows"], p["separation"]
    wins = sum(r["won"] for r in rows)
    out = [f"# Why the breaks fail", "",
           f"**{len(rows)} breaks · {p['symbols']} symbols · from "
           f"{p['start']} · {p['generated']}**", "",
           f"Base rate: **{wins} of {len(rows)} reached 2R before -1R "
           f"({100 * wins / max(len(rows), 1):.1f}%).** Every break in the "
           "window is labelled, not only the ones a portfolio had room for.",
           ""]
    if not sep:
        out.append("**Too few of one class to compare.**")
        return "\n".join(out)

    out += ["| Condition | Winners | Losers | Separation |",
            "|---|---|---|---|"]
    for r in sep:
        mark = " ⭐" if abs(r["separation_sd"]) >= 0.30 else ""
        out.append(f"| {r['feature']} | {r['winners']} | {r['losers']} | "
                   f"**{r['separation_sd']:+.2f} SD**{mark} |")
    strong = [r for r in sep if abs(r["separation_sd"]) >= 0.30]
    out += ["", "_Separation is how far apart the two groups sit in pooled "
            "standard deviations. Below about 0.30 SD a condition cannot "
            "sort anything usefully, whatever its p-value._", ""]
    if strong:
        out += ["### Worth acting on", ""]
        for r in strong:
            better = "higher" if r["separation_sd"] > 0 else "lower"
            out.append(f"- **{r['feature']}** — winners run {better} "
                       f"({r['winners']} vs {r['losers']}).")
    else:
        out += ["### Nothing separates them", "",
                "No condition reaches 0.30 SD. On this evidence the winners "
                "and losers look the same at the moment of entry, which means "
                "no filter built from these features will help - and the "
                "honest conclusion is that this entry has no edge to find, "
                "rather than one that needs better tuning."]

    for side in ("long", "short"):
        sub = [r for r in rows if r["side"] == side]
        if len(sub) >= 20:
            w = sum(r["won"] for r in sub)
            out.append(f"\n_{side}: {w}/{len(sub)} = "
                       f"{100 * w / len(sub):.1f}% hit 2R first._")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--minutes", type=int, default=5)
    ap.add_argument("--universe", default="movers", choices=list(UNIVERSES))
    args = ap.parse_args(argv)

    p = {**SCAN, "minutes": args.minutes}
    syms = UNIVERSES[args.universe]
    start = args.start or (pd.Timestamp.now(tz=EASTERN)
                           - pd.Timedelta(days=60)).date().isoformat()
    try:
        md = MarketData(Credentials.from_env(), feed="iex")
        log.info("Fetching %d symbols, %d-minute bars from %s",
                 len(syms), args.minutes, start)
        data = md.intraday_bars(syms, args.minutes, start=start, end=args.end)
    except AlpacaError as exc:
        log.error("Fetch failed: %s", exc)
        return 1
    data = {s: d for s, d in data.items() if not d.empty}
    rows = collect(data, p)
    log.info("%d breaks labelled", len(rows))
    keys = ["minutes_in", "coil_tight_atr", "rvol", "atr_pct",
            "break_size_atr", "vwap_dist_atr", "day_move_atr",
            "range_used_atr", "body_frac", "htf_aligned"]
    payload = {"symbols": len(data), "start": start, "rows": rows,
               "separation": separation(rows, keys),
               "generated": datetime.now().strftime("%Y-%m-%d %H:%M")}
    REPORTS.mkdir(exist_ok=True)
    text = render(payload)
    (REPORTS / "sq_autopsy.md").write_text(text)
    (REPORTS / "sq_autopsy.json").write_text(
        json.dumps({**payload, "rows": rows[:400]}, indent=2, default=str))
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
