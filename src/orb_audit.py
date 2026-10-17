"""Profitability audit of the live day-trade rule (ORB on big tech) - the
baseline, a reproduction check, and five changes fixed in advance.

Written 17 Oct 2026 before any of it was run. Nothing here changes what the
live bot does; it only measures.

The live rule is `orb_live.RULES["bigtech"]`: `orb_paper.CANDIDATE` traded
every day on `orb_research.BIG_TECH`. This module calls the research functions
the live bot calls (`orb_research.first_signal` / `exit_r` via `trades`), so
the backtest and the live channel cannot disagree about what a signal is.

Data: Alpaca IEX 1-minute bars (the feed the live bot trades from), 2024-09-03
to 2026-10-16. Dates are split in time order:

  train    2024-10-01 .. 2025-09-29  never used by any earlier ORB study here
  val      2025-09-30 .. 2026-07-06  the "earlier 189 sessions" the rule lost on
  test     2026-07-07 .. 2026-10-02  the "recent 63"; the owner chose the big
                                     tech list after seeing it, so it is NOT
                                     untouched for the baseline (disclosed)
  forward  2026-10-05 .. 2026-10-16  after every decision; untouched

Choices are made on train and validation only. Test and forward are printed
once, beside them.

Results are % of the account per trade when a full stop costs 1% (the live
cards' sizing), plus the stock's own move. Costs: realistic = 0.05% a side
(orb_checks measured a 0.045% median round trip, so this is conservative);
stressed = 0.10% a side; stressed + late = 0.10% a side and the entry a full
minute late (the next minute's close; live signals are sometimes a poll late).
Stops fill at the stop or the bar's open if it gapped through.

Pre-registered changes (one at a time, then the passing ones together):
  H1 regime     trade only with SPY's daily trend: longs when SPY's prior close
                is above its 20-day average of prior closes, shorts when below
  H2 crowding   at most 2 same-side entries in any 10 minutes (the six names
                move together; six same-side trades are one bet)
  H3 in play    the name's first-5-minute volume must be at least its 14-day
                average (rvol5 >= 1.0)
  H4 strength   the breakout close must be >= 0.10 of the range width past it
  H5 timing     entries 09:35-09:39 only (today 09:35-09:44)
No stop or target variant: 63-78% of trades end at the bell, and the settled
research found none positive; the exit-reason table is printed instead.

Adoption rule, fixed before running (realistic costs unless stated):
  1. validation expectancy >= baseline + 0.03% on >= 60 validation trades
  2. train expectancy >= baseline train expectancy
  3. profit factor not lower on train or validation
  4. the validation gain survives dropping the two best validation trades
  5. at stressed + late costs, train and validation still >= baseline
  6. train + validation expectancy > 0 (a smaller loss is not an edge)
  7. train + validation t-stat >= the noise floor sqrt(2 ln N), N = variants
Then promotion also needs test and forward >= baseline and > 0.

The Stocks-in-Play candidate (`orb_paper.CANDIDATE`, top 10 by rvol5) is
re-checked on the same dates. Criteria fixed in advance: positive on the
untouched train year at 0.05% and not negative at 0.10%; and its forward
paper record (`reports/orb_paper.csv`) positive over >= 60 trades.

Usage: python -m src.orb_audit [--bigtech-only]
"""
from __future__ import annotations

import json
import math
import pickle
import sys
from dataclasses import replace

import numpy as np
import pandas as pd

from . import orb_research as orr
from .config import REPO_ROOT
from .orb_checks import md as throttled
from .orb_paper import CANDIDATE

CACHE = REPO_ROOT / "cache" / "minute_iex_audit.pkl"
OUT = REPO_ROOT / "reports"
START, END = "2024-09-03", "2026-10-16T21:00:00Z"
PERIODS = [("train", "2024-10-01", "2025-09-29"), ("val", "2025-09-30", "2026-07-06"),
           ("test", "2026-07-07", "2026-10-02"), ("forward", "2026-10-05", "2026-10-16")]
