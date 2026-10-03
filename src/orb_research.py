"""ORB on stocks in play: a staged, out-of-sample study.

Pool: the 103-name `inplay.UNIVERSES["wide"]` list (liquid US stocks and ETFs;
hand-assembled earlier, so it carries some survivorship bias - noted in the
report). Data: Alpaca IEX 1-minute bars, regular session only (the free IEX
premarket is unusable, so the gap and the first five minutes stand in for
premarket activity).

Fixed definitions (never optimised): opening range = 09:30-09:34 candles;
breakout = a completed 1-minute close outside it; entry at that close plus
slippage; one trade per stock per day; out at 15:55 at the latest.

Dates are split in order into TRAIN (60%), VALIDATION (20%) and TEST (20%).
Stages are decided on train + validation only. A change is adopted when, set
before running (spec section 20):
  1. validation expectancy improves by >= 0.03R on >= 60 validation trades
  2. training expectancy does not get worse, and validation profit factor does not drop
  3. the validation gain survives removing the two best validation trades
  4. it still improves validation at double the slippage
TEST is run once, at the end, on the baseline and the final candidate.
Everything is in R: 1R = the trade's initial stop distance.

Usage: python -m src.orb_research [--days 252] [--refresh]
"""
from __future__ import annotations

import argparse
import json
import math
import pickle
import sys
from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

from .config import REPO_ROOT, Credentials
from .data import MarketData
from .forensics import LIVE as STATIC10
from .inplay import UNIVERSES

EASTERN = "America/New_York"
POOL = sorted(set(UNIVERSES["wide"]) | {"SPY", "QQQ"} | set(STATIC10))
CACHE = REPO_ROOT / "cache" / "minute_iex_wide.pkl"
REPORT = REPO_ROOT / "reports" / "orb_research.md"
N_MIN = 390
FLAT_IDX = 385                     # 15:55
LOOKBACK = 14                      # sessions for every "relative" baseline
RNG = np.random.default_rng(11)


# ======================================================================= data
def load(days: int, refresh: bool) -> dict[str, pd.DataFrame]:
    now = pd.Timestamp.now(tz=EASTERN)
    start = (now - pd.Timedelta(days=int((days + LOOKBACK + 25) * 1.45))).date()
    data: dict[str, pd.DataFrame] = {}
    if CACHE.exists() and not refresh:
        data = pickle.loads(CACHE.read_bytes())
    first = min((df.index[0] for df in data.values() if len(df)), default=None)
    last = min((df.index[-1] for df in data.values() if len(df)), default=None)
    missing = [s for s in POOL if s not in data]
    md = MarketData(Credentials.from_env(), feed="iex")
    if first is None or first.date() > start + pd.Timedelta(days=10):
        data, fetch_from, syms = {}, start, POOL
    else:
        fetch_from, syms = last.date(), POOL
    for i in range(0, len(syms), 25):                       # chunks keep pages small
        chunk = syms[i:i + 25]
        frm = start if any(s in missing for s in chunk) else fetch_from
        fresh = md.intraday_bars(chunk, 1, start=frm.isoformat())
        for s, df in fresh.items():
            old = data.get(s)
            df = df.astype("float32")
            df = df if old is None else pd.concat([old, df])
            data[s] = df[~df.index.duplicated(keep="last")].sort_index()
        print(f"loaded {i + len(chunk)}/{len(syms)}", flush=True)
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_bytes(pickle.dumps(data))
    return data


def to_days(df: pd.DataFrame, min_bars: int = 300) -> dict:
    """{date: (open, high, low, close, volume) arrays of 390 minutes}; gaps filled.
    `min_bars` drops half-empty days; the live feed passes 1 for today."""
    out = {}
    idx = df.index.tz_convert(EASTERN)
    mins = (idx.hour * 60 + idx.minute - 570).to_numpy()
    dates = idx.date
    for d in np.unique(dates):
        m = dates == d
        k = mins[m]
        if (k == 0).sum() == 0 or m.sum() < min_bars:
            continue
        a = np.full((5, N_MIN), np.nan, dtype="float64")
        vals = df[m][["open", "high", "low", "close", "volume"]].to_numpy("float64").T
        ok = (k >= 0) & (k < N_MIN)
        a[:, k[ok]] = vals[:, ok]
        c = pd.Series(a[3]).ffill().to_numpy()
        for r in (0, 1, 2):
            a[r] = np.where(np.isnan(a[r]), c, a[r])
        a[3] = c
        a[4] = np.nan_to_num(a[4])
        if np.isnan(a[3, 0]):
            continue
        out[d] = a
    return out


@dataclass
class Day:
    o: np.ndarray; h: np.ndarray; l: np.ndarray; c: np.ndarray; v: np.ndarray
    vwap: np.ndarray
    or_h: float; or_l: float; or_w: float
    rvol5: float; vol_base: np.ndarray
    prev_c: float; atr: float; adv: float; gap: float


