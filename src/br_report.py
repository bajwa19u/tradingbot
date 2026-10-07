"""Break & Retest V1: statistics and the markdown that reports them.

Win %, profit and winners vs losers lead every table (the house rule); the R
columns the V1 spec asks for follow. Dollars assume `risk.risk_dollars` at
risk per trade. Every verdict checks the all-negative case first.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

RNG = np.random.default_rng(7)
TOD = [(570, 600, "09:30-10:00"), (600, 630, "10:00-10:30"), (630, 660, "10:30-11:00"),
       (660, 691, "11:00-11:30")]


def stats(df: pd.DataFrame, risk_dollars: float = 1000.0) -> dict:
    if df is None or df.empty or "r" not in df:
        return {"n": 0}
    df = df[df.r.notna()]
    if df.empty:
        return {"n": 0}
    r = df.r.astype(float).to_numpy()
    n = len(r)
    w, l = r[r > 0], r[r <= 0]
    eq = np.cumsum(r)
    dd = float((np.maximum.accumulate(np.concatenate([[0], eq]))[1:] - eq).max()) if n else 0.0
    out = {"n": n, "wins": len(w), "losses": len(l), "win": 100 * len(w) / n,
           "profit": float(r.sum() * risk_dollars), "avg": float(r.mean()), "med": float(np.median(r)),
           "total": float(r.sum()), "pf": float(w.sum() / -l.sum()) if l.sum() < 0 else math.inf,
           "dd": dd, "dd_usd": dd * risk_dollars,
           "dur": float(df.duration_min.mean()) if "duration_min" in df else float("nan")}
    out["exp_usd"] = out["avg"] * risk_dollars
    if n >= 5:
        boot = RNG.choice(r, size=(2000, n)).mean(axis=1)
        out["ci"] = (float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5)))
    return out


HEAD = ("| {k} | trades | won | lost | win % | profit | avg R | median R | total R | PF | max DD | avg min |\n"
        "|---|---|---|---|---|---|---|---|---|---|---|---|")


def row(name, s: dict) -> str:
    if not s.get("n"):
        return f"| {name} | 0 | | | | | | | | | | |"
    pf = "inf" if s["pf"] == math.inf else f"{s['pf']:.2f}"
    return (f"| {name} | {s['n']} | {s['wins']} | {s['losses']} | {s['win']:.1f}% | "
            f"{_usd(s['profit'])} | {s['avg']:+.3f} | {s['med']:+.2f} | {s['total']:+.1f} | {pf} | "
            f"{_usd(-s['dd_usd'])} | {_mins(s['dur'])} |")


def _mins(x: float) -> str:
    return "" if x != x else f"{x:.0f}"


def _usd(x: float) -> str:
    return f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}"


def table(df: pd.DataFrame, by, label: str, risk: float, order=None, min_n: int = 1) -> str:
    lines = [HEAD.format(k=label)]
    if df.empty:
        return lines[0] + "\n| (none) |"
    groups = df.groupby(by, dropna=False)
    keys = order if order is not None else sorted(groups.groups, key=lambda x: str(x))
    for k in keys:
        if k not in groups.groups:
            continue
        g = groups.get_group(k)
        if len(g) >= min_n:
            lines.append(row(k, stats(g, risk)))
    return "\n".join(lines)


def tod_label(minute: float) -> str:
    for a, b, name in TOD:
        if a <= minute < b:
            return name
    return "other"


def noise_floor(n_variants: int) -> float:
    return math.sqrt(2 * math.log(max(n_variants, 2)))


def verdict(s: dict) -> str:
    """All-negative case first: a losing number is never described as working."""
    if not s.get("n"):
        return "no trades"
    if s["avg"] <= 0 or s["total"] <= 0:
        return "LOSING - does not work as specified"
    lo = s.get("ci", (s["avg"], s["avg"]))[0]
    if lo <= 0:
        return "positive but not distinguishable from zero (95% CI includes 0)"
    return "positive, CI above zero"


def pct(series) -> str:
    s = pd.Series(series).dropna()
    return f"{100 * s.astype(float).mean():.0f}%" if len(s) else "n/a"


def stop_section(t: pd.DataFrame, cfg) -> str:
    st = t[t.outcome == "stop"]
    hz = list(cfg.analysis.post_exit_minutes)
    out = [f"Stops hit: **{len(st)}** of {len(t)} trades.\n"]
    if st.empty:
        return out[0]
    out.append("| after the stop | back to entry | reached 1R | reached original 2R | avg best R (from entry) |")
    out.append("|---|---|---|---|---|")
    for m in hz + ["eod"]:
        e, one, two, mfe = (f"sl_entry_{m}", f"sl_1r_{m}", f"sl_2r_{m}", f"sl_mfe_{m}")
        if e not in st:
            continue
        lab = "rest of day" if m == "eod" else f"+{m} min"
        out.append(f"| {lab} | {pct(st[e])} | {pct(st[one]) if one in st else 'n/a'} | {pct(st[two])} | "
                   f"{st[mfe].mean():+.2f} |")
    cls = st.sl_class.value_counts()
    out.append("\n| classification (within +%d min) | stops | share |" % hz[-1])
    out.append("|---|---|---|")
    for k in ("TRUE FAILURE", "POSSIBLY TOO-TIGHT STOP", "STOP-OUT -> 2R RECOVERY"):
        out.append(f"| {k} | {int(cls.get(k, 0))} | {100 * cls.get(k, 0) / len(st):.0f}% |")
    return "\n".join(out)


def tp_section(t: pd.DataFrame, cfg) -> str:
    tp = t[t.outcome == "target"]
    hz = list(cfg.analysis.post_exit_minutes)
    out = [f"2R targets hit: **{len(tp)}** of {len(t)} trades.\n"]
    if tp.empty:
        return out[0]
    out.append("| after the target | reached 3R | reached 4R | avg extra R beyond 2R |")
    out.append("|---|---|---|---|")
    for m in hz:
        if f"tp_3r_{m}" not in tp:
            continue
        out.append(f"| +{m} min | {pct(tp[f'tp_3r_{m}'])} | {pct(tp[f'tp_4r_{m}'])} | "
                   f"{tp[f'tp_extra_r_{m}'].mean():+.2f} |")
    if "tp_extra_r_eod" in tp:
        out.append(f"| rest of day | | | {tp.tp_extra_r_eod.mean():+.2f} |")
    out.append(f"\nReversed within {hz[0]} minutes (gave back to +1R or worse): "
               f"**{pct(tp.tp_reversed_fast)}** of 2R hits.")
    return "\n".join(out)


ALT_NAMES = {"after_2r": "trail 1R behind the high after 2R", "none": "no target (stop or time exit)"}


def alt_section(t: pd.DataFrame, prefix: str, label: str, split_col: str, risk: float) -> str:
    cols = [c for c in t.columns if c.startswith(prefix)]
    if not cols:
        return ""
    lines = [f"| {label} | period | trades | win % | profit | avg R | PF |", "|---|---|---|---|---|---|---|"]
    for c in cols:
        name = ALT_NAMES.get(c[len(prefix):], c[len(prefix):])
        for per in ("in-sample", "out-of-sample"):
            g = t[t[split_col] == per]
            s = stats(g.assign(r=g[c]), risk)
            if not s.get("n"):
                continue
            pf = "inf" if s["pf"] == math.inf else f"{s['pf']:.2f}"
            lines.append(f"| {name} | {per} | {s['n']} | {s['win']:.1f}% | {_usd(s['profit'])} | "
                         f"{s['avg']:+.3f} | {pf} |")
    return "\n".join(lines)


HINDSIGHT = {"retest_timeout", "window_closed", "failed_breakout", "confirm_timeout"}


def missed_section(conf: pd.DataFrame, fails: pd.DataFrame, taken: pd.DataFrame, risk: float, top: int = 15) -> str:
    """Rejected setups and what they would have done.

    Two kinds, and only one of them can indict a rule:
      blocked          a complete setup stopped by a rule (inactive level, gap,
                       open position, daily cap). Its outcome is a fair test of
                       that rule; it is flagged when its rejects beat the trades
                       taken on 20+ setups.
      never completed  a breakout that never retested/confirmed, simulated as if
                       bought at the break. These are SELECTED BY WHAT PRICE DID
                       NEXT ("retest_timeout" means price ran away and never came
                       back), so they win or lose by construction and are never
                       flagged. The fair question - "should we skip the retest?" -
                       is answered by buying EVERY breakout at its close, below.
    """
    base = stats(taken, risk)
    rej = conf[~conf.taken & conf.r.notna()].assign(stage="blocked")
    flr = fails[fails.r.notna()].assign(stage="never completed (at the break, hindsight-selected)",
                                        reject_reason=fails.status) if len(fails) else fails
    allr = pd.concat([rej, flr], ignore_index=True) if len(flr) else rej
    lines = ["| rejected by | stage | setups | would-win % | would-profit | avg R | vs trades taken |",
             "|---|---|---|---|---|---|---|"]
    flags = []
    for (reason, stage), g in allr.groupby(["reject_reason", "stage"]):
        s = stats(g, risk)
        better = (stage == "blocked" and base.get("n") and s["n"] >= 20
                  and s["avg"] > base["avg"] and s["avg"] > 0)
        mark = "**REVIEW: rejects beat trades**" if better else (
            "not evidence (selected by outcome)" if reason in HINDSIGHT else "")
        if better:
            flags.append(reason)
        lines.append(f"| {reason} | {stage} | {s['n']} | {s['win']:.1f}% | {_usd(s['profit'])} | "
                     f"{s['avg']:+.3f} | {mark} |")
    # The fair test of the retest rule: every breakout, bought at its close.
    every = pd.concat([conf[["r_at_break"]], fails[["r_at_break"]] if len(fails) else None])
    every = every.rename(columns={"r_at_break": "r"}).dropna()
    se = stats(every, risk)
    lines.append("\n**Is waiting for the retest worth it?** The same breakouts, every one bought at the "
                 "breakout candle's close with the same stop and target:\n")
    lines.append(HEAD.format(k="entry"))
    lines.append(row("every breakout, at the break", se))
    lines.append(row("V1 (break, retest, confirm)", base))
    best = rej.sort_values("r", ascending=False).head(top)
    lines.append(f"\n**Most profitable complete setups that a rule blocked (top {top}):**\n")
    lines.append("| date | time | symbol | side | level | blocked by | would-R |")
    lines.append("|---|---|---|---|---|---|---|")
    for _, r in best.iterrows():
        lines.append(f"| {r.date} | {pd.Timestamp(r.t_known):%H:%M} | {r.symbol} | {r.direction} | "
                     f"{r.level_name} {r.level:.2f} | {r.reject_reason} | {r.r:+.2f} |")
    head = ("Rules flagged for review (blocked complete setups beat the trades taken, 20+ setups): "
            + (", ".join(f"`{f}`" for f in flags) if flags else "none") + "\n\n")
    return head + "\n".join(lines)


def funnel(ev: pd.DataFrame, tfs, cfg) -> str:
    from .br_run import _keys
    e = ev[ev.tf.isin(list(tfs))].sort_values("tf")
    k = _keys(e, cfg).astype(str)
    one = e[~(k + e.attempt.astype(str)).duplicated()]
    retested = one[one.touch_ts.notna()]
    conf = e[(e.status == "confirmed") & ~k.duplicated()]
    lines = ["| stage | count |", "|---|---|",
             f"| breakouts (close beyond a level) | {len(one)} |",
             f"| ... of which retested | {len(retested)} |",
             f"| ... of which confirmed | {len(conf)} |"]
    for k, v in one.status.value_counts().items():
        if k != "confirmed":
            lines.append(f"| ended as `{k}` | {v} |")
    return "\n".join(lines)
