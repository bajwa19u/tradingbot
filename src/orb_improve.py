"""Trade-level analysis of the current day-trade rule, and a disciplined test
of the improvements it suggests.

Two date ranges, fixed before looking:
  RECENT  the last 63 sessions - the 257 trades the owner asked about. Losing
          clusters are LOOKED FOR here.
  EARLIER the 189 sessions before that (about 9 months). Never used to find a
          pattern; only used to confirm one.

A candidate change is adopted only if, on BOTH ranges (rule fixed before the run):
  1. average per trade improves
  2. profit factor does not fall
  3. at least 60% of the trades are kept (filters that starve the rule are out)
  4. average per trade still improves at 0.10% slippage per side
Adopted changes are then combined (at most three) and the combination must
pass the same test. Candidates come from the owner's list, decided before the
run, each at one round value - no threshold searching.

Results are per trade as a share of the account (a full stop costs 1%).
Usage: python -m src.orb_improve
"""
from __future__ import annotations

import json
import math
import sys
from dataclasses import replace

import numpy as np
import pandas as pd

from . import orb_research as orr
from .config import REPO_ROOT
from .orb_paper import CANDIDATE, bar_label

REPORT = REPO_ROOT / "reports" / "orb_improve.md"
TRADES_CSV = REPO_ROOT / "reports" / "orb_improve_trades.csv"
RECENT = 63


# ---------------------------------------------------------------- trade table
def rich_trades(D: dict, dates: list, p: orr.P) -> pd.DataFrame:
    """Every trade the rule takes, with everything known at entry plus how the
    trade travelled (best and worst excursion, what happened after the exit)."""
    spy, qqq = D["SPY"], D["QQQ"]
    spy_dates = sorted(spy)
    spy_close = {d: float(spy[d].c[-1]) for d in spy_dates}
    rows = []
    for d in dates:
        S, Q = spy[d], qqq[d]
        sa, qa = S.c > S.vwap, Q.c > Q.vwap
        i = spy_dates.index(d)
        prior = [spy_close[x] for x in spy_dates[max(0, i - 20):i]]
        spy_trend20 = (S.o[0] / np.mean(prior) - 1) if len(prior) >= 10 else np.nan
        for rank, s in enumerate(orr.select(D, d, p.universe), 1):
            x = D[s][d]
            sig = orr.first_signal(x, sa, qa, p, orr.FLAT_IDX - 1, S)
            if sig is None:
                continue
            k, sgn = sig["k"], sig["sign"]
            R, j, why = orr.exit_r(x, sig["kk"], sgn, sig["entry"], sig["stop"], p)
            rps = abs(sig["entry"] - sig["stop"])
            seg_h, seg_l = x.h[k + 1:j + 1], x.l[k + 1:j + 1]
            mfe = ((seg_h.max() - sig["entry"]) if sgn > 0 else (sig["entry"] - seg_l.min())) / rps if len(seg_h) else 0.0
            mae = ((sig["entry"] - seg_l.min()) if sgn > 0 else (seg_h.max() - sig["entry"])) / rps if len(seg_h) else 0.0
            rest = slice(j + 1, orr.FLAT_IDX + 1)
            after_best = (((x.h[rest].max() if sgn > 0 else -x.l[rest].min()) - (sig["entry"] if sgn > 0 else -sig["entry"])) / rps
                          if j < orr.FLAT_IDX else np.nan)
            bell_R = sgn * (x.c[orr.FLAT_IDX] - sig["entry"]) / rps
            prev = sorted(q for q in D[s] if q < d)
            pdh = float(D[s][prev[-1]].h.max()) if prev else np.nan
            pdl = float(D[s][prev[-1]].l.min()) if prev else np.nan
            key = ((pdh - sig["entry"]) if sgn > 0 else (sig["entry"] - pdl)) / x.atr  # room to yesterday's extreme, in ATR
            rows.append(dict(
                date=str(d), dow=pd.Timestamp(d).day_name()[:3], symbol=s, rank=rank, side=sig["side"],
                entry_bar=bar_label(k), k=k, exit_bar=bar_label(j), j=j, exit=why, R=float(R),
                stop_pct=rps / sig["entry"] * 100, rvol5=x.rvol5, orw=sig["orw"], disp=sig["disp"], bvol=sig["bvol"],
                ext=sig["ext"], gap=x.gap * 100 if x.gap == x.gap else np.nan,
                with_gap=bool(x.gap == x.gap and x.gap * sgn > 0),
                spy_vwap_ok=bool(sig["spy_ok"]), spy_open_ok=bool((S.c[k] - S.o[0]) * sgn > 0),
                spy_orw=S.or_w / S.atr if S.atr else np.nan, spy_atr_pct=S.atr / S.o[0] * 100,
                spy_trend20_ok=bool(spy_trend20 == spy_trend20 and spy_trend20 * sgn > 0),
                key_room_atr=key, mfe=mfe, mae=mae, after_exit_best=after_best, bell_R=bell_R))
    return pd.DataFrame(rows)