def _true_ranges(days: dict, ds: list) -> dict:
    tr = {}
    for i, d in enumerate(ds):
        hi, lo = days[d][1].max(), days[d][2].min()
        pc = days[ds[i - 1]][3, -1] if i else days[d][3][0]
        tr[d] = max(hi - lo, abs(hi - pc), abs(lo - pc))
    return tr


def make_day(days: dict, ds: list, i: int, tr: dict) -> Day:
    """Day ds[i] with every baseline taken from the LOOKBACK sessions before it."""
    d, prev = ds[i], ds[i - LOOKBACK:i]
    a = days[d]
    base5 = np.mean([days[x][4, :5].sum() for x in prev])
    pc = days[ds[i - 1]][3, -1]
    tp = (a[1] + a[2] + a[3]) / 3
    cv = np.cumsum(a[4])
    vwap = np.where(cv > 0, np.cumsum(tp * a[4]) / np.maximum(cv, 1e-9), a[3])
    or_h, or_l = float(a[1, :5].max()), float(a[2, :5].min())
    return Day(a[0], a[1], a[2], a[3], a[4], vwap, or_h, or_l, or_h - or_l,
               float(a[4, :5].sum() / base5) if base5 > 0 else np.nan,
               np.mean([days[x][4] for x in prev], axis=0) + 1e-9,
               float(pc), float(np.mean([tr[x] for x in prev])),
               float(np.mean([float((days[x][3] * days[x][4]).sum()) for x in prev])),
               float(a[0, 0] / pc - 1) if pc else np.nan)


def build(data: dict) -> tuple[dict, list]:
    """Per symbol, per day: arrays plus everything known by 09:35."""
    D = {}
    for s, df in data.items():
        days = to_days(df)
        ds = sorted(days)
        tr = _true_ranges(days, ds)
        D[s] = {ds[i]: make_day(days, ds, i, tr) for i in range(LOOKBACK + 1, len(ds))}
    common = sorted(set.intersection(*(set(D[m]) for m in ("SPY", "QQQ"))))
    return D, common


# ======================================================================= strategy
@dataclass(frozen=True)
class P:
    universe: str = "static10"     # static10 | top10 | top20 | top30
    window_end: int = 30           # minute index; 30 = 10:00
    orw: tuple = (0.0, 9e9)        # allowed OR width / daily ATR
    market: str = "none"           # none | vwap | idx | all
    disp: float = 0.0              # breakout close past the level, as a share of OR width
    bvol: float = 0.0              # breakout-minute volume vs that minute's 14-day average
    sides: str = "both"
    ext: float = 9e9               # max |close - VWAP| / daily ATR
    stop: str = "D"                # A opposite OR side | B level - 0.1 ATR | C 5-min swing - 0.02 ATR | D session extreme - 0.02 ATR
    target: float = 2.0
    manage: str = "fixed"          # fixed | partial | trail | ctrail
    cluster_max: int = 99          # same-side signals allowed in any 10-minute span
    slip: float = 0.0005
    delay: int = 0                 # 1 = fill at the next minute's open
    gap: str = "any"               # any | with: only breaks in the direction of the overnight gap
    crowd: int = 0                 # min same-side signals in the last 10 min, itself included (prior-only)
    spy_trend: bool = False        # SPY's move since its open must agree with the trade's direction
    spy_vol: float = 0.0           # skip the day unless SPY's own opening range >= this share of its ATR
    max_risk: float = 0.10         # skip if the stop is further than this share of the entry price


def select(D: dict, d, universe: str) -> list[str]:
    if universe == "static10":
        return [s for s in STATIC10 if d in D.get(s, {})]
    # topN: first-5-minute volume vs its 14-session average (needs 09:35)
    # pmN:  premarket 04:00-09:15 volume vs its 14-session average (orb_checks
    #       attaches `pm_rvol`; delayed SIP makes it known live by 09:30)
    key, n = ("pm_rvol", int(universe[2:])) if universe.startswith("pm") else ("rvol5", int(universe[3:]))
    cand = [(v, s) for s in POOL if s not in ("SPY", "QQQ") and d in D.get(s, {})
            and D[s][d].prev_c >= 5 and D[s][d].adv >= 5e7
            for v in [getattr(D[s][d], key, np.nan)] if v == v]
    return [s for _, s in sorted(cand, reverse=True)[:n]]


def stop_for(x: Day, k: int, side: int, kind: str, level: float) -> float:
    a = x.atr
    if kind == "A":
        return x.or_l if side > 0 else x.or_h
    if kind == "B":
        return level - side * 0.1 * a
    if kind == "C":
        w = slice(max(0, k - 4), k + 1)
        return (x.l[w].min() - 0.02 * a) if side > 0 else (x.h[w].max() + 0.02 * a)
    return (x.l[:k + 1].min() - 0.02 * a) if side > 0 else (x.h[:k + 1].max() + 0.02 * a)