KEYS = [k for k, _, _ in PERIODS]
BASE = replace(CANDIDATE, universe="bigtech")          # = orb_live.RULES["bigtech"][0]
REAL, STRESS = 0.0005, 0.0010
COSTS = {"realistic": dict(slip=REAL), "stressed": dict(slip=STRESS), "stressed+late": dict(slip=STRESS, delay=1, delay_fill="close")}
# name: (rule, H1 regime, H3 min rvol5)
SINGLES = {
    "H1 regime (with SPY 20-day trend)": (BASE, True, 0.0),
    "H2 crowding (max 2 same-side / 10 min)": (replace(BASE, cluster_max=2), False, 0.0),
    "H3 in play (rvol5 >= 1.0)": (BASE, False, 1.0),
    "H4 strength (close >= 0.10 range past)": (replace(BASE, disp=0.10), False, 0.0),
    "H5 timing (entries 09:35-09:39)": (replace(BASE, window_end=10), False, 0.0),
}
N_VARIANTS = len(SINGLES) + 1                           # + the combination
FLOOR = math.sqrt(2 * math.log(N_VARIANTS))
# what the earlier study printed for the same rule (reports/orb_bigtech.md)
PUBLISHED = {"recent": (88, 0.170), "earlier": (265, -0.028)}


# ======================================================================= data
def load(symbols: list[str]) -> dict[str, pd.DataFrame]:
    data = pickle.loads(CACHE.read_bytes()) if CACHE.exists() else {}
    need = [s for s in symbols if s not in data]
    m = throttled("iex") if need else None
    for i in range(0, len(need), 8):
        chunk = need[i:i + 8]
        for s, df in m.intraday_bars(chunk, 1, start=START, end=END).items():
            data[s] = df.astype("float32")
        for s in chunk:
            data.setdefault(s, pd.DataFrame())
        CACHE.parent.mkdir(exist_ok=True)
        CACHE.write_bytes(pickle.dumps(data))
        print(f"loaded {i + len(chunk)}/{len(need)}", flush=True)
    return {s: data[s] for s in symbols if len(data.get(s, ()))}


def label(dates) -> dict:
    out = {}
    for d in dates:
        for k, a, b in PERIODS:
            if pd.Timestamp(a).date() <= d <= pd.Timestamp(b).date():
                out[d] = k
    return out


def spy_trend(D: dict, dates: list) -> dict:
    """date -> 'long' if SPY's prior close > the mean of its 20 prior closes, else 'short'.
    Uses only sessions before the date, so it is known at 09:30."""
    ds = sorted(D["SPY"])
    close = pd.Series([float(D["SPY"][d].c[-1]) for d in ds], index=ds)
    prev, sma = close.shift(1), close.shift(1).rolling(20).mean()
    return {d: ("long" if prev[d] > sma[d] else "short") for d in dates if d in prev.index and sma[d] == sma[d]}


# ======================================================================= runs
def run(D: dict, dates: list, lab: dict, p: orr.P, regime: dict | None = None, min_rvol: float = 0.0) -> pd.DataFrame:
    if min_rvol:
        D = {s: ({d: x for d, x in v.items() if x.rvol5 >= min_rvol} if s in orr.BIG_TECH else v) for s, v in D.items()}
    if regime is None:
        t = orr.trades(D, dates, lab, p)
    else:
        parts = [orr.trades(D, [d], lab, replace(p, sides=regime[d])) for d in dates if d in regime]
        parts = [x for x in parts if len(x)]
        t = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    if len(t):
        t["date"] = pd.to_datetime(t.date).dt.date
        t = t.sort_values(["date", "k", "sym"]).reset_index(drop=True)
    return t


def st(df: pd.DataFrame) -> dict:
    """Account % per trade at 1% risk (= the R column) and the stock's move %."""
    if df is None or len(df) == 0:
        return dict(n=0)
    r = df["R"].to_numpy(float)
    n, w, l = len(r), r[r > 0], r[r <= 0]
    eq = np.cumsum(r)
    sd = r.std(ddof=1) if n > 1 else 0.0
    srt = np.sort(r)
    return dict(n=n, win=100 * len(w) / n, wins=int(len(w)), losses=int(len(l)), avg=float(r.mean()),
                pf=float(w.sum() / -l.sum()) if l.sum() < 0 else float("inf"), total=float(r.sum()),
                dd=float((np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:] - eq).max()),
                avg_w=float(w.mean()) if len(w) else 0.0, avg_l=float(l.mean()) if len(l) else 0.0,
                t=float(r.mean() / sd * math.sqrt(n)) if sd > 0 else 0.0,
                no_top2=float(srt[:-2].mean()) if n > 2 else float("nan"),
                top5=float(srt[-5:].sum()), move=float(df["pct"].mean()))


