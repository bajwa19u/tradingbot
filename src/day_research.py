"""Day-trade research: the live rules on 12 months of IEX minute bars, then
one change at a time.

Everything is measured in R (1R = the trade's initial stop distance; a full
stop is about -1R / -1% of the account at the live sizing). The live code is
reused wherever it exists - `opening.day_trades` with the live OPENING
settings, `retest.breaks_in` / `find_retest` with the live scan - so the
baseline is the bot as it runs, not a re-implementation of it.

Dates are split in order: 60% train, 20% validation, 20% test. A change is
adopted only if, fixed before running:
  1. train: at least 30 trades, average R up by 0.05 or more, profit factor not lower
  2. validation: at least 15 trades and average R not lower than the baseline's
  3. a numeric setting also needs a neighbouring value that passes 1
The test period is reported for everything and used for nothing.

Usage: python -m src.day_research [--days 365] [--refresh]
"""
from __future__ import annotations

import argparse
import json
import math
import pickle
import sys

import numpy as np
import pandas as pd

from . import opening as op
from .config import REPO_ROOT, Credentials
from .data import MarketData
from .forensics import LIVE as WATCHLIST
from .live_bot import LIVE as RLIVE, OPENING, SCAN, STOP_ATR, TARGET_R
from .retest import breaks_in, find_retest
from .squeeze import prepare_sq

EASTERN = op.EASTERN
CACHE = REPO_ROOT / "cache" / "minute_iex.pkl"
REPORT = REPO_ROOT / "reports" / "day_research.md"
SLIP = op.SLIP_PCT / 100.0
FLAT = pd.Timestamp(op.FORCE_EXIT).time()
RNG = np.random.default_rng(7)


# ============================================================== data
def load(days: int, refresh: bool) -> dict[str, pd.DataFrame]:
    """1-minute IEX bars, 04:00-15:59, for the watchlist. Cached; topped up."""
    now = pd.Timestamp.now(tz=EASTERN)
    data: dict[str, pd.DataFrame] = {}
    if CACHE.exists() and not refresh:
        data = pickle.loads(CACHE.read_bytes())
    start = (now - pd.Timedelta(days=int(days * 1.45) + 10)).date()
    have = min((df.index[-1] for df in data.values() if len(df)), default=None)
    first = min((df.index[0] for df in data.values() if len(df)), default=None)
    md = MarketData(Credentials.from_env(), feed="iex")
    if have is None or first is None or first.date() > start + pd.Timedelta(days=7):
        fetch_from = start
        data = {}
    else:
        fetch_from = have.date()
    fresh = md.intraday_bars(WATCHLIST, 1, start=fetch_from.isoformat(), extended=True)
    for s, df in fresh.items():
        old = data.get(s)
        df = df if old is None else pd.concat([old, df])
        data[s] = df[~df.index.duplicated(keep="last")].sort_index()
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_bytes(pickle.dumps(data))
    return data


def sessions(data: dict[str, pd.DataFrame]) -> dict[str, dict]:
    """{symbol: {date: day_ext}} with only complete regular sessions."""
    out = {}
    for s, df in data.items():
        out[s] = {d: ext for d, ext in op.by_day(df)
                  if len(op.split_session(ext)[1]) >= 300}
    return out


def splits(dates: list) -> dict:
    n = len(dates)
    a, b = int(n * 0.6), int(n * 0.8)
    lab = {}
    for i, d in enumerate(sorted(dates)):
        lab[d] = "train" if i < a else "val" if i < b else "test"
    return lab


