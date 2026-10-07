"""Break & Retest V1: the end-of-day replay and daily report.

After the close, today is re-run through exactly the backtest code on SIP
bars (the whole tape, now complete). That replay is the record of the day:
it finishes trades the live job stopped watching, runs the post-stop and
post-target analysis, draws every screenshot, and compares itself with what
the live job actually sent.

Writes reports/br_v1/daily/<date>.md (+ charts in reports/br_v1/daily/<date>/),
appends the day's trades to reports/br_v1/forward.csv, and posts a short
summary to the BR Discord channel.

Usage: python -m src.br_daily [--date YYYY-MM-DD] [--no-post]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import pandas as pd

from . import br_chart, br_discord
from . import br_config as bcfg
from . import br_report as rp
from . import br_run
from .br_backtest import market_day_type, sip_end
from .config import REPO_ROOT, Credentials
from .data import MarketData

ET = "America/New_York"
OUT = REPO_ROOT / "reports" / "br_v1"


def load_day(cfg, day) -> tuple[dict, dict]:
    md = MarketData(Credentials.from_env(), feed="sip")
    start = (pd.Timestamp(day) - pd.Timedelta(days=30)).date().isoformat()
    end = min(pd.Timestamp(f"{day} 16:00", tz=ET), pd.Timestamp(sip_end())).isoformat()
    data = md.intraday_bars(cfg.universe.symbols, 1, start=start, end=end, extended=True)
    dstart = (pd.Timestamp(day) - pd.Timedelta(days=90)).date().isoformat()
    daily = {}
    for s, df in md.daily_bars(cfg.universe.symbols, start=dstart, end=end).items():
        df = df.copy()
        df.index = pd.Index([t.date() for t in df.index])
        daily[s] = df
    return data, daily


def live_records(day) -> dict:
    base = REPO_ROOT / "state" / "br_v1" / str(day)
    out = {}
    for name in ("signals", "latency", "rejected", "exits"):
        f = base / f"{name}.jsonl"
        out[name] = [json.loads(x) for x in f.read_text().splitlines() if x.strip()] if f.exists() else []
    return out


def index_summary(sess, sym: str, day) -> str:
    g = sess.get(sym, {}).get(day)
    if g is None:
        return f"{sym}: no data"
    m = g.index.hour * 60 + g.index.minute
    rth = g[(m >= 570) & (m < 960)]
    w = rth[rth.index.hour * 60 + rth.index.minute < 690]
    o, c11, c = rth.open.iloc[0], w.close.iloc[-1], rth.close.iloc[-1]
    return (f"{sym}: open {o:.2f}, 11:30 {c11:.2f} ({(c11 / o - 1) * 100:+.2f}%), close {c:.2f} "
            f"({(c / o - 1) * 100:+.2f}% from the open)")


def build(cfg, day) -> tuple[str, dict]:
    data, daily = load_day(cfg, day)
    sess = br_run.sessions(data)
    if day not in sess.get("SPY", {}):
        return f"# Break & Retest V1 — {day}\n\nNo complete SPY session for {day}; nothing to report.", {}
    ev, setups = br_run.run(sess, daily, [day], cfg)
    risk = cfg.risk.risk_dollars
    tfs = list(cfg.timeframes.setup)
    if ev.empty:
        D = T = F = pd.DataFrame()
    else:
        ev["period"] = "live"
        ev["tod"] = ev.minute.map(rp.tod_label)
        D = br_run.decide(ev, tfs, cfg)
        T = D[D.taken]
        F = br_run.failures(ev, tfs, cfg)
    live = live_records(day)
    L = []
    w = L.append
    w(f"# Break & Retest V1 — daily report, {day}\n")
    w("Replayed after the close on SIP (consolidated) 1-minute bars with the backtest code. "
      "This replay is the record; the live section below shows what was actually sent.\n")
    w("## Market\n")
    w(f"- {index_summary(sess, 'SPY', day)}")
    w(f"- {index_summary(sess, 'QQQ', day)}")
    w(f"- SPY morning: **{market_day_type(sess, day)}**")
    if len(T):
        w(f"- Market bias at the signals: {', '.join(f'{k} {v}' for k, v in T.market_bias.value_counts().items())}")
    w("\n## Setups\n")
    w(rp.funnel(ev, tfs, cfg) if len(ev) else "No breakouts.")
    if len(D):
        rej = D[~D.taken].reject_reason.value_counts()
        if len(rej):
            w("\n| complete setups not taken | count |\n|---|---|")
            for k, v in rej.items():
                w(f"| `{k}` | {v} |")
    w("\n## Performance\n")
    s = rp.stats(T, risk)
    w(rp.HEAD.format(k="today"))
    w(rp.row("all", s))
    if len(T):
        w("\n| time | symbol | side | level | tf | conf | entry | stop | target | outcome | R | MFE R | after |")
        w("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for _, r in T.sort_values("signal_ts").iterrows():
            after = r.get("sl_class") if r.outcome == "stop" else (
                f"+{r.get('tp_extra_r_30', 0):.1f}R more in 30m" if r.outcome == "target" else "")
            w(f"| {pd.Timestamp(r.signal_ts):%H:%M} | {r.symbol} | {r.direction} | {r.level_name} {r.level:.2f} | "
              f"{r.tf}m | {r.confidence} | {r.plan_entry:.2f} | {r.plan_stop:.2f} | {r.plan_target:.2f} | "
              f"{r.outcome} | {r.r:+.2f} | {r.mfe_r_eod:+.2f} | {after or ''} |")
        w("\n### By ticker\n")
        w(rp.table(T, "symbol", "symbol", risk))
        w("\n### By setup\n")
        w(rp.table(T, "level_kind", "level", risk))
        w("\n## Stops\n")
        w(rp.stop_section(T, cfg))
        w("\n## Targets\n")
        w(rp.tp_section(T, cfg))
    if len(D):
        w("\n## Missed and rejected\n")
        w(rp.missed_section(D, F, T, risk, top=8))
    w("\n## Live vs replay\n")
    sent = live["signals"]
    if not sent and not len(T):
        w("No signals live or in the replay.")
    else:
        lk = {(x["symbol"], x["level_name"], x["direction"]) for x in sent}
        rk = {(r.symbol, r.level_name, r.direction) for _, r in T.iterrows()} if len(T) else set()
        w(f"Sent live: {len(sent)}. In the replay: {len(rk)}. Both: {len(lk & rk)}.")
        for k in sorted(lk - rk):
            w(f"- live only: {' '.join(k)} (IEX bars broke/confirmed where the full tape did not)")
        for k in sorted(rk - lk):
            w(f"- replay only: {' '.join(k)} (not sent live: IEX bars differed, or the live job was not running)")
    lat = pd.DataFrame(live["latency"])
    if len(lat):
        w("\n| latency (s) | median | max |\n|---|---|---|")
        for c, lab in (("detect_s", "candle close -> detected"), ("analyse_s", "detected -> analysed"),
                       ("send_s", "analysed -> Discord sent"), ("total_s", "total")):
            w(f"| {lab} | {lat[c].median():.1f} | {lat[c].max():.1f} |")
    charts = []
    for _, r in (T.iterrows() if len(T) else []):
        st = setups[(r.symbol, r.date)]
        tr = {"level": r.level, "level_name": r.level_name, "entry": r.plan_entry, "stop": r.plan_stop,
              "target": r.plan_target, "signal_ts": r.signal_ts, "exit_ts": r.exit_ts,
              "outcome": r.outcome, "exit_px": r.exit_px}
        lv = {k: st["lv"].get(k) for k in ("pdh", "pdl", "pdc", "pmh", "pml")}
        for name, as_of in br_chart.snapshots(tr, cfg).items():
            p = OUT / "daily" / str(day) / f"{r.symbol}_{r.direction}_{pd.Timestamp(r.signal_ts):%H%M}_{name}.png"
            charts.append(br_chart.render(p, r.symbol, r.direction, st["day"], as_of, lv, tr,
                                          f"{r.level_name} {r.tf}m · {r.confidence} · R {r.r:+.2f}"))
    if charts:
        w("\n## Charts\n")
        for p in charts:
            w(f"- [{p.name}]({p.relative_to(OUT / 'daily')})")
    if len(T):
        f = OUT / "forward.csv"
        keep = ["date", "symbol", "direction", "tf", "level_kind", "level_name", "level", "signal_ts",
                "plan_entry", "plan_stop", "plan_target", "outcome", "exit_ts", "r", "pnl", "mfe_r_eod",
                "mae_r", "confidence", "market_bias", "stock_bias", "sl_class"]
        rows = T[[c for c in keep if c in T]]
        old = pd.read_csv(f) if f.exists() else pd.DataFrame()
        if len(old):
            old = old[old.date.astype(str) != str(day)]
        pd.concat([old, rows]).to_csv(f, index=False)
    summary = {"date": str(day), "stats": s, "sent_live": len(sent), "charts": len(charts)}
    return "\n".join(L), summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    ap.add_argument("--no-post", action="store_true")
    a = ap.parse_args(argv)
    cfg = bcfg.load()
    now = pd.Timestamp.now(tz=ET)
    day = pd.Timestamp(a.date).date() if a.date else now.date()
    if not a.date and (now.weekday() >= 5 or now.hour * 60 + now.minute < 16 * 60 + 20):
        print("Not after today's close yet (SIP needs ~15 minutes) - nothing to do")
        return 0
    md, summary = build(cfg, day)
    (OUT / "daily").mkdir(parents=True, exist_ok=True)
    (OUT / "daily" / f"{day}.md").write_text(md)
    print(md)
    s = summary.get("stats", {})
    if not a.no_post and cfg.live.post_daily_summary and summary:
        text = (f"📊 Break & Retest V1 — {day}\nSignals: {s.get('n', 0)} · won {s.get('wins', 0)} · "
                f"lost {s.get('losses', 0)}" + (f" · win {s['win']:.0f}% · {rp._usd(s['profit'])}" if s.get("n") else "")
                + f"\nReport: reports/br_v1/daily/{day}.md")
        br_discord.post(os.environ.get(cfg.live.discord_secret), text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
