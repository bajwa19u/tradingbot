"""Break & Retest V1: the real-time monitor.

Not "scan everything, then send". The work is front-loaded so that each
closing candle costs one small request and a few engine steps:

  before 09:30   load yesterday's regular session (PDH/PDL/PDC), 15+ days of
                 history for context, and today's premarket (PMH/PML)
  each minute    fetch only the bar(s) that just closed, a couple of seconds
                 after the minute ends; feed them to one Engine per symbol per
                 setup timeframe (3- and 5-minute bars are built from the
                 1-minute ones as each bucket completes)
  on a confirmation  context, sizing, chart, Discord - immediately
  after 11:30    no new signals; open trades are followed to their stop,
                 target or the job's end; the end-of-day replay finishes the rest

Why polling and not the websocket: the free plan allows ONE stream connection
and the deployed live bot holds it. A REST poll two seconds after the minute
is within a few seconds of the stream, and cannot knock the other bot off.

Data caveats, also written into every daily report:
  * real-time bars are IEX (a slice of the tape); the backtest and the
    end-of-day replay use SIP (the whole tape), so a level can break on one and
    not the other
  * SIP is delayed 15 minutes on the free plan, so PMH/PML at the bell are
    built from SIP up to ~09:15 plus IEX for the last quarter hour

Latency is measured per signal: candle close -> detected -> analysed -> sent.

Usage: python -m src.br_live [--dry-run] [--force] [--until 14:50]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time as _time

import pandas as pd

from . import br_chart, br_discord
from . import br_config as bcfg
from . import br_context as bc
from .br_engine import Engine
from .br_run import level_key
from .br_levels import build_levels, hhmm, premarket_levels, prior_day_levels, split_day
from .br_trade import plan
from .config import REPO_ROOT, Credentials
from .data import MarketData

ET = "America/New_York"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
log = logging.getLogger("br_live")


def now_et() -> pd.Timestamp:
    return pd.Timestamp.now(tz=ET)


def at(day, hm: str) -> pd.Timestamp:
    return pd.Timestamp(f"{day} {hm}", tz=ET)


class Session:
    """Everything live for one trading day."""

    def __init__(self, cfg, dry_run: bool = False, md_iex=None, md_sip=None, webhook=None, today=None):
        self.cfg, self.dry = cfg, dry_run
        self.today = today or now_et().date()
        self.syms = list(cfg.universe.symbols)
        self.md_iex, self.md_sip = md_iex, md_sip
        self.webhook = None if dry_run else webhook
        self.dir_state = REPO_ROOT / "state" / "br_v1" / str(self.today)
        self.dir_charts = REPO_ROOT / "reports" / "br_v1" / "live" / str(self.today)
        self.bars: dict[str, pd.DataFrame] = {}       # today's extended 1-minute bars
        self.history: dict[str, pd.DataFrame] = {}    # previous sessions, regular hours
        self.daily: dict[str, pd.DataFrame] = {}
        self.levels: dict[str, dict] = {}
        self.engines: dict[str, list[Engine]] = {}
        self.fed: dict[str, pd.Timestamp] = {}
        self.seen_keys: set = set()
        self.count: dict[str, int] = {}
        self.open: dict[str, dict] = {}               # symbol -> live trade
        self.closed_window = False
        self.open_done: list[dict] = []               # closed trades still owed +5/+10 charts

    # ------------------------------------------------------------ preparation
    def prepare(self) -> None:
        """Previous-day levels and context history. Run any time before the bell."""
        start = (pd.Timestamp(self.today) - pd.Timedelta(days=30)).date().isoformat()
        end = at(self.today, "00:00").isoformat()
        hist = self.md_sip.intraday_bars(self.syms, 1, start=start, end=end, extended=True)
        for s, df in hist.items():
            self.history[s] = df
        dstart = (pd.Timestamp(self.today) - pd.Timedelta(days=90)).date().isoformat()
        for s, df in self.md_sip.daily_bars(self.syms, start=dstart, end=end).items():
            df = df.copy()
            df.index = pd.Index([t.date() for t in df.index])
            self.daily[s] = df[df.index < self.today]
        for s in self.syms:
            h = self.history.get(s, pd.DataFrame())
            if h.empty:
                log.warning("%s: no history - it will not be traded today", s)
                continue
            last_day = max(h.index.date)
            _, prior_rth = split_day(h[h.index.date == last_day])
            self.levels[s] = {"pd": prior_day_levels(prior_rth)}
        log.info("Prepared previous-day levels for %d symbols", len(self.levels))

    def premarket(self) -> None:
        """Today's 04:00-now: SIP where it exists (15-minute delay), IEX after."""
        t0 = at(self.today, self.cfg.session.premarket_start)
        sip_end = min(now_et() - pd.Timedelta(minutes=16), at(self.today, "09:30"))
        merged = {}
        if sip_end > t0:
            merged = self.md_sip.intraday_bars(self.syms, 1, start=t0.isoformat(), end=sip_end.isoformat(),
                                               extended=True)
        iex = self.md_iex.intraday_bars(self.syms, 1, start=t0.isoformat(), extended=True)
        for s in self.syms:
            a, b = merged.get(s, pd.DataFrame()), iex.get(s, pd.DataFrame())
            if len(a) and len(b):
                b = b[b.index > a.index[-1]]
            df = pd.concat([x for x in (a, b) if len(x)]) if (len(a) or len(b)) else pd.DataFrame(
                columns=["open", "high", "low", "close", "volume"])
            self.bars[s] = df[~df.index.duplicated(keep="first")].sort_index()

    def _start_engines(self, s: str) -> None:
        """At the first regular-session bar: the open decides which levels are active."""
        df = self.bars[s]
        pre, rth = split_day(df, self.cfg.session.premarket_start, self.cfg.session.open)
        pdl = self.levels.get(s, {}).get("pd")
        if rth.empty or not pdl:
            return
        pm = premarket_levels(pre)
        levels, state = build_levels(pdl, pm, float(rth.open.iloc[0]), self.cfg)
        self.levels[s].update(pm=pm, state=state, lv={**pdl, **pm}, pm_bars=len(pre))
        prev = float(pre.close.iloc[-1]) if len(pre) else pdl["pdc"]
        self.engines[s] = [Engine(s, tf, self.today, levels, self.cfg, prev) for tf in self.cfg.timeframes.setup]
        log.info("%s opened %s (%s); levels: %s", s, f"{rth.open.iloc[0]:.2f}", state,
                 ", ".join(f"{lv.label}{'' if lv.active else '(inactive)'} {lv.price:.2f}" for lv in levels))

    # ------------------------------------------------------------ each minute
    def poll(self, since: pd.Timestamp) -> dict[str, pd.DataFrame]:
        got = self.md_iex.intraday_bars(self.syms, 1, start=since.isoformat(), extended=True)
        for s, df in got.items():
            if df.empty:
                continue
            old = self.bars.get(s)
            new = df if old is None or old.empty else pd.concat([old[~old.index.isin(df.index)], df])
            self.bars[s] = new.sort_index()
        return got

    def on_minute(self, minute: pd.Timestamp, detected_at: pd.Timestamp) -> list[dict]:
        """Every 1-minute bar up to and including `minute` (bar start) is in."""
        until = hhmm(self.cfg.session.signals_until)
        out = []
        for s in self.syms:
            df = self.bars.get(s)
            if df is None or df.empty:
                continue
            if s not in self.engines:
                self._start_engines(s)
                if s not in self.engines:
                    continue
            m = df.index.hour * 60 + df.index.minute
            rth = df[(m >= 570) & (df.index <= minute)]
            # Walk the CLOCK, not the bars: IEX skips minutes with no trades,
            # and a 5-minute bucket must still close when its last minute is empty.
            last = self.fed.get(s, at(self.today, self.cfg.session.open) - pd.Timedelta(minutes=1))
            clock = last + pd.Timedelta(minutes=1)
            while clock <= minute:
                self.fed[s] = clock
                if clock in rth.index:
                    self._track(s, clock, rth.loc[clock])
                close_min = clock.hour * 60 + clock.minute + 1
                for eng in self.engines[s]:
                    tf = eng.tf
                    if (close_min - 570) % tf or close_min > until:
                        continue                                  # bucket not complete, or window over
                    b = rth[(rth.index > clock - pd.Timedelta(minutes=tf)) & (rth.index <= clock)]
                    if b.empty:
                        continue
                    start = clock - pd.Timedelta(minutes=tf - 1)
                    for c in eng.on_bar(start, b.open.iloc[0], b.high.max(), b.low.min(),
                                        b.close.iloc[-1], b.volume.sum()):
                        out.append(self._finished(c, detected_at))
                clock += pd.Timedelta(minutes=1)
        if not self.closed_window and minute.hour * 60 + minute.minute + 1 >= until:
            self.closed_window = True
            for engs in self.engines.values():
                for eng in engs:
                    for c in eng.close_session():
                        out.append(self._finished(c, detected_at))
            log.info("Signal window closed at %s", self.cfg.session.signals_until)
        self._snapshots(minute)
        return [o for o in out if o]

    # ------------------------------------------------------------ signals
    def _context(self, s: str, direction: str, t: pd.Timestamp) -> dict:
        def book(sym):
            h = self.history.get(sym, pd.DataFrame())
            parts = [split_day(g)[1] for _, g in h.groupby(h.index.date)] if len(h) else []
            today = self.bars.get(sym, pd.DataFrame())
            if len(today):
                parts.append(split_day(today)[1])
            rth = pd.concat([p for p in parts if len(p)]) if parts else pd.DataFrame(
                columns=["open", "high", "low", "close", "volume"])
            return bc.Book(rth, self.daily.get(sym, pd.DataFrame(columns=["open", "high", "low", "close"])),
                           self.cfg).at(t)
        return bc.describe(s, direction, book(s), book("SPY"), book("QQQ"))

    def _finished(self, c, detected_at: pd.Timestamp) -> dict | None:
        rec = {"kind": "candidate", **{k: (str(v) if isinstance(v, pd.Timestamp) else v)
                                       for k, v in c.to_dict().items()}}
        self._write("candidates.jsonl", rec)
        if c.status != "confirmed":
            return None
        key = level_key(c.symbol, c.date, c.direction, c.level_kind, c.level, self.cfg.levels.merge_within_pct)
        reasons = list(c.blockers)
        if key in self.seen_keys:
            return None                                           # another timeframe got there first
        self.seen_keys.add(key)
        ctx = self._context(c.symbol, c.direction, pd.Timestamp(c.signal_ts))
        if self.cfg.context.block_counter_bias and ctx["counter_bias"]:
            reasons.append("counter_bias")
        if c.symbol in self.open:
            reasons.append("position_open")
        if self.count.get(c.symbol, 0) >= self.cfg.risk.max_signals_per_symbol_per_day:
            reasons.append("max_signals_per_day")
        p = plan(c.direction, c.entry, c.level, c.touch_extreme, self.cfg)
        if not p:
            reasons.append("no_risk")
        analysed = now_et()
        sig = {"symbol": c.symbol, "direction": c.direction, "tf": c.tf, "level": c.level,
               "level_kind": c.level_kind, "level_name": c.level_name, "signal_ts": pd.Timestamp(c.signal_ts),
               "confirm_ts": str(c.confirm_ts), "break_ts": str(c.break_ts), "touch_ts": str(c.touch_ts),
               "risk_dollars": self.cfg.risk.risk_dollars, **{k: v for k, v in p.items()}, **ctx,
               "taken": not reasons, "reject_reason": reasons[0] if reasons else ""}
        if reasons:
            self._write("rejected.jsonl", _jsonable(sig))
            log.info("Setup %s %s %s rejected: %s", c.symbol, c.direction, c.level_name, reasons[0])
            return None
        if sig["confidence"] == "LOW":
            sig["notes"] = [f"bias {sig['stock_bias']}, market {sig['market_bias']}"]
        self.count[c.symbol] = self.count.get(c.symbol, 0) + 1
        self.open[c.symbol] = {**sig, "snaps": set()}
        png = self._chart(c.symbol, sig, as_of=sig["signal_ts"], name="signal")
        sent_id = br_discord.post(self.webhook, br_discord.card(sig), png)
        sent = now_et()
        lat = {"kind": "latency", "symbol": c.symbol, "candle_close": str(sig["signal_ts"]),
               "detected": str(detected_at), "analysed": str(analysed), "sent": str(sent),
               "detect_s": (detected_at - sig["signal_ts"]).total_seconds(),
               "analyse_s": (analysed - detected_at).total_seconds(),
               "send_s": (sent - analysed).total_seconds(),
               "total_s": (sent - sig["signal_ts"]).total_seconds(), "discord_id": sent_id}
        self._write("latency.jsonl", lat)
        self._write("signals.jsonl", _jsonable({**sig, "latency_s": lat["total_s"], "discord_id": sent_id}))
        log.info("SIGNAL %s %s at %.2f (stop %.2f, target %.2f) - %.1fs after the candle closed",
                 c.symbol, c.direction, sig["entry"], sig["stop"], sig["target"], lat["total_s"])
        return sig

    # ------------------------------------------------------------ trades
    def _track(self, s: str, ts: pd.Timestamp, r) -> None:
        tr = self.open.get(s)
        if tr is None or ts < tr["signal_ts"]:
            return
        side = 1 if tr["direction"] == "long" else -1
        hit_stop = r.low <= tr["stop"] if side > 0 else r.high >= tr["stop"]
        hit_tgt = r.high >= tr["target"] if side > 0 else r.low <= tr["target"]
        if not (hit_stop or hit_tgt):
            return
        why = "stop" if hit_stop else "target"
        px = tr["stop"] if hit_stop else tr["target"]
        rr = side * (px - tr["entry"]) / tr["risk_per_share"]
        tr.update(outcome=why, exit_ts=ts, exit_px=px, r=rr)
        self._chart(s, tr, as_of=ts + pd.Timedelta(minutes=1), name=why)
        br_discord.post(self.webhook, br_discord.result_line(tr, why, rr))
        self._write("exits.jsonl", _jsonable({k: v for k, v in tr.items() if k != "snaps"}))
        log.info("EXIT %s %s: %s %+.2fR", s, tr["direction"], why, rr)
        self.open.pop(s)
        self.open_done.append(tr)

    def _snapshots(self, minute: pd.Timestamp) -> None:
        now_bar_end = minute + pd.Timedelta(minutes=1)
        for tr in list(self.open.values()) + self.open_done:
            for name, mins in (("plus5", 5), ("plus10", 10)):
                due = tr["signal_ts"] + pd.Timedelta(minutes=mins)
                if name not in tr.setdefault("snaps", set()) and now_bar_end >= due:
                    tr["snaps"].add(name)
                    self._chart(tr["symbol"], tr, as_of=due, name=name)

    # ------------------------------------------------------------ output
    def _chart(self, s: str, tr: dict, as_of, name: str):
        try:
            lv = self.levels.get(s, {}).get("lv", {})
            p = self.dir_charts / f"{s}_{tr['direction']}_{tr['signal_ts']:%H%M}_{name}.png"
            return br_chart.render(p, s, tr["direction"], self.bars[s], as_of,
                                   {k: lv.get(k) for k in ("pdh", "pdl", "pdc", "pmh", "pml")},
                                   {"level": tr["level"], "level_name": tr["level_name"], "entry": tr["entry"],
                                    "stop": tr["stop"], "target": tr["target"], "signal_ts": tr["signal_ts"],
                                    "exit_ts": tr.get("exit_ts"), "outcome": tr.get("outcome"),
                                    "exit_px": tr.get("exit_px")},
                                   f"{tr['level_name']} {tr['tf']}m · {tr.get('confidence', '')}")
        except Exception as exc:                                   # noqa: BLE001
            log.error("chart failed for %s: %s", s, exc)
            return None

    def _write(self, name: str, rec: dict) -> None:
        self.dir_state.mkdir(parents=True, exist_ok=True)
        with open(self.dir_state / name, "a") as fh:
            fh.write(json.dumps(rec, default=str) + "\n")