# ============================================================== metrics
def stats(r, days=None, hold=None) -> dict:
    r = np.asarray(r, dtype=float)
    n = len(r)
    if n == 0:
        return {"n": 0}
    w, l = r[r > 0], r[r <= 0]
    eq = np.cumsum(r)
    dd = float((np.maximum.accumulate(np.concatenate([[0], eq]))[1:] - eq).max())
    streak = lambda mask: max((len(x) for x in "".join("1" if m else "0" for m in mask).split("0")), default=0)
    out = dict(n=n, wins=len(w), losses=len(l), win=100 * len(w) / n,
               avg_w=float(w.mean()) if len(w) else 0.0, avg_l=float(l.mean()) if len(l) else 0.0,
               avg=float(r.mean()), med=float(np.median(r)), total=float(r.sum()),
               pf=float(w.sum() / -l.sum()) if l.sum() < 0 else float("inf"),
               dd=dd, maxl=streak(r <= 0), maxw=streak(r > 0))
    if n >= 5:
        boot = RNG.choice(r, size=(1000, n)).mean(axis=1)
        out["ci"] = (float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5)))
    if days is not None:
        d = pd.Series(r).groupby(np.asarray(days)).sum()
        sd, dn = d.std(), d[d < 0].std()
        out["sharpe"] = float(d.mean() / sd * math.sqrt(252)) if sd > 0 else 0.0
        out["sortino"] = float(d.mean() / dn * math.sqrt(252)) if dn and dn > 0 else 0.0
    if hold is not None:
        out["hold"] = float(np.mean(hold))
    return out


# ============================================================== exits
def run_exit(rth: pd.DataFrame, j: int, side: str, entry: float, stop: float,
             target_r: float = 2.0, be_at: float | None = None,
             partial: bool = False, trail: float | None = None) -> tuple[float, int, str]:
    """One trade from bar j's close. Stop first on ties; out at 15:55's close.
    Returns (R after slippage on the exit, exit bar, reason)."""
    s = 1 if side == "long" else -1
    rps = abs(entry - stop)
    h, l, c = (rth[x].to_numpy(float) for x in ("high", "low", "close"))
    times = rth.index.tz_convert(EASTERN).time
    tgt = entry + s * target_r * rps
    cur, best, banked, weight = stop, entry, 0.0, 1.0
    fill = lambda px: px * (1 - s * SLIP)                         # exit slippage against us

    def r_of(px):
        return s * (fill(px) - entry) / rps

    for k in range(j + 1, len(rth)):
        hit_stop = l[k] <= cur if s > 0 else h[k] >= cur
        if hit_stop:
            return banked + weight * r_of(cur), k, "stop"
        if partial and weight == 1.0 and (h[k] >= entry + rps if s > 0 else l[k] <= entry - rps):
            banked, weight, cur = 0.5 * r_of(entry + s * rps), 0.5, entry   # half off at 1R, rest at breakeven
            tgt = entry + s * 3.0 * rps
        if h[k] >= tgt if s > 0 else l[k] <= tgt:
            return banked + weight * r_of(tgt), k, "target"
        if times[k] >= FLAT:
            return banked + weight * r_of(c[k]), k, "bell"
        if be_at is not None and (h[k] >= entry + be_at * rps if s > 0 else l[k] <= entry - be_at * rps):
            cur = entry if s > 0 and cur < entry or s < 0 and cur > entry else cur
        if trail is not None:
            best = max(best, c[k]) if s > 0 else min(best, c[k])
            if s * (best - entry) >= rps:
                ts = best - s * trail * rps
                cur = max(cur, ts) if s > 0 else min(cur, ts)
    return banked + weight * r_of(c[-1]), len(rth) - 1, "bell"


# ============================================================== features
def day_frame(ext: pd.DataFrame) -> pd.DataFrame:
    """Regular session with running VWAP and cumulative volume."""
    _, rth = op.split_session(ext)
    rth = rth.copy()
    tp = (rth["high"] + rth["low"] + rth["close"]) / 3
    rth["vwap"] = (tp * rth["volume"]).cumsum() / rth["volume"].cumsum().replace(0, np.nan)
    rth["cumvol"] = rth["volume"].cumsum()
    return rth


def daily_table(days: dict) -> pd.DataFrame:
    rows = []
    for d, ext in sorted(days.items()):
        _, r = op.split_session(ext)
        rows.append({"date": d, "o": float(r["open"].iloc[0]), "h": float(r["high"].max()),
                     "l": float(r["low"].min()), "c": float(r["close"].iloc[-1])})
    t = pd.DataFrame(rows).set_index("date")
    pc = t["c"].shift(1)
    tr = pd.concat([t["h"] - t["l"], (t["h"] - pc).abs(), (t["l"] - pc).abs()], axis=1).max(axis=1)
    t["atr_prev"] = tr.rolling(14).mean().shift(1)          # known before the open
    t["prev_c"] = pc
    t["ret5_prev"] = t["c"].shift(1) / t["c"].shift(6) - 1
    t["atrpct_prev"] = t["atr_prev"] / pc
    return t