def per(df: pd.DataFrame) -> dict:
    out = {k: st(df[df.period == k] if len(df) else df) for k in KEYS}
    out["train+val"] = st(df[df.period.isin(["train", "val"])] if len(df) else df)
    out["all"] = st(df)
    return out


def adopt(b: dict, c: dict, b_late: dict, c_late: dict) -> list[str]:
    """Every adoption-rule line the candidate fails (empty = passes 1-7)."""
    bt, bv, ct, cv = b["train"], b["val"], c["train"], c["val"]
    fails = []
    if cv.get("n", 0) < 60:
        fails.append(f"1: {cv.get('n', 0)} validation trades")
    elif cv["avg"] < bv["avg"] + 0.03:
        fails.append("1: no validation gain")
    if ct.get("n", 0) == 0 or ct["avg"] < bt["avg"]:
        fails.append("2: worse on train")
    if ct.get("n", 0) == 0 or cv.get("n", 0) == 0 or ct["pf"] < bt["pf"] or cv["pf"] < bv["pf"]:
        fails.append("3: profit factor lower")
    if cv.get("n", 0) and not cv["no_top2"] >= bv["avg"]:
        fails.append("4: gain rests on 2 trades")
    if any(c_late[k].get("n", 0) == 0 or c_late[k]["avg"] < b_late[k]["avg"] for k in ("train", "val")):
        fails.append("5: not better at stressed+late costs")
    tv = c["train+val"]
    if not tv.get("n") or tv["avg"] <= 0:
        fails.append("6: train+val expectancy not positive")
    elif tv["t"] < FLOOR:
        fails.append(f"7: t {tv['t']:.2f} < noise floor {FLOOR:.2f}")
    return fails


# ======================================================================= report
def f(v, d=3) -> str:
    return "-" if v is None or v != v else f"{v:+.{d}f}%"


def row(name: str, s: dict) -> str:
    if not s.get("n"):
        return f"| {name} | 0 | | | | | | | | |"
    return (f"| {name} | {s['n']} | {s['win']:.1f}% ({s['wins']}/{s['losses']}) | {f(s['avg'])} | {s['pf']:.2f} | "
            f"{s['total']:+.1f}% | {s['dd']:.1f}% | {f(s['avg_w'], 2)} / {f(s['avg_l'], 2)} | {f(s['move'])} | {s['t']:+.2f} |")


HDR = ("| | trades | win % (won/lost) | expectancy (account %/trade) | PF | cumulative | max DD | avg win / loss | "
       "avg stock move | t |\n|---|---|---|---|---|---|---|---|---|---|")


def period_table(res: dict) -> list[str]:
    L = [HDR]
    for k in KEYS + ["train+val", "all"]:
        L.append(row(k, res[k]))
    return L