def st(r: pd.Series) -> dict:
    r = r.to_numpy(float)
    if not len(r):
        return dict(n=0, win=np.nan, avg=np.nan, pf=np.nan, tot=0.0)
    w, l = r[r > 0], r[r <= 0]
    return dict(n=len(r), win=100 * len(w) / len(r), avg=r.mean(), tot=r.sum(),
                pf=w.sum() / -l.sum() if l.sum() < 0 else np.inf)


def seg_table(title: str, rec: pd.DataFrame, ear: pd.DataFrame, key) -> list[str]:
    """One segment, recent beside earlier. `key` maps a trade table to bucket labels."""
    L = [f"### {title}", "", "| bucket | recent trades | win % | avg | PF | total | earlier trades | win % | avg | PF |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    kr, ke = key(rec), key(ear)
    for b in sorted(set(kr.dropna()) | set(ke.dropna()), key=str):
        a, e = st(rec.R[kr == b]), st(ear.R[ke == b])
        cell = lambda s: (f"{s['n']} | {s['win']:.0f}% | {s['avg']:+.2f}% | {s['pf']:.2f}" if s["n"] else "0 | | |")
        L.append(f"| {b} | {cell(a)} | {a['tot']:+.1f}% | {cell(e)} |")
    return L + [""]


def cut(col, edges, labels=None):
    return lambda df: pd.cut(df[col], edges, right=False, labels=labels).astype(str).replace("nan", np.nan)


# ---------------------------------------------------------------- summary stats for the comparison table
def summary(tr: pd.DataFrame, ds: list) -> dict:
    r = tr.R.to_numpy(float)
    if not len(r):
        return dict(trades=0)
    w, l = r[r > 0], r[r <= 0]
    eq = np.cumsum(r)
    by_day = tr.groupby("date").R.sum()
    return dict(trades=len(r), win=100 * len(w) / len(r), avg=r.mean(), total=r.sum(),
                pf=w.sum() / -l.sum() if l.sum() < 0 else np.inf,
                dd=float((np.maximum.accumulate(np.concatenate([[0], eq]))[1:] - eq).max()),
                green=int((by_day > 0).sum()), sessions=len(ds), best=r.max(), worst=r.min())


def main(argv=None) -> int:
    D, common = orr.build(orr.load(260, False))
    dates = common[-252:]
    rec_d, ear_d = dates[-RECENT:], dates[:-RECENT]
    base = rich_trades(D, dates, CANDIDATE)
    rec, ear = base[base.date.isin(map(str, rec_d))], base[base.date.isin(map(str, ear_d))]
    rec.to_csv(TRADES_CSV, index=False)

    L = ["# Improving the current day-trade rule", "",
         f"Current rule: `{CANDIDATE}`.", "",
         f"Recent range: {rec_d[0]} to {rec_d[-1]} ({len(rec_d)} sessions, {len(rec)} trades) - where losing clusters were looked for. "
         f"Earlier range: {ear_d[0]} to {ear_d[-1]} ({len(ear_d)} sessions, {len(ear)} trades) - used only to confirm. "
         "Each % is one trade as a share of the account (a full stop costs 1%), after 0.05% slippage a side.", "",
         "## 1. Where the results come from", ""]

    # --- excursions: are winners cut short, are losers allowed the full stop?
    for nm, df in (("recent", rec), ("earlier", ear)):
        stops, bells, tgts = df[df.exit == "stop"], df[df.exit == "bell"], df[df.exit == "target"]
        L += [f"**{nm.title()}:** {len(tgts)} targets, {len(stops)} stops, {len(bells)} closed at 15:55. "
              f"Of the stopped trades, {100 * (stops.mfe >= 1).mean():.0f}% had been at least +1x risk in profit first "
              f"and {100 * (stops.mfe >= 0.5).mean():.0f}% at least +0.5x. "
              f"Of the 15:55 exits, {100 * (bells.mfe >= 1.5).mean():.0f}% had been +1.5x or more at some point. "
              f"After a target hit, price ran a further {np.nanmedian(tgts.after_exit_best - 2):+.2f}x risk (median) by 15:55. "
              f"After a stop, {100 * (stops.after_exit_best >= 2).mean():.0f}% went on to where the target was.", ""]

    segs = [
        ("Long vs short", lambda df: df.side),
        ("Setup type (with or against the overnight gap)", lambda df: df.with_gap.map({True: "with the gap", False: "against / no gap"})),
        ("Entry time", cut("k", [5, 10, 15, 20, 30], ["09:35-09:39", "09:40-09:44", "09:45-09:49", "09:50-09:59"])),
        ("Exit time", cut("j", [0, 60, 150, 270, 385, 400], ["before 10:30", "10:30-11:59", "12:00-13:59", "14:00-15:54", "15:55 (bell)"])),
        ("How it ended", lambda df: df.exit),
        ("Day of week", lambda df: df.dow),
        ("SPY above/below VWAP, matching the trade", lambda df: df.spy_vwap_ok.map({True: "matches", False: "against"})),
        ("SPY move since its open, matching the trade", lambda df: df.spy_open_ok.map({True: "matches", False: "against"})),
        ("SPY 20-day trend, matching the trade", lambda df: df.spy_trend20_ok.map({True: "matches", False: "against"})),
        ("Market volatility: SPY opening range / its ATR", cut("spy_orw", [0, 0.1, 0.2, 99], ["quiet open (<0.1)", "normal (0.1-0.2)", "wild open (>=0.2)"])),
        ("Market volatility: SPY daily ATR as % of price", cut("spy_atr_pct", [0, 0.8, 1.2, 99], ["low (<0.8%)", "mid", "high (>=1.2%)"])),
        ("Room to yesterday's high (long) / low (short), in ATR", cut("key_room_atr", [-99, 0, 0.5, 99], ["already through it", "within 0.5 ATR", "more than 0.5 ATR away"])),
        ("Stock rank by opening volume", cut("rank", [1, 4, 7, 11], ["1-3", "4-6", "7-10"])),
        ("Opening volume vs normal", cut("rvol5", [0, 1.5, 3, 999], ["<1.5x", "1.5-3x", ">=3x"])),
        ("Opening range / stock's ATR", cut("orw", [0.35, 0.5, 0.75, 99], ["0.35-0.5", "0.5-0.75", ">=0.75"])),
        ("Breakout strength (close past the level / range)", cut("disp", [0, 0.1, 0.3, 99], ["<0.1", "0.1-0.3", ">=0.3"])),
        ("Breakout-minute volume vs that minute's normal", cut("bvol", [0, 1, 2, 9999], ["<1x", "1-2x", ">=2x"])),
        ("Stop distance (% of price)", cut("stop_pct", [0, 1, 2, 3, 99], ["<1%", "1-2%", "2-3%", ">=3%"])),
    ]
    L += ["## 2. Segments (recent | earlier)", ""]
    for t, f in segs:
        L += seg_table(t, rec, ear, f)
    by = rec.groupby("symbol").R.agg(["count", "sum", "mean"]).sort_values("sum")
    ear_by = ear.groupby("symbol").R.agg(["count", "sum"])
    L += ["### Tickers (recent, worst 8 and best 8)", "", "| ticker | recent trades | recent total | earlier trades | earlier total |", "|---|---|---|---|---|"]
    for s_, r_ in pd.concat([by.head(8), by.tail(8)]).iterrows():
        e_ = ear_by.loc[s_] if s_ in ear_by.index else None
        e_n, e_t = (int(e_["count"]), f"{e_['sum']:+.2f}%") if e_ is not None else (0, "-")
        L.append(f"| {s_} | {int(r_['count'])} | {r_['sum']:+.2f}% | {e_n} | {e_t} |")
    L += ["", "Only 2-6 trades per name in the recent range: far too few to drop a ticker on. Not tested as a rule.", ""]

    # --- pre-registered candidates
    cands = [
        ("No entries after 09:45 (late signals)", replace(CANDIDATE, window_end=15)),
        ("No entries after 09:50", replace(CANDIDATE, window_end=20)),
        ("Longs only", replace(CANDIDATE, sides="long")),
        ("Shorts only", replace(CANDIDATE, sides="short")),
        ("SPY above/below VWAP must match (SPY and QQQ)", replace(CANDIDATE, market="idx")),
        ("SPY's move since the open must match", replace(CANDIDATE, spy_trend=True)),
        ("Skip quiet market opens (SPY range < 0.1 ATR)", replace(CANDIDATE, spy_vol=0.1)),
        ("Stronger breakout (close >= 0.1 of the range past it)", replace(CANDIDATE, disp=0.1)),
        ("Breakout-minute volume >= 1.5x normal", replace(CANDIDATE, bvol=1.5)),
        ("Only the top 5 by opening volume", replace(CANDIDATE, universe="top5")),
        ("Skip wide stops (> 3% of price)", replace(CANDIDATE, max_risk=0.03)),
        ("Stop to breakeven after +1x risk", replace(CANDIDATE, manage="be")),
        ("Target 3x risk instead of 2x", replace(CANDIDATE, target=3.0)),
    ]
    tried = len(cands)
    lab = {d: "x" for d in dates}

    def split(p):
        t = orr.trades(D, dates, lab, p)
        t["date"] = t.date.astype(str)
        return t[t.date.isin(map(str, rec_d))], t[t.date.isin(map(str, ear_d))]

    def verdict(p, cur=CANDIDATE):
        r1, e1 = split(p); r2, e2 = split(replace(p, slip=0.001))
        c1, ce1 = split(cur); c2, ce2 = split(replace(cur, slip=0.001))
        s = {k: st(v.R) for k, v in dict(r=r1, e=e1, r2=r2, e2=e2, cr=c1, ce=ce1, cr2=c2, ce2=ce2).items()}
        why = ("better avg on both" if s["r"]["avg"] > s["cr"]["avg"] and s["e"]["avg"] > s["ce"]["avg"] else "avg not better on both")
        ok = (s["r"]["avg"] > s["cr"]["avg"] and s["e"]["avg"] > s["ce"]["avg"]
              and s["r"]["pf"] >= s["cr"]["pf"] and s["e"]["pf"] >= s["ce"]["pf"]
              and s["r"]["n"] >= 0.6 * s["cr"]["n"] and s["e"]["n"] >= 0.6 * s["ce"]["n"]
              and s["r2"]["avg"] > s["cr2"]["avg"] and s["e2"]["avg"] > s["ce2"]["avg"])
        if not ok and why == "better avg on both":
            why = ("PF fell" if not (s["r"]["pf"] >= s["cr"]["pf"] and s["e"]["pf"] >= s["ce"]["pf"]) else
                   "keeps < 60% of trades" if not (s["r"]["n"] >= 0.6 * s["cr"]["n"] and s["e"]["n"] >= 0.6 * s["ce"]["n"]) else
                   "gain gone at 0.10% slippage")
        return ok, ("ADOPT" if ok else why), s

    L += ["## 3. Candidate changes (fixed before the run; each tested on both ranges)", "",
          f"{tried} candidates. With that many tries, one can look good by chance; that is why each must hold on the earlier range too.", "",
          "| change | verdict | recent trades | recent avg | recent PF | earlier trades | earlier avg | earlier PF | recent avg @0.10% | earlier avg @0.10% |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    ok0, _, s0 = verdict(CANDIDATE)
    L.append(f"| current rule | - | {s0['cr']['n']} | {s0['cr']['avg']:+.3f}% | {s0['cr']['pf']:.2f} | {s0['ce']['n']} | {s0['ce']['avg']:+.3f}% | "
             f"{s0['ce']['pf']:.2f} | {s0['cr2']['avg']:+.3f}% | {s0['ce2']['avg']:+.3f}% |")
    adopted = []
    for nm, p in cands:
        ok, why, s = verdict(p)
        L.append(f"| {nm} | {why} | {s['r']['n']} | {s['r']['avg']:+.3f}% | {s['r']['pf']:.2f} | {s['e']['n']} | {s['e']['avg']:+.3f}% | "
                 f"{s['e']['pf']:.2f} | {s['r2']['avg']:+.3f}% | {s['e2']['avg']:+.3f}% |")
        if ok:
            adopted.append((nm, p, s["r"]["avg"] + s["e"]["avg"]))
    L.append("")

    # --- combine the adopted ones (best first), keeping each only if it still helps
    final, names = CANDIDATE, []
    for nm, p, _ in sorted(adopted, key=lambda a: -a[2])[:3]:
        diff = {f: getattr(p, f) for f in p.__dataclass_fields__ if getattr(p, f) != getattr(CANDIDATE, f)}
        trial = replace(final, **diff)
        ok, why, _ = verdict(trial, final)
        if ok:
            final, names = trial, names + [nm]
    L += ["## 4. Result", "",
          ("Adopted: " + "; ".join(names) + "." if names else
           "**Nothing passed.** No candidate improved the rule on both date ranges. The current rule stays as it is."),
          f"Final rule: `{final}`", ""]

    # --- comparison windows on the recent range (the owner's week / month / 3 months)
    old = orr.P()
    comp = {}
    for wname, n in (("week", 5), ("month", 21), ("3 months", 63)):
        ds = [str(d) for d in dates[-n:]]
        comp[wname] = {}
        for lbl, p in (("old", old), ("current", CANDIDATE), ("improved", final)):
            t = orr.trades(D, dates[-n:], {d: "x" for d in dates[-n:]}, p)
            t["date"] = t.date.astype(str)
            comp[wname][lbl] = summary(t.sort_values(["date", "k"]), ds)
    fmt = lambda v, k: ("-" if v is None or (isinstance(v, float) and math.isnan(v)) else
                        f"{v:.0f}" if k in ("trades", "green") else f"{v:.1f}%" if k == "win" else
                        f"{v:.2f}" if k == "pf" else f"{v:+.2f}%" if k in ("avg", "total", "best", "worst") else f"{v:.2f}%")
    for wname in comp:
        L += [f"### {wname}", "", "| metric | old rule | current rule | improved rule |", "|---|---|---|---|"]
        for k, nm in (("trades", "Trades"), ("win", "Win rate"), ("avg", "Avg/trade"), ("total", "Total"), ("pf", "Profit factor"),
                      ("dd", "Max drawdown"), ("green", "Green days"), ("best", "Best trade"), ("worst", "Worst trade")):
            L.append(f"| {nm} | " + " | ".join(fmt(comp[wname][x].get(k), k) for x in ("old", "current", "improved")) + " |")
        L.append("")
    out = "\n".join(L) + "\n"
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(out)
    REPORT.with_suffix(".json").write_text(json.dumps({"adopted": names, "final": str(final), "comparison": comp}, indent=1, default=float))
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
