"""ORB on stocks in play: the open questions from reports/orb_research.md.

1. Real execution cost. Every candidate trade is re-priced with the NBBO (SIP
   quotes; free for anything older than 15 minutes): entry at the ask (long) or
   bid (short) a few seconds after the breakout bar closes - when a live signal
   can be acted on - against the IEX close the rule saw. Exits: a target is a
   resting limit (no cost); a bell exit sells at the bid / buys at the ask
   after the 15:55 bar; a stop pays the half-spread on top of the stop price.
2. Data source. The candidate re-run on SIP (consolidated) minute bars instead
   of IEX's slice of the tape.
3. Survivorship. The pool rebuilt every day from EVERY listed and delisted US
   equity in Alpaca's asset list, by point-in-time price and dollar volume.
4. Premarket. Ranking by 04:00-09:15 SIP volume against its own normal. On the
   free plan that is known live by 09:30 (15-minute delay), so unlike IEX
   premarket it is usable. One pre-registered variant, the usual adoption rule.

The gate at the bottom was fixed before the first run. Nothing here changes a
live setting; a pass is acted on by hand.

Usage: python -m src.orb_checks [--days 252] [--skip broad]
"""
from __future__ import annotations

import argparse
import bisect
import json
import math
import os
import pickle
import re
import sys
import time as _time
from dataclasses import replace

import numpy as np
import pandas as pd
import requests

from . import orb_research as orr
from .config import REPO_ROOT, Credentials
from .data import MarketData

ET = orr.EASTERN
CAND = orr.P(universe="top10", orw=(0.35, 9e9))
PM = replace(CAND, universe="pm10")
REPORT = REPO_ROOT / "reports" / "orb_checks.md"
CACHE = REPO_ROOT / "cache" / "orb_checks"
PAPER_API = "https://paper-api.alpaca.markets"    # read-only asset list; never orders
EXCHANGES = {"NYSE", "NASDAQ", "ARCA", "AMEX", "BATS"}
ENTRY_DELAY_S = (4, 15)            # live acts a few seconds after the bar closes
FALLBACK = 0.0005                  # per side, when no quote can be found
MAX_GAP = 0.01                     # a quote this far from the bar is a split or a bad print, not a cost


class Throttled(MarketData):
    """Alpaca's free plan allows 200 requests a minute; stay under it."""
    gap = 0.32

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._last = 0.0

    def _get(self, path, params, retries=6):
        wait = self._last + self.gap - _time.time()
        if wait > 0:
            _time.sleep(wait)
        self._last = _time.time()
        return super()._get(path, params, retries)


def md(feed: str) -> Throttled:
    return Throttled(Credentials.from_env(), feed=feed)


def cached(name: str, make):
    f = CACHE / name
    if f.exists():
        return pickle.loads(f.read_bytes())
    out = make()
    CACHE.mkdir(parents=True, exist_ok=True)
    f.write_bytes(pickle.dumps(out))
    return out


# ============================================================ quotes
def first_nbbo(quotes: list[dict]) -> tuple[float, float] | None:
    """The first sane quote: both sides present, not crossed, spread under 2%."""
    for q in quotes:
        bp, ap = float(q.get("bp") or 0), float(q.get("ap") or 0)
        if bp > 0 and ap > bp and (ap - bp) / ap < 0.02:
            return bp, ap
    return None


def nbbo_at(m: MarketData, sym: str, t: pd.Timestamp, span_s: tuple = ENTRY_DELAY_S):
    q = m.quotes(sym, (t + pd.Timedelta(seconds=span_s[0])).isoformat(),
                 (t + pd.Timedelta(seconds=span_s[1])).isoformat(), limit=100)
    return first_nbbo(q)


def bar_close_ts(d, k: int) -> pd.Timestamp:
    return pd.Timestamp(f"{d} 09:30", tz=ET) + pd.Timedelta(minutes=k + 1)