def split_table(df: pd.DataFrame, key, title: str) -> list[str]:
    L = [f"#### {title}", "", "| bucket | train n | train exp | val n | val exp | test n | test exp | fwd n | fwd exp | all n | all exp | all PF |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    g = pd.Series(np.asarray(key(df)), index=df.index) if callable(key) else df[key]
    for b in sorted(g.dropna().unique(), key=str):
        part = df[g == b]
        cells = []
        for k in KEYS:
            s = st(part[part.period == k])
            cells.append(f"{s.get('n', 0)} | {f(s.get('avg'))}")
        a = st(part)
        L.append(f"| {b} | " + " | ".join(cells) + f" | {a['n']} | {f(a['avg'])} | {a['pf']:.2f} |")
    return L + [""]


def month_table(t: pd.DataFrame, D: dict, dates: list) -> tuple[list[str], list[dict]]:
    """Why some months work: the rule's month next to what the market did."""
    spy = pd.Series({d: float(D["SPY"][d].c[-1]) for d in sorted(D["SPY"])})
    spy.index = pd.to_datetime(spy.index)
    rets = spy.pct_change()
    t = t.assign(m=pd.to_datetime(t.date).dt.to_period("M"))
    ok = {}                                            # share of name-days passing the 0.35 range filter
    for d in dates:
        xs = [D[s][d] for s in orr.BIG_TECH if d in D.get(s, {})]
        ok.setdefault(pd.Timestamp(d).to_period("M"), []).extend(
            [x.or_w / x.atr >= BASE.orw[0] for x in xs if x.atr > 0])
    rows, L = [], ["| month | trades | win % | expectancy | total | longs | bell exits avg | range filter pass | SPY month | SPY daily vol (ann.) | SPY trend days up |",
                   "|---|---|---|---|---|---|---|---|---|---|---|"]
    for m in sorted(ok):
        g = t[t.m == m]
        s = st(g)
        r = rets[rets.index.to_period("M") == m].dropna()
        mr = float((1 + r).prod() - 1) * 100 if len(r) else float("nan")
        vol = float(r.std() * math.sqrt(252) * 100) if len(r) > 2 else float("nan")
        bell = g[g.why == "bell"].R.mean() if len(g) else float("nan")
        up = float((r > 0).mean() * 100) if len(r) else float("nan")
        rows.append(dict(month=str(m), n=s.get("n", 0), avg=s.get("avg"), total=s.get("total"), spy=mr, vol=vol,
                         longs=float((g.side == "long").mean()) if len(g) else float("nan"), pass_rate=float(np.mean(ok[m]))))
        L.append(f"| {m} | {s.get('n', 0)} | {s.get('win', 0):.0f}% | {f(s.get('avg'))} | {s.get('total', 0):+.1f}% | "
                 f"{(g.side == 'long').mean() * 100 if len(g) else 0:.0f}% | {f(bell)} | {np.mean(ok[m]) * 100:.0f}% | "
                 f"{mr:+.1f}% | {vol:.0f}% | {up:.0f}% |")
    return L, rows


def ledger_check(t: pd.DataFrame) -> list[str]:
    """The live channel's record next to this backtest, from the day it ran big tech."""
    p = REPO_ROOT / "state" / "ledger_daytrade.csv"
    if not p.exists():
        return ["No day-trade ledger."]
    lg = pd.read_csv(p)
    lg = lg[lg.date >= "2026-10-06"]
    bt = t[(t.period == "forward") & (t.date.astype(str) >= "2026-10-06")].copy()
    bt["key"] = bt.date.astype(str) + bt.sym
    lg["key"] = lg.date + lg.symbol
    L = ["| date | symbol | ledger side / entry / exit / result (source) | backtest side / entry / exit / result |", "|---|---|---|---|"]
    for k in sorted(set(bt.key) | set(lg.key)):
        a, b = lg[lg.key == k], bt[bt.key == k]
        la = (f"{a.side.iloc[0]} {a.entry_time.iloc[0]} {a.exit_time.iloc[0]} {a.pct.iloc[0]:+.2f}% ({a.source.iloc[0]})"
              if len(a) else "not in ledger")
        lb = (f"{b.side.iloc[0]} {orr_label(b.k.iloc[0])} {b.why.iloc[0]} {b.R.iloc[0]:+.2f}%" if len(b) else "no backtest trade")
        d, s = (a.date.iloc[0], a.symbol.iloc[0]) if len(a) else (str(b.date.iloc[0]), b.sym.iloc[0])
        L.append(f"| {d} | {s} | {la} | {lb} |")
    both = set(bt.key) & set(lg.key)
    L += ["", f"Ledger {len(lg)} trades, backtest {len(bt)}, in both {len(both)}. "
          f"Ledger total {lg.pct.sum():+.2f}%, backtest total {bt.R.sum():+.2f}% (forward dates only)."]
    return L


def orr_label(k: int) -> str:
    return f"{9 + (30 + int(k)) // 60:02d}:{(30 + int(k)) % 60:02d}"


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    bigtech_only = "--bigtech-only" in argv
    syms = sorted(set(orr.BIG_TECH) | {"SPY", "QQQ"}) if bigtech_only else orr.POOL
    data = load(syms)
    D, common = orr.build(data)
    dates = [d for d in common if pd.Timestamp(PERIODS[0][1]).date() <= d <= pd.Timestamp(PERIODS[-1][2]).date()]
    lab = label(dates)
    reg = spy_trend(D, dates)
    J: dict = {"periods": PERIODS, "sessions": {k: sum(1 for d in dates if lab.get(d) == k) for k in KEYS},
               "noise_floor": FLOOR, "variants": N_VARIANTS}

    # ---- baseline at three cost levels
    base = {c: run(D, dates, lab, replace(BASE, **kw)) for c, kw in COSTS.items()}
    B = {c: per(t) for c, t in base.items()}
    J["baseline"] = B
    t0 = base["realistic"]

    # ---- reproduction of reports/orb_bigtech.md (same rule, same 252 sessions)
    old = [d for d in dates if pd.Timestamp("2025-09-30").date() <= d <= pd.Timestamp("2026-10-02").date()]
    rec, ear = set(old[-63:]), set(old[:-63])
    repro = {"recent": st(t0[t0.date.isin(rec)]), "earlier": st(t0[t0.date.isin(ear)])}
    J["reproduction"] = repro

    # ---- singles, then the passing ones combined
    V, fails = {}, {}
    for nm, (p, use_reg, mr) in SINGLES.items():
        V[nm] = {c: per(run(D, dates, lab, replace(p, **kw), reg if use_reg else None, mr)) for c, kw in COSTS.items()}
        fails[nm] = adopt(B["realistic"], V[nm]["realistic"], B["stressed+late"], V[nm]["stressed+late"])
    passed = [nm for nm in SINGLES if not fails[nm]]
    combo_from = passed if len(passed) >= 2 else list(SINGLES)
    p = BASE
    for nm in combo_from:
        q = SINGLES[nm][0]
        p = replace(p, cluster_max=min(p.cluster_max, q.cluster_max), disp=max(p.disp, q.disp),
                    window_end=min(p.window_end, q.window_end))
    use_reg = any(SINGLES[nm][1] for nm in combo_from)
    mr = max(SINGLES[nm][2] for nm in combo_from)
    cname = ("combined: " if len(passed) >= 2 else "all five combined (information only - fewer than two passed): ") + \
        " + ".join(nm.split(" ")[0] for nm in combo_from)
    combo_t = {c: run(D, dates, lab, replace(p, **kw), reg if use_reg else None, mr) for c, kw in COSTS.items()}
    V[cname] = {c: per(t) for c, t in combo_t.items()}
    fails[cname] = adopt(B["realistic"], V[cname]["realistic"], B["stressed+late"], V[cname]["stressed+late"])
    if len(passed) < 2:
        fails[cname] = ["not eligible (fewer than two singles passed)"] + fails[cname]
    J["variants_results"], J["fails"] = V, fails

    def promoted(nm):
        r = V[nm]["realistic"]
        return not fails[nm] and all(r[k].get("n") and r[k]["avg"] > 0 and r[k]["avg"] >= B["realistic"][k]["avg"]
                                     for k in ("test", "forward"))
    J["promoted"] = [nm for nm in V if promoted(nm)]

    # ---- Stocks-in-Play re-check
    sip = None
    if not bigtech_only:
        sip = {c: per(run(D, dates, lab, replace(CANDIDATE, **kw))) for c, kw in COSTS.items()}
        J["inplay"] = sip

    # ---- write
    S = J["sessions"]
    L = ["# Day-trade ORB audit: big tech (live rule), baseline and five pre-registered changes", "",
         f"Alpaca IEX 1-minute bars. Sessions: train {S['train']} ({PERIODS[0][1]} to {PERIODS[0][2]}), "
         f"validation {S['val']} ({PERIODS[1][1]} to {PERIODS[1][2]}), test {S['test']} ({PERIODS[2][1]} to {PERIODS[2][2]}; "
         f"seen when the big tech list was chosen, so not untouched for the baseline), forward {S['forward']} "
         f"({PERIODS[3][1]} to {PERIODS[3][2]}; untouched).", "",
         f"Rule: `{BASE}`. Names: {', '.join(orr.BIG_TECH)}.", "",
         "Results are % of the account per trade when a full stop costs 1% (sums, not compounded). "
         "Backtest only - the live and paper records are in `reports/audit_baseline.md`.", "",
         "## 1. Reproduction of reports/orb_bigtech.md", "",
         "| range | published trades | published expectancy | reproduced trades | reproduced expectancy |", "|---|---|---|---|---|"]
    for k in ("recent", "earlier"):
        L.append(f"| {k} | {PUBLISHED[k][0]} | {f(PUBLISHED[k][1])} | {repro[k].get('n', 0)} | {f(repro[k].get('avg'))} |")
    L += ["", "Differences come from a longer warm-up history (ATR and volume baselines on the first sessions) and "
          "any IEX bar revisions since 2 Oct.", "", "## 2. Baseline", ""]
    for c in COSTS:
        L += [f"### {c} costs", ""] + period_table(B[c]) + [""]
    L += ["## 3. Baseline breakdowns (realistic costs)", ""]
    L += split_table(t0, "sym", "By ticker")
    L += split_table(t0, "side", "By side")
    L += split_table(t0, lambda d: np.where(d.k < 10, "09:35-09:39", "09:40-09:44"), "By entry time")
    L += split_table(t0, lambda d: pd.Series([("SPY up-trend" if reg.get(x) == "long" else "SPY down-trend") for x in d.date], index=d.index), "By SPY 20-day trend (known at the open)")
    L += split_table(t0, lambda d: pd.Series(np.where([(reg.get(x) == "long") == (s == "long") for x, s in zip(d.date, d.side)], "with SPY trend", "against SPY trend"), index=d.index), "Trade direction vs SPY trend")
    L += split_table(t0, "why", "By exit")
    L += split_table(t0, lambda d: pd.cut(d.rvol5, [0, 0.75, 1.0, 1.5, 99], right=False).astype(str), "By opening relative volume")
    L += split_table(t0, lambda d: pd.cut(d.orw, [0.35, 0.5, 0.75, 99], right=False).astype(str), "By opening range / daily ATR")
    ml, mrows = month_table(t0, D, dates)
    J["months"] = mrows
    mdf = pd.DataFrame(mrows).dropna(subset=["avg"])
    cor = {c: float(mdf["avg"].corr(mdf[c])) for c in ("spy", "vol", "pass_rate", "longs")} if len(mdf) > 3 else {}
    J["month_correlations"] = cor
    L += ["## 4. Month by month (realistic costs) - why recent months worked", ""] + ml + [
        "", "Correlation of the month's expectancy with: " + ", ".join(f"{k} {v:+.2f}" for k, v in cor.items()) +
        f" ({len(mdf)} months; descriptive, not a filter).", ""]
    L += ["## 5. Pre-registered changes", "",
          f"Variants: {N_VARIANTS}. Noise floor sqrt(2 ln {N_VARIANTS}) = {FLOOR:.2f} standard errors.", "",
          "| variant | realistic: train | val | test | forward | train+val t | stressed+late: train | val | verdict |",
          "|---|---|---|---|---|---|---|---|---|"]

    def c2(s):
        return f"{s.get('n', 0)} / {f(s.get('avg'))} / PF {s.get('pf', float('nan')):.2f}" if s.get("n") else "0"
    for nm, r in [("baseline", B)] + list(V.items()):
        R, Lt = r["realistic"], r["stressed+late"]
        verdict = "-" if nm == "baseline" else ("ADOPT" if not fails[nm] else "; ".join(fails[nm]))
        L.append(f"| {nm} | {c2(R['train'])} | {c2(R['val'])} | {c2(R['test'])} | {c2(R['forward'])} | "
                 f"{R['train+val'].get('t', 0):+.2f} | {c2(Lt['train'])} | {c2(Lt['val'])} | {verdict} |")
    L += ["", "Cells: trades / expectancy / profit factor.", "",
          f"Promoted (passes 1-7 and test and forward both positive and >= baseline): {', '.join(J['promoted']) or 'none'}.", ""]
    if sip:
        L += ["## 6. Stocks-in-Play candidate re-check (top 10 by opening relative volume)", ""]
        for c in COSTS:
            L += [f"### {c} costs", ""] + period_table(sip[c]) + [""]
        ok_train = sip["realistic"]["train"].get("avg", -1) > 0 and sip["stressed"]["train"].get("avg", -1) >= 0
        J["inplay_train_pass"] = bool(ok_train)
        L += [f"Untouched train year: {'positive at 0.05% and not negative at 0.10%' if ok_train else 'FAILS (not positive at 0.05%, or negative at 0.10%)'}. "
              "The forward paper criterion is checked in reports/audit_baseline.md.", ""]
    L += ["## 7. Live ledger vs this backtest on the forward dates", ""] + ledger_check(t0) + [""]
    (OUT / "orb_audit.md").write_text("\n".join(L) + "\n")
    (OUT / "orb_audit.json").write_text(json.dumps(J, indent=1, default=str))
    keep = ["sym", "date", "period", "side", "k", "R", "pct", "why", "hold", "rvol5", "orw", "disp", "gap"]
    t0[keep].to_csv(OUT / "orb_audit_trades.csv", index=False)
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    sys.exit(main())