def _jsonable(d: dict) -> dict:
    return {k: (str(v) if isinstance(v, (pd.Timestamp, set)) else v) for k, v in d.items()}


def run(cfg, dry_run: bool, force: bool, until: str) -> int:
    creds = Credentials.from_env()
    sess = Session(cfg, dry_run, MarketData(creds, feed=cfg.live.feed), MarketData(creds, feed="sip"),
                   os.environ.get(cfg.live.discord_secret))
    t = now_et()
    if t.weekday() >= 5 and not force:
        log.info("Weekend - nothing to do")
        return 0
    start_at = at(sess.today, cfg.session.live_start)
    stop_at = at(sess.today, until)
    # Cron runs in UTC with no daylight saving, so two start times are
    # scheduled. The early one in winter is far too early: leave it to the next.
    if t < start_at - pd.Timedelta(minutes=45) and not force:
        log.info("Too early (%s ET) - the next scheduled run takes the session", f"{t:%H:%M}")
        return 0
    if t > stop_at and not force:
        log.info("Past %s - the end-of-day replay covers today", until)
        return 0
    while now_et() < start_at and not force:
        _time.sleep(15)
    sess.prepare()
    open_at = at(sess.today, cfg.session.open)
    while now_et() < open_at - pd.Timedelta(seconds=40) and not force:
        _time.sleep(10)
    sess.premarket()
    log.info("Premarket loaded: %s", ", ".join(f"{s} {len(split_day(df)[0])} bars" for s, df in sess.bars.items()))
    last_done = None
    while True:
        t = now_et()
        if t >= stop_at:
            break
        if sess.closed_window and not sess.open and t >= at(sess.today, cfg.session.signals_until) + pd.Timedelta(minutes=12):
            log.info("Window closed and no open trades - done")
            break
        minute = t.floor("min") - pd.Timedelta(minutes=1)          # the newest bar that has closed
        if minute < open_at or minute == last_done:
            _time.sleep(max(0.2, (t.ceil("min") - t).total_seconds() + 1.8) if minute == last_done else 1)
            continue
        try:
            since = (last_done or open_at - pd.Timedelta(minutes=1)) + pd.Timedelta(minutes=1)
            sess.poll(since)
            sess.on_minute(minute, now_et())
            last_done = minute
        except Exception as exc:                                    # noqa: BLE001
            log.exception("minute %s failed, will retry: %s", minute, exc)
            _time.sleep(3)
    log.info("Live session over: %d signals", sum(sess.count.values()))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="log the cards instead of posting")
    ap.add_argument("--force", action="store_true", help="ignore the clock (testing)")
    ap.add_argument("--until", default="14:50", help="Eastern time to stop; the EOD replay finishes the day")
    a = ap.parse_args(argv)
    return run(bcfg.load(), a.dry_run, a.force, a.until)


if __name__ == "__main__":
    sys.exit(main())