def exit_r(x: Day, k: int, side: int, entry: float, stop: float, p: P,
           j_end: int = N_MIN) -> tuple[float, int, str]:
    """(R, exit minute, why). Live passes `j_end` = minutes completed so far; a
    trade still running then returns (nan, last minute, "open")."""
    rps = abs(entry - stop)
    fill = lambda px: px * (1 - side * p.slip)
    r_of = lambda px: side * (fill(px) - entry) / rps
    tgt = entry + side * p.target * rps
    cur, best, banked, w = stop, entry, 0.0, 1.0
    for j in range(k + 1, min(j_end, N_MIN)):
        if (x.l[j] <= cur) if side > 0 else (x.h[j] >= cur):
            return banked + w * r_of(min(x.o[j], cur) if side > 0 else max(x.o[j], cur)), j, "stop"
        if p.manage == "be" and cur != entry and ((x.h[j] >= entry + rps) if side > 0 else (x.l[j] <= entry - rps)):
            cur = entry                                # from the next minute on, the stop sits at entry
        if p.manage == "partial" and w == 1.0 and ((x.h[j] >= entry + rps) if side > 0 else (x.l[j] <= entry - rps)):
            banked, w, cur, tgt = 0.5 * r_of(entry + side * rps), 0.5, entry, entry + side * 3 * rps
        if p.manage in ("fixed", "partial", "be") and ((x.h[j] >= tgt) if side > 0 else (x.l[j] <= tgt)):
            return banked + w * r_of(tgt), j, "target"
        if j >= FLAT_IDX:
            return banked + w * r_of(x.c[j]), j, "bell"
        if p.manage in ("trail", "ctrail"):
            best = max(best, x.h[j] if p.manage == "trail" else x.c[j]) if side > 0 else \
                min(best, x.l[j] if p.manage == "trail" else x.c[j])
            if side * (best - entry) >= rps:
                cur = max(cur, best - rps) if side > 0 else min(cur, best + rps)
    if j_end < N_MIN:
        return float("nan"), j_end - 1, "open"
    return banked + w * r_of(x.c[-1]), N_MIN - 1, "bell"


def first_signal(x: Day, sa: np.ndarray, qa: np.ndarray, p: P, k_end: int, spy: Day | None = None) -> dict | None:
    """The day's one trade for this stock: the first completed 1-minute close
    outside the opening range, before minute `k_end`, that passes every filter.
    `sa`/`qa` say whether SPY/QQQ closed above their VWAP each minute. The live
    paper feed passes k_end = the minutes completed so far."""
    if not (x.or_w > 0 and x.atr > 0):
        return None
    ratio = x.or_w / x.atr
    if not (p.orw[0] <= ratio < p.orw[1]):
        return None
    if (p.spy_vol or p.spy_trend) and spy is None:
        return None                                   # a market filter with no market data takes nothing
    if p.spy_vol and not (spy.atr > 0 and spy.or_w / spy.atr >= p.spy_vol):
        return None
    for k in range(5, min(p.window_end, FLAT_IDX - 1, k_end)):
        c = x.c[k]
        side = 1 if c > x.or_h else -1 if c < x.or_l else 0
        if side == 0 or (p.sides == "long" and side < 0) or (p.sides == "short" and side > 0):
            continue
        if p.gap == "with" and not (x.gap == x.gap and x.gap * side > 0):
            continue
        if p.spy_trend and not ((spy.c[k] - spy.o[0]) * side > 0):
            continue
        level = x.or_h if side > 0 else x.or_l
        disp = abs(c - level) / x.or_w
        bv = x.v[k] / x.vol_base[k]
        vw_ok = (c > x.vwap[k]) == (side > 0)
        mk_ok = (bool(sa[k]) == (side > 0)) and (bool(qa[k]) == (side > 0))
        if disp < p.disp or bv < p.bvol:
            continue
        if p.market in ("vwap", "all") and not vw_ok:
            continue
        if p.market in ("idx", "all") and not mk_ok:
            continue
        ext = abs(c - x.vwap[k]) / x.atr
        if ext > p.ext:
            continue
        kk = k + p.delay
        if kk >= FLAT_IDX:
            return None
        raw = x.c[k] if p.delay == 0 else x.o[kk]
        entry = raw * (1 + side * p.slip)
        stop = stop_for(x, k, side, p.stop, level)
        if side * (entry - stop) <= 0 or abs(entry - stop) / entry > p.max_risk:
            return None
        return dict(k=k, kk=kk, sign=side, side="long" if side > 0 else "short", level=level,
                    entry=entry, stop=stop, target=entry + side * p.target * abs(entry - stop),
                    orw=ratio, disp=disp, bvol=bv, ext=ext, vwap_ok=vw_ok,
                    spy_ok=bool(sa[k]) == (side > 0), qqq_ok=bool(qa[k]) == (side > 0), spy_above=bool(sa[k]))
    return None