def trade_costs(m: MarketData, D: dict, rows: pd.DataFrame) -> pd.DataFrame:
    """Per trade: entry and exit cost as a fraction of price, from the NBBO."""
    out = []
    for r in rows.itertuples():
        x = D[r.sym][r.date]
        sgn = 1 if r.side == "long" else -1
        c = float(x.c[r.k])
        ce = cx = None
        try:
            q = nbbo_at(m, r.sym, bar_close_ts(r.date, r.k))
            if q:
                fill = q[1] if sgn > 0 else q[0]
                ce = sgn * (fill - c) / c if abs(fill - c) / c <= MAX_GAP else None
            j = r.k + int(r.hold)
            if r.why == "target":
                cx = 0.0
            elif r.why == "bell":
                q = nbbo_at(m, r.sym, bar_close_ts(r.date, j))
                if q:
                    cj = float(x.c[j])
                    fill = q[0] if sgn > 0 else q[1]
                    cx = sgn * (cj - fill) / cj if abs(fill - cj) / cj <= MAX_GAP else None
            else:                                           # stop: half the spread when it triggers
                q = nbbo_at(m, r.sym, bar_close_ts(r.date, j - 1), (0, 60))
                if q:
                    cx = (q[1] - q[0]) / 2 / ((q[0] + q[1]) / 2)
        except Exception as exc:                            # noqa: BLE001
            print(f"quote failed {r.sym} {r.date}: {exc}", flush=True)
        out.append(dict(ce=ce, cx=cx))
    return pd.DataFrame(out, index=rows.index, columns=["ce", "cx"], dtype=float)


def reprice(rows: pd.DataFrame, cost_total: pd.Series) -> pd.DataFrame:
    """Gross R minus a per-trade round-trip cost (fraction of price)."""
    return rows.assign(R=rows.R - cost_total * 100 / rows.risk_pct)


# ============================================================ SIP minute bars + premarket
def load_sip(days: int) -> tuple[dict, dict]:
    """Regular-session SIP minute bars and 04:00-09:15 premarket volume per day."""
    def make():
        m = md("sip")
        now = pd.Timestamp.now(tz=ET)
        start = (now - pd.Timedelta(days=int((days + orr.LOOKBACK + 25) * 1.45))).date().isoformat()
        end = sip_end()
        bars, pm = {}, {}
        for i in range(0, len(orr.POOL), 6):
            chunk = orr.POOL[i:i + 6]
            got = m.intraday_bars(chunk, 1, start=start, end=end, extended=True)
            for s, df in got.items():
                if df.empty:
                    continue
                t = df.index.tz_convert(ET)
                mins = t.hour * 60 + t.minute
                pre = df[(mins >= 240) & (mins < 555)]
                pm[s] = {d: float(v) for d, v in pre.volume.groupby(pre.index.date).sum().items()}
                bars[s] = df[(mins >= 570) & (mins < 960)].astype("float32")
            print(f"sip {i + len(chunk)}/{len(orr.POOL)}", flush=True)
        return bars, pm
    return cached(f"sip_wide_{days}.pkl", make)


def attach_pm(D: dict, pm: dict) -> None:
    """pm_rvol = today's premarket volume / mean of the prior 14 sessions'."""
    for s, days in D.items():
        series = pm.get(s, {})
        ds = sorted(days)
        vals = [series.get(d, 0.0) for d in ds]
        for i, d in enumerate(ds):
            prev = vals[max(0, i - orr.LOOKBACK):i]
            base = np.mean(prev) if len(prev) >= 10 else 0.0
            days[d].pm_rvol = vals[i] / base if base > 0 else np.nan


# ============================================================ survivorship-free universe
def asset_list() -> dict[str, str]:
    key = os.environ.get("ALPACA_PAPER_KEY") or os.environ.get("ALPACA_API_KEY", "")
    sec = os.environ.get("ALPACA_PAPER_SECRET") or os.environ.get("ALPACA_API_SECRET", "")
    out = {}
    for status in ("inactive", "active"):                 # active last, so it wins a reused ticker
        r = requests.get(f"{PAPER_API}/v2/assets", params={"status": status, "asset_class": "us_equity"},
                         headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec}, timeout=60)
        r.raise_for_status()
        for a in r.json():
            s = a.get("symbol", "")
            if a.get("exchange") in EXCHANGES and re.fullmatch(r"[A-Z]{1,5}", s):
                out[s] = status
    return out


def sip_end() -> str:
    """The free plan serves consolidated data older than 15 minutes."""
    return (pd.Timestamp.now(tz=ET) - pd.Timedelta(minutes=20)).isoformat()


