"""Break & Retest V1: the baseline backtest and its report.

Runs the V1 rules exactly as written in br_config.yaml on SIP (consolidated)
1-minute bars, 04:00-16:00, for the fixed universe. Nothing is optimised.
Dates are split by time: the first `in_sample_fraction` is in-sample, the
rest out-of-sample, and every table shows both.

Writes reports/br_v1/baseline.md (+ .json, trades.csv, candidates.csv.gz) and
charts for a sample of trades under reports/br_v1/charts/ (all of them with
--charts all). Nothing is posted, nothing is traded.

Usage: python -m src.br_backtest [--days 252] [--refresh] [--charts sample]
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
import time as _time

import numpy as np
import pandas as pd

from . import br_bench, br_chart
from . import br_config as bcfg
from . import br_report as rp
from . import br_run
from .config import REPO_ROOT, Credentials
from .data import MarketData

ET = "America/New_York"
OUT = REPO_ROOT / "reports" / "br_v1"
CACHE = REPO_ROOT / "cache" / "br_v1"


def sip_end() -> str:
    """The free plan serves consolidated data older than 15 minutes."""
    return (pd.Timestamp.now(tz=ET) - pd.Timedelta(minutes=20)).isoformat()


def load(cfg, days: int, refresh: bool = False, end: str | None = None) -> tuple[dict, dict]:
    """1-minute extended bars and daily bars for the universe. Cached."""
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"sip_{days}.pkl"
    if f.exists() and not refresh:
        data, daily = pickle.loads(f.read_bytes())
        newest = max(df.index[-1] for df in data.values() if len(df))
        if (pd.Timestamp.now(tz=ET) - newest).days < 2 or end:
            return data, daily
    md = MarketData(Credentials.from_env(), feed=cfg.backtest.feed)
    now = pd.Timestamp.now(tz=ET)
    start = (now - pd.Timedelta(days=int(days * 1.45) + 10)).date().isoformat()
    stop = end or sip_end()
    data = {}
    for s in cfg.universe.symbols:                 # one symbol per call keeps pages simple
        t0 = _time.time()
        data[s] = md.intraday_bars([s], 1, start=start, end=stop, extended=True).get(s, pd.DataFrame())
        print(f"{s}: {len(data[s])} bars ({_time.time() - t0:.0f}s)", flush=True)
    dstart = (now - pd.Timedelta(days=int(days * 1.45) + 120)).date().isoformat()
    raw = md.daily_bars(cfg.universe.symbols, start=dstart, end=stop)
    daily = {}
    for s, df in raw.items():
        df = df.copy()
        df.index = pd.Index([t.date() for t in df.index])
        daily[s] = df
    f.write_bytes(pickle.dumps((data, daily)))
    return data, daily


VARIANTS = {"combined (1m+3m+5m, live)": None, "1m only": [1], "3m only": [3], "5m only": [5]}


def label_split(dates: list, frac: float) -> dict:
    ds = sorted(dates)
    cut = int(len(ds) * frac)
    return {d: ("in-sample" if i < cut else "out-of-sample") for i, d in enumerate(ds)}


def market_day_type(sess: dict, d) -> str:
    """SPY's regular session up to 11:30: trend up / trend down / range.
    Known only at 11:30, so it describes the day; it is never a filter."""
    g = sess.get("SPY", {}).get(d)
    if g is None:
        return "n/a"
    m = g.index.hour * 60 + g.index.minute
    w = g[(m >= 570) & (m < 690)]
    if w.empty:
        return "n/a"
    move = (w.close.iloc[-1] - w.open.iloc[0]) / w.open.iloc[0] * 100
    span = (w.high.max() - w.low.min()) / w.open.iloc[0] * 100
    if abs(move) >= 0.4 and abs(move) >= 0.5 * span:
        return "trend up" if move > 0 else "trend down"
    return "range"


def build(cfg, data: dict, daily: dict, days: int, extras: bool = True):
    sess = br_run.sessions(data)
    all_dates = sorted({d for s in sess.values() for d in s})
    dates = [d for d in all_dates if sum(d in sess.get(s, {}) for s in cfg.universe.market_symbols) == 2]
    dates = dates[-days:]
    t0 = _time.time()
    ev, setups = br_run.run(sess, daily, dates, cfg, extras=extras)
    print(f"evaluated {len(ev)} candidates on {len(dates)} sessions in {_time.time() - t0:.0f}s", flush=True)
    split = label_split(dates, cfg.analysis.in_sample_fraction)
    dtype = {d: market_day_type(sess, d) for d in dates}
    if len(ev):
        ev["period"] = ev.date.map(split)
        ev["spy_day"] = ev.date.map(dtype)
        ev["tod"] = ev.minute.map(rp.tod_label)
    return sess, ev, setups, dates, split


def report(cfg, sess, ev, dates, split, bench_res, chart_files):
    risk = cfg.risk.risk_dollars
    tfs_all = list(cfg.timeframes.setup)
    variants = {k: (v or tfs_all) for k, v in VARIANTS.items()}
    dec = {k: br_run.decide(ev, v, cfg) for k, v in variants.items()}
    head = next(iter(variants))
    D = dec[head]
    T = D[D.taken]
    F = br_run.failures(ev, tfs_all, cfg)
    ins, oos = T[T.period == "in-sample"], T[T.period == "out-of-sample"]
    s_all, s_in, s_out = rp.stats(T, risk), rp.stats(ins, risk), rp.stats(oos, risk)
    is_dates = sorted(d for d in dates if split[d] == "in-sample")
    oos_dates = sorted(d for d in dates if split[d] == "out-of-sample")
    L = []
    w = L.append
    w("# Break & Retest V1 — baseline backtest\n")
    w(f"SIP 1-minute bars, {len(dates)} sessions ({dates[0]} to {dates[-1]}), "
      f"{len(cfg.universe.symbols)} symbols. In-sample {len(is_dates)} sessions ({is_dates[0]} to {is_dates[-1]}), "
      f"out-of-sample {len(oos_dates)} ({oos_dates[0]} to {oos_dates[-1]}). Rules exactly as in "
      f"`br_config.yaml` — **nothing tuned**. ${risk:,.0f} risk per trade, "
      f"{cfg.risk.slippage_pct}% slippage per side, stop {cfg.risk.stop_buffer_pct}% beyond the level, "
      f"target {cfg.risk.target_r}R, out at {cfg.session.time_exit} if neither. Headline = the "
      f"combined variant (every setup timeframe, first confirmation wins), which is what the live bot runs.\n")
    w("## Verdict\n")
    w(f"- All sessions: **{rp.verdict(s_all)}**")
    w(f"- In-sample: **{rp.verdict(s_in)}**")
    w(f"- Out-of-sample: **{rp.verdict(s_out)}**\n")
    w(rp.HEAD.format(k="period"))
    for name, s in (("all", s_all), ("in-sample", s_in), ("out-of-sample", s_out)):
        w(rp.row(name, s))
    if s_all.get("ci"):
        w(f"\nAverage R 95% bootstrap interval, all sessions: {s_all['ci'][0]:+.3f} to {s_all['ci'][1]:+.3f}. "
          f"Expectancy {rp._usd(s_all['exp_usd'])} per trade.\n")
    w("## Setup funnel (combined)\n")
    w(rp.funnel(ev, tfs_all, cfg))
    rej = D[~D.taken].reject_reason.value_counts()
    w("\n| complete setups not taken, by rule | count |\n|---|---|")
    for k, v in rej.items():
        w(f"| `{k}` | {v} |")
    w("\n## By setup timeframe\n")
    w("Each row is the same rules run on one bar size alone; the combined row is the headline.\n")
    w(rp.HEAD.format(k="variant / period"))
    for name in variants:
        t = dec[name][dec[name].taken]
        for per in ("in-sample", "out-of-sample"):
            w(rp.row(f"{name} · {per}", rp.stats(t[t.period == per], risk)))
    w("\nIn the combined run, which bar size found the trade first:\n")
    w(rp.table(T, "tf", "tf (min)", risk))
    w("\n## By ticker\n")
    w(rp.table(T, "symbol", "symbol", risk, order=list(cfg.universe.symbols)))
    w("\n## By setup (level broken)\n")
    w(rp.table(T, "level_kind", "level", risk,
               order=["pdh", "pdl", "pmh", "pml", "pdc", "swing_high", "swing_low"]))
    w("\n### By level and period\n")
    w(rp.table(T.assign(k=T.level_kind + " · " + T.period), "k", "level · period", risk))
    w("\n## By time of day (signal time)\n")
    w(rp.table(T, "tod", "window", risk, order=[x[2] for x in rp.TOD]))
    w("\n## By direction\n")
    w(rp.table(T, "direction", "side", risk))
    w("\n## By market condition\n")
    w("Market bias = SPY + QQQ context at the signal (known then). SPY day = how SPY's morning "
      "actually went by 11:30 (hindsight; describes the day, not usable as a filter).\n")
    w(rp.table(T, "market_bias", "market bias at signal", risk, order=["Bullish", "Neutral", "Bearish"]))
    w("")
    lean = np.where(T.market_bias == "Neutral", "market neutral",
                    np.where((T.market_bias == "Bullish") == (T.direction == "long"),
                             "with the market", "against the market"))
    w(rp.table(T.assign(al=lean), "al", "trade vs market bias", risk))
    w("")
    w(rp.table(T, "spy_day", "SPY morning (hindsight)", risk, order=["trend up", "trend down", "range"]))
    w("\n## By confidence and stock bias\n")
    w(rp.table(T, "confidence", "confidence", risk, order=["HIGH", "MEDIUM", "LOW"]))
    w("")
    w(rp.table(T, "stock_bias", "stock bias at signal", risk, order=["Bullish", "Neutral", "Bearish"]))
    w("")
    w(rp.table(T.assign(v=T.vwap_supports.map({True: "VWAP supports", False: "VWAP against"}).fillna("n/a")),
               "v", "VWAP", risk))
    w("")
    w(rp.table(T, "open_state", "open vs previous day", risk))
    w("\n## Stops: correct, or too tight?\n")
    w(rp.stop_section(T, cfg))
    w("\n### The same entries with other stops (each with its own 2R target)\n")
    n_alt = len([c for c in T.columns if c.startswith("alt_")])
    w(f"Exploratory. {n_alt} alternative exits are listed across this and the next table; with that "
      f"many looks, a difference smaller than about {rp.noise_floor(n_alt):.1f} standard errors is "
      f"noise. Judge on out-of-sample, and expect the best in-sample row to shrink.\n")
    w(rp.alt_section(T, "alt_stop_", "stop", "period", risk))
    w("\n## Targets: is 2R too conservative?\n")
    w(rp.tp_section(T, cfg))
    if len(T):
        w(f"\nTrades that reached 2R at any point before the bell: {rp.pct(T.reached_2r_eod)}; "
          f"average best R before the bell (MFE): {T.mfe_r_eod.mean():+.2f}; "
          f"average worst R while open (MAE): {T.mae_r.mean():+.2f}.\n")
    w("### The same entries and stop with other exits\n")
    w(rp.alt_section(T, "alt_target_", "target", "period", risk))
    w(rp.alt_section(T, "alt_trail_", "exit", "period", risk).split("\n", 2)[-1])
    w("\n## Missed and rejected setups\n")
    w(rp.missed_section(D, F, T, risk))
    w("\n## SNDK — benchmark ticker\n")
    sn = T[T.symbol == cfg.universe.benchmark_symbol]
    w(rp.HEAD.format(k="SNDK"))
    w(rp.row("all", rp.stats(sn, risk)))
    snd = ev[(ev.symbol == cfg.universe.benchmark_symbol)]
    if len(snd):
        w(f"\nSNDK candidates: {len(snd.drop_duplicates(['date', 'level_name', 'direction', 'attempt']))} "
          f"breakouts, {int((D.symbol == cfg.universe.benchmark_symbol).sum())} complete setups, {len(sn)} taken. "
          f"Premarket-level setups (PMH/PML) on SNDK: "
          f"{int(snd.level_kind.isin(['pmh', 'pml']).sum())} candidates, "
          f"{int(sn.level_kind.isin(['pmh', 'pml']).sum())} taken.\n")
        w("| date | time | side | level | tf | outcome | R |\n|---|---|---|---|---|---|---|")
        for _, r in sn.sort_values("signal_ts").tail(25).iterrows():
            w(f"| {r.date} | {pd.Timestamp(r.signal_ts):%H:%M} | {r.direction} | {r.level_name} {r.level:.2f} | "
              f"{r.tf}m | {r.outcome} | {r.r:+.2f} |")
    w("\n## Benchmark trades\n")
    w(br_bench.markdown(bench_res))
    w("\n## Data notes\n")
    pm = ev.drop_duplicates(["symbol", "date"]).pm_bars if len(ev) else pd.Series(dtype=float)
    w(f"- Premarket bars per symbol-session (SIP): median {pm.median():.0f}, "
      f"{100 * (pm < 30).mean():.0f}% of sessions under 30 bars (thin premarket = PMH/PML less meaningful).")
    w("- Context votes use only bars closed before the signal; daily vote and ATR use yesterday's row.")
    w("- Live trades will use IEX real-time bars and SIP data delayed 15 minutes for premarket levels, "
      "so PMH/PML live may miss 09:15-09:29 prints. See `src/br_live.py`.")
    if chart_files:
        w(f"\n## Charts\n\n{len(chart_files)} chart(s): the best and worst trades and the latest SNDK "
          f"trades, at the signal and at the exit. They are in the workflow run's `br-v1-charts` artifact "
          f"(not committed, to keep the repo small).")
    return "\n".join(L), dec, T, F


def charts(cfg, sess, setups, T: pd.DataFrame, mode: str, sample: int, bench_res) -> list:
    if mode == "none" or T.empty:
        return []
    if mode == "all":
        pick = T
    else:
        srt = T.sort_values("r")
        pick = pd.concat([srt.head(sample), srt.tail(sample), T[T.symbol == cfg.universe.benchmark_symbol].tail(10)])
        pick = pick[~pick.index.duplicated()]
    files = []
    for _, r in pick.iterrows():
        st = setups[(r.symbol, r.date)]
        tr = {"level": r.level, "level_name": r.level_name, "entry": r.plan_entry, "stop": r.plan_stop,
              "target": r.plan_target, "signal_ts": r.signal_ts, "exit_ts": r.exit_ts,
              "outcome": r.outcome, "exit_px": r.exit_px}
        lv = {k: st["lv"].get(k) for k in ("pdh", "pdl", "pdc", "pmh", "pml")}
        note = f"{r.level_name} {r.tf}m · {r.confidence} · R {r.r:+.2f}"
        for name, as_of in br_chart.snapshots(tr, cfg).items():
            if mode != "all" and name not in ("signal", "stop", "target"):
                continue
            p = OUT / "charts" / f"{r.date}_{r.symbol}_{r.direction}_{pd.Timestamp(r.signal_ts):%H%M}_{name}.png"
            files.append(br_chart.render(p, r.symbol, r.direction, st["day"], as_of, lv, tr, note))
    return files


# Pre-registered before the run (8 Oct 2026), from two of this week's SNDK
# losses: a "break" that closed $2 above the level and was "retested" the next
# minute, and a trade held 4h40m after being +1.76R. Nothing is adopted from
# this table without passing in BOTH halves.
ENTRY_VARIANTS = {
    "break closes >= 0.10% beyond": {"breakout": {"min_close_beyond_pct": 0.10}},
    "break closes >= 0.20% beyond": {"breakout": {"min_close_beyond_pct": 0.20}},
    "moves >= 0.20% away before retest": {"retest": {"min_displacement_pct": 0.20}},
    "moves >= 0.40% away before retest": {"retest": {"min_displacement_pct": 0.40}},
    "0.10% close + 0.20% move away": {"breakout": {"min_close_beyond_pct": 0.10},
                                      "retest": {"min_displacement_pct": 0.20}},
}
TIME_LABEL = {"always": "exit at {n}m close", "if_profit": "exit at {n}m close if in profit",
              "be_if_profit": "stop to breakeven at {n}m if in profit"}


def _per(t: pd.DataFrame, col: str = "r") -> dict:
    out = {}
    for per in ("in-sample", "out-of-sample"):
        r = t.loc[t.period == per, col].dropna().astype(float)
        out[per] = (len(r), r.mean() if len(r) else float("nan"),
                    r.std(ddof=1) / np.sqrt(len(r)) if len(r) > 1 else float("nan"),
                    100 * (r > 0).mean() if len(r) else float("nan"), r.sum())
    return out


def _verdict(b: dict, v: dict, tstats: list) -> str:
    better = all(v[p][1] > b[p][1] for p in b)
    positive = all(v[p][1] > 0 for p in b)
    if not better:
        return "rejected (not better in both halves)"
    if not positive:
        return "better in both halves, still losing" + ("" if max(tstats) >= rp.noise_floor(14) else " - within noise")
    return "CANDIDATE: better and positive in both halves" + ("" if min(tstats) >= rp.noise_floor(14) else " - but within noise")


def variants(cfg, data, daily, days, base_taken: pd.DataFrame) -> str:
    """Pre-registered variants vs the baseline, by half. Exit variants are
    the same trades (paired); entry variants are different trades (unpaired)."""
    nvar = len(ENTRY_VARIANTS) + 3 * len(cfg.analysis.alt_time_minutes)
    floor = rp.noise_floor(nvar)
    b = _per(base_taken)
    L = ["# Break & Retest V1 — variant test\n",
         f"{nvar} variants fixed before the run. A change has to beat the baseline in BOTH halves; "
         f"with {nvar} looks, anything under about {floor:.1f} standard errors is noise. Account % "
         "assumes 1% risked per trade (simple sum). Nothing here changes the live settings.\n",
         "| variant | half | trades | win % | account % | avg account % per trade | t vs baseline | verdict |",
         "|---|---|---|---|---|---|---|---|"]

    def rows(name, v, ts, verdict):
        for k, per in enumerate(("in-sample", "out-of-sample")):
            n, m, se, w, tot = v[per]
            L.append(f"| {name if k == 0 else ''} | {per} | {n} | {w:.1f}% | {tot:+.1f}% | {m:+.3f}% | "
                     f"{'' if ts is None else f'{ts[k]:+.1f}'} | {verdict if k == 0 else ''} |")

    rows("**baseline (V1)**", b, None, "")
    L.append("| **exits** (same trades) | | | | | | | |")
    for n in cfg.analysis.alt_time_minutes:
        for key, lab in TIME_LABEL.items():
            col = f"alt_time_{n}m" if key == "always" else f"alt_time_{n}m_{key}"
            if col not in base_taken:
                continue
            v = _per(base_taken, col)
            ts = []
            for per in ("in-sample", "out-of-sample"):
                d = (base_taken.loc[base_taken.period == per, col] - base_taken.loc[base_taken.period == per, "r"]).dropna()
                ts.append(d.mean() / (d.std(ddof=1) / np.sqrt(len(d))) if len(d) > 1 and d.std() > 0 else 0.0)
            rows(lab.format(n=n), v, ts, _verdict(b, v, ts))
    L.append("| **entries** (different trades) | | | | | | | |")
    for name, ov in ENTRY_VARIANTS.items():
        vc = bcfg.load(**ov)
        _, ev, _, _, _ = build(vc, data, daily, days, extras=False)
        T = br_run.decide(ev, list(vc.timeframes.setup), vc)
        T = T[T.taken]
        v = _per(T)
        ts = [(v[p][1] - b[p][1]) / np.sqrt(v[p][2] ** 2 + b[p][2] ** 2) for p in ("in-sample", "out-of-sample")]
        rows(name, v, ts, _verdict(b, v, ts))
        print(f"variant done: {name}", flush=True)
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=None)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--charts", default=None, choices=["none", "sample", "all"])
    ap.add_argument("--variants", action="store_true", help="also run the pre-registered variant test")
    a = ap.parse_args(argv)
    cfg = bcfg.load()
    days = a.days or cfg.backtest.days
    data, daily = load(cfg, days, a.refresh)
    sess, ev, setups, dates, split = build(cfg, data, daily, days)
    OUT.mkdir(parents=True, exist_ok=True)
    tfs = list(cfg.timeframes.setup)
    D = br_run.decide(ev, tfs, cfg)
    bench_res = br_bench.evaluate(br_bench.load(), D, ev, set(dates))
    files = charts(cfg, sess, setups, D[D.taken], a.charts or cfg.backtest.charts,
                   cfg.backtest.chart_sample, bench_res)
    md, dec, T, F = report(cfg, sess, ev, dates, split, bench_res, files)
    (OUT / "baseline.md").write_text(md)
    keep = [c for c in T.columns if not c.startswith("_")]
    T[keep].to_csv(OUT / "trades.csv", index=False)
    ev.to_csv(OUT / "candidates.csv.gz", index=False, compression="gzip")
    summary = {"sessions": len(dates), "first": str(dates[0]), "last": str(dates[-1]),
               "variants": {k: rp.stats(v[v.taken], cfg.risk.risk_dollars) for k, v in dec.items()},
               "by_period": {p: rp.stats(T[T.period == p], cfg.risk.risk_dollars)
                             for p in ("in-sample", "out-of-sample")},
               "benchmarks": bench_res, "charts": [str(f.relative_to(REPO_ROOT)) for f in files]}
    (OUT / "baseline.json").write_text(json.dumps(summary, indent=1, default=str))
    if a.variants:
        vmd = variants(cfg, data, daily, days, T)
        (OUT / "variants.md").write_text(vmd)
        print(vmd)
    print(md[:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