def trades(D: dict, dates: list, lab: dict, p: P) -> pd.DataFrame:
    rows = []
    spy, qqq = D["SPY"], D["QQQ"]
    for d in dates:
        if d not in lab:
            continue
        sa = spy[d].c > spy[d].vwap
        qa = qqq[d].c > qqq[d].vwap
        day_rows = []
        for s in select(D, d, p.universe):
            x = D[s][d]
            sig = first_signal(x, sa, qa, p, FLAT_IDX - 1, spy[d])
            if sig is None:
                continue
            r, j, why = exit_r(x, sig["kk"], sig["sign"], sig["entry"], sig["stop"], p)
            rps = abs(sig["entry"] - sig["stop"])
            day_rows.append(dict(
                sym=s, date=d, period=lab[d], side=sig["side"], k=sig["k"], R=float(r),
                hold=j - sig["kk"], why=why, pct=float(r) * rps / sig["entry"] * 100, risk_pct=rps / sig["entry"] * 100,
                rvol5=x.rvol5, orw=sig["orw"], disp=sig["disp"], bvol=sig["bvol"], ext=sig["ext"], gap=x.gap,
                vwap_ok=sig["vwap_ok"], spy_ok=sig["spy_ok"], qqq_ok=sig["qqq_ok"],
                spy_above=sig["spy_above"], spy_orw=spy[d].or_w / spy[d].atr if spy[d].atr else np.nan))
        # correlated-signal control: count same-side signals in the prior 10 minutes
        day_rows.sort(key=lambda r: r["k"])
        for r in day_rows:
            # the crowd as it can be known live: this signal plus same-side ones already seen
            r["crowd"] = sum(1 for q in day_rows if q["side"] == r["side"] and r["k"] - 10 <= q["k"] <= r["k"])
        if p.crowd:
            day_rows = [r for r in day_rows if r["crowd"] >= p.crowd]
        kept = []
        for r in day_rows:
            r["cluster"] = sum(1 for q in day_rows if q["side"] == r["side"] and r["k"] - 10 <= q["k"] < r["k"])
            if sum(1 for q in kept if q["side"] == r["side"] and r["k"] - 10 <= q["k"] <= r["k"]) < p.cluster_max:
                kept.append(r)
        rows += kept
    return pd.DataFrame(rows)


# ======================================================================= metrics
def stats(df: pd.DataFrame) -> dict:
    if df is None or len(df) == 0:
        return {"n": 0, "avg": np.nan, "pf": np.nan}
    r = df["R"].to_numpy(float)
    w, l = r[r > 0], r[r <= 0]
    eq = np.cumsum(r)
    dd = float((np.maximum.accumulate(np.concatenate([[0], eq]))[1:] - eq).max())
    daily = df.groupby("date")["R"].sum()
    sd, dn = daily.std(), daily[daily < 0].std()
    boot = RNG.choice(r, size=(1000, len(r))).mean(axis=1) if len(r) >= 5 else np.array([np.nan])
    top2 = np.sort(r)[:-2].mean() if len(r) > 2 else np.nan
    return dict(n=len(r), win=100 * len(w) / len(r), avg_w=float(w.mean()) if len(w) else 0.0,
                avg_l=float(l.mean()) if len(l) else 0.0, avg=float(r.mean()), total=float(r.sum()),
                pf=float(w.sum() / -l.sum()) if l.sum() < 0 else float("inf"), dd=dd,
                sharpe=float(daily.mean() / sd * math.sqrt(252)) if sd > 0 else 0.0,
                sortino=float(daily.mean() / dn * math.sqrt(252)) if dn and dn > 0 else 0.0,
                hold=float(df["hold"].mean()), hold_med=float(df["hold"].median()),
                ci=(float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))), no_top2=float(top2))


def per(df: pd.DataFrame) -> dict:
    return {k: stats(df[df.period == k] if len(df) else df) for k in ("train", "val", "test")}


def adopt(cur: dict, cand: dict, cand_2x: dict) -> tuple[bool, str]:
    ct, cv, nt, nv, nv2 = cur["train"], cur["val"], cand["train"], cand["val"], cand_2x["val"]
    if nv["n"] < 60:
        return False, f"too few validation trades ({nv['n']})"
    if not nv["avg"] >= cv["avg"] + 0.03:
        return False, "no validation gain"
    if nt["avg"] < ct["avg"]:
        return False, "worse on train"
    if nv["pf"] < cv["pf"]:
        return False, "validation PF lower"
    if not nv["no_top2"] >= cv["avg"]:
        return False, "gain rests on 2 trades"
    if nv2["avg"] < cv["avg"]:
        return False, "gain gone at 2x slippage"
    return True, "ADOPT"


# ======================================================================= report
def cell(s: dict) -> str:
    if s["n"] == 0:
        return "0 | | | | |"
    return f"{s['n']} | {s['win']:.0f}% | {s['avg']:+.3f} | {s['pf']:.2f} | {s['ci'][0]:+.2f} to {s['ci'][1]:+.2f}"


def fam_table(rows: list[tuple[str, dict, str]], show_test=False) -> list[str]:
    hdr = "| variant | verdict | train: n | win | avg R | PF | 95% CI | val: n | win | avg R | PF | 95% CI |"
    sep = "|---|---|" + "---|" * 10
    if show_test:
        hdr += " test: n | win | avg R | PF | 95% CI |"
        sep += "---|" * 5
    L = [hdr, sep]
    for nm, st, why in rows:
        L.append(f"| {nm} | {why} | {cell(st['train'])} | {cell(st['val'])} |" + (f" {cell(st['test'])} |" if show_test else ""))
    return L