# ============================================================== ORB
def orb_trades(S: dict, lab: dict, mkt_frames: dict, dailies: dict) -> pd.DataFrame:
    """Baseline opening-range trades with the features known at the entry bar."""
    rows = []
    for sym, days in S.items():
        dates = sorted(days)
        frames = {d: day_frame(days[d]) for d in dates}
        dt = dailies[sym]
        for k in range(1, len(dates)):
            d = dates[k]
            if d not in lab:
                continue
            _, prior = op.split_session(days[dates[k - 1]])
            for t in op.day_trades(days[d], prior, OPENING):
                rth = frames[d]
                hhmm = t["entry_time"]
                j = int(np.flatnonzero(rth.index.strftime("%H:%M") == hhmm)[0])
                side, entry, stop = t["side"], float(t["entry"]), float(t["stop"])
                # relative volume: volume to this minute vs the same minutes on the prior 14 sessions
                past = [frames[x] for x in dates[max(0, k - 14):k]]
                base = [float(p["cumvol"].iloc[min(j, len(p) - 1)]) for p in past if len(p)]
                rvol = float(rth["cumvol"].iloc[j]) / np.mean(base) if base and np.mean(base) > 0 else np.nan
                row = dt.loc[d]
                gap = row["o"] / row["prev_c"] - 1 if row["prev_c"] else np.nan
                vw = float(rth["vwap"].iloc[j])
                close_j = float(rth["close"].iloc[j])
                ts = rth.index[j]
                mk = {}
                for m in ("SPY", "QQQ"):
                    f = mkt_frames.get(m, {}).get(d)
                    if f is not None and ts in f.index:
                        mk[m] = float(f.loc[ts, "close"]) > float(f.loc[ts, "vwap"])
                    else:
                        mk[m] = None
                s = 1 if side == "long" else -1
                brk_vol = float(rth["volume"].iloc[j]) / max(float(rth["volume"].iloc[:5].mean()), 1.0)
                rows.append(dict(
                    sym=sym, date=d, period=lab[d], side=side, entry_time=hhmm, j=j,
                    entry=entry, stop=stop, R=float(t["pct"]) / OPENING.get("risk_pct", 1.0),
                    reason=t["reason"],
                    hold=((int(t["exit_time"][:2]) * 60 + int(t["exit_time"][3:5])) - (ts.hour * 60 + ts.minute))
                    if t.get("exit_time") else np.nan,
                    rvol=rvol, gap=gap, gap_aligned=(gap > 0) == (s > 0) if gap == gap else None,
                    vwap_aligned=(close_j > vw) == (s > 0),
                    spy_aligned=None if mk["SPY"] is None else mk["SPY"] == (s > 0),
                    qqq_aligned=None if mk["QQQ"] is None else mk["QQQ"] == (s > 0),
                    ext_atr=abs(close_j - vw) / row["atr_prev"] if row["atr_prev"] == row["atr_prev"] else np.nan,
                    brk_vol=brk_vol, hour=ts.hour, weekday=ts.day_name()[:3],
                    stop_pct=abs(entry - stop) / entry * 100))
    df = pd.DataFrame(rows)
    return df