def broad_daily(syms: list[str], start: str) -> dict[str, pd.DataFrame]:
    m = md("sip")
    out = {}
    for i in range(0, len(syms), 200):
        for s, df in m.daily_bars(syms[i:i + 200], start=start, end=sip_end()).items():
            if len(df) >= 20:
                df = df.copy()
                df.index = pd.Index([t.date() for t in df.index])
                pc = df.close.shift(1)
                tr = pd.concat([df.high - df.low, (df.high - pc).abs(), (df.low - pc).abs()], axis=1).max(axis=1)
                df["prev_c"], df["gap"] = pc, df.open / pc - 1
                df["atr"] = tr.shift(1).rolling(orr.LOOKBACK).mean()
                df["adv"] = (df.close * df.volume).shift(1).rolling(orr.LOOKBACK).mean()
                out[s] = df
        print(f"daily {min(i + 200, len(syms))}/{len(syms)}", flush=True)
    return out


def broad_open(syms: list[str], sessions: list, rank: str) -> dict:
    """Per session, per symbol: (volume, high, low) of the 09:30-09:34 bar, or
    premarket volume when rank == "pm"."""
    m = md("sip")
    out = {}
    for n, d in enumerate(sessions):
        if rank == "pm":
            t0, t1, tf, ext = f"{d} 04:00", f"{d} 09:14", 15, True
        else:
            t0, t1, tf, ext = f"{d} 09:30", f"{d} 09:34", 5, False
        day = {}
        for i in range(0, len(syms), 400):
            got = m.intraday_bars(syms[i:i + 400], tf, start=pd.Timestamp(t0, tz=ET).isoformat(),
                                  end=pd.Timestamp(t1, tz=ET).isoformat(), extended=ext)
            for s, df in got.items():
                if len(df):
                    day[s] = (float(df.volume.sum()), float(df.high.max()), float(df.low.min()))
        out[d] = day
        if n % 20 == 0:
            print(f"open bars {n + 1}/{len(sessions)}", flush=True)
    return out


def broad_trades(p: orr.P, dates: list, lab: dict, D_sip: dict, days: int) -> tuple[pd.DataFrame, dict]:
    status = cached("assets.pkl", asset_list)
    syms = sorted(status)
    start = (pd.Timestamp(dates[0]) - pd.Timedelta(days=45)).date().isoformat()
    daily = cached(f"broad_daily_{days}.pkl", lambda: broad_daily(syms, start))
    spy = daily.get("SPY")
    sessions = [d for d in spy.index if d >= spy.index[0]] if spy is not None else []
    first = sessions.index(dates[0]) if dates[0] in sessions else 0
    sessions = sessions[max(0, first - orr.LOOKBACK - 1):]
    elig = {d: [] for d in dates}
    for s, df in daily.items():
        if s in ("SPY", "QQQ"):
            continue
        ok = (df.prev_c >= 5) & (df.adv >= 5e7) & (df.atr > 0)
        for d in df.index[ok.to_numpy()]:
            if d in elig:
                elig[d].append(s)
    S = sorted({s for v in elig.values() for s in v})
    rank = "pm" if p.universe.startswith("pm") else "rvol5"
    opens = cached(f"broad_open_{rank}_{days}.pkl", lambda: broad_open(S, sessions, rank))
    m = md("sip")
    rows, info = [], {"symbols_listed": len(syms), "inactive_listed": sum(v == "inactive" for v in status.values()),
                      "eligible_per_day": float(np.mean([len(v) for v in elig.values()])) if elig else 0}
    picked = []
    for d in dates:
        if d not in D_sip.get("SPY", {}) or d not in D_sip.get("QQQ", {}):
            continue
        i = sessions.index(d) if d in sessions else None
        if i is None or i < orr.LOOKBACK:
            continue
        prior = sessions[i - orr.LOOKBACK:i]
        cand = []
        for s in elig[d]:
            today = opens.get(d, {}).get(s)
            base = [opens.get(q, {}).get(s, (0.0,))[0] for q in prior]
            if today is None or np.mean(base) <= 0:
                continue
            cand.append((today[0] / np.mean(base), s))
        top = [s for _, s in sorted(cand, reverse=True)[:int(p.universe[-2:])]]
        rv = dict((s, v) for v, s in cand)
        keep = [s for s in top if (opens[d][s][1] - opens[d][s][2]) / daily[s].at[d, "atr"] >= p.orw[0]] \
            if rank == "rvol5" else top
        picked += [(d, s) for s in top]
        if not keep:
            continue
        got = m.intraday_bars(keep, 1, start=pd.Timestamp(f"{d} 09:30", tz=ET).isoformat(),
                              end=pd.Timestamp(f"{d} 16:00", tz=ET).isoformat())
        sa = D_sip["SPY"][d].c > D_sip["SPY"][d].vwap
        qa = D_sip["QQQ"][d].c > D_sip["QQQ"][d].vwap
        for s in keep:
            df = got.get(s)
            arr = orr.to_days(df, min_bars=100).get(d) if df is not None and len(df) else None
            if arr is None:
                continue
            row = daily[s].loc[d]
            tp = (arr[1] + arr[2] + arr[3]) / 3
            cv = np.cumsum(arr[4])
            vwap = np.where(cv > 0, np.cumsum(tp * arr[4]) / np.maximum(cv, 1e-9), arr[3])
            or_h, or_l = float(arr[1, :5].max()), float(arr[2, :5].min())
            x = orr.Day(arr[0], arr[1], arr[2], arr[3], arr[4], vwap, or_h, or_l, or_h - or_l, rv[s],
                        np.ones(orr.N_MIN), float(row.prev_c), float(row.atr), float(row.adv), float(row.gap))
            sig = orr.first_signal(x, sa, qa, p, orr.FLAT_IDX - 1, D_sip["SPY"][d])
            if sig is None:
                continue
            R, j, why = orr.exit_r(x, sig["kk"], sig["sign"], sig["entry"], sig["stop"], p)
            rps = abs(sig["entry"] - sig["stop"])
            rows.append(dict(sym=s, date=d, period=lab[d], side=sig["side"], k=sig["k"], R=float(R), hold=j - sig["kk"],
                             why=why, pct=float(R) * rps / sig["entry"] * 100, risk_pct=rps / sig["entry"] * 100,
                             inactive=status.get(s) == "inactive", in_pool=s in orr.POOL))
    info["picks"] = len(picked)
    info["picks_outside_pool"] = sum(1 for _, s in picked if s not in orr.POOL)
    info["picks_inactive"] = sum(1 for _, s in picked if status.get(s) == "inactive")
    return pd.DataFrame(rows), info