def full(name: str, s: dict) -> str:
    if s["n"] == 0:
        return f"| {name} | 0 |" + " |" * 13
    return (f"| {name} | {s['n']} | {s['win']:.1f}% | {s['avg_w']:+.2f} | {s['avg_l']:+.2f} | {s['avg']:+.3f} | {s['pf']:.2f} | "
            f"{s['total']:+.1f} | {s['dd']:.1f} | {s['sharpe']:.2f} | {s['sortino']:.2f} | {s['hold']:.0f} | {s['hold_med']:.0f} | "
            f"{s['ci'][0]:+.2f} to {s['ci'][1]:+.2f} |")


FULLH = ("| version | trades | win % | avg win R | avg loss R | expectancy R | PF | total R | max DD R | Sharpe | Sortino | "
         "avg hold min | median hold min | 95% CI expectancy |\n|" + "---|" * 14)


def buckets(df: pd.DataFrame, col: str, edges: list, title: str) -> list[str]:
    L = [f"#### {title}", "", "| bucket | trades | win % | expectancy R | PF |", "|---|---|---|---|---|"]
    lab = pd.cut(df[col], edges, right=False) if edges else df[col]
    for k, g in df.groupby(lab, observed=True):
        s = stats(g)
        L.append(f"| {k} | {s['n']} | {s['win']:.0f} | {s['avg']:+.3f} | {s['pf']:.2f} |")
    return L + [""]


def _row(name: str, df: pd.DataFrame) -> str:
    s = stats(df)
    if s["n"] == 0:
        return f"| {name} | 0 | | | | |"
    return (f"| {name} | {s['n']} | {s['win']:.0f}% | {df.pct.mean():+.3f}% | {s['avg']:+.3f} | {s['pf']:.2f} |")