# ============================================================== retest
def five_min(rth: pd.DataFrame) -> pd.DataFrame:
    return rth.resample("5min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["open"])


def confirm_ok(day: pd.DataFrame, j: int, side: str, level: float, a: float, mode: str) -> bool:
    if mode == "none":
        return True
    o, h, l, c = (float(day[x].iloc[j]) for x in ("open", "high", "low", "close"))
    rng = max(h - l, 1e-9)
    s = 1 if side == "long" else -1
    if mode == "candle":                                    # bullish candle for longs, bearish for shorts
        return (c > o) if s > 0 else (c < o)
    if mode == "wick":                                      # rejection wick at least half the bar
        return ((min(o, c) - l) if s > 0 else (h - max(o, c))) >= 0.5 * rng
    if mode == "away":                                      # closed back away from the level
        return (c >= level + 0.1 * a) if s > 0 else (c <= level - 0.1 * a)
    if mode == "engulf":
        if j == 0:
            return False
        po, pc = float(day["open"].iloc[j - 1]), float(day["close"].iloc[j - 1])
        return (c > po and o < pc) if s > 0 else (c < po and o > pc)
    raise ValueError(mode)


def retest_trades(S: dict, lab: dict, sides="short", vol_mult=None, squeeze=None,
                  confirm="none", warm="today") -> pd.DataFrame:
    p = {**SCAN, "tail": 0}
    if vol_mult is not None:
        p["vol_mult"] = vol_mult
    if squeeze is not None:
        p["squeeze_atr"] = squeeze
    rows = []
    for sym, days in S.items():
        dates = sorted(days)
        five = {d: five_min(op.split_session(days[d])[1]) for d in dates}
        for k, d in enumerate(dates):
            if d not in lab:
                continue
            today = five[d]
            if warm == "prior" and k > 0:
                full = pd.concat([five[dates[k - 1]], today])
                offset = len(five[dates[k - 1]])
            else:
                full, offset = today, 0
            if len(full) < p["base_len"] + p["atr_len"] + 3:
                continue
            day = prepare_sq(full, p)
            for i, side, level in breaks_in(day, p):
                if i < offset or (sides != "both" and side != sides):
                    continue
                j = find_retest(day, i, side, level, RLIVE["wait"], RLIVE["depth"], False)
                if j is None:
                    continue
                a = float(day["atr"].iloc[i])
                if not confirm_ok(day, j, side, level, a, confirm):
                    continue
                s = 1 if side == "long" else -1
                entry = float(day["close"].iloc[j]) * (1 + s * SLIP)
                stop = level - s * STOP_ATR * a
                rps = abs(entry - stop)
                if rps <= 0 or rps / entry > 0.10 or s * (entry - stop) <= 0:
                    continue
                R, kx, why = run_exit(day, j, side, entry, stop, target_r=TARGET_R)
                rows.append(dict(sym=sym, date=d, period=lab[d], side=side, R=R, reason=why,
                                 hour=day.index[j].hour, weekday=day.index[j].day_name()[:3],
                                 hold=(day.index[kx] - day.index[j]).total_seconds() / 60))
    return pd.DataFrame(rows)


# ============================================================== decision
def by_period(df: pd.DataFrame, col="R") -> dict:
    out = {}
    for per in ("train", "val", "test"):
        x = df[df.period == per] if len(df) else df
        out[per] = stats(x[col], x["date"], x["hold"] if "hold" in x else None) if len(x) else {"n": 0}
    return out


def verdict(base: dict, cand: dict) -> tuple[bool, str]:
    bt, bv, ct, cv = base["train"], base["val"], cand["train"], cand["val"]
    if ct.get("n", 0) < 30 or cv.get("n", 0) < 15:
        return False, "too few trades"
    if not (ct["avg"] >= bt["avg"] + 0.05 and ct["pf"] >= bt["pf"]):
        return False, "no train gain"
    if cv["avg"] < bv["avg"]:
        return False, "fails validation"
    return True, "passes"


def decide(family: list[tuple[str, dict, float | None]], base: dict) -> list[tuple[str, dict, str]]:
    """family: (name, per-period stats, numeric value or None). Adds the neighbour rule."""
    res = [(nm, st, *verdict(base, st), v) for nm, st, v in family]
    out = []
    nums = sorted({v for *_, v in res if v is not None})
    for nm, st, ok, why, v in res:
        if ok and v is not None and len(nums) > 1:
            i = nums.index(v)
            nbr = [x for x in (nums[i - 1] if i > 0 else None, nums[i + 1] if i + 1 < len(nums) else None) if x is not None]
            nbr_ok = any(verdict(base, s2)[0] or (s2["train"].get("n", 0) >= 30 and s2["train"]["avg"] >= base["train"]["avg"] + 0.05)
                         for _, s2, _, _, v2 in res if v2 in nbr)
            if not nbr_ok:
                ok, why = False, "lone spike"
        out.append((nm, st, "ADOPT" if ok else why))
    return out


# ============================================================== report
def fmt(s: dict) -> str:
    if not s or s.get("n", 0) == 0:
        return "| 0 | | | | | | | | |"
    ci = s.get("ci")
    return (f"| {s['n']} | {s['win']:.0f}% | {s['avg']:+.3f} | {s['med']:+.2f} | {s['total']:+.1f} | "
            f"{s['pf']:.2f} | {s['dd']:.1f} | {s.get('sharpe', 0):.2f} | "
            + (f"{ci[0]:+.2f} to {ci[1]:+.2f} |" if ci else " |"))


HEAD = ("| variant | verdict | period | trades | win | avg R | median R | total R | PF | max DD R | Sharpe | 95% CI avg R |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|---|")


def table(rows: list[tuple[str, dict, str]]) -> list[str]:
    L = [HEAD]
    for nm, st, why in rows:
        for per in ("train", "val", "test"):
            L.append(f"| {nm if per == 'train' else ''} | {why if per == 'train' else ''} | {per} " + fmt(st[per]))
    return L


def full_row(name: str, s: dict) -> str:
    if s.get("n", 0) == 0:
        return f"| {name} | 0 |" + " |" * 15
    return (f"| {name} | {s['n']} | {s['wins']} | {s['losses']} | {s['win']:.1f}% | {s['avg_w']:+.2f} | {s['avg_l']:+.2f} | "
            f"{s['avg']:+.3f} | {s['med']:+.2f} | {s['total']:+.1f} | {s['pf']:.2f} | {s['dd']:.1f} | {s['maxl']} | {s['maxw']} | "
            f"{s.get('sharpe', 0):.2f} | {s.get('sortino', 0):.2f} | {s.get('hold', 0):.0f} |")


FULL = ("| version | trades | wins | losses | win % | avg win R | avg loss R | avg R | median R | total R | PF | max DD R | "
        "max losing run | max winning run | Sharpe | Sortino | avg hold min |\n|" + "---|" * 17)


def breakdown(df: pd.DataFrame, col: str, title: str) -> list[str]:
    L = [f"#### {title}", "", "| " + col + " | trades | win % | avg R | total R | PF |", "|---|---|---|---|---|---|"]
    for k, g in df.groupby(col):
        s = stats(g["R"])
        L.append(f"| {k} | {s['n']} | {s['win']:.0f} | {s['avg']:+.3f} | {s['total']:+.1f} | {s['pf']:.2f} |")
    return L + [""]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args(argv)

    data = load(args.days, args.refresh)
    S = sessions(data)
    all_dates = sorted(set.intersection(*(set(v) for v in S.values() if v)))
    all_dates = all_dates[-args.days:] if len(all_dates) > args.days else all_dates
    lab = splits(all_dates[1:])                      # the first date only seeds "prior"
    mkt = {m: {d: day_frame(S[m][d]) for d in S[m]} for m in ("SPY", "QQQ") if m in S}
    dailies = {s: daily_table(days) for s, days in S.items()}
    per = {p: sum(1 for v in lab.values() if v == p) for p in ("train", "val", "test")}
    span = f"{min(lab)} to {max(lab)}"
    L = [f"# Day-trade research", "",
         f"IEX 1-minute bars, {len(lab)} sessions ({span}): train {per['train']}, validation {per['val']}, "
         f"test {per['test']} sessions, in date order. {len(WATCHLIST)} symbols. R = the trade's initial stop distance; "
         "0.05% slippage on entry and exit. Test results are shown but were not used for any decision.", ""]

    # ---------------- ORB baseline + re-simulation check
    orb = orb_trades(S, lab, mkt, dailies)
    frames = {(s, d): day_frame(S[s][d]) for s, d in set(zip(orb.sym, orb.date))}
    resim = [run_exit(frames[(t.sym, t.date)], t.j, t.side, t.entry, t.stop, 2.0)[0] for t in orb.itertuples()]
    match = float(np.mean(np.abs(np.array(resim) - orb.R.to_numpy()) < 0.05)) if len(orb) else 0
    base = by_period(orb)
    L += ["## 1. Baseline: the live opening-range rule", "",
          f"Re-simulation agrees with the live code on {100 * match:.0f}% of trades (within 0.05R).", "", FULL]
    for per in ("train", "val", "test"):
        x = orb[orb.period == per]
        L.append(full_row(f"ORB {per}", stats(x.R, x.date, x.hold)))
    L.append(full_row("ORB all", stats(orb.R, orb.date, orb.hold)))
    L.append("")
    L += breakdown(orb, "sym", "By ticker (all periods)") + breakdown(orb, "hour", "By hour") + \
        breakdown(orb, "weekday", "By weekday") + breakdown(orb, "side", "By side") + breakdown(orb, "reason", "How trades ended")

    # ---------------- ORB filters (one at a time)
    def filt(name, mask, v=None):
        return (name, by_period(orb[mask.fillna(False).astype(bool)]), v)

    fam_rvol = [filt(f"RVOL > {x}", orb.rvol > x, x) for x in (1.0, 1.5, 2.0, 3.0)]
    fam_gap = [filt(f"|gap| > {x}% and aligned", (orb.gap.abs() * 100 > x) & (orb.gap_aligned == True), x) for x in (0, 0.5, 1, 2)]
    fam_gap += [filt(f"|gap| > {x}% against", (orb.gap.abs() * 100 > x) & (orb.gap_aligned == False), None) for x in (0, 0.5, 1)]
    fam_gap += [filt("flat open (|gap| < 0.25%)", orb.gap.abs() * 100 < 0.25)]
    fam_mkt = [filt("SPY on the trade's side of VWAP", orb.spy_aligned == True),
               filt("SPY against", orb.spy_aligned == False),
               filt("QQQ on the trade's side of VWAP", orb.qqq_aligned == True),
               filt("QQQ against", orb.qqq_aligned == False),
               filt("SPY and QQQ both aligned", (orb.spy_aligned == True) & (orb.qqq_aligned == True))]
    fam_vwap = [filt("stock on the trade's side of its VWAP", orb.vwap_aligned == True),
                filt("stock against its VWAP", orb.vwap_aligned == False)]
    fam_ext = [filt(f"not extended: < {x} ATR from VWAP", orb.ext_atr < x, x) for x in (0.5, 1.0, 1.5)]
    orb["score"] = (orb.gap_aligned.fillna(False).astype(int) + orb.spy_aligned.fillna(False).astype(int)
                    + orb.qqq_aligned.fillna(False).astype(int) + orb.vwap_aligned.fillna(False).astype(int)
                    + (orb.rvol > 2).fillna(False).astype(int) + (orb.brk_vol > 2).fillna(False).astype(int))
    fam_score = [filt(f"quality score >= {x}", orb.score >= x, x) for x in range(1, 6)]
    L += ["## 2. Opening-range filters, one at a time", "",
          "Each row keeps only the trades that meet the condition. 'against' rows are shown for completeness and are not candidates.", ""]
    for title, fam in (("Relative volume", fam_rvol), ("Gap", fam_gap), ("Market direction (SPY / QQQ vs VWAP)", fam_mkt),
                       ("Stock VWAP", fam_vwap), ("Extension from VWAP", fam_ext), ("Research quality score (not a live filter)", fam_score)):
        nf = math.sqrt(2 * math.log(max(len(fam), 2)))
        L += [f"### {title}", "", f"Noise floor for {len(fam)} variants: about {nf:.1f} standard errors.", ""]
        rows = decide([f for f in fam if "against" not in f[0]], base) + \
            [(nm, st, "not a candidate") for nm, st, _ in fam if "against" in nm]
        L += table([("baseline", base, "baseline")] + rows) + [""]
    L += breakdown(orb, "score", "Quality score buckets (all periods)")

    # ---------------- ORB targets, management, stops
    def resim_family(fn):
        out = []
        for t in orb.itertuples():
            r = fn(t)
            out.append(np.nan if r is None else r)
        x = orb.copy()
        x["R"] = out
        return by_period(x.dropna(subset=["R"]))

    fam_t = [(f"target {x}R", resim_family(lambda t, x=x: run_exit(frames[(t.sym, t.date)], t.j, t.side, t.entry, t.stop, x)[0]), x)
             for x in (1.0, 1.25, 1.5, 2.5, 3.0)]
    fam_m = [("breakeven stop after 1R", resim_family(lambda t: run_exit(frames[(t.sym, t.date)], t.j, t.side, t.entry, t.stop, 2.0, be_at=1.0)[0]), None),
             ("half off at 1R, runner to 3R", resim_family(lambda t: run_exit(frames[(t.sym, t.date)], t.j, t.side, t.entry, t.stop, 3.0, partial=True)[0]), None),
             ("trail 1R behind best close (no target)", resim_family(lambda t: run_exit(frames[(t.sym, t.date)], t.j, t.side, t.entry, t.stop, 99.0, trail=1.0)[0]), None)]

    def alt_stop(kind, k):
        def fn(t):
            rth = frames[(t.sym, t.date)]
            s = 1 if t.side == "long" else -1
            atr_d = dailies[t.sym].loc[t.date, "atr_prev"]
            if kind == "atr":
                stop = t.entry - s * k * atr_d
            elif kind == "pct":
                stop = t.entry * (1 - s * k / 100)
            elif kind == "or":
                orr = rth.iloc[:5]
                stop = float(orr["low"].min()) if s > 0 else float(orr["high"].max())
            elif kind == "swing":
                w = rth.iloc[max(0, t.j - 5):t.j]
                stop = float(w["low"].min()) if s > 0 else float(w["high"].max())
            if not stop == stop or s * (t.entry - stop) <= 0 or abs(t.entry - stop) / t.entry > 0.10:
                return None
            return run_exit(rth, t.j, t.side, t.entry, stop, 2.0)[0]
        return fn
    fam_s = [(f"stop {k} x daily ATR", resim_family(alt_stop("atr", k)), k) for k in (0.1, 0.2, 0.3)]
    fam_s += [(f"stop {k}% fixed", resim_family(alt_stop("pct", k)), None) for k in (0.5, 1.0)]
    fam_s += [("stop at the far side of the opening range", resim_family(alt_stop("or", 0)), None),
              ("stop at the last 5-minute swing", resim_family(alt_stop("swing", 0)), None)]
    early = float(((orb.reason == "stop") & (orb.hold <= 5)).mean() * 100) if len(orb) else 0
    L += ["## 3. Opening-range targets, trade management and stops", "",
          f"Premature stop-outs (stopped within 5 minutes of entry) under the live stop: {early:.0f}% of all trades.", ""]
    for title, fam in (("Targets (live: 2R)", fam_t), ("Trade management", fam_m), ("Stops (live: past the session extreme + buffer)", fam_s)):
        L += [f"### {title}", ""] + table([("baseline", base, "baseline")] + decide(fam, base)) + [""]

    # ---------------- regime
    spy_d = dailies.get("SPY")
    if spy_d is not None:
        orb["spy_trend"] = orb.date.map(lambda d: "up 5 days" if spy_d.loc[d, "ret5_prev"] > 0 else "down 5 days")
        med = spy_d["atrpct_prev"].rolling(60, min_periods=20).median()
        orb["vol_regime"] = orb.date.map(lambda d: "high vol" if spy_d.loc[d, "atrpct_prev"] > med.loc[d] else "low vol")
        orb["spy_gap"] = orb.date.map(lambda d: "SPY gap > 0.5%" if abs(spy_d.loc[d, "o"] / spy_d.loc[d, "prev_c"] - 1) > 0.005 else "SPY gap < 0.5%")
        rng = spy_d.apply(lambda r: abs(r["c"] - r["o"]) / max(r["h"] - r["l"], 1e-9), axis=1)
        orb["day_type"] = orb.date.map(lambda d: "trend day (hindsight)" if rng.loc[d] > 0.5 else "range day (hindsight)")
        L += ["## 4. Market regime (opening-range trades, all periods)", "",
              "The first three are known before the open; the last uses the whole day and is a diagnosis only.", ""]
        for c in ("spy_trend", "vol_regime", "spy_gap", "day_type"):
            L += breakdown(orb, c, c)

    # ---------------- correlation
    orb = orb.sort_values(["date", "entry_time"])
    orb["mins"] = orb.entry_time.map(lambda x: int(x[:2]) * 60 + int(x[3:]))
    orb["burst"] = 0
    for (d, side), g in orb.groupby(["date", "side"]):
        m = g.mins.to_numpy()
        orb.loc[g.index, "burst"] = [int(((m >= x - 15) & (m < x)).sum()) for x in m]
    first = orb[orb.burst == 0]
    L += ["## 5. Correlated signals", "",
          "`burst` = how many same-side signals fired in the 15 minutes before this one, across the watchlist.", ""]
    L += breakdown(orb.assign(burst=orb.burst.clip(upper=4)), "burst", "Signals already in the same direction (4 = 4 or more)")
    L += ["### Taking only the first signal of each burst", ""] + table(
        [("baseline", base, "baseline"), ("first of each burst only", by_period(first), verdict(base, by_period(first))[1])]) + [""]
    etf = orb[~orb.sym.isin(["SPY", "QQQ"])]
    L += ["### Without SPY and QQQ", ""] + table(
        [("baseline", base, "baseline"), ("stocks only", by_period(etf), verdict(base, by_period(etf))[1])]) + [""]

    # ---------------- retest
    rb = retest_trades(S, lab)
    rbase = by_period(rb)
    L += ["## 6. Break & retest: baseline (live: shorts only, warm-up on today's bars)", "", FULL]
    for per in ("train", "val", "test"):
        x = rb[rb.period == per] if len(rb) else rb
        L.append(full_row(f"retest {per}", stats(x.R, x.date, x.hold) if len(x) else {"n": 0}))
    L.append("")
    sides = [(f"{s}", by_period(retest_trades(S, lab, sides=s)), None) for s in ("long", "both")]
    L += ["## 7. Long vs short retests", ""] + table([("short only (live)", rbase, "baseline")] + decide(sides, rbase)) + [""]
    fam_v = [(f"break volume >= {x}x", by_period(retest_trades(S, lab, vol_mult=x)), x) for x in (1.25, 1.5, 2.0, 3.0)]
    fam_q = [(f"range <= {x} average moves", by_period(retest_trades(S, lab, squeeze=x)), x) for x in (1.5, 2.0, 2.5, 3.5)]
    fam_c = [(f"retest confirmation: {c}", by_period(retest_trades(S, lab, confirm=c)), None) for c in ("candle", "wick", "away", "engulf")]
    fam_w = [("indicators warmed on yesterday too (trades from 09:45)", by_period(retest_trades(S, lab, warm="prior")), None)]
    for title, fam in (("Breakout volume (live: 1x)", fam_v), ("Range tightness (live: 3)", fam_q),
                       ("Retest confirmation (one at a time)", fam_c), ("Warm-up", fam_w)):
        L += [f"### {title}", ""] + table([("baseline", rbase, "baseline")] + decide(fam, rbase)) + [""]
    if len(rb):
        L += breakdown(rb, "hour", "Retest by hour") + breakdown(rb, "sym", "Retest by ticker")

    # ---------------- comparison
    def pick(fam):
        return [(nm, st) for nm, st, why in decide(fam, base) if why == "ADOPT"]
    adopted = {f"ORB {nm}": st for fam in (fam_rvol, fam_mkt, fam_vwap, fam_ext, fam_t, fam_m, fam_s) for nm, st in pick(fam)}
    L += ["## 8. Comparison", "", "| system | period | trades | win | avg R | median R | total R | PF | max DD R | Sharpe | 95% CI avg R |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    comp = {"current ORB": base, "current retest": rbase, **adopted}
    for nm, st in comp.items():
        for per in ("train", "val", "test"):
            L.append(f"| {nm if per == 'train' else ''} | {per} " + fmt(st[per]))
    L += ["", f"Adopted changes: {', '.join(adopted) or 'none'}.", ""]

    out = "\n".join(L) + "\n"
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(out)
    REPORT.with_suffix(".json").write_text(json.dumps(
        {"sessions": len(lab), "span": span, "orb_trades": int(len(orb)), "retest_trades": int(len(rb)),
         "adopted": list(adopted), "resim_match": match}, indent=1, default=str))
    print(out[:4000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