# ============================================================ report helpers
def per3(df: pd.DataFrame) -> dict:
    return orr.per(df) if len(df) else {k: orr.stats(df) for k in ("train", "val", "test")}


def row3(name: str, st: dict) -> str:
    def c(s):
        if s["n"] == 0:
            return "0 | | | |"
        return f"{s['n']} | {s['win']:.1f}% | {s['avg']:+.3f}% | {s['pf']:.2f} | {s['total']:+.1f}%"
    return f"| {name} | {c(st['train'])} | {c(st['val'])} | {c(st['test'])} |"


H3 = ("| version | train n | win | per trade | PF | total | val n | win | per trade | PF | total | "
      "test n | win | per trade | PF | total |\n|" + "---|" * 16)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=252)
    ap.add_argument("--skip", default="", help="comma list of: costs, sip, broad, pm")
    args = ap.parse_args(argv)
    skip = set(filter(None, args.skip.split(",")))

    D, common = orr.build(orr.load(args.days, False))
    dates = common[-args.days:]
    a, b = int(len(dates) * 0.6), int(len(dates) * 0.8)
    lab = {d: ("train" if i < a else "val" if i < b else "test") for i, d in enumerate(dates)}
    run = lambda p, DD=D, dd=dates: orr.trades(DD, dd, lab, p)
    res, notes = {}, []
    L = ["# ORB on stocks in play: the open questions", "",
         f"{len(dates)} sessions ({dates[0]} to {dates[-1]}), the same train / validation / test dates as "
         "reports/orb_research.md. Results are per trade as a share of the account at the live sizing "
         "(a full stop = 1% of the account; the same number is R). Nothing here changes a live setting.", "",
         "## The gate (fixed before the first run)", "",
         "1. Measured costs: test per trade > 0.",
         "2. Measured costs: test 95% interval above zero.",
         "3. Stress (the larger of measured + 0.05% per side and 0.10% per side): test > 0.",
         "4. Stress: validation > 0.",
         "5. Measured costs: test > 0 without its best 3 stocks.",
         "6. SIP bars instead of IEX: test > 0 at 0.05% per side.",
         "7. Survivorship-free universe: test > 0 at 0.05% per side.",
         "",
         "If the premarket ranking (section 4) is adopted by the usual rule, the gate is run on that version.", ""]

    # ---------------------------------------------------------------- 4 first: it decides the final version
    final = CAND
    sip_bars = pm = None
    if not ({"pm", "sip"} <= skip):
        try:
            sip_bars, pm = load_sip(args.days)
        except Exception as exc:                                # noqa: BLE001
            notes.append(f"SIP minute bars unavailable: {exc}")
    sec4 = ["## 4. Premarket ranking (live-usable through delayed SIP)", ""]
    if pm is not None and "pm" not in skip:
        attach_pm(D, pm)
        cur, alt = orr.per(run(CAND)), orr.per(run(PM))
        alt2 = orr.per(run(replace(PM, slip=CAND.slip * 2)))
        ok, why = orr.adopt(cur, alt, alt2)
        sec4 += ["Top 10 by 04:00-09:15 consolidated volume against its own 14-session normal, same range filter "
                 "and rules. Decided on train + validation by the same adoption rule as every stage.", "",
                 *orr.fam_table([("first-5-minute ranking (current)", cur, "incumbent"),
                                 ("premarket ranking", alt, why)], show_test=True), ""]
        res["pm_adopted"] = ok
        if ok:
            final = PM
            sec4.append("**Adopted.** The rest of this report tests the premarket version.")
        else:
            sec4.append(f"**Not adopted** ({why}). The rest of this report tests the first-5-minute version.")
    else:
        sec4.append("Not run: " + ("; ".join(notes) or "skipped"))
    sec4.append("")

    base_rows = run(final)
    gross = run(replace(final, slip=0.0))
    gate = {}

    # ---------------------------------------------------------------- 1. measured costs
    sec1 = ["## 1. Real execution cost (NBBO at the moment a live signal can act)", ""]
    if "costs" not in skip:
        try:
            costs = cached(f"costs_{final.universe}_{args.days}.pkl", lambda: trade_costs(md("sip"), D, gross))
            miss_e, miss_x = costs.ce.isna().sum(), costs.cx.isna().sum()
            ce, cx = costs.ce.fillna(FALLBACK), costs.cx.fillna(FALLBACK)
            tot = ce + cx
            meas = reprice(gross, tot)
            stress = reprice(gross, np.maximum(tot + 0.001, 0.002))
            sm, ss = orr.per(meas), orr.per(stress)
            q = lambda s: f"{100 * s.median():.3f}% | {100 * s.mean():.3f}% | {100 * s.quantile(.9):.3f}%"
            sec1 += [f"{len(gross)} trades. Usable quotes for {len(gross) - miss_e} entries and "
                     f"{len(gross) - miss_x} exits; the rest (no quote, or more than 1% from the bar - "
                     "bars are split-adjusted, quotes are not) use 0.05%.", "",
                     "| cost | median | mean | 90th percentile |", "|---|---|---|---|",
                     f"| entry (fill vs the bar close the rule saw) | {q(costs.ce.dropna())} |",
                     f"| exit | {q(costs.cx.dropna())} |",
                     f"| round trip | {q(tot)} |",
                     f"| assumed so far | 0.100% | 0.100% | 0.100% |", "",
                     H3, row3("assumed 0.05% per side", orr.per(base_rows)), row3("measured costs", sm),
                     row3("stress", ss), ""]
            for side in ("long", "short"):
                g = meas[meas.side == side]
                sec1.append(f"- {side}: measured per trade {g.R.mean():+.3f}% over {len(g)} trades")
            sec1.append("")
            te = meas[meas.period == "test"]
            top3 = te.groupby("sym").R.sum().sort_values().index[-3:]
            gate[1] = sm["test"]["avg"] > 0
            gate[2] = sm["test"]["ci"][0] > 0
            gate[3] = ss["test"]["avg"] > 0
            gate[4] = ss["val"]["avg"] > 0
            gate[5] = te[~te.sym.isin(top3)].R.mean() > 0
            res["measured"] = {k: {kk: v for kk, v in sm[k].items() if kk != "ci"} for k in sm}
            res["cost_round_trip_median_pct"] = float(100 * tot.median())
        except Exception as exc:                                # noqa: BLE001
            sec1.append(f"Not run: {exc}")
    else:
        sec1.append("Skipped.")
    sec1.append("")

    # ---------------------------------------------------------------- 2. SIP bars
    sec2 = ["## 2. Consolidated (SIP) bars instead of IEX", ""]
    D_sip = None
    if sip_bars is not None and "sip" not in skip:
        try:
            D_sip, common_s = orr.build(sip_bars)
            if pm is not None:
                attach_pm(D_sip, pm)
            ds = [d for d in dates if d in set(common_s)]
            st_c, st_f = per3(run(orr.P(), D_sip, ds)), per3(run(final, D_sip, ds))
            sec2 += [f"{len(ds)} of {len(dates)} sessions have SIP bars for SPY and QQQ.", "", H3,
                     row3("live rule, static 10 (SIP)", st_c), row3(f"candidate {final.universe} (SIP)", st_f),
                     row3(f"candidate {final.universe} (IEX, for reference)", orr.per(base_rows)), ""]
            ov = [len(set(orr.select(D, d, final.universe)) & set(orr.select(D_sip, d, final.universe)))
                  for d in ds]
            sec2.append(f"Same names picked from IEX and SIP volume: {np.mean(ov):.1f} of 10 on average.")
            # What live actually does: rank on IEX volume (the only real-time feed), but the
            # trade happens at real prices. Same picks as the IEX study, SIP price path.
            D_h = {s: {d: replace(x, rvol5=D[s][d].rvol5) for d, x in days.items() if d in D.get(s, {})}
                   for s, days in D_sip.items()}
            for s in ("SPY", "QQQ"):
                D_h[s] = D_sip[s]
            sec2 += ["", "### What live does: picks from IEX volume, prices from the consolidated tape", "", H3]
            for sl in (0.00025, 0.0005, 0.001):
                st_h = per3(run(replace(final, slip=sl), D_h, ds))
                sec2.append(row3(f"IEX picks, SIP prices, {sl * 100:.3f}% a side", st_h))
                res[f"hybrid_{sl}"] = {k: st_h[k]["avg"] for k in st_h}
            sec2.append("0.025% a side is about the measured median round trip (section 1).")
            gate[6] = st_f["test"]["avg"] > 0
            res["sip_test"] = st_f["test"]["avg"]
        except Exception as exc:                                # noqa: BLE001
            sec2.append(f"Not run: {exc}")
    else:
        sec2.append("Not run: " + ("; ".join(notes) or "skipped"))
    sec2.append("")

    # ---------------------------------------------------------------- 3. survivorship-free universe
    sec3 = ["## 3. Survivorship-free universe (every listed and delisted US equity)", ""]
    if D_sip is not None and "broad" not in skip:
        try:
            bt, info = broad_trades(final, dates, lab, D_sip, args.days)
            st_b = per3(bt)
            st_cur = per3(run(final, D_sip, [d for d in dates if d in D_sip.get("SPY", {})]))
            sec3 += [f"Alpaca lists {info['symbols_listed']} US equity tickers on the main exchanges "
                     f"({info['inactive_listed']} delisted or inactive). On an average day "
                     f"{info['eligible_per_day']:.0f} pass price >= 5 and 14-day dollar volume >= 50M as known "
                     "that morning. Ranked the same way, SIP data.", "",
                     f"Of {info['picks']} daily picks, {info['picks_outside_pool']} were outside the hand-made pool "
                     f"and {info['picks_inactive']} are no longer listed.", "", H3,
                     row3("hand-made pool (SIP)", st_cur), row3("every listed name (SIP)", st_b), ""]
            if len(bt):
                for nm, g in (("names outside the old pool", bt[~bt.in_pool]), ("names in the old pool", bt[bt.in_pool])):
                    sec3.append(f"- {nm}: {len(g)} trades, per trade {g.R.mean():+.3f}%")
            gate[7] = st_b["test"]["avg"] > 0
            res["broad_test"] = st_b["test"]["avg"]
        except Exception as exc:                                # noqa: BLE001
            sec3.append(f"Not run: {exc}")
    else:
        sec3.append("Not run (needs the SIP bars from section 2)." if D_sip is None else "Skipped.")
    sec3.append("")

    names = {1: "measured costs: test > 0", 2: "measured costs: test 95% interval above zero",
             3: "stress: test > 0", 4: "stress: validation > 0", 5: "measured costs: test > 0 without best 3 stocks",
             6: "SIP bars: test > 0", 7: "survivorship-free universe: test > 0"}
    passed = all(gate.get(i, False) for i in names)
    verdict = ["## Gate result", "", f"Version tested: `{final.universe}` with range >= {final.orw[0]} ATR.", ""]
    verdict += [f"- {'PASS' if gate.get(i) else 'FAIL' if i in gate else 'NOT RUN'}: {n}" for i, n in names.items()]
    verdict += ["", f"**{'PASSED' if passed else 'FAILED'}.**", ""]
    L += verdict + sec1 + sec2 + sec3 + sec4
    out = "\n".join(L) + "\n"
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(out)
    REPORT.with_suffix(".json").write_text(json.dumps(
        {"final": final.universe, "gate": {names[i]: gate.get(i) for i in names}, "passed": passed, **res},
        indent=1, default=str))
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