def diagnose(run, cur: P, t0: pd.DataFrame, tf: pd.DataFrame, tried: int) -> list[str]:
    """Is the candidate real or a lucky stretch? Run after the test was seen,
    so nothing here may be used to pick rules - it is for judging them."""
    H = "| {} | trades | win % | avg % per trade (price) | expectancy R | PF |\n|---|---|---|---|---|---|"
    L = ["## 8. Source of the result (diagnostics, run after the test; not used to choose rules)", ""]

    se = math.sqrt(2 * math.log(max(tried, 2)))
    L += [f"Variants tried in the staged search: {tried}. Noise floor sqrt(2 ln N) = {se:.2f} standard errors.", ""]
    for nm, df in (("candidate", tf),):
        for k in ("train", "val", "test"):
            r = df[df.period == k].R
            if len(r) > 2:
                t = r.mean() / (r.std() / math.sqrt(len(r)))
                L.append(f"- {nm} {k}: t = {t:+.2f} ({'above' if t > se else 'below'} the noise floor)")
    L += [""]

    L += ["### Month by month (all periods)", "", H.format("month / version")]
    for m in sorted(set(pd.to_datetime(tf.date).dt.to_period("M")) | set(pd.to_datetime(t0.date).dt.to_period("M"))):
        for nm, df in (("static 10", t0), ("candidate", tf)):
            g = df[pd.to_datetime(df.date).dt.to_period("M") == m]
            L.append(_row(f"{m} {nm}", g))
    L += [""]

    L += ["### How trades end", "", "| version | period | stop % | target % | bell % | avg R at stop | avg R at target | avg R at bell |", "|---|---|---|---|---|---|---|---|"]
    for nm, df in (("static 10", t0), ("candidate", tf)):
        for k in ("train", "val", "test"):
            g = df[df.period == k]
            if not len(g):
                continue
            sh = g.why.value_counts(normalize=True) * 100
            av = g.groupby("why").R.mean()
            L.append(f"| {nm} | {k} | {sh.get('stop', 0):.0f} | {sh.get('target', 0):.0f} | {sh.get('bell', 0):.0f} | "
                     f"{av.get('stop', float('nan')):+.2f} | {av.get('target', float('nan')):+.2f} | {av.get('bell', float('nan')):+.2f} |")
    L += [""]

    # Is the OR-width gain a real effect, or only cheaper costs? A wide range means a
    # wide stop, so the same 0.05% slippage is a smaller slice of 1R.
    L += ["### OR width: real effect or just smaller costs in R?", "",
          "Top 10 by opening volume, no width filter, all periods.", "",
          "| OR width / ATR | trades | median stop distance % | gross R (no slippage) | net R | win % gross |", "|---|---|---|---|---|---|"]
    base_u = replace(cur, orw=(0.0, 9e9))
    net, gross = run(base_u), run(replace(base_u, slip=0.0))
    for lo, hi in ((0, 0.2), (0.2, 0.35), (0.35, 0.5), (0.5, 0.75), (0.75, 9e9)):
        n_ = net[(net.orw >= lo) & (net.orw < hi)]
        g_ = gross[(gross.orw >= lo) & (gross.orw < hi)]
        if len(n_):
            L.append(f"| {lo:g}-{hi:g} | {len(n_)} | {n_.risk_pct.median():.2f}% | {g_.R.mean():+.3f} | {n_.R.mean():+.3f} | {100 * (g_.R > 0).mean():.0f}% |")
    L += [""]

    L += ["### Neighbours of the chosen settings (plateau check, every period)", "",
          "| universe | min OR width / ATR | train avg R | val avg R | test avg R | test trades |", "|---|---|---|---|---|---|"]
    for u in ("top5", "top10", "top20"):
        for lo in (0.25, 0.30, 0.35, 0.40, 0.50):
            st = per(run(replace(cur, universe=u, orw=(lo, 9e9))))
            L.append(f"| {u} | {lo:.2f} | {st['train']['avg']:+.3f} | {st['val']['avg']:+.3f} | {st['test']['avg']:+.3f} | {st['test']['n']} |")
    L += [""]

    te = tf[tf.period == "test"]
    if len(te) > 10:
        days = te.groupby("date").R.sum().sort_values()
        syms = te.groupby("sym").R.sum().sort_values()
        L += ["### How concentrated is the test result?", "",
              f"- Test total {te.R.sum():+.1f}R over {te.date.nunique()} days and {len(te)} trades.",
              f"- Without the best 2 days: {te[~te.date.isin(days.index[-2:])].R.mean():+.3f}R per trade.",
              f"- Without the best 5 trades: {np.sort(te.R.to_numpy())[:-5].mean():+.3f}R per trade.",
              f"- Best 3 stocks ({', '.join(syms.index[-3:])}) made {syms.iloc[-3:].sum():+.1f}R; without them {te[~te.sym.isin(syms.index[-3:])].R.mean():+.3f}R per trade.",
              f"- Winning days {100 * (days > 0).mean():.0f}% of {len(days)}.", ""]
        L += ["#### Test by side", "", H.format("side")]
        for sd, g in te.groupby("side"):
            L.append(_row(sd, g))
        L += [""]
    return L


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=252)
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args(argv)
    D, common = build(load(args.days, args.refresh))
    dates = common[-args.days:]
    a, b = int(len(dates) * 0.6), int(len(dates) * 0.8)
    lab = {d: ("train" if i < a else "val" if i < b else "test") for i, d in enumerate(dates)}
    run = lambda p: trades(D, dates, lab, p)
    L = ["# ORB on stocks in play", "",
         f"IEX 1-minute bars, {len(dates)} sessions ({dates[0]} to {dates[-1]}): train {a}, validation {b - a}, "
         f"test {len(dates) - b}. Pool {len(POOL)} symbols (hand-assembled earlier: some survivorship bias). "
         "0.05% slippage per side unless stated. Stages decided on train + validation; test run once at the end.", ""]

    # ---------------------------------------------------------------- stage 0: baseline
    p0 = P()
    t0 = run(p0)
    base = per(t0)
    L += ["## 1. Baseline: the live rule on the static 10", "", FULLH]
    for k in ("train", "val"):
        L.append(full(f"static 10, {k}", base[k]))
    L += [""]
    L += buckets(t0, "side", [], "By side (train+val)") if False else []

    # ---------------------------------------------------------------- staged search
    cur, cur_st = p0, base
    log = []
    tried = [0]

    def stage(title: str, cands: list[tuple[str, P]], note: str = ""):
        nonlocal cur, cur_st
        rows, best = [("current", cur_st, "incumbent")], None
        tried[0] += len(cands)
        for nm, p in cands:
            t = run(p)
            st = per(t)
            st2 = per(run(replace(p, slip=cur.slip * 2)))
            ok, why = adopt(cur_st, st, st2)
            rows.append((nm, st, why))
            if ok and (best is None or st["val"]["avg"] > best[1]["val"]["avg"]):
                best = (nm, st, p)
        L.extend([f"### {title}", ""] + ([note, ""] if note else []) + fam_table(rows) + [""])
        if best:
            log.append(f"{title}: **{best[0]}** (validation expectancy {cur_st['val']['avg']:+.3f}R -> {best[1]['val']['avg']:+.3f}R)")
            cur, cur_st = best[2], best[1]
        else:
            log.append(f"{title}: no change")

    L += ["## 2. Feature-by-feature research (staged; each stage starts from the rules adopted so far)", ""]
    stage("Universe: stocks in play vs the static 10",
          [(f"top {n} by opening relative volume", replace(cur, universe=f"top{n}")) for n in (10, 20, 30)],
          "Ranked at 09:35 by first-5-minute volume vs its 14-session average; price >= 5 and 14-day average dollar volume >= 50M. Nothing about past trade results is used.")
    stage("OR width / daily ATR",
          [(f"{lo:g}-{hi:g}", replace(cur, orw=(lo, hi))) for lo, hi in ((0.0, 0.1), (0.1, 0.2), (0.2, 0.35), (0.35, 9e9), (0.1, 0.35))],
          "Fixed buckets, not fitted percentiles.")
    stage("Market / VWAP confirmation",
          [("B: stock VWAP only", replace(cur, market="vwap")), ("C: SPY and QQQ", replace(cur, market="idx")),
           ("D: stock + SPY + QQQ", replace(cur, market="all"))])
    stage("Breakout displacement (close past the level / OR width)",
          [(f">= {x}", replace(cur, disp=x)) for x in (0.1, 0.25, 0.5)])
    stage("Breakout-minute relative volume (vs that minute's 14-day average)",
          [(f">= {x}x", replace(cur, bvol=x)) for x in (1.25, 1.5, 2.0)])
    stage("Direction", [("long only", replace(cur, sides="long")), ("short only", replace(cur, sides="short"))])
    stage("Extension (|close - VWAP| / daily ATR)", [(f"<= {x}", replace(cur, ext=x)) for x in (0.25, 0.5, 1.0)])
    stage("Entry window", [(f"until {9 + (30 + m) // 60}:{(30 + m) % 60:02d}", replace(cur, window_end=m)) for m in (10, 15, 20, 45, 60)])
    stage("Stop (live: D, session extreme)",
          [("A: opposite side of OR", replace(cur, stop="A")), ("B: level - 0.1 ATR", replace(cur, stop="B")),
           ("C: 5-minute swing - 0.02 ATR", replace(cur, stop="C"))])
    stage("Target", [(f"{x}R", replace(cur, target=x)) for x in (1.0, 1.5, 2.5, 3.0)])
    stage("Trade management", [("half at 1R + runner to 3R", replace(cur, manage="partial")),
                               ("trail 1R behind the best price after 1R", replace(cur, manage="trail")),
                               ("trail 1R behind the best close after 1R", replace(cur, manage="ctrail"))])
    stage("Correlated signals (max same-side signals in 10 min)", [(f"max {x}", replace(cur, cluster_max=x)) for x in (1, 2, 3)])

    # Follow-up, pre-registered 3 Oct 2026. The opening-range autopsy (15-minute
    # range, static names, a crowd count that also used LATER breaks) found
    # "with the gap" and "gap + crowd of 5+" positive on both its splits. Tested
    # here the production way: 5-minute range, the adopted selection, and a crowd
    # counted only from signals already seen. Same adoption rule as every stage.
    stage("Overnight gap direction (follow-up)", [("only breaks with the gap", replace(cur, gap="with"))])
    stage("Crowd, prior-only (follow-up)", [("5+ same-side signals in the last 10 min", replace(cur, crowd=5)),
                                            ("gap AND 5+ crowd", replace(cur, gap="with", crowd=5))])

    # ---------------------------------------------------------------- final: test once
    tf = run(cur)
    fin = per(tf)
    L += ["## 3. Decisions", ""] + [f"- {x}" for x in log] + ["", f"Final candidate: `{cur}`", ""]
    L += ["## 4. Train, validation and the untouched test", "", FULLH]
    for nm, st in (("baseline (static 10, live rule)", base), ("candidate", fin)):
        for k in ("train", "val", "test"):
            L.append(full(f"{nm} - {k}", st[k]))
    L += ["", f"Test-period verdict: candidate expectancy {fin['test']['avg']:+.3f}R "
          f"(95% CI {fin['test']['ci'][0]:+.2f} to {fin['test']['ci'][1]:+.2f}) on {fin['test']['n']} trades; "
          + ("positive and its interval excludes zero." if fin['test']['ci'][0] > 0 else
             "positive, but the interval includes zero - not proven." if fin['test']['avg'] > 0 else
             "NOT positive. No robust edge found."), ""]

    # ---------------------------------------------------------------- autopsy replication
    L += ["## 4b. The autopsy's filters, re-run the production way (diagnostic)", "",
          "Live rule, 5-minute range. Not used to choose anything; shows whether the autopsy's result carries over.", ""]
    L += fam_table([(nm, per(run(pp)), "") for nm, pp in (
        ("static 10, no filter", p0), ("static 10, with the gap", replace(p0, gap="with")),
        ("static 10, crowd 5+ (prior-only)", replace(p0, crowd=5)),
        ("static 10, gap AND crowd 5+", replace(p0, gap="with", crowd=5)),
        ("top 10 in play, with the gap", replace(p0, universe="top10", gap="with")),
        ("final candidate, with the gap", replace(cur, gap="with")))], show_test=True) + [""]

    # ---------------------------------------------------------------- slippage per period + gate
    L += ["## 4c. Slippage by period (final candidate)", "",
          "| slippage per side | train avg R | train PF | val avg R | val PF | test avg R | test PF | test win % |", "|---|---|---|---|---|---|---|---|"]
    by_slip = {}
    for sl in (0.0005, 0.001, 0.0015):
        st = per(run(replace(cur, slip=sl)))
        by_slip[sl] = st
        L.append(f"| {sl * 100:.2f}% | {st['train']['avg']:+.3f} | {st['train']['pf']:.2f} | {st['val']['avg']:+.3f} | "
                 f"{st['val']['pf']:.2f} | {st['test']['avg']:+.3f} | {st['test']['pf']:.2f} | {st['test']['win']:.1f}% |")
    te = tf[tf.period == "test"]
    top3 = te.groupby("sym").R.sum().sort_values().index[-3:] if len(te) else []
    gate = [
        ("test expectancy > 0 at 0.05%", fin["test"]["avg"] > 0),
        ("test 95% interval above zero at 0.05%", fin["test"]["ci"][0] > 0),
        ("test expectancy > 0 at 0.10%", by_slip[0.001]["test"]["avg"] > 0),
        ("validation expectancy > 0 at 0.10%", by_slip[0.001]["val"]["avg"] > 0),
        ("test > 0 without its best 3 stocks", len(te) > 0 and te[~te.sym.isin(top3)].R.mean() > 0),
        ("beats the live rule on train, validation and test",
         all(fin[k]["avg"] > base[k]["avg"] for k in ("train", "val", "test"))),
    ]
    passed = all(ok for _, ok in gate)
    L += ["", "### Go-live gate (fixed before the run)", ""] + [f"- {'PASS' if ok else 'FAIL'}: {nm}" for nm, ok in gate]
    L += ["", f"**Gate: {'PASSED' if passed else 'FAILED'}.** 0.15% is reported, not gated: it is the stress case.", ""]

    # ---------------------------------------------------------------- slippage / delay
    L += ["## 5. Execution sensitivity (candidate, validation + test)", "", "| slippage per side | delay | trades | expectancy R | PF |", "|---|---|---|---|---|"]
    for sl in (0.0002, 0.0005, 0.001, 0.0015):
        for dl in (0, 1):
            t = run(replace(cur, slip=sl, delay=dl))
            t = t[t.period != "train"] if len(t) else t
            s = stats(t)
            L.append(f"| {sl * 100:.2f}% | {'next minute open' if dl else 'breakout close'} | {s['n']} | {s['avg']:+.3f} | {s['pf']:.2f} |")
    L += [""]

    # ---------------------------------------------------------------- diagnostics on the candidate
    if len(tf):
        eq = tf.sort_values(["date", "k"])
        cum = eq.R.cumsum().to_numpy()
        peak = np.maximum.accumulate(np.concatenate([[0], cum]))[1:]
        L += ["## 6. Drawdown (candidate, all periods)", "",
              f"Max drawdown {float((peak - cum).max()):.1f}R; longest losing streak {stats(tf).get('n') and int(max((len(s) for s in ''.join('1' if r <= 0 else '0' for r in eq.R).split('0')), default=0))} trades.", ""]
        L += ["## 7. Breakdowns (candidate, train + validation)", ""]
        tv = tf[tf.period != "test"]
        L += buckets(tv, "side", [], "Long vs short")
        L += buckets(tv, "k", [5, 10, 15, 20, 30, 61], "Breakout minute (5 = 09:35)")
        L += buckets(tv, "orw", [0, 0.1, 0.2, 0.35, 99], "OR width / ATR")
        L += buckets(tv, "rvol5", [0, 1, 1.5, 2, 3, 999], "Opening relative volume")
        L += buckets(tv, "bvol", [0, 1, 1.5, 2, 3, 999], "Breakout-minute relative volume")
        L += buckets(tv, "cluster", [0, 1, 2, 4, 99], "Same-side signals in the prior 10 min")
        L += buckets(tv.assign(regime=np.where(tv.spy_above, "SPY above VWAP", "SPY below VWAP")), "regime", [], "Market regime at the signal")
        L += buckets(tv, "spy_orw", [0, 0.1, 0.2, 99], "SPY opening volatility (SPY OR width / ATR)")
        score = (tv.vwap_ok.astype(int) + tv.spy_ok.astype(int) + tv.qqq_ok.astype(int) + (tv.bvol >= 1.5).astype(int)
                 + (tv.disp >= 0.25).astype(int) + (tv.ext <= 0.5).astype(int) + (tv.cluster == 0).astype(int))
        L += buckets(tv.assign(score=score), "score", [], "Setup-quality score (0-7; research only)")
        bys = tv.groupby("sym").R.agg(["count", "mean", "sum"]).sort_values("sum")
        L += ["#### By stock (train + validation; 10 worst and 10 best by total R)", "", "| stock | trades | expectancy R | total R |", "|---|---|---|---|"]
        for s, r in pd.concat([bys.head(10), bys.tail(10)]).iterrows():
            L.append(f"| {s} | {int(r['count'])} | {r['mean']:+.3f} | {r['sum']:+.1f} |")
        L += [""]

    if len(tf):
        L += diagnose(run, cur, t0, tf, tried[0])

    out = "\n".join(L) + "\n"
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(out)
    REPORT.with_suffix(".json").write_text(json.dumps(
        {"sessions": len(dates), "candidate": str(cur), "decisions": log, "gate_passed": passed,
         "gate": {nm: bool(ok) for nm, ok in gate},
         "test": {k: v for k, v in fin["test"].items() if k != "ci"}, "test_ci": fin["test"].get("ci")}, indent=1, default=str))
    print(out[:6000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
